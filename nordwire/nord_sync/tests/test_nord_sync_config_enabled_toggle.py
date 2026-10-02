from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNordSyncConfigEnabledToggle(TransactionCase):
    """'enabled' is editable any time from Settings, not just at install —
    real gap found live, 2026-08-18: re-enabling outside the install wizard
    never backfilled pre-existing records the way the wizard's own Finish
    step does, so anything created/edited during a disabled window was lost
    with no way to catch up.
    """

    def _configure(self, **vals):
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_enabling_backfills_existing_records(self):
        config = self._configure(enabled=False)
        with patch.object(type(config), '_nord_sync_backfill_existing_records') as mocked_backfill:
            config.write({'enabled': True})
        mocked_backfill.assert_called_once()

    def test_disabling_does_not_backfill(self):
        config = self._configure(enabled=True)
        with patch.object(type(config), '_nord_sync_backfill_existing_records') as mocked_backfill:
            config.write({'enabled': False})
        mocked_backfill.assert_not_called()

    def test_writing_enabled_true_again_does_not_rebackfill(self):
        config = self._configure(enabled=True)
        with patch.object(type(config), '_nord_sync_backfill_existing_records') as mocked_backfill:
            config.write({'enabled': True})
        mocked_backfill.assert_not_called()

    def test_unrelated_write_does_not_trigger_backfill_check(self):
        config = self._configure(enabled=True)
        with patch.object(type(config), '_nord_sync_backfill_existing_records') as mocked_backfill:
            config.write({'company_uid': 'some-uid'})
        mocked_backfill.assert_not_called()

    def test_multi_record_write_only_backfills_the_ones_that_transitioned(self):
        company_a = self.env['res.company'].create({'name': 'Toggle Test Co A'})
        company_b = self.env['res.company'].create({'name': 'Toggle Test Co B'})
        config_a = self._configure(enabled=False, company_id=company_a.id)
        config_b = self._configure(enabled=True, company_id=company_b.id)
        configs = config_a + config_b
        with patch.object(type(config_a), '_nord_sync_backfill_existing_records') as mocked_backfill:
            configs.write({'enabled': True})
        mocked_backfill.assert_called_once()
