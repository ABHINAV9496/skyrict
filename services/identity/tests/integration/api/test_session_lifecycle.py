from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, select

from identity.db.session import async_session_factory
from identity.models.audit_log import AuditLogModel
from identity.models.tenant import TenantModel

if TYPE_CHECKING:
    from httpx import AsyncClient


async def _delete_tenant_by_slug(slug: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.slug == slug))
        await session.commit()


async def _provision(client: AsyncClient) -> tuple[str, str]:
    email = f"session-{uuid.uuid4().hex[:8]}@test.com"
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "TestPassword123!",
            "full_name": "Session User",
            "organization_name": f"Session Org {uuid.uuid4().hex[:8]}",
        },
    )
    assert register.status_code == 200
    data = register.json()["data"]
    verify = await client.post(
        "/api/v1/auth/verify-email", json={"token": data["verification_token"]}
    )
    assert verify.status_code == 200
    return data["tenant_slug"], email


async def _login(client: AsyncClient, *, slug: str, email: str) -> tuple[str, str, str]:
    login = await client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"email": email, "password": "TestPassword123!"},
    )
    assert login.status_code == 200
    data = login.json()["data"]
    return str(data["user"]["id"]), data["access_token"], data["refresh_token"]


async def _list_sessions(client: AsyncClient, *, slug: str, access_token: str) -> list[dict]:
    response = await client.get(
        "/api/v1/sessions",
        headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    return response.json()["data"]["sessions"]


async def _refresh(client: AsyncClient, *, slug: str, refresh_token: str):
    return await client.post(
        "/api/v1/auth/refresh",
        headers={"X-Tenant-Slug": slug},
        json={"refresh_token": refresh_token},
    )


@pytest.mark.integration
class TestSessionLifecycle:
    async def test_login_creates_session_listed_with_device_fields(
        self, client: AsyncClient
    ) -> None:
        slug, email = await _provision(client)
        user_id, access, _ = await _login(client, slug=slug, email=email)
        try:
            sessions = await _list_sessions(client, slug=slug, access_token=access)

            assert len(sessions) == 1
            session = sessions[0]
            assert session["user_id"] == user_id
            assert session["is_active"] is True
            assert session["last_active_at"]
            assert session["user_agent"]
        finally:
            await _delete_tenant_by_slug(slug)

    async def test_old_refresh_token_reuse_kills_the_session_chain(
        self, client: AsyncClient
    ) -> None:
        slug, email = await _provision(client)
        user_id, access, refresh = await _login(client, slug=slug, email=email)
        try:
            first = await _refresh(client, slug=slug, refresh_token=refresh)
            assert first.status_code == 200
            assert first.json()["data"]["refresh_token"] != refresh

            reuse = await _refresh(client, slug=slug, refresh_token=refresh)
            assert reuse.status_code == 401
            assert reuse.json()["type"].endswith("/token-reuse-detected")

            assert await _list_sessions(client, slug=slug, access_token=access) == []

            async with async_session_factory() as session:
                row = await session.scalar(
                    select(AuditLogModel).where(
                        AuditLogModel.action == "auth.refresh.reuse_detected",
                        AuditLogModel.actor_user_id == uuid.UUID(user_id),
                    )
                )
                assert row is not None
        finally:
            await _delete_tenant_by_slug(slug)

    async def test_logout_revokes_only_the_matching_session(self, client: AsyncClient) -> None:
        slug, email = await _provision(client)
        _, access_a, refresh_a = await _login(client, slug=slug, email=email)
        _, access_b, _ = await _login(client, slug=slug, email=email)
        try:
            assert len(await _list_sessions(client, slug=slug, access_token=access_a)) == 2

            logout = await client.post(
                "/api/v1/auth/logout",
                headers={
                    "X-Tenant-Slug": slug,
                    "Authorization": f"Bearer {access_a}",
                },
                json={"refresh_token": refresh_a},
            )
            assert logout.status_code == 200

            sessions = await _list_sessions(client, slug=slug, access_token=access_b)
            assert len(sessions) == 1

            reuse = await _refresh(client, slug=slug, refresh_token=refresh_a)
            assert reuse.status_code == 401
            assert reuse.json()["type"].endswith("/token-reuse-detected")
        finally:
            await _delete_tenant_by_slug(slug)

    async def test_revoke_session_by_id_and_foreign_id_404(self, client: AsyncClient) -> None:
        slug, email = await _provision(client)
        _, access_a, _ = await _login(client, slug=slug, email=email)
        _, access_b, _ = await _login(client, slug=slug, email=email)
        try:
            sessions = await _list_sessions(client, slug=slug, access_token=access_a)
            assert len(sessions) == 2
            victim_id = sessions[0]["id"]

            foreign = await client.delete(
                f"/api/v1/sessions/{uuid.uuid4()}",
                headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {access_a}"},
            )
            assert foreign.status_code == 404

            revoke = await client.delete(
                f"/api/v1/sessions/{victim_id}",
                headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {access_a}"},
            )
            assert revoke.status_code == 200

            remaining = await _list_sessions(client, slug=slug, access_token=access_b)
            assert len(remaining) == 1
        finally:
            await _delete_tenant_by_slug(slug)
