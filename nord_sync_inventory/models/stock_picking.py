# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    """Nordwire Source for stock.picking — same minimal shape as
    maintenance.request (nord_sync_maintenance): create-only Automation Rule, no product/
    declaration/result push, own _nord_sync_payload only (the create/enqueue
    plumbing is nord_sync.notify.mixin, shared by every source). `operation_type`
    in the payload is what tells the Core which nord.job.type to use — never
    hardcoded Core-side.
    """
    _inherit = ['stock.picking', 'nord_sync.notify.mixin']

    def _nord_sync_payload(self):
        """Payload sent to the Core when this picking is created.

        name comes from _nord_sync_configurable_payload(), per-company
        selectable (default: on, unchanged behavior). operation_type stays
        hardcoded — it's a constant, not a field read.

        Keys:
            operation_type (str): always 'inventory' — tells the Core which
                nord.job.type to use.
        """
        self.ensure_one()
        return {
            **self._nord_sync_configurable_payload(),
            'operation_type': 'inventory',
        }
