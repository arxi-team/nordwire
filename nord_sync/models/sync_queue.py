# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class NordSyncQueue(models.Model):
    """Change log header the Nord Core pulls from (GET /nord_sync/api/v1/queue)
    — one row per owner (a manufacturing order, a work center, ...), never
    one row per raw change. `id` doubles as the pull cursor (`seq`) —
    it's already a monotonic, unique, ordered counter, so there's no need for
    a second ir.sequence just to reproduce what the ORM gives for free.

    Every real change (create/write/unlink of one record) becomes a
    nord.sync.queue.line, never a field directly on this model — a header has
    no res_model/res_id/operation/data of its own, only an owner
    (owner_res_model/owner_res_id) and the lines folded under it. This header
    is looked up/created once per still-open owner and reused for every
    further related change until it's served (`is_sealed`), so a burst of
    activity on the same owner (a workorder starting, stopping, a quality
    check) collapses into one served entry instead of one per change.
    """
    _name = 'nord.sync.queue'
    _description = 'Nord Sync Queue'
    _order = 'id asc'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    owner_res_model = fields.Char(
        string='Owner Model', required=True, index=True,
        help='(res_model, res_id) this header represents — resolved once, at '
             'creation, via _nord_sync_resolve_owner. Every further related '
             'change folds its own line under this same header instead of '
             'opening a new one, until it seals.',
    )
    owner_res_id = fields.Integer(string='Owner Record ID', required=True, index=True)
    line_ids = fields.One2many(
        'nord.sync.queue.line', 'queue_id', string='Changes',
        help='Every real change folded under this header, in arrival order — '
             'debug-only, never independently fetched by the Core (see '
             '_nord_sync_aggregate_payload for how the Core actually gets '
             'this data, merged into the header\'s own served payload).',
    )
    payload = fields.Json(
        compute='_compute_payload',
        help='The payload actually served to the Core for this header — '
             'read-only preview of _nord_sync_aggregate_payload, so a human '
             'inspecting this record sees the same merge the Core does '
             'without needing to call the API.',
    )
    is_sealed = fields.Boolean(
        default=False, index=True,
        help='Set the moment this header is served in a /queue response — a '
             'sealed header never accepts a new line, the next related '
             'change for the same owner opens a fresh header instead.',
    )
    status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ], default='pending', required=True,
        help='Wake webhook delivery to the Nord Cloud for this header — not the '
             "Core's downstream processing of it (the Core pulls by seq/last_seq "
             'regardless of this field). Stays "pending" when the webhook is not '
             'yet configured (nothing attempted); "failed" headers are what the '
             'client-side reconciliation cron retries.',
    )
    last_error = fields.Char(
        string='Last Error',
        help='Exception message from the most recent failed webhook attempt for '
             'this header — cleared on success.',
    )

    def _compute_payload(self):
        for header in self:
            header.payload = header._nord_sync_aggregate_payload()

    # ── owner resolution + payload aggregation ──────────────────────────────────

    @api.model
    def _nord_sync_resolve_owner(self, res_model, res_id, data):
        """Extension point: (owner_res_model, owner_res_id) that (res_model,
        res_id) logically belongs to — itself by default. A source addon
        overrides this to redirect a child model onto its real owner (e.g.
        mrp.workorder -> its MO's mrp.production id), reading `data` instead
        of a live browse() of the record (same reasoning as everywhere else
        this bridge reads a _res_id reference from data instead of
        re-resolving a record that may since have been deleted).

        Unrelated to _nord_sync_hidden_owner_models below — a model can
        resolve to itself here and still be hidden from friendly surfaces
        (mrp.bom/mrp.workcenter/hr.employee do exactly that), the two are
        independent axes.
        """
        return (res_model, res_id)

    @api.model
    def _nord_sync_hidden_owner_models(self):
        """Extension point: owner_res_model values that should never surface
        on the friendly failure surfaces (systray count, Failure Wizard) —
        empty by default. A source addon extends this for its own catalog
        models with no owning instance of their own — a work center or BOM
        is shared across every MO that uses it, not scoped to one, so
        surfacing it there the same way as a real MO's own failure would
        mislead a shop-floor user about which order actually needs
        attention. The technical Sync Queue/Sync Failures lists are never
        filtered by this — only the friendly surfaces are.
        """
        return ()

    def _nord_sync_aggregate_payload(self):
        """The payload actually served to the Core for this header — the
        latest line for its own owner type merged bare (the exact same flat
        shape a source addon's _apply_nord_sync_* has always read directly,
        e.g. payload.get('name')), plus one extra key per distinct *other*
        res_model folded in. A res_model always contains a '.', a business
        field name never does, so the two never collide in the same dict.

        model/res_id are duplicated here from the entry envelope
        (_nord_sync_build_entry) on purpose — the Core itself never reads
        them from here, it already gets both from the envelope, but a human
        (or a log line) looking at just this payload in isolation — e.g.
        this header's own `payload` field in the backend — would otherwise
        have no way to tell whose data it's looking at without cross-
        referencing owner_res_model/owner_res_id on the header separately.
        Always first in the dict for exactly that reason.

        Keys:
            model (str): this header's own owner_res_model, echoed for
                readability — always mrp.production/mrp.bom/... never a
                business field itself.
            res_id (int): this header's own owner_res_id, echoed for the
                same reason as model above.
            <own business fields> (mixed, optional): the latest line whose
                res_model equals this header's owner_res_model, merged bare —
                every plain field a source addon's _apply_nord_sync_* already
                reads directly (name, state, ...). Absent entirely if no such
                line exists yet (the owner's own change hasn't folded in —
                see _nord_sync_build_entry for the top-level operation used
                in that case).
            <other res_model> (list[dict], optional): one entry per distinct
                res_id folded under this header for that model — [{res_id,
                operation, payload}]. Repeated folds of the very same
                (res_model, res_id) — a record edited more than once before
                the Core's next pull — collapse to the latest one; two
                genuinely different records of the same model (e.g. two
                workorders on the same MO) both survive as separate items.
        """
        self.ensure_one()
        own_fields = {}
        by_model = {}
        for line in self.line_ids.sorted('id'):
            if line.res_model == self.owner_res_model:
                own_fields = dict(line.data or {})
            else:
                by_model.setdefault(line.res_model, {})[line.res_id] = line
        payload = {'model': self.owner_res_model, 'res_id': self.owner_res_id, **own_fields}
        for model, by_res_id in by_model.items():
            payload[model] = [
                {'res_id': res_id, 'operation': line.operation, 'payload': line.data or {}}
                for res_id, line in by_res_id.items()
            ]
        return payload

    def _nord_sync_build_entry(self):
        """The full {model, operation, res_id, payload} shape served to the
        Core for this header (seq is added by the controller, the only piece
        that's this header's own id rather than derived from its lines).
        operation/model/res_id mirror the owner's own line when one exists
        yet — 'write' is a safe default otherwise (every _apply_nord_sync_*
        treats create/write identically already, branching only on
        'unlink', which can't be the *missing* case here since an unlink
        line always folds in as the owner's own line, never only as a
        related one).
        """
        self.ensure_one()
        owner_lines = self.line_ids.filtered(lambda line: line.res_model == self.owner_res_model).sorted('id')
        return {
            'model': self.owner_res_model,
            'operation': owner_lines[-1:].operation or 'write',
            'res_id': self.owner_res_id,
            'payload': self._nord_sync_aggregate_payload(),
        }

    # ── Systray failed-count + dedicated failures view ──────────────────────────

    @api.model
    def systray_get_failed_count(self):
        """Counts distinct failing owners — each header is already exactly
        one owner, but a sealed header that failed and a fresh one opened
        for the same owner afterward can both be 'failed' at once, so this
        still dedups by (owner_res_model, owner_res_id)."""
        hidden = self._nord_sync_hidden_owner_models()
        failed = self.sudo().search([
            ('status', '=', 'failed'), ('company_id', 'in', self.env.companies.ids),
        ])
        owners = {
            (h.owner_res_model, h.owner_res_id) for h in failed if h.owner_res_model not in hidden
        }
        return len(owners)

    def action_retry_now(self):
        """Manual resend — same one-ping-per-company mechanism as the
        periodic cron, just triggered on demand instead of waiting for the
        next tick. Bound as a list-view server action, so it can act on
        whatever's selected (or all failures, if the whole list is selected).
        """
        configs = self.env['nord_sync.config'].sudo().search([
            ('company_id', 'in', self.mapped('company_id').ids),
        ])
        for config in configs:
            config._retry_failed_webhooks()

    # ── user-facing failure surfaces ─────────────────────────────────────────────

    def _nord_sync_friendly_error(self):
        """Best-effort translation of last_error (a raw Python exception
        string — see _send_wake_webhook) into something a non-technical user
        can read. Pattern-matched on the known shapes `requests` raises for
        this one webhook call — connection failure, timeout, or an HTTPError
        from raise_for_status() (always starts with the numeric status
        code) — not a parse of a structured error type, since none is
        persisted (last_error is just str(exc)). Never shown instead of
        last_error, only alongside it, on the user-facing surfaces only —
        the technical Sync Failures list keeps the raw text.
        """
        self.ensure_one()
        error = (self.last_error or '').lower()
        if not error:
            return ''
        if 'timed out' in error or 'timeout' in error:
            return _('Nord Sync: the Nord Cloud took too long to respond.')
        if 'server error' in error:
            return _('Nord Sync: the Nord Cloud reported a server error.')
        if 'client error' in error:
            return _('Nord Sync: the Nord Cloud rejected the request.')
        if 'connection' in error or 'refused' in error or 'resolve' in error or 'name or service not known' in error:
            return _('Nord Sync: could not reach the Nord Cloud — check the network connection.')
        return _('Nord Sync: synchronization failed for an unknown reason.')

    def action_open_failure_wizard(self):
        """Bound to the technical Sync Failures form — a Nord Sync Manager
        investigating one specific header gets the same action wizard
        (create an activity for whoever, or jump to the related record) as
        the systray's own, just scoped to this one header instead of the
        current visible failures. owner_res_model is always a real,
        browsable Odoo model — resolved once at enqueue time by
        _nord_sync_resolve_owner, which is exactly what redirects a
        payload-only synthetic channel (e.g. mrp.production.moves, never a
        model of its own) onto the real record it describes before it ever
        reaches this field.
        """
        self.ensure_one()
        record = self.env[self.owner_res_model].sudo().browse(self.owner_res_id)
        wizard = self.env['nord_sync.failure.wizard'].create({
            'line_ids': [(0, 0, {
                'res_model': self.owner_res_model,
                'res_id': self.owner_res_id,
                'record_name': record.exists() and record.display_name
                    or f'{self.owner_res_model} #{self.owner_res_id}',
                'message': self._nord_sync_friendly_error(),
            })],
        })
        return wizard._action_open()
