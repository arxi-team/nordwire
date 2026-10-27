# -*- coding: utf-8 -*-
import json

from odoo.tests import HttpCase, tagged

ENDPOINT = '/nord_sync/api/v1/resources'


@tagged('post_install', '-at_install')
class TestNordSyncResourcesController(HttpCase):
    """/resources only validates the envelope now (valid JSON, config
    resolves — there's no res_model to check, same as today) and queues a
    nord_sync.inbox entry — the resource upsert
    (nord_sync.resource._nord_sync_upsert_from_core) happens later, from
    nord_sync.inbox._cron_process_pending, not in-request anymore. The
    inbox entry's res_model is the fixed literal 'nord_sync.resource' (this
    route's own body carries no res_model key at all).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord_sync.config']._get_or_create_for_company(cls.env.company)
        cls.config.write({'enabled': True, 'company_uid': 'core-resources-test-uid'})
        cls.tech_user = cls.env['res.users'].create({
            'name': 'Nord Core Resources Technical User',
            'login': 'test_nord_core_resources_tech',
            'groups_id': [(4, cls.env.ref('nord_sync.group_nord_sync_integration').id)],
        })
        cls.api_key = cls.env['res.users.apikeys'].with_user(cls.tech_user).sudo()._generate(
            'rpc', 'nord core resources test key',
        )

    def _post(self, body, api_key=None):
        headers = {'Authorization': f'Bearer {api_key}'} if api_key is not None else {}
        headers['Content-Type'] = 'application/json'
        return self.url_open(ENDPOINT, data=json.dumps(body), headers=headers)

    def test_missing_api_key_is_unauthorized(self):
        response = self._post({'resources': []})
        self.assertEqual(response.status_code, 401)

    def test_invalid_json_is_bad_request(self):
        headers = {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}
        response = self.url_open(ENDPOINT, data='not json', headers=headers)
        self.assertEqual(response.status_code, 400)

    def test_unconfigured_company_is_forbidden(self):
        other_company = self.env['res.company'].create({'name': 'No Nordwire Config Resources'})
        other_user = self.env['res.users'].create({
            'name': 'Other Company Resources Tech User',
            'login': 'test_other_company_resources_tech',
            'company_id': other_company.id,
            'company_ids': [(4, other_company.id)],
            'groups_id': [(4, self.env.ref('nord_sync.group_nord_sync_integration').id)],
        })
        other_key = self.env['res.users.apikeys'].with_user(other_user).sudo()._generate(
            'rpc', 'other company resources test key',
        )
        response = self._post({'resources': []}, api_key=other_key)
        self.assertEqual(response.status_code, 403)

    def test_valid_request_queues_one_inbox_entry_with_no_immediate_effect(self):
        response = self._post(
            {'resources': [{'uid': 'resources-ctrl-test-uid', 'complete_name': 'Line 1 / Motor'}]},
            api_key=self.api_key,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        entries = self.env['nord_sync.inbox'].search([('endpoint', '=', 'resources')])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.res_model, 'nord_sync.resource')
        self.assertEqual(entries.status, 'pending')
        self.assertFalse(self.env['nord_sync.resource'].search([('uid', '=', 'resources-ctrl-test-uid')]))

    def test_cron_applies_the_queued_resource_upsert(self):
        self._post(
            {'resources': [{'uid': 'resources-ctrl-cron-test-uid', 'complete_name': 'Line 2 / Sensor'}]},
            api_key=self.api_key,
        )
        self.env['nord_sync.inbox']._cron_process_pending()
        resource = self.env['nord_sync.resource'].search([('uid', '=', 'resources-ctrl-cron-test-uid')])
        self.assertEqual(len(resource), 1)
        self.assertEqual(resource.complete_name, 'Line 2 / Sensor')
        self.assertFalse(self.env['nord_sync.inbox'].search([]))
