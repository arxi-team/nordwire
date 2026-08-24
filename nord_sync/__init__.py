# -*- coding: utf-8 -*-
from . import models
from . import controllers
from . import wizard


def post_init_hook(env):
    """MRP source backfill + access grant — merged in from nord_sync_mrp's
    own post_init_hook, back when MRP shipped as a separate addon instead
    of a built-in source of this one. The source-installed-signal push it
    used to also do is gone: that
    signal told the Core to auto-install its own nordos_nord_sync_core_mrp
    counterpart, which no longer exists as a separate addon to install —
    MRP is just part of nordos_nord_sync_core now, same as it's part of
    this addon.

    Backfills the Resource/Employee Bridges: both only push on
    create/write/unlink, so anything that already existed before this
    addon was installed (a work center, and especially hr.employee — the
    default "Administrator" employee predates almost every install) would
    otherwise never reach the Core at all, silently, until someone happens
    to edit it.

    Also grants Nord Sync access to any user who already has a
    Manufacturing group, tiered the same way Manufacturing itself is
    tiered: an Administrator (mrp.group_mrp_manager) gets Nord Sync
    Manager, a plain User (mrp.group_mrp_user, not Manager) gets only Nord
    Sync User — a Manufacturing user is exactly who's expected to work
    with Sync Queue/Failures day to day, not just whoever happened to run
    the Install Wizard, but only a Manufacturing admin should inherit Nord
    Sync's own admin-level access (Configuration, Install Wizard,
    Automation Rules). One-time backfill, same spirit as the bridges
    above: a user who gains Manufacturing access afterwards isn't caught
    retroactively.
    """
    for company in env['res.company'].sudo().search([]):
        config = env['nord_sync.config'].sudo()._get_for_company(company)
        if config:
            config._nord_sync_backfill_existing_records()
    manufacturing_admins = env.ref('mrp.group_mrp_manager').sudo().all_user_ids
    manufacturing_admins.write({'group_ids': [(4, env.ref('nord_sync.group_nord_sync_manager').id)]})
    manufacturing_users = env.ref('mrp.group_mrp_user').sudo().all_user_ids - manufacturing_admins
    manufacturing_users.write({'group_ids': [(4, env.ref('nord_sync.group_nord_sync_user').id)]})
