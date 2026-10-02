# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

from odoo.addons.nord_sync import post_init_hook


@tagged('post_install', '-at_install')
class TestPostInitHook(TransactionCase):
    """Base post_init_hook is source-agnostic — MRP-specific backfill
    (Resource/Employee Bridge, Manufacturing group grant) moved to
    nord_sync_mrp's own post_init_hook (see that addon's own
    tests/test_post_init_hook.py) when the source addons split back apart.
    What's left here: the generic backfill dispatch (a no-op with no source
    addon installed, exercised implicitly by not raising) and seeding
    nord_sync.payload.field.config defaults.
    """

    def test_seeds_payload_field_config_only_for_installed_models(self):
        # nord_sync alone has none of the 10 known models' addons installed
        # — every row should be skipped, not created inert.
        post_init_hook(self.env)
        self.assertFalse(self.env['nord_sync.payload.field.config'].search([
            ('company_id', '=', self.env.company.id),
        ]))

    def test_seeding_is_idempotent(self):
        config = self.env['nord_sync.payload.field.config'].create({
            'company_id': self.env.company.id, 'res_model': 'sale.order',
        })
        post_init_hook(self.env)
        self.assertEqual(self.env['nord_sync.payload.field.config'].search([
            ('company_id', '=', self.env.company.id), ('res_model', '=', 'sale.order'),
        ]), config)
