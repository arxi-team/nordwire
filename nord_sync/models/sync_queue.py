# -*- coding: utf-8 -*-
from odoo import api, fields, models


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
             'this entry — cleared on success. Docs/NordSyncFase2, Fase 4 Slice 4.2.',
    )

    # ── Fase 4 Slices 4.1/4.2: systray count + dedicated failures view ─────────

    @api.model
    def systray_get_failed_count(self):
        return self.sudo().search_count([
            ('status', '=', 'failed'), ('company_id', 'in', self.env.companies.ids),
        ])

    def action_retry_now(self):
        """Manual resend (Slice 4.2) — same one-ping-per-company mechanism as the
        periodic cron (Slice 4.3), just triggered on demand instead of waiting
        for the next tick. Bound as a list-view server action, so it can act on
        whatever's selected (or all failures, if the whole list is selected).
        """
        configs = self.env['nord_sync.config'].sudo().search([
            ('company_id', 'in', self.mapped('company_id').ids),
        ])
        for config in configs:
            config._retry_failed_webhooks()
