"""Unit tests for approval engine tenant flags (SKY-92, Commit 2).

Guards the default-OFF contract: absent keys never enable the engine, and
the resource-specific switches require the master switch to be ON first.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from core.features.approval_workflow.tenant_flags import (
    approval_engine_enabled,
    je_approval_engine_enabled,
    payroll_approval_engine_enabled,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _FakeResult:
    def __init__(self, *, row: object = None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class _FakeSession:
    def __init__(self, *, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    async def execute(self, stmt: object) -> _FakeResult:
        # Render the statement with literal binds so the key appears as
        # ``'approval_engine_enabled'`` in the SQL text, then match it.
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        matched = [key for key in self._values if f"'{key}'" in sql]
        key = matched[0] if matched else None
        value = self._values.get(key) if key else None
        return _FakeResult(row=SimpleNamespace(value=value) if value is not None else None)


async def test_absent_master_flag_means_disabled() -> None:
    session = _FakeSession()

    assert await approval_engine_enabled(session, TENANT) is False


async def test_master_flag_on() -> None:
    session = _FakeSession(values={"approval_engine_enabled": "true"})

    assert await approval_engine_enabled(session, TENANT) is True


async def test_je_requires_master_switch() -> None:
    # resource flag on, master off -> still disabled
    session = _FakeSession(values={"je_approval_engine": "true"})

    assert await je_approval_engine_enabled(session, TENANT) is False


async def test_je_enabled_with_both_flags() -> None:
    session = _FakeSession(values={"approval_engine_enabled": "true", "je_approval_engine": "true"})

    assert await je_approval_engine_enabled(session, TENANT) is True


async def test_payroll_requires_master_switch() -> None:
    session = _FakeSession(values={"payroll_approval_engine": "true"})

    assert await payroll_approval_engine_enabled(session, TENANT) is False


async def test_payroll_enabled_with_both_flags() -> None:
    session = _FakeSession(
        values={"approval_engine_enabled": "true", "payroll_approval_engine": "true"}
    )

    assert await payroll_approval_engine_enabled(session, TENANT) is True


async def test_truthy_value_variants() -> None:
    for raw in ("1", "yes", "on", "TRUE", " true "):
        session = _FakeSession(values={"approval_engine_enabled": raw})
        assert await approval_engine_enabled(session, TENANT) is True, raw


async def test_falsy_values_are_off() -> None:
    for raw in ("0", "false", "no", "off", ""):
        session = _FakeSession(values={"approval_engine_enabled": raw})
        assert await approval_engine_enabled(session, TENANT) is False, raw
