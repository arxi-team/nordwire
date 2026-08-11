# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MrpWorkcenter(models.Model):
    """Resource Bridge: keeps edge.resource on the Core up to date on its
    own — independent of any mrp.bom, since a work center doesn't need a
    BOM to exist. Unlike product.product (which only reaches the Core
    lazily via BOM/MO association — see _get_or_create_nord_sync_product,
    to avoid flooding the Core with products never actually used in a job),
    the set of work centers is small and bounded, so syncing all of them
    eagerly doesn't risk flooding the Core DB.
    """
    _inherit = 'mrp.workcenter'

    resource_kind = fields.Selection([
        ('human', 'Human'),
        ('machine', 'Machine'),
        ('tool', 'Tool'),
    ], string='Nord Resource Kind', default='machine',
        help='What this work center represents on the Nord Core (edge.resource.resource_kind) — '
             'not native to mrp.workcenter, added for the Resource Bridge.',
    )

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
            config._enqueue_and_notify('mrp.workcenter', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        self.ensure_one()
        return {
            'name': self.name,
            'resource_kind': self.resource_kind,
        }
