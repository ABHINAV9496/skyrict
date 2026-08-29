"""Tenant-scoped access to ai_restock_settings (INV-AI-002).

``get_or_create_default`` is the scan bootstrap: the restock service needs one
settings row per tenant and works when none exists. Rows are one-per-tenant and
RLS-scoped; the repository intentionally hides the ORM model from the service.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from ai_agent.models.ai_restock_settings import AiRestockSettingsModel

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


# Mirrors the migration server_defaults so a missing row behaves like the
# defaults (spec §3.2 conservative defaults: lead time 7d, safety factor 1.0,
# v2 off until a tenant opts in).
_DEFAULT_LEAD_TIME_DAYS = Decimal("7.00")
_DEFAULT_SAFETY_FACTOR = Decimal("1.000")
_DEFAULT_SENSITIVITY = Decimal("0.500")
_DEFAULT_FP_THRESHOLD = Decimal("0.500")


@dataclass(frozen=True, slots=True)
class RestockSettings:
    """Per-tenant settings snapshot (value object, not the ORM row)."""

    tenant_id: uuid.UUID
    lead_time_days: Decimal
    safety_factor: Decimal
    v2_enabled: bool
    sensitivity: Decimal
    fp_threshold: Decimal
    email_alerts_enabled: bool


class SettingsRepository:
    """Persistence for per-tenant AI settings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, *, tenant_id: uuid.UUID) -> RestockSettings | None:
        """Return the tenant's settings, or None when no row exists."""
        row = await self._get_row(tenant_id=tenant_id)
        if row is None:
            return None
        return _to_settings(row)

    async def get_or_create_default(self, *, tenant_id: uuid.UUID) -> RestockSettings:
        """Return existing settings or create + flush a defaults row."""
        return _to_settings(await self._get_or_create_row(tenant_id=tenant_id))

    async def update(
        self,
        *,
        tenant_id: uuid.UUID,
        lead_time_days: Decimal | None = None,
        safety_factor: Decimal | None = None,
        v2_enabled: bool | None = None,
        sensitivity: Decimal | None = None,
        fp_threshold: Decimal | None = None,
        email_alerts_enabled: bool | None = None,
    ) -> RestockSettings:
        """Apply a partial settings patch (None fields untouched) in place.

        Creates the defaults row first when the tenant has none, so PATCH is
        idempotent from a cold start. Range/positivity validation mirrors the
        DB CHECK constraints here at the repository seam and is re-enforced
        by the constraints themselves in Postgres.
        """
        row = await self._get_or_create_row(tenant_id=tenant_id)
        if lead_time_days is not None:
            row.lead_time_days = lead_time_days
        if safety_factor is not None:
            row.safety_factor = safety_factor
        if v2_enabled is not None:
            row.v2_enabled = v2_enabled
        if sensitivity is not None:
            row.sensitivity = sensitivity
        if fp_threshold is not None:
            row.fp_threshold = fp_threshold
        if email_alerts_enabled is not None:
            row.email_alerts_enabled = email_alerts_enabled
        await self.session.flush()
        return _to_settings(row)

    async def _get_or_create_row(self, *, tenant_id: uuid.UUID) -> AiRestockSettingsModel:
        row = await self._get_row(tenant_id=tenant_id)
        if row is not None:
            return row
        row = AiRestockSettingsModel(
            tenant_id=tenant_id,
            lead_time_days=_DEFAULT_LEAD_TIME_DAYS,
            safety_factor=_DEFAULT_SAFETY_FACTOR,
            v2_enabled=False,
            sensitivity=_DEFAULT_SENSITIVITY,
            fp_threshold=_DEFAULT_FP_THRESHOLD,
            email_alerts_enabled=False,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _get_row(self, *, tenant_id: uuid.UUID) -> AiRestockSettingsModel | None:
        result = await self.session.execute(
            select(AiRestockSettingsModel).where(AiRestockSettingsModel.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()


def _to_settings(row: AiRestockSettingsModel) -> RestockSettings:
    return RestockSettings(
        tenant_id=row.tenant_id,
        lead_time_days=Decimal(str(row.lead_time_days)),
        safety_factor=Decimal(str(row.safety_factor)),
        v2_enabled=row.v2_enabled,
        sensitivity=Decimal(str(row.sensitivity)),
        fp_threshold=Decimal(str(row.fp_threshold)),
        email_alerts_enabled=row.email_alerts_enabled,
    )
