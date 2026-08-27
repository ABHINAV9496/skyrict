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
    }
)
"""The complete, closed vocabulary accepted by the AuditService."""
