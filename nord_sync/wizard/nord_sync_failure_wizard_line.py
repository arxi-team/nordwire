# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class NordSyncFailureWizardLine(models.TransientModel):
    _name = 'nord_sync.failure.wizard.line'
    _description = 'Nordwire: Failure Action Line'

    wizard_id = fields.Many2one('nord_sync.failure.wizard', required=True, ondelete='cascade')
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    record_name = fields.Char(string='Record')
    message = fields.Char(string='Reason')
    assignee_id = fields.Many2one('res.users', string='Assign Activity To')
    activity_note = fields.Char(string='Activity Note')
    activity_deadline = fields.Date(string='Deadline', default=lambda self: fields.Date.context_today(self))

    def action_create_activity(self):
        self.ensure_one()
        if not self.assignee_id:
            raise UserError(_('Choose someone to assign the activity to first.'))
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_('This record no longer exists.'))
        record.activity_schedule(
            'mail.mail_activity_data_todo',
            date_deadline=self.activity_deadline,
            summary=_('Nordwire: follow-up requested'),
            note=self.activity_note or self.message or _('Nordwire: this record is not syncing to the Nord Cloud.'),
            user_id=self.assignee_id.id,
        )
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'message': _('Activity created.'), 'type': 'success', 'next': {'type': 'ir.actions.act_window_close'}},
        }

    def action_open_related_record(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'views': [[False, 'form']],
            'target': 'current',
        }
