"""Compliance finding repository (HR-AI-001, Unit C).

Projects ``erp_employees`` + ``erp_employee_documents`` into pure-engine
signals, runs the SHARED rule pack :func:`skyrict_common.ai_hr_rules.detect_compliance_findings`
and persists findings into ``ai_compliance_checks`` by replace-tenant scan (the
leave/payroll inbox pattern). The detection itself is the exact code the
ai-agent eval harness grades.

Rules (see the shared engine docstring): ``document_expiry``,
``training_overdue``, ``contract_missing_field``. ``requires_training`` is
derived as "holds a certification document" — presence of a certification row
signals a role that must keep it current; the expired-required-certification
finding is the primary runtime signal, while the missing-document branch stays
exercisable by the pure engine only (no native ``requires_training`` column).

``title``/``description`` have no columns on ``ai_compliance_checks``, so they
are stored under the ``evidence`` JSONB keys of the same name (the payroll
anomaly convention) and re-surfaced as first-class fields on read.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.ai_hr.models.compliance_check import ComplianceCheckModel
from core.features.ai_hr.models.employee_document import EmployeeDocumentModel
from core.features.hr.models.department import DepartmentModel
from core.features.hr.models.employee import EmployeeModel
from skyrict_common.ai_hr_rules import (
    ComplianceFinding,
    DocumentComplianceSignal,
    EmployeeComplianceContext,
    detect_compliance_findings,
)


@dataclass(frozen=True, slots=True)
class ComplianceFindingRow:
    """One stored compliance finding, with read-side enrichment."""

    employee_id: uuid.UUID | None
    check_type: str
    severity: str
    owner_rule: str
    status: str
    title: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    check_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    employee_number: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    department_name: str | None = None


class AiHrComplianceRepository:
    """Read/write access to compliance signals and persisted findings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- signal projection ----------------------------------------------------

    async def build_compliance_rows(self, tenant_id: uuid.UUID) -> list[ComplianceFindingRow]:
        """Detect findings for the tenant's current people + documents."""
        employees_stmt = select(
            EmployeeModel.id,
            EmployeeModel.employment_status,
            EmployeeModel.email,
            EmployeeModel.department_id,
            EmployeeModel.job_title,
            EmployeeModel.phone,
        ).where(EmployeeModel.tenant_id == tenant_id)
        employee_rows = (await self.session.execute(employees_stmt)).all()
        employees = {
            r.id: EmployeeComplianceContext(
                employee_id=r.id,
                status=r.employment_status,
                email=r.email,
                department_id=r.department_id,
                job_title=r.job_title,
                phone=r.phone,
                requires_training=False,
            )
            for r in employee_rows
        }

        docs_stmt = select(
            EmployeeDocumentModel.employee_id,
            EmployeeDocumentModel.id,
            EmployeeDocumentModel.doc_type,
            EmployeeDocumentModel.expiry_date,
            EmployeeDocumentModel.is_required,
            EmployeeDocumentModel.status,
        ).where(EmployeeDocumentModel.tenant_id == tenant_id)
        doc_rows = (await self.session.execute(docs_stmt)).all()
        documents = [
            DocumentComplianceSignal(
                employee_id=d.employee_id,
                document_id=d.id,
                doc_type=d.doc_type,
                expiry_date=d.expiry_date,
                is_required=d.is_required,
                status=d.status,
            )
            for d in doc_rows
        ]

        # requires_training <=> the employee holds a certification document.
        for doc in documents:
            if doc.doc_type == "certification":
                ctx = employees.get(doc.employee_id)
                if ctx is not None:
                    employees[doc.employee_id] = EmployeeComplianceContext(
                        employee_id=ctx.employee_id,
                        status=ctx.status,
                        email=ctx.email,
                        department_id=ctx.department_id,
                        job_title=ctx.job_title,
                        phone=ctx.phone,
                        requires_training=True,
                    )

        findings = detect_compliance_findings(
            documents=documents,
            employees=employees,
            today=date.today(),
        )
        return [self._map_finding(f) for f in findings]

    @classmethod
    def _map_finding(cls, finding: ComplianceFinding) -> ComplianceFindingRow:
        now = datetime.now(UTC)
        return ComplianceFindingRow(
            employee_id=finding.employee_id,
            check_type=finding.check_type,
            severity=finding.severity,
            owner_rule=finding.owner_rule,
            status="open",
            title=finding.title,
            description=finding.description,
            evidence={
                **finding.evidence,
                "title": finding.title,
                "description": finding.description,
            },
            created_at=now,
        )

    # -- persistence ----------------------------------------------------------

    async def latest_generated_at(self, tenant_id: uuid.UUID) -> datetime | None:
        stmt = select(func.max(ComplianceCheckModel.created_at)).where(
            ComplianceCheckModel.tenant_id == tenant_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def replace_tenant_findings(
        self, tenant_id: uuid.UUID, rows: list[ComplianceFindingRow]
    ) -> None:
        """Regenerate the tenant's compliance inbox for one scan run."""
        await self.session.execute(
            delete(ComplianceCheckModel).where(ComplianceCheckModel.tenant_id == tenant_id)
        )
        if not rows:
            return
        values = [
            {
                "tenant_id": tenant_id,
                "employee_id": row.employee_id,
                "check_type": row.check_type,
                "severity": row.severity,
                "owner_rule": row.owner_rule,
                "evidence": row.evidence,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in rows
        ]
        await self.session.execute(insert(ComplianceCheckModel), values)

    # -- reads ----------------------------------------------------------------

    async def list_findings(
        self, tenant_id: uuid.UUID, employee_id: uuid.UUID | None = None
    ) -> list[ComplianceFindingRow]:
        stmt = self._read_stmt(tenant_id).order_by(
            ComplianceCheckModel.created_at.desc(),
            ComplianceCheckModel.severity.asc(),
        )
        if employee_id is not None:
            stmt = stmt.where(ComplianceCheckModel.employee_id == employee_id)
        rows = (await self.session.execute(stmt)).all()
        return [self._to_row(r) for r in rows]

    async def get_finding(
        self, tenant_id: uuid.UUID, check_id: uuid.UUID
    ) -> ComplianceFindingRow | None:
        stmt = self._read_stmt(tenant_id).where(ComplianceCheckModel.id == check_id)
        r = (await self.session.execute(stmt)).first()
        return self._to_row(r) if r is not None else None

    # -- dispositions ---------------------------------------------------------

    async def set_status(
        self,
        tenant_id: uuid.UUID,
        check_id: uuid.UUID,
        *,
        status: str,
        owner_user_id: uuid.UUID | None = None,
    ) -> ComplianceFindingRow | None:
        """Set a finding's status (open -> acknowledged|resolved)."""
        values: dict[str, Any] = {"status": status}
        if status == "acknowledged":
            values["owner_user_id"] = owner_user_id
        result = (
            await self.session.execute(
                update(ComplianceCheckModel)
                .where(
                    ComplianceCheckModel.tenant_id == tenant_id,
                    ComplianceCheckModel.id == check_id,
                )
                .values(**values)
                .returning(ComplianceCheckModel.id)
            )
        ).first()
        if result is None:
            return None
        return await self.get_finding(tenant_id, check_id)

    def _read_stmt(self, tenant_id: uuid.UUID) -> Any:
        return (
            select(
                ComplianceCheckModel.id,
                ComplianceCheckModel.employee_id,
                ComplianceCheckModel.check_type,
                ComplianceCheckModel.severity,
                ComplianceCheckModel.owner_rule,
                ComplianceCheckModel.owner_user_id,
                ComplianceCheckModel.evidence,
                ComplianceCheckModel.status,
                ComplianceCheckModel.created_at,
                EmployeeModel.employee_number,
                EmployeeModel.first_name,
                EmployeeModel.last_name,
                DepartmentModel.name.label("department_name"),
            )
            .outerjoin(
                EmployeeModel,
                and_(
                    EmployeeModel.tenant_id == ComplianceCheckModel.tenant_id,
                    EmployeeModel.id == ComplianceCheckModel.employee_id,
                ),
            )
            .outerjoin(
                DepartmentModel,
                and_(
                    DepartmentModel.tenant_id == EmployeeModel.tenant_id,
                    DepartmentModel.id == EmployeeModel.department_id,
                ),
            )
            .where(ComplianceCheckModel.tenant_id == tenant_id)
        )

    @staticmethod
    def _to_row(r: Any) -> ComplianceFindingRow:
        evidence = dict(r.evidence or {})
        title = str(evidence.pop("title", "Compliance finding"))
        description = str(evidence.pop("description", ""))
        return ComplianceFindingRow(
            employee_id=r.employee_id,
            check_type=r.check_type,
            severity=r.severity,
            owner_rule=r.owner_rule,
            status=r.status,
            title=title,
            description=description,
            evidence=evidence,
            created_at=r.created_at,
            check_id=r.id,
            owner_user_id=r.owner_user_id,
            employee_number=r.employee_number,
            first_name=r.first_name,
            last_name=r.last_name,
            department_name=r.department_name,
        )


__all__ = ["AiHrComplianceRepository", "ComplianceFindingRow"]
