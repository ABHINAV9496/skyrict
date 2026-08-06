"""Integration coverage for the mfaToken login challenge flow."""

from __future__ import annotations

import uuid

import pyotp
import pytest
from sqlalchemy import delete

from identity.db.session import async_session_factory
from identity.models.tenant import TenantModel
from tests.integration.api.wizard import provision_tenant

pytestmark = pytest.mark.integration


async def _cleanup(slug: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.slug == slug))
        await session.commit()


async def _register_enrolled_org(client) -> dict:
    tenant = await provision_tenant(
        client,
        email=f"chal-{uuid.uuid4().hex[:8]}@test.com",
        org=f"Chal Corp {uuid.uuid4().hex[:8]}",
    )
    login = await client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": tenant["slug"]},
        json={"email": tenant["email"], "password": tenant["password"]},
    )
    assert login.status_code == 200
    data = login.json()["data"]
    headers = {"X-Tenant-Slug": tenant["slug"], "Authorization": f"Bearer {data['access_token']}"}

    setup = await client.post("/api/v1/mfa/setup", headers=headers)
    assert setup.status_code == 200
    setup_data = setup.json()["data"]
    verify = await client.post(
        "/api/v1/mfa/verify",
        headers=headers,
        json={"code": pyotp.TOTP(setup_data["secret"]).now()},
    )
    assert verify.status_code == 200

    return {
        "slug": tenant["slug"],
        "email": tenant["email"],
        "password": tenant["password"],
        "secret": setup_data["secret"],
        "backup_codes": setup_data["backup_codes"],
    }


async def _login_for_challenge(client, data: dict) -> dict:
    login = await client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": data["slug"]},
        json={"email": data["email"], "password": data["password"]},
    )
    assert login.status_code == 200
    return login.json()["data"]


async def _verify_challenge(client, data: dict, body: dict, code: str):
    return await client.post(
        "/api/v1/auth/mfa/verify",
        headers={"X-Tenant-Slug": data["slug"]},
        json={"mfa_token": body["mfa_token"], "code": code},
    )


class TestMfaChallengeFlow:
    async def test_login_issues_challenge_instead_of_tokens(self, client) -> None:
        data = await _register_enrolled_org(client)
        try:
            body = await _login_for_challenge(client, data)
            assert body["mfa_required"] is True
            assert body["next_step"] == "mfa.verify"
            assert body["mfa_token"]
            assert body["access_token"] is None
            assert body["refresh_token"] is None
        finally:
            await _cleanup(data["slug"])

    async def test_valid_totp_redeems_challenge(self, client) -> None:
        data = await _register_enrolled_org(client)
        try:
            body = await _login_for_challenge(client, data)
            redeem = await _verify_challenge(client, data, body, pyotp.TOTP(data["secret"]).now())
            assert redeem.status_code == 200
            tokens = redeem.json()["data"]
            assert tokens["access_token"]
            assert tokens["refresh_token"]
            me = await client.get(
                "/api/v1/users/me",
                headers={
                    "X-Tenant-Slug": data["slug"],
                    "Authorization": f"Bearer {tokens['access_token']}",
                },
            )
            assert me.status_code == 200
        finally:
            await _cleanup(data["slug"])

    async def test_backup_code_redeems_challenge(self, client) -> None:
        data = await _register_enrolled_org(client)
        try:
            body = await _login_for_challenge(client, data)
            redeem = await _verify_challenge(client, data, body, data["backup_codes"][0])
            assert redeem.status_code == 200
            assert redeem.json()["data"]["access_token"]
        finally:
            await _cleanup(data["slug"])

    async def test_challenge_is_single_use(self, client) -> None:
        data = await _register_enrolled_org(client)
        try:
            body = await _login_for_challenge(client, data)
            code = pyotp.TOTP(data["secret"]).now()
            first = await _verify_challenge(client, data, body, code)
            assert first.status_code == 200
            second = await _verify_challenge(client, data, body, code)
            assert second.status_code == 401
            assert second.json()["type"].endswith("/authentication-error")
        finally:
            await _cleanup(data["slug"])

    async def test_wrong_code_fails_uniformly(self, client) -> None:
        data = await _register_enrolled_org(client)
        try:
            body = await _login_for_challenge(client, data)
            wrong = await _verify_challenge(client, data, body, "000000")
            assert wrong.status_code == 401
            assert wrong.json()["type"].endswith("/authentication-error")
        finally:
            await _cleanup(data["slug"])

    async def test_exhausted_attempts_revoke_challenge(self, client) -> None:
        data = await _register_enrolled_org(client)
        try:
            body = await _login_for_challenge(client, data)
            for _ in range(5):
                attempt = await _verify_challenge(client, data, body, "000000")
                assert attempt.status_code == 401

            final = await _verify_challenge(client, data, body, pyotp.TOTP(data["secret"]).now())
            assert final.status_code == 401
        finally:
            await _cleanup(data["slug"])

    async def test_unknown_challenge_token_rejected(self, client) -> None:
        data = await _register_enrolled_org(client)
        try:
            unknown = await client.post(
                "/api/v1/auth/mfa/verify",
                headers={"X-Tenant-Slug": data["slug"]},
                json={"mfa_token": "no-such-token", "code": "123456"},
            )
            assert unknown.status_code == 401
            assert unknown.json()["type"].endswith("/authentication-error")
        finally:
            await _cleanup(data["slug"])
