# -*- coding: utf-8 -*-
from odoo import models


class SaleOrder(models.Model):
    """Nord Sync Source for sale.order — same minimal shape as
    maintenance.request (nord_sync_maintenance): create-only Automation Rule, no product/
    declaration/result push, own _nord_sync_payload only (the create/enqueue
    plumbing is nord_sync.notify.mixin, shared by every source). `operation_type`
    in the payload is what tells the Core which nord.job.type to use — never
    hardcoded Core-side.
    """
    _inherit = ['sale.order', 'nord_sync.notify.mixin']

    def _nord_sync_payload(self):
        """Payload sent to the Core when this sale order is created.

        name comes from _nord_sync_configurable_payload(), per-company
        selectable (default: on, unchanged behavior). operation_type stays
        hardcoded — it's a constant, not a field read.

        Keys:
            operation_type (str): always 'sale' — tells the Core which
                nord.job.type to use.
        """
        self.ensure_one()
        return {
            **self._nord_sync_configurable_payload(),
            'operation_type': 'sale',
        }
