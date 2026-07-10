# API Reference

Two wire formats matter here: the inbound pull endpoint this addon exposes
(consumed by Nord Core), and the outbound webhook payload Odoo sends to
Nord Cloud (produced by Odoo core, not custom code in this addon — documented
here because Cloud's receiving controller has to agree with it).

## 1. `GET /nord_sync/api/v1/queue` (Core ← Odoo)

`controllers/nord_sync_controller.py::pull_queue`

### Auth

`auth='bearer'` — a standard Odoo API key
(`res.users.apikeys`, generated on the client Odoo, Settings → Users →
target user → Account Security → New API Key), sent as:

```
Authorization: Bearer <key>
```

The owning user **must** be in the `nord_sync.group_nord_sync_integration`
group, or the request is rejected regardless of whether the key itself is
valid — see `MODELS_AND_SECURITY.md`.

### Query parameters

| Param | Required | Notes |
|---|---|---|
| `company_uid` | yes | Must match an existing `nord.sync.config.company_uid`. |
| `last_seq` | no, default `0` | Integer cursor. Returns rows with `id > last_seq`. |

### Responses

| Status | Condition |
|---|---|
| `200` | Success — see body shape below. |
| `400` | Missing `company_uid`, unknown `company_uid`, or non-integer `last_seq`. |
| `401` | Missing/invalid/expired API key. |
| `403` | Key belongs to a user not in `group_nord_sync_integration`, **or** the user's `company_ids` doesn't include the tenant resolved from `company_uid` (cross-tenant isolation). |

`200` body:

```json
{
  "company_uid": "cec66d88-edbe-45c8-b0ea-b44399f006e3",
  "last_seq": 19,
  "entries": [
    {
      "seq": 18,
      "model": "nord_sync.test",
      "operation": "create",
      "res_id": 0,
      "data": {"note": "Live team-check E2E run"}
    }
  ]
}
```

- `last_seq` in the response is `entries[-1].seq` if any rows were
  returned, otherwise it echoes back the request's `last_seq` unchanged.
  The caller should persist this value and pass it as the next request's
  `last_seq` — this is the entire cursor protocol, there is no separate
  "ack" step.
- `entries` is capped at `PULL_LIMIT = 500` rows per call, ordered by `id`
  ascending. If a call returns exactly 500 entries, there may be more —
  call again immediately with the new `last_seq`.
- An entry's `data` is whatever was passed as `payload` to `_push()` —
  currently only the fake `{'note': ...}` shape from
  `action_create_test_entry`. Phase 2 will define real shapes per
  `model`/`operation` once `mrp.production` (etc.) triggers exist.
- This endpoint is delivery-agnostic by design: it returns rows regardless
  of whether the Odoo→Cloud webhook (leg A) ever fired for them. See
  `ARCHITECTURE.md`.

### Example

```bash
curl -H "Authorization: Bearer $API_KEY" \
  "http://<odoo-host>/nord_sync/api/v1/queue?company_uid=$UID&last_seq=17"
```

## 2. Outbound webhook (Odoo → Cloud)

Not a controller in this addon — this is Odoo core's built-in "Send
Webhook Notification" server action (`ir.actions.server`,
`state='webhook'`), configured via `data/nord_sync_automation.xml`
(`webhook_action_queue_to_cloud`) and fired by the `base.automation` rule
on every `nord.sync.queue` row creation with a non-blank `company_uid`.

Source: `odoo/addons/base/models/ir_actions.py::_run_action_webhook`
(verified against this Odoo 19 build).

### Request

```
POST <webhook_url>
Content-Type: application/json
```

Body — always includes Odoo's own bookkeeping keys plus every field listed
in `webhook_field_ids` (currently `company_uid`, `model_name`, `operation`,
`res_id`, `payload`):

```json
{
  "_model": "nord.sync.queue",
  "_id": 19,
  "_action": "Nord Sync: send queue entry to Cloud(#3)",
  "company_uid": "cec66d88-edbe-45c8-b0ea-b44399f006e3",
  "model_name": "nord_sync.test",
  "operation": "create",
  "res_id": 0,
  "payload": {"note": "Live team-check E2E run"}
}
```

Serialized with `json.dumps(vals, sort_keys=True, default=str)` — keys are
alphabetically sorted in the actual bytes on the wire; non-JSON-native
values (datetime, date, binary) are stringified via `str()`, not omitted.

### What Odoo does with the response

- Any `2xx` within a **1-second timeout** → logged as
  `Webhook call to <url> - succeeded`, nothing else happens.
- Timeout (>1s, even if the server would have eventually answered) →
  logged as a warning, treated as "may or may not have failed," **no
  retry**.
- Connection refused / DNS failure / non-2xx → the exception propagates
  out of the postcommit callback. Since it fires after commit, the queue
  row itself is safe regardless, but this can surface as an error
  toast/traceback on whatever UI action triggered the push. See
  `GOTCHAS_AND_GAPS.md`.
- **The response body is never read or used for anything.** Whatever
  Cloud's controller returns (`{"success": true, "woken": true}` or
  otherwise) is invisible to Odoo — only the HTTP status code and whether
  the connection succeeded within the timeout matter.
- There is no shared secret/signature on this leg — Cloud's receiving
  controller only validates that `company_uid` matches a known tenant (see
  `nordos_cloud`'s own docs for that side).

### `company_uid` delivery detail

Because `webhook_url` is one shared URL for the whole Odoo install (see
`MODELS_AND_SECURITY.md`), `company_uid` cannot be embedded in the URL as a
per-tenant query string — it travels in the JSON body instead, as shown
above. Cloud's controller must read it from the body, not assume a query
string (it accepts both, body as fallback, as of 2026-07-09).
