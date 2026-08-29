"""Add erp.inventory.ai.approve permission for AI restock suggestion workflow.

Ticket SKY-68 (inventory AI advisor suite): approves/rejects AI restock
suggestions require a dedicated permission separate from erp.inventory.write.
The core AI proxy router uses this key to gate /ai/suggestions/scan,
/ai/suggestions/{id}/approve, and /ai/suggestions/{id}/reject.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-27
"""

from __future__ import annotations

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_PERMISSIONS: tuple[tuple[str, str], ...] = (
    (
        "erp.inventory.ai.approve",
        "Approve or reject AI-generated restock suggestions",
    ),
)


def upgrade() -> None:
    for key, description in _PERMISSIONS:
        op.execute(
            "INSERT INTO core_permissions (key, description) VALUES "
            f"('{key}', '{description}') ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    for key, _ in _PERMISSIONS:
        op.execute(f"DELETE FROM core_permissions WHERE key = '{key}'")
