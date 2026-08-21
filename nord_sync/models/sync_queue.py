
# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class NordSyncQueue(models.Model):
    """Change log the Nord Core pulls from (GET /nord_sync/api/v1/queue).

    `id` doubles as the pull cursor (`seq`) — it's already a monotonic,
    unique, ordered counter, so there's no need for a second ir.sequence
    just to reproduce what the ORM gives for free.
    """
    _name = 'nord.sync.queue'
    _description = 'Nord Sync Queue Entry'
    _order = 'id asc'

    res_model = fields.Char(string='Model', required=True)
    res_id = fields.Integer(string='Record ID', required=True)
    operation = fields.Selection([
        ('create', 'Create'),
        ('write', 'Write'),
        ('unlink', 'Unlink'),
    ], required=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    data = fields.Json(
        string='Payload',
        help='Business payload snapshot taken at enqueue time, so the Core does not '
             'need a follow-up request per entry to know what changed. Captured '
             'before unlink, since the record is gone afterwards.',
    )
    status = fields.Selection([
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ], default='pending', required=True,
        help='Wake webhook delivery to the Nord Cloud for this entry — not the '
             "Core's downstream processing of it (the Core pulls by seq/last_seq "
             'regardless of this field). Stays "pending" when the webhook is not '
             'yet configured (nothing attempted); "failed" entries are what the '
             'client-side reconciliation cron retries.',
    )
    last_error = fields.Char(
        string='Last Error',
        help='Exception message from the most recent failed webhook attempt for '
             'this entry — cleared on success.',
    )

    # ── Systray failed-count + dedicated failures view ──────────────────────────

    @api.model
    def systray_get_failed_count(self):
        """Counts distinct visible owners, not raw failed entries — an MO
        whose own entry, moves, and a workorder all failed together is one
        problem, not three (see _nord_sync_visible_owner)."""
        failed = self.sudo().search([
            ('status', '=', 'failed'), ('company_id', 'in', self.env.companies.ids),
        ])
        owners = {entry._nord_sync_visible_owner() for entry in failed}
        owners.discard(None)
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
    # The wake webhook is one best-effort ping per company (see
    # _send_wake_webhook), not one per entry — a single outage marks every
    # entry created in that window as failed, with the same transport error
    # repeated. A source whose model has "child" models describing the same
    # real-world thing (nord_sync_mrp: an MO's own entry, its moves, one of
    # its workorders) would otherwise show up as several independent
    # failures for what is one problem. _nord_sync_visible_owner lets a
    # source addon collapse/hide that — every entry is its own owner by
    # default (unchanged, current behaviour), only narrowed by a source that
    # actually has this child-model shape (see nord_sync_mrp's override).

    def _nord_sync_visible_owner(self):
        """Extension point: (res_model, res_id) of the record this entry's
        failure should surface as, on the failure-count/activity/wizard
        surfaces — itself by default. A source addon narrows this per
        res_model: None to hide entirely (a child model with no independent
        meaning of its own, e.g. nord_sync_mrp's mrp.bom/mrp.workcenter/
        hr.employee — still retried normally, still visible in the
        technical Sync Failures list below), or another record's
        (res_model, res_id) to redirect (e.g. mrp.production.moves/
        mrp.workorder onto their owning MO).
        """
        self.ensure_one()
        return (self.res_model, self.res_id)

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
        """Bound to the technical Sync Failures form (any res_model,
        including the ones _nord_sync_visible_owner hides from the
        count/activity) — a Nord Sync Manager investigating one specific
        entry gets the same action wizard (create an activity for whoever,
        or jump to the related record) as the systray's own, just scoped to
        this one entry instead of the current visible failures.

        Real bug: res_model isn't always a real, browsable Odoo model — a
        source addon can use a synthetic one for a payload-only channel
        (e.g. nord_sync_mrp's 'mrp.production.moves', the MO's move
        snapshot, never a model of its own). self.env[res_model] raises
        KeyError for those. _nord_sync_visible_owner() already knows how to
        redirect a synthetic/child res_model onto its real owning record
        (same mapping the systray/friendly surfaces already rely on) — used
        here too instead of trusting the raw res_model. A "hidden" owner
        (None — a catalog entry with no owning MO, e.g. mrp.bom) still
        falls back to the raw res_model, which is always a real model in
        that case, just not one _nord_sync_visible_owner chooses to
        surface elsewhere.
        """
        self.ensure_one()
        owner_model, owner_res_id = self._nord_sync_visible_owner() or (self.res_model, self.res_id)
        record = self.env[owner_model].sudo().browse(owner_res_id)
        wizard = self.env['nord_sync.failure.wizard'].create({
            'line_ids': [(0, 0, {
                'res_model': owner_model,
                'res_id': owner_res_id,
                'record_name': record.exists() and record.display_name or f'{owner_model} #{owner_res_id}',
                'message': self._nord_sync_friendly_error(),
            })],
        })
        return wizard._action_open()
