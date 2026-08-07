# -*- coding: utf-8 -*-
from odoo import fields, models


class IrActionsServer(models.Model):
    """Adds a "Notify Nord Cloud" server action type, same pattern as core Odoo's
    own state additions (e.g. sms/models/ir_actions_server.py's 'sms' state) —
    a Selection the client picks from instead of typing `records._nord_sync_notify
    ('unlink')` as raw Python in a Server Action's code editor. Only used by
    data/nord_sync_automation.xml today, but editable by the client from
    Settings > Technical > Automation Rules without touching code.
    """
    _inherit = 'ir.actions.server'

    state = fields.Selection(selection_add=[
        ('nord_sync_notify', 'Notify Nord Cloud'),
    ], ondelete={'nord_sync_notify': 'cascade'})
    nord_sync_operation = fields.Selection([
        ('create', 'Record Created'),
        ('write', 'Record Updated'),
        ('unlink', 'Record Deleted'),
    ], string='Nord Sync Change Type',
        help='What happened to the record — sent to the Nord Cloud/Core so they '
             'know whether to create, update, or remove the corresponding job.')

    def _run_action_nord_sync_notify_multi(self, eval_context=None):
        records = eval_context.get('records') or eval_context.get('record')
        if not records or not self.nord_sync_operation:
            return False
        records._nord_sync_notify(self.nord_sync_operation)
        return False
