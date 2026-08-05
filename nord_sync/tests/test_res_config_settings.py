# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestResConfigSettingsNordSync(TransactionCase):

    def test_compute_gets_or_creates_config_for_company(self):
        settings = self.env['res.config.settings'].create({})
        self.assertTrue(settings.nord_sync_config_id)
        self.assertEqual(settings.nord_sync_config_id.company_id, self.env.company)

    def test_save_writes_to_nord_sync_config(self):
        settings = self.env['res.config.settings'].create({
            'nord_sync_enabled': True,
            'nord_sync_company_uid': 'settings-uid',
            'nord_sync_cloud_webhook_url': 'http://cloud.example.com/webhook',
        })
        settings.execute()
        config = self.env['nord_sync.config']._get_for_company(self.env.company)
        self.assertTrue(config.enabled)
        self.assertEqual(config.company_uid, 'settings-uid')
        self.assertEqual(config.cloud_webhook_url, 'http://cloud.example.com/webhook')

    def test_save_updates_existing_config_instead_of_duplicating(self):
        self.env['nord_sync.config'].create({'company_id': self.env.company.id, 'company_uid': 'old-uid'})
        settings = self.env['res.config.settings'].create({'nord_sync_company_uid': 'new-uid'})
        settings.execute()
        configs = self.env['nord_sync.config'].search([('company_id', '=', self.env.company.id)])
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs.company_uid, 'new-uid')

    def test_open_install_wizard_action_returns_wizard_action(self):
        settings = self.env['res.config.settings'].create({})
        action = settings.action_open_nord_sync_install_wizard()
        self.assertEqual(action['res_model'], 'nord_sync.install.wizard')
        self.assertEqual(action['context']['default_company_id'], self.env.company.id)
