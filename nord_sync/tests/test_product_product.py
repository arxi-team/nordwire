from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestProductProductNordSync(TransactionCase):

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def _create_product(self, **vals):
        vals.setdefault('name', 'Nord Sync Test Product')
        with patch(POST_TARGET):
            return self.env['product.product'].create(vals)

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            product = self.env['product.product'].create({'name': 'No Config Product'})
        self.assertFalse(self.env['nord.sync.queue'].search([('res_id', '=', product.id), ('res_model', '=', 'product.product')]))
        mocked_post.assert_not_called()

    def test_disabled_config_does_not_enqueue(self):
        self._configure(enabled=False)
        with patch(POST_TARGET) as mocked_post:
            product = self.env['product.product'].create({'name': 'Disabled Config Product'})
        self.assertFalse(self.env['nord.sync.queue'].search([('res_id', '=', product.id), ('res_model', '=', 'product.product')]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            product = self.env['product.product'].create({'name': 'Enabled Config Product', 'default_code': 'ECP-1'})
        entry = self.env['nord.sync.queue'].search([('res_id', '=', product.id), ('res_model', '=', 'product.product')])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.operation, 'create')
        self.assertEqual(entry.data['name'], 'Enabled Config Product')
        self.assertEqual(entry.data['default_code'], 'ECP-1')

    def test_write_enqueues_with_current_payload(self):
        self._configure()
        product = self._create_product(default_code='W-1')
        with patch(POST_TARGET):
            product.write({'name': 'Renamed Product'})
        entries = self.env['nord.sync.queue'].search([
            ('res_id', '=', product.id), ('res_model', '=', 'product.product'), ('operation', '=', 'write'),
        ])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.data['name'], 'Renamed Product')

    def test_unlink_enqueues_before_record_is_gone(self):
        self._configure()
        product = self._create_product(default_code='U-1')
        product_id = product.id
        with patch(POST_TARGET):
            product.unlink()
        entry = self.env['nord.sync.queue'].search([
            ('res_id', '=', product_id), ('res_model', '=', 'product.product'), ('operation', '=', 'unlink'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.data['default_code'], 'U-1')
