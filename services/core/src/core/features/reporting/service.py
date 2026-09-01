"""Service layer for dashboard layout operations."""

from __future__ import annotations

import uuid

import structlog

from core.features.reporting.repository import DashboardRepository

logger = structlog.get_logger("core.reporting.service")

# Minimum telemetry events required before the AI suggestion engine
# will produce a layout recommendation.
_MIN_EVENTS_FOR_SUGGESTION = 50


class DashboardService:
    """Orchestrates layout reads/writes and telemetry recording."""

    def __init__(self, repository: DashboardRepository) -> None:
        self._repo = repository

    # --- Layout resolution ---------------------------------------------------

    async def resolve_layout(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict:
        """Return the effective layout for a user.

        Priority: user override > tenant default > empty layout.
        """
        user_layout = await self._repo.get_user_layout(tenant_id=tenant_id, user_id=user_id)
        if user_layout is not None:
            return {
                "source": "user",
                "layout": user_layout.layout,
                "updated_at": user_layout.updated_at.isoformat(),
            }

        tenant_default = await self._repo.get_tenant_default(tenant_id=tenant_id)
        if tenant_default is not None:
            return {
                "source": "tenant_default",
                "layout": tenant_default.layout,
                "updated_at": tenant_default.updated_at.isoformat(),
            }

        return {"source": "empty", "layout": [], "updated_at": None}

    # --- User layout CRUD ----------------------------------------------------

    async def save_user_layout(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        layout: list[dict],
    ) -> dict:
        """Save the user's personal layout."""
        record = await self._repo.upsert_user_layout(
            tenant_id=tenant_id, user_id=user_id, layout=layout
        )
        logger.info(
            "user_layout_saved",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            widget_count=len(layout),
        )
        return {
            "layout": record.layout,
            "updated_at": record.updated_at.isoformat(),
        }

    async def reset_user_layout(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Delete the user's personal layout, reverting to the tenant default."""
        deleted = await self._repo.delete_user_layout(tenant_id=tenant_id, user_id=user_id)
        logger.info(
            "user_layout_reset",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            deleted=deleted,
        )
        return deleted

    # --- Telemetry -----------------------------------------------------------

    async def record_events(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        events: list[dict],
    ) -> int:
        """Record widget interaction events."""
        count = await self._repo.record_widget_events(
            tenant_id=tenant_id, user_id=user_id, events=events
        )
        if count > 0:
            logger.info(
                "widget_events_recorded",
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                count=count,
            )
        return count

    async def has_enough_events(self, *, tenant_id: uuid.UUID) -> bool:
        """Check whether the tenant has enough telemetry for an AI suggestion."""
        # Check across all widgets — if any widget hits the threshold, we suggest.
        summary = await self._repo.get_widget_event_summary(tenant_id=tenant_id)
        return any(item["total_events"] >= _MIN_EVENTS_FOR_SUGGESTION for item in summary)

    async def get_event_summary(self, *, tenant_id: uuid.UUID) -> list[dict]:
        """Return per-widget event counts."""
        return await self._repo.get_widget_event_summary(tenant_id=tenant_id)
