import datetime
import logging
from unittest.mock import patch

from odoo.tests.common import HttpCase, new_test_user, tagged

_logger = logging.getLogger(__name__)

ENDPOINT = '/nord_sync/api/v1/queue'
PULL_LIMIT_TARGET = 'odoo.addons.nord_sync.controllers.nord_sync_controller.PULL_LIMIT'


@tagged('post_install', '-at_install')
class TestNordSyncController(HttpCase):
    """Pull-by-seq endpoint (manual test plan section 5)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord.sync.config'].create({
            'company_uid': 'tenant-a',
            'cloud_webhook_url': 'http://localhost:8090/webhook',
        })
        cls.integration_user = new_test_user(
            cls.env, login='nord_integration', groups='base.group_user,nord_sync.group_nord_sync_integration',
        )
        expiration = datetime.datetime.now() + datetime.timedelta(days=1)
        cls.api_key = cls.env['res.users.apikeys'].with_user(cls.integration_user)._generate(
            'rpc', 'test key', expiration,
        )

        # A user without the integration group, to test the Forbidden branch.
        cls.other_user = new_test_user(cls.env, login='nord_no_group')
        cls.other_api_key = cls.env['res.users.apikeys'].with_user(cls.other_user)._generate(
            'rpc', 'test key', expiration,
        )
        _logger.info(
            '[setUpClass] config #%d (uid=%s), integration user=%s, no-group user=%s',
            cls.config.id, cls.config.company_uid, cls.integration_user.login, cls.other_user.login,
        )

    def _auth_headers(self, key):
        return {'Authorization': f'Bearer {key}'}

    def _get(self, params, key=None):
        headers = self._auth_headers(key) if key else None
        url = f'{ENDPOINT}?{params}' if params else ENDPOINT
        _logger.info('[request] GET %s (auth=%s)', url, 'yes' if key else 'no')
        response = self.url_open(url, headers=headers)
        _logger.info('[response] HTTP %d', response.status_code)
        return response

    # -- authentication (manual test plan steps 24-25) -------------------------

    def test_no_auth_returns_401(self):
        response = self._get(f'company_uid={self.config.company_uid}')
        _logger.info('[auth] no key supplied -> expecting 401, got %d', response.status_code)
        self.assertEqual(response.status_code, 401)

    def test_invalid_key_returns_401(self):
        response = self._get(f'company_uid={self.config.company_uid}', key='not-a-real-key')
        _logger.info('[auth] bogus key supplied -> expecting 401, got %d', response.status_code)
        self.assertEqual(response.status_code, 401)

    def test_user_without_integration_group_returns_403(self):
        response = self._get(f'company_uid={self.config.company_uid}', key=self.other_api_key)
        _logger.info(
            '[auth] valid key but user lacks integration group -> expecting 403, got %d', response.status_code,
        )
        self.assertEqual(response.status_code, 403)

    # -- validation (manual test plan steps 26-28) -----------------------------

    def test_missing_company_uid_returns_400(self):
        response = self._get('', key=self.api_key)
        _logger.info('[validation] missing company_uid -> expecting 400, got %d', response.status_code)
        self.assertEqual(response.status_code, 400)

    def test_unknown_company_uid_returns_400(self):
        response = self._get('company_uid=does-not-exist', key=self.api_key)
        _logger.info('[validation] unknown company_uid -> expecting 400, got %d', response.status_code)
        self.assertEqual(response.status_code, 400)

    def test_wrong_tenant_user_returns_403(self):
        other_company = self.env['res.company'].create({'name': 'Other Co'})
        other_config = self.env['nord.sync.config'].create({
            'company_id': other_company.id,
            'company_uid': 'tenant-b',
            'cloud_webhook_url': 'http://localhost:8091/webhook',
        })
        _logger.info(
            '[tenant isolation] created config #%d for %s, requesting it with a key scoped to %s',
            other_config.id, other_config.company_uid, self.config.company_uid,
        )
        response = self._get(f'company_uid={other_config.company_uid}', key=self.api_key)
        _logger.info('[tenant isolation] expecting 403, got %d', response.status_code)
        self.assertEqual(response.status_code, 403)

    # -- happy path & cursor semantics (manual test plan steps 29-31) ---------

    def test_pull_returns_entries_in_order_with_expected_shape(self):
        Queue = self.env['nord.sync.queue']
        first = Queue._push(self.env.company.id, 'nord_sync.test', 'create', 1, {'a': 1})
        second = Queue._push(self.env.company.id, 'nord_sync.test', 'write', 2, {'b': 2})
        _logger.info('[pull] pushed queue entries #%d and #%d', first.id, second.id)

        response = self._get(f'company_uid={self.config.company_uid}', key=self.api_key)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        _logger.info('[pull] response body: %s', body)
        self.assertEqual(body['company_uid'], self.config.company_uid)
        self.assertEqual(body['last_seq'], second.id)
        self.assertEqual([e['seq'] for e in body['entries']], [first.id, second.id])
        self.assertEqual(body['entries'][0], {
            'seq': first.id, 'model': 'nord_sync.test', 'operation': 'create', 'res_id': 1, 'data': {'a': 1},
        })
        _logger.info('[pull] entries returned in order with the expected shape')

    def test_cursor_only_returns_newer_entries(self):
        Queue = self.env['nord.sync.queue']
        first = Queue._push(self.env.company.id, 'nord_sync.test', 'create', 1, {})
        second = Queue._push(self.env.company.id, 'nord_sync.test', 'create', 2, {})
        _logger.info('[cursor] pushed #%d and #%d, pulling with last_seq=%d', first.id, second.id, first.id)

        response = self._get(f'company_uid={self.config.company_uid}&last_seq={first.id}', key=self.api_key)
        body = response.json()
        _logger.info('[cursor] entries returned: %s (expected only #%d)', [e['seq'] for e in body['entries']], second.id)
        self.assertEqual([e['seq'] for e in body['entries']], [second.id])

    def test_cursor_with_no_new_entries_returns_empty_list(self):
        Queue = self.env['nord.sync.queue']
        last = Queue._push(self.env.company.id, 'nord_sync.test', 'create', 1, {})
        _logger.info('[cursor] pulling with last_seq=%d equal to the newest entry -> expecting empty list', last.id)

        response = self._get(f'company_uid={self.config.company_uid}&last_seq={last.id}', key=self.api_key)
        body = response.json()
        _logger.info('[cursor] entries=%s, last_seq=%s', body['entries'], body['last_seq'])
        self.assertEqual(body['entries'], [])
        self.assertEqual(body['last_seq'], last.id)

    def test_entries_with_blank_company_uid_are_still_returned(self):
        """The pull endpoint ignores webhook-delivery status entirely - it serves
        every row for the tenant regardless of whether the native webhook fired
        (manual test plan step 31)."""
        self.config.active = False
        record = self.env['nord.sync.queue']._push(self.env.company.id, 'nord_sync.test', 'create', 1, {})
        self.config.active = True
        _logger.info('[pull] queue entry #%d created with company_uid=%r, pulling anyway', record.id, record.company_uid)

        response = self._get(f'company_uid={self.config.company_uid}', key=self.api_key)
        body = response.json()
        seqs = [e['seq'] for e in body['entries']]
        _logger.info('[pull] entries returned: %s (expecting #%d present despite blank company_uid)', seqs, record.id)
        self.assertIn(record.id, seqs)

    def test_pagination_caps_at_pull_limit(self):
        """Manual test plan step 32, exercised against a small limit instead of 500+ real rows."""
        Queue = self.env['nord.sync.queue']
        rows = Queue
        for i in range(3):
            rows |= Queue._push(self.env.company.id, 'nord_sync.test', 'create', i, {})
        _logger.info('[pagination] pushed 3 entries: %s, capping PULL_LIMIT to 2', rows.ids)

        with patch(PULL_LIMIT_TARGET, 2):
            response = self._get(f'company_uid={self.config.company_uid}', key=self.api_key)
        body = response.json()
        _logger.info('[pagination] first page returned %s (expecting 2 entries)', [e['seq'] for e in body['entries']])

        self.assertEqual(len(body['entries']), 2)
        self.assertEqual(body['last_seq'], rows[1].id)

        with patch(PULL_LIMIT_TARGET, 2):
            follow_up = self._get(
                f'company_uid={self.config.company_uid}&last_seq={body["last_seq"]}', key=self.api_key,
            )
        follow_up_body = follow_up.json()
        _logger.info(
            '[pagination] second page (cursor=%s) returned %s (expecting only #%d)',
            body['last_seq'], [e['seq'] for e in follow_up_body['entries']], rows[2].id,
        )
        self.assertEqual([e['seq'] for e in follow_up_body['entries']], [rows[2].id])
