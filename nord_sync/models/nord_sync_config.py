# -*- coding: utf-8 -*-
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 5

# The Cloud webhook path is fixed per deployment, not something a client should
# ever need to know or type — only the host (e.g. https://nordwire.pt or
# http://localhost:8080) is client-provided, as a system parameter (one Nord
# Cloud target per Odoo instance, not per company).
CLOUD_BASE_URL_PARAM = 'nord_sync.cloud_base_url'
CLOUD_WEBHOOK_PATH = '/nordos/sync/nord_sync/webhook'

JOB_NAMING_MODES = [
    ('sequence', 'Core Sequence'),
    ('source_document', 'Source Document Name'),
    ('custom_prefix', 'Custom Prefix'),
]
JOB_NAMING_FIELDS = {'job_naming_mode', 'job_naming_custom_prefix'}


class NordSyncConfig(models.Model):
    """Nord Sync connection config — one record per company, replacing the
    nord_sync_enabled/nord_sync_company_uid fields that used to live directly
    on res.company. Kept company-scoped so multi-company opt-in still works —
    see docs/plano_addon_odoo_cliente_producao.md §7 (data scope section).
    The Cloud base URL itself is not company-scoped (see CLOUD_BASE_URL_PARAM
    above) — it lives in ir.config_parameter, not on this model.
    """
    _name = 'nord_sync.config'
    _description = 'Nord Sync Configuration'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    enabled = fields.Boolean(string='Nord Sync Enabled')
    company_uid = fields.Char(
        string='Nord Company UID',
        help='Tenant UID assigned by Nord (matches a res.company.uid on the Nord '
             'Cloud/Core side). Sent in the wake webhook payload and used to '
             'identify this company on queue pulls.',
    )

    job_naming_mode = fields.Selection(
        JOB_NAMING_MODES, default='sequence', string='Job Naming',
        help='How jobs created on the Nord Core from this company\'s synced '
             "records get their name/reference — the Core's own sequence, "
             "the originating document's own name (e.g. a Manufacturing "
             "Order's WH/MO/00019), or a custom prefix on the Core sequence.",
    )
    job_naming_custom_prefix = fields.Char(
        string='Custom Job Naming Prefix',
        help='Only used when Job Naming is Custom Prefix — Core ir.sequence '
             'prefix syntax, e.g. "ACME-JOB/%(year)s/".',
    )

    _company_unique = models.Constraint(
        'UNIQUE(company_id)', 'Only one Nord Sync configuration per company is allowed.',
    )

    def write(self, vals):
        changed = JOB_NAMING_FIELDS & set(vals)
        result = super().write(vals)
        if changed:
            for config in self:
                if config.enabled:
                    config._push_job_naming_signal()
        return result

    def _push_job_naming_signal(self):
        self.ensure_one()
        self._enqueue_and_notify('nord_sync.config', self.company_id.id, 'write', {
            'job_naming_mode': self.job_naming_mode,
            'job_naming_custom_prefix': self.job_naming_custom_prefix or False,
        })

    @api.model
    def _get_for_company(self, company):
        return self.search([('company_id', '=', company.id)], limit=1)

    @api.model
    def _nord_sync_available_native_sources(self):
        """Extension point — the single place every Nord Sync Source addon
        (nord_sync_mrp, nord_sync_maintenance, ...) registers itself, via
        _inherit chain: prepend its own {'source_model', 'source_field',
        'label'} entry and call super(). Consumed by the install wizard's
        Job Stages & Mapping step and by nord_sync.state.mapping's
        source_model/source_value Selections — one registration, two
        consumers, so they can never drift apart. Job state has no entry
        here at all — it's exclusive to the job, resolved on the Core from
        each source's own hardcoded registration there
        (_nord_sync_default_target_state_by_value in
        nordos_nord_sync_core*), with nothing mirrored on this side. Base
        returns none: with no source addon installed there's nothing native
        to map yet.
        """
        return []

    @api.model
    def _get_or_create_for_company(self, company):
        config = self._get_for_company(company)
        return config or self.create({'company_id': company.id})

    def _ensure_state_mapping(self, source_model, source_value, target_job_stage_id=False):
        """Idempotent upsert for one Nord Sync Job Stage Mapping row — the
        one place that decides what "already configured" means, so the
        install wizard (Job Stages & Mapping step) is the only writer and
        never disagrees with itself about it. Job stage only — nord.job.state
        is resolved on the Core from each source's own hardcoded
        registration, never from a row here.
        """
        self.ensure_one()
        StateMapping = self.env['nord_sync.state.mapping'].sudo()
        existing = StateMapping.search([
            ('company_id', '=', self.company_id.id),
            ('source_model', '=', source_model),
            ('source_value', '=', source_value),
        ], limit=1)
        vals = {'target_job_stage_id': target_job_stage_id}
        if existing:
            if existing.target_job_stage_id.id != target_job_stage_id:
                existing.write(vals)
            return existing
        vals.update({'company_id': self.company_id.id, 'source_model': source_model, 'source_value': source_value})
        return StateMapping.create(vals)

    @api.model
    def _get_cloud_base_url(self):
        return self.env['ir.config_parameter'].sudo().get_param(CLOUD_BASE_URL_PARAM)

    @api.model
    def _set_cloud_base_url(self, base_url):
        self.env['ir.config_parameter'].sudo().set_param(CLOUD_BASE_URL_PARAM, base_url or '')

    @api.model
    def _get_cloud_webhook_url(self):
        base_url = self._get_cloud_base_url()
        return base_url.rstrip('/') + CLOUD_WEBHOOK_PATH if base_url else False

    def _enqueue_and_notify(self, res_model, res_id, operation, payload):
        """Shared by every Nord Sync Source's create/write/unlink override
        (mrp.production, maintenance.request, ...), plus nord_sync.job.stage/
        nord_sync.state.mapping — one nord.sync.queue entry + one best-effort
        wake webhook per change, so each model only needs to supply its own
        payload.
        """
        self.ensure_one()
        entry = self.env['nord.sync.queue'].sudo().create({
            'res_model': res_model,
            'res_id': res_id,
            'operation': operation,
            'company_id': self.company_id.id,
            'data': payload,
        })
        sent, error = self._send_wake_webhook()
        if sent is not None:
            entry.write({'status': 'sent' if sent else 'failed', 'last_error': error})
        return entry

    def _push_source_installed_signal(self, module_name):
        """Tells the Core (via the same queue/pull channel as job stages and
        state mappings) that this client has a Nord Sync Source addon
        installed, so it can auto-install its own matching counterpart
        (nordos_nord_sync_core_<x>) instead of requiring an operator to do
        it by hand on every client onboarding. No dedicated model: the
        signal rides nord.sync.queue with a synthetic res_model
        ('ir.module.module') and just the addon's technical name as payload
        — nobody edits this fact, it's derived from ir.module.module, so a
        real table for it would just be another thing to keep in sync.
        Idempotent — skipped if already signalled for this module, so a
        reinstall/upgrade doesn't spam the queue with duplicates.
        """
        self.ensure_one()
        module = self.env['ir.module.module'].sudo().search([('name', '=', module_name)], limit=1)
        if not module:
            return
        already = self.env['nord.sync.queue'].sudo().search_count([
            ('company_id', '=', self.company_id.id),
            ('res_model', '=', 'ir.module.module'),
            ('res_id', '=', module.id),
        ])
        if already:
            return
        self._enqueue_and_notify('ir.module.module', module.id, 'write', {'name': module_name})

    def _send_wake_webhook(self):
        """Returns (status, error): status is None if skipped (not configured
        yet), True/False if attempted; error is the exception text on failure,
        else None — surfaced on nord.sync.queue.last_error instead of only
        ever living in the server log.
        """
        self.ensure_one()
        webhook_url = self._get_cloud_webhook_url()
        if not webhook_url or not self.company_uid:
            return None, None
        _logger.info(
            'nord_sync: sending wake webhook to Nord Cloud (url=%s, company_uid=%s)',
            webhook_url, self.company_uid,
        )
        try:
            response = requests.post(
                webhook_url,
                json={'company_uid': self.company_uid},
                timeout=WEBHOOK_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except Exception as exc:
            _logger.warning('nord_sync: failed to notify Nord Cloud webhook: %s', exc)
            return False, str(exc)
        _logger.info('nord_sync: wake webhook delivered to Nord Cloud (company_uid=%s)', self.company_uid)
        return True, None

    def _retry_failed_webhooks(self):
        """nord.sync.queue.status='failed' is exactly what this retries (see
        that field's help text). One webhook ping
        per company, not per entry — the wake payload carries no entry-specific
        data (just company_uid), so a single successful ping resolves every
        pending entry for this company at once, same as the Core's own
        reconciliation (_incremental_sync) already guarantees on its side; this
        cron only shortens the wait, it's not the correctness guarantee.
        """
        self.ensure_one()
        failed_entries = self.env['nord.sync.queue'].sudo().search([
            ('company_id', '=', self.company_id.id), ('status', '=', 'failed'),
        ])
        if not failed_entries:
            return False
        sent, error = self._send_wake_webhook()
        if sent:
            failed_entries.write({'status': 'sent', 'last_error': False})
        elif error:
            failed_entries.write({'last_error': error})
        return bool(sent)

    @api.model
    def _cron_retry_failed_webhooks(self):
        for config in self.search([('enabled', '=', True)]):
            config._retry_failed_webhooks()
