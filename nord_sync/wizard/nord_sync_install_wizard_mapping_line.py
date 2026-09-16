# -*- coding: utf-8 -*-
from odoo import fields, models


class NordSyncInstallWizardMappingLine(models.TransientModel):
    """One row per value the source model can actually take — not narrowed
    to whichever values today's shipped Automation Rules happen to send. The
    client edits Automation Rules directly, so any native state could reach
    the bridge; the wizard shouldn't decide on the client's behalf which ones are worth
    mapping. A row left entirely blank (no stage) just means that value isn't
    mapped — never an error, same resilience posture as
    _resolve_nord_sync_state_mapping on the Core.

    Job state is never shown or mapped here at all — it's exclusive to the
    job, resolved on the Core from each source addon's own hardcoded
    registration, with no client-side counterpart of any kind (not even a
    read-only echo — that was itself removed, this wizard has no notion of
    job state left). Job Stage is the only thing a row here ever means.

    Rows themselves aren't freely addable/removable — the fixed set of native
    values *is* the row set (see _mapping_line_vals in the wizard), so
    there's no way to end up with a duplicate or invalid source_value here.

    source_value is plain Char, not Selection — it's readonly, populated
    once server-side in _mapping_line_vals and never picked by the user, so
    there's no dropdown to build and nothing for a Selection widget to
    resolve at render time. (An earlier version used a dynamic Selection
    here purely for display; that hit a real, reproducible crash — the web
    client resolves a Selection field's option list once, unbound to any
    specific record, so any row whose stored value wasn't in that resolved
    list crashed the browser's SelectionField widget. Plain Char removes the
    whole class of bug for a field nobody ever edits.) source_value_label
    carries the human-readable label instead, resolved once per row from
    that row's own source at generation time — see _mapping_line_vals.

    source_model: which Nordwire Source this row belongs to — with more than one
    source addon installed, rows from different sources coexist in the same
    mapping_line_ids list (there's no per-source sub-view in a Transient
    wizard), grouped by _mapping_line_vals's own generation order and told
    apart by this column.
    """
    _name = 'nord_sync.install.wizard.mapping.line'
    _description = 'Nordwire Install Wizard — Mapping Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('nord_sync.install.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    source_model = fields.Char(required=True, readonly=True)
    source_label = fields.Char(readonly=True, help='Human label for source_model (e.g. "Manufacturing Orders").')
    source_value = fields.Char(required=True, readonly=True)
    source_value_label = fields.Char(readonly=True, help='Human label for source_value (e.g. "Confirmed").')
    target_job_stage_line_id = fields.Many2one(
        'nord_sync.install.wizard.stage.line', string='Job Stage',
        domain="[('wizard_id', '=', wizard_id)]", ondelete='set null',
    )
