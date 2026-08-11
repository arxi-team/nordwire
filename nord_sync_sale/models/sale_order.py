# -*- coding: utf-8 -*-
from odoo import models


class SaleOrder(models.Model):
    """Nord Sync Source for sale.order — same minimal shape as
    maintenance.request (nord_sync_maintenance): create-only Automation Rule, no product/
    declaration/result push. `operation_type` in the payload is what tells
    the Core which nord.job.type to use — never hardcoded Core-side.
    """
    _inherit = 'sale.order'

    def _nord_sync_notify(self, operation):
        for record in self:
            config = self.env['nord_sync.config'].sudo()._get_for_company(record.company_id)
            if not config or not config.enabled:
                continue
            config._enqueue_and_notify('sale.order', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        self.ensure_one()
        return {
            'name': self.name,
            'operation_type': 'sale',
        }
