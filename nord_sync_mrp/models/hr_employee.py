# -*- coding: utf-8 -*-
from odoo import api, models


class HrEmployee(models.Model):
    """Resource Bridge for the person side of a workorder — mirrors
    mrp_workcenter.py's own Resource Bridge (edge.resource on the Core),
    just sourced from hr.employee instead of mrp.workcenter, and always
    resource_kind='human' there since hr.employee has no equivalent field
    to read it from.
    """
    _inherit = 'hr.employee'

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
            config._enqueue_and_notify('hr.employee', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        self.ensure_one()
        return {'name': self.name}
