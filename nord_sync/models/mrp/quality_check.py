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
    this bridge.
    """
    _inherit = 'quality.check'

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

    def _nord_sync_notify(self, operation):
        for record in self:
            if not record.production_id:
                continue
            config = self.env['nord_sync.config'].sudo()._get_for_company(record.company_id)
            if not config or not config.enabled or not config._is_source_enabled('mrp.production'):
                continue
            config._enqueue_and_notify('quality.check', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        self.ensure_one()
        return {
            'production_source_res_id': self.production_id.id,
            'name': self.title or self.name or False,
            'sequence': self.point_id.sequence or 10,
            'test_type': self.test_type,
            'is_done': self.quality_state != 'none',
            'value': self.quality_state if self.test_type == 'passfail' else False,
        }
