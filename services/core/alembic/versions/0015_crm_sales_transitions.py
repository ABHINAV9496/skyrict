"""crm_sales_transitions: lead_id + source_opportunity_id anchor columns

CRM-BE-002 (SKY-44). Two additive anchor columns on the existing CRM tables —
exactly what docs/modules/sales-crm.md §3.2 calls for:

- ``erp_crm_opportunities.lead_id`` — the lead that qualified into this
  opportunity. Soft link: plain UUID with NO FK (a lead does not outlive its
  pipeline deal) plus ``UNIQUE (tenant_id, lead_id)`` so one lead can never
  qualify twice — the idempotency stamp ``qualify_lead`` re-probes.
- ``erp_crm_customers.source_opportunity_id`` — the won opportunity this
  customer was promoted from. Soft link, NO FK, plus ``UNIQUE (tenant_id,
  source_opportunity_id)`` so one opportunity can never promote twice — the
  idempotency stamp ``promote_opportunity`` re-probes.

Both columns are nullable: existing rows need no backfill and the service
layer treats NULL as "not yet linked". No RLS policy change is needed — the
new columns carry no tenant identity (they are tenant-relative by
construction, and the UNIQUE keys are composite with ``tenant_id``).

Follows the composite-constraint convention from 0003: every uniqueness
constraint is scoped ``(tenant_id, ...)`` so cross-tenant collisions are
impossible at the constraint level.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "erp_crm_opportunities",
        sa.Column("lead_id", sa.Uuid(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_erp_crm_opportunities_tenant_lead",
        "erp_crm_opportunities",
        ["tenant_id", "lead_id"],
    )

    op.add_column(
        "erp_crm_customers",
        sa.Column("source_opportunity_id", sa.Uuid(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_erp_crm_customers_tenant_source_opportunity",
        "erp_crm_customers",
        ["tenant_id", "source_opportunity_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_erp_crm_customers_tenant_source_opportunity",
        "erp_crm_customers",
        type_="unique",
    )
    op.drop_column("erp_crm_customers", "source_opportunity_id")

    op.drop_constraint(
        "uq_erp_crm_opportunities_tenant_lead",
        "erp_crm_opportunities",
        type_="unique",
    )
    op.drop_column("erp_crm_opportunities", "lead_id")
