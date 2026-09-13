"""Unit tests for notification domain types (SKY-93).

Covers the contract surface the producer SDK relies on: recipient spec
factories + validation, and the draft's fail-fast validation.
"""

from __future__ import annotations

import uuid

import pytest

from core.features.notifications.domain import (
    RECIPIENT_KIND_PERMISSION,
    RECIPIENT_KIND_ROLE,
    RECIPIENT_KIND_USERS,
    NotificationConfigurationError,
    NotificationDraft,
    NotificationSeverity,
    RecipientSpec,
)


class TestRecipientSpec:
    def test_from_users_accepts_str_and_uuid(self) -> None:
        uid1 = uuid.uuid4()
        spec = RecipientSpec.from_users(str(uid1), uuid.uuid4())
        assert spec.kind == RECIPIENT_KIND_USERS
        assert len(spec.values) == 2
        assert spec.values[0] == str(uid1)

    def test_from_permissions_kind_and_values(self) -> None:
        spec = RecipientSpec.from_permissions("erp.finance.read", "erp.inventory.read")
        assert spec.kind == RECIPIENT_KIND_PERMISSION
        assert spec.values == ("erp.finance.read", "erp.inventory.read")

    def test_from_roles_kind_and_values(self) -> None:
        spec = RecipientSpec.from_roles("Finance Manager", "CFO")
        assert spec.kind == RECIPIENT_KIND_ROLE
        assert spec.values == ("Finance Manager", "CFO")

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(NotificationConfigurationError):
            RecipientSpec(kind="everyone", values=("x",))

    def test_empty_values_rejected(self) -> None:
        with pytest.raises(NotificationConfigurationError):
            RecipientSpec(kind=RECIPIENT_KIND_USERS)


class TestNotificationDraft:
    def test_empty_dedupe_key_rejected(self) -> None:
        with pytest.raises(NotificationConfigurationError):
            NotificationDraft(
                dedupe_key="",
                event_type="finance.alert",
                category="finance",
                module="finance",
                severity=NotificationSeverity.HIGH,
                title="t",
                body="b",
                recipients=RecipientSpec.from_users(str(uuid.uuid4())),
            )

    def test_empty_title_rejected(self) -> None:
        with pytest.raises(NotificationConfigurationError):
            NotificationDraft(
                dedupe_key="k",
                event_type="finance.alert",
                category="finance",
                module="finance",
                severity=NotificationSeverity.HIGH,
                title="  ",
                body="b",
                recipients=RecipientSpec.from_users(str(uuid.uuid4())),
            )

    def test_naive_occurred_at_is_normalized_to_utc(self) -> None:
        from datetime import datetime

        draft = NotificationDraft(
            dedupe_key="k",
            event_type="finance.alert",
            category="finance",
            module="finance",
            severity=NotificationSeverity.HIGH,
            title="t",
            body="b",
            recipients=RecipientSpec.from_users(str(uuid.uuid4())),
            occurred_at=datetime(2026, 1, 1, 12, 0, 0),
        )
        assert draft.occurred_at is not None
        assert draft.occurred_at.tzinfo is not None
