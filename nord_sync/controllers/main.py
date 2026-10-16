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
            return request.make_json_response({'error': 'Nordwire not configured for this company'}, status=403)

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
        work session closes. Only the envelope is validated in-request
        (valid JSON, res_model present, config resolves) — the body is
        captured verbatim into a nord_sync.inbox entry and applied later by
        nord_sync.inbox._cron_process_pending (same
        nord_sync.config._nord_sync_apply_result extension-point dispatch
        the old in-request handler used, just called from the cron now), so
        a slow/failing domain handler never blocks the Core's own request.
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
            return request.make_json_response({'error': 'Nordwire not configured for this company'}, status=403)

        request.env['nord_sync.inbox'].sudo().create({
            'endpoint': 'result', 'res_model': res_model, 'payload': body, 'company_id': config.company_id.id,
        })
        return request.make_json_response({'success': True})

    @http.route(
        '/nord_sync/api/v1/workorder_event', type='http', auth='nord_sync_api_key',
        methods=['POST'], csrf=False,
    )
    def nord_sync_workorder_event(self, **kwargs):
        """Granular Core->client push (session start/stop, job cancellation)
        — opt-in per resource (nord_sync_granular_push on the client's
        mrp.workcenter), unlike the always-on result push above. Same
        envelope-only validation and inbox capture as nord_sync_result.
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
            return request.make_json_response({'error': 'Nordwire not configured for this company'}, status=403)

        request.env['nord_sync.inbox'].sudo().create({
            'endpoint': 'workorder_event', 'res_model': res_model, 'payload': body, 'company_id': config.company_id.id,
        })
        return request.make_json_response({'success': True})

    @http.route('/nord_sync/api/v1/resources', type='http', auth='nord_sync_api_key', methods=['POST'], csrf=False)
    def nord_sync_resources(self, **kwargs):
        """Nordwire Resource Mapping — the Core pushes its full
        edge.resource list here on every heartbeat tick (see
        _push_nord_sync_resources), upserted wholesale into nord_sync.resource
        by uid, later, from the cron — same envelope-only/inbox-capture
        shape as the two routes above. Base-addon endpoint, not a source
        extension point: the mapping is generic (resource.resource, not any
        one business model), so unlike /result and /workorder_event there's
        nothing here for a source addon (nord_sync_mrp, ...) to override.
        This route's own body carries no res_model key at all (just
        {'resources': [...]}) — the inbox entry's res_model is set to the
        fixed literal 'nord_sync.resource', the model it always upserts
        into, rather than read from the body.
        """
        try:
            body = request.get_json_data()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return request.make_json_response({'error': 'Invalid JSON body'}, status=400)

        config = request.env['nord_sync.config'].sudo()._get_for_company(request.env.company)
        if not config:
            return request.make_json_response({'error': 'Nordwire not configured for this company'}, status=403)

        request.env['nord_sync.inbox'].sudo().create({
            'endpoint': 'resources', 'res_model': 'nord_sync.resource', 'payload': body, 'company_id': config.company_id.id,
        })
        return request.make_json_response({'success': True})
