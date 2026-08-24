# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    """Nord Sync Source for stock.picking — same minimal shape as
    maintenance.request (nord_sync_maintenance): create-only Automation Rule, no product/
    declaration/result push, own _nord_sync_payload only (the create/enqueue
    plumbing is nord_sync.notify.mixin, shared by every source). `operation_type`
    in the payload is what tells the Core which nord.job.type to use — never
    hardcoded Core-side.
    """
    _inherit = ['stock.picking', 'nord_sync.notify.mixin']

    def _nord_sync_payload(self):
        """Payload sent to the Core when this picking is created.

        Keys:
            name (str): the picking's display name.
            operation_type (str): always 'inventory' — tells the Core which
                nord.job.type to use.
        """
        self.ensure_one()
        return {
            'name': self.name,
            'operation_type': 'inventory',
        }
