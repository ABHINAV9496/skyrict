"""Fix ai_query_cache uniqueness to be tenant-scoped (SKY-58).

Migration 0004 declared ``UniqueConstraint("query_hash")`` which is GLOBAL -
two tenants asking the same question would collide. The cache contract is one
entry per (tenant_id, query_hash): the composite PK already scopes rows per
tenant, and the unique index must match, otherwise the write-through upsert
(``ON CONFLICT``) has no working conflict target and every second tenant's
identical query fails.

Drops the global constraint and recreates it as a unique INDEX on
(tenant_id, query_hash) - the ORM model's ``__table_args__`` carries the same
index so metadata stays in sync with the schema.

Renumbered from 0003 to 0005 on 2026-08-29 for the same reason as 0004
(dev's SKY-72/SKY-68 took 0002/0003); final ai-agent chain:
0001 -> 0002 (hr copilot) -> 0003 (forecast/abc/monitor) -> 0004 (RAG) ->
0005 (this fix).

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_ai_query_cache_hash", "ai_query_cache", type_="unique")
    op.create_index(
        "uq_ai_query_cache_tenant_hash",
        "ai_query_cache",
        ["tenant_id", "query_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_ai_query_cache_tenant_hash", table_name="ai_query_cache")
    op.create_unique_constraint("uq_ai_query_cache_hash", "ai_query_cache", ["query_hash"])
