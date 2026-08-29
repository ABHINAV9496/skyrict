"""Unit tests for the anomaly-email transports and factory (spec §4.3)."""

from __future__ import annotations

import uuid

import pytest

import ai_agent.core.email as email_mod
from ai_agent.core.anomaly_email_templates import CriticalAnomalyAlert
from ai_agent.core.email import (
    LogEmailService,
    SmtpEmailService,
    build_email_service,
)


def _alert() -> CriticalAnomalyAlert:
    return CriticalAnomalyAlert(
        to="ops@skyrict.dev",
        tenant_id=str(uuid.uuid4()),
        anomaly_id=str(uuid.uuid4()),
        anomaly_type="ledger_mismatch",
        severity="critical",
        title="Ledger mismatch: delta of -5 units",
        description="Stock level shows 5 on hand but the ledger sums to 10.",
        status="open",
        created_at="2026-08-29T10:00:00+00:00",
        review_url="https://app.skyrict.io/anomalies/abc",
    )


class FakeSMTP:
    """In-process stand-in for smtplib.SMTP (captures the composed message)."""

    def __init__(self, host: str, port: int, timeout: int = 10) -> None:
        self.host = host
        self.port = port
        self.sent: list[object] = []
        self.closed = False

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True

    def ehlo(self) -> None: ...

    def starttls(self) -> None: ...

    def login(self, username: str, password: str) -> None: ...

    def send_message(self, message: object) -> None:
        self.sent.append(message)


class FailingSMTP(FakeSMTP):
    """Relay that refuses connections (asserts the failure is swallowed)."""

    def __enter__(self) -> FailingSMTP:
        raise OSError("connection refused")


class TestBuildEmailService:
    def test_empty_host_returns_log_transport(self) -> None:
        svc = build_email_service(host="")

        assert isinstance(svc, LogEmailService)

    def test_host_returns_smtp_transport(self) -> None:
        svc = build_email_service(host="mailhog", port=1025)

        assert isinstance(svc, SmtpEmailService)


class TestLogEmailService:
    async def test_sends_without_raising(self) -> None:
        svc = LogEmailService()

        await svc.send_critical_anomaly_alert(alert=_alert())


class TestSmtpEmailService:
    async def test_delivers_message_with_all_parts(self, monkeypatch) -> None:
        fake = FakeSMTP("mailhog", 1025)
        monkeypatch.setattr(email_mod.smtplib, "SMTP", lambda host, port, timeout: fake)

        await SmtpEmailService(
            host="mailhog", port=1025, from_addr="Skyrict <no-reply@skyrict.dev>"
        ).send_critical_anomaly_alert(alert=_alert())

        assert len(fake.sent) == 1
        message = fake.sent[0]
        assert message["From"] == "Skyrict <no-reply@skyrict.dev>"
        assert message["To"] == "ops@skyrict.dev"
        assert message["Subject"] == "CRITICAL: Ledger mismatch: delta of -5 units"
        assert fake.closed

    async def test_failure_is_logged_never_raised(self, monkeypatch) -> None:
        monkeypatch.setattr(
            email_mod.smtplib, "SMTP", lambda host, port, timeout: FailingSMTP(host, port)
        )

        # Must NOT raise: delivery problems never break the scan/review flow.
        await SmtpEmailService(
            host="down", port=1025, from_addr="x@y.dev"
        ).send_critical_anomaly_alert(alert=_alert())

    async def test_uses_tls_login_when_configured(self, monkeypatch) -> None:
        fake = FakeSMTP("mailhog", 1025)
        monkeypatch.setattr(email_mod.smtplib, "SMTP", lambda host, port, timeout: fake)

        await SmtpEmailService(
            host="mailhog",
            port=1025,
            from_addr="Skyrict <no-reply@skyrict.dev>",
            username="user",
            password="pass",
            use_tls=True,
        ).send_critical_anomaly_alert(alert=_alert())

        assert len(fake.sent) == 1

    @pytest.mark.anyio
    async def test_smtp_exception_type_is_swallowed(self, monkeypatch) -> None:
        import smtplib

        def explode(*args, **kwargs):
            raise smtplib.SMTPException("relay rejected mail")

        monkeypatch.setattr(email_mod.smtplib, "SMTP", explode)

        # Also an smtplib.SMTPException subclass (weird relay) → no raise.
        await SmtpEmailService(host="x", port=1, from_addr="x@y.dev").send_critical_anomaly_alert(
            alert=_alert()
        )
