# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    """Nord Sync Source for stock.picking — same minimal shape as
    maintenance.request (nord_sync_maintenance): create-only Automation Rule, no product/
    declaration/result push. `operation_type` in the payload is what tells
    the Core which nord.job.type to use — never hardcoded Core-side.
    """
    _inherit = 'stock.picking'

    def _nord_sync_notify(self, operation):
        for record in self:
            config = self.env['nord_sync.config'].sudo()._get_for_company(record.company_id)
            if not config or not config.enabled or not config._is_source_enabled('stock.picking'):
                continue
            config._enqueue_and_notify('stock.picking', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        """Payload sent to the Core when this picking is created.

        Keys:
            name (str): the picking's display name.
            operation_type (str): always 'inventory' — tells the Core which
                nord.job.type to use.
        """
        self.ensure_one()
        return {
            'name': self.name,
            'operation_type': 'inventory',
        }
