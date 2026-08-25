"""agent_registry - global catalog of deployed agent graphs (AI-INFRA-001).

Platform-level table with NO tenant_id and NO row-level security: it lists
the agent modules/graphs this service can execute (LangGraph graph ids land
with SKY-59). Rows are managed by operators/migrations, never by tenants -
reads happen at request time to resolve ``module -> graph_id`` and the
enabled flag; a disabled agent is rejected before any LLM call.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AgentRegistryModel(Base):
    """One registered agent module (global, not tenant-scoped)."""

    __tablename__ = "agent_registry"
    __table_args__ = (UniqueConstraint("name", name="uq_agent_registry_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    # Stable machine name used by callers to address an agent ("nl_query",
    # "restock_analyzer", ...). Unique across the platform.
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Dotted module path providing the agent implementation.
    module: Mapped[str] = mapped_column(String(200), nullable=False)
    # LangGraph graph id once the orchestration layer exists (SKY-59).
    graph_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
