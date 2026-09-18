from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestMrpBomNordSync(TransactionCase):
    """BOM Bridge."""

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def _product(self, name):
        return self.env['product.product'].create({'name': name, 'type': 'consu'})

    def _last_bom_entry(self, bom_id):
        return self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', bom_id), ('owner_res_model', '=', 'mrp.bom'),
        ], order='id desc', limit=1)

    def test_no_config_does_not_enqueue(self):
        product_tmpl = self._product('No Config Product').product_tmpl_id
        with patch(POST_TARGET) as mocked_post:
            bom = self.env['mrp.bom'].create({'product_tmpl_id': product_tmpl.id, 'product_qty': 1.0})
        self.assertFalse(self._last_bom_entry(bom.id))
        mocked_post.assert_not_called()

    def test_create_enqueues_with_lines_and_output(self):
        self._configure()
        material = self._product('Screw')
        product_tmpl = self._product('Widget').product_tmpl_id
        with patch(POST_TARGET):
            bom = self.env['mrp.bom'].create({
                'product_tmpl_id': product_tmpl.id,
                'product_qty': 1.0,
                'bom_line_ids': [(0, 0, {'product_id': material.id, 'product_qty': 4.0})],
            })
        entry = self._last_bom_entry(bom.id)
        self.assertEqual(len(entry.payload['lines']), 1)
        self.assertEqual(entry.payload['lines'][0]['product']['name'], 'Screw')
        self.assertEqual(entry.payload['lines'][0]['quantity'], 4.0)
        self.assertEqual(len(entry.payload['product_lines']), 1)
        self.assertEqual(entry.payload['product_lines'][0]['product']['name'], 'Widget')

    def test_byproducts_included_in_product_lines(self):
        self._configure()
        product_tmpl = self._product('Main Output').product_tmpl_id
        byproduct = self._product('Sawdust')
        with patch(POST_TARGET):
            bom = self.env['mrp.bom'].create({
                'product_tmpl_id': product_tmpl.id,
                'product_qty': 1.0,
                'byproduct_ids': [(0, 0, {'product_id': byproduct.id, 'product_qty': 0.3})],
            })
        entry = self._last_bom_entry(bom.id)
        names = sorted(line['product']['name'] for line in entry.payload['product_lines'])
        self.assertEqual(names, ['Main Output', 'Sawdust'])

    def test_adding_line_to_existing_bom_notifies_parent(self):
        self._configure()
        product_tmpl = self._product('Existing BOM Product').product_tmpl_id
        material = self._product('New Material')
        with patch(POST_TARGET):
            bom = self.env['mrp.bom'].create({'product_tmpl_id': product_tmpl.id, 'product_qty': 1.0})
            self.env['mrp.bom.line'].create({'bom_id': bom.id, 'product_id': material.id, 'product_qty': 1.0})
        entry = self._last_bom_entry(bom.id)
        self.assertEqual(len(entry.payload['lines']), 1)
        self.assertEqual(entry.payload['lines'][0]['product']['name'], 'New Material')

    def test_removing_line_notifies_parent_with_updated_snapshot(self):
        self._configure()
        product_tmpl = self._product('Line Removal Product').product_tmpl_id
        material = self._product('Removable Material')
        with patch(POST_TARGET):
            bom = self.env['mrp.bom'].create({
                'product_tmpl_id': product_tmpl.id,
                'product_qty': 1.0,
                'bom_line_ids': [(0, 0, {'product_id': material.id, 'product_qty': 1.0})],
            })
            bom.bom_line_ids.unlink()
        entry = self._last_bom_entry(bom.id)
        self.assertFalse(entry.payload['lines'])

    def test_operation_carries_workcenter_source_reference_and_duration_in_hours(self):
        self._configure()
        product_tmpl = self._product('Op Product').product_tmpl_id
        wc = self.env['mrp.workcenter'].create({'name': 'Assembly'})
        with patch(POST_TARGET):
            bom = self.env['mrp.bom'].create({'product_tmpl_id': product_tmpl.id, 'product_qty': 1.0})
            self.env['mrp.routing.workcenter'].create({
                'name': 'Assemble', 'bom_id': bom.id, 'workcenter_id': wc.id, 'time_cycle_manual': 90,
            })
        entry = self._last_bom_entry(bom.id)
        self.assertEqual(len(entry.payload['operations']), 1)
        op = entry.payload['operations'][0]
        self.assertEqual(op['workcenter_source_res_id'], wc.id)
        self.assertEqual(op['expected_duration'], 1.5)  # 90 minutes -> 1.5 hours

    def test_unlink_enqueues_before_bom_is_gone(self):
        self._configure()
        product_tmpl = self._product('Removed BOM Product').product_tmpl_id
        with patch(POST_TARGET):
            bom = self.env['mrp.bom'].create({'product_tmpl_id': product_tmpl.id, 'product_qty': 1.0})
            bom_id = bom.id
            bom.unlink()
        line = self.env['nord.sync.queue.line'].search([
            ('res_id', '=', bom_id), ('res_model', '=', 'mrp.bom'), ('operation', '=', 'unlink'),
        ])
        self.assertEqual(len(line), 1)

    def test_mrp_production_payload_carries_bom_source_res_id(self):
        self._configure()
        product_tmpl = self._product('MO BOM Product').product_tmpl_id
        with patch(POST_TARGET):
            bom = self.env['mrp.bom'].create({'product_tmpl_id': product_tmpl.id, 'product_qty': 1.0})
        mo = self.env['mrp.production'].create({
            'product_id': product_tmpl.product_variant_id.id,
            'product_qty': 1.0,
            'product_uom_id': product_tmpl.uom_id.id,
            'bom_id': bom.id,
        })
        self.assertEqual(mo._nord_sync_payload()['bom_source_res_id'], bom.id)

    def test_mrp_production_without_bom_carries_false(self):
        product = self._product('No BOM Product')
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 1.0, 'product_uom_id': product.uom_id.id,
        })
        self.assertFalse(mo._nord_sync_payload()['bom_source_res_id'])
