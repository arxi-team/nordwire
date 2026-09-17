import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

ENDPOINT = '/nord_sync/api/v1/workorder_event'
POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncWorkorderEventController(HttpCase):
    """/workorder_event only validates the envelope now (valid JSON,
    res_model/event_type present, config resolves) and queues a
    nord_sync.inbox entry — the domain effect (session start/stop, job
    cancel) happens later, from nord_sync.inbox._cron_process_pending, not
    in-request anymore.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # get_or_create, not a plain create() — a persistent dev DB reused
        # across sessions can already have a real nord_sync.config for this
        # company, which UNIQUE(company_id) would otherwise reject.
        cls.config = cls.env['nord_sync.config']._get_or_create_for_company(cls.env.company)
        cls.config.write({'enabled': True, 'company_uid': 'core-event-test-uid'})
        cls.tech_user = cls.env['res.users'].create({
            'name': 'Nord Core Event Technical User',
            'login': 'test_nord_core_event_tech',
            'group_ids': [(4, cls.env.ref('nord_sync.group_nord_sync_integration').id)],
        })
        cls.api_key = cls.env['res.users.apikeys'].with_user(cls.tech_user).sudo()._generate(
            'rpc', 'nord core event test key', None,
        )
        cls.product = cls.env['product.product'].create({'name': 'Nordwire Event Test Product'})

    def _create_mo_with_workorder(self):
        wc = self.env['mrp.workcenter'].create({'name': 'Event Test WC'})
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'product_qty': 1.0,
            'operation_ids': [(0, 0, {'name': 'Op', 'workcenter_id': wc.id, 'time_cycle_manual': 30})],
        })
        with patch(POST_TARGET):
            mo = self.env['mrp.production'].create({
                'product_id': self.product.id, 'product_qty': 1.0, 'bom_id': bom.id,
            })
            mo.action_confirm()
        workorder = self.env['mrp.workorder'].search([('production_id', '=', mo.id)], limit=1)
        return mo, workorder

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
        other_company = self.env['res.company'].create({'name': 'No Nordwire Config Event'})
        other_user = self.env['res.users'].create({
            'name': 'Other Company Event Tech User',
            'login': 'test_other_company_event_tech',
            'company_id': other_company.id,
            'company_ids': [(4, other_company.id)],
            'group_ids': [(4, self.env.ref('nord_sync.group_nord_sync_integration').id)],
        })
        other_key = self.env['res.users.apikeys'].with_user(other_user).sudo()._generate(
            'rpc', 'other company event test key', None,
        )
        response = self._post(
            {'res_model': 'mrp.workorder', 'res_id': 1, 'event_type': 'session_start'},
            api_key=other_key,
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_request_queues_one_inbox_entry_with_no_immediate_effect(self):
        _mo, workorder = self._create_mo_with_workorder()
        response = self._post(
            {
                'company_uid': 'core-event-test-uid', 'res_model': 'mrp.workorder',
                'res_id': workorder.id, 'event_type': 'session_start', 'payload': {},
            },
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        entries = self.env['nord_sync.inbox'].search([('endpoint', '=', 'workorder_event')])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.res_model, 'mrp.workorder')
        self.assertEqual(entries.status, 'pending')
        self.assertNotEqual(workorder.state, 'progress')  # no domain effect until the cron runs

    def test_cron_applies_the_queued_session_start(self):
        _mo, workorder = self._create_mo_with_workorder()
        self._post(
            {
                'company_uid': 'core-event-test-uid', 'res_model': 'mrp.workorder',
                'res_id': workorder.id, 'event_type': 'session_start', 'payload': {},
            },
            api_key=self.api_key,
        )
        self._process_inbox()
        self.assertEqual(workorder.state, 'progress')
        self.assertFalse(self.env['nord_sync.inbox'].search([]))

    def test_cron_applies_the_queued_job_cancel(self):
        mo, _workorder = self._create_mo_with_workorder()
        self._post(
            {
                'company_uid': 'core-event-test-uid', 'res_model': 'mrp.production',
                'res_id': mo.id, 'event_type': 'job_cancel', 'payload': {},
            },
            api_key=self.api_key,
        )
        self.assertNotEqual(mo.state, 'cancel')  # no domain effect until the cron runs
        self._process_inbox()
        self.assertEqual(mo.state, 'cancel')

    def test_unsupported_res_model_is_queued_and_fails_on_cron(self):
        response = self._post(
            {
                'company_uid': 'core-event-test-uid', 'res_model': 'product.product',
                'res_id': 1, 'event_type': 'session_start',
            },
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        entry = self.env['nord_sync.inbox'].search([('endpoint', '=', 'workorder_event')])
        self._process_inbox()
        self.assertEqual(entry.status, 'failed')
        self.assertIn('Unsupported res_model', entry.last_error)

    def test_unknown_workorder_is_queued_and_fails_on_cron(self):
        response = self._post(
            {
                'company_uid': 'core-event-test-uid', 'res_model': 'mrp.workorder',
                'res_id': 999999, 'event_type': 'session_start',
            },
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        entry = self.env['nord_sync.inbox'].search([('endpoint', '=', 'workorder_event')])
        self._process_inbox()
        self.assertEqual(entry.status, 'failed')
        self.assertEqual(entry.last_error, 'Unknown record')
