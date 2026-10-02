# -*- coding: utf-8 -*-
import logging

from odoo import models
from odoo.http import request
from werkzeug.exceptions import Forbidden, Unauthorized

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _auth_method_nord_sync_api_key(cls):
        """Bearer API key auth for the Nord Core -> this Odoo endpoints.

        Same mechanism as arxi_invoice_connector (/odoo19/custom/addons/bizay/),
        restricted to the Bearer form only — this leg is always Core-to-Odoo,
        never a human, so there's no Basic-auth fallback to support.
        """
        auth_header = request.httprequest.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            raise Unauthorized('Missing bearer API key')

        key = auth_header.removeprefix('Bearer ').strip()
        uid = request.env['res.users.apikeys']._check_credentials(scope='rpc', key=key)
        if not uid:
            _logger.warning('nord_sync: invalid API key on %s', request.httprequest.path)
            raise Forbidden('Invalid API key')
        request.update_env(uid)
