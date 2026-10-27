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
        cls.partner = cls.env['res.partner'].create({'name': 'Nordwire Test Customer'})

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            order = self.env['sale.order'].create({'partner_id': self.partner.id})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', order.id), ('owner_res_model', '=', 'sale.order'),
        ]))
        mocked_post.assert_not_called()

    def test_disabled_config_does_not_enqueue(self):
        self._configure(enabled=False)
        with patch(POST_TARGET) as mocked_post:
            order = self.env['sale.order'].create({'partner_id': self.partner.id})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', order.id), ('owner_res_model', '=', 'sale.order'),
        ]))
        mocked_post.assert_not_called()

    def test_source_not_selected_does_not_enqueue(self):
        # enabled_source_ids picked something else entirely — sale.order
        # stays fully installed but inert for this company, same as before
        # this was a per-addon install/uninstall choice.
        production_source = self.env['nord_sync.source'].search([('model', '=', 'mrp.production')])
        self._configure(enabled_source_ids=[(6, 0, production_source.ids)])
        with patch(POST_TARGET) as mocked_post:
            order = self.env['sale.order'].create({'partner_id': self.partner.id})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', order.id), ('owner_res_model', '=', 'sale.order'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            order = self.env['sale.order'].create({'partner_id': self.partner.id})
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', order.id), ('owner_res_model', '=', 'sale.order'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.line_ids.operation, 'create')
        self.assertEqual(entry.payload['name'], order.name)
        self.assertEqual(entry.payload['operation_type'], 'sale')

    def test_does_not_register_as_native_state_source(self):
        # Real bug found live, 2026-08-18: this addon used to register with
        # source_field='state' — letting
        # the install wizard's Job Stage Mapping step promise a mapping
        # that could never actually engage, since sale.order only ever
        # notifies on_create (never on a state transition, see the
        # Automation Rule data file). Same minimal shape as
        # nord_sync_maintenance now: no registration at all.
        models = [s['source_model'] for s in self.env['nord_sync.config']._nord_sync_available_native_sources()]
        self.assertNotIn('sale.order', models)

    def test_write_does_not_enqueue(self):
        """No write Automation Rule wired for this model — confirms the
        per-model trigger choice, not a shared default."""
        self._configure()
        with patch(POST_TARGET):
            order = self.env['sale.order'].create({'partner_id': self.partner.id})
        with patch(POST_TARGET) as mocked_post:
            order.write({'client_order_ref': 'Urgent'})
        entries = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', order.id), ('owner_res_model', '=', 'sale.order'), ('line_ids.operation', '=', 'write'),
        ])
        self.assertFalse(entries)
        mocked_post.assert_not_called()
