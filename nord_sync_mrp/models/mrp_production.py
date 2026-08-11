# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    """Source model for the Nord Sync bridge's MO channel.

    No create/write/unlink override here — the trigger criterion is
    configurable: `_nord_sync_notify` is called from the native Automation
    Rules in data/nord_sync_automation.xml instead (a "MO confirmed"
    state-transition rule + an unconditional "MO deleted" rule),
    editable/duplicable by the client afterwards (Settings > Technical >
    Automation Rules) without touching code, e.g. narrowing "Apply on" to a
    tag/warehouse/category.
    """
    _inherit = 'mrp.production'

    def _nord_sync_notify(self, operation):
        for record in self:
            config = self.env['nord_sync.config'].sudo()._get_for_company(record.company_id)
            if not config or not config.enabled:
                continue
            config._enqueue_and_notify('mrp.production', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        """Business payload for this MO, captured at enqueue time.

        Product name/UoM/internal reference only — never BOM components/
        quantities inline, those are explicitly not replicated into this
        payload. bom_source_res_id is just a reference to the mrp.bom
        actually used for this MO, not its contents — the Core resolves the already-synced
        nord.bom by source reference and loads it, same distinction as
        nord_sync_source_res_id everywhere else in this bridge.
        """
        self.ensure_one()
        product = self.product_id
        return {
            'name': self.name,
            'product_qty': self.product_qty,
            'state': self.state,
            'operation_type': 'production',
            'bom_source_res_id': self.bom_id.id or False,
            'product': {
                'name': product.name,
                'default_code': product.default_code or False,
                'uom': product.uom_id.name,
            },
        }

    def _nord_sync_apply_result(self, qty_produced):
        """Applies a finished Nord job's result via the standard MRP flow —
        the real value is always recorded, even if it differs from what was expected (no validation
        against the original quantity). A state that's already terminal
        (done/cancel) is a benign no-op (duplicate delivery, or the MO moved on
        client-side before the Core's result arrived) — logged, not alarmed.
        Anything else that stops the standard flow (missing lot/serial,
        consumption/backorder wizard, any other error) is a real failure: never
        silent, chatter + an activity for the MO's responsible user.
        """
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            message = f'Nord Sync: result received but the MO was already "{self.state}" — ignored.'
            self.message_post(body=message)
            return False, message

        try:
            self.qty_producing = qty_produced
            result = self.button_mark_done()
        except Exception as exc:
            message = f'Nord Sync: failed to apply the result ({exc}).'
            _logger.warning('nord_sync: failed to apply result to MO %s: %s', self.id, exc)
            self._nord_sync_notify_result_failure(message)
            return False, message

        if result is not True:
            message = (
                'Nord Sync: result received, but the MO needs manual confirmation '
                '(lot/serial, consumed quantity, or backorder) before it can close on its own.'
            )
            self._nord_sync_notify_result_failure(message)
            return False, message

        self.message_post(
            body=f'Nord Sync: result applied — {qty_produced} {self.product_uom_id.name} produced.',
        )
        return True, 'ok'

    def _nord_sync_notify_result_failure(self, message):
        self.ensure_one()
        self.message_post(body=message)
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary='Nord Sync: result not applied automatically',
            note=message,
            user_id=self.user_id.id or self.env.user.id,
        )
