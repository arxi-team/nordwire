# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class NordSyncFailureWizard(models.TransientModel):
    """Action wizard for Sync Failures — one line per failure the user is
    meant to see (see nord.sync.queue._nord_sync_visible_owner), each with
    its own "create an activity for whoever" / "open the related record"
    actions. Two entry points build this: the systray (current visible
    failures, action_open_for_current_failures below) and a button on the
    technical Sync Failures form (one specific entry, any res_model —
    nord.sync.queue.action_open_failure_wizard).
    """
    _name = 'nord_sync.failure.wizard'
    _description = 'Nord Sync: Failures'

    # Not readonly: record_name/message are read-only per-line already (no
    # explicit readonly needed, the view just never edits them), but
    # assignee_id/activity_note are exactly what the Manager is here to
    # fill in — readonly=True on this field would have blocked editing any
    # of them, list rows included. create="0"/delete="0" on the list view
    # is what actually stops adding/removing lines, not this.
    line_ids = fields.One2many('nord_sync.failure.wizard.line', 'wizard_id', string='Failures')

    def _action_open(self):
        """views (not just view_mode) — action_open_for_current_failures
        below is called via a plain orm.call from the systray's JS, not a
        button (type="object"), so there's no call_button-side clean_action
        normalization to fill it in: the client's doAction() gets this dict
        exactly as returned and expects the full shape, or _preprocessAction
        fails trying to read action.views.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nord Sync: Failures'),
            'res_model': self._name,
            'res_id': self.id,
            'views': [[False, 'form']],
            'target': 'new',
        }

    @api.model
    def action_open_for_current_failures(self):
        """Systray entry point — one line per distinct visible owner among
        this company's current failures, friendly message taken from
        whichever failed entry names that owner first.
        """
        failed = self.env['nord.sync.queue'].sudo().search([
            ('status', '=', 'failed'), ('company_id', 'in', self.env.companies.ids),
        ])
        owners = {}
        for entry in failed:
            owner = entry._nord_sync_visible_owner()
            if owner and owner not in owners:
                owners[owner] = entry._nord_sync_friendly_error()
        line_vals = []
        for (res_model, res_id), message in owners.items():
            record = self.env[res_model].sudo().browse(res_id)
            if not record.exists():
                continue
            line_vals.append((0, 0, {
                'res_model': res_model,
                'res_id': res_id,
                'record_name': record.display_name,
                'message': message,
            }))
        wizard = self.create({'line_ids': line_vals})
        return wizard._action_open()
