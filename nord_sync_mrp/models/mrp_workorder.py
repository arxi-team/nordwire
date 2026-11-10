# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


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

    nord_sync_not_ok_count = fields.Integer(
        string='Not OK (PDA)', readonly=True, copy=False,
        help='Units rejected on the Nord PDA ("Não OK") while this operation was running. '
             'Each one is declared on the Core as a not_pass of 1, and reaches this '
             'production order with the job\'s result as quality time.',
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
        if vals.get('state') in ('done', 'cancel', 'pending'):
            self._nord_sync_update_wc_current_production_on_stop()
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
        self._nord_sync_identify_on_workcenter()
        # Shop Floor's button_start goes through start_employee, which tells the
        # Nord side itself: one start, not two.
        result = super(MrpWorkorder, self.with_context(nord_sync_in_button_start=True)).button_start(*args, **kwargs)
        if not kwargs.get('bypass'):
            self._nord_sync_notify_floor_event('start')
        return result

    def _nord_sync_identify_on_workcenter(self):
        """A work order about to start takes its MO onto the work center
        first: the previous MO is dealt with by the work center's own MO-change
        setting (its stop reaches the Nord side before this start does) and a
        setup left by a PDA scan ends here, since Odoo refuses to start a
        work center that is blocked by one."""
        for workorder in self:
            workcenter = workorder.workcenter_id
            if not (workcenter and workorder.production_id):
                continue
            workcenter._nord_sync_close_setup_lines(workorder)
            workcenter.with_context(
                nord_sync_skip_prevent_check=True,
                nord_sync_from_wo_start=True,
                nord_sync_starting_workorder_ids=workorder.ids,
            ).nord_sync_current_production_id = workorder.production_id.id

    def button_pending(self):
        result = super().button_pending()
        self._nord_sync_notify_floor_event('stop')
        self._nord_sync_update_wc_current_production_on_stop()
        return result

    def button_finish(self):
        result = super().button_finish()
        self._nord_sync_notify_floor_event('stop')
        self._nord_sync_update_wc_current_production_on_stop()
        return result

    def action_cancel(self):
        result = super().action_cancel()
        self._nord_sync_update_wc_current_production_on_stop()
        return result

    def start_employee(self, employee_id):
        # Shop Floor starts a work order per employee, not through button_start
        self._nord_sync_identify_on_workcenter()
        result = super().start_employee(employee_id)
        if not self.env.context.get('nord_sync_in_button_start'):
            self._nord_sync_notify_floor_event('start')
        return result

    def stop_employee(self, employee_ids):
        result = super().stop_employee(employee_ids)
        for workorder in self:
            if not workorder.time_ids.filtered(lambda t: not t.date_end):
                workorder._nord_sync_notify_floor_event('stop')
                workorder._nord_sync_update_wc_current_production_on_stop()
        return result

    def _nord_sync_update_wc_current_production_on_stop(self):
        """When this work order stops (finished, paused, cancelled, or employee stopped),
        checks whether the work center is still being used by this MO. If no active
        open timesheets or running work orders remain on that work center, clears
        nord_sync_current_production_id so it does not stay stuck on an MO that is not in use."""
        for wo in self:
            wc = wo.workcenter_id
            if wc and wc.nord_sync_current_production_id == wo.production_id:
                other_open_session = self.env['mrp.workcenter.productivity'].search([
                    ('workcenter_id', '=', wc.id),
                    ('date_end', '=', False),
                    ('nord_sync_downtime_kind', '=', False),
                ], limit=1)
                if other_open_session and other_open_session.workorder_id:
                    new_mo = other_open_session.workorder_id.production_id
                    wc.with_context(nord_sync_skip_mo_change=True).nord_sync_current_production_id = new_mo.id
                else:
                    other_running_wo = self.env['mrp.workorder'].search([
                        ('workcenter_id', '=', wc.id),
                        ('state', '=', 'progress'),
                        ('id', '!=', wo.id),
                    ], limit=1)
                    running_times = other_running_wo.time_ids.filtered(lambda t: not t.date_end)
                    if running_times:
                        wc.with_context(nord_sync_skip_mo_change=True).nord_sync_current_production_id = other_running_wo.production_id.id
                    else:
                        wc.with_context(nord_sync_skip_mo_change=True).nord_sync_current_production_id = False

    def _nord_sync_notify_floor_event(self, event):
        """Tells the Core a human started ('start') or paused/finished
        ('stop') this work order here, so the machine's session follows —
        the reverse of the Core's own granular push (session_start/
        session_stop), which applies through bypass=True/end_previous and so
        never comes back through here."""
        if self.env.context.get('nord_sync_from_core'):
            return
        self.with_context(nord_sync_floor_event=event)._nord_sync_notify('write')

    def action_nord_sync_not_ok(self):
        """One unit rejected on the PDA ("Não OK"): counted here, noted on
        the MO, and sent to the Core as a 'not_pass' floor event, which
        declares it there (resource_setup_nord_sync.py). Only while the
        machine is running it, on a work center with stop tracking on — the
        fair demo's opt-in. Scrapped and logged as quality time right away,
        the same way the job's result does it for the Core's not_pass.

        The counter and the floor event go out in one write: write() already
        notifies the Core, and nord_sync_floor_event rides along on it, so
        the Core gets exactly one entry per tap.
        """
        self.ensure_one()
        if not self.workcenter_id.nord_sync_stop_tracking:
            raise UserError(self.env._('%s does not track stops on Nord.', self.workcenter_id.display_name))
        if self.state != 'progress' or not self._nord_sync_is_running():
            # The open time line is the machine running (session_start
            # opens it, session_stop closes it): a reject needs a running
            # machine, not just an operation started at some point.
            raise UserError(self.env._('%s is stopped.', self.workcenter_id.display_name))
        production = self.production_id
        self.with_context(nord_sync_floor_event='not_pass').write({
            'nord_sync_not_ok_count': self.nord_sync_not_ok_count + 1,
        })
        # Same scrap and quality time a not_pass gets when the Core's result
        # arrives (mrp.production._nord_sync_apply_result), applied now;
        # that result leaves these units out.
        production._nord_sync_create_scrap(1, self.env._('Nord PDA: not OK on %s', self.name), workorder=self)
        production._nord_sync_log_quality_loss(1, workorder=self)
        production.message_post(body=self.env._(
            'Nord PDA: 1 unit not OK on %(operation)s (%(count)s so far).',
            operation=self.name, count=self.nord_sync_not_ok_count,
        ))
        return self.nord_sync_not_ok_count

    def _nord_sync_is_running(self):
        """The machine is working this operation now: an open work line (the
        Core's session_start opens it, session_stop closes it), not a setup
        or stop line shown live."""
        self.ensure_one()
        return bool(self.time_ids.filtered(lambda t: not t.date_end and not t.nord_sync_downtime_kind))

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
        # Acting for the Core (nord_sync_from_core), the acting user is the
        # integration's technical user, never a real operator: its employee
        # (Administrador) only shows up in time_ids because an earlier
        # operator-less session got attributed to it, and falling back to it
        # here would keep perpetuating that.
        technical = (
            self.env.user.employee_id
            if self.env.context.get('nord_sync_from_core') else self.env['hr.employee']
        )
        # The "Nordwire" placeholder employee an older version of this addon
        # created for operator-less sessions: its past lines are still in
        # time_ids, and it must never be picked up as a real operator.
        technical |= self.env['hr.employee'].sudo().with_context(active_test=False).search([
            ('name', '=', 'Nordwire'), ('user_id', '=', False), ('company_id', '=', self.company_id.id),
        ])
        open_session = self.time_ids.filtered(
            lambda t: not t.date_end and t.employee_id and t.employee_id not in technical
        ).sorted('date_start', reverse=True)
        if open_session:
            return open_session[0].employee_id
        assigned = self.employee_assigned_ids - technical
        if assigned:
            return assigned[0]
        last_session = self.time_ids.filtered(lambda t: t.employee_id and t.employee_id not in technical).sorted('date_start', reverse=True)
        if last_session:
            return last_session[0].employee_id
        return self.env['hr.employee']

    def _nord_sync_source_key(self):
        return 'mrp.production'

    def _prepare_timeline_vals(self, duration, date_start, date_end=False):
        """A Nord session is the machine's real running time: always "Fully
        Productive Time". Odoo's own rule opens it as "Reduced Speed" once
        this work order has run past its expected duration, which tagged
        every session after the first stop that way."""
        vals = super()._prepare_timeline_vals(duration, date_start, date_end=date_end)
        if self.env.context.get('nord_sync_from_core'):
            productive = self.env['mrp.workcenter.productivity.loss'].search([('loss_type', '=', 'productive')], limit=1)
            if productive:
                vals['loss_id'] = productive.id
        return vals

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
            event_type (str): 'session_start', 'session_stop',
                'session_loss_justified', 'session_setup' or
                'session_downtime', any other value is rejected.
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
        if event_type in ('session_setup', 'session_downtime', 'session_downtime_open', 'session_downtime_cancel'):
            # Historical too, like session_loss_justified: logged even when
            # the work order already finished by the time it arrives.
            try:
                if event_type == 'session_downtime_open':
                    return self._nord_sync_apply_session_downtime_open(payload)
                if event_type == 'session_downtime_cancel':
                    return self._nord_sync_apply_session_downtime_cancel(payload)
                if event_type == 'session_downtime':
                    return self._nord_sync_apply_session_downtime(payload)
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
                self._nord_sync_close_before_start(payload)
                Line = self.env['mrp.workcenter.productivity'].sudo()
                already_open = Line.search([('workorder_id', '=', self.id), ('date_end', '=', False)])
                self.with_context(nord_sync_from_core=True)._nord_sync_button_start_bypassing_employee_check(payload)
                # Same correction session_stop makes for end_date below: the
                # line just opened is stamped with delivery time, the Core
                # sends the machine's real start.
                opened = Line.search([('workorder_id', '=', self.id), ('date_end', '=', False)]) - already_open
                start_date = payload.get('start_date')
                if start_date:
                    opened.write({'date_start': start_date})
                # ... and carries the Core's session id, which the stop looks the line up by. Stamped here
                # too (not only when the helper opened it itself): a line opened some other way by the
                # start was left with no id, and the stop never closed it.
                if payload.get('nord_timesheet_id'):
                    opened.filtered(lambda t: not t.nord_sync_timesheet_id).write(
                        {'nord_sync_timesheet_id': payload['nord_timesheet_id']})
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
                self._nord_sync_update_wc_current_production_on_stop()
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
        return self._nord_sync_log_downtime(payload, 'setup')

    def _nord_sync_apply_session_downtime(self, payload):
        """Logs a stop of the machine in the middle of this work order
        (Core: nord_sync_stop_tracking) as a closed time line: unjustified
        ("Undefined" loss) unless the Core already had a reason for it; a
        later reason reaches the same line through session_loss_justified.
        Idempotent on nord_timesheet_id.

        Keys:
            start_date (str, required) / end_date (str, required).
            nord_timesheet_id (int, required).
            reason_name (str, optional) / reason_type (str, optional): see
                session_loss_justified; absent means unjustified.
        """
        self.ensure_one()
        return self._nord_sync_log_downtime(payload, 'stop')

    def _nord_sync_apply_session_downtime_open(self, payload):
        """Shows a setup (PDA scan, handover) or a stop of the machine live:
        an open time line, closed by the later session_setup/
        session_downtime with the same nord_timesheet_id. While it is open
        the work center shows as blocked, Odoo's own way of saying it is not
        producing; the Core's next session_start closes it first.

        Keys:
            nord_timesheet_id (int, required) / start_date (str, required).
            kind (str, required): 'setup' or 'stop'.
            reason_name (str, optional) / reason_type (str, optional).
        """
        self.ensure_one()
        nord_timesheet_id, start_date, kind = (payload.get(k) for k in ('nord_timesheet_id', 'start_date', 'kind'))
        if not nord_timesheet_id or not start_date or kind not in ('setup', 'stop'):
            return False, 'Missing nord_timesheet_id/start_date/kind'
        Productivity = self.env['mrp.workcenter.productivity'].sudo()
        if Productivity.search_count([('nord_sync_timesheet_id', '=', nord_timesheet_id)]):
            return True, 'Already shown.'
        Productivity.create(self._nord_sync_downtime_line_vals(payload, kind))
        return True, 'ok'

    def _nord_sync_apply_session_downtime_cancel(self, payload):
        """A segment shown live that turned out not to be this work order's
        (another machine's changeover took it over, or a setup was undone):
        its open line goes. A closed one is history and stays.

        Keys:
            nord_timesheet_id (int, required).
        """
        self.ensure_one()
        lines = self.env['mrp.workcenter.productivity'].sudo().search([
            ('nord_sync_timesheet_id', '=', payload.get('nord_timesheet_id') or -1), ('date_end', '=', False),
        ])
        lines.unlink()
        return True, 'ok'

    def _nord_sync_downtime_loss(self, kind, payload):
        Loss = self.env['mrp.workcenter.productivity.loss']
        if kind == 'setup':
            return Loss._nord_sync_get_or_create(
                payload.get('reason_name') or 'Setup and Adjustments', payload.get('reason_type') or 'Availability',
            )
        if payload.get('reason_name'):
            return Loss._nord_sync_get_or_create(payload['reason_name'], payload.get('reason_type'))
        return Loss._nord_sync_get_or_create_undefined()

    def _nord_sync_downtime_line_vals(self, payload, kind):
        return {
            'workorder_id': self.id,
            'workcenter_id': self.workcenter_id.id,
            'date_start': payload['start_date'],
            'date_end': payload.get('end_date') or False,
            'loss_id': self._nord_sync_downtime_loss(kind, payload).id,
            'description': 'Setup' if kind == 'setup' else 'Unjustified stop',
            'nord_sync_timesheet_id': payload['nord_timesheet_id'],
            'nord_sync_downtime_kind': kind,
            # No human behind a machine downtime line: user_id would default
            # to the Core's technical user (Administrador), which
            # mrp_workorder turns into that user's employee.
            'user_id': False,
            'employee_id': False,
        }

    def _nord_sync_log_downtime(self, payload, kind):
        """Closes the line session_downtime_open showed live, or logs the
        whole segment when it never was (an older Core, a lost event).
        Idempotent on nord_timesheet_id."""
        nord_timesheet_id = payload.get('nord_timesheet_id')
        start_date, end_date = payload.get('start_date'), payload.get('end_date')
        if not nord_timesheet_id or not start_date or not end_date:
            return False, 'Missing nord_timesheet_id/start_date/end_date'
        Productivity = self.env['mrp.workcenter.productivity'].sudo()
        line = Productivity.search([('nord_sync_timesheet_id', '=', nord_timesheet_id)], limit=1)
        if line and line.date_end:
            return True, 'Already logged.'
        if line:
            # Its reason may have been set while it was open (a justified stop)
            line.write({
                'date_start': start_date, 'date_end': end_date,
                'loss_id': self._nord_sync_downtime_loss(kind, payload).id,
            })
            return True, 'ok'
        Productivity.create(self._nord_sync_downtime_line_vals(payload, kind))
        return True, 'ok'

    def _nord_sync_open_machine_lines(self):
        """Open time lines of this work order that no person owns and no Nord session claims."""
        self.ensure_one()
        return self.env['mrp.workcenter.productivity'].sudo().search([
            ('workorder_id', '=', self.id), ('date_end', '=', False),
            ('employee_id', '=', False), ('user_id', '=', False),
            ('nord_sync_downtime_kind', '=', False), ('nord_sync_timesheet_id', 'in', (False, 0)),
        ])

    def _nord_sync_close_before_start(self, payload):
        """Before a Nord session opens its line: whatever this machine still
        shows open must end where it starts. A setup/stop line on its work
        center would block the start (Odoo refuses to start a blocked work
        center), and a work line of an older Nord session left open (its
        stop never arrived) would swallow this one: the start finds a line
        already open and opens none, which once made a 12-day line."""
        self.ensure_one()
        start = payload.get('start_date') or fields.Datetime.now()
        stale = self.env['mrp.workcenter.productivity'].sudo().search([
            ('workcenter_id', '=', self.workcenter_id.id), ('date_end', '=', False),
            ('nord_sync_downtime_kind', '!=', False),
        ])
        stale |= self.time_ids.filtered(
            lambda t: not t.date_end and t.nord_sync_timesheet_id
            and t.nord_sync_timesheet_id != payload.get('nord_timesheet_id')
        )
        # A machine line (no employee, no user) of this work order with no Nord session id: one a Nord
        # start opened without stamping it, whose stop therefore never found it. Never a person's line.
        stale |= self._nord_sync_open_machine_lines()
        for line in stale:
            line.date_end = max(fields.Datetime.to_datetime(start), line.date_start)

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
        running (real bug, caught live 2026-09-03). employee_id on
        mrp.workcenter.productivity is a plain compute/store field, not
        required, so with no operator to attribute it to the session is
        opened without one, via the same _prepare_timeline_vals
        start_employee() itself uses -- a legitimate session, only nobody
        to attribute the cost to. With an operator (assigned or already on
        a past session) start_employee() is used as before, and already
        no-ops if that employee has an open session here, so a retried
        granular push never opens a second one. session_stop closes
        whichever timer is open (end_previous(doall=True)), so it never
        depended on the line having an employee.

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
        # employee-less session below even when this exact workorder had
        # a real human on its last session (e.g. a paused job the Core is
        # resuming) -- _nord_sync_current_operator() also falls back
        # through employee_assigned_ids, then the most recent past
        # session's employee, before finally coming up empty here.
        employee = self._nord_sync_current_operator()
        if employee:
            already_open = self.time_ids.filtered(lambda t: not t.date_end and t.employee_id == employee)
            self.start_employee(employee.id)
        else:
            already_open = self.time_ids.filtered(lambda t: not t.date_end)
            if not already_open:
                # employee_id is False explicitly: mrp_workorder computes it
                # from user_id (defaulted to the acting user, here the Core's
                # technical user), so leaving it out attributed every
                # operator-less session to that user's employee
                # ("Administrador").
                self.env['mrp.workcenter.productivity'].create({
                    **self._prepare_timeline_vals(self.duration, fields.Datetime.now()),
                    'user_id': False,
                    'employee_id': False,
                })
        if not already_open:
            nord_timesheet_id = (payload or {}).get('nord_timesheet_id')
            if nord_timesheet_id:
                line = self.time_ids.filtered(
                    lambda t: not t.date_end and (not employee or t.employee_id == employee)
                )[:1]
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
                MO (self.sequence) — consulted by Nordwire Chain Close to
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
            'sequence': self.sequence,
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
