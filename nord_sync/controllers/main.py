# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

QUEUE_PAGE_SIZE = 500


class NordSyncQueueController(http.Controller):

    @http.route('/nord_sync/api/v1/queue', type='http', auth='nord_sync_api_key', methods=['GET'], csrf=False)
    def nord_sync_queue(self, company_uid=None, last_seq=0, **kwargs):
        """Entries carry the full business payload captured at enqueue time
        (nord.sync.queue.data) — the Core never needs a follow-up request per
        entry to know what changed.
        """
        try:
            last_seq = int(last_seq or 0)
        except (TypeError, ValueError):
            last_seq = 0

        if not company_uid:
            return request.make_json_response({'error': 'Missing company_uid'}, status=400)

        company = request.env['res.company'].sudo().search(
            [('nord_sync_company_uid', '=', company_uid)], limit=1,
        )
        if not company:
            return request.make_json_response({'error': 'Unknown company_uid'}, status=403)

        entries = request.env['nord.sync.queue'].sudo().search([
            ('id', '>', last_seq),
            ('company_id', '=', company.id),
        ], order='id asc', limit=QUEUE_PAGE_SIZE)

        body = {
            'entries': [{
                'seq': entry.id,
                'model': entry.res_model,
                'operation': entry.operation,
                'res_id': entry.res_id,
                'payload': entry.data or {},
            } for entry in entries],
            'last_seq': entries[-1].id if entries else last_seq,
        }
        return request.make_json_response(body)
