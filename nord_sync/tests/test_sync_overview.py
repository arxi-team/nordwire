# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSyncOverview(TransactionCase):
    """get_overview_data() backs the Sync Overview client action (cards row +
    queue/inbox/failures panels) — plain @api.model ORM calls, no controller
    route, matching this addon's own nord_sync_systray.js convention.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Queue = cls.env['nord.sync.queue']

    def _create(self, model, res_id, status='pending', is_sealed=False, last_error=None):
        return self.Queue.create({
            'company_id': self.env.company.id,
            'owner_res_model': model, 'owner_res_id': res_id,
            'status': status, 'is_sealed': is_sealed, 'last_error': last_error,
        })

    def test_kpis_match_direct_orm_counts(self):
        self._create('nord_sync_overview.test_model_a', 1, status='pending')
        self._create('nord_sync_overview.test_model_a', 2, status='sent', is_sealed=True)
        self._create('nord_sync_overview.test_model_b', 3, status='failed', last_error='boom')
        self._create('nord_sync_overview.test_model_b', 4, status='failed', is_sealed=True, last_error='boom2')

        data = self.Queue.get_overview_data()

        domain = [('company_id', 'in', self.env.companies.ids)]
        for status in ('pending', 'sent', 'failed'):
            expected = self.Queue.search_count(domain + [('status', '=', status)])
            self.assertEqual(data['kpis'][status], expected)
        expected_unsealed = self.Queue.search_count(domain + [('is_sealed', '=', False)])
        self.assertEqual(data['kpis']['unsealed'], expected_unsealed)

    def test_queue_panel_lists_one_row_per_header(self):
        h1 = self._create('nord_sync_overview.test_model_a', 10, status='pending')
        h2 = self._create('nord_sync_overview.test_model_a', 11, status='sent')

        data = self.Queue.get_overview_data()
        rows = {row['key']: row for row in data['queue']}
        self.assertEqual(rows[f'queue-{h1.id}']['owner'], 'nord_sync_overview.test_model_a #10')
        self.assertEqual(rows[f'queue-{h1.id}']['status'], 'pending')
        self.assertEqual(rows[f'queue-{h2.id}']['status'], 'sent')

    def test_inbox_panel_lists_current_inbox_entries(self):
        entry = self.env['nord_sync.inbox'].create({
            'endpoint': 'result', 'res_model': 'res.partner',
            'payload': {'res_id': 1}, 'company_id': self.env.company.id,
        })

        data = self.Queue.get_overview_data()
        rows = {row['key']: row for row in data['inbox']}
        self.assertEqual(rows[f'inbox-{entry.id}']['endpoint'], 'result')
        self.assertEqual(rows[f'inbox-{entry.id}']['res_model'], 'res.partner')
        self.assertEqual(rows[f'inbox-{entry.id}']['status'], 'pending')

    def test_failures_panel_shows_raw_error_and_cheap_owner_form(self):
        self._create('nord_sync_overview.test_model_d', 99, status='failed', last_error='boom: timeout')

        data = self.Queue.get_overview_data()
        entries = [f for f in data['failures'] if f['owner_res_model'] == 'nord_sync_overview.test_model_d']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['owner_res_id'], 99)
        self.assertEqual(entries[0]['last_error'], 'boom: timeout')
        self.assertEqual(entries[0]['owner'], 'nord_sync_overview.test_model_d #99')

    def test_sent_and_pending_headers_never_appear_in_failures_panel(self):
        self._create('nord_sync_overview.test_model_e', 1, status='pending')
        self._create('nord_sync_overview.test_model_e', 2, status='sent')

        data = self.Queue.get_overview_data()
        self.assertFalse([f for f in data['failures'] if f['owner_res_model'] == 'nord_sync_overview.test_model_e'])

    def test_action_open_queue_filtered_builds_domain_per_kpi(self):
        action = self.Queue.action_open_queue_filtered(status='pending')
        self.assertEqual(action['res_model'], 'nord.sync.queue')
        self.assertEqual(action['domain'], [('status', '=', 'pending')])

        action = self.Queue.action_open_queue_filtered(unsealed=True)
        self.assertEqual(action['domain'], [('is_sealed', '=', False)])

    def test_empty_queue_returns_zeroed_kpis_and_empty_breakdowns(self):
        # A fresh company, isolated via allowed_company_ids so this test
        # never depends on no other test/signal in this DB having left a
        # nord.sync.queue row behind for the default company.
        company = self.env['res.company'].create({'name': 'Sync Overview Empty Co'})
        data = self.Queue.with_context(allowed_company_ids=[company.id]).get_overview_data()
        self.assertEqual(data['kpis'], {'pending': 0, 'sent': 0, 'failed': 0, 'unsealed': 0})
        self.assertEqual(data['queue'], [])
        self.assertEqual(data['inbox'], [])
        self.assertEqual(data['failures'], [])
