# -*- coding: utf-8 -*-
from odoo.http import request

from odoo.addons.nord_sync.controllers.main import NordSyncQueueController as BaseNordSyncQueueController


class NordSyncQueueController(BaseNordSyncQueueController):
    """mrp.production result push-back — _inherit-chain shape: handles what
    it knows, falls back to super() otherwise. The only Core->client push
    there is: a finished job's result, on a deliberate 'Mark Done'. Every
    other action (start, cancel, closing a work session) is Core-side
    only, never pushed to the client (reverted 2026-08-13).
    """

    def _nord_sync_apply_result(self, config, body, res_model):
        if res_model == 'mrp.production':
            return self._nord_sync_result_mrp_production(config, body)
        return super()._nord_sync_apply_result(config, body, res_model)

    def _nord_sync_result_mrp_production(self, config, body):
        res_id = body.get('res_id')
        if not res_id:
            return request.make_json_response({'error': 'Missing res_id'}, status=400)
        record = request.env['mrp.production'].sudo().browse(int(res_id))
        if not record.exists() or record.company_id != config.company_id:
            return request.make_json_response({'error': 'Unknown record'}, status=404)
        applied, message = record._nord_sync_apply_result(
            body.get('qty_produced') or 0.0,
            scrap_qty=body.get('scrap_qty') or 0.0,
            not_pass_qty=body.get('not_pass_qty') or 0.0,
            materials=body.get('materials') or [],
            work_sessions=body.get('work_sessions') or [],
        )
        return request.make_json_response({'success': applied, 'message': message})

    # ── granular push (session start/stop, job cancellation) ───────────────────

    def _nord_sync_apply_workorder_event(self, config, body, res_model, event_type):
        if res_model == 'mrp.workorder':
            return self._nord_sync_workorder_event_mrp_workorder(config, body, event_type)
        if res_model == 'mrp.production':
            return self._nord_sync_workorder_event_mrp_production(config, body, event_type)
        return super()._nord_sync_apply_workorder_event(config, body, res_model, event_type)

    def _nord_sync_workorder_event_mrp_workorder(self, config, body, event_type):
        res_id = body.get('res_id')
        if not res_id:
            return request.make_json_response({'error': 'Missing res_id'}, status=400)
        workorder = request.env['mrp.workorder'].sudo().browse(int(res_id))
        if not workorder.exists() or workorder.production_id.company_id != config.company_id:
            return request.make_json_response({'error': 'Unknown record'}, status=404)
        applied, message = workorder._nord_sync_apply_granular_event(event_type, body.get('payload') or {})
        return request.make_json_response({'success': applied, 'message': message})

    def _nord_sync_workorder_event_mrp_production(self, config, body, event_type):
        res_id = body.get('res_id')
        if not res_id:
            return request.make_json_response({'error': 'Missing res_id'}, status=400)
        production = request.env['mrp.production'].sudo().browse(int(res_id))
        if not production.exists() or production.company_id != config.company_id:
            return request.make_json_response({'error': 'Unknown record'}, status=404)
        applied, message = production._nord_sync_apply_granular_event(event_type, body.get('payload') or {})
        return request.make_json_response({'success': applied, 'message': message})
