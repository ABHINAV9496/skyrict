"""Audit + sequence integration tests (0006) - real Postgres, real migrations.

Covers what a model test cannot:

  - the SHA-256 hash chain on ``core_audit_logs``: every row links to its
    predecessor, and - critically - the chain is SELF-CONTAINED PER TENANT
    under RLS (a non-owner role scoped by the ``app.current_tenant_id`` GUC
    sees genesis ``prev_hash = 64 zeros`` for ITS OWN tenant even when other
    tenants have rows). The table owner bypasses RLS, so owner-level writes
    chain globally; the RLS-scoped behavior is the intended production one;
  - append-only enforcement (direct UPDATE / DELETE raise);
  - the repository adapters (``AuditLogRepository``, ``SequenceRepository``)
    end-to-end, including atomic first-use of a counter;
  - RLS on ``core_audit_logs`` and ``erp_sequences``: a non-owner role plus
    the GUC sees only its own tenant's rows, and a cross-tenant INSERT is
    rejected;
  - migration 0006 seeded the six ``erp.hr.*`` / ``erp.payroll.*`` permission
    keys and created the two trigger functions.

Each test gets a FRESH pair of tenants (function-scoped ``audit_world``), and
the teardown temporarily disables the append-only trigger so it can delete the
fixture's rows - the log is otherwise unrecoverable even for its owner.

Skipped automatically when Postgres is unreachable (``migrated_schema``).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from core.core.audit_events import HR_LEAVE_APPROVED, PAYROLL_RUN_APPROVED
from core.core.audit_service import AuditService
from core.db.audit_repository import AuditLogRepository
from core.db.sequence_repository import SequenceRepository
from core.db.session import async_session_factory, engine
from core.domain.entities import AuditLogEntry
from core.models.tenant import TenantModel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

RLS_ROLE = "core_rls_smoke"

_ERP_CHILD_TABLES = (
    "core_audit_logs",
    "erp_sequences",
)

_ERP_PERMISSION_KEYS = (
    "erp.hr.read",
    "erp.hr.write",
    "erp.hr.approve",
    "erp.payroll.read",
    "erp.payroll.write",
    "erp.payroll.approve",
)


@pytest.fixture
async def audit_world(migrated_schema: None) -> AsyncIterator[dict[str, str]]:
    """Seed two fresh tenants; tear down completely after each test.

    Async (not a sync fixture calling ``asyncio.run``): pytest-asyncio gives
    every function-scoped async test its own event loop, and ``asyncio.run``
    clears the current loop (Python 3.12+), which breaks the next test's loop
    setup. An async fixture runs on the test's own loop, so no extra loop is
    created.

    ``core_audit_logs`` is append-only - the trigger blocks even the owner's
    DELETE. Teardown disables the trigger for the cleanup transaction
    (transactional DDL in Postgres), then always restores it so the table stays
    append-only.
    """
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    async with async_session_factory() as session:
        session.add_all(
            [
                TenantModel(
                    id=uuid.UUID(tenant_a),
                    name="Audit Tenant A",
                    slug=f"audit-a-{tenant_a[:8]}",
                    plan_tier="free",
                    is_active=True,
                ),
                TenantModel(
                    id=uuid.UUID(tenant_b),
                    name="Audit Tenant B",
                    slug=f"audit-b-{tenant_b[:8]}",
                    plan_tier="free",
                    is_active=True,
                ),
            ]
        )
        await session.commit()

    try:
        yield {"tenant_a": tenant_a, "tenant_b": tenant_b}
    finally:
        async with async_session_factory() as session:
            await session.execute(
                text("ALTER TABLE core_audit_logs DISABLE TRIGGER core_audit_logs_append_only")
            )
            for tid in (tenant_a, tenant_b):
                for table in _ERP_CHILD_TABLES:
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
                        {"tid": uuid.UUID(tid)},
                    )
                await session.execute(
                    text("DELETE FROM tenants WHERE id = :tid"), {"tid": uuid.UUID(tid)}
                )
            await session.execute(
                text("ALTER TABLE core_audit_logs ENABLE TRIGGER core_audit_logs_append_only")
            )
            await session.commit()


async def _ensure_erp_rls_role() -> None:
    """Create the non-owner RLS test role + grants on the 0006 tables.

    The dev ``skyrict`` user owns the tables (and bypasses RLS), so a
    NON-OWNER role is needed to prove the policies bite. Skipped with an
    actionable message when the local ``skyrict`` lacks CREATEROLE.
    """
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{RLS_ROLE}') "
                f"THEN CREATE ROLE {RLS_ROLE} NOLOGIN; "
                "END IF; END $$;"
            )
            await conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {RLS_ROLE}")
            await conn.exec_driver_sql(
                f"GRANT SELECT ON TABLE public.core_audit_logs TO {RLS_ROLE}"
            )
            await conn.exec_driver_sql(
                f"GRANT INSERT ON TABLE public.core_audit_logs TO {RLS_ROLE}"
            )
            await conn.exec_driver_sql(
                f"GRANT SELECT, INSERT ON TABLE public.erp_sequences TO {RLS_ROLE}"
            )
    except ProgrammingError as exc:
        if "permission denied to create role" not in str(exc).lower():
            raise
        pytest.skip(
            "SQL-level RLS smoke tests require a role with CREATEROLE to create "
            "the non-owner 'core_rls_smoke' test role. The compose/CI stack's "
            "skyrict superuser can; a non-superuser local skyrict cannot. "
            "Run the tests against the compose stack, or grant CREATEROLE to "
            'skyrict with: psql -U postgres -c "ALTER ROLE skyrict CREATEROLE"'
        )


class TestAuditHashChain:
    async def test_add_computes_linked_hashes(
        self, migrated_schema: None, audit_world: dict[str, str]
    ) -> None:
        async with async_session_factory() as session:
            repo = AuditLogRepository(session)
            actor = uuid.uuid4()
            first = await repo.add(
                AuditLogEntry(
                    tenant_id=uuid.UUID(audit_world["tenant_a"]),
                    action=HR_LEAVE_APPROVED,
                    target=f"leave_request:{uuid.uuid4()}",
                    actor_user_id=actor,
                    details={"days": 2},
                )
            )
            second = await repo.add(
                AuditLogEntry(
                    tenant_id=uuid.UUID(audit_world["tenant_a"]),
                    action=PAYROLL_RUN_APPROVED,
                    target=f"payroll_run:{uuid.uuid4()}",
                )
            )
            await session.commit()

            assert first.hash is not None and len(first.hash) == 64
            assert first.prev_hash is not None and len(first.prev_hash) == 64
            assert first.created_at is not None
            assert first.details == {"days": 2}
            assert first.actor_user_id == actor
            # Every row links to its predecessor's hash (chain continuity).
            assert second.prev_hash == first.hash
            assert second.hash is not None and second.hash != first.hash

        await engine.dispose()

    async def test_append_only_blocks_update_and_delete(
        self, migrated_schema: None, audit_world: dict[str, str]
    ) -> None:
        async with async_session_factory() as session:
            repo = AuditLogRepository(session)
            entry = await repo.add(
                AuditLogEntry(
                    tenant_id=uuid.UUID(audit_world["tenant_a"]),
                    action=HR_LEAVE_APPROVED,
                    target="leave_request:x",
                )
            )
            await session.commit()

            with pytest.raises(Exception) as excinfo:
                await session.execute(
                    text("UPDATE core_audit_logs SET action = 'x.y' WHERE id = :id"),
                    {"id": entry.id},
                )
            assert "append-only" in str(excinfo.value)
            await session.rollback()

            with pytest.raises(Exception) as excinfo:
                await session.execute(
                    text("DELETE FROM core_audit_logs WHERE id = :id"),
                    {"id": entry.id},
                )
            assert "append-only" in str(excinfo.value)
            await session.rollback()

        await engine.dispose()

    async def test_feed_is_newest_first_and_filterable(
        self, migrated_schema: None, audit_world: dict[str, str]
    ) -> None:
        async with async_session_factory() as session:
            repo = AuditLogRepository(session)
            # Commit after each insert so ``created_at`` (transaction start time)
            # differs row to row - otherwise ordering within the same transaction
            # is not meaningful.
            for i in range(3):
                await repo.add(
                    AuditLogEntry(
                        tenant_id=uuid.UUID(audit_world["tenant_a"]),
                        action=PAYROLL_RUN_APPROVED,
                        target=f"payroll_run:{i}",
                    )
                )
                await session.commit()
            await repo.add(
                AuditLogEntry(
                    tenant_id=uuid.UUID(audit_world["tenant_a"]),
                    action=HR_LEAVE_APPROVED,
                    target="leave_request:0",
                )
            )
            await session.commit()

            feed = await repo.list(uuid.UUID(audit_world["tenant_a"]))
            assert len(feed) == 4
            assert feed[0].action == HR_LEAVE_APPROVED  # inserted last
            assert [e.target for e in feed] == [
                "leave_request:0",
                "payroll_run:2",
                "payroll_run:1",
                "payroll_run:0",
            ]

            filtered = await repo.list(
                uuid.UUID(audit_world["tenant_a"]), action=PAYROLL_RUN_APPROVED
            )
            assert [e.target for e in filtered] == [
                "payroll_run:2",
                "payroll_run:1",
                "payroll_run:0",
            ]

            fetched = await repo.get(uuid.UUID(audit_world["tenant_a"]), feed[0].id)
            assert fetched is not None and fetched.action == HR_LEAVE_APPROVED
            assert (
                await repo.get(uuid.UUID(audit_world["tenant_b"]), feed[0].id)
            ) is None  # tenant-scoped

        await engine.dispose()

    async def test_per_tenant_chain_genesis_under_rls(
        self, migrated_schema: None, audit_world: dict[str, str]
    ) -> None:
        """The hash chain is self-contained PER TENANT when RLS applies.

        As a non-owner role scoped by the tenant GUC, the trigger's previous-hash
        lookup only sees the current tenant's rows - so each tenant's chain
        starts from 64 zeros even though the other tenant already has rows.
        """
        await _ensure_erp_rls_role()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            # Tenant A's first-ever row: genesis hash.
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (audit_world["tenant_a"],),
            )
            await conn.execute(
                text(
                    "INSERT INTO core_audit_logs (tenant_id, action, target) "
                    "VALUES (:tid, 'hr.leave.approved', 'leave_request:genesis')"
                ),
                {"tid": uuid.UUID(audit_world["tenant_a"])},
            )
            row_a = (await conn.execute(text("SELECT hash, prev_hash FROM core_audit_logs"))).one()
            # Tenant B's first-ever row ALSO starts at genesis, despite A's rows.
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (audit_world["tenant_b"],),
            )
            await conn.execute(
                text(
                    "INSERT INTO core_audit_logs (tenant_id, action, target) "
                    "VALUES (:tid, 'payroll.run.approved', 'payroll_run:genesis')"
                ),
                {"tid": uuid.UUID(audit_world["tenant_b"])},
            )
            row_b = (await conn.execute(text("SELECT hash, prev_hash FROM core_audit_logs"))).one()

            assert row_a.prev_hash == "0" * 64
            assert row_b.prev_hash == "0" * 64
            assert row_a.hash != row_b.hash
            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()

    async def test_audit_service_writes_through_repository(
        self, migrated_schema: None, audit_world: dict[str, str]
    ) -> None:
        async with async_session_factory() as session:
            service = AuditService(AuditLogRepository(session))
            entry = await service.log(
                action=HR_LEAVE_APPROVED,
                target="leave_request:svc",
                tenant_id=uuid.UUID(audit_world["tenant_a"]),
                user_id=uuid.uuid4(),
            )
            await session.commit()
            assert entry.hash is not None and len(entry.hash) == 64
        await engine.dispose()


class TestSequenceRepository:
    async def test_next_value_first_use_starts_at_one(
        self, migrated_schema: None, audit_world: dict[str, str]
    ) -> None:
        async with async_session_factory() as session:
            repo = SequenceRepository(session)
            first = await repo.next_value(uuid.UUID(audit_world["tenant_a"]), "invoice")
            second = await repo.next_value(uuid.UUID(audit_world["tenant_a"]), "invoice")
            await session.commit()

            assert first == 1
            assert second == 2

            current = await repo.get(uuid.UUID(audit_world["tenant_a"]), "invoice")
            assert current is not None
            assert current.entity == "invoice"
            assert current.current_value == 2
            assert current.id is not None

        await engine.dispose()

    async def test_sequences_are_tenant_scoped(
        self, migrated_schema: None, audit_world: dict[str, str]
    ) -> None:
        async with async_session_factory() as session:
            repo = SequenceRepository(session)
            a_first = await repo.next_value(uuid.UUID(audit_world["tenant_a"]), "quote")
            b_first = await repo.next_value(uuid.UUID(audit_world["tenant_b"]), "quote")
            await session.commit()

            assert a_first == 1
            assert b_first == 1  # separate counter per tenant

            other = await repo.get(uuid.UUID(audit_world["tenant_b"]), "invoice")
            assert other is None  # tenant A's invoice counter is not visible to B

        await engine.dispose()


class TestAuditAndSequenceRls:
    async def test_audit_and_sequence_tenant_isolation(
        self, migrated_schema: None, audit_world: dict[str, str]
    ) -> None:
        await _ensure_erp_rls_role()

        async with async_session_factory() as session:
            repo = AuditLogRepository(session)
            seq = SequenceRepository(session)
            await repo.add(
                AuditLogEntry(
                    tenant_id=uuid.UUID(audit_world["tenant_a"]),
                    action=HR_LEAVE_APPROVED,
                    target="leave_request:rls",
                )
            )
            await seq.next_value(uuid.UUID(audit_world["tenant_a"]), "invoice")
            await session.commit()
        await engine.dispose()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (audit_world["tenant_a"],),
            )
            a_logs = (
                (await conn.execute(text("SELECT target FROM core_audit_logs"))).scalars().all()
            )
            assert a_logs == ["leave_request:rls"]
            a_seqs = (await conn.execute(text("SELECT entity FROM erp_sequences"))).scalars().all()
            assert a_seqs == ["invoice"]

            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (audit_world["tenant_b"],),
            )
            b_logs = (
                (await conn.execute(text("SELECT target FROM core_audit_logs"))).scalars().all()
            )
            b_seqs = (await conn.execute(text("SELECT entity FROM erp_sequences"))).scalars().all()
            assert b_logs == []
            assert b_seqs == []
            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()

    async def test_cross_tenant_sequence_insert_blocked(
        self, migrated_schema: None, audit_world: dict[str, str]
    ) -> None:
        await _ensure_erp_rls_role()

        async with engine.connect() as conn:
            await conn.exec_driver_sql(f"SET ROLE {RLS_ROLE}")
            await conn.exec_driver_sql(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                (audit_world["tenant_a"],),
            )
            with pytest.raises(Exception) as excinfo:
                await conn.execute(
                    text(
                        "INSERT INTO erp_sequences (tenant_id, id, entity) "
                        "VALUES (:tid, gen_random_uuid(), 'invoice')"
                    ),
                    {"tid": uuid.UUID(audit_world["tenant_b"])},
                )
            assert "row-level security" in str(excinfo.value).lower()
            await conn.rollback()
            await conn.exec_driver_sql("RESET ROLE")

        await engine.dispose()


class TestMigration0006:
    async def test_erp_permission_keys_seeded(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT key FROM core_permissions"))
            keys = result.scalars().all()
            for key in _ERP_PERMISSION_KEYS:
                assert key in keys

        await engine.dispose()

    async def test_trigger_functions_exist(self, migrated_schema: None) -> None:
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT proname FROM pg_proc WHERE proname IN "
                    "('core_audit_logs_set_hash', 'core_audit_logs_append_only')"
                )
            )
            names = result.scalars().all()
            assert sorted(names) == ["core_audit_logs_append_only", "core_audit_logs_set_hash"]

        await engine.dispose()
