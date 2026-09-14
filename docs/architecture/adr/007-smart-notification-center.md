# ADR-007: Smart notification center - idempotent events, priority scoring, digest batching

## Status

Accepted

## Date

2026-09-14

## Context

SKY-93 (PLT-NOTIF-001) introduces a platform notification center to the core
service: producers emit events, the service fans each event out to the right
recipients, and the user sees an inbox with read/snooze/preferences plus a
topbar bell. A naive "write a row per recipient on every emit" design fails in
the ways the platform rule exists to prevent:

- **Duplicate deliveries.** A producer retry, a replay of a read-model
  integration, or a repeated batch sweep re-inserts the same logical event and
  the user's inbox shows duplicates.
- **Channel selection at the wrong layer.** If the service decides email vs
  in-app at emit time, a later preference change is ignored and the deliverable
  contract between service and user is not the user's stored preference.
- **Unbounded inbox noise.** A burst of 50 low-severity `inventory` events
  creates 50 rows; the user must click each. High-volume operational signals
  need collapsing into a digest without hiding mandatory rows.
- **No escape hatches.** A mandatory category (e.g. compliance) must always be
  visible in-app; permission-scoped categories must reach exactly their natural
  audience (permission holders), never the whole workspace.
- **Cross-tenant or cross-user leakage.** Recipient resolution and row reads
  must be tenant- and user-scoped by construction.

## Decision

1. **Composites keys and idempotent emission anchor on one event table.**
   `notification_events` carries `(tenant_id, dedupe_key)` as its unique
   delivery identity. `emit()` inserts with `ON CONFLICT DO NOTHING`: a re-emit
   returns `EmitOutcome(deduped=True)` and creates no notification rows. The
   fan-out rows in `notifications` are keyed by
   `(tenant_id, recipient_user_id, dedupe_key)` so even a concurrent double
   emit can never double-deliver to one user. Every primary key in the feature
   is the tenant-scoped composite - there is no bare cross-tenant UUID.

2. **Recipients are resolved from the registry, not from producer guesses.**
   `RecipientSpec` is `users` (explicit ids), `permissions`, or `roles`; the
   producer resolves membership at emit time against live identity data. The
   service applies the user's stored per-category preference at fan-out, and
   channel selection (`select_channels`) is a pure function of preference +
   master switches + category mandatory flag. Users who opted out of every
   channel for a non-mandatory category receive no row at all.

3. **Priority scoring is deterministic and auditably recomputable.** Each
   notification row stores `priority_score` computed as
   `severity_weight * (1 - min(0.6, age_hours * 0.15)) + (10 if relevant)`
   (weights: low 10, medium 40, high 70, critical 100), floored at 40% of the
   weight and clamped to 0-100. "Relevant" means the recipient was resolved via
   the category's `relevance_permission` (i.e. they are the natural audience),
   which is always true for permission/role/audience-driven fan-out. The score
   decays with age so older notifications rank lower in the inbox.

4. **Digest batching collapses low/medium bursts, never mandatory rows.** The
   in-process worker (`notification_batch_pass` in `lifespan.py`, disabled
   under the test environment) groups eligible low/medium rows of the same
   category+module within `NOTIF_BATCH_WINDOW_MINUTES` (default 60) once the
   group meets `NOTIF_BATCH_MIN_COUNT` (default 1). A digest replaces the group
   member rows (except the anchor) with a summary row (`is_digest=True`,
   `digest_count`), giving the user one card instead of N. Mandatory categories
   are excluded from batching; pinned rows are never collapsed. The CLI exposes
   `notification-batch` for manual/CI operator control of the same code path.

5. **Mandatory is enforced server-side, twice.** Category registry flags a
   category `mandatory`; the service refuses snooze on mandatory or pinned rows
   (`ConflictError`), keeps `in_app_on` forced true on preference upsert
   regardless of the payload, and excludes the category from digest collapse.
   The UI mirrors this by disabling the in-app toggle and hiding snooze on
   pinned rows - but the server is the authority and the UI is only a hint.

6. **The API is recipient-scoped by construction, no new permission.** Every
   inbox/counts/read/snooze/preferences query carries `tenant_id` (from
   request context) and `user_id` (from the authenticated principal) and all
   rows are additionally protected by RLS on the composite-tenant key. No
   module permission gates reading your own inbox; a module permission gates
   *who receives* the category at fan-out time. Multiple snooze of the same row
   is idempotent (keeps the earliest future `snoozed_until`); snoozes into the
   past are rejected.

7. **The web surface is a thin client over the same API.** The topbar bell
   fetches `/notifications/counts` for its badge; the drawer lists
   `/notifications/inbox`, marks read, snoozes, and links to a preferences page
   that PUTs per-category channel flags. Notifications proxy through the BFF
   (`[...path]/route.ts`) routed to **core** - the segment was added to the
   core-target list so the browser never talks to identity for them.

## Consequences

### Positive

- Retries, replays, and concurrent emits are safe by construction: the unique
  keys turn duplicates into no-ops without application-level locking.
- Channel delivery honors the user's stored preference, and toggling a
  preference affects the next emit without code changes.
- Digests keep the inbox readable under bursts while compliance rows are
  always visible and always in-app.
- The recipient-scoped API + RLS gives tenant/user isolation at two layers;
  adding a category to the registry is all a new producer needs.

### Negative

- An event is materialized per recipient at emit time, so a workspace-wide
  permission-scoped cast (e.g. "all finance") materializes N rows. The digest
  pass mitigates the resulting inbox noise but the fan-out is still explicit.
- Email/webhook adapters are intentionally log-only behind
  `NOTIF_EMAIL_ENABLED` / `NOTIF_WEBHOOK_ENABLED` (both default False); real
  SMTP/webhook delivery is a future adapter swap, not implemented here.
- The batching worker runs in-process; a future large-scale deployment would
  move it to a separate worker process (the pass logic is already
  CLI-invocable, so the move is contained to lifespan wiring).

### Mitigations

- The service unit matrix and the integration suite encode the invariants:
  re-emit is a no-op per user, mandatory cannot opt out/snooze/collapse, and
  counts are per-tenant.
- Priority scoring is a pure function of stored inputs (severity, occurrence,
  relevance) so scores can be recomputed for any row later without migration.
- All error paths surface sanitized messages (e.g. "This notification cannot
  be snoozed") - no internal identifiers or stack traces leave the service.