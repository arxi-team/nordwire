# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    nord_sync_enabled = fields.Boolean(
        string='Nord Sync Enabled',
        help='Whether this company\'s mrp.production changes are queued for the Nord Core to pull.',
    )
    nord_sync_company_uid = fields.Char(
        string='Nord Sync: Company UID',
        help='Tenant UID assigned by Nord (matches a res.company.uid on the Nord Cloud side). '
             'Sent in the wake webhook payload and used to identify this company on queue pulls.',
    )
    nord_sync_cloud_webhook_url = fields.Char(
        string='Nord Sync: Cloud Webhook URL',
        help='Nord Cloud endpoint to notify when something changes '
             '(e.g. http://<cloud-host>/nordos/sync/nord_sync/webhook).',
    )
