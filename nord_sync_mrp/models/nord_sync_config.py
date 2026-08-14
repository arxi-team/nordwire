# -*- coding: utf-8 -*-
from odoo import api, models


class NordSyncConfig(models.Model):
    """Registers mrp.production as a Nord Sync Source — consumed by the
    install wizard's Job Stages & Mapping step and by nord_sync.state.mapping's
    source_model/source_value Selections. _inherit chain, same shape as the
    Core's _apply_nord_sync_entry override in nordos_nord_sync_core_mrp.
    """
    _inherit = 'nord_sync.config'

    @api.model
    def _nord_sync_available_native_sources(self):
        sources = super()._nord_sync_available_native_sources()
        return sources + [{
            'source_model': 'mrp.production',
            'source_field': 'state',
            'label': 'Manufacturing Orders',
        }]
