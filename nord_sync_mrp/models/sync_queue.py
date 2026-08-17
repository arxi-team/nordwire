# -*- coding: utf-8 -*-
from odoo import models

# mrp.production/mrp.production.moves both enqueue with res_id = the MO's own
# id (see mrp_production.py's _nord_sync_notify/_nord_sync_notify_moves) —
# already their own owner, same as the base default, listed here only so the
# mapping below is a complete picture of the whole mrp.production "family".
_DIRECT_MODELS = ('mrp.production', 'mrp.production.moves')

# No MO of their own — a work center/BOM/employee is a catalog entry, not an
# instance of one specific MO, so there's no owning mrp.production to
# redirect to. Hidden rather than shown as themselves (the base default):
# see ADR 0011, a deliberate call to keep the user-facing surfaces scoped to
# what a shop-floor user actually works from.
_HIDDEN_MODELS = ('mrp.bom', 'mrp.workcenter', 'hr.employee')


class NordSyncQueueMrp(models.Model):
    _inherit = 'nord.sync.queue'

    def _nord_sync_visible_owner(self):
        self.ensure_one()
        if self.res_model in _HIDDEN_MODELS:
            return None
        if self.res_model in _DIRECT_MODELS:
            return ('mrp.production', self.res_id)
        if self.res_model == 'mrp.workorder':
            # Payload's own snapshot, not a live browse() of the workorder —
            # same reasoning as everywhere else this bridge reads _res_id
            # references from data instead of re-resolving a record that may
            # since have been deleted.
            production_id = (self.data or {}).get('production_source_res_id')
            return ('mrp.production', production_id) if production_id else None
        return super()._nord_sync_visible_owner()
