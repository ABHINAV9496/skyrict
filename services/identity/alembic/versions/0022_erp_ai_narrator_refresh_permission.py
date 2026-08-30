"""Add erp.ai.narrator.refresh permission (SKY-63 cross-module narrator).

Ticket SKY-63 ([AI-NARR-001]): the core monolith proxies ``/api/v1/ai/
narrator/*`` to ai-agent. Reading the daily digest requires ``erp.ai.invoke``
plus every module read (``erp.finance.read``/``erp.sales.read``/
``erp.inventory.read``/``erp.crm.read``); force-refreshing it additionally
requires ``erp.ai.narrator.refresh``. Granted to organization_admin only —
tenant owners already pass via the ``*`` wildcard — mirroring the 0018
``erp.ai.invoke`` precedent.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-27
"""

from __future__ import annotations

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

# (key, description) - mirrors identity.core.permissions catalog entries.
_PERMISSIONS: tuple[tuple[str, str], ...] = (
    (
        "erp.ai.narrator.refresh",
        "Force-refresh the cross-module intelligence narrator digest",
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
