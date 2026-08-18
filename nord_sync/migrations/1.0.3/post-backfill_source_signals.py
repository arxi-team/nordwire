# -*- coding: utf-8 -*-
"""post_init_hook only fires on a fresh install, never on an upgrade of an
already-installed module — so nord_sync_mrp/_maintenance/_sale/_purchase/
_inventory addons installed before their own post_init_hook existed would
otherwise never announce themselves to the Core. This one-time migration
(runs when nord_sync itself upgrades past 1.0.3) catches up: for every
company, push the installed-source signal for every nord_sync_* addon
already installed. _push_source_installed_signal is idempotent, so this is
safe even if some of them already got signalled by their own
post_init_hook.

Also backfills pre-existing catalog/resource records the same way
post_init_hook does (real gap found 2026-08-18, Docs/
NordSyncAuditoriaErros.md finding #3) — an upgrade-path client (this
migration's whole reason to exist) has exactly the same pre-existing
work centers/employees/BOMs that a fresh-install client's post_init_hook
already handles; missing this here meant an upgrade never backfilled them
at all, only a fresh install or a wizard re-run did.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # 'to upgrade' (not just 'installed') matters here: a deploy that bumps
    # nord_sync to 1.0.3 alongside its already-installed source siblings in
    # the same -u command runs this migration while those siblings are
    # mid-upgrade — their own state is still 'to upgrade' at this exact
    # point, not yet flipped to 'installed'. Both states only ever apply to
    # a module that was genuinely already installed before this run.
    modules = env['ir.module.module'].sudo().search([
        ('name', 'like', 'nord_sync_'), ('state', 'in', ('installed', 'to upgrade')),
    ])
    if not modules:
        return
    Config = env['nord_sync.config'].sudo()
    for company in env['res.company'].sudo().search([]):
        config = Config._get_for_company(company)
        if not config:
            continue
        for module in modules:
            config._push_source_installed_signal(module.name)
        config._nord_sync_backfill_existing_records()
