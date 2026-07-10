from werkzeug.exceptions import BadRequest, Forbidden

from odoo import http
from odoo.http import request

PULL_LIMIT = 500


class NordSyncController(http.Controller):

    @http.route('/nord_sync/api/v1/queue', type='http', auth='bearer', methods=['GET'], readonly=True)
    def pull_queue(self, **kwargs):
        if not request.env.user.has_group('nord_sync.group_nord_sync_integration'):
            raise Forbidden('This user is not authorized to call the Nord Sync API.')

        company_uid = kwargs.get('company_uid')
        if not company_uid:
            raise BadRequest('Missing company_uid parameter.')

        config = request.env['nord.sync.config'].sudo().search(
            [('company_uid', '=', company_uid)], limit=1,
        )
        if not config:
            raise BadRequest('Unknown company_uid.')
        if config.company_id.id not in request.env.user.company_ids.ids:
            raise Forbidden('This user is not authorized for this tenant.')

        try:
            last_seq = int(kwargs.get('last_seq', 0))
        except ValueError:
            raise BadRequest('last_seq must be an integer.')

        rows = request.env['nord.sync.queue'].sudo().search([
            ('company_id', '=', config.company_id.id),
            ('id', '>', last_seq),
        ], order='id asc', limit=PULL_LIMIT)

        return request.make_json_response({
            'company_uid': company_uid,
            'last_seq': rows[-1].id if rows else last_seq,
            'entries': [row._to_command() for row in rows],
        })
