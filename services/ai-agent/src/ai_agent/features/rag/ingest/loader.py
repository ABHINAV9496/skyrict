"""Source loaders for RAG ingestion (SKY-58).

Two loaders cover the two approved sources:

- :class:`DocsLoader` — markdown documents from a directory (ERP manuals,
  SOPs, UI help). ``source_ref`` is the POSIX path relative to the root.
- :class:`ModuleLoader` — whitelisted transactional text fields fetched from
  the core monolith (SKY-70 semantic product search needs product name and
  SKU, not money or PII). Every row becomes a compact markdown record.

FIELD WHITELIST SECURITY RULE (inventory AI spec §5.5): never include cost
prices, sell prices, customer/supplier names, or user IDs — those data
classes must not leave the trust boundary even for embeddings. Each module
lists its allowed fields explicitly in :data:`MODULE_FIELD_WHITELISTS`; a
field added to core is not ingested until the whitelist grows deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from ai_agent.core.exceptions import AiUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger("ai_agent.rag.ingest")

# Core endpoints per module (real contracts; envelope: {success, data, meta}).
MODULE_ENDPOINTS: dict[str, str] = {
    "products": "/api/v1/inventory/products",
}

# Allowed textual fields per module — see module docstring for the whitelist
# rule. Money (reorder_point, cost prices) and PII are deliberately absent.
MODULE_FIELD_WHITELISTS: dict[str, tuple[str, ...]] = {
    "products": ("name", "sku"),
}


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """One ingestible document: module classification + stable source ref."""

    module: str
    source_ref: str
    text: str


class DocsLoader:
    """Load every non-empty ``*.md`` file under a directory, sorted."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self) -> list[SourceDocument]:
        if not self.root.is_dir():
            raise ValueError(f"docs root is not a directory: {self.root}")
        docs: list[SourceDocument] = []
        for path in sorted(self.root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                continue
            rel = path.relative_to(self.root).as_posix()
            docs.append(SourceDocument(module="docs", source_ref=rel, text=text))
        return docs


class ModuleLoader:
    """Fetch one module's whitelisted fields from the core monolith.

    Forwards the caller's bearer token and tenant slug exactly as the
    NL-query gateway does (X-Tenant-Slug contract), paginating the standard
    envelope until ``meta.total_pages`` is consumed.
    """

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        tenant_slug: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not base_url.strip().lower().startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._tenant_slug = tenant_slug
        self._timeout_seconds = max(timeout_seconds, 1.0)

    def _create_client(self) -> httpx.AsyncClient:
        """Create the per-call HTTP client (overridable seam for tests)."""
        return httpx.AsyncClient(timeout=self._timeout_seconds)

    async def load(self, module: str) -> list[SourceDocument]:
        """Fetch all rows of *module* and render them as markdown records."""
        if module not in MODULE_ENDPOINTS:
            raise ValueError(
                f"module loader has no configured endpoint for '{module}' "
                f"(known: {sorted(MODULE_ENDPOINTS)})"
            )
        rows = await self._fetch_all(MODULE_ENDPOINTS[module])
        fields = MODULE_FIELD_WHITELISTS[module]
        docs: list[SourceDocument] = []
        for row in rows:
            doc = self._render(module, row, fields)
            if doc is not None:
                docs.append(doc)
        return docs

    async def _fetch_all(self, path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            data, total_pages = await self._fetch_page(path, page)
            rows.extend(data)
            if page >= total_pages:
                return rows
            page += 1

    async def _fetch_page(self, path: str, page: int) -> tuple[list[dict[str, Any]], int]:
        headers = {
            "Authorization": f"Bearer {self._bearer_token}",
            "X-Tenant-Slug": self._tenant_slug,
        }
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}{path}",
                    params={"page": page, "page_size": 100},
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "rag.module_http_error",
                module_path=path,
                status_code=exc.response.status_code,
            )
            raise AiUnavailableError("Core service could not serve the module data") from exc
        except httpx.HTTPError as exc:
            logger.warning("rag.module_transport_error", module_path=path)
            raise AiUnavailableError("Core service is unreachable for module data") from exc

        try:
            body = response.json()
            data = body["data"]
            meta = body.get("meta", {})
            if not isinstance(data, list):
                raise TypeError("data must be a list")
            total_pages = int(meta.get("total_pages", 1))
            if total_pages < 1:
                raise TypeError("total_pages must be >= 1")
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("rag.module_invalid_envelope", module_path=path)
            raise AiUnavailableError("Core service returned an unusable envelope") from exc
        return data, total_pages

    def _render(
        self, module: str, row: dict[str, Any], fields: tuple[str, ...]
    ) -> SourceDocument | None:
        """Render one row as a markdown record, or None when it is blank."""
        record_id = row.get("id")
        if not record_id:
            logger.debug("rag.module_row_skipped_missing_id", module=module)
            return None
        values = {f: row.get(f) for f in fields}
        if not any(v is not None and str(v).strip() for v in values.values()):
            return None
        lines = [f"## {module}:{record_id}"]
        for field_name in fields:
            value = values.get(field_name)
            if value is not None and str(value).strip():
                lines.append(f"- {field_name}: {value}")
        return SourceDocument(
            module=module,
            source_ref=f"{module}/{record_id}",
            text="\n".join(lines),
        )
