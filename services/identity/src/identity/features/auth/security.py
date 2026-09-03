"""Auth security helpers - JWT tenant cross-checking.

Pure functions shared by the HTTP middleware and the API dependency layer;
both are consumers that verify a token belongs to the routed tenant.
"""

from __future__ import annotations

from identity.core.exceptions import TenantMismatchError


def cross_check_jwt_tenant(jwt_tenant_id: str | None, routed_tenant_id: str) -> None:
    """Reject when a verified JWT's tenant claim differs from the routed tenant.

    Raises TenantMismatchError (401); processing stops. A missing JWT claim is
    treated as a mismatch (a valid token must always carry its tenant).
    """
    if jwt_tenant_id is None or jwt_tenant_id != routed_tenant_id:
        raise TenantMismatchError(
            "Token tenant does not match the tenant resolved from the request routing."
        )
