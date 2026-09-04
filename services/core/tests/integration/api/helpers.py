"""Shared helpers for the HR & Payroll API integration tests.

These run against a real PostgreSQL database (via ``integration_db``); the
whole suite is skipped unless ``TEST_DATABASE_URL`` is reachable (see
``tests/integration/conftest.py``).

Tenant routing: the app resolves the tenant from the ``X-Tenant-Slug`` header
and ``get_current_user`` verifies the Bearer token's ``tenant_id`` claim
against it, so every helper builds a properly signed RS256 JWT bound to the
requested tenant's UUID (the ``integration_db`` fixture supplies those IDs).
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any, cast

from jose import jwt

from core.core.config import settings

if TYPE_CHECKING:
    from httpx import AsyncClient


def make_tenant_headers(
    rsa_private_key: str, tenant_id: str, slug: str, *, sub: str | None = None
) -> dict[str, str]:
    """Build ``{X-Tenant-Slug, Authorization}`` for a signed access token.

    ``tenant_id`` must be the tenant's row UUID (from ``integration_db``);
    ``slug`` is the routing header the middleware uses to resolve it. ``sub``
    pins the token's user id - pass it to get a stable identity for permission
    seeding; defaults to a fresh random user (no grants).
    """
    now = int(time.time())
    payload = {
        "sub": sub or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "iss": settings.JWKS_ISSUER,
        "aud": settings.JWKS_AUDIENCE,
        "iat": now,
        "nbf": now - 10,
        "exp": now + 300,
        "type": "access",
    }
    token = jwt.encode(payload, rsa_private_key, algorithm="RS256")
    return {"X-Tenant-Slug": slug, "Authorization": f"Bearer {token}"}


async def hire_employee(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    first_name: str = "Ada",
    last_name: str = "Lovelace",
    job_title: str = "Engineer",
    hire_date: str = "2026-01-05",
    email: str | None = None,
    phone: str | None = None,
    monthly_salary: str | None = "5000.00",
    **overrides: Any,
) -> dict[str, Any]:
    """Create an employee; returns the ``data`` payload of the 201 response.

    ``monthly_salary=None`` omits salary so the employee is created without
    compensation (compensation is then recorded via ``POST /payroll/compensation``).
    Email/phone default to valid values because ``EmployeeCreate`` requires
    them; emails are unique per call so parallel hires never collide.
    """
    payload: dict[str, Any] = {
        "first_name": first_name,
        "last_name": last_name,
        "job_title": job_title,
        "hire_date": hire_date,
        "email": email
        or f"{first_name.lower()}.{last_name.lower()}.{uuid.uuid4().hex[:8]}@example.com",
        "phone": phone or "+1 555 010 0000",
    }
    if monthly_salary is not None:
        payload["monthly_salary"] = monthly_salary
    payload.update(overrides)
    response = await client.post("/api/v1/hr/employees", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json()["data"])


async def create_payroll_run(
    client: AsyncClient,
    headers: dict[str, str],
    period_start: str,
    period_end: str,
) -> dict[str, Any]:
    """Create a payroll run; returns the ``data`` payload of the 201 response."""
    response = await client.post(
        "/api/v1/payroll/runs",
        json={"period_start": period_start, "period_end": period_end},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return cast("dict[str, Any]", response.json()["data"])
