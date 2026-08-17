"""crm_workspace: contacts, activities, notes, timeline events

CRM workspace upgrade — the unified CRM activity model plus the
customer-facing timeline. Four additive tables, each tenant-scoped with the
composite ``(tenant_id, id)`` primary key convention and RLS (migration 0003
pattern):

- ``erp_crm_contacts`` — a person on a customer account (tenant-scoped like
  customers; ``customer_id`` is a plain UUID soft link, no FK).
- ``erp_crm_activities`` — unified activity rows (task/call/meeting/
  follow_up/email/note). Follow-ups are ``kind = 'follow_up'`` rows with a
  ``due_at``; completion is ``completed_at`` + ``completed_by`` together
  (DB CHECK). Owner/team-scoped like leads/opportunities.
- ``erp_crm_notes`` — persistent free-form notes anchored to one CRM entity.
- ``erp_crm_timeline_events`` — the curated CRM business log (customer-facing
  timeline). Deliberately separate from the security ``audit_logs`` trail.

Activities, notes, and timeline events anchor to exactly one CRM entity via
the shared ``erp_crm_entity_type`` enum + ``entity_id``. Order creations are
recorded as ``event_type = 'order.created'`` anchored to the customer —
there is NO ``order`` entity type.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES = (
    "erp_crm_contacts",
    "erp_crm_activities",
    "erp_crm_notes",
    "erp_crm_timeline_events",
)


def upgrade() -> None:
    activity_kind = postgresql.ENUM(
        "task",
        "call",
        "meeting",
        "follow_up",
        "email",
        "note",
        name="erp_crm_activity_kind",
        # Migrations own type creation (create() below); columns must not
        # re-create it on table create (SQLAlchemy's before_create event
        # fires with checkfirst=False, colliding with the explicit create).
        create_type=False,
    )
    entity_type = postgresql.ENUM(
        "lead",
        "opportunity",
        "customer",
        "contact",
        name="erp_crm_entity_type",
        create_type=False,
    )
    timeline_event_type = postgresql.ENUM(
        "lead.created",
        "lead.status_changed",
        "lead.qualified",
        "lead.disqualified",
        "opportunity.stage_changed",
        "opportunity.won",
        "opportunity.lost",
        "customer.created",
        "order.created",
        "contact.created",
        "contact.deactivated",
        name="erp_crm_timeline_event_type",
        create_type=False,
    )
    activity_kind.create(op.get_bind(), checkfirst=True)
    entity_type.create(op.get_bind(), checkfirst=True)
    timeline_event_type.create(op.get_bind(), checkfirst=True)

    # --- erp_crm_contacts (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_crm_contacts",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # customer_id: soft link to the owning account (plain UUID, no FK).
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("job_title", sa.String(255), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(first_name IS NOT NULL AND first_name <> '')"
            " OR (last_name IS NOT NULL AND last_name <> '')"
            " OR (email IS NOT NULL AND email <> '')",
            name="ck_erp_crm_contacts_identity_present",
        ),
    )
    op.create_index(
        "ix_erp_crm_contacts_tenant_customer",
        "erp_crm_contacts",
        ["tenant_id", "customer_id"],
    )
    # NON-unique dedupe probe index — like leads, contact dedupe is a soft
    # service-layer operation, never a uniqueness constraint.
    op.create_index(
        "ix_erp_crm_contacts_tenant_email",
        "erp_crm_contacts",
        ["tenant_id", "email"],
    )

    # --- erp_crm_activities (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_crm_activities",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kind", activity_kind, nullable=False),
        sa.Column("entity_type", entity_type, nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("description", sa.String(4000), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.String(4000), nullable=True),
        # owner_id / team_id: plain UUIDs, NO FK (identity users / teams).
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_by IS NOT NULL",
            name="ck_erp_crm_activities_completed_pair",
        ),
    )
    op.create_index(
        "ix_erp_crm_activities_tenant_entity",
        "erp_crm_activities",
        ["tenant_id", "entity_type", "entity_id"],
    )
    op.create_index(
        "ix_erp_crm_activities_tenant_owner_due",
        "erp_crm_activities",
        ["tenant_id", "owner_id", "due_at"],
    )

    # --- erp_crm_notes (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_crm_notes",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_type", entity_type, nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.String(4000), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "body IS NOT NULL AND body <> ''",
            name="ck_erp_crm_notes_body_present",
        ),
    )
    op.create_index(
        "ix_erp_crm_notes_tenant_entity",
        "erp_crm_notes",
        ["tenant_id", "entity_type", "entity_id"],
    )

    # --- erp_crm_timeline_events (tenant-scoped, composite PK, RLS) ---
    op.create_table(
        "erp_crm_timeline_events",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entity_type", entity_type, nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", timeline_event_type, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_erp_crm_timeline_tenant_entity_created",
        "erp_crm_timeline_events",
        ["tenant_id", "entity_type", "entity_id", "created_at"],
    )

    # --- Row-Level Security policies ---
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
            "USING (tenant_id = public.current_tenant_id()) "
            "WITH CHECK (tenant_id = public.current_tenant_id())"
        )


def downgrade() -> None:
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")

    op.drop_index("ix_erp_crm_timeline_tenant_entity_created", table_name="erp_crm_timeline_events")
    op.drop_table("erp_crm_timeline_events")

    op.drop_index("ix_erp_crm_notes_tenant_entity", table_name="erp_crm_notes")
    op.drop_table("erp_crm_notes")

    op.drop_index("ix_erp_crm_activities_tenant_owner_due", table_name="erp_crm_activities")
    op.drop_index("ix_erp_crm_activities_tenant_entity", table_name="erp_crm_activities")
    op.drop_table("erp_crm_activities")

    op.drop_index("ix_erp_crm_contacts_tenant_email", table_name="erp_crm_contacts")
    op.drop_index("ix_erp_crm_contacts_tenant_customer", table_name="erp_crm_contacts")
    op.drop_table("erp_crm_contacts")

    op.execute("DROP TYPE IF EXISTS erp_crm_timeline_event_type")
    op.execute("DROP TYPE IF EXISTS erp_crm_entity_type")
    op.execute("DROP TYPE IF EXISTS erp_crm_activity_kind")
