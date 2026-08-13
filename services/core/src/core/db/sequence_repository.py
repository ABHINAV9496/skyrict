"""Sequence repository — tenant-scoped monotonic document counters.

``next_value`` claims the next number with a single row-locking
``UPDATE ... SET current_value = current_value + 1 ... RETURNING``, so
consecutive numbers are race-safe and never reused. First use inserts the
counter row (``current_value = 0``) via ``ON CONFLICT DO NOTHING`` so two
concurrent first-uses can't duplicate the row, then retries the UPDATE.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.db.repository import SqlRepository
from core.domain.entities import ErpSequence
from core.models.erp_sequence import ErpSequenceModel


def _sequence_from_orm(model: ErpSequenceModel) -> ErpSequence:
    return ErpSequence(
        id=model.id,
        tenant_id=model.tenant_id,
        entity=model.entity,
        current_value=model.current_value,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SequenceRepository(SqlRepository):
    """Concrete SQLAlchemy implementation of :class:`SequenceRepositoryPort`."""

    async def next_value(self, tenant_id: uuid.UUID, entity: str) -> int:
        """Claim the next number for ``entity``, inserting the counter on first use."""
        stmt = (
            update(ErpSequenceModel)
            .where(
                ErpSequenceModel.tenant_id == tenant_id,
                ErpSequenceModel.entity == entity,
            )
            .values(current_value=ErpSequenceModel.current_value + 1)
            .returning(ErpSequenceModel.current_value)
        )
        result = await self.session.execute(stmt)
        value = result.scalar_one_or_none()
        if value is None:
            await self.session.execute(
                pg_insert(ErpSequenceModel)
                .values(tenant_id=tenant_id, entity=entity)
                .on_conflict_do_nothing(index_elements=["tenant_id", "entity"])
            )
            result = await self.session.execute(stmt)
            value = result.scalar_one()
        return int(value)

    async def get(self, tenant_id: uuid.UUID, entity: str) -> ErpSequence | None:
        stmt = select(ErpSequenceModel).where(
            ErpSequenceModel.tenant_id == tenant_id,
            ErpSequenceModel.entity == entity,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _sequence_from_orm(model) if model is not None else None
