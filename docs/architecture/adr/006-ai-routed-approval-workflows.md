# ADR-006: AI-routed approval workflows - suggestions advise, the engine decides

## Status

Accepted

## Date

2026-09-13

## Context

SKY-92 (PLT-APPR-001) adds approval workflows to the core service: a journal
entry reaches the "pending approval" state before posting, a payroll run
before approval, and the AI agent can analyze each submission and suggest who
should approve it. The naive design is "the AI picks the approver" - the LLM
names a user and the workflow waits on that user. That inverts the control
boundary:

- Eligibility is a business fact (who may approve this step), recomputed from
  live role memberships and active delegations. Delegating it to a
  non-deterministic model makes eligibility stale, spoofable, or wrong.
- A model that can both *choose* the approver and be *shown* the approver set
  can be steered (prompt injection in the submission body) into narrowing
  review to a colluding actor.
- Every decision must be auditable and attributable; "the model suggested
  X" written as a plain decision would look like X approved.

At the same time the platform rule is explicit: business operations emit
domain events, and completion side effects (posting a journal entry, approving
a payroll run) must happen exactly once per workflow, from one authority.

## Decision

1. **The engine, not the AI, is the sole authority on eligibility.** At
   decision time `ApprovalEngine.decide` resolves the current step's assignee
   set from the live database (user/role memberships, plus any active
   delegation record) and requires the actor to be a member. The AI suggestion
   can only *name a member of that same set*; it is validated against it and
   never narrows the step. If the suggested approver is missing, unknown, or
   not in the set, the suggestion degrades to its audit record and the human
   flow is unaffected.

2. **The AI's influence is written down, once, as an audited transition.**
   The routing agent records a transition with actor_type `ai_suggestion`
   carrying recommendation, confidence, reasoning, model, and the suggested
   approver. Nothing the model said is reconstructed later: the read model
   surfaces the latest suggestion transition as an advisory panel. Every
   human/system decision is a separate append-only transition naming its real
   actor.

3. **Workflows are configured, versioned definitions; decisions are
   append-only state machines.** Definitions (ordered steps, assignee kinds,
   SLA, escalation) are seeded defaults that can be versioned; instances move
   `draft → in_review → step outcomes → completed/rejected` through
   `approval_workflow_transitions`. A decision is valid only on the instance's
   current pending step, by a member of that step's resolved assignee set.

4. **Completion is one dispatch from the engine.** The request-scoped
   resource port owns the mapping from resource type to the authoritative
   completion service: `journal_entry` → `FinanceService.complete_posting`,
   `payroll_run` → `PayrollService.complete_approval`. Those services keep
   their own audit + domain-event responsibility (e.g. `journal_entry_posted`).
   Unknown resource types fail closed with a conflict that rolls back the
   workflow, so a completed workflow can never lack a side effect. The DB
   session commits after the dispatch, making the workflow state and the
   resource mutation atomic.

5. **The API is a thin read-model + decide surface; eligibility is never
   re-implemented in routers.** Inbox/detail endpoints render
   query-service views; `POST /approval/inbox/{id}/decide` validates the body
   shape (decision + optional reason ≤ 1000) and delegates every workflow
   check to the engine. Routers only enforce a coarse module gate
   (`erp.finance.approve` / `erp.payroll.approve`); the engine re-checks step
   membership.

6. **The web surface presents AI suggestions as advisory only.** The inbox
   shows a suggestion chip and the review dialog a labeled panel ("AI routing
   suggestion — advisory only ... never bypasses a manual review"), with the
   model's recommendation, confidence, reasoning, and model name visible. All
   decision buttons (approve / request changes / reject) pass through the same
   decide endpoint.

## Consequences

### Positive

- One eligibility authority (the engine) - the same code path serves the API,
  the web UI, and future programmatic decisions; routers cannot drift into
  re-implementing membership checks.
- AI cannot shrink the approver set: the suggestion is validated against the
  resolved set, so prompt injection in a submission body cannot steer review
  toward a colluding actor.
- Fully auditable: suggestion content and every actor's decision are
  append-only transitions; completion side effects run through the owning
  feature's existing audit + event path.
- Extensible: a new resource type needs a definition seed plus a dispatch
  mapping and its completion service; the engine, transitions, inbox, and
  decide API stay unchanged.

### Negative

- The workflow definition is an explicit schema + seeded defaults, so a new
  approval shape costs a definition rather than ad-hoc code.
- Suggestions depend on the routing agent running on time; if the AI agent is
  down the workflow still proceeds manually (correctness over automation).
- Decisions and completion are one synchronous dispatch, which keeps a
  workflow's last step in the HTTP request lifetime (acceptable at this
  scale; a durable outbox is the future refactor if spin-off warrants it).

### Mitigations

- The engine's unit matrix (and the route-handler tests) encode the
  invariant "suggestion can never narrow the resolved assignee set".
- Delegation is stored with explicit `delegated_from`, surfaced to the
  reviewer, and still resolved inside the engine's assignee computation.
- The `ai_suggestion` transition guarantees the model's output survives as
  data even when the advisory UI is not rendered.