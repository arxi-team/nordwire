# -*- coding: utf-8 -*-
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 5


class NordSyncConfig(models.Model):
    """Nord Sync connection config — one record per company, replacing the
    nord_sync_enabled/nord_sync_company_uid/nord_sync_cloud_webhook_url fields
    that used to live directly on res.company. Kept company-scoped (not a
    single global ir.config_parameter) so multi-company opt-in still works —
    see docs/plano_addon_odoo_cliente_producao.md §7 (data scope section).
    """
    _name = 'nord_sync.config'
    _description = 'Nord Sync Configuration'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    enabled = fields.Boolean(string='Nord Sync Enabled')
    company_uid = fields.Char(
        string='Nord Company UID',
        help='Tenant UID assigned by Nord (matches a res.company.uid on the Nord '
             'Cloud/Core side). Sent in the wake webhook payload and used to '
             'identify this company on queue pulls.',
    )
    cloud_webhook_url = fields.Char(
        string='Nord Cloud Webhook URL',
        help='Nord Cloud endpoint to notify when something changes '
             '(e.g. http://<cloud-host>/nordos/sync/nord_sync/webhook).',
    )

    _company_unique = models.Constraint(
        'UNIQUE(company_id)', 'Only one Nord Sync configuration per company is allowed.',
    )

    @api.model
    def _get_for_company(self, company):
        return self.search([('company_id', '=', company.id)], limit=1)

    @api.model
    def _get_or_create_for_company(self, company):
        config = self._get_for_company(company)
        return config or self.create({'company_id': company.id})

    def _enqueue_and_notify(self, res_model, res_id, operation, payload):
        """Shared by every source model's create/write/unlink override (mrp.production,
        product.product, ...) — one nord.sync.queue entry + one best-effort wake
        webhook per change, so each model only needs to supply its own payload.
        """
        self.ensure_one()
        entry = self.env['nord.sync.queue'].sudo().create({
            'res_model': res_model,
            'res_id': res_id,
            'operation': operation,
            'company_id': self.company_id.id,
            'data': payload,
        })
        sent, error = self._send_wake_webhook()
        if sent is not None:
            entry.write({'status': 'sent' if sent else 'failed', 'last_error': error})
        return entry

    def _send_wake_webhook(self):
        """Returns (status, error): status is None if skipped (not configured
        yet), True/False if attempted; error is the exception text on failure,
        else None — surfaced on nord.sync.queue.last_error (Fase 4 Slice 4.2)
        instead of only ever living in the server log.
        """
        self.ensure_one()
        if not self.cloud_webhook_url or not self.company_uid:
            return None, None
        try:
            response = requests.post(
                self.cloud_webhook_url,
                json={'company_uid': self.company_uid},
                timeout=WEBHOOK_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except Exception as exc:
            _logger.warning('nord_sync: failed to notify Nord Cloud webhook: %s', exc)
            return False, str(exc)
        return True, None

    def _retry_failed_webhooks(self):
        """Docs/NordSyncFase2, Fase 4 Slice 4.3: nord.sync.queue.status='failed' is
        exactly what this retries (see that field's help text). One webhook ping
        per company, not per entry — the wake payload carries no entry-specific
        data (just company_uid), so a single successful ping resolves every
        pending entry for this company at once, same as the Core's own
        reconciliation (_incremental_sync) already guarantees on its side; this
        cron only shortens the wait, it's not the correctness guarantee.
        """
        self.ensure_one()
        failed_entries = self.env['nord.sync.queue'].sudo().search([
            ('company_id', '=', self.company_id.id), ('status', '=', 'failed'),
        ])
        if not failed_entries:
            return False
        sent, error = self._send_wake_webhook()
        if sent:
            failed_entries.write({'status': 'sent', 'last_error': False})
        elif error:
            failed_entries.write({'last_error': error})
        return bool(sent)

    @api.model
    def _cron_retry_failed_webhooks(self):
        for config in self.search([('enabled', '=', True)]):
            config._retry_failed_webhooks()
