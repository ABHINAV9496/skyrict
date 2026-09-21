"""High-water-mark (HWM) semantics for incremental Bronze extraction.

All logic in this module is **pure** — no I/O, no connector, no engine — so the
incremental contract is *provable in CI* without any database. This honors the
repo's heritage rule that DB-gated tests skip when compose Postgres is
unavailable, while the pure carrier contract stays green everywhere.

Contract (what CI proves)
-------------------------
1. **Monotonic advance.** A watermark only moves *forward*. ``advance_watermark``
   returns the identity unless the candidate *strictly* exceeds the stored HWM,
   or — at an *equal* HWM — the candidate PK strictly exceeds the stored boundary
   PK. Re-running the same load is a no-op; the stored value never regresses.
2. **Exact incremental clause.** The predicate is

       (wm_col > :hwm) OR (wm_col = :hwm AND pk_col > :hwm_pk)

   Re-running with the *same* stored watermark re-fetches **exactly zero rows**
   (no duplicates, no gaps) — idempotent by construction.
3. **Parity-safe.** ``(wm_col, pk_col)`` is a strict total order, so a
   full → incremental transition can never double-count or skip a row.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "ExtractMode",
    "WatermarkState",
    "advance_watermark",
    "build_incremental_clause",
]


class ExtractMode(StrEnum):
    """How one source table is loaded: full (parity/initial) or incremental."""

    FULL = "full"
    INCREMENTAL = "incremental"


@dataclass(frozen=True)
class WatermarkState:
    """One stored high-water mark for a source table.

    ``hwm`` is the maximum value of the watermark column seen so far; ``hwm_pk``
    is the source PK of the row that carried that boundary value (the exact
    equal-value tie-break, making the incremental contract parity-safe).
    """

    hwm: Any
    hwm_pk: Any | None = None


def advance_watermark(
    stored: WatermarkState | None,
    candidate: Any,
    candidate_pk: Any | None = None,
) -> WatermarkState:
    """Return the new watermark after a load, guaranteeing **monotonic advance**.

    Identity unless the candidate *strictly* exceeds the stored HWM, or — at an
    *equal* HWM — the candidate PK strictly exceeds the stored boundary PK.
    Re-running with the same stored watermark is a no-op (idempotent, never
    regresses).
    """
    if stored is None:
        return WatermarkState(hwm=candidate, hwm_pk=candidate_pk)
    if candidate > stored.hwm:
        return WatermarkState(hwm=candidate, hwm_pk=candidate_pk)
    if (
        candidate == stored.hwm
        and candidate_pk is not None
        and (stored.hwm_pk is None or candidate_pk > stored.hwm_pk)
    ):
        return WatermarkState(hwm=stored.hwm, hwm_pk=candidate_pk)


def build_incremental_clause(watermark_col: str, pk_col: str) -> str:
    """Return the parameterized incremental predicate for one source table.

    ``watermark_col`` / ``pk_col`` are **identifiers** drawn from the declarative
    pipeline spec (trusted, never user input); all boundary values are bound
    parameters (``:hwm``, ``:hwm_pk``).
    """
    return f"({watermark_col} > :hwm) OR ({watermark_col} = :hwm AND {pk_col} > :hwm_pk)"
