"""Async database engine and session factory — the ONE place DB connections are created.

Sets Row-Level Security context on every transaction: when the request-scoped
TenantContext is populated, ``app.current_tenant_id`` is set via
``set_config(..., true)`` (transaction-local) so Postgres RLS policies
(``public.current_tenant_id()``) bound every query to the current tenant.

The middleware's pre-context tenant lookup (and any bootstrap/seed work that
runs without a request) does not set the GUC, so it stays unconstrained.

Event wiring follows the SQLAlchemy asyncio docs: an event is attached to the
*sync* ``sessionmaker`` that backs the ``async_sessionmaker`` (via
``sync_session_class``); ``after_begin`` then fires on the sync ``Connection``
inside the greenlet bridge, before any statement of the transaction runs.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from identity.core.config import settings
from identity.core.tenant_context import TenantContext

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

_sync_session_factory = sessionmaker(
    engine.sync_engine,
    class_=Session,
    expire_on_commit=False,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    sync_session_class=_sync_session_factory,
)


@event.listens_for(_sync_session_factory, "after_begin")
def _set_rls_tenant_context(_session: Session, _transaction: object, connection: object) -> None:
    """Set the RLS tenant on every new transaction when a tenant is in scope."""
    tenant_id = TenantContext.get_optional()
    if tenant_id is None:
        return
    connection.exec_driver_sql(  # type: ignore[attr-defined]
        "SELECT set_config('app.current_tenant_id', $1, true)",
        (tenant_id,),
    )


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields an async session."""
    async with async_session_factory() as session:
        yield session
