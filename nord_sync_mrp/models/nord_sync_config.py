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
            # The two transitions the shipped Automation Rules send today
            # (data/nord_sync_automation.xml) — every other native state
            # still gets its own row in the wizard (the client decides, not
            # just for confirm/cancel), just with no default filled in.
            'default_target_state_by_value': {'confirmed': 'open', 'cancel': 'cancelled'},
        }]

    def _ensure_backward_compat_state_mapping(self):
        """'cancel' used to be a hardcoded string check on the Core, now
        it's a Nord Sync State Mapping lookup — without this row, a company
        that never configures one stops cancelling jobs on MO cancellation entirely.
        The install wizard covers brand new activations itself (Job Stages &
        Mapping step); this is the idempotent fallback for anything else
        that enables Nord Sync with mrp.production active but skips that
        step's defaults.
        """
        self.ensure_one()
        return self._ensure_state_mapping('mrp.production', 'cancel', target_state='cancelled')
