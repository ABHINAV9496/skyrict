"""initial schema: tenants, users, roles, permissions, user_roles, sessions, audit_logs

- Postgres Row-Level Security on every tenant-scoped table (GUC
  ``app.current_tenant_id``; policy reads ``public.current_tenant_id()``).
- Tamper-evident audit log: sha256 hash chain (pgcrypto ``digest``) computed
  by a BEFORE INSERT trigger, plus an append-only trigger that rejects
  UPDATE/DELETE.
- Seed of the platform-fixed permission catalog (~18 entries).

Revision ID: 0001
Revises:
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_TENANT_SCOPED_TABLES = ("users", "roles", "user_roles", "sessions", "audit_logs")

# ---------------------------------------------------------------------------
# Permission catalog (platform-fixed, no tenant)
# ---------------------------------------------------------------------------
PERMISSION_CATALOG: tuple[tuple[str, str], ...] = (
    ("users:read", "List and view users"),
    ("users:write", "Create and update users"),
    ("users:delete", "Delete or deactivate users"),
    ("roles:read", "View roles and role assignments"),
    ("roles:write", "Create and update roles and grants"),
    ("tenants:read", "View tenant settings"),
    ("tenants:write", "Update tenant settings and plan"),
    ("sessions:read", "List sessions"),
    ("sessions:revoke", "Revoke sessions"),
    ("audit:read", "Read the audit log"),
    ("mfa:manage", "Configure multi-factor authentication"),
    ("sso:manage", "Configure single sign-on"),
    ("settings:read", "Read tenant settings"),
    ("settings:write", "Write tenant settings"),
    ("erp.invoice.read", "View invoices"),
    ("erp.invoice.approve", "Approve invoices"),
    ("erp.purchase.approve", "Approve purchase orders"),
    ("billing.manage", "Manage billing"),
)


def upgrade() -> None:
    # --- extensions ---
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # --- enum types ---
    scope_type = postgresql.ENUM(
        "tenant", "org", "workspace", "department", "team", name="identity_scope_type"
    )

    # --- tenants ---
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column(
            "plan_tier",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'free'"),
        ),
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
            "plan_tier IN ('free', 'starter', 'pro', 'enterprise')",
            name="ck_tenants_plan_tier",
        ),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("full_name", sa.String(256), nullable=False, server_default=sa.text("''")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mfa_secret", sa.String(64), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    # --- roles ---
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("is_system_role", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
        sa.UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])

    # --- permissions (platform-fixed catalog) ---
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("key", name="uq_permissions_key"),
    )
    op.create_index("ix_permissions_key", "permissions", ["key"], unique=True)

    # --- user_roles (scoped grants) ---
    op.create_table(
        "user_roles",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "role_id", sa.Uuid(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_type", scope_type, nullable=False, server_default=sa.text("'tenant'")),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id", "role_id", "scope_type", "scope_id", name="uq_user_roles_scope"
        ),
    )
    op.create_index("ix_user_roles_tenant_id", "user_roles", ["tenant_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    # --- sessions ---
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_token_hash", sa.String(128), nullable=False),
        sa.Column("device_info", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"])

    # --- audit_logs (append-only, hash-chained) ---
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    # --- Row-Level Security ---
    op.execute(
        "CREATE FUNCTION public.current_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS $$ "
        "SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid $$"
    )

    # tenants: SELECT always readable so routing middleware can resolve the
    # slug before any tenant context exists.
    op.execute("ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenants_readable ON public.tenants FOR SELECT USING (true)")

    # tenant-scoped tables: every DML op must match the current tenant.
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON public.{table} "
            "USING (tenant_id = public.current_tenant_id()) "
            "WITH CHECK (tenant_id = public.current_tenant_id())"
        )

    # --- Audit tamper-evidence: hash chain + append-only ---
    op.execute(
        """
        CREATE FUNCTION public.audit_logs_set_hash() RETURNS trigger AS $$
        DECLARE
            prev char(64);
        BEGIN
            SELECT hash INTO prev FROM public.audit_logs
            ORDER BY created_at DESC, id DESC LIMIT 1;
            NEW.created_at := COALESCE(NEW.created_at, now());
            NEW.prev_hash := COALESCE(prev, repeat('0', 64));
            NEW.hash := encode(digest(
                NEW.prev_hash::text
                || NEW.action::text
                || NEW.target::text
                || COALESCE(NEW.actor_user_id::text, '')
                || NEW.tenant_id::text
                || NEW.created_at::text,
                'sha256'
            ), 'hex');
            RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER audit_logs_hash_chain BEFORE INSERT ON public.audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION public.audit_logs_set_hash()"
    )

    op.execute(
        """
        CREATE FUNCTION public.audit_logs_append_only() RETURNS trigger AS $$
        BEGIN
            -- Referential-integrity writes (FK CASCADE / SET NULL) fire at
            -- trigger depth >= 2; allow those. Direct UPDATE/DELETE against
            -- the log (depth 1) is rejected: the log is append-only.
            IF pg_trigger_depth() > 1 THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                ELSE
                    RETURN NEW;
                END IF;
            END IF;
            RAISE EXCEPTION 'audit_logs is append-only; UPDATE/DELETE forbidden';
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON public.audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION public.audit_logs_append_only()"
    )

    # --- Seed the platform-fixed permission catalog ---
    # Literal values only (fixed tuple above) so offline SQL generation works.
    permission_rows = ", ".join(
        f"('{key}', '{description}')" for key, description in PERMISSION_CATALOG
    )
    op.execute(
        # ``permission_rows`` is built solely from the compile-time literal
        # ``PERMISSION_CATALOG`` above — no user input, so this f-string SQL
        # is not an injection vector.
        "INSERT INTO permissions (key, description) VALUES "
        f"{permission_rows} ON CONFLICT (key) DO NOTHING"  # nosec B608
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON public.audit_logs")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_hash_chain ON public.audit_logs")
    op.execute("DROP FUNCTION IF EXISTS public.audit_logs_append_only()")
    op.execute("DROP FUNCTION IF EXISTS public.audit_logs_set_hash()")

    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON public.{table}")

    op.execute("DROP POLICY IF EXISTS tenants_readable ON public.tenants")
    op.execute("ALTER TABLE public.tenants DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS public.current_tenant_id()")

    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_sessions_tenant_id", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_index("ix_user_roles_tenant_id", table_name="user_roles")
    op.drop_table("user_roles")

    op.drop_index("ix_permissions_key", table_name="permissions")
    op.drop_table("permissions")

    op.drop_index("ix_roles_tenant_id", table_name="roles")
    op.drop_table("roles")

    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")

    op.execute("DROP TYPE IF EXISTS identity_scope_type")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
