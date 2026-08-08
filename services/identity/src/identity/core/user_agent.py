"""User-Agent parsing — turns a raw UA string into human-readable device facts.

Backed by the ``user-agents`` library (ua-parser regexes). Never raises: a
missing or unparseable UA yields ``Unknown`` values so downstream consumers
(session records, security-alert emails) always get a renderable string.
"""

from __future__ import annotations

from dataclasses import dataclass

from user_agents import parse

UNKNOWN = "Unknown"


@dataclass(frozen=True)
class DeviceInfo:
    """Human-readable facts extracted from a User-Agent string."""

    browser: str = UNKNOWN
    browser_version: str = ""
    os: str = UNKNOWN
    os_version: str = ""
    device: str = UNKNOWN
    device_type: str = "Unknown"


def _first(*parts: str) -> str:
    """Join non-empty parts with a space, dropping leading/trailing cruft."""
    cleaned = " ".join(p for p in parts if p and p != "Other")
    return cleaned or UNKNOWN


def parse_user_agent(user_agent: str | None) -> DeviceInfo:
    """Parse a raw User-Agent header into a :class:`DeviceInfo`.

    Empty input and bot UAs produce ``DeviceInfo`` with ``Unknown`` fields and
    an empty ``browser_version`` — never an exception.
    """
    if not user_agent or not user_agent.strip():
        return DeviceInfo()

    parsed = parse(user_agent)

    browser = _first(parsed.browser.family)
    browser_version = _first(parsed.browser.version_string)
    os = _first(parsed.os.family)
    os_version = _first(parsed.os.version_string)
    device = _first(parsed.device.family)
    if parsed.is_bot:
        device = "Bot"

    device_type = (
        "Mobile"
        if parsed.is_mobile
        else "Tablet"
        if parsed.is_tablet
        else "Bot"
        if parsed.is_bot
        else "Desktop"
    )

    return DeviceInfo(
        browser=browser,
        browser_version="" if browser_version == UNKNOWN else browser_version,
        os=os,
        os_version="" if os_version == UNKNOWN else os_version,
        device=device,
        device_type=device_type,
    )
