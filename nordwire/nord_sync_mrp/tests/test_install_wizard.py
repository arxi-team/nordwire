# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

CONFIG_GET = 'odoo.addons.nord_sync.wizard.nord_sync_install_wizard.config.get'
VERSION_INFO = 'odoo.addons.nord_sync.wizard.nord_sync_install_wizard.release.version_info'
POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


def _patch_env(cron_threads=2, major_version=17):
    return patch(CONFIG_GET, return_value=cron_threads), patch(VERSION_INFO, (major_version, 0, 0, 'final', 0, ''))


@tagged('post_install', '-at_install')
class TestNordSyncInstallWizardMrp(TransactionCase):
    """mrp.production as the registered native source — generic wizard
    mechanism itself is tested in nord_sync/tests/test_install_wizard.py
    without any source addon installed.
    """

    def _new_wizard(self, cron_threads=2, major_version=17, **vals):
        cron_patch, version_patch = _patch_env(cron_threads, major_version)
        with cron_patch, version_patch:
            return self.env['nord_sync.install.wizard'].create(vals)

    def _map_line(self, wizard, source_value):
        return wizard.mapping_line_ids.filtered(lambda line: line.source_value == source_value)

    def test_default_mode_is_native_prefilled_from_mrp_production_state(self):
        wizard = self._new_wizard()
        self.assertEqual(wizard.job_stage_mode, 'native')
        state_field = self.env['mrp.production']._fields['state']
        expected = [label for _value, label in state_field.selection]
        self.assertEqual(wizard.job_stage_line_ids.mapped('name'), expected)

    def test_switching_to_both_combines_native_and_suggestion(self):
        wizard = self._new_wizard()
        wizard.job_stage_mode = 'both'
        wizard._onchange_job_stage_mode()
        names = wizard.job_stage_line_ids.mapped('name')
        self.assertIn('Confirmed', names)
        self.assertIn('Queued', names)

    def test_confirm_pushes_created_stages_to_queue(self):
        # Nothing pushes before Confirm — stages only become real records (and
        # therefore only enqueue/notify, via nord_sync.job.stage's own create
        # override) once config.enabled is actually True. Dedicated company
        # (not self.env.company, shared by every test in this class) so the
        # queue count below only reflects what this test itself pushed.
        company = self.env['res.company'].create({'name': 'Job Stage Push Test Co'})
        wizard = self._new_wizard(company_id=company.id, company_uid='new-uid')
        self.env['nord_sync.config']._set_cloud_base_url('http://cloud.example.com')
        with patch(POST_TARGET) as mocked_post:
            wizard.action_confirm()
        mocked_post.assert_called()
        entries = self.env['nord.sync.queue'].search([
            ('owner_res_model', '=', 'nord_sync.job.stage'), ('company_id', '=', company.id),
        ])
        self.assertEqual(len(entries), 6)  # mrp.production's 6 native states

    def test_confirm_creates_cancel_mapping(self):
        # No longer a dedicated "backward compat" seeding step — the 'cancel'
        # row is just one of every native state's own mapping row (native
        # mode auto-picks the 'Cancelled' job stage for it by name, see
        # _default_mapping_targets), created the same way as every other row.
        company = self.env['res.company'].create({'name': 'Job Stage Compat Test Co'})
        wizard = self._new_wizard(company_id=company.id, company_uid='new-uid')
        with patch(POST_TARGET):
            wizard.action_confirm()
        mapping = self.env['nord_sync.state.mapping'].search([
            ('company_id', '=', company.id), ('source_model', '=', 'mrp.production'), ('source_value', '=', 'cancel'),
        ])
        self.assertEqual(len(mapping), 1)
        self.assertEqual(mapping.target_job_stage_id.name, 'Cancelled')

    def test_mapping_has_one_row_per_native_state_not_just_confirm_cancel(self):
        # The client decides for every state, not just the two the shipped
        # Automation Rules happen to send today.
        wizard = self._new_wizard()
        state_field = self.env['mrp.production']._fields['state']
        self.assertEqual(
            sorted(wizard.mapping_line_ids.mapped('source_value')),
            sorted(value for value, _label in state_field.selection),
        )
        self.assertTrue(all(m == 'mrp.production' for m in wizard.mapping_line_ids.mapped('source_model')))

    def test_native_mode_every_row_defaults_to_its_own_same_named_stage(self):
        # _default_mapping_targets() pre-picks a stage whenever a row's own
        # source_value_label matches a job stage line by name — in native
        # mode job_stage_line_ids IS the list of mrp.production's own state
        # labels, so every row's own label always has a same-named stage to
        # match, not just Confirmed/Cancelled.
        wizard = self._new_wizard()
        state_labels = dict(self.env['mrp.production']._fields['state'].selection)
        for line in wizard.mapping_line_ids:
            self.assertEqual(line.target_job_stage_line_id.name, state_labels[line.source_value])

    def test_native_mode_defaults_confirmed_and_cancelled_stage_by_name(self):
        wizard = self._new_wizard()
        self.assertEqual(self._map_line(wizard, 'confirmed').target_job_stage_line_id.name, 'Confirmed')
        self.assertEqual(self._map_line(wizard, 'cancel').target_job_stage_line_id.name, 'Cancelled')

    def test_own_mode_has_no_name_match_leaves_mapping_targets_blank(self):
        wizard = self._new_wizard()
        wizard.job_stage_mode = 'own'
        wizard._onchange_job_stage_mode()
        self.assertFalse(self._map_line(wizard, 'confirmed').target_job_stage_line_id)
        self.assertFalse(self._map_line(wizard, 'cancel').target_job_stage_line_id)

    def test_switching_mode_back_and_forth_does_not_leave_stale_reference(self):
        wizard = self._new_wizard()
        original_line_id = self._map_line(wizard, 'confirmed').target_job_stage_line_id.id
        wizard.job_stage_mode = 'own'
        wizard._onchange_job_stage_mode()
        wizard.job_stage_mode = 'native'
        wizard._onchange_job_stage_mode()
        # A fresh line with the same name, not the (now-deleted) original id.
        confirmed_target = self._map_line(wizard, 'confirmed').target_job_stage_line_id
        self.assertEqual(confirmed_target.name, 'Confirmed')
        self.assertNotEqual(confirmed_target.id, original_line_id)

    def test_blank_row_creates_no_mapping_on_confirm(self):
        company = self.env['res.company'].create({'name': 'Job Stage Blank Row Test Co'})
        wizard = self._new_wizard(company_id=company.id, company_uid='new-uid')
        # 'own' mode: no default target_state, and its label ("To Close")
        # matches neither a native state label nor JOB_STAGE_SUGGESTED_NAMES
        # (unlike 'progress'/'In Progress' or 'done'/'Done', both of which
        # the suggested list also happens to contain) — so this row stays
        # genuinely blank on both sides.
        wizard.job_stage_mode = 'own'
        wizard._onchange_job_stage_mode()
        with patch(POST_TARGET):
            wizard.action_confirm()
        self.assertFalse(self.env['nord_sync.state.mapping'].search([
            ('company_id', '=', company.id), ('source_model', '=', 'mrp.production'),
            ('source_value', '=', 'to_close'),
        ]))

    def test_confirm_creates_confirmed_and_cancelled_mappings_with_stages(self):
        company = self.env['res.company'].create({'name': 'Job Stage Mapping Test Co'})
        wizard = self._new_wizard(company_id=company.id, company_uid='new-uid')
        with patch(POST_TARGET):
            wizard.action_confirm()
        mappings = self.env['nord_sync.state.mapping'].search([('company_id', '=', company.id)])
        by_value = {m.source_value: m for m in mappings}
        self.assertEqual(by_value['confirmed'].target_job_stage_id.name, 'Confirmed')
        self.assertEqual(by_value['cancel'].target_job_stage_id.name, 'Cancelled')
