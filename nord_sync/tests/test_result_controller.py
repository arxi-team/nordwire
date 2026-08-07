import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

ENDPOINT = '/nord_sync/api/v1/result'
POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncResultController(HttpCase):

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
            'group_ids': [(4, cls.env.ref('nord_sync.group_nord_sync_integration').id)],
        })
        cls.api_key = cls.env['res.users.apikeys'].with_user(cls.tech_user).sudo()._generate(
            'rpc', 'nord core result test key', None,
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
            'group_ids': [(4, self.env.ref('nord_sync.group_nord_sync_integration').id)],
        })
        other_key = self.env['res.users.apikeys'].with_user(other_user).sudo()._generate(
            'rpc', 'other company result test key', None,
        )
        response = self._post(
            {'res_model': 'mrp.production', 'res_id': 1, 'qty_produced': 1},
            api_key=other_key,
        )
        self.assertEqual(response.status_code, 403)

    def test_unsupported_res_model_is_bad_request(self):
        response = self._post(
            {'company_uid': 'core-result-test-uid', 'res_model': 'product.product', 'res_id': 1, 'qty_produced': 1},
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_res_id_is_not_found(self):
        response = self._post(
            {'company_uid': 'core-result-test-uid', 'res_model': 'mrp.production', 'res_id': 999999, 'qty_produced': 1},
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 404)

    def test_valid_request_applies_result(self):
        mo = self._create_mo(qty=2.0)
        response = self._post(
            {'company_uid': 'core-result-test-uid', 'res_model': 'mrp.production', 'res_id': mo.id, 'qty_produced': 2.0},
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['success'])
        self.assertEqual(mo.state, 'done')
