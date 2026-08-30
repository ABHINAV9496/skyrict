"""Pydantic request/response schemas for ``/ai/hr/attrition/score`` (spec §6)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmployeeFeatureInput(BaseModel):
    employee_ref: str = Field(..., description="opaque per-employee reference (core Employee UUID)")
    tenure_years: float = Field(..., ge=0, description="years since hire_date")
    compa_ratio: float = Field(..., ge=0, description="salary / department-baseline salary")
    promotion_gap_months: float = Field(
        ..., ge=0, description="months since last comp effective_from"
    )
    activity_count: float = Field(..., ge=0, description="recent leave/attendance record count")


class FactorOut(BaseModel):
    feature: str
    contribution: float
    direction: str


class ScoredEmployeeOut(BaseModel):
    employee_ref: str
    score: float
    risk_band: str
    confidence: float
    factors: list[FactorOut]


class ScoreRequest(BaseModel):
    employees: list[EmployeeFeatureInput] = Field(..., min_length=1)


class ScoreResponse(BaseModel):
    model_version: str
    model_source: str
    considered: int
    abstained: int
    scored: list[ScoredEmployeeOut]
