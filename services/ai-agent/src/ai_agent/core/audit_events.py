"""Audit event catalog for AI actions - Appendix B of
``docs/modules/skyrict-ai/inventory-ai-features.md``.

Every audit write MUST use one of these constants for ``action``; the
AuditService rejects anything else so the vocabulary cannot drift between
call sites and the spec. Values are dotted lowercase strings namespaced under
``ai.``.
"""

from __future__ import annotations

AI_QUERY_EXECUTED = "ai.query.executed"
"""Every natural-language query execution (spec §2: feature 1)."""

AI_SUGGESTION_CREATED = "ai.suggestion.created"
"""The daily scan (or on-demand analysis) created a restock suggestion."""

AI_SUGGESTION_APPROVED = "ai.suggestion.approved"
"""A human approved a restock suggestion."""

AI_SUGGESTION_REJECTED = "ai.suggestion.rejected"
"""A human rejected a restock suggestion."""

AI_ANOMALY_DETECTED = "ai.anomaly.detected"
"""The detector created an anomaly record."""

AI_ANOMALY_RESOLVED = "ai.anomaly.resolved"
"""A human resolved an anomaly (real issue, handled)."""

AI_ANOMALY_DISMISSED = "ai.anomaly.dismissed"
"""A human marked an anomaly as a false positive."""

AI_ANOMALY_ESCALATED = "ai.anomaly.escalated"
"""A human escalated an anomaly to an admin (spec §4.4 workflow).

Not in the spec's Appendix B table - the workflow section defines
escalation but the appendix omits its event. Added here so escalations
are never mis-audited as dismissals; flagged for the next ADR pass.
"""

AI_NARRATOR_GENERATED = "ai.narrator.generated"
"""The daily (or on-demand) cross-module digest was produced (SKY-63)."""

AI_NARRATOR_REFRESHED = "ai.narrator.refreshed"
"""A human force-refreshed the cross-module digest (SKY-63)."""

AI_HR_COPILOT_EXCHANGE = "ai.hr.copilot.exchange"
"""An HR Copilot chat exchange was answered (spec §9: feature 5)."""

AI_AGENT_INTERRUPT_APPROVED = "ai.agent.interrupt.approved"
"""A human approved an agent's pending interrupt (SKY-59 HITL ledger)."""

AI_AGENT_INTERRUPT_DENIED = "ai.agent.interrupt.denied"
"""A human denied an agent's pending interrupt (SKY-59 HITL ledger)."""

AI_AGENT_INTERRUPT_EXPIRED = "ai.agent.interrupt.expired"
"""A pending agent interrupt auto-denied on lazy expiry (SKY-59, 24h)."""

AI_LEAD_SCORED = "ai.crm.lead.scored"
"""The CRM AI service produced a deterministic lead score (SKY-61)."""

AI_DEAL_HEALTH_ASSESSED = "ai.crm.deal.health"
"""The CRM AI service assessed an opportunity's deal health (SKY-61)."""

AI_FOLLOW_UP_GENERATED = "ai.crm.follow_up.generated"
"""The hourly scan generated a CRM follow-up suggestion (SKY-61)."""

AI_FOLLOW_UP_APPLIED = "ai.crm.follow_up.applied"
"""A human one-click-applied a follow-up, creating a CRM activity (SKY-61)."""

AI_FOLLOW_UP_DISMISSED = "ai.crm.follow_up.dismissed"
"""A human dismissed a follow-up suggestion (SKY-61)."""

AI_L3_PAYROLL_COST_GENERATED = "ai.l3.payroll_cost.generated"
"""The L3 payroll-cost narrative was generated."""

AI_L3_LEAVE_PAY_CORRELATED = "ai.l3.leave_pay.correlated"
"""The L3 leave-pay-correlation narrative was generated."""

AI_L3_COMPLIANCE_DIGESTED = "ai.l3.compliance.digested"
"""The L3 compliance-digest narrative was generated."""

AI_L3_ACCESSED = "ai.l3.accessed"
"""An L3 narrative was retrieved from cache (every read is audited)."""

AI_L3_ABSTAINED = "ai.l3.abstained"
"""The L3 narrator abstained (no material activity, LLM disabled, or unusable output)."""
AI_TRANSCRIPT_ANALYZED = "ai.crm.transcript.analyzed"
"""The CRM AI service analyzed a call/meeting transcript (SKY-91)."""

AI_CRM_ANOMALY_DETECTED = "ai.crm.anomaly.detected"
"""The CRM pipeline anomaly scan detected an anomaly on an open deal (SKY-91)."""

AI_CRM_ANOMALY_RESOLVED = "ai.crm.anomaly.resolved"
"""A human resolved a CRM anomaly (real issue, acted on)."""

AI_CRM_ANOMALY_DISMISSED = "ai.crm.anomaly.dismissed"
"""A human dismissed a CRM anomaly as a false positive."""

AI_REPORT_GENERATED = "ai.report.generated"
"""The NL report builder generated (and ran) a report from free text (SKY-80)."""

AI_REPORT_SAVED = "ai.report.saved"
"""The NL report builder persisted a generated report as a saved definition (SKY-80)."""

AI_L4_SCENARIO_CREATED = "ai.l4.scenario.created"
"""The L4 what-if planner saved a named scenario with a frozen projection (SKY-93)."""

AI_L4_SCENARIO_VIEWED = "ai.l4.scenario.viewed"
"""A user opened one frozen L4 what-if scenario (SKY-93, Commit 4).

Read-auditing scenario detail keeps the "who opened which planning scenario"
trail required to review who saw a forecast before it is exported to Finance.
"""

AI_L4_SCENARIO_COMPARED = "ai.l4.scenario.compared"
"""A user compared up to 3 frozen L4 what-if scenarios side-by-side (SKY-93, Commit 4).

Compare is read-only, but it is the highest-value planning read (multiple
forecasts at once), so it gets its own event rather than being lumped with
plain views.
"""

AI_COACHING_SUGGESTION_CREATED = "ai.coaching.suggestion.created"
"""The Sales Coach agent produced a coaching suggestion (SKY-90)."""

AI_COACHING_SUGGESTION_VIEWED = "ai.coaching.suggestion.viewed"
"""A manager viewed a coaching suggestion (SKY-90)."""

AI_COACHING_SUGGESTION_ACCEPTED = "ai.coaching.suggestion.accepted"
"""A manager accepted a coaching suggestion (SKY-90)."""

AI_COACHING_SUGGESTION_DISMISSED = "ai.coaching.suggestion.dismissed"
"""A manager dismissed a coaching suggestion (SKY-90)."""

AI_GUARDIAN_REPORT_GENERATED = "ai.guardian.report.generated"
"""The Audit Guardian generated a weekly integrity report (SKY-90)."""

AI_GUARDIAN_EVENT_FLAGGED = "ai.guardian.event.flagged"
"""The Audit Guardian flagged a suspicious audit event (SKY-90)."""

ALL_AI_AUDIT_EVENTS = frozenset(
    {
        AI_QUERY_EXECUTED,
        AI_SUGGESTION_CREATED,
        AI_SUGGESTION_APPROVED,
        AI_SUGGESTION_REJECTED,
        AI_ANOMALY_DETECTED,
        AI_ANOMALY_RESOLVED,
        AI_ANOMALY_DISMISSED,
        AI_ANOMALY_ESCALATED,
        AI_NARRATOR_GENERATED,
        AI_NARRATOR_REFRESHED,
        AI_HR_COPILOT_EXCHANGE,
        AI_AGENT_INTERRUPT_APPROVED,
        AI_AGENT_INTERRUPT_DENIED,
        AI_AGENT_INTERRUPT_EXPIRED,
        AI_LEAD_SCORED,
        AI_DEAL_HEALTH_ASSESSED,
        AI_FOLLOW_UP_GENERATED,
        AI_FOLLOW_UP_APPLIED,
        AI_FOLLOW_UP_DISMISSED,
        AI_L3_PAYROLL_COST_GENERATED,
        AI_L3_LEAVE_PAY_CORRELATED,
        AI_L3_COMPLIANCE_DIGESTED,
        AI_L3_ACCESSED,
        AI_L3_ABSTAINED,
        AI_REPORT_GENERATED,
        AI_REPORT_SAVED,
        AI_TRANSCRIPT_ANALYZED,
        AI_CRM_ANOMALY_DETECTED,
        AI_CRM_ANOMALY_RESOLVED,
        AI_L4_SCENARIO_CREATED,
        AI_L4_SCENARIO_VIEWED,
        AI_L4_SCENARIO_COMPARED,
        AI_CRM_ANOMALY_DISMISSED,
        AI_COACHING_SUGGESTION_CREATED,
        AI_COACHING_SUGGESTION_VIEWED,
        AI_COACHING_SUGGESTION_ACCEPTED,
        AI_COACHING_SUGGESTION_DISMISSED,
        AI_GUARDIAN_REPORT_GENERATED,
        AI_GUARDIAN_EVENT_FLAGGED,
    }
)
"""The complete, closed vocabulary accepted by the AuditService."""
