import logging

from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestNordSyncConfig(TransactionCase):

    def test_one_config_per_company(self):
        """A second config for the same company must be rejected (manual test plan step 12)."""
        first = self.env['nord.sync.config'].create({
            'company_uid': 'tenant-a',
            'cloud_webhook_url': 'http://localhost:8090/webhook',
        })
        _logger.info('[unique constraint] created config #%d for company %s', first.id, self.env.company.name)
        _logger.info('[unique constraint] creating a second config for the same company (expected: IntegrityError)')
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self.env['nord.sync.config'].create({
                'company_uid': 'tenant-a-bis',
                'cloud_webhook_url': 'http://localhost:8091/webhook',
            })
        _logger.info('[unique constraint] second create correctly raised IntegrityError')

    def test_create_or_update_for_company_creates_once(self):
        """First call creates a row scoped to the current company (manual test plan step 11)."""
        config = self.env['nord.sync.config']._create_or_update_for_company(
            self.env.company,
            {'company_uid': 'tenant-a', 'cloud_webhook_url': 'http://localhost:8090/webhook'},
        )
        _logger.info('[upsert] first call created config #%d for company %s', config.id, self.env.company.name)
        self.assertEqual(config.company_id, self.env.company)
        count = self.env['nord.sync.config'].search_count([('company_id', '=', self.env.company.id)])
        _logger.info('[upsert] config count for company %s is now %d (expected 1)', self.env.company.name, count)
        self.assertEqual(count, 1)

    def test_create_or_update_for_company_upserts(self):
        """A second call for the same company updates the existing row instead of creating a new one."""
        Config = self.env['nord.sync.config']
        first = Config._create_or_update_for_company(
            self.env.company,
            {'company_uid': 'tenant-a', 'cloud_webhook_url': 'http://localhost:8090/webhook'},
        )
        _logger.info('[upsert] first call created config #%d with webhook %s', first.id, first.cloud_webhook_url)
        second = Config._create_or_update_for_company(
            self.env.company,
            {'company_uid': 'tenant-a', 'cloud_webhook_url': 'http://localhost:9090/webhook'},
        )
        _logger.info('[upsert] second call returned config #%d with webhook %s', second.id, second.cloud_webhook_url)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.cloud_webhook_url, 'http://localhost:9090/webhook')
        count = Config.search_count([('company_id', '=', self.env.company.id)])
        _logger.info('[upsert] config count for company %s is still %d (expected 1, no duplicate)', self.env.company.name, count)
        self.assertEqual(count, 1)
