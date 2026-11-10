from odoo.modules.neutralize import get_neutralization_queries
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNordSyncMrpNeutralize(TransactionCase):
    """PDA demo URLs: wake_core() falls back to a default URL when the
    parameter is empty, so neutralize must point it somewhere dead instead."""

    def _neutralize(self):
        self.env.flush_all()  # the ORM defers writes; raw SQL below must see them
        for query in get_neutralization_queries(['nord_sync_mrp']):
            self.env.cr.execute(query)
        self.env.invalidate_all()
        self.env.registry.clear_cache()  # get_param is cached; SQL bypasses the ORM

    def test_demo_urls_are_neutralized(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('nord_sync.demo_webhook_url', 'https://demo.example/hook')
        params.set_param('nord_sync.demo_core_pull_url', 'https://demo.example/pull')
        self._neutralize()
        self.assertFalse(params.get_param('nord_sync.demo_webhook_url'))
        self.assertEqual(params.get_param('nord_sync.demo_core_pull_url'), 'http://127.0.0.1:1/neutralized')

    def test_demo_pull_url_is_set_even_when_missing(self):
        params = self.env['ir.config_parameter'].sudo()
        params.search([('key', '=', 'nord_sync.demo_core_pull_url')]).unlink()
        self._neutralize()
        self.assertEqual(params.get_param('nord_sync.demo_core_pull_url'), 'http://127.0.0.1:1/neutralized')
