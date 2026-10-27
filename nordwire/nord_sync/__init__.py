# -*- coding: utf-8 -*-
from . import models
from . import controllers
from . import wizard


def post_init_hook(env):
    """Seeds nord_sync.payload.field.config defaults for whichever of the
    10 known models actually exist for this install (see that method's own
    docstring — it skips the rest, no addon dependency of its own to check
    here).

    Does NOT backfill pre-existing records into the sync queue — that's an
    explicit, user-triggered action (nord_sync.config's "Backfill Existing
    Records" button), never something installing this addon does on its
    own.
    """
    for company in env['res.company'].sudo().search([]):
        env['nord_sync.payload.field.config']._nord_sync_seed_defaults_for_company(company)
