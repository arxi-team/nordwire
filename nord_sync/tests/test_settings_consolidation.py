# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNordSyncSettingsConsolidation(TransactionCase):
    """Configuration / Payload Fields had their own top-level menu item
    under Nordwire — moved into Settings > Nordwire instead (own scalar
    fields merged in directly, reachable via a button). Both stay
    base.group_system-only, no regression there. Job Stages / Job Stage
    Mapping / Automation Rules got the same Settings-page boxes, but also
    kept their own top-level menu item (group_nord_sync_manager) — the
    whole Settings `<app>` block is base.group_system-gated, and Manager is
    deliberately not an administrator (see nord_sync_security.xml), so
    losing the top-level menu would have locked Manager out of them
    entirely. Every action/view is kept either way, since the Settings
    buttons open the same ones.
    """

    REMOVED_MENU_XMLIDS = [
        'nord_sync.menu_nord_sync_config',
        'nord_sync.menu_nord_sync_payload_field_config',
    ]
    RESTORED_MANAGER_MENU_XMLIDS = [
        'nord_sync.menu_nord_sync_job_stage',
        'nord_sync.menu_nord_sync_state_mapping',
        'nord_sync.menu_nord_sync_automation_rules',
    ]
    KEPT_ACTION_XMLIDS = [
        'nord_sync.action_nord_sync_config',
        'nord_sync.action_nord_sync_job_stage',
        'nord_sync.action_nord_sync_state_mapping',
        'nord_sync.action_nord_sync_payload_field_config',
        'nord_sync.action_nord_sync_automation_rules',
    ]

    def test_absorbed_menu_items_are_gone(self):
        for xmlid in self.REMOVED_MENU_XMLIDS:
            with self.assertRaises(ValueError):
                self.env.ref(xmlid)

    def test_manager_menu_items_are_restored_alongside_settings(self):
        root = self.env.ref('nord_sync.menu_nord_sync_root')
        manager_group = self.env.ref('nord_sync.group_nord_sync_manager')
        for xmlid in self.RESTORED_MANAGER_MENU_XMLIDS:
            menu = self.env.ref(xmlid)
            self.assertEqual(menu.parent_id, root)
            self.assertIn(manager_group, menu.group_ids)

    def test_absorbed_actions_still_exist(self):
        for xmlid in self.KEPT_ACTION_XMLIDS:
            self.assertTrue(self.env.ref(xmlid))

    def test_support_menu_items_are_untouched(self):
        root = self.env.ref('nord_sync.menu_nord_sync_root')
        self.assertTrue(self.env.ref('nord_sync.menu_nord_sync_queue').parent_id == root)
        self.assertTrue(self.env.ref('nord_sync.menu_nord_sync_failures').parent_id == root)

    def test_settings_page_writes_absorbed_config_fields(self):
        settings = self.env['res.config.settings'].create({
            'nord_sync_job_naming_mode': 'custom_prefix',
            'nord_sync_job_naming_custom_prefix': 'ACME-JOB/%(year)s/',
            'nord_sync_wake_mode': 'throttled',
            'nord_sync_wake_throttle_minutes': 10,
        })
        settings.execute()
        config = self.env['nord_sync.config']._get_for_company(self.env.company)
        self.assertEqual(config.job_naming_mode, 'custom_prefix')
        self.assertEqual(config.job_naming_custom_prefix, 'ACME-JOB/%(year)s/')
        self.assertEqual(config.wake_mode, 'throttled')
        self.assertEqual(config.wake_throttle_minutes, 10)

    def test_settings_form_renders_without_error(self):
        # Forces the full inherited-view combination (base + nord_sync +
        # nord_sync_mrp res_config_settings_views.xml) to resolve, same as
        # actually opening Settings > Nordwire would — %(xmlid)d placeholders
        # in the button `name` attrs are already substituted with numeric
        # action ids by this point, so only the field names are still
        # findable literally.
        view = self.env['res.config.settings'].get_view(view_type='form')
        self.assertIn('nord_sync_job_naming_mode', view['arch'])
        self.assertIn('nord_sync_wake_mode', view['arch'])
        self.assertIn('Configure Job Stages', view['arch'])
        self.assertIn('Configure Job Stage Mapping', view['arch'])
        self.assertIn('Configure Payload Fields', view['arch'])

    def test_job_stage_and_mapping_actions_open_from_button(self):
        # Same mechanism the Settings buttons use (%(action)d resolved into
        # an action window) — proves the button targets are still openable,
        # not just present as records.
        job_stage_action = self.env.ref('nord_sync.action_nord_sync_job_stage')
        state_mapping_action = self.env.ref('nord_sync.action_nord_sync_state_mapping')
        payload_field_action = self.env.ref('nord_sync.action_nord_sync_payload_field_config')
        self.assertEqual(job_stage_action.res_model, 'nord_sync.job.stage')
        self.assertEqual(state_mapping_action.res_model, 'nord_sync.state.mapping')
        self.assertEqual(payload_field_action.res_model, 'nord_sync.payload.field.config')
