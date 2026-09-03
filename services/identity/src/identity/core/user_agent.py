"""User-Agent parsing - turns a raw UA string into structured device facts.

Backed by the ``user-agents`` library (ua-parser regexes) and optionally
supplemented by ``Sec-CH-UA*`` Client Hints. Never raises: a missing or
unparseable UA yields ``Unknown`` values so downstream consumers (session
records, security-alert emails) always get a renderable string.

Classification is deliberately conservative:

* ``service`` - obvious non-browser clients (curl, node, python-requests…),
  detected before ua-parser so they are never mislabeled as ``Desktop``.
* ``bot`` - known crawlers already flagged by ua-parser.
* ``mobile`` / ``tablet`` / ``desktop`` - derived from ua-parser device hints.
* ``unknown`` - nothing reliable to say (e.g. a bare ``Mozilla/5.0``).

Windows 10 vs Windows 11 is only distinguished via
``Sec-CH-UA-Platform-Version`` (major >= 15 implies Windows 11); a bare
``Windows NT 10.0`` string is never enough to claim either. Device *models*
are reported only when the parser yields a specific handset model - never
invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from user_agents import parse

if TYPE_CHECKING:
    from collections.abc import Mapping

UNKNOWN = "Unknown"

# Lowercase UA prefix tokens that unambiguously indicate a programmatic client.
# A real browser always starts with "Mozilla/5.0", so these are only consulted
# for non-browser strings.
_PROGRAMMATIC: dict[str, str] = {
    "node": "Node.js",
    "node-fetch": "Node.js",
    "axios": "Axios",
    "curl": "curl",
    "wget": "wget",
    "httpie": "HTTPie",
    "python-requests": "Python Requests",
    "python-httpx": "Python HTTPX",
    "httpx": "Python HTTPX",
    "aiohttp": "Python aiohttp",
    "python": "Python",
    "requests": "Python Requests",
    "postmanruntime": "Postman",
    "insomnia": "Insomnia",
    "okhttp": "OkHttp",
    "go-http-client": "Go HTTP Client",
    "httpclient": "HTTP Client",
    "powershell": "PowerShell",
    "java": "Java",
    "dart": "Dart",
    "guzzlehttp": "Guzzle HTTP",
    "ruby": "Ruby",
    "php": "PHP",
    "lua": "Lua",
    "rust": "Rust",
}

_OS_LABELS = {
    "Windows": "Windows",
    "Mac OS X": "macOS",
    "Android": "Android",
    "iOS": "iOS",
    "Linux": "Linux",
}

_BROWSER_CANONICAL = {
    "Chrome Mobile": "Chrome",
    "Chrome Mobile iOS": "Chrome",
    "Mobile Safari": "Safari",
    "Mobile Safari UI/WKWebView": "Safari",
}

_GENERIC_HARDWARE = {"other", "generic", "unknown", "desktop", "android", "generic android", ""}

# Models that describe a device *class* rather than a specific handset are not
# reliable models. iPhone/iPad are named by every iOS UA but never the exact
# hardware revision, so they stay "unknown" per the "never fabricate models"
# rule.
_NON_MODELS = {"iphone", "ipad", "mac", "desktop", "computer", "windows", "linux"}

CLIENT_HINT_HEADERS = (
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-ch-ua-platform-version",
    "sec-ch-ua-model",
)

_BRAND_RE = re.compile(r'^\s*"?([^";]+?)"?\s*;\s*v\s*=\s*"?([^";]*)"?\s*$')


@dataclass(frozen=True)
class DeviceInfo:
    """Structured facts extracted from a User-Agent string.

    Legacy fields (``browser``/``browser_version``/``os``/``os_version``/
    ``device``/``device_type``) keep the pre-existing labels for email
    templates and older consumers. The ``*_name``/``device_family``/
    ``device_model`` fields are the structured, machine-friendly form:
    ``None`` means the fact genuinely could not be determined.
    """

    browser: str = UNKNOWN
    browser_version: str = ""
    os: str = UNKNOWN
    os_version: str = ""
    device: str = UNKNOWN
    device_type: str = "unknown"
    browser_name: str | None = None
    os_name: str | None = None
    device_family: str | None = None
    device_model: str | None = None


@dataclass(frozen=True)
class ClientHints:
    """Structured ``Sec-CH-UA*`` Client Hints (every field optional)."""

    brands: tuple[tuple[str, str], ...] = ()
    mobile: bool | None = None
    platform: str | None = None
    platform_version: str | None = None
    model: str | None = None


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
    else falls back to the browser so desktops read ``Chrome 126 on Windows``
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


def _programmatic_family(user_agent: str) -> str | None:
    """Return the program label when the UA identifies a script/client."""
    lower = user_agent.strip().lower()
    if lower.startswith("mozilla/"):
        return None
    token = lower.split("/", 1)[0].strip()
    return _PROGRAMMATIC.get(token)


def _clean_hint(raw: str | None) -> str | None:
    """Normalize a Client Hints value (strip quotes/backslashes/whitespace)."""
    if raw is None:
        return None
    cleaned = raw.replace("\\", "").strip().strip('"').strip()
    return cleaned or None


def _parse_brands(value: str) -> tuple[tuple[str, str], ...]:
    """Parse ``Sec-CH-UA: "Chromium";v="126", "Google Chrome";v="126"``."""
    brands: list[tuple[str, str]] = []
    for part in value.split(","):
        match = _BRAND_RE.match(part)
        if match:
            brands.append((match.group(1).strip(), match.group(2).strip()))
    return tuple(brands)


def parse_client_hints(headers: Mapping[str, str | None] | None) -> ClientHints:
    """Extract Client Hints from a headers mapping (case-insensitive keys)."""
    if not headers:
        return ClientHints()

    lower = {key.lower(): value for key, value in headers.items() if value}

    brands = _parse_brands(lower.get("sec-ch-ua", "")) if lower.get("sec-ch-ua") else ()

    mobile_raw = _clean_hint(lower.get("sec-ch-ua-mobile"))
    mobile: bool | None = None
    if mobile_raw in ("?1", "1"):
        mobile = True
    elif mobile_raw in ("?0", "0"):
        mobile = False

    platform_version = _clean_hint(lower.get("sec-ch-ua-platform-version"))

    return ClientHints(
        brands=brands,
        mobile=mobile,
        platform=_clean_hint(lower.get("sec-ch-ua-platform")),
        platform_version=platform_version,
        model=_clean_hint(lower.get("sec-ch-ua-model")),
    )


def _os_name(family: str) -> str:
    return _OS_LABELS.get(family, family) if family != "Other" else UNKNOWN


def _browser_name(family: str) -> str | None:
    if family == UNKNOWN:
        return None
    return _BROWSER_CANONICAL.get(family, family)


def _windows_version(hints: ClientHints | None) -> str:
    """Windows 10/11 via Client Hints; '' when the evidence is insufficient."""
    if hints is None or not hints.platform_version:
        return ""
    major = _major(hints.platform_version)
    if not major:
        return ""
    return "11" if int(major) >= 15 else "10"


def _device_facts(
    *,
    device_type: str,
    hardware: str,
    model: str,
    os_name: str | None,
    hints: ClientHints | None,
) -> tuple[str | None, str | None]:
    """Resolve the structured ``device_family`` / ``device_model`` pair."""
    if device_type == "bot":
        return "Bot", None

    if device_type in ("mobile", "tablet"):
        if hardware and hardware.lower() not in _GENERIC_HARDWARE:
            family = hardware
        elif hints is not None and hints.model:
            family = hints.model
        else:
            family = None
        if model and model.lower() not in _GENERIC_HARDWARE | _NON_MODELS:
            device_model = model
        else:
            device_model = None
        return family, device_model

    if device_type == "desktop":
        family = {
            "Windows": "Windows PC",
            "macOS": "Mac",
            "Linux": "Linux PC",
            "Android": "Android Desktop",
        }.get(os_name or "", "Desktop")
        return family, None

    return None, None


def parse_user_agent(
    user_agent: str | None,
    *,
    hints: ClientHints | None = None,
) -> DeviceInfo:
    """Parse a raw User-Agent header into a :class:`DeviceInfo`.

    Empty input and bot UAs produce ``DeviceInfo`` with ``Unknown`` fields and
    an empty ``browser_version`` - never an exception. Programmatic clients
    are classified as ``service``; everything else is classified
    conservatively and never claims a Windows 10/11 label without Client
    Hints evidence.
    """
    if not user_agent or not user_agent.strip():
        return DeviceInfo()

    programmatic = _programmatic_family(user_agent)
    if programmatic is not None:
        return _service_info(user_agent, programmatic)

    parsed = parse(user_agent)

    browser = _first(parsed.browser.family)
    browser_version = _major(parsed.browser.version_string)
    os = _os_name(parsed.os.family)
    os_version = _major(parsed.os.version_string)

    if (
        os == UNKNOWN
        and hints is not None
        and hints.platform is not None
        and hints.platform in _OS_LABELS.values()
    ):
        os = hints.platform
        os_version = _windows_version(hints) if hints.platform == "Windows" else os_version

    if os == "Windows":
        os_version = _windows_version(hints)

    if parsed.is_mobile:
        device_type = "mobile"
    elif parsed.is_tablet:
        device_type = "tablet"
    elif parsed.is_bot:
        device_type = "bot"
    elif browser != UNKNOWN or os != UNKNOWN:
        device_type = "desktop"
    else:
        device_type = "unknown"

    os_name = os if os != UNKNOWN else None
    family, model = _device_facts(
        device_type=device_type,
        hardware=parsed.device.family,
        model=parsed.device.model,
        os_name=os_name,
        hints=hints,
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
        browser_name=_browser_name(browser)
        if device_type in ("desktop", "mobile", "tablet")
        else None,
        os_name=os_name if device_type in ("desktop", "mobile", "tablet") else None,
        device_family=family,
        device_model=model,
    )


def _service_info(user_agent: str, family: str) -> DeviceInfo:
    """Build a ``DeviceInfo`` for a programmatic client (curl, node, …)."""
    version = ""
    if "/" in user_agent:
        tail = user_agent.rsplit("/", 1)[-1].split(" ", 1)[0].strip()
        version = _major(tail)
    return DeviceInfo(
        browser=family,
        browser_version=version,
        device=family,
        device_type="service",
        device_family=family,
    )
