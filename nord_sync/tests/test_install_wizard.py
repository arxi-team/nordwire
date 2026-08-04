# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

CONFIG_GET = 'odoo.addons.nord_sync.wizard.nord_sync_install_wizard.config.get'
VERSION_INFO = 'odoo.addons.nord_sync.wizard.nord_sync_install_wizard.release.version_info'


def _patch_env(cron_threads=2, major_version=19):
    return patch(CONFIG_GET, return_value=cron_threads), patch(VERSION_INFO, (major_version, 0, 0, 'final', 0, ''))


@tagged('post_install', '-at_install')
class TestNordSyncInstallWizard(TransactionCase):

    def test_default_get_prefills_from_existing_company_config(self):
        self.env.company.write({
            'nord_sync_company_uid': 'existing-uid',
            'nord_sync_cloud_webhook_url': 'http://cloud.example.com/webhook',
        })
        cron_patch, version_patch = _patch_env()
        with cron_patch, version_patch:
            wizard = self.env['nord_sync.install.wizard'].create({})
        self.assertEqual(wizard.company_uid, 'existing-uid')
        self.assertEqual(wizard.cloud_webhook_url, 'http://cloud.example.com/webhook')

    def test_preflight_ok_when_cron_active_and_version_supported(self):
        cron_patch, version_patch = _patch_env(cron_threads=2, major_version=19)
        with cron_patch, version_patch:
            wizard = self.env['nord_sync.install.wizard'].create({
                'company_uid': 'uid', 'cloud_webhook_url': 'http://cloud.example.com/webhook',
            })
        self.assertTrue(wizard.preflight_ok)
        self.assertTrue(wizard.cron_active)
        self.assertTrue(wizard.odoo_version_supported)

    def test_preflight_fails_when_cron_disabled(self):
        cron_patch, version_patch = _patch_env(cron_threads=0, major_version=19)
        with cron_patch, version_patch:
            wizard = self.env['nord_sync.install.wizard'].create({
                'company_uid': 'uid', 'cloud_webhook_url': 'http://cloud.example.com/webhook',
            })
        self.assertFalse(wizard.preflight_ok)
        self.assertFalse(wizard.cron_active)
        self.assertIn('cron', wizard.preflight_message.lower())

    def test_preflight_fails_when_version_unsupported(self):
        cron_patch, version_patch = _patch_env(cron_threads=2, major_version=17)
        with cron_patch, version_patch:
            wizard = self.env['nord_sync.install.wizard'].create({
                'company_uid': 'uid', 'cloud_webhook_url': 'http://cloud.example.com/webhook',
            })
        self.assertFalse(wizard.preflight_ok)
        self.assertFalse(wizard.odoo_version_supported)

    def test_confirm_writes_company_config(self):
        cron_patch, version_patch = _patch_env()
        with cron_patch, version_patch:
            wizard = self.env['nord_sync.install.wizard'].create({
                'company_uid': 'new-uid',
                'cloud_webhook_url': 'http://cloud.example.com/new-webhook',
            })
            wizard.action_confirm()
        self.assertTrue(self.env.company.nord_sync_enabled)
        self.assertEqual(self.env.company.nord_sync_company_uid, 'new-uid')
        self.assertEqual(self.env.company.nord_sync_cloud_webhook_url, 'http://cloud.example.com/new-webhook')

    def test_confirm_raises_when_preflight_not_ok(self):
        cron_patch, version_patch = _patch_env(cron_threads=0)
        with cron_patch, version_patch:
            wizard = self.env['nord_sync.install.wizard'].create({
                'company_uid': 'new-uid',
                'cloud_webhook_url': 'http://cloud.example.com/new-webhook',
            })
            with self.assertRaises(UserError):
                wizard.action_confirm()
        self.assertFalse(self.env.company.nord_sync_enabled)

    def test_refresh_preflight_picks_up_fixed_environment(self):
        cron_patch, version_patch = _patch_env(cron_threads=0)
        with cron_patch, version_patch:
            wizard = self.env['nord_sync.install.wizard'].create({
                'company_uid': 'uid', 'cloud_webhook_url': 'http://cloud.example.com/webhook',
            })
        self.assertFalse(wizard.preflight_ok)

        cron_patch_fixed, version_patch_fixed = _patch_env(cron_threads=2)
        with cron_patch_fixed, version_patch_fixed:
            wizard.action_refresh_preflight()
        self.assertTrue(wizard.preflight_ok)
