"""Add erp.inventory.ai.approve permission for AI restock suggestion workflow.

Ticket SKY-68 (inventory AI advisor suite): approves/rejects AI restock
suggestions require a dedicated permission separate from erp.inventory.write.
The core AI proxy router uses this key to gate /ai/suggestions/scan,
/ai/suggestions/{id}/approve, and /ai/suggestions/{id}/reject.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-27

Renumbered from 0022 to 0025 on the HR-AI-002 branch: dev's 0022 collided
with the HR-AI-002 wave-2 schema migration, so this inventory-approve
permission is appended after 0024 (the last HR-AI-002 pattern-engine head).
"""

from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
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
