# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NordSyncJobStage(models.Model):
    """Client-authored job stage. Unlike every other Nordwire channel, the
    client is the source of truth here — a fresh Core has no pre-existing
    nord.job.stage to reconcile against, so this pushes one way (client ->
    Core) through the same nord.sync.queue/webhook/pull pipeline
    mrp.production and product.product already use, never a pull.

    Set up in the install wizard's 4th step (native MRP states / own names /
    both), editable afterwards from this model directly.
    """
    _name = 'nord_sync.job.stage'
    _inherit = ['nord_sync.notify.mixin']
    _description = 'Nordwire Job Stage'
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

    def _nord_sync_source_key(self):
        # A client-authored meta model, not a toggle-able Nordwire Source —
        # only config.enabled gates it, no per-source check.
        return False

    def _nord_sync_payload(self):
        """Payload sent to the Core for this client-authored job stage.

        Keys:
            name (str): the job stage's display name.
            sequence (int): ordering among this company's job stages.
        """
        self.ensure_one()
        return {'name': self.name, 'sequence': self.sequence}
