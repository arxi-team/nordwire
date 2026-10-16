from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

POST_TARGET = 'odoo.addons.nord_sync.models.nord_sync_config.requests.post'


@tagged('post_install', '-at_install')
class TestJobNamingSignal(TransactionCase):
    """write() on nord_sync.config pushes the client's job naming
    preference (install wizard's Job Naming step, or a later Settings
    edit) to the Core via the same nord.sync.queue channel as job stages/
    state mapping/source-installed signals.
    """

    def _configure(self, **vals):
        vals.setdefault('enabled', True)
        return self.env['nord_sync.config'].create({'company_id': self.env.company.id, **vals})

    def test_write_job_naming_mode_pushes_signal(self):
        config = self._configure()
        with patch(POST_TARGET):
            config.write({'job_naming_mode': 'source_document'})
        entry = self.env['nord.sync.queue'].search([('owner_res_model', '=', 'nord_sync.config')])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.payload['job_naming_mode'], 'source_document')

    def test_write_custom_prefix_included_in_payload(self):
        config = self._configure()
        with patch(POST_TARGET):
            config.write({'job_naming_mode': 'custom_prefix', 'job_naming_custom_prefix': 'ACME-JOB/'})
        entry = self.env['nord.sync.queue'].search([('owner_res_model', '=', 'nord_sync.config')])
        self.assertEqual(entry.payload['job_naming_custom_prefix'], 'ACME-JOB/')

    def test_write_unrelated_field_does_not_push(self):
        config = self._configure()
        with patch(POST_TARGET) as mocked_post:
            config.write({'company_uid': 'some-uid'})
        mocked_post.assert_not_called()
        self.assertFalse(self.env['nord.sync.queue'].search([('owner_res_model', '=', 'nord_sync.config')]))

    def test_write_while_disabled_does_not_push(self):
        config = self._configure(enabled=False)
        with patch(POST_TARGET) as mocked_post:
            config.write({'job_naming_mode': 'source_document'})
        mocked_post.assert_not_called()
        self.assertFalse(self.env['nord.sync.queue'].search([('owner_res_model', '=', 'nord_sync.config')]))
