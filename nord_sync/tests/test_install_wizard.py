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
    """Generic wizard mechanism only — no Nord Sync Source addon assumed
    installed. Tests that depend on a real native source (e.g. mrp.production's states)
    live in that source's own addon — see nord_sync_mrp/tests/
    test_install_wizard.py.
    """

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

    def test_next_step_advances_from_preflight_to_sources(self):
        wizard = self._new_wizard()
        wizard.action_next_step()
        self.assertEqual(wizard.state, 'step_sources')
        self.assertTrue(wizard.show_previous)

    def test_next_step_advances_from_sources_to_connection(self):
        wizard = self._new_wizard()
        wizard.action_next_step()  # -> step_sources
        wizard.action_next_step()  # -> step_connection
        self.assertEqual(wizard.state, 'step_connection')

    def test_next_step_blocked_on_connection_without_required_fields(self):
        wizard = self._new_wizard()
        wizard.action_next_step()  # -> step_sources
        wizard.action_next_step()  # -> step_connection
        with self.assertRaises(UserError):
            wizard.action_next_step()
        self.assertEqual(wizard.state, 'step_connection')

    def test_next_step_advances_to_job_stages_with_fields_filled(self):
        wizard = self._new_wizard(company_uid='new-uid')
        wizard.action_next_step()  # -> step_sources
        wizard.action_next_step()  # -> step_connection
        wizard.action_next_step()  # -> step_job_stages
        self.assertEqual(wizard.state, 'step_job_stages')
        self.assertTrue(wizard.show_next)

    def test_next_step_advances_to_finish_with_fields_filled(self):
        wizard = self._new_wizard(company_uid='new-uid')
        wizard.action_next_step()  # -> step_sources
        wizard.action_next_step()  # -> step_connection
        wizard.action_next_step()  # -> step_job_stages
        wizard.action_next_step()  # -> step_finish
        self.assertEqual(wizard.state, 'step_finish')
        self.assertTrue(wizard.show_finish)
        self.assertFalse(wizard.show_next)

    def test_previous_step_goes_back(self):
        wizard = self._new_wizard()
        wizard.action_next_step()  # -> step_sources
        wizard.action_previous_step()
        self.assertEqual(wizard.state, 'step_preflight')

    # ── Step 2: sources ──────────────────────────────────────────────────

    def test_sources_discovered_by_naming_convention_only(self):
        # Not a hardcoded list — any ir.module.module named nord_sync_* shows
        # up, nord_sync itself never does.
        wizard = self._new_wizard()
        names = wizard.available_source_ids.module_id.mapped('name')
        self.assertNotIn('nord_sync', names)
        self.assertTrue(all(name.startswith('nord_sync_') for name in names))

    def test_already_installed_source_is_preselected_and_locked(self):
        wizard = self._new_wizard()
        installed = wizard.available_source_ids.filtered('installed')
        if not installed:
            self.skipTest('no Nord Sync Source addon installed in this test DB')
        self.assertTrue(all(installed.mapped('selected')))

    def test_confirm_sources_advances_without_selection(self):
        # Nothing checked (or only already-installed, locked rows) — behaves
        # exactly like the generic Next, no install attempted.
        wizard = self._new_wizard()
        wizard.action_next_step()  # -> step_sources
        wizard.available_source_ids.selected = False
        with patch.object(type(self.env['ir.module.module']), 'button_immediate_install') as mocked_install:
            wizard.action_confirm_sources()
        mocked_install.assert_not_called()
        self.assertEqual(wizard.state, 'step_connection')

    def test_confirm_sources_installs_selected_uninstalled_modules(self):
        wizard = self._new_wizard()
        wizard.action_next_step()  # -> step_sources
        candidate = wizard.available_source_ids.filtered(lambda line: not line.installed)[:1]
        if not candidate:
            self.skipTest('every discovered Nord Sync Source addon is already installed in this test DB')
        candidate.selected = True
        install_result = {'type': 'ir.actions.act_window', 'res_model': self.env.company._name}
        with patch.object(
            type(self.env['ir.module.module']), 'button_immediate_install', return_value=install_result,
        ) as mocked_install:
            result = wizard.action_confirm_sources()
        mocked_install.assert_called_once()
        # button_immediate_install()'s own return value comes back untouched
        # — its result is whatever ir.module.module.next() decides (the
        # resume todo's action, once installed for real), never something
        # this method second-guesses or reinterprets.
        self.assertEqual(result, install_result)
        # Advanced before the install call, same as the generic Next would
        # — so a client landing back on this record via the resume todo
        # continues on Connection, never re-offered the Sources step for
        # modules it just installed.
        self.assertEqual(wizard.state, 'step_connection')
        # The resume action/todo point at this exact record, ready for
        # ir.module.module.next() to pick up.
        resume_action = self.env.ref('nord_sync.action_nord_sync_install_wizard_resume')
        self.assertEqual(resume_action.context, repr({'res_id': wizard.id}))
        resume_todo = self.env.ref('nord_sync.todo_nord_sync_install_wizard_resume')
        self.assertEqual(resume_todo.state, 'open')

    # ── Step 3: job stages ───────────────────────────────────────────────
    # 'own' mode only here — no dependency on any native source being registered.

    def test_switching_to_own_replaces_lines_with_suggestion(self):
        wizard = self._new_wizard()
        wizard.job_stage_mode = 'own'
        wizard._onchange_job_stage_mode()
        self.assertEqual(
            wizard.job_stage_line_ids.mapped('name'),
            ['Queued', 'In Progress', 'Quality Check', 'Done'],
        )

    def test_reentering_job_stages_preserves_edits_when_sources_unchanged(self):
        # Going back to this step (e.g. from Finish) and forward again, with
        # nothing installed meanwhile, must not silently discard a rename.
        wizard = self._new_wizard(company_uid='new-uid')
        wizard.action_next_step()  # -> step_sources
        wizard.action_confirm_sources()  # -> step_connection (nothing selected to install)
        wizard.action_next_step()  # -> step_job_stages
        wizard.job_stage_line_ids[0].name = 'Renamed Stage'
        wizard.action_next_step()  # -> step_finish
        wizard.action_previous_step()  # -> step_job_stages again
        self.assertEqual(wizard.job_stage_line_ids[0].name, 'Renamed Stage')

    def test_reentering_job_stages_refreshes_when_source_set_changed(self):
        # A source installed via the Sources step earlier in this same
        # wizard isn't reflected in mapping_line_ids until this step is
        # (re-)entered — this is the mechanism, exercised with a stand-in
        # source (res.partner.type, always present) rather than a real Nord
        # Sync Source addon. Doesn't assume anything about what's already
        # registered in this test DB (nord_sync_mrp may or may not be
        # installed alongside this base suite) — only that the fake source
        # is genuinely new, so the refresh must fire.
        wizard = self._new_wizard(company_uid='new-uid')
        wizard.action_next_step()  # -> step_sources
        wizard.action_confirm_sources()  # -> step_connection
        wizard.action_next_step()  # -> step_job_stages
        self.assertNotIn('res.partner', wizard.mapping_line_ids.mapped('source_model'))
        fake_source = [{'source_model': 'res.partner', 'source_field': 'type', 'label': 'Fake'}]
        with patch.object(type(wizard), '_nord_sync_available_native_sources', return_value=fake_source):
            wizard.action_previous_step()  # -> step_connection
            wizard.action_next_step()  # -> step_job_stages, re-triggers the refresh
        self.assertEqual(set(wizard.mapping_line_ids.mapped('source_model')), {'res.partner'})

    def test_mapping_line_source_value_label_keeps_each_sources_own_label_on_collision(self):
        # Two registered sources sharing a raw value (e.g. purchase.order and
        # stock.picking both have a 'draft' state) each get their OWN correct
        # label on their own row — source_value_label is resolved per-row
        # from that row's own source, not from a shared cross-source list, so
        # there's no collision to dedup and no wrong label on either row.
        fake_sources = [
            {'source_model': 'res.partner', 'source_field': 'type', 'label': 'Fake A'},
            {'source_model': 'res.partner', 'source_field': 'type', 'label': 'Fake B'},
        ]
        with patch.object(type(self.env['nord_sync.install.wizard']), '_nord_sync_available_native_sources', return_value=fake_sources):
            vals = self.env['nord_sync.install.wizard']._mapping_line_vals()
        partner_type_selection = dict(self.env['res.partner']._fields['type'].selection)
        self.assertTrue(vals)
        for line_vals in vals:
            self.assertEqual(line_vals['source_value_label'], partner_type_selection[line_vals['source_value']])

    def test_emptying_lines_stays_empty_after_confirm(self):
        # Optional by design — a user who deliberately clears
        # the list must end up with zero stages, not have it silently
        # repopulated (default_get only runs once, at wizard creation).
        company = self.env['res.company'].create({'name': 'Job Stage Empty Test Co'})
        wizard = self._new_wizard(company_id=company.id, company_uid='new-uid')
        wizard.job_stage_line_ids.unlink()
        with patch('odoo.addons.nord_sync.models.nord_sync_config.requests.post'):
            wizard.action_confirm()
        self.assertFalse(self.env['nord_sync.job.stage'].search([('company_id', '=', company.id)]))

    def test_confirm_creates_real_stages_from_lines(self):
        company = self.env['res.company'].create({'name': 'Job Stage Create Test Co'})
        wizard = self._new_wizard(company_id=company.id, company_uid='new-uid')
        wizard.job_stage_mode = 'own'
        wizard._onchange_job_stage_mode()
        with patch('odoo.addons.nord_sync.models.nord_sync_config.requests.post'):
            wizard.action_confirm()
        stages = self.env['nord_sync.job.stage'].search(
            [('company_id', '=', company.id)], order='sequence',
        )
        self.assertEqual(stages.mapped('name'), ['Queued', 'In Progress', 'Quality Check', 'Done'])

    def test_mapping_line_fields_all_present_in_form_view(self):
        # Real bug found live (2026-08-10): a field the arch never references
        # gets dropped from the web client's save round-trip even when
        # default_get sets it server-side — source_value ended up NULL on
        # every row, tripping its own required=True. This directly checks
        # the mechanism that broke, not just the Python-side value — pure
        # view-structure check, no native source needed.
        from lxml import etree
        view = self.env['nord_sync.install.wizard'].get_view(
            view_id=self.env.ref('nord_sync.view_nord_sync_install_wizard_form').id, view_type='form',
        )
        arch = etree.fromstring(view['arch'])
        list_el = arch.xpath("//field[@name='mapping_line_ids']")[0].find('list')
        field_names = {f.get('name') for f in list_el.findall('field')}
        self.assertIn('source_value', field_names)
        self.assertIn('source_model', field_names)

    # ── Step 4: confirm ──────────────────────────────────────────────────────

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

    def test_confirm_hands_off_to_automation_rules_list(self):
        # The base wizard can't assume any one Nordwire Source's
        # automation rule exists.
        wizard = self._new_wizard(company_uid='new-uid')
        action = wizard.action_confirm()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'base.automation')
        self.assertEqual(action['domain'], ['|', ('name', 'like', 'Nordwire'), ('name', 'like', 'Nord Sync')])

    def test_confirm_raises_when_preflight_not_ok(self):
        wizard = self._new_wizard(cron_threads=0, company_uid='new-uid')
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertFalse(self.env['nord_sync.config']._get_for_company(self.env.company))
