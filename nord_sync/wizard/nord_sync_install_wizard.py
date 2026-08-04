# -*- coding: utf-8 -*-
from odoo import api, fields, models, release
from odoo.exceptions import UserError
from odoo.tools import config

SUPPORTED_MAJOR_VERSIONS = (19,)


class NordSyncInstallWizard(models.TransientModel):
    """Fase 1.2 (Docs/PLAN.md): pré-voo de ambiente + configuração mínima.

    Field scope mirrors the original decision (v1 §7, "Onboarding/instalação"): only
    connection config (company UID, Cloud webhook URL) — the trigger criteria
    (Fase 2.4) isn't built yet, so it stays out of this wizard for now ("o mapeamento
    de campos fica fora do wizard").
    """
    _name = 'nord_sync.install.wizard'
    _description = 'Nord Sync Installation Wizard'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
    )
    company_uid = fields.Char(string='Nord Company UID', required=True)
    cloud_webhook_url = fields.Char(string='Nord Cloud Webhook URL', required=True)

    cron_active = fields.Boolean(string='Scheduler Active', readonly=True)
    odoo_version_supported = fields.Boolean(string='Odoo Version Supported', readonly=True)
    preflight_ok = fields.Boolean(readonly=True)
    preflight_message = fields.Char(readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
        vals.setdefault('company_uid', company.nord_sync_company_uid)
        vals.setdefault('cloud_webhook_url', company.nord_sync_cloud_webhook_url)
        vals.update(self._run_preflight())
        return vals

    @api.model
    def _run_preflight(self):
        """Checked once when the wizard opens (default_get) and again on demand
        (action_refresh_preflight) — never re-checked silently on save, so a
        problem fixed after opening the wizard still needs an explicit refresh
        before action_confirm will accept it.
        """
        cron_active = (config.get('max_cron_threads') or 0) > 0
        version_supported = release.version_info[0] in SUPPORTED_MAJOR_VERSIONS
        problems = []
        if not cron_active:
            problems.append(
                'O agendador de tarefas (cron) está desativado neste servidor '
                '(max_cron_threads=0) — a reconciliação periódica nunca vai correr.'
            )
        if not version_supported:
            problems.append(
                f'Este addon é para Odoo {SUPPORTED_MAJOR_VERSIONS[0]}, mas o '
                f'servidor corre Odoo {release.version_info[0]}.'
            )
        return {
            'cron_active': cron_active,
            'odoo_version_supported': version_supported,
            'preflight_ok': cron_active and version_supported,
            'preflight_message': ' '.join(problems) or 'Ambiente pronto para configurar o Nord Sync.',
        }

    def action_refresh_preflight(self):
        self.ensure_one()
        self.write(self._run_preflight())
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm(self):
        self.ensure_one()
        if not self.preflight_ok:
            raise UserError('Corrige os problemas de ambiente antes de continuar (ver mensagem de pré-voo).')
        self.company_id.write({
            'nord_sync_enabled': True,
            'nord_sync_company_uid': self.company_uid,
            'nord_sync_cloud_webhook_url': self.cloud_webhook_url,
        })
        return {'type': 'ir.actions.act_window_close'}
