"""Register AI Agents and Market Intelligence module permissions.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("agents:read", "View AI agents and their runs"),
    ("intelligence:read", "View market intelligence and trends"),
)


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

    _append_permissions(("organization_admin",), tuple(key for key, _ in _PERMISSIONS))


def downgrade() -> None:
    for key, _ in _PERMISSIONS:
        op.execute(f"UPDATE roles SET permissions = array_remove(permissions, '{key}')")
        op.execute(f"DELETE FROM permissions WHERE key = '{key}'")
