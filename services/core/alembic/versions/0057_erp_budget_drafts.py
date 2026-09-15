"""HR-AI-004 finance budget-draft bridge tables (SKY-93, Commit 4).

The finance export from the L4 what-if planner is a *proposed budget draft*,
not a journal entry: a what-if projection is a planning figure that must never
share the ``erp_journal_entries`` inbox (or the post/void code path) that turns
real payroll runs into ledger entries. Two tables:

``erp_budget_drafts``
    The proposed-budget header. ``UNIQUE (tenant_id, source, source_ref)`` is
    the idempotency lock (source='workforce_plan', source_ref=scenario_id) so
    a replayed export can never create a second draft. Status is draft →
    pending → approved (String(16) + CHECK, so FIN-AI-001 can extend states
    without a migration).

``erp_budget_draft_lines``
    Cost-component lines (salary, benefits) from the projection. Composite FK
    ``(tenant_id, draft_id)`` keeps lines tenant-scoped; CASCADE frees lines
    with their draft.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_budget_drafts",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scenario_id", sa.UUID(), nullable=False),
        sa.Column("scenario_name", sa.String(200), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'draft'")
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("base_as_of", sa.Date(), nullable=False),
        sa.Column("salary_total", sa.Numeric(16, 2), nullable=False),
        sa.Column("benefit_total", sa.Numeric(16, 2), nullable=False),
        sa.Column("grand_total", sa.Numeric(16, 2), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'pending', 'approved')",
            name="ck_erp_budget_drafts_status",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.UniqueConstraint(
            "tenant_id", "source", "source_ref", name="uq_erp_budget_drafts_source_ref"
        ),
    )
    op.create_index(
        "ix_erp_budget_drafts_tenant_status", "erp_budget_drafts", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_erp_budget_drafts_tenant_created", "erp_budget_drafts", ["tenant_id", "created_at"]
    )

    op.create_table(
        "erp_budget_draft_lines",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("draft_id", sa.UUID(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("amount", sa.Numeric(16, 2), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "draft_id"],
            ["erp_budget_drafts.tenant_id", "erp_budget_drafts.id"],
            ondelete="CASCADE",
            name="fk_budget_draft_lines_draft",
        ),
        sa.PrimaryKeyConstraint("draft_id", "line_no"),
    )
    op.create_index("ix_budget_draft_lines_draft", "erp_budget_draft_lines", ["tenant_id", "draft_id"])


def downgrade() -> None:
    op.drop_table("erp_budget_draft_lines")
    op.drop_table("erp_budget_drafts")
