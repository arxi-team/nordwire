from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.nord_sync_mrp.controllers.pda import NordSyncPda


@tagged('post_install', '-at_install')
class TestStopTrackingNordSync(TransactionCase):
    """Stop & Changeover Tracking, client side: the Core's closed stop
    (session_downtime) and setup (session_setup) segments land on the work
    order as time lines tagged with their kind, which the work center's
    "Nord Times" charts split into productive / stop / setup."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({'name': 'Stop Tracking Test Product'})
        cls.workcenter = cls.env['mrp.workcenter'].create({'name': 'Stop Tracking WC'})
        bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'product_qty': 1.0,
            'operation_ids': [(0, 0, {'name': 'Torra', 'workcenter_id': cls.workcenter.id, 'time_cycle_manual': 30})],
        })
        cls.production = cls.env['mrp.production'].create({
            'product_id': cls.product.id, 'product_qty': 1.0, 'bom_id': bom.id,
        })
        cls.production.action_confirm()
        cls.workorder = cls.production.workorder_ids

    def _segment(self, nord_timesheet_id, minutes=5):
        end = fields.Datetime.now()
        return {
            'nord_timesheet_id': nord_timesheet_id,
            'start_date': str(end - timedelta(minutes=minutes)),
            'end_date': str(end),
        }

    def test_downtime_is_logged_as_unjustified_stop(self):
        ok, _message = self.workorder._nord_sync_apply_granular_event('session_downtime', self._segment(9001))
        self.assertTrue(ok)
        line = self.env['mrp.workcenter.productivity'].search([('nord_sync_timesheet_id', '=', 9001)])
        self.assertEqual(len(line), 1)
        self.assertEqual(line.workorder_id, self.workorder)
        self.assertEqual(line.loss_id.name, 'Undefined')
        self.assertEqual(line.nord_sync_downtime_kind, 'stop')
        self.assertEqual(line.nord_sync_time_category, 'stop')
        self.assertAlmostEqual(line.nord_sync_elapsed_minutes, 5.0)

    def test_downtime_is_logged_once(self):
        self.workorder._nord_sync_apply_granular_event('session_downtime', self._segment(9002))
        self.workorder._nord_sync_apply_granular_event('session_downtime', self._segment(9002))
        self.assertEqual(self.env['mrp.workcenter.productivity'].search_count([('nord_sync_timesheet_id', '=', 9002)]), 1)

    def test_justified_downtime_keeps_its_reason(self):
        payload = {**self._segment(9003), 'reason_name': 'Falta de material', 'reason_type': 'Availability'}
        self.workorder._nord_sync_apply_granular_event('session_downtime', payload)
        line = self.env['mrp.workcenter.productivity'].search([('nord_sync_timesheet_id', '=', 9003)])
        self.assertEqual(line.loss_id.name, 'Falta de material')
        self.assertEqual(line.nord_sync_time_category, 'stop')

    def test_setup_is_categorised_as_setup(self):
        self.workorder._nord_sync_apply_granular_event('session_setup', self._segment(9004))
        line = self.env['mrp.workcenter.productivity'].search([('nord_sync_timesheet_id', '=', 9004)])
        self.assertEqual(line.nord_sync_time_category, 'setup')

    def test_unjustified_work_session_counts_as_productive(self):
        undefined = self.env['mrp.workcenter.productivity.loss']._nord_sync_get_or_create_undefined()
        line = self.env['mrp.workcenter.productivity'].create({
            'workorder_id': self.workorder.id, 'workcenter_id': self.workcenter.id,
            'loss_id': undefined.id, 'date_start': fields.Datetime.now() - timedelta(minutes=3),
            'date_end': fields.Datetime.now(),
        })
        self.assertEqual(line.nord_sync_time_category, 'productive')

    def test_workcenter_payload_carries_stop_tracking(self):
        self.workcenter.nord_sync_stop_tracking = True
        self.assertTrue(self.workcenter._nord_sync_payload()['stop_tracking'])

    def test_time_report_is_scoped_to_the_workcenter(self):
        action = self.workcenter.action_nord_sync_time_report()
        self.assertEqual(action['domain'], [('workcenter_id', '=', self.workcenter.id)])

    def test_pda_todo_groups_by_waiting_workcenter(self):
        fake_request = type('FakeRequest', (), {'env': self.env})()
        with patch('odoo.addons.nord_sync_mrp.controllers.pda.request', new=fake_request):
            groups = NordSyncPda().pda_todo()
        group = next(g for g in groups if g['workcenter'] == self.workcenter.display_name)
        self.assertIn(self.production.name, [o['name'] for o in group['orders']])
        self.assertEqual(group['orders'][0]['operation'], 'Torra')

    def _start(self, running=True):
        """The work order under way; running = the machine's open time line
        (what the Core's session_start opens)."""
        self.workcenter.nord_sync_stop_tracking = True
        self.workorder.state = 'progress'
        if running:
            productive = self.env['mrp.workcenter.productivity.loss'].search([('loss_type', '=', 'productive')], limit=1)
            self.env['mrp.workcenter.productivity'].create({
                'workorder_id': self.workorder.id, 'workcenter_id': self.workcenter.id,
                'loss_id': productive.id, 'date_start': fields.Datetime.now() - timedelta(minutes=10),
            })

    def test_not_ok_counts_notes_and_sends_floor_event(self):
        self.env['nord_sync.config'].create({'company_id': self.env.company.id, 'enabled': True})
        self._start()
        with patch('odoo.addons.nord_sync.models.nord_sync_config.requests.post'):
            count = self.workorder.action_nord_sync_not_ok()
        self.assertEqual(count, 1)
        self.assertEqual(self.workorder.nord_sync_not_ok_count, 1)
        entries = self.env['nord.sync.queue.line'].search([
            ('res_model', '=', 'mrp.workorder'), ('res_id', '=', self.workorder.id),
        ])
        self.assertEqual([e.data.get('floor_event') for e in entries if e.data.get('floor_event')], ['not_pass'])
        self.assertIn('not OK', self.production.message_ids[0].body)

    def test_not_ok_scraps_and_logs_quality_time_now(self):
        self._start()
        with patch('odoo.addons.nord_sync.models.nord_sync_config.requests.post'):
            self.workorder.action_nord_sync_not_ok()
        scrap = self.env['stock.scrap'].search([('production_id', '=', self.production.id)])
        self.assertEqual(len(scrap), 1)
        self.assertEqual(scrap.scrap_qty, 1)
        quality = self.workorder.time_ids.filtered(lambda t: t.loss_type == 'quality')
        self.assertEqual(len(quality), 1)
        self.assertEqual(quality.nord_sync_time_category, 'quality')

    def test_not_ok_refused_while_the_machine_is_stopped(self):
        self._start(running=False)
        with self.assertRaises(UserError):
            self.workorder.action_nord_sync_not_ok()
        self.assertFalse(self.env['stock.scrap'].search([('production_id', '=', self.production.id)]))

    def test_not_ok_note_follows_the_operator_language(self):
        if not self.env['res.lang']._lang_get('pt_PT'):
            self.skipTest('pt_PT not installed')
        self._start()
        with patch('odoo.addons.nord_sync.models.nord_sync_config.requests.post'):
            self.workorder.with_context(lang='pt_PT').action_nord_sync_not_ok()
        self.assertIn('Não OK', self.production.message_ids[0].body)

    def test_nord_session_opens_as_fully_productive_past_expected(self):
        timeline = self.workorder.with_context(nord_sync_from_core=True)._prepare_timeline_vals(
            self.workorder.duration_expected + 60, fields.Datetime.now(),
        )
        self.assertEqual(self.env['mrp.workcenter.productivity.loss'].browse(timeline['loss_id']).loss_type, 'productive')

    def test_nord_session_closes_without_reduced_speed_split(self):
        self._start()
        line = self.workorder.time_ids.filtered(lambda t: not t.date_end)
        line.date_start = fields.Datetime.now() - timedelta(minutes=self.workorder.duration_expected + 30)
        line.with_context(nord_sync_from_core=True)._close()
        self.assertEqual(len(self.workorder.time_ids), 1)
        self.assertEqual(self.workorder.time_ids.loss_type, 'productive')

    def test_chart_data_splits_lines_by_hour(self):
        self.workorder._nord_sync_apply_granular_event('session_downtime', self._segment(9100, minutes=5))
        data = self.workcenter.nord_sync_time_chart_data()
        self.assertEqual(data['totals']['stop'], 5.0)
        stop = next(s for s in data['series'] if s['key'] == 'stop')
        self.assertEqual(round(sum(stop['minutes']), 1), 5.0)
        self.assertEqual(len(stop['minutes']), len(data['labels']))

    def test_not_ok_needs_stop_tracking(self):
        self.workorder.state = 'progress'
        with self.assertRaises(UserError):
            self.workorder.action_nord_sync_not_ok()

    def test_pda_offers_not_ok_on_the_running_card(self):
        self._start()
        fake_request = type('FakeRequest', (), {'env': self.env})()
        with patch('odoo.addons.nord_sync_mrp.controllers.pda.request', new=fake_request):
            groups = NordSyncPda().pda_todo()
            result = NordSyncPda().pda_not_ok(self.production.name)
        card = next(o for g in groups for o in g['orders'] if o['name'] == self.production.name)
        self.assertTrue(card['running'])
        self.assertTrue(card['can_not_ok'])
        self.assertTrue(result['success'])
        self.assertEqual(self.workorder.nord_sync_not_ok_count, 1)

    def test_setup_shows_live_and_closes_on_the_same_line(self):
        start = fields.Datetime.now() - timedelta(minutes=4)
        self.workorder._nord_sync_apply_granular_event('session_downtime_open', {
            'nord_timesheet_id': 9200, 'start_date': str(start), 'kind': 'setup',
        })
        line = self.env['mrp.workcenter.productivity'].search([('nord_sync_timesheet_id', '=', 9200)])
        self.assertEqual(len(line), 1)
        self.assertFalse(line.date_end)
        self.assertEqual(line.nord_sync_time_category, 'setup')
        self.workorder._nord_sync_apply_granular_event('session_setup', {
            'nord_timesheet_id': 9200, 'start_date': str(start), 'end_date': str(fields.Datetime.now()),
        })
        line = self.env['mrp.workcenter.productivity'].search([('nord_sync_timesheet_id', '=', 9200)])
        self.assertEqual(len(line), 1)
        self.assertTrue(line.date_end)

    def test_cancelled_live_segment_goes(self):
        self.workorder._nord_sync_apply_granular_event('session_downtime_open', {
            'nord_timesheet_id': 9201, 'start_date': str(fields.Datetime.now()), 'kind': 'stop',
        })
        self.workorder._nord_sync_apply_granular_event('session_downtime_cancel', {'nord_timesheet_id': 9201})
        self.assertFalse(self.env['mrp.workcenter.productivity'].search([('nord_sync_timesheet_id', '=', 9201)]))

    def test_start_closes_live_setup_and_stale_work_line(self):
        self._start()
        stale = self.workorder.time_ids.filtered(lambda t: not t.date_end)
        stale.nord_sync_timesheet_id = 9300
        self.workorder._nord_sync_apply_granular_event('session_downtime_open', {
            'nord_timesheet_id': 9301, 'start_date': str(fields.Datetime.now() - timedelta(minutes=2)), 'kind': 'setup',
        })
        self.workorder._nord_sync_close_before_start({'nord_timesheet_id': 9302, 'start_date': str(fields.Datetime.now())})
        self.assertTrue(stale.date_end)
        self.assertTrue(self.env['mrp.workcenter.productivity'].search([('nord_sync_timesheet_id', '=', 9301)]).date_end)

    def test_live_setup_is_not_running(self):
        self.workcenter.nord_sync_stop_tracking = True
        self.workorder.state = 'progress'
        self.workorder._nord_sync_apply_granular_event('session_downtime_open', {
            'nord_timesheet_id': 9400, 'start_date': str(fields.Datetime.now()), 'kind': 'setup',
        })
        self.assertFalse(self.workorder._nord_sync_is_running())
        fake_request = type('FakeRequest', (), {'env': self.env})()
        with patch('odoo.addons.nord_sync_mrp.controllers.pda.request', new=fake_request):
            groups = NordSyncPda().pda_todo()
        card = next(o for g in groups for o in g['orders'] if o['name'] == self.production.name)
        self.assertEqual(card['floor'], 'setup')
        self.assertFalse(card['can_not_ok'])

    def test_demo_deliver_closes_the_mo_and_leaves_pda_rejects_out(self):
        self._start()
        with patch('odoo.addons.nord_sync.models.nord_sync_config.requests.post'):
            self.workorder.action_nord_sync_not_ok()
            success, message = self.production._nord_sync_demo_deliver(qty=1)
        self.assertTrue(success, message)
        self.assertEqual(self.production.state, 'done')
        # Only the PDA's own scrap: the result didn't scrap that reject again
        self.assertEqual(self.env['stock.scrap'].search_count([('production_id', '=', self.production.id)]), 1)

    def test_demo_deliver_needs_stop_tracking(self):
        success, _message = self.production._nord_sync_demo_deliver(qty=1)
        self.assertFalse(success)
        self.assertNotEqual(self.production.state, 'done')
