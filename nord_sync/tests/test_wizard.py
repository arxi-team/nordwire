import logging
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)

VERSION_INFO_TARGET = 'odoo.addons.nord_sync.wizard.nord_sync_setup_wizard.odoo.release.version_info'


@tagged('post_install', '-at_install')
class TestNordSyncSetupWizard(TransactionCase):

    def _new_wizard(self):
        return self.env['nord.sync.setup.wizard'].create({})

    # -- pre-flight checks (manual test plan steps 5-6) ------------------------

    def test_preflight_all_checks_pass(self):
        with patch(VERSION_INFO_TARGET, (19, 0, 0, 'final', 0, '')):
            wizard = self._new_wizard()
            _logger.info(
                '[preflight] odoo_version_supported=%s warning=%r',
                wizard.odoo_version_supported, wizard.preflight_warning,
            )
            self.assertTrue(wizard.odoo_version_supported)
            self.assertFalse(wizard.preflight_warning)

    def test_preflight_warns_when_version_unsupported(self):
        with patch(VERSION_INFO_TARGET, (17, 0, 0, 'final', 0, '')):
            wizard = self._new_wizard()
            _logger.info('[preflight] Odoo version 17.0 (unsupported) -> warning: %r', wizard.preflight_warning)
            self.assertFalse(wizard.odoo_version_supported)
            self.assertIn('not a supported', wizard.preflight_warning)

    # -- save/validation (manual test plan steps 8-9, 11) ----------------------

    def test_save_requires_tenant_uid_and_webhook_url(self):
        wizard = self._new_wizard()
        _logger.info('[save] saving wizard with no tenant uid / webhook url (expected: UserError)')
        with self.assertRaises(UserError):
            wizard.action_save_config()
        _logger.info('[save] correctly raised UserError')

    def test_save_rejects_url_without_scheme(self):
        wizard = self._new_wizard()
        wizard.write({'company_uid': 'tenant-a', 'cloud_webhook_url': 'localhost:8090/webhook'})
        _logger.info('[save] saving wizard with schemeless url %r (expected: UserError)', wizard.cloud_webhook_url)
        with self.assertRaises(UserError):
            wizard.action_save_config()
        _logger.info('[save] correctly raised UserError')

    def test_save_creates_config(self):
        wizard = self._new_wizard()
        wizard.write({
            'company_uid': 'tenant-a',
            'cloud_webhook_url': 'http://localhost:8090/webhook',
            'mo_filter_criteria': 'state = done',
        })
        wizard.action_save_config()
        config = self.env['nord.sync.config'].search([('company_id', '=', self.env.company.id)])
        _logger.info(
            '[save] created config #%d: uid=%s webhook=%s filter=%r',
            config.id, config.company_uid, config.cloud_webhook_url, config.mo_filter_criteria,
        )
        self.assertEqual(len(config), 1)
        self.assertEqual(config.company_uid, 'tenant-a')
        self.assertEqual(config.cloud_webhook_url, 'http://localhost:8090/webhook')
        self.assertEqual(config.mo_filter_criteria, 'state = done')

    def test_save_wires_the_native_webhook_action_url(self):
        """action_save_config must point the shared ir.actions.server (Odoo->Cloud
        leg) at the configured URL, not just store it on nord.sync.config."""
        wizard = self._new_wizard()
        wizard.write({'company_uid': 'tenant-a', 'cloud_webhook_url': 'http://localhost:8090/webhook'})
        wizard.action_save_config()
        action = self.env.ref('nord_sync.webhook_action_queue_to_cloud')
        _logger.info('[save] native webhook action url=%s (expected http://localhost:8090/webhook)', action.webhook_url)
        self.assertEqual(action.webhook_url, 'http://localhost:8090/webhook')

    def test_save_upserts_existing_config(self):
        first = self._new_wizard()
        first.write({'company_uid': 'tenant-a', 'cloud_webhook_url': 'http://localhost:8090/webhook'})
        first.action_save_config()
        _logger.info('[save] first wizard saved webhook=http://localhost:8090/webhook')

        second = self._new_wizard()
        second.write({'company_uid': 'tenant-a', 'cloud_webhook_url': 'http://localhost:9090/webhook'})
        second.action_save_config()
        _logger.info('[save] second wizard saved webhook=http://localhost:9090/webhook for the same tenant')

        configs = self.env['nord.sync.config'].search([('company_id', '=', self.env.company.id)])
        _logger.info(
            '[save] config count for company: %d (expected 1), final webhook: %s',
            len(configs), configs.cloud_webhook_url,
        )
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs.cloud_webhook_url, 'http://localhost:9090/webhook')
