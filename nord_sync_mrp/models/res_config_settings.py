# -*- coding: utf-8 -*-
from odoo import fields, models


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
