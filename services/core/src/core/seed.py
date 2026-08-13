"""Database seeding — per-tenant HR/Payroll defaults (HR-DATA-001).

Global reference data (currencies, permissions) is seeded by migration 0001;
the per-tenant defaults that CANNOT live in a migration (they are tenant-scoped
decisions) live here and are applied at tenant provisioning time:

  - the leave-type catalogue defaults: annual (accrual, 20 days/yr), sick and
    unpaid (non-accrual ledger-only types);
  - the single ``erp_payroll_settings`` row per tenant (default currency from
    settings, zero PF/tax rates, nearest rounding).

EMP-/PR- record-numbering seeds are deliberately NOT here: there is no
``erp_sequences`` table in HR-DATA-001 scope and a naive counter would race
under concurrency. Numbering lands in the HR service ticket with a locking
mechanism (advisory lock or a Postgres sequence).

Idempotent: safe to re-run — existing rows are left untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from core.core.config import settings
from core.db.session import async_session_factory
from core.features.hr.models.leave_type import LeaveTypeModel
from core.features.payroll.models.payroll_run import PayrollRounding
from core.features.payroll.models.payroll_settings import PayrollSettingsModel

if TYPE_CHECKING:
    import uuid

logger = structlog.get_logger("core.seed")


@dataclass(frozen=True)
class LeaveTypeDefault:
    """One default leave-type catalogue entry."""

    code: str
    name: str
    is_accrual: bool
    accrual_days_per_year: int | None


LEAVE_TYPE_DEFAULTS: tuple[LeaveTypeDefault, ...] = (
    LeaveTypeDefault("annual", "Annual Leave", True, 20),
    LeaveTypeDefault("sick", "Sick Leave", False, None),
    LeaveTypeDefault("unpaid", "Unpaid Leave", False, None),
)


@dataclass(frozen=True)
class PayrollDefaults:
    """Shape of the single per-tenant payroll settings row."""

    default_currency: str
    pf_rate: Decimal
    tax_rate: Decimal
    rounding: PayrollRounding


async def seed_tenant_hr_defaults(tenant_id: uuid.UUID) -> None:
    """Idempotently seed the HR/Payroll defaults for one tenant."""
    async with async_session_factory() as session:
        existing_types = {
            code
            for (code,) in (
                await session.execute(
                    select(LeaveTypeModel.code).where(LeaveTypeModel.tenant_id == tenant_id)
                )
            ).all()
        }

        inserted_types = 0
        for defaults in LEAVE_TYPE_DEFAULTS:
            if defaults.code in existing_types:
                continue
            session.add(
                LeaveTypeModel(
                    tenant_id=tenant_id,
                    code=defaults.code,
                    name=defaults.name,
                    is_accrual=defaults.is_accrual,
                    accrual_days_per_year=defaults.accrual_days_per_year,
                )
            )
            inserted_types += 1
        if inserted_types:
            logger.info("seed.leave_types.created", tenant_id=str(tenant_id), count=inserted_types)

        existing_settings = await session.execute(
            select(PayrollSettingsModel.id).where(PayrollSettingsModel.tenant_id == tenant_id)
        )
        if existing_settings.scalar_one_or_none() is None:
            session.add(
                PayrollSettingsModel(
                    tenant_id=tenant_id,
                    default_currency=settings.DEFAULT_CURRENCY,
                    pf_rate=Decimal("0"),
                    tax_rate=Decimal("0"),
                    rounding=PayrollRounding.NEAREST,
                )
            )
            logger.info("seed.payroll_settings.created", tenant_id=str(tenant_id))

        await session.commit()
