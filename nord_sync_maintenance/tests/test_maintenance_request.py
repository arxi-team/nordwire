from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestMaintenanceRequestNordSync(TransactionCase):
    """A second source model, wired only via the "Maintenance Request
    created" Automation Rule (on_create), unlike
    mrp.production/product.product which also react to write/unlink.
    """

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            request = self.env['maintenance.request'].create({'name': 'No Config Request'})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', request.id), ('owner_res_model', '=', 'maintenance.request'),
        ]))
        mocked_post.assert_not_called()

    def test_disabled_config_does_not_enqueue(self):
        self._configure(enabled=False)
        with patch(POST_TARGET) as mocked_post:
            request = self.env['maintenance.request'].create({'name': 'Disabled Config Request'})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', request.id), ('owner_res_model', '=', 'maintenance.request'),
        ]))
        mocked_post.assert_not_called()

    def test_source_not_selected_does_not_enqueue(self):
        production_source = self.env['nord_sync.source'].search([('model', '=', 'mrp.production')])
        self._configure(enabled_source_ids=[(6, 0, production_source.ids)])
        with patch(POST_TARGET) as mocked_post:
            request = self.env['maintenance.request'].create({'name': 'Not Selected Request'})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', request.id), ('owner_res_model', '=', 'maintenance.request'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            request = self.env['maintenance.request'].create({'name': 'Fix conveyor belt'})
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', request.id), ('owner_res_model', '=', 'maintenance.request'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.line_ids.operation, 'create')
        self.assertEqual(entry.payload['name'], 'Fix conveyor belt')
        self.assertEqual(entry.payload['operation_type'], 'maintenance')

    def test_write_does_not_enqueue(self):
        """No write Automation Rule wired for this model (unlike MO/product) —
        confirms the per-model trigger choice, not a shared default."""
        self._configure()
        with patch(POST_TARGET):
            request = self.env['maintenance.request'].create({'name': 'Fix conveyor belt'})
        with patch(POST_TARGET) as mocked_post:
            request.write({'name': 'Fix conveyor belt urgently'})
        entries = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', request.id), ('owner_res_model', '=', 'maintenance.request'), ('line_ids.operation', '=', 'write'),
        ])
        self.assertFalse(entries)
        mocked_post.assert_not_called()
