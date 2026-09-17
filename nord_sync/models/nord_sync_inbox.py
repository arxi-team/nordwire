# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class NordSyncInbox(models.TransientModel):
    """Raw capture for every Core->client push (POST /result,
    /workorder_event, /resources) — the controller only validates the
    envelope (valid JSON, res_model present) and stores it here, returning
    200 immediately; no domain processing happens in-request anymore. The
    actual domain effect (the same nord_sync.config._nord_sync_apply_result/
    _nord_sync_apply_workorder_event / resource-upsert logic the controller
    used to call directly) happens later, from _cron_process_pending below —
    so a slow or failing domain handler never blocks the Core's own request,
    and one bad entry never blocks the rest of a cron batch (see the
    savepoint in _cron_process_pending).

    TransientModel, 2h retention — same posture and same reasoning as
    nord.sync.queue: Odoo's own periodic vacuum is the cleanup mechanism,
    not a bespoke cron keyed off what got applied.

    A failed entry surfaces through the same Sync Failures systray/wizard
    already built for the outbound direction (nord.sync.queue) — see
    _nord_sync_failed_owners below, folded in by
    nord.sync.queue.systray_get_failed_count and
    nord_sync.failure.wizard.action_open_for_current_failures.
    """
    _name = 'nord_sync.inbox'
    _description = 'Nordwire Inbox'
    _order = 'id asc'
    # ponytail: 2h retention — a Core push that fails and sits unretried
    # longer than that is only ever visible via the Sync Failures systray/
    # wizard by then, not by browsing this record directly (no UI for it —
    # see the plan's own "no dedicated Sync Inbox screen" scope). Same
    # accepted tradeoff as nord.sync.queue.
    _transient_max_hours = 2

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    endpoint = fields.Selection([
        ('result', 'Result'),
        ('workorder_event', 'Workorder Event'),
        ('resources', 'Resources'),
    ], required=True, help='Which of the 3 inbound routes this entry came from — picks the cron\'s '
                            'own dispatch branch (see _cron_process_pending). Not the same axis as '
                            'res_model below: one endpoint can carry different res_model values '
                            '(/result carries both mrp.production and future source models), while '
                            '/resources always carries the same fixed one.')
    res_model = fields.Char(
        required=True,
        help='body["res_model"] verbatim for result/workorder_event. For resources, there is no '
             "res_model key in that route's body at all — the controller sets this to the fixed "
             "literal 'nord_sync.resource', the model that endpoint always upserts into.",
    )
    payload = fields.Json(required=True, help='The full raw request body, verbatim.')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], default='pending', required=True)
    last_error = fields.Char(help='Exception/failure message from the most recent cron attempt — cleared on success.')

    @api.model
    def _cron_process_pending(self):
        """Dispatches every pending entry, oldest first (order='id asc',
        same "no ordering guarantee beyond oldest-first" as nord.sync.queue).

        Each entry's dispatch runs inside its own savepoint — a domain-level
        failure inside _nord_sync_apply_result (or the resource upsert) can
        be a raw DB constraint violation, not a clean Python exception caught
        before any SQL runs, and an aborted statement poisons the whole
        Postgres transaction, including the entry.write({'status': 'failed',
        ...}) below if it ran in that same poisoned transaction. The
        savepoint rolls back only this entry's own attempted changes,
        leaving the transaction clean for that write and for every other
        entry in the same batch — one bad entry never blocks the rest.
        """
        Config = self.env['nord_sync.config'].sudo()
        for entry in self.sudo().search([('status', '=', 'pending')], order='id asc'):
            try:
                with self.env.cr.savepoint():
                    config = Config._get_for_company(entry.company_id)
                    if not config:
                        raise ValueError(_('Nordwire not configured for company %s') % entry.company_id.display_name)
                    if entry.endpoint == 'result':
                        applied, message = config._nord_sync_apply_result(entry.payload, entry.res_model)
                    elif entry.endpoint == 'workorder_event':
                        applied, message = config._nord_sync_apply_workorder_event(
                            entry.payload, entry.res_model, entry.payload.get('event_type'),
                        )
                    else:  # 'resources' — _nord_sync_upsert_from_core has no (applied, message) return of
                           # its own, unchanged by this task — any raised exception is treated as failure,
                           # otherwise it's a success.
                        self.env['nord_sync.resource'].sudo()._nord_sync_upsert_from_core(
                            config.company_id, entry.payload.get('resources') or [],
                        )
                        applied, message = True, 'ok'
                    if not applied:
                        raise ValueError(message)
            except Exception as exc:
                _logger.warning('nord_sync: inbox entry %s (%s) failed: %s', entry.id, entry.endpoint, exc)
                entry.write({'status': 'failed', 'last_error': str(exc)})
            else:
                entry.unlink()

    # ── failure visibility (folded into nord.sync.queue's own systray/wizard) ──

    def _nord_sync_failed_owners(self):
        """[(res_model, res_id, last_error)], one row per failed entry
        visible to the current companies — same owner shape
        (owner_res_model, owner_res_id) as nord.sync.queue's own headers, so
        nord.sync.queue.systray_get_failed_count and
        nord_sync.failure.wizard.action_open_for_current_failures can fold
        this set into theirs. Not deduped here — each caller already dedupes
        its own combined owner set the same way it dedupes nord.sync.queue's.

        For endpoint in ('result', 'workorder_event') the owner is
        (entry.res_model, entry.payload.get('res_id')) — always a real
        browsable record, both handlers already require res_id in the body.
        For endpoint == 'resources' there is no single owning record (one
        heartbeat covers a whole list of resources) — resolved onto the
        company's own Nordwire Configuration record instead, so the caller
        still gets a real, browsable owner rather than a fake id.
        """
        Config = self.env['nord_sync.config'].sudo()
        rows = []
        for entry in self.sudo().search([
            ('status', '=', 'failed'), ('company_id', 'in', self.env.companies.ids),
        ]):
            if entry.endpoint == 'resources':
                config = Config._get_for_company(entry.company_id)
                if config:
                    rows.append((config._name, config.id, entry.last_error))
                continue
            res_id = entry.payload.get('res_id')
            if res_id:
                rows.append((entry.res_model, res_id, entry.last_error))
        return rows
