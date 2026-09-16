# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NordSyncConfig(models.Model):
    """Registers mrp.production as a Nordwire Source — consumed by the
    install wizard's Job Stages & Mapping step and by nord_sync.state.mapping's
    source_model/source_value Selections. _inherit chain, same shape as the
    Core's _apply_nord_sync_entry override in nordos_nord_sync_core_mrp.
    """
    _inherit = 'nord_sync.config'

    nord_sync_confirm_workcenter_on_start = fields.Boolean(
        string='Confirm Work Center on Start',
        default=False,
        help='Off by default (today\'s behavior, unchanged): a workorder\'s "Start" button '
             'starts it immediately. On: interrupts a human-clicked Start (never an '
             'autonomous Nord Core one) with a lightweight wizard showing the work center '
             'already assigned, so it can be confirmed or changed before work actually '
             'begins.',
    )

    nord_sync_default_workcenter_control_mode = fields.Selection([
        ('odoo', 'Odoo'), ('nord', 'Nord'),
    ], string='Default Work Center Control Mode',
        help='Preset applied to the four floor-event fields (mrp_workcenter.py, ADR 0028) of '
             'a new work center that leaves Control Mode and all four of those fields unset — '
             'left empty (the default), a new work center keeps behaving exactly as it always '
             'has, implicitly "Odoo" via those fields\' own defaults. Purely a starting point: '
             'once a work center exists it never revisits this setting again, so changing it '
             'later never touches a work center already created, and any field explicitly '
             'given at creation time (its own value or Control Mode itself) always wins over '
             'this default.',
    )

    @api.model
    def _nord_sync_available_native_sources(self):
        sources = super()._nord_sync_available_native_sources()
        return sources + [{
            'source_model': 'mrp.production',
            'source_field': 'state',
            'label': 'Manufacturing Orders',
        }]

    def _nord_sync_backfill_existing_records(self):
        super()._nord_sync_backfill_existing_records()
        self.env['mrp.workcenter'].sudo().search(
            [('company_id', '=', self.company_id.id)])._nord_sync_notify('create')
        self.env['hr.employee'].sudo().search(
            [('company_id', '=', self.company_id.id)])._nord_sync_notify('create')
        # Real gap found live, 2026-08-18: missed here same as the two
        # above — a pre-existing BOM never got backfilled, so an MO
        # referencing it just warned and created a BOM-less job, forever.
        # company_id 'in' (False, ...) because BOMs
        # can be shared across companies (mrp.bom.company_id is optional),
        # unlike workcenter/employee above which are always company-owned.
        self.env['mrp.bom'].sudo().search(
            [('company_id', 'in', (False, self.company_id.id))])._nord_sync_notify('create')
        # Second real gap, found the same way: mrp.production itself was
        # never backfilled here, only its support models above — an MO
        # created/finished entirely during a disabled window (or before a
        # source addon was even installed) stayed invisible to the Core
        # forever unless someone happened to edit it again afterwards.
        self.env['mrp.production'].sudo().search(
            [('company_id', '=', self.company_id.id)])._nord_sync_notify('create')
