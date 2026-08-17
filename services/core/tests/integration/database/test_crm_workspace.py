"""CRM workspace integration tests (real Postgres, real migrations).

Complements the API suite with what only SQL-level access can prove:

  - RLS on the four new ``erp_crm_*`` workspace tables (non-owner role +
    the ``app.current_tenant_id`` GUC): tenant B cannot read tenant A's
    contacts/activities/notes/timeline events, and a cross-tenant INSERT is
    rejected by ``WITH CHECK``;
  - the three new native enum types created by migration 0016;
  - OWNER/TEAM/ALL scoping of activities (the owner/team-scoped surface) —
    direct fetch/update/complete/delete blocked outside scope, unassigned
    rows visible only to ALL;
  - the merged timeline: the DB-layer UNION is ordered and paginated as ONE
    list (notes + activities + events interleaved), and it is isolated per
    anchor + per tenant;
  - the curated-event wiring: lead lifecycle, stage moves, and an order
    creation anchored to the CUSTOMER entity;
  - the overview aggregates and cross-table search against real rows;
  - migration 0016's downgrade round-trip (declared LAST).

Skipped automatically when Postgres is unreachable (``migrated_schema``).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from core.db.session import async_session_factory, engine
from core.domain.entities import Activity, Contact, Customer, Lead, Note, Opportunity
from core.domain.value_objects import (
    ActivityKind,
    CrmEntityType,
    CrmTimelineEventType,
    DataScope,
    LeadStatus,
    Money,
    OpportunityStage,
)
from core.features.crm.models.customer import ErpCrmCustomerModel
from core.features.crm.repository import CrmRepository
from core.models.tenant import TenantModel

pytestmark = pytest.mark.integration

RLS_ROLE = "core_rls_smoke"

_CORE_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"
_CORE_ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "alembic"

_WORKSPACE_TABLES = (
    "erp_crm_timeline_events",
    "erp_crm_notes",
    "erp_crm_activities",
    "erp_crm_contacts",
    "erp_crm_customers",
    "erp_crm_opportunities",
    "erp_crm_leads",
)

_UTC = UTC


def _now() -> datetime:
    return datetime(2026, 8, 1, tzinfo=_UTC)


@pytest.fixture(scope="module")
def crm_workspace_world(migrated_schema: None) -> dict[str, str]:
    """Seed two tenants with a customer + lead each for the workspace tests."""

    async def _setup() -> dict[str, str]:
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        customer_a = str(uuid.uuid4())
        customer_b = str(uuid.uuid4())

        async with async_session_factory() as session:
            session.add_all(
                [
                    TenantModel(
                        id=uuid.UUID(tenant_a),
                        name="Workspace Tenant A",
                        slug=f"ws-a-{tenant_a[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                    TenantModel(
                        id=uuid.UUID(tenant_b),
                        name="Workspace Tenant B",
                        slug=f"ws-b-{tenant_b[:8]}",
                        plan_tier="free",
                        is_active=True,
                    ),
                ]
            )
            # Flush so the FK from customers -> tenants resolves in insert order
            # (no SQLAlchemy relationship exists to infer the dependency).
            await session.flush()
            session.add_all(
                [
                    ErpCrmCustomerModel(
                        tenant_id=uuid.UUID(tenant_a),
                        id=uuid.UUID(customer_a),
                        customer_code="WS-CUST-A",
                        name="Workspace Customer A",
                    ),
                    ErpCrmCustomerModel(
                        tenant_id=uuid.UUID(tenant_b),
                        id=uuid.UUID(customer_b),
                        customer_code="WS-CUST-B",
                        name="Workspace Customer B",
                    ),
                ]
            )
            await session.commit()
            await engine.dispose()

        return {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "customer_a": customer_a,
            "customer_b": customer_b,
        }

    async def _teardown() -> None:
        async with async_session_factory() as session:
            for tid in (world_data["tenant_a"], world_data["tenant_b"]):
                for table in _WORKSPACE_TABLES:
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                        {"tid": uuid.UUID(tid)},
                    )
                await session.execute(
                    text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(tid)}
                )
            await session.commit()
            await engine.dispose()

    world_data = asyncio.run(_setup())
    try:
        yield world_data
    finally:
        asyncio.run(_teardown())


async def _ensure_workspace_rls_role() -> None:
    """Grant the RLS smoke role SELECT/INSERT on the workspace tables."""
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{RLS_ROLE}') "
                f"THEN CREATE ROLE {RLS_ROLE} NOLOGIN; "
                "END IF; END $$;"
            )
            await conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {RLS_ROLE}")
            for table in _WORKSPACE_TABLES:
                await conn.exec_driver_sql(
                    f"GRANT SELECT, INSERT ON TABLE public.{table} TO {RLS_ROLE}"
                )
    except ProgrammingError as exc:
        if "permission denied to create role" not in str(exc).lower():
            raise
        pytest.skip(
            "SQL-level RLS smoke tests require a role with CREATEROLE to create "
            "the non-owner 'core_rls_smoke' test role. Run the tests against the "
            "compose stack, or grant CREATEROLE to skyrict."
        )


class TestCrmWorkspaceEnums:
    async def test_migration_created_workspace_enum_types(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        async with engine.connect() as conn:
            activity_kind = (
                (
                    await conn.execute(
                        text("SELECT unnest(enum_range(NULL::erp_crm_activity_kind))::text")
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(activity_kind) == ["call", "email", "follow_up", "meeting", "note", "task"]

            entity_type = (
                (
                    await conn.execute(
                        text("SELECT unnest(enum_range(NULL::erp_crm_entity_type))::text")
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(entity_type) == ["contact", "customer", "lead", "opportunity"]

            timeline_type = (
                (
                    await conn.execute(
                        text(
                            "SELECT unnest(enum_range(NULL::erp_crm_timeline_event_type))::text"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(timeline_type) == [
                "contact.created",
                "contact.deactivated",
                "customer.created",
                "lead.created",
                "lead.disqualified",
                "lead.qualified",
                "lead.status_changed",
                "opportunity.lost",
                "opportunity.stage_changed",
                "opportunity.won",
                "order.created",
            ]

        await engine.dispose()


class TestCrmWorkspaceRls:
    async def test_tenant_b_cannot_read_tenant_a_workspace_rows(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        await _ensure_workspace_rls_role()

        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO erp_crm_contacts "
                    "(tenant_id, id, customer_id, first_name, email) "
                    "VALUES (:tid, gen_random_uuid(), :cust, 'Secret', 'secret@x.com')"
                ),
                {"tid": uuid.UUID(crm_workspace_world["tenant_a"]), "cust": uuid.UUID(crm_workspace_world["customer_a"])},
            )
            await conn.execute(
                text(
                    "INSERT INTO erp_crm_timeline_events "
                    "(tenant_id, id, entity_type, entity_id, event_type, title) "
                    "VALUES (:tid, gen_random_uuid(), 'customer', :cust, "
                    "'customer.created', 'Customer created')"
                ),
                {"tid": uuid.UUID(crm_workspace_world["tenant_a"]), "cust": uuid.UUID(crm_workspace_world["customer_a"])},
            )
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")

            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (crm_workspace_world["tenant_a"],),
            )
            a_emails = (
                (await conn.execute(text("SELECT email FROM erp_crm_contacts"))).scalars().all()
            )
            assert "secret@x.com" in a_emails

            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (crm_workspace_world["tenant_b"],),
            )
            b_emails = (
                (await conn.execute(text("SELECT email FROM erp_crm_contacts"))).scalars().all()
            )
            assert "secret@x.com" not in b_emails
            b_titles = (
                (await conn.execute(text("SELECT title FROM erp_crm_timeline_events")))
                .scalars()
                .all()
            )
            assert "Customer created" not in b_titles

            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()

    async def test_cross_tenant_contact_insert_blocked_by_rls(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        await _ensure_workspace_rls_role()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (crm_workspace_world["tenant_a"],),
            )
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_crm_contacts "
                        "(tenant_id, id, customer_id, first_name, email) "
                        "VALUES (:tid, gen_random_uuid(), :cust, 'Sneaky', 's@x.com')"
                    ),
                    {
                        "tid": uuid.UUID(crm_workspace_world["tenant_b"]),
                        "cust": uuid.UUID(crm_workspace_world["customer_b"]),
                    },
                )
            assert "row-level security" in str(excinfo.value).lower()
            await conn.rollback()
            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()


class TestWorkspaceRepository:
    async def test_contact_roundtrip_and_deactivate(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        tenant_a = uuid.UUID(crm_workspace_world["tenant_a"])
        customer_a = uuid.UUID(crm_workspace_world["customer_a"])
        async with async_session_factory() as session:
            repo = CrmRepository(session)
            created = await repo.create_contact(
                Contact(
                    tenant_id=tenant_a,
                    customer_id=customer_a,
                    first_name="Grace",
                    last_name="Hopper",
                    email="grace@navy.test",
                    is_primary=True,
                )
            )
            assert created.id is not None
            assert created.is_active is True

            fetched = await repo.get_contact(created.id, tenant_id=tenant_a)
            assert fetched is not None
            assert fetched.email == "grace@navy.test"
            assert fetched.customer_id == customer_a

            listed = await repo.list_contacts(tenant_id=tenant_a, customer_id=customer_a)
            assert any(contact.id == created.id for contact in listed)

            # A contact in tenant B is invisible.
            assert (
                await repo.get_contact(created.id, tenant_id=uuid.UUID(crm_workspace_world["tenant_b"]))
                is None
            )

            updated = await repo.update_contact(
                created.id, tenant_id=tenant_a, changes={"job_title": "Rear Admiral"}
            )
            assert updated is not None
            assert updated.job_title == "Rear Admiral"

            deactivated = await repo.deactivate_contact(created.id, tenant_id=tenant_a)
            assert deactivated is not None
            assert deactivated.is_active is False
            hidden = await repo.list_contacts(tenant_id=tenant_a, customer_id=customer_a)
            assert all(contact.id != created.id for contact in hidden)
            await session.commit()

    async def test_activity_owner_scope_hides_other_users(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        tenant_a = uuid.UUID(crm_workspace_world["tenant_a"])
        user1 = uuid.uuid4()
        user2 = uuid.uuid4()
        async with async_session_factory() as session:
            repo = CrmRepository(session)
            mine = await repo.create_activity(
                Activity(
                    tenant_id=tenant_a,
                    kind=ActivityKind.TASK,
                    entity_type=CrmEntityType.LEAD,
                    entity_id=uuid.uuid4(),
                    subject="Mine",
                    owner_id=user1,
                )
            )
            other = await repo.create_activity(
                Activity(
                    tenant_id=tenant_a,
                    kind=ActivityKind.TASK,
                    entity_type=CrmEntityType.LEAD,
                    entity_id=uuid.uuid4(),
                    subject="Other",
                    owner_id=user2,
                )
            )

            mine_ids = {
                activity.id
                for activity in await repo.list_activities(
                    tenant_id=tenant_a,
                    scope=DataScope.OWNER,
                    user_id=user1,
                    team_id=None,
                )
            }
            assert mine.id in mine_ids
            assert other.id not in mine_ids

            assert (
                await repo.get_activity(
                    other.id,
                    tenant_id=tenant_a,
                    scope=DataScope.OWNER,
                    user_id=user1,
                    team_id=None,
                )
                is None
            )
            assert (
                await repo.update_activity(
                    other.id,
                    tenant_id=tenant_a,
                    scope=DataScope.OWNER,
                    user_id=user1,
                    team_id=None,
                    changes={"subject": "Hijacked"},
                )
                is None
            )
            assert (
                await repo.complete_activity(
                    other.id,
                    tenant_id=tenant_a,
                    scope=DataScope.OWNER,
                    user_id=user1,
                    team_id=None,
                    completed_by=user1,
                )
                is None
            )
            assert (
                await repo.delete_activity(
                    other.id,
                    tenant_id=tenant_a,
                    scope=DataScope.OWNER,
                    user_id=user1,
                    team_id=None,
                )
                is None
            )

            all_ids = {
                activity.id
                for activity in await repo.list_activities(
                    tenant_id=tenant_a, scope=DataScope.ALL, user_id=None, team_id=None
                )
            }
            assert mine.id in all_ids
            assert other.id in all_ids
            await session.commit()

    async def test_activity_team_scope_and_unassigned(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        tenant_a = uuid.UUID(crm_workspace_world["tenant_a"])
        user1 = uuid.uuid4()
        user2 = uuid.uuid4()
        team1 = uuid.uuid4()
        team2 = uuid.uuid4()
        async with async_session_factory() as session:
            repo = CrmRepository(session)

            async def _make(subject: str, **kwargs: object) -> Activity:
                return await repo.create_activity(
                    Activity(
                        tenant_id=tenant_a,
                        kind=ActivityKind.FOLLOW_UP,
                        entity_type=CrmEntityType.LEAD,
                        entity_id=uuid.uuid4(),
                        subject=subject,
                        **kwargs,
                    )
                )

            owned = await _make("Owned", owner_id=user1)
            teamed = await _make("Teamed", team_id=team1)
            foreign = await _make("Foreign", owner_id=user2, team_id=team2)
            unassigned = await _make("Unassigned")

            team_ids = {
                activity.id
                for activity in await repo.list_activities(
                    tenant_id=tenant_a,
                    scope=DataScope.TEAM,
                    user_id=user1,
                    team_id=team1,
                )
            }
            assert owned.id in team_ids
            assert teamed.id in team_ids
            assert foreign.id not in team_ids
            assert unassigned.id not in team_ids

            count = await repo.count_activities(
                tenant_id=tenant_a,
                scope=DataScope.TEAM,
                user_id=user1,
                team_id=team1,
            )
            assert count == len(team_ids)
            await session.commit()

    async def test_activity_complete_and_status_filters(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        tenant_a = uuid.UUID(crm_workspace_world["tenant_a"])
        user1 = uuid.uuid4()
        async with async_session_factory() as session:
            repo = CrmRepository(session)
            pending = await repo.create_activity(
                Activity(
                    tenant_id=tenant_a,
                    kind=ActivityKind.CALL,
                    entity_type=CrmEntityType.LEAD,
                    entity_id=uuid.uuid4(),
                    subject="Call later",
                    owner_id=user1,
                )
            )
            completed = await repo.create_activity(
                Activity(
                    tenant_id=tenant_a,
                    kind=ActivityKind.MEETING,
                    entity_type=CrmEntityType.LEAD,
                    entity_id=uuid.uuid4(),
                    subject="Met already",
                    owner_id=user1,
                )
            )
            done = await repo.complete_activity(
                completed.id,
                tenant_id=tenant_a,
                scope=DataScope.OWNER,
                user_id=user1,
                team_id=None,
                completed_by=user1,
            )
            assert done is not None
            assert done.completed_at is not None
            assert done.completed_by == user1

            open_rows = await repo.list_activities(
                tenant_id=tenant_a,
                scope=DataScope.OWNER,
                user_id=user1,
                team_id=None,
                status="open",
            )
            assert pending.id in {activity.id for activity in open_rows}
            assert completed.id not in {activity.id for activity in open_rows}

            completed_rows = await repo.list_activities(
                tenant_id=tenant_a,
                scope=DataScope.OWNER,
                user_id=user1,
                team_id=None,
                status="completed",
            )
            assert completed.id in {activity.id for activity in completed_rows}
            assert pending.id not in {activity.id for activity in completed_rows}
            await session.commit()

    async def test_note_roundtrip(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        tenant_a = uuid.UUID(crm_workspace_world["tenant_a"])
        anchor = uuid.uuid4()
        async with async_session_factory() as session:
            repo = CrmRepository(session)
            created = await repo.create_note(
                Note(
                    tenant_id=tenant_a,
                    entity_type=CrmEntityType.CUSTOMER,
                    entity_id=anchor,
                    body="Key account, renew in Q3.",
                    author_id=uuid.uuid4(),
                )
            )
            assert created.id is not None
            fetched = await repo.get_note(created.id, tenant_id=tenant_a)
            assert fetched is not None
            assert fetched.body == "Key account, renew in Q3."

            # Other-tenant and other-anchor isolation.
            assert (
                await repo.get_note(created.id, tenant_id=uuid.UUID(crm_workspace_world["tenant_b"]))
                is None
            )
            other = await repo.list_notes(
                tenant_id=tenant_a, entity_type=CrmEntityType.CUSTOMER, entity_id=uuid.uuid4()
            )
            assert all(note.id != created.id for note in other)

            updated = await repo.update_note(created.id, tenant_id=tenant_a, changes={"body": "Renew Q4"})
            assert updated is not None
            assert updated.body == "Renew Q4"
            await repo.delete_note(created.id, tenant_id=tenant_a)
            assert await repo.get_note(created.id, tenant_id=tenant_a) is None
            await session.commit()

    async def test_timeline_is_curated_business_log_not_audit(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        tenant_a = uuid.UUID(crm_workspace_world["tenant_a"])
        customer_a = uuid.UUID(crm_workspace_world["customer_a"])
        async with async_session_factory() as session:
            repo = CrmRepository(session)
            event = await repo.record_timeline_event(
                tenant_id=tenant_a,
                entity_type=CrmEntityType.CUSTOMER,
                entity_id=customer_a,
                event_type=CrmTimelineEventType.CUSTOMER_CREATED,
                title="Customer created",
                actor_id=uuid.uuid4(),
                payload={"customer_code": "WS-CUST-A"},
            )
            assert event.id is not None
            fetched = await repo.get_timeline(
                tenant_id=tenant_a, entity_type=CrmEntityType.CUSTOMER, entity_id=customer_a
            )
            items, total = fetched
            assert total == 1
            assert items[0].title == "Customer created"
            assert items[0].source == "event"
            assert items[0].entity_type is CrmEntityType.CUSTOMER
            await session.commit()

    async def test_timeline_union_is_ordered_paginated_and_isolated(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        tenant_a = uuid.UUID(crm_workspace_world["tenant_a"])
        anchor = uuid.uuid4()
        now = _now()
        async with async_session_factory() as session:
            repo = CrmRepository(session)
            # Controlled timestamps for the event rows (repo API uses now()); the
            # note and activity are created at "now" so the ordering is exact:
            # oldest event (t-10m), middle event (t-5m), then the two just-created rows.
            await session.execute(
                text(
                    "INSERT INTO erp_crm_timeline_events "
                    "(tenant_id, id, entity_type, entity_id, event_type, title, created_at) "
                    "VALUES (:tid, gen_random_uuid(), 'lead', :anchor, 'lead.created', "
                    "'Lead created', :oldest)"
                ),
                {"tid": tenant_a, "anchor": anchor, "oldest": now - timedelta(minutes=10)},
            )
            await session.execute(
                text(
                    "INSERT INTO erp_crm_timeline_events "
                    "(tenant_id, id, entity_type, entity_id, event_type, title, created_at) "
                    "VALUES (:tid, gen_random_uuid(), 'lead', :anchor, 'lead.qualified', "
                    "'Lead qualified', :middle)"
                ),
                {"tid": tenant_a, "anchor": anchor, "middle": now - timedelta(minutes=5)},
            )
            note = await repo.create_note(
                Note(
                    tenant_id=tenant_a,
                    entity_type=CrmEntityType.LEAD,
                    entity_id=anchor,
                    body="Merged note",
                    author_id=uuid.uuid4(),
                )
            )
            activity = await repo.create_activity(
                Activity(
                    tenant_id=tenant_a,
                    kind=ActivityKind.TASK,
                    entity_type=CrmEntityType.LEAD,
                    entity_id=anchor,
                    subject="Merged task",
                )
            )

            items, total = await repo.get_timeline(
                tenant_id=tenant_a, entity_type=CrmEntityType.LEAD, entity_id=anchor
            )
            assert total == 4
            # One merged list, newest first, across all three sources. The two
            # just-created rows (a task + a note) share one created_at (same
            # transaction) so their relative order falls to id desc; a task's
            # text lives in `title`, a note's in `body` (title stays NULL).
            recent = [(item.source, item.title, item.body) for item in items[:2]]
            assert ("activity", "Merged task", None) in recent
            assert ("note", None, "Merged note") in recent
            assert items[2].title == "Lead qualified"
            assert items[3].title == "Lead created"
            assert {item.source for item in items} == {"event", "note", "activity"}
            assert {item.id for item in items} >= {note.id, activity.id}

            # Pagination applies AFTER the merge (SQL-level), not per source.
            page, page_total = await repo.get_timeline(
                tenant_id=tenant_a,
                entity_type=CrmEntityType.LEAD,
                entity_id=anchor,
                offset=2,
                limit=1,
            )
            assert page_total == 4
            assert len(page) == 1
            assert page[0].title == "Lead qualified"

            # Anchor isolation: another lead sees none of these rows.
            other_anchor = uuid.uuid4()
            empty, empty_total = await repo.get_timeline(
                tenant_id=tenant_a, entity_type=CrmEntityType.LEAD, entity_id=other_anchor
            )
            assert empty_total == 0
            assert empty == []
            await session.commit()

    async def test_search_across_tables(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        tenant_a = uuid.UUID(crm_workspace_world["tenant_a"])
        customer_a = uuid.UUID(crm_workspace_world["customer_a"])
        marker = f"zebra-{uuid.uuid4().hex[:6]}"
        async with async_session_factory() as session:
            repo = CrmRepository(session)
            lead = await repo.create_lead(
                Lead(
                    tenant_id=tenant_a,
                    first_name="Zoe",
                    email=f"{marker}@search.test",
                    source="web",
                )
            )
            customer = await repo.create_customer(
                Customer(tenant_id=tenant_a, customer_code="Z-1", name=f"{marker} Corp")
            )
            contact = await repo.create_contact(
                Contact(
                    tenant_id=tenant_a,
                    customer_id=customer_a,
                    first_name="Zed",
                    email=f"{marker}-contact@search.test",
                )
            )

            hits, total = await repo.search(
                tenant_id=tenant_a,
                scope=DataScope.ALL,
                user_id=None,
                team_id=None,
                query=marker,
            )
            assert total >= 3
            kinds = {(hit.entity_type, hit.entity_id) for hit in hits}
            assert (CrmEntityType.LEAD, lead.id) in kinds
            assert (CrmEntityType.CUSTOMER, customer.id) in kinds
            assert (CrmEntityType.CONTACT, contact.id) in kinds

            # Type filter narrows the union.
            customers, customer_total = await repo.search(
                tenant_id=tenant_a,
                scope=DataScope.ALL,
                user_id=None,
                team_id=None,
                query=marker,
                entity_type=CrmEntityType.CUSTOMER,
            )
            assert customer_total == 1
            assert customers[0].entity_id == customer.id
            await session.commit()

    async def test_overview_aggregates(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        tenant_a = uuid.UUID(crm_workspace_world["tenant_a"])
        async with async_session_factory() as session:
            repo = CrmRepository(session)
            await repo.create_lead(
                Lead(tenant_id=tenant_a, first_name="Agg", email=f"agg-{uuid.uuid4().hex[:6]}@x.test")
            )
            won = await repo.create_opportunity(
                Opportunity(
                    tenant_id=tenant_a,
                    name="Won Deal",
                    amount=Money("10000.00", "USD"),
                    probability=90,
                )
            )
            assert won.id is not None
            await repo.update_opportunity_stage(
                won.id,
                tenant_id=tenant_a,
                stage=OpportunityStage.WON,
                won_at=_now(),
                scope=DataScope.ALL,
                user_id=None,
                team_id=None,
            )
            open_opp = await repo.create_opportunity(
                Opportunity(
                    tenant_id=tenant_a,
                    name="Open Deal",
                    amount=Money("2500.00", "EUR"),
                    probability=50,
                )
            )
            assert open_opp.id is not None

            by_status = await repo.lead_status_counts(
                tenant_id=tenant_a, scope=DataScope.ALL, user_id=None, team_id=None
            )
            # Other tests in this module seed leads for the same tenant, so the
            # count is cumulative — assert the shape, not an exact total.
            status_map = dict(by_status)
            assert status_map[LeadStatus.NEW] >= 1

            funnel = await repo.opportunity_funnel(
                tenant_id=tenant_a, scope=DataScope.ALL, user_id=None, team_id=None
            )
            funnel_map = {(stage, currency): (count, amount) for stage, currency, count, amount in funnel}
            assert (OpportunityStage.WON, "USD") in funnel_map
            assert funnel_map[(OpportunityStage.WON, "USD")] == (1, Decimal("10000.0000"))
            assert funnel_map[(OpportunityStage.PROSPECTING, "EUR")] == (1, Decimal("2500.0000"))

            won_lost = await repo.won_lost_counts(
                tenant_id=tenant_a, scope=DataScope.ALL, user_id=None, team_id=None
            )
            assert dict(won_lost)[OpportunityStage.WON] == 1

            customers_total, customers_active = await repo.customer_counts(tenant_id=tenant_a)
            assert customers_total >= 1
            assert customers_active == customers_total

            recent = await repo.recent_won_opportunities(
                tenant_id=tenant_a, scope=DataScope.ALL, user_id=None, team_id=None, limit=5
            )
            assert any(opp.id == won.id for opp in recent)
            # top_opportunities is explicitly open (non-terminal) only.
            top = await repo.top_opportunities(
                tenant_id=tenant_a, scope=DataScope.ALL, user_id=None, team_id=None, limit=5
            )
            assert all(opp.id != won.id for opp in top)
            assert any(opp.id == open_opp.id for opp in top)
            await session.commit()


class TestDowngradeRoundTrip0016:
    """Migration 0016 downgrade round-trip — MUST stay the last class here.

    Drops the four workspace tables + three enum types, then re-applies to
    head so every later test module sees the head schema.
    """

    def _run_alembic(self, *args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(_CORE_ALEMBIC_INI), *args],
            cwd=_CORE_ALEMBIC_INI.parent,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout

    async def test_downgrade_to_0015_then_upgrade_restores_head(
        self, migrated_schema: None, crm_workspace_world: dict[str, str]
    ) -> None:
        scripts = ScriptDirectory(str(_CORE_ALEMBIC_DIR))
        core_head = scripts.get_current_head()
        workspace_parent = scripts.get_revision("0016").down_revision
        assert isinstance(workspace_parent, str)

        self._run_alembic("downgrade", workspace_parent)

        async with engine.connect() as conn:
            version = (
                await conn.execute(text("SELECT version_num FROM alembic_version_core"))
            ).scalar_one()
            assert version == workspace_parent
            tables = (
                (
                    await conn.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    )
                )
                .scalars()
                .all()
            )
            for table in (
                "erp_crm_contacts",
                "erp_crm_activities",
                "erp_crm_notes",
                "erp_crm_timeline_events",
            ):
                assert table not in tables
        await engine.dispose()

        self._run_alembic("upgrade", "head")

        async with engine.connect() as conn:
            version = (
                await conn.execute(text("SELECT version_num FROM alembic_version_core"))
            ).scalar_one()
            assert version == core_head
            tables = (
                (
                    await conn.execute(
                        text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    )
                )
                .scalars()
                .all()
            )
            for table in (
                "erp_crm_contacts",
                "erp_crm_activities",
                "erp_crm_notes",
                "erp_crm_timeline_events",
            ):
                assert table in tables
        await engine.dispose()
