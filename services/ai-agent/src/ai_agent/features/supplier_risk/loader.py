"""Supplier catalog + performance loader (SKY-86 / INV-AI-004).

Fetches the supplier master rows a tenant may grade, page by page, from the
core monolith's ``/api/v1/inventory/suppliers`` endpoint, then pulls each
supplier's grading-period facts from ``/suppliers/{id}/performance``. Only the
fields the risk engine needs pass through (id, name, lead_time_days and the
raw performance metrics) - money/PII never leave the trust boundary.

Uses the ingest service token (AI_INGEST_TOKEN) as bearer (the core supplier
read routes accept the same m2m secret as the product catalog), mirroring the
``ProductSnapshotLoader`` the ``inventory reindex`` CLI uses (SKY-70).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import structlog

from ai_agent.core.core_http import CoreHttpTransport
from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.domain.supplier_risk import SupplierPerformanceFacts

logger = structlog.get_logger("ai_agent.supplier_risk")

_SUPPLIERS_PATH = "/api/v1/inventory/suppliers"
_PAGE_SIZE = 100
_MAX_PAGES = 40  # 4000 suppliers ceiling guard; reindexes scale by page count.


@dataclass(frozen=True, slots=True)
class SupplierSnapshot:
    """One supplier master row with its latest raw performance facts."""

    supplier_id: uuid.UUID
    name: str
    lead_time_days: int
    performance: list[SupplierPerformanceFacts]


class SupplierSnapshotLoader(CoreHttpTransport):
    """Paginate core's supplier master + performance facts for one tenant."""

    async def load_all(self) -> list[SupplierSnapshot]:
        """Fetch every supplier + its performance facts; 503s on transport failure."""
        suppliers: list[SupplierSnapshot] = []
        for page in range(1, _MAX_PAGES + 1):
            rows = await self._fetch_supplier_page(page)
            for row in rows:
                supplier_id = uuid.UUID(str(row["id"]))
                performance = await self._fetch_performance(supplier_id)
                suppliers.append(
                    SupplierSnapshot(
                        supplier_id=supplier_id,
                        name=_as_text(row.get("name")) or "",
                        lead_time_days=int(row.get("lead_time_days", 7)),
                        performance=performance,
                    )
                )
            if not rows:
                return suppliers
        logger.warning(
            "supplier_risk.page_ceiling_hit",
            max_pages=_MAX_PAGES,
            tenant_slug=self._tenant_slug,
        )
        return suppliers

    async def _fetch_supplier_page(self, page: int) -> list[dict[str, Any]]:
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}{_SUPPLIERS_PATH}",
                    params={"page": page, "page_size": _PAGE_SIZE},
                    headers=self._headers(),
                )
                response.raise_for_status()
                body = response.json()
            data = body["data"]
            if not isinstance(data, list):
                raise TypeError("data must be a list")
            return data
        except httpx.HTTPStatusError as exc:
            logger.warning("supplier_risk.http_error", status_code=exc.response.status_code)
            raise AiUnavailableError("Core service could not serve the supplier catalog") from exc
        except httpx.HTTPError as exc:
            logger.warning("supplier_risk.transport_error")
            raise AiUnavailableError(
                "Core service is unreachable for the supplier catalog"
            ) from exc
        except (KeyError, TypeError) as exc:
            logger.warning("supplier_risk.invalid_envelope")
            raise AiUnavailableError("Core service returned an unusable supplier envelope") from exc

    async def _fetch_performance(self, supplier_id: uuid.UUID) -> list[SupplierPerformanceFacts]:
        path = f"{_SUPPLIERS_PATH}/{supplier_id}/performance"
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}{path}",
                    params={"page": 1, "page_size": _PAGE_SIZE},
                    headers=self._headers(),
                )
                response.raise_for_status()
                body = response.json()
            data = body["data"]
            if not isinstance(data, list):
                raise TypeError("data must be a list")
            return [_to_facts(supplier_id, row) for row in data]
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "supplier_risk.performance_http_error", status_code=exc.response.status_code
            )
            raise AiUnavailableError("Core service could not serve supplier performance") from exc
        except httpx.HTTPError as exc:
            logger.warning("supplier_risk.performance_transport_error")
            raise AiUnavailableError(
                "Core service is unreachable for supplier performance"
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("supplier_risk.performance_invalid_envelope")
            raise AiUnavailableError("Core service returned unusable supplier performance") from exc


def _to_facts(supplier_id: uuid.UUID, row: dict[str, Any]) -> SupplierPerformanceFacts:
    return SupplierPerformanceFacts(
        supplier_id=supplier_id,
        period_start=date.fromisoformat(str(row["period_start"])),
        period_end=date.fromisoformat(str(row["period_end"])),
        on_time_delivery_pct=Decimal(str(row["on_time_delivery_pct"])),
        defect_rate_pct=Decimal(str(row["defect_rate_pct"])),
        price_stability_index=Decimal(str(row["price_stability_index"])),
        responsiveness_days=Decimal(str(row["responsiveness_days"])),
    )


def _as_text(value: object) -> str | None:
    """Coerce a catalog field to str, keeping None/missing as None."""
    if value is None:
        return None
    return str(value)
