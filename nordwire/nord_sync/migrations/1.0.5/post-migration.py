# -*- coding: utf-8 -*-
def migrate(cr, version):
    """Seeds nord_sync.payload.field.config for every company that already
    exists at upgrade time, with each model's default field list — without
    this, an existing company's payload would go from the old hardcoded
    dict to an empty one the moment this version installs, since
    _nord_sync_payload() has nothing else to fall back on once the fixed
    dict is gone. Skipped on a fresh install (version is falsy then,
    standard Odoo migration convention) — post_init_hook covers that case
    instead, same seeding call.
    """
    if not version:
        return
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env['res.company'].sudo().search([]):
        env['nord_sync.payload.field.config']._nord_sync_seed_defaults_for_company(company)
