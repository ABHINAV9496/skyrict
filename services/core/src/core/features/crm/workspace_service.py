"""CRM workspace service - contacts, activities, notes, timeline, overview.

Extends :class:`CrmService` (leads/opportunities/customers) with the CRM
workspace surface: contacts (people on accounts), the unified activity model
(tasks/follow-ups/calls/meetings/emails/notes), persistent notes, the merged
relationship timeline, the overview dashboard, and server-side search.

Conventions:
- Reads use the request-resolved :class:`DataScope` + caller ids - the service
  can only narrow, never broaden. Activities are owner/team-scoped; contacts,
  notes, and timeline events are tenant-scoped (like customers).
- Timeline records are written transactionally here (or in the sales service
  for order creations) - the curated CRM business log is SEPARATE from the
  security ``audit_logs`` trail and from the async ``crm.*`` domain events.
- Every mutation audits through the shared ``audit_logs`` trail AND emits its
  domain event via the after-commit buffer.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from core.audit_events import (
    CRM_ACTIVITY_COMPLETED,
    CRM_ACTIVITY_CREATED,
    CRM_ACTIVITY_DELETED,
    CRM_ACTIVITY_UPDATED,
    CRM_CONTACT_CREATED,
    CRM_CONTACT_DEACTIVATED,
    CRM_CONTACT_UPDATED,
    CRM_NOTE_CREATED,
    CRM_NOTE_DELETED,
    CRM_NOTE_UPDATED,
)
from core.core.exceptions import IllegalStateTransitionError
from core.core.tenant_context import TenantContext
from core.domain.entities import Activity, Contact, CrmSearchHit, Note, TimelineItem
from core.domain.value_objects import (
    ActivityKind,
    CrmEntityType,
    CrmTimelineEventType,
    DataScope,
    LeadStatus,
    OpportunityStage,
)
from core.events.producers.crm_events import (
    emit_activity_completed,
    emit_activity_created,
    emit_contact_created,
    emit_note_created,
)
from skyrict_common.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from core.domain.entities import Customer, Opportunity
    from core.features.audit.service import AuditService
    from core.features.crm.ports import CrmWorkspaceRepositoryPort

_ACTIVITY_KIND_MUTABLE = {
    "kind",
    "subject",
    "description",
    "due_at",
    "notes",
    "owner_id",
    "team_id",
}


@dataclass(frozen=True)
class MoneyBucket:
    """A currency-tagged value aggregate (sums stay per-currency)."""

    currency: str
    amount: Decimal


@dataclass(frozen=True)
class LeadStatusCount:
    status: LeadStatus
    count: int


@dataclass(frozen=True)
class LeadSourceCount:
    source: str | None
    count: int


@dataclass(frozen=True)
class StageBucket:
    stage: OpportunityStage
    count: int
    value: tuple[MoneyBucket, ...]


@dataclass(frozen=True)
class LeadsOverview:
    total: int
    by_status: tuple[LeadStatusCount, ...]
    by_source: tuple[LeadSourceCount, ...]


@dataclass(frozen=True)
class OpportunitiesOverview:
    open_count: int
    open_value: tuple[MoneyBucket, ...]
    by_stage: tuple[StageBucket, ...]
    won_count: int
    won_value: tuple[MoneyBucket, ...]
    lost_count: int
    win_rate: Decimal | None


@dataclass(frozen=True)
class CustomersOverview:
    total: int
    active: int


@dataclass(frozen=True)
class ActivitiesOverview:
    today: int
    overdue: int
    upcoming: int
    completed_30d: int


@dataclass(frozen=True)
class CrmOverview:
    leads: LeadsOverview
    opportunities: OpportunitiesOverview
    customers: CustomersOverview
    activities: ActivitiesOverview
    recent_won: tuple[Opportunity, ...]
    top_opportunities: tuple[Opportunity, ...]


class CrmWorkspaceService:
    """Business rules for the CRM workspace surface."""

    def __init__(
        self,
        repository: CrmWorkspaceRepositoryPort,
        audit: AuditService,
    ) -> None:
        self._repo = repository
        self._audit_service = audit

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    async def create_contact(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        phone: str | None,
        job_title: str | None,
        is_primary: bool,
    ) -> Contact:
        await self._require_customer(customer_id, tenant_id=tenant_id)
        if not any((first_name, last_name, email)):
            raise ValidationError("A contact needs at least one of first name, last name, or email")
        contact = Contact(
            tenant_id=tenant_id,
            customer_id=customer_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            job_title=job_title,
            is_primary=is_primary,
        )
        created = await self._repo.create_contact(contact)
        assert created.id is not None
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_CONTACT_CREATED,
            target=f"contact:{created.id}",
            details={"customer_id": str(customer_id), "email": email},
        )
        await emit_contact_created(
            contact_id=created.id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            email=email,
        )
        await self._record_timeline(
            tenant_id=tenant_id,
            entity_type=CrmEntityType.CONTACT,
            entity_id=created.id,
            event_type=CrmTimelineEventType.CONTACT_CREATED,
            title="Contact added",
            payload={"customer_id": str(customer_id), "name": created.first_name or created.email},
        )
        return created

    async def get_contact(self, contact_id: uuid.UUID, *, tenant_id: uuid.UUID) -> Contact:
        contact = await self._repo.get_contact(contact_id, tenant_id=tenant_id)
        if contact is None:
            raise NotFoundError(f"Contact {contact_id} not found")
        return contact

    async def list_contacts(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Contact]:
        return list(
            await self._repo.list_contacts(
                tenant_id=tenant_id,
                customer_id=customer_id,
                include_inactive=include_inactive,
                offset=offset,
                limit=limit,
            )
        )

    async def count_contacts(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        include_inactive: bool = False,
    ) -> int:
        return await self._repo.count_contacts(
            tenant_id=tenant_id,
            customer_id=customer_id,
            include_inactive=include_inactive,
        )

    async def update_contact(
        self,
        contact_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        changes: dict[str, object],
    ) -> Contact:
        if not changes:
            return await self.get_contact(contact_id, tenant_id=tenant_id)
        updated = await self._repo.update_contact(contact_id, tenant_id=tenant_id, changes=changes)
        if updated is None:
            raise NotFoundError(f"Contact {contact_id} not found")
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_CONTACT_UPDATED,
            target=f"contact:{contact_id}",
            details=changes,
        )
        return updated

    async def deactivate_contact(self, contact_id: uuid.UUID, *, tenant_id: uuid.UUID) -> Contact:
        updated = await self._repo.deactivate_contact(contact_id, tenant_id=tenant_id)
        if updated is None:
            raise NotFoundError(f"Contact {contact_id} not found")
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_CONTACT_DEACTIVATED,
            target=f"contact:{contact_id}",
            details={},
        )
        await self._record_timeline(
            tenant_id=tenant_id,
            entity_type=CrmEntityType.CONTACT,
            entity_id=contact_id,
            event_type=CrmTimelineEventType.CONTACT_DEACTIVATED,
            title="Contact removed",
        )
        return updated

    # ------------------------------------------------------------------
    # Activities
    # ------------------------------------------------------------------

    async def create_activity(
        self,
        *,
        tenant_id: uuid.UUID,
        kind: ActivityKind,
        entity_type: CrmEntityType,
        entity_id: uuid.UUID,
        subject: str,
        description: str | None,
        due_at: datetime | None,
        notes: str | None,
        owner_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> Activity:
        if not subject.strip():
            raise ValidationError("Activity subject is required")
        if due_at is not None and due_at.tzinfo is None:
            raise ValidationError("Activity due date must include a timezone")
        await self._require_anchor(entity_type, entity_id, tenant_id=tenant_id)
        activity = Activity(
            tenant_id=tenant_id,
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            subject=subject.strip(),
            description=description,
            due_at=due_at,
            notes=notes,
            owner_id=owner_id,
            team_id=team_id,
        )
        created = await self._repo.create_activity(activity)
        assert created.id is not None
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_ACTIVITY_CREATED,
            target=f"activity:{created.id}",
            details={
                "kind": kind.value,
                "entity_type": entity_type.value,
                "subject": created.subject,
            },
        )
        await emit_activity_created(
            activity_id=created.id,
            tenant_id=tenant_id,
            kind=kind.value,
            entity_type=entity_type.value,
            entity_id=entity_id,
        )
        return created

    async def get_activity(
        self,
        activity_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> Activity:
        activity = await self._repo.get_activity(
            activity_id, tenant_id=tenant_id, scope=scope, user_id=user_id, team_id=team_id
        )
        if activity is None:
            raise NotFoundError(f"Activity {activity_id} not found")
        return activity

    async def list_activities(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        entity_type: CrmEntityType | None,
        entity_id: uuid.UUID | None,
        kind: ActivityKind | None,
        status: str | None,
        assignee_id: uuid.UUID | None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Activity]:
        day_start, day_end, completed_since = _activity_windows(status)
        return list(
            await self._repo.list_activities(
                tenant_id=tenant_id,
                scope=scope,
                user_id=user_id,
                team_id=team_id,
                entity_type=entity_type,
                entity_id=entity_id,
                kind=kind,
                status=status,
                assignee_id=assignee_id,
                day_start=day_start,
                day_end=day_end,
                completed_since=completed_since,
                offset=offset,
                limit=limit,
            )
        )

    async def count_activities(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        entity_type: CrmEntityType | None,
        entity_id: uuid.UUID | None,
        kind: ActivityKind | None,
        status: str | None,
        assignee_id: uuid.UUID | None,
    ) -> int:
        day_start, day_end, completed_since = _activity_windows(status)
        return await self._repo.count_activities(
            tenant_id=tenant_id,
            scope=scope,
            user_id=user_id,
            team_id=team_id,
            entity_type=entity_type,
            entity_id=entity_id,
            kind=kind,
            status=status,
            assignee_id=assignee_id,
            day_start=day_start,
            day_end=day_end,
            completed_since=completed_since,
        )

    async def update_activity(
        self,
        activity_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        changes: dict[str, object],
    ) -> Activity:
        unknown = set(changes) - _ACTIVITY_KIND_MUTABLE
        if unknown:
            raise ValidationError(f"Cannot update activity fields: {sorted(unknown)}")
        if "due_at" in changes and changes["due_at"] is not None:
            due_at = changes["due_at"]
            if not isinstance(due_at, datetime) or due_at.tzinfo is None:
                raise ValidationError("Activity due date must include a timezone")
        if not changes:
            return await self.get_activity(
                activity_id, tenant_id=tenant_id, scope=scope, user_id=user_id, team_id=team_id
            )
        updated = await self._repo.update_activity(
            activity_id,
            tenant_id=tenant_id,
            scope=scope,
            user_id=user_id,
            team_id=team_id,
            changes=changes,
        )
        if updated is None:
            raise NotFoundError(f"Activity {activity_id} not found")
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_ACTIVITY_UPDATED,
            target=f"activity:{activity_id}",
            details=changes,
        )
        return updated

    async def complete_activity(
        self,
        activity_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        completed_by: uuid.UUID,
    ) -> Activity:
        completed = await self._repo.complete_activity(
            activity_id,
            tenant_id=tenant_id,
            scope=scope,
            user_id=user_id,
            team_id=team_id,
            completed_by=completed_by,
        )
        if completed is None:
            raise NotFoundError(f"Activity {activity_id} not found")
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_ACTIVITY_COMPLETED,
            target=f"activity:{activity_id}",
            details={},
        )
        await emit_activity_completed(
            activity_id=activity_id, tenant_id=tenant_id, completed_by=completed_by
        )
        return completed

    async def delete_activity(
        self,
        activity_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> Activity:
        removed = await self._repo.delete_activity(
            activity_id, tenant_id=tenant_id, scope=scope, user_id=user_id, team_id=team_id
        )
        if removed is None:
            raise NotFoundError(f"Activity {activity_id} not found")
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_ACTIVITY_DELETED,
            target=f"activity:{activity_id}",
            details={},
        )
        return removed

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    async def create_note(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_type: CrmEntityType,
        entity_id: uuid.UUID,
        body: str,
    ) -> Note:
        if not body.strip():
            raise ValidationError("Note body is required")
        await self._require_anchor(entity_type, entity_id, tenant_id=tenant_id)
        note = Note(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            body=body.strip(),
            author_id=uuid.UUID(TenantContext.get_user_id())
            if TenantContext.get_user_id()
            else None,
        )
        created = await self._repo.create_note(note)
        assert created.id is not None
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_NOTE_CREATED,
            target=f"note:{created.id}",
            details={"entity_type": entity_type.value, "entity_id": str(entity_id)},
        )
        await emit_note_created(
            note_id=created.id,
            tenant_id=tenant_id,
            entity_type=entity_type.value,
            entity_id=entity_id,
        )
        return created

    async def get_note(self, note_id: uuid.UUID, *, tenant_id: uuid.UUID) -> Note:
        note = await self._repo.get_note(note_id, tenant_id=tenant_id)
        if note is None:
            raise NotFoundError(f"Note {note_id} not found")
        return note

    async def list_notes(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_type: CrmEntityType | None,
        entity_id: uuid.UUID | None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Note]:
        return list(
            await self._repo.list_notes(
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                offset=offset,
                limit=limit,
            )
        )

    async def count_notes(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_type: CrmEntityType | None,
        entity_id: uuid.UUID | None,
    ) -> int:
        return await self._repo.count_notes(
            tenant_id=tenant_id, entity_type=entity_type, entity_id=entity_id
        )

    async def update_note(
        self,
        note_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        changes: dict[str, object],
    ) -> Note:
        if not changes:
            return await self.get_note(note_id, tenant_id=tenant_id)
        body = changes.get("body")
        if body is None or not str(body).strip():
            raise ValidationError("Note body is required")
        updated = await self._repo.update_note(note_id, tenant_id=tenant_id, changes=changes)
        if updated is None:
            raise NotFoundError(f"Note {note_id} not found")
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_NOTE_UPDATED,
            target=f"note:{note_id}",
            details={},
        )
        return updated

    async def delete_note(self, note_id: uuid.UUID, *, tenant_id: uuid.UUID) -> Note:
        removed = await self._repo.delete_note(note_id, tenant_id=tenant_id)
        if removed is None:
            raise NotFoundError(f"Note {note_id} not found")
        await self._audit(
            tenant_id=tenant_id,
            action=CRM_NOTE_DELETED,
            target=f"note:{note_id}",
            details={},
        )
        return removed

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    async def get_timeline(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_type: CrmEntityType,
        entity_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TimelineItem], int]:
        """Merged relationship timeline (activities + notes + business events)."""
        await self._require_anchor(entity_type, entity_id, tenant_id=tenant_id)
        items, total = await self._repo.get_timeline(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            offset=offset,
            limit=limit,
        )
        return list(items), total

    async def get_global_timeline(
        self,
        *,
        tenant_id: uuid.UUID,
        offset: int = 0,
        limit: int = 10,
    ) -> list[TimelineItem]:
        """Recent CRM activity across all entities - dashboard feed."""
        items = await self._repo.get_global_timeline(
            tenant_id=tenant_id,
            offset=offset,
            limit=limit,
        )
        return list(items)

    # ------------------------------------------------------------------
    # Overview + search
    # ------------------------------------------------------------------

    async def get_overview(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
    ) -> CrmOverview:
        """CRM overview dashboard - every number from real DB aggregates."""
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        completed_since = now - timedelta(days=30)

        status_counts = await self._repo.lead_status_counts(
            tenant_id=tenant_id, scope=scope, user_id=user_id, team_id=team_id
        )
        by_status = tuple(
            LeadStatusCount(status=status, count=count) for status, count in status_counts
        )
        lead_total = sum(count for _, count in status_counts)

        source_counts = await self._repo.lead_source_counts(
            tenant_id=tenant_id, scope=scope, user_id=user_id, team_id=team_id
        )
        by_source = tuple(
            LeadSourceCount(source=source, count=count) for source, count in source_counts
        )

        funnel = await self._repo.opportunity_funnel(
            tenant_id=tenant_id, scope=scope, user_id=user_id, team_id=team_id
        )
        terminal = await self._repo.won_lost_counts(
            tenant_id=tenant_id, scope=scope, user_id=user_id, team_id=team_id
        )
        by_stage = tuple(
            _stage_bucket(stage, currency, count, amount)
            for stage, currency, count, amount in funnel
        )
        open_count = sum(
            bucket.count for bucket in by_stage if bucket.stage not in _TERMINAL_STAGES
        )
        open_value = _merge_buckets(
            value
            for bucket in by_stage
            if bucket.stage not in _TERMINAL_STAGES
            for value in bucket.value
        )
        won_count = 0
        lost_count = 0
        won_value: list[MoneyBucket] = []
        for stage, count in terminal:
            if stage is OpportunityStage.WON:
                won_count = count
            else:
                lost_count = count
        won_value = list(
            _merge_buckets(
                value
                for bucket in by_stage
                if bucket.stage is OpportunityStage.WON
                for value in bucket.value
            )
        )
        win_rate = None
        if won_count + lost_count > 0:
            win_rate = Decimal(won_count) / Decimal(won_count + lost_count)

        customers_total, customers_active = await self._repo.customer_counts(tenant_id=tenant_id)
        activity_counts = await self._repo.activity_window_counts(
            tenant_id=tenant_id,
            scope=scope,
            user_id=user_id,
            team_id=team_id,
            today_start=today_start,
            today_end=today_end,
            completed_since=completed_since,
        )
        recent_won = await self._repo.recent_won_opportunities(
            tenant_id=tenant_id, scope=scope, user_id=user_id, team_id=team_id, limit=5
        )
        top = await self._repo.top_opportunities(
            tenant_id=tenant_id, scope=scope, user_id=user_id, team_id=team_id, limit=5
        )

        return CrmOverview(
            leads=LeadsOverview(total=lead_total, by_status=by_status, by_source=by_source),
            opportunities=OpportunitiesOverview(
                open_count=open_count,
                open_value=tuple(open_value),
                by_stage=by_stage,
                won_count=won_count,
                won_value=tuple(won_value),
                lost_count=lost_count,
                win_rate=win_rate,
            ),
            customers=CustomersOverview(total=customers_total, active=customers_active),
            activities=ActivitiesOverview(
                today=activity_counts["today"],
                overdue=activity_counts["overdue"],
                upcoming=activity_counts["upcoming"],
                completed_30d=activity_counts["completed_30d"],
            ),
            recent_won=tuple(recent_won),
            top_opportunities=tuple(top),
        )

    async def search(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: DataScope,
        user_id: uuid.UUID | None,
        team_id: uuid.UUID | None,
        query: str,
        entity_type: CrmEntityType | None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[CrmSearchHit], int]:
        query = query.strip()
        if not query:
            raise ValidationError("Search query is required")
        hits, total = await self._repo.search(
            tenant_id=tenant_id,
            scope=scope,
            user_id=user_id,
            team_id=team_id,
            query=query,
            entity_type=entity_type,
            offset=offset,
            limit=limit,
        )
        return list(hits), total

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _require_customer(self, customer_id: uuid.UUID, *, tenant_id: uuid.UUID) -> Customer:
        customer = await self._repo.get_customer(customer_id, tenant_id=tenant_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} not found")
        return customer

    async def _require_anchor(
        self,
        entity_type: CrmEntityType,
        entity_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
    ) -> None:
        """The anchor entity must exist in the tenant before attaching rows to it."""
        if entity_type is CrmEntityType.LEAD:
            lead = await self._repo.get_lead(
                entity_id, tenant_id=tenant_id, scope=DataScope.ALL, user_id=None, team_id=None
            )
            if lead is None:
                raise NotFoundError(f"Lead {entity_id} not found")
        elif entity_type is CrmEntityType.OPPORTUNITY:
            opp = await self._repo.get_opportunity(
                entity_id, tenant_id=tenant_id, scope=DataScope.ALL, user_id=None, team_id=None
            )
            if opp is None:
                raise NotFoundError(f"Opportunity {entity_id} not found")
        elif entity_type is CrmEntityType.CUSTOMER:
            await self._require_customer(entity_id, tenant_id=tenant_id)
        elif entity_type is CrmEntityType.CONTACT:
            contact = await self._repo.get_contact(entity_id, tenant_id=tenant_id)
            if contact is None:
                raise NotFoundError(f"Contact {entity_id} not found")
        else:  # pragma: no cover - guarded by the schema enum
            raise IllegalStateTransitionError(f"Unknown anchor entity type: {entity_type}")

    async def _record_timeline(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_type: CrmEntityType,
        entity_id: uuid.UUID,
        event_type: CrmTimelineEventType,
        title: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        await self._repo.record_timeline_event(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            title=title,
            actor_id=uuid.UUID(TenantContext.get_user_id())
            if TenantContext.get_user_id()
            else None,
            payload=payload,
        )

    async def _audit(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        target: str,
        details: dict[str, object] | None,
    ) -> None:
        await self._audit_service.log(
            action=action,
            target=target,
            user_id=TenantContext.get_user_id(),
            tenant_id=str(tenant_id),
            details=details,
        )


_TERMINAL_STAGES = frozenset((OpportunityStage.WON, OpportunityStage.LOST))


def _activity_windows(
    status: str | None,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    """UTC day boundaries for the follow-up window filters (None when unused)."""
    if status is None:
        return None, None, None
    if status == "today":
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start, day_start + timedelta(days=1), None
    if status == "completed":
        return None, None, datetime.now(UTC) - timedelta(days=30)
    return None, None, None


def _stage_bucket(
    stage: OpportunityStage, currency: str | None, count: int, amount: Decimal
) -> StageBucket:
    value: tuple[MoneyBucket, ...] = ()
    if currency is not None:
        value = (MoneyBucket(currency=currency, amount=amount),)
    return StageBucket(stage=stage, count=count, value=value)


def _merge_buckets(buckets: Iterable[MoneyBucket]) -> list[MoneyBucket]:
    """Combine per-currency sums into one bucket per currency (order-stable)."""
    merged: dict[str, Decimal] = {}
    order: list[str] = []
    for bucket in buckets:
        if bucket.currency not in merged:
            merged[bucket.currency] = Decimal("0")
            order.append(bucket.currency)
        merged[bucket.currency] += bucket.amount
    return [MoneyBucket(currency=currency, amount=merged[currency]) for currency in order]
