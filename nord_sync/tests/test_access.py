import logging

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestNordSyncAccess(TransactionCase):
    """Group-based access control (manual test plan steps 2-4)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, login='nord_manager', groups='base.group_user,nord_sync.group_nord_sync_manager',
        )
        cls.integration = new_test_user(
            cls.env, login='nord_integration', groups='base.group_user,nord_sync.group_nord_sync_integration',
        )
        cls.plain_user = new_test_user(cls.env, login='nord_plain', groups='base.group_user')

        cls.config = cls.env['nord.sync.config'].create({
            'company_uid': 'tenant-a',
            'cloud_webhook_url': 'http://localhost:8090/webhook',
        })
        cls.queue_entry = cls.env['nord.sync.queue']._push(
            cls.env.company.id, 'nord_sync.test', 'create', 0, {},
        )
        _logger.info(
            '[setUpClass] created users manager=%s integration=%s plain=%s, config#%d, queue_entry#%d',
            cls.manager.login, cls.integration.login, cls.plain_user.login,
            cls.config.id, cls.queue_entry.id,
        )

    def test_manager_has_full_crud_on_queue_and_config(self):
        _logger.info('[manager/queue] creating a queue entry as the manager user')
        queue_as_manager = self.env['nord.sync.queue'].with_user(self.manager)
        record = queue_as_manager.create({
            'company_id': self.env.company.id, 'model_name': 'x', 'operation': 'create', 'res_id': 1,
        })
        _logger.info('[manager/queue] created queue entry #%d, now writing to it', record.id)
        record.write({'company_uid': 'edited'})
        _logger.info('[manager/queue] reading queue entry #%d', record.id)
        record.read(['company_uid'])
        _logger.info('[manager/queue] unlinking queue entry #%d', record.id)
        record.unlink()

        _logger.info('[manager/config] reading and writing config #%d', self.config.id)
        config_as_manager = self.config.with_user(self.manager)
        config_as_manager.read(['cloud_webhook_url'])
        config_as_manager.write({'mo_filter_criteria': 'x'})
        _logger.info('[manager] full CRUD on queue and config succeeded as expected')

    def test_integration_group_is_read_only_on_queue(self):
        record = self.queue_entry.with_user(self.integration)
        _logger.info('[integration/queue] reading queue entry #%d (expected: allowed)', record.id)
        record.read(['company_uid'])  # allowed
        _logger.info('[integration/queue] attempting write on #%d (expected: AccessError)', record.id)
        with self.assertRaises(AccessError):
            record.write({'company_uid': 'nope'})
        _logger.info('[integration/queue] attempting create (expected: AccessError)')
        with self.assertRaises(AccessError):
            self.env['nord.sync.queue'].with_user(self.integration).create({
                'company_id': self.env.company.id, 'model_name': 'x', 'operation': 'create', 'res_id': 1,
            })
        _logger.info('[integration/queue] attempting unlink on #%d (expected: AccessError)', record.id)
        with self.assertRaises(AccessError):
            record.unlink()
        _logger.info('[integration/queue] confirmed read-only access as expected')

    def test_integration_group_is_read_only_on_config(self):
        config = self.config.with_user(self.integration)
        _logger.info('[integration/config] reading config #%d (expected: allowed)', config.id)
        config.read(['cloud_webhook_url'])  # allowed
        _logger.info('[integration/config] attempting write on #%d (expected: AccessError)', config.id)
        with self.assertRaises(AccessError):
            config.write({'mo_filter_criteria': 'x'})
        _logger.info('[integration/config] confirmed read-only access as expected')

    def test_plain_internal_user_has_no_access_to_queue_or_config(self):
        _logger.info(
            '[plain user] attempting to read queue entry #%d (expected: AccessError)', self.queue_entry.id,
        )
        with self.assertRaises(AccessError):
            self.queue_entry.with_user(self.plain_user).read(['company_uid'])
        _logger.info(
            '[plain user] attempting to read config #%d (expected: AccessError)', self.config.id,
        )
        with self.assertRaises(AccessError):
            self.config.with_user(self.plain_user).read(['cloud_webhook_url'])
        _logger.info('[plain user] confirmed no access to queue or config as expected')

    def test_menu_is_restricted_to_manager_group(self):
        """Proxy check for manual test plan steps 2-3 (menu visibility is UI-only)."""
        menu = self.env.ref('nord_sync.nord_sync_menu_root')
        _logger.info(
            '[menu] checking that group %s is among menu groups: %s',
            self.env.ref('nord_sync.group_nord_sync_manager').full_name, menu.group_ids.mapped('full_name'),
        )
        self.assertIn(self.env.ref('nord_sync.group_nord_sync_manager'), menu.group_ids)
        _logger.info('[menu] manager group is correctly attached to the root menu')
