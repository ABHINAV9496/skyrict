"""Add transcript_text to CRM activities (SKY-91).

Adds the raw call/meeting transcript column to ``erp_crm_activities``. The
transcript is user-submitted CRM data about an activity (what was said on a
call); it stays in core alongside the rest of the CRM data plane. Analysis of
that transcript (summary, objection score, next-best-action) is AI product data
the ai-agent owns in its own table (``ai_transcript_analyses``) - core only
ever stores the input, never AI outputs on CRM rows.

Renumbered from ``0050`` to ``0051`` (chains after ``0050_ai_docs``) to repair
the duplicate-revision collision: two files originally claimed ``revision =
"0050"`` with the same ``down_revision = "0049"``, which broke ``alembic
upgrade head`` with "Multiple head revisions". ``0050_ai_docs`` was merged
first and keeps ``0050``; any DB stamped ``0050`` refers to it, and this
transcript column now applies afterwards.

Idempotency: the column already exists on some databases out-of-band (an
earlier manual ALTER propped it up while the version table lagged), so the
upgrade uses ``ADD COLUMN IF NOT EXISTS`` — the container boot migration
(``alembic upgrade head`` in Dockerfile.dev) must not crash on a column that
is already present. The post-upgrade round-trip probe (``test_migration_roundtrip``)
still passes because the column ends up present either way.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-11
"""

from __future__ import annotations

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE erp_crm_activities ADD COLUMN IF NOT EXISTS transcript_text TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE erp_crm_activities DROP COLUMN IF EXISTS transcript_text")
