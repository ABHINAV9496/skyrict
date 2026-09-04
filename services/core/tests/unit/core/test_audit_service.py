"""AuditService unit tests - port double, no database."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from core.core.audit_events import HR_LEAVE_APPROVED
from core.core.audit_service import AuditService

if TYPE_CHECKING:
    from core.domain.entities import AuditLogEntry


class FakeAuditRepository:
    """Records calls and returns canned entries."""

    def __init__(self) -> None:
        self.added: list[AuditLogEntry] = []
        self.listed: list[tuple[uuid.UUID, str | None, int]] = []

    async def add(self, entry: AuditLogEntry) -> AuditLogEntry:
        self.added.append(entry)
        return entry

    async def list(
        self, tenant_id: uuid.UUID, *, action: str | None = None, limit: int = 100
    ) -> list[AuditLogEntry]:
        self.listed.append((tenant_id, action, limit))
        return self.added

    async def get(self, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> AuditLogEntry | None:
        return None


class TestAuditService:
    async def test_log_delegates_with_known_action(self) -> None:
        repo = FakeAuditRepository()
        service = AuditService(repo)
        tenant = uuid.uuid4()
        actor = uuid.uuid4()

        entry = await service.log(
            action=HR_LEAVE_APPROVED,
            target="leave_request:1",
            tenant_id=tenant,
            user_id=actor,
            ip_address="127.0.0.1",
            user_agent="pytest",
            details={"days": 2},
        )

        assert repo.added == [entry]
        assert entry.tenant_id == tenant
        assert entry.actor_user_id == actor
        assert entry.action == HR_LEAVE_APPROVED
        assert entry.details == {"days": 2}

    async def test_log_rejects_unknown_action(self) -> None:
        service = AuditService(FakeAuditRepository())
        with pytest.raises(ValueError, match="unknown audit action"):
            await service.log(
                action="hr.leave.typo",
                target="leave_request:1",
                tenant_id=uuid.uuid4(),
            )

    async def test_feed_delegates(self) -> None:
        repo = FakeAuditRepository()
        service = AuditService(repo)
        tenant = uuid.uuid4()

        result = await service.feed(tenant, action=HR_LEAVE_APPROVED, limit=5)

        assert repo.listed == [(tenant, HR_LEAVE_APPROVED, 5)]
        assert result == []
