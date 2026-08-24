# -*- coding: utf-8 -*-
from odoo import api, models


class HrEmployee(models.Model):
    """Resource Bridge for the person side of a workorder — mirrors
    mrp_workcenter.py's own Resource Bridge (edge.resource on the Core),
    just sourced from hr.employee instead of mrp.workcenter, and always
    resource_kind='human' there since hr.employee has no equivalent field
    to read it from. A support model of the mrp.production source, not a
    toggle-able source of its own — see _nord_sync_source_key below.
    """
    _inherit = ['hr.employee', 'nord_sync.notify.mixin']

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

    def _nord_sync_source_key(self):
        return 'mrp.production'

    def _nord_sync_payload(self):
        """Payload sent to the Core to keep this employee's edge.resource
        up to date.

        Keys:
            name (str): the employee's display name.
        """
        self.ensure_one()
        return {'name': self.name}
