"""Leave-ledger hardening: erp_leave_movements append-only + non-negative.

Close-out of gap-audit item 11. The ledger contract was documented
(docs/modules/hr-payroll.md §4.2) and service-enforced but had ZERO database
enforcement: nothing at the SQL layer stopped a row from being updated,
deleted, or from summing to a negative balance. This migration adds both:

* ``erp_leave_movements_append_only`` — direct UPDATE/DELETE is rejected
  (referential-integrity writes at ``pg_trigger_depth() > 1`` still pass,
  mirroring the core_audit_logs pattern from 0006).
* ``erp_leave_movements_guard_negative`` (SECURITY DEFINER) — on INSERT the
  SUM(qty) for the affected ``(tenant_id, employee_id, leave_type)`` is
  recomputed including the new row and raises when it is negative. The
  function reads the full ledger as the owner, deliberately bypassing the
  invoking role's RLS so an accurate sum is computed for every tenant.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-14
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION public.erp_leave_movements_append_only() RETURNS trigger AS $$
        BEGIN
            -- Referential-integrity writes (FK CASCADE / SET NULL) fire at
            -- trigger depth >= 2; allow those. Direct UPDATE/DELETE against
            -- the ledger (depth 1) is rejected: it is append-only.
            IF pg_trigger_depth() > 1 THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                ELSE
                    RETURN NEW;
                END IF;
            END IF;
            RAISE EXCEPTION 'erp_leave_movements is append-only; UPDATE/DELETE forbidden';
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER erp_leave_movements_append_only BEFORE UPDATE OR DELETE "
        "ON public.erp_leave_movements FOR EACH ROW "
        "EXECUTE FUNCTION public.erp_leave_movements_append_only()"
    )

    op.execute(
        """
        CREATE FUNCTION public.erp_leave_movements_guard_negative() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        DECLARE
            running integer;
        BEGIN
            -- Recompute the employee's balance for this leave type from the
            -- whole ledger AS the owner (so RLS on the invoking role can never
            -- hide part of the ledger), INCLUDING the incoming row.
            running := COALESCE(
                (
                    SELECT SUM(qty) FROM public.erp_leave_movements
                    WHERE tenant_id = NEW.tenant_id
                      AND employee_id = NEW.employee_id
                      AND leave_type = NEW.leave_type
                ),
                0
            ) + NEW.qty;
            IF running < 0 THEN
                RAISE EXCEPTION
                    'leave balance would go negative for employee % leave type % (sum %)',
                    NEW.employee_id, NEW.leave_type, running;
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER erp_leave_movements_guard_negative BEFORE INSERT "
        "ON public.erp_leave_movements FOR EACH ROW "
        "EXECUTE FUNCTION public.erp_leave_movements_guard_negative()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER erp_leave_movements_guard_negative ON public.erp_leave_movements")
    op.execute("DROP FUNCTION public.erp_leave_movements_guard_negative()")
    op.execute("DROP TRIGGER erp_leave_movements_append_only ON public.erp_leave_movements")
    op.execute("DROP FUNCTION public.erp_leave_movements_append_only()")
