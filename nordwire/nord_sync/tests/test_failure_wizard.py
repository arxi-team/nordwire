from datetime import date, timedelta
from unittest.mock import Mock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncFriendlyError(TransactionCase):

    def _entry(self, last_error):
        return self.env['nord.sync.queue'].create({
            'owner_res_model': 'mrp.production', 'owner_res_id': 1,
            'company_id': self.env.company.id, 'status': 'failed', 'last_error': last_error,
        })

    def test_empty_error_is_empty(self):
        self.assertEqual(self._entry(False)._nord_sync_friendly_error(), '')

    def test_timeout_is_classified(self):
        message = self._entry("HTTPConnectionPool(...): Read timed out.")._nord_sync_friendly_error()
        self.assertIn('too long to respond', message)

    def test_connection_refused_is_classified(self):
        message = self._entry("ConnectionError: [Errno 111] Connection refused")._nord_sync_friendly_error()
        self.assertIn('could not reach', message.lower())

    def test_server_error_is_classified(self):
        message = self._entry("502 Server Error: Bad Gateway for url: https://cloud.example.com/x")._nord_sync_friendly_error()
        self.assertIn('server error', message.lower())

    def test_client_error_is_classified(self):
        message = self._entry("401 Client Error: Unauthorized for url: https://cloud.example.com/x")._nord_sync_friendly_error()
        self.assertIn('rejected', message.lower())

    def test_unrecognized_error_falls_back_to_generic(self):
        message = self._entry("some never-seen-before exception text")._nord_sync_friendly_error()
        self.assertIn('unknown reason', message.lower())


@tagged('post_install', '-at_install')
class TestNordSyncFailureWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Failure Wizard Test Partner'})
        cls.assignee = cls.env['res.users'].create({
            'name': 'Failure Wizard Assignee', 'login': 'test_failure_wizard_assignee',
        })

    def test_open_failure_wizard_from_entry_creates_one_line(self):
        header = self.env['nord.sync.queue'].create({
            'owner_res_model': 'res.partner', 'owner_res_id': self.partner.id,
            'company_id': self.env.company.id, 'status': 'failed', 'last_error': 'Connection refused',
        })
        action = header.action_open_failure_wizard()
        wizard = self.env['nord_sync.failure.wizard'].browse(action['res_id'])
        self.assertEqual(len(wizard.line_ids), 1)
        line = wizard.line_ids
        self.assertEqual(line.res_model, 'res.partner')
        self.assertEqual(line.res_id, self.partner.id)
        self.assertEqual(line.record_name, self.partner.display_name)
        self.assertTrue(line.message)

    def test_create_activity_requires_assignee(self):
        line = self.env['nord_sync.failure.wizard.line'].create({
            'wizard_id': self.env['nord_sync.failure.wizard'].create({}).id,
            'res_model': 'res.partner', 'res_id': self.partner.id,
        })
        with self.assertRaises(UserError):
            line.action_create_activity()

    def test_create_activity_schedules_on_target_record(self):
        line = self.env['nord_sync.failure.wizard.line'].create({
            'wizard_id': self.env['nord_sync.failure.wizard'].create({}).id,
            'res_model': 'res.partner', 'res_id': self.partner.id,
            'assignee_id': self.assignee.id, 'activity_note': 'please check this',
        })
        line.action_create_activity()
        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'), ('res_id', '=', self.partner.id),
        ])
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.assignee)
        self.assertIn('please check this', activity.note)
        self.assertEqual(activity.date_deadline, fields.Date.context_today(self.env.user))

    def test_create_activity_uses_chosen_deadline(self):
        deadline = date.today() + timedelta(days=5)
        line = self.env['nord_sync.failure.wizard.line'].create({
            'wizard_id': self.env['nord_sync.failure.wizard'].create({}).id,
            'res_model': 'res.partner', 'res_id': self.partner.id,
            'assignee_id': self.assignee.id, 'activity_deadline': deadline,
        })
        line.action_create_activity()
        activity = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'), ('res_id', '=', self.partner.id),
        ])
        self.assertEqual(activity.date_deadline, deadline)

    def test_open_related_record_returns_act_window(self):
        line = self.env['nord_sync.failure.wizard.line'].create({
            'wizard_id': self.env['nord_sync.failure.wizard'].create({}).id,
            'res_model': 'res.partner', 'res_id': self.partner.id,
        })
        action = line.action_open_related_record()
        self.assertEqual(action['res_model'], 'res.partner')
        self.assertEqual(action['res_id'], self.partner.id)

    def test_open_for_current_failures_lists_distinct_owners(self):
        Queue = self.env['nord.sync.queue']
        Queue.create({
            'owner_res_model': 'res.partner', 'owner_res_id': self.partner.id,
            'company_id': self.env.company.id, 'status': 'failed', 'last_error': 'x',
        })
        Queue.create({
            'owner_res_model': 'res.partner', 'owner_res_id': self.partner.id,
            'company_id': self.env.company.id, 'status': 'failed', 'last_error': 'x',
        })
        action = self.env['nord_sync.failure.wizard'].action_open_for_current_failures()
        wizard = self.env['nord_sync.failure.wizard'].browse(action['res_id'])
        self.assertEqual(len(wizard.line_ids), 1)  # same owner twice -> one line

    def test_model_breakdown_counts_per_distinct_model(self):
        wizard = self.env['nord_sync.failure.wizard'].create({'line_ids': [
            (0, 0, {'res_model': 'mrp.workorder', 'res_id': 1}),
            (0, 0, {'res_model': 'mrp.workorder', 'res_id': 2}),
            (0, 0, {'res_model': 'sale.order', 'res_id': 1}),
        ]})
        self.assertEqual(wizard.model_breakdown, 'mrp.workorder: 2, sale.order: 1')

    def test_model_breakdown_empty_when_single_model(self):
        wizard = self.env['nord_sync.failure.wizard'].create({'line_ids': [
            (0, 0, {'res_model': 'sale.order', 'res_id': 1}),
        ]})
        self.assertFalse(wizard.model_breakdown)

    def test_retry_now_resends_failed_entries_for_wizard_companies(self):
        # Real gap, user-reported: the list view already had its own Retry
        # Now (nord.sync.queue.action_retry_now) — the systray wizard had
        # no equivalent, only Create Activity/Open Related Record per line.
        self.env['nord_sync.config']._set_cloud_base_url('http://cloud.example.com')
        config = self.env['nord_sync.config'].create({
            'company_id': self.env.company.id, 'enabled': True, 'company_uid': 'test-uid',
        })
        entry = self.env['nord.sync.queue'].create({
            'owner_res_model': 'res.partner', 'owner_res_id': self.partner.id,
            'company_id': config.company_id.id, 'status': 'failed', 'last_error': 'old error',
        })
        wizard = self.env['nord_sync.failure.wizard'].create({'line_ids': [(0, 0, {
            'res_model': 'res.partner', 'res_id': self.partner.id, 'message': 'x',
        })]})
        with patch(POST_TARGET, return_value=Mock(raise_for_status=Mock())) as mocked_post:
            wizard.action_retry_now()
        mocked_post.assert_called_once()
        self.assertEqual(entry.status, 'sent')
