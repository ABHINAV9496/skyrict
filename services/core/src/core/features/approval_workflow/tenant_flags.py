"""Per-tenant approval engine feature flags (SKY-92).

Flags live in the generic ``erp_tenant_settings`` store (values are TEXT;
JSON booleans/numbers are stored as their string representations). Every flag
defaults to OFF when the key is absent so existing ERP flows (direct
posting, direct payroll approval) remain unchanged until a tenant opts in.

Flag keys:

- ``approval_engine_enabled`` - master switch: when OFF (default) the
  approval engine is inert everywhere.
- ``je_approval_engine`` - route journal-entry posting through the engine.
- ``payroll_approval_engine`` - route payroll run approval through the engine.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.finance.models.tenant_setting import ErpTenantSettingModel

APPROVAL_ENGINE_ENABLED = "approval_engine_enabled"
JE_APPROVAL_ENGINE = "je_approval_engine"
PAYROLL_APPROVAL_ENGINE = "payroll_approval_engine"

_ALL_KEYS = (APPROVAL_ENGINE_ENABLED, JE_APPROVAL_ENGINE, PAYROLL_APPROVAL_ENGINE)


async def get_tenant_flag(session: AsyncSession, tenant_id: uuid.UUID, key: str) -> bool:
    """Read one engine flag; absent key means OFF."""
    result = await session.execute(
        select(ErpTenantSettingModel).where(
            ErpTenantSettingModel.tenant_id == tenant_id,
            ErpTenantSettingModel.key == key,
        )
    )
    model = result.scalar_one_or_none()
    return model.value.strip().lower() in ("true", "1", "yes", "on") if model else False


async def approval_engine_enabled(session: AsyncSession, tenant_id: uuid.UUID) -> bool:
    return await get_tenant_flag(session, tenant_id, APPROVAL_ENGINE_ENABLED)


async def je_approval_engine_enabled(session: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """JE routing requires both the master switch and the JE-specific flag."""
    if not await approval_engine_enabled(session, tenant_id):
        return False
    return await get_tenant_flag(session, tenant_id, JE_APPROVAL_ENGINE)


async def payroll_approval_engine_enabled(session: AsyncSession, tenant_id: uuid.UUID) -> bool:
    if not await approval_engine_enabled(session, tenant_id):
        return False
    return await get_tenant_flag(session, tenant_id, PAYROLL_APPROVAL_ENGINE)
