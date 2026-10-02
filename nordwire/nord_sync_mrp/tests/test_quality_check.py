from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestQualityCheckNordSync(TransactionCase):
    """Quality Check Bridge (source side) — each workorder-tied
    quality.check pushes create/write/unlink, resolved by the Core into a
    real nord.tasks checklist item on the matching job. quality.check always
    redirects to its MO as owner — its own entries are
    nord.sync.queue.line rows, never their own header.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({'name': 'Nordwire Quality Test Product'})
        cls.instructions_type = cls.env.ref('quality.test_type_instructions')

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def _create_mo_with_workorder(self):
        wc = self.env['mrp.workcenter'].create({'name': 'Quality Test WC'})
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'product_qty': 1.0,
            'operation_ids': [(0, 0, {'name': 'Op', 'workcenter_id': wc.id, 'time_cycle_manual': 30})],
        })
        mo = self.env['mrp.production'].create({
            'product_id': self.product.id, 'product_qty': 1.0, 'bom_id': bom.id,
        })
        mo.action_confirm()
        workorder = self.env['mrp.workorder'].search([('production_id', '=', mo.id)], limit=1)
        return mo, workorder

    def _create_check(self, mo, workorder, **vals):
        vals.setdefault('test_type_id', self.instructions_type.id)
        vals.setdefault('title', 'Check the seal')
        # v17's quality.check.team_id is required with no default of its own
        # (only quality.point has one) — fine when created from a point, but
        # this test creates the check directly.
        vals.setdefault('team_id', self.env['quality.alert.team'].search([], limit=1).id)
        return self.env['quality.check'].create({
            'production_id': mo.id, 'workorder_id': workorder.id, **vals,
        })

    def test_no_config_does_not_enqueue(self):
        mo, workorder = self._create_mo_with_workorder()
        with patch(POST_TARGET) as mocked_post:
            check = self._create_check(mo, workorder)
        self.assertFalse(self.env['nord.sync.queue.line'].search([
            ('res_id', '=', check.id), ('res_model', '=', 'quality.check'),
        ]))
        mocked_post.assert_not_called()

    def test_source_not_selected_does_not_enqueue(self):
        sale_source = self.env['nord_sync.source'].search([('model', '=', 'sale.order')])
        self._configure(enabled_source_ids=[(6, 0, sale_source.ids)])
        mo, workorder = self._create_mo_with_workorder()
        with patch(POST_TARGET) as mocked_post:
            check = self._create_check(mo, workorder)
        self.assertFalse(self.env['nord.sync.queue.line'].search([
            ('res_id', '=', check.id), ('res_model', '=', 'quality.check'),
        ]))
        mocked_post.assert_not_called()

    def test_check_without_production_does_not_enqueue(self):
        # A check on e.g. a stock.picking's own quality point has no job to
        # attach to on the Core — out of scope for this bridge.
        self._configure()
        with patch(POST_TARGET) as mocked_post:
            check = self.env['quality.check'].create({
                'test_type_id': self.instructions_type.id, 'title': 'Unrelated check',
                'team_id': self.env['quality.alert.team'].search([], limit=1).id,
            })
        self.assertFalse(self.env['nord.sync.queue.line'].search([
            ('res_id', '=', check.id), ('res_model', '=', 'quality.check'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_create_with_payload(self):
        self._configure()
        mo, workorder = self._create_mo_with_workorder()
        with patch(POST_TARGET):
            check = self._create_check(mo, workorder)
        entry = self.env['nord.sync.queue.line'].search([
            ('res_id', '=', check.id), ('res_model', '=', 'quality.check'), ('operation', '=', 'create'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.data['production_source_res_id'], mo.id)
        self.assertEqual(entry.data['name'], 'Check the seal')
        self.assertEqual(entry.data['test_type'], 'instructions')
        self.assertFalse(entry.data['is_done'])
        self.assertFalse(entry.data['value'])

    def test_passfail_value_carries_quality_state(self):
        passfail_type = self.env['quality.point.test_type'].create({
            'name': 'Pass/Fail', 'technical_name': 'passfail',
        })
        self._configure()
        mo, workorder = self._create_mo_with_workorder()
        with patch(POST_TARGET):
            check = self._create_check(mo, workorder, test_type_id=passfail_type.id)
            checkpoint = self.env['nord.sync.queue.line'].search([], order='id desc', limit=1).id
            check.quality_state = 'pass'
        entries = self.env['nord.sync.queue.line'].search([
            ('id', '>', checkpoint),
            ('res_id', '=', check.id), ('res_model', '=', 'quality.check'), ('operation', '=', 'write'),
        ])
        self.assertTrue(entries)
        self.assertTrue(entries[0].data['is_done'])
        self.assertEqual(entries[0].data['value'], 'pass')

    def test_unlink_enqueues_before_record_is_gone(self):
        self._configure()
        mo, workorder = self._create_mo_with_workorder()
        with patch(POST_TARGET):
            check = self._create_check(mo, workorder)
            check_id = check.id
            check.unlink()
        entry = self.env['nord.sync.queue.line'].search([
            ('res_id', '=', check_id), ('res_model', '=', 'quality.check'), ('operation', '=', 'unlink'),
        ])
        self.assertEqual(len(entry), 1)
