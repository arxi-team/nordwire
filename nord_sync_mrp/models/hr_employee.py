# -*- coding: utf-8 -*-
from odoo import api, models

NORD_SYNC_AUTONOMOUS_EMPLOYEE_NAME = 'Nordwire'


class HrEmployee(models.Model):
    """Resource Bridge for the person side of a workorder — mirrors
    mrp_workcenter.py's own Resource Bridge (edge.resource on the Core),
    just sourced from hr.employee instead of mrp.workcenter, and always
    resource_kind='human' there since hr.employee has no equivalent field
    to read it from. A support model of the mrp.production source, not a
    toggle-able source of its own — see _nord_sync_source_key below.
    """
    _inherit = ['hr.employee', 'nord_sync.notify.mixin']

    @api.model
    def _nord_sync_get_or_create_autonomous_employee(self, company):
        """The employee a granular session_start attributes work to when no
        real operator is assigned to the workorder (machine-autonomous
        work, no human ever picked one) — see
        mrp_workorder.py's own _nord_sync_button_start_bypassing_employee_check.
        Get-or-create by (name, company), same natural-key posture as the
        rest of this bridge (e.g. _get_or_create_nord_sync_product on the
        Core side) — idempotent, never duplicates once it exists.
        """
        employee = self.search([
            ('name', '=', NORD_SYNC_AUTONOMOUS_EMPLOYEE_NAME), ('company_id', '=', company.id),
        ], limit=1)
        if not employee:
            employee = self.create({'name': NORD_SYNC_AUTONOMOUS_EMPLOYEE_NAME, 'company_id': company.id})
        return employee

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
        up to date. Every key except nord_resource_uid is "read this field
        off self" — the rest comes from _nord_sync_configurable_payload(),
        per-company selectable (default: name, unchanged behavior).

        Keys:
            nord_resource_uid (str or False): the Core's edge.resource this
                employee is mapped to (Nordwire Resource Mapping, ADR
                0026) — self.resource_id.nord_sync_resource_id.uid, False
                when unmapped. Same "never create/guess, just skip" posture
                as mrp.workcenter's own payload — see that docstring.
            (all other keys) — entirely per-company configurable, see
                _nord_sync_configurable_payload(). resource_kind isn't sent
                from here either: the Core fixes it to 'human' on its own for
                every hr.employee payload, hr.employee has no field to read
                it from.
        """
        self.ensure_one()
        return {
            **self._nord_sync_configurable_payload(),
            'nord_resource_uid': self.resource_id.nord_sync_resource_id.uid or False,
        }
