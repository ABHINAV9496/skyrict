"""Email delivery port and transports for critical-anomaly alerts.

Two transports behind the same ``EmailService`` protocol:

* ``LogEmailService`` — logs the alert payload (default when no SMTP is
  configured; dev/test default).
* ``SmtpEmailService`` — delivers via SMTP using the stdlib (dev: shared
  Mailpit relay; prod: a real relay).

SMTP failures are logged but never raised, so anomaly scans don't hard-fail
on delivery problems. The :func:`build_email_service` factory picks a
transport from configuration and is the only place that needs to know about
the SMTP settings (spec §4.3 admin-notification email).
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

import structlog

from ai_agent.core.anomaly_email_templates import (
    CriticalAnomalyAlert,
    render_anomaly_alert_html,
    render_anomaly_alert_text,
)

logger = structlog.get_logger("ai_agent.email")


class EmailService(Protocol):
    """Delivery contract for critical-anomaly admin alerts."""

    async def send_critical_anomaly_alert(self, *, alert: CriticalAnomalyAlert) -> None: ...


class LogEmailService:
    """Transport that logs the alert payload (dev/test default)."""

    async def send_critical_anomaly_alert(self, *, alert: CriticalAnomalyAlert) -> None:
        logger.info(
            "email.anomaly_alert.sent",
            to=alert.to,
            tenant_id=alert.tenant_id,
            anomaly_id=alert.anomaly_id,
            anomaly_type=alert.anomaly_type,
            severity=alert.severity,
            title=alert.title,
            status=alert.status,
            created_at=alert.created_at,
        )


class SmtpEmailService:
    """Transport that delivers critical-anomaly alerts over SMTP.

    Delivery runs in a thread so the event loop is never blocked by the
    (usually sub-millisecond) local relay round-trip. Failures are logged and
    swallowed — the scanner's own audit trail remains the source of truth.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_addr: str,
        username: str = "",
        password: str = "",
        use_tls: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._from_addr = from_addr
        self._username = username
        self._password = password
        self._use_tls = use_tls

    async def send_critical_anomaly_alert(self, *, alert: CriticalAnomalyAlert) -> None:
        text = render_anomaly_alert_text(alert)
        html = render_anomaly_alert_html(alert)
        subject = f"CRITICAL: {alert.title}"
        await self._deliver(alert.to, subject, text, html)

    async def _deliver(self, to: str, subject: str, text: str, html: str | None) -> None:
        message = EmailMessage()
        message["From"] = self._from_addr
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")

        def _blocking() -> None:
            with smtplib.SMTP(self._host, self._port, timeout=10) as client:
                client.ehlo()
                if self._use_tls:
                    client.starttls()
                    client.ehlo()
                if self._username:
                    client.login(self._username, self._password)
                client.send_message(message)

        try:
            await asyncio.to_thread(_blocking)
        except (OSError, smtplib.SMTPException) as exc:
            logger.exception(
                "email.anomaly_alert.delivery_failed",
                to=to,
                subject=subject,
                smtp_host=self._host,
                smtp_port=self._port,
                error=str(exc),
            )
            return
        logger.info("email.anomaly_alert.delivered", to=to, subject=subject)


def build_email_service(
    *,
    host: str,
    port: int = 1025,
    from_addr: str = "Skyrict <no-reply@skyrict.dev>",
    username: str = "",
    password: str = "",
    use_tls: bool = False,
) -> EmailService:
    """Pick the SMTP transport when a relay host is configured, else log-only."""
    if host:
        return SmtpEmailService(
            host=host,
            port=port,
            from_addr=from_addr,
            username=username,
            password=password,
            use_tls=use_tls,
        )
    return LogEmailService()
