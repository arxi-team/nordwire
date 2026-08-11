from unittest.mock import Mock, patch

import requests

from odoo.tests import Form, TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({'name': 'Nord Sync Test Product'})

    def _create_mo(self):
        mo_form = Form(self.env['mrp.production'])
        mo_form.product_id = self.product
        return mo_form.save()

    def _confirm_mo(self):
        """Create + confirm — the trigger the "MO confirmed" Automation Rule
        (data/nord_sync_automation.xml) watches for.
        """
        with patch(POST_TARGET):
            mo = self._create_mo()
        mo.action_confirm()
        return mo

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_create_alone_does_not_enqueue(self):
        """A draft MO is not synced — only on confirm (or delete)."""
        self._configure()
        with patch(POST_TARGET) as mocked_post:
            mo = self._create_mo()
        self.assertFalse(self.env['nord.sync.queue'].search([('res_id', '=', mo.id)]))
        mocked_post.assert_not_called()

    def test_no_config_does_not_enqueue_on_confirm(self):
        with patch(POST_TARGET) as mocked_post:
            mo = self._create_mo()
            mo.action_confirm()
        self.assertFalse(self.env['nord.sync.queue'].search([('res_id', '=', mo.id)]))
        mocked_post.assert_not_called()

    def test_disabled_config_does_not_enqueue_on_confirm(self):
        self._configure(enabled=False)
        with patch(POST_TARGET) as mocked_post:
            mo = self._create_mo()
            mo.action_confirm()
        self.assertFalse(self.env['nord.sync.queue'].search([('res_id', '=', mo.id)]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_confirm(self):
        self._configure()
        with patch(POST_TARGET) as mocked_post:
            mo = self._create_mo()
            mo.action_confirm()
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.res_model, 'mrp.production')
        mocked_post.assert_not_called()  # no webhook_url/company_uid configured yet

    def test_write_after_confirm_does_not_reenqueue(self):
        """Known ceiling (ponytail): the rule only fires on the state
        transition INTO 'confirmed', not on later edits to an already-confirmed
        MO — the client can add a broader rule via the native UI if needed."""
        mo = self._confirm_mo()
        self._configure()
        with patch(POST_TARGET) as mocked_post:
            mo.write({'product_qty': 5})
        self.assertFalse(self.env['nord.sync.queue'].search([('res_id', '=', mo.id), ('operation', '=', 'write')]))
        mocked_post.assert_not_called()

    def test_webhook_not_configured_leaves_status_pending(self):
        self._configure()
        with patch(POST_TARGET):
            mo = self._create_mo()
            mo.action_confirm()  # no webhook_url/company_uid set
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertEqual(entry.status, 'pending')

    def test_enqueue_captures_business_payload(self):
        self.product.write({'default_code': 'NSPT-1'})
        self._configure()
        with patch(POST_TARGET):
            mo = self._create_mo()
            mo.action_confirm()
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertEqual(entry.data['name'], mo.name)
        self.assertEqual(entry.data['product_qty'], mo.product_qty)
        self.assertEqual(entry.data['state'], mo.state)
        self.assertEqual(entry.data['product'], {
            'name': self.product.name,
            'default_code': 'NSPT-1',
            'uom': self.product.uom_id.name,
        })

    def test_unlink_payload_captured_before_record_is_gone(self):
        with patch(POST_TARGET):
            mo = self._create_mo()
            mo_name = mo.name
            mo_id = mo.id
        self._configure()
        with patch(POST_TARGET):
            mo.unlink()
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo_id), ('operation', '=', 'unlink')])
        self.assertEqual(entry.data['name'], mo_name)

    def test_webhook_posted_when_configured(self):
        self._configure(company_uid='test-uid')
        self.env['nord_sync.config']._set_cloud_base_url('http://cloud.example.com')
        with patch(POST_TARGET) as mocked_post:
            mo = self._create_mo()
            mo.action_confirm()
        mocked_post.assert_called_once()
        call_args, call_kwargs = mocked_post.call_args
        self.assertEqual(call_args[0], 'http://cloud.example.com/nordos/sync/nord_sync/webhook')
        self.assertEqual(call_kwargs['json'], {'company_uid': 'test-uid'})
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertEqual(entry.status, 'sent')

    def test_webhook_failure_does_not_raise(self):
        self._configure(company_uid='test-uid')
        self.env['nord_sync.config']._set_cloud_base_url('http://cloud.example.com')
        with patch(POST_TARGET, side_effect=ConnectionError('refused')):
            mo = self._create_mo()
            mo.action_confirm()  # must not raise
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertTrue(entry)
        self.assertEqual(entry.status, 'failed')

    def test_webhook_non_2xx_response_marks_status_failed(self):
        self._configure(company_uid='test-uid')
        self.env['nord_sync.config']._set_cloud_base_url('http://cloud.example.com')
        error_response = Mock()
        error_response.raise_for_status.side_effect = requests.HTTPError('502')
        with patch(POST_TARGET, return_value=error_response):
            mo = self._create_mo()
            mo.action_confirm()
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertEqual(entry.status, 'failed')

    def test_cancel_enqueues(self):
        """Cancelling (not deleting) an MO has its own Automation Rule,
        separate from "MO confirmed"."""
        mo = self._confirm_mo()
        self._configure()
        with patch(POST_TARGET) as mocked_post:
            mo.action_cancel()
        entries = self.env['nord.sync.queue'].search([('res_id', '=', mo.id), ('operation', '=', 'write')])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.data['state'], 'cancel')
        mocked_post.assert_not_called()  # no webhook_url/company_uid configured yet

    def test_unlink_enqueues_regardless_of_confirmed_state(self):
        """Deletion always notifies (own Automation Rule, no state filter) — even
        for a draft MO that was never confirmed/synced; the Core's dispatcher
        already treats "unlink with no matching job" as a no-op."""
        with patch(POST_TARGET):
            mo = self._create_mo()
            mo_id = mo.id
        self._configure()
        with patch(POST_TARGET):
            mo.unlink()
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo_id), ('operation', '=', 'unlink')])
        self.assertEqual(len(entry), 1)
