from unittest.mock import patch

from odoo.tests import Form, TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'
MARK_DONE_TARGET = 'odoo.addons.mrp.models.mrp_production.MrpProduction.button_mark_done'


@tagged('post_install', '-at_install')
class TestMrpProductionApplyResult(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({'name': 'Nord Sync Apply Result Test Product'})

    def _create_and_confirm_mo(self):
        with patch(POST_TARGET):
            mo_form = Form(self.env['mrp.production'])
            mo_form.product_id = self.product
            mo = mo_form.save()
            mo.action_confirm()
        return mo

    def test_apply_result_success_marks_done(self):
        mo = self._create_and_confirm_mo()
        applied, message = mo._nord_sync_apply_result(3.0)
        self.assertTrue(applied)
        self.assertEqual(message, 'ok')
        self.assertEqual(mo.state, 'done')

    def test_apply_result_already_done_is_noop(self):
        mo = self._create_and_confirm_mo()
        mo._nord_sync_apply_result(3.0)
        applied, message = mo._nord_sync_apply_result(3.0)
        self.assertFalse(applied)
        self.assertIn('already', message)

    def test_apply_result_cancelled_is_noop(self):
        mo = self._create_and_confirm_mo()
        mo.action_cancel()
        applied, message = mo._nord_sync_apply_result(3.0)
        self.assertFalse(applied)
        self.assertIn('already', message)

    def test_apply_result_exception_creates_activity_not_silent(self):
        mo = self._create_and_confirm_mo()
        with patch(MARK_DONE_TARGET, side_effect=Exception('boom')):
            applied, message = mo._nord_sync_apply_result(3.0)
        self.assertFalse(applied)
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'mrp.production'), ('res_id', '=', mo.id),
        ])
        self.assertEqual(len(activities), 1)

    def test_apply_result_wizard_needed_creates_activity_not_silent(self):
        mo = self._create_and_confirm_mo()
        with patch(MARK_DONE_TARGET, return_value={'type': 'ir.actions.act_window'}):
            applied, message = mo._nord_sync_apply_result(3.0)
        self.assertFalse(applied)
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'mrp.production'), ('res_id', '=', mo.id),
        ])
        self.assertEqual(len(activities), 1)
