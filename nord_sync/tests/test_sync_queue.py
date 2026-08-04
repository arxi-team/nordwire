from unittest.mock import Mock, patch

import requests

from odoo.tests import Form, TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.mrp_production.requests.post'


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

    def test_disabled_company_does_not_enqueue(self):
        self.env.company.nord_sync_enabled = False
        with patch(POST_TARGET) as mocked_post:
            mo = self._create_mo()
        self.assertFalse(self.env['nord.sync.queue'].search([('res_id', '=', mo.id)]))
        mocked_post.assert_not_called()

    def test_enabled_company_enqueues_on_create(self):
        self.env.company.nord_sync_enabled = True
        with patch(POST_TARGET) as mocked_post:
            mo = self._create_mo()
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.res_model, 'mrp.production')
        self.assertEqual(entry.operation, 'create')
        mocked_post.assert_not_called()  # no webhook_url/company_uid configured yet

    def test_webhook_not_configured_leaves_status_pending(self):
        self.env.company.nord_sync_enabled = True
        with patch(POST_TARGET):
            mo = self._create_mo()  # no webhook_url/company_uid set
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertEqual(entry.status, 'pending')

    def test_enqueue_captures_business_payload(self):
        self.product.write({'default_code': 'NSPT-1'})
        self.env.company.nord_sync_enabled = True
        with patch(POST_TARGET):
            mo = self._create_mo()
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
        self.env.company.nord_sync_enabled = True
        with patch(POST_TARGET):
            mo = self._create_mo()
            mo_name = mo.name
            mo_id = mo.id
        with patch(POST_TARGET):
            mo.unlink()
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo_id), ('operation', '=', 'unlink')])
        self.assertEqual(entry.data['name'], mo_name)

    def test_enabled_company_enqueues_on_write(self):
        self.env.company.nord_sync_enabled = True
        with patch(POST_TARGET):
            mo = self._create_mo()
        with patch(POST_TARGET) as mocked_post:
            mo.write({'product_qty': 5})
        entries = self.env['nord.sync.queue'].search([('res_id', '=', mo.id), ('operation', '=', 'write')])
        self.assertEqual(len(entries), 1)
        mocked_post.assert_not_called()

    def test_webhook_posted_when_configured(self):
        self.env.company.write({
            'nord_sync_enabled': True,
            'nord_sync_company_uid': 'test-uid',
            'nord_sync_cloud_webhook_url': 'http://cloud.example.com/nordos/sync/nord_sync/webhook',
        })
        with patch(POST_TARGET) as mocked_post:
            mo = self._create_mo()
        mocked_post.assert_called_once()
        call_args, call_kwargs = mocked_post.call_args
        self.assertEqual(call_args[0], 'http://cloud.example.com/nordos/sync/nord_sync/webhook')
        self.assertEqual(call_kwargs['json'], {'company_uid': 'test-uid'})
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertEqual(entry.status, 'sent')

    def test_webhook_failure_does_not_raise(self):
        self.env.company.write({
            'nord_sync_enabled': True,
            'nord_sync_company_uid': 'test-uid',
            'nord_sync_cloud_webhook_url': 'http://cloud.example.com/nordos/sync/nord_sync/webhook',
        })
        with patch(POST_TARGET, side_effect=ConnectionError('refused')):
            mo = self._create_mo()  # must not raise
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertTrue(entry)
        self.assertEqual(entry.status, 'failed')

    def test_webhook_non_2xx_response_marks_status_failed(self):
        self.env.company.write({
            'nord_sync_enabled': True,
            'nord_sync_company_uid': 'test-uid',
            'nord_sync_cloud_webhook_url': 'http://cloud.example.com/nordos/sync/nord_sync/webhook',
        })
        error_response = Mock()
        error_response.raise_for_status.side_effect = requests.HTTPError('502')
        with patch(POST_TARGET, return_value=error_response):
            mo = self._create_mo()
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo.id)])
        self.assertEqual(entry.status, 'failed')

    def test_unlink_enqueues_before_record_is_gone(self):
        self.env.company.nord_sync_enabled = True
        with patch(POST_TARGET):
            mo = self._create_mo()
            mo_id = mo.id
        with patch(POST_TARGET):
            mo.unlink()
        entry = self.env['nord.sync.queue'].search([('res_id', '=', mo_id), ('operation', '=', 'unlink')])
        self.assertEqual(len(entry), 1)
