
# -*- coding: utf-8 -*-
from odoo import fields, models


class NordSyncInstallWizardStageLine(models.TransientModel):
    """Staging area for the wizard's Job Stages step — real nord_sync.job.stage
    records aren't created (and pushed to the Core) until Confirm, so
    switching modes or cancelling the wizard never leaves a half-authored
    push behind.
    """
    _name = 'nord_sync.install.wizard.stage.line'
    _description = 'Nordwire Install Wizard — Job Stage Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('nord_sync.install.wizard', required=True, ondelete='cascade')
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
