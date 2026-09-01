"""Product snapshot events — keeps the ai-agent embedding store in sync (SKY-70).

Two concerns ride on every product mutation:

1. Domain event: ``inventory.product.upserted`` / ``inventory.product.removed``
   envelopes through the process-wide producer (Phase 1 = structlog stub).
   The inventory service calls these AFTER the mutation transaction commits,
   so a rolled-back write can never emit a phantom event (same rule as
   ``stock_events``).

2. Post-commit HTTP dispatch: the same production also forwards the product's
   catalog snapshot (sku/name/category/unit) to the ai-agent
   ``POST /api/v1/ai/inventory/embeddings/sync`` endpoint so the searchable
   pgvector snapshot project lives independently of the core schema. Dispatch
   is BEST-EFFORT by design: it runs as a background task on the request loop
   and a failure is logged, never turned into a 500 — the write already
   committed. Recovery is the ``ai-agent inventory reindex`` CLI. Disabled
   when ``CORE_AI_SYNC_TOKEN`` (or the routed tenant slug) is absent.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import structlog

from core.core.config import settings
from core.core.tenant_context import TenantContext
from core.events.constants import INVENTORY_PRODUCT_REMOVED, INVENTORY_PRODUCT_UPSERTED
from core.events.producers import get_event_producer
from skyrict_events.base import BaseEvent

logger = structlog.get_logger("core.events.inventory")

_SYNC_PATH = "/api/v1/ai/inventory/embeddings/sync"


class ProductUpsertedEvent(BaseEvent):
    """Envelope for ``inventory.product.upserted``.

    Metadata carries the catalog snapshot text fields (sku/name/category/unit)
    — exactly the projection the ai-agent embedding row mirrors, and nothing
    more: cost/sell prices never leave the trust boundary via events (spec §5.5).
    """

    event_type: str = INVENTORY_PRODUCT_UPSERTED


class ProductRemovedEvent(BaseEvent):
    """Envelope for ``inventory.product.removed`` (product deactivated/archived)."""

    event_type: str = INVENTORY_PRODUCT_REMOVED


async def emit_inventory_product_upserted(
    *,
    tenant_id: str | uuid.UUID,
    product_id: str | uuid.UUID,
    sku: str,
    name: str,
    category: str | None,
    unit: str | None,
) -> None:
    """Publish a product upsert (create/update/reactivate) + sync the snapshot."""
    event = ProductUpsertedEvent(
        tenant_id=str(tenant_id),
        metadata={
            "product_id": str(product_id),
            "sku": sku,
            "name": name,
            "category": category,
            "unit": unit,
        },
    )
    get_event_producer().publish(INVENTORY_PRODUCT_UPSERTED, event, key=str(tenant_id))
    _spawn_sync_dispatch(
        {
            "upserts": [
                {
                    "product_id": str(product_id),
                    "sku": sku,
                    "name": name,
                    "category": category,
                    "unit": unit,
                }
            ],
            "removes": [],
        }
    )


async def emit_inventory_product_removed(
    *,
    tenant_id: str | uuid.UUID,
    product_id: str | uuid.UUID,
) -> None:
    """Publish a product removal (deactivate) + delete it from the snapshot."""
    event = ProductRemovedEvent(
        tenant_id=str(tenant_id),
        metadata={"product_id": str(product_id)},
    )
    get_event_producer().publish(INVENTORY_PRODUCT_REMOVED, event, key=str(tenant_id))
    _spawn_sync_dispatch({"upserts": [], "removes": [{"product_id": str(product_id)}]})


# ---------------------------------------------------------------------------
# Best-effort HTTP sync dispatch
# ---------------------------------------------------------------------------


def _spawn_sync_dispatch(payload: dict[str, Any]) -> None:
    """POST *payload* to ai-agent as a fire-and-forget background task.

    Skips when sync is disabled (empty token) or the routed tenant slug is
    unknown (e.g. an out-of-request emit); ai-agent resolves the tenant from
    the forwarded slug, never from the payload.
    """
    token = settings.AI_SYNC_TOKEN
    slug = TenantContext.get_tenant_slug()
    if not token or not slug:
        logger.debug(
            "inventory_product.sync_skipped",
            reason="sync token or tenant slug unavailable",
            tenant_id=TenantContext.get_optional(),
        )
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("inventory_product.sync_skipped", reason="no running loop")
        return
    task: asyncio.Task[object] = loop.create_task(
        _post_sync(
            payload=payload,
            sync_path=_SYNC_PATH,
            token=token,
            tenant_slug=slug,
        )
    )
    task.add_done_callback(_log_dispatch_failure)


def _log_dispatch_failure(task: asyncio.Task[object]) -> None:
    """Log (never raise) a failed background sync — the write already committed."""
    try:
        task.result()
    except Exception:
        logger.exception(
            "inventory_product.sync_failed",
            message="product embedding sync failed; recovery via `ai-agent inventory reindex`",
        )


async def _post_sync(
    *,
    payload: dict[str, Any],
    sync_path: str,
    token: str,
    tenant_slug: str,
) -> None:
    """POST one sync payload to ai-agent; httpx errors surface to the caller."""
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Slug": tenant_slug,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=settings.AI_AGENT_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{settings.AI_AGENT_URL.rstrip('/')}{sync_path}",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
