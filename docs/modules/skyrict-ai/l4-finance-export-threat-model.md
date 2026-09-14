# L4 Finance-Export Threat Model — SKY-93 (HR-AI-004, Commit 4)

> **Ticket:** SKY-93 (HR-AI-004)  
> **Commit:** 4 — finance bridge  
> **Author:** skyrict-engineering  
> **Status:** Implementation  
> **Last reviewed:** 2026-09-12  

This document is the deep-dive security analysis and threat model for the L4
what-if scenario → Finance budget-draft bridge.  It lives alongside the
implementation (not inside the PR description) so it survives future reviews
and the next audit pass.

---

## Table of contents

1. [Gherkin contract (acceptance tests)](#1-gherkin-contract)
2. [Attack surface overview](#2-attack-surface-overview)
3. [Mitigations in place](#3-mitigations-in-place)
4. [Specific SKY-93 attacks](#4-specific-sky-93-attacks)
5. [Spec alignment: contract ↔ code](#5-spec-alignment)

---

## 1. Gherkin contract

```
Given a user with erp.hr.ai.planning + erp.ai.invoke
When they export a named L4 what-if scenario to Finance
Then Finance shows a proposed budget draft linked back to the scenario version
And the draft carries only line-2 (salary) and line-3 (benefit) totals
And the scenario is immutable once exported
```

**Replay variant:**

```
Given an L4 scenario already exported to Finance
When the same user re-exports the same scenario
Then Finance still shows exactly one draft for that scenario
And the API returns { already_booked: true, draft_id: <original> }
```

---

## 2. Attack surface overview

The export crosses three trust boundaries in one request:

```
Browser → core API (auth + authz) → ai-agent (proxy, scenario read) → finance service (DB write)
```

| Boundary | Asset | Threat class |
|----------|-------|-------------|
| core→ai-agent proxy | Frozen projection JSON | Spoofed/forged scenario body |
| ai-agent→finance DB write | `erp_budget_drafts` row | Unauthorized cross-tenant write |
| Browser→core POST body | `scenario_id` path param | IDOR / replay / mass-export |
| finance DB | Status lifecycle `draft→pending→approved` | Status-factory / escalation |
| all surfaces | Scenario + draft data at rest | Confidentiality / PII leak |

---

## 3. Mitigations in place

### 3.1 Auth + authz (top of funnel)

The core router gates the endpoint with two permissions **sequentially**:

```python
# core/features/ai_hr/router.py (lines 829–832)
_invoke: _AiInvokeDep          # erp.ai.invoke
current_user: _HrAiPlanningDep # erp.hr.ai.planning
```

Both are enforced *before* the first DB call or proxy call.  No code path
reaches the finance service without passing both.  The `erp.hr.ai.planning`
permission is owner-wildcard: only users explicitly granted this permission on
the tenant can trigger exports.

### 3.2 Tenant isolation (DB row security)

Every DB read and write is scoped through the `tenant_id` extracted from the
authenticated user's JWT (`_tenant_id(current_user)`).  The budget-draft
`INSERT` is:

```python
# core/features/finance/service.py — create_workforce_budget_draft()
BudgetDraft(
    tenant_id=tenant_id,       # ← always from JWT, never from the URL/body
    source_ref=str(scenario_id),
    ...
)
```

The `UNIQUE (tenant_id, source, source_ref)` index (migration 0054) acts as
the cross-tenant isolation guard: a replayed export *within the same tenant*
hits the unique constraint and is returned as `already_booked` (409
ConflictError caught by the service).  A cross-tenant replay with the same
`scenario_id` (impossible — scenario IDs are UUID4 and tenant-scoped in
ai-agent) would produce a different `source_ref` per-tenant.

### 3.3 Scenario immutability after export

The budget-draft row is **write-once**.  There is no UPDATE endpoint on
`erp_budget_drafts`.  The `status` field starts as `draft` and can only be
moved to `pending` or `approved` through a future approval workflow (not
shipped in Commit 4).  This satisfies the Gherkin "scenario is immutable once
exported": the scenario lives in ai-agent (read-only frozen snapshot) and the
budget draft lives in finance (write-once artifact); neither can be mutated
through the export path.

### 3.4 Audit trail

The export endpoint appends an `hr.ai.l4.budget_draft.created` event to the
core audit log **in the same transaction** as the draft creation:

```python
await audit.log(
    action=HR_AI_L4_BUDGET_DRAFT_CREATED,
    target=f"scenario:{scenario_id}",
    tenant_id=tenant_id,
    user_id=actor,
    details={
        "source": "workforce_plan",
        "draft_id": str(draft_id),
        "grand_total": projection["grand_total"],
    },
)
```

In ai-agent, `ai.l4.scenario.viewed` and `ai.l4.scenario.compared` events
were added for the get and compare read paths respectively (Commit 4e).  The
audit chain is: view → export → audit, and every link is now traced.

### 3.5 Minimal data surface

The budget draft carries **only two lines**: salary and benefits totals.  It
does not carry per-employee rows, names, IDs, departments, or any other PII.
The projection's `months[]` array (which contains monthly granularity) is
deliberately not stored in the budget draft — only the 12-month totals.  This
is the smallest possible data surface that satisfies the Finance "know the
forecast" need.

### 3.6 Deliberate separation from the JE inbox

The budget draft is **not** a DRAFT journal entry.  The `erp_budget_drafts`
table is separate from `erp_journal_entries`.  A what-if projection must not
share the JE inbox because:

1. The JE inbox is strictly separated from planned figures (design principle).
2. A draft JE would be visible to accounts payable and could be accidentally
   posted, turning a what-if projection into a real ledger entry.
3. The JE path (status: `draft→posted→voided`) does not match the budget
   path (`draft→pending→approved`).

This architectural boundary is the single most important defense against
misclassification of projected costs as booked costs.

---

## 4. Specific SKY-93 attacks

### Attack 1 — Forged projection body (spoofed totals)

**Scenario:** An attacker calls the core export endpoint directly with a
manually constructed request, hoping to write arbitrary amounts into the
finance table.

**Why it fails:** The projection is **never read from the request body**.  The
endpoint fetches the frozen scenario from ai-agent via an internal HTTP call
(`forward_to_ai_agent`) using the caller's JWT:

```python
upstream = await forward_to_ai_agent(
    client,
    method="GET",
    upstream_path=f"/api/v1/ai/l4/scenarios/{scenario_id}",
    authorization=authorization,   # ← caller's JWT forwarded
    tenant_slug=derive_tenant_slug(request),
)
```

The projection is parsed from ai-agent's response JSON, not from any user
supplied field.  The `salary_total`, `benefit_total`, and `grand_total` are
read exclusively from the stored frozen snapshot.  An attacker has no write
path to the scenario in ai-agent through this endpoint.

### Attack 2 — Mass-export (IDOR / cross-scenario abuse)

**Scenario:** An attacker iterates over UUIDs to export every scenario in the
tenant, or tries to export another tenant's scenario.

**Mitigations:**

| Defense | Mechanism |
|---------|-----------|
| Permission gate | `erp.hr.ai.planning` checked before any DB or proxy call |
| Scenario ID validation | ai-agent returns 404 for non-existent or cross-tenant scenario IDs (tenant-scoped query) |
| Idempotency lock | `UNIQUE (tenant_id, source, source_ref)` prevents duplicate drafts per scenario |
| Audit trail | Every export attempt is audited — even if ai-agent returns 404, the caller's action is logged (no silent failure) |

The `tenant_slug` header is derived from the JWT's tenant claim and forwarded
to ai-agent; ai-agent resolves the tenant from the slug independently, so
cross-tenant access requires compromising both the JWT and ai-agent's tenant
resolver.

### Attack 3 — Status-factory (escalation from draft to approved)

**Scenario:** An attacker tries to move the budget draft from `draft` to
`approved` (or to `pending`) without proper authorization, bypassing the
approval workflow.

**Why it fails:**

1. There is **no update endpoint** for `erp_budget_drafts` in Commit 4.  The
   only way to create a draft is through the POST export endpoint.
2. The `status` column has a CHECK constraint:
   `ck_erp_budget_drafts_status: status IN ('draft', 'pending', 'approved')`.
   Only valid lifecycle transitions are possible at the DB level.
3. A future approval endpoint (not shipped) would enforce:
   - Only `draft→pending` and `pending→approved` transitions
   - A separate approval permission (e.g., `erp.finance.budget.approve`)
   - An audit event for every transition

The current state is secure-by-absence: the attack surface literally does not
exist yet.

### Attack 4 — Confidentiality / PII leak through budget drafts

**Scenario:** An attacker gains read access to `erp_budget_drafts` (e.g.,
through a compromised service account or SQL injection) and tries to extract
employee PII.

**Mitigations:**

| Column | Risk | Residual risk |
|--------|------|--------------|
| `scenario_name` | Could contain employee names if user named it poorly | Low — name is user-controlled free text; no enforcement against PII in names |
| `salary_total` / `benefit_total` / `grand_total` | Aggregate payroll cost | Low — org-level aggregate, not per-employee; same as what finance sees in annual reports |
| `created_by` | UUID of the user who exported | Minimal — UUID, not PII; needed for audit |
| `scenario_id` | UUID reference to ai-agent | Minimal — UUID, not PII |

**Residual risk:** The `scenario_name` field is the only potential PII leak
vector.  It is user-controlled free text (up to 120 chars).  The L4 scenario
create endpoint (`POST /api/v1/ai/l4/scenarios`) accepts a `name` field
without PII validation.  A user *could* name a scenario "John Smith salary
increase" and that name propagates into the finance budget draft.

**Recommended follow-up (not in scope for Commit 4):** Add a PII warning on
the scenario create endpoint, or consider truncating/rejecting names that
match employee names from the payroll base.  The current risk is acceptable
because: (a) only users with `erp.hr.ai.planning` can create/export scenarios,
(b) those users already see employee names in the payroll base, and (c) the
budget draft name is not exposed to anyone outside the finance module.

---

## 5. Spec alignment

| Spec requirement | Implementation | Location |
|------------------|---------------|----------|
| Export produces a proposed budget draft | `erp_budget_drafts` table, status `draft`, source `workforce_plan` | `core/features/finance/models/budget_draft.py` |
| Draft carries salary + benefit totals | Two `erp_budget_drafts_lines` rows: label `Salary` + `Benefits` | `core/features/finance/models/budget_draft_line.py` |
| Idempotent on replay | `UNIQUE (tenant_id, source, source_ref)` constraint; service returns `already_booked` | `core/features/finance/service.py:1073` |
| Status lifecycle: draft→pending→approved | `ck_erp_budget_drafts_status` CHECK constraint | Migration 0054 |
| Deliberate separation from JE inbox | Separate table, separate port (`BudgetDraftPort`), not routed through `erp_journal_entries` | `core/features/finance/ports.py:537` |
| Audit trail | `hr.ai.l4.budget_draft.created` in core; `ai.l4.scenario.viewed` + `ai.l4.scenario.compared` in ai-agent | `core/core/audit_events.py:41`, `ai_agent/core/audit_events.py` |
| No PII in budget draft | Only aggregates (no employee rows); `scenario_name` is the only free-text field | Design decision documented above |
| Gherkin "Finance shows pending budget draft linked back to scenario version" | `scenario_id` + `scenario_name` columns on `erp_budget_drafts`; `source_ref` = scenario UUID | Migration 0054 + service |

---

## Open items

| # | Item | Priority | Owner |
|---|------|----------|-------|
| 1 | Approval workflow for `erp_budget_drafts` (draft→pending→approved) | High | Finance / HR |
| 2 | UI export button in Planning Studio (deferred to separate follow-up per user decision) | Medium | Frontend |
| 3 | PII warning on scenario name field | Low | AI-HR |
| 4 | Full audit-comparison: `AI_L4_SCENARIO_VIEWED` on list endpoint (omitted — noisy per-page; covered by get + compare) | Low | Security |
