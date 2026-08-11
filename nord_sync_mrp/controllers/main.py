# -*- coding: utf-8 -*-
from odoo.addons.nord_sync.controllers.main import NordSyncQueueController as BaseNordSyncQueueController
from odoo.http import request


class NordSyncQueueController(BaseNordSyncQueueController):
    """mrp.production/mrp.workorder result push-back — _inherit-chain
    shape: handles what it knows, falls back to super() otherwise.
    """

    def _nord_sync_apply_result(self, config, body, res_model):
        if res_model == 'mrp.production':
            return self._nord_sync_result_mrp_production(config, body)
        if res_model == 'mrp.workorder':
            return self._nord_sync_result_mrp_workorder(config, body)
        return super()._nord_sync_apply_result(config, body, res_model)

    def _nord_sync_result_mrp_production(self, config, body):
        res_id = body.get('res_id')
        if not res_id:
            return request.make_json_response({'error': 'Missing res_id'}, status=400)
        record = request.env['mrp.production'].sudo().browse(int(res_id))
        if not record.exists() or record.company_id != config.company_id:
            return request.make_json_response({'error': 'Unknown record'}, status=404)
        applied, message = record._nord_sync_apply_result(body.get('qty_produced') or 0.0)
        return request.make_json_response({'success': applied, 'message': message})

    def _nord_sync_result_mrp_workorder(self, config, body):
        """Resolves the mrp.workorder by (production source reference,
        workcenter source reference) instead of a literal res_id — the Core
        never has the client's workorder id, only the MO's and the
        workcenter's. Assumes 1 workorder per workcenter per MO, the normal
        case unless the same operation repeats on the same MO (known,
        accepted gap — the second workorder for that repeat can't be
        distinguished from the first by this lookup alone).
        """
        production_source_res_id = body.get('production_source_res_id')
        workcenter_source_res_id = body.get('workcenter_source_res_id')
        if not production_source_res_id or not workcenter_source_res_id:
            return request.make_json_response(
                {'error': 'Missing production_source_res_id/workcenter_source_res_id'}, status=400,
            )
        production = request.env['mrp.production'].sudo().browse(int(production_source_res_id))
        if not production.exists() or production.company_id != config.company_id:
            return request.make_json_response({'error': 'Unknown production'}, status=404)
        workcenter = request.env['mrp.workcenter'].sudo().browse(int(workcenter_source_res_id))
        if not workcenter.exists():
            return request.make_json_response({'error': 'Unknown workcenter'}, status=404)
        workorder = request.env['mrp.workorder'].sudo().search([
            ('production_id', '=', production.id), ('workcenter_id', '=', workcenter.id),
        ], limit=1)
        if not workorder:
            return request.make_json_response({'error': 'No matching workorder'}, status=404)
        applied, message = workorder._nord_sync_apply_result(body.get('duration') or 0.0)
        return request.make_json_response({'success': applied, 'message': message})
