# -*- coding: utf-8 -*-
from odoo import api, models


class StockMove(models.Model):
    """Production Bridge: a move tied to an MO (raw material consumed, or
    finished product/byproduct produced) is a child of mrp.production —
    editing it never calls write() on the MO, so it notifies via the
    related production(s) instead, same reasoning as mrp_bom.py's
    MrpBomLine/MrpRoutingWorkcenter notifying via bom_id. Pushes a full
    snapshot of the MO's current move_raw_ids/move_finished_ids every
    time, not just the line that changed — same posture as the BOM Bridge.

    Moves unrelated to any MO (regular warehouse transfers, deliveries,
    …) never notify — nothing on the Core cares about those.
    """
    _inherit = 'stock.move'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._nord_sync_related_productions()._nord_sync_notify_moves()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._nord_sync_related_productions()._nord_sync_notify_moves()
        return result

    def unlink(self):
        productions = self._nord_sync_related_productions()
        result = super().unlink()
        productions._nord_sync_notify_moves()
        return result

    def _nord_sync_related_productions(self):
        """No state filter here — action_confirm() generates move_raw_ids/
        move_finished_ids while the MO is technically still draft, then
        flips its own state after, so filtering on production.state at
        move-creation time would race and drop the very push that matters.
        A push for an MO the Core hasn't turned into a job yet (still
        genuinely draft, never confirmed) is harmless noise, same
        resilience posture as everywhere else in this bridge — the Core
        just logs "job not found" and skips it.
        """
        return self.mapped('raw_material_production_id') | self.mapped('production_id')
