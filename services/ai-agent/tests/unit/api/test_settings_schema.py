"""Schema tests for GET/PATCH /ai/suggestions/settings (INV-AI-002)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ai_agent.api.v1.schemas.restock import RestockSettingsResponse, RestockSettingsUpdate


class TestRestockSettingsUpdate:
    def test_partial_patch_has_none_for_unset_fields(self) -> None:
        body = RestockSettingsUpdate(lead_time_days=Decimal("14.00"))
        assert body.lead_time_days == Decimal("14.00")
        assert body.safety_factor is None
        assert body.v2_enabled is None

    def test_accepts_full_patch(self) -> None:
        body = RestockSettingsUpdate(
            lead_time_days=Decimal("10.00"),
            safety_factor=Decimal("1.500"),
            v2_enabled=True,
            sensitivity=Decimal("0.700"),
            fp_threshold=Decimal("0.300"),
            email_alerts_enabled=True,
        )
        assert body.v2_enabled is True
        assert body.fp_threshold == Decimal("0.300")

    def test_rejects_non_positive_lead_time(self) -> None:
        with pytest.raises(ValidationError):
            RestockSettingsUpdate(lead_time_days=Decimal("0"))

    def test_rejects_non_positive_safety_factor(self) -> None:
        with pytest.raises(ValidationError):
            RestockSettingsUpdate(safety_factor=Decimal("-1"))

    def test_rejects_sensitivity_above_range(self) -> None:
        with pytest.raises(ValidationError):
            RestockSettingsUpdate(sensitivity=Decimal("1.001"))

    def test_rejects_fp_threshold_below_range(self) -> None:
        with pytest.raises(ValidationError):
            RestockSettingsUpdate(fp_threshold=Decimal("-0.1"))

    def test_rejects_empty_patch(self) -> None:
        with pytest.raises(ValidationError, match="at least one settings field"):
            RestockSettingsUpdate()

    def test_false_is_a_valid_patch_value(self) -> None:
        body = RestockSettingsUpdate(email_alerts_enabled=False)
        assert body.email_alerts_enabled is False


class TestRestockSettingsResponse:
    def test_builds_snapshot(self) -> None:
        resp = RestockSettingsResponse(
            tenant_id=uuid.uuid4(),
            lead_time_days=Decimal("7.00"),
            safety_factor=Decimal("1.000"),
            v2_enabled=False,
            sensitivity=Decimal("0.500"),
            fp_threshold=Decimal("0.500"),
            email_alerts_enabled=False,
        )
        assert resp.safety_factor == Decimal("1.000")
        assert resp.tenant_id is not None
