"""Audit event catalog consistency tests — CATALOG vs AUDIT_EVENT_MODULES."""

from __future__ import annotations

from core.core.audit_events import (
    AUDIT_EVENT_MODULES,
    CATALOG,
    HR_LEAVE_APPROVED,
    PAYROLL_RUN_APPROVED,
)


class TestAuditEventCatalog:
    def test_modules_cover_catalog_exactly(self) -> None:
        module_keys = {key for _, _, keys in AUDIT_EVENT_MODULES for key in keys}
        assert module_keys == set(CATALOG)

    def test_catalog_has_no_duplicates(self) -> None:
        assert len(CATALOG) == len(set(CATALOG))

    def test_hr_payroll_events_follow_doc_vocabulary(self) -> None:
        # docs/modules/hr-payroll.md step 4 canonical vocabulary.
        assert HR_LEAVE_APPROVED == "hr.leave.approved"
        assert PAYROLL_RUN_APPROVED == "payroll.run.approved"
        assert "hr.department.created" in CATALOG
        assert "payroll.settings.updated" in CATALOG
