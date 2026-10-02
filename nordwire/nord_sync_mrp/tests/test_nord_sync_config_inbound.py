# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import Form, TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncConfigInboundDispatch(TransactionCase):
    """nord_sync.config._nord_sync_apply_result/_nord_sync_apply_workorder_event
    called directly, not through HTTP — moved here (from
    nord_sync_mrp/controllers/main.py) verbatim apart from the mechanical
    request.env -> self.env / HTTP response -> (applied, message) changes,
    so these still produce the exact same shape the old controller-owned
    dispatch did. Actual HTTP-level coverage (envelope validation, the
    async queue-then-cron flow) lives in test_result_controller.py /
    test_workorder_event_controller.py.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord_sync.config']._get_or_create_for_company(cls.env.company)
        cls.product = cls.env['product.product'].create({'name': 'Config Inbound Dispatch Test Product'})

    def _create_mo(self, qty=2.0):
        with patch(POST_TARGET):
            mo_form = Form(self.env['mrp.production'])
            mo_form.product_id = self.product
            mo_form.product_qty = qty
            mo = mo_form.save()
            mo.action_confirm()
        return mo

    def _create_mo_with_workorder(self):
        with patch(POST_TARGET):
            wc = self.env['mrp.workcenter'].create({'name': 'Config Inbound Dispatch WC'})
            bom = self.env['mrp.bom'].create({
                'product_tmpl_id': self.product.product_tmpl_id.id, 'product_qty': 1.0,
                'operation_ids': [(0, 0, {'name': 'Op', 'workcenter_id': wc.id, 'time_cycle_manual': 30})],
            })
            mo = self.env['mrp.production'].create({
                'product_id': self.product.id, 'product_qty': 1.0, 'bom_id': bom.id,
            })
            mo.action_confirm()
        workorder = self.env['mrp.workorder'].search([('production_id', '=', mo.id)], limit=1)
        return mo, workorder

    # ── result push ──────────────────────────────────────────────────────────

    def test_apply_result_unsupported_res_model(self):
        applied, message = self.config._nord_sync_apply_result({'res_id': 1}, 'res.partner')
        self.assertFalse(applied)
        self.assertIn('Unsupported res_model', message)

    def test_apply_result_missing_res_id(self):
        applied, message = self.config._nord_sync_apply_result({}, 'mrp.production')
        self.assertFalse(applied)
        self.assertEqual(message, 'Missing res_id')

    def test_apply_result_unknown_record(self):
        applied, message = self.config._nord_sync_apply_result({'res_id': 999999}, 'mrp.production')
        self.assertFalse(applied)
        self.assertEqual(message, 'Unknown record')

    def test_apply_result_applies_the_production(self):
        mo = self._create_mo(qty=2.0)
        applied, message = self.config._nord_sync_apply_result(
            {'res_id': mo.id, 'qty_produced': 2.0}, 'mrp.production',
        )
        self.assertTrue(applied, message)
        self.assertEqual(mo.state, 'done')

    # ── workorder event ──────────────────────────────────────────────────────

    def test_apply_workorder_event_unsupported_res_model(self):
        applied, message = self.config._nord_sync_apply_workorder_event({}, 'res.partner', 'session_start')
        self.assertFalse(applied)
        self.assertIn('Unsupported res_model', message)

    def test_apply_workorder_event_missing_res_id(self):
        applied, message = self.config._nord_sync_apply_workorder_event({}, 'mrp.workorder', 'session_start')
        self.assertFalse(applied)
        self.assertEqual(message, 'Missing res_id')

    def test_apply_workorder_event_unknown_workorder(self):
        applied, message = self.config._nord_sync_apply_workorder_event(
            {'res_id': 999999}, 'mrp.workorder', 'session_start',
        )
        self.assertFalse(applied)
        self.assertEqual(message, 'Unknown record')

    def test_apply_workorder_event_session_start_on_workorder(self):
        _mo, workorder = self._create_mo_with_workorder()
        applied, message = self.config._nord_sync_apply_workorder_event(
            {'res_id': workorder.id, 'payload': {}}, 'mrp.workorder', 'session_start',
        )
        self.assertTrue(applied, message)
        self.assertEqual(workorder.state, 'progress')

    def test_apply_workorder_event_job_cancel_on_production(self):
        mo, _workorder = self._create_mo_with_workorder()
        applied, message = self.config._nord_sync_apply_workorder_event(
            {'res_id': mo.id, 'payload': {}}, 'mrp.production', 'job_cancel',
        )
        self.assertTrue(applied, message)
        self.assertEqual(mo.state, 'cancel')
