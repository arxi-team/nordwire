from datetime import timedelta
from unittest.mock import patch

import psycopg2

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

    def test_starting_the_second_operation_marks_the_first_workorder_done(self):
        first_workorder = self.mo.workorder_ids.filtered(lambda w: w.workcenter_id == self.first)
        self._start(self.first, 9212)
        self.assertEqual(first_workorder.state, 'progress')
        self._start(self.second, 9213)
        self.assertEqual(first_workorder.state, 'done')

    def test_the_stop_of_the_first_operation_ends_when_the_second_starts(self):
        # the bag leaves the first machine (its plate is released: a stop opens there), then the second starts
        first = self._start(self.first, 9206)
        ok, _msg = self.config._nord_sync_apply_workorder_event(
            {'res_id': self.first.id, 'payload': {'nord_timesheet_id': 9206, 'end_date': str(fields.Datetime.now())}},
            'mrp.workcenter', 'session_stop')
        self.assertTrue(ok)
        ok, _msg = self.config._nord_sync_apply_workorder_event(
            {'res_id': self.first.id, 'payload': {
                'nord_timesheet_id': 9207, 'start_date': str(fields.Datetime.now()), 'kind': 'stop'}},
            'mrp.workcenter', 'session_downtime_open')
        self.assertTrue(ok)
        stop = self.Line.search([('nord_sync_timesheet_id', '=', 9207)])
        self.assertFalse(stop.date_end, 'the first machine shows as stopped')
        self._start(self.second, 9208)
        self.assertTrue(stop.date_end, 'its operation is over once the next one starts, the stop does not go on')

    def test_the_machine_taking_the_first_scheduled_mo_also_ends_the_previous_operation(self):
        # the second machine has no MO picked and takes the first scheduled one, the MO the first machine started
        self.second.with_context(nord_sync_skip_mo_change=True).nord_sync_current_production_id = False
        self.second.nord_sync_unassigned_work_behavior = 'first_scheduled'
        self._start(self.first, 9209)
        ok, _msg = self.config._nord_sync_apply_workorder_event(
            {'res_id': self.first.id, 'payload': {'nord_timesheet_id': 9209, 'end_date': str(fields.Datetime.now())}},
            'mrp.workcenter', 'session_stop')
        self.config._nord_sync_apply_workorder_event(
            {'res_id': self.first.id, 'payload': {
                'nord_timesheet_id': 9210, 'start_date': str(fields.Datetime.now()), 'kind': 'stop'}},
            'mrp.workcenter', 'session_downtime_open')
        stop = self.Line.search([('nord_sync_timesheet_id', '=', 9210)])
        self.assertFalse(stop.date_end)
        self._start(self.second, 9211)
        self.assertEqual(self.second.nord_sync_current_production_id, self.mo)
        self.assertTrue(stop.date_end, 'the first operation is over once the second starts, whichever way it started')

    def test_a_first_operation_line_with_no_session_id_is_ended_too(self):
        first_workorder = self.mo.workorder_ids.filtered(lambda w: w.workcenter_id == self.first)
        loss = self.env['mrp.workcenter.productivity.loss'].search([], limit=1)
        unstamped = self.Line.create({
            'workcenter_id': self.first.id, 'workorder_id': first_workorder.id, 'loss_id': loss.id,
            'date_start': fields.Datetime.now() - timedelta(minutes=5), 'user_id': False, 'employee_id': False,
        })
        self._start(self.second, 9205)
        self.assertTrue(unstamped.date_end)

    def test_without_chain_close_the_first_operation_keeps_running(self):
        self.first.nord_sync_chain_close = False
        first = self._start(self.first, 9203)
        self._start(self.second, 9204)
        self.assertFalse(first.date_end)


@tagged('post_install', '-at_install')
class TestWorkcenterUnstampedLinesNordSync(TransactionCase):
    """A Nord start once left its time line with no session id (opened some other way than by the helper
    that stamps it), and the stop, which looks the line up by that id, never closed it: 65 minutes of
    "work" for a 24 second plate press. The start now ends such a stale machine line and stamps the line
    it opens, and the stop also ends the machine lines of the current MO's work order. A line a person
    opened (an employee or a user on it) is never touched."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord_sync.config']._get_or_create_for_company(cls.env.company)
        cls.workcenter = cls.env['mrp.workcenter'].create({'name': 'Unstamped WC'})
        product = cls.env['product.product'].create({'name': 'Unstamped Test Product'})
        bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id, 'product_qty': 1.0,
            'operation_ids': [(0, 0, {'name': 'Op', 'workcenter_id': cls.workcenter.id, 'time_cycle_manual': 30})],
        })
        with patch(POST_TARGET):
            mo = cls.env['mrp.production'].create({'product_id': product.id, 'product_qty': 1.0, 'bom_id': bom.id})
            mo.action_confirm()
        cls.workorder = mo.workorder_ids
        cls.workcenter.with_context(nord_sync_skip_mo_change=True).nord_sync_current_production_id = mo
        cls.Line = cls.env['mrp.workcenter.productivity']
        cls.loss = cls.env['mrp.workcenter.productivity.loss'].search([], limit=1)

    def _open_line(self, **vals):
        return self.Line.create({
            'workcenter_id': self.workcenter.id, 'workorder_id': self.workorder.id,
            'date_start': fields.Datetime.now() - timedelta(minutes=5), 'loss_id': self.loss.id,
            'user_id': False, 'employee_id': False, **vals,
        })

    def _event(self, event_type, nord_timesheet_id):
        payload = {'nord_timesheet_id': nord_timesheet_id}
        payload['start_date' if event_type == 'session_start' else 'end_date'] = str(fields.Datetime.now())
        ok, _msg = self.config._nord_sync_apply_workorder_event(
            {'res_id': self.workcenter.id, 'payload': payload}, 'mrp.workcenter', event_type)
        self.assertTrue(ok)

    def test_stop_ends_a_machine_line_that_has_no_session_id(self):
        line = self._open_line()
        self._event('session_stop', 9401)
        self.assertTrue(line.date_end)

    def test_stop_leaves_a_line_a_person_opened(self):
        operator = self.env['hr.employee'].create({'name': 'Unstamped Test Operator'})
        by_person = self._open_line(employee_id=operator.id)
        self._event('session_stop', 9402)
        self.assertFalse(by_person.date_end)

    def test_start_ends_the_stale_machine_line_and_stamps_the_one_it_opens(self):
        stale = self._open_line()
        self._event('session_start', 9403)
        self.assertTrue(stale.date_end, 'the stale line ended where the new session starts')
        fresh = self.Line.search([('nord_sync_timesheet_id', '=', 9403)])
        self.assertEqual(len(fresh), 1)
        self.assertFalse(fresh.date_end)
        self._event('session_stop', 9403)
        self.assertTrue(fresh.date_end, 'the stop finds the stamped line')

    def test_start_leaves_a_line_a_person_opened(self):
        operator = self.env['hr.employee'].create({'name': 'Unstamped Test Operator 2'})
        by_person = self._open_line(employee_id=operator.id)
        self._event('session_start', 9404)
        self.assertFalse(by_person.date_end)


@tagged('post_install', '-at_install')
class TestFirstScheduledNordSync(TransactionCase):
    """A machine working with no MO picked starts the first scheduled MO. Starting an MO moves its date_start
    to now, so the next machine of an MO already started in the chain must take that MO, not the next planned one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord_sync.config']._get_or_create_for_company(cls.env.company)
        cls.first = cls.env['mrp.workcenter'].create({'name': 'Scheduled First WC'})
        cls.second = cls.env['mrp.workcenter'].create({
            'name': 'Scheduled Second WC', 'nord_sync_unassigned_work_behavior': 'first_scheduled'})
        product = cls.env['product.product'].create({'name': 'Scheduled Test Product'})
        bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id, 'product_qty': 1.0,
            'operation_ids': [
                (0, 0, {'name': 'First', 'workcenter_id': cls.first.id, 'time_cycle_manual': 30, 'sequence': 1}),
                (0, 0, {'name': 'Second', 'workcenter_id': cls.second.id, 'time_cycle_manual': 30, 'sequence': 2}),
            ],
        })
        cls.mos = cls.env['mrp.production']
        with patch(POST_TARGET):
            for index in range(2):
                mo = cls.env['mrp.production'].create({
                    'product_id': product.id, 'product_qty': 1.0, 'bom_id': bom.id,
                    'date_start': fields.Datetime.now() - timedelta(days=2 - index),
                })
                mo.action_confirm()
                cls.mos |= mo

    def test_the_next_machine_takes_the_mo_the_previous_one_started(self):
        planned_first, planned_second = self.mos
        # the planner's first MO gets its first operation started: its date_start becomes now
        first_op = planned_first.workorder_ids.filtered(lambda w: w.workcenter_id == self.first)
        first_op.with_context(nord_sync_from_core=True).button_start()
        self.assertEqual(planned_first.state, 'progress')
        self.assertLess(planned_second.date_start, planned_first.date_start,
                        'the started MO fell behind the planned one by date')
        self.assertEqual(self.second._nord_sync_first_scheduled_mo(), planned_first)

    def test_without_an_mo_started_the_first_planned_one(self):
        self.assertEqual(self.second._nord_sync_first_scheduled_mo(), self.mos.sorted('date_start')[:1])


@tagged('post_install', '-at_install')
class TestFirstScheduledConcurrencyNordSync(TransactionCase):
    """A machine taking the first scheduled MO while another transaction updates the same sync queue row
    gets a PostgreSQL serialization failure. It must reach Odoo's request retry, not be turned into an
    unassigned line with the MO left unstarted."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workcenter = cls.env['mrp.workcenter'].create({
            'name': 'Concurrency WC', 'nord_sync_unassigned_work_behavior': 'first_scheduled'})
        product = cls.env['product.product'].create({'name': 'Concurrency Test Product'})
        bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id, 'product_qty': 1.0,
            'operation_ids': [(0, 0, {'name': 'Op', 'workcenter_id': cls.workcenter.id, 'time_cycle_manual': 30})],
        })
        with patch(POST_TARGET):
            mo = cls.env['mrp.production'].create({'product_id': product.id, 'product_qty': 1.0, 'bom_id': bom.id})
            mo.action_confirm()

    def test_a_concurrent_update_is_not_swallowed(self):
        with patch.object(type(self.workcenter), '_nord_sync_on_change_current_mo',
                          side_effect=psycopg2.errors.SerializationFailure('could not serialize access')):
            with self.assertRaises(psycopg2.errors.TransactionRollbackError):
                self.workcenter._nord_sync_handle_machine_working_without_mo(payload={'nord_timesheet_id': 9501})
        self.assertFalse(self.env['mrp.workcenter.productivity'].search([('nord_sync_timesheet_id', '=', 9501)]),
                         'no unassigned line was left behind')

    def test_another_failure_still_falls_back_to_an_unassigned_line(self):
        with patch.object(type(self.workcenter), '_nord_sync_on_change_current_mo',
                          side_effect=ValueError('cannot start')):
            ok, _msg = self.workcenter._nord_sync_handle_machine_working_without_mo(payload={'nord_timesheet_id': 9502})
        self.assertTrue(ok)
        self.assertTrue(self.env['mrp.workcenter.productivity'].search([('nord_sync_timesheet_id', '=', 9502)]))
