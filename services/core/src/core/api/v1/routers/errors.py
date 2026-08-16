"""Service-error translation for routers (HR-BE-002 §7 error table).

The service layer raises bare ``ValueError`` for not-found and invalid inputs
(that was the pre-API convention). The API layer must map those onto the
domain error taxonomy so the app's RFC 7807 handlers return the right status:
404 for "not found", 422 for anything else (validation).
"""

from __future__ import annotations

from skyrict_common.exceptions import NotFoundError, ValidationError


def raise_from_service_error(exc: ValueError) -> None:
    """Re-raise a service ``ValueError`` as the correct domain error."""
    if "not found" in str(exc):
        raise NotFoundError(str(exc)) from exc
    raise ValidationError(str(exc)) from exc


__all__ = ["raise_from_service_error"]
