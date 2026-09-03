"""/ai/inventory/embeddings/sync - machine-to-machine snapshot sync (SKY-70).

Core's post-commit product-change dispatch calls this endpoint for every
``inventory.product.upserted`` / ``.removed`` event. Unlike user-facing
routes, this is NOT a JWT flow: the caller is the core monolith, authenticated
by the shared secret ``AI_INVENTORY_SYNC_TOKEN`` (which must match core's
``CORE_AI_SYNC_TOKEN``). The tenant is the one routed by the middleware
(X-Tenant-Slug in dev/test, the tenant subdomain Host in production).

Authorization happened upstream (core emitted the events after the product
mutations committed); this endpoint only persists the snapshot mirror. A
missing/mismatched token is a 401, an unconfigured endpoint is a 503, and a
failed embed is a typed 503 the core dispatch loop logs and absorbs - sync is
best-effort by design, so the committed request never waits on it.
"""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_db
from ai_agent.api.v1.schemas.inventory_sync import (
    InventorySyncRequest,
    InventorySyncResponse,
)
from ai_agent.core.config import settings
from ai_agent.core.embedding import build_embedding_provider
from ai_agent.core.exceptions import AiUnavailableError, AuthenticationError
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.inventory_embedding_repository import InventoryEmbeddingRepository
from ai_agent.features.inventory_semantic.snapshot import (
    InventorySnapshotSyncService,
    ProductSnapshot,
)

router = APIRouter(prefix="/ai/inventory/embeddings", tags=["ai-inventory-sync"])


def require_sync_token(request: Request) -> None:
    """Dependency: the bearer must match AI_INVENTORY_SYNC_TOKEN exactly.

    Fails closed: an empty/invalid shared secret never processes a sync.
    """
    expected = settings.INVENTORY_SYNC_TOKEN
    if not expected:
        raise AiUnavailableError("Inventory embedding sync is not configured on this service")
    presented = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not presented or not hmac.compare_digest(presented, expected):
        raise AuthenticationError("Invalid sync token")


def _build_service(session: AsyncSession) -> InventorySnapshotSyncService:
    """Compose the snapshot writer for one sync (test-visible seam)."""
    return InventorySnapshotSyncService(
        embedding_provider=build_embedding_provider(settings),
        store=InventoryEmbeddingRepository(session),
    )


@router.post("/sync", response_model=InventorySyncResponse)
async def inventory_sync(
    body: InventorySyncRequest,
    _token: Annotated[None, Depends(require_sync_token)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InventorySyncResponse:
    """Apply one batch of product changes to the tenant's embedding snapshot.

    Bearer-token authenticated (service-to-service). The tenant is already
    resolved by the middleware into TenantContext; never taken from the body.
    """
    tenant_id = uuid.UUID(TenantContext.get())
    service = _build_service(session)
    report = await service.apply(
        tenant_id=tenant_id,
        upserts=[
            ProductSnapshot(
                product_id=item.product_id,
                sku=item.sku,
                name=item.name,
                category=item.category,
                unit=item.unit,
            )
            for item in body.upserts
        ],
        removes=[item.product_id for item in body.removes],
    )
    await session.commit()
    return InventorySyncResponse(
        upserts_applied=report.upserts_applied,
        removes_applied=report.removes_applied,
        skipped=report.skipped,
        model_used=report.model_used,
        dims=report.dims,
    )
