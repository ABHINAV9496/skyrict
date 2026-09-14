"""Document & tax AI suite tables (SKY-81/SKY-83 FIN-AI-004).

Adds the two persistence tables behind the finance AI document features:

- ``erp_ai_documents`` - versioned, DRAFT-gated PDF artifacts (P&L / balance
  sheet packs rendered from report snapshots). ``watermarked`` is true until a
  human approves the artifact; the PDF bytes embed the DRAFT overlay.
- ``erp_tax_summaries`` - draft tax summaries (per category input/output/net)
  generated from a fiscal period's posted journal lines. ``status`` moves
  draft -> approved|rejected; the generated figures always cite the
  ``snapshot`` of accounts + journal lines (and the report ``snapshot_id``)
  they were built from so a reviewer can trace the draft to its source.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erp_ai_documents",
        sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "doc_type",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'pnl'"),
        ),
        sa.Column("snapshot_id", UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_data", JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("watermarked", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("approved_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_bytes", sa.LargeBinary, nullable=True),
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
            "doc_type IN ('pnl', 'balance_sheet', 'tax_summary', 'audit_narrative')",
            name="ck_erp_ai_documents_doc_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'rejected')",
            name="ck_erp_ai_documents_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_erp_ai_documents_version"),
    )
    op.create_index(
        "ix_erp_ai_documents_tenant_doc_type",
        "erp_ai_documents",
        ["tenant_id", "doc_type"],
    )
    op.create_index(
        "ix_erp_ai_documents_tenant_snapshot",
        "erp_ai_documents",
        ["tenant_id", "snapshot_id"],
    )

    op.create_table(
        "erp_tax_summaries",
        sa.Column("tenant_id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("period_id", UUID(as_uuid=True), nullable=False),
        sa.Column("period_name", sa.String(100), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("snapshot_id", UUID(as_uuid=True), nullable=True),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("categories", JSONB, nullable=False),
        sa.Column("total_input", sa.Numeric(19, 4), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "total_output",
            sa.Numeric(19, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("model_used", sa.String(64), nullable=False, server_default=sa.text("''")),
        sa.Column("approved_by_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('draft', 'approved', 'rejected')",
            name="ck_erp_tax_summaries_status",
        ),
    )
    op.create_index(
        "ix_erp_tax_summaries_tenant_period",
        "erp_tax_summaries",
        ["tenant_id", "period_id"],
    )
    op.create_index(
        "ix_erp_tax_summaries_tenant_status",
        "erp_tax_summaries",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_erp_tax_summaries_tenant_status", table_name="erp_tax_summaries")
    op.drop_index("ix_erp_tax_summaries_tenant_period", table_name="erp_tax_summaries")
    op.drop_table("erp_tax_summaries")
    op.drop_index("ix_erp_ai_documents_tenant_snapshot", table_name="erp_ai_documents")
    op.drop_index("ix_erp_ai_documents_tenant_doc_type", table_name="erp_ai_documents")
    op.drop_table("erp_ai_documents")
