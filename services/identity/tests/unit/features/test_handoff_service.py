"""Unit tests for the handoff feature service (fake HandoffRepositoryPort)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from identity.core.audit_events import HANDOFF_ISSUED, HANDOFF_REDEEMED
from identity.core.security import hash_handoff_token
from identity.features.handoffs.service import HandoffService
from skyrict_common.exceptions import (
    HandoffTokenAlreadyUsedError,
    HandoffTokenExpiredError,
    HandoffTokenNotFoundError,
)

if TYPE_CHECKING:
    from identity.domain.entities import Handoff


class FakeAuditService:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    async def log(self, *, action: str, target: str, **kwargs: object) -> None:
        self.entries.append({"action": action, "target": target, **kwargs})


class FakeHandoffRepo:
    def __init__(self) -> None:
        self.handoffs: dict[uuid.UUID, Handoff] = {}
        self.consumed: list[uuid.UUID] = []

    async def create(self, handoff: Handoff) -> Handoff:
        if handoff.id is None:
            handoff.id = uuid.uuid4()
        self.handoffs[handoff.id] = handoff
        return handoff

    async def get_by_hash(self, token_hash: str) -> Handoff | None:
        for handoff in self.handoffs.values():
            if handoff.token_hash == token_hash:
                return handoff
        return None

    async def mark_consumed(self, handoff_id: str | uuid.UUID) -> Handoff | None:
        handoff = self.handoffs.get(uuid.UUID(str(handoff_id)))
        if handoff is None:
            return None
        self.consumed.append(uuid.UUID(str(handoff_id)))
        handoff.consumed_at = datetime.now(UTC)
        return handoff


def _service(repo: FakeHandoffRepo | None = None, audit: FakeAuditService | None = None):
    return HandoffService(repo or FakeHandoffRepo(), audit or FakeAuditService())


class TestIssue:
    async def test_returns_once_only_token_and_stores_only_its_hash(self) -> None:
        repo = FakeHandoffRepo()
        service = _service(repo)

        handoff, token = await service.issue(
            purpose="wizard",
            payload={"step": "verify-code", "email": "a@b.co"},
        )

        assert token
        assert len(token) >= 32
        assert handoff.id is not None
        assert handoff.token_hash == hash_handoff_token(token)
        assert handoff.purpose == "wizard"
        assert handoff.payload == {"step": "verify-code", "email": "a@b.co"}
        assert handoff.consumed_at is None
        assert handoff.token_hash != token

    async def test_carries_optional_tenant_and_actor(self) -> None:
        tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
        service = _service()

        handoff, _ = await service.issue(
            purpose="bff",
            tenant_id=tenant_id,
            created_by_user_id=user_id,
        )

        assert handoff.tenant_id == tenant_id
        assert handoff.created_by_user_id == user_id

    async def test_audits_handoff_issued(self) -> None:
        audit = FakeAuditService()
        service = _service(audit=audit)

        handoff, _ = await service.issue(purpose="wizard")

        assert audit.entries[0]["action"] == HANDOFF_ISSUED
        assert audit.entries[0]["target"] == f"handoff:{handoff.id}"
        assert audit.entries[0]["details"] == {"purpose": "wizard"}


class TestRedeem:
    async def test_redeems_single_use_token_and_returns_payload(self) -> None:
        repo = FakeHandoffRepo()
        service = _service(repo)
        handoff, token = await service.issue(
            purpose="wizard", payload={"step": "password", "email": "a@b.co"}
        )

        redeemed = await service.redeem(token=token)

        assert redeemed.id == handoff.id
        assert redeemed.payload == {"step": "password", "email": "a@b.co"}
        assert redeemed.consumed_at is not None
        assert repo.consumed == [handoff.id]

    async def test_audits_handoff_redeemed(self) -> None:
        audit = FakeAuditService()
        service = _service(audit=audit)
        handoff, token = await service.issue(purpose="wizard")

        await service.redeem(token=token)

        assert audit.entries[-1]["action"] == HANDOFF_REDEEMED
        assert audit.entries[-1]["target"] == f"handoff:{handoff.id}"

    async def test_reject_redeeming_the_same_token_twice(self) -> None:
        service = _service()
        _, token = await service.issue(purpose="wizard")

        await service.redeem(token=token)

        with pytest.raises(HandoffTokenAlreadyUsedError):
            await service.redeem(token=token)

    async def test_rejects_unknown_token(self) -> None:
        service = _service()

        with pytest.raises(HandoffTokenNotFoundError):
            await service.redeem(token="not-a-real-token")

    async def test_rejects_expired_token(self) -> None:
        repo = FakeHandoffRepo()
        service = _service(repo)
        handoff, token = await service.issue(purpose="wizard")
        handoff.expires_at = datetime.now(UTC) - timedelta(seconds=1)

        with pytest.raises(HandoffTokenExpiredError):
            await service.redeem(token=token)

    async def test_rejects_purpose_mismatch(self) -> None:
        service = _service()
        _, token = await service.issue(purpose="wizard")

        with pytest.raises(HandoffTokenNotFoundError):
            await service.redeem(token=token, purpose="bff")

    async def test_purpose_matches_when_requested(self) -> None:
        service = _service()
        _, token = await service.issue(purpose="wizard")

        redeemed = await service.redeem(token=token, purpose="wizard")

        assert redeemed.purpose == "wizard"
