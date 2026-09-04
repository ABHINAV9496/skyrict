"""CRM API schemas - request bodies and response models (CRM-BE-002).

Request models validate client input; response models validate domain entities
(``from_attributes``) so the router stays a thin translation layer. Money
fields are exposed as ``amount`` + ``currency`` pairs; the service constructs
the :class:`Money` value objects (currency validation happens there).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from core.domain.value_objects import LeadStatus, OpportunityStage

# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


class LeadCreateRequest(BaseModel):
    source: str | None = Field(default=None, max_length=64)
    first_name: str | None = Field(default=None, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    company: str | None = Field(default=None, max_length=255)
    owner_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class LeadUpdateRequest(BaseModel):
    source: str | None = Field(default=None, max_length=64)
    first_name: str | None = Field(default=None, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    company: str | None = Field(default=None, max_length=255)
    owner_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    status: LeadStatus
    source: str | None
    first_name: str | None
    last_name: str | None
    email: str | None
    phone: str | None
    company: str | None
    owner_id: uuid.UUID | None
    team_id: uuid.UUID | None
    created_at: datetime | None
    updated_at: datetime | None


# ---------------------------------------------------------------------------
# Opportunities
# ---------------------------------------------------------------------------


class OpportunityCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    lead_id: uuid.UUID | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str = "USD"
    probability: int = Field(default=0, ge=0, le=100)
    expected_close_date: date | None = None
    owner_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class OpportunityUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    expected_close_date: date | None = None
    owner_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class LeadQualifyRequest(BaseModel):
    """Optional enrichment for the opportunity created by a lead qualify.

    The opportunity ``name`` is derived from the lead (first/last name or
    company) by the service, so the request never requires it.
    """

    amount: Decimal | None = Field(default=None, ge=0)
    currency: str = "USD"
    probability: int = Field(default=0, ge=0, le=100)
    expected_close_date: date | None = None
    owner_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class OpportunityStageRequest(BaseModel):
    stage: OpportunityStage
    lost_reason: str | None = Field(default=None, max_length=500)


class OpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    lead_id: uuid.UUID | None
    stage: OpportunityStage
    amount: Decimal | None
    currency: str | None
    probability: int
    expected_close_date: date | None
    owner_id: uuid.UUID | None
    team_id: uuid.UUID | None
    won_at: datetime | None
    lost_at: datetime | None
    lost_reason: str | None
    created_at: datetime | None
    updated_at: datetime | None


class OpportunityStageResponse(BaseModel):
    """Outcome of a pipeline transition - the customer appears on ``won``."""

    opportunity: OpportunityResponse
    customer: CustomerResponse | None


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


class CustomerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    credit_limit: Decimal | None = Field(default=None, ge=0)
    currency: str = "USD"


class CustomerUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    credit_limit: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    customer_code: str
    name: str
    source_opportunity_id: uuid.UUID | None
    email: str | None
    phone: str | None
    credit_limit: Decimal | None
    currency: str | None
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None
