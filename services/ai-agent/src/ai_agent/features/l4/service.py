"""L4 scenario service - orchestrates gateway → engine → store (SKY-93).

The service is the thin seam between I/O (gateway fetch, DB persist, audit
log) and the pure projection engine.  It parses the wire action dicts into
engine dataclasses, runs the engine, serializes the projection to JSONB, and
stores the frozen scenario.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from ai_agent.core.audit_events import AI_L4_SCENARIO_CREATED
from ai_agent.core.audit_service import AuditService
from ai_agent.db.l4_scenario_repository import L4ScenarioRepository
from ai_agent.features.l4.engine import (
    Action,
    BenefitChange,
    NewHire,
    PayrollBase,
    PayrollEmployee,
    Reduction,
    SalaryMerit,
    project,
)
from ai_agent.features.l4.gateway import L4CoreGatewayPort

_CENT = Decimal("0.01")


class L4ScenarioService:
    """Create, list, get, and compare named what-if scenarios."""

    def __init__(
        self,
        *,
        gateway: L4CoreGatewayPort,
        repository: L4ScenarioRepository,
        audit: AuditService,
    ) -> None:
        self._gateway = gateway
        self._repo = repository
        self._audit = audit

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        description: str | None,
        base_as_of: date,
        horizon: int,
        actions_raw: list[dict[str, object]],
    ) -> dict[str, object]:
        """Fetch the payroll base, project, freeze the snapshot, persist, audit."""
        base_data = await self._gateway.get_payroll_base(as_of=base_as_of.isoformat())
        payroll_base = _parse_payroll_base(base_data, base_as_of)
        actions = [_parse_action(a, base=payroll_base) for a in actions_raw]
        result = project(payroll_base, actions, horizon=horizon)
        snapshot = _serialize_projection(result)

        scenario_id = uuid.uuid4()
        row = await self._repo.create(
            tenant_id=tenant_id,
            scenario_id=scenario_id,
            name=name,
            description=description,
            base_as_of=base_as_of,
            horizon=horizon,
            currency=result.currency,
            actions=actions_raw,
            projection=snapshot,
            created_by=user_id,
        )
        await self._audit.log(
            action=AI_L4_SCENARIO_CREATED,
            tenant_id=tenant_id,
            user_id=user_id,
            input_payload={"scenario_id": str(scenario_id), "name": name},
        )
        return _scenario_row_to_dict(row)

    async def list_scenarios(self, *, tenant_id: uuid.UUID) -> list[dict[str, object]]:
        rows = await self._repo.list_all(tenant_id=tenant_id)
        return [_scenario_row_to_dict(row) for row in rows]

    async def get(self, *, tenant_id: uuid.UUID, scenario_id: uuid.UUID) -> dict[str, object]:
        row = await self._repo.get(tenant_id=tenant_id, scenario_id=scenario_id)
        return _scenario_row_to_dict(row)

    async def compare(
        self,
        *,
        tenant_id: uuid.UUID,
        scenario_ids: list[uuid.UUID],
    ) -> list[dict[str, object]]:
        rows = [await self._repo.get(tenant_id=tenant_id, scenario_id=sid) for sid in scenario_ids]
        return [_scenario_row_to_dict(row) for row in rows]


# ── payroll base / action parsing ─────────────────────────────────────────────


def _parse_payroll_base(data: dict[str, Any], as_of: date) -> PayrollBase:
    """Parse the core payroll-base ``data`` envelope into the engine's base."""
    currency = str(data.get("currency") or "USD")
    employees_raw = data.get("employees")
    if not isinstance(employees_raw, list):
        employees_raw = []
    employees = []
    for item in employees_raw:
        if not isinstance(item, dict):
            continue
        hire_date = item.get("hire_date")
        employees.append(
            PayrollEmployee(
                employee_id=str(item["employee_id"]),
                first_name=str(item.get("first_name") or ""),
                last_name=str(item.get("last_name") or ""),
                department_id=None
                if item.get("department_id") is None
                else str(item["department_id"]),
                department_name=None
                if item.get("department_name") is None
                else str(item["department_name"]),
                job_title=str(item.get("job_title") or ""),
                hire_date=date.fromisoformat(str(hire_date)) if hire_date else date.min,
                monthly_salary=Decimal(str(item.get("monthly_salary") or "0")),
                currency=currency,
                monthly_benefit_cost=Decimal(str(item.get("monthly_benefit_cost") or "0")),
            )
        )
    return PayrollBase(as_of=as_of, currency=currency, employees=tuple(employees))


def _parse_action(raw: dict[str, Any], *, base: PayrollBase) -> Action:
    """Parse one wire action dict into an engine Action dataclass."""
    action_type = raw.get("type")
    effective_month = int(raw.get("effective_month") or 0)

    if action_type == "salary_merit":
        return SalaryMerit(
            percent=Decimal(str(raw.get("percent") or "0")),
            effective_month=effective_month,
        )
    if action_type == "new_hire":
        emp_raw = raw.get("employee") or {}
        employee = PayrollEmployee(
            employee_id=str(emp_raw.get("employee_id") or uuid.uuid4()),
            first_name=str(emp_raw.get("first_name") or ""),
            last_name=str(emp_raw.get("last_name") or ""),
            department_id=None
            if emp_raw.get("department_id") is None
            else str(emp_raw["department_id"]),
            department_name=None
            if emp_raw.get("department_name") is None
            else str(emp_raw["department_name"]),
            job_title=str(emp_raw.get("job_title") or ""),
            hire_date=date.fromisoformat(str(emp_raw["hire_date"]))
            if emp_raw.get("hire_date")
            else date.min,
            monthly_salary=Decimal(str(emp_raw.get("monthly_salary") or "0")),
            currency=str(emp_raw.get("currency") or base.currency),
            monthly_benefit_cost=Decimal(str(emp_raw.get("monthly_benefit_cost") or "0")),
        )
        return NewHire(employee=employee, effective_month=effective_month)
    if action_type == "reduction":
        return Reduction(
            employee_id=str(raw.get("employee_id") or ""),
            effective_month=effective_month,
        )
    if action_type == "benefit_change":
        return BenefitChange(
            employee_id=str(raw.get("employee_id") or ""),
            monthly_benefit_cost=Decimal(str(raw.get("monthly_benefit_cost") or "0")),
            effective_month=effective_month,
        )
    raise ValueError(f"unknown action type {action_type!r}")


# ── serialization ─────────────────────────────────────────────────────────────


def _serialize_projection(result: object) -> dict[str, object]:
    """Engine result → JSONB-safe dict (money as 2dp strings)."""
    from ai_agent.features.l4.engine import ProjectionMonth, ProjectionResult

    if not isinstance(result, ProjectionResult):
        return {}
    return {
        "currency": result.currency,
        "horizon": result.horizon,
        "months": [
            {
                "month": month.month,
                "headcount": month.headcount,
                "salary_cost": f"{month.salary_cost.quantize(_CENT):.2f}",
                "benefit_cost": f"{month.benefit_cost.quantize(_CENT):.2f}",
                "total_cost": f"{month.total_cost.quantize(_CENT):.2f}",
            }
            for month in result.months
            if isinstance(month, ProjectionMonth)
        ],
        "salary_total": f"{result.salary_total.quantize(_CENT):.2f}",
        "benefit_total": f"{result.benefit_total.quantize(_CENT):.2f}",
        "grand_total": f"{result.grand_total.quantize(_CENT):.2f}",
    }


def _scenario_row_to_dict(row: object) -> dict[str, object]:
    """ORM row → plain dict (dates/JSONB shaped for Pydantic).

    Duck-typed so repository test doubles work alongside the real model
    without forcing tests to build ORM instances.
    """
    return {
        "id": row.id,  # type: ignore[attr-defined]
        "name": row.name,  # type: ignore[attr-defined]
        "description": row.description,  # type: ignore[attr-defined]
        "base_as_of": _to_iso(row.base_as_of),  # type: ignore[attr-defined]
        "horizon": row.horizon,  # type: ignore[attr-defined]
        "currency": row.currency,  # type: ignore[attr-defined]
        "actions": row.actions or [],  # type: ignore[attr-defined]
        "projection": row.projection or {},  # type: ignore[attr-defined]
        "created_by": row.created_by,  # type: ignore[attr-defined]
        "created_at": _to_iso(getattr(row, "created_at", None)),
    }


def _to_iso(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


__all__ = ["L4ScenarioService"]
