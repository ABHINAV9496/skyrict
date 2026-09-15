"""Invoice line-history loader for ``finance reindex`` (SKY-67 C1) - feature layer.

Fetches a tenant's invoice lines, page by page, from the core monolith's
``/api/v1/finance/invoices`` endpoint (which accepts the m2m ingest secret)
and aggregates them into :class:`FinanceLineSnapshot` rows.

Only descriptive/accounting facts pass through - the embedded text is the
line description, and the account is stored as the code/name/label it was most
often posted to. Money, customer PII, and currency values never cross the
trust boundary (they are irrelevant to "sensible line suggestions").

Uses the ingest service token (AI_INGEST_TOKEN) as bearer: a reindex is a
machine-to-machine operation, not one user's session.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import TYPE_CHECKING, Any, cast

import httpx
import structlog

from ai_agent.core.core_http import CoreHttpTransport
from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.finance_lines.snapshot import FinanceLineSnapshot

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

logger = structlog.get_logger("ai_agent.finance_lines_loader")

_INVOICES_PATH = "/api/v1/finance/invoices"
_ACCOUNTS_PATH = "/api/v1/finance/accounts"
_PAGE_SIZE = 100
_MAX_PAGES = 20  # 2000 invoices ceiling guard; reindexes scale by page count.


class FinanceLineLoader(CoreHttpTransport):
    """Paginate core's invoice lines into aggregated snapshot rows."""

    async def load_all(self) -> list[FinanceLineSnapshot]:
        """Fetch every line; aggregate into snapshot rows keyed by description."""
        account_names = await self._fetch_account_names()
        groups: dict[str, Counter[uuid.UUID]] = {}

        async with self._create_client() as client:
            for offset in range(0, _MAX_PAGES * _PAGE_SIZE, _PAGE_SIZE):
                items = await self._fetch_invoice_page(client, offset)
                for line in self._extract_lines(items):
                    description = cast("str", line["description"])
                    account_id = cast("uuid.UUID", line["account_id"])
                    groups.setdefault(description, Counter())[account_id] += 1
                if len(items) < _PAGE_SIZE:
                    break
            else:
                logger.warning(
                    "finance_lines_loader.page_ceiling_hit",
                    max_pages=_MAX_PAGES,
                    tenant_slug=self._tenant_slug,
                )

        snapshots: list[FinanceLineSnapshot] = []
        for description, account_ids in groups.items():
            account_id = account_ids.most_common(1)[0][0]
            code, name = account_names.get(account_id, ("", ""))
            snapshots.append(
                FinanceLineSnapshot(
                    description=description,
                    account_id=account_id,
                    account_code=code,
                    account_name=name,
                    times_used=sum(account_ids.values()),
                )
            )
        return snapshots

    async def _fetch_account_names(self) -> dict[uuid.UUID, tuple[str, str]]:
        """Fetch the chart of accounts (id -> (code, name)) for labeling."""
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}{_ACCOUNTS_PATH}", headers=self._headers()
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("finance_lines_loader.accounts_error")
            raise AiUnavailableError(
                "Core service is unreachable for the chart of accounts"
            ) from exc
        try:
            data = response.json().get("data")
        except ValueError as exc:
            raise AiUnavailableError("Core service returned an unusable chart of accounts") from exc
        accounts: dict[uuid.UUID, tuple[str, str]] = {}
        for row in data or []:
            if not isinstance(row, dict):
                continue
            try:
                account_id = uuid.UUID(str(row["id"]))
            except (KeyError, ValueError):
                continue
            accounts[account_id] = (str(row.get("code") or ""), str(row.get("name") or ""))
        return accounts

    async def _fetch_invoice_page(
        self, client: httpx.AsyncClient, offset: int
    ) -> list[dict[str, Any]]:
        """Fetch one ListResponse page of invoices; transport failures are 503s."""
        try:
            response = await client.get(
                f"{self._base_url}{_INVOICES_PATH}",
                params={"offset": offset, "limit": _PAGE_SIZE},
                headers=self._headers(),
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "finance_lines_loader.http_error",
                status_code=getattr(getattr(exc, "response", None), "status_code", None),
            )
            raise AiUnavailableError("Core service could not serve invoice lines") from exc

        try:
            body = response.json()
            data = body["data"]
            if not isinstance(data, list):
                raise TypeError("data must be a list")
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("finance_lines_loader.invalid_envelope")
            raise AiUnavailableError("Core service returned an unusable envelope") from exc
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _extract_lines(invoices: Iterable[Mapping[str, object]]) -> Iterable[dict[str, object]]:
        """Yield the description + account_id of every non-empty line."""
        for invoice in invoices:
            lines = invoice.get("lines")
            if not isinstance(lines, list):
                continue
            for line in lines:
                if not isinstance(line, dict):
                    continue
                description = str(line.get("description") or "").strip()
                account_id = line.get("account_id")
                if not description or account_id is None:
                    continue
                try:
                    parsed_id = uuid.UUID(str(account_id))
                except ValueError:
                    continue
                yield {"description": description, "account_id": parsed_id}
