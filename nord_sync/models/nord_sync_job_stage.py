# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NordSyncJobStage(models.Model):
    """Client-authored job stage. Unlike every other Nord Sync channel, the
    client is the source of truth here — a fresh Core has no pre-existing
    nord.job.stage to reconcile against, so this pushes one way (client ->
    Core) through the same nord.sync.queue/webhook/pull pipeline
    mrp.production and product.product already use, never a pull.

    Set up in the install wizard's 4th step (native MRP states / own names /
    both), editable afterwards from this model directly.
    """
    _name = 'nord_sync.job.stage'
    _description = 'Nord Sync Job Stage'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )

    _company_name_unique = models.Constraint(
        'UNIQUE(company_id, name)',
        'A job stage with this name already exists for this company.',
    )

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
            company = record.company_id or self.env.company
            config = self.env['nord_sync.config'].sudo()._get_for_company(company)
            if not config or not config.enabled:
                continue
            config._enqueue_and_notify('nord_sync.job.stage', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        self.ensure_one()
        return {'name': self.name, 'sequence': self.sequence}
