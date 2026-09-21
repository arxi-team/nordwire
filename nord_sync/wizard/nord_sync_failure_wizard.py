# -*- coding: utf-8 -*-
from collections import Counter

from odoo import _, api, fields, models


class NordSyncFailureWizard(models.TransientModel):
    """Action wizard for Sync Failures — one line per failing owner (see
    nord.sync.queue.owner_res_model/owner_res_id), each with its
    own "create an activity for whoever" / "open the related record"
    actions. Two entry points build this: the systray (current visible
    failures, action_open_for_current_failures below) and a button on the
    technical Sync Failures form (one specific header —
    nord.sync.queue.action_open_failure_wizard).
    """
    _name = 'nord_sync.failure.wizard'
    _description = 'Nordwire: Failures'

    # Not readonly: record_name/message are read-only per-line already (no
    # explicit readonly needed, the view just never edits them), but
    # assignee_id/activity_note are exactly what the Manager is here to
    # fill in — readonly=True on this field would have blocked editing any
    # of them, list rows included. create="0"/delete="0" on the list view
    # is what actually stops adding/removing lines, not this.
    line_ids = fields.One2many('nord_sync.failure.wizard.line', 'wizard_id', string='Failures')
    model_breakdown = fields.Char(compute='_compute_model_breakdown')

    @api.depends('line_ids.res_model')
    def _compute_model_breakdown(self):
        """'mrp.workorder: 3, sale.order: 1' — a quick sense of which model is
        actually on fire before scrolling the (record_name, message) list
        below, which has no model column of its own. Skips the count
        entirely once there's only one distinct model, since a breakdown of
        one thing is just the total already shown by the line count."""
        for wizard in self:
            counts = Counter(wizard.line_ids.mapped('res_model'))
            wizard.model_breakdown = (
                ', '.join(f'{model}: {count}' for model, count in counts.most_common())
                if len(counts) > 1 else False
            )
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
            'name': _('Nordwire: Failures'),
            'res_model': self._name,
            'res_id': self.id,
            'views': [[False, 'form']],
            'target': 'new',
        }

    @api.model
    def action_open_for_current_failures(self):
        """Systray entry point — one line per distinct failing owner among
        this company's current failures, both outbound (nord.sync.queue)
        and inbound (nord_sync.inbox — same mechanism, not a second one to
        learn), friendly message taken from whichever failed entry names
        that owner first. Each nord.sync.queue header is already exactly
        one owner, but a sealed header that failed and a fresh one opened
        for the same owner afterward can both be 'failed' at once, so this
        still dedups by owner — same reasoning extends to folding inbox
        owners into the same dict. Inbox entries have no friendly-
        translation helper (nord.sync.queue._nord_sync_friendly_error) — raw
        last_error is used directly for them, same as the technical Sync
        Failures list already shows for the outbound direction.
        """
        Queue = self.env['nord.sync.queue']
        hidden = Queue._nord_sync_hidden_owner_models()
        failed = Queue.sudo().search([
            ('status', '=', 'failed'), ('company_id', 'in', self.env.companies.ids),
        ])
        owners = {}
        for header in failed:
            if header.owner_res_model in hidden:
                continue
            owner = (header.owner_res_model, header.owner_res_id)
            if owner not in owners:
                owners[owner] = header._nord_sync_friendly_error()
        for res_model, res_id, message, _create_date in self.env['nord_sync.inbox']._nord_sync_failed_owners():
            owner = (res_model, res_id)
            if owner not in owners:
                owners[owner] = message
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

    def action_retry_now(self):
        """Same manual resend as the technical Sync Failures list's own
        Retry Now (nord.sync.queue.action_retry_now) — one wake ping per
        company in self.env.companies, matching how this wizard's own
        lines were scoped when opened (action_open_for_current_failures).
        Footer-level, not per-line: the underlying retry is already a
        single per-company ping regardless of how many entries/owners are
        failing (see _retry_failed_webhooks), so a per-line button would
        just do the exact same company-wide sweep as this one, repeatedly.
        """
        self.ensure_one()
        configs = self.env['nord_sync.config'].sudo().search([
            ('company_id', 'in', self.env.companies.ids),
        ])
        for config in configs:
            config._retry_failed_webhooks()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'message': _('Retry requested.'), 'type': 'success'},
        }
