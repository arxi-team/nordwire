# -*- coding: utf-8 -*-
from odoo import api, models


class NordSyncConfig(models.Model):
    """Registers mrp.production as a Nord Sync Source — consumed by the
    install wizard's Job Stages & Mapping step and by nord_sync.state.mapping's
    source_model/source_value Selections. _inherit chain, same shape as the
    Core's _apply_nord_sync_entry override in nordos_nord_sync_core_mrp.
    """
    _inherit = 'nord_sync.config'

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
