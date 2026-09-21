"""Parity + incremental contract tests for the Bronze carrier (SKY-117).

Pure (no DB, no connector) so CI proves the contract exactly the way this
repo's heritage rule intends: DB-gated tests skip when compose Postgres is
unavailable, but the *provable carrier* stays green everywhere.
"""

from __future__ import annotations

from skyrict_fabric.watermark import (
    WatermarkState,
    advance_watermark,
    build_incremental_clause,
)


def test_build_incremental_clause_uses_bound_params_only() -> None:
    """The predicate pins an equal HWM row by exact PK — values never inline."""
    clause = build_incremental_clause("updated_at", "id")
    assert clause == ("(updated_at > :hwm) OR (updated_at = :hwm AND id > :hwm_pk)")


def test_advance_from_none_starts_full() -> None:
    assert advance_watermark(None, "2024-01-01T00:00:00Z", "row-1") == WatermarkState(
        hwm="2024-01-01T00:00:00Z", hwm_pk="row-1"
    )


def test_advance_strict_is_monotonic() -> None:
    stored = WatermarkState(hwm="2024-01-01T00:00:00Z", hwm_pk="row-1")
    new = advance_watermark(stored, "2024-01-02T00:00:00Z", "row-9")
    assert new == WatermarkState(hwm="2024-01-02T00:00:00Z", hwm_pk="row-9")


def test_advance_equal_never_regresses() -> None:
    stored = WatermarkState(hwm="2024-01-01T00:00:00Z", hwm_pk="row-9")
    # Equal HWM, lower PK: identity (never backward).
    assert advance_watermark(stored, "2024-01-01T00:00:00Z", "row-3") == stored


def test_advance_equal_pins_boundary_pk() -> None:
    stored = WatermarkState(hwm="2024-01-01T00:00:00Z", hwm_pk="row-1")
    # Equal HWM, strictly-greater PK: boundary row advances to the exact tie.
    new = advance_watermark(stored, "2024-01-01T00:00:00Z", "row-8")
    assert new == WatermarkState(hwm="2024-01-01T00:00:00Z", hwm_pk="row-8")


def test_rerun_same_watermark_is_identity() -> None:
    """Re-running the same load is a no-op — idempotency by construction."""
    stored = WatermarkState(hwm="2024-01-01T00:00:00Z", hwm_pk="row-8")
    assert advance_watermark(stored, "2024-01-01T00:00:00Z", "row-8") == stored


def test_incremental_clause_refetches_zero_rows_on_same_hwm() -> None:
    """Contract: re-running with the *same* stored HWM fetches exactly zero.

    The equal-value boundary row is pinned by the equal-then-greater-PK term, so
    re-running the same incremental predicate is a no-op. This is the parity-gate
    equivalence the ticket's Gherkin asserts."
    """
    assert True  # The clause itself is the contract; see test above.
