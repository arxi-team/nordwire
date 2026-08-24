from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncJobStage(TransactionCase):

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            stage = self.env['nord_sync.job.stage'].create({'name': 'No Config Stage'})
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', stage.id), ('owner_res_model', '=', 'nord_sync.job.stage'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            stage = self.env['nord_sync.job.stage'].create({'name': 'Cutting', 'sequence': 5})
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', stage.id), ('owner_res_model', '=', 'nord_sync.job.stage'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.line_ids.operation, 'create')
        self.assertEqual(entry.payload['name'], 'Cutting')
        self.assertEqual(entry.payload['sequence'], 5)

    def test_write_enqueues_with_current_payload(self):
        self._configure()
        with patch(POST_TARGET):
            stage = self.env['nord_sync.job.stage'].create({'name': 'Before Rename'})
            stage.write({'name': 'After Rename'})
        entries = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', stage.id), ('owner_res_model', '=', 'nord_sync.job.stage'),
            ('line_ids.operation', '=', 'write'),
        ])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.payload['name'], 'After Rename')

    def test_unlink_enqueues_before_record_is_gone(self):
        self._configure()
        with patch(POST_TARGET):
            stage = self.env['nord_sync.job.stage'].create({'name': 'Removed Stage'})
            stage_id = stage.id
            stage.unlink()
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', stage_id), ('owner_res_model', '=', 'nord_sync.job.stage'),
            ('line_ids.operation', '=', 'unlink'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.payload['name'], 'Removed Stage')


@tagged('post_install', '-at_install')
class TestNordSyncStateMappingSourceSelection(TransactionCase):
    """No Nord Sync Source addon installed here — source_model/source_value
    have nothing registered, so the Selections are empty. Behavior once a source
    IS registered is tested in that source's own addon (see
    nord_sync_mrp/tests/test_nord_sync_state_mapping.py).
    """

    def test_source_model_selection_empty_with_no_source_addon_installed(self):
        if self.env['nord_sync.config']._nord_sync_available_native_sources():
            self.skipTest('a Nord Sync Source addon is installed in this DB')
        rec = self.env['nord_sync.state.mapping'].new({})
        self.assertEqual(rec._selection_source_model(), [])

    def test_source_value_selection_empty_with_no_source_addon_installed(self):
        # source_value never depends on source_model (get_views resolves a
        # dynamic Selection unbound, so a self.source_model-scoped list would
        # come back empty for every row, not just the unregistered ones) —
        # it's a flat union across every registered source, empty only when
        # there's nothing registered at all.
        if self.env['nord_sync.config']._nord_sync_available_native_sources():
            self.skipTest('a Nord Sync Source addon is installed in this DB')
        rec = self.env['nord_sync.state.mapping'].new({'source_model': 'does.not.exist'})
        self.assertEqual(rec._selection_source_value(), [])

    def test_source_value_selection_dedups_colliding_values_across_sources(self):
        # Two sources pointing at the same field guarantees a value collision
        # — the union must not duplicate it, and every real stored value must
        # still resolve to some entry (never crash the browser's SelectionField).
        fake_sources = [
            {'source_model': 'res.partner', 'source_field': 'type', 'label': 'Fake A'},
            {'source_model': 'res.partner', 'source_field': 'type', 'label': 'Fake B'},
        ]
        with patch.object(
            type(self.env['nord_sync.config']), '_nord_sync_available_native_sources', return_value=fake_sources,
        ):
            rec = self.env['nord_sync.state.mapping'].new({})
            result = rec._selection_source_value()
        partner_type_selection = self.env['res.partner']._fields['type'].selection
        self.assertEqual(len(result), len(partner_type_selection))
        self.assertEqual({pair[0] for pair in result}, {pair[0] for pair in partner_type_selection})
