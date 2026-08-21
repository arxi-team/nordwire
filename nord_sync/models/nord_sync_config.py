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

    enabled_source_ids = fields.Many2many(
        'nord_sync.source', string='Enabled Sources',
        default=lambda self: self.env['nord_sync.source'].search([]),
        help='Which Nord Sync Sources actually produce jobs for this company '
             '— every source is always installed together '
             '(Docs/ADR/0014-nord-sync-reunify-single-addon.md), this is what '
             "used to be a per-source addon install/uninstall. Defaults to "
             'every known source, so an existing config from before this '
             'field existed keeps behaving exactly as it did before.',
    )

    core_applied_seq = fields.Integer(
        string='Core Applied Seq', default=0,
        help='Highest nord.sync.queue id the Core has confirmed it actually applied, '
             'as reported on its own next pull request. Used only to know which "sent" '
             'queue entries are safe to garbage-collect — the Core still pulls by '
             'last_seq regardless of this value.',
    )

    _company_unique = models.Constraint(
        'UNIQUE(company_id)', 'Only one Nord Sync configuration per company is allowed.',
    )

    def write(self, vals):
        changed = JOB_NAMING_FIELDS & set(vals)
        # Captured before super().write() — self.enabled below still reads
        # the pre-write value at this point. 'enabled' is editable any time
        # from Settings (not just install-time), and every Nord Sync Source
        # model's own create/write guard on it is otherwise completely
        # silent (real gap found 2026-08-18, Docs/NordSyncAuditoriaErros.md
        # finding #6) — logged here once per toggle instead of once per
        # skipped record everywhere that guard is duplicated.
        was_enabled_by_id = {config.id: config.enabled for config in self} if 'enabled' in vals else {}
        result = super().write(vals)
        if changed:
            for config in self:
                if config.enabled:
                    config._push_job_naming_signal()
        if 'enabled' in vals:
            for config in self:
                was_enabled = was_enabled_by_id.get(config.id, False)
                if config.enabled and not was_enabled:
                    _logger.info(
                        'nord_sync: enabled for company_id=%s — backfilling pre-existing records',
                        config.company_id.id,
                    )
                    # Re-enabling outside the install wizard (its own Finish
                    # step already does this) had no equivalent catch-up —
                    # a record created/edited entirely during a disabled
                    # window would otherwise never reach the Core.
                    config._nord_sync_backfill_existing_records()
                elif was_enabled and not config.enabled:
                    _logger.info(
                        'nord_sync: disabled for company_id=%s — every create/write on a '
                        'Nord Sync Source model is silently skipped until re-enabled',
                        config.company_id.id,
                    )
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

    def _is_source_enabled(self, source_model):
        """Gate every Nord Sync Source's create/write hook — this addon
        always has every source's code installed, so `enabled` alone can no
        longer say whether a specific source (e.g. sale.order) should
        actually produce jobs for this company; enabled_source_ids is what
        used to be a per-source addon install/uninstall. A source_model with
        no matching nord_sync.source row (a support model like
        mrp.workorder/mrp.bom, not a top-level source itself) is checked
        against its own parent source's model by the caller, not here.
        """
        self.ensure_one()
        return source_model in self.enabled_source_ids.mapped('model')

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

        Delegates the actual send to _retry_failed_webhooks rather than
        pinging on its own: that method already sweeps every pending/failed
        entry for this company in one webhook call (the wake payload carries
        no entry-specific data), so this new entry rides along with any
        stragglers left behind by an earlier skipped/failed attempt (e.g. an
        install wizard run that pushed stages/a state mapping before
        cloud_base_url was configured) — they get resolved the moment any
        new activity happens, not just every 5 minutes via the cron. One
        webhook call either way, whether this is the only entry or there are
        ten stale ones waiting.
        """
        self.ensure_one()
        entry = self.env['nord.sync.queue'].sudo().create({
            'res_model': res_model,
            'res_id': res_id,
            'operation': operation,
            'company_id': self.company_id.id,
            'data': payload,
        })
        self._retry_failed_webhooks()
        return entry

    def _nord_sync_backfill_existing_records(self):
        """Notify the Core about every pre-existing record a source's own
        create/write hooks would otherwise never catch — those only fire on
        an edit *after* the bridge exists. Base is a no-op (nothing to
        backfill without a source installed); each Nord Sync Source addon
        overrides via _inherit and calls super(), same pattern as
        _apply_nord_sync_entry.

        Called from two places, covering the two different timings a source
        can start existing for a company: the install wizard's Finish step
        (config only becomes enabled here — a source installed earlier in
        the same wizard's Sources step had nothing to notify yet, since
        _nord_sync_notify itself no-ops without an enabled config) and
        nord_sync_mrp's own post_init_hook (covers adding a source to a
        client that's already configured and enabled, where the wizard
        never runs again).
        """
        self.ensure_one()

    def _send_wake_webhook(self):
        """Returns (status, error): status is None if skipped (not configured
        yet), True/False if attempted; error is the exception text on failure,
        else None — surfaced on nord.sync.queue.last_error instead of only
        ever living in the server log.
        """
        self.ensure_one()
        webhook_url = self._get_cloud_webhook_url()
        if not webhook_url or not self.company_uid:
            # Entry itself still landed in nord.sync.queue (status stays
            # 'pending', visible/retried normally) — this only skips the
            # best-effort accelerator. Logged because a missing
            # cloud_base_url/company_uid at this point is always a
            # configuration gap worth noticing, not routine.
            _logger.info(
                'nord_sync: wake webhook skipped — not configured yet (cloud_base_url or company_uid unset)',
            )
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
        """Resends both 'failed' (webhook attempted, got an error) and
        'pending' (webhook attempt was skipped outright, e.g. cloud_base_url
        wasn't configured yet at push time — the install wizard's Finish step
        pushes stages/mapping before an operator has necessarily set that
        param, see nord_sync_install_wizard.py) — both are just "never
        confirmed delivered", same recovery. Also the send path
        _enqueue_and_notify itself delegates to, so a brand-new entry (still
        'pending' from its own create) is swept by this same query — no
        separate single-entry write needed there. One webhook ping per
        company, not per entry — the wake payload carries no entry-specific
        data (just company_uid), so a single successful ping resolves every
        stale entry for this company at once, same as the Core's own
        reconciliation (_incremental_sync) already guarantees on its side;
        this is just what shortens the wait, not the correctness guarantee.
        status is written on failure too (not just last_error) — otherwise a
        brand-new 'pending' entry whose first-ever attempt fails would be
        left in 'pending' with an error message attached, instead of
        'failed' like every other failed attempt.
        """
        self.ensure_one()
        stale_entries = self.env['nord.sync.queue'].sudo().search([
            ('company_id', '=', self.company_id.id), ('status', 'in', ('failed', 'pending')),
        ])
        if not stale_entries:
            return False
        sent, error = self._send_wake_webhook()
        if sent:
            stale_entries.write({'status': 'sent', 'last_error': False})
        elif error:
            stale_entries.write({'status': 'failed', 'last_error': error})
        return bool(sent)

    @api.model
    def _cron_retry_failed_webhooks(self):
        for config in self.search([('enabled', '=', True)]):
            config._retry_failed_webhooks()

    def _cleanup_synced_queue_entries(self):
        """Deletes nord.sync.queue rows the Core has confirmed it applied —
        never by age, since a Core offline for days/weeks must still find
        every entry on its next reconciliation pull. Only 'sent' entries
        (wake webhook delivered) are touched; 'pending' (webhook never
        attempted) and 'failed' stay untouched regardless of
        core_applied_seq — a webhook-delivery problem must never hide a row
        the Core hasn't actually confirmed.
        """
        self.ensure_one()
        if not self.core_applied_seq:
            return
        self.env['nord.sync.queue'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('status', '=', 'sent'),
            ('id', '<=', self.core_applied_seq),
        ]).unlink()

    @api.model
    def _cron_cleanup_synced_queue_entries(self):
        for config in self.search([('enabled', '=', True)]):
            config._cleanup_synced_queue_entries()
