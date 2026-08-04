# -*- coding: utf-8 -*-
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 5


class MrpProduction(models.Model):
    """Phase 1 source model for the Nord Sync bridge.

    ponytail: the real nord_sync (client addon, not in this repo) triggers
    its outbound webhook via Odoo's native "Send Webhook Notification"
    Automation Rule (state='webhook' on ir.actions.server) — see
    nord-os/docs/nord_sync/ARCHITECTURE.md. Wiring that declaratively means
    guessing the auto-generated ir.model.fields xmlid for a field this
    module defines, which is brittle to get right without a live instance
    to check against. Since this module only exists to test the Cloud/Core
    side already built, a direct `requests.post` here is equivalent
    behaviour (same payload, same endpoint) and far more testable. Swap for
    the native automation action if a no-code, admin-editable trigger is
    wanted later.
    """
    _inherit = 'mrp.production'

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

    def _nord_sync_notify(self, operation):
        for record in self:
            company = record.company_id
            if not company.nord_sync_enabled:
                continue
            entry = self.env['nord.sync.queue'].sudo().create({
                'res_model': 'mrp.production',
                'res_id': record.id,
                'operation': operation,
                'company_id': company.id,
                'data': record._nord_sync_payload(),
            })
            sent = record._nord_sync_send_wake_webhook(company)
            if sent is not None:
                entry.status = 'sent' if sent else 'failed'

    def _nord_sync_payload(self):
        """Business payload for this MO, captured at enqueue time.

        Reference only (docs/plano_addon_odoo_cliente_producao.md §7, "Âmbito de
        dados"): product name/UoM/internal reference, never BOM components/
        quantities — those are explicitly not replicated to the Nord side.
        """
        self.ensure_one()
        product = self.product_id
        return {
            'name': self.name,
            'product_qty': self.product_qty,
            'state': self.state,
            'product': {
                'name': product.name,
                'default_code': product.default_code or False,
                'uom': product.uom_id.name,
            },
        }

    def _nord_sync_send_wake_webhook(self, company):
        """Returns None if skipped (not configured yet), True/False if attempted."""
        if not company.nord_sync_cloud_webhook_url or not company.nord_sync_company_uid:
            return None
        try:
            response = requests.post(
                company.nord_sync_cloud_webhook_url,
                json={'company_uid': company.nord_sync_company_uid},
                timeout=WEBHOOK_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except Exception as exc:
            _logger.warning('nord_sync: failed to notify Nord Cloud webhook: %s', exc)
            return False
        return True
