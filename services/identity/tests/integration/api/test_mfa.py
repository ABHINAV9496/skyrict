"""Integration tests for MFA enforcement (AUTH-TASK-035).

Proves the end-to-end contract over real Postgres:
  - Tenant owners are always forced to enroll: login is 200 with
    ``mfa_required``/``next_step``, and every other authenticated route returns
    403 until MFA is enabled.
  - TOTP setup/verify enables MFA; the same TOTP secret works at /users/me.
  - Tenant policy (``mfa_required_for_all_members``) extends the same forced
    enrollment + gate to ordinary members.
  - Backup codes enroll a user and are single-use.
  - Owner-assisted reset clears a member's MFA (forcing re-enrollment).
"""

from __future__ import annotations

import uuid

import pyotp
import pytest
from sqlalchemy import delete

from identity.db.session import async_session_factory
from identity.models.tenant import TenantModel
from tests.integration.api.wizard import provision_tenant

pytestmark = pytest.mark.integration


async def _register_org(client):
    tenant = await provision_tenant(
        client, email=f"mfa-{uuid.uuid4().hex[:8]}@test.com", org=f"MFA Corp {uuid.uuid4().hex[:8]}"
    )
    return {
        "tenant_slug": tenant["slug"],
        "tenant_id": tenant["tenant_id"],
        "email": tenant["email"],
    }


async def _verify_and_login(client, data):
    login = await client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": data["tenant_slug"]},
        json={"email": data["email"], "password": "TestPassword123!"},
    )
    assert login.status_code == 200
    return login.json()["data"]


async def _cleanup_tenant(slug: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.slug == slug))
        await session.commit()


class TestOwnerMfaFlow:
    async def test_owner_is_forced_to_enroll_then_unlocked(self, client) -> None:
        data = await _register_org(client)
        try:
            login = await _verify_and_login(client, data)
            assert login["mfa_required"] is True
            assert login["next_step"] == "mfa.setup"
            token = login["access_token"]
            headers = {"X-Tenant-Slug": data["tenant_slug"], "Authorization": f"Bearer {token}"}

            # Enforcement gate: authenticated routes are blocked until MFA is on.
            me = await client.get("/api/v1/users/me", headers=headers)
            assert me.status_code == 403
            assert me.json()["type"].endswith("/mfa-required")

            # Enrollment endpoints are exempt from the gate.
            setup = await client.post("/api/v1/mfa/setup", headers=headers)
            assert setup.status_code == 200
            setup_data = setup.json()["data"]
            assert len(setup_data["backup_codes"]) == 10
            assert setup_data["provisioning_uri"].startswith("otpauth://totp/")

            totp = pyotp.TOTP(setup_data["secret"]).now()
            verify = await client.post("/api/v1/mfa/verify", headers=headers, json={"code": totp})
            assert verify.status_code == 200
            assert verify.json()["data"]["method"] == "totp"

            # Re-login: MFA is now satisfied — no gate, no next step.
            relogin = await _verify_and_login(client, data)
            assert relogin["mfa_required"] is False
            assert relogin["next_step"] is None
            headers = {
                "X-Tenant-Slug": data["tenant_slug"],
                "Authorization": f"Bearer {relogin['access_token']}",
            }
            me = await client.get("/api/v1/users/me", headers=headers)
            assert me.status_code == 200
        finally:
            await _cleanup_tenant(data["tenant_slug"])

    async def test_owner_can_enable_tenant_wide_mfa_policy(self, client) -> None:
        data = await _register_org(client)
        try:
            login = await _verify_and_login(client, data)
            setup = await client.post(
                "/api/v1/mfa/setup",
                headers={
                    "X-Tenant-Slug": data["tenant_slug"],
                    "Authorization": f"Bearer {login['access_token']}",
                },
            )
            setup_data = setup.json()["data"]
            await client.post(
                "/api/v1/mfa/verify",
                headers={
                    "X-Tenant-Slug": data["tenant_slug"],
                    "Authorization": f"Bearer {login['access_token']}",
                },
                json={"code": pyotp.TOTP(setup_data["secret"]).now()},
            )
            relogin = await _verify_and_login(client, data)
            headers = {
                "X-Tenant-Slug": data["tenant_slug"],
                "Authorization": f"Bearer {relogin['access_token']}",
            }

            updated = await client.patch(
                f"/api/v1/tenants/{data['tenant_id']}/settings",
                headers=headers,
                json={"mfa_required_for_all_members": True},
            )
            assert updated.status_code == 200
            assert updated.json()["data"]["mfa_required_for_all_members"] is True

            me = await client.get("/api/v1/organizations/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["data"]["mfa_required_for_all_members"] is True
        finally:
            await _cleanup_tenant(data["tenant_slug"])


class TestMemberMfaPolicy:
    async def test_member_is_forced_when_policy_enforced_and_backup_code_is_single_use(
        self, client
    ) -> None:
        data = await _register_org(client)
        try:
            login = await _verify_and_login(client, data)
            owner_headers = {
                "X-Tenant-Slug": data["tenant_slug"],
                "Authorization": f"Bearer {login['access_token']}",
            }

            # Owner enables MFA and the tenant-wide policy.
            setup = await client.post("/api/v1/mfa/setup", headers=owner_headers)
            setup_data = setup.json()["data"]
            await client.post(
                "/api/v1/mfa/verify",
                headers=owner_headers,
                json={"code": pyotp.TOTP(setup_data["secret"]).now()},
            )
            await client.patch(
                f"/api/v1/tenants/{data['tenant_id']}/settings",
                headers=owner_headers,
                json={"mfa_required_for_all_members": True},
            )

            # Invite and accept a member (not an owner).
            invite_email = f"member-{uuid.uuid4().hex[:8]}@test.com"
            invite = await client.post(
                "/api/v1/invitations",
                headers=owner_headers,
                json={"email": invite_email, "role_name": "viewer"},
            )
            assert invite.status_code == 200
            invite_token = invite.json()["data"]["token"]

            accepted = await client.post(
                "/api/v1/invitations/accept",
                json={
                    "token": invite_token,
                    "email": invite_email,
                    "password": "TestPassword123!",
                    "full_name": "MFA Member",
                },
            )
            assert accepted.status_code == 200
            member_id = accepted.json()["data"]["id"]

            # Member login under the enforced policy: forced but not blocked.
            member_login = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": data["tenant_slug"]},
                json={"email": invite_email, "password": "TestPassword123!"},
            )
            assert member_login.status_code == 200
            member_body = member_login.json()["data"]
            assert member_body["mfa_required"] is True
            assert member_body["next_step"] == "mfa.setup"
            member_headers = {
                "X-Tenant-Slug": data["tenant_slug"],
                "Authorization": f"Bearer {member_body['access_token']}",
            }

            blocked = await client.get("/api/v1/users/me", headers=member_headers)
            assert blocked.status_code == 403
            assert blocked.json()["type"].endswith("/mfa-required")

            # Member enrolls using a backup code.
            member_setup = await client.post("/api/v1/mfa/setup", headers=member_headers)
            assert member_setup.status_code == 200
            backup_code = member_setup.json()["data"]["backup_codes"][0]
            member_verify = await client.post(
                "/api/v1/mfa/verify",
                headers=member_headers,
                json={"code": backup_code},
            )
            assert member_verify.status_code == 200
            assert member_verify.json()["data"]["method"] == "backup_code"

            # Same backup code is single-use: verification now fails.
            replay = await client.post(
                "/api/v1/mfa/verify",
                headers=member_headers,
                json={"code": backup_code},
            )
            assert replay.status_code == 403
            assert replay.json()["type"].endswith("/mfa-verification-error")

            member_relogin = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": data["tenant_slug"]},
                json={"email": invite_email, "password": "TestPassword123!"},
            )
            assert member_relogin.json()["data"]["mfa_required"] is False
            member_headers = {
                "X-Tenant-Slug": data["tenant_slug"],
                "Authorization": f"Bearer {member_relogin.json()['data']['access_token']}",
            }
            assert (await client.get("/api/v1/users/me", headers=member_headers)).status_code == 200

            # Owner-assisted reset clears the member's MFA — forced again.
            reset = await client.post(
                "/api/v1/mfa/reset",
                headers=owner_headers,
                json={"user_id": member_id},
            )
            assert reset.status_code == 200

            member_after_reset = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": data["tenant_slug"]},
                json={"email": invite_email, "password": "TestPassword123!"},
            )
            assert member_after_reset.json()["data"]["mfa_required"] is True
            assert member_after_reset.json()["data"]["next_step"] == "mfa.setup"
        finally:
            await _cleanup_tenant(data["tenant_slug"])


class TestMemberNotForcedWithoutPolicy:
    async def test_member_login_is_not_forced_when_policy_is_off(self, client) -> None:
        data = await _register_org(client)
        try:
            login = await _verify_and_login(client, data)
            owner_headers = {
                "X-Tenant-Slug": data["tenant_slug"],
                "Authorization": f"Bearer {login['access_token']}",
            }
            setup = await client.post("/api/v1/mfa/setup", headers=owner_headers)
            setup_data = setup.json()["data"]
            await client.post(
                "/api/v1/mfa/verify",
                headers=owner_headers,
                json={"code": pyotp.TOTP(setup_data["secret"]).now()},
            )

            invite_email = f"member-{uuid.uuid4().hex[:8]}@test.com"
            invite = await client.post(
                "/api/v1/invitations",
                headers=owner_headers,
                json={"email": invite_email, "role_name": "viewer"},
            )
            await client.post(
                "/api/v1/invitations/accept",
                json={
                    "token": invite.json()["data"]["token"],
                    "email": invite_email,
                    "password": "TestPassword123!",
                    "full_name": "MFA Member",
                },
            )

            member_login = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": data["tenant_slug"]},
                json={"email": invite_email, "password": "TestPassword123!"},
            )
            assert member_login.status_code == 200
            assert member_login.json()["data"]["mfa_required"] is False
            assert member_login.json()["data"]["next_step"] is None
        finally:
            await _cleanup_tenant(data["tenant_slug"])
