"""Reporting data layer — definitions + snapshots with tenant RLS (RPT-DATA-001).

Creates the two tables the reporting chain is built on:

* ``erp_report_definitions`` — the per-tenant Phase-1 report catalog. Each row
  carries the read-only, parameterized dataset query, the JSONB allow-list of
  ``:name`` bind parameters, and the permission key that gates serving it.
* ``erp_report_snapshots`` — materialized report results keyed by
  ``(definition, period)``. ``UNIQUE (tenant_id, definition_id, period)`` makes
  snapshot refresh idempotent; the composite FK pins a snapshot to a definition
  in the same tenant and cascades on definition removal.

Tenant isolation is enforced with the standard ``tenant_isolation_*`` RLS
policies keyed on ``public.current_tenant_id()`` (same pattern as 0027/0035),
so the acceptance criterion "every report returns the tenant's data only" holds
even if a query layer ever forgets a tenant filter.

The migration then seeds:

* the ``erp.reports.read`` permission key (0030 pattern), and
* the 12 Phase-1 report definitions into EVERY existing tenant, from the
  canonical ``core.features.reporting.seeds`` catalog — the same pack the
  tenant-provisioning hook applies to new tenants. Each seed's SQL is validated
  read-only BEFORE any insert so a bad definition aborts the whole upgrade.

The import of ``seeds``/``validation`` into a migration is deliberate: those
modules are pure data + pure validation (no DB, no settings), so they are safe
at migration time and keep exactly one source of truth for the report pack.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-05
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

from core.features.reporting.seeds import PHASE_1_REPORT_SEEDS
from core.features.reporting.validation import validate_read_only_sql

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

_REPORTS_READ_KEY = "erp.reports.read"
_REPORTS_READ_DESCRIPTION = "Read reporting definitions and snapshots"


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


def _seed_permission() -> None:
    op.execute(
        "INSERT INTO core_permissions (key, description) VALUES "
        f"('{_REPORTS_READ_KEY}', '{_REPORTS_READ_DESCRIPTION}') "  # nosec B608
        "ON CONFLICT (key) DO NOTHING"
    )


def _seed_definitions() -> None:
    """Insert one definition row per seed for every existing tenant.

    Rules:
    * every seed SQL must validate read-only first — fail closed, aborting the
      upgrade if any definition is out of contract;
    * ``id`` is left to ``gen_random_uuid()``; audit columns take server
      defaults;
    * ``ON CONFLICT (tenant_id, slug) DO NOTHING`` keeps re-runs idempotent.
    """
    bind = op.get_bind()
    for seed in PHASE_1_REPORT_SEEDS:
        validate_read_only_sql(seed.sql, seed.params)
        bind.execute(
            sa.text(
                """
                INSERT INTO erp_report_definitions
                    (tenant_id, slug, title, module, description, sql, params, permission_key)
                SELECT t.id,
                       :slug,
                       :title,
                       :module,
                       :description,
                       :sql,
                       CAST(:params AS jsonb),
                       :permission_key
                  FROM tenants t
                ON CONFLICT (tenant_id, slug) DO NOTHING
                """
            ),
            {
                "slug": seed.slug,
                "title": seed.title,
                "module": seed.module,
                "description": seed.description,
                "sql": seed.sql,
                "params": json.dumps(list(seed.params)),
                "permission_key": seed.permission_key,
            },
        )


def upgrade() -> None:
    op.create_table(
        "erp_report_definitions",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("module", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column(
            "params",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "permission_key",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'erp.reports.read'"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_erp_report_definitions_tenant_module",
        "erp_report_definitions",
        ["tenant_id", "module"],
    )
    op.create_unique_constraint(
        "uq_erp_report_definitions_tenant_slug",
        "erp_report_definitions",
        ["tenant_id", "slug"],
    )
    _enable_rls("erp_report_definitions")

    op.create_table(
        "erp_report_snapshots",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "definition_id"],
            ["erp_report_definitions.tenant_id", "erp_report_definitions.id"],
            name="fk_erp_report_snapshots_definition",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_erp_report_snapshots_tenant_period",
        "erp_report_snapshots",
        ["tenant_id", "period"],
    )
    op.create_unique_constraint(
        "uq_erp_report_snapshots_tenant_definition_period",
        "erp_report_snapshots",
        ["tenant_id", "definition_id", "period"],
    )
    _enable_rls("erp_report_snapshots")

    _seed_permission()
    _seed_definitions()


def downgrade() -> None:
    _disable_rls("erp_report_snapshots")
    _disable_rls("erp_report_definitions")

    op.drop_constraint(
        "uq_erp_report_snapshots_tenant_definition_period",
        "erp_report_snapshots",
        type_="unique",
    )
    op.drop_index("ix_erp_report_snapshots_tenant_period", "erp_report_snapshots")
    op.drop_table("erp_report_snapshots")

    op.drop_constraint(
        "uq_erp_report_definitions_tenant_slug",
        "erp_report_definitions",
        type_="unique",
    )
    op.drop_index("ix_erp_report_definitions_tenant_module", "erp_report_definitions")
    op.drop_table("erp_report_definitions")

    op.execute(f"DELETE FROM core_permissions WHERE key = '{_REPORTS_READ_KEY}'")  # nosec B608
