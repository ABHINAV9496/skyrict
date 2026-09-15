"""Unit tests for channel selection + dispatch (SKY-93).

The policy contract: in-app is always on and forced on for mandatory
categories; email/webhook need BOTH the user pref AND the config master
switch; dispatch only touches adapters enabled for the row.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from core.features.notifications.channels import (
    EmailChannelAdapter,
    InAppChannelAdapter,
    NotificationChannel,
    WebhookChannelAdapter,
    build_dispatcher,
    dispatch_channels,
    select_channels,
)


class RecordingAdapter:
    """Adapter that records deliveries for assertions."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.delivered: list[object] = []

    async def deliver(self, notification: object) -> None:
        self.delivered.append(notification)


class TestSelectChannels:
    def test_defaults_in_app_only(self) -> None:
        channels = select_channels(
            category_mandatory=False,
            in_app_on=True,
            email_on=False,
            webhook_on=False,
            email_master_enabled=False,
            webhook_master_enabled=False,
        )
        assert channels == {
            NotificationChannel.IN_APP: True,
            NotificationChannel.EMAIL: False,
            NotificationChannel.WEBHOOK: False,
        }

    def test_mandatory_forces_in_app_despite_opt_out(self) -> None:
        channels = select_channels(
            category_mandatory=True,
            in_app_on=False,
            email_on=False,
            webhook_on=False,
            email_master_enabled=False,
            webhook_master_enabled=False,
        )
        assert channels[NotificationChannel.IN_APP] is True

    def test_email_requires_both_pref_and_master_switch(self) -> None:
        # pref on but master off -> off
        off = select_channels(
            category_mandatory=False,
            in_app_on=True,
            email_on=True,
            webhook_on=False,
            email_master_enabled=False,
            webhook_master_enabled=False,
        )
        assert off[NotificationChannel.EMAIL] is False
        # both on -> on
        on = select_channels(
            category_mandatory=False,
            in_app_on=True,
            email_on=True,
            webhook_on=False,
            email_master_enabled=True,
            webhook_master_enabled=False,
        )
        assert on[NotificationChannel.EMAIL] is True

    def test_mandatory_email_respects_master_switch(self) -> None:
        on = select_channels(
            category_mandatory=True,
            in_app_on=False,
            email_on=False,
            webhook_on=False,
            email_master_enabled=True,
            webhook_master_enabled=False,
        )
        assert on[NotificationChannel.EMAIL] is True
        off = select_channels(
            category_mandatory=True,
            in_app_on=False,
            email_on=False,
            webhook_on=False,
            email_master_enabled=False,
            webhook_master_enabled=False,
        )
        assert off[NotificationChannel.EMAIL] is False


class TestBuildDispatcher:
    def test_in_app_always_present(self) -> None:
        adapters = build_dispatcher(email_enabled=False, webhook_enabled=False)
        assert [a.name for a in adapters] == [NotificationChannel.IN_APP.value]

    def test_email_and_webhook_are_conditional(self) -> None:
        names = [a.name for a in build_dispatcher(email_enabled=True, webhook_enabled=True)]
        assert names == [
            NotificationChannel.IN_APP.value,
            NotificationChannel.EMAIL.value,
            NotificationChannel.WEBHOOK.value,
        ]

    def test_adapter_classes_carry_enum_value_names(self) -> None:
        assert InAppChannelAdapter.name == NotificationChannel.IN_APP.value
        assert EmailChannelAdapter.name == NotificationChannel.EMAIL.value
        assert WebhookChannelAdapter.name == NotificationChannel.WEBHOOK.value


class TestDispatchChannels:
    @pytest.mark.asyncio
    async def test_only_enabled_adapters_receive_delivery(self) -> None:
        notification = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
        email = RecordingAdapter(NotificationChannel.EMAIL.value)
        webhook = RecordingAdapter(NotificationChannel.WEBHOOK.value)
        await dispatch_channels(
            notification,
            [email, webhook],
            enabled_channels={NotificationChannel.EMAIL.value: True},
        )
        assert email.delivered == [notification]
        assert webhook.delivered == []

    @pytest.mark.asyncio
    async def test_channels_off_means_no_delivery(self) -> None:
        notification = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
        email = RecordingAdapter(NotificationChannel.EMAIL.value)
        await dispatch_channels(
            notification,
            [email],
            enabled_channels={NotificationChannel.EMAIL.value: False},
        )
        assert email.delivered == []
