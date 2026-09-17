"""Billing security helper - pure owner-role validation.

The ``Depends``-wired guards (``require_billing_owner``, ``require_plan``) are
defined in the api composition root (``identity.api.deps``) so this feature
never imports ``identity.api``, matching the ``auth.security`` convention.
Keep the check here pure and unit-testable.

**402 vs 403 distinction** (raised by ``BillingService.require_plan_access``)
  * 403 (PermissionDeniedError) - the tenant has an active subscription
    but the feature is not included in their plan tier.
  * 402 (PaymentRequiredError) - the tenant's subscription is inactive
    (never trialed or trial expired), so a paid plan must be obtained
    first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from skyrict_common.exceptions import PermissionDeniedError

if TYPE_CHECKING:
    from identity.features.roles.repository import RoleRepository

_TENANT_OWNER_ROLE = "tenant_owner"


async def validate_tenant_owner(
    current_user: dict[str, Any],
    role_repo: RoleRepository,
) -> None:
    """Raise 403 unless the user holds the tenant_owner role."""
    roles = await role_repo.get_roles_for_user(current_user["user_id"], current_user["tenant_id"])
    if _TENANT_OWNER_ROLE not in roles:
        raise PermissionDeniedError("Only a tenant owner can manage billing")
