"""Audit feature - append-only audit trail for ERP mutations.

Writes into the SHARED ``audit_logs`` table (created by identity's migration,
hash-chained + append-only + RLS-protected), so core records security-relevant
actions without owning the schema. Mirrors ``identity.features.audit``.
"""

from core.features.audit.ports import AuditRepositoryPort
from core.features.audit.repository import AuditRepository
from core.features.audit.service import AuditService

__all__ = ["AuditRepository", "AuditRepositoryPort", "AuditService"]
