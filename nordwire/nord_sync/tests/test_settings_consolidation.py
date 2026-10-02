# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNordSyncSettingsConsolidation(TransactionCase):
    """Settings (the res.config.settings page), Job Stages, Job Stage
    Mapping, Payload Fields, and Automation Rules are real submenus under
    Nordwire > Configuration, not res.config.settings link-out buttons —
    each keeps its own access group under there, since Payload Fields is
    base.group_system-only (no group_nord_sync_manager row in
    ir.model.access.csv) while Job Stages/Job Stage Mapping/Automation
    Rules are Manager-level and Settings itself stays base.group_system
    (same gate the res.config.settings <app> block it opens already has).
    Sync Queue, Sync Failures, and Sync Inbox live under their own "Sync"
    menu folder (a later addition, separate from this Settings
    consolidation) as well as being reachable from Sync Overview buttons.
    """

    REMOVED_MENU_XMLIDS = [
        'nord_sync.menu_nord_sync_config',
    ]
    SYNC_GROUP_MENU_XMLIDS = [
        'nord_sync.menu_nord_sync_queue',
        'nord_sync.menu_nord_sync_failures',
        'nord_sync.menu_nord_sync_inbox',
    ]
    SETTINGS_SUBMENU_XMLIDS = [
        'nord_sync.menu_nord_sync_general_settings',
        'nord_sync.menu_nord_sync_job_stage',
        'nord_sync.menu_nord_sync_state_mapping',
        'nord_sync.menu_nord_sync_payload_field_config',
        'nord_sync.menu_nord_sync_automation_rules',
    ]
    MANAGER_SETTINGS_SUBMENU_XMLIDS = [
        'nord_sync.menu_nord_sync_job_stage',
        'nord_sync.menu_nord_sync_state_mapping',
        'nord_sync.menu_nord_sync_automation_rules',
    ]
    KEPT_ACTION_XMLIDS = [
        'nord_sync.action_nord_sync_config',
        'nord_sync.action_nord_sync_queue',
        'nord_sync.action_nord_sync_failures',
        'nord_sync.action_nord_sync_res_config_settings',
        'nord_sync.action_nord_sync_job_stage',
        'nord_sync.action_nord_sync_state_mapping',
        'nord_sync.action_nord_sync_payload_field_config',
        'nord_sync.action_nord_sync_automation_rules',
    ]

    def test_absorbed_menu_items_are_gone(self):
        for xmlid in self.REMOVED_MENU_XMLIDS:
            with self.assertRaises(ValueError):
                self.env.ref(xmlid)

    def test_sync_group_menu_items(self):
        group = self.env.ref('nord_sync.menu_nord_sync_group')
        self.assertEqual(group.name, 'Sync')
        self.assertEqual(group.parent_id, self.env.ref('nord_sync.menu_nord_sync_root'))
        for xmlid in self.SYNC_GROUP_MENU_XMLIDS:
            self.assertEqual(self.env.ref(xmlid).parent_id, group)

    def test_config_items_are_settings_submenus(self):
        settings = self.env.ref('nord_sync.menu_nord_sync_settings')
        root = self.env.ref('nord_sync.menu_nord_sync_root')
        self.assertEqual(settings.name, 'Configuration')
        self.assertEqual(settings.parent_id, root)
        for xmlid in self.SETTINGS_SUBMENU_XMLIDS:
            self.assertEqual(self.env.ref(xmlid).parent_id, settings)

    def test_manager_settings_submenus_keep_manager_group(self):
        manager_group = self.env.ref('nord_sync.group_nord_sync_manager')
        for xmlid in self.MANAGER_SETTINGS_SUBMENU_XMLIDS:
            self.assertIn(manager_group, self.env.ref(xmlid).groups_id)

    def test_payload_field_config_menu_is_system_only(self):
        manager_group = self.env.ref('nord_sync.group_nord_sync_manager')
        menu = self.env.ref('nord_sync.menu_nord_sync_payload_field_config')
        self.assertIn(self.env.ref('base.group_system'), menu.groups_id)
        self.assertNotIn(manager_group, menu.groups_id)

    def test_general_settings_menu_opens_res_config_settings(self):
        manager_group = self.env.ref('nord_sync.group_nord_sync_manager')
        menu = self.env.ref('nord_sync.menu_nord_sync_general_settings')
        self.assertEqual(menu.action.res_model, 'res.config.settings')
        self.assertIn(self.env.ref('base.group_system'), menu.groups_id)
        self.assertNotIn(manager_group, menu.groups_id)

    def test_absorbed_actions_still_exist(self):
        for xmlid in self.KEPT_ACTION_XMLIDS:
            self.assertTrue(self.env.ref(xmlid))

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

    def test_settings_form_renders_without_the_moved_buttons(self):
        # Forces the full inherited-view combination (base + nord_sync +
        # nord_sync_mrp res_config_settings_views.xml) to resolve, same as
        # actually opening Settings > Nordwire would.
        view = self.env['res.config.settings'].get_view(view_type='form')
        self.assertIn('nord_sync_job_naming_mode', view['arch'])
        self.assertIn('nord_sync_wake_mode', view['arch'])
        self.assertNotIn('Configure Job Stages', view['arch'])
        self.assertNotIn('Configure Job Stage Mapping', view['arch'])
        self.assertNotIn('Configure Payload Fields', view['arch'])
        self.assertNotIn('Configure Trigger Rules', view['arch'])

    def test_job_stage_and_mapping_actions_open_from_button(self):
        # Same mechanism the Sync Overview page uses to reach Sync Queue/
        # Sync Failures — proves the moved actions are still openable, not
        # just present as records.
        job_stage_action = self.env.ref('nord_sync.action_nord_sync_job_stage')
        state_mapping_action = self.env.ref('nord_sync.action_nord_sync_state_mapping')
        payload_field_action = self.env.ref('nord_sync.action_nord_sync_payload_field_config')
        self.assertEqual(job_stage_action.res_model, 'nord_sync.job.stage')
        self.assertEqual(state_mapping_action.res_model, 'nord_sync.state.mapping')
        self.assertEqual(payload_field_action.res_model, 'nord_sync.payload.field.config')
