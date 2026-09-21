# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    """Source model for the Nordwire bridge's MO channel.

    No create/write/unlink override here — the trigger criterion is
    configurable: `_nord_sync_notify` is called from the native Automation
    Rules in data/nord_sync_automation.xml instead (a "MO confirmed"
    state-transition rule + an unconditional "MO deleted" rule),
    editable/duplicable by the client afterwards (Settings > Technical >
    Automation Rules) without touching code, e.g. narrowing "Apply on" to a
    tag/warehouse/category. The create/enqueue plumbing itself is
    nord_sync.notify.mixin, shared by every source.
    """
    _inherit = ['mrp.production', 'nord_sync.notify.mixin']

    def action_start(self):
        """Interrupts a human-clicked Start on the MO header the same way
        mrp.workorder.button_start does (nord_sync.workorder.start.wizard,
        see mrp_workorder.py) — reuses that same wizard, pointed at this
        production's own next-up workorder, so confirming/changing its
        work center behaves identically regardless of which Start button
        the human actually clicked. A routing-less production (no open
        workorder_ids) has no work center to confirm, so it always falls
        through to super() untouched.
        """
        self.ensure_one()
        if self.state == 'confirmed' and not self.env.context.get('nord_sync_skip_confirm'):
            workorder = self.workorder_ids.filtered(lambda wo: wo.state not in ('done', 'cancel'))[:1]
            if workorder and workorder.workcenter_id.nord_sync_control_mode != 'nord':
                config = self.env['nord_sync.config'].sudo()._get_for_company(self.company_id)
                if config and config.nord_sync_confirm_workcenter_on_start:
                    return {
                        'type': 'ir.actions.act_window',
                        'res_model': 'nord_sync.workorder.start.wizard',
                        'view_mode': 'form',
                        'target': 'new',
                        'context': {
                            'default_workorder_id': workorder.id,
                            'default_production_id': self.id,
                        },
                    }
        return super().action_start()

    def _nord_sync_payload(self):
        """Business payload for this MO, captured at enqueue time.

        Product name/UoM/internal reference only — never BOM components/
        quantities inline, those are explicitly not replicated into this
        payload. bom_source_res_id is just a reference to the mrp.bom
        actually used for this MO, not its contents — the Core resolves the already-synced
        nord.bom by source reference and loads it, same distinction as
        nord_sync_source_res_id everywhere else in this bridge.

        name/product_qty/state/log_note are no longer hardcoded here — they
        come from _nord_sync_configurable_payload(), per-company selectable
        (default: all four, unchanged behavior). operation_type/
        bom_source_res_id/product below can't move there: operation_type is
        a constant (not a field read at all), bom_source_res_id and product
        are a relational reference and a snapshot of a *different* record
        (self.product_id, not self) — neither is "read this field off self".

        Keys:
            operation_type (str): always 'production' — tells the Core which
                nord.job.type to use.
            bom_source_res_id (int or False): the client's own mrp.bom id
                actually used, False if none.
            product (dict): {name, default_code, uom} snapshot of the
                product being produced.
        """
        self.ensure_one()
        product = self.product_id
        return {
            **self._nord_sync_configurable_payload(),
            'operation_type': 'production',
            'bom_source_res_id': self.bom_id.id or False,
            'product': {
                'name': product.name,
                'default_code': product.default_code or False,
                'uom': product.uom_id.name,
            },
        }

    def _nord_sync_notify_moves(self):
        for record in self:
            config = self.env['nord_sync.config'].sudo()._get_for_company(record.company_id)
            if not config or not config.enabled or not config._is_source_enabled('mrp.production'):
                continue
            config._enqueue_and_notify('mrp.production.moves', record.id, 'write', record._nord_sync_moves_payload())

    def _nord_sync_moves_payload(self):
        """This MO's real components/outputs (move_raw_ids/move_finished_ids)
        — distinct from _nord_sync_payload above, which is the MO's own
        header fields. move_finished_ids covers the main product and any
        byproducts alike, no distinction — same "just a flat list of
        outputs" shape as mrp_bom.py's own product_lines.

        Keys:
            materials (list[dict]): [{product: <product payload>, quantity,
                workcenter_source_res_id}], one per move_raw_ids — the
                workcenter reference is False when the move isn't tied to
                any operation.
            finished_products (list[dict]): [{product: <product payload>,
                quantity}], one per move_finished_ids (main product and any
                byproducts alike).
        """
        self.ensure_one()
        return {
            'materials': [
                {
                    'product': self._nord_sync_product_payload(move.product_id),
                    'quantity': move.product_uom_qty,
                    # Which operation/resource this material is consumed at —
                    # same reasoning as mrp_bom.py's own bom_line_ids payload.
                    'workcenter_source_res_id': move.operation_id.workcenter_id.id or False,
                }
                for move in self.move_raw_ids
            ],
            'finished_products': [
                {
                    'product': self._nord_sync_product_payload(move.product_id),
                    'quantity': move.product_uom_qty,
                }
                for move in self.move_finished_ids
            ],
        }

    def _nord_sync_product_payload(self, product):
        """Snapshot of a product, embedded wherever this bridge references
        one, so the Core can lazily get-or-create the matching
        nord.product itself instead of requiring it to already exist.

        Keys:
            name (str): the product's display name.
            default_code (str or False): the product's internal reference,
                False if unset.
            uom (str): the product's unit of measure name.
        """
        return {
            'name': product.name,
            'default_code': product.default_code or False,
            'uom': product.uom_id.name,
        }

    def _nord_sync_apply_result(self, qty_produced, scrap_qty=0.0, not_pass_qty=0.0, materials=None, work_sessions=None):
        """Applies a finished Nord job's result via the standard MRP flow —
        the real value is always recorded, even if it differs from what was expected (no validation
        against the original quantity). A state that's already terminal
        (done/cancel) is a benign no-op (duplicate delivery, or the MO moved on
        client-side before the Core's result arrived) — logged, not alarmed.
        Anything else that stops the standard flow (missing lot/serial,
        consumption/backorder wizard, any other error) is a real failure: never
        silent, chatter + an activity for the MO's responsible user.

        scrap_qty/not_pass_qty each become their own stock.scrap record
        (Odoo's own native quantity-loss ledger), auto-validated right
        away — no human in this loop to confirm it by hand, same posture
        as the rest of this autonomous flow. Neither counts toward
        qty_producing (only qty_produced does — real bug found live: summing
        them in let a plan of 10 close as "fully produced" on 6 good + 4
        scrap, moving 10 units of usable stock for only 6 real ones).
        Whatever's short of product_qty becomes a real backorder MO
        instead (skip_backorder + mo_ids_to_backorder, see below).
        not_pass_qty additionally logs a mrp.workcenter.productivity time
        entry (loss_type='quality') — see _nord_sync_log_quality_loss —
        because Odoo's own OEE is computed purely from those time logs,
        never from stock.scrap quantities; scrap_qty gets no such entry,
        physical waste isn't a quality-inspection stoppage.

        materials is the Core's real per-product consumed quantity
        (job.final_product_ids as it stood at close) — can differ from
        this MO's own move_raw_ids.product_uom_qty (e.g. only 1 of the 2
        reserved units of a component actually got used). Matched the same
        way _get_or_create_nord_sync_product resolves products elsewhere in
        this bridge: default_code, else name. A raw move with no matching
        entry falls back to its own reserved quantity — unchanged behavior
        for materials the Core didn't report anything about.

        work_sessions is every real work session the Core recorded for
        this job (nord.timesheet, one per resource), keyed to a client
        mrp.workorder/hr.employee by source reference. Logged as real
        mrp.workcenter.productivity entries before button_mark_done() —
        without this, a workorder with no time log gets one auto-invented
        by Odoo itself using "now minus duration_expected" as a guess,
        wrong whenever the real session was shorter/longer than planned.

        Keys:
            qty_produced (float): quantity to record as good, usable
                output.
            scrap_qty (float, optional): quantity to scrap, default 0.0 —
                never counted into qty_producing, becomes its own
                auto-validated stock.scrap record when non-zero.
            not_pass_qty (float, optional): quantity rejected on quality
                check, default 0.0 — same treatment as scrap_qty, its own
                auto-validated stock.scrap record when non-zero, plus a
                mrp.workcenter.productivity 'quality' time entry (see
                _nord_sync_log_quality_loss) so it counts toward Odoo's
                own OEE.
            materials (list[dict], optional): the Core's real per-product
                consumed quantity, default None (treated as empty) —
                [{product: {name, default_code}, quantity}], only read when
                the standard flow hits the Consumption Warning.
            work_sessions (list[dict], optional): every real work session
                the Core recorded for this job, default None (treated as
                empty) — [{workorder_source_res_id, employee_source_res_id,
                start_date, end_date, nord_timesheet_id, energy_kwh_used,
                reason_name, reason_type}], logged as real
                mrp.workcenter.productivity entries.
        """
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            message = f'Nordwire: result received but the MO was already "{self.state}" — ignored.'
            self.message_post(body=message)
            return False, message

        # Stock can have arrived since this MO's components were last
        # checked — re-try reservation right before closing rather than
        # trusting a stale state, same reasoning a human would apply
        # before manually confirming.
        self.action_assign()
        self._nord_sync_log_work_sessions(work_sessions or [])

        try:
            # Wrapped in its own savepoint: button_mark_done() can fail on a
            # real DB constraint (e.g. mrp_production_qty_positive on a
            # zero-qty backorder), which aborts the whole Postgres
            # transaction. Without a savepoint to roll back to, the except
            # branch's own recovery below (message_post + activity_schedule)
            # would run on that same aborted transaction and fail too,
            # turning a caught error into an uncaught 500 with zero
            # chatter/activity anywhere (real bug, found live).
            with self.env.cr.savepoint():
                # qty_producing is only the good/usable output — scrap and
                # not_pass never counted as "produced" (real bug found live:
                # summing them in here let 6 good + 4 scrap satisfy a plan of
                # 10, moving 10 units of the finished product into stock when
                # only 6 were actually good). Whatever's short of product_qty
                # becomes a real backorder MO instead, via skip_backorder +
                # mo_ids_to_backorder=self.ids — same as ticking "to backorder"
                # on the wizard's own Confirm button, except no human is there
                # to click it. The backorder MO is created already
                # state='confirmed', which nord_sync_automation.xml's
                # on_create_or_write rule still notifies Cloud for, same as a
                # human-confirmed MO would.
                #
                # mo_ids_to_backorder is only added when there's an actual
                # shortfall (real bug, found live: passing it unconditionally
                # made _split_productions() try to create a backorder even when
                # qty_produced == product_qty, with product_qty=0 — hit the
                # mrp_production_qty_positive DB constraint and 500'd the whole
                # request, silently dropping the Result Push).
                self.qty_producing = qty_produced
                mo = self.with_context(skip_backorder=True)
                if not self.product_uom_id.is_zero(self._get_quantity_to_backorder()):
                    mo = mo.with_context(mo_ids_to_backorder=self.ids)
                result = mo.button_mark_done()
                if isinstance(result, dict) and result.get('res_model') == 'mrp.consumption.warning':
                    # Odoo's own "consumed qty differs from the BOM's expected
                    # qty, are you sure?" warning — this flow already knows the
                    # real declared quantity (nord.declaration is the ledger a
                    # human would otherwise be asked to eyeball here), so
                    # auto-confirm it exactly like the wizard's own "Set
                    # Quantities & Confirm" button would (action_confirm() alone
                    # is the plain "Confirm" button — it trusts move.quantity as
                    # already set, which our automated flow never touches, so it
                    # left every raw move at quantity=0/picked=False and Odoo
                    # cancelled them instead of consuming anything — real bug,
                    # caught by checking the MO's Components tab after a close).
                    # Any *other* wizard button_mark_done() might still return
                    # (lot/serial) is a real business decision, left for a
                    # human — falls through to the generic blocked message.
                    self._nord_sync_set_raw_move_quantities(materials or [])
                    result = mo.with_context(skip_consumption=True).button_mark_done()
                if isinstance(result, dict) and result.get('res_model') == 'mrp.production':
                    # button_mark_done() already wrote state='done' on this MO and
                    # split the backorder off (both happen unconditionally once
                    # pre_button_mark_done() clears, before this return) — this
                    # dict is only its own "go look at the new backorder" form
                    # navigation for a human, not a block. Real bug, found live:
                    # every backorder case was falling through to the generic
                    # blocked message below despite having actually finished,
                    # silently skipping scrap creation. mrp.action_assign_serial_numbers
                    # (the one real lot/serial block button_mark_done() can still
                    # return) is a different res_model, so this stays specific.
                    result = True
        except Exception as exc:
            _logger.warning('nord_sync: failed to apply result to MO %s: %s', self.id, exc)
            message = f'Nordwire: failed to apply the result. {self._nord_sync_friendly_error(exc)}'
            self._nord_sync_notify_result_failure(message)
            return False, message

        if result is not True:
            message = self._nord_sync_result_blocked_message()
            self._nord_sync_notify_result_failure(message)
            return False, message

        self._nord_sync_create_scrap(scrap_qty, 'Nordwire: scrap')
        self._nord_sync_create_scrap(not_pass_qty, 'Nordwire: quality reject (not pass)')
        self._nord_sync_log_quality_loss(not_pass_qty)

        self.message_post(
            body=f'Nordwire: result applied — {qty_produced} {self.product_uom_id.name} produced.',
        )
        return True, 'ok'

    def _nord_sync_apply_granular_event(self, event_type, payload):
        """The only granular event routed to the MO itself (not one of its
        workorders): a job cancelled on the Core, mirrored here as the
        standard MO cancellation — same as a human cancelling it by hand,
        no shortcut. Never raises, same best-effort posture as
        _nord_sync_apply_result above.

        Keys:
            event_type (str): only 'job_cancel' is recognized today, any
                other value is rejected.
            payload (dict): unused today, always {} for 'job_cancel'.
        """
        self.ensure_one()
        if event_type != 'job_cancel':
            return False, f'Unknown event_type: {event_type}'
        if self.state in ('done', 'cancel'):
            # Same fix as mrp.workorder._nord_sync_apply_granular_event: a
            # delayed job_cancel arriving after the MO already reached
            # done/cancel by another path is a moot no-op, not a failure --
            # False here made _cron_process_pending surface it as a Sync
            # Failures entry with nothing actually to retry or fix.
            return True, f'Production already {self.state}, event ignored.'
        try:
            self.action_cancel()
        except Exception as exc:
            _logger.warning('nord_sync: failed to cancel MO %s: %s', self.id, exc)
            return False, self._nord_sync_friendly_error(exc)
        return True, 'ok'

    def _nord_sync_friendly_error(self, exc):
        """Turns a caught exception into text safe to show a non-technical
        user in chatter, an activity, or a Core-side alert.

        Odoo's own UserError family (UserError itself, ValidationError,
        AccessError, MissingError, ...) is already written to be read by a
        human -- that is the entire point of raising one -- so it's shown
        as-is, unchanged: covers every raise this MO's own close can hit
        without needing this method to know about each one by name (a
        missing lot/serial, a duplicate serial already produced, a rounding
        precision mismatch, a negative quantity, a duplicate production
        reference, ...). Anything else is a lower-level failure never meant
        for a human eye -- typically a bare DB/psycopg2 error surfacing
        straight from a flush, which can carry a full row dump ("DETAIL:
        Failing row contains (...)"), meaningless and alarming to whoever
        reads it. The full exc is always logged server-side by the caller
        before this runs, so nothing is actually lost by hiding it here.
        Recognized shapes get a real explanation; anything unrecognized
        falls back to a generic message pointing at the server log.

        Keys:
            exc (Exception): the exception caught applying a Nordwire
                action to this MO.
        """
        if isinstance(exc, UserError):
            return str(exc)
        text = str(exc)
        if 'mrp_production_qty_positive' in text:
            return (
                'This production order cannot close with 0 units produced '
                'automatically — please confirm the quantity manually.'
            )
        return 'An unexpected error occurred — see the server log for details.'

    def _nord_sync_log_work_sessions(self, work_sessions):
        """Creates one real mrp.workcenter.productivity entry per Core
        session, on the matching workorder (found by source reference) —
        see _nord_sync_apply_result's docstring for why. Silently skips a
        session whose workorder isn't found (ordering hazard, same
        resilience posture as the rest of this bridge) or whose dates are
        missing.

        loss_id (required on mrp.workcenter.productivity) comes from the
        session's own nord.timesheet.reason_id when it already had one at
        push time (reason_name/reason_type present) — get-or-created by
        name, loss.type resolved from reason_type (the Core's own
        nord.reason.reason_type_id.name, matched case-insensitively
        against this client's own loss_type Selection — see
        mrp.workcenter.productivity.loss._nord_sync_get_or_create).
        Otherwise it's the shared "Undefined" placeholder, not the old
        blanket 'productive' default: an unclassified session shouldn't
        silently count as good time. A later correction
        (session_loss_justified, found by nord_sync_timesheet_id) rewrites
        this same row once a real justification exists.

        electric_consume comes straight from the session's own
        energy_kwh_used (nord.timesheet, Core-side B9 snapshot) —
        electric_consume_cost (mrp.workorder) derives from it here, same
        tariff already synced via res.company.
        """
        self.ensure_one()
        if not work_sessions:
            return
        Loss = self.env['mrp.workcenter.productivity.loss']
        for session in work_sessions:
            if not session.get('start_date') or not session.get('end_date'):
                continue
            workorder = self.workorder_ids.filtered(
                lambda wo, sid=session.get('workorder_source_res_id'): wo.id == sid
            )
            if not workorder:
                continue
            employee = False
            if session.get('employee_source_res_id'):
                employee = self.env['hr.employee'].sudo().browse(session['employee_source_res_id'])
                if not employee.exists():
                    employee = False
            if session.get('reason_name'):
                loss = Loss._nord_sync_get_or_create(
                    session['reason_name'], session.get('reason_type'),
                )
            else:
                loss = Loss._nord_sync_get_or_create_undefined()
            self.env['mrp.workcenter.productivity'].sudo().create({
                'workorder_id': workorder.id,
                'workcenter_id': workorder.workcenter_id.id,
                'description': f"Nordwire: real session ({employee.name if employee else workorder.workcenter_id.name})",
                'loss_id': loss.id,
                'date_start': session['start_date'],
                'date_end': session['end_date'],
                'user_id': self.env.user.id,
                'company_id': workorder.company_id.id,
                'employee_id': employee.id if employee else False,
                'nord_sync_timesheet_id': session.get('nord_timesheet_id') or False,
                'electric_consume': session.get('energy_kwh_used') or 0.0,
            })

    def _nord_sync_set_raw_move_quantities(self, materials):
        """Sets each open raw move's consumed quantity/picked flag from the
        Core's real per-product figures before re-confirming past the
        Consumption Warning — mirrors what that wizard's own "Set
        Quantities & Confirm" button does, except using the Core's real
        number instead of always re-deriving the BOM's expected one.

        A raw move whose product isn't in materials at all means the Core's
        final_product_ids genuinely has nothing to say about it — same
        "consume exactly this, don't re-derive from the BOM" contract
        _push_nord_sync_result's own docstring promises, so that's 0
        consumed, never a re-derived guess (real bug, caught live
        2026-08-20: this used to fall back to the move's full *reserved*
        quantity, so an operator removing a component's line on the Core
        because it genuinely wasn't used still got it fully consumed here
        instead). Under-consuming (a move stuck open, reservation freed) is
        the safe direction to fail in either case this fallback fires for —
        a real operator can notice and fix an unconsumed line; silent
        over-consumption corrupts the stock count with nothing to notice.
        """
        self.ensure_one()
        by_code = {m['product']['default_code']: m['quantity'] for m in materials if m['product'].get('default_code')}
        by_name = {m['product']['name']: m['quantity'] for m in materials if m['product'].get('name')}
        for move in self.move_raw_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            product = move.product_id
            if product.default_code in by_code:
                quantity = by_code[product.default_code]
            elif product.name in by_name:
                quantity = by_name[product.name]
            else:
                quantity = 0.0
            move.quantity = quantity
            move.picked = True

    def _nord_sync_create_scrap(self, quantity, reason):
        """Creates and immediately validates the scrap — no human in this
        autonomous loop to confirm it by hand. action_validate() itself
        never raises; when the scrap location doesn't have enough on hand
        to validate straight away it returns a forecast-wizard action
        instead, left in draft for manual follow-up (logged, not alarmed —
        same resilience posture as the rest of this bridge).
        """
        self.ensure_one()
        if not quantity:
            return
        scrap = self.env['stock.scrap'].sudo().create({
            'product_id': self.product_id.id,
            'production_id': self.id,
            'scrap_qty': quantity,
            'company_id': self.company_id.id,
            'origin': reason,
        })
        if scrap.action_validate() is not True:
            _logger.warning(
                'nord_sync: scrap %s for MO %s could not be auto-validated (not enough '
                'on hand at the scrap location) — left in draft for manual confirmation.',
                scrap.id, self.id,
            )

    def _nord_sync_log_quality_loss(self, not_pass_qty):
        """Logs not_pass_qty as a real mrp.workcenter.productivity time
        entry with loss_type='quality', so it counts in Odoo's own native
        OEE (mrp.workcenter.oee, computed purely from productivity time
        logs — a stock.scrap record alone, see _nord_sync_create_scrap
        above, is invisible to it). scrap_qty gets no equivalent entry:
        physical waste isn't a quality-inspection stoppage, only
        not_pass is.

        The "time lost" is estimated from the workorder's own planned
        cycle time (duration_expected / product_qty), same time-per-unit
        the BOM operation itself is built from — not an arbitrary number.

        ponytail: attributed to the MO's LAST real workorder only — a
        job-level not_pass_qty carries no per-workorder breakdown in the
        Result Push payload today, correct for the common single-operation
        case, an approximation for a multi-operation MO. Upgrade path: a
        per-workorder not_pass breakdown in the payload, if that's ever
        needed.
        """
        self.ensure_one()
        if not not_pass_qty or not self.product_qty:
            return
        workorder = self.workorder_ids[-1:]
        if not workorder:
            return
        loss = self.env['mrp.workcenter.productivity.loss'].sudo().search(
            [('loss_type', '=', 'quality')], limit=1,
        )
        if not loss:
            return
        duration_minutes = not_pass_qty * (workorder.duration_expected / self.product_qty)
        if duration_minutes <= 0:
            return
        date_end = fields.Datetime.now()
        self.env['mrp.workcenter.productivity'].sudo().create({
            'workorder_id': workorder.id,
            'workcenter_id': workorder.workcenter_id.id,
            'description': f'Nordwire: quality reject ({not_pass_qty} {self.product_uom_id.name})',
            'loss_id': loss.id,
            'date_start': date_end - timedelta(minutes=duration_minutes),
            'date_end': date_end,
            'user_id': self.env.user.id,
            'company_id': workorder.company_id.id,
        })

    def _nord_sync_result_blocked_message(self):
        """button_mark_done() returned instead of raising or fully closing —
        traced every non-True return in Odoo 19's own pre_button_mark_done()/
        button_mark_done() (mrp/models/mrp_production.py): the backorder-ask
        wizard can't reach here (skip_backorder=True above already empties
        _get_quantity_produced_issues()), the consumption-warning wizard is
        already handled above, and the one path left (action_generate_serial(),
        a finished good needing a lot/serial assigned) returns before any
        component is even touched — a genuine raw-material shortage never
        reaches this function at all, it raises instead (caught by the
        except Exception above). No specific-cause branch to make here.
        """
        self.ensure_one()
        return (
            'Nordwire: result received, but the MO needs manual confirmation '
            '(lot/serial, consumed quantity, or backorder) before it can close on its own.'
        )

    def _nord_sync_notify_result_failure(self, message):
        self.ensure_one()
        self.message_post(body=message)
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary='Nordwire: result not applied automatically',
            note=message,
            user_id=self.user_id.id or self.env.user.id,
        )

