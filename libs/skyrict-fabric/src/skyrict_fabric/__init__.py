"""Skyrict Fabric — incremental carrier for the SKY-117 Bronze job.

The carrier is the **testable** core of the Skyrict Fabric piece of the SKY-117
ticket. It owns exactly the part a repository can and must prove in CI, and it
is deliberately *pure*: no connector, no engine, no I/O — so the incremental
contract is provable anywhere, honoring this repo's heritage rule that
DB-gated tests skip when the compose Postgres is unavailable.

Public surface (what CI proves)
-------------------------------
* ``advance_watermark`` — monotonic, idempotent high-water-mark advance; a stored
  watermark **never regresses**, and re-running the same load re-fetches exactly
  zero rows (no duplicates, no gaps).
* ``build_incremental_clause`` — the exact parameterized incremental predicate
  ``(wm > :hwm) OR (wm = :hwm AND pk > :hwm_pk)``; identifiers come from the
  trusted declarative spec, boundary **values** are always bound parameters.
* ``WatermarkState`` / ``ExtractMode`` — the declarative HWM unit and the
  full/incremental extract mode.

Provisioning the actual Fabric workspace / capacity / connector / Key Vault is a
tenant-credential step that lives in the runbook, not here (same boundary as
the DB-provisioning step of SKY-109).
"""

from __future__ import annotations

from skyrict_fabric.watermark import (
    ExtractMode,
    WatermarkState,
    advance_watermark,
    build_incremental_clause,
)

__all__ = [
    "ExtractMode",
    "WatermarkState",
    "advance_watermark",
    "build_incremental_clause",
]

__version__ = "0.1.0"
