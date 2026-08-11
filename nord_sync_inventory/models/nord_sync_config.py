# -*- coding: utf-8 -*-
from odoo import api, models


class NordSyncConfig(models.Model):
    """Registers stock.picking as a Nord Sync Source — consumed by the
    install wizard's Job Stages & Mapping step and by nord_sync.state.mapping's
    source_model/source_value Selections. _inherit chain, same shape as
    nord_sync_mrp's own registration.
    """
    _inherit = 'nord_sync.config'

    @api.model
    def _nord_sync_available_native_sources(self):
        sources = super()._nord_sync_available_native_sources()
        return sources + [{
            'source_model': 'stock.picking',
            'source_field': 'state',
            'label': 'Transfers',
            # Only 'cancel' is unambiguous here — unlike sale/purchase's own
            # single "confirmed" state, a transfer's 'confirmed'/'assigned'
            # are readiness states, not a clean 1:1 analogue for a job
            # starting, so left with no default (the client decides).
            'default_target_state_by_value': {'cancel': 'cancelled'},
        }]
