# -*- coding: utf-8 -*-
from odoo import models

# mrp.production/mrp.production.moves both resolve to the MO's own id (see
# mrp_production.py's _nord_sync_notify/_nord_sync_notify_moves) — already
# their own owner, same as the base default, listed here only so the mapping
# below is a complete picture of the whole mrp.production "family".
_DIRECT_MODELS = ('mrp.production', 'mrp.production.moves')

# No MO of their own — a work center/BOM/employee is a catalog entry, not an
# instance of one specific MO, so there's no owning mrp.production to
# redirect to (they resolve to themselves, same as the base default) — only
# hidden from the friendly failure surfaces: a work center or BOM is shared
# across every MO that uses it, not scoped to one, so surfacing it there the
# same way as a real MO's own failure would mislead a shop-floor user about
# which order actually needs attention.
_HIDDEN_MODELS = ('mrp.bom', 'mrp.workcenter', 'hr.employee')


class NordSyncQueueMrp(models.Model):
    _inherit = 'nord.sync.queue'

    def _nord_sync_resolve_owner(self, res_model, res_id, data):
        if res_model in _DIRECT_MODELS:
            return ('mrp.production', res_id)
        if res_model in ('mrp.workorder', 'quality.check'):
            # data's own snapshot, not a live browse() of the record — same
            # reasoning as everywhere else this bridge reads a _res_id
            # reference from data instead of re-resolving a record that may
            # since have been deleted. quality.check carries the same
            # production_source_res_id as mrp.workorder (see
            # _apply_nord_sync_quality_check on the Core) — same redirect.
            production_id = (data or {}).get('production_source_res_id')
            if production_id:
                return ('mrp.production', production_id)
        return super()._nord_sync_resolve_owner(res_model, res_id, data)

    def _nord_sync_hidden_owner_models(self):
        return super()._nord_sync_hidden_owner_models() + _HIDDEN_MODELS
