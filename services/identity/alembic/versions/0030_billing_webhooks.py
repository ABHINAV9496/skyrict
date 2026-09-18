"""billing webhook lifecycle: grace period column + idempotency store

BILLING-SERV-002. Adds the two pieces the Stripe webhook lifecycle needs:

* ``tenants.grace_started_at``     - nullable DateTime; set once on first
  receipt of ``subscription_status='past_due'`` (first-write-wins so replay
  cannot reset the clock), cleared atomically on return to ``active``, and
  read by the lazy grace-expiry check that soft-downgrades the tenant to
  free when ``grace_started_at + grace_days`` passes.
* ``processed_stripe_events``      - persisted idempotency store. Stripe
  retries any non-2xx or timed-out webhook delivery, so replay is expected
  in production. ``event_id`` is UNIQUE; handlers do
  ``INSERT ... ON CONFLICT DO NOTHING`` in the same transaction as the
  state change and skip apply when the insert affects 0 rows.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tenants.grace_started_at --------------------------------------------------
    op.add_column(
        "tenants",
        sa.Column("grace_started_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- processed_stripe_events (idempotency store) -------------------------------
    op.create_table(
        "processed_stripe_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_processed_stripe_events_event_id",
        "processed_stripe_events",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_table("processed_stripe_events")
    op.drop_column("tenants", "grace_started_at")
