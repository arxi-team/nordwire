# nord_sync — Test Suite Guide

This document walks through every test file in `nord_sync/tests`, what each
test class/function actually verifies, and how to run them with visible
logging so you can watch what's happening step by step instead of only
seeing a final `OK`/`FAIL`.

All test files were annotated with `_logger.info(...)` calls at the key
steps of each test (setup, actions taken, and the value being asserted).
Run Odoo's test runner with `--log-level=info` (or `test` if you want
everything) to see them in the console output.

```bash
./odoo-bin -d your_db -i nord_sync --test-enable --test-tags nord_sync \
    --log-level=info --stop-after-init
```

Or, to run a single file/class/test:

```bash
./odoo-bin -d your_db --test-enable \
    --test-tags /nord_sync:TestNordSyncQueue.test_creating_a_row_fires_the_native_webhook \
    --log-level=info --stop-after-init
```

Each log line is prefixed with a short tag like `[push]`, `[deliver]`,
`[auth]`, `[cursor]`, etc. so you can quickly scan the output and follow
the story of each test (what was created, what action was taken, what
value came back, and what was expected).

---

## `__init__.py`

Just imports every test module below so Odoo's test loader picks them all
up:

```python
from . import test_access
from . import test_config
from . import test_controller
from . import test_queue
from . import test_wizard
```

---

## `test_access.py` — `TestNordSyncAccess`

Verifies the group-based access control (record rules / `ir.model.access`)
defined for `nord.sync.queue` and `nord.sync.config`, plus menu visibility.
Corresponds to steps 2–4 of the manual test plan.

**`setUpClass`** creates three users and one config/queue row shared by all
tests in the class:
- `manager` — in `nord_sync.group_nord_sync_manager` (full access group).
- `integration` — in `nord_sync.group_nord_sync_integration` (read-only
  integration group).
- `plain_user` — a regular internal user with neither group.

| Test | What it checks |
|---|---|
| `test_manager_has_full_crud_on_queue_and_config` | The manager group can create, write, read and unlink queue entries, and read/write the config. |
| `test_integration_group_is_read_only_on_queue` | The integration group can **read** a queue entry but gets `AccessError` on write, create, and unlink. |
| `test_integration_group_is_read_only_on_config` | Same read-only pattern, but on the config model. |
| `test_plain_internal_user_has_no_access_to_queue_or_config` | A user in neither group can't even read queue entries or config. |
| `test_menu_is_restricted_to_manager_group` | Proxy/static check that the root menu (`nord_sync.nord_sync_menu_root`) lists the manager group in `group_ids` — actual menu *visibility* is a UI concern that can't be asserted from a `TransactionCase`, so this only confirms the underlying access group wiring. |

---

## `test_config.py` — `TestNordSyncConfig`

Verifies the `nord.sync.config` model's one-config-per-company invariant
and its `_create_or_update_for_company` upsert helper. Corresponds to
manual test plan steps 11–12.

| Test | What it checks |
|---|---|
| `test_one_config_per_company` | Creating a second `nord.sync.config` row for the same company raises a Postgres `IntegrityError` (the unique SQL constraint on `company_id`). Uses `mute_logger('odoo.sql_db')` to keep the expected DB error out of the console noise. |
| `test_create_or_update_for_company_creates_once` | The first call to `_create_or_update_for_company` creates exactly one row scoped to `self.env.company`. |
| `test_create_or_update_for_company_upserts` | A second call for the *same* company updates the existing row (same `id`, new `cloud_webhook_url`) instead of creating a duplicate. |

---

## `test_access.py` (queue field references)

`test_manager_has_full_crud_on_queue_and_config`,
`test_integration_group_is_read_only_on_queue`, and
`test_plain_internal_user_has_no_access_to_queue_or_config` read/write
`company_uid` on a queue row as their probe field (the old probes,
`state`/`error_message`, no longer exist - see `test_queue.py` below for why).

---

## `test_controller.py` — `TestNordSyncController`

`HttpCase`-based tests for the pull endpoint `GET /nord_sync/api/v1/queue`.
Corresponds to manual test plan section 5 (steps 24–32).

**`setUpClass`** creates a config (`tenant-a`), an `integration_user` with
an API key (used as a Bearer token), and an `other_user` (no integration
group) with its own API key to exercise the 403 branch.

Helpers:
- `_auth_headers(key)` — builds the `Authorization: Bearer <key>` header.
- `_get(params, key=None)` — issues the actual `GET` request and logs the
  URL, whether a key was sent, and the resulting status code.

| Test | What it checks |
|---|---|
| `test_no_auth_returns_401` | No `Authorization` header → `401`. |
| `test_invalid_key_returns_401` | A garbage API key → `401`. |
| `test_user_without_integration_group_returns_403` | Valid key, but the owning user lacks the integration group → `403`. |
| `test_missing_company_uid_returns_400` | Valid auth but no `company_uid` query param → `400`. |
| `test_unknown_company_uid_returns_400` | `company_uid` that doesn't match any config → `400`. |
| `test_wrong_tenant_user_returns_403` | A key valid for `tenant-a` used against a *different* company's config (`tenant-b`) → `403` (tenant isolation). |
| `test_pull_returns_entries_in_order_with_expected_shape` | Two queued entries are returned in insertion order, `last_seq` equals the last entry's id, and each entry has the exact `{seq, model, operation, res_id, data}` shape. |
| `test_cursor_only_returns_newer_entries` | Passing `last_seq=<first.id>` returns only entries created *after* that cursor. |
| `test_cursor_with_no_new_entries_returns_empty_list` | Passing `last_seq` equal to the newest entry returns an empty `entries` list (not an error). |
| `test_entries_with_blank_company_uid_are_still_returned` | An entry pushed while the company had no active config (blank `company_uid`, so the native webhook never fired) is still included in the pull response — the endpoint doesn't care whether/how the Odoo→Cloud leg delivered. |
| `test_pagination_caps_at_pull_limit` | With `PULL_LIMIT` patched down to 2, a batch of 3 pushed entries is split across two pages; the second page is fetched using the `last_seq` returned by the first. |

---

## `test_queue.py` — `TestNordSyncQueue`

Covers `nord.sync.queue`: enqueueing (`_push`), serialization (`_to_command`),
and the native Odoo→Cloud webhook (an `ir.actions.server` of
`state='webhook'`, fired by a `base.automation` rule on row creation — see
`data/nord_sync_automation.xml`). There is no custom delivery/retry/backoff
code anymore: Odoo's own webhook action does a single fire-and-forget POST
registered on `self.env.cr.postcommit`, so tests that need to observe it call
`self.env.cr.postcommit.run()` to flush that queue synchronously (real commits
never happen inside a `TransactionCase`, so nothing fires the callbacks on its
own). All HTTP calls are mocked via `patch('requests.post')` — the core
webhook code does a bare `import requests` at call time, so patching the
`requests` module's `post` attribute directly (not
`odoo.addons.nord_sync...requests.post`) is what actually intercepts it.

`setUpClass` points the shared webhook action's `webhook_url` at the test
config's URL — without that, `_push` deliberately leaves `company_uid` blank
(see below), since Odoo's native action *raises synchronously* if fired with
no URL, which would otherwise crash whatever transaction (e.g. a future MO
save) triggered the push.

`_mock_response(status_code, text)` is a small helper building a `Mock()`
that looks like a `requests.Response`.

### push / enqueue

| Test | What it checks |
|---|---|
| `test_push_creates_entry_with_expected_fields` | `_push(...)` creates a row with the right `company_id`, `company_uid`, `model_name`, `operation`, `res_id`, `payload`. |
| `test_push_leaves_company_uid_blank_when_config_inactive` | Pausing the company's config (`active=False`) makes `_push` leave `company_uid` blank on the new row. |
| `test_push_still_creates_row_when_no_config_exists` | A company with no `nord.sync.config` at all still gets a queue row (blank `company_uid`) — the audit trail/reconciliation cursor never has gaps, sync just never fires for it. |
| `test_action_create_test_entry_uses_canned_payload` | The `action_create_test_entry` button/action creates a canned entry (`model_name='nord_sync.test'`, `res_id=0`, payload containing a `note` key) — used for manual smoke testing from the UI. |
| `test_to_command_shape` | `_to_command()` serializes a queue entry into the exact wire format the Core's pull-by-seq endpoint returns: `{seq, model, operation, res_id, data}`. |

### native Odoo→Cloud webhook (Automation Rule)

| Test | What it checks |
|---|---|
| `test_creating_a_row_fires_the_native_webhook` | Creating a row with a non-blank `company_uid` registers a postcommit `requests.post` call to the configured URL, with a JSON body containing `company_uid`, `model_name`, `operation`, `res_id`, `payload`. |
| `test_row_with_blank_company_uid_does_not_fire_the_webhook` | Pausing the company's config first means the created row has a blank `company_uid`, and the rule's `filter_domain` skips it — no `requests.post` call at all. |

---

## `test_wizard.py` — `TestNordSyncSetupWizard`

Covers `nord.sync.setup.wizard`: the pre-flight diagnostics shown when
opening the wizard, and the `action_save_config` validation/upsert logic.

### pre-flight checks (manual test plan steps 5–6)

The wizard checks the running Odoo version (`odoo.release.version_info`,
patched via `VERSION_INFO_TARGET`) to warn before the user goes further.
There's no cron-related check anymore - the Odoo→Cloud leg is a native
Automation Rule, not a consumer cron, so there's nothing local left to poll.

| Test | What it checks |
|---|---|
| `test_preflight_all_checks_pass` | On a "supported" version (19.0), the computed flag is `True` and there's no `preflight_warning`. |
| `test_preflight_warns_when_version_unsupported` | Running on Odoo 17.0 (not the supported 19.0 line used in this test) produces a warning containing "not a supported". |

### save/validation (manual test plan steps 8–9, 11)

| Test | What it checks |
|---|---|
| `test_save_requires_tenant_uid_and_webhook_url` | Saving with both fields empty raises `UserError`. |
| `test_save_rejects_url_without_scheme` | A webhook URL missing `http://`/`https://` (e.g. `localhost:8090/webhook`) raises `UserError`. |
| `test_save_creates_config` | A valid save creates exactly one `nord.sync.config` row for the current company with the submitted `company_uid`, `cloud_webhook_url`, and `mo_filter_criteria`. |
| `test_save_wires_the_native_webhook_action_url` | A valid save also writes the URL onto the shared `nord_sync.webhook_action_queue_to_cloud` server action - not just onto `nord.sync.config` - since that's what the Automation Rule actually reads. |
| `test_save_upserts_existing_config` | Saving the wizard twice for the same company updates the single existing config row (same tenant, new webhook URL) rather than creating a second one. |

---

## Reading the logs

With `--log-level=info`, a run of, say,
`test_creating_a_row_fires_the_native_webhook` will print something like:

```
INFO ... odoo.addons.nord_sync.tests.test_queue: [webhook] entry #123 created, requests.post called: True
INFO ... odoo.addons.nord_sync.tests.test_queue: [webhook] POST body: {'company_uid': 'tenant-a', 'model_name': 'nord_sync.test', 'operation': 'create', 'res_id': 7, 'payload': {'message': 'hi'}}
```

That lets you follow, test by test, what record was created, what mocked
response/error was injected, and what the resulting field values were —
without having to attach a debugger or add temporary `print()`s.