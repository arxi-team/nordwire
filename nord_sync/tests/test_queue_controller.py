from unittest.mock import patch

from odoo.tests import HttpCase, tagged

ENDPOINT = '/nord_sync/api/v1/queue'
POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncQueueController(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['nord_sync.config'].create({
            'company_id': cls.env.company.id,
            'enabled': True,
            'company_uid': 'core-test-uid',
        })
        cls.tech_user = cls.env['res.users'].create({
            'name': 'Nord Core Technical User',
            'login': 'test_nord_core_tech',
            'group_ids': [(4, cls.env.ref('nord_sync.group_nord_sync_integration').id)],
        })
        cls.api_key = cls.env['res.users.apikeys'].with_user(cls.tech_user).sudo()._generate(
            'rpc', 'nord core test key', None,
        )

    def _get(self, company_uid='core-test-uid', last_seq=0, api_key=None):
        headers = {'Authorization': f'Bearer {api_key}'} if api_key is not None else {}
        return self.url_open(f'{ENDPOINT}?company_uid={company_uid}&last_seq={last_seq}', headers=headers)

    def test_missing_api_key_is_unauthorized(self):
        response = self._get()
        self.assertEqual(response.status_code, 401)

    def test_wrong_api_key_is_forbidden(self):
        response = self._get(api_key='not-a-real-key')
        self.assertEqual(response.status_code, 403)

    def test_unknown_company_uid_is_forbidden(self):
        response = self._get(company_uid='does-not-exist', api_key=self.api_key)
        self.assertEqual(response.status_code, 403)

    def test_valid_key_returns_new_entries_since_last_seq(self):
        with patch(POST_TARGET):
            product = self.env['product.product'].create({'name': 'Nord Sync Controller Test Product'})
            mo = self.env['mrp.production'].create({'product_id': product.id})
            mo.action_confirm()  # a draft MO alone doesn't enqueue, see Slice 2.4

        response = self._get(api_key=self.api_key)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        entries = [e for e in body['entries'] if e['res_id'] == mo.id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['model'], 'mrp.production')
        self.assertEqual(body['last_seq'], max(e['seq'] for e in body['entries']))

    def test_entry_carries_business_payload(self):
        with patch(POST_TARGET):
            product = self.env['product.product'].create({
                'name': 'Nord Sync Payload Test Product', 'default_code': 'NSPP-1',
            })
            mo = self.env['mrp.production'].create({'product_id': product.id, 'product_qty': 3})
            mo.action_confirm()

        body = self._get(api_key=self.api_key).json()
        entry = next(e for e in body['entries'] if e['res_id'] == mo.id)
        self.assertEqual(entry['payload']['product_qty'], 3)
        self.assertEqual(entry['payload']['product']['default_code'], 'NSPP-1')

    def test_last_seq_excludes_already_pulled_entries(self):
        with patch(POST_TARGET):
            product = self.env['product.product'].create({'name': 'Nord Sync Controller Test Product 2'})
            mo = self.env['mrp.production'].create({'product_id': product.id})
            mo.action_confirm()

        first = self._get(api_key=self.api_key).json()
        response = self._get(last_seq=first['last_seq'], api_key=self.api_key)
        self.assertEqual(response.json()['entries'], [])
