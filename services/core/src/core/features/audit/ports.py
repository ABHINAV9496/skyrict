"""Audit repository port - the persistence contract the audit service depends on.

Ports abstract persistence only (never business rules). SQLAlchemy lives in the
concrete implementation ``core.features.audit.repository``.
"""

from __future__ import annotations

from typing import Any, Protocol


class AuditRepositoryPort(Protocol):
    """Persistence operations for the append-only audit log."""

    async def log(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
        action: str,
        target: str,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None: ...
