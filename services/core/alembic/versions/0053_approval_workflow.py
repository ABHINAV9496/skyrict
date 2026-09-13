"""Approval workflow engine tables (SKY-92, Commit 2).

Creates the five tables backing the reusable approval workflow engine:

- ``erp_approval_workflow_definitions`` - versioned per-tenant Pydantic DSL
  documents (JSONB). A version is immutable once ``status = 'active'``; later
  edits create a new version via ``UNIQUE (tenant_id, resource_type, version)``.
- ``erp_approval_workflow_instances`` - one row per submitted resource awaiting
  (or having completed) approval. ``status`` moves pending -> auto_approved /
  approved / rejected / request_changes / cancelled.
- ``erp_approval_workflow_steps`` - resolved step state for an instance:
  effective assignee (including runtime delegation), SLA due time and decision.
  ``original_assignee`` is preserved when a step is delegated (history contract).
- ``erp_approval_transitions`` - append-only audit trail: every state change
  records previous/new state, actor, actor type (human / delegated / system /
  ai_suggestion / escalation), reason and delegation context.
- ``erp_approval_delegations`` - runtime approver-level delegation records. They
  never rewrite workflow definitions or historical transitions.

Every table follows core's tenancy convention: composite ``(tenant_id, id)``
primary key, ``created_at``/``updated_at`` audit columns, RLS enforced via the
``public.current_tenant_id()`` policy (the session sets ``app.current_tenant_id``
once per connection, so every query is bound to the tenant).

Renumbered from ``0052`` to ``0053`` during the HR-AI-004 branch merge: two
unmerged branches independently took revision ``0052`` (this SKY-92 approval
engine and SKY-93's ``erp.hr.ai.planning`` permission seed). HR-AI-004 kept
``0052``; this SKY-92 table set now chains after it.

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def _disable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")


def upgrade() -> None:
    op.create_table(
        "erp_approval_workflow_definitions",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_erp_approval_workflow_definitions_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_erp_approval_workflow_definitions_version"),
        sa.UniqueConstraint(
            "tenant_id",
            "resource_type",
            "version",
            name="uq_erp_approval_workflow_definitions_tenant_resource_version",
        ),
    )
    op.create_index(
        "ix_erp_approval_workflow_definitions_tenant_resource",
        "erp_approval_workflow_definitions",
        ["tenant_id", "resource_type"],
    )
    _enable_rls("erp_approval_workflow_definitions")

    op.create_table(
        "erp_approval_workflow_instances",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("current_step_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("submitted_by", sa.Uuid(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'auto_approved', 'approved', "
            "'rejected', 'request_changes', 'cancelled')",
            name="ck_erp_approval_workflow_instances_status",
        ),
        sa.CheckConstraint(
            "current_step_index >= 0",
            name="ck_erp_approval_workflow_instances_current_step_index",
        ),
    )
    op.create_index(
        "ix_erp_approval_workflow_instances_tenant_status",
        "erp_approval_workflow_instances",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_erp_approval_workflow_instances_resource",
        "erp_approval_workflow_instances",
        ["tenant_id", "resource_type", "resource_id"],
    )
    _enable_rls("erp_approval_workflow_instances")

    op.create_table(
        "erp_approval_workflow_steps",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(100), nullable=False),
        sa.Column("assignee_kind", sa.String(16), nullable=False),
        sa.Column("assignee_value", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("original_assignee", sa.Uuid(), nullable=True),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("delegated_from", sa.Uuid(), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'skipped', 'escalated')",
            name="ck_erp_approval_workflow_steps_status",
        ),
        sa.CheckConstraint(
            "assignee_kind IN ('role', 'permission', 'users')",
            name="ck_erp_approval_workflow_steps_assignee_kind",
        ),
        sa.UniqueConstraint(
            "instance_id", "step_index", name="uq_erp_approval_workflow_steps_instance_index"
        ),
    )
    op.create_index(
        "ix_erp_approval_workflow_steps_instance",
        "erp_approval_workflow_steps",
        ["tenant_id", "instance_id"],
    )
    _enable_rls("erp_approval_workflow_steps")

    op.create_table(
        "erp_approval_transitions",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_instance_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=True),
        sa.Column("previous_state", sa.String(32), nullable=True),
        sa.Column("new_state", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("original_assignee", sa.Uuid(), nullable=True),
        sa.Column("delegated_actor", sa.Uuid(), nullable=True),
        sa.Column("context", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('human', 'delegated', 'system', 'ai_suggestion', 'escalation')",
            name="ck_erp_approval_transitions_actor_type",
        ),
    )
    op.create_index(
        "ix_erp_approval_transitions_instance",
        "erp_approval_transitions",
        ["tenant_id", "workflow_instance_id"],
    )
    _enable_rls("erp_approval_transitions")

    op.create_table(
        "erp_approval_delegations",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("delegator", sa.Uuid(), nullable=False),
        sa.Column("delegate", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(100), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_erp_approval_delegations_delegate",
        "erp_approval_delegations",
        ["tenant_id", "delegate", "revoked_at"],
    )
    _enable_rls("erp_approval_delegations")


def downgrade() -> None:
    tables = [
        "erp_approval_delegations",
        "erp_approval_transitions",
        "erp_approval_workflow_steps",
        "erp_approval_workflow_instances",
        "erp_approval_workflow_definitions",
    ]
    for table in tables:
        _disable_rls(table)
        op.drop_table(table)
