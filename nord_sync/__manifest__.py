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
  per company) holds `enabled`/`company_uid`/`cloud_webhook_url` — replaces the
  fields that used to live directly on `res.company`.
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
Odoo version) / connection (company UID, Cloud webhook URL) / finish — opens
automatically right after install via ir.actions.todo, and reachable afterwards
from Settings > Nord Sync (own sidebar app section, not a top-level menu —
mirrors an unrelated project's Shopify integration `res.config.settings`
extension, see models/res_config_settings.py docstring). Technical/debug lists
(Configuration, Sync Queue) stay under Settings > Technical.
    """,
    'author': 'NORD / Nordwire',
    'license': 'LGPL-3',
    'depends': ['mrp', 'base_automation', 'maintenance'],
    'data': [
        'security/nord_sync_security.xml',
        'security/ir.model.access.csv',
        'views/nord_sync_config_views.xml',
        'views/nord_sync_queue_views.xml',
        'views/nord_sync_failures_views.xml',
        'data/nord_sync_automation.xml',
        'data/nord_sync_cron.xml',
        'views/res_config_settings_views.xml',
        'wizard/nord_sync_install_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nord_sync/static/src/components/nord_sync_systray/nord_sync_systray.js',
            'nord_sync/static/src/components/nord_sync_systray/nord_sync_systray.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
