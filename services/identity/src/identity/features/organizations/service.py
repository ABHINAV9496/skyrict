"""Organization service — tenant CRUD business rules."""

from __future__ import annotations

from typing import TYPE_CHECKING

from identity.core.exceptions import TenantNotFoundError
from identity.models.tenant import TenantModel
from skyrict_common.exceptions import ValidationError

if TYPE_CHECKING:
    import uuid

    from identity.features.organizations.repository import TenantRepository
    from identity.features.organizations.schemas import TenantCreateRequest


class TenantService:
    """Encapsulates organization/tenant business rules."""

    def __init__(self, tenant_repo: TenantRepository) -> None:
        self.tenant_repo = tenant_repo

    async def get_organization(self, tenant_id: str | uuid.UUID) -> TenantModel:
        """Fetch a tenant, raising TenantNotFoundError when absent."""
        tenant = await self.tenant_repo.get_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Organization not found")
        return tenant

    async def create_organization(self, body: TenantCreateRequest) -> TenantModel:
        """Create a tenant, rejecting duplicate slugs."""
        if await self.tenant_repo.slug_exists(body.slug):
            raise ValidationError(f"Slug '{body.slug}' is already taken")

        tenant = TenantModel(name=body.name, slug=body.slug)
        await self.tenant_repo.create(tenant)
        return tenant
