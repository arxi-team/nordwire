# -*- coding: utf-8 -*-
from odoo import models


class NordSyncConfigInventory(models.Model):
    _inherit = 'nord_sync.config'

    def _nord_sync_apply_workorder_event(self, body, res_model, event_type):
        if res_model != 'stock.picking':
            return super()._nord_sync_apply_workorder_event(body, res_model, event_type)
        self.ensure_one()
        res_id = body.get('res_id')
        picking = self.env['stock.picking'].sudo().browse(int(res_id or 0))
        if not picking.exists() or picking.company_id != self.company_id:
            return False, 'Unknown record'
        return picking._nord_sync_apply_granular_event(event_type, body.get('payload') or {})
