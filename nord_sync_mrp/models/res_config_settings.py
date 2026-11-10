# -*- coding: utf-8 -*-
import base64
import io
import secrets

import qrcode

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nord_sync_confirm_workcenter_on_start = fields.Boolean(
        related='nord_sync_config_id.nord_sync_confirm_workcenter_on_start',
        readonly=False,
    )
    nord_sync_default_workcenter_control_mode = fields.Selection(
        related='nord_sync_config_id.nord_sync_default_workcenter_control_mode',
        readonly=False,
    )
    nord_sync_mo_change_behavior = fields.Selection(
        related='nord_sync_config_id.nord_sync_mo_change_behavior',
        readonly=False,
    )
    nord_sync_prevent_mo_change_if_running = fields.Boolean(
        related='nord_sync_config_id.nord_sync_prevent_mo_change_if_running',
        readonly=False,
    )
    nord_sync_unassigned_work_behavior = fields.Selection(
        related='nord_sync_config_id.nord_sync_unassigned_work_behavior',
        readonly=False,
    )

    # nordCount closes MOs with a call to <this link>/<qrcode read>: the
    # token is the only credential, one for the whole database.
    nord_sync_close_token = fields.Char(
        string='Close MO Token', config_parameter='nord_sync_mrp.close_mo_token', readonly=True,
    )
    nord_sync_close_url = fields.Char(string='Close MO Link', compute='_compute_nord_sync_close_link')
    nord_sync_close_qr = fields.Binary(string='Close MO QR', compute='_compute_nord_sync_close_link')

    @api.depends('nord_sync_close_token')
    def _compute_nord_sync_close_link(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for settings in self:
            link = f'{base}/nordwire/close-mo/{settings.nord_sync_close_token}' if settings.nord_sync_close_token else False
            settings.nord_sync_close_url = link
            if not link:
                settings.nord_sync_close_qr = False
                continue
            buffer = io.BytesIO()
            qrcode.make(link, box_size=12, border=4,
                        error_correction=qrcode.constants.ERROR_CORRECT_M).save(buffer, format='PNG')
            settings.nord_sync_close_qr = base64.b64encode(buffer.getvalue())

    def action_nord_sync_generate_close_token(self):
        """Creates the close-MO token, or replaces it (the old link stops working)."""
        self.env['ir.config_parameter'].sudo().set_param(
            'nord_sync_mrp.close_mo_token', secrets.token_urlsafe(24))
        return {'type': 'ir.actions.client', 'tag': 'reload'}
