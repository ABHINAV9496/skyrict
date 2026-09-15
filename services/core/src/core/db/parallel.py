"""Concurrent read helpers - the ONLY way independent queries actually overlap.

Empirical note (SKY-99): ``asyncio.gather`` over a SINGLE
:class:`AsyncSession` provides no speedup - SQLAlchemy serializes concurrent
``execute()`` calls on the one connection the session binds per transaction
(measured ~1.0x). Real (and verified ~N x) parallelism requires one pooled
connection per query, i.e. one short-lived session per job.

These helper functions run independent read-only aggregate jobs concurrently,
each opening its OWN session from the shared async session factory. Because
the sessions are distinct, the RLS ``app.current_tenant_id`` GUC is set
explicitly on each session before its queries run (mirroring the
``after_begin`` listener on the primary factory) so every job stays bound to
the caller's tenant even when no request TenantContext is in scope (tests,
background tasks).

Each job receives a forked repository bound to its own session. Forks are
read-only and rolled back on close; the request's primary session is never
touched, so autocommit/event-buffer behaviour is unchanged.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from core.db.session import async_session_factory

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession


async def parallel_reads(
    tenant_id: object,
    jobs: list[Callable[[AsyncSession], Awaitable[Any]]],
) -> list[Any]:
    """Run ``jobs`` concurrently, each on its own tenant-scoped pooled session.

    ``tenant_id`` is set as the RLS GUC on every forked session before its job
    runs, so each job can only ever see that tenant's rows (defense in depth
    on top of the explicit ``tenant_id`` filters the repositories pass to
    every query).

    Returns the job results in input order. If any job raises, ``asyncio.gather``
    cancels the siblings and every forked session is closed by its own
    ``finally`` - nothing leaks connections.
    """

    async def _run(job: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        session = async_session_factory()
        try:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            return await job(session)
        finally:
            await session.close()

    return await asyncio.gather(*(_run(job) for job in jobs))
