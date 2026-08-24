# -*- coding: utf-8 -*-
from odoo import models


class PurchaseOrder(models.Model):
    """Nord Sync Source for purchase.order — same minimal shape as
    maintenance.request (nord_sync_maintenance): create-only Automation Rule, no product/
    declaration/result push, own _nord_sync_payload only (the create/enqueue
    plumbing is nord_sync.notify.mixin, shared by every source). `operation_type`
    in the payload is what tells the Core which nord.job.type to use — never
    hardcoded Core-side.
    """
    _inherit = ['purchase.order', 'nord_sync.notify.mixin']

    def _nord_sync_payload(self):
        """Payload sent to the Core when this purchase order is created.

        Keys:
            name (str): the purchase order's display name.
            operation_type (str): always 'purchase' — tells the Core which
                nord.job.type to use.
        """
        self.ensure_one()
        return {
            'name': self.name,
            'operation_type': 'purchase',
        }
