from odoo import api, fields, models


class NordSyncConfig(models.Model):
    _name = 'nord.sync.config'
    _description = 'Nord Sync Configuration'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    company_uid = fields.Char(
        string='Tenant UID', required=True,
        help='Identifier for this Odoo installation as a Nord tenant. '
             'Not a regular Odoo user id.',
    )
    cloud_webhook_url = fields.Char(string='Cloud Webhook URL', required=True)
    mo_filter_criteria = fields.Char(
        string='MO Filter Criteria',
        help='Reserved for a future phase: which manufacturing orders should '
             'be synced. Stored only, not yet enforced.',
    )
    active = fields.Boolean(default=True, help='Pause sync for this company without deleting the configuration.')

    _company_id_unique = models.Constraint(
        'UNIQUE(company_id)',
        'Only one Nord Sync configuration is allowed per company.',
    )

    @api.model
    def _create_or_update_for_company(self, company, values):
        config = self.sudo().search([('company_id', '=', company.id)], limit=1)
        values = dict(values, company_id=company.id)
        if config:
            config.write(values)
        else:
            config = self.sudo().create(values)
        return config
