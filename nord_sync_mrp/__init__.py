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
    """
    for company in env['res.company'].sudo().search([]):
        config = env['nord_sync.config'].sudo()._get_for_company(company)
        if config:
            config._push_source_installed_signal('nord_sync_mrp')
        env['mrp.workcenter'].sudo().search([('company_id', '=', company.id)])._nord_sync_notify('create')
        env['hr.employee'].sudo().search([('company_id', '=', company.id)])._nord_sync_notify('create')
