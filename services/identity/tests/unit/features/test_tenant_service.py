"""Unit tests for the organizations feature service (fake TenantRepositoryPort)."""

from __future__ import annotations

import uuid

import pytest

from identity.core.exceptions import TenantNotFoundError
from identity.domain.entities import Tenant
from identity.features.organizations.schemas import TenantCreateRequest
from identity.features.organizations.service import TenantService
from skyrict_common.exceptions import ValidationError


class FakeTenantRepo:
    """In-memory TenantRepositoryPort double."""

    def __init__(self, tenants: list[Tenant] | None = None) -> None:
        self.tenants: dict[uuid.UUID, Tenant] = {}
        for tenant in tenants or []:
            if tenant.id is None:
                tenant.id = uuid.uuid4()
            self.tenants[tenant.id] = tenant
        self.created: list[Tenant] = []

    async def get_by_id(self, tenant_id: str | uuid.UUID) -> Tenant | None:
        return self.tenants.get(uuid.UUID(str(tenant_id)))

    async def get_by_slug(self, slug: str) -> Tenant | None:
        for tenant in self.tenants.values():
            if tenant.slug == slug:
                return tenant
        return None

    async def slug_exists(self, slug: str) -> bool:
        return await self.get_by_slug(slug) is not None

    async def create(self, tenant: Tenant) -> Tenant:
        tenant.id = uuid.uuid4()
        self.tenants[tenant.id] = tenant
        self.created.append(tenant)
        return tenant

    async def mark_onboarding_complete(self, tenant_id: str | uuid.UUID) -> Tenant:
        tenant = await self.get_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Organization not found")
        return tenant


class TestGetOrganization:
    async def test_returns_tenant_when_found(self) -> None:
        tenant = Tenant(name="Acme", slug="acme")
        repo = FakeTenantRepo([tenant])
        service = TenantService(repo)

        assert await service.get_organization(str(tenant.id)) is tenant

    async def test_raises_when_missing(self) -> None:
        service = TenantService(FakeTenantRepo())

        with pytest.raises(TenantNotFoundError):
            await service.get_organization(uuid.uuid4())


class TestCreateOrganization:
    async def test_rejects_duplicate_slug(self) -> None:
        existing = Tenant(name="Acme", slug="acme")
        repo = FakeTenantRepo([existing])
        service = TenantService(repo)

        with pytest.raises(ValidationError):
            await service.create_organization(TenantCreateRequest(name="Acme 2", slug="acme"))

        assert repo.created == []

    async def test_creates_tenant_when_slug_is_free(self) -> None:
        repo = FakeTenantRepo()
        service = TenantService(repo)

        tenant = await service.create_organization(TenantCreateRequest(name="Acme", slug="acme"))

        assert tenant.name == "Acme"
        assert tenant.slug == "acme"
        assert tenant.id is not None
        assert tenant.is_active is True
        assert repo.created == [tenant]


class TestCompleteOnboarding:
    async def test_delegates_to_repo_and_returns_tenant(self) -> None:
        tenant = Tenant(name="Acme", slug="acme")
        repo = FakeTenantRepo([tenant])
        service = TenantService(repo)

        completed = await service.complete_onboarding(str(tenant.id))

        assert completed is tenant

    async def test_raises_when_missing(self) -> None:
        service = TenantService(FakeTenantRepo())

        with pytest.raises(TenantNotFoundError):
            await service.complete_onboarding(uuid.uuid4())
