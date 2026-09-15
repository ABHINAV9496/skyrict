"""Integration test for the L4 export bridge (HR-AI-004, SKY-93, Commit 4).

Runs against a real Postgres (skipped w/o DB; requires ``migrated_schema``).
Covers: the payroll-base owner-only gate (403 without planning keys), a 200
with exact money strings from live ``erp_compensation`` rows, tenant isolation,
and the budget-draft export flow — a frozen ai-agent scenario becoming a
proposed ``erp_budget_drafts`` row with two cost lines, and idempotent replay
(``already_booked`` without a second row).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import text

from core.db.session import async_session_factory
from core.features.ai.router import get_ai_client
from core.main import app

from .helpers import hire_employee

if TYPE_CHECKING:
    from collections.abc import Callable

    from httpx import AsyncClient

pytestmark = pytest.mark.integration

_PLANNING_KEYS = ("erp.ai.invoke", "erp.hr.ai.planning")
_BUDGET_DRAFT_SOURCE = "workforce_plan"


def _frozen_scenario(scenario_id: uuid.UUID) -> dict[str, Any]:
    """The exact body ai-agent returns for ``GET /api/v1/ai/l4/scenarios/{id}``.

    Bare ``ScenarioOut`` (not the ``data`` envelope) — the export endpoint
    accepts both shapes; this mirrors the live microservice.
    """
    return {
        "id": str(scenario_id),
        "name": "phase-2-headcount",
        "description": None,
        "base_as_of": "2026-06-01",
        "horizon": 12,
        "currency": "USD",
        "actions": [],
        "projection": {
            "currency": "USD",
            "horizon": 12,
            "salary_total": "240000.00",
            "benefit_total": "12000.00",
            "grand_total": "252000.00",
        },
        "created_by": str(uuid.uuid4()),
        "created_at": "2026-06-01",
    }


async def _grant_planning_keys(tenant_id: uuid.UUID) -> None:
    """Append the L4 gate keys to olympus's organization_admin role.

    Inverts the owner-only default for this test only: the seeded test admin
    sub holds organization_admin, and granting the two keys to that role is the
    cheapest stable stand-in for an owner who passes everything via ``*``.
    """
    async with async_session_factory() as session:
        for key in _PLANNING_KEYS:
            await session.execute(
                text(
                    "UPDATE core_roles SET permissions = array_append(permissions, :key) "
                    "WHERE tenant_id = :tenant_id AND name = 'organization_admin' "
                    "AND NOT (:key = ANY(permissions))"
                ),
                {"key": key, "tenant_id": tenant_id},
            )
        await session.commit()


class TestL4PayrollBase:
    async def test_403_without_planning_permission(
        self,
        client: AsyncClient,
        tenant_headers: Callable[..., dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        # admin holds only the six erp.hr.*/erp.payroll.* keys - not the gate.
        response = await client.get(
            "/api/v1/ai/hr/l4/payroll-base", headers=tenant_headers("olympus")
        )
        assert response.status_code == 403, response.text

    async def test_200_with_exact_money_from_seeded_roster(
        self,
        client: AsyncClient,
        integration_db: dict[str, str],
        tenant_headers: Callable[..., dict[str, str]],
    ) -> None:
        olympus_id = uuid.UUID(integration_db["acme_id"])
        await _grant_planning_keys(olympus_id)
        headers = tenant_headers("olympus")

        await hire_employee(client, headers, first_name="Ada", monthly_salary="5000.00")
        await hire_employee(client, headers, first_name="Grace", monthly_salary="5250.00")

        response = await client.get("/api/v1/ai/hr/l4/payroll-base", headers=headers)
        assert response.status_code == 200, response.text
        body = cast("dict[str, Any]", response.json()["data"])
        assert body["tenant_id"] == str(olympus_id)
        assert body["headcount"] == 2
        assert body["currency"] == "USD"
        assert body["monthly_salary_total"] == "10250.00"
        assert body["monthly_benefit_cost_total"] == "0.00"
        salaries = sorted(emp["monthly_salary"] for emp in body["employees"])
        assert salaries == ["5000.00", "5250.00"]
        assert all(emp["monthly_benefit_cost"] == "0.00" for emp in body["employees"])

    async def test_tenant_isolation_still_403(
        self,
        client: AsyncClient,
        integration_db: dict[str, str],
        tenant_headers: Callable[..., dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        # Grant only olympus; globex's admin must stay locked out.
        await _grant_planning_keys(uuid.UUID(integration_db["acme_id"]))
        response = await client.get(
            "/api/v1/ai/hr/l4/payroll-base", headers=tenant_headers("globex")
        )
        assert response.status_code == 403, response.text


class TestL4BudgetDraftExport:
    async def test_export_proposes_draft_and_replay_is_idempotent(
        self,
        client: AsyncClient,
        integration_db: dict[str, str],
        tenant_headers: Callable[..., dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        await _grant_planning_keys(uuid.UUID(integration_db["acme_id"]))
        scenario_id = uuid.uuid4()

        import httpx

        async def _mock_upstream(request: httpx.Request) -> httpx.Response:
            assert request.url.path == f"/api/v1/ai/l4/scenarios/{scenario_id}"
            return httpx.Response(200, json=_frozen_scenario(scenario_id))

        mock_client = httpx.AsyncClient(
            transport=httpx.MockTransport(_mock_upstream), base_url="http://ai-agent"
        )
        app.dependency_overrides[get_ai_client] = lambda: mock_client
        try:
            headers = tenant_headers("olympus")
            url = f"/api/v1/ai/hr/l4/scenarios/{scenario_id}/export"

            first = await client.post(url, headers=headers)
            assert first.status_code == 200, first.text
            body = first.json()["data"]
            assert body["already_booked"] is False
            draft_id = uuid.UUID(body["draft_id"])

            async with async_session_factory() as session:
                draft = (
                    (
                        await session.execute(
                            text(
                                "SELECT scenario_id, scenario_name, status, source, "
                                "source_ref, currency, horizon, salary_total, "
                                "benefit_total, grand_total FROM erp_budget_drafts "
                                "WHERE tenant_id = :tenant AND id = :id"
                            ),
                            {"tenant": integration_db["acme_id"], "id": draft_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert draft["scenario_id"] == scenario_id
                assert draft["scenario_name"] == "phase-2-headcount"
                assert draft["status"] == "draft"
                assert draft["source"] == _BUDGET_DRAFT_SOURCE
                assert draft["source_ref"] == str(scenario_id)
                assert draft["currency"] == "USD"
                assert draft["horizon"] == 12
                assert str(draft["salary_total"]) == "240000.00"
                assert str(draft["benefit_total"]) == "12000.00"
                assert str(draft["grand_total"]) == "252000.00"

                lines = (
                    (
                        await session.execute(
                            text(
                                "SELECT line_no, label, amount FROM erp_budget_draft_lines "
                                "WHERE tenant_id = :tenant AND draft_id = :id ORDER BY line_no"
                            ),
                            {"tenant": integration_db["acme_id"], "id": draft_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                assert [(r["line_no"], r["label"]) for r in lines] == [
                    (1, "Salary"),
                    (2, "Benefits"),
                ]
                assert [str(r["amount"]) for r in lines] == [
                    "240000.00",
                    "12000.00",
                ]

                replay = await client.post(url, headers=headers)
                assert replay.status_code == 200, replay.text
                replay_body = replay.json()["data"]
                assert replay_body["already_booked"] is True
                assert uuid.UUID(replay_body["draft_id"]) == draft_id

                count = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM erp_budget_drafts "
                            "WHERE tenant_id = :tenant AND source = :source "
                            "AND source_ref = :ref"
                        ),
                        {
                            "tenant": integration_db["acme_id"],
                            "source": _BUDGET_DRAFT_SOURCE,
                            "ref": str(scenario_id),
                        },
                    )
                ).scalar_one()
                assert count == 1, "replayed export must not create a second draft"
        finally:
            app.dependency_overrides.pop(get_ai_client, None)
            await mock_client.aclose()
