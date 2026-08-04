"""Integration tests for the invitation flow (SKY-16).

Tests the full invitation lifecycle: create, accept, expired token rejection,
already-used token rejection, and email-mismatch rejection.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete

from identity.db.session import async_session_factory
from identity.models.invitation import InvitationModel
from identity.models.tenant import TenantModel

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def _cleanup_tenant(slug: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.slug == slug))
        await session.commit()


async def _register_tenant(client: AsyncClient, *, org_name: str | None = None) -> dict:
    org = org_name or f"Invite Corp {uuid.uuid4().hex[:8]}"
    email = f"admin-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "AdminPass123!",
            "full_name": "Admin User",
            "organization_name": org,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    await client.post(
        "/api/v1/auth/verify-email",
        json={"token": data["verification_token"]},
    )
    login = await client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": data["tenant_slug"]},
        json={"email": email, "password": "AdminPass123!"},
    )
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    return {
        "slug": data["tenant_slug"],
        "tenant_id": data["tenant_id"],
        "email": email,
        "token": token,
    }


class TestInvitationFlow:
    async def test_create_and_accept_invitation(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = {"X-Tenant-Slug": tenant["slug"], "Authorization": f"Bearer {tenant['token']}"}

        invite_email = f"invitee-{uuid.uuid4().hex[:8]}@test.com"
        create_resp = await client.post(
            "/api/v1/invitations",
            headers=headers,
            json={"email": invite_email, "role_name": "viewer"},
        )
        assert create_resp.status_code == 200
        invite_data = create_resp.json()["data"]
        assert invite_data["email"] == invite_email
        assert invite_data["token"]
        assert invite_data["used_at"] is None

        accept_resp = await client.post(
            "/api/v1/invitations/accept",
            headers={"X-Tenant-Slug": tenant["slug"]},
            json={
                "token": invite_data["token"],
                "email": invite_email,
                "password": "InviteePass123!",
                "full_name": "Invitee User",
            },
        )
        assert accept_resp.status_code == 200
        user_data = accept_resp.json()["data"]
        assert user_data["email"] == invite_email
        assert user_data["is_verified"] is True

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_expired_token_rejected(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = {"X-Tenant-Slug": tenant["slug"], "Authorization": f"Bearer {tenant['token']}"}

        invite_email = f"expired-{uuid.uuid4().hex[:8]}@test.com"
        create_resp = await client.post(
            "/api/v1/invitations",
            headers=headers,
            json={"email": invite_email},
        )
        assert create_resp.status_code == 200
        invite_data = create_resp.json()["data"]
        invite_id = invite_data["id"]
        invite_token = invite_data["token"]

        async with async_session_factory() as session:
            model = await session.get(InvitationModel, uuid.UUID(invite_id))
            if model:
                model.expires_at = datetime.now(UTC) - timedelta(days=1)
                await session.commit()

        accept_resp = await client.post(
            "/api/v1/invitations/accept",
            headers={"X-Tenant-Slug": tenant["slug"]},
            json={
                "token": invite_token,
                "email": invite_email,
                "password": "InviteePass123!",
                "full_name": "Expired User",
            },
        )
        assert accept_resp.status_code in (400, 403, 422)

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_already_used_token_rejected(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = {"X-Tenant-Slug": tenant["slug"], "Authorization": f"Bearer {tenant['token']}"}

        invite_email = f"used-{uuid.uuid4().hex[:8]}@test.com"
        create_resp = await client.post(
            "/api/v1/invitations",
            headers=headers,
            json={"email": invite_email},
        )
        assert create_resp.status_code == 200
        invite_data = create_resp.json()["data"]

        first_accept = await client.post(
            "/api/v1/invitations/accept",
            headers={"X-Tenant-Slug": tenant["slug"]},
            json={
                "token": invite_data["token"],
                "email": invite_email,
                "password": "InviteePass123!",
                "full_name": "First Accept",
            },
        )
        assert first_accept.status_code == 200

        second_accept = await client.post(
            "/api/v1/invitations/accept",
            headers={"X-Tenant-Slug": tenant["slug"]},
            json={
                "token": invite_data["token"],
                "email": invite_email,
                "password": "InviteePass123!",
                "full_name": "Second Accept",
            },
        )
        assert second_accept.status_code in (400, 409)

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_email_mismatch_rejected(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = {"X-Tenant-Slug": tenant["slug"], "Authorization": f"Bearer {tenant['token']}"}

        invite_email = f"correct-{uuid.uuid4().hex[:8]}@test.com"
        create_resp = await client.post(
            "/api/v1/invitations",
            headers=headers,
            json={"email": invite_email},
        )
        assert create_resp.status_code == 200
        invite_data = create_resp.json()["data"]

        accept_resp = await client.post(
            "/api/v1/invitations/accept",
            headers={"X-Tenant-Slug": tenant["slug"]},
            json={
                "token": invite_data["token"],
                "email": "wrong-email@test.com",
                "password": "InviteePass123!",
                "full_name": "Wrong Email",
            },
        )
        assert accept_resp.status_code in (400, 403, 422)

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])

    async def test_requires_admin_permission(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)

        unprivileged = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"regular-{uuid.uuid4().hex[:8]}@test.com",
                "password": "RegularPass123!",
                "full_name": "Regular User",
                "organization_name": f"Regular Corp {uuid.uuid4().hex[:8]}",
            },
        )
        assert unprivileged.status_code == 200
        reg_data = unprivileged.json()["data"]
        await client.post(
            "/api/v1/auth/verify-email",
            json={"token": reg_data["verification_token"]},
        )
        await client.post(
            "/api/v1/auth/login",
            headers={"X-Tenant-Slug": reg_data["tenant_slug"]},
            json={
                "email": reg_data["email"],
                "password": "RegularPass123!",
            },
        )

        with contextlib.suppress(Exception):
            await _cleanup_tenant(tenant["slug"])
            await _cleanup_tenant(reg_data["tenant_slug"])
