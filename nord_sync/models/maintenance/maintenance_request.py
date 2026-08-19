# -*- coding: utf-8 -*-
from odoo import models


class MaintenanceRequest(models.Model):
    """A second source model for the Nord Sync bridge, proving the
    dispatcher is genuinely generic: this model only needs its own notify/
    payload methods and an Automation Rule (data/nord_sync_automation.xml),
    same shape as mrp.production, nothing shared touched. `operation_type`
    in the payload below is what tells the
    Core which nord.job.type to use (production/purchase/sale/maintenance/
    inventory) — the Core never hardcodes "maintenance.request → maintenance"
    itself, so a future third source model can declare whichever type fits
    without touching Core code either.

    Unlike mrp.production, there's no draft/confirmed state to gate on — a
    maintenance request is actionable the moment it's created (no separate
    "confirm" step in the base `maintenance` module), so its Automation Rule
    triggers on_create rather than a state transition.
    """
    _inherit = 'maintenance.request'

    def _nord_sync_notify(self, operation):
        for record in self:
            config = self.env['nord_sync.config'].sudo()._get_for_company(record.company_id)
            if not config or not config.enabled or not config._is_source_enabled('maintenance.request'):
                continue
            config._enqueue_and_notify(
                'maintenance.request', record.id, operation, record._nord_sync_payload(),
            )

    def _nord_sync_payload(self):
        self.ensure_one()
        return {
            'name': self.name,
            'equipment': self.equipment_id.name or False,
            'operation_type': 'maintenance',
        }
