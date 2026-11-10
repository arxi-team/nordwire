from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestWorkcenterDowntimeNordSync(TransactionCase):
    """The stop of a Nord resource with no job (a plate released) reaches its work center:
    session_downtime_open / session_downtime / session_downtime_cancel, on the work order of
    the current MO when it has one, else as a line with no work order. The machine starting
    again ends the stop that is still open."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord_sync.config']._get_or_create_for_company(cls.env.company)
        cls.workcenter = cls.env['mrp.workcenter'].create({
            'name': 'Downtime WC', 'nord_sync_unassigned_work_behavior': 'unassigned_timesheets',
        })
        cls.Line = cls.env['mrp.workcenter.productivity']

    def _event(self, event_type, payload):
        return self.config._nord_sync_apply_workorder_event(
            {'res_id': self.workcenter.id, 'payload': payload}, 'mrp.workcenter', event_type)

    def _lines(self, nord_timesheet_id):
        return self.Line.search([('nord_sync_timesheet_id', '=', nord_timesheet_id)])

    def _stop_payload(self, nord_timesheet_id, minutes=10, closed=False):
        end = fields.Datetime.now()
        payload = {'nord_timesheet_id': nord_timesheet_id, 'start_date': str(end - timedelta(minutes=minutes)),
                   'kind': 'stop'}
        if closed:
            payload['end_date'] = str(end)
        return payload

    def _current_mo_with_workorder(self):
        product = self.env['product.product'].create({'name': 'Downtime Test Product'})
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id, 'product_qty': 1.0,
            'operation_ids': [(0, 0, {'name': 'Op', 'workcenter_id': self.workcenter.id, 'time_cycle_manual': 30})],
        })
        with patch(POST_TARGET):
            mo = self.env['mrp.production'].create({'product_id': product.id, 'product_qty': 1.0, 'bom_id': bom.id})
            mo.action_confirm()
        self.workcenter.with_context(nord_sync_skip_mo_change=True).nord_sync_current_production_id = mo
        return mo.workorder_ids

    def test_open_stop_with_no_mo_is_a_line_with_no_work_order(self):
        ok, _msg = self._event('session_downtime_open', self._stop_payload(9101))
        self.assertTrue(ok)
        line = self._lines(9101)
        self.assertEqual(len(line), 1)
        self.assertFalse(line.workorder_id)
        self.assertFalse(line.date_end)
        self.assertEqual(line.workcenter_id, self.workcenter)
        self.assertEqual(line.nord_sync_downtime_kind, 'stop')
        self.assertEqual(line.loss_id.name, 'Undefined')
        self._event('session_downtime_open', self._stop_payload(9101))
        self.assertEqual(len(self._lines(9101)), 1, 'the same stop twice is one line')

    def test_closing_the_stop_ends_the_line_shown_live(self):
        self._event('session_downtime_open', self._stop_payload(9102))
        ok, _msg = self._event('session_downtime', self._stop_payload(9102, closed=True))
        self.assertTrue(ok)
        line = self._lines(9102)
        self.assertEqual(len(line), 1)
        self.assertTrue(line.date_end)

    def test_a_stop_never_shown_is_logged_whole(self):
        self._event('session_downtime', self._stop_payload(9103, closed=True))
        line = self._lines(9103)
        self.assertEqual(len(line), 1)
        self.assertTrue(line.date_end)
        self._event('session_downtime', self._stop_payload(9103, closed=True))
        self.assertEqual(len(self._lines(9103)), 1, 'a retried delivery logs it once')

    def test_cancel_removes_only_a_stop_still_open(self):
        self._event('session_downtime_open', self._stop_payload(9104))
        self._event('session_downtime_cancel', {'nord_timesheet_id': 9104})
        self.assertFalse(self._lines(9104))
        self._event('session_downtime', self._stop_payload(9105, closed=True))
        self._event('session_downtime_cancel', {'nord_timesheet_id': 9105})
        self.assertEqual(len(self._lines(9105)), 1, 'a stop already closed is history')

    def test_with_a_current_mo_the_stop_lands_on_its_work_order(self):
        workorder = self._current_mo_with_workorder()
        self._event('session_downtime_open', self._stop_payload(9106))
        self.assertEqual(self._lines(9106).workorder_id, workorder)

    def test_machine_starting_with_no_mo_ends_the_open_stop(self):
        self._event('session_downtime_open', self._stop_payload(9107))
        ok, _msg = self._event('session_start', {
            'nord_timesheet_id': 9108, 'start_date': str(fields.Datetime.now())})
        self.assertTrue(ok)
        stop = self._lines(9107)
        self.assertTrue(stop.date_end, 'the stop ended when the machine started')
        work = self._lines(9108)
        self.assertEqual(len(work), 1)
        self.assertTrue(work.nord_sync_is_unassigned)
        self.assertFalse(work.date_end)
        self.assertLessEqual(stop.date_end, work.date_start)

    def test_a_stop_without_its_session_id_is_refused(self):
        ok, _msg = self._event('session_downtime_open', {'start_date': str(fields.Datetime.now())})
        self.assertFalse(ok)


@tagged('post_install', '-at_install')
class TestWorkcenterSequentialOperationsNordSync(TransactionCase):
    """The operations of an MO run one after the other: the machine of a later operation starting
    ends the Nord time still open on the earlier one, when that work center has Chain Close
    (nord_sync_chain_close) on."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord_sync.config']._get_or_create_for_company(cls.env.company)
        cls.first = cls.env['mrp.workcenter'].create({'name': 'Sequential First WC', 'nord_sync_chain_close': True})
        cls.second = cls.env['mrp.workcenter'].create({'name': 'Sequential Second WC'})
        product = cls.env['product.product'].create({'name': 'Sequential Test Product'})
        bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id, 'product_qty': 1.0,
            'operation_ids': [
                (0, 0, {'name': 'First', 'workcenter_id': cls.first.id, 'time_cycle_manual': 30, 'sequence': 1}),
                (0, 0, {'name': 'Second', 'workcenter_id': cls.second.id, 'time_cycle_manual': 30, 'sequence': 2}),
            ],
        })
        with patch(POST_TARGET):
            cls.mo = cls.env['mrp.production'].create({'product_id': product.id, 'product_qty': 1.0, 'bom_id': bom.id})
            cls.mo.action_confirm()
        for workcenter in (cls.first, cls.second):
            workcenter.with_context(nord_sync_skip_mo_change=True).nord_sync_current_production_id = cls.mo
        cls.Line = cls.env['mrp.workcenter.productivity']

    def _start(self, workcenter, nord_timesheet_id):
        ok, _msg = self.config._nord_sync_apply_workorder_event(
            {'res_id': workcenter.id, 'payload': {
                'nord_timesheet_id': nord_timesheet_id, 'start_date': str(fields.Datetime.now())}},
            'mrp.workcenter', 'session_start')
        self.assertTrue(ok)
        return self.Line.search([('nord_sync_timesheet_id', '=', nord_timesheet_id)])

    def test_starting_the_second_operation_ends_the_first(self):
        first = self._start(self.first, 9201)
        self.assertFalse(first.date_end)
        second = self._start(self.second, 9202)
        self.assertTrue(first.date_end, 'the first operation stopped when the second started')
        self.assertFalse(second.date_end)
        self.assertLessEqual(first.date_end, second.date_start)

    def test_without_chain_close_the_first_operation_keeps_running(self):
        self.first.nord_sync_chain_close = False
        first = self._start(self.first, 9203)
        self._start(self.second, 9204)
        self.assertFalse(first.date_end)
