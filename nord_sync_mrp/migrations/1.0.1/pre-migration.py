# -*- coding: utf-8 -*-
def migrate(cr, version):
    """nord_sync moved the 6 MRP-owned models' default payload fields out of
    _nord_sync_seed_defaults_for_company (nord_sync's own Python fallback,
    which could run before mrp/mrp_workorder were even installed) and into
    this addon's own static data (data/nord_sync_payload_field_config.xml,
    loaded as part of its dependency graph, mrp/mrp_workorder guaranteed
    installed by then).

    An install that already ran the old Python path before this version
    left a plain, untagged row behind for each of these 6 models (created
    via create(), never env.ref()) -- the new noupdate XML records collide
    with it on UNIQUE(company_id, res_model) the moment this same upgrade
    tries to create them (real bug, caught live 2026-09-03: a pre-existing
    client install failed this exact upgrade with a ParseError). Runs as a
    pre-migration so the stale row is gone before the data file loads.
    Skipped on a fresh install (version is falsy then, standard Odoo
    migration convention) -- there's nothing to clean up there, the static
    data is all this model has ever seen.

    A company that already customized field_ids on one of these 6 rows
    loses that customization once -- the row gets recreated fresh from the
    static data right after this runs.
    """
    if not version:
        return
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    Config = env['nord_sync.payload.field.config'].sudo()
    tagged_ids = env['ir.model.data'].sudo().search([
        ('model', '=', 'nord_sync.payload.field.config'),
    ]).mapped('res_id')
    stale = Config.search([
        ('res_model', 'in', [
            'mrp.production', 'mrp.workcenter', 'hr.employee',
            'mrp.bom', 'mrp.workorder', 'quality.check',
        ]),
        ('id', 'not in', tagged_ids),
    ])
    stale.unlink()
