"""CRM workspace API schemas - contacts, activities, notes, timeline.

Follows ``crm/schemas.py`` conventions: request models validate client input,
response models validate domain entities. Money values travel as plain
Decimals (currency tags live on the row) except the overview aggregates, which
use per-currency :class:`MoneyBucket` pairs so cross-currency sums never mix.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from core.domain.value_objects import (
    ActivityKind,
    CrmEntityType,
    LeadStatus,
    OpportunityStage,
)
from core.features.crm.schemas import OpportunityResponse

# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


class ContactCreateRequest(BaseModel):
    """Body for ``POST /crm/customers/{customer_id}/contacts`` (customer in path)."""

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    job_title: str | None = Field(default=None, max_length=255)
    is_primary: bool = False


class ContactUpdateRequest(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    job_title: str | None = Field(default=None, max_length=255)
    is_primary: bool | None = None


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    first_name: str | None
    last_name: str | None
    email: str | None
    phone: str | None
    job_title: str | None
    is_primary: bool
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


class ActivityCreateRequest(BaseModel):
    kind: ActivityKind
    entity_type: CrmEntityType
    entity_id: uuid.UUID
    subject: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    due_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=4000)
    owner_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class ActivityUpdateRequest(BaseModel):
    kind: ActivityKind | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    due_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=4000)
    owner_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    kind: ActivityKind
    entity_type: CrmEntityType
    entity_id: uuid.UUID
    subject: str
    description: str | None
    due_at: datetime | None
    completed_at: datetime | None
    completed_by: uuid.UUID | None
    notes: str | None
    owner_id: uuid.UUID | None
    team_id: uuid.UUID | None
    created_at: datetime | None
    updated_at: datetime | None


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


class NoteCreateRequest(BaseModel):
    entity_type: CrmEntityType
    entity_id: uuid.UUID
    body: str = Field(..., min_length=1, max_length=4000)


class NoteUpdateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    entity_type: CrmEntityType
    entity_id: uuid.UUID
    body: str
    author_id: uuid.UUID | None
    created_at: datetime | None
    updated_at: datetime | None


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


class TimelineItemResponse(BaseModel):
    """One merged row of the relationship timeline (DB-layer UNION)."""

    source: str
    id: uuid.UUID
    entity_type: CrmEntityType
    entity_id: uuid.UUID
    kind: str | None
    title: str | None
    body: str | None
    actor_id: uuid.UUID | None
    occurred_at: datetime


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


class MoneyBucket(BaseModel):
    currency: str
    amount: Decimal


class LeadStatusCountResponse(BaseModel):
    status: LeadStatus
    count: int


class LeadSourceCountResponse(BaseModel):
    source: str | None
    count: int


class StageBucketResponse(BaseModel):
    stage: OpportunityStage
    count: int
    value: list[MoneyBucket]


class LeadsOverviewResponse(BaseModel):
    total: int
    by_status: list[LeadStatusCountResponse]
    by_source: list[LeadSourceCountResponse]


class OpportunitiesOverviewResponse(BaseModel):
    open_count: int
    open_value: list[MoneyBucket]
    by_stage: list[StageBucketResponse]
    won_count: int
    won_value: list[MoneyBucket]
    lost_count: int
    win_rate: Decimal | None


class CustomersOverviewResponse(BaseModel):
    total: int
    active: int


class ActivitiesOverviewResponse(BaseModel):
    today: int
    overdue: int
    upcoming: int
    completed_30d: int


class CrmOverviewResponse(BaseModel):
    leads: LeadsOverviewResponse
    opportunities: OpportunitiesOverviewResponse
    customers: CustomersOverviewResponse
    activities: ActivitiesOverviewResponse
    recent_won: list[OpportunityResponse]
    top_opportunities: list[OpportunityResponse]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchHitResponse(BaseModel):
    entity_type: CrmEntityType
    entity_id: uuid.UUID
    title: str
    subtitle: str | None
