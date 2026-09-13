"""ai_l4_scenario_versions - one named scenario snapshot per planning session (SKY-93).

The L4 what-if engine projects a payroll base forward over a horizon; each
*create* call stores the actions (request) and the deterministic projection
(snapshot) together.  Projections are frozen at save time so the same
scenario reads the same numbers regardless of how the live roster evolves.

``created_by`` is a soft-link UUID (no FK to identity - cross-service idiom).
The projection JSONB stores the full engine output (months + totals) so the
compare endpoint never re-runs the engine.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiL4ScenarioModel(Base):
    """One named L4 what-if scenario with its frozen projection."""

    __tablename__ = "ai_l4_scenario_versions"
    __table_args__ = (
        CheckConstraint(
            "horizon >= 1 AND horizon <= 36",
            name="ck_ai_l4_scenario_versions_horizon",
        ),
        Index(
            "idx_ai_l4_scenario_versions_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_as_of: Mapped[date] = mapped_column(nullable=False)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    actions: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'"),
    )
    projection: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'"),
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
