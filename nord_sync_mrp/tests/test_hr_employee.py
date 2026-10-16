from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestHrEmployeeNordSync(TransactionCase):
    """Resource Bridge, person side."""

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            employee = self.env['hr.employee'].create({'name': 'No Config Employee'})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', employee.id), ('owner_res_model', '=', 'hr.employee'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        # hr.employee.create() itself writes to the just-created record more
        # than once internally (resource.resource linkage, computed fields,
        # …), each write folding its own line under the same header — same
        # known noise as mrp.workorder's own reassignment test. Asserted on
        # the header's merged payload (reflects final state), not an exact
        # line count.
        self._configure()
        with patch(POST_TARGET):
            employee = self.env['hr.employee'].create({'name': 'Jane Operator'})
        entries = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', employee.id), ('owner_res_model', '=', 'hr.employee'),
        ], order='id desc', limit=1)
        self.assertTrue(entries)
        self.assertEqual(entries.payload['name'], 'Jane Operator')

    def test_write_enqueues_with_current_payload(self):
        self._configure()
        with patch(POST_TARGET):
            employee = self.env['hr.employee'].create({'name': 'Before Rename'})
            checkpoint = self.env['nord.sync.queue.line'].search([], order='id desc', limit=1).id
            employee.write({'name': 'After Rename'})
        entries = self.env['nord.sync.queue.line'].search([
            ('id', '>', checkpoint),
            ('res_id', '=', employee.id), ('res_model', '=', 'hr.employee'), ('operation', '=', 'write'),
        ])
        self.assertTrue(entries)
        self.assertEqual(entries[0].data['name'], 'After Rename')

    def test_unlink_enqueues_before_record_is_gone(self):
        self._configure()
        with patch(POST_TARGET):
            employee = self.env['hr.employee'].create({'name': 'Removed Employee'})
            employee_id = employee.id
            employee.unlink()
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', employee_id), ('owner_res_model', '=', 'hr.employee'),
            ('line_ids.operation', '=', 'unlink'),
        ])
        self.assertEqual(len(entry), 1)


@tagged('post_install', '-at_install')
class TestHrEmployeeAutonomousPlaceholder(TransactionCase):
    """_nord_sync_get_or_create_autonomous_employee — the shared "Nordwire"
    employee a machine-autonomous session (no real operator assigned)
    attributes its mrp.workcenter.productivity timer to, see
    mrp_workorder.py's own _nord_sync_button_start_bypassing_employee_check.
    No nord_sync.config needed — a plain get-or-create, no push involved.
    """

    def test_creates_it_on_first_call(self):
        with patch(POST_TARGET):
            employee = self.env['hr.employee']._nord_sync_get_or_create_autonomous_employee(self.env.company)
        self.assertEqual(employee.name, 'Nordwire')
        self.assertEqual(employee.company_id, self.env.company)

    def test_reuses_the_same_record_on_later_calls(self):
        with patch(POST_TARGET):
            first = self.env['hr.employee']._nord_sync_get_or_create_autonomous_employee(self.env.company)
            second = self.env['hr.employee']._nord_sync_get_or_create_autonomous_employee(self.env.company)
        self.assertEqual(first, second)
        self.assertEqual(
            self.env['hr.employee'].search_count([('name', '=', 'Nordwire')]), 1,
        )

    def test_scoped_per_company_not_shared_globally(self):
        other_company = self.env['res.company'].create({'name': 'Autonomous Placeholder Other Co'})
        with patch(POST_TARGET):
            here = self.env['hr.employee']._nord_sync_get_or_create_autonomous_employee(self.env.company)
            there = self.env['hr.employee']._nord_sync_get_or_create_autonomous_employee(other_company)
        self.assertNotEqual(here, there)
        self.assertEqual(here.company_id, self.env.company)
        self.assertEqual(there.company_id, other_company)
