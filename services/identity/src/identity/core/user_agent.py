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


def _major(version: str) -> str:
    """Collapse a dotted version string to its major component ('' if none)."""
    head = version.split(".", 1)[0] if version else ""
    return head if head and head.isdigit() else ""


def _device_label(
    *,
    is_bot: bool,
    hardware: str,
    browser: str,
    browser_version: str,
    os: str,
    os_version: str,
) -> str:
    """Build the human-facing device label.

    Phones/tablets name the hardware (``Pixel 8 on Android 14``); everything
    else falls back to the browser so desktops read ``Chrome 126 on Windows 10``
    instead of ``Unknown``.
    """
    if is_bot:
        return "Bot"

    hardware = (hardware or "").strip()
    if hardware and hardware.lower() not in ("other", "generic", "unknown"):
        label = hardware
    else:
        label = _first(browser, _major(browser_version))

    if os != UNKNOWN:
        os_label = _first(os, _major(os_version))
        if os_label != UNKNOWN:
            label = f"{label} on {os_label}"

    return label or UNKNOWN


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
        device=_device_label(
            is_bot=parsed.is_bot,
            hardware=parsed.device.family,
            browser=browser,
            browser_version=browser_version,
            os=os,
            os_version=os_version,
        ),
        device_type=device_type,
    )
