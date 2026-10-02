from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestWakeThrottle(TransactionCase):
    """_nord_sync_wake_due / _cron_send_throttled_wakes: Wake Mode Throttled
    paces the wake webhook to at most one attempt per wake_throttle_minutes,
    without ever delaying the underlying nord.sync.queue entry itself.
    """

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        vals.setdefault('company_uid', 'test-uid')
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_immediate_mode_always_due(self):
        config = self._configure(wake_mode='immediate', last_wake_sent=fields.Datetime.now())
        self.assertTrue(config._nord_sync_wake_due())

    def test_throttled_mode_due_when_never_sent(self):
        config = self._configure(wake_mode='throttled', wake_throttle_minutes=5)
        self.assertTrue(config._nord_sync_wake_due())

    def test_throttled_mode_not_due_within_window(self):
        config = self._configure(
            wake_mode='throttled', wake_throttle_minutes=5,
            last_wake_sent=fields.Datetime.now() - timedelta(minutes=1),
        )
        self.assertFalse(config._nord_sync_wake_due())

    def test_throttled_mode_due_after_window(self):
        config = self._configure(
            wake_mode='throttled', wake_throttle_minutes=5,
            last_wake_sent=fields.Datetime.now() - timedelta(minutes=6),
        )
        self.assertTrue(config._nord_sync_wake_due())

    def test_throttled_write_still_enqueues_immediately_but_skips_webhook(self):
        config = self._configure(
            wake_mode='throttled', wake_throttle_minutes=5,
            last_wake_sent=fields.Datetime.now(),
        )
        with patch(POST_TARGET) as mocked_post:
            config.write({'job_naming_mode': 'source_document'})
        mocked_post.assert_not_called()
        entry = self.env['nord.sync.queue'].search([('owner_res_model', '=', 'nord_sync.config')])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.status, 'pending')

    def test_cron_sends_only_when_due(self):
        self.env['nord_sync.config']._set_cloud_base_url('http://cloud.example.com')
        due = self._configure(wake_mode='throttled', wake_throttle_minutes=5)
        not_due = self._configure(
            company_id=self.env['res.company'].create({'name': 'Other Co'}).id,
            wake_mode='throttled', wake_throttle_minutes=5,
            last_wake_sent=fields.Datetime.now(),
        )
        self.env['nord.sync.queue'].create({
            'owner_res_model': 'nord_sync.config', 'owner_res_id': due.company_id.id,
            'company_id': due.company_id.id,
        })
        self.env['nord.sync.queue'].create({
            'owner_res_model': 'nord_sync.config', 'owner_res_id': not_due.company_id.id,
            'company_id': not_due.company_id.id,
        })
        with patch(POST_TARGET) as mocked_post:
            self.env['nord_sync.config']._cron_send_throttled_wakes()
        self.assertEqual(mocked_post.call_count, 1)
        self.assertTrue(due.last_wake_sent)
