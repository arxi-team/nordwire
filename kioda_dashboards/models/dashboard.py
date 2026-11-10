import uuid

from odoo import api, fields, models


class KiodaDashboardsDevices(models.Model):
    _name = 'kioda.dashboards.devices'
    _description = "Kioda Dashboards Devices"

    # Modelo mantido para dashboards futuras que precisem de autorizar
    # dispositivos por MAC/token (ver kioda.dashboards.screen). A dashboard
    # 'test' não usa este modelo.
    name = fields.Char()
    mac = fields.Char(required=True, readonly=True)
    token = fields.Char(default=lambda self: str(uuid.uuid4()), readonly=True)
    dashboard_id = fields.Many2one('kioda.dashboards', required=True, ondelete="cascade")
    has_access = fields.Boolean(default=False, readonly=True)
    user_id = fields.Many2one('res.users', string='User')

    def action_add_access(self):
        self.has_access = True

    def action_remove_access(self):
        self.has_access = False

    def restart_token(self):
        self.token = str(uuid.uuid4())

    def action_delete(self):
        self.unlink()


class KiodaDashboards(models.Model):
    _name = 'kioda.dashboards'
    _description = "Kioda Dashboards"

    name = fields.Char()
    # Apenas o ecrã 'test' está implementado. Novos ecrãs devem ser
    # adicionados aqui e, ao contrário do 'test', devem passar pela
    # verificação de dispositivo em KiodaDashboardsController._validate_device.
    screen = fields.Selection([('test', 'Test')], default='test', required=True)
    uuid = fields.Char(default=lambda self: str(uuid.uuid4())[:8], readonly=True, copy=False)
    kioda_dashboard_device_ids = fields.One2many('kioda.dashboards.devices', 'dashboard_id', copy=False)
    company_id = fields.Many2one('res.company', string='Company')

    def action_open_devices(self):
        return {
            'name': 'Dispositivos',
            'type': 'ir.actions.act_window',
            'res_model': 'kioda.dashboards.devices',
            'view_mode': 'list',
            'view_id': self.env.ref('kioda_dashboards.kioda_dashboards_devices_view_list').id,
            'target': 'new',
            'domain': [('id', 'in', self.kioda_dashboard_device_ids.ids)],
        }

    def action_open_device_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        url = f"{base_url}/kioda/dashboards/{self.uuid}"

        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }
