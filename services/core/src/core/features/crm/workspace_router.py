"""CRM workspace routes — contacts, activities, notes, timeline, overview, search.

Thin wrappers over :class:`CrmWorkspaceService`. Reads use ``erp.crm.read``,
mutations ``erp.crm.write``. Activities are owner/team/all-scoped (the request
-resolved :class:`DataScope` is passed straight through — the service can only
narrow it); contacts, notes, and timeline rows are tenant-scoped like customers.

The timeline endpoint is the ONE place the merged relationship timeline is
read — it is assembled by the database (UNION ALL) before ordering/pagination,
never by three separately paged lists merged in the app. The audit trail is a
separate concept and is never surfaced here.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi import APIRouter, Depends, Query

from core.api.deps import (
    get_crm_workspace_service,
    get_current_scope,
    require_permission,
)
from core.core.permissions import ERP_CRM_READ, ERP_CRM_WRITE
from core.domain.entities import Activity, Contact, CrmSearchHit, Note, TimelineItem
from core.domain.value_objects import ActivityKind, CrmEntityType, DataScope
from core.features.crm.router import _opportunity_out
from core.features.crm.workspace_schemas import (
    ActivitiesOverviewResponse,
    ActivityCreateRequest,
    ActivityResponse,
    ActivityUpdateRequest,
    ContactCreateRequest,
    ContactResponse,
    ContactUpdateRequest,
    CrmOverviewResponse,
    CustomersOverviewResponse,
    LeadSourceCountResponse,
    LeadsOverviewResponse,
    LeadStatusCountResponse,
    MoneyBucket,
    NoteCreateRequest,
    NoteResponse,
    NoteUpdateRequest,
    OpportunitiesOverviewResponse,
    SearchHitResponse,
    StageBucketResponse,
    TimelineItemResponse,
)
from core.features.crm.workspace_service import CrmWorkspaceService
from core.features.crm.workspace_service import MoneyBucket as ServiceMoneyBucket
from skyrict_common.exceptions import ValidationError
from skyrict_common.schemas import ListResponse, PaginationMeta, ResponseEnvelope

router = APIRouter(prefix="/crm", tags=["crm-workspace"])

_require_crm_read = require_permission(ERP_CRM_READ)
_require_crm_write = require_permission(ERP_CRM_WRITE)


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    return uuid.UUID(current_user["tenant_id"])


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    # get_current_user already normalizes the JWT ``sub`` to a real UUID.
    return cast("uuid.UUID", current_user["user_id"])


def _contact_out(contact: Contact) -> ContactResponse:
    return ContactResponse.model_validate(contact)


def _activity_out(activity: Activity) -> ActivityResponse:
    return ActivityResponse.model_validate(activity)


def _note_out(note: Note) -> NoteResponse:
    return NoteResponse.model_validate(note)


def _timeline_item_out(item: TimelineItem) -> TimelineItemResponse:
    return TimelineItemResponse(
        source=item.source,
        id=item.id,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        kind=item.kind,
        title=item.title,
        body=item.body,
        actor_id=item.actor_id,
        occurred_at=item.occurred_at,
    )


def _search_hit_out(hit: CrmSearchHit) -> SearchHitResponse:
    return SearchHitResponse(
        entity_type=hit.entity_type,
        entity_id=hit.entity_id,
        title=hit.title,
        subtitle=hit.subtitle,
    )


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


@router.get("/contacts", response_model=ListResponse[ContactResponse])
async def list_contacts(
    customer_id: uuid.UUID | None = None,
    include_inactive: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict[str, Any] = Depends(_require_crm_read),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ListResponse[ContactResponse]:
    contacts = await svc.list_contacts(
        tenant_id=_tenant_id(current_user),
        customer_id=customer_id,
        include_inactive=include_inactive,
        offset=offset,
        limit=limit,
    )
    total = await svc.count_contacts(
        tenant_id=_tenant_id(current_user),
        customer_id=customer_id,
        include_inactive=include_inactive,
    )
    return ListResponse(
        data=[_contact_out(contact) for contact in contacts],
        meta=PaginationMeta.create(total=total, page=(offset // limit) + 1, page_size=limit),
    )


@router.post(
    "/customers/{customer_id}/contacts",
    response_model=ResponseEnvelope[ContactResponse],
    status_code=201,
)
async def create_contact(
    customer_id: uuid.UUID,
    body: ContactCreateRequest,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[ContactResponse]:
    contact = await svc.create_contact(
        tenant_id=_tenant_id(current_user),
        customer_id=customer_id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        phone=body.phone,
        job_title=body.job_title,
        is_primary=body.is_primary,
    )
    return ResponseEnvelope(data=_contact_out(contact), message="Contact created")


@router.get("/contacts/{contact_id}", response_model=ResponseEnvelope[ContactResponse])
async def get_contact(
    contact_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_crm_read),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[ContactResponse]:
    contact = await svc.get_contact(contact_id, tenant_id=_tenant_id(current_user))
    return ResponseEnvelope(data=_contact_out(contact))


@router.patch("/contacts/{contact_id}", response_model=ResponseEnvelope[ContactResponse])
async def update_contact(
    contact_id: uuid.UUID,
    body: ContactUpdateRequest,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[ContactResponse]:
    changes = body.model_dump(exclude_unset=True)
    contact = await svc.update_contact(
        contact_id, tenant_id=_tenant_id(current_user), changes=changes
    )
    return ResponseEnvelope(data=_contact_out(contact), message="Contact updated")


@router.delete("/contacts/{contact_id}", response_model=ResponseEnvelope[ContactResponse])
async def deactivate_contact(
    contact_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[ContactResponse]:
    contact = await svc.deactivate_contact(contact_id, tenant_id=_tenant_id(current_user))
    return ResponseEnvelope(data=_contact_out(contact), message="Contact deactivated")


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


@router.get("/activities", response_model=ListResponse[ActivityResponse])
async def list_activities(
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    kind: str | None = None,
    status: str | None = None,
    assignee_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict[str, Any] = Depends(_require_crm_read),
    scope_team: tuple[DataScope, uuid.UUID | None] = Depends(get_current_scope),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ListResponse[ActivityResponse]:
    scope, team_id = scope_team
    activities = await svc.list_activities(
        tenant_id=_tenant_id(current_user),
        scope=scope,
        user_id=_user_id(current_user),
        team_id=team_id,
        entity_type=_parse_entity_type(entity_type),
        entity_id=entity_id,
        kind=_parse_activity_kind(kind),
        status=status,
        assignee_id=assignee_id,
        offset=offset,
        limit=limit,
    )
    total = await svc.count_activities(
        tenant_id=_tenant_id(current_user),
        scope=scope,
        user_id=_user_id(current_user),
        team_id=team_id,
        entity_type=_parse_entity_type(entity_type),
        entity_id=entity_id,
        kind=_parse_activity_kind(kind),
        status=status,
        assignee_id=assignee_id,
    )
    return ListResponse(
        data=[_activity_out(activity) for activity in activities],
        meta=PaginationMeta.create(total=total, page=(offset // limit) + 1, page_size=limit),
    )


@router.post("/activities", response_model=ResponseEnvelope[ActivityResponse], status_code=201)
async def create_activity(
    body: ActivityCreateRequest,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[ActivityResponse]:
    activity = await svc.create_activity(
        tenant_id=_tenant_id(current_user),
        kind=body.kind,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        subject=body.subject,
        description=body.description,
        due_at=body.due_at,
        notes=body.notes,
        owner_id=body.owner_id,
        team_id=body.team_id,
    )
    return ResponseEnvelope(data=_activity_out(activity), message="Activity created")


@router.get("/activities/{activity_id}", response_model=ResponseEnvelope[ActivityResponse])
async def get_activity(
    activity_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_crm_read),
    scope_team: tuple[DataScope, uuid.UUID | None] = Depends(get_current_scope),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[ActivityResponse]:
    scope, team_id = scope_team
    activity = await svc.get_activity(
        activity_id,
        tenant_id=_tenant_id(current_user),
        scope=scope,
        user_id=_user_id(current_user),
        team_id=team_id,
    )
    return ResponseEnvelope(data=_activity_out(activity))


@router.patch("/activities/{activity_id}", response_model=ResponseEnvelope[ActivityResponse])
async def update_activity(
    activity_id: uuid.UUID,
    body: ActivityUpdateRequest,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    scope_team: tuple[DataScope, uuid.UUID | None] = Depends(get_current_scope),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[ActivityResponse]:
    scope, team_id = scope_team
    changes = body.model_dump(exclude_unset=True)
    activity = await svc.update_activity(
        activity_id,
        tenant_id=_tenant_id(current_user),
        scope=scope,
        user_id=_user_id(current_user),
        team_id=team_id,
        changes=changes,
    )
    return ResponseEnvelope(data=_activity_out(activity), message="Activity updated")


@router.post(
    "/activities/{activity_id}/complete",
    response_model=ResponseEnvelope[ActivityResponse],
)
async def complete_activity(
    activity_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    scope_team: tuple[DataScope, uuid.UUID | None] = Depends(get_current_scope),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[ActivityResponse]:
    scope, team_id = scope_team
    activity = await svc.complete_activity(
        activity_id,
        tenant_id=_tenant_id(current_user),
        scope=scope,
        user_id=_user_id(current_user),
        team_id=team_id,
        completed_by=_user_id(current_user),
    )
    return ResponseEnvelope(data=_activity_out(activity), message="Activity completed")


@router.delete("/activities/{activity_id}", response_model=ResponseEnvelope[ActivityResponse])
async def delete_activity(
    activity_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    scope_team: tuple[DataScope, uuid.UUID | None] = Depends(get_current_scope),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[ActivityResponse]:
    scope, team_id = scope_team
    activity = await svc.delete_activity(
        activity_id,
        tenant_id=_tenant_id(current_user),
        scope=scope,
        user_id=_user_id(current_user),
        team_id=team_id,
    )
    return ResponseEnvelope(data=_activity_out(activity), message="Activity deleted")


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


@router.get("/notes", response_model=ListResponse[NoteResponse])
async def list_notes(
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict[str, Any] = Depends(_require_crm_read),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ListResponse[NoteResponse]:
    notes = await svc.list_notes(
        tenant_id=_tenant_id(current_user),
        entity_type=_parse_entity_type(entity_type),
        entity_id=entity_id,
        offset=offset,
        limit=limit,
    )
    total = await svc.count_notes(
        tenant_id=_tenant_id(current_user),
        entity_type=_parse_entity_type(entity_type),
        entity_id=entity_id,
    )
    return ListResponse(
        data=[_note_out(note) for note in notes],
        meta=PaginationMeta.create(total=total, page=(offset // limit) + 1, page_size=limit),
    )


@router.post("/notes", response_model=ResponseEnvelope[NoteResponse], status_code=201)
async def create_note(
    body: NoteCreateRequest,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[NoteResponse]:
    note = await svc.create_note(
        tenant_id=_tenant_id(current_user),
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        body=body.body,
    )
    return ResponseEnvelope(data=_note_out(note), message="Note created")


@router.get("/notes/{note_id}", response_model=ResponseEnvelope[NoteResponse])
async def get_note(
    note_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_crm_read),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[NoteResponse]:
    note = await svc.get_note(note_id, tenant_id=_tenant_id(current_user))
    return ResponseEnvelope(data=_note_out(note))


@router.patch("/notes/{note_id}", response_model=ResponseEnvelope[NoteResponse])
async def update_note(
    note_id: uuid.UUID,
    body: NoteUpdateRequest,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[NoteResponse]:
    changes = body.model_dump(exclude_unset=True)
    note = await svc.update_note(note_id, tenant_id=_tenant_id(current_user), changes=changes)
    return ResponseEnvelope(data=_note_out(note), message="Note updated")


@router.delete("/notes/{note_id}", response_model=ResponseEnvelope[NoteResponse])
async def delete_note(
    note_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_crm_write),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[NoteResponse]:
    note = await svc.delete_note(note_id, tenant_id=_tenant_id(current_user))
    return ResponseEnvelope(data=_note_out(note), message="Note deleted")


# ---------------------------------------------------------------------------
# Timeline (DB-layer UNION of activities + notes + business events)
# ---------------------------------------------------------------------------


@router.get("/timeline", response_model=ListResponse[TimelineItemResponse])
async def get_timeline(
    entity_type: str = Query(...),
    entity_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict[str, Any] = Depends(_require_crm_read),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ListResponse[TimelineItemResponse]:
    items, total = await svc.get_timeline(
        tenant_id=_tenant_id(current_user),
        entity_type=_parse_entity_type(entity_type),
        entity_id=entity_id,
        offset=offset,
        limit=limit,
    )
    return ListResponse(
        data=[_timeline_item_out(item) for item in items],
        meta=PaginationMeta.create(total=total, page=(offset // limit) + 1, page_size=limit),
    )


# ---------------------------------------------------------------------------
# Overview + search
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=ResponseEnvelope[CrmOverviewResponse])
async def get_overview(
    current_user: dict[str, Any] = Depends(_require_crm_read),
    scope_team: tuple[DataScope, uuid.UUID | None] = Depends(get_current_scope),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ResponseEnvelope[CrmOverviewResponse]:
    scope, team_id = scope_team
    overview = await svc.get_overview(
        tenant_id=_tenant_id(current_user),
        scope=scope,
        user_id=_user_id(current_user),
        team_id=team_id,
    )
    return ResponseEnvelope(
        data=CrmOverviewResponse(
            leads=LeadsOverviewResponse(
                total=overview.leads.total,
                by_status=[
                    LeadStatusCountResponse(status=item.status, count=item.count)
                    for item in overview.leads.by_status
                ],
                by_source=[
                    LeadSourceCountResponse(source=item.source, count=item.count)
                    for item in overview.leads.by_source
                ],
            ),
            opportunities=OpportunitiesOverviewResponse(
                open_count=overview.opportunities.open_count,
                open_value=[_bucket_out(item) for item in overview.opportunities.open_value],
                by_stage=[
                    StageBucketResponse(
                        stage=bucket.stage,
                        count=bucket.count,
                        value=[_bucket_out(item) for item in bucket.value],
                    )
                    for bucket in overview.opportunities.by_stage
                ],
                won_count=overview.opportunities.won_count,
                won_value=[_bucket_out(item) for item in overview.opportunities.won_value],
                lost_count=overview.opportunities.lost_count,
                win_rate=overview.opportunities.win_rate,
            ),
            customers=CustomersOverviewResponse(
                total=overview.customers.total,
                active=overview.customers.active,
            ),
            activities=ActivitiesOverviewResponse(
                today=overview.activities.today,
                overdue=overview.activities.overdue,
                upcoming=overview.activities.upcoming,
                completed_30d=overview.activities.completed_30d,
            ),
            recent_won=[_opportunity_out(opportunity) for opportunity in overview.recent_won],
            top_opportunities=[
                _opportunity_out(opportunity) for opportunity in overview.top_opportunities
            ],
        )
    )


@router.get("/search", response_model=ListResponse[SearchHitResponse])
async def search(
    q: str = Query(..., min_length=1, max_length=200),
    entity_type: str | None = Query(default=None, alias="type"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict[str, Any] = Depends(_require_crm_read),
    scope_team: tuple[DataScope, uuid.UUID | None] = Depends(get_current_scope),
    svc: CrmWorkspaceService = Depends(get_crm_workspace_service),
) -> ListResponse[SearchHitResponse]:
    scope, team_id = scope_team
    hits, total = await svc.search(
        tenant_id=_tenant_id(current_user),
        scope=scope,
        user_id=_user_id(current_user),
        team_id=team_id,
        query=q,
        entity_type=_parse_entity_type(entity_type),
        offset=offset,
        limit=limit,
    )
    return ListResponse(
        data=[_search_hit_out(hit) for hit in hits],
        meta=PaginationMeta.create(total=total, page=(offset // limit) + 1, page_size=limit),
    )


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_entity_type(value: str | None) -> CrmEntityType | None:
    if value is None:
        return None
    try:
        return CrmEntityType(value)
    except ValueError as exc:
        raise ValidationError(f"Unknown entity type: {value}") from exc


def _parse_activity_kind(value: str | None) -> ActivityKind | None:
    if value is None:
        return None
    try:
        return ActivityKind(value)
    except ValueError as exc:
        raise ValidationError(f"Unknown activity kind: {value}") from exc


def _bucket_out(bucket: ServiceMoneyBucket) -> MoneyBucket:
    return MoneyBucket(currency=bucket.currency, amount=bucket.amount)
