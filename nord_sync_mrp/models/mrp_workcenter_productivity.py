# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Nord's 3 loss categories, mapped to
# Odoo's own 4 (mrp.workcenter.productivity.loss.type.loss_type). 'quality'
# has no Nord equivalent on purpose -- quality is covered by
# nord.declaration (not_pass/scrap) on the Core, never by a resource
# session's reason.
NORD_SYNC_LOSS_CATEGORY_MAP = {
    'production': 'productive',
    'speed_loss': 'performance',
    'downtime': 'availability',
}
NORD_SYNC_UNDEFINED_LOSS_NAME = 'Undefined'
NORD_SYNC_UNDEFINED_LOSS_TYPE = 'availability'


class MrpWorkcenterProductivityLoss(models.Model):
    """Get-or-create side of Nord Sync Timesheet Loss -- unlike
    the rest of this bridge (which never overwrites a value a human already
    set), a reason matched by name has its category rewritten every time:
    Nord is authoritative here, since re-justifying the category is the
    whole point of the correction channel this feeds.
    """
    _inherit = 'mrp.workcenter.productivity.loss'

    @api.model
    def _nord_sync_get_or_create(self, name, loss_type):
        """loss_type here is Odoo's real Selection value (already mapped
        from Nord's own category by the caller) -- writing it means
        pointing loss_id at the right mrp.workcenter.productivity.loss.type
        record (itself get-or-created, a thin one-row-per-value enum table
        with no seed data of its own to rely on)."""
        LossType = self.env['mrp.workcenter.productivity.loss.type'].sudo()
        loss_type_record = LossType.search([('loss_type', '=', loss_type)], limit=1)
        if not loss_type_record:
            loss_type_record = LossType.create({'loss_type': loss_type})
        loss = self.sudo().search([('name', '=', name)], limit=1)
        if loss:
            if loss.loss_id != loss_type_record:
                loss.loss_id = loss_type_record.id
            return loss
        return self.sudo().create({'name': name, 'loss_id': loss_type_record.id})

    @api.model
    def _nord_sync_get_or_create_undefined(self):
        """Every mrp.workcenter.productivity.loss_id is required -- a Core
        session with no loss_id of its own yet can't just leave it blank,
        so it lands here instead of on the old always-'productive' default,
        distinct and get-or-corrected the same way once really justified."""
        return self._nord_sync_get_or_create(NORD_SYNC_UNDEFINED_LOSS_NAME, NORD_SYNC_UNDEFINED_LOSS_TYPE)


class MrpWorkcenterProductivity(models.Model):
    _inherit = 'mrp.workcenter.productivity'

    nord_sync_timesheet_id = fields.Integer(
        string='Nord Timesheet', index=True,
        help='The nord.timesheet id on the Core this session came from -- the only stable '
             'reference to find this exact row again for a later loss-reason correction; '
             'a workorder can have several sessions.',
    )
    electric_consume = fields.Float(
        string='Electric Consume', copy=False,
        help='Same field/shape as the Zerynth app\'s own mrp.workcenter.productivity.'
             'electric_consume -- schema only for now, nothing writes to it yet.',
    )
