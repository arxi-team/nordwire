# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    """Result side of the Timesheet Bridge — never authored by this
    client (a real work session only exists on the Core, via NordGo), only
    the result (duration) flows back here on session close.
    """
    _inherit = 'mrp.workorder'

    def _nord_sync_apply_result(self, duration_hours):
        """Adds a closed Nord work session's duration to this workorder's
        own duration (its inverse setter manages the underlying time_ids,
        same "standard flow" spirit as mrp.production._nord_sync_apply_result
        using qty_producing/button_mark_done instead of writing raw fields).
        Additive, not a plain overwrite — more than one Nord session can
        close against the same workorder over time (known, accepted gap
        when the same operation repeats on the same MO and both sessions
        land on the same workorder record — this still adds up correctly
        session by session either way).
        """
        self.ensure_one()
        try:
            # mrp.workorder.duration is in minutes; the Core sends hours.
            self.duration = self.duration + (duration_hours * 60)
        except Exception as exc:
            message = f'Nord Sync: failed to apply work session duration ({exc}).'
            _logger.warning('nord_sync: failed to apply workorder result to %s: %s', self.id, exc)
            self.production_id.message_post(body=message)
            return False, message

        self.production_id.message_post(
            body=f'Nord Sync: {duration_hours}h work session applied to "{self.name}" ({self.workcenter_id.name}).',
        )
        return True, 'ok'
