"""Audit service - the shared facade for writing AI audit events.

Every AI action goes through :meth:`AuditService.log`; the repository appends
to ``ai_audit_log`` (spec §5.3). Producers must use the constants from
:mod:`ai_agent.core.audit_events` for ``action`` - unknown values are rejected
here so the vocabulary cannot drift from the spec's Appendix B.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ai_agent.core.audit_events import ALL_AI_AUDIT_EVENTS

if TYPE_CHECKING:
    import uuid

    from ai_agent.models.ai_audit_log import AiAuditLogModel


class AiAuditRepositoryPort(Protocol):
    """Structural port satisfied by :class:`AiAuditLogRepository`."""

    async def add(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        user_id: uuid.UUID | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        model_used: str | None = None,
        latency_ms: int | None = None,
    ) -> AiAuditLogModel: ...


class AuditService:
    """Validate-and-delegate facade over the audit repository."""

    def __init__(self, repository: AiAuditRepositoryPort) -> None:
        self._repository = repository

    async def log(
        self,
        *,
        action: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        model_used: str | None = None,
        latency_ms: int | None = None,
    ) -> AiAuditLogModel:
        """Append one immutable audit event for an executed AI action.

        Raises:
            ValueError: If ``action`` is not in the Appendix B vocabulary.
        """
        if action not in ALL_AI_AUDIT_EVENTS:
            raise ValueError(
                f"unknown audit action {action!r}; use ai_agent.core.audit_events constants"
            )
        return await self._repository.add(
            tenant_id=tenant_id,
            action=action,
            user_id=user_id,
            input_payload=input_payload,
            output_payload=output_payload,
            model_used=model_used,
            latency_ms=latency_ms,
        )
