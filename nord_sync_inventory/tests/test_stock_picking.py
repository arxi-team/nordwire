from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestStockPickingNordSync(TransactionCase):
    """Same minimal shape as nord_sync_maintenance — create-only, no write/
    unlink Automation Rule wired."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.picking_type = cls.env.ref('stock.picking_type_in')

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def _create_picking(self):
        return self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'location_id': self.picking_type.default_location_src_id.id,
            'location_dest_id': self.picking_type.default_location_dest_id.id,
        })

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            picking = self._create_picking()
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', picking.id), ('owner_res_model', '=', 'stock.picking'),
        ]))
        mocked_post.assert_not_called()

    def test_disabled_config_does_not_enqueue(self):
        self._configure(enabled=False)
        with patch(POST_TARGET) as mocked_post:
            picking = self._create_picking()
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', picking.id), ('owner_res_model', '=', 'stock.picking'),
        ]))
        mocked_post.assert_not_called()

    def test_source_not_selected_does_not_enqueue(self):
        production_source = self.env['nord_sync.source'].search([('model', '=', 'mrp.production')])
        self._configure(enabled_source_ids=[(6, 0, production_source.ids)])
        with patch(POST_TARGET) as mocked_post:
            picking = self._create_picking()
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', picking.id), ('owner_res_model', '=', 'stock.picking'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            picking = self._create_picking()
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', picking.id), ('owner_res_model', '=', 'stock.picking'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.line_ids.operation, 'create')
        self.assertEqual(entry.payload['name'], picking.name)
        self.assertEqual(entry.payload['operation_type'], 'inventory')

    def test_does_not_register_as_native_state_source(self):
        # Real bug found live, 2026-08-18 —
        # see nord_sync_sale's identical test for the full explanation.
        models = [s['source_model'] for s in self.env['nord_sync.config']._nord_sync_available_native_sources()]
        self.assertNotIn('stock.picking', models)

    def test_write_does_not_enqueue(self):
        """No write Automation Rule wired for this model — confirms the
        per-model trigger choice, not a shared default."""
        self._configure()
        with patch(POST_TARGET):
            picking = self._create_picking()
        with patch(POST_TARGET) as mocked_post:
            picking.write({'note': 'Urgent'})
        entries = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', picking.id), ('owner_res_model', '=', 'stock.picking'), ('line_ids.operation', '=', 'write'),
        ])
        self.assertFalse(entries)
        mocked_post.assert_not_called()
