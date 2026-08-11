from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestSaleOrderNordSync(TransactionCase):
    """Same minimal shape as nord_sync_maintenance — create-only, no write/
    unlink Automation Rule wired."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Nord Sync Test Customer'})

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            order = self.env['sale.order'].create({'partner_id': self.partner.id})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('res_id', '=', order.id), ('res_model', '=', 'sale.order'),
        ]))
        mocked_post.assert_not_called()

    def test_disabled_config_does_not_enqueue(self):
        self._configure(enabled=False)
        with patch(POST_TARGET) as mocked_post:
            order = self.env['sale.order'].create({'partner_id': self.partner.id})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('res_id', '=', order.id), ('res_model', '=', 'sale.order'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            order = self.env['sale.order'].create({'partner_id': self.partner.id})
        entry = self.env['nord.sync.queue'].search([
            ('res_id', '=', order.id), ('res_model', '=', 'sale.order'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.operation, 'create')
        self.assertEqual(entry.data['name'], order.name)
        self.assertEqual(entry.data['operation_type'], 'sale')

    def test_write_does_not_enqueue(self):
        """No write Automation Rule wired for this model — confirms the
        per-model trigger choice, not a shared default."""
        self._configure()
        with patch(POST_TARGET):
            order = self.env['sale.order'].create({'partner_id': self.partner.id})
        with patch(POST_TARGET) as mocked_post:
            order.write({'client_order_ref': 'Urgent'})
        entries = self.env['nord.sync.queue'].search([
            ('res_id', '=', order.id), ('res_model', '=', 'sale.order'), ('operation', '=', 'write'),
        ])
        self.assertFalse(entries)
        mocked_post.assert_not_called()
