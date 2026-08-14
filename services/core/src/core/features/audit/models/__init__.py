"""Audit ORM models — registered on ``Base.metadata``.

``audit_logs`` is created by identity's migration 0001 in the SHARED database
(no core migration). The model is a read/write mapping of that table so core's
repositories can append audit rows; the DB triggers fill ``hash``/``prev_hash``
and block UPDATE/DELETE.
"""

from core.features.audit.models.audit_log import AuditLogModel

__all__ = ["AuditLogModel"]
