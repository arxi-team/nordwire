# -*- coding: utf-8 -*-
from odoo import models


class NordSyncNotifyMixin(models.AbstractModel):
    """Shared "look up the config, check it's allowed, enqueue" plumbing for
    every Nordwire Source/support model. Identical everywhere except two
    knobs a concrete model overrides when it isn't the plain case: the
    per-record guard (_nord_sync_should_notify, e.g. quality.check skipping
    checks with no production_id) and the source-gating key
    (_nord_sync_source_key, e.g. mrp.workcenter/hr.employee/mrp.bom/
    mrp.workorder/quality.check are all support models of mrp.production and
    have no toggle of their own). Each concrete model still defines its own
    _nord_sync_payload — never touched here, that stays per-model.
    """
    _name = 'nord_sync.notify.mixin'
    _description = 'Nordwire Notify Mixin'

    def action_nord_sync_force_resync(self):
        """Manually re-enqueue these records as a 'write' — same effect on
        the wire as actually editing a field, without needing a real change
        to trigger it. Every Nordwire Source/support model gets this for
        free (this mixin is shared, never subclassed per-model), callable
        from a button, a Server Action, or the shell.

        Real need this solves: several Core-side handlers in this bridge
        are get-or-create, not get-or-update (e.g. Nordwire Reason Type
        Import, _apply_nord_sync_loss_type/_apply_nord_sync_loss on the
        Core — once a record's ir.model.data tag exists there, a later
        'write' entry is a no-op, deliberately, since most of this bridge
        never overwrites a value a human may have already edited on the
        Core). A genuine edit on this side still won't retroactively
        correct an already-imported Core record — but this lets a human
        force a fresh entry through the same queue on demand (e.g. after
        the Core's own copy was lost — a DB reset, a record deleted there —
        so its own ir.model.data tag is gone and the next entry, replayed
        for real this time, creates it again instead of finding nothing to
        do).
        """
        self._nord_sync_notify('write')

    def _nord_sync_notify(self, operation):
        for record in self:
            if not record._nord_sync_should_notify():
                continue
            company = record.company_id or self.env.company
            config = self.env['nord_sync.config'].sudo()._get_for_company(company)
            if not config or not config.enabled:
                continue
            source_key = record._nord_sync_source_key()
            if source_key and not config._is_source_enabled(source_key):
                continue
            config._enqueue_and_notify(record._name, record.id, operation, record._nord_sync_payload())

    def _nord_sync_should_notify(self):
        self.ensure_one()
        return True

    def _nord_sync_source_key(self):
        """Model checked against nord_sync.config.enabled_source_ids. False
        means no per-source gate at all, only config.enabled — used by the
        client-authored meta models (nord_sync.state.mapping/job.stage),
        which have no install-time source toggle to check.
        """
        self.ensure_one()
        return self._name

    def _nord_sync_configurable_payload(self):
        """The scalar-field slice of this record's payload, per
        nord_sync.payload.field.config (company + model).
        Each concrete model's own _nord_sync_payload() merges this in
        alongside whatever it still builds by hand (constants, relational
        references, nested snapshots — none of that fits here, see that
        config model's own docstring). Empty dict when nothing's configured
        for this (company, model) yet — never raises, missing config just
        means no scalar fields go out, same resilience posture as the rest
        of this bridge.
        """
        self.ensure_one()
        company = self.company_id if 'company_id' in self._fields and self.company_id else self.env.company
        config = self.env['nord_sync.payload.field.config'].sudo().search([
            ('company_id', '=', company.id), ('res_model', '=', self._name),
        ], limit=1)
        return {field.name: self[field.name] for field in config.field_ids}
