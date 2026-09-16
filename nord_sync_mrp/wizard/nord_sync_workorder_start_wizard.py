# -*- coding: utf-8 -*-
from odoo import fields, models


class NordSyncWorkorderStartWizard(models.TransientModel):
    """Interrupts a human-clicked "Start" — either mrp.workorder.button_start
    or the MO header's own mrp.production.action_start, opt-in per company
    via nord_sync_confirm_workcenter_on_start — to show the work center
    already assigned before work actually begins — a confirmation
    checkpoint, not a picker; changing it is a separate step, see
    action_change_workcenter below.
    """
    _name = 'nord_sync.workorder.start.wizard'
    _description = 'Nordwire: Confirm Work Center on Start'

    workorder_id = fields.Many2one('mrp.workorder', required=True, readonly=True)
    workcenter_id = fields.Many2one(related='workorder_id.workcenter_id', readonly=True)
    production_id = fields.Many2one(
        'mrp.production', readonly=True,
        help='Set only when this checkpoint was raised by the MO header\'s own Start button '
             '(mrp.production.action_start) rather than the workorder\'s — picks which record '
             'action_confirm re-enters below. workorder_id/workcenter_id above still point at '
             'the production\'s next-up workorder either way, purely for display.',
    )

    def action_confirm(self):
        """Re-enters whichever Start actually raised this checkpoint —
        production_id set means mrp.production.action_start, otherwise
        mrp.workorder.button_start — with nord_sync_skip_confirm=True so it
        actually starts this time instead of reopening this same wizard.
        Never bypass=True on the workorder path, that also skips the Shop
        Floor employee-badge check, which a human confirming here should
        still have to pass.
        """
        self.ensure_one()
        if self.production_id:
            return self.production_id.with_context(nord_sync_skip_confirm=True).action_start()
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
