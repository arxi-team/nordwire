from odoo import api, fields, models


class NordSyncQueue(models.Model):
    _name = 'nord.sync.queue'
    _description = 'Nord Sync Queue'
    _order = 'id asc'

    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='cascade')
    company_uid = fields.Char(
        help='Tenant UID copied from nord.sync.config at push time. Left blank unless the '
             'company has an active config AND the shared webhook action has a URL - the '
             "Odoo->Cloud Automation Rule's filter_domain skips blank rows, so sync stays "
             'paused (or not-yet-configured) without dropping the audit trail. Never leave '
             "this truthy with a blank webhook_url: Odoo's native webhook action raises "
             'synchronously (not just a failed POST) when its URL is empty, which would break '
             'whatever transaction (e.g. an MO save) triggered the push.',
    )
    model_name = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    operation = fields.Selection([
        ('create', 'Create'),
        ('write', 'Write'),
        ('unlink', 'Unlink'),
    ], required=True)
    payload = fields.Json()

    @api.model
    def _push(self, company_id, model_name, operation, res_id, payload=None):
        """Enqueue one sync entry.

        Creating the row is the trigger: a base.automation rule (on_create on
        this model, see data/nord_sync_automation.xml) fires the native Odoo
        webhook action to notify the Cloud. The row is always created, even
        when the company has no active nord.sync.config, so the audit trail/
        reconciliation cursor never has gaps - company_uid is just left blank,
        which the automation's filter_domain uses to skip the webhook call.
        Also requires the shared webhook action to actually have a URL (see
        company_uid's help text for why - a blank URL isn't just a no-op).
        """
        config = self.env['nord.sync.config'].sudo().search([('company_id', '=', company_id)], limit=1)
        ready = bool(config.active and config.company_uid)
        if ready:
            action = self.env.ref('nord_sync.webhook_action_queue_to_cloud', raise_if_not_found=False)
            ready = bool(action and action.webhook_url)
        return self.sudo().create({
            'company_id': company_id,
            'company_uid': config.company_uid if ready else False,
            'model_name': model_name,
            'operation': operation,
            'res_id': res_id,
            'payload': payload or {},
        })

    def _to_command(self):
        self.ensure_one()
        return {
            'seq': self.id,
            'model': self.model_name,
            'operation': self.operation,
            'res_id': self.res_id,
            'data': self.payload or {},
        }

    @api.model
    def action_create_test_entry(self):
        """Manual Phase 1 verification aid: push a fictitious entry (no source model yet)."""
        self._push(
            self.env.company.id, 'nord_sync.test', 'create', 0,
            {'note': 'Fictitious entry created for manual Phase 1 verification.'},
        )
