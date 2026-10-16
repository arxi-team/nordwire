# -*- coding: utf-8 -*-
from . import models
from . import controllers
from . import wizard


def post_init_hook(env):
    """Source-agnostic backfill — dispatches through the same _inherit chain
    _apply_nord_sync_entry already uses (base is a no-op; each source addon
    that's actually installed, e.g. nord_sync_mrp, extends it via super()).
    Safe to call regardless of which source addons are installed for this
    client — a source with no addon here just never gets to extend it.

    Also seeds nord_sync.payload.field.config defaults for whichever of the
    10 known models actually exist for this install (see that method's own
    docstring — it skips the rest, no addon dependency of its own to check
    here).

    MRP-specific backfill (Resource/Employee Bridge for pre-existing
    records) and the Manufacturing-group access grant used to live here —
    moved to nord_sync_mrp's own post_init_hook when the source addons split
    back apart, since neither makes sense for a client that never installs
    that addon at all.
    """
    for company in env['res.company'].sudo().search([]):
        config = env['nord_sync.config'].sudo()._get_for_company(company)
        if config:
            config._nord_sync_backfill_existing_records()
        env['nord_sync.payload.field.config']._nord_sync_seed_defaults_for_company(company)
