"""SequenceService unit tests - port double, no database."""

from __future__ import annotations

import uuid

from core.core.sequence_service import SequenceService
from core.domain.entities import ErpSequence


class FakeSequenceRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, uuid.UUID, str]] = []
        self._current = 0

    async def next_value(self, tenant_id: uuid.UUID, entity: str) -> int:
        self.calls.append(("next", tenant_id, entity))
        self._current += 1
        return self._current

    async def get(self, tenant_id: uuid.UUID, entity: str) -> ErpSequence | None:
        self.calls.append(("get", tenant_id, entity))
        return ErpSequence(tenant_id=tenant_id, entity=entity, current_value=self._current)


class TestSequenceService:
    async def test_next_delegates(self) -> None:
        repo = FakeSequenceRepository()
        service = SequenceService(repo)
        tenant = uuid.uuid4()

        value = await service.next(tenant_id=tenant, entity="invoice")

        assert value == 1
        assert repo.calls == [("next", tenant, "invoice")]

    async def test_current_delegates(self) -> None:
        repo = FakeSequenceRepository()
        service = SequenceService(repo)
        tenant = uuid.uuid4()

        seq = await service.current(tenant_id=tenant, entity="invoice")

        assert seq is not None and seq.entity == "invoice"
        assert repo.calls == [("get", tenant, "invoice")]
