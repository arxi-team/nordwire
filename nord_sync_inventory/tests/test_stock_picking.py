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
            ('res_id', '=', picking.id), ('res_model', '=', 'stock.picking'),
        ]))
        mocked_post.assert_not_called()

    def test_disabled_config_does_not_enqueue(self):
        self._configure(enabled=False)
        with patch(POST_TARGET) as mocked_post:
            picking = self._create_picking()
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('res_id', '=', picking.id), ('res_model', '=', 'stock.picking'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            picking = self._create_picking()
        entry = self.env['nord.sync.queue'].search([
            ('res_id', '=', picking.id), ('res_model', '=', 'stock.picking'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.operation, 'create')
        self.assertEqual(entry.data['name'], picking.name)
        self.assertEqual(entry.data['operation_type'], 'inventory')

    def test_write_does_not_enqueue(self):
        """No write Automation Rule wired for this model — confirms the
        per-model trigger choice, not a shared default."""
        self._configure()
        with patch(POST_TARGET):
            picking = self._create_picking()
        with patch(POST_TARGET) as mocked_post:
            picking.write({'note': 'Urgent'})
        entries = self.env['nord.sync.queue'].search([
            ('res_id', '=', picking.id), ('res_model', '=', 'stock.picking'), ('operation', '=', 'write'),
        ])
        self.assertFalse(entries)
        mocked_post.assert_not_called()
