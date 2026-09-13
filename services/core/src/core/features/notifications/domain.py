"""Notification domain types (SKY-93) - enums, drafts and recipient specs.

Pydantic is intentionally avoided here: these types are consumed by
producers, the batching worker and the CLI, and plain frozen dataclasses
keep them dependency-free. API boundaries use the Pydantic schemas in
``schemas.py``.

Severity is the single source of truth for ranking weights: low=10,
medium=40, high=70, critical=100. Only low/medium are batchable - high and
critical always render as individual rows (a critical approval-due pin must
never collapse into a digest).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class NotificationSeverity(enum.StrEnum):
    """Notification severity - drives priority scoring and batching policy."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_WEIGHTS: dict[NotificationSeverity, int] = {
    NotificationSeverity.LOW: 10,
    NotificationSeverity.MEDIUM: 40,
    NotificationSeverity.HIGH: 70,
    NotificationSeverity.CRITICAL: 100,
}

# Severities that may be collapsed into a digest by the batching worker.
BATCHABLE_SEVERITIES: frozenset[NotificationSeverity] = frozenset(
    (NotificationSeverity.LOW, NotificationSeverity.MEDIUM)
)

# Recipient resolution kinds supported by the producer SDK.
RECIPIENT_KIND_USERS = "users"
RECIPIENT_KIND_PERMISSION = "permission"
RECIPIENT_KIND_ROLE = "role"
RECIPIENT_KINDS: frozenset[str] = frozenset(
    (RECIPIENT_KIND_USERS, RECIPIENT_KIND_PERMISSION, RECIPIENT_KIND_ROLE)
)


class NotificationConfigurationError(ValueError):
    """Raised when a producer references an unknown category/severity.

    Producer SDK contracts fail fast: an unknown category or severity is
    almost always a producer bug, and silently dropping the event would hide
    it. This error is a programming error, not a client 4xx.
    """


@dataclass(frozen=True)
class RecipientSpec:
    """Who receives a notification.

    ``kind`` selects the resolution strategy:

    - ``users`` - ``values`` are explicit user UUID strings.
    - ``permission`` - ``values`` are permission keys; recipients are every
      user holding any of the keys (resolved via core_roles grants).
    - ``role`` - ``values`` are role names; recipients are every user granted
      any of the roles.
    """

    kind: str
    values: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.kind not in RECIPIENT_KINDS:
            raise NotificationConfigurationError(
                f"Unknown recipient kind: {self.kind!r} (expected one of {sorted(RECIPIENT_KINDS)})"
            )
        if not self.values:
            raise NotificationConfigurationError("RecipientSpec.values must not be empty")

    @classmethod
    def from_users(cls, *user_ids: str | uuid.UUID) -> RecipientSpec:
        """Recipients are explicit user ids (accepts str or UUID)."""
        return cls(kind=RECIPIENT_KIND_USERS, values=tuple(str(uid) for uid in user_ids))

    @classmethod
    def from_permissions(cls, *permission_keys: str) -> RecipientSpec:
        """Recipients are every user holding any of the permission keys."""
        return cls(kind=RECIPIENT_KIND_PERMISSION, values=tuple(permission_keys))

    @classmethod
    def from_roles(cls, *role_names: str) -> RecipientSpec:
        """Recipients are every user granted any of the role names."""
        return cls(kind=RECIPIENT_KIND_ROLE, values=tuple(role_names))


@dataclass(frozen=True)
class NotificationDraft:
    """The producer SDK input - one logical event to fan out to recipients.

    ``dedupe_key`` makes the emission idempotent per recipient: re-emitting
    the same key creates no second row. Producers must pick a stable key
    (e.g. ``{module}.{event}:{tenant-scoped-entity-id}``) so retries and
    repeated reads collapse to the first delivery.
    """

    dedupe_key: str
    event_type: str
    category: str
    module: str
    severity: NotificationSeverity
    title: str
    body: str
    recipients: RecipientSpec
    relevance_key: str | None = None
    payload: dict[str, Any] | None = None
    occurred_at: datetime | None = None
    is_dismissible: bool = True
    created_by: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if not self.dedupe_key.strip():
            raise NotificationConfigurationError("dedupe_key must not be empty")
        if not self.event_type.strip():
            raise NotificationConfigurationError("event_type must not be empty")
        if not self.title.strip():
            raise NotificationConfigurationError("title must not be empty")
        if not self.body.strip():
            raise NotificationConfigurationError("body must not be empty")
        if self.occurred_at is not None and self.occurred_at.tzinfo is None:
            object.__setattr__(self, "occurred_at", self.occurred_at.replace(tzinfo=UTC))
