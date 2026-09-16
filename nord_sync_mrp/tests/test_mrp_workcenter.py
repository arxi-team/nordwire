
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestMrpWorkcenterNordSync(TransactionCase):
    """Resource Bridge."""

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            wc = self.env['mrp.workcenter'].create({'name': 'No Config WC'})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', wc.id), ('owner_res_model', '=', 'mrp.workcenter'),
        ]))
        mocked_post.assert_not_called()

    def test_production_source_not_selected_does_not_enqueue(self):
        # Workcenter is a support model for the mrp.production source, not
        # a selectable source itself — gated against 'mrp.production' being
        # in enabled_source_ids, same as the Employee/BOM/Workorder Bridges.
        sale_source = self.env['nord_sync.source'].search([('model', '=', 'sale.order')])
        self._configure(enabled_source_ids=[(6, 0, sale_source.ids)])
        with patch(POST_TARGET) as mocked_post:
            wc = self.env['mrp.workcenter'].create({'name': 'Not Selected WC'})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', wc.id), ('owner_res_model', '=', 'mrp.workcenter'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Cutting Line'})
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', wc.id), ('owner_res_model', '=', 'mrp.workcenter'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.payload['name'], 'Cutting Line')

    def test_autonomous_resource_policies_default_in_payload(self):
        self._configure()
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Default Policies WC'})
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', wc.id), ('owner_res_model', '=', 'mrp.workcenter'),
        ])
        self.assertEqual(entry.payload['autonomous_close'], False)
        self.assertEqual(entry.payload['granular_push'], False)
        self.assertEqual(entry.payload['contention_policy'], 'block')
        self.assertEqual(entry.payload['chain_close'], False)
        self.assertEqual(entry.payload['mirror_mode'], False)
        self.assertEqual(entry.payload['auto_idle_segments'], False)
        self.assertEqual(entry.payload['idle_segment_reason'], 'Idle')
        self.assertEqual(entry.payload['auto_tooling_segments'], False)
        self.assertEqual(entry.payload['tooling_segment_reason'], 'Tooling')

    def test_autonomous_resource_policies_carried_in_payload(self):
        self._configure()
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({
                'name': 'Autonomous WC',
                'nord_sync_autonomous_close': True,
                'nord_sync_granular_push': True,
                'nord_sync_contention_policy': 'auto_close_previous',
                'nord_sync_chain_close': True,
                'nord_sync_mirror_mode': True,
                'nord_sync_auto_idle_segments': True,
                'nord_sync_idle_segment_reason_name': 'Custom Idle',
                'nord_sync_auto_tooling_segments': True,
                'nord_sync_tooling_segment_reason_name': 'Custom Tooling',
            })
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', wc.id), ('owner_res_model', '=', 'mrp.workcenter'),
        ])
        self.assertEqual(entry.payload['autonomous_close'], True)
        self.assertEqual(entry.payload['granular_push'], True)
        self.assertEqual(entry.payload['contention_policy'], 'auto_close_previous')
        self.assertEqual(entry.payload['chain_close'], True)
        self.assertEqual(entry.payload['mirror_mode'], True)
        self.assertEqual(entry.payload['auto_idle_segments'], True)
        self.assertEqual(entry.payload['idle_segment_reason'], 'Custom Idle')
        self.assertEqual(entry.payload['auto_tooling_segments'], True)
        self.assertEqual(entry.payload['tooling_segment_reason'], 'Custom Tooling')

    def test_write_enqueues_with_current_payload(self):
        self._configure()
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Before Rename'})
            wc.write({'name': 'After Rename'})
        entries = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', wc.id), ('owner_res_model', '=', 'mrp.workcenter'),
            ('line_ids.operation', '=', 'write'),
        ])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.payload['name'], 'After Rename')

    def test_unlink_enqueues_before_record_is_gone(self):
        self._configure()
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Removed WC'})
            wc_id = wc.id
            wc.unlink()
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', wc_id), ('owner_res_model', '=', 'mrp.workcenter'),
            ('line_ids.operation', '=', 'unlink'),
        ])
        self.assertEqual(len(entry), 1)


@tagged('post_install', '-at_install')
class TestMrpWorkcenterForceResyncReasons(TransactionCase):
    """action_nord_sync_force_resync_reasons — the "Resync Reasons to Core"
    button's underlying method. Not itself scoped to the work center that
    happens to carry the button (loss/loss.type are global tables), so a
    plain, unconfigured work center is enough to call it from.
    """

    def _configure(self, **vals):
        # get_or_create, not a plain create() — a persistent dev DB reused
        # across sessions can already have a real nord_sync.config for this
        # company, which UNIQUE(company_id) would otherwise reject.
        vals.setdefault('enabled', True)
        config = self.env['nord_sync.config']._get_or_create_for_company(self.env.company)
        config.write(vals)
        return config

    def _queue_lines(self, res_model, res_id):
        return self.env['nord.sync.queue.line'].search([
            ('res_model', '=', res_model), ('res_id', '=', res_id),
        ])

    def test_enqueues_a_loss_type_with_no_external_id_needed(self):
        # loss.type has no external-id gate (unlike loss below) -- every
        # loss.type always pushes. create() itself already enqueues a
        # 'create' line (config is enabled) -- force-resync is what should
        # additionally produce its own 'write' line on top of that.
        self._configure()
        with patch(POST_TARGET):
            loss_type = self.env['mrp.workcenter.productivity.loss.type'].create({
                'loss_type': 'performance',
            })
            wc = self.env['mrp.workcenter'].create({'name': 'Force Resync Trigger WC'})
            wc.action_nord_sync_force_resync_reasons()
        write_lines = self._queue_lines('mrp.workcenter.productivity.loss.type', loss_type.id).filtered(
            lambda line: line.operation == 'write',
        )
        self.assertEqual(len(write_lines), 1)
        self.assertEqual(write_lines.data['loss_type'], 'performance')

    def test_does_not_enqueue_a_loss_without_a_real_external_id(self):
        # The force-resync button must never bypass the external-id gate
        # MrpWorkcenterProductivityLoss._nord_sync_notify already applies --
        # a custom reason a human created by hand on the client (no
        # ir.model.data row) must still never flood the Core.
        self._configure()
        with patch(POST_TARGET):
            loss_type = self.env['mrp.workcenter.productivity.loss.type'].create({'loss_type': 'quality'})
            loss = self.env['mrp.workcenter.productivity.loss'].create({
                'name': 'Custom Hand-Made Reason', 'loss_id': loss_type.id,
            })
            wc = self.env['mrp.workcenter'].create({'name': 'Force Resync Trigger WC 2'})
            wc.action_nord_sync_force_resync_reasons()
        self.assertFalse(self._queue_lines('mrp.workcenter.productivity.loss', loss.id))

    def test_enqueues_a_loss_that_has_a_real_external_id(self):
        self._configure()
        with patch(POST_TARGET):
            loss_type = self.env['mrp.workcenter.productivity.loss.type'].create({'loss_type': 'availability'})
            loss = self.env['mrp.workcenter.productivity.loss'].create({
                'name': 'Seeded Reason', 'loss_id': loss_type.id,
            })
            self.env['ir.model.data'].create({
                'module': 'nord_sync_mrp_test', 'name': f'test_seeded_loss_{loss.id}',
                'model': 'mrp.workcenter.productivity.loss', 'res_id': loss.id,
            })
            wc = self.env['mrp.workcenter'].create({'name': 'Force Resync Trigger WC 3'})
            wc.action_nord_sync_force_resync_reasons()
        lines = self._queue_lines('mrp.workcenter.productivity.loss', loss.id)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.data['name'], 'Seeded Reason')


@tagged('post_install', '-at_install')
class TestMrpWorkcenterControlMode(TransactionCase):
    """nord_sync_control_mode — computed shortcut over the four
    floor-event fields. Mirror Mode is deliberately outside
    it (a standalone opt-in, never touched by picking a preset) — see
    TestMrpWorkcenterMirrorModeStandalone below. No nord_sync.config/sync
    needed, purely local.
    """

    def _workcenter(self, **vals):
        with patch(POST_TARGET):
            return self.env['mrp.workcenter'].create({'name': 'Control Mode WC', **vals})

    def test_factory_default_is_odoo(self):
        # (False, False, 'block', False) matches the 'odoo' preset exactly
        # -- a work center nobody has touched already reads as Odoo-controlled.
        wc = self._workcenter()
        self.assertEqual(wc.nord_sync_control_mode, 'odoo')

    def test_nord_preset_matches_its_four_fields(self):
        wc = self._workcenter(
            nord_sync_autonomous_close=True, nord_sync_granular_push=True,
            nord_sync_contention_policy='auto_close_previous', nord_sync_chain_close=True,
        )
        self.assertEqual(wc.nord_sync_control_mode, 'nord')

    def test_setting_odoo_writes_the_four_fields(self):
        wc = self._workcenter(nord_sync_autonomous_close=True, nord_sync_chain_close=True)
        with patch(POST_TARGET):
            wc.nord_sync_control_mode = 'odoo'
        self.assertFalse(wc.nord_sync_autonomous_close)
        self.assertFalse(wc.nord_sync_granular_push)
        self.assertEqual(wc.nord_sync_contention_policy, 'block')
        self.assertFalse(wc.nord_sync_chain_close)

    def test_setting_nord_writes_the_four_fields(self):
        wc = self._workcenter()
        with patch(POST_TARGET):
            wc.nord_sync_control_mode = 'nord'
        self.assertTrue(wc.nord_sync_autonomous_close)
        self.assertTrue(wc.nord_sync_granular_push)
        self.assertEqual(wc.nord_sync_contention_policy, 'auto_close_previous')
        self.assertTrue(wc.nord_sync_chain_close)

    def test_editing_one_field_by_hand_falls_back_to_custom(self):
        wc = self._workcenter()
        self.assertEqual(wc.nord_sync_control_mode, 'odoo')
        with patch(POST_TARGET):
            wc.nord_sync_granular_push = True
        self.assertEqual(wc.nord_sync_control_mode, 'custom')

    def test_setting_custom_explicitly_is_a_noop(self):
        wc = self._workcenter()
        with patch(POST_TARGET):
            wc.nord_sync_control_mode = 'custom'
        # Still matches 'odoo' by value -- 'custom' has no preset to write,
        # so picking it explicitly changes nothing about the three fields.
        self.assertEqual(wc.nord_sync_control_mode, 'odoo')


@tagged('post_install', '-at_install')
class TestMrpWorkcenterMirrorModeStandalone(TransactionCase):
    """Mirror Mode lives next to Control Mode but isn't part of it —
    neither preset touches it, in either direction."""

    def _workcenter(self, **vals):
        with patch(POST_TARGET):
            return self.env['mrp.workcenter'].create({'name': 'Mirror Standalone WC', **vals})

    def test_odoo_preset_does_not_touch_mirror_mode(self):
        wc = self._workcenter(nord_sync_mirror_mode=True)
        with patch(POST_TARGET):
            wc.nord_sync_control_mode = 'odoo'
        self.assertTrue(wc.nord_sync_mirror_mode)

    def test_nord_preset_does_not_touch_mirror_mode(self):
        wc = self._workcenter(nord_sync_mirror_mode=True)
        with patch(POST_TARGET):
            wc.nord_sync_control_mode = 'nord'
        self.assertTrue(wc.nord_sync_mirror_mode)

    def test_mirror_mode_on_still_matches_a_preset(self):
        # Mirror Mode is orthogonal -- turning it on doesn't knock the
        # other three fields out of matching 'odoo'.
        wc = self._workcenter(nord_sync_mirror_mode=True)
        self.assertEqual(wc.nord_sync_control_mode, 'odoo')


@tagged('post_install', '-at_install')
class TestMrpWorkcenterDefaultControlMode(TransactionCase):
    """nord_sync_default_workcenter_control_mode (nord_sync.config) —
    applied to a new work center's four floor-event fields only when the
    vals dict says nothing about Control Mode at all. No nord.sync.queue
    involvement needed for any of this, purely local -- POST_TARGET is
    still patched throughout since mrp.workcenter.create() always calls
    _nord_sync_notify regardless.
    """

    def _configure(self, **vals):
        config = self.env['nord_sync.config']._get_or_create_for_company(self.env.company)
        config.write(vals)
        return config

    def test_default_applies_when_nothing_specified(self):
        self._configure(nord_sync_default_workcenter_control_mode='nord')
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Default To Nord WC'})
        self.assertEqual(wc.nord_sync_control_mode, 'nord')
        self.assertTrue(wc.nord_sync_autonomous_close)
        self.assertTrue(wc.nord_sync_granular_push)
        self.assertEqual(wc.nord_sync_contention_policy, 'auto_close_previous')
        self.assertTrue(wc.nord_sync_chain_close)

    def test_explicit_control_mode_wins_over_default(self):
        self._configure(nord_sync_default_workcenter_control_mode='nord')
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({
                'name': 'Explicit Odoo WC', 'nord_sync_control_mode': 'odoo',
            })
        self.assertEqual(wc.nord_sync_control_mode, 'odoo')

    def test_explicit_underlying_field_wins_over_default(self):
        # Naming even one of the four fields directly (never
        # nord_sync_control_mode itself) is still an explicit override --
        # the default must not clobber it. chain_close=True alone (the
        # other three left to their own factory defaults) matches neither
        # preset, landing on 'custom' -- proof the 'nord' default was never
        # applied at all, not just partially overwritten afterwards.
        self._configure(nord_sync_default_workcenter_control_mode='nord')
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({
                'name': 'Explicit Field WC', 'nord_sync_chain_close': True,
            })
        self.assertEqual(wc.nord_sync_control_mode, 'custom')
        self.assertFalse(wc.nord_sync_autonomous_close)
        self.assertTrue(wc.nord_sync_chain_close)

    def test_changing_default_later_does_not_touch_existing_workcenters(self):
        self._configure(nord_sync_default_workcenter_control_mode='nord')
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Already Created WC'})
        self.assertEqual(wc.nord_sync_control_mode, 'nord')
        self._configure(nord_sync_default_workcenter_control_mode='odoo')
        self.assertEqual(wc.nord_sync_control_mode, 'nord')

    def test_no_company_default_configured_keeps_todays_behavior(self):
        self._configure()  # nord_sync_default_workcenter_control_mode left unset
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'No Default WC'})
        self.assertEqual(wc.nord_sync_control_mode, 'odoo')
