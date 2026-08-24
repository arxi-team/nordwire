# -*- coding: utf-8 -*-
from odoo import models


class MaintenanceRequest(models.Model):
    """A second source model for the Nord Sync bridge, proving the
    dispatcher is genuinely generic: this model only needs its own
    _nord_sync_payload and an Automation Rule (data/nord_sync_automation.xml)
    — the create/enqueue plumbing is nord_sync.notify.mixin, shared by
    every source. `operation_type` in the payload below is what tells the
    Core which nord.job.type to use (production/purchase/sale/maintenance/
    inventory) — the Core never hardcodes "maintenance.request → maintenance"
    itself, so a future source model can declare whichever type fits without
    touching Core code either.

    Unlike mrp.production, there's no draft/confirmed state to gate on — a
    maintenance request is actionable the moment it's created (no separate
    "confirm" step in the base `maintenance` module), so its Automation Rule
    triggers on_create rather than a state transition.
    """
    _inherit = ['maintenance.request', 'nord_sync.notify.mixin']

    def _nord_sync_payload(self):
        """Payload sent to the Core when this maintenance request is created.

        Keys:
            name (str): the maintenance request's display name.
            equipment (str or False): the linked equipment's name, False if none.
            operation_type (str): always 'maintenance' — tells the Core which
                nord.job.type to use.
        """
        self.ensure_one()
        return {
            'name': self.name,
            'equipment': self.equipment_id.name or False,
            'operation_type': 'maintenance',
        }
