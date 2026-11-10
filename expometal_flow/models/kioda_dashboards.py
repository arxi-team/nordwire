from odoo import fields, models


class KiodaDashboards(models.Model):
    _inherit = 'kioda.dashboards'

    screen = fields.Selection(selection_add=[('flow', 'Flow')], ondelete={'flow': 'cascade'})

    def action_open_device_url(self):
        # the Flow screen is opened per device (it needs the device token): see "Abrir" in the devices list
        if self.screen == 'flow':
            return self.action_open_devices()
        return super().action_open_device_url()


class KiodaDashboardsDevices(models.Model):
    _inherit = 'kioda.dashboards.devices'

    def action_open_url(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return {'type': 'ir.actions.act_url', 'url': f'{base_url}/flow/v6/?clean&token={self.token}', 'target': 'new'}
