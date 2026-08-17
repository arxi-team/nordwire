# -*- coding: utf-8 -*-
from . import models
from . import controllers


def post_init_hook(env):
    """Announce this source to the Core so it can auto-install its own
    nordos_nord_sync_core_mrp counterpart, instead of requiring an operator
    to install it by hand on every client onboarding.

    Also backfills the Resource/Employee Bridges: both only push on
    create/write/unlink, so anything that already existed before this addon
    was installed (a work center, and especially hr.employee — the default
    "Administrator" employee predates almost every install) would otherwise
    never reach the Core at all, silently, until someone happens to edit it.

    Also grants Nord Sync access to any user who already has a Manufacturing
    group, tiered the same way Manufacturing itself is tiered: an
    Administrator (mrp.group_mrp_manager) gets Nord Sync Manager, a plain
    User (mrp.group_mrp_user, not Manager) gets only Nord Sync User — a
    Manufacturing user is exactly who's expected to work with Sync
    Queue/Failures day to day, not just whoever happened to run the Install
    Wizard, but only a Manufacturing admin should inherit Nord Sync's own
    admin-level access (Configuration, Install Wizard, Automation Rules).
    One-time backfill, same spirit as the bridges above: a user who gains
    Manufacturing access afterwards isn't caught retroactively.
    """
    for company in env['res.company'].sudo().search([]):
        config = env['nord_sync.config'].sudo()._get_for_company(company)
        if config:
            config._push_source_installed_signal('nord_sync_mrp')
        env['mrp.workcenter'].sudo().search([('company_id', '=', company.id)])._nord_sync_notify('create')
        env['hr.employee'].sudo().search([('company_id', '=', company.id)])._nord_sync_notify('create')
    manufacturing_admins = env.ref('mrp.group_mrp_manager').sudo().all_user_ids
    manufacturing_admins.write({'group_ids': [(4, env.ref('nord_sync.group_nord_sync_manager').id)]})
    manufacturing_users = env.ref('mrp.group_mrp_user').sudo().all_user_ids - manufacturing_admins
    manufacturing_users.write({'group_ids': [(4, env.ref('nord_sync.group_nord_sync_user').id)]})
