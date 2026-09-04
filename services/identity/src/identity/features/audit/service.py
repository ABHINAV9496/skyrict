"""Audit service - log all security-relevant actions.

Owns the business rules (tenant-context gating). All persistence goes through
the ``AuditRepositoryPort``; no ORM models or sessions are touched here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from identity.core.tenant_context import TenantContext

if TYPE_CHECKING:
    from identity.domain.entities import AuditLog
    from identity.features.audit.ports import AuditRepositoryPort


class AuditService:
    """Logs security-relevant actions for compliance and debugging."""

    def __init__(self, audit_repo: AuditRepositoryPort) -> None:
        self.audit_repo = audit_repo

    async def log(
        self,
        *,
        action: str,
        target: str,
        user_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Create an audit log entry for the current tenant.

        ``target`` is a ``"<type>:<id>"`` string (e.g. ``"user:3f4..."``) so
        the audit log stays a single source of truth for what changed.

        ``tenant_id`` overrides the resolved request tenant - used by flows
        that run without a routed tenant (self-service registration).
        """
        resolved_tenant = tenant_id or TenantContext.get_optional()
        if not resolved_tenant:
            return  # Skip audit if no tenant context (e.g., during startup)

        await self.audit_repo.log(
            tenant_id=resolved_tenant,
            user_id=user_id,
            action=action,
            target=target,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def get_user_audit_log(
        self, user_id: str, *, offset: int = 0, limit: int = 50
    ) -> list[AuditLog]:
        """Retrieve audit entries for a user."""
        return await self.audit_repo.get_by_user(user_id, offset=offset, limit=limit)
