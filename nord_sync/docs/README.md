# nord_sync — Implementation Documentation

Odoo 19 addon. Phase 1 ("Fundação") of the Nord integration: a local sync
queue on the client Odoo, a native-Odoo outbound webhook to Nord Cloud, and
an authenticated pull endpoint for Nord Core. No source-model
(`mrp.production`) logic yet — that's Phase 2.

This folder documents the addon as it exists in code, for whoever is
maintaining or extending it. For the cross-repo picture (Cloud, Core, the
overall roadmap, locked architectural decisions) see the canonical plan at
`docs/plano_addon_odoo_cliente_producao.md` and `docs/CLAUDE.md` in the
`nord` project root — this addon is only one of three legs described there.

## Files in this folder

- **`ARCHITECTURE.md`** — data flow end to end, the two directions of
  traffic (Odoo→Cloud push, Core→Odoo pull), and why the design looks the
  way it does.
- **`API.md`** — the one HTTP endpoint this addon exposes
  (`GET /nord_sync/api/v1/queue`) and the exact JSON shape of the outbound
  webhook Odoo sends to Cloud. Read this if you're implementing or changing
  the Cloud/Core side that talks to this addon.
- **`MODELS_AND_SECURITY.md`** — every model, field, and security
  group/ACL, with the *why* behind non-obvious choices.
- **`GOTCHAS_AND_GAPS.md`** — known rough edges that are accepted
  trade-offs (not bugs), plus what the plan describes for this addon that
  is **not** built yet.

Test coverage is documented separately in `../tests/README.md` (one section
per test file, cross-referenced to the manual test plan steps).

## Directory map (code)

```
nord_sync/
├── __manifest__.py                     addon metadata, depends, data files
├── models/
│   ├── nord_sync_config.py             nord.sync.config — one row per company
│   └── nord_sync_queue.py              nord.sync.queue — the audit trail / outbox
├── controllers/
│   └── nord_sync_controller.py         GET /nord_sync/api/v1/queue (Core pulls from here)
├── data/
│   └── nord_sync_automation.xml        native webhook action + base.automation rule
├── wizard/
│   ├── nord_sync_setup_wizard.py       guided setup: pre-flight + save config
│   └── nord_sync_setup_wizard_views.xml
├── views/
│   ├── nord_sync_queue_views.xml       Sync Queue list/form + "Create Test Entry" action
│   ├── nord_sync_config_views.xml      Tenant Configuration list/form
│   └── nord_sync_menus.xml
├── security/
│   ├── nord_sync_security.xml          group_nord_sync_manager, group_nord_sync_integration
│   └── ir.model.access.csv
└── tests/                              see tests/README.md
```

## One-paragraph mental model

A row in `nord.sync.queue` is both an audit-trail entry and a trigger. Every
row is created regardless of whether sync is actually configured/active for
that company — only `company_uid` is conditionally populated. A native Odoo
`base.automation` rule watches for new rows with a non-blank `company_uid`
and fires Odoo's built-in "Send Webhook Notification" server action, which
POSTs the row to Cloud and forgets about it (no retry, no delivery status
stored on the row). Separately, Nord Core pulls from this same table via an
authenticated, cursor-based `GET` endpoint — this is deliberately
delivery-agnostic: it doesn't care whether the webhook fired, succeeded, or
was skipped, so it also serves as the reconciliation path when the webhook
leg drops something.
