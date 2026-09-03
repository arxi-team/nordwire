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
        (nord.sync.queue.line.data, merged) — the Core never needs a
        follow-up request per entry to know what changed.

        One entry per nord.sync.queue header — a related change
        folded under one (e.g. a workorder under its MO) never appears as
        its own top-level entry: it rides inside its header's own payload
        instead, under a key named after its res_model (see
        nord.sync.queue._nord_sync_aggregate_payload). Every returned header
        is sealed (is_sealed=True) right here, in this same request — the
        next related change for that same owner opens a fresh header rather
        than reopening this one.

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

        # Locked before building the payload (not just before the seal write
        # below) so a concurrent _enqueue_and_notify for the same still-open
        # header blocks until this request's transaction commits, instead of
        # slipping a new line in between the read and the seal — see
        # nord.sync.queue._nord_sync_lock_for_update.
        entries._nord_sync_lock_for_update()
        body = {
            'entries': [{'seq': entry.id, **entry._nord_sync_build_entry()} for entry in entries],
            'last_seq': entries[-1].id if entries else last_seq,
        }
        entries.write({'is_sealed': True})
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

    @http.route(
        '/nord_sync/api/v1/workorder_event', type='http', auth='nord_sync_api_key',
        methods=['POST'], csrf=False,
    )
    def nord_sync_workorder_event(self, **kwargs):
        """Granular Core->client push (session start/stop, job cancellation)
        — opt-in per resource (nord_sync_granular_push on the client's
        mrp.workcenter), unlike the always-on result push above. Same
        res_model-keyed extension-point dispatch as _nord_sync_apply_result.
        """
        try:
            body = request.get_json_data()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return request.make_json_response({'error': 'Invalid JSON body'}, status=400)

        res_model = body.get('res_model')
        event_type = body.get('event_type')
        if not res_model or not event_type:
            return request.make_json_response({'error': 'Missing res_model/event_type'}, status=400)

        config = request.env['nord_sync.config'].sudo()._get_for_company(request.env.company)
        if not config:
            return request.make_json_response({'error': 'Nord Sync not configured for this company'}, status=403)

        return self._nord_sync_apply_workorder_event(config, body, res_model, event_type)

    def _nord_sync_apply_workorder_event(self, config, body, res_model, event_type):
        """Extension point, same shape as _nord_sync_apply_result — base has
        no handler, each Nord Sync Source addon that opts into granular
        push overrides this and checks its own res_model(s) first.
        """
        return request.make_json_response({'error': f'Unsupported res_model: {res_model}'}, status=400)

    @http.route('/nord_sync/api/v1/resources', type='http', auth='nord_sync_api_key', methods=['POST'], csrf=False)
    def nord_sync_resources(self, **kwargs):
        """Nord Sync Resource Mapping (ADR 0026) — the Core pushes its full
        edge.resource list here on every heartbeat tick (see
        _push_nord_sync_resources), upserted wholesale into nord_sync.resource
        by uid. Base-addon endpoint, not a source extension point: the
        mapping is generic (resource.resource, not any one business model),
        so unlike /result and /workorder_event above there's nothing here
        for a source addon (nord_sync_mrp, ...) to override.
        """
        try:
            body = request.get_json_data()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return request.make_json_response({'error': 'Invalid JSON body'}, status=400)

        config = request.env['nord_sync.config'].sudo()._get_for_company(request.env.company)
        if not config:
            return request.make_json_response({'error': 'Nord Sync not configured for this company'}, status=403)

        request.env['nord_sync.resource'].sudo()._nord_sync_upsert_from_core(
            request.env.company, body.get('resources') or [],
        )
        return request.make_json_response({'success': True})
