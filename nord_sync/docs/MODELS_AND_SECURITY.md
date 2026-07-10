# Models & Security

## `nord.sync.config` (`models/nord_sync_config.py`)

One row per company. Holds the tenant identity and the Cloud endpoint.

| Field | Type | Notes |
|---|---|---|
| `company_id` | Many2one `res.company` | Defaults to `self.env.company`. Unique per company (`_company_id_unique` SQL constraint). |
| `company_uid` | Char, required | Nord tenant identifier. **Not** an Odoo user id — explicitly called out in the field's help text to avoid confusion. |
| `cloud_webhook_url` | Char, required | The URL saved here is *also* copied onto the shared `ir.actions.server` webhook action (see below) — this field alone does not control delivery. |
| `mo_filter_criteria` | Char | Reserved for Phase 2 (which MOs to sync). Stored, not enforced by anything yet. |
| `active` | Boolean, default `True` | Pausing this (unchecking Active) is how you pause sync for a company without deleting its configuration — see "Pause/resume" below. |

`_create_or_update_for_company(company, values)` is the only write path
used by the setup wizard: search-by-company, write if found, create if
not. Guarantees the one-row-per-company invariant is upheld by code, not
just by the SQL constraint being there to catch mistakes.

### Why the webhook URL is shared across all companies, not per-company

`data/nord_sync_automation.xml` defines exactly **one**
`webhook_action_queue_to_cloud` record, shared by the single
`automation_queue_to_cloud` rule, which watches `nord.sync.queue` for
**every** company. There is no per-company action/rule. This means:

- Running the setup wizard for company B overwrites the URL that company
  A's rows will also POST to (the last wizard save wins, globally) — see
  `wizard/nord_sync_setup_wizard.py::action_save_config`'s inline comment.
- If you need genuinely different Cloud endpoints per company on the same
  Odoo install, this addon does not support that today. Each row still
  carries its own `company_uid` in the payload, so Cloud can still route
  correctly *if* it's the same Cloud instance — this only breaks if
  different companies need different Cloud *hosts*.

## `nord.sync.queue` (`models/nord_sync_queue.py`)

The outbox / audit trail. See `ARCHITECTURE.md` for the full story of how
rows here get created and consumed. `_order = 'id asc'` — `id` doubles as
the sequence number (`seq` in the API), so ordering must never change.

| Field | Type | Notes |
|---|---|---|
| `company_id` | Many2one `res.company`, required, indexed | `ondelete='cascade'`. |
| `company_uid` | Char | **Conditionally blank** — see `_push()` logic in `ARCHITECTURE.md`. Never write this truthy without confirming the shared webhook action has a URL (see the field's own help text for the failure mode). |
| `model_name` | Char, required | Free text, not a real `ir.model` reference — e.g. `nord_sync.test` for fake Phase-1 entries. |
| `res_id` | Integer, required | Id of the source record. `0` for entries with no real source model yet (test entries). |
| `operation` | Selection: `create`/`write`/`unlink`, required | |
| `payload` | Json | Arbitrary. Currently only ever `{'note': ...}` from the test-entry action. |

### `_push(company_id, model_name, operation, res_id, payload=None)`

The only way rows get created. `@api.model`, always runs as `sudo()` (so
callers don't need queue-model write access — enforced separately via
`group_nord_sync_manager`/`group_nord_sync_integration`, see below).
Decides `company_uid` based on config + webhook-URL readiness, then
creates unconditionally. See `ARCHITECTURE.md` for the full reasoning.

### `_to_command()`

Serializes one row into the exact dict shape returned by the pull API —
`{seq, model, operation, res_id, data}`. `self.ensure_one()`. This is the
single place that shape is defined; keep `API.md` in sync if it changes.

### `action_create_test_entry()`

Bound to a list-view server action ("Create Test Entry", manager group
only) and callable directly (used by the manual test plan and by ad-hoc
E2E verification). Pushes a canned fictitious entry — `model_name =
'nord_sync.test'`, `res_id = 0`. This is the only thing that populates the
queue today; there is no real source-model trigger yet (Phase 2).

## `nord.sync.setup.wizard` (`wizard/nord_sync_setup_wizard.py`)

`TransientModel`, two-step form (`state`: `preflight` → `config`).

- **Pre-flight** (`_compute_preflight`): checks
  `odoo.release.version_info[0]` against `SUPPORTED_MAJOR_VERSIONS = (19,)`
  and shows a warning if it doesn't match. This is the *only* pre-flight
  check — there used to be cron-related checks, removed when the
  Odoo→Cloud leg moved from a consumer cron to the native Automation Rule
  (nothing local left to poll for).
- **Config** (`action_save_config`): validates `company_uid` and
  `cloud_webhook_url` are both present, and that the URL starts with
  `http://` or `https://` (`URL_RE`), then:
  1. Upserts `nord.sync.config` via `_create_or_update_for_company`.
  2. **Also** writes `cloud_webhook_url` onto the shared
     `nord_sync.webhook_action_queue_to_cloud` action's `webhook_url`
     field. This second write is easy to forget when reading only the
     config model — it's the one that actually controls whether the
     native webhook fires (see `ARCHITECTURE.md`'s "both an active config
     and a webhook URL" section).

No API key field anywhere in this wizard — the pull endpoint's API key is
generated and managed entirely through Odoo's standard
Settings → Users → API Keys screen, independent of this addon. See
`GOTCHAS_AND_GAPS.md` for the gap between this and what the canonical plan
describes for key propagation.

## Security groups (`security/nord_sync_security.xml`)

Both groups share one `res.groups.privilege` (`Nord Sync`), so they appear
together in a dedicated category rather than mixed into generic Odoo
groups.

| Group | Intended holder | Purpose |
|---|---|---|
| `group_nord_sync_manager` | Human admin | Full UI access: menu, Sync Queue, Configuration, Setup Wizard, the "Create Test Entry" action. Full CRUD on both models (`ir.model.access.csv`). |
| `group_nord_sync_integration` | **Technical user only** — comment in the XML explicitly says "Do not assign to human users" | Read-only on both models via ACL, **and** it's the group checked by the pull controller (`request.env.user.has_group('nord_sync.group_nord_sync_integration')`) before anything else. This is what Nord Core's API key must belong to. |

### `ir.model.access.csv`

```
nord.sync.queue   — manager: rwcd   integration: r---
nord.sync.config  — manager: rwcd   integration: r---
nord.sync.setup.wizard — manager: rwcd   (no integration access — it's a UI-only tool)
```

### Tenant isolation (defense in depth beyond the group check)

The pull controller checks group membership *and* tenant ownership
separately:

```python
if config.company_id.id not in request.env.user.company_ids.ids:
    raise Forbidden('This user is not authorized for this tenant.')
```

So even if two different companies share technical users with the
integration group (unusual, but not structurally prevented), a key can
only read the queue for companies its owning user actually belongs to.
Verified live: a valid key for company B against company A's
`company_uid` returns `403`, not data leakage.

## Pause/resume

Unchecking `nord.sync.config.active` for a company:

- Does **not** stop rows from being created — `_push()` always creates.
- Makes `_push()` leave the new rows' `company_uid` blank.
- Blank `company_uid` means the `base.automation` rule's `filter_domain`
  skips them — no webhook fires.
- The pull-by-seq endpoint still returns them (it doesn't filter on
  `company_uid` being set) — so once you re-activate, nothing already
  pushed is silently lost from Core's point of view, it's just sitting
  there without a tenant UID stamped on it, same as if it had been pushed
  before the company was ever configured at all.
