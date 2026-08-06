"""Unit tests for the email transports (log vs SMTP)."""

from __future__ import annotations

import json
import smtplib

import pytest
import structlog

import identity.core.email as email_mod
from identity.core.email import LogEmailService, SmtpEmailService
from identity.core.logging import configure_identity_logging


class FakeSMTP:
    """In-memory stand-in for smtplib.SMTP that records what it would send."""

    def __init__(self, *args, **kwargs) -> None:
        self.sent: list = []
        self.ehlos = 0
        self.tls = 0
        self.logins: list[tuple[str, str]] = []

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc) -> None:
        return None

    def ehlo(self) -> None:
        self.ehlos += 1

    def starttls(self) -> None:
        self.tls += 1

    def login(self, username: str, password: str) -> None:
        self.logins.append((username, password))

    def send_message(self, message) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _isolate_email_logger() -> None:
    """Swap the module logger for a fresh structlog proxy per test.

    Structlog bound loggers capture the processor chain at first use, so each
    test replaces the module logger so it observes the config just installed.
    """
    original = email_mod.logger
    yield
    email_mod.logger = original
    structlog.reset_defaults()


def _service(**overrides) -> SmtpEmailService:
    kwargs: dict = {
        "host": "mailhog",
        "port": 1025,
        "from_addr": "Skyrict <no-reply@skyrict.dev>",
    }
    kwargs.update(overrides)
    return SmtpEmailService(**kwargs)


def _capture_json_line(capsys) -> dict:
    out = capsys.readouterr().out
    lines = [line for line in out.strip().splitlines() if line.strip()]
    assert lines, "no log output captured"
    return json.loads(lines[-1])


async def test_smtp_service_sends_otp_with_code(monkeypatch) -> None:
    fake = FakeSMTP()
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: fake)

    await _service().send_otp(to="alice@test.com", code="123456")

    assert len(fake.sent) == 1
    message = fake.sent[0]
    assert message["To"] == "alice@test.com"
    assert message["From"] == "Skyrict <no-reply@skyrict.dev>"
    plain = message.get_body(preferencelist=("plain",))
    assert plain is not None
    assert "123456" in plain.get_content()
    # Multipart alternative includes an HTML variant.
    assert message.get_body(preferencelist=("html",)) is not None


async def test_smtp_service_applies_tls_and_auth(monkeypatch) -> None:
    fake = FakeSMTP()
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: fake)

    await _service(username="user", password="secret", use_tls=True).send_otp(
        to="bob@test.com", code="654321"
    )

    assert fake.tls == 1
    assert fake.logins == [("user", "secret")]
    assert len(fake.sent) == 1


async def test_smtp_service_swallows_delivery_failure(monkeypatch, capsys) -> None:
    def _raising(*args, **kwargs) -> None:
        raise smtplib.SMTPConnectError(421, b"service not available")

    monkeypatch.setattr(smtplib, "SMTP", _raising)
    configure_identity_logging(log_level="INFO", json_output=True)
    email_mod.logger = structlog.get_logger("identity.email")

    # Must not raise — auth flows tolerate a dead relay.
    await _service().send_otp(to="carol@test.com", code="000000")

    parsed = _capture_json_line(capsys)
    assert parsed["event"] == "email.delivery.failed"
    assert parsed["to"] == "carol@test.com"


async def test_log_service_logs_otp_code(capsys) -> None:
    configure_identity_logging(log_level="INFO", json_output=True)
    email_mod.logger = structlog.get_logger("identity.email")

    await LogEmailService().send_otp(to="dave@test.com", code="112233")

    parsed = _capture_json_line(capsys)
    assert parsed["event"] == "email.otp.sent"
    assert parsed["otp_code"] == "112233"
    assert parsed["to"] == "dave@test.com"
