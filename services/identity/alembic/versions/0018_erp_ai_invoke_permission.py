"""Add erp.ai.invoke permission (AI assistant gate).

Ticket SKY-57 ([AI-INFRA-001], docs/modules/skyrict-ai/
inventory-ai-features.md §6.3): core checks ``erp.ai.invoke`` BEFORE
proxying any ``/api/v1/ai/*`` request to the ai-agent microservice, so a
permissionless call is rejected 403 at the monolith and never reaches the
AI service. Granted to organization_admin only — tenant admins opt in to
the AI assistant for their users via custom roles.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

# (key, description) - mirrors identity.core.permissions catalog entries.
_PERMISSIONS: tuple[tuple[str, str], ...] = (
    (
        "erp.ai.invoke",
        "Invoke AI assistant features (queries, restock suggestions, anomaly review)",
    ),
)

_ALL = tuple(key for key, _ in _PERMISSIONS)


def _append_permissions(role_names: tuple[str, ...], permission_keys: tuple[str, ...]) -> None:
    """Append missing keys without disturbing tenant-specific role grants."""
    for key in permission_keys:
        op.execute(
            "UPDATE roles SET permissions = array_append(permissions, "
            f"'{key}') WHERE name IN ({', '.join(repr(name) for name in role_names)}) "
            f"AND NOT ('{key}' = ANY(permissions))"
        )


def upgrade() -> None:
    for key, description in _PERMISSIONS:
        op.execute(
            "INSERT INTO permissions (key, description) VALUES "
            f"('{key}', '{description}') ON CONFLICT (key) DO NOTHING"
        )

    _append_permissions(("organization_admin",), _ALL)


def downgrade() -> None:
    for key in _ALL:
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{key}')")
        op.execute(f"DELETE FROM permissions WHERE key = '{key}'")
