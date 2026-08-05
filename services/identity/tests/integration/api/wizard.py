"""Shared helpers for provisioning tenants through the onboarding wizard.

The wizard (SKY-30) replaced one-shot ``POST /auth/register`` with five steps
that each run in the request session. These helpers drive the real HTTP
contract — camelCase bodies, camelCase wizard responses — so integration tests
exercise the exact wire format the web app sends.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from tests.integration.api.mfa_helpers import enroll_mfa_if_required

if TYPE_CHECKING:
    from httpx import AsyncClient

DEFAULT_PASSWORD = "TestPassword123!"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or f"ws-{uuid.uuid4().hex[:8]}"


async def wizard_start(client: AsyncClient, *, email: str) -> None:
    resp = await client.post("/api/v1/auth/signup/start", json={"email": email})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "ok"


async def wizard_send_code(client: AsyncClient, *, email: str) -> str:
    resp = await client.post("/api/v1/auth/signup/send-code", json={"email": email})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["code"] is not None, "test env must return the plaintext code"
    return data["code"]


async def wizard_verify_code(client: AsyncClient, *, email: str, code: str) -> str:
    resp = await client.post("/api/v1/auth/signup/verify-code", json={"email": email, "code": code})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "ok"
    assert data["verificationToken"]
    return data["verificationToken"]


async def wizard_set_password(
    client: AsyncClient, *, email: str, verification_token: str, password: str
) -> None:
    resp = await client.post(
        "/api/v1/auth/signup/password",
        json={
            "email": email,
            "verificationToken": verification_token,
            "password": password,
        },
    )
    assert resp.status_code == 200, resp.text


async def wizard_create_organization(
    client: AsyncClient,
    *,
    email: str,
    verification_token: str,
    password: str,
    org: str,
    slug: str,
    plan_id: str = "professional",
) -> dict:
    resp = await client.post(
        "/api/v1/auth/signup/organization",
        json={
            "email": email,
            "verificationToken": verification_token,
            "planId": plan_id,
            "companyName": org,
            "industry": "Technology",
            "workspaceSlug": slug,
            "ownerFullName": "Wizard Owner",
            "phoneCountry": "US",
            "phoneNumber": "555-0134",
            "address": {
                "country": "US",
                "addressLine1": "100 Market Street",
                "city": "San Francisco",
                "state": "CA",
                "postalCode": "94103",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "ok"
    assert data["mfaRequired"] is True
    assert data["tenantSlug"] == slug
    return data


async def provision_tenant(
    client: AsyncClient,
    *,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    org: str | None = None,
    slug: str | None = None,
    plan_id: str = "professional",
) -> dict:
    """Run the full 5-step wizard and return the provisioned tenant."""
    email = email or f"wizard-{uuid.uuid4().hex[:8]}@test.com"
    org = org or f"Wizard Corp {uuid.uuid4().hex[:8]}"
    slug = slug or _slugify(org)

    await wizard_start(client, email=email)
    code = await wizard_send_code(client, email=email)
    vt = await wizard_verify_code(client, email=email, code=code)
    await wizard_set_password(client, email=email, verification_token=vt, password=password)
    data = await wizard_create_organization(
        client,
        email=email,
        verification_token=vt,
        password=password,
        org=org,
        slug=slug,
        plan_id=plan_id,
    )

    return {
        "slug": data["tenantSlug"],
        "tenant_id": data["tenantId"],
        "email": email,
        "password": password,
        "verification_token": vt,
    }


async def wizard_login(
    client: AsyncClient, *, slug: str, email: str, password: str = DEFAULT_PASSWORD
) -> dict:
    """Login as the tenant owner and return routed credentials + tokens."""
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["mfa_required"] is True
    token = await enroll_mfa_if_required(client, slug=slug, login_data=data)
    return {
        "token": token,
        "refresh_token": data["refresh_token"],
        "user_id": str(data["user"]["id"]),
    }
