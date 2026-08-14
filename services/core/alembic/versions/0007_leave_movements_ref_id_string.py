"""Corrective migration: ``erp_leave_movements.ref_id`` as String(64), not UUID.

Background — this revision heals a silent schema drift; it is not a design
change. Migration ``0005`` originally created ``erp_leave_movements.ref_id``
as ``sa.Uuid()``. Before any new revision was added, the column's intent
changed to a plain reference string (the annual-accrual ref is the leave
year, e.g. ``"2026"``; leave-request / manual-adjustment refs are request /
adjustment ids) and the already-committed migration file was edited in place
(commit ``8bfcc08``). The ORM model and the migration file now say
``String(64)``, but any database migrated with the original ``0005`` still
has a ``uuid`` column while its alembic version table already reads head —
so ``alembic upgrade`` never repairs it on its own.

``upgrade`` changes the column to ``String(64)``:
- on drifted databases (``uuid``) it converts the type (uuid -> text);
- on databases already at ``String(64)`` it is a no-op (same-type ALTER).

It is therefore safe on both clean and drifted environments. No data is
lost: uuid values round-trip to their text form.

The ``downgrade`` is intentionally a no-op: reversing the type back to
``uuid`` would fail for string refs that are not valid UUIDs (e.g. the leave
year ``"2026"``), so the change is irreversible in practice.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "erp_leave_movements",
        "ref_id",
        existing_type=sa.Uuid(),
        type_=sa.String(64),
        existing_nullable=True,
        postgresql_using="ref_id::text",
    )


def downgrade() -> None:
    # Irreversible by design — see the module docstring.
    pass
