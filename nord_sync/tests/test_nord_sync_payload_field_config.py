# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNordSyncPayloadFieldConfigOnchange(TransactionCase):
    """ADR 0020 accepted the risk of deselecting a field that drives real
    Core-side behavior (e.g. mrp.production.state) without blocking it — this
    only covers the warning half of that decision.
    """

    def test_warns_when_state_deselected_for_mrp_production(self):
        name_field = self.env['ir.model.fields'].search(
            [('model', '=', 'mrp.production'), ('name', '=', 'name')], limit=1,
        )
        record = self.env['nord_sync.payload.field.config'].new({
            'company_id': self.env.company.id,
            'res_model': 'mrp.production',
            'field_ids': [(6, 0, name_field.ids)],  # state left out on purpose
        })
        result = record._onchange_field_ids_warn_behavioral()
        self.assertIn('warning', result)
        self.assertIn('state', result['warning']['message'])

    def test_no_warning_when_state_selected(self):
        fields = self.env['ir.model.fields'].search(
            [('model', '=', 'mrp.production'), ('name', 'in', ('name', 'state'))],
        )
        record = self.env['nord_sync.payload.field.config'].new({
            'company_id': self.env.company.id,
            'res_model': 'mrp.production',
            'field_ids': [(6, 0, fields.ids)],
        })
        self.assertIsNone(record._onchange_field_ids_warn_behavioral())

    def test_no_warning_for_model_with_no_behavioral_fields(self):
        record = self.env['nord_sync.payload.field.config'].new({
            'company_id': self.env.company.id,
            'res_model': 'hr.employee',
            'field_ids': [(6, 0, [])],
        })
        self.assertIsNone(record._onchange_field_ids_warn_behavioral())
