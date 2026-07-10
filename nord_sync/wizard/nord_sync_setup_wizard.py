import re

import odoo.release
from odoo import api, fields, models
from odoo.exceptions import UserError

SUPPORTED_MAJOR_VERSIONS = (19,)
URL_RE = re.compile(r'^https?://', re.IGNORECASE)


class NordSyncSetupWizard(models.TransientModel):
    _name = 'nord.sync.setup.wizard'
    _description = 'Nord Sync Setup Wizard'

    state = fields.Selection([
        ('preflight', 'Pre-flight'),
        ('config', 'Configuration'),
    ], default='preflight', required=True)

    odoo_version_supported = fields.Boolean(compute='_compute_preflight')
    preflight_warning = fields.Text(compute='_compute_preflight')

    company_uid = fields.Char(string='Tenant UID')
    cloud_webhook_url = fields.Char(string='Cloud Webhook URL')
    mo_filter_criteria = fields.Char(
        string='MO Filter Criteria',
        help='Not yet enforced - reserved for Phase 2.',
    )

    @api.depends('state')
    def _compute_preflight(self):
        version_supported = odoo.release.version_info[0] in SUPPORTED_MAJOR_VERSIONS

        warnings = []
        if not version_supported:
            warnings.append(
                f'This Odoo version ({odoo.release.version_info[0]}) is not a supported '
                f'Nord Sync target ({", ".join(map(str, SUPPORTED_MAJOR_VERSIONS))}).'
            )

        for wizard in self:
            wizard.odoo_version_supported = version_supported
            wizard.preflight_warning = '\n'.join(warnings) if warnings else False

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def action_next(self):
        self.ensure_one()
        self.state = 'config'
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        self.state = 'preflight'
        return self._reopen()

    def action_save_config(self):
        self.ensure_one()
        if not self.company_uid or not self.cloud_webhook_url:
            raise UserError('Tenant UID and Cloud Webhook URL are required.')
        if not URL_RE.match(self.cloud_webhook_url):
            raise UserError('Cloud Webhook URL must start with http:// or https://.')

        self.env['nord.sync.config']._create_or_update_for_company(self.env.company, {
            'company_uid': self.company_uid,
            'cloud_webhook_url': self.cloud_webhook_url,
            'mo_filter_criteria': self.mo_filter_criteria,
        })
        # The native webhook action (data/nord_sync_automation.xml) is shared by every
        # company on this Odoo install - there is one Cloud ingest URL, not one per tenant
        # (plan §4.1), so the last wizard run to save a URL wins for all companies.
        self.env.ref('nord_sync.webhook_action_queue_to_cloud').sudo().webhook_url = self.cloud_webhook_url
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Nord Sync',
                'message': 'Configuration saved.',
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
