# -*- coding: utf-8 -*-
from odoo import api, models


class NordSyncConfig(models.Model):
    """Registers purchase.order as a Nord Sync Source — consumed by the
    install wizard's Job Stages & Mapping step and by nord_sync.state.mapping's
    source_model/source_value Selections. _inherit chain, same shape as
    nord_sync_mrp's own registration.
    """
    _inherit = 'nord_sync.config'

    @api.model
    def _nord_sync_available_native_sources(self):
        sources = super()._nord_sync_available_native_sources()
        return sources + [{
            'source_model': 'purchase.order',
            'source_field': 'state',
            'label': 'Purchase Orders',
            # Only the unambiguous transitions default — every other native
            # state still gets its own row in the wizard, just with no
            # default filled in (the client decides).
            'default_target_state_by_value': {'purchase': 'open', 'cancel': 'cancelled'},
        }]
