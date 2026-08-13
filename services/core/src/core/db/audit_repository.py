"""Audit repository — writes finance state changes into the shared audit trail.

Implements (structurally) the ``AuditSink`` port declared in
``core.features.finance.ports`` without importing it — core.db may not depend
on feature modules (import-linter), and the service depends on the Protocol,
so the duck-typed boundary keeps both contracts intact.

Rows land in the SAME request transaction as the finance mutation: the
``get_db`` teardown commit publishes audit + business change atomically. The
``hash`` / ``prev_hash`` chain and the append-only guard are applied by
identity's DB triggers, so this repository never writes those columns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.db.repository import SqlRepository
from core.models.audit_log import AuditLogModel

if TYPE_CHECKING:
    import uuid


class AuditRepository(SqlRepository):
    """Append-only audit writes for core (ERP) state changes."""

    async def log(
        self,
        *,
        tenant_id: str | uuid.UUID,
        user_id: str | uuid.UUID | None = None,
        action: str,
        target: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Create an audit log entry in the current request transaction.

        ``target`` is a ``"<type>:<id>"`` string (e.g. ``"journal_entry:3f4..."``)
        so the audit log stays a single source of truth for what changed.
        """
        model = AuditLogModel(
            tenant_id=tenant_id,
            actor_user_id=user_id,
            action=action,
            target=target,
            details=details,
        )
        self.session.add(model)
        await self.session.flush()
