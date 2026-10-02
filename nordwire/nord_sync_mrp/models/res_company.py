# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    """Client-authored, same direction as nord_sync.job.stage/state.mapping
    (and nord_sync.config's own job naming/mirror mode signal) -- the Odoo
    user is the one who knows this site's real electricity tariff/CO2e
    factor, not the Core, so this pushes client->Core rather than the Core
    ever pushing a default down. Applied onto the same field names on the
    Core's own res.company (nordos_core/models/res_company.py) -- feeds
    nordos_onpremise's edge.resource.energy_cost_total/co2e_total_kg.
    """
    _name = 'res.company'
    _inherit = ['res.company', 'nord_sync.notify.mixin']

    energy_tariff_eur_kwh = fields.Float(string='Energy Tariff (€/kWh)')
    co2e_factor_kg_kwh = fields.Float(string='CO2e Factor (kg/kWh)')

    def write(self, vals):
        result = super().write(vals)
        if 'energy_tariff_eur_kwh' in vals or 'co2e_factor_kg_kwh' in vals:
            self._nord_sync_notify('write')
        return result

    def _nord_sync_payload(self):
        """Payload sent to the Core to keep its own res.company energy
        fields in sync.

        Keys:
            energy_tariff_eur_kwh (float): €/kWh.
            co2e_factor_kg_kwh (float): kg CO2e/kWh.
        """
        self.ensure_one()
        return {
            'energy_tariff_eur_kwh': self.energy_tariff_eur_kwh,
            'co2e_factor_kg_kwh': self.co2e_factor_kg_kwh,
        }

    def _nord_sync_notify(self, operation):
        """Overrides the mixin's base loop instead of just setting
        _nord_sync_source_key/_nord_sync_should_notify: that loop resolves
        the owning company via record.company_id, which res.company itself
        doesn't have -- a company IS the company, it isn't owned by one.
        """
        for record in self:
            config = self.env['nord_sync.config'].sudo()._get_for_company(record)
            if not config or not config.enabled:
                continue
            config._enqueue_and_notify(record._name, record.id, operation, record._nord_sync_payload())
