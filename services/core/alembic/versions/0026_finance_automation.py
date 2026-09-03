"""Finance automation tables: erp_tenant_settings, ai_finance_anomalies, ai_finance_suggestions

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-30
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def _tenant_scoped_pk() -> list[Any]:
    return [
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    ]


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


def _create_rls_policy(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
        "USING (tenant_id = public.current_tenant_id()) "
        "WITH CHECK (tenant_id = public.current_tenant_id())"
    )


def _drop_rls_policy(table: str) -> None:
    op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")


_TABLES: tuple[str, ...] = (
    "erp_tenant_settings",
    "ai_finance_anomalies",
    "ai_finance_suggestions",
)


def upgrade() -> None:
    op.add_column(
        "erp_journal_entries",
        sa.Column("reversal_entry_id", sa.Uuid(), nullable=True),
    )

    # erp_tenant_settings - generic KV config store
    op.create_table(
        "erp_tenant_settings",
        *_tenant_scoped_pk(),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.String(4096), nullable=False),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("tenant_id", "key", name="uq_erp_tenant_settings_tenant_key"),
    )

    # ai_finance_anomalies - persisted anomaly detections
    op.create_table(
        "ai_finance_anomalies",
        *_tenant_scoped_pk(),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("anomaly_type", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default=sa.text("'low'")),
        sa.Column("description", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'open'")),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "anomaly_type",
            name="uq_ai_finance_anomalies_tenant_entity_type",
        ),
    )

    # ai_finance_suggestions - persisted account-code suggestions
    op.create_table(
        "ai_finance_suggestions",
        *_tenant_scoped_pk(),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("suggested_code", sa.String(32), nullable=False),
        sa.Column("suggested_name", sa.String(255), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint(
            "tenant_id",
            "description",
            name="uq_ai_finance_suggestions_tenant_description",
        ),
    )

    for table in _TABLES:
        _create_rls_policy(table)


def downgrade() -> None:
    for table in reversed(_TABLES):
        _drop_rls_policy(table)

    op.drop_table("ai_finance_suggestions")
    op.drop_table("ai_finance_anomalies")
    op.drop_table("erp_tenant_settings")
    op.drop_column("erp_journal_entries", "reversal_entry_id")
