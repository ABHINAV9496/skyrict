"""Resolve a tenant identifier (slug or UUID) to its tenant UUID.

Both CLI composition roots (``ai_agent.ingest`` and ``ai_agent.rag_eval``) pin
the session's RLS context to one tenant BEFORE any statement runs, so they
share this resolver. Accepts a raw UUID directly (CI/ops convenience) or a
slug looked up in the shared ``tenants`` projection.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from ai_agent.core.exceptions import StartupError
from ai_agent.models.tenant import TenantModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_tenant_id(session: AsyncSession, tenant: str) -> uuid.UUID:
    """Resolve *tenant* (slug or UUID) to the tenants row id."""
    try:
        return uuid.UUID(tenant)
    except ValueError:
        pass
    result = await session.execute(select(TenantModel).where(TenantModel.slug == tenant))
    row = result.scalar_one_or_none()
    if row is None:
        raise StartupError(f"tenant not found: {tenant}")
    return row.id
