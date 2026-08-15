"""CRM repository — DB operations for leads, opportunities, and customers.

Concrete implementation of :class:`CrmRepositoryPort`. Every read is
tenant-scoped (``WHERE tenant_id = :tenant_id`` — defense in depth under RLS)
AND owner/team-scoped for leads and opportunities: the caller passes a
:class:`DataScope` (resolved once per request by ``core.db.rbac``) plus their
``user_id`` / ``team_id``, and :func:`_scope_filter` turns that into a SQL
predicate. The repository never sees a role name, so a role change cannot
silently broaden a query.

Scope semantics (fail closed — missing ids narrow, never broaden):

- ``OWNER``: rows where ``owner_id = user_id``; no user -> no rows.
- ``TEAM``: rows where ``owner_id = user_id`` OR ``team_id = team_id``;
  neither id -> no rows.
- ``ALL``: tenant filter only (RLS still bounds the tenant).

Unassigned rows (owner_id AND team_id NULL) are visible only to ``ALL``
scope — a deliberate strict default; the service layer can opt into broader
visibility explicitly.

Customers have no owner/team columns (locked SKY-43 decision), so they are
tenant-scoped only; ``is_active`` is their soft-delete flag.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, false, or_, select
from sqlalchemy.orm import Mapped

from core.domain.entities import Customer, Lead, Opportunity
from core.domain.value_objects import DataScope, LeadStatus, Money, OpportunityStage
from core.features.crm.models.customer import ErpCrmCustomerModel
from core.features.crm.models.lead import ErpCrmLeadModel
from core.features.crm.models.opportunity import ErpCrmOpportunityModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _scope_filter(
    *,
    scope: DataScope,
    owner: Mapped[uuid.UUID | None],
    team: Mapped[uuid.UUID | None],
    user_id: uuid.UUID | None,
    team_id: uuid.UUID | None,
) -> ColumnElement[bool] | None:
    """SQL predicate enforcing owner/team/all scoping on a lead/opportunity.

    Returns ``None`` for ALL scope (tenant filter only — RLS bounds the
    tenant). Fails closed: a missing user/team id narrows the result, never
    broadens it.
    """
    if scope is DataScope.OWNER:
        if user_id is None:
            return false()
        return owner == user_id
    if scope is DataScope.TEAM:
        predicates: list[ColumnElement[bool]] = []
        if user_id is not None:
            predicates.append(owner == user_id)
        if team_id is not None:
            predicates.append(team == team_id)
        if not predicates:
            return false()
        return or_(*predicates)
    return None


def _lead_to_orm(lead: Lead) -> ErpCrmLeadModel:
    kwargs: dict[str, object] = {
        "tenant_id": lead.tenant_id,
        "status": lead.status,
        "source": lead.source,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "email": lead.email,
        "phone": lead.phone,
        "company": lead.company,
        "owner_id": lead.owner_id,
        "team_id": lead.team_id,
    }
    if lead.id is not None:
        kwargs["id"] = lead.id
    return ErpCrmLeadModel(**kwargs)


def _lead_from_orm(model: ErpCrmLeadModel) -> Lead:
    return Lead(
        id=model.id,
        tenant_id=model.tenant_id,
        status=model.status,
        source=model.source,
        first_name=model.first_name,
        last_name=model.last_name,
        email=model.email,
        phone=model.phone,
        company=model.company,
        owner_id=model.owner_id,
        team_id=model.team_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _opportunity_to_orm(opportunity: Opportunity) -> ErpCrmOpportunityModel:
    kwargs: dict[str, object] = {
        "tenant_id": opportunity.tenant_id,
        "name": opportunity.name,
        "stage": opportunity.stage,
        "probability": opportunity.probability,
        "expected_close_date": opportunity.expected_close_date,
        "owner_id": opportunity.owner_id,
        "team_id": opportunity.team_id,
        "won_at": opportunity.won_at,
        "lost_at": opportunity.lost_at,
        "lost_reason": opportunity.lost_reason,
    }
    if opportunity.amount is not None:
        kwargs["amount"] = opportunity.amount.amount
        kwargs["currency_code"] = opportunity.amount.currency
    if opportunity.id is not None:
        kwargs["id"] = opportunity.id
    return ErpCrmOpportunityModel(**kwargs)


def _opportunity_from_orm(model: ErpCrmOpportunityModel) -> Opportunity:
    if model.amount is not None:
        # DB CHECK ck_erp_crm_opportunities_currency_present guarantees the
        # currency travels with a non-null amount.
        assert model.currency_code is not None
        amount: Money | None = Money(model.amount, model.currency_code)
    else:
        amount = None
    return Opportunity(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        stage=model.stage,
        amount=amount,
        probability=model.probability,
        expected_close_date=model.expected_close_date,
        owner_id=model.owner_id,
        team_id=model.team_id,
        won_at=model.won_at,
        lost_at=model.lost_at,
        lost_reason=model.lost_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _customer_to_orm(customer: Customer) -> ErpCrmCustomerModel:
    kwargs: dict[str, object] = {
        "tenant_id": customer.tenant_id,
        "customer_code": customer.customer_code,
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "is_active": customer.is_active,
    }
    if customer.credit_limit is not None:
        kwargs["credit_limit"] = customer.credit_limit.amount
        kwargs["currency_code"] = customer.credit_limit.currency
    if customer.id is not None:
        kwargs["id"] = customer.id
    return ErpCrmCustomerModel(**kwargs)


def _customer_from_orm(model: ErpCrmCustomerModel) -> Customer:
    if model.credit_limit is not None:
        # DB CHECK ck_erp_crm_customers_currency_present guarantees the
        # currency travels with a non-null limit.
        assert model.currency_code is not None
        credit_limit: Money | None = Money(model.credit_limit, model.currency_code)
    else:
        credit_limit = None
    return Customer(
        id=model.id,
        tenant_id=model.tenant_id,
        customer_code=model.customer_code,
        name=model.name,
        email=model.email,
        phone=model.phone,
        credit_limit=credit_limit,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class CrmRepository:
    """Concrete SQLAlchemy implementation of :class:`CrmRepositoryPort`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Leads
    # ------------------------------------------------------------------

    async def create_lead(self, lead: Lead) -> Lead:
        model = _lead_to_orm(lead)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _lead_from_orm(model)

    async def get_lead(
        self,
        lead_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> Lead | None:
        stmt = select(ErpCrmLeadModel).where(
            ErpCrmLeadModel.tenant_id == tenant_id,
            ErpCrmLeadModel.id == lead_id,
        )
        scoped = _scope_filter(
            scope=scope,
            owner=ErpCrmLeadModel.owner_id,
            team=ErpCrmLeadModel.team_id,
            user_id=user_id,
            team_id=team_id,
        )
        if scoped is not None:
            stmt = stmt.where(scoped)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _lead_from_orm(model) if model is not None else None

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
    ) -> list[Lead]:
        stmt = select(ErpCrmLeadModel).where(ErpCrmLeadModel.tenant_id == tenant_id)
        scoped = _scope_filter(
            scope=scope,
            owner=ErpCrmLeadModel.owner_id,
            team=ErpCrmLeadModel.team_id,
            user_id=user_id,
            team_id=team_id,
        )
        if scoped is not None:
            stmt = stmt.where(scoped)
        if status is not None:
            stmt = stmt.where(ErpCrmLeadModel.status == status)
        if source is not None:
            stmt = stmt.where(ErpCrmLeadModel.source == source)
        stmt = stmt.order_by(ErpCrmLeadModel.created_at.desc())
        result = await self.session.execute(stmt.offset(offset).limit(limit))
        return [_lead_from_orm(model) for model in result.scalars().all()]

    async def find_leads_by_email(self, email: str, *, tenant_id: uuid.UUID) -> list[Lead]:
        """Soft dedupe probe: every lead in the tenant with this email.

        Deliberately NON-unique at the DB level (locked SKY-43 decision) —
        the service layer decides how to act on duplicates. This probe is
        tenant-scoped only: it answers "has anyone in this tenant been
        approached at this address", not "can this user see them".
        """
        stmt = select(ErpCrmLeadModel).where(
            ErpCrmLeadModel.tenant_id == tenant_id,
            ErpCrmLeadModel.email == email,
        )
        result = await self.session.execute(stmt)
        return [_lead_from_orm(model) for model in result.scalars().all()]

    async def update_lead_status(
        self,
        lead_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        status: LeadStatus,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> Lead | None:
        stmt = select(ErpCrmLeadModel).where(
            ErpCrmLeadModel.tenant_id == tenant_id,
            ErpCrmLeadModel.id == lead_id,
        )
        scoped = _scope_filter(
            scope=scope,
            owner=ErpCrmLeadModel.owner_id,
            team=ErpCrmLeadModel.team_id,
            user_id=user_id,
            team_id=team_id,
        )
        if scoped is not None:
            stmt = stmt.where(scoped)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.status = status
        await self.session.flush()
        await self.session.refresh(model)
        return _lead_from_orm(model)

    # ------------------------------------------------------------------
    # Opportunities
    # ------------------------------------------------------------------

    async def create_opportunity(self, opportunity: Opportunity) -> Opportunity:
        model = _opportunity_to_orm(opportunity)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _opportunity_from_orm(model)

    async def get_opportunity(
        self,
        opportunity_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> Opportunity | None:
        stmt = select(ErpCrmOpportunityModel).where(
            ErpCrmOpportunityModel.tenant_id == tenant_id,
            ErpCrmOpportunityModel.id == opportunity_id,
        )
        scoped = _scope_filter(
            scope=scope,
            owner=ErpCrmOpportunityModel.owner_id,
            team=ErpCrmOpportunityModel.team_id,
            user_id=user_id,
            team_id=team_id,
        )
        if scoped is not None:
            stmt = stmt.where(scoped)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _opportunity_from_orm(model) if model is not None else None

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
    ) -> list[Opportunity]:
        stmt = select(ErpCrmOpportunityModel).where(ErpCrmOpportunityModel.tenant_id == tenant_id)
        scoped = _scope_filter(
            scope=scope,
            owner=ErpCrmOpportunityModel.owner_id,
            team=ErpCrmOpportunityModel.team_id,
            user_id=user_id,
            team_id=team_id,
        )
        if scoped is not None:
            stmt = stmt.where(scoped)
        if stage is not None:
            stmt = stmt.where(ErpCrmOpportunityModel.stage == stage)
        if from_close_date is not None:
            stmt = stmt.where(ErpCrmOpportunityModel.expected_close_date >= from_close_date)
        if to_close_date is not None:
            stmt = stmt.where(ErpCrmOpportunityModel.expected_close_date <= to_close_date)
        stmt = stmt.order_by(ErpCrmOpportunityModel.created_at.desc())
        result = await self.session.execute(stmt.offset(offset).limit(limit))
        return [_opportunity_from_orm(model) for model in result.scalars().all()]

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
    ) -> Opportunity | None:
        stmt = select(ErpCrmOpportunityModel).where(
            ErpCrmOpportunityModel.tenant_id == tenant_id,
            ErpCrmOpportunityModel.id == opportunity_id,
        )
        scoped = _scope_filter(
            scope=scope,
            owner=ErpCrmOpportunityModel.owner_id,
            team=ErpCrmOpportunityModel.team_id,
            user_id=user_id,
            team_id=team_id,
        )
        if scoped is not None:
            stmt = stmt.where(scoped)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.stage = stage
        model.won_at = won_at
        model.lost_at = lost_at
        model.lost_reason = lost_reason
        await self.session.flush()
        await self.session.refresh(model)
        return _opportunity_from_orm(model)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    async def create_customer(self, customer: Customer) -> Customer:
        model = _customer_to_orm(customer)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _customer_from_orm(model)

    async def get_customer(
        self, customer_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Customer | None:
        stmt = select(ErpCrmCustomerModel).where(
            ErpCrmCustomerModel.tenant_id == tenant_id,
            ErpCrmCustomerModel.id == customer_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _customer_from_orm(model) if model is not None else None

    async def get_customer_by_code(self, code: str, *, tenant_id: uuid.UUID) -> Customer | None:
        stmt = select(ErpCrmCustomerModel).where(
            ErpCrmCustomerModel.tenant_id == tenant_id,
            ErpCrmCustomerModel.customer_code == code,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _customer_from_orm(model) if model is not None else None

    async def list_customers(
        self,
        *,
        tenant_id: uuid.UUID,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Customer]:
        stmt = select(ErpCrmCustomerModel).where(ErpCrmCustomerModel.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(ErpCrmCustomerModel.is_active.is_(True))
        stmt = stmt.order_by(ErpCrmCustomerModel.name.asc())
        result = await self.session.execute(stmt.offset(offset).limit(limit))
        return [_customer_from_orm(model) for model in result.scalars().all()]

    async def deactivate_customer(
        self, customer_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Customer | None:
        stmt = select(ErpCrmCustomerModel).where(
            ErpCrmCustomerModel.tenant_id == tenant_id,
            ErpCrmCustomerModel.id == customer_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        model.is_active = False
        await self.session.flush()
        await self.session.refresh(model)
        return _customer_from_orm(model)
