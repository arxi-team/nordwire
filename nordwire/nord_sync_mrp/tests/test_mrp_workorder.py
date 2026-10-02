from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestMrpWorkorderNordSync(TransactionCase):
    """Workorder Bridge (source side) — each real mrp.workorder pushes
    create/write/unlink, resolved by the Core into a real nord.timesheet.
    mrp.workorder always redirects to its MO as owner — its own
    entries are nord.sync.queue.line rows, never their own header. Result-side
    (_nord_sync_apply_result) is covered by test_result_controller.py.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({'name': 'Nordwire Workorder Test Product'})

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def _create_mo_with_workorder(self, workcenter_name='Workorder Test WC'):
        wc = self.env['mrp.workcenter'].create({'name': workcenter_name})
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'product_qty': 1.0,
            'operation_ids': [(0, 0, {'name': 'Op', 'workcenter_id': wc.id, 'time_cycle_manual': 30})],
        })
        mo = self.env['mrp.production'].create({
            'product_id': self.product.id, 'product_qty': 1.0, 'bom_id': bom.id,
        })
        mo.action_confirm()
        workorder = self.env['mrp.workorder'].search([('production_id', '=', mo.id)], limit=1)
        return mo, wc, workorder

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            _mo, _wc, workorder = self._create_mo_with_workorder()
        self.assertFalse(self.env['nord.sync.queue.line'].search([
            ('res_id', '=', workorder.id), ('res_model', '=', 'mrp.workorder'),
        ]))
        mocked_post.assert_not_called()

    def test_confirm_enqueues_create_with_source_references(self):
        self._configure()
        with patch(POST_TARGET):
            mo, wc, workorder = self._create_mo_with_workorder()
        entry = self.env['nord.sync.queue.line'].search([
            ('res_id', '=', workorder.id), ('res_model', '=', 'mrp.workorder'), ('operation', '=', 'create'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.data['production_source_res_id'], mo.id)
        self.assertEqual(entry.data['workcenter_source_res_id'], wc.id)
        # Snapshot lets the Core get-or-create the resource on the spot if
        # the Resource Bridge's own push hasn't landed yet.
        self.assertEqual(entry.data['workcenter'], {
            'name': wc.name,
            'nord_resource_uids': [],
            'autonomous_close': wc.nord_sync_autonomous_close,
            'granular_push': wc.nord_sync_granular_push,
            'contention_policy': wc.nord_sync_contention_policy,
            'chain_close': wc.nord_sync_chain_close,
            'mirror_mode': wc.nord_sync_mirror_mode,
            'auto_idle_segments': wc.nord_sync_auto_idle_segments,
            'idle_segment_reason': wc.nord_sync_idle_segment_reason_name,
            'auto_tooling_segments': wc.nord_sync_auto_tooling_segments,
            'tooling_segment_reason': wc.nord_sync_tooling_segment_reason_name,
        })
        # duration_expected (minutes) -> expected_duration (hours).
        self.assertEqual(entry.data['expected_duration'], workorder.duration_expected / 60.0)
        self.assertEqual(entry.data['sequence'], workorder.operation_id.sequence)
        self.assertFalse(entry.data['employee_source_res_id'])

    def test_assigned_employee_is_carried_in_the_payload(self):
        self._configure()
        employee = self.env['hr.employee'].create({'name': 'Assigned Operator'})
        with patch(POST_TARGET):
            _mo, _wc, workorder = self._create_mo_with_workorder()
            checkpoint = self.env['nord.sync.queue.line'].search([], order='id desc', limit=1).id
            workorder.employee_assigned_ids = [(4, employee.id)]
        entries = self.env['nord.sync.queue.line'].search([
            ('id', '>', checkpoint),
            ('res_id', '=', workorder.id), ('res_model', '=', 'mrp.workorder'), ('operation', '=', 'write'),
        ])
        self.assertTrue(entries)
        self.assertEqual(entries[0].data['employee_source_res_id'], employee.id)
        self.assertEqual(entries[0].data['employee'], {'name': employee.name, 'nord_resource_uids': []})

    def test_workcenter_reassignment_enqueues_write(self):
        # Known pre-existing noise (unrelated to this test): action_confirm()
        # itself writes to a just-created workorder more than once internally
        # (state, computed fields, …), each write pushing its own entry — so
        # entries from setup already exist by the time the reassignment
        # write happens below. Isolated here via a checkpoint (last id before
        # the write), not by counting all 'write' entries for this workorder.
        self._configure()
        with patch(POST_TARGET):
            _mo, _wc, workorder = self._create_mo_with_workorder()
            other_wc = self.env['mrp.workcenter'].create({'name': 'Reassigned WC'})
            checkpoint = self.env['nord.sync.queue.line'].search([], order='id desc', limit=1).id
            workorder.write({'workcenter_id': other_wc.id})
        entries = self.env['nord.sync.queue.line'].search([
            ('id', '>', checkpoint),
            ('res_id', '=', workorder.id), ('res_model', '=', 'mrp.workorder'), ('operation', '=', 'write'),
        ])
        self.assertTrue(entries)
        # v17's own mrp.workorder.write() assigns duration_expected (a field
        # assignment, itself a write()) before calling super().write() for
        # the vals dict that actually carries the new workcenter_id -- that
        # intermediate write notifies too, with the still-old workcenter_id.
        # The last entry is the one that reflects the real, final value.
        self.assertEqual(entries[-1].data['workcenter_source_res_id'], other_wc.id)

    def test_unlink_enqueues_before_record_is_gone(self):
        self._configure()
        with patch(POST_TARGET):
            _mo, _wc, workorder = self._create_mo_with_workorder()
            workorder_id = workorder.id
            workorder.unlink()
        entry = self.env['nord.sync.queue.line'].search([
            ('res_id', '=', workorder_id), ('res_model', '=', 'mrp.workorder'), ('operation', '=', 'unlink'),
        ])
        self.assertEqual(len(entry), 1)


@tagged('post_install', '-at_install')
class TestMrpWorkorderStartWizard(TransactionCase):
    """button_start()'s nord_sync.workorder.start.wizard checkpoint,
    gated by nord_sync_confirm_workcenter_on_start (company) and skipped
    when the work order's own work center is fully handed to Nord (Control
    Mode == 'nord', see mrp_workcenter.py/ADR 0028) — a human confirming
    which work center a Nord-owned resource is on would be backwards.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({'name': 'Start Wizard Test Product'})

    def _create_mo_with_workorder(self, **workcenter_vals):
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Start Wizard WC', **workcenter_vals})
            bom = self.env['mrp.bom'].create({
                'product_tmpl_id': self.product.product_tmpl_id.id,
                'product_qty': 1.0,
                'operation_ids': [(0, 0, {'name': 'Op', 'workcenter_id': wc.id, 'time_cycle_manual': 30})],
            })
            mo = self.env['mrp.production'].create({
                'product_id': self.product.id, 'product_qty': 1.0, 'bom_id': bom.id,
            })
            mo.action_confirm()
        workorder = self.env['mrp.workorder'].search([('production_id', '=', mo.id)], limit=1)
        return wc, workorder

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        vals.setdefault('nord_sync_confirm_workcenter_on_start', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_opt_out_starts_directly(self):
        self.env['nord_sync.config'].create({'company_id': self.env.company.id, 'enabled': True})
        _wc, workorder = self._create_mo_with_workorder()
        with patch(POST_TARGET):
            workorder.button_start()
        self.assertEqual(workorder.state, 'progress')

    def test_odoo_control_mode_shows_the_wizard(self):
        # Default work center fields already match the 'odoo' preset -- the
        # wizard shows for anything short of 'nord', 'odoo' included.
        self._configure()
        _wc, workorder = self._create_mo_with_workorder()
        with patch(POST_TARGET):
            result = workorder.button_start()
        self.assertEqual(result.get('res_model'), 'nord_sync.workorder.start.wizard')
        self.assertNotEqual(workorder.state, 'progress')

    def test_nord_control_mode_skips_the_wizard(self):
        self._configure()
        _wc, workorder = self._create_mo_with_workorder(
            nord_sync_autonomous_close=True, nord_sync_granular_push=True,
            nord_sync_contention_policy='auto_close_previous', nord_sync_chain_close=True,
        )
        with patch(POST_TARGET):
            workorder.button_start()
        self.assertEqual(workorder.state, 'progress')

    def test_wizard_confirm_starts_and_never_reopens_itself(self):
        self._configure()
        _wc, workorder = self._create_mo_with_workorder()
        with patch(POST_TARGET):
            wizard_action = workorder.button_start()
            wizard = self.env['nord_sync.workorder.start.wizard'].create({
                'workorder_id': workorder.id,
            })
            self.assertEqual(wizard_action.get('res_model'), 'nord_sync.workorder.start.wizard')
            wizard.action_confirm()
        self.assertEqual(workorder.state, 'progress')

    # No TestMrpProductionStartWizard class — that covered the MO header's
    # own Start button (mrp.production.action_start), a later Odoo
    # version's addition with no v17 equivalent (see mrp_production.py).
