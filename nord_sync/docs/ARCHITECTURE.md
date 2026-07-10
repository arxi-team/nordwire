# Architecture

## Two independent legs, one shared table

`nord.sync.queue` is the single source of truth. Two things happen around
it, and they don't depend on each other:

```
                         ┌─────────────────────┐
  mrp.production, etc.   │  nord.sync.queue     │
  (Phase 2, not built)   │  ─ audit trail       │
  ───────push()────────► │  ─ outbox            │
                         └──────────┬───────────┘
                                    │ create()
                    ┌───────────────┴───────────────┐
                    │                                │
         (A) base.automation fires          (B) Core polls independently
         synchronously, post-commit         GET /nord_sync/api/v1/queue
                    │                                │
                    ▼                                ▲
            Cloud webhook receiver          same table, filtered by
            (nordos_cloud)                  company_id + id > last_seq
                    │
                    ▼
            MQTT wake signal ───────────────────────►│
            (best-effort accelerator                 │
             for when Core should poll now)   (B) fires sooner
```

### Leg A — Odoo → Cloud (push, best-effort, fire-and-forget)

Implemented entirely with **native Odoo mechanisms**, no custom Python HTTP
code:

1. `nord.sync.queue._push(...)` calls `self.sudo().create({...})`.
2. A `base.automation` record (`data/nord_sync_automation.xml`,
   `trigger='on_create'`, `filter_domain=[('company_uid', '!=', False)]`)
   is watching `nord.sync.queue`. Odoo's `base_automation` module patches
   `create()` on every model generically, so this fires **synchronously**,
   inside the same transaction, as part of the same `create()` call that
   inserted the row.
3. If the row's `company_uid` is set, the rule's action
   (`webhook_action_queue_to_cloud`, `state='webhook'` — Odoo's built-in
   "Send Webhook Notification" action type) runs. It reads the row's
   `company_uid`, `model_name`, `operation`, `res_id`, `payload` fields and
   registers an HTTP POST to `webhook_url` on `self.env.cr.postcommit` —
   i.e. the POST only actually fires after the surrounding transaction
   commits, and Odoo does not wait for a response beyond a 1-second
   timeout. See `API.md` for the exact wire format.
4. If `company_uid` is blank, the rule's `filter_domain` skips the row
   entirely — no webhook call, no error, nothing. This is the mechanism
   behind "pause sync for a company": see `MODELS_AND_SECURITY.md`.

There is no retry, no backoff, no delivery status written back onto the
row. This is intentional (see `GOTCHAS_AND_GAPS.md`) — recovering a missed
delivery is leg B's job, not this leg's.

### Leg B — Core → Odoo (pull, authoritative, delivery-agnostic)

`GET /nord_sync/api/v1/queue?company_uid=<uid>&last_seq=<n>`
(`controllers/nord_sync_controller.py`), authenticated with a standard Odoo
API key (`auth='bearer'`) belonging to a technical user in the
`Nord Sync Integration` group.

This endpoint does not know or care whether leg A's webhook fired,
succeeded, timed out, or was skipped because `company_uid` was blank at
push time — it just returns every `nord.sync.queue` row for that company
with `id > last_seq`, in ascending order, capped at `PULL_LIMIT = 500`.
Core is expected to call this:

- **On MQTT wake** (published by Cloud after it receives leg A's webhook)
  — the fast path, typically sub-second end to end.
- **On a periodic heartbeat regardless of wake signals** — the
  reconciliation safety net. This is what makes the overall pipeline
  correct even though leg A has zero delivery guarantees: whatever leg A
  drops, the next heartbeat pull picks up, because the cursor (`last_seq`)
  is just "highest id seen," not "highest id successfully webhooked."

This is why blank-`company_uid` rows (pushed while a company's config is
inactive/incomplete) are still returned by this endpoint even though leg A
never fires for them — see
`test_entries_with_blank_company_uid_are_still_returned` in
`tests/test_controller.py`.

## Why the row is always created, even when unconfigured

`_push()` (`models/nord_sync_queue.py`) never skips creating the row — it
only conditionally sets `company_uid`. Two reasons:

1. **No gaps in the audit trail / cursor.** If pushes were skipped
   entirely while a company was unconfigured, the `id` sequence Core relies
   on as its cursor would have silent holes that are indistinguishable from
   "nothing happened" vs. "something happened but we don't know what."
2. **Safe resume.** Turning sync on later doesn't require backfilling
   anything — new rows after that point just start getting a real
   `company_uid` and firing the webhook. Nothing before that point is lost;
   it's still sitting in the table for leg B to eventually pick up if the
   config becomes active again with the same tenant UID.

## Why `company_uid` requires *both* an active config *and* a webhook URL

```python
config = self.env['nord.sync.config'].sudo().search([('company_id', '=', company_id)], limit=1)
ready = bool(config.active and config.company_uid)
if ready:
    action = self.env.ref('nord_sync.webhook_action_queue_to_cloud', raise_if_not_found=False)
    ready = bool(action and action.webhook_url)
```

Odoo's native webhook action raises `UserError` **synchronously, before
registering the postcommit callback** if fired with a blank `webhook_url`
(see `odoo/addons/base/models/ir_actions.py::_run_action_webhook`, checked
live against this Odoo 19 build). That's not a failed POST you can shrug
off — it aborts whatever transaction triggered the push (e.g. a future MO
save in Phase 2). So `_push()` treats "config active" and "webhook action
has a URL" as one combined precondition before it's willing to set
`company_uid` truthy, specifically to keep that failure mode impossible.
The webhook action's URL is written by the setup wizard
(`wizard/nord_sync_setup_wizard.py::action_save_config`) — see
`MODELS_AND_SECURITY.md` for why it's one shared URL, not one per company.
