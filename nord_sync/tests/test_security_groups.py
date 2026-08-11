from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNordSyncSecurityGroups(TransactionCase):
    """Nord Sync User/Manager are deliberately narrower than
    base.group_system — this is the one runnable check that the ir.rule
    scoping Manager's base.automation/ir.actions.server access actually holds
    (a typo in the domain, or a missing rule, would silently open every
    Automation Rule in the instance to Manager).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].create({
            'name': 'Nord Sync User Test',
            'login': 'test_nord_sync_user',
            'group_ids': [(4, cls.env.ref('nord_sync.group_nord_sync_user').id)],
        })
        cls.manager = cls.env['res.users'].create({
            'name': 'Nord Sync Manager Test',
            'login': 'test_nord_sync_manager',
            'group_ids': [(4, cls.env.ref('nord_sync.group_nord_sync_manager').id)],
        })
        cls.config = cls.env['nord_sync.config'].create({
            'company_id': cls.env.company.id, 'company_uid': 'sec-test-uid',
        })
        cls.other_automation = cls.env['base.automation'].create({
            'name': 'Unrelated: Contact created',
            'model_id': cls.env.ref('base.model_res_partner').id,
            'trigger': 'on_create',
        })
        # Own fixture rather than a real source addon's xmlid (nord_sync_mrp's
        # "MO confirmed" rule, say) — the base module is source-agnostic,
        # so this test only needs a record matching the
        # ir.rule's actual scoping mechanism: name like 'Nord Sync'.
        cls.nord_sync_rule = cls.env['base.automation'].create({
            'name': 'Nord Sync: Test Rule',
            'model_id': cls.env.ref('base.model_res_partner').id,
            'trigger': 'on_create',
        })

    def test_user_can_read_queue(self):
        self.env['nord.sync.queue'].create({
            'res_model': 'mrp.production', 'res_id': 1, 'operation': 'write',
            'company_id': self.env.company.id,
        })
        entries = self.env['nord.sync.queue'].with_user(self.user).search([])
        self.assertTrue(entries)

    def test_user_cannot_write_config(self):
        with self.assertRaises(AccessError):
            self.config.with_user(self.user).write({'company_uid': 'hacked'})

    def test_manager_can_write_config(self):
        self.config.with_user(self.manager).write({'company_uid': 'updated-by-manager'})
        self.assertEqual(self.config.company_uid, 'updated-by-manager')

    def test_manager_sees_only_nord_sync_automation_rules(self):
        visible = self.env['base.automation'].with_user(self.manager).search([
            ('id', 'in', [self.nord_sync_rule.id, self.other_automation.id]),
        ])
        self.assertIn(self.nord_sync_rule, visible)
        self.assertNotIn(self.other_automation, visible)

    def test_manager_cannot_write_unrelated_automation_rule(self):
        with self.assertRaises(AccessError):
            self.other_automation.with_user(self.manager).write({'active': False})
