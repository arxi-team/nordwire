from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestMrpWorkcenterNordSync(TransactionCase):
    """Resource Bridge."""

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            wc = self.env['mrp.workcenter'].create({'name': 'No Config WC'})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('res_id', '=', wc.id), ('res_model', '=', 'mrp.workcenter'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Cutting Line', 'resource_kind': 'machine'})
        entry = self.env['nord.sync.queue'].search([
            ('res_id', '=', wc.id), ('res_model', '=', 'mrp.workcenter'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.data['name'], 'Cutting Line')
        self.assertEqual(entry.data['resource_kind'], 'machine')

    def test_write_enqueues_with_current_payload(self):
        self._configure()
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Before Rename'})
            wc.write({'name': 'After Rename', 'resource_kind': 'human'})
        entries = self.env['nord.sync.queue'].search([
            ('res_id', '=', wc.id), ('res_model', '=', 'mrp.workcenter'), ('operation', '=', 'write'),
        ])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.data['name'], 'After Rename')
        self.assertEqual(entries.data['resource_kind'], 'human')

    def test_unlink_enqueues_before_record_is_gone(self):
        self._configure()
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Removed WC'})
            wc_id = wc.id
            wc.unlink()
        entry = self.env['nord.sync.queue'].search([
            ('res_id', '=', wc_id), ('res_model', '=', 'mrp.workcenter'), ('operation', '=', 'unlink'),
        ])
        self.assertEqual(len(entry), 1)
