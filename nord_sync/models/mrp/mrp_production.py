# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import fields, models

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    """Source model for the Nord Sync bridge's MO channel.

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

    def _nord_sync_payload(self):
        """Business payload for this MO, captured at enqueue time.

        Product name/UoM/internal reference only — never BOM components/
        quantities inline, those are explicitly not replicated into this
        payload. bom_source_res_id is just a reference to the mrp.bom
        actually used for this MO, not its contents — the Core resolves the already-synced
        nord.bom by source reference and loads it, same distinction as
        nord_sync_source_res_id everywhere else in this bridge.

        Keys:
            name (str): the MO's display name.
            product_qty (float): the quantity to produce.
            state (str): the MO's own mrp.production state.
            operation_type (str): always 'production' — tells the Core which
                nord.job.type to use.
            bom_source_res_id (int or False): the client's own mrp.bom id
                actually used, False if none.
            log_note (str or False): the MO's own log note, False if unset.
            product (dict): {name, default_code, uom} snapshot of the
                product being produced.
        """
        self.ensure_one()
        product = self.product_id
        return {
            'name': self.name,
            'product_qty': self.product_qty,
            'state': self.state,
            'operation_type': 'production',
            'bom_source_res_id': self.bom_id.id or False,
            'log_note': self.log_note or False,
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
        (Odoo's own native quantity-loss ledger) left in draft, not
        auto-validated — a human confirms the actual scrap before it moves
        real stock, same caution as every other integration that touches
        inventory this way. They also count toward qty_producing (see
        below) — Odoo's button_mark_done() only completes on its own when
        the quantity being marked as produced covers the full plan;
        production+scrap+not_pass is what was actually processed, even
        though only the production share ends up as usable output.
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
                counted into qty_producing so button_mark_done() sees the
                full plan as accounted for, then becomes its own draft
                stock.scrap record when non-zero.
            not_pass_qty (float, optional): quantity rejected on quality
                check, default 0.0 — same treatment as scrap_qty, its own
                draft stock.scrap record when non-zero, plus a
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
                start_date, end_date}], logged as real
                mrp.workcenter.productivity entries.
        """
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            message = f'Nord Sync: result received but the MO was already "{self.state}" — ignored.'
            self.message_post(body=message)
            return False, message

        # Stock can have arrived since this MO's components were last
        # checked — re-try reservation right before closing rather than
        # trusting a stale state, same reasoning a human would apply
        # before manually confirming.
        self.action_assign()
        self._nord_sync_log_work_sessions(work_sessions or [])

        try:
            # The planned quantity (product_qty) is what Odoo checks
            # button_mark_done() against to decide whether to block on its
            # own backorder wizard — qty_produced alone under-reports how
            # much was actually processed whenever scrap/not_pass is
            # nonzero (a declaration ledger where production+scrap+not_pass
            # sums to what was planned, real bug found live: 2 good + 0.7
            # not_pass + 0.3 scrap out of 3 planned left qty_producing=2,
            # Odoo saw 1 unit "missing" against the plan, and silently
            # blocked on a backorder decision no one was there to answer).
            # scrap_qty/not_pass_qty aren't separately reserved/produced
            # moves of their own — they're a breakdown of the same
            # qty_producing, backed out again right after via the draft
            # stock.scrap records below.
            self.qty_producing = qty_produced + scrap_qty + not_pass_qty
            result = self.button_mark_done()
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
                # (backorder, lot/serial) is a real business decision, left
                # for a human — falls through to the generic blocked message.
                self._nord_sync_set_raw_move_quantities(materials or [])
                result = self.with_context(skip_consumption=True).button_mark_done()
        except Exception as exc:
            message = f'Nord Sync: failed to apply the result ({exc}).'
            _logger.warning('nord_sync: failed to apply result to MO %s: %s', self.id, exc)
            self._nord_sync_notify_result_failure(message)
            return False, message

        if result is not True:
            message = self._nord_sync_result_blocked_message()
            self._nord_sync_notify_result_failure(message)
            return False, message

        self._nord_sync_create_scrap(scrap_qty, 'Nord Sync: scrap')
        self._nord_sync_create_scrap(not_pass_qty, 'Nord Sync: quality reject (not pass)')
        self._nord_sync_log_quality_loss(not_pass_qty)

        self.message_post(
            body=f'Nord Sync: result applied — {qty_produced} {self.product_uom_id.name} produced.',
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
            return False, f'Production already {self.state}, event ignored.'
        try:
            self.action_cancel()
        except Exception as exc:
            return False, str(exc)
        return True, 'ok'

    def _nord_sync_log_work_sessions(self, work_sessions):
        """Creates one real mrp.workcenter.productivity entry per Core
        session, on the matching workorder (found by source reference) —
        see _nord_sync_apply_result's docstring for why. Silently skips a
        session whose workorder isn't found (ordering hazard, same
        resilience posture as the rest of this bridge) or whose dates are
        missing.
        """
        self.ensure_one()
        if not work_sessions:
            return
        loss = self.env['mrp.workcenter.productivity.loss'].sudo().search(
            [('loss_type', '=', 'productive')], limit=1,
        )
        if not loss:
            return
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
            self.env['mrp.workcenter.productivity'].sudo().create({
                'workorder_id': workorder.id,
                'workcenter_id': workorder.workcenter_id.id,
                'description': f"Nord Sync: real session ({employee.name if employee else workorder.workcenter_id.name})",
                'loss_id': loss.id,
                'date_start': session['start_date'],
                'date_end': session['end_date'],
                'user_id': self.env.user.id,
                'company_id': workorder.company_id.id,
                'employee_id': employee.id if employee else False,
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
        self.ensure_one()
        if not quantity:
            return
        self.env['stock.scrap'].sudo().create({
            'product_id': self.product_id.id,
            'production_id': self.id,
            'scrap_qty': quantity,
            'company_id': self.company_id.id,
            'origin': reason,
        })

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
            'description': f'Nord Sync: quality reject ({not_pass_qty} {self.product_uom_id.name})',
            'loss_id': loss.id,
            'date_start': date_end - timedelta(minutes=duration_minutes),
            'date_end': date_end,
            'user_id': self.env.user.id,
            'company_id': workorder.company_id.id,
        })

    def _nord_sync_result_blocked_message(self):
        """Distinguishes *why* button_mark_done() didn't complete, checked
        right after action_assign() already had its chance to reserve
        whatever's now available — a raw material still short at this
        point is a real, specific, actionable blocker (restock it, don't
        just "confirm manually"); anything else (lot/serial, backorder,
        an unrelated wizard) gets the same generic message as before.
        """
        self.ensure_one()
        short_moves = self.move_raw_ids.filtered(
            lambda m: m.state not in ('done', 'cancel') and m.product_uom_qty > m.quantity
        )
        if short_moves:
            names = ', '.join(short_moves.mapped('product_id.display_name'))
            return (
                f'Nord Sync: result received, but there is not enough stock to consume '
                f'{names} — the MO could not close automatically. It will need to be '
                'confirmed manually once stock is available.'
            )
        return (
            'Nord Sync: result received, but the MO needs manual confirmation '
            '(lot/serial, consumed quantity, or backorder) before it can close on its own.'
        )

    def _nord_sync_notify_result_failure(self, message):
        self.ensure_one()
        self.message_post(body=message)
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary='Nord Sync: result not applied automatically',
            note=message,
            user_id=self.user_id.id or self.env.user.id,
        )

