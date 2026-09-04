# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .mrp_workcenter_productivity import NORD_SYNC_LOSS_CATEGORY_MAP


class MrpWorkorder(models.Model):
    """Source side of the Workorder Bridge: each real mrp.workorder
    (one per actual MO operation, not the BOM's routing template — that's
    the separate BOM Bridge in mrp_bom.py) is pushed create/write/unlink so
    the Core can create/update the matching real nord.timesheet, resolving
    resource_id from its own workcenter_id instead of relying on the BOM
    template's — real MOs can deviate from their BOM's routing (a
    workcenter reassignment), which the template alone could never reflect.
    Also carries employee_assigned_ids (Shop Floor) as a second, optional
    resource reference — the workplace (workcenter_id) and the person
    allocated to the work are two distinct resources on the Core side,
    each with its own real work session.

    No result side anymore (reverted 2026-08-13): a real work session's
    start/end only ever existed on the Core, and nothing about it —
    start, duration — pushes back here mid-flight. The only thing the
    Core ever writes back to the client is the finished job's result
    (mrp.production._nord_sync_apply_result), on a deliberate 'Mark Done'.
    A support model of the mrp.production source, not a toggle-able source
    of its own — see _nord_sync_source_key below.
    """
    _inherit = ['mrp.workorder', 'nord_sync.notify.mixin']

    electric_consume = fields.Float(
        string='Electric Consume (kWh)', compute='_compute_nord_sync_electric_consume', store=True,
        help='Sum of this workorder\'s own real work sessions\' electric_consume -- same shape '
             'as the Zerynth app\'s own mrp.workorder.zcloud_electric_consume.',
    )
    electric_consume_cost = fields.Float(
        string='Electric Consume Cost', compute='_compute_nord_sync_electric_consume', store=True,
        # Plain Float, not Monetary -- mrp.workorder has no currency_id of its own to hang a
        # currency_field off, same reasoning mrp.workcenter.costs_hour already settled for.
        help='electric_consume x this company\'s energy_tariff_eur_kwh (res.company, Nord '
             'Sync-synced to the Core -- see res_company.py).',
    )

    @api.depends('time_ids.electric_consume', 'company_id.energy_tariff_eur_kwh')
    def _compute_nord_sync_electric_consume(self):
        for order in self:
            order.electric_consume = sum(order.time_ids.mapped('electric_consume'))
            order.electric_consume_cost = order.electric_consume * order.company_id.energy_tariff_eur_kwh

    def _compute_current_operation_cost(self):
        return super()._compute_current_operation_cost() + self.electric_consume_cost

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._nord_sync_notify('create')
        return records

    def write(self, vals):
        result = super().write(vals)
        self._nord_sync_notify('write')
        return result

    def unlink(self):
        self._nord_sync_notify('unlink')
        return super().unlink()

    def _nord_sync_source_key(self):
        return 'mrp.production'

    def _nord_sync_apply_granular_event(self, event_type, payload):
        """Applies one of the real-time work events a granular-push-opted
        resource sends back. session_start moves the workorder to
        'progress'; session_stop only ends its running timer
        (end_previous), it does NOT change state — mrp.workorder has no
        distinct "paused" value, _compute_state only ever toggles between
        'blocked'/'ready' and otherwise leaves 'progress' alone, so a
        workorder legitimately stays 'progress' between sessions, same as
        it would with a human clocking in and out via the Shop Floor app.
        Neither event ever reaches 'done': completion is still exclusively
        the deliberate Result Push on the finished job
        (mrp.production._nord_sync_apply_result above), same as before this
        existed. Never raises — same best-effort posture as the result push
        controller, caller turns the (bool, message) into the HTTP response.

        session_loss_justified is deliberately exempt from the done/cancel
        guard below — it corrects a historical session, not a live work
        event, and the whole reason it exists is to keep working after
        this workorder's MO already reached 'done' (the Result Push itself
        refuses to touch one).

        Keys:
            event_type (str): 'session_start', 'session_stop' or
                'session_loss_justified', any other value is rejected.
            payload (dict): unused for session_start/session_stop (always
                {}). See _nord_sync_apply_session_loss_justified for that
                event's own keys.
        """
        self.ensure_one()
        if event_type == 'session_loss_justified':
            try:
                return self._nord_sync_apply_session_loss_justified(payload)
            except Exception as exc:
                return False, str(exc)
        if self.state in ('done', 'cancel'):
            return False, f'Workorder already {self.state}, event ignored.'
        try:
            if event_type == 'session_start':
                self._nord_sync_button_start_bypassing_employee_check()
            elif event_type == 'session_stop':
                # Not button_pending(): its end_previous(doall=False) only
                # closes a timer started by the *calling* user, and the Nord
                # Core technical user (bypass=True above) is never the one
                # tracked as having started it. doall=True closes whichever
                # timer is actually open on this workorder, regardless of
                # who/what started it — the right primitive for a
                # machine-driven event.
                self.end_previous(doall=True)
            else:
                return False, f'Unknown event_type: {event_type}'
        except Exception as exc:
            return False, str(exc)
        return True, 'ok'

    def _nord_sync_apply_session_loss_justified(self, payload):
        """Rewrites the loss reason on a session already logged by a past
        Result Push — found by nord_sync_timesheet_id, the only stable
        reference to that exact
        mrp.workcenter.productivity row (this workorder can have several
        sessions; pause/resume never reopens an old one). No match (session
        never logged yet, or a stale id) is a no-op, same skip-and-log
        posture as the rest of this bridge — never a hard failure.

        Keys:
            nord_timesheet_id (int, required): matched against
                mrp.workcenter.productivity.nord_sync_timesheet_id.
            loss_name (str, required): the Blocking Reason's display name,
                get-or-created by name.
            loss_category (str, required): 'production'/'speed_loss'/
                'downtime' — mapped to the Odoo loss_type Nord always wins
                on, even for an already-existing reason (see
                mrp.workcenter.productivity.loss._nord_sync_get_or_create).
        """
        self.ensure_one()
        nord_timesheet_id = payload.get('nord_timesheet_id')
        loss_name = payload.get('loss_name')
        odoo_loss_type = NORD_SYNC_LOSS_CATEGORY_MAP.get(payload.get('loss_category'))
        if not nord_timesheet_id or not loss_name or not odoo_loss_type:
            return False, 'Missing nord_timesheet_id/loss_name/loss_category'
        line = self.env['mrp.workcenter.productivity'].sudo().search([
            ('nord_sync_timesheet_id', '=', nord_timesheet_id),
        ], limit=1)
        if not line:
            return False, f'No session found for nord_timesheet_id={nord_timesheet_id}'
        loss = self.env['mrp.workcenter.productivity.loss']._nord_sync_get_or_create(loss_name, odoo_loss_type)
        line.loss_id = loss.id
        return True, 'ok'

    def _nord_sync_button_start_bypassing_employee_check(self):
        """button_start(bypass=True) skips the Shop Floor "link this user to
        an employee" guard the mrp_workorder enterprise app adds — this call
        is a machine-to-machine Nord Core event, never an interactive
        session, exactly the case that parameter exists for. Falls back to
        the plain call when that app isn't installed (base button_start
        takes no such argument, and has no employee concept to skip).

        bypass=True skips employee resolution entirely inside button_start,
        which also skips its own call to start_employee() — the only thing
        that opens the real mrp.workcenter.productivity timer the Shop
        Floor "Today" counter reads. Without this, the workorder/MO state
        still flips to 'progress' (button_start's base class writes that
        directly), but no timer ever starts (real bug, caught live
        2026-08-28). start_employee() is called here explicitly, using the
        operator already assigned via the Workorder Bridge — a no-op when
        that app isn't installed (plain button_start has no employee/timer
        concept to open).

        No operator assigned is not the same as "no timer needed" -- a
        machine-autonomous resource (no human ever assigned, the normal
        case for a port-driven Nord Sync start) has nothing in
        employee_assigned_ids by design. mrp_workorder's own
        _should_start_timer() is hardcoded False (it defers ALL timer
        creation to start_employee(), which requires a real employee_id),
        so without a fallback here the state flip to 'progress' was the
        only visible effect: no mrp.workcenter.productivity session ever
        opened, so Shop Floor's "Today" counter and OEE availability
        stayed at zero for the entire session despite the machine actually
        running (real bug, caught live 2026-09-03). Nord always attributes
        the session to a real hr.employee now — the assigned operator when
        there is one, otherwise the shared "Nordwire" placeholder employee
        (get-or-created on demand, see
        hr.employee._nord_sync_get_or_create_autonomous_employee) — rather
        than an employee-less timer, so every session shows up the same
        way in Shop Floor/OEE regardless of whether a human was involved.
        start_employee() already no-ops if this exact employee already has
        an open session on this workorder, so a retried granular push
        never opens a second one.
        """
        self.ensure_one()
        try:
            self.button_start(bypass=True)
        except TypeError:
            self.button_start()
            return
        employee = self.employee_assigned_ids[:1]
        if not employee:
            employee = self.env['hr.employee']._nord_sync_get_or_create_autonomous_employee(self.company_id)
        self.start_employee(employee.id)

    def _nord_sync_payload(self):
        """Payload sent to the Core for this real workorder.

        Every key below is relational, nested, or unit-converted — none of
        it is "read this field off self", so none of it can move to
        _nord_sync_configurable_payload(). Merged in anyway (empty by
        default) so a company can still add a genuinely scalar field of its
        own later without touching this method.

        Keys:
            production_source_res_id (int): the client's own mrp.production
                id this workorder belongs to.
            workcenter_source_res_id (int): the client's own mrp.workcenter id.
            workcenter (dict): snapshot of the work center itself ({name,
                nord_resource_uid, autonomous_close, granular_push,
                contention_policy, chain_close, mirror_mode, auto_idle_segments,
                idle_segment_reason, auto_tooling_segments, tooling_segment_reason})
                — lets the Core lazily resolve/update the
                edge.resource on the spot if the Resource Bridge's own push
                hasn't reached it yet. No resource_kind key, same as
                mrp.workcenter's own payload — the Core defaults it to
                'machine' on its own.
            expected_duration (float): expected duration in hours (converted
                from duration_expected, which is in minutes).
            sequence (int): this workorder's own routing order within its
                MO (self.sequence) — consulted by Nord Sync Chain Close to
                find this job's earlier operations, not a display/list
                ordering concern on the Core side.
            employee_source_res_id (int or False): the client's own
                hr.employee id of the first assigned operator, False if none
                assigned (only the first of employee_assigned_ids is carried).
            employee (dict or False): {name, nord_resource_uid} snapshot of
                that same employee, only present (non-False) when someone is
                actually assigned — same lazy-resolution safety net as
                'workcenter' above, but optional since an unresolved
                operator never blocks the task.
        """
        self.ensure_one()
        return {
            **self._nord_sync_configurable_payload(),
            'production_source_res_id': self.production_id.id,
            'workcenter_source_res_id': self.workcenter_id.id,
            # Snapshot of the work center itself (same shape as
            # mrp.workcenter's own payload) — lets the Core lazily resolve
            # the edge.resource on the spot if the Resource Bridge's own
            # eager push hasn't reached it yet for any reason, instead of
            # just dropping the task silently (real gap found 2026-08-18: a
            # pre-existing work center's first push can miss the window
            # between the install wizard's Sources and Finish steps). Same
            # "no mapping yet" skip as the eager path applies either way —
            # this only helps once nord_resource_uid is actually set.
            'workcenter': {
                'name': self.workcenter_id.name,
                'nord_resource_uid': self.workcenter_id.resource_id.nord_sync_resource_id.uid or False,
                'autonomous_close': self.workcenter_id.nord_sync_autonomous_close,
                'granular_push': self.workcenter_id.nord_sync_granular_push,
                'contention_policy': self.workcenter_id.nord_sync_contention_policy,
                'chain_close': self.workcenter_id.nord_sync_chain_close,
                'mirror_mode': self.workcenter_id.nord_sync_mirror_mode,
                'auto_idle_segments': self.workcenter_id.nord_sync_auto_idle_segments,
                'idle_segment_reason': self.workcenter_id.nord_sync_idle_segment_reason_name,
                'auto_tooling_segments': self.workcenter_id.nord_sync_auto_tooling_segments,
                'tooling_segment_reason': self.workcenter_id.nord_sync_tooling_segment_reason_name,
            },
            # duration_expected is in minutes; nord.timesheet.expected_duration is hours.
            'expected_duration': self.duration_expected / 60.0,
            'sequence': self.sequence,
            # employee_assigned_ids (Shop Floor) can hold several people —
            # only the first is carried over, one operator per task on the
            # Core side today.
            'employee_source_res_id': self.employee_assigned_ids[:1].id or False,
            # Same lazy-resolution safety net as 'workcenter' above, for the
            # same reason — only sent when someone is actually assigned,
            # since an unresolved operator is optional and never blocks the
            # task (unlike the work center).
            'employee': {
                'name': self.employee_assigned_ids[0].name,
                'nord_resource_uid': self.employee_assigned_ids[0].resource_id.nord_sync_resource_id.uid or False,
            } if self.employee_assigned_ids else False,
        }
