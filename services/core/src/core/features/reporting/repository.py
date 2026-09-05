"""Repository for dashboard layout CRUD and report definitions/snapshots (RPT-DATA-001)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.reporting.models.dashboard import ErpDashboardModel
from core.features.reporting.models.report_definition import ErpReportDefinitionModel
from core.features.reporting.models.report_snapshot import ErpReportSnapshotModel
from core.features.reporting.models.user_layout import UserDashboardLayoutModel
from core.features.reporting.models.widget_event import WidgetEventModel

logger = structlog.get_logger("core.reporting.repository")


class DashboardRepository:
    """Data-access layer for dashboard layouts and widget telemetry."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Tenant default dashboard --------------------------------------------

    async def get_tenant_default(self, *, tenant_id: uuid.UUID) -> ErpDashboardModel | None:
        """Return the tenant's default dashboard, or None."""
        result = await self._session.execute(
            select(ErpDashboardModel).where(
                ErpDashboardModel.tenant_id == tenant_id,
                ErpDashboardModel.tenant_default.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def upsert_tenant_default(
        self,
        *,
        tenant_id: uuid.UUID,
        title: str,
        layout: list[dict[str, Any]],
    ) -> ErpDashboardModel:
        """Create or update the tenant's default dashboard."""
        existing = await self.get_tenant_default(tenant_id=tenant_id)
        if existing is not None:
            existing.title = title
            existing.layout = layout
            await self._session.flush()
            return existing

        dashboard = ErpDashboardModel(
            tenant_id=tenant_id,
            title=title,
            layout=layout,
            tenant_default=True,
        )
        self._session.add(dashboard)
        await self._session.flush()
        return dashboard

    # --- User layout ---------------------------------------------------------

    async def get_user_layout(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> UserDashboardLayoutModel | None:
        """Return the user's personal layout override, or None."""
        result = await self._session.execute(
            select(UserDashboardLayoutModel).where(
                UserDashboardLayoutModel.tenant_id == tenant_id,
                UserDashboardLayoutModel.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_user_layout(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        layout: list[dict[str, Any]],
    ) -> UserDashboardLayoutModel:
        """Create or update the user's personal layout."""
        existing = await self.get_user_layout(tenant_id=tenant_id, user_id=user_id)
        if existing is not None:
            existing.layout = layout
            await self._session.flush()
            return existing

        user_layout = UserDashboardLayoutModel(
            tenant_id=tenant_id,
            user_id=user_id,
            layout=layout,
        )
        self._session.add(user_layout)
        await self._session.flush()
        return user_layout

    async def delete_user_layout(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Delete the user's personal layout (reset to default). Returns True if deleted."""
        existing = await self.get_user_layout(tenant_id=tenant_id, user_id=user_id)
        if existing is None:
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

    # --- Widget events -------------------------------------------------------

    async def record_widget_events(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        events: list[dict[str, Any]],
    ) -> int:
        """Insert widget interaction events. Returns the count of inserted rows."""
        if not events:
            return 0

        rows = [
            WidgetEventModel(
                tenant_id=tenant_id,
                user_id=user_id,
                widget_id=ev["widget_id"],
                event=ev["event"],
            )
            for ev in events
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return len(rows)

    async def count_widget_events(
        self,
        *,
        tenant_id: uuid.UUID,
        widget_id: str,
    ) -> int:
        """Count total events for a widget in a tenant (for AI gating)."""
        from sqlalchemy import func as sqlfunc

        result = await self._session.execute(
            select(sqlfunc.count())
            .select_from(WidgetEventModel)
            .where(
                WidgetEventModel.tenant_id == tenant_id,
                WidgetEventModel.widget_id == widget_id,
            )
        )
        return result.scalar_one() or 0

    async def get_widget_event_summary(
        self,
        *,
        tenant_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Return per-widget event counts for the AI suggestion engine.

        Only returns widgets with >= 1 event.  The AI suggestion endpoint
        uses the 50-event threshold separately.
        """
        from sqlalchemy import func as sqlfunc

        result = await self._session.execute(
            select(
                WidgetEventModel.widget_id,
                sqlfunc.count().label("total_events"),
                sqlfunc.count(WidgetEventModel.event.distinct()).label("distinct_events"),
            )
            .where(WidgetEventModel.tenant_id == tenant_id)
            .group_by(WidgetEventModel.widget_id)
            .order_by(sqlfunc.count().desc())
        )
        return [
            {
                "widget_id": row.widget_id,
                "total_events": row.total_events,
                "distinct_events": row.distinct_events,
            }
            for row in result
        ]


class ReportRepository:
    """Data-access layer for report definitions and snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active_definitions(
        self, *, tenant_id: uuid.UUID
    ) -> list[ErpReportDefinitionModel]:
        """Return the tenant's active definitions ordered by module then slug."""
        result = await self._session.execute(
            select(ErpReportDefinitionModel)
            .where(
                ErpReportDefinitionModel.tenant_id == tenant_id,
                ErpReportDefinitionModel.is_active.is_(True),
            )
            .order_by(ErpReportDefinitionModel.module, ErpReportDefinitionModel.slug)
        )
        return list(result.scalars().all())

    async def get_definition(
        self,
        *,
        tenant_id: uuid.UUID,
        slug: str,
    ) -> ErpReportDefinitionModel | None:
        """Return one active definition by slug, or None."""
        result = await self._session.execute(
            select(ErpReportDefinitionModel).where(
                ErpReportDefinitionModel.tenant_id == tenant_id,
                ErpReportDefinitionModel.slug == slug,
                ErpReportDefinitionModel.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def upsert_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        definition_id: uuid.UUID,
        period: date,
        payload: list[dict[str, Any]],
    ) -> ErpReportSnapshotModel:
        """Idempotently store a snapshot for (tenant, definition, period).

        Re-running the same period replaces the payload (and refreshes
        ``generated_at``) instead of inserting a second row - erp-phase1.md
        §M-RPT snapshot-refresh acceptance.
        """
        existing = await self.get_snapshot(
            tenant_id=tenant_id,
            definition_id=definition_id,
            period=period,
        )
        if existing is not None:
            existing.payload = payload
            await self._session.flush()
            return existing

        snapshot = ErpReportSnapshotModel(
            tenant_id=tenant_id,
            definition_id=definition_id,
            period=period,
            payload=payload,
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot

    async def get_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        definition_id: uuid.UUID,
        period: date,
    ) -> ErpReportSnapshotModel | None:
        """Return the snapshot for (tenant, definition, period), or None."""
        result = await self._session.execute(
            select(ErpReportSnapshotModel).where(
                ErpReportSnapshotModel.tenant_id == tenant_id,
                ErpReportSnapshotModel.definition_id == definition_id,
                ErpReportSnapshotModel.period == period,
            )
        )
        return result.scalar_one_or_none()
