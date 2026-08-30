"""Unit tests for critical-anomaly email templates (spec §4.3).

Focus: HTML escaping of rule text, brand/slug-only tenant representation, and
the optional review button. Rendering never touches I/O.
"""

from __future__ import annotations

import uuid

from ai_agent.core.anomaly_email_templates import (
    CriticalAnomalyAlert,
    render_anomaly_alert_html,
    render_anomaly_alert_text,
)


def _alert(**overrides: object) -> CriticalAnomalyAlert:
    base: dict[str, object] = {
        "to": "ops@skyrict.dev",
        "tenant_id": str(uuid.uuid4()),
        "anomaly_id": str(uuid.uuid4()),
        "anomaly_type": "ledger_mismatch",
        "severity": "critical",
        "title": "Ledger mismatch: delta of -5 units",
        "description": "Stock level shows 5 on hand but the ledger sums to 10.",
        "status": "open",
        "created_at": "2026-08-29T10:00:00+00:00",
    }
    base.update(overrides)
    return CriticalAnomalyAlert(**base)


class TestPlaintext:
    def test_contains_core_fields(self) -> None:
        alert = _alert()
        text = render_anomaly_alert_text(alert)

        assert alert.title in text
        assert alert.description in text
        assert alert.anomaly_id in text
        assert alert.tenant_id in text
        assert "ledger_mismatch" in text
        assert alert.created_at in text

    def test_review_url_included_when_present(self) -> None:
        url = "https://app.skyrict.io/anomalies/abc"
        text = render_anomaly_alert_text(_alert(review_url=url))

        assert f"Review anomaly: {url}" in text

    def test_no_review_url_when_absent(self) -> None:
        text = render_anomaly_alert_text(_alert())

        assert "Review anomaly:" not in text


class TestHtml:
    def test_escapes_description(self) -> None:
        alert = _alert(
            description='Wrapper box <script>alert("x")</script> & "quotes"',
            title="Ledger mismatch",
        )
        html = render_anomaly_alert_html(alert)

        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&lt;/script&gt;" in html

    def test_escapes_title(self) -> None:
        alert = _alert(title="Delta <b>of</b> -5 & units")
        html = render_anomaly_alert_html(alert)

        assert "<b>of</b>" not in html
        assert "&lt;b&gt;of&lt;/b&gt;" in html

    def test_review_button_when_url_present(self) -> None:
        url = "https://app.skyrict.io/anomalies/abc"
        html = render_anomaly_alert_html(_alert(review_url=url))

        assert "Review anomaly" in html
        assert f'href="{url}"' in html

    def test_omits_button_when_no_url(self) -> None:
        html = render_anomaly_alert_html(_alert())

        assert "Review anomaly" not in html

    def test_badge_and_tenant_present(self) -> None:
        alert = _alert()
        html = render_anomaly_alert_html(alert)

        assert "Critical anomaly" in html
        assert alert.tenant_id in html
        assert alert.anomaly_id in html


class TestDataclass:
    def test_app_name_defaults_to_brand(self) -> None:
        assert _alert().app_name == "Skyrict"
