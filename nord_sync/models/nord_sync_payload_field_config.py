# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Every model with nord_sync.notify.mixin whose payload has a genuinely
# scalar-field portion worth making configurable — the 5 job-producing
# sources plus the 5 support bridges. Fixed on purpose: adding a new bridge
# is already a code change (its own _nord_sync_payload override), so
# registering it here at the same time costs nothing extra. Client-authored
# meta models (nord_sync.job.stage/state.mapping/config) are deliberately
# left out — their own payload is the client's authored content itself, not
# a business object's fields, so "which fields to send" isn't a meaningful
# question for them.
NORD_SYNC_PAYLOAD_CONFIGURABLE_MODELS = [
    ('mrp.production', 'Manufacturing Order'),
    ('mrp.workcenter', 'Work Center'),
    ('hr.employee', 'Employee'),
    ('mrp.bom', 'Bill of Materials'),
    ('mrp.workorder', 'Work Order'),
    ('quality.check', 'Quality Check'),
    ('sale.order', 'Sale Order'),
    ('purchase.order', 'Purchase Order'),
    ('stock.picking', 'Transfer'),
    ('maintenance.request', 'Maintenance Request'),
]

# Odoo field types that serialize directly to a JSON payload value with no
# extra resolution — a many2one/one2many/many2many's "value" is a client-local
# id, meaningless on the Core without the same source-reference resolution
# every other relational payload field already needs (see bom_source_res_id
# etc.); binary is a file. Both stay out of this mechanism, permanently.
NORD_SYNC_PAYLOAD_SCALAR_TTYPES = [
    'char', 'text', 'integer', 'float', 'boolean', 'selection', 'date', 'datetime', 'monetary',
]

# Default field_ids per model — exactly the fields each model's own
# _nord_sync_payload() used to hardcode under their own real name, before
# this mechanism existed. Anything that was hardcoded under a *different*
# name (a rename, a unit conversion, a fallback across fields, a snapshot of
# a different record) can't appear here — this mechanism only ever sends a
# field under its own real name, so reproducing the old behavior for those
# means leaving them hardcoded in the model's own _nord_sync_payload()
# instead, permanently, not a matter of a missing default. Read by both
# post_init_hook (fresh install) and the 1.0.5 migration (existing
# companies) so a company's payload never silently goes empty.
NORD_SYNC_PAYLOAD_DEFAULT_FIELDS = {
    'mrp.production': ['name', 'product_qty', 'state', 'log_note'],
    'mrp.workcenter': ['name'],
    'hr.employee': ['name'],
    'mrp.bom': [],
    'mrp.workorder': [],
    'quality.check': ['test_type'],
    'sale.order': ['name'],
    'purchase.order': ['name'],
    'stock.picking': ['name'],
    'maintenance.request': ['name'],
}


class NordSyncPayloadFieldConfig(models.Model):
    """Per-company, per-model selection of which of a Nord Sync source/
    support model's own scalar fields go out in its _nord_sync_payload().
    Only the genuinely scalar-field slice of each payload is
    covered: constants, relational-reference resolutions, and nested
    snapshots of other records stay hardcoded in each model's own
    _nord_sync_payload() (they can't be expressed as "read this field off
    self" at all, not a matter of preference). The two are merged there,
    dynamic dict first so the wired keys always win on a name collision
    (shouldn't happen — a wired key is never also a real field name on the
    same model — but never let a misconfiguration shadow one).

    No protection against selecting a field the Core wires real behavior to
    (e.g. mrp.production's own 'state', which drives Nord Sync State
    Mapping) — deselecting it silently stops that behavior, on purpose: the
    company configuring this decides, the system doesn't second-guess them.
    """
    _name = 'nord_sync.payload.field.config'
    _description = 'Nord Sync Payload Field Config'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    res_model = fields.Selection(
        NORD_SYNC_PAYLOAD_CONFIGURABLE_MODELS, required=True, string='Model',
    )
    field_ids = fields.Many2many(
        'ir.model.fields', string='Fields',
        domain="[('model', '=', res_model), ('ttype', 'in', %s)]" % (NORD_SYNC_PAYLOAD_SCALAR_TTYPES,),
        help='Only scalar fields are selectable — relational/binary fields need their own '
             'dedicated resolution and are never sent through this mechanism.',
    )

    _company_model_unique = models.Constraint(
        'UNIQUE(company_id, res_model)',
        'A payload field config already exists for this model in this company.',
    )

    @api.onchange('res_model')
    def _onchange_res_model(self):
        # A field selected for the previous res_model is very likely not
        # even a field on the new one — never leave stale field_ids sitting
        # there silently unused (the domain would just hide them, not clear
        # them, without this).
        self.field_ids = False

    @api.model
    def _nord_sync_seed_defaults_for_company(self, company):
        """Creates one row per model in NORD_SYNC_PAYLOAD_DEFAULT_FIELDS for
        this company, pre-populated with that model's default field names —
        idempotent (skips a model that already has a row for this company,
        so calling this again after a company has customized its selection
        never resets it). Called both from post_init_hook (a fresh install)
        and the 1.0.5 migration (an existing install) — the only two moments
        a company can reach this module without any config rows yet. Since
        the source addons split back apart (nord_sync_mrp/_sale/_purchase/
        _inventory/_maintenance), most of these 10 models won't be
        registered at all for a client that only installed a subset —
        skipped rather than seeding an inert row for a model that doesn't
        exist yet.
        """
        existing_models = set(self.sudo().search([
            ('company_id', '=', company.id),
        ]).mapped('res_model'))
        Fields = self.env['ir.model.fields'].sudo()
        for res_model, field_names in NORD_SYNC_PAYLOAD_DEFAULT_FIELDS.items():
            if res_model in existing_models or res_model not in self.env:
                continue
            field_ids = Fields.search([('model', '=', res_model), ('name', 'in', field_names)]).ids
            self.sudo().create({
                'company_id': company.id, 'res_model': res_model, 'field_ids': [(6, 0, field_ids)],
            })
