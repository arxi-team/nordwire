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

    # ── mrp.workorder (Timesheet Bridge) ────────────────────────────────────────

    def _create_mo_with_workorder(self, workcenter_name='Result Test WC'):
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': workcenter_name})
            bom = self.env['mrp.bom'].create({
                'product_tmpl_id': self.product.product_tmpl_id.id,
                'product_qty': 1.0,
                'operation_ids': [(0, 0, {'name': 'Op', 'workcenter_id': wc.id, 'time_cycle_manual': 30})],
            })
            mo = self.env['mrp.production'].create({
                'product_id': self.product.id, 'product_qty': 1.0, 'bom_id': bom.id,
            })
            mo.action_confirm()
        return mo, wc

    def test_workorder_missing_source_references_is_bad_request(self):
        response = self._post(
            {'company_uid': 'core-result-test-uid', 'res_model': 'mrp.workorder', 'duration': 1.0},
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 400)

    def test_workorder_unknown_production_is_not_found(self):
        response = self._post(
            {
                'company_uid': 'core-result-test-uid', 'res_model': 'mrp.workorder',
                'production_source_res_id': 999999, 'workcenter_source_res_id': 1, 'duration': 1.0,
            },
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 404)

    def test_workorder_no_matching_workorder_is_not_found(self):
        mo, _wc = self._create_mo_with_workorder()
        other_wc = self.env['mrp.workcenter'].create({'name': 'Unrelated WC'})
        response = self._post(
            {
                'company_uid': 'core-result-test-uid', 'res_model': 'mrp.workorder',
                'production_source_res_id': mo.id, 'workcenter_source_res_id': other_wc.id, 'duration': 1.0,
            },
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 404)

    def test_workorder_valid_request_applies_duration(self):
        mo, wc = self._create_mo_with_workorder()
        workorder = self.env['mrp.workorder'].search([
            ('production_id', '=', mo.id), ('workcenter_id', '=', wc.id),
        ], limit=1)
        response = self._post(
            {
                'company_uid': 'core-result-test-uid', 'res_model': 'mrp.workorder',
                'production_source_res_id': mo.id, 'workcenter_source_res_id': wc.id, 'duration': 1.5,
            },
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(workorder.duration, 90.0)  # 1.5h -> 90 minutes

    def test_workorder_second_session_accumulates_duration(self):
        mo, wc = self._create_mo_with_workorder()
        workorder = self.env['mrp.workorder'].search([
            ('production_id', '=', mo.id), ('workcenter_id', '=', wc.id),
        ], limit=1)
        body = {
            'company_uid': 'core-result-test-uid', 'res_model': 'mrp.workorder',
            'production_source_res_id': mo.id, 'workcenter_source_res_id': wc.id,
        }
        self._post({**body, 'duration': 1.0}, api_key=self.api_key)
        self._post({**body, 'duration': 0.5}, api_key=self.api_key)
        self.assertEqual(workorder.duration, 90.0)  # 60 + 30 minutes
