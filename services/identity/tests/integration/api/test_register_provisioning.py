"""Integration tests for self-service tenant provisioning (SKY-15).

Proves the atomic register contract: a successful request provisions tenant +
5 system roles + owner + grant; a mid-transaction failure leaves ZERO orphan
rows; and anti-enumeration returns an identical 200 for a taken email.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, func, select

from identity.db.session import async_session_factory
from identity.models.role import RoleModel
from identity.models.tenant import TenantModel
from identity.models.user import UserModel
from identity.models.user_role import UserRoleModel
from skyrict_common.exceptions import RateLimitExceededError
from tests.integration.api.mfa_helpers import enroll_mfa_if_required

if TYPE_CHECKING:
    from httpx import AsyncClient

SYSTEM_ROLE_NAMES = {
    "tenant_owner",
    "organization_admin",
    "department_manager",
    "standard_user",
    "auditor",
}

pytestmark = pytest.mark.integration


async def _register(client: AsyncClient, *, email: str | None = None, org: str | None = None):
    """Register a fresh tenant and return the raw response."""
    return await client.post(
        "/api/v1/auth/register",
        json={
            "email": email or f"prov-{uuid.uuid4().hex[:8]}@test.com",
            "password": "TestPassword123!",
            "full_name": "Provisioning User",
            "organization_name": org or f"Prov Corp {uuid.uuid4().hex[:8]}",
        },
    )


async def _cleanup_tenant(slug: str) -> None:
    """Remove a provisioned tenant (cascades to users/roles/grants/audit)."""
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.slug == slug))
        await session.commit()


class TestProvisioning:
    async def test_register_provisions_tenant_owner_and_five_system_roles(
        self, client: AsyncClient
    ) -> None:
        email = f"prov-{uuid.uuid4().hex[:8]}@test.com"
        org = f"Prov Corp {uuid.uuid4().hex[:8]}"
        response = await _register(client, email=email, org=org)
        assert response.status_code == 200
        data = response.json()["data"]
        slug = data["tenant_slug"]

        try:
            async with async_session_factory() as session:
                tenant = await session.scalar(select(TenantModel).where(TenantModel.slug == slug))
                assert tenant is not None
                assert tenant.name == org

                roles = (
                    await session.scalars(select(RoleModel).where(RoleModel.tenant_id == tenant.id))
                ).all()
                assert len(roles) == 5
                by_name = {role.name: role for role in roles}
                assert set(by_name) == SYSTEM_ROLE_NAMES
                assert all(role.is_system_role for role in roles)
                assert "*" in by_name["tenant_owner"].permissions

                user = await session.scalar(select(UserModel).where(UserModel.email == email))
                assert user is not None
                assert user.tenant_id == tenant.id
                assert user.is_verified is False

                grant = await session.scalar(
                    select(UserRoleModel).where(
                        UserRoleModel.user_id == user.id,
                        UserRoleModel.role_id == by_name["tenant_owner"].id,
                    )
                )
                assert grant is not None
                assert grant.scope_id == tenant.id
        finally:
            await _cleanup_tenant(slug)

    async def test_register_failure_leaves_no_orphan_rows(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from identity.features.roles.repository import RoleRepository

        async def boom(self: RoleRepository, role: object) -> object:
            raise RuntimeError("simulated mid-transaction failure")

        monkeypatch.setattr(RoleRepository, "create", boom)

        email = f"prov-{uuid.uuid4().hex[:8]}@test.com"
        org = f"Prov Corp {uuid.uuid4().hex[:8]}"
        slug = org.lower().replace(" ", "-")

        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "TestPassword123!",
                "full_name": "Provisioning User",
                "organization_name": org,
            },
        )
        assert response.status_code == 500

        async with async_session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(TenantModel).where(TenantModel.slug == slug)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(UserModel).where(UserModel.email == email)
                )
                == 0
            )

    async def test_duplicate_email_returns_identical_200(self, client: AsyncClient) -> None:
        email = f"prov-{uuid.uuid4().hex[:8]}@test.com"
        first = await _register(client, email=email)
        assert first.status_code == 200
        second = await _register(client, email=email)
        assert second.status_code == 200

        d1 = first.json()["data"]
        d2 = second.json()["data"]
        # No existence leak: same shape, no 409, no error detail.
        assert d1["email"] == d2["email"] == email
        assert d1["verification_pending"] is True
        assert d2["verification_pending"] is True
        assert d1["tenant_slug"] != d2["tenant_slug"]

        await _cleanup_tenant(d1["tenant_slug"])
        await _cleanup_tenant(d2["tenant_slug"])

    async def test_unverified_login_blocked_until_verified(self, client: AsyncClient) -> None:
        response = await _register(client)
        data = response.json()["data"]
        slug = data["tenant_slug"]
        email = data["email"]
        try:
            blocked = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"email": email, "password": "TestPassword123!"},
            )
            assert blocked.status_code == 403
            assert blocked.json()["type"].endswith("/email-not-verified")

            verified = await client.post(
                "/api/v1/auth/verify-email", json={"token": data["verification_token"]}
            )
            assert verified.status_code == 200

            # verify-email is idempotent.
            verified_again = await client.post(
                "/api/v1/auth/verify-email", json={"token": data["verification_token"]}
            )
            assert verified_again.status_code == 200

            login = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"email": email, "password": "TestPassword123!"},
            )
            assert login.status_code == 200
        finally:
            await _cleanup_tenant(slug)


class TestAuthPosture:
    async def test_mfa_required_for_tenant_owner_without_mfa(self, client: AsyncClient) -> None:
        response = await _register(client)
        data = response.json()["data"]
        slug = data["tenant_slug"]
        email = data["email"]
        try:
            await client.post(
                "/api/v1/auth/verify-email", json={"token": data["verification_token"]}
            )
            login = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"email": email, "password": "TestPassword123!"},
            )
            assert login.status_code == 200
            assert login.json()["data"]["mfa_required"] is True
            assert login.json()["data"]["access_token"]
        finally:
            await _cleanup_tenant(slug)


class TestCustomRoles:
    async def test_create_and_list_custom_role(self, client: AsyncClient) -> None:
        response = await _register(client)
        data = response.json()["data"]
        slug = data["tenant_slug"]
        email = data["email"]
        try:
            await client.post(
                "/api/v1/auth/verify-email", json={"token": data["verification_token"]}
            )
            login = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"email": email, "password": "TestPassword123!"},
            )
            token = await enroll_mfa_if_required(client, slug=slug, login_data=login.json()["data"])
            headers = {"X-Tenant-Slug": slug, "Authorization": f"Bearer {token}"}

            created = await client.post(
                "/api/v1/roles",
                headers=headers,
                json={"name": "custom_ops", "permission_keys": ["users:read", "audit:read"]},
            )
            assert created.status_code == 200
            created_data = created.json()["data"]
            assert created_data["name"] == "custom_ops"
            assert created_data["is_system_role"] is False

            listed = await client.get("/api/v1/roles", headers=headers)
            assert listed.status_code == 200
            names = {role["name"] for role in listed.json()["data"]}
            assert "custom_ops" in names
            assert names >= SYSTEM_ROLE_NAMES

            # Reserved system names are rejected for custom roles.
            reserved = await client.post(
                "/api/v1/roles",
                headers=headers,
                json={"name": "tenant_owner", "permission_keys": ["users:read"]},
            )
            assert reserved.status_code == 422
        finally:
            await _cleanup_tenant(slug)


class TestRateLimit:
    async def test_register_rate_limited(self, client: AsyncClient) -> None:
        from identity.api.deps import get_rate_limiter
        from identity.main import app

        class DenyLimiter:
            async def enforce(self, *, key: str, limit: int, window_seconds: int) -> None:
                raise RateLimitExceededError("rate limited")

        app.dependency_overrides[get_rate_limiter] = lambda: DenyLimiter()
        try:
            response = await _register(client)
            assert response.status_code == 429
            assert response.json()["type"].endswith("/rate-limit-exceeded")
        finally:
            app.dependency_overrides.pop(get_rate_limiter, None)
