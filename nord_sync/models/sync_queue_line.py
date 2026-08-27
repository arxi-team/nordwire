# -*- coding: utf-8 -*-
from odoo import fields, models


class NordSyncQueueLine(models.TransientModel):
    """One real change (create/write/unlink of one record) folded under a
    nord.sync.queue header — debug-only, never independently
    fetched by the Core, only inspectable from its header's own form. The
    header's own payload merges these back together, see
    nord.sync.queue._nord_sync_aggregate_payload.

    TransientModel like its header (Odoo forbids a Many2one from a regular
    Model to a TransientModel) — vacuumed on the same clock, no independent
    retention of its own.
    """
    _name = 'nord.sync.queue.line'
    _description = 'Nord Sync Queue Line'
    _order = 'id asc'

    queue_id = fields.Many2one('nord.sync.queue', required=True, ondelete='cascade', index=True)
    res_model = fields.Char(string='Model', required=True)
    res_id = fields.Integer(string='Record ID', required=True)
    operation = fields.Selection([
        ('create', 'Create'),
        ('write', 'Write'),
        ('unlink', 'Unlink'),
    ], required=True)
    data = fields.Json(
        string='Payload',
        help='Business payload snapshot taken at enqueue time — captured '
             'before unlink, since the record is gone afterwards.',
    )
