"""Leave-grant heritage repair carrier (SKY-109 B1, idempotent + collision-guarded).

Heritage tensor closure (from SKY-109's three-tree audit): the identity
migration FILES are heritage-clean in all three trees - creation tree ==
origin/dev == disk for every identity revision, ``git diff origin/dev --
services/identity`` is empty, and every legacy grant carrier was already
renumbered onto the canonical chain. The canonical constants are already
correct everywhere (``erp.leave.self`` permission key via 0019/0011 carriers,
``employee_self_service`` system role via 0019).

The one thing a migration file cannot fix is *row data already written into an
applied database by an older, in-place-edited revision*. A dev/staging
database migrated while core 0005 still carried the heritage ``String(64)``
in-place edit (the ``hr.leave.self`` / ``employee`` naming era) can hold grant
rows under those legacy names that no later migration ever repairs. This
revision is that repair: an idempotent data-repair carrier that canonicalizes
any lingering heritage-named grant rows, screens for collisions, and is a
verifiable no-op on a database that is already canonical.

Mechanisms (all idempotent by construction):

1. ``roles.permissions`` array entries equal to ``hr.leave.self`` are rewritten
   to ``erp.leave.self`` (the canonical key). ``array_replace`` is NULL-safe
   and a no-op when the key is absent, so re-running changes nothing.
2. A legacy system role named ``employee`` is renamed to the canonical
   ``employee_self_service`` ONLY when (a) it is a system role (``employee``
   custom roles created by tenants are left alone - never clobbered) and (b)
   the canonical name is not already taken in the same tenant (collision
   guard - the canonical role already exists from a clean migration). The
   ``NOT EXISTS`` guard makes re-runs and duplicate-guarded.
3. The canonical ``erp.leave.self`` permission row is seeded with
   ``ON CONFLICT (key) DO NOTHING`` if it is missing (mirrors 0028's
   seed-carrier pattern), closing the catalog gap for tenants provisioned in
   the heritage era.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

_LEGACY_LEAVE_GRANT_KEYS = ("hr.leave.self", "hr.leave.request", "hr.leave.admin")
_CANONICAL_LEAVE_GRANT_KEYS = (
    "erp.leave.self",
    "erp.leave.request",
    "erp.leave.admin",
)
_LEGACY_EMPLOYEE_ROLE_NAMES = ("employee", "employee_self")
_CANONICAL_EMPLOYEE_ROLE_NAME = "employee_self_service"


def _rewrite_grant_keys() -> None:
    """Rewrite any lingering legacy leave-grant keys to canonical.

    ``array_replace`` is NULL-safe and a no-op when the legacy key is absent,
    so the statement is idempotent by construction.
    """
    for legacy, canonical in zip(_LEGACY_LEAVE_GRANT_KEYS, _CANONICAL_LEAVE_GRANT_KEYS):
        if legacy == canonical:
            continue
        op.execute(
            "UPDATE roles SET permissions = "
            f"array_replace(permissions, '{legacy}', '{canonical}') "
            f"WHERE '{legacy}' = ANY(permissions)"
        )


def _rename_legacy_employee_role() -> None:
    """Rename the heritage ``employee`` system role, guarded by collision.

    Only system roles move (``is_system_role = true``); a custom role named
    ``employee`` created by a tenant is left alone. The canonical name must
    not already exist in the same tenant, otherwise the rename would create a
    duplicate role name for that tenant - guarded by the unique constraint.
    """
    op.execute(
        "UPDATE roles r SET name = '" + _CANONICAL_EMPLOYEE_ROLE_NAME + "' "
        "FROM roles c "
        "WHERE r.name IN ('" + "', '".join(_LEGACY_EMPLOYEE_ROLE_NAMES) + "') "
        "AND r.is_system_role = true "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM roles c2 "
        "  WHERE c2.tenant_id = r.tenant_id "
        "  AND c2.name = '" + _CANONICAL_EMPLOYEE_ROLE_NAME + "'"
        ")"
    )


def _seed_canonical_permission() -> None:
    """Ensure the canonical leave-grant permission row exists (idempotent)."""
    op.execute(
        "INSERT INTO permissions (key, description) VALUES "
        "('erp.leave.self', 'Register leave requests for the employee self-service role') "
        "ON CONFLICT (key) DO NOTHING"
    )


def upgrade() -> None:
    _rewrite_grant_keys()
    _rename_legacy_employee_role()
    _seed_canonical_permission()


def downgrade() -> None:
    """Reverse the rename only (idempotent reverse of this carrier).

    The canonical role name and permission row are NOT removed here: the
    employee self-service role is a system role seeded by 0019 and the
    canonical permission by 0019/0020, so this carrier only ever *repairs*
    data; a downgrade of the carrier must not delete rows that 0019 shipped.
    """
    op.execute(
        "UPDATE roles r SET name = 'employee' "
        "FROM roles c "
        "WHERE r.name = '" + _CANONICAL_EMPLOYEE_ROLE_NAME + "' "
        "AND r.is_system_role = true "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM roles c2 "
        "  WHERE c2.tenant_id = r.tenant_id "
        "  AND c2.name = 'employee'"
        ")"
    )
