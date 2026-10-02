from unittest.mock import Mock, patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestRetryFailedWebhooks(TransactionCase):

    def _configure(self, company=None, **vals):
        vals.setdefault('enabled', True)
        vals.setdefault('company_uid', 'test-uid')
        self.env['nord_sync.config']._set_cloud_base_url('http://cloud.example.com')
        return self.env['nord_sync.config'].create({'company_id': (company or self.env.company).id, **vals})

    def _failed_entry(self, company_id, res_id=1, **vals):
        vals.setdefault('last_error', 'old error')
        return self.env['nord.sync.queue'].create({
            'owner_res_model': 'mrp.production', 'owner_res_id': res_id,
            'company_id': company_id, 'status': 'failed', **vals,
        })

    def test_retry_sends_and_marks_failed_entries_sent(self):
        config = self._configure()
        entry = self._failed_entry(config.company_id.id)
        with patch(POST_TARGET, return_value=Mock(raise_for_status=Mock())) as mocked_post:
            retried = config._retry_failed_webhooks()
        mocked_post.assert_called_once()
        self.assertTrue(retried)
        self.assertEqual(entry.status, 'sent')
        self.assertFalse(entry.last_error)

    def test_retry_no_failed_entries_is_noop(self):
        config = self._configure()
        with patch(POST_TARGET) as mocked_post:
            retried = config._retry_failed_webhooks()
        mocked_post.assert_not_called()
        self.assertFalse(retried)

    def test_retry_still_failing_leaves_status_failed(self):
        config = self._configure()
        entry = self._failed_entry(config.company_id.id, last_error='old error')
        with patch(POST_TARGET, side_effect=ConnectionError('refused')):
            retried = config._retry_failed_webhooks()
        self.assertFalse(retried)
        self.assertEqual(entry.status, 'failed')
        self.assertIn('refused', entry.last_error)

    def test_retry_only_touches_own_company_entries(self):
        config = self._configure()
        other_company = self.env['res.company'].create({'name': 'Other Co'})
        other_entry = self._failed_entry(other_company.id)
        with patch(POST_TARGET, return_value=Mock(raise_for_status=Mock())):
            config._retry_failed_webhooks()
        self.assertEqual(other_entry.status, 'failed')

    def test_cron_only_processes_enabled_configs(self):
        other_company = self.env['res.company'].create({'name': 'Disabled Co'})
        enabled = self._configure()
        disabled = self._configure(company=other_company, enabled=False, company_uid='other-uid')
        entry_enabled = self._failed_entry(enabled.company_id.id)
        entry_disabled = self._failed_entry(disabled.company_id.id)
        with patch(POST_TARGET, return_value=Mock(raise_for_status=Mock())):
            self.env['nord_sync.config']._cron_retry_failed_webhooks()
        self.assertEqual(entry_enabled.status, 'sent')
        self.assertEqual(entry_disabled.status, 'failed')

    # ── Slices 4.1/4.2: systray count + manual resend ───────────────────────────

    def test_systray_count_matches_failed_entries_in_accessible_companies(self):
        config = self._configure()
        self._failed_entry(config.company_id.id, res_id=1)
        self._failed_entry(config.company_id.id, res_id=2)
        self.env['nord.sync.queue'].create({
            'owner_res_model': 'mrp.production', 'owner_res_id': 3,
            'company_id': config.company_id.id, 'status': 'sent',
        })
        count = self.env['nord.sync.queue'].systray_get_failed_count()
        self.assertEqual(count, 2)

    def test_systray_count_excludes_other_companies(self):
        other_company = self.env['res.company'].create({'name': 'Not My Co'})
        self._failed_entry(other_company.id)
        count = self.env['nord.sync.queue'].with_context(
            allowed_company_ids=[self.env.company.id],
        ).systray_get_failed_count()
        self.assertEqual(count, 0)

    def test_action_retry_now_retries_selected_entries_company(self):
        config = self._configure()
        entry = self._failed_entry(config.company_id.id)
        with patch(POST_TARGET, return_value=Mock(raise_for_status=Mock())) as mocked_post:
            entry.action_retry_now()
        mocked_post.assert_called_once()
        self.assertEqual(entry.status, 'sent')
