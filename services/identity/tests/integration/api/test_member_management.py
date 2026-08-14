"""
Integration tests for member management (list, change role, remove).

Covers the full lifecycle: the owner shows in the member list, an invited
member appears with their role, a role change persists, removal deactivates
the account, and the last-owner + permission guards hold.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete

from identity.db.session import async_session_factory
from identity.models.tenant import TenantModel
from identity.models.user import UserModel
from tests.integration.api.mfa_helpers import enroll_mfa_if_required
from tests.integration.api.wizard import provision_tenant, wizard_login

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def _cleanup_tenant(slug: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.slug == slug))
        await session.commit()


async def _register_tenant(client: AsyncClient) -> dict:
    tenant = await provision_tenant(client)
    creds = await wizard_login(
        client, slug=tenant["slug"], email=tenant["email"], password=tenant["password"]
    )
    return {
        "slug": tenant["slug"],
        "email": tenant["email"],
        "token": creds["token"],
        "user_id": creds["user_id"],
    }


def _member_row(payload: dict, email: str) -> dict | None:
    return next((row for row in payload["data"] if row["email"] == email), None)


async def _invite_and_accept(client: AsyncClient, *, slug: str, owner_headers: dict) -> dict:
    """Create + accept an invitation and return the new member's auth context."""
    invite_email = f"member-{uuid.uuid4().hex[:8]}@test.com"
    create_resp = await client.post(
        "/api/v1/invitations",
        headers=owner_headers,
        json={"email": invite_email, "role_name": "standard_user"},
    )
    assert create_resp.status_code == 200
    invite_token = create_resp.json()["data"]["token"]

    accept_resp = await client.post(
        "/api/v1/invitations/accept",
        headers={"X-Tenant-Slug": slug},
        data={
            "token": invite_token,
            "email": invite_email,
            "password": "InviteePass123!",
            "full_name": "Team Member",
        },
    )
    assert accept_resp.status_code == 200
    member_user_id = accept_resp.json()["data"]["id"]

    login = await client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"email": invite_email, "password": "InviteePass123!"},
    )
    assert login.status_code == 200
    token = await enroll_mfa_if_required(client, slug=slug, login_data=login.json()["data"])
    return {
        "email": invite_email,
        "user_id": member_user_id,
        "token": token,
        "headers": {"X-Tenant-Slug": slug, "Authorization": f"Bearer {token}"},
    }


class TestListMembers:
    async def test_owner_is_listed_with_role_and_self_flag(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = {"X-Tenant-Slug": tenant["slug"], "Authorization": f"Bearer {tenant['token']}"}

        resp = await client.get("/api/v1/members", headers=headers)
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["data"], "the owner must always appear in the member list"

        owner = _member_row(payload, tenant["email"])
        assert owner is not None
        assert owner["role_name"] == "tenant_owner"
        assert owner["is_self"] is True
        assert owner["full_name"] == "Wizard Owner"
        assert owner["joined_at"] is not None

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_every_standard_user_can_read_members(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        resp = await client.get("/api/v1/members", headers=member["headers"])
        assert resp.status_code == 200
        assert _member_row(resp.json(), member["email"]) is not None

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])


class TestChangeRole:
    async def test_admin_can_change_a_members_role(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        update_resp = await client.patch(
            f"/api/v1/members/{member['user_id']}/role",
            headers=owner_headers,
            json={"role_name": "department_manager"},
        )
        assert update_resp.status_code == 200

        listed = await client.get("/api/v1/members", headers=owner_headers)
        row = _member_row(listed.json(), member["email"])
        assert row is not None and row["role_name"] == "department_manager"

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_unknown_role_rejected(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        resp = await client.patch(
            f"/api/v1/members/{member['user_id']}/role",
            headers=owner_headers,
            json={"role_name": "ghost_role"},
        )
        assert resp.status_code == 422

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_last_owner_cannot_be_demoted(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }

        resp = await client.patch(
            f"/api/v1/members/{tenant['user_id']}/role",
            headers=owner_headers,
            json={"role_name": "standard_user"},
        )
        assert resp.status_code == 422

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_standard_user_cannot_change_roles(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        resp = await client.patch(
            f"/api/v1/members/{member['user_id']}/role",
            headers=member["headers"],
            json={"role_name": "department_manager"},
        )
        assert resp.status_code == 403

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])


class TestRemoveMember:
    async def test_admin_can_remove_a_member(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        remove_resp = await client.delete(
            f"/api/v1/members/{member['user_id']}", headers=owner_headers
        )
        assert remove_resp.status_code == 200

        listed = await client.get("/api/v1/members", headers=owner_headers)
        assert _member_row(listed.json(), member["email"]) is None

        async with async_session_factory() as session:
            user = await session.get(UserModel, uuid.UUID(member["user_id"]))
            assert user is not None
            assert user.is_active is False

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_last_owner_cannot_be_removed(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }

        resp = await client.delete(f"/api/v1/members/{tenant['user_id']}", headers=owner_headers)
        assert resp.status_code == 422

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_standard_user_cannot_remove_members(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        resp = await client.delete(
            f"/api/v1/members/{tenant['user_id']}", headers=member["headers"]
        )
        assert resp.status_code == 403

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])


class TestMemberSessions:
    async def test_admin_can_list_member_sessions(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        resp = await client.get(
            f"/api/v1/members/{member['user_id']}/sessions", headers=owner_headers
        )
        assert resp.status_code == 200
        payload = resp.json()["data"]
        assert payload["total"] >= 1, "the member's login must leave an active session"
        session = payload["sessions"][0]
        assert session["status"] == "active"
        assert session["device"] is not None
        assert session["is_trusted"] in (True, False)
        assert session["last_active_at"] is not None

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_admin_can_revoke_a_single_member_session(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        listed = await client.get(
            f"/api/v1/members/{member['user_id']}/sessions", headers=owner_headers
        )
        session_id = listed.json()["data"]["sessions"][0]["id"]

        revoke = await client.delete(
            f"/api/v1/members/{member['user_id']}/sessions/{session_id}",
            headers=owner_headers,
        )
        assert revoke.status_code == 200

        re_listed = await client.get(
            f"/api/v1/members/{member['user_id']}/sessions", headers=owner_headers
        )
        ids = [s["id"] for s in re_listed.json()["data"]["sessions"]]
        assert session_id not in ids

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_admin_can_revoke_all_member_sessions(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        revoke = await client.delete(
            f"/api/v1/members/{member['user_id']}/sessions", headers=owner_headers
        )
        assert revoke.status_code == 200

        listed = await client.get(
            f"/api/v1/members/{member['user_id']}/sessions", headers=owner_headers
        )
        assert listed.json()["data"]["total"] == 0

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_owner_cannot_log_self_out_of_all_devices(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }

        resp = await client.delete(
            f"/api/v1/members/{tenant['user_id']}/sessions", headers=owner_headers
        )
        assert resp.status_code == 422

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_standard_user_cannot_list_or_revoke_member_sessions(
        self, client: AsyncClient
    ) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        listed = await client.get(
            f"/api/v1/members/{tenant['user_id']}/sessions", headers=member["headers"]
        )
        assert listed.status_code == 403

        revoked = await client.delete(
            f"/api/v1/members/{tenant['user_id']}/sessions", headers=member["headers"]
        )
        assert revoked.status_code == 403

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_department_manager_can_view_but_not_revoke_sessions(
        self, client: AsyncClient
    ) -> None:
        tenant = await _register_tenant(client)
        owner_headers = {
            "X-Tenant-Slug": tenant["slug"],
            "Authorization": f"Bearer {tenant['token']}",
        }
        member = await _invite_and_accept(client, slug=tenant["slug"], owner_headers=owner_headers)

        update_resp = await client.patch(
            f"/api/v1/members/{member['user_id']}/role",
            headers=owner_headers,
            json={"role_name": "department_manager"},
        )
        assert update_resp.status_code == 200

        listed = await client.get(
            f"/api/v1/members/{tenant['user_id']}/sessions", headers=member["headers"]
        )
        assert listed.status_code == 200

        revoked = await client.delete(
            f"/api/v1/members/{tenant['user_id']}/sessions", headers=member["headers"]
        )
        assert revoked.status_code == 403

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])
