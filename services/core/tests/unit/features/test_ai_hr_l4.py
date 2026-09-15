"""Unit tests for the HR-AI-004 payroll-base endpoint (Commit 1, SKY-93).

Covers: money always serialized as exact two-decimal strings (the hand-check
contract), the envelope shape, `erp.ai.invoke` + `erp.hr.ai.planning` both
required, and tenant scoping via the authenticated user's tenant. Auth deps
and the repository are stubbed so no DB is needed.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.features.ai_hr import router as ai_hr_router
from core.features.ai_hr.l4_repository import (
    PayrollBase,
    PayrollBaseEmployee,
)
from core.features.ai_hr.l4_schemas import money, payroll_base_to_out
from core.features.finance.ports import BudgetDraftOutcome

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
EMP_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _employee(index: int, salary: str, benefit: str) -> PayrollBaseEmployee:
    return PayrollBaseEmployee(
        employee_id=uuid.uuid4(),
        employee_number=f"E-{index:03d}",
        first_name="Ada",
        last_name=f"L{index}",
        department_id=None,
        department_name=None,
        job_title="Engineer",
        employment_status="active",
        hire_date=date(2024, 1, 1),
        monthly_salary=Decimal(salary),
        currency="USD",
        monthly_benefit_cost=Decimal(benefit),
    )


def _base(employees: tuple[PayrollBaseEmployee, ...]) -> PayrollBase:
    return PayrollBase(
        tenant_id=TENANT_ID,
        as_of=date(2026, 1, 1),
        currency="USD",
        employees=employees,
    )


class _FakeRepo:
    def __init__(self, base: PayrollBase) -> None:
        self.base = base
        self.calls: list[tuple[uuid.UUID, date]] = []

    async def get_payroll_base(self, tenant_id: uuid.UUID, *, as_of: date) -> PayrollBase:
        self.calls.append((tenant_id, as_of))
        return self.base


def _build_app(repo: _FakeRepo) -> TestClient:
    app = FastAPI()
    app.include_router(ai_hr_router.router, prefix="/api/v1")
    app.dependency_overrides[ai_hr_router._require_ai_invoke] = lambda: {
        "tenant_id": str(TENANT_ID)
    }
    app.dependency_overrides[ai_hr_router._require_hr_ai_planning] = lambda: {
        "tenant_id": str(TENANT_ID),
        "user_id": str(uuid.uuid4()),
    }
    app.dependency_overrides[ai_hr_router.get_l4_payroll_repository] = lambda: repo
    return TestClient(app)


def test_payroll_base_money_is_exact_string_and_enveloped() -> None:
    base = _base((_employee(1, "5000.0000", "500"), _employee(2, "5250.0000", "0")))
    repo = _FakeRepo(base)
    client = _build_app(repo)

    resp = client.get(
        "/api/v1/ai/hr/l4/payroll-base?as_of=2026-06-01",
        headers={"authorization": "Bearer tok"},
    )
    assert resp.status_code == 200
    assert repo.calls == [(TENANT_ID, date(2026, 6, 1))]

    body = resp.json()["data"]
    assert body["tenant_id"] == str(TENANT_ID)
    assert body["as_of"] == "2026-01-01"
    assert body["currency"] == "USD"
    assert body["headcount"] == 2
    # Aggregates are summed in Decimal and serialized to fixed cents.
    assert body["monthly_salary_total"] == "10250.00"
    assert body["monthly_benefit_cost_total"] == "500.00"

    (first, second) = body["employees"]
    assert first["monthly_salary"] == "5000.00"
    assert first["monthly_benefit_cost"] == "500.00"
    assert second["monthly_salary"] == "5250.00"
    assert second["monthly_benefit_cost"] == "0.00"
    assert set(first) == {
        "employee_id",
        "employee_number",
        "first_name",
        "last_name",
        "department_id",
        "department_name",
        "job_title",
        "employment_status",
        "hire_date",
        "monthly_salary",
        "currency",
        "monthly_benefit_cost",
    }


def test_payroll_base_handcheck_totals_are_exact() -> None:
    """10 x 5000 with zero benefits - the engine hand-check input contract."""
    base = _base(tuple(_employee(i, "5000.0000", "0") for i in range(10)))
    out = payroll_base_to_out(base)
    assert out.monthly_salary_total == "50000.00"
    assert out.headcount == 10


def test_money_rounds_four_decimal_input_to_cents_losslessly() -> None:
    assert money(Decimal("5000.0000")) == "5000.00"
    assert money(Decimal("52500.0000")) == "52500.00"
    assert money(Decimal("0")) == "0.00"
    assert money(Decimal("123.456")) == "123.46"


def test_payroll_base_requires_planning_permission() -> None:
    """Without erp.hr.ai.planning granted the route must 403 (owner-only gate)."""
    repo = _FakeRepo(_base(()))
    client = _build_app(repo)
    client.app.dependency_overrides[ai_hr_router._require_hr_ai_planning] = lambda: _deny()

    resp = client.get("/api/v1/ai/hr/l4/payroll-base")
    assert resp.status_code == 403


def _deny() -> None:
    from fastapi import HTTPException

    raise HTTPException(status_code=403, detail="access denied")


def test_money_helper_never_emits_floats() -> None:
    # Decimal input always -> str; a float would fail the contract loudly.
    assert isinstance(money(Decimal("1.00")), str)


def test_empty_base_defaults_currency_and_zero_totals() -> None:
    out = payroll_base_to_out(_base(()))
    assert out.currency == "USD"
    assert out.headcount == 0
    assert out.monthly_salary_total == "0.00"
    assert out.monthly_benefit_cost_total == "0.00"
    assert out.employees == []


# --- L4 scenario proxy -> ai-agent (Commit 2, SKY-93) ------------------------

_SCENARIO_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _build_proxy_app(seen: list[httpx.Request]) -> TestClient:
    """App with an ai-client over MockTransport; records every relayed request."""
    app = FastAPI()
    app.include_router(ai_hr_router.router, prefix="/api/v1")
    app.dependency_overrides[ai_hr_router._require_ai_invoke] = lambda: {
        "tenant_id": str(TENANT_ID)
    }
    app.dependency_overrides[ai_hr_router._require_hr_ai_planning] = lambda: {
        "tenant_id": str(TENANT_ID),
        "user_id": str(uuid.uuid4()),
    }

    def capture_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"success": True, "data": {"id": str(_SCENARIO_ID)}, "message": "ok"},
        )

    async def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(capture_handler),
            base_url="http://ai-agent.test",
        )

    app.dependency_overrides[ai_hr_router.get_ai_client] = client_factory
    return TestClient(app)


def test_proxy_relays_scenario_create_to_ai_agent() -> None:
    seen: list[httpx.Request] = []
    client = _build_proxy_app(seen)

    resp = client.post(
        "/api/v1/ai/hr/l4/scenarios",
        headers={"authorization": "Bearer tok"},
        json={"name": "five-percent", "base_as_of": "2026-01-01"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == str(_SCENARIO_ID)
    assert len(seen) == 1
    assert seen[0].url.path == "/api/v1/ai/l4/scenarios"
    assert seen[0].headers.get("authorization") == "Bearer tok"


def test_proxy_relays_scenario_get_with_id_path() -> None:
    seen: list[httpx.Request] = []
    client = _build_proxy_app(seen)

    resp = client.get(
        f"/api/v1/ai/hr/l4/scenarios/{_SCENARIO_ID}",
        headers={"authorization": "Bearer tok"},
    )

    assert resp.status_code == 200
    assert seen[0].url.path == f"/api/v1/ai/l4/scenarios/{_SCENARIO_ID}"


def test_proxy_relays_scenario_compare_query_params() -> None:
    seen: list[httpx.Request] = []
    client = _build_proxy_app(seen)
    other = uuid.uuid4()

    resp = client.get(
        f"/api/v1/ai/hr/l4/scenarios/compare?ids={_SCENARIO_ID}&ids={other}",
        headers={"authorization": "Bearer tok"},
    )

    assert resp.status_code == 200
    assert seen[0].url.path == "/api/v1/ai/l4/scenarios/compare"
    query = seen[0].url.query.decode()
    assert f"ids={_SCENARIO_ID}" in query
    assert f"ids={other}" in query


def test_proxy_requires_planning_permission() -> None:
    seen: list[httpx.Request] = []
    client = _build_proxy_app(seen)
    client.app.dependency_overrides[ai_hr_router._require_hr_ai_planning] = lambda: _deny()

    resp = client.get("/api/v1/ai/hr/l4/scenarios")
    assert resp.status_code == 403
    assert seen == []  # never reached ai-agent


# --- L4 scenario export -> finance budget draft (Commit 4, SKY-93) ----------

_USER_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class _FakeFinance:
    def __init__(self, outcome: BudgetDraftOutcome) -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    async def create_workforce_budget_draft(
        self,
        *,
        tenant_id,
        scenario_id,
        scenario_name,
        currency,
        horizon,
        base_as_of,
        salary_total,
        benefit_total,
        grand_total,
        created_by,
    ) -> BudgetDraftOutcome:
        self.calls.append(
            {
                "tenant_id": str(tenant_id),
                "scenario_id": str(scenario_id),
                "scenario_name": scenario_name,
                "currency": currency,
                "horizon": horizon,
                "base_as_of": str(base_as_of),
                "salary_total": str(salary_total),
                "benefit_total": str(benefit_total),
                "grand_total": str(grand_total),
                "created_by": str(created_by),
            }
        )
        return self.outcome


class _FakeAudit:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def log(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _scenario_payload(name: str = "five-percent") -> dict:
    return {
        "id": str(_SCENARIO_ID),
        "name": name,
        "description": None,
        "base_as_of": "2026-01-01",
        "horizon": 12,
        "currency": "USD",
        "actions": [],
        "created_by": str(_USER_ID),
        "created_at": "2026-01-02T00:00:00Z",
        "projection": {
            "currency": "USD",
            "horizon": 12,
            "months": [{"month": "2026-01", "salary": "4375.00", "benefit": "437.50"}],
            "salary_total": "52500.00",
            "benefit_total": "5250.00",
            "grand_total": "57750.00",
        },
    }


def _build_export_app(
    finance: _FakeFinance,
    audit: _FakeAudit,
    upstream_status: int = 200,
    upstream_body: dict | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(ai_hr_router.router, prefix="/api/v1")
    app.dependency_overrides[ai_hr_router._require_ai_invoke] = lambda: {
        "tenant_id": str(TENANT_ID)
    }
    app.dependency_overrides[ai_hr_router._require_hr_ai_planning] = lambda: {
        "tenant_id": str(TENANT_ID),
        "user_id": str(_USER_ID),
    }
    app.dependency_overrides[ai_hr_router.get_ai_client] = lambda: _client_for(
        upstream_status, upstream_body
    )
    app.dependency_overrides[ai_hr_router.get_finance_service] = lambda: finance
    app.dependency_overrides[ai_hr_router.get_core_audit_service] = lambda: audit
    return TestClient(app)


def _client_for(status: int, body: dict | None) -> httpx.AsyncClient:
    if body is None:
        body = {"success": True, "data": _scenario_payload(), "message": "ok"}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ai-agent.test"
    )


def test_export_creates_budget_draft_and_audits() -> None:
    finance = _FakeFinance(BudgetDraftOutcome(draft_id=uuid.uuid4(), already_booked=False))
    audit = _FakeAudit()
    client = _build_export_app(finance, audit)

    resp = client.post(
        f"/api/v1/ai/hr/l4/scenarios/{_SCENARIO_ID}/export",
        headers={"authorization": "Bearer tok"},
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["already_booked"] is False
    assert body["draft_id"] == str(finance.outcome.draft_id)

    assert finance.calls == [
        {
            "tenant_id": str(TENANT_ID),
            "scenario_id": str(_SCENARIO_ID),
            "scenario_name": "five-percent",
            "currency": "USD",
            "horizon": 12,
            "base_as_of": "2026-01-01",
            "salary_total": "52500.00",
            "benefit_total": "5250.00",
            "grand_total": "57750.00",
            "created_by": str(_USER_ID),
        }
    ]
    assert len(audit.calls) == 1
    assert audit.calls[0]["action"] == "hr.ai.l4.budget_draft.created"
    assert audit.calls[0]["target"] == f"scenario:{_SCENARIO_ID}"
    assert audit.calls[0]["tenant_id"] == TENANT_ID
    assert audit.calls[0]["details"]["grand_total"] == "57750.00"


def test_export_replay_reports_already_booked() -> None:
    draft_id = uuid.uuid4()
    finance = _FakeFinance(BudgetDraftOutcome(draft_id=draft_id, already_booked=True))
    audit = _FakeAudit()
    client = _build_export_app(finance, audit)

    resp = client.post(
        f"/api/v1/ai/hr/l4/scenarios/{_SCENARIO_ID}/export",
        headers={"authorization": "Bearer tok"},
    )

    assert resp.status_code == 200
    assert resp.json()["data"] == {
        "draft_id": str(draft_id),
        "already_booked": True,
    }
    assert len(finance.calls) == 1  # idempotency is enforced in the service


def test_export_forwards_wrapped_response_from_ai_agent() -> None:
    """ai-agent may reply with a bare payload (no {data: ...}); both shapes work."""
    finance = _FakeFinance(BudgetDraftOutcome(draft_id=uuid.uuid4(), already_booked=False))
    audit = _FakeAudit()
    client = _build_export_app(finance, audit, upstream_body=_scenario_payload())

    resp = client.post(
        f"/api/v1/ai/hr/l4/scenarios/{_SCENARIO_ID}/export",
        headers={"authorization": "Bearer tok"},
    )

    assert resp.status_code == 200
    assert finance.calls[0]["scenario_name"] == "five-percent"


def test_export_relays_upstream_failure() -> None:
    finance = _FakeFinance(BudgetDraftOutcome(draft_id=uuid.uuid4(), already_booked=False))
    audit = _FakeAudit()
    client = _build_export_app(
        finance,
        audit,
        upstream_status=404,
        upstream_body={"success": False, "message": "scenario not found"},
    )

    resp = client.post(
        f"/api/v1/ai/hr/l4/scenarios/{_SCENARIO_ID}/export",
        headers={"authorization": "Bearer tok"},
    )

    assert resp.status_code == 404
    assert finance.calls == []  # nothing persisted on a bad upstream read
    assert audit.calls == []


def test_export_requires_planning_permission() -> None:
    finance = _FakeFinance(BudgetDraftOutcome(draft_id=uuid.uuid4(), already_booked=False))
    audit = _FakeAudit()
    client = _build_export_app(finance, audit)
    client.app.dependency_overrides[ai_hr_router._require_hr_ai_planning] = lambda: _deny()

    resp = client.post(
        f"/api/v1/ai/hr/l4/scenarios/{_SCENARIO_ID}/export",
        headers={"authorization": "Bearer tok"},
    )

    assert resp.status_code == 403
    assert finance.calls == []  # gate closes before any downstream work
