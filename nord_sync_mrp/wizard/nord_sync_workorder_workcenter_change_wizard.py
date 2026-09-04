# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class NordSyncWorkorderWorkcenterChangeWizard(models.TransientModel):
    """Two entry points share this one wizard: nord_sync.workorder.start.
    wizard's own "Change Work Center" button (before Start), and a
    standalone button on the workorder itself, visible once it's already
    'progress' (Start already happened, its button is gone, workcenter_id
    is read-only at that point in the base workorder views).

    action_confirm below branches on that same state: not started yet just
    writes the new workcenter_id and re-enters button_start(); already
    'progress' additionally closes whichever session is open right now and
    reopens a fresh one on the new work center for the same employee(s) --
    same "close the old one as-is, start a new one" reassignment shape
    already used Core-side for the same situation (a mid-session workcenter
    swap), just the client's own copy of it. mrp.workcenter.productivity's
    own workcenter_id is a plain stored field, never a related one, so
    already-closed sessions are never touched by this.
    """
    _name = 'nord_sync.workorder.workcenter.change.wizard'
    _description = 'Nord Sync: Change Work Center'

    workorder_id = fields.Many2one('mrp.workorder', required=True, readonly=True)
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='New Work Center', required=True,
        default=lambda self: self.env['mrp.workorder'].browse(
            self.env.context.get('default_workorder_id'),
        ).workcenter_id.id,
    )

    def action_confirm(self):
        self.ensure_one()
        workorder = self.workorder_id
        if self.workcenter_id == workorder.workcenter_id:
            raise UserError('Pick a different work center, or close this wizard to keep the current one.')
        if workorder.state == 'progress':
            open_employees = workorder.time_ids.filtered(lambda t: not t.date_end).mapped('employee_id')
            workorder.end_previous(doall=True)
            workorder.workcenter_id = self.workcenter_id.id
            for employee in open_employees:
                if employee:
                    workorder.start_employee(employee.id)
            return True
        workorder.workcenter_id = self.workcenter_id.id
        return workorder.with_context(nord_sync_skip_confirm=True).button_start()
