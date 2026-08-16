"""Restrict the leave-ledger negative guard to accrual leave types.

Migration 0013 made ``erp_leave_movements`` append-only and hardened the per-
``(tenant, employee, leave_type)`` ledger against going negative for EVERY
leave type. That over-reached for non-accrual (ledger-only) types such as
``sick`` and ``unpaid``: the HR service deliberately treats those as unbounded
ledger entries (no balance rows, no balance pre-check — see
``core/features/hr/service.py`` approve) yet the guard made their very first
approval INSERT raise and surface as an unhandled 500 against the real stack.

This migration makes the guard apply only to accrual types (the ones that
materialize a balance capped at zero): the function skips the check when the
leave type is not accrual, so ledger-only types stay tracked but are never
blocked. The append-only trigger is untouched.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-16
"""

from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _guard_function(*, accrual_only: bool) -> str:
    guard = (
        """            -- Only accrual leave types (which materialize a capped balance)
            -- are guarded. Non-accrual / ledger-only types (sick, unpaid, ...)
            -- are pure logging and may run negative.
            IF NOT EXISTS (
                SELECT 1 FROM public.erp_leave_types
                WHERE tenant_id = NEW.tenant_id
                  AND code = NEW.leave_type
                  AND is_accrual IS TRUE
            ) THEN
                RETURN NEW;
            END IF;
"""
        if accrual_only
        else ""
    )
    return f"""
        CREATE FUNCTION public.erp_leave_movements_guard_negative() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        DECLARE
            running integer;
        BEGIN
{guard}
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


def upgrade() -> None:
    op.execute("DROP TRIGGER erp_leave_movements_guard_negative ON public.erp_leave_movements")
    op.execute("DROP FUNCTION public.erp_leave_movements_guard_negative()")
    op.execute(_guard_function(accrual_only=True))
    op.execute(
        "CREATE TRIGGER erp_leave_movements_guard_negative BEFORE INSERT "
        "ON public.erp_leave_movements FOR EACH ROW "
        "EXECUTE FUNCTION public.erp_leave_movements_guard_negative()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER erp_leave_movements_guard_negative ON public.erp_leave_movements")
    op.execute("DROP FUNCTION public.erp_leave_movements_guard_negative()")
    op.execute(_guard_function(accrual_only=False))
    op.execute(
        "CREATE TRIGGER erp_leave_movements_guard_negative BEFORE INSERT "
        "ON public.erp_leave_movements FOR EACH ROW "
        "EXECUTE FUNCTION public.erp_leave_movements_guard_negative()"
    )
