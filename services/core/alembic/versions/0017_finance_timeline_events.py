"""finance_timeline_events: add finance event types to CRM timeline

Add three new values to the ``erp_crm_timeline_event_type`` PostgreSQL enum
so the finance service can write curated timeline events anchored to the
customer entity: ``invoice.issued``, ``invoice.approved``, ``payment.applied``.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-21
"""

from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for value in ("invoice.issued", "invoice.approved", "payment.applied"):
        op.execute(
            f"ALTER TYPE erp_crm_timeline_event_type ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    # PostgreSQL does not support removing individual enum values.
    # A full downgrade would require recreating the type — out of scope for v1.
    pass
