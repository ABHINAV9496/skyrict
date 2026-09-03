"""Unit tests for identity/core/logging.py - structured JSON logging.

Verifies the acceptance criteria:
  - output is machine-readable JSON
  - request_id and tenant_id are auto-included when available
  - full tracebacks are rendered for 500s (exc_info -> "exception" field)
"""

from __future__ import annotations

import json

import pytest
import structlog

from identity.core.logging import configure_identity_logging
from identity.core.tenant_context import TenantContext


@pytest.fixture(autouse=True)
def _isolate_structlog() -> None:
    """Reset structlog state so each test gets a fresh processor chain."""
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    TenantContext.reset()
    yield
    structlog.contextvars.clear_contextvars()
    TenantContext.reset()


def _capture_json_line(capsys) -> dict:
    """Read the most recent JSON log line emitted by the current test."""
    out = capsys.readouterr().out
    lines = [line for line in out.strip().splitlines() if line.strip()]
    assert lines, "no log output captured"
    return json.loads(lines[-1])


def test_emits_json_with_standard_fields(capsys) -> None:
    configure_identity_logging(log_level="INFO", json_output=True)
    structlog.get_logger("test_logging").info("hello", foo="bar")

    parsed = _capture_json_line(capsys)
    assert parsed["event"] == "hello"
    assert parsed["foo"] == "bar"
    assert parsed["level"] == "info"
    assert parsed["logger"] == "test_logging"
    assert "timestamp" in parsed


def test_request_id_auto_included(capsys) -> None:
    configure_identity_logging(log_level="INFO", json_output=True)
    structlog.contextvars.bind_contextvars(request_id="req-123")
    structlog.get_logger("test_logging").info("hello")

    parsed = _capture_json_line(capsys)
    assert parsed["request_id"] == "req-123"


def test_tenant_id_auto_included_from_context(capsys) -> None:
    configure_identity_logging(log_level="INFO", json_output=True)
    TenantContext.set("tenant-456")
    structlog.get_logger("test_logging").info("hello")

    parsed = _capture_json_line(capsys)
    assert parsed["tenant_id"] == "tenant-456"


def test_tenant_id_omitted_when_not_set(capsys) -> None:
    configure_identity_logging(log_level="INFO", json_output=True)
    structlog.get_logger("test_logging").info("hello")

    parsed = _capture_json_line(capsys)
    assert "tenant_id" not in parsed


def test_exc_info_renders_full_traceback(capsys) -> None:
    configure_identity_logging(log_level="INFO", json_output=True)
    logger = structlog.get_logger("test_logging")

    try:
        raise RuntimeError("secret db detail")
    except RuntimeError:
        logger.error("unhandled_exception", exc_info=True)

    parsed = _capture_json_line(capsys)
    assert parsed["event"] == "unhandled_exception"
    assert parsed["level"] == "error"
    exception = parsed["exception"]
    assert "Traceback (most recent call last)" in exception
    assert "RuntimeError" in exception
    assert "secret db detail" in exception
