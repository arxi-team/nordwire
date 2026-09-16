# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Nordwire's entry in the standard Settings page (sidebar app section),
    mirroring an unrelated project's Shopify integration
    (/odoo17/custom/addons/server-casca-rija/appstore/integration/models/
    res_config_settings.py) — requested explicitly by the user 2026-08-04 in
    place of the earlier top-level app menu.
    """
    _inherit = 'res.config.settings'

    nord_sync_config_id = fields.Many2one(
        'nord_sync.config', compute='_compute_nord_sync_config_id',
    )
    nord_sync_enabled = fields.Boolean(related='nord_sync_config_id.enabled', readonly=False)
    nord_sync_company_uid = fields.Char(related='nord_sync_config_id.company_uid', readonly=False)

    @api.depends('company_id')
    def _compute_nord_sync_config_id(self):
        for rec in self:
            rec.nord_sync_config_id = self.env['nord_sync.config']._get_or_create_for_company(
                rec.company_id or self.env.company,
            )

    def action_open_nord_sync_install_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nord_sync.install.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_company_id': (self.company_id or self.env.company).id},
        }
