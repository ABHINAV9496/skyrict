"""report_cache - TTL-swept aggregate cache for expensive dashboard queries.

Write-through cache keyed by (tenant_id, cache_key) with JSONB payloads.
``hash_report_key(*parts)`` produces a stable 64-char SHA-256 hex key from
arbitrary string parts; the UNIQUE index on (tenant_id, cache_key) ensures one
row per tenant per report.  Same-hash repeats within the TTL window increment
``hit_count`` instead of inserting duplicate rows (ON CONFLICT DO UPDATE).

Expired rows are purged by ``core sweep-report-cache`` (same pattern as
``ai-agent sweep-caches``).  The ``ix_erp_report_cache_expires`` index keeps
the sweep a narrow index scan.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from core.features.finance.models.erp_report_cache import ErpReportCacheModel

try:
    from sqlalchemy.ext.asyncio import AsyncSession
except ImportError:  # pragma: no cover
    AsyncSession = None  # type: ignore[assignment,misc]

# Default TTL for report aggregates (5 minutes).  Sufficiently fresh for
# dashboards while eliminating redundant DB scans on rapid page refreshes.
REPORT_CACHE_TTL_SECONDS = 300


def hash_report_key(*parts: Any) -> str:
    """Return a stable SHA-256 hex digest for the given cache key parts.

    Each part is stringified and joined with ``|`` before hashing so the same
    positional arguments always produce the same key, regardless of how the
    caller formats them.
    """
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()


class ReportCacheRepository:
    """Tenant-scoped write-through persistence for pre-computed report payloads."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, *, tenant_id: uuid.UUID, cache_key: str) -> dict[str, Any] | None:
        """Return the cached payload if present and unexpired, else ``None``."""
        result = await self.session.execute(
            select(ErpReportCacheModel).where(
                ErpReportCacheModel.tenant_id == tenant_id,
                ErpReportCacheModel.cache_key == cache_key,
                ErpReportCacheModel.expires_at > func.now(),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return dict(row.payload)

    async def put(
        self,
        *,
        tenant_id: uuid.UUID,
        cache_key: str,
        payload: dict[str, Any],
        ttl_seconds: int = REPORT_CACHE_TTL_SECONDS,
    ) -> None:
        """Upsert one cache entry; a same-hash repeat increments hit_count."""
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        stmt = (
            insert(ErpReportCacheModel)
            .values(
                tenant_id=tenant_id,
                id=uuid.uuid4(),
                cache_key=cache_key,
                payload=payload,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "cache_key"],
                set_={
                    "payload": payload,
                    "expires_at": expires_at,
                    "hit_count": ErpReportCacheModel.hit_count + 1,
                },
            )
        )
        await self.session.execute(stmt)

    async def delete_expired(self) -> int:
        """Purge expired rows; returns the number of rows deleted.

        The ``core sweep-report-cache`` CLI gate calls this.  The
        ``ix_erp_report_cache_expires`` index keeps this a narrow index scan.
        """
        result = await self.session.execute(
            delete(ErpReportCacheModel).where(ErpReportCacheModel.expires_at <= func.now())
        )
        if isinstance(result, CursorResult):
            return result.rowcount or 0
        return 0


# ------------------------------------------------------------------
# Serialization helpers for domain entities → JSON-safe dicts
# ------------------------------------------------------------------


def _json_safe(obj: Any) -> Any:
    """Recursively convert domain objects to JSON-serializable primitives.

    ``Decimal`` → ``str``, ``uuid.UUID`` → ``str``, ``date/datetime`` → ISO
    string, ``enum`` → ``.value``, ``tuple`` → ``list``, nested ``dataclass``
    → nested ``dict``.
    """
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _json_safe(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, tuple):
        return [_json_safe(i) for i in obj]
    if isinstance(obj, list):
        return [_json_safe(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    return obj


def serialize_entity(entity: Any) -> dict[str, Any]:
    """Serialize a frozen dataclass domain entity to a JSON-safe dict.

    The resulting dict is suitable for JSONB storage and Pydantic
    ``model_validate()`` (which accepts dicts natively).
    """
    result = _json_safe(entity)
    if isinstance(result, dict):
        return result
    return {"value": result}
