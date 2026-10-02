from unittest.mock import patch

from odoo.tests import Form, TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestSyncQueueFailureVisibility(TransactionCase):
    """Sync Failure Visibility: mrp.bom/mrp.workcenter/hr.employee
    have no owning MO and never surface (systray count, Failure Wizard);
    mrp.production.moves/mrp.workorder/quality.check redirect to their MO;
    mrp.production (and anything else) is unaffected. There is no automatic
    activity — owner resolution only feeds the systray count and the Failure
    Wizard's line list, an activity is only ever created manually from there
    (nord_sync/wizard/nord_sync_failure_wizard_line.py).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({'name': 'Failure Visibility Test Product'})
        with patch(POST_TARGET):
            mo_form = Form(cls.env['mrp.production'])
            mo_form.product_id = cls.product
            cls.mo = mo_form.save()
        cls.Queue = cls.env['nord.sync.queue']

    def _header(self, owner_res_model, owner_res_id, **vals):
        return self.env['nord.sync.queue'].create({
            'owner_res_model': owner_res_model, 'owner_res_id': owner_res_id,
            'company_id': self.env.company.id, 'status': 'pending', **vals,
        })

    # ── _nord_sync_resolve_owner ─────────────────────────────────────────────

    def test_production_is_its_own_owner(self):
        owner = self.Queue._nord_sync_resolve_owner('mrp.production', self.mo.id, {})
        self.assertEqual(owner, ('mrp.production', self.mo.id))

    def test_moves_redirect_to_owning_production(self):
        owner = self.Queue._nord_sync_resolve_owner('mrp.production.moves', self.mo.id, {})
        self.assertEqual(owner, ('mrp.production', self.mo.id))

    def test_workorder_redirects_via_payload_snapshot(self):
        owner = self.Queue._nord_sync_resolve_owner(
            'mrp.workorder', 999, {'production_source_res_id': self.mo.id},
        )
        self.assertEqual(owner, ('mrp.production', self.mo.id))

    def test_workorder_without_production_in_payload_falls_back_to_itself(self):
        owner = self.Queue._nord_sync_resolve_owner('mrp.workorder', 999, {})
        self.assertEqual(owner, ('mrp.workorder', 999))

    def test_quality_check_redirects_via_payload_snapshot(self):
        owner = self.Queue._nord_sync_resolve_owner(
            'quality.check', 998, {'production_source_res_id': self.mo.id},
        )
        self.assertEqual(owner, ('mrp.production', self.mo.id))

    def test_quality_check_without_production_in_payload_falls_back_to_itself(self):
        owner = self.Queue._nord_sync_resolve_owner('quality.check', 998, {})
        self.assertEqual(owner, ('quality.check', 998))

    def test_bom_workcenter_employee_resolve_to_themselves_but_are_hidden(self):
        hidden = self.Queue._nord_sync_hidden_owner_models()
        for res_model in ('mrp.bom', 'mrp.workcenter', 'hr.employee'):
            self.assertEqual(self.Queue._nord_sync_resolve_owner(res_model, 1, {}), (res_model, 1))
            self.assertIn(res_model, hidden)

    def test_unrelated_model_is_its_own_owner_and_not_hidden(self):
        """Anything outside the mrp.production family (job stage config,
        state mapping, ...) keeps the base behaviour — not part of what the
        mrp override narrows."""
        owner = self.Queue._nord_sync_resolve_owner('nord_sync.job.stage', 5, {})
        self.assertEqual(owner, ('nord_sync.job.stage', 5))
        self.assertNotIn('nord_sync.job.stage', self.Queue._nord_sync_hidden_owner_models())

    # ── systray count ─────────────────────────────────────────────────────────

    def test_systray_count_ignores_hidden_owner_models(self):
        self._header('mrp.workcenter', 1, status='failed', last_error='x')
        self._header('hr.employee', 2, status='failed', last_error='x')
        self.assertEqual(self.Queue.systray_get_failed_count(), 0)

    def test_systray_count_dedups_same_owner_across_two_headers(self):
        # Two headers for the exact same owner (e.g. one sealed+failed, a
        # fresh one opened afterward that also failed) still count as one
        # problem, not two.
        self._header('mrp.production', self.mo.id, status='failed', last_error='x')
        self._header('mrp.production', self.mo.id, status='failed', last_error='x')
        self.assertEqual(self.Queue.systray_get_failed_count(), 1)

    # ── Take Action (technical list) ────────────────────────────────────────────

    def test_open_failure_wizard_uses_owner_fields_directly(self):
        header = self._header('mrp.production', self.mo.id, status='failed', last_error='x')
        action = header.action_open_failure_wizard()
        wizard = self.env['nord_sync.failure.wizard'].browse(action['res_id'])
        self.assertEqual(len(wizard.line_ids), 1)
        line = wizard.line_ids
        self.assertEqual(line.res_model, 'mrp.production')
        self.assertEqual(line.res_id, self.mo.id)
        self.assertEqual(line.record_name, self.mo.display_name)

    def test_open_failure_wizard_on_hidden_owner_still_works(self):
        # mrp.bom is a real model (just hidden from the friendly surfaces),
        # so browsing it directly is safe here.
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': self.product.product_tmpl_id.id, 'product_qty': 1.0,
        })
        header = self._header('mrp.bom', bom.id, status='failed', last_error='x')
        action = header.action_open_failure_wizard()
        wizard = self.env['nord_sync.failure.wizard'].browse(action['res_id'])
        line = wizard.line_ids
        self.assertEqual(line.res_model, 'mrp.bom')
        self.assertEqual(line.res_id, bom.id)
        self.assertEqual(line.record_name, bom.display_name)
