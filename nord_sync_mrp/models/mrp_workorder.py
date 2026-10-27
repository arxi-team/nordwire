# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MrpWorkorder(models.Model):
    """Source side of the Workorder Bridge: each real mrp.workorder
    (one per actual MO operation, not the BOM's routing template — that's
    the separate BOM Bridge in mrp_bom.py) is pushed create/write/unlink so
    the Core can create/update the matching real nord.timesheet, resolving
    resource_id from its own workcenter_id instead of relying on the BOM
    template's — real MOs can deviate from their BOM's routing (a
    workcenter reassignment), which the template alone could never reflect.
    Also carries the real operator (see _nord_sync_current_operator) as a
    second, optional resource reference — the workplace (workcenter_id)
    and the person allocated to the work are two distinct resources on
    the Core side, each with its own real work session.

    No result side anymore (reverted 2026-08-13): a real work session's
    start/end only ever existed on the Core, and nothing about it —
    start, duration — pushes back here mid-flight. The only thing the
    Core ever writes back to the client is the finished job's result
    (mrp.production._nord_sync_apply_result), on a deliberate 'Mark Done'.
    A support model of the mrp.production source, not a toggle-able source
    of its own — see _nord_sync_source_key below.
    """
    _name = 'mrp.workorder'
    _inherit = ['mrp.workorder', 'nord_sync.notify.mixin']

    electric_consume = fields.Float(
        string='Electric Consume (kWh)', compute='_compute_nord_sync_electric_consume', store=True,
        help='Sum of this workorder\'s own real work sessions\' electric_consume -- compatible with '
             'the field shape of known external manufacturing systems for data portability.',
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

    def button_start(self, *args, **kwargs):
        """Interrupts a human-clicked Start with
        nord_sync.workorder.start.wizard when the company opted in
        (nord_sync_confirm_workcenter_on_start) — never for bypass=True
        (the Nord Core's own autonomous start, no human there to answer a
        wizard), a re-entry from that same wizard's own Confirm/Change
        actions (nord_sync_skip_confirm context, set by them once the human
        already answered), or a work center already fully handed to Nord
        (Control Mode == 'nord', see mrp_workcenter.py): confirming which
        work center a resource the company has explicitly said the Core
        owns is on would be backwards. Checked against the full four-field
        preset, not just autonomous_close alone — a 'custom' work center
        with autonomous_close on but the other three untouched still gets
        the checkpoint. Mirror Mode plays no part in this check — it's
        deliberately outside Control Mode (see mrp_workcenter.py).
        """
        self.ensure_one()
        if (
            not kwargs.get('bypass') and not self.env.context.get('nord_sync_skip_confirm')
            and self.state not in ('done', 'cancel')
            and self.workcenter_id.nord_sync_control_mode != 'nord'
        ):
            config = self.env['nord_sync.config'].sudo()._get_for_company(self.company_id)
            if config and config.nord_sync_confirm_workcenter_on_start:
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'nord_sync.workorder.start.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_workorder_id': self.id},
                }
        result = super().button_start(*args, **kwargs)
        if not kwargs.get('bypass'):
            self._nord_sync_notify_floor_event('start')
        return result

    def button_pending(self):
        result = super().button_pending()
        self._nord_sync_notify_floor_event('stop')
        return result

    def button_finish(self):
        result = super().button_finish()
        self._nord_sync_notify_floor_event('stop')
        return result

    def start_employee(self, employee_id):
        # Shop Floor starts a work order per employee, not through button_start
        result = super().start_employee(employee_id)
        self._nord_sync_notify_floor_event('start')
        return result

    def stop_employee(self, employee_ids):
        result = super().stop_employee(employee_ids)
        for workorder in self:
            if not workorder.time_ids.filtered(lambda t: not t.date_end):
                workorder._nord_sync_notify_floor_event('stop')
        return result

    def _nord_sync_notify_floor_event(self, event):
        """Tells the Core a human started ('start') or paused/finished
        ('stop') this work order here, so the machine's session follows —
        the reverse of the Core's own granular push (session_start/
        session_stop), which applies through bypass=True/end_previous and so
        never comes back through here."""
        if self.env.context.get('nord_sync_from_core'):
            return
        self.with_context(nord_sync_floor_event=event)._nord_sync_notify('write')

    def action_nord_sync_change_workcenter(self):
        """Standalone button, visible once this workorder is already
        'progress' (Start's own button is gone by then, and workcenter_id
        is read-only in the base views at that point) — the operator's own
        way to correct which work center they're actually on, independent
        of nord_sync_confirm_workcenter_on_start (that toggle only gates
        the pre-Start checkpoint, this is a standing capability).
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nord_sync.workorder.workcenter.change.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': self.id},
        }

    def _nord_sync_current_operator(self):
        """The real operator for this workorder — never
        employee_assigned_ids: real clients' Shop Floor usage never
        populates that field (a separate "pre-assigned via planning"
        concept), they just click Start, which only ever fills
        employee_ids/time_ids (real bug, caught live 2026-10-22: SK
        Coffee's own data has 0 employee_assigned_ids rows across 457
        worked workorders, so the Workorder Bridge never carried an
        operator for any of them). Whoever has a currently open time_ids
        session wins (the one actually working right now); next, the
        legacy employee_assigned_ids, for any company that does use that
        planning field; last, the most recently active employee_ids entry,
        for a workorder that's already finished its only session.
        """
        self.ensure_one()
        open_session = self.time_ids.filtered(lambda t: not t.date_end).sorted('date_start', reverse=True)
        if open_session:
            return open_session[0].employee_id
        if self.employee_assigned_ids:
            return self.employee_assigned_ids[0]
        last_session = self.time_ids.sorted('date_start', reverse=True)
        if last_session:
            return last_session[0].employee_id
        return self.env['hr.employee']

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
            payload (dict): session_start carries nord_timesheet_id (see
                _nord_sync_button_start_bypassing_employee_check).
                session_stop carries end_date (str, optional) — the Core's
                own real end timestamp, applied on top of whatever
                end_previous()'s own _close() stamped, see that branch's
                own comment for why. See
                _nord_sync_apply_session_loss_justified for that event's
                own keys.
        """
        self.ensure_one()
        if event_type == 'session_loss_justified':
            try:
                return self._nord_sync_apply_session_loss_justified(payload)
            except Exception as exc:
                return False, str(exc)
        if event_type == 'session_setup':
            # Historical too, like session_loss_justified: logged even when
            # the work order already finished by the time it arrives.
            try:
                return self._nord_sync_apply_session_setup(payload)
            except Exception as exc:
                return False, str(exc)
        if self.state in ('done', 'cancel'):
            # Real bug, caught live: a delayed session_stop (retried after
            # the workorder already reached 'done' through the deliberate
            # Result Push) is a moot no-op, not a failure -- the target
            # state was already reached by another path. Returning False
            # here made _cron_process_pending's `if not applied: raise`
            # surface it as a Sync Failures entry needing attention, when
            # there is nothing to retry or fix.
            return True, f'Workorder already {self.state}, event ignored.'
        try:
            if event_type == 'session_start':
                already_open = self.time_ids.filtered(lambda t: not t.date_end)
                self.with_context(nord_sync_from_core=True)._nord_sync_button_start_bypassing_employee_check(payload)
                # Same correction session_stop makes for end_date below: the
                # line just opened is stamped with delivery time, the Core
                # sends the machine's real start.
                start_date = payload.get('start_date')
                if start_date:
                    (self.time_ids.filtered(lambda t: not t.date_end) - already_open).write(
                        {'date_start': start_date},
                    )
            elif event_type == 'session_stop':
                # Not button_pending(): its end_previous(doall=False) only
                # closes a timer started by the *calling* user, and the Nord
                # Core technical user (bypass=True above) is never the one
                # tracked as having started it. doall=True closes whichever
                # timer is actually open on this workorder, regardless of
                # who/what started it — the right primitive for a
                # machine-driven event.
                still_open = self.time_ids.filtered(lambda t: not t.date_end)
                self.with_context(nord_sync_from_core=True).end_previous(doall=True)
                # _close() (base mrp) always stamps date_end with ITS OWN
                # fields.Datetime.now() -- real gap, found live 2026-09-14:
                # on a delayed retry (the granular push queue's own retry
                # cron, not the first attempt) that's measurably later than
                # the Core's real end_date, sent right here in payload but
                # silently discarded until now. Corrected after the fact,
                # on exactly the line(s) this same call just closed --
                # _close()'s own duration-based under/over-performance
                # split (mrp_workorder.py, base) already ran against the
                # wrong instant by then, a pre-existing limitation of that
                # split applied to any delayed correction, not something
                # this fixes; the timestamp actually shown everywhere else
                # (Shop Floor, OEE duration, electric_consume_cost) is.
                end_date = payload.get('end_date')
                if end_date:
                    still_open.write({'date_end': end_date})
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
            reason_name (str, required): the reason's display name,
                get-or-created by name.
            reason_type (str, optional): this reason's nord.reason.
                reason_type_id.name (e.g. 'Performance') — Nord always wins
                on the loss.type it resolves to, even for an
                already-existing reason (see
                mrp.workcenter.productivity.loss._nord_sync_get_or_create).
        """
        self.ensure_one()
        nord_timesheet_id = payload.get('nord_timesheet_id')
        reason_name = payload.get('reason_name')
        if not nord_timesheet_id or not reason_name:
            return False, 'Missing nord_timesheet_id/reason_name'
        line = self.env['mrp.workcenter.productivity'].sudo().search([
            ('nord_sync_timesheet_id', '=', nord_timesheet_id),
        ], limit=1)
        if not line:
            return False, f'No session found for nord_timesheet_id={nord_timesheet_id}'
        loss = self.env['mrp.workcenter.productivity.loss']._nord_sync_get_or_create(
            reason_name, payload.get('reason_type'),
        )
        line.loss_id = loss.id
        return True, 'ok'

    def _nord_sync_apply_session_setup(self, payload):
        """Logs the machine's setup time for this work order (the MO was
        scanned on the PDA, the machine waited for it until its own start)
        as a closed time line with a setup loss reason. Idempotent on
        nord_timesheet_id, so a retried delivery logs it once.

        Keys:
            start_date (str, required) / end_date (str, required).
            nord_timesheet_id (int, required).
            reason_name (str, optional): defaults to 'Setup and Adjustments',
                Odoo's own setup loss. reason_type (str, optional): see
                session_loss_justified.
        """
        self.ensure_one()
        nord_timesheet_id = payload.get('nord_timesheet_id')
        start_date, end_date = payload.get('start_date'), payload.get('end_date')
        if not nord_timesheet_id or not start_date or not end_date:
            return False, 'Missing nord_timesheet_id/start_date/end_date'
        Productivity = self.env['mrp.workcenter.productivity'].sudo()
        if Productivity.search_count([('nord_sync_timesheet_id', '=', nord_timesheet_id)]):
            return True, 'Setup already logged.'
        loss = self.env['mrp.workcenter.productivity.loss']._nord_sync_get_or_create(
            payload.get('reason_name') or 'Setup and Adjustments', payload.get('reason_type') or 'Availability',
        )
        Productivity.create({
            'workorder_id': self.id,
            'workcenter_id': self.workcenter_id.id,
            'date_start': start_date,
            'date_end': end_date,
            'loss_id': loss.id,
            'description': 'Setup',
            'nord_sync_timesheet_id': nord_timesheet_id,
        })
        return True, 'ok'

    def _nord_sync_button_start_bypassing_employee_check(self, payload=None):
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
        case for a port-driven Nordwire start) has nothing in
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

        payload's nord_timesheet_id (see _nord_sync_session_start_payload,
        Core) gets stamped onto the line this call opens — the only stable
        reference session_loss_justified has to find this exact row again
        later, live or after Mark Done. Real bug, found live 2026-09-14:
        without this stamp nord_sync_timesheet_id stayed 0 forever, so
        every reason correction for this session failed permanently ("No
        session found"). The start_employee() no-op case above (already
        has an open session) is skipped on purpose — that session was
        already stamped whenever IT first opened, restamping here would at
        best be a no-op and at worst overwrite a real id with a retried
        push's own (the same nord_timesheet_id either way, so harmless in
        practice, but the intent is "stamp once, at creation").
        """
        self.ensure_one()
        try:
            self.button_start(bypass=True)
        except TypeError:
            self.button_start()
            return
        # Same gap _nord_sync_payload() had (see _nord_sync_current_operator):
        # employee_assigned_ids alone is almost always empty on a real
        # install, which silently routed every Core-initiated start to the
        # autonomous placeholder below even when this exact workorder had
        # a real human on its last session (e.g. a paused job the Core is
        # resuming) -- _nord_sync_current_operator() also falls back
        # through employee_assigned_ids, then the most recent past
        # session's employee, before finally coming up empty here.
        employee = self._nord_sync_current_operator()
        if not employee:
            employee = self.env['hr.employee']._nord_sync_get_or_create_autonomous_employee(self.company_id)
        already_open = self.time_ids.filtered(lambda t: not t.date_end and t.employee_id == employee)
        self.start_employee(employee.id)
        if not already_open:
            nord_timesheet_id = (payload or {}).get('nord_timesheet_id')
            if nord_timesheet_id:
                line = self.time_ids.filtered(lambda t: not t.date_end and t.employee_id == employee)[:1]
                line.nord_sync_timesheet_id = nord_timesheet_id

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
                nord_resource_uids, autonomous_close, granular_push,
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
                MO (self.operation_id.sequence) — consulted by Nordwire Chain Close to
                find this job's earlier operations, not a display/list
                ordering concern on the Core side.
            employee_source_res_id (int or False): the client's own
                hr.employee id of the real operator (see
                _nord_sync_current_operator), False if there's none to
                report.
            employee (dict or False): {name, nord_resource_uids} snapshot of
                that same employee, only present (non-False) when there is
                one — same lazy-resolution safety net as 'workcenter'
                above, but optional since an unresolved operator never
                blocks the task.
        """
        self.ensure_one()
        operator = self._nord_sync_current_operator()
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
                'nord_resource_uids': self.workcenter_id.resource_id.nord_sync_resource_id.mapped('uid'),
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
            # v17's mrp.workorder has no sequence field of its own — its BOM
            # operation (operation_id) always has one, same ordering semantics.
            'sequence': self.operation_id.sequence,
            'employee_source_res_id': operator.id or False,
            # Same lazy-resolution safety net as 'workcenter' above, for the
            # same reason — only sent when there's an actual operator,
            # since an unresolved one is optional and never blocks the task
            # (unlike the work center).
            'employee': {
                'name': operator.name,
                'nord_resource_uids': operator.resource_id.nord_sync_resource_id.mapped('uid'),
            } if operator else False,
            # Only on the line a human start/pause/finish enqueues
            # (_nord_sync_notify_floor_event), never on a plain write.
            **({'floor_event': self.env.context['nord_sync_floor_event']}
               if self.env.context.get('nord_sync_floor_event') else {}),
        }
