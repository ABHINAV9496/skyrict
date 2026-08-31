"""LangGraph orchestration persistence: checkpoints, writes, interrupts (SKY-59).

Lands the Postgres storage for the AGT-001 orchestration runtime:

- ``agent_registry.tools`` - JSONB array of tool names each registered agent
  may call. The runtime refuses any tool absent from the agent's row (tools
  are additionally gated by the caller's resolved permission at invoke time).
- ``graph_checkpoints`` - one row per LangGraph checkpoint, keyed per tenant
  + graph run. ``state`` holds the serialized checkpoint (a typed envelope
  ``{"type": "json"|"msgpack", "data": ...}`` written by the async SQLAlchemy
  checkpointer — no psycopg/msgpack sidecar). ``step`` and ``updated_at``
  mirror the runtime metadata for cheap list/sweep queries.
- ``graph_checkpoint_writes`` - pending task writes LangGraph needs to
  continue a paused graph after resume (the same role as the stock Postgres
  checkpointer's second table).
- ``agent_interrupts`` - human-in-the-loop ledger: one row per interrupt
  raised before a write-action tool. ``status`` pending|approved|denied;
  ``decided_by``/``decided_at`` record the approver; ``expires_at`` (24h)
  drives lazy auto-deny with an audit row.

All three tables are tenant-scoped (composite ``(tenant_id, id)`` PK + RLS
against ``public.current_tenant_id()``, the repo-wide convention). The
``graph_checkpoint_writes`` parent reference is a COMPOSITE FK into
``graph_checkpoints(tenant_id, graph_run_id, checkpoint_id)`` so a write can
only ever attach to a checkpoint in the same tenant. ``agent_registry`` stays
global platform data (no RLS).

Seeds the ``restock_advisor`` demo agent (two tool calls + one approval
interrupt, resumable after restart) into ``agent_registry``.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# Tenant-scoped tables get RLS; agent_registry stays global.
_TENANT_SCOPED_TABLES = (
    "graph_checkpoints",
    "graph_checkpoint_writes",
    "agent_interrupts",
)


# ---------------------------------------------------------------------------
# Schema helpers (same idiom as migrations 0001/0004)
# ---------------------------------------------------------------------------
def _tenant_scoped_pk(fk: bool) -> list[Any]:
    """Composite (tenant_id, id) PK so no generated PK column leaks."""
    columns: list[Any] = [
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        )
        if fk
        else sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    ]
    return columns


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _updated_at() -> sa.Column[Any]:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


# ---------------------------------------------------------------------------
# Row-level security helpers (idempotent)
# ---------------------------------------------------------------------------
def _create_rls_policy(table: str) -> None:
    """Enable RLS and create the tenant-isolation policy for a tenant table."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def _drop_rls_policy(table: str) -> None:
    """Disable RLS and drop the tenant-isolation policy for a tenant table."""
    op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")


def _ensure_current_tenant_id() -> None:
    """Pins the current-tenant-id function that RLS policies reference."""
    op.execute(
        "CREATE OR REPLACE FUNCTION public.current_tenant_id() RETURNS uuid "
        "LANGUAGE sql STABLE AS $$ "
        "SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid $$"
    )


def upgrade() -> None:
    # --- agent_registry.tools: per-agent tool allowlist ----------------------
    op.add_column(
        "agent_registry",
        sa.Column(
            "tools",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )

    # --- graph_checkpoints: one row per LangGraph checkpoint -----------------
    op.create_table(
        "graph_checkpoints",
        *_tenant_scoped_pk(fk=True),
        sa.Column("graph_run_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Uuid(), nullable=True),
        sa.Column(
            "checkpoint_type", sa.String(32), nullable=False, server_default=sa.text("'json'")
        ),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("step", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _updated_at(),
        sa.UniqueConstraint(
            "tenant_id",
            "graph_run_id",
            "checkpoint_id",
            name="uq_graph_checkpoints_run_checkpoint",
        ),
        sa.Index(
            "idx_graph_checkpoints_run_updated",
            "tenant_id",
            "graph_run_id",
            sa.text("updated_at DESC"),
        ),
    )

    # --- graph_checkpoint_writes: pending task writes for resume ------------
    op.create_table(
        "graph_checkpoint_writes",
        *_tenant_scoped_pk(fk=True),
        sa.Column("graph_run_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("task_path", sa.String(512), nullable=False, server_default=sa.text("''")),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("write_type", sa.String(32), nullable=False, server_default=sa.text("'json'")),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        _updated_at(),
        sa.UniqueConstraint(
            "tenant_id",
            "graph_run_id",
            "checkpoint_id",
            "task_id",
            "task_path",
            "idx",
            name="uq_graph_checkpoint_writes_key",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "graph_run_id", "checkpoint_id"],
            [
                "graph_checkpoints.tenant_id",
                "graph_checkpoints.graph_run_id",
                "graph_checkpoints.checkpoint_id",
            ],
            ondelete="CASCADE",
            name="fk_graph_checkpoint_writes_checkpoint",
        ),
        sa.Index(
            "idx_graph_checkpoint_writes_run",
            "tenant_id",
            "graph_run_id",
            "checkpoint_id",
        ),
    )

    # --- agent_interrupts: human-in-the-loop ledger -------------------------
    op.create_table(
        "agent_interrupts",
        *_tenant_scoped_pk(fk=True),
        sa.Column("graph_run_id", sa.Uuid(), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("tool", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '24 hours'"),
        ),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_agent_interrupts_status",
        ),
        sa.Index("idx_agent_interrupts_run", "tenant_id", "graph_run_id"),
        sa.Index("idx_agent_interrupts_status_expiry", "tenant_id", "status", "expires_at"),
    )

    # --- Row-level security ---------------------------------------------------
    _ensure_current_tenant_id()
    for table in _TENANT_SCOPED_TABLES:
        _create_rls_policy(table)

    # --- Seed the restock_advisor demo agent (AGT-001) ------------------------
    op.execute(
        "INSERT INTO agent_registry (name, module, graph_id, enabled, tools) "
        "VALUES ('restock_advisor', 'ai_agent.features.restock_agent.graph', "
        "'restock_advisor', true, "
        'CAST(\'["query_stock","draft_suggestion","apply_suggestion"]\' AS jsonb)) '
        "ON CONFLICT (name) DO NOTHING"
    )


def downgrade() -> None:
    # 1) drop RLS policies
    for table in _TENANT_SCOPED_TABLES:
        _drop_rls_policy(table)

    # 2) drop tables (indexes/constraints go with them; writes first for FK)
    op.drop_table("graph_checkpoint_writes")
    op.drop_table("graph_checkpoints")
    op.drop_table("agent_interrupts")

    # 3) remove the seed and the tools column
    op.execute(
        "DELETE FROM agent_registry WHERE name = 'restock_advisor' "
        "AND module = 'ai_agent.features.restock_agent.graph'"
    )
    op.drop_column("agent_registry", "tools")
