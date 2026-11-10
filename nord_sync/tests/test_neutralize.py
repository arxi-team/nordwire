from unittest.mock import patch

from odoo.modules.neutralize import get_neutralization_queries
from odoo.tests import HttpCase, TransactionCase, tagged


def _neutralize(env, *modules):
    """Runs the given modules' data/neutralize.sql the way `odoo-bin neutralize` does."""
    env.flush_all()  # the ORM defers writes; raw SQL below must see them
    for query in get_neutralization_queries(modules):
        env.cr.execute(query)
    env.invalidate_all()
    env.registry.clear_cache()  # get_param is cached; SQL bypasses the ORM


@tagged('post_install', '-at_install')
class TestNordSyncNeutralize(TransactionCase):
    """A neutralized copy of production must never reach the Nord Cloud/Core
    (found live, 2026-11-08: neutralized-looking copies kept pinging the real
    cloud webhook because nord_sync shipped no neutralize.sql)."""

    def test_neutralize_turns_sync_off(self):
        company = self.env['res.company'].create({'name': 'Neutralize Test Co'})
        with patch.object(type(self.env['nord_sync.config']), '_nord_sync_backfill_existing_records'):
            config = self.env['nord_sync.config'].create({
                'company_id': company.id, 'enabled': True, 'company_uid': 'uid-1',
            })
        self.env['ir.config_parameter'].sudo().set_param('nord_sync.cloud_base_url', 'https://cloud.example/')
        cron = self.env.ref('nord_sync.ir_cron_retry_failed_webhooks')
        cron.active = True

        _neutralize(self.env, 'nord_sync')

        self.assertFalse(config.enabled)
        self.assertFalse(self.env['ir.config_parameter'].sudo().get_param('nord_sync.cloud_base_url'))
        self.assertFalse(cron.active)

    def test_neutralized_config_sends_no_webhook(self):
        company = self.env['res.company'].create({'name': 'Neutralize Test Co 2'})
        with patch.object(type(self.env['nord_sync.config']), '_nord_sync_backfill_existing_records'):
            config = self.env['nord_sync.config'].create({
                'company_id': company.id, 'enabled': True, 'company_uid': 'uid-2',
            })
        self.env['ir.config_parameter'].sudo().set_param('nord_sync.cloud_base_url', 'https://cloud.example/')
        _neutralize(self.env, 'nord_sync')
        with patch('odoo.addons.nord_sync.models.nord_sync_config.requests.post') as post:
            sent, _error = config._send_wake_webhook()
        post.assert_not_called()
        self.assertIsNone(sent)


@tagged('post_install', '-at_install')
class TestNordSyncNeutralizeApi(HttpCase):
    """Core -> Odoo API is refused on a neutralized database, whatever the key."""

    URL = '/nord_sync/api/v1/queue'
    HEADERS = {'Authorization': 'Bearer not-a-real-key'}

    def test_api_refused_when_neutralized(self):
        self.env['ir.config_parameter'].sudo().set_param('database.is_neutralized', 'true')
        response = self.url_open(self.URL, headers=self.HEADERS)
        self.assertEqual(response.status_code, 403)
        self.assertIn('Database is neutralized', response.text)

    def test_api_normal_auth_when_not_neutralized(self):
        self.env['ir.config_parameter'].sudo().search([('key', '=', 'database.is_neutralized')]).unlink()
        response = self.url_open(self.URL, headers=self.HEADERS)
        self.assertEqual(response.status_code, 403)
        self.assertIn('Invalid API key', response.text)
