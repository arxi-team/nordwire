# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NordSyncInstallWizardSourceLine(models.TransientModel):
    """One row per discoverable Nord Sync Source addon — discovered by
    naming convention (any `ir.module.module` named `nord_sync_*`), never a
    hardcoded list, so a future `nord_sync_project`/etc. addon shows up here
    without touching this wizard's code.

    Installing the addon IS still the real "choose this source" action —
    this step is a convenience that calls the same
    `button_immediate_install()` Apps screen uses, not a parallel enable/
    disable toggle. Already-installed sources show up read-only/checked —
    nothing here can uninstall one.
    """
    _name = 'nord_sync.install.wizard.source.line'
    _description = 'Nord Sync Install Wizard — Source Line'
    _order = 'id'

    wizard_id = fields.Many2one('nord_sync.install.wizard', required=True, ondelete='cascade')
    module_id = fields.Many2one('ir.module.module', required=True, readonly=True)
    name = fields.Char(related='module_id.shortdesc', readonly=True)
    summary = fields.Char(related='module_id.summary', readonly=True)
    installed = fields.Boolean(compute='_compute_installed')
    selected = fields.Boolean(
        default=False,
        help='Install this Nord Sync Source now, alongside the base module.',
    )

    @api.depends('module_id.state')
    def _compute_installed(self):
        for line in self:
            line.installed = line.module_id.state == 'installed'
