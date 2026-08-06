# -*- coding: utf-8 -*-
from odoo import api, fields, models, release
from odoo.exceptions import UserError
from odoo.tools import config

SUPPORTED_MAJOR_VERSIONS = (19,)

RUN_BEFORE_PREFIX = 'run_before_'
RUN_AFTER_PREFIX = 'run_after_'


class NordSyncInstallWizard(models.TransientModel):
    """Fase 1.2 (Docs/PLAN.md): install wizard, 3 steps — pre-flight, connection, finish.

    Multi-step shape (state + _steps + run_before_/run_after_ per-step hooks)
    mirrors the pattern used by /odoo17/custom/addons/server-casca-rija/appstore/
    integration_shopify's configuration.wizard (a project unrelated to Nord — only
    borrowed here as UX inspiration, per the user's explicit request 2026-08-04).
    That project has a full reusable abstract base (configuration.wizard) because
    it backs several real integrations; this wizard doesn't build that abstraction
    since Nord Sync is the only one today — the step machinery lives directly here.
    """
    _name = 'nord_sync.install.wizard'
    _description = 'Nord Sync Installation Wizard'

    _steps = [
        ('step_preflight', 'Pre-flight'),
        ('step_connection', 'Connection'),
        ('step_finish', 'Finish'),
    ]

    state = fields.Char(default='step_preflight')
    state_index = fields.Integer(compute='_compute_state_index_and_visibility')
    show_previous = fields.Boolean(compute='_compute_state_index_and_visibility')
    show_next = fields.Boolean(compute='_compute_state_index_and_visibility')
    show_finish = fields.Boolean(compute='_compute_state_index_and_visibility')

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
    )
    company_uid = fields.Char(string='Nord Company UID')

    cron_active = fields.Boolean(string='Scheduler Active', readonly=True)
    odoo_version_supported = fields.Boolean(string='Odoo Version Supported', readonly=True)
    preflight_ok = fields.Boolean(readonly=True)
    preflight_message = fields.Char(readonly=True)

    # ── step machine ────────────────────────────────────────────────────────────

    def get_steps(self):
        return self._steps

    @api.depends('state', 'preflight_ok')
    def _compute_state_index_and_visibility(self):
        for wiz in self:
            steps = wiz.get_steps()
            keys = [s[0] for s in steps]
            index = keys.index(wiz.state) if wiz.state in keys else 0
            wiz.state_index = index
            wiz.show_previous = index != 0
            can_advance = wiz.state != 'step_preflight' or wiz.preflight_ok
            wiz.show_next = (index + 1 != len(steps)) and can_advance
            wiz.show_finish = (index + 1 == len(steps))

    def run_step_action(self, prefix):
        self.ensure_one()
        method = getattr(self, prefix + self.state, None)
        if not method:
            return True
        return method()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_next_step(self):
        self.ensure_one()
        if self.run_step_action(RUN_AFTER_PREFIX):
            steps = self.get_steps()
            self.state = steps[self.state_index + 1][0]
            self.run_step_action(RUN_BEFORE_PREFIX)
        return self._reopen()

    def action_previous_step(self):
        self.ensure_one()
        steps = self.get_steps()
        self.state = steps[self.state_index - 1][0]
        self.run_step_action(RUN_BEFORE_PREFIX)
        return self._reopen()

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        company = self.env['res.company'].browse(vals['company_id']) if vals.get('company_id') else self.env.company
        config_rec = self.env['nord_sync.config']._get_for_company(company)
        if config_rec:
            vals.setdefault('company_uid', config_rec.company_uid)
        vals.update(self._run_preflight())
        return vals

    # ── Step 1: Pre-flight ───────────────────────────────────────────────────────

    @api.model
    def _run_preflight(self):
        cron_active = (config.get('max_cron_threads') or 0) > 0
        version_supported = release.version_info[0] in SUPPORTED_MAJOR_VERSIONS
        problems = []
        if not cron_active:
            problems.append(
                'The task scheduler (cron) is disabled on this server '
                '(max_cron_threads=0) — periodic reconciliation will never run.'
            )
        if not version_supported:
            problems.append(
                f'This addon targets Odoo {SUPPORTED_MAJOR_VERSIONS[0]}, but the '
                f'server is running Odoo {release.version_info[0]}.'
            )
        return {
            'cron_active': cron_active,
            'odoo_version_supported': version_supported,
            'preflight_ok': cron_active and version_supported,
            'preflight_message': ' '.join(problems) or 'Environment ready to configure Nord Sync.',
        }

    def action_refresh_preflight(self):
        self.ensure_one()
        self.write(self._run_preflight())
        return self._reopen()

    def run_after_step_preflight(self):
        if not self.preflight_ok:
            raise UserError('Fix the environment issues before continuing (see pre-flight message).')
        return True

    # ── Step 2: Connection ───────────────────────────────────────────────────────

    def run_after_step_connection(self):
        if not self.company_uid:
            raise UserError('Fill in the company UID before continuing.')
        return True

    # ── Step 3: Finish ───────────────────────────────────────────────────────────

    def action_confirm(self):
        """Finish: saves the config, then hands off straight to the "MO confirmed"
        Automation Rule (data/nord_sync_automation.xml) instead of just closing —
        so the trigger criterion (Docs/NordSyncFase2, Slice 2.4) is the very next
        thing the person configuring this sees, ready to narrow if needed, rather
        than a separate thing to go find afterwards.
        """
        self.ensure_one()
        if not self.preflight_ok:
            raise UserError('Fix the environment issues before continuing (see pre-flight message).')
        config_rec = self.env['nord_sync.config']._get_or_create_for_company(self.company_id)
        config_rec.write({'enabled': True, 'company_uid': self.company_uid})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'base.automation',
            'res_id': self.env.ref('nord_sync.automation_mrp_production_confirmed').id,
            'view_mode': 'form',
            'target': 'current',
        }
