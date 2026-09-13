"""Unit tests for the L4 scenario service.

The service orchestrates: gateway → engine → repo → audit.  All I/O is faked
(mocks for gateway, repo, audit) so these tests verify:
- the 10x5000 + 5% merit month-4 hand-check (engine math through the parse path)
- actions round-trip through wire dicts → engine dataclasses
- list/get/compare delegate to repo correctly
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

from ai_agent.core.audit_events import AI_L4_SCENARIO_CREATED
from ai_agent.features.l4.service import L4ScenarioService

_TENANT_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_USER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
_SCENARIO_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

_10_EMPLOYEES = [
    {
        "employee_id": str(uuid.UUID(f"{i:032d}")),
        "employee_number": f"EMP-{i:04d}",
        "first_name": f"Emp{i}",
        "last_name": "Test",
        "department_id": None,
        "department_name": None,
        "job_title": "Tester",
        "employment_status": "active",
        "hire_date": "2025-01-01",
        "monthly_salary": "5000.00",
        "currency": "USD",
        "monthly_benefit_cost": "500.00",
    }
    for i in range(1, 11)
]


class _FakeGateway:
    def __init__(self, employees: list[dict] | None = None) -> None:
        self._employees = employees or _10_EMPLOYEES
        self.call_count = 0

    async def get_payroll_base(self, as_of: str) -> dict[str, object]:
        self.call_count += 1
        return {
            "tenant_id": str(_TENANT_ID),
            "as_of": as_of,
            "currency": "USD",
            "headcount": len(self._employees),
            "monthly_salary_total": "0.00",
            "monthly_benefit_cost_total": "0.00",
            "employees": self._employees,
        }


class _FakeRepo:
    def __init__(self) -> None:
        self._rows: list[SimpleNamespace] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        kwargs["id"] = kwargs.pop("scenario_id")
        row = SimpleNamespace(**kwargs)
        self._rows.append(row)
        return row

    async def list_all(self, *, tenant_id: uuid.UUID) -> list[SimpleNamespace]:
        return list(self._rows)

    async def get(self, *, tenant_id: uuid.UUID, scenario_id: uuid.UUID) -> SimpleNamespace:
        for row in self._rows:
            if row.id == scenario_id:
                return row
        raise Exception("not found")


class _FakeAudit:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _make_service(
    employees: list[dict] | None = None,
) -> tuple[L4ScenarioService, _FakeGateway, _FakeRepo, _FakeAudit]:
    gateway = _FakeGateway(employees)
    repo = _FakeRepo()
    audit = _FakeAudit()
    service = L4ScenarioService(gateway=gateway, repository=repo, audit=audit)
    return service, gateway, repo, audit


class TestHandCheck:
    """The 10 x 5000 + 5% merit month-4 exact-cents contract."""

    async def test_10_x_5000_merit_5pct_month4(self) -> None:
        service, _, _, _ = _make_service()
        result = await service.create(
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            name="hand check",
            description=None,
            base_as_of=date(2026, 1, 1),
            horizon=12,
            actions_raw=[{"type": "salary_merit", "percent": "0.05", "effective_month": 4}],
        )

        proj = result["projection"]
        months = proj["months"]

        assert len(months) == 12

        # Months 1-3: 10 x 5000 = 50000 salary, 10 x 500 = 5000 benefit
        for m in months[:3]:
            assert m["salary_cost"] == "50000.00", f"month {m['month']}"
            assert m["benefit_cost"] == "5000.00", f"month {m['month']}"
            assert m["total_cost"] == "55000.00", f"month {m['month']}"

        # Months 4-12: 10 x 5250 = 52500 salary, 10 x 500 = 5000 benefit
        for m in months[3:]:
            assert m["salary_cost"] == "52500.00", f"month {m['month']}"
            assert m["benefit_cost"] == "5000.00", f"month {m['month']}"
            assert m["total_cost"] == "57500.00", f"month {m['month']}"

        # Salaries: 3 x 50000 + 9 x 52500 = 622500.00 (matches engine test).
        assert proj["salary_total"] == "622500.00"
        # Benefits: 12 x 5000 = 60000.00
        assert proj["benefit_total"] == "60000.00"
        assert proj["grand_total"] == "682500.00"

    async def test_actions_round_trip_through_wire_dict(self) -> None:
        service, _, _, _ = _make_service()
        action = {"type": "salary_merit", "percent": "0.05", "effective_month": 4}
        result = await service.create(
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            name="round trip",
            description=None,
            base_as_of=date(2026, 1, 1),
            horizon=12,
            actions_raw=[action],
        )
        assert result["actions"] == [action]

    async def test_new_hire_increases_headcount(self) -> None:
        service, _, _, _ = _make_service()
        new_emp = {
            "employee_number": "NEW-001",
            "first_name": "New",
            "last_name": "Person",
            "department_id": None,
            "department_name": None,
            "job_title": "Junior",
            "hire_date": "2026-03-01",
            "monthly_salary": "4000.00",
            "currency": "USD",
            "monthly_benefit_cost": "200.00",
        }
        result = await service.create(
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            name="new hire",
            description=None,
            base_as_of=date(2026, 1, 1),
            horizon=6,
            actions_raw=[{"type": "new_hire", "employee": new_emp, "effective_month": 3}],
        )
        months = result["projection"]["months"]
        assert months[0]["headcount"] == 10
        assert months[2]["headcount"] == 11


class TestRepoOperations:
    async def test_list_delegates_to_repo(self) -> None:
        service, _, _repo, _ = _make_service()
        await service.create(
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            name="a",
            description=None,
            base_as_of=date(2026, 1, 1),
            horizon=1,
            actions_raw=[],
        )
        rows = await service.list_scenarios(tenant_id=_TENANT_ID)
        assert len(rows) == 1
        assert rows[0]["name"] == "a"

    async def test_get_delegates_to_repo(self) -> None:
        service, _, _repo, _ = _make_service()
        row = await service.create(
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            name="b",
            description=None,
            base_as_of=date(2026, 1, 1),
            horizon=1,
            actions_raw=[],
        )
        result = await service.get(tenant_id=_TENANT_ID, scenario_id=row["id"])
        assert result["name"] == "b"

    async def test_compare_returns_requested_rows(self) -> None:
        service, _, _, _ = _make_service()
        r1 = await service.create(
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            name="x",
            description=None,
            base_as_of=date(2026, 1, 1),
            horizon=1,
            actions_raw=[],
        )
        r2 = await service.create(
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            name="y",
            description=None,
            base_as_of=date(2026, 1, 1),
            horizon=1,
            actions_raw=[],
        )
        result = await service.compare(
            tenant_id=_TENANT_ID,
            scenario_ids=[r1["id"], r2["id"]],
        )
        assert [r["name"] for r in result] == ["x", "y"]


class TestAudit:
    async def test_create_emits_audit_event(self) -> None:
        service, _, _, audit = _make_service()
        result = await service.create(
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            name="audit test",
            description=None,
            base_as_of=date(2026, 1, 1),
            horizon=1,
            actions_raw=[],
        )
        assert len(audit.calls) == 1
        call = audit.calls[0]
        assert call["action"] == AI_L4_SCENARIO_CREATED
        assert call["tenant_id"] == _TENANT_ID
        assert call["user_id"] == _USER_ID
        assert call["input_payload"]["scenario_id"] == str(result["id"])
