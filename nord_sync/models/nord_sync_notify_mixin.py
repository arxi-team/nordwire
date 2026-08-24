# -*- coding: utf-8 -*-
from odoo import models


class NordSyncNotifyMixin(models.AbstractModel):
    """Shared "look up the config, check it's allowed, enqueue" plumbing for
    every Nord Sync Source/support model. Identical everywhere except two
    knobs a concrete model overrides when it isn't the plain case: the
    per-record guard (_nord_sync_should_notify, e.g. quality.check skipping
    checks with no production_id) and the source-gating key
    (_nord_sync_source_key, e.g. mrp.workcenter/hr.employee/mrp.bom/
    mrp.workorder/quality.check are all support models of mrp.production and
    have no toggle of their own). Each concrete model still defines its own
    _nord_sync_payload — never touched here, that stays per-model.
    """
    _name = 'nord_sync.notify.mixin'
    _description = 'Nord Sync Notify Mixin'

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
