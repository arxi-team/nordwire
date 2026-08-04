# -*- coding: utf-8 -*-
from odoo import fields, models


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
