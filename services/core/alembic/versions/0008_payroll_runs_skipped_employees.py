"""Add ``erp_payroll_runs.skipped_employees`` (JSONB) for compute exclusions.

Design (docs/modules/hr-payroll.md §4.9, gap #6): a compute may exclude roster
employees that have no effective compensation or no payable days in the
period. That exclusion list must be observable, so the run persists it as a
nullable JSON array of ``{"employee_id": str, "reason": str}`` objects, set at
compute time and carried through the run lifecycle. Purely additive — no data
migration, no backfill (``NULL`` means "not computed yet").

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "erp_payroll_runs",
        sa.Column("skipped_employees", sa.dialects.postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("erp_payroll_runs", "skipped_employees")
