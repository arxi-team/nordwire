from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestStockMoveNordSync(TransactionCase):
    """Production Bridge: a real MO's move_raw_ids/move_finished_ids push a
    full snapshot to the Core, distinct from the BOM template."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.component = cls.env['product.product'].create({
            'name': 'Real Component', 'is_storable': True,
        })
        cls.product = cls.env['product.product'].create({'name': 'Real Output Product'})

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def _create_mo_with_component(self):
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {'product_id': self.component.id, 'product_qty': 2.0})],
        })
        with patch(POST_TARGET):
            mo = self.env['mrp.production'].create({
                'product_id': self.product.id, 'product_qty': 1.0, 'bom_id': bom.id,
            })
            mo.action_confirm()
        return mo

    def _last_moves_entry(self, mo_id):
        # mrp.production.moves always redirects to its MO's owner —
        # the snapshot itself is a nord.sync.queue.line folded
        # under that header, never its own header.
        return self.env['nord.sync.queue.line'].search([
            ('res_id', '=', mo_id), ('res_model', '=', 'mrp.production.moves'),
        ], order='id desc', limit=1)

    def test_no_config_does_not_enqueue(self):
        self.env['nord_sync.config'].search([('company_id', '=', self.env.company.id)]).unlink()
        with patch(POST_TARGET) as mocked_post:
            mo = self._create_mo_with_component()
        self.assertFalse(self.env['nord.sync.queue.line'].search([
            ('res_id', '=', mo.id), ('res_model', '=', 'mrp.production.moves'),
        ]))
        mocked_post.assert_not_called()

    def test_confirm_enqueues_snapshot_with_materials_and_finished_products(self):
        self._configure()
        mo = self._create_mo_with_component()
        entry = self._last_moves_entry(mo.id)
        self.assertTrue(entry)
        self.assertEqual(len(entry.data['materials']), 1)
        self.assertEqual(entry.data['materials'][0]['product']['name'], 'Real Component')
        self.assertEqual(entry.data['materials'][0]['quantity'], 2.0)
        self.assertEqual(len(entry.data['finished_products']), 1)
        self.assertEqual(entry.data['finished_products'][0]['product']['name'], 'Real Output Product')

    def test_material_carries_its_operations_workcenter_reference(self):
        self._configure()
        wc = self.env['mrp.workcenter'].create({'name': 'Real Cutting'})
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'product_qty': 1.0,
            'operation_ids': [(0, 0, {'name': 'Cut', 'workcenter_id': wc.id, 'time_cycle_manual': 10})],
        })
        # move_raw_ids is captured from the BOM's own lines at MO creation
        # time — the operation-linked line must exist on the BOM *before*
        # the MO is created, not added to it afterward.
        bom.bom_line_ids = [(0, 0, {
            'product_id': self.component.id, 'product_qty': 1.0, 'operation_id': bom.operation_ids.id,
        })]
        with patch(POST_TARGET):
            mo = self.env['mrp.production'].create({
                'product_id': self.product.id, 'product_qty': 1.0, 'bom_id': bom.id,
            })
            mo.action_confirm()
        entry = self._last_moves_entry(mo.id)
        self.assertEqual(entry.data['materials'][0]['workcenter_source_res_id'], wc.id)

    def test_removing_component_notifies_with_updated_snapshot(self):
        self._configure()
        mo = self._create_mo_with_component()
        with patch(POST_TARGET):
            mo.move_raw_ids.unlink()
        entry = self._last_moves_entry(mo.id)
        self.assertFalse(entry.data['materials'])

    def test_unrelated_move_never_enqueues(self):
        self._configure()
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        with patch(POST_TARGET) as mocked_post:
            self.env['stock.move'].create({
                'product_id': self.component.id, 'product_uom_qty': 1.0, 'product_uom': self.component.uom_id.id,
                'location_id': warehouse.lot_stock_id.id, 'location_dest_id': warehouse.lot_stock_id.id,
            })
        self.assertFalse(self.env['nord.sync.queue.line'].search([('res_model', '=', 'mrp.production.moves')]))
        mocked_post.assert_not_called()
