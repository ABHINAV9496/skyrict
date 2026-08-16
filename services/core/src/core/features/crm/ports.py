"""CRM ports — persistence contract for the CRM feature.

Declares what the repository must offer so the future service depends on a
Protocol (hexagonal "ports") rather than the concrete SQLAlchemy
implementation. The repository lives in the same feature package, so there is
no import-linter violation.

Owner/team/all scoping: every read takes an explicit ``scope`` (a
:class:`DataScope` resolved ONCE per request by ``core.db.rbac`` — never a
role name) plus the caller's ``user_id`` / ``team_id``. The repository
translates that into a SQL filter; the service can only pass narrower ids, it
can never broaden the scope.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from core.domain.entities import Customer, Lead, Opportunity
    from core.domain.value_objects import DataScope, LeadStatus, OpportunityStage


class CrmRepositoryPort(Protocol):
    """Persistence contract for leads, opportunities, and customers."""

    # --- Document sequences (wired at the composition root) ---
    async def next_customer_sequence(self, tenant_id: uuid.UUID) -> int: ...

    # --- Leads ---
    async def create_lead(self, lead: Lead) -> Lead: ...

    async def get_lead(
        self,
        lead_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> Lead | None: ...

    async def list_leads(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        status: LeadStatus | None = None,
        source: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Lead]: ...

    async def count_leads(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        status: LeadStatus | None = None,
        source: str | None = None,
    ) -> int: ...

    async def find_leads_by_email(self, email: str, *, tenant_id: uuid.UUID) -> Sequence[Lead]: ...

    async def update_lead_status(
        self,
        lead_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        status: LeadStatus,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> Lead | None: ...

    async def update_lead(
        self,
        lead_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        changes: dict[str, object],
    ) -> Lead | None: ...

    # --- Opportunities ---
    async def create_opportunity(self, opportunity: Opportunity) -> Opportunity: ...

    async def get_opportunity(
        self,
        opportunity_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> Opportunity | None: ...

    async def get_opportunity_by_lead(
        self, lead_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Opportunity | None: ...

    async def list_opportunities(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        stage: OpportunityStage | None = None,
        from_close_date: date | None = None,
        to_close_date: date | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Opportunity]: ...

    async def count_opportunities(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        stage: OpportunityStage | None = None,
        from_close_date: date | None = None,
        to_close_date: date | None = None,
    ) -> int: ...

    async def update_opportunity_stage(
        self,
        opportunity_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        stage: OpportunityStage,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        won_at: datetime | None = None,
        lost_at: datetime | None = None,
        lost_reason: str | None = None,
    ) -> Opportunity | None: ...

    async def update_opportunity(
        self,
        opportunity_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        changes: dict[str, object],
    ) -> Opportunity | None: ...

    # --- Customers ---
    async def create_customer(self, customer: Customer) -> Customer: ...

    async def get_customer(
        self, customer_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Customer | None: ...

    async def get_customer_by_code(self, code: str, *, tenant_id: uuid.UUID) -> Customer | None: ...

    async def get_customer_by_source_opportunity(
        self, opportunity_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Customer | None: ...

    async def list_customers(
        self,
        *,
        tenant_id: uuid.UUID,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Customer]: ...

    async def count_customers(
        self,
        *,
        tenant_id: uuid.UUID,
        include_inactive: bool = False,
    ) -> int: ...

    async def update_customer(
        self,
        customer_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        changes: dict[str, object],
    ) -> Customer | None: ...

    async def deactivate_customer(
        self, customer_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Customer | None: ...
