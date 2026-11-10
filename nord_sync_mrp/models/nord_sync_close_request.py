# -*- coding: utf-8 -*-
from odoo import fields, models


class NordSyncCloseRequest(models.Model):
    """Every call to the close-MO link (nordCount), whatever its outcome."""
    _name = 'nord_sync.close.request'
    _description = 'nordCount Close MO Request'
    _order = 'id desc'

    create_date = fields.Datetime(string='Date', readonly=True)
    code = fields.Char(string='Codes received', readonly=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True, ondelete='set null')
    outcome = fields.Selection([
        ('closed', 'Closed'),
        ('refused', 'Refused'),
        ('invalid_token', 'Invalid token'),
        ('no_codes', 'No QR codes in the call'),
        ('not_found', 'MO not found'),
        ('error', 'Error'),
    ], string='Result', readonly=True)
    http_status = fields.Integer(string='HTTP', readonly=True)
    message = fields.Text(readonly=True)
    remote_ip = fields.Char(string='From', readonly=True)
