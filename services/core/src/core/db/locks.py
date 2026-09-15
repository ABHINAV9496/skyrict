"""Transaction-scoped advisory locks - serialize a code path per family key.

``advisory_family_lock`` acquires a session-level PostgreSQL advisory lock
(``pg_advisory_xact_lock``) keyed on a stable hash of the given parts. Use it
to make "read latest + write next" sections atomic under concurrency - e.g.
``max(version) + 1`` version allocation, where two concurrent creates for the
same family would otherwise both pick the same number and one would fail the
unique constraint (or write a silent duplicate version).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, bindparam, func, select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_MAX_SIGNED_63 = 0x7FFFFFFF_FFFFFFFF


def _family_key(*parts: object) -> int:
    """Stable, process-independent 63-bit key (negative bigint would error)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, ":".join(str(p) for p in parts)).int & _MAX_SIGNED_63


async def advisory_family_lock(session: AsyncSession, *parts: object) -> None:
    """Hold the advisory lock for ``*parts`` until the current transaction ends."""
    stmt = select(func.pg_advisory_xact_lock(bindparam("key", type_=BigInteger)))
    await session.execute(stmt, {"key": _family_key(*parts)})
