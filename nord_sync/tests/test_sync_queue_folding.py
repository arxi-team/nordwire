# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestSyncQueueFolding(TransactionCase):
    """Master/child folding: every change still creates its own
    nord.sync.queue.line — folding only decides which header (nord.sync.queue)
    that line lands under, via _enqueue_and_notify.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['nord_sync.config'].create({
            'company_id': cls.env.company.id, 'enabled': True,
        })

    def _enqueue(self, res_model, res_id, payload=None):
        with patch(POST_TARGET):
            return self.config._enqueue_and_notify(res_model, res_id, 'write', payload or {})

    def test_first_change_becomes_its_own_header(self):
        header = self._enqueue('mrp.workcenter', 1)
        self.assertEqual((header.owner_res_model, header.owner_res_id), ('mrp.workcenter', 1))
        self.assertEqual(len(header.line_ids), 1)

    def test_workorder_folds_into_already_open_production_header(self):
        production = self._enqueue('mrp.production', 10)
        workorder = self._enqueue('mrp.workorder', 20, {'production_source_res_id': 10})
        self.assertEqual(workorder, production)
        self.assertEqual(len(production.line_ids), 2)

    def test_quality_check_folds_into_already_open_production_header(self):
        production = self._enqueue('mrp.production', 11)
        check = self._enqueue('quality.check', 30, {'production_source_res_id': 11})
        self.assertEqual(check, production)

    def test_workorder_arriving_before_production_still_shares_one_header(self):
        # Real hazard (Odoo ORM hook order): a workorder's own enqueue can
        # fire before its MO's — no open header exists yet for that owner
        # (mrp.production, 12), so the workorder's own call creates one.
        # mrp.production's own call, moments later, resolves the exact same
        # owner and folds into it — same header either way, regardless of
        # which change arrived first.
        workorder = self._enqueue('mrp.workorder', 21, {'production_source_res_id': 12})
        production = self._enqueue('mrp.production', 12)
        self.assertEqual(workorder, production)
        self.assertEqual(len(production.line_ids), 2)

    def test_unrelated_owners_never_fold_together(self):
        workcenter = self._enqueue('mrp.workcenter', 2)
        employee = self._enqueue('hr.employee', 3)
        self.assertNotEqual(workcenter, employee)

    def test_repeated_write_to_same_standalone_record_folds(self):
        first = self._enqueue('mrp.workcenter', 4)
        second = self._enqueue('mrp.workcenter', 4)
        self.assertEqual(first, second)
        self.assertEqual(len(first.line_ids), 2)

    def test_sealed_header_does_not_accept_new_lines(self):
        production = self._enqueue('mrp.production', 13)
        production.is_sealed = True
        workorder = self._enqueue('mrp.workorder', 22, {'production_source_res_id': 13})
        self.assertNotEqual(workorder, production)
        self.assertEqual((workorder.owner_res_model, workorder.owner_res_id), ('mrp.production', 13))

    def test_deleting_header_cascades_to_lines(self):
        production = self._enqueue('mrp.production', 14)
        self._enqueue('mrp.workorder', 23, {'production_source_res_id': 14})
        line_ids = production.line_ids.ids
        production.unlink()
        self.assertFalse(self.env['nord.sync.queue.line'].browse(line_ids).exists())

    def test_child_without_owner_becomes_its_own_header(self):
        header = self._enqueue('mrp.workorder', 999, {})
        self.assertEqual((header.owner_res_model, header.owner_res_id), ('mrp.workorder', 999))

    # ── payload aggregation ──────────────────────────────────────────────────────

    def test_aggregate_payload_with_no_lines_still_identifies_owner(self):
        header = self.env['nord.sync.queue'].create({
            'company_id': self.env.company.id,
            'owner_res_model': 'mrp.production', 'owner_res_id': 40,
        })
        self.assertEqual(header._nord_sync_aggregate_payload(), {'model': 'mrp.production', 'res_id': 40})

    def test_aggregate_payload_merges_own_line_bare(self):
        header = self._enqueue('mrp.production', 41, {'name': 'Solo MO'})
        self.assertEqual(
            header._nord_sync_aggregate_payload(),
            {'model': 'mrp.production', 'res_id': 41, 'name': 'Solo MO'},
        )

    def test_aggregate_payload_nests_other_models_by_key(self):
        header = self._enqueue('mrp.production', 42, {'name': 'Aggregated MO'})
        self._enqueue('mrp.workorder', 51, {'production_source_res_id': 42, 'expected_duration': 1.0})
        payload = header._nord_sync_aggregate_payload()
        self.assertEqual(payload['name'], 'Aggregated MO')
        self.assertEqual(payload['mrp.workorder'], [
            {'res_id': 51, 'operation': 'write', 'payload': {
                'production_source_res_id': 42, 'expected_duration': 1.0,
            }},
        ])

    def test_aggregate_payload_keeps_distinct_records_of_same_model_separate(self):
        header = self._enqueue('mrp.production', 43, {'name': 'Multi WO MO'})
        self._enqueue('mrp.workorder', 52, {'production_source_res_id': 43})
        self._enqueue('mrp.workorder', 53, {'production_source_res_id': 43})
        payload = header._nord_sync_aggregate_payload()
        self.assertEqual(sorted(item['res_id'] for item in payload['mrp.workorder']), [52, 53])

    def test_aggregate_payload_collapses_repeated_edit_of_same_record_to_latest(self):
        header = self._enqueue('mrp.production', 44, {'name': 'Repeated Edit MO'})
        self._enqueue('mrp.workorder', 54, {'production_source_res_id': 44, 'expected_duration': 1.0})
        self._enqueue('mrp.workorder', 54, {'production_source_res_id': 44, 'expected_duration': 2.0})
        payload = header._nord_sync_aggregate_payload()
        self.assertEqual(len(payload['mrp.workorder']), 1)
        self.assertEqual(payload['mrp.workorder'][0]['payload']['expected_duration'], 2.0)

    def test_aggregate_payload_collapses_repeated_edit_of_own_owner_to_latest(self):
        header = self._enqueue('mrp.production', 45, {'name': 'First'})
        self._enqueue('mrp.production', 45, {'name': 'Second'})
        self.assertEqual(
            header._nord_sync_aggregate_payload(),
            {'model': 'mrp.production', 'res_id': 45, 'name': 'Second'},
        )

    def test_aggregate_payload_puts_model_and_res_id_first(self):
        header = self._enqueue('mrp.production', 47, {'name': 'Ordered MO'})
        self.assertEqual(list(header._nord_sync_aggregate_payload().keys())[:2], ['model', 'res_id'])

    def test_build_entry_uses_owner_fields_and_latest_own_operation(self):
        header = self._enqueue('mrp.production', 46, {'name': 'Entry MO'})
        entry = header._nord_sync_build_entry()
        self.assertEqual(entry['model'], 'mrp.production')
        self.assertEqual(entry['res_id'], 46)
        self.assertEqual(entry['operation'], 'write')
        self.assertEqual(entry['payload']['name'], 'Entry MO')

    def test_header_sealed_while_waiting_for_lock_falls_back_to_fresh_header(self):
        """Pins the exact race _nord_sync_lock_for_update closes: a header
        found open by _enqueue_and_notify's own search, but sealed (by a
        concurrent /queue pull) before this call's lock is actually granted.
        A real cross-connection reproduction needs two live DB connections
        genuinely racing — not reproducible deterministically inside a
        single TransactionCase transaction — so the seal is simulated here
        as a side effect of the lock call itself, standing in for "another
        connection won that race and committed first". What's under test is
        real: does the post-lock is_sealed recheck correctly discard this
        header and open a fresh one, rather than silently keep using it.
        """
        header = self._enqueue('mrp.production', 61, {'name': 'Raced MO'})
        Queue = type(header)
        original_lock = Queue._nord_sync_lock_for_update

        def seal_then_lock(recordset):
            recordset.write({'is_sealed': True})
            return original_lock(recordset)

        with patch.object(Queue, '_nord_sync_lock_for_update', seal_then_lock):
            workorder = self._enqueue('mrp.workorder', 62, {'production_source_res_id': 61})

        self.assertNotEqual(workorder, header)
        self.assertFalse(workorder.is_sealed)
        self.assertEqual((workorder.owner_res_model, workorder.owner_res_id), ('mrp.production', 61))
