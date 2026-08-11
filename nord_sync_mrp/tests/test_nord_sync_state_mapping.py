from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestNordSyncStateMapping(TransactionCase):
    """mrp.production as the registered native source — the generic
    (nothing registered) case is tested in
    nord_sync/tests/test_nord_sync_state_mapping.py.
    """

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

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
                'source_model': 'mrp.production', 'source_value': 'confirmed',
            })
        self.assertFalse(self.env['nord.sync.queue'].search([
            ('res_id', '=', mapping.id), ('res_model', '=', 'nord_sync.state.mapping'),
        ]))
        mocked_post.assert_not_called()

    def test_enabled_config_enqueues_on_create(self):
        self._configure()
        with patch(POST_TARGET):
            mapping = self.env['nord_sync.state.mapping'].create({
                'source_model': 'mrp.production', 'source_value': 'confirmed', 'target_state': 'open',
            })
        entry = self.env['nord.sync.queue'].search([
            ('res_id', '=', mapping.id), ('res_model', '=', 'nord_sync.state.mapping'),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.data['source_model'], 'mrp.production')
        self.assertEqual(entry.data['source_value'], 'confirmed')
        self.assertEqual(entry.data['target_state'], 'open')
        self.assertFalse(entry.data['target_job_stage_source_res_id'])

    def test_payload_carries_target_job_stage_source_res_id_not_name(self):
        # The Core resolves the stage by the client-side stage's own id
        # (correlation key), not by name — names can be renamed after the
        # mapping is pushed.
        self._configure()
        with patch(POST_TARGET):
            stage = self.env['nord_sync.job.stage'].create({'name': 'Cutting'})
            mapping = self.env['nord_sync.state.mapping'].create({
                'source_model': 'mrp.production', 'source_value': 'confirmed',
                'target_job_stage_id': stage.id,
            })
        entry = self.env['nord.sync.queue'].search([
            ('res_id', '=', mapping.id), ('res_model', '=', 'nord_sync.state.mapping'),
        ])
        self.assertEqual(entry.data['target_job_stage_source_res_id'], stage.id)

    def test_unlink_enqueues_before_record_is_gone(self):
        self._configure()
        with patch(POST_TARGET):
            mapping = self.env['nord_sync.state.mapping'].create({
                'source_model': 'mrp.production', 'source_value': 'cancel', 'target_state': 'cancelled',
            })
            mapping_id = mapping.id
            mapping.unlink()
        entry = self.env['nord.sync.queue'].search([
            ('res_id', '=', mapping_id), ('res_model', '=', 'nord_sync.state.mapping'), ('operation', '=', 'unlink'),
        ])
        self.assertEqual(len(entry), 1)

    def test_duplicate_source_value_for_same_company_raises(self):
        self._configure()
        with patch(POST_TARGET):
            self.env['nord_sync.state.mapping'].create({
                'source_model': 'mrp.production', 'source_value': 'confirmed',
            })
            with self.assertRaises(Exception):
                self.env['nord_sync.state.mapping'].create({
                    'source_model': 'mrp.production', 'source_value': 'confirmed',
                })


@tagged('post_install', '-at_install')
class TestEnsureBackwardCompatStateMapping(TransactionCase):
    """'cancel' used to be a hardcoded string check, now it's a mapping
    lookup — this backfills the row so nothing regresses."""

    def _configure(self, company):
        return self.env['nord_sync.config'].create({
            'company_id': company.id, 'enabled': True, 'company_uid': 'backward-compat-uid',
        })

    def test_creates_cancel_mapping_when_missing(self):
        company = self.env['res.company'].create({'name': 'Backward Compat Test Co'})
        config = self._configure(company)
        with patch(POST_TARGET):
            mapping = config._ensure_backward_compat_state_mapping()
        self.assertEqual(mapping.source_model, 'mrp.production')
        self.assertEqual(mapping.source_value, 'cancel')
        self.assertEqual(mapping.target_state, 'cancelled')

    def test_idempotent_does_not_duplicate(self):
        company = self.env['res.company'].create({'name': 'Backward Compat Idempotent Co'})
        config = self._configure(company)
        with patch(POST_TARGET):
            first = config._ensure_backward_compat_state_mapping()
            second = config._ensure_backward_compat_state_mapping()
        self.assertEqual(first, second)
        mappings = self.env['nord_sync.state.mapping'].search([
            ('company_id', '=', company.id), ('source_model', '=', 'mrp.production'), ('source_value', '=', 'cancel'),
        ])
        self.assertEqual(len(mappings), 1)

    def test_pushes_to_queue(self):
        company = self.env['res.company'].create({'name': 'Backward Compat Push Test Co'})
        config = self._configure(company)
        self.env['nord_sync.config']._set_cloud_base_url('http://cloud.example.com')
        with patch(POST_TARGET) as mocked_post:
            mapping = config._ensure_backward_compat_state_mapping()
        mocked_post.assert_called()
        entry = self.env['nord.sync.queue'].search([
            ('res_model', '=', 'nord_sync.state.mapping'), ('res_id', '=', mapping.id),
        ])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.data['target_state'], 'cancelled')
