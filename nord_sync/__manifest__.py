# -*- coding: utf-8 -*-
{
    'name': 'Nord Sync',
    'version': '1.0.5',
    'category': 'Manufacturing',
    'summary': 'Bridges this Odoo to the Nord platform: notifies the Nord Cloud of changes, '
               'exposes a queue for the Nord Core to pull, authenticated by API key.',
    'description': """
Nord Sync
=========

Bridges this Odoo instance to the Nord platform: notifies the Nord Cloud of
changes, exposes a queue for the Nord Core to pull, authenticated by API key.

- `nord_sync.config` (one record per company_id, multi-company: sync is opt-in
  per company) holds `enabled`/`company_uid` — replaces the fields that used to
  live directly on `res.company`. The Cloud webhook target is not per-company:
  the client only provides the host (`nord_sync.cloud_base_url` system
  parameter, e.g. `https://nordwire.pt` or `http://localhost:8080`) —
  the webhook path itself (`/nordos/sync/nord_sync/webhook`) is fixed in code.
- `GET /nord_sync/api/v1/queue` — the Nord Core pulls new queue entries here,
  authenticated with an API key (technical user in the "Nord Sync
  Integration" group).

This addon is only the generic bridge machinery (queue, config, payload
field config, job stage/state mapping, install wizard) — depends on nothing
business-specific, no mrp/sale/purchase/stock/maintenance/hr. Each Nord Sync
Source (`mrp.production`/`sale.order`/`purchase.order`/`stock.picking`/
`maintenance.request`) lives in its own thin addon (`nord_sync_mrp`,
`nord_sync_sale`, ...) that depends on this one plus whichever business app
it extends, `auto_install`s the moment both are present, and never shows as
its own tile on the Apps screen (`application: False`) — a client that only
runs Manufacturing never sees `nord_sync_sale` exist at all. This structure
was tried once before, merged back into a single addon, then split again
here: the merge happened because `quality.check` (a support model, not a
source of its own) had no obvious addon to live in — resolved this time by
a clear rule instead: support models always live inside their parent
source's addon, never get one of their own.

Phase 2 in progress: queue entries now carry a business payload snapshot
(name/qty/state and product name/UoM/internal reference, captured at
enqueue time) alongside the change reference (seq/model/operation/res_id),
plus a delivery status (pending/sent/failed) for the wake webhook. No
write-back endpoint yet.

Install wizard, 5 steps — pre-flight (scheduler active, Odoo version) /
sources (which currently-installed Nord Sync Source addons to enable) /
connection (company UID) / job stages & mapping / finish — opens
automatically right after install via ir.actions.todo, and reachable
afterwards from a button on the Configuration screen.

Own top-level app (not nested in Settings) — Sync Queue/Sync
Failures/Configuration/Automation Rules all live under the "Nord Sync" main
menu. Two groups gate access: Nord Sync User (read Sync Queue/Sync Failures,
retry a failed webhook) and Nord Sync Manager (implies User; Configuration,
Install Wizard, and the nord_sync-tagged Automation Rules). Neither group is
`base.group_system` — the Nord Cloud URL (`nord_sync.cloud_base_url` system
parameter, Settings > Technical > Parameters) and non-Nord-Sync Automation
Rules stay reserved to the real Odoo administrator, on purpose.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['base_automation'],
    'data': [
        'security/nord_sync_security.xml',
        'security/ir.model.access.csv',
        'data/nord_sync_sources.xml',
        # Wizard views first: nord_sync_config_views.xml's "Open Install Wizard"
        # button resolves %(action_nord_sync_install_wizard)d at load time (not
        # lazily at render time), so the action must already be defined.
        'wizard/nord_sync_install_wizard_views.xml',
        'wizard/nord_sync_failure_wizard_views.xml',
        'views/nord_sync_queue_views.xml',
        'views/nord_sync_failures_views.xml',
        'views/nord_sync_state_mapping_views.xml',
        'views/nord_sync_payload_field_config_views.xml',
        'views/nord_sync_config_views.xml',
        'views/ir_actions_server_views.xml',
        'data/nord_sync_automation.xml',
        'data/nord_sync_cron.xml',
        'data/nord_sync_config_parameter.xml',
        # After data/nord_sync_automation.xml: resolves
        # %(nord_sync.action_nord_sync_automation_rules)d at load time.
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nord_sync/static/src/components/nord_sync_systray/nord_sync_systray.js',
            'nord_sync/static/src/components/nord_sync_systray/nord_sync_systray.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'application': True,
}
