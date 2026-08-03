"""SQLAlchemy repository bases.

- :class:`SqlRepository`: thin base for feature repository adapters. Holds the
  request session; concrete repositories own their persistence methods and
  map ORM models to/from domain entities. The request-scoped commit lives in
  the ``get_db`` dependency; ``commit`` here is for bootstrap scripts only.
- :class:`BaseRepository`: generic CRUD over a single ORM model, used by
  bootstrap tooling (e.g. role seeding) where no feature repository exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import ColumnElement, select

from identity.models.base import Base

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlRepository:
    """Minimal SQLAlchemy-backed repository base.

    Feature repositories subclass this for the shared session wiring. They
    expose persistence methods that accept and return domain entities, so
    SQLAlchemy never leaks above the repository layer.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        """Commit the current transaction (bootstrap scripts only)."""
        await self.session.commit()


class BaseRepository[M: Base]:
    """Async CRUD operations for a single ORM model."""

    model: ClassVar[type[M]]

    def __init__(self, session: AsyncSession, *, model: type[M] | None = None) -> None:
        self.session = session
        if model is not None:
            type(self).model = model

    async def create(self, entry: M) -> M:
        """Persist a new instance and return it."""
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    async def get_by_id(self, entity_id: Any) -> M | None:
        """Fetch a single instance by primary key."""
        return await self.session.get(self.model, entity_id)

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        filters: list[ColumnElement[bool]] | None = None,
    ) -> list[M]:
        """List instances, optionally filtered, with pagination."""
        stmt = select(self.model)
        if filters:
            stmt = stmt.where(*filters)
        result = await self.session.execute(stmt.offset(offset).limit(limit))
        return list(result.scalars().all())

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.session.commit()
