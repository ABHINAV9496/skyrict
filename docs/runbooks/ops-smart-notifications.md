# Runbook: Smart Notification Center — Events, Fan-out, Batching & Preferences

Operational runbook for the PLT-NOTIF-001 notification center feature
(SKY-93): producer SDK, idempotent event fan-out, priority scoring, digest
batching worker, recipient-scoped API, and per-category preferences. This is
the Definition-of-Done ops artifact for ticket **PLT-NOTIF-001**.

Architecture reference:
[`docs/architecture/adr/007-smart-notification-center.md`](../architecture/adr/007-smart-notification-center.md).

---

## Operational overview

Per producer action, the pipeline is: a feature calls the **producer SDK**
(`NotificationProducer.emit(draft)`) → the service inserts one
**idempotent event** (unique on `(tenant_id, dedupe_key)`) → recipients are
resolved from the spec (`users` / `permissions` / `roles`) and each gets a
**notification row** honoring their stored per-category channel preferences →
the user sees the row in the **inbox** (topbar bell → drawer) or **preferences**
page. A background **batching worker** periodically collapses bursts of
low/medium rows of the same category into a single **digest** row.

### Key tables

| Table                    | Unique / anchor identity                          | Purpose                                        |
| ------------------------ | ------------------------------------------------- | ---------------------------------------------- |
| `notification_events`    | `(tenant_id, dedupe_key)`                         | Idempotent anchor per logical event            |
| `notifications`          | `(tenant_id, recipient_user_id, dedupe_key)`      | Per-user fan-out rows (inbox)                  |
| `notification_prefs`     | `(tenant_id, user_id, category)`                  | Per-user channel flags (`in_app`/`email`/`webhook`) |

Every PK is a tenant-scoped composite; rows are additionally protected by RLS
on the tenant key. There are no bare cross-tenant UUIDs in this feature.

### State / lifecycle

A notification row is created unread at emit time and becomes **read**
(`read_at`) via the API. **Snoozed** rows (`snoozed_until`) stay out of the
inbox until the time passes; snoozing an already-snoozed row keeps the earliest
future timestamp (idempotent). Mandatory or pinned rows cannot be snoozed, and
mandatory categories are never collapsed into digests (server-enforced).

---

## Configuration (services/core settings)

| Setting                        | Default  | Meaning                                                              |
| ------------------------------ | -------- | ------------------------------------------------------------------- |
| `NOTIF_BATCH_WORKER_ENABLED`   | `True`   | Run the in-process digest batching worker; disabled under the test env |
| `NOTIF_BATCH_POLL_SECONDS`     | `300`    | Idle interval between batching passes                                 |
| `NOTIF_BATCH_WINDOW_MINUTES`   | `60`     | Rolling window width for grouping rows into one digest                |
| `NOTIF_BATCH_MIN_COUNT`        | `1`      | Minimum low/medium rows required to trigger a digest                  |
| `NOTIF_EMAIL_ENABLED`          | `False`  | Enable the log-only email adapter (no SMTP dialling)                  |
| `NOTIF_WEBHOOK_ENABLED`        | `False`  | Enable the log-only webhook adapter                                   |
| `NOTIF_INBOX_PAGE_SIZE`        | `50`     | Default page size for `GET /notifications/inbox`                      |

Email/webhook are **log-only by default**: with the flag on, the dispatcher
records a structured "would-send" event instead of dialling a provider. Real
SMTP/webhook delivery is a future adapter swap.

## Category registry

Source of truth: `core.features.notifications.categories.CATEGORIES` — adding a
category here is all a new producer needs. Display label, owning module,
`relevance_permission` (the natural audience; grants the scoring boost),
`mandatory` flag.

| Category        | Module      | Mandatory | Relevance permission   |
| --------------- | ----------- | --------- | ---------------------- |
| `inventory`     | inventory   | no        | `erp.inventory.read`   |
| `finance`       | finance     | no        | `erp.finance.read`     |
| `approval`      | approval    | no        | `erp.finance.approve`  |
| `compliance`    | compliance  | **yes**   | - (every recipient)    |
| `payroll`       | payroll     | no        | `erp.payroll.read`     |
| `anomaly`       | ai          | no        | -                      |
| `product`       | product     | no        | -                      |

Mandatory semantics (enforced server-side, not just in the UI): in-app channel
forced on for every recipient, cannot be opted out, snoozed, or collapsed into
a digest.

## Producer SDK

```python
from core.features.notifications.producer import NotificationProducer
from core.features.notifications.domain import (
    NotificationDraft,
    RecipientSpec,
    NotificationSeverity,
)

await NotificationProducer(db).emit(
    NotificationDraft(
        dedupe_key="inventory.low_stock:prod_123",  # stable per logical event
        event_type="inventory.low_stock",
        category="inventory",
        module="inventory",
        severity=NotificationSeverity.HIGH,
        title="Low stock: SKU-1001",
        body="Steel bracket is below reorder point.",
        recipients=RecipientSpec.from_permissions("erp.inventory.read"),
        relevance_key="inventory",
        payload={"sku": "SKU-1001"},
    )
)
```

- **`dedupe_key` is the idempotency contract.** Pick a stable
  `{module}.{event}:{tenant-scoped-entity-id}`; re-emitting the same key (retry,
  replay, re-read) returns `EmitOutcome(deduped=True)` and never creates a
  second row for any recipient.
- `RecipientSpec`: `from_users(*ids)`, `from_permissions(*keys)`,
  `from_roles(*names)`.
- Severity weights drive `priority_score`: low 10, medium 40, high 70,
  critical 100; decays with age (min 40% weight), `+10` when relevant (default
  for permission/role audiences), clamped 0–100.

## API reference (recipient-scoped; user id from the authenticated principal)

| Method | Path                                    | Purpose                                  |
| ------ | --------------------------------------- | ---------------------------------------- |
| GET    | `/api/v1/notifications/inbox`           | Paged inbox (`limit` ≤200, `offset`, `category?`, `unread_only?`) |
| GET    | `/api/v1/notifications/counts`          | `unread_count` + `pinned_unread_count` (bell badge) |
| POST   | `/api/v1/notifications/read-all`        | Mark entire inbox read; returns `marked` |
| POST   | `/api/v1/notifications/{id}/read`       | Mark one read                            |
| POST   | `/api/v1/notifications/{id}/snooze`     | `{until}` ISO; 409 for mandatory/pinned or past |
| GET    | `/api/v1/notifications/preferences`     | All category preferences with labels     |
| PUT    | `/api/v1/notifications/preferences/{category}` | Upsert channel flags (`in_app_on`, `email_on`, `webhook_on`) |

Notes:

- Reading your own inbox needs **no module permission**; the module permission
  decides *who receives* the category at fan-out time.
- Snoozing a mandatory/pinned row returns 409 with a sanitized message.
- The web BFF routes `/api/v1/notifications/*` to **core** (the segment is in
  the core-target list in `apps/web/src/app/api/v1/[...path]/route.ts`).

## Digest batching worker

- Runs in the core process (started in the API lifespan) unless disabled;
  **disabled under the test environment** so integration tests drive the batch
  pass directly.
- One pass: selects eligible low/medium rows per tenant+category+module within
  `NOTIF_BATCH_WINDOW_MINUTES`, collapses groups meeting
  `NOTIF_BATCH_MIN_COUNT` into one digest row (anchor stays; members are merged
  with `digest_count`), never touching mandatory or pinned rows.
- **Manual/CI operator control:** `uv run --directory services/core core notification_batch`
  runs the same pass deterministically (optional `--window` minutes, default
  `NOTIF_BATCH_WINDOW_MINUTES`). A demo producer is available:
  `core notification_demo`.

## Web surface

- Topbar bell (replaces the previous dead Inbox button): fetches
  `/notifications/counts` for the unread badge; drawer fetches
  `/notifications/inbox`, supports per-row read, mark-all-read, snooze presets
  (1h / tomorrow 9:00 / 1 week), and links to preferences.
- Preferences page (`/dashboard/settings/notifications`, also in the sidebar
  under Manage): per-category channel toggles; mandatory categories show a
  locked in-app toggle; the backend still enforces the lock if the UI is
  bypassed.

## Monitoring / troubleshooting

| Signal                                   | Meaning                                           |
| ---------------------------------------- | ------------------------------------------------- |
| `notifications.emit.deduped` (info)      | Re-emit of an existing `dedupe_key`; expected on retries/replays |
| `notifications.prefs.mandatory_in_app_forced` (info) | A client tried to disable in-app on a mandatory category; server kept it on |
| `notification-batch` CLI run             | Deterministic single pass; verify counts/summary rows after a burst |
| Inbox shows N identical cards            | Producer used an unstable `dedupe_key`; fix the key so re-emits collapse |

Known limits: email/webhook are log-only adapters behind their master flags;
the batching worker is in-process (CLI-invocable pass makes a future worker
process split a contained change).