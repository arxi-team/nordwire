import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class KiodaDashboardsController(http.Controller):

    @http.route(['/kioda/dashboards/<uuid>'], methods=['GET'], csrf=False, type='http', auth="public")
    def dashboard_details(self, uuid=False, **kwargs):
        if not uuid:
            return request.render('kioda_dashboards.not_found', {'uuid': 'uuid-not-found'})

        dashboard = request.env['kioda.dashboards'].sudo().search([('uuid', '=', uuid)], limit=1)
        if not dashboard:
            return request.render('kioda_dashboards.not_found', {'uuid': 'dashboard-not-found'})

        # A dashboard 'test' é pública e não exige verificação de
        # dispositivo (MAC/token). Ecrãs futuros que precisem dessa
        # verificação devem ser tratados aqui antes de renderizar, usando
        # o modelo kioda.dashboards.devices (ver models/dashboard.py).
        if dashboard.screen != 'test':
            _logger.warning("Kioda Dashboards: screen '%s' sem verificação de dispositivo implementada", dashboard.screen)
            return request.render('kioda_dashboards.not_found', {'uuid': 'screen-not-implemented'})

        data = dashboard.read(['name', 'screen', 'uuid'])[0]

        return request.render('kioda_dashboards.main_dashboard_views', {
            'data': json.dumps(data),
        })
