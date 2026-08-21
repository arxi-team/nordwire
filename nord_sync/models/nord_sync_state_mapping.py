# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NordSyncStateMapping(models.Model):
    """Client-authored Nord Sync Job Stage Mapping — ties a raw source value
    (e.g. mrp.production's own 'confirmed'/'cancel' state, or another adapter's
    stage name) to the job stage that should land on the matching nord.job
    on the Core.

    Only job stage lives here — nord.job.state is exclusive to the job
    itself, resolved entirely on the Core from each source addon's own
    hardcoded registration there (_nord_sync_default_target_state_by_value
    in nordos_nord_sync_core*). Nothing about job state is mirrored,
    mapped, or even displayed on this client at all — no row here, no
    field on this model, no column in the install wizard.

    Pushed one way (client -> Core) through the same nord.sync.queue/webhook/
    pull pipeline every other Nord Sync source model uses — the Core keeps
    its own local copy (nord.sync.state.mapping there) and is what actually
    resolves mappings at apply time; this client-side copy is only ever the
    authoring surface.
    """
    _name = 'nord_sync.state.mapping'
    _description = 'Nord Sync Job Stage Mapping'

    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    source_model = fields.Selection(selection='_selection_source_model', required=True)
    source_value = fields.Selection(
        selection='_selection_source_value', required=True,
        help='Value as this model itself tracks it — picked from a real list, never typed.',
    )
    target_job_stage_id = fields.Many2one('nord_sync.job.stage')

    _company_source_unique = models.Constraint(
        'UNIQUE(company_id, source_model, source_value)',
        'A mapping already exists for this source model/value in this company.',
    )

    @api.model
    def _selection_source_model(self):
        """One entry per currently-registered Nord Sync Source — dynamic,
        not a hardcoded list, so installing a new source addon makes it selectable
        here without touching this file. A source with nothing in its own
        'source_field' (no native state to map — e.g. maintenance.request
        today) simply doesn't register at all (see nord_sync.config's
        _nord_sync_available_native_sources), so it never shows up as a
        pickable-but-unusable option.
        """
        return [
            (source['source_model'], source.get('label') or source['source_model'])
            for source in self.env['nord_sync.config']._nord_sync_available_native_sources()
        ]

    @api.model
    def _selection_source_value(self):
        """A Selection field's options are resolved once, unbound to any
        specific record (confirmed live: scoping this by self.source_model,
        as a genuine "cascading dropdown", returns [] here every time — the
        web client never re-evaluates this bound to what the user just
        picked, only at initial view load with no record context yet) — so
        this has to stay a union across every currently-registered source.
        Unlike the wizard's own mapping line (which switched to a plain
        Char + resolved label, since that field is readonly and never
        user-picked), this one genuinely needs a live dropdown — the user
        actively chooses source_value here — so Selection stays, with the
        union as the only way to make get_views' unbound evaluation safe.

        ponytail: deduped by value only (first source registered wins the
        label on a collision, e.g. purchase.order and stock.picking both
        have a 'draft' state with a different label) — a real Selection
        field can't carry two different labels for the same value at once.
        Upgrade if a genuine label collision across two installed sources
        turns out to matter in practice — none has yet.
        """
        seen_values = set()
        result = []
        for source in self.env['nord_sync.config']._nord_sync_available_native_sources():
            for pair in self.env[source['source_model']]._fields[source['source_field']].selection:
                if pair[0] not in seen_values:
                    seen_values.add(pair[0])
                    result.append(pair)
        return result

    @api.onchange('source_model')
    def _onchange_source_model(self):
        # A value picked for the previous source_model won't be valid for the
        # new one (different Selection entirely) — never leave a stale value
        # silently sitting there.
        self.source_value = False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._nord_sync_notify('create')
        return records

    def write(self, vals):
        result = super().write(vals)
        self._nord_sync_notify('write')
        return result

    def unlink(self):
        self._nord_sync_notify('unlink')
        return super().unlink()

    def _nord_sync_notify(self, operation):
        for record in self:
            company = record.company_id or self.env.company
            config = self.env['nord_sync.config'].sudo()._get_for_company(company)
            if not config or not config.enabled:
                continue
            config._enqueue_and_notify('nord_sync.state.mapping', record.id, operation, record._nord_sync_payload())

    def _nord_sync_payload(self):
        """Payload sent to the Core for this client-authored state mapping.

        Keys:
            source_model (str): the source model this mapping applies to
                (e.g. 'mrp.production').
            source_value (str): the raw state value on that source model.
            target_job_stage_source_res_id (int or False): the client's own
                id of the nord_sync.job.stage this value maps to, False if unset.
        """
        self.ensure_one()
        return {
            'source_model': self.source_model,
            'source_value': self.source_value,
            'target_job_stage_source_res_id': self.target_job_stage_id.id or False,
        }
