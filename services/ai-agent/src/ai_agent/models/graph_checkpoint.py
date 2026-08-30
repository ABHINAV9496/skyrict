"""graph_checkpoints + graph_checkpoint_writes — LangGraph persistence (SKY-59).

ORM views over the orchestration runtime's storage (migration 0007):

- ``graph_checkpoints`` — one row per LangGraph checkpoint, per tenant and
  graph run. ``state`` holds the typed serialization envelope
  (``{"type": "json"|"msgpack", "data": ...}``) written by
  ``ai_agent.graphs.checkpointer.SqlAlchemyCheckpointSaver``; ``metadata`` is
  the LangGraph checkpoint metadata (source/step/parents + runtime extras)
  with JSON-safe scalar values. ``step``/``updated_at`` mirror the runtime
  metadata so list and sweep queries never decode blobs.
- ``graph_checkpoint_writes`` — pending task writes LangGraph needs to
  continue a paused graph after resume, the same role as the stock Postgres
  checkpointer's second table (channel, task_id, task_path, idx, value
  envelope; task ``idx`` is negative for special writes: error/interrupt/
  resume/scheduled).

Both tables are tenant-scoped with composite ``(tenant_id, id)`` PKs + RLS;
the write ledger's parent reference is a composite FK back into
``graph_checkpoints(tenant_id, graph_run_id, checkpoint_id)`` so a write can
never attach to another tenant's checkpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class GraphCheckpointModel(Base):
    """One persisted LangGraph checkpoint snapshot."""

    __tablename__ = "graph_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "graph_run_id",
            "checkpoint_id",
            name="uq_graph_checkpoints_run_checkpoint",
        ),
        # Newest-first lookup per run (also used by the expiry sweep).
        Index(
            "idx_graph_checkpoints_run_updated",
            "tenant_id",
            "graph_run_id",
            text("updated_at DESC"),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    graph_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    checkpoint_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'json'")
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # ORM attribute is metadata_json because "metadata" is reserved by
    # SQLAlchemy's Declarative API; the DB column stays named "metadata".
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'")
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class GraphCheckpointWriteModel(Base):
    """One pending task write attached to a checkpoint."""

    __tablename__ = "graph_checkpoint_writes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "graph_run_id",
            "checkpoint_id",
            "task_id",
            "task_path",
            "idx",
            name="uq_graph_checkpoint_writes_key",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "graph_run_id", "checkpoint_id"],
            [
                "graph_checkpoints.tenant_id",
                "graph_checkpoints.graph_run_id",
                "graph_checkpoints.checkpoint_id",
            ],
            ondelete="CASCADE",
            name="fk_graph_checkpoint_writes_checkpoint",
        ),
        Index(
            "idx_graph_checkpoint_writes_run",
            "tenant_id",
            "graph_run_id",
            "checkpoint_id",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    graph_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_path: Mapped[str] = mapped_column(String(512), nullable=False, server_default=text("''"))
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    write_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'json'")
    )
    value: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
