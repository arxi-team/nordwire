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
WAKE_MODES = [
    ('immediate', 'Immediate'),
    ('throttled', 'Throttled'),
]
# Fields pushed to the Core as company-wide preferences (same nord_sync.config
# channel/entry as job naming already used) — wake_mode/wake_throttle_minutes/
# last_wake_sent are NOT here on purpose: they only govern this client's own
# outbound wake timing, the Core has no use for them.
NORD_SYNC_CONFIG_SIGNAL_FIELDS = {'job_naming_mode', 'job_naming_custom_prefix', 'mirror_mode'}


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

    mirror_mode = fields.Boolean(
        string='Mirror Mode',
        help='Off (default): the Core only ever advances a job past a human/device action '
             "on the Core itself (NordGo, a port-driven alert) — this MO's own state is "
             "paperwork, not real production. On: this MO reaching Confirmed/In Progress/"
             'Done on the client additionally drives the matching action on the Core job '
             "(no result push back for a Done reached this way — the client's own qty is "
             "already final by then). Cancelling always cancels the job either way, this "
             'toggle only adds the other three.',
    )

    wake_mode = fields.Selection(
        WAKE_MODES, default='immediate', required=True, string='Wake Mode',
        help='Immediate (default): every change pings the Nord Cloud wake webhook right '
             'away, same as today. Throttled: at most one wake ping every Wake Throttle '
             'field below, however many changes happen in between — the changes themselves '
             'still land in the queue immediately either way, this only paces how soon the '
             "Core is nudged to come get them (its own periodic reconciliation is always "
             'the upper bound regardless of this setting).',
    )
    wake_throttle_minutes = fields.Integer(
        string='Wake Throttle (minutes)', default=5,
        help='Only used when Wake Mode is Throttled.',
    )
    last_wake_sent = fields.Datetime(
        string='Last Wake Attempt',
        help='When the last wake webhook attempt (success or failure) happened — paces '
             'Throttled mode only, never affects whether data actually syncs.',
    )

    enabled_source_ids = fields.Many2many(
        'nord_sync.source', string='Enabled Sources',
        default=lambda self: self.env['nord_sync.source'].search([]),
        help='Which Nord Sync Sources actually produce jobs for this company '
             '— every source is always installed together now (they all live '
             'in this one addon), this is what used to be a per-source addon '
             'install/uninstall. Defaults to every known source, so an '
             'existing config from before this field existed keeps behaving '
             'exactly as it did before.',
    )

    _company_unique = models.Constraint(
        'UNIQUE(company_id)', 'Only one Nord Sync configuration per company is allowed.',
    )

    def write(self, vals):
        changed = NORD_SYNC_CONFIG_SIGNAL_FIELDS & set(vals)
        # Captured before super().write() — self.enabled below still reads
        # the pre-write value at this point. 'enabled' is editable any time
        # from Settings (not just install-time), and every Nord Sync Source
        # model's own create/write guard on it is otherwise completely
        # silent — a company left disabled by mistake would just have every
        # create/write quietly no-op with zero trace, nothing to notice by.
        # Logged here once per toggle instead of once per skipped record
        # everywhere that guard is duplicated.
        was_enabled_by_id = {config.id: config.enabled for config in self} if 'enabled' in vals else {}
        result = super().write(vals)
        if changed:
            for config in self:
                if config.enabled:
                    config._push_config_signal()
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

    def _push_config_signal(self):
        """Pushes every company-wide preference the Core needs to know about
        together, regardless of which one actually changed — there's
        exactly one of these per company on both sides, same "always
        overwrite, no upsert-by-reference" reasoning as everywhere else in
        this bridge that resolution applies to.
        """
        self.ensure_one()
        self._enqueue_and_notify('nord_sync.config', self.company_id.id, 'write', {
            'job_naming_mode': self.job_naming_mode,
            'job_naming_custom_prefix': self.job_naming_custom_prefix or False,
            'mirror_mode': self.mirror_mode,
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
        nord_sync.state.mapping — one nord.sync.queue.line + one best-effort
        wake webhook per change, so each model only needs to supply its own
        payload.

        The line always folds under a header — an already-open one for this
        same owner (_nord_sync_resolve_owner) when one exists, else a fresh
        header, which this line then becomes the first line of.
        Delegates the actual send to _retry_failed_webhooks rather than
        pinging on its own: that method already sweeps every pending/failed
        header for this company in one webhook call (the wake payload
        carries no header-specific data), so this new line rides along with
        any stragglers left behind by an earlier skipped/failed attempt
        (e.g. an install wizard run that pushed stages/a state mapping
        before cloud_base_url was configured) — they get resolved the
        moment any new activity happens, not just every 5 minutes via the
        cron. One webhook call either way, whether this is the only header
        or there are ten stale ones waiting.

        The line itself always lands in nord.sync.queue.line immediately, no
        matter what — _nord_sync_wake_due only gates whether the wake ping
        happens right now (Wake Mode Immediate, the default) or waits for
        _cron_send_throttled_wakes (Wake Mode Throttled).
        """
        self.ensure_one()
        Queue = self.env['nord.sync.queue'].sudo()
        owner_model, owner_res_id = Queue._nord_sync_resolve_owner(res_model, res_id, payload)
        header = Queue.search([
            ('company_id', '=', self.company_id.id), ('is_sealed', '=', False),
            ('owner_res_model', '=', owner_model), ('owner_res_id', '=', owner_res_id),
        ], limit=1)
        if header:
            # Blocks here if a /queue pull is mid-flight for this same header
            # (it takes the same lock right after its own search). Once
            # unblocked, is_sealed may have flipped to True under us — that
            # pull already built and served this header's payload without
            # what we're about to add, so treat it as gone and open a fresh
            # one instead of silently folding into an already-served header.
            header._nord_sync_lock_for_update()
            header.invalidate_recordset(['is_sealed'])
            if header.is_sealed:
                header = Queue.browse()
        if not header:
            header = Queue.create({
                'company_id': self.company_id.id,
                'owner_res_model': owner_model, 'owner_res_id': owner_res_id,
            })
        self.env['nord.sync.queue.line'].sudo().create({
            'queue_id': header.id, 'res_model': res_model, 'res_id': res_id,
            'operation': operation, 'data': payload,
        })
        if self._nord_sync_wake_due():
            self._retry_failed_webhooks()
        return header

    def _nord_sync_wake_due(self):
        """True when a wake attempt should happen right now. Always true in
        Immediate mode (today's behavior, unchanged). In Throttled mode,
        true only once wake_throttle_minutes have actually passed since the
        last attempt — a burst of writes inside that window shares a single
        wake instead of pinging once per write.
        """
        self.ensure_one()
        if self.wake_mode != 'throttled':
            return True
        if not self.last_wake_sent:
            return True
        elapsed = fields.Datetime.now() - self.last_wake_sent
        return elapsed.total_seconds() >= (self.wake_throttle_minutes or 0) * 60

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
        # Recorded for any real attempt (True or False), not a skip (None,
        # e.g. cloud_base_url not configured yet) — a skip never happened as
        # far as Throttled mode's pacing is concerned, so it shouldn't reset
        # the window either.
        if sent is not None:
            self.last_wake_sent = fields.Datetime.now()
        if sent:
            stale_entries.write({'status': 'sent', 'last_error': False})
        elif error:
            stale_entries.write({'status': 'failed', 'last_error': error})
        return bool(sent)

    @api.model
    def _cron_retry_failed_webhooks(self):
        for config in self.search([('enabled', '=', True)]):
            config._retry_failed_webhooks()

    @api.model
    def _cron_send_throttled_wakes(self):
        """Dedicated, frequent cron (see data/nord_sync_cron.xml) for Wake
        Mode Throttled companies only — separate from
        _cron_retry_failed_webhooks (every 5 min, a different concern:
        transport failures, not pacing) so a small wake_throttle_minutes
        value (e.g. 2) is actually honored instead of silently rounding up
        to that cron's own cadence.
        """
        for config in self.search([('enabled', '=', True), ('wake_mode', '=', 'throttled')]):
            if config._nord_sync_wake_due():
                config._retry_failed_webhooks()

