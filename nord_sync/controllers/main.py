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
        """Docs/NordSyncFase2, Fase 3 Slice 3.1: the Core pushes here when a
        Nord-sourced job finishes. Chaveado por res_model/res_id (not
        MRP-specific in the wire format) per the 2026-08-05 architecture note in
        NordSyncFase2Plan.md — mrp.production is the only handler today, same
        deliberately-minimal dispatch-by-model shape as the queue side.
        """
        try:
            body = request.get_json_data()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return request.make_json_response({'error': 'Invalid JSON body'}, status=400)

        res_model = body.get('res_model')
        res_id = body.get('res_id')
        if not res_model or not res_id:
            return request.make_json_response({'error': 'Missing res_model/res_id'}, status=400)

        config = request.env['nord_sync.config'].sudo()._get_for_company(request.env.company)
        if not config:
            return request.make_json_response({'error': 'Nord Sync not configured for this company'}, status=403)

        if res_model != 'mrp.production':
            return request.make_json_response({'error': f'Unsupported res_model: {res_model}'}, status=400)

        record = request.env['mrp.production'].sudo().browse(int(res_id))
        if not record.exists() or record.company_id != config.company_id:
            return request.make_json_response({'error': 'Unknown record'}, status=404)

        applied, message = record._nord_sync_apply_result(body.get('qty_produced') or 0.0)
        return request.make_json_response({'success': applied, 'message': message})
