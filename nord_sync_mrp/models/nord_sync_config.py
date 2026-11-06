# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NordSyncConfig(models.Model):
    """Registers mrp.production as a Nordwire Source — consumed by the
    install wizard's Job Stages & Mapping step and by nord_sync.state.mapping's
    source_model/source_value Selections. _inherit chain, same shape as the
    Core's _apply_nord_sync_entry override in nordos_nord_sync_core_mrp.
    """
    _inherit = 'nord_sync.config'

    nord_sync_confirm_workcenter_on_start = fields.Boolean(
        string='Confirm Work Center on Start',
        default=False,
        help='Off by default (today\'s behavior, unchanged): a workorder\'s "Start" button '
             'starts it immediately. On: interrupts a human-clicked Start (never an '
             'autonomous Nord Core one) with a lightweight wizard showing the work center '
             'already assigned, so it can be confirmed or changed before work actually '
             'begins.',
    )

    nord_sync_default_workcenter_control_mode = fields.Selection([
        ('odoo', 'Odoo'), ('nord', 'Nord'),
    ], string='Default Work Center Control Mode',
        help='Preset applied to the four floor-event fields (Control Mode\'s own fields on '
             'mrp.workcenter) of a new work center that leaves Control Mode and all four of '
             'those fields unset — '
             'left empty (the default), a new work center keeps behaving exactly as it always '
             'has, implicitly "Odoo" via those fields\' own defaults. Purely a starting point: '
             'once a work center exists it never revisits this setting again, so changing it '
             'later never touches a work center already created, and any field explicitly '
             'given at creation time (its own value or Control Mode itself) always wins over '
             'this default.',
    )

    nord_sync_mo_change_behavior = fields.Selection([
        ('close_and_open', 'Close current timesheet and open new on new MO'),
        ('start_without_close', 'Start new WO without closing previous'),
    ], string='Work Center MO Change Behavior', default='close_and_open',
        help='Determines the behavior when the current MO changes on a work center.',
    )

    nord_sync_prevent_mo_change_if_running = fields.Boolean(
        string='Block MO Change If Running',
        default=False,
        help='If enabled, prevents selecting a new MO on a work center if it already has a work order in progress (requires stop first).',
    )

    nord_sync_unassigned_work_behavior = fields.Selection([
        ('first_scheduled', 'Start 1st Scheduled MO'),
        ('unassigned_timesheets', 'Create Unassigned Timesheets'),
    ], string='Machine Working Without MO', default='first_scheduled',
        help='Behavior when the machine reports work but the work center has no MO assigned.',
    )

    @api.model
    def _nord_sync_available_native_sources(self):
        sources = super()._nord_sync_available_native_sources()
        return sources + [{
            'source_model': 'mrp.production',
            'source_field': 'state',
            'label': 'Manufacturing Orders',
        }]

    def _nord_sync_backfill_existing_records(self):
        super()._nord_sync_backfill_existing_records()
        self.env['mrp.workcenter'].sudo().search(
            [('company_id', '=', self.company_id.id)])._nord_sync_notify('create')
        self.env['hr.employee'].sudo().search(
            [('company_id', '=', self.company_id.id)])._nord_sync_notify('create')
        # Real gap found live, 2026-08-18: missed here same as the two
        # above — a pre-existing BOM never got backfilled, so an MO
        # referencing it just warned and created a BOM-less job, forever.
        # company_id 'in' (False, ...) because BOMs
        # can be shared across companies (mrp.bom.company_id is optional),
        # unlike workcenter/employee above which are always company-owned.
        self.env['mrp.bom'].sudo().search(
            [('company_id', 'in', (False, self.company_id.id))])._nord_sync_notify('create')
        # Second real gap, found the same way: mrp.production itself was
        # never backfilled here, only its support models above — an MO
        # created/finished entirely during a disabled window (or before a
        # source addon was even installed) stayed invisible to the Core
        # forever unless someone happened to edit it again afterwards.
        # Only confirmed/progress: a draft MO isn't real work yet (nothing
        # for the Core to do with it), and done/cancel are over — pushing
        # either would just create a nord.job the Core immediately has to
        # treat as historical noise instead of catching up on live work.
        self.env['mrp.production'].sudo().search([
            ('company_id', '=', self.company_id.id), ('state', 'in', ('confirmed', 'progress')),
        ])._nord_sync_notify('create')

    # ── inbound extension points (Core->client result/event push) ──────────────
    # Moved here from nord_sync_mrp/controllers/main.py — the dispatch is now
    # called from nord_sync.inbox._cron_process_pending, not in-request, so it
    # can no longer read request.env/return request.make_json_response. Same
    # _inherit-chain shape as _nord_sync_available_native_sources above: check
    # this addon's own res_model(s) first, fall back to super() otherwise.

    def _nord_sync_apply_result(self, body, res_model):
        if res_model == 'mrp.production':
            return self._nord_sync_result_mrp_production(body)
        return super()._nord_sync_apply_result(body, res_model)

    def _nord_sync_result_mrp_production(self, body):
        self.ensure_one()
        res_id = body.get('res_id')
        if not res_id:
            return False, 'Missing res_id'
        record = self.env['mrp.production'].sudo().browse(int(res_id))
        if not record.exists() or record.company_id != self.company_id:
            return False, 'Unknown record'
        return record._nord_sync_apply_result(
            body.get('qty_produced') or 0.0,
            scrap_qty=body.get('scrap_qty') or 0.0,
            not_pass_qty=body.get('not_pass_qty') or 0.0,
            materials=body.get('materials') or [],
            work_sessions=body.get('work_sessions') or [],
        )

    # ── granular push (session start/stop, job cancellation) ───────────────────

    def _nord_sync_apply_workorder_event(self, body, res_model, event_type):
        if res_model == 'mrp.workorder':
            return self._nord_sync_workorder_event_mrp_workorder(body, event_type)
        if res_model == 'mrp.production':
            return self._nord_sync_workorder_event_mrp_production(body, event_type)
        if res_model == 'mrp.workcenter':
            return self._nord_sync_workorder_event_mrp_workcenter(body, event_type)
        return super()._nord_sync_apply_workorder_event(body, res_model, event_type)

    def _nord_sync_workorder_event_mrp_workcenter(self, body, event_type):
        self.ensure_one()
        res_id = body.get('res_id')
        if not res_id:
            return False, 'Missing res_id'
        workcenter = self.env['mrp.workcenter'].sudo().browse(int(res_id))
        if not workcenter.exists() or workcenter.company_id != self.company_id:
            return False, 'Unknown record'
        if event_type == 'session_start':
            if not workcenter.nord_sync_current_production_id:
                return workcenter._nord_sync_handle_machine_working_without_mo(payload=body.get('payload'))
            wo = workcenter.nord_sync_current_production_id.workorder_ids.filtered(
                lambda w: w.workcenter_id == workcenter and w.state not in ('done', 'cancel')
            )[:1]
            if wo:
                return wo._nord_sync_apply_granular_event(event_type, body.get('payload') or {})
            return workcenter._nord_sync_handle_machine_working_without_mo(payload=body.get('payload'))
        elif event_type == 'session_stop':
            open_lines = self.env['mrp.workcenter.productivity'].sudo().search([
                ('workcenter_id', '=', workcenter.id), ('date_end', '=', False),
            ])
            end_date = (body.get('payload') or {}).get('end_date') or fields.Datetime.now()
            open_lines.write({'date_end': end_date})
            return True, 'ok'
        return True, 'ok'

    def _nord_sync_workorder_event_mrp_workorder(self, body, event_type):
        self.ensure_one()
        res_id = body.get('res_id')
        if not res_id:
            return False, 'Missing res_id'
        workorder = self.env['mrp.workorder'].sudo().browse(int(res_id))
        if not workorder.exists() or workorder.production_id.company_id != self.company_id:
            return False, 'Unknown record'
        return workorder._nord_sync_apply_granular_event(event_type, body.get('payload') or {})

    def _nord_sync_workorder_event_mrp_production(self, body, event_type):
        self.ensure_one()
        res_id = body.get('res_id')
        if not res_id:
            return False, 'Missing res_id'
        production = self.env['mrp.production'].sudo().browse(int(res_id))
        if not production.exists() or production.company_id != self.company_id:
            return False, 'Unknown record'
        return production._nord_sync_apply_granular_event(event_type, body.get('payload') or {})
