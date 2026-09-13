"""Notification channel adapters (SKY-93).

The ticket scopes this sprint's delivery as: in-app always on (the inbox row
IS the in-app delivery); email/webhook adapters exist behind config master
switches and are **log-only** - they record the structured, would-be delivery
instead of dialling an SMTP/webhook integration that is not yet vetted.

Every adapter implements the same contract: ``deliver(notification)``, where
``notification`` is the ORM row just committed (or about to commit) to
``erp_notifications``. The producer picks the enabled channels per recipient
from prefs + flags and dispatches each enabled non-in-app channel here.

The adapter logs the recipient id, notification id, module and channel - not
free-text payload - so the audit trail never leaks PII.
"""

from __future__ import annotations

import enum
from typing import Any, Protocol

from core.core.logging import get_logger

logger = get_logger("core.notifications.channels")


class NotificationChannel(enum.StrEnum):
    """Channel identifiers stored in ``erp_notifications.channels``."""

    IN_APP = "in_app"
    EMAIL = "email"
    WEBHOOK = "webhook"


class ChannelAdapter(Protocol):
    """Contract every delivery adapter implements."""

    name: str

    async def deliver(self, notification: Any) -> None: ...


class InAppChannelAdapter:
    """In-app delivery - the inbox row itself.

    Nothing to send: the notification center IS the in-app inbox. Kept as an
    explicit adapter (rather than a silent no-op) so the channel pipeline is
    uniform: ``select_channels`` always enables it and dispatch calls it like
    any other channel.
    """

    name = NotificationChannel.IN_APP.value

    async def deliver(self, notification: Any) -> None:
        logger.debug(
            "notifications.channel.in_app.delivered",
            notification_id=str(notification.id),
            tenant_id=str(notification.tenant_id),
        )


class EmailChannelAdapter:
    """Email delivery - log-only until an SMTP transport is vetted."""

    name = NotificationChannel.EMAIL.value

    async def deliver(self, notification: Any) -> None:
        logger.info(
            "notifications.channel.email.would_send",
            notification_id=str(notification.id),
            recipient_user_id=str(notification.recipient_user_id),
            tenant_id=str(notification.tenant_id),
            module=notification.module,
            category=notification.category,
            severity=notification.severity,
        )


class WebhookChannelAdapter:
    """Webhook delivery - log-only until a webhook sink is vetted."""

    name = NotificationChannel.WEBHOOK.value

    async def deliver(self, notification: Any) -> None:
        logger.info(
            "notifications.channel.webhook.would_post",
            notification_id=str(notification.id),
            recipient_user_id=str(notification.recipient_user_id),
            tenant_id=str(notification.tenant_id),
            module=notification.module,
            category=notification.category,
            severity=notification.severity,
        )


def select_channels(
    *,
    category_mandatory: bool,
    in_app_on: bool,
    email_on: bool,
    webhook_on: bool,
    email_master_enabled: bool,
    webhook_master_enabled: bool,
) -> dict[str, bool]:
    """Compute the delivery channels for one recipient from prefs + flags.

    - ``in_app`` is on by default and forced on for mandatory categories.
    - ``email``/``webhook`` require BOTH the user's pref AND the config
      master switch (master switches keep the log-only adapters off unless an
      operator enables them). Mandatory categories are never silenced by a
      user opt-out, but respect the master switch too - the log-only adapter
      must not claim a delivery path that is not wired.
    """
    return {
        NotificationChannel.IN_APP: category_mandatory or in_app_on,
        NotificationChannel.EMAIL: email_master_enabled and (category_mandatory or email_on),
        NotificationChannel.WEBHOOK: webhook_master_enabled and (category_mandatory or webhook_on),
    }


def build_dispatcher(
    *,
    email_enabled: bool,
    webhook_enabled: bool,
) -> list[ChannelAdapter]:
    """Assemble the per-process adapter list (master switches from config)."""
    adapters: list[ChannelAdapter] = [InAppChannelAdapter()]
    if email_enabled:
        adapters.append(EmailChannelAdapter())
    if webhook_enabled:
        adapters.append(WebhookChannelAdapter())
    return adapters


async def dispatch_channels(
    notification: Any,
    adapters: list[ChannelAdapter],
    *,
    enabled_channels: dict[str, bool],
) -> None:
    """Dispatch one notification row over its enabled channels.

    The ``channels`` dict on the row is the source of truth (persisted at
    emit time); adapters not enabled for the row are skipped even when the
    adapter exists in the process.
    """
    for adapter in adapters:
        if enabled_channels.get(adapter.name, False):
            await adapter.deliver(notification)


def channel_names_from_flags(
    email_enabled: bool, webhook_enabled: bool
) -> list[NotificationChannel]:
    """Return the channel names the current config wires (for validation/logging)."""
    names = [NotificationChannel.IN_APP]
    if email_enabled:
        names.append(NotificationChannel.EMAIL)
    if webhook_enabled:
        names.append(NotificationChannel.WEBHOOK)
    return names
