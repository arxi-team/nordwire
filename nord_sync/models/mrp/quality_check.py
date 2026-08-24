# -*- coding: utf-8 -*-
from odoo import api, models


class QualityCheck(models.Model):
    """Quality Check Bridge: a workorder's checklist items (Shop Floor
    instructions/pass-fail/measure/... steps) become the Core's own
    nord.tasks checklist on the matching job. Resolved to a job the same
    way the Workorder Bridge does — by the check's own production_id, a
    direct field on quality.check (mrp_workorder's own extension), no need
    to go through workorder_id first.

    Only workorder-tied checks are this bridge's concern — a check on a
    stock.picking's own quality point (no production_id at all) has no
    nord.job to attach to, so it's silently out of scope, same resilience
    posture as any other unrecognized/irrelevant record everywhere else in
    this bridge (see _nord_sync_should_notify below). A support model of
    the mrp.production source, not a toggle-able source of its own — see
    _nord_sync_source_key below.
    """
    _inherit = ['quality.check', 'nord_sync.notify.mixin']

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._nord_sync_notify('create')
        return records

    def write(self, vals):
        result = super().write(vals)
        self._nord_sync_notify('write')
        return result

    def unlink(self):
        self._nord_sync_notify('unlink')
        return super().unlink()

    def _nord_sync_should_notify(self):
        self.ensure_one()
        return bool(self.production_id)

    def _nord_sync_source_key(self):
        return 'mrp.production'

    def _nord_sync_payload(self):
        """Payload sent to the Core for this checklist item.

        Keys:
            production_source_res_id (int): the client's own mrp.production
                id this check belongs to — resolved to a nord.job on the Core.
            name (str or False): the check's title, falling back to its own
                name, False if neither is set.
            sequence (int): the check's ordering among the job's checklist,
                falling back to 10 when the quality point has none.
            test_type (str): the check's quality.check test_type
                (e.g. 'passfail', 'measure', ...).
            is_done (bool): whether the check has been performed
                (quality_state is not 'none').
            value (str or False): the passfail result, only meaningful
                (and only sent as non-False) when test_type is 'passfail'.
        """
        self.ensure_one()
        return {
            'production_source_res_id': self.production_id.id,
            'name': self.title or self.name or False,
            'sequence': self.point_id.sequence or 10,
            'test_type': self.test_type,
            'is_done': self.quality_state != 'none',
            'value': self.quality_state if self.test_type == 'passfail' else False,
        }
