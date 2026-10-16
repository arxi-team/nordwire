# -*- coding: utf-8 -*-
from odoo import api, fields, models

NORD_SYNC_UNDEFINED_LOSS_NAME = 'Undefined'
NORD_SYNC_UNDEFINED_LOSS_TYPE = 'availability'


class MrpWorkcenterProductivityLossType(models.Model):
    """Nordwire Reason Type Import — pushes this loss type's own value to
    the Core as a nord.reason.type, so classifying a session there can
    still resolve a real Odoo loss_type on the way back, even though
    nord.reason.type itself carries no fixed category (client-configured
    by design). A support model of the mrp.production source, not a
    toggle-able source of its own — see _nord_sync_source_key below.
    """
    _inherit = ['mrp.workcenter.productivity.loss.type', 'nord_sync.notify.mixin']

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._nord_sync_notify('create')
        return records

    def write(self, vals):
        result = super().write(vals)
        self._nord_sync_notify('write')
        return result

    def _nord_sync_notify(self, operation):
        """Overrides the mixin's base loop instead of just setting
        _nord_sync_source_key: this model has no company_id of its own
        (Odoo's own base model, a shared enum table) — same reasoning as
        res_company.py's own override, resolving the acting user's company
        instead of a field the record doesn't have.
        """
        config = self.env['nord_sync.config'].sudo()._get_for_company(self.env.company)
        if not config or not config.enabled or not config._is_source_enabled(self._nord_sync_source_key()):
            return
        for record in self:
            config._enqueue_and_notify(record._name, record.id, operation, record._nord_sync_payload())

    def _nord_sync_source_key(self):
        return 'mrp.production'

    def _nord_sync_payload(self):
        """Snapshot sent to the Core on every change.

        Keys:
            loss_type (str): Odoo's own Selection value (availability/
                performance/quality/productive).
        """
        self.ensure_one()
        return {'loss_type': self.loss_type}


class MrpWorkcenterProductivityLoss(models.Model):
    """Get-or-create side of the Nordwire bridge's session classification —
    unlike the rest of this bridge (which never overwrites a value a human
    already set), a reason matched by name has its loss.type rewritten
    every time: Nord is authoritative here, since re-justifying is the
    whole point of the correction channel this feeds.

    Also pushes this record to the Core as a nord.reason, but only when it
    already has a real Odoo external id (mrp's own block_reason0..7 seed
    data, or any other addon's) — a plain create() from _nord_sync_get_or_create
    below (a reason the Core pushed down) or from a human via the UI never
    gets one, so neither loops back nor floods the Core with every custom
    reason a client creates by hand.
    """
    _inherit = ['mrp.workcenter.productivity.loss', 'nord_sync.notify.mixin']

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._nord_sync_notify('create')
        return records

    def write(self, vals):
        result = super().write(vals)
        self._nord_sync_notify('write')
        return result

    def _nord_sync_notify(self, operation):
        """Same company-less override as MrpWorkcenterProductivityLossType
        above, plus the external-id gate this model needs."""
        config = self.env['nord_sync.config'].sudo()._get_for_company(self.env.company)
        if not config or not config.enabled or not config._is_source_enabled(self._nord_sync_source_key()):
            return
        external_ids = self.get_external_id()
        for record in self:
            if not external_ids.get(record.id):
                continue
            config._enqueue_and_notify(record._name, record.id, operation, record._nord_sync_payload())

    def _nord_sync_source_key(self):
        return 'mrp.production'

    def _nord_sync_payload(self):
        """Snapshot sent to the Core on every change.

        Keys:
            name (str): the reason's display name.
            loss_type_source_res_id (int or False): this reason's own
                loss.id, so the Core can resolve the nord.reason.type it
                already imported (Nordwire Reason Type Import) — False
                when this reason has no category.
        """
        self.ensure_one()
        return {'name': self.name, 'loss_type_source_res_id': self.loss_id.id or False}

    @api.model
    def _nord_sync_get_or_create(self, name, reason_type_name):
        """reason_type_name is the Core's own nord.reason.reason_type_id.name
        (e.g. 'Performance') — for a reason.type Nordwire originally
        imported FROM this client (Nordwire Reason Type Import,
        reason_nord_sync.py on the Core), that name is exactly this
        client's own loss_type Selection value, capitalized. Matched
        case-insensitively against loss.type.loss_type, never by id — real
        bug, found live 2026-09-14: this used to be called
        loss_type_source_res_id and treated as a client-side record id to
        browse(), but neither Core payload that calls here
        (_nord_sync_session_loss_justified_payload,
        _push_nord_sync_result's work_sessions) has ever sent an id, only
        this name — so the id branch always missed and every reason landed
        on "Undefined" regardless of its real type, even when the reason
        NAME itself (a separate, unaffected code path) applied correctly.
        Falls back to the shared "Undefined" loss.type when the name is
        absent or doesn't match any of Odoo's 4 fixed values — e.g. a
        Core-native type with no client counterpart yet, like Automatic
        Idle Segments' 'Downtime' (edge_resource.py, Core)."""
        LossType = self.env['mrp.workcenter.productivity.loss.type'].sudo()
        loss_type_record = (
            LossType.search([('loss_type', '=', reason_type_name.lower())], limit=1)
            if reason_type_name else False
        )
        if not loss_type_record:
            loss_type_record = LossType.search([('loss_type', '=', NORD_SYNC_UNDEFINED_LOSS_TYPE)], limit=1) \
                or LossType.create({'loss_type': NORD_SYNC_UNDEFINED_LOSS_TYPE})
        loss = self.sudo().search([('name', '=', name)], limit=1)
        if loss:
            if loss.loss_id != loss_type_record:
                loss.loss_id = loss_type_record.id
            return loss
        return self.sudo().create({'name': name, 'loss_id': loss_type_record.id})

    @api.model
    def _nord_sync_get_or_create_undefined(self):
        """Every mrp.workcenter.productivity.loss_id is required -- a Core
        session with no reason yet can't just leave it blank, so it lands
        here instead of on the old always-'productive' default, distinct
        and get-or-corrected the same way once really justified."""
        return self._nord_sync_get_or_create(NORD_SYNC_UNDEFINED_LOSS_NAME, False)


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
        help='Tracks electric consumption for this session, using the same field shape as known '
             'external manufacturing systems for data compatibility -- filled from the Core\'s own '
             'nord.timesheet.energy_kwh_used for this exact session (Nordwire Result Push).',
    )
