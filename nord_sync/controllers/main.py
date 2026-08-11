# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

QUEUE_PAGE_SIZE = 500


class NordSyncQueueController(http.Controller):

    @http.route('/nord_sync/api/v1/queue', type='http', auth='nord_sync_api_key', methods=['GET'], csrf=False)
    def nord_sync_queue(self, last_seq=0, **kwargs):
        """Entries carry the full business payload captured at enqueue time
        (nord.sync.queue.data) — the Core never needs a follow-up request per
        entry to know what changed.

        Company is derived from the authenticated technical user (the Bearer
        API key already resolved request.env in ir_http._auth_method_nord_sync_api_key)
        rather than from a client-supplied company_uid — that field is the
        Nord-side tenant identity, not something this endpoint needs to
        cross-check to know who's asking.
        """
        try:
            last_seq = int(last_seq or 0)
        except (TypeError, ValueError):
            last_seq = 0

        config = request.env['nord_sync.config'].sudo()._get_for_company(request.env.company)
        if not config:
            return request.make_json_response({'error': 'Nord Sync not configured for this company'}, status=403)

        entries = request.env['nord.sync.queue'].sudo().search([
            ('id', '>', last_seq),
            ('company_id', '=', config.company_id.id),
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

    @http.route('/nord_sync/api/v1/result', type='http', auth='nord_sync_api_key', methods=['POST'], csrf=False)
    def nord_sync_result(self, **kwargs):
        """The Core pushes here when a Nord-sourced job finishes, or a real
        work session closes. Keyed by res_model (not MRP-specific in the
        wire format), same deliberately-minimal dispatch-by-model shape as
        the queue side — but not every res_model is keyed by a literal
        res_id: mrp.workorder never gets one (the Core never creates a
        client-side workorder to reference), so its own handler resolves by
        two source references instead — see that handler's docstring.
        """
        try:
            body = request.get_json_data()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return request.make_json_response({'error': 'Invalid JSON body'}, status=400)

        res_model = body.get('res_model')
        if not res_model:
            return request.make_json_response({'error': 'Missing res_model'}, status=400)

        config = request.env['nord_sync.config'].sudo()._get_for_company(request.env.company)
        if not config:
            return request.make_json_response({'error': 'Nord Sync not configured for this company'}, status=403)

        return self._nord_sync_apply_result(config, body, res_model)

    def _nord_sync_apply_result(self, config, body, res_model):
        """Extension point — each Nord Sync Source addon that pushes a
        result back (today only nord_sync_mrp: mrp.production/mrp.workorder)
        subclasses this controller and overrides this method, checking its
        own res_model(s) first and calling super() otherwise. Base has none
        — unsupported is the correct answer when no source addon claims it.
        """
        return request.make_json_response({'error': f'Unsupported res_model: {res_model}'}, status=400)
