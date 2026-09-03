"""
Shared MFA enrollment helper for API integration tests (AUTH-TASK-035).

The enforcement gate blocks a fresh tenant owner from every authenticated route
until MFA is set up. Tests that provision a new org and then call protected
endpoints must enroll MFA right after login. This helper runs the
setup -> TOTP verify dance and returns the access token.
"""

from __future__ import annotations

import pyotp


async def enroll_mfa_if_required(client, slug: str, login_data: dict) -> str:
    """
    Enroll MFA when login reports ``mfa_required``; otherwise no-op.

    The enforcement gate re-reads ``mfa_enabled`` from the database on every
    request, so the original access token stays valid once /mfa/verify
    succeeds - no re-login needed.
    """
    token = login_data["access_token"]
    if not login_data.get("mfa_required"):
        return token
    headers = {"X-Tenant-Slug": slug, "Authorization": f"Bearer {token}"}
    setup = await client.post("/api/v1/mfa/setup", headers=headers)
    assert setup.status_code == 200
    code = pyotp.TOTP(setup.json()["data"]["secret"]).now()
    verify = await client.post("/api/v1/mfa/verify", headers=headers, json={"code": code})
    assert verify.status_code == 200
    return token


async def mfa_challenge_login(client, *, slug: str, email: str, password: str, code: str) -> dict:
    login = await client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    data = login.json()["data"]
    assert data["mfa_required"] is True
    assert data["next_step"] == "mfa.verify"
    assert data["mfa_token"] is not None
    assert data["access_token"] is None
    verify = await client.post(
        "/api/v1/auth/mfa/verify",
        headers={"X-Tenant-Slug": slug},
        json={"mfa_token": data["mfa_token"], "code": code},
    )
    assert verify.status_code == 200, verify.text
    return verify.json()["data"]
