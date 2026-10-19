# -*- coding: utf-8 -*-
from . import models
from . import wizard


def post_init_hook(env):
    """Grants Nordwire access to any user who already has a Manufacturing
    group, tiered the same way Manufacturing itself is tiered: an
    Administrator (mrp.group_mrp_manager) gets Nordwire Manager, a plain
    User (mrp.group_mrp_user, not Manager) gets only Nordwire User — a
    Manufacturing user is exactly who's expected to work with Sync Queue/
    Sync Failures day to day, not just whoever happened to run the Install
    Wizard, but only a Manufacturing admin should inherit Nordwire's own
    admin-level access (Configuration, Install Wizard, Automation Rules).
    One-time grant, so a user who gains Manufacturing access afterwards
    isn't caught retroactively.

    Does NOT backfill pre-existing work centers/employees/BOMs/MOs into the
    sync queue — installing this addon (even on a client already enabled)
    never pushes anything on its own; use nord_sync.config's "Backfill
    Existing Records" button for that, explicitly.

    Split out of nord_sync's own post_init_hook when the source addons split
    back apart — this grant doesn't make sense for a client that never
    installs this addon at all.
    """
    manufacturing_admins = env.ref('mrp.group_mrp_manager').sudo().all_user_ids
    manufacturing_admins.write({'group_ids': [(4, env.ref('nord_sync.group_nord_sync_manager').id)]})
    manufacturing_users = env.ref('mrp.group_mrp_user').sudo().all_user_ids - manufacturing_admins
    manufacturing_users.write({'group_ids': [(4, env.ref('nord_sync.group_nord_sync_user').id)]})
