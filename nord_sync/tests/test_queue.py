import logging
from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)

POST_TARGET = 'requests.post'


def _mock_response(status_code=200, text=''):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.raise_for_status = Mock() if status_code < 400 else Mock(side_effect=Exception(text))
    return response


@tagged('post_install', '-at_install')
class TestNordSyncQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord.sync.config'].create({
            'company_uid': 'tenant-a',
            'cloud_webhook_url': 'http://localhost:8090/webhook',
        })
        cls.Queue = cls.env['nord.sync.queue']
        cls.action = cls.env.ref('nord_sync.webhook_action_queue_to_cloud')
        cls.action.webhook_url = cls.config.cloud_webhook_url

    # -- push / enqueue -----------------------------------------------------

    def test_push_creates_entry_with_expected_fields(self):
        record = self.Queue._push(
            self.env.company.id, 'nord_sync.test', 'create', 0, {'message': 'hello world'},
        )
        _logger.info(
            '[push] created queue entry #%d: model=%s op=%s res_id=%d uid=%s payload=%s',
            record.id, record.model_name, record.operation, record.res_id, record.company_uid, record.payload,
        )
        self.assertEqual(record.company_id.id, self.env.company.id)
        self.assertEqual(record.company_uid, 'tenant-a')
        self.assertEqual(record.model_name, 'nord_sync.test')
        self.assertEqual(record.operation, 'create')
        self.assertEqual(record.res_id, 0)
        self.assertEqual(record.payload, {'message': 'hello world'})

    def test_push_leaves_company_uid_blank_when_config_inactive(self):
        self.config.active = False
        record = self.Queue._push(self.env.company.id, 'nord_sync.test', 'create', 0, {})
        _logger.info('[push] config inactive -> company_uid=%r (expected blank)', record.company_uid)
        self.assertFalse(record.company_uid)
        self.config.active = True

    def test_push_still_creates_row_when_no_config_exists(self):
        """Audit trail/reconciliation cursor must never have gaps, even unconfigured."""
        other_company = self.env['res.company'].create({'name': 'No Config Co'})
        record = self.Queue._push(other_company.id, 'nord_sync.test', 'create', 0, {})
        _logger.info('[push] no config for company #%d -> row #%d, company_uid=%r', other_company.id, record.id, record.company_uid)
        self.assertTrue(record)
        self.assertFalse(record.company_uid)

    def test_action_create_test_entry_uses_canned_payload(self):
        self.Queue.action_create_test_entry()
        record = self.Queue.search([], order='id desc', limit=1)
        _logger.info(
            '[test entry] canned entry #%d: model=%s res_id=%d payload=%s',
            record.id, record.model_name, record.res_id, record.payload,
        )
        self.assertEqual(record.model_name, 'nord_sync.test')
        self.assertEqual(record.res_id, 0)
        self.assertIn('note', record.payload)

    def test_to_command_shape(self):
        """Payload shape read back by the Core's pull-by-seq endpoint."""
        record = self.Queue._push(
            self.env.company.id, 'nord_sync.test', 'create', 42, {'message': 'hello world'},
        )
        command = record._to_command()
        _logger.info('[to_command] queue entry #%d serialized as: %s', record.id, command)
        self.assertEqual(command, {
            'seq': record.id,
            'model': 'nord_sync.test',
            'operation': 'create',
            'res_id': 42,
            'data': {'message': 'hello world'},
        })

    # -- native Odoo->Cloud webhook (Automation Rule) ------------------------

    def test_creating_a_row_fires_the_native_webhook(self):
        """The base.automation rule (on_create) must register a postcommit
        webhook POST as soon as a row with a non-blank company_uid is created -
        no cron, no custom delivery code (manual test plan: Odoo->Cloud leg)."""
        with patch(POST_TARGET, return_value=_mock_response(200)) as mocked_post:
            record = self.Queue._push(
                self.env.company.id, 'nord_sync.test', 'create', 7, {'message': 'hi'},
            )
            self.env.cr.postcommit.run()
        _logger.info('[webhook] entry #%d created, requests.post called: %s', record.id, mocked_post.called)
        mocked_post.assert_called_once()
        url, kwargs = mocked_post.call_args.args[0], mocked_post.call_args.kwargs
        self.assertEqual(url, self.config.cloud_webhook_url)
        import json
        body = json.loads(kwargs['data'])
        _logger.info('[webhook] POST body: %s', body)
        self.assertEqual(body['company_uid'], 'tenant-a')
        self.assertEqual(body['model_name'], 'nord_sync.test')
        self.assertEqual(body['operation'], 'create')
        self.assertEqual(body['res_id'], 7)
        self.assertEqual(body['payload'], {'message': 'hi'})

    def test_row_with_blank_company_uid_does_not_fire_the_webhook(self):
        """filter_domain=[('company_uid', '!=', False)] must skip paused/unconfigured companies."""
        self.config.active = False
        with patch(POST_TARGET, return_value=_mock_response(200)) as mocked_post:
            self.Queue._push(self.env.company.id, 'nord_sync.test', 'create', 0, {})
            self.env.cr.postcommit.run()
        _logger.info('[webhook] config inactive, requests.post called: %s (expected False)', mocked_post.called)
        mocked_post.assert_not_called()
        self.config.active = True
