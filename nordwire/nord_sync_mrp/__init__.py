# -*- coding: utf-8 -*-
from . import models
from . import wizard


def post_init_hook(env):
    """Backfills the Resource/Employee Bridges: both only push on
    create/write/unlink, so anything that already existed before this addon
    was installed (a work center, and especially hr.employee — the default
    "Administrator" employee predates almost every install) would otherwise
    never reach the Core at all, silently, until someone happens to edit it.
    Delegates to nord_sync.config._nord_sync_backfill_existing_records() —
    this addon's own models/nord_sync_config.py extends it via _inherit, the
    same dispatch base nord_sync's own post_init_hook already calls.

    Also grants Nordwire access to any user who already has a Manufacturing
    group, tiered the same way Manufacturing itself is tiered: an
    Administrator (mrp.group_mrp_manager) gets Nordwire Manager, a plain
    User (mrp.group_mrp_user, not Manager) gets only Nordwire User — a
    Manufacturing user is exactly who's expected to work with Sync Queue/
    Sync Failures day to day, not just whoever happened to run the Install
    Wizard, but only a Manufacturing admin should inherit Nordwire's own
    admin-level access (Configuration, Install Wizard, Automation Rules).
    One-time backfill, same spirit as the bridges above: a user who gains
    Manufacturing access afterwards isn't caught retroactively.

    Split out of nord_sync's own post_init_hook when the source addons split
    back apart — neither of these makes sense for a client that never
    installs this addon at all.
    """
    for company in env['res.company'].sudo().search([]):
        config = env['nord_sync.config'].sudo()._get_for_company(company)
        if config:
            # nord_sync_skip_wake: avoid one synchronous HTTP wake per
            # backfilled record (workcenter/employee/bom/production) — a
            # single consolidated ping afterward covers everything just
            # enqueued, same effect without blocking installation on a
            # client with real manufacturing history.
            config.with_context(nord_sync_skip_wake=True)._nord_sync_backfill_existing_records()
            config._retry_failed_webhooks()
    manufacturing_admins = env.ref('mrp.group_mrp_manager').sudo().users
    manufacturing_admins.write({'groups_id': [(4, env.ref('nord_sync.group_nord_sync_manager').id)]})
    manufacturing_users = env.ref('mrp.group_mrp_user').sudo().users - manufacturing_admins
    manufacturing_users.write({'groups_id': [(4, env.ref('nord_sync.group_nord_sync_user').id)]})
