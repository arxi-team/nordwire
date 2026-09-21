from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.nord_sync_mrp import post_init_hook

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestPostInitHook(TransactionCase):
    """post_init_hook must backfill pre-existing mrp.workcenter/hr.employee
    records — both only push on create/write/unlink, so anything that
    existed before this addon was installed (the default "Administrator"
    employee, almost always) would otherwise never reach the Core.
    """

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_backfills_existing_workcenter_and_employee(self):
        self._configure()
        wc = self.env['mrp.workcenter'].create({'name': 'Pre-Existing WC'})
        employee = self.env['hr.employee'].create({'name': 'Pre-Existing Employee'})
        # Wipe out whatever create() itself already enqueued — the backfill
        # must (re-)enqueue on its own, standing in for "this record existed
        # before the addon/config ever existed".
        self.env['nord.sync.queue'].search([]).unlink()
        with patch(POST_TARGET):
            post_init_hook(self.env)
        self.assertTrue(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', wc.id), ('owner_res_model', '=', 'mrp.workcenter'),
        ]))
        self.assertTrue(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', employee.id), ('owner_res_model', '=', 'hr.employee'),
        ]))

    def test_backfills_existing_bom(self):
        # Real bug found live, 2026-08-18: this was the one
        # pre-existing-record model missed by the original backfill — a
        # pre-existing BOM never reached the Core, so an MO referencing it
        # just warned and created a BOM-less job, forever.
        self._configure()
        product_tmpl = self.env['product.product'].create({'name': 'Pre-Existing Product', 'type': 'consu'}).product_tmpl_id
        bom = self.env['mrp.bom'].create({'product_tmpl_id': product_tmpl.id, 'product_qty': 1.0})
        self.env['nord.sync.queue'].search([]).unlink()
        with patch(POST_TARGET):
            post_init_hook(self.env)
        self.assertTrue(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', bom.id), ('owner_res_model', '=', 'mrp.bom'),
        ]))

    def test_backfills_existing_mrp_production(self):
        # Real gap found live, 2026-08-25 grill-me audit: the source itself
        # (mrp.production) was never in this backfill, only its support
        # models above — an MO created/closed entirely during a disabled
        # window stayed invisible to the Core forever unless edited again.
        self._configure()
        product = self.env['product.product'].create({'name': 'Pre-Existing Product'})
        mo = self.env['mrp.production'].create({'product_id': product.id})
        self.env['nord.sync.queue'].search([]).unlink()
        with patch(POST_TARGET):
            post_init_hook(self.env)
        self.assertTrue(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', mo.id), ('owner_res_model', '=', 'mrp.production'),
        ]))

    def test_grants_nord_sync_access_tiered_by_manufacturing_level(self):
        """A Manufacturing Administrator gets Nordwire Manager (implies
        User); a plain Manufacturing User gets only Nordwire User — mirrors
        Manufacturing's own tiering instead of handing everyone Nordwire's
        admin-level access just for having any Manufacturing group.
        """
        user_group = self.env.ref('nord_sync.group_nord_sync_user')
        manager_group = self.env.ref('nord_sync.group_nord_sync_manager')
        mrp_user = self.env['res.users'].create({
            'name': 'Pre-Existing MRP User', 'login': 'test_pre_existing_mrp_user',
            'group_ids': [(4, self.env.ref('mrp.group_mrp_user').id)],
        })
        mrp_admin = self.env['res.users'].create({
            'name': 'Pre-Existing MRP Admin', 'login': 'test_pre_existing_mrp_admin',
            'group_ids': [(4, self.env.ref('mrp.group_mrp_manager').id)],
        })
        outsider = self.env['res.users'].create({
            'name': 'No Manufacturing Access', 'login': 'test_no_mrp_access',
        })
        with patch(POST_TARGET):
            post_init_hook(self.env)
        self.assertIn(user_group, mrp_user.group_ids)
        self.assertNotIn(manager_group, mrp_user.group_ids)
        self.assertIn(manager_group, mrp_admin.group_ids)
        # implied_ids grants effective access without adding a literal
        # group_ids membership — has_group() is the correct check, not
        # group_ids (direct assignments only).
        self.assertTrue(mrp_admin.has_group('nord_sync.group_nord_sync_user'))
        self.assertNotIn(user_group, outsider.group_ids)
        self.assertNotIn(manager_group, outsider.group_ids)
