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

    def _new_wizard(self, cron_threads=2, major_version=19, **vals):
        cron_patch, version_patch = _patch_env(cron_threads, major_version)
        with cron_patch, version_patch:
            return self.env['nord_sync.install.wizard'].create(vals)

    # ── default_get / prefill ────────────────────────────────────────────────

    def test_default_get_prefills_from_existing_config(self):
        self.env['nord_sync.config'].create({
            'company_id': self.env.company.id,
            'company_uid': 'existing-uid',
        })
        wizard = self._new_wizard()
        self.assertEqual(wizard.company_uid, 'existing-uid')

    def test_default_get_starts_on_preflight_step(self):
        wizard = self._new_wizard()
        self.assertEqual(wizard.state, 'step_preflight')

    # ── Step 1: pre-flight ───────────────────────────────────────────────────

    def test_preflight_ok_when_cron_active_and_version_supported(self):
        wizard = self._new_wizard(cron_threads=2, major_version=19)
        self.assertTrue(wizard.preflight_ok)
        self.assertTrue(wizard.cron_active)
        self.assertTrue(wizard.odoo_version_supported)
        self.assertTrue(wizard.show_next)

    def test_preflight_fails_when_cron_disabled(self):
        wizard = self._new_wizard(cron_threads=0)
        self.assertFalse(wizard.preflight_ok)
        self.assertFalse(wizard.cron_active)
        self.assertIn('cron', wizard.preflight_message.lower())
        self.assertFalse(wizard.show_next)

    def test_preflight_fails_when_version_unsupported(self):
        wizard = self._new_wizard(major_version=17)
        self.assertFalse(wizard.preflight_ok)
        self.assertFalse(wizard.odoo_version_supported)

    def test_next_step_blocked_when_preflight_not_ok(self):
        wizard = self._new_wizard(cron_threads=0)
        with self.assertRaises(UserError):
            wizard.action_next_step()
        self.assertEqual(wizard.state, 'step_preflight')

    def test_refresh_preflight_picks_up_fixed_environment(self):
        wizard = self._new_wizard(cron_threads=0)
        self.assertFalse(wizard.preflight_ok)
        cron_patch_fixed, version_patch_fixed = _patch_env(cron_threads=2)
        with cron_patch_fixed, version_patch_fixed:
            wizard.action_refresh_preflight()
        self.assertTrue(wizard.preflight_ok)

    # ── Step machine navigation ──────────────────────────────────────────────

    def test_next_step_advances_from_preflight_to_connection(self):
        wizard = self._new_wizard()
        wizard.action_next_step()
        self.assertEqual(wizard.state, 'step_connection')
        self.assertTrue(wizard.show_previous)

    def test_next_step_blocked_on_connection_without_required_fields(self):
        wizard = self._new_wizard()
        wizard.action_next_step()  # -> step_connection
        with self.assertRaises(UserError):
            wizard.action_next_step()
        self.assertEqual(wizard.state, 'step_connection')

    def test_next_step_advances_to_finish_with_fields_filled(self):
        wizard = self._new_wizard(company_uid='new-uid')
        wizard.action_next_step()  # -> step_connection
        wizard.action_next_step()  # -> step_finish
        self.assertEqual(wizard.state, 'step_finish')
        self.assertTrue(wizard.show_finish)
        self.assertFalse(wizard.show_next)

    def test_previous_step_goes_back(self):
        wizard = self._new_wizard()
        wizard.action_next_step()  # -> step_connection
        wizard.action_previous_step()
        self.assertEqual(wizard.state, 'step_preflight')

    # ── Step 3: confirm ──────────────────────────────────────────────────────

    def test_confirm_writes_nord_sync_config(self):
        wizard = self._new_wizard(company_uid='new-uid')
        wizard.action_confirm()
        config = self.env['nord_sync.config']._get_for_company(self.env.company)
        self.assertTrue(config.enabled)
        self.assertEqual(config.company_uid, 'new-uid')

    def test_confirm_updates_existing_config_instead_of_duplicating(self):
        self.env['nord_sync.config'].create({'company_id': self.env.company.id, 'company_uid': 'old-uid'})
        wizard = self._new_wizard(company_uid='new-uid')
        wizard.action_confirm()
        configs = self.env['nord_sync.config'].search([('company_id', '=', self.env.company.id)])
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs.company_uid, 'new-uid')

    def test_confirm_hands_off_to_automation_rule(self):
        wizard = self._new_wizard(company_uid='new-uid')
        action = wizard.action_confirm()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'base.automation')
        self.assertEqual(action['res_id'], self.env.ref('nord_sync.automation_mrp_production_confirmed').id)

    def test_confirm_raises_when_preflight_not_ok(self):
        wizard = self._new_wizard(cron_threads=0, company_uid='new-uid')
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertFalse(self.env['nord_sync.config']._get_for_company(self.env.company))
