# -*- coding: utf-8 -*-
from odoo import fields, models


class NordSyncWorkorderStartWizard(models.TransientModel):
    """Interrupts a human-clicked mrp.workorder.button_start, opt-in per
    company via nord_sync_confirm_workcenter_on_start — to show the work
    center already assigned before work actually begins — a confirmation
    checkpoint, not a picker; changing it is a separate step, see
    action_change_workcenter below.

    v17 has no MO-header Start button of its own (that's a later Odoo
    version's addition) — this checkpoint is only ever raised from the
    workorder side here.
    """
    _name = 'nord_sync.workorder.start.wizard'
    _description = 'Nordwire: Confirm Work Center on Start'

    workorder_id = fields.Many2one('mrp.workorder', required=True, readonly=True)
    workcenter_id = fields.Many2one(related='workorder_id.workcenter_id', readonly=True)

    def action_confirm(self):
        """Re-enters mrp.workorder.button_start with
        nord_sync_skip_confirm=True so it actually starts this time instead
        of reopening this same wizard. Never bypass=True — that also skips
        the Shop Floor employee-badge check, which a human confirming here
        should still have to pass.
        """
        self.ensure_one()
        return self.workorder_id.with_context(nord_sync_skip_confirm=True).button_start()

    def action_change_workcenter(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nord_sync.workorder.workcenter.change.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': self.workorder_id.id},
        }
