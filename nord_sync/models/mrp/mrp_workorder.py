# -*- coding: utf-8 -*-
from odoo import api, models


class MrpWorkorder(models.Model):
    """Source side of the Workorder Bridge: each real mrp.workorder
    (one per actual MO operation, not the BOM's routing template — that's
    the separate BOM Bridge in mrp_bom.py) is pushed create/write/unlink so
    the Core can create/update the matching real nord.timesheet, resolving
    resource_id from its own workcenter_id instead of relying on the BOM
    template's — real MOs can deviate from their BOM's routing (a
    workcenter reassignment), which the template alone could never reflect.
    Also carries employee_assigned_ids (Shop Floor) as a second, optional
    resource reference — the workplace (workcenter_id) and the person
    allocated to the work are two distinct resources on the Core side,
    each with its own real work session.

    No result side anymore (reverted 2026-08-13): a real work session's
    start/end only ever existed on the Core, and nothing about it —
    start, duration — pushes back here mid-flight. The only thing the
    Core ever writes back to the client is the finished job's result
    (mrp.production._nord_sync_apply_result), on a deliberate 'Mark Done'.
    """
    _inherit = 'mrp.workorder'

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
            config = self.env['nord_sync.config'].sudo()._get_for_company(record.company_id)
            if not config or not config.enabled or not config._is_source_enabled('mrp.production'):
                continue
            config._enqueue_and_notify('mrp.workorder', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        self.ensure_one()
        return {
            'production_source_res_id': self.production_id.id,
            'workcenter_source_res_id': self.workcenter_id.id,
            # Snapshot of the work center itself (same shape as
            # mrp.workcenter's own payload) — lets the Core get-or-create the
            # edge.resource on the spot if the Resource Bridge's own eager
            # push hasn't reached it yet for any reason, instead of just
            # dropping the task silently (real gap found 2026-08-18: a
            # pre-existing work center's first push can miss the window
            # between the install wizard's Sources and Finish steps).
            'workcenter': {
                'name': self.workcenter_id.name,
                'resource_kind': self.workcenter_id.resource_kind,
            },
            # duration_expected is in minutes; nord.timesheet.expected_duration is hours.
            'expected_duration': self.duration_expected / 60.0,
            # employee_assigned_ids (Shop Floor) can hold several people —
            # only the first is carried over, one operator per task on the
            # Core side today.
            'employee_source_res_id': self.employee_assigned_ids[:1].id or False,
            # Same lazy-resolution safety net as 'workcenter' above, for the
            # same reason — only sent when someone is actually assigned,
            # since an unresolved operator is optional and never blocks the
            # task (unlike the work center).
            'employee': {'name': self.employee_assigned_ids[0].name} if self.employee_assigned_ids else False,
        }

