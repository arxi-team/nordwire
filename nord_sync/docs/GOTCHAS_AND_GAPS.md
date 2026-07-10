# Gotchas & Gaps

Two different categories, kept separate on purpose:

- **Gotchas** — accepted trade-offs of the current design. Not bugs. Don't
  "fix" these without a deliberate decision to change the architecture.
- **Gaps** — things the canonical plan (`docs/plano_addon_odoo_cliente_producao.md`
  in the `nord` project root) describes for this addon that simply don't
  exist in code yet. Useful as a punch list for Phase 2/3 scoping.

## Gotchas (by design, verified live)

### The native webhook action raises synchronously on a blank URL

`_run_action_webhook` in Odoo core raises `UserError` **before** it even
registers the postcommit callback if `webhook_url` is empty — this would
crash whatever transaction created the triggering row (e.g. a future MO
save). `_push()` specifically guards against this by only setting
`company_uid` when both the config is active *and* the shared webhook
action already has a URL. See `ARCHITECTURE.md`. Confirmed via a live
traceback during Phase 1 testing before this guard existed.

### No retry, no backoff, no delivery status on the queue row

Odoo's native webhook action is fire-and-forget: one POST, 1-second
timeout, no retry. There is deliberately no `state`/`attempts`/`sent_at`
field on `nord.sync.queue` — recovering a missed delivery is entirely
Core's job (the periodic reconciliation pull, leg B in
`ARCHITECTURE.md`), not something this addon attempts. If you're tempted
to add retry logic here, that's very likely fighting the design rather
than fixing a gap — talk to the team first.

### A hard connection failure surfaces as a UI error, even though the row is safe

If leg A's webhook hits connection-refused (Cloud down) rather than a slow
response, the exception propagates out of the postcommit callback and can
show up as an error toast/traceback on whatever UI action triggered the
push (e.g. clicking "Create Test Entry"). The row itself is unaffected —
it fires *after* commit — but expect a visible error in that specific
interaction. Documented as an accepted rough edge in
`docs/ODOO_ADDON_NORD_SYNC_MANUAL_TEST_PLAN.md` §4, not something to
silently swallow with a broad `except`.

### One shared webhook URL for the whole install, not per company

See `MODELS_AND_SECURITY.md` — running the setup wizard for one company
overwrites the URL every other company's queue rows will also POST to.
`company_uid` in the payload is what lets Cloud attribute the row to the
right tenant; there's no per-company routing at the transport level.

### No persisted log of webhook deliveries anywhere

Neither this addon nor Cloud's receiving controller
(`nordos_cloud/controllers/nord_sync_webhook.py`) writes a row anywhere
when a webhook call happens. The only observable trail today is server
logs and `sync.config.nord_sync_last_seq` advancing on the Core side.
Flagged during the 2026-07-10 staging run
(`docs/2026-07-10_fase_1_run.md` in the `nord` project) as a real
observability gap worth scoping for Phase 2, not a defect in what shipped.

## Gaps — described in the plan, not yet built

The canonical plan's "Nord Core ↔ Odoo do cliente" section describes a
significantly larger surface than what exists today:

> "o Core lê (MOs, produtos, BOM) e escreve (resultado final) diretamente
> na API do Odoo do cliente, autenticando-se com uma API key gerada no
> próprio Odoo do cliente ... copiada para a Cloud durante a instalação e
> por esta propagada ao Core."

Audited against the actual code (2026-07-10):

| Described in plan | Status |
|---|---|
| Core reads `mrp.production`/`product.product`/`mrp.bom` from Odoo | **Not built.** The only read path is the generic pull-by-seq endpoint, which returns opaque `payload` JSON — currently only fake test data. No model-specific read logic exists anywhere. |
| Core writes final results back to Odoo | **Not built.** `nord_sync`'s controller only defines a `GET` route. No write-back endpoint exists on either side. |
| API key generated in Odoo, copied to Cloud during install, propagated to Core | **Not built.** The setup wizard has no API key field at all. Cloud has no endpoint that receives/stores a nord_sync API key. `sync.config.nord_sync_odoo_api_key` on the Core side is a plain manually-editable `Char` field — today a human copies the key from Odoo's Settings → API Keys screen and pastes it directly into Core's config form. |

What **is** built and live-verified as of the 2026-07-10 staging run: the
generic pull-by-seq mechanism, fully authenticated (`401`/`403`/`400`
boundaries all confirmed, not just the happy path), with a real
least-privilege technical user (`Nord Sync Integration` group only, not
admin) — see `docs/2026-07-10_fase_1_run.md`. This satisfies the Phase 1
"validate the full pipeline delivers and authenticates correctly, no
business logic" checklist item. The MO/BOM/write-back business logic
itself is Phase 2/3 scope and needs a separate design pass — in
particular a decision on whether the "Cloud propagates the key to Core"
automation described in the plan will actually be built, or whether manual
key entry is an accepted permanent shortcut for this on-premise deployment
model.

## Environment gotchas (not code, but bite during testing)

### `dbfilter` must be set if the Postgres cluster has multiple databases

The pull endpoint (`auth='bearer'`, no session) is a stateless request.
Odoo can't route it to a database without either `dbfilter` matching the
host, or exactly one database existing. An empty `dbfilter` with several
databases present produces a raw `404 Not Found — No database is selected`
that has nothing to do with the addon's own logic — easy to misdiagnose as
a broken endpoint. Hit and fixed during the 2026-07-10 staging run by
setting `dbfilter = ^nord_sync_test$` in the client's config.
