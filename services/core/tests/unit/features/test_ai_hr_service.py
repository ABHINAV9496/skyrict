"""Unit tests for the L1 aggregate service narrative builders (HR-AI-001).

The narratives are deterministic, rule-based templates (spec §5) - they must
never emit per-employee data and must degrade gracefully on empty inputs.
Pure unit tests (no database): they exercise the narrative helpers directly.
"""

from __future__ import annotations

import uuid

import pytest

from core.features.ai_hr.repository import (
    DepartmentCount,
    HeadcountPoint,
    TenureBand,
)
from core.features.ai_hr.service import (
    _dept_narrative,
    _format_pct,
    _tenure_narrative,
    _trend_narrative,
)

pytestmark = pytest.mark.unit


def test_format_pct_rounds_to_one_decimal() -> None:
    assert _format_pct(3, 5) == "60.0%"
    assert _format_pct(0, 5) == "0.0%"


def test_format_pct_guards_division_by_zero() -> None:
    assert _format_pct(5, 0) == "0%"


def test_trend_narrative_empty_input() -> None:
    assert _trend_narrative([], 5) == "Headcount is 5 across the tenant."


def test_trend_narrative_uses_most_recent_month() -> None:
    trend = [
        HeadcountPoint(year=2026, month=2, hires=4),
        HeadcountPoint(year=2026, month=1, hires=1),
    ]
    text = _trend_narrative(trend, 10)
    assert "2026" in text and "new hire(s)" in text
    assert "02-2026" in text and "4" in text


def test_dept_narrative_empty_input() -> None:
    assert _dept_narrative([], 5) == ""


def test_dept_narrative_names_largest_team() -> None:
    depts = [
        DepartmentCount(department_id=uuid.uuid4(), department_name="Eng", count=8),
        DepartmentCount(department_id=None, department_name="Unassigned", count=2),
    ]
    assert _dept_narrative(depts, 10) == "Largest team is Eng (8, 80.0%)."


def test_tenure_narrative_empty_input() -> None:
    assert _tenure_narrative([], 5) == ""


def test_tenure_narrative_picks_modal_band() -> None:
    bands = [TenureBand(band="<1", count=2), TenureBand(band="1-3", count=6)]
    assert _tenure_narrative(bands, 10) == "Tenure is concentrated at 1-3 years (60.0%)."
