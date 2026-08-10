"""Unit tests for the premium new-login security-alert email templates."""

from __future__ import annotations

from identity.core.email_templates import (
    SecurityAlert,
    render_security_alert_html,
    render_security_alert_text,
)


def _alert(**overrides) -> SecurityAlert:
    base = {
        "to": "alice@skyrict.dev",
        "full_name": "Alice Example",
        "event_type": "new_device",
        "ip_address": "203.0.113.***",
        "location": "Bengaluru, Karnataka, India",
        "browser": "Chrome 126",
        "os": "Windows 11",
        "device": "Unknown (Desktop)",
        "auth_method": "Password + MFA",
        "session_id_masked": "3f9a2c1d••••",
        "date_time": "Aug 8, 2026 at 2:07 PM UTC",
        "review_url": "https://app.skyrict.io/settings/security",
        "secure_url": "https://app.skyrict.io/settings/security/password",
        "support_email": "security@skyrict.dev",
    }
    base.update(overrides)
    return SecurityAlert(**base)


def test_html_contains_all_login_detail_rows() -> None:
    html = render_security_alert_html(_alert())

    for label in (
        "Date &amp; time",
        "Location",
        "IP address",
        "Browser",
        "Operating system",
        "Device",
        "Authentication",
        "Session ID",
    ):
        assert label in html

    for value in (
        "Aug 8, 2026 at 2:07 PM UTC",
        "Bengaluru, Karnataka, India",
        "203.0.113.***",
        "Chrome 126",
        "Windows 11",
        "Password + MFA",
        "3f9a2c1d••••",
    ):
        assert value in html


def test_html_does_not_leak_python_repr() -> None:
    html = render_security_alert_html(_alert())

    assert "[" not in html
    assert "]" not in html
    assert "''" not in html
    assert "<tr><td" in html  # rows are real table markup, not stringified
    assert len(html.split('<tr><td width="34"')) == 9  # header + 8 detail rows


def test_html_structure_and_actions() -> None:
    html = render_security_alert_html(_alert())

    assert "<!DOCTYPE html>" in html
    assert "New login detected" in html
    assert "Security alert" in html
    assert 'href="https://app.skyrict.io/settings/security"' in html
    assert 'href="https://app.skyrict.io/settings/security/password"' in html
    assert "Review activity" in html
    assert "Secure my account" in html
    assert "security@skyrict.dev" in html
    assert "automated security notification" in html
    assert "Skyrict" in html


def test_html_omits_buttons_without_urls() -> None:
    html = render_security_alert_html(_alert(review_url=None, secure_url=None))

    assert 'href="https://app.skyrict.io/settings/security"' not in html
    assert "Review activity" not in html
    assert "Secure my account" not in html
    # Advice section still present for self-service action.
    assert "If this wasn't you" in html
    assert "Change your password" in html


def test_html_escapes_user_values() -> None:
    html = render_security_alert_html(
        _alert(
            full_name="Alice <img src=x onerror=alert(1)>",
            browser='Chrome"><script>alert(1)</script>',
            os="<b>Windows</b>",
        )
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;Windows&lt;/b&gt;" in html
    assert "<img src=x" not in html


def test_unknown_location_renders_gracefully() -> None:
    html = render_security_alert_html(_alert(location=""))
    assert "Unknown" in html


def test_plaintext_includes_details_and_urls() -> None:
    text = render_security_alert_text(_alert())

    assert "New login detected" in text
    assert "Aug 8, 2026 at 2:07 PM UTC" in text
    assert "203.0.113.***" in text
    assert "Bengaluru, Karnataka, India" in text
    assert "Password + MFA" in text
    assert "3f9a2c1d••••" in text
    assert "https://app.skyrict.io/settings/security" in text
    assert "https://app.skyrict.io/settings/security/password" in text


def test_plaintext_without_urls() -> None:
    text = render_security_alert_text(_alert(review_url=None, secure_url=None))
    assert "https://app.skyrict.io" not in text
    assert "change your password" in text
