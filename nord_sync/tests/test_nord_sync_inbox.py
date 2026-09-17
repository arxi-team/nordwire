# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

UPSERT_TARGET = 'odoo.addons.nord_sync.models.nord_sync_resource.NordSyncResource._nord_sync_upsert_from_core'


@tagged('post_install', '-at_install')
class TestNordSyncInboxCron(TransactionCase):
    """nord_sync.inbox._cron_process_pending — the off-request dispatch
    every inbound route (/result, /workorder_event, /resources) now feeds
    instead of applying its own domain effect in-request. Base nord_sync
    alone has no source addon registered, so every 'result'/'workorder_event'
    dispatch here hits nord_sync.config's own base "Unsupported res_model"
    fallback — the 'resources' endpoint is the only one this addon can
    exercise end to end on its own (nord_sync_mrp's own equivalent tests
    cover mrp.production/mrp.workorder).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord_sync.config']._get_or_create_for_company(cls.env.company)

    def _entry(self, endpoint, res_model, payload):
        return self.env['nord_sync.inbox'].create({
            'endpoint': endpoint, 'res_model': res_model, 'payload': payload,
            'company_id': self.env.company.id,
        })

    def test_dispatch_calls_config_extension_point_directly(self):
        """Not through HTTP — same (applied, message) shape the old
        controller-owned extension point produced for an unsupported
        res_model."""
        applied, message = self.config._nord_sync_apply_result({'res_id': 1}, 'res.partner')
        self.assertFalse(applied)
        self.assertIn('Unsupported res_model', message)
        applied, message = self.config._nord_sync_apply_workorder_event({}, 'res.partner', 'session_start')
        self.assertFalse(applied)
        self.assertIn('Unsupported res_model', message)

    def test_cron_marks_unsupported_res_model_entry_failed(self):
        entry = self._entry('result', 'res.partner', {'res_id': 1})
        self.env['nord_sync.inbox']._cron_process_pending()
        self.assertEqual(entry.status, 'failed')
        self.assertIn('Unsupported res_model', entry.last_error)

    def test_no_domain_side_effect_before_cron_runs(self):
        self._entry('resources', 'nord_sync.resource', {
            'resources': [{'uid': 'inbox-pending-test-uid', 'complete_name': 'Pending Resource'}],
        })
        self.assertFalse(self.env['nord_sync.resource'].search([('uid', '=', 'inbox-pending-test-uid')]))

    def test_cron_applies_resources_endpoint_and_unlinks_on_success(self):
        resource = self.env['nord_sync.resource'].create({
            'uid': 'inbox-cron-test-uid', 'complete_name': 'Old Name', 'company_id': self.env.company.id,
        })
        entry = self._entry('resources', 'nord_sync.resource', {
            'resources': [{'uid': 'inbox-cron-test-uid', 'complete_name': 'New Name'}],
        })
        self.env['nord_sync.inbox']._cron_process_pending()
        self.assertFalse(entry.exists())
        self.assertEqual(resource.complete_name, 'New Name')

    def test_savepoint_isolates_one_bad_entry_from_the_rest_of_the_batch(self):
        """A raised exception mid-dispatch (a raw DB constraint violation in
        production, mocked here) must not poison the transaction for the
        entry.write({'status': 'failed', ...}) that follows, nor for any
        other entry later in the same batch — see the savepoint in
        _cron_process_pending.
        """
        first = self._entry('resources', 'nord_sync.resource', {'resources': []})
        second = self._entry('resources', 'nord_sync.resource', {'resources': []})
        with patch(UPSERT_TARGET, side_effect=[Exception('boom'), None]):
            self.env['nord_sync.inbox']._cron_process_pending()
        self.assertEqual(first.status, 'failed')
        self.assertIn('boom', first.last_error)
        self.assertFalse(second.exists())  # the second entry still processed and succeeded

    def test_cron_never_raises_out_of_a_normal_run(self):
        self._entry('result', 'res.partner', {'res_id': 1})
        self._entry('workorder_event', 'res.partner', {'event_type': 'session_start'})
        self.env['nord_sync.inbox']._cron_process_pending()  # must not raise


@tagged('post_install', '-at_install')
class TestNordSyncInboxFailureVisibility(TransactionCase):
    """A failed nord_sync.inbox entry surfaces through the same Sync
    Failures systray/wizard already built for the outbound direction
    (nord.sync.queue) — not a second mechanism to learn.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord_sync.config']._get_or_create_for_company(cls.env.company)
        cls.partner = cls.env['res.partner'].create({'name': 'Inbox Failure Test Partner'})

    def _failed_entry(self, endpoint, res_model, payload, last_error='boom'):
        return self.env['nord_sync.inbox'].create({
            'endpoint': endpoint, 'res_model': res_model, 'payload': payload,
            'company_id': self.env.company.id, 'status': 'failed', 'last_error': last_error,
        })

    def test_failed_owners_resolves_res_id_from_payload(self):
        self._failed_entry('result', 'res.partner', {'res_id': self.partner.id})
        self._failed_entry('workorder_event', 'res.partner', {'res_id': self.partner.id})
        owners = self.env['nord_sync.inbox']._nord_sync_failed_owners()
        self.assertEqual({(m, i) for m, i, _msg, _create_date in owners}, {('res.partner', self.partner.id)})

    def test_failed_owners_resolves_resources_endpoint_onto_the_company_config(self):
        self._failed_entry('resources', 'nord_sync.resource', {'resources': []})
        owners = self.env['nord_sync.inbox']._nord_sync_failed_owners()
        self.assertEqual(
            [(m, i) for m, i, _msg, _create_date in owners], [('nord_sync.config', self.config.id)],
        )

    def test_systray_count_folds_in_failed_inbox_entries(self):
        self._failed_entry('result', 'res.partner', {'res_id': self.partner.id})
        self.assertEqual(self.env['nord.sync.queue'].systray_get_failed_count(), 1)

    def test_systray_count_mixes_queue_and_inbox_failures(self):
        self.env['nord.sync.queue'].create({
            'owner_res_model': 'res.partner', 'owner_res_id': self.partner.id + 1000,
            'company_id': self.env.company.id, 'status': 'failed', 'last_error': 'x',
        })
        self._failed_entry('result', 'res.partner', {'res_id': self.partner.id})
        self.assertEqual(self.env['nord.sync.queue'].systray_get_failed_count(), 2)

    def test_wizard_lists_failed_inbox_entries_alongside_queue(self):
        self.env['nord.sync.queue'].create({
            'owner_res_model': 'res.partner', 'owner_res_id': self.partner.id,
            'company_id': self.env.company.id, 'status': 'failed', 'last_error': 'queue error',
        })
        other_partner = self.env['res.partner'].create({'name': 'Inbox Failure Test Partner 2'})
        self._failed_entry('result', 'res.partner', {'res_id': other_partner.id}, last_error='inbox error')
        action = self.env['nord_sync.failure.wizard'].action_open_for_current_failures()
        wizard = self.env['nord_sync.failure.wizard'].browse(action['res_id'])
        self.assertEqual(len(wizard.line_ids), 2)
        self.assertIn('inbox error', wizard.line_ids.mapped('message'))

    def test_wizard_dedupes_same_owner_between_queue_and_inbox(self):
        self.env['nord.sync.queue'].create({
            'owner_res_model': 'res.partner', 'owner_res_id': self.partner.id,
            'company_id': self.env.company.id, 'status': 'failed', 'last_error': 'queue error',
        })
        self._failed_entry('result', 'res.partner', {'res_id': self.partner.id}, last_error='inbox error')
        action = self.env['nord_sync.failure.wizard'].action_open_for_current_failures()
        wizard = self.env['nord_sync.failure.wizard'].browse(action['res_id'])
        self.assertEqual(len(wizard.line_ids), 1)
