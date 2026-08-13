"""Domain entities — pure Python, no framework dependencies.

These are the in-memory representations the repository layer maps ORM models
to/from. They are plain (immutable) dataclasses so services can reason about
tenant-scoped RBAC grants without touching SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from core.core.constants import (
    EmploymentStatus,
    LeaveRequestStatus,
    PayrollRounding,
    PayrollRunStatus,
)
from core.domain.value_objects import Money

if TYPE_CHECKING:
    import uuid
    from datetime import date, datetime

    from core.domain.value_objects import StockMovementType


@dataclass(frozen=True)
class CorePermission:
    """A platform-fixed permission key (e.g. ``erp.invoice.read``).

    Global — not tenant-scoped: the catalog is the same for every tenant.
    """

    key: str
    description: str = ""


@dataclass(frozen=True)
class CoreRole:
    """A tenant-scoped role holding a set of permission grants.

    ``permissions`` holds granted permission keys. The wildcard ``"*"`` grants
    every key in the catalog (owner role).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    permissions: tuple[str, ...] = ()
    is_system_role: bool = False


@dataclass(frozen=True)
class CoreUserRole:
    """A tenant-scoped grant of one role to one user.

    ``user_id`` references an identity-service user (no FK at the DB level —
    identity owns users).
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    scope_id: uuid.UUID | None = field(default=None)


@dataclass(frozen=True)
class Product:
    """A tenant-scoped sellable/countable item (soft-deletable via ``is_active``).

    Prices are ``Money`` amounts so currency validation happens at construction,
    and the ORM layer splits them into a Numeric column + currency code.
    """

    tenant_id: uuid.UUID
    sku: str
    name: str
    category: str | None = None
    unit: str | None = None
    cost_price: Money = field(default_factory=lambda: Money.zero("USD"))
    sell_price: Money = field(default_factory=lambda: Money.zero("USD"))
    reorder_point: Decimal = Decimal("0")
    is_active: bool = True
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Warehouse:
    """A tenant-scoped storage location (soft-deletable via ``is_active``)."""

    tenant_id: uuid.UUID
    name: str
    location: str | None = None
    is_active: bool = True
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class StockLevel:
    """Materialized current stock for one product in one warehouse.

    ``qty_on_hand`` = ledger sum of non-reservation movements; ``qty_reserved``
    = net of reservation/release movements. The DB CHECK ``0 <= qty_reserved
    <= qty_on_hand`` makes over-reservation impossible at the constraint level.
    """

    tenant_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty_on_hand: Decimal = Decimal("0")
    qty_reserved: Decimal = Decimal("0")
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class StockMovement:
    """One immutable ledger entry — insert-only, never updated or deleted.

    ``qty`` is signed (negative for issues/outflows). ``(ref_type, ref_id)``
    identifies the source document line for idempotency probes; combined with
    ``warehouse_id`` it is unique per tenant so a transfer pair can share a ref.
    """

    tenant_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    movement_type: StockMovementType
    qty: Decimal
    ref_type: str
    ref_id: str
    id: uuid.UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class ErpSequence:
    """A per-tenant monotonic counter for one document numbering sequence.

    Services claim the next value via ``SequenceRepository.next_value`` (a
    row-locking ``UPDATE ... SET current_value = current_value + 1 RETURNING``),
    so consecutive numbers are race-safe and never reused.
    """

    tenant_id: uuid.UUID
    entity: str
    current_value: int = 0
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class AuditLogEntry:
    """One immutable core (ERP) audit event in the tenant's hash chain.

    ``hash`` / ``prev_hash`` are computed by the DB trigger on INSERT and are
    ``None`` until then. Append-only: never update or delete.
    """

    tenant_id: uuid.UUID
    action: str
    target: str
    actor_user_id: uuid.UUID | None = None
    details: dict | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    id: uuid.UUID | None = None
    hash: str | None = None
    prev_hash: str | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# HR & Payroll entities (HR-BE-002) — pure domain, no framework dependencies.
# The repository layer maps these to/from the ORM models under
# ``features/{hr,payroll}/models/``.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Department:
    """An organizational unit within a tenant (soft-deletable via ``is_active``)."""

    tenant_id: uuid.UUID
    name: str
    manager_employee_id: uuid.UUID | None = None
    is_active: bool = True
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Employee:
    """A person employed within a tenant.

    ``employment_status`` is the single source of employment truth — there is
    deliberately no separate ``is_active`` flag. ``termination_date`` is
    required when status is ``terminated``.
    """

    tenant_id: uuid.UUID
    employee_number: str
    first_name: str
    last_name: str
    job_title: str
    hire_date: date
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    email: str | None = None
    phone: str | None = None
    user_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    termination_date: date | None = None
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class LeaveType:
    """Tenant-scoped leave catalogue entry (per-tenant accrual policy)."""

    tenant_id: uuid.UUID
    code: str
    name: str
    is_accrual: bool
    accrual_days_per_year: int | None = None
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class LeaveRequest:
    """A leave request raised by an employee and its approval state.

    ``days`` is derived (``end_date - start_date + 1``), computed server-side.
    """

    tenant_id: uuid.UUID
    employee_id: uuid.UUID
    leave_type: str
    start_date: date
    end_date: date
    days: int
    status: LeaveRequestStatus = LeaveRequestStatus.PENDING
    reason: str | None = None
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class LeaveMovement:
    """One immutable entry in the leave ledger for a single employee.

    ``qty`` is signed (``+`` accrued/refunded, ``-`` approved/used) and must
    never be zero. Append-only: no update, no delete.
    """

    tenant_id: uuid.UUID
    employee_id: uuid.UUID
    leave_type: str
    qty: int
    ref_type: str
    ref_id: str | None = None
    reason: str | None = None
    id: uuid.UUID | None = None
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class LeaveBalance:
    """Materialized current balance for one employee + leave type.

    Only accrual leave types have balance rows; ``balance`` is recomputed from
    the ledger and can never be negative (service + DB CHECK).
    """

    tenant_id: uuid.UUID
    employee_id: uuid.UUID
    leave_type: str
    balance: int = 0
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Compensation:
    """An effective-dated salary record for an employee.

    The row effective at or before period end (``is_active = true``, latest
    ``effective_from``) is used by payroll. ``monthly_salary`` is ``Money`` so
    currency is validated at construction.
    """

    tenant_id: uuid.UUID
    employee_id: uuid.UUID
    monthly_salary: Money
    effective_from: date
    is_active: bool = True
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class PayrollRun:
    """A payroll run covering one tenant and one monthly period.

    ``total_gross``/``total_net`` are None until the run is computed; a
    zero-dollar run must stay distinct from a not-yet-computed run.
    """

    tenant_id: uuid.UUID
    run_code: str
    period_start: date
    period_end: date
    status: PayrollRunStatus = PayrollRunStatus.DRAFT
    total_gross: Money | None = None
    total_net: Money | None = None
    computed_by: uuid.UUID | None = None
    approved_by: uuid.UUID | None = None
    paid_by: uuid.UUID | None = None
    computed_at: datetime | None = None
    approved_at: datetime | None = None
    paid_at: datetime | None = None
    void_reason: str | None = None
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class PayrollEntry:
    """An immutable per-employee result row inside a payroll run.

    Once the run is approved, entries are frozen (no update, no delete).
    ``adjustments`` is free-form (bonus/other deductions) applied while the
    run is draft/computed.
    """

    tenant_id: uuid.UUID
    run_id: uuid.UUID
    employee_id: uuid.UUID
    base_salary: Money
    pay_days: int
    gross: Money
    deductions: Money
    net: Money
    adjustments: dict[str, object] | None = None
    id: uuid.UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class PayrollSettings:
    """Tenant payroll configuration — exactly one row per tenant."""

    tenant_id: uuid.UUID
    default_currency: str = "USD"
    pf_rate: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    rounding: PayrollRounding = PayrollRounding.NEAREST
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
