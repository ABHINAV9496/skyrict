"""Unit tests for identity/api/readiness.py — gate transitions and startup verification.

Covers:
  - gate lifecycle: STARTING -> READY -> STOPPING, reset() for tests
  - verify_startup_dependencies: passes when all checks pass, raises
    StartupError when database, Redis, or JWT key verification fails
  - the probes themselves (real engine / Redis PING) are exercised by the
    integration suite; here they are stubbed so tests need no infrastructure
"""

from __future__ import annotations

import pytest

from identity.api import readiness
from identity.api.readiness import ReadinessState, verify_startup_dependencies
from identity.core.exceptions import StartupError


@pytest.fixture(autouse=True)
def _reset_gate():
    """The gate is module-global — reset it so tests are order-independent."""
    readiness.reset()
    yield


class TestReadinessGate:
    """Gate state machine — closed until mark_ready()."""

    def test_initial_state_is_starting_and_not_ready(self):
        assert readiness.get_state() is ReadinessState.STARTING
        assert readiness.is_ready() is False

    def test_mark_ready_opens_the_gate(self):
        readiness.mark_ready()
        assert readiness.get_state() is ReadinessState.READY
        assert readiness.is_ready() is True

    def test_mark_stopping_closes_the_gate(self):
        readiness.mark_ready()
        readiness.mark_stopping()
        assert readiness.get_state() is ReadinessState.STOPPING
        assert readiness.is_ready() is False

    def test_reset_returns_to_starting(self):
        readiness.mark_ready()
        readiness.reset()
        assert readiness.get_state() is ReadinessState.STARTING
        assert readiness.is_ready() is False


class TestVerifyStartupDependencies:
    """Startup verification fails fast (raises) on any failed dependency."""

    @pytest.fixture(autouse=True)
    def _stub_all_checks(self, monkeypatch: pytest.MonkeyPatch):
        """Stub every probe so each test controls the failure it cares about."""

        async def _ok() -> None:
            return None

        monkeypatch.setattr(readiness, "check_database", _ok)
        monkeypatch.setattr(readiness, "check_redis", _ok)
        monkeypatch.setattr(readiness, "verify_jwt_keys_usable", lambda: None)

    async def test_passes_when_all_dependencies_are_healthy(self):
        await verify_startup_dependencies()  # must not raise

    async def test_raises_when_database_check_fails(self, monkeypatch: pytest.MonkeyPatch):
        async def _boom() -> None:
            raise OSError("connection refused")

        monkeypatch.setattr(readiness, "check_database", _boom)
        with pytest.raises(StartupError, match="database"):
            await verify_startup_dependencies()

    async def test_raises_when_redis_check_fails(self, monkeypatch: pytest.MonkeyPatch):
        async def _boom() -> None:
            raise OSError("connection refused")

        monkeypatch.setattr(readiness, "check_redis", _boom)
        with pytest.raises(StartupError, match="redis"):
            await verify_startup_dependencies()

    async def test_raises_when_jwt_key_verification_fails(self, monkeypatch: pytest.MonkeyPatch):
        def _boom() -> None:
            raise StartupError("bad key")

        monkeypatch.setattr(readiness, "verify_jwt_keys_usable", _boom)
        with pytest.raises(StartupError):
            await verify_startup_dependencies()
