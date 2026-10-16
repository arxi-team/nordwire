from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncStateMapping(TransactionCase):
    """mrp.production as the registered native source — the generic
    (nothing registered) case is tested in
    nord_sync/tests/test_nord_sync_state_mapping.py.
    """

    def setUp(self):
        super().setUp()
        # Own company per test, not self.env.company — a mrp.production/
        # confirmed mapping for the default company can already exist from
        # unrelated earlier work, and (company_id, source_model, source_value)
        # is unique.
        self.company = self.env['res.company'].create({'name': 'State Mapping Test Co'})

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.company.id, **vals})

    def test_source_model_selection_includes_mrp_production(self):
        rec = self.env['nord_sync.state.mapping'].new({})
        self.assertIn(('mrp.production', 'Manufacturing Orders'), rec._selection_source_model())

    def test_source_value_selection_reflects_mrp_production_state(self):
        rec = self.env['nord_sync.state.mapping'].new({'source_model': 'mrp.production'})
        state_field = self.env['mrp.production']._fields['state']
        self.assertEqual(rec._selection_source_value(), state_field.selection)

    def test_changing_source_model_clears_stale_source_value(self):
        rec = self.env['nord_sync.state.mapping'].new({
            'source_model': 'mrp.production', 'source_value': 'confirmed',
        })
        rec.source_model = 'does.not.exist'
        rec._onchange_source_model()
        self.assertFalse(rec.source_value)

    def test_no_config_does_not_enqueue(self):
        with patch(POST_TARGET) as mocked_post:
            mapping = self.env['nord_sync.state.mapping'].create({
                'source_model': 'mrp.production', 'source_value': 'confirmed', 'company_id': self.company.id,
            })
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', mapping.id), ('owner_res_model', '=', 'nord_sync.state.mapping'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            mapping = self.env['nord_sync.state.mapping'].create({
                'source_model': 'mrp.production', 'source_value': 'confirmed', 'company_id': self.company.id,
            })
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', mapping.id), ('owner_res_model', '=', 'nord_sync.state.mapping'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.payload['source_model'], 'mrp.production')
        self.assertEqual(entry.payload['source_value'], 'confirmed')
        self.assertFalse(entry.payload['target_job_stage_source_res_id'])

    def test_payload_carries_target_job_stage_source_res_id_not_name(self):
        # The Core resolves the stage by the client-side stage's own id
        # (correlation key), not by name — names can be renamed after the
        # mapping is pushed.
        self._configure()
        with patch(POST_TARGET):
            stage = self.env['nord_sync.job.stage'].create({'name': 'Cutting'})
            mapping = self.env['nord_sync.state.mapping'].create({
                'source_model': 'mrp.production', 'source_value': 'confirmed',
                'target_job_stage_id': stage.id, 'company_id': self.company.id,
            })
        entry = self.env['nord.sync.queue'].search([
            ('owner_res_id', '=', mapping.id), ('owner_res_model', '=', 'nord_sync.state.mapping'),
        ])
        self.assertEqual(entry.payload['target_job_stage_source_res_id'], stage.id)

    def test_unlink_enqueues_before_record_is_gone(self):
        self._configure()
        with patch(POST_TARGET):
            mapping = self.env['nord_sync.state.mapping'].create({
                'source_model': 'mrp.production', 'source_value': 'cancel', 'company_id': self.company.id,
            })
            mapping_id = mapping.id
            mapping.unlink()
        line = self.env['nord.sync.queue.line'].search([
            ('res_id', '=', mapping_id), ('res_model', '=', 'nord_sync.state.mapping'), ('operation', '=', 'unlink'),
        ])
        self.assertEqual(len(line), 1)

    def test_duplicate_source_value_for_same_company_raises(self):
        self._configure()
        with patch(POST_TARGET):
            self.env['nord_sync.state.mapping'].create({
                'source_model': 'mrp.production', 'source_value': 'confirmed', 'company_id': self.company.id,
            })
            with self.assertRaises(Exception):
                self.env['nord_sync.state.mapping'].create({
                    'source_model': 'mrp.production', 'source_value': 'confirmed', 'company_id': self.company.id,
                })

# TestEnsureBackwardCompatStateMapping removed — _ensure_backward_compat_state_mapping()
# no longer exists. The install wizard's action_confirm() creates a real
# per-row mapping (via _default_mapping_targets picking the 'Cancelled' job
# stage by name) for every native state, cancel included, so no separate
# backfill step is needed any more — see
# nord_sync_mrp/tests/test_install_wizard.py::test_confirm_creates_cancel_mapping.
