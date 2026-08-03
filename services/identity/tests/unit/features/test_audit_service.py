"""Unit tests for the audit feature service (fake AuditRepositoryPort)."""

from __future__ import annotations

import uuid

import pytest

from identity.core.tenant_context import TenantContext
from identity.domain.entities import AuditLog
from identity.features.audit.service import AuditService


class FakeAuditRepo:
    """In-memory AuditRepositoryPort double."""

    def __init__(self) -> None:
        self.entries: list[AuditLog] = []
        self.logged: list[dict[str, object]] = []

    async def log(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
        action: str,
        target: str,
        details: dict[str, object] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            tenant_id=uuid.UUID(tenant_id),
            actor_user_id=uuid.UUID(user_id) if user_id else None,
            action=action,
            target=target,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.entries.append(entry)
        self.logged.append(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "action": action,
                "target": target,
            }
        )
        return entry

    async def get_by_user(
        self, user_id: str | uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> list[AuditLog]:
        uid = uuid.UUID(str(user_id))
        return [entry for entry in self.entries if entry.actor_user_id == uid]


@pytest.fixture
def tenant_ctx() -> str:
    tenant_id = str(uuid.uuid4())
    TenantContext.set(tenant_id)
    yield tenant_id
    TenantContext.reset()


class TestLog:
    async def test_skips_when_no_tenant_context(self) -> None:
        repo = FakeAuditRepo()
        service = AuditService(repo)

        await service.log(action="auth.login.success", target="user:1")

        assert repo.logged == []

    async def test_records_when_tenant_context_is_set(self, tenant_ctx: str) -> None:
        repo = FakeAuditRepo()
        service = AuditService(repo)
        user_id = str(uuid.uuid4())

        await service.log(
            action="auth.login.success",
            target="user:1",
            user_id=user_id,
            ip_address="127.0.0.1",
            user_agent="pytest-agent",
        )

        assert repo.logged == [
            {
                "tenant_id": tenant_ctx,
                "user_id": user_id,
                "action": "auth.login.success",
                "target": "user:1",
            }
        ]


class TestGetUserAuditLog:
    async def test_delegates_to_repo(self, tenant_ctx: str) -> None:
        repo = FakeAuditRepo()
        service = AuditService(repo)
        user_id = str(uuid.uuid4())
        await service.log(action="auth.login.success", target="user:1", user_id=user_id)

        entries = await service.get_user_audit_log(user_id)

        assert len(entries) == 1
        assert entries[0].action == "auth.login.success"
