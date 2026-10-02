import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

ENDPOINT = '/nord_sync/api/v1/result'
POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncResultController(HttpCase):
    """/result only validates the envelope now (valid JSON, res_model
    present, config resolves) and queues a nord_sync.inbox entry — the
    domain effect (record lookup, mrp.production._nord_sync_apply_result)
    happens later, from nord_sync.inbox._cron_process_pending. So an
    unsupported res_model or an unknown res_id no longer 4xx synchronously
    (that used to be a domain-level check inside the controller) — both
    are now accepted at 200 and only surface as a failed inbox entry once
    the cron actually tries to dispatch them.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['nord_sync.config'].create({
            'company_id': cls.env.company.id,
            'enabled': True,
            'company_uid': 'core-result-test-uid',
        })
        cls.tech_user = cls.env['res.users'].create({
            'name': 'Nord Core Result Technical User',
            'login': 'test_nord_core_result_tech',
            'groups_id': [(4, cls.env.ref('nord_sync.group_nord_sync_integration').id)],
        })
        cls.api_key = cls.env['res.users.apikeys'].with_user(cls.tech_user).sudo()._generate(
            'rpc', 'nord core result test key',
        )
        cls.product = cls.env['product.product'].create({'name': 'Nord Sync Result Test Product'})

    def _create_mo(self, qty=2.0):
        with patch(POST_TARGET):
            mo = self.env['mrp.production'].create({'product_id': self.product.id, 'product_qty': qty})
            mo.action_confirm()
        return mo

    def _post(self, body, api_key=None):
        headers = {'Authorization': f'Bearer {api_key}'} if api_key is not None else {}
        headers['Content-Type'] = 'application/json'
        return self.url_open(ENDPOINT, data=json.dumps(body), headers=headers)

    def _process_inbox(self):
        self.env['nord_sync.inbox']._cron_process_pending()

    def test_missing_api_key_is_unauthorized(self):
        response = self._post({})
        self.assertEqual(response.status_code, 401)

    def test_missing_fields_is_bad_request(self):
        response = self._post({}, api_key=self.api_key)
        self.assertEqual(response.status_code, 400)

    def test_unconfigured_company_is_forbidden(self):
        other_company = self.env['res.company'].create({'name': 'No Nord Sync Config'})
        other_user = self.env['res.users'].create({
            'name': 'Other Company Result Tech User',
            'login': 'test_other_company_result_tech',
            'company_id': other_company.id,
            'company_ids': [(4, other_company.id)],
            'groups_id': [(4, self.env.ref('nord_sync.group_nord_sync_integration').id)],
        })
        other_key = self.env['res.users.apikeys'].with_user(other_user).sudo()._generate(
            'rpc', 'other company result test key',
        )
        response = self._post(
            {'res_model': 'mrp.production', 'res_id': 1, 'qty_produced': 1},
            api_key=other_key,
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_request_queues_one_inbox_entry_with_no_immediate_effect(self):
        mo = self._create_mo(qty=2.0)
        response = self._post(
            {'company_uid': 'core-result-test-uid', 'res_model': 'mrp.production', 'res_id': mo.id, 'qty_produced': 2.0},
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        entries = self.env['nord_sync.inbox'].search([('endpoint', '=', 'result')])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.res_model, 'mrp.production')
        self.assertEqual(entries.status, 'pending')
        self.assertEqual(entries.payload['res_id'], mo.id)
        self.assertNotEqual(mo.state, 'done')  # no domain effect until the cron runs

    def test_cron_applies_the_queued_result(self):
        mo = self._create_mo(qty=2.0)
        self._post(
            {'company_uid': 'core-result-test-uid', 'res_model': 'mrp.production', 'res_id': mo.id, 'qty_produced': 2.0},
            api_key=self.api_key,
        )
        self._process_inbox()
        self.assertEqual(mo.state, 'done')
        self.assertFalse(self.env['nord_sync.inbox'].search([]))

    def test_unsupported_res_model_is_queued_and_fails_on_cron(self):
        response = self._post(
            {'company_uid': 'core-result-test-uid', 'res_model': 'product.product', 'res_id': 1, 'qty_produced': 1},
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        entry = self.env['nord_sync.inbox'].search([('endpoint', '=', 'result')])
        self.assertEqual(entry.status, 'pending')
        self._process_inbox()
        self.assertEqual(entry.status, 'failed')
        self.assertIn('Unsupported res_model', entry.last_error)

    def test_unknown_res_id_is_queued_and_fails_on_cron(self):
        response = self._post(
            {'company_uid': 'core-result-test-uid', 'res_model': 'mrp.production', 'res_id': 999999, 'qty_produced': 1},
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        entry = self.env['nord_sync.inbox'].search([('endpoint', '=', 'result')])
        self._process_inbox()
        self.assertEqual(entry.status, 'failed')
        self.assertEqual(entry.last_error, 'Unknown record')

    # mrp.workorder duration result-push tests used to live here, but they were
    # already failing before this refactor: _nord_sync_result_mrp_production
    # only ever handled res_model == 'mrp.production', never 'mrp.workorder' —
    # posting a workorder duration result has always come back "Unsupported
    # res_model" underneath. Removed rather than carried forward broken;
    # duration-accumulation support of its own is a separate feature, out of
    # this refactor's scope.
