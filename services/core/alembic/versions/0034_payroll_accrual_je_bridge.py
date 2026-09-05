"""Payroll→Finance accrual JE bridge (HR-AUT-001, Commit 4).

Commit 4 lets a payroll admin mark a run paid and — when the per-tenant flag
is on and the Finance chart-of-accounts exists — drafts the payroll accrual
journal entry into the Finance inbox in the same transaction. Two columns:

``erp_payroll_runs.je_bridge_status``
    Outcome of the bridge on the run: ``none`` (bridge off / unpaid / no
    gross), ``pending`` (chart accounts 5010/2010/2020 missing so no entry
    was drafted — the run is paid but the JE has to be created manually), or
    ``draft`` (a balanced DRAFT journal entry exists in ``journal_entries``
    with source ``payroll`` and source_ref ``<run_id>``). A String(16) column
    with a CHECK constraint rather than a native enum so FIN-AI-001 can add
    ``posted`` / ``approved`` states without a migration.

``erp_payroll_settings.je_bridge_enabled``
    Per-tenant feature flag (ticket: "Feature flag per tenant; disable
    returns fully manual flow instantly") — same shape as
    ``ai_automation_enabled`` (0026). Off = marking a run paid is fully
    manual: no journal entry is drafted, ``je_bridge_status`` stays ``none``.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "erp_payroll_runs",
        sa.Column(
            "je_bridge_status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
    )
    op.create_check_constraint(
        "ck_erp_payroll_runs_je_bridge_status",
        "erp_payroll_runs",
        "je_bridge_status IN ('none', 'pending', 'draft')",
    )

    op.add_column(
        "erp_payroll_settings",
        sa.Column(
            "je_bridge_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("erp_payroll_settings", "je_bridge_enabled")
    op.drop_constraint("ck_erp_payroll_runs_je_bridge_status", "erp_payroll_runs", type_="check")
    op.drop_column("erp_payroll_runs", "je_bridge_status")
