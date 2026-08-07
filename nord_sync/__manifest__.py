# -*- coding: utf-8 -*-
{
    'name': 'Nord Sync',
    'version': '1.0.0',
    'category': 'Manufacturing',
    'summary': 'Bridges this Odoo to the Nord platform: notifies the Nord Cloud of changes, '
               'exposes a queue for the Nord Core to pull, authenticated by API key.',
    'description': """
Nord Sync
=========

Phase 1 (wake-signal plumbing) test module, built to exercise the Cloud/Core
side already implemented in `nordos_nord_sync_cloud` / `nordos_nord_sync_core`
(see the `nord` project root, `custom/plano_addon_odoo_cliente_producao_v2.md`
and `nord-os/docs/nord_sync/`).

- `nord_sync.config` (one record per company_id, multi-company: sync is opt-in
  per company) holds `enabled`/`company_uid` — replaces the fields that used to
  live directly on `res.company`. The Cloud webhook target is not per-company:
  the client only provides the host (`nord_sync.cloud_base_url` system
  parameter, e.g. `https://nordwire.pt` or `http://localhost:8080`) —
  the webhook path itself (`/nordos/sync/nord_sync/webhook`) is fixed in code.
- `mrp.production` create/write/unlink append an entry to the local
  `nord.sync.queue` and best-effort POST a wake webhook to the Nord Cloud.
- `GET /nord_sync/api/v1/queue` — the Nord Core pulls new queue entries here,
  authenticated with an API key (technical user in the "Nord Sync
  Integration" group).

Phase 2 in progress: queue entries now carry a business payload snapshot
(name/qty/state and product name/UoM/internal reference, captured at
enqueue time) alongside the change reference (seq/model/operation/res_id),
plus a delivery status (pending/sent/failed) for the wake webhook. No
write-back endpoint yet.

Install wizard (Docs/PLAN.md, Fase 1.2), 3 steps — pre-flight (scheduler active,
Odoo version) / connection (company UID) / finish — opens automatically right
after install via ir.actions.todo, and reachable afterwards from a button on
the Configuration screen.

Own top-level app (not nested in Settings, Docs/ADR/0002) — Sync Queue/Sync
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
    'depends': ['mrp', 'base_automation', 'maintenance'],
    'data': [
        'security/nord_sync_security.xml',
        'security/ir.model.access.csv',
        # Wizard views first: nord_sync_config_views.xml's "Open Install Wizard"
        # button resolves %(action_nord_sync_install_wizard)d at load time (not
        # lazily at render time), so the action must already be defined.
        'wizard/nord_sync_install_wizard_views.xml',
        'views/nord_sync_queue_views.xml',
        'views/nord_sync_failures_views.xml',
        'views/nord_sync_config_views.xml',
        'views/ir_actions_server_views.xml',
        'data/nord_sync_automation.xml',
        'data/nord_sync_cron.xml',
        'data/nord_sync_config_parameter.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nord_sync/static/src/components/nord_sync_systray/nord_sync_systray.js',
            'nord_sync/static/src/components/nord_sync_systray/nord_sync_systray.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
}
