# -*- coding: utf-8 -*-
from odoo import fields, models


class NordSyncAlertWizard(models.TransientModel):
    """Emit an alert on a work center: it stops (the running work order is
    paused) and a stop timesheet opens with the chosen reason, until the
    alerts are cleared or the work center starts again."""
    _name = 'nord_sync.alert.wizard'
    _description = 'Emit Work Center Alert'

    workcenter_id = fields.Many2one('mrp.workcenter', required=True)
    loss_id = fields.Many2one(
        'mrp.workcenter.productivity.loss', string='Reason', required=True,
        domain="[('loss_type', '!=', 'productive')]",
        default=lambda self: self.env['mrp.workcenter.productivity.loss']._nord_sync_get_or_create_undefined())
    description = fields.Char(string='Note')

    def action_emit(self):
        self.ensure_one()
        self.workcenter_id._nord_sync_emit_alert(self.loss_id, self.description)
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}
