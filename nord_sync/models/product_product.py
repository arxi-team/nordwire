# -*- coding: utf-8 -*-
from odoo import api, models


class ProductProduct(models.Model):
    """Dedicated product channel (Docs/NordSyncFase2, Slice 2.3): keeps nord.product
    on the Nord side up to date on its own, independent of any mrp.production —
    unlike the Slice 2.2 payload nested inside an MO entry, res_id here IS this
    product's own id, letting the Core match it directly even if default_code
    changes later (see _apply_nord_sync_product_product's docstring).
    """
    _inherit = 'product.product'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._nord_sync_notify('create')
        return records

    def write(self, vals):
        result = super().write(vals)
        self._nord_sync_notify('write')
        return result

    def unlink(self):
        self._nord_sync_notify('unlink')
        return super().unlink()

    def _nord_sync_notify(self, operation):
        for record in self:
            company = record.company_id or self.env.company
            config = self.env['nord_sync.config'].sudo()._get_for_company(company)
            if not config or not config.enabled:
                continue
            config._enqueue_and_notify('product.product', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        self.ensure_one()
        return {
            'name': self.name,
            'default_code': self.default_code or False,
            'uom': self.uom_id.name,
        }
