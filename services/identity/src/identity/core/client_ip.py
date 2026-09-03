"""Real client IP extraction behind trusted reverse proxies.

The identity service records a client IP for every session, rate-limit key,
and audit event. That IP must be the *end user's* address - never a value the
client itself supplied. Only peers listed in ``IDENTITY_TRUSTED_PROXIES`` may
influence the result:

* No trusted proxies configured: the direct TCP peer (``request.client``) is
  authoritative and ``X-Forwarded-For`` is ignored entirely, so spoofed
  headers are never honoured.
* Trusted proxies configured: the ``X-Forwarded-For`` chain is walked from the
  right; hops that belong to a trusted proxy are skipped and the first
  untrusted entry is the client IP. This mirrors how nginx/ingress-nginx
  append to the chain and defeats client-supplied leading entries.

Never raises: missing client info, non-IP peers (e.g. ``testclient`` from an
ASGI test client) and malformed chain entries fall back to the TCP peer.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from identity.core.config import settings

if TYPE_CHECKING:
    from fastapi import Request


def _as_ip(value: str | None) -> ipaddress._BaseAddress | None:
    """Parse a value as an IP address; None for anything non-IP."""
    if not value:
        return None
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _normalize(value: str | None) -> str | None:
    """Canonicalize an IP string, unwrapping IPv4-mapped IPv6.

    Non-IP values (e.g. ``testclient``) pass through untouched so they can be
    recorded verbatim rather than mangled.
    """
    addr = _as_ip(value)
    if addr is None:
        stripped = value.strip() if value else None
        return stripped or None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    return addr.compressed


def _is_trusted(value: str | None) -> bool:
    """True when a value falls inside a configured trusted-proxy network."""
    if not settings.TRUSTED_PROXIES:
        return False
    addr = _as_ip(value)
    if addr is None:
        return False
    return any(
        addr.version == net.version and addr in net for net in settings.trusted_proxy_networks
    )


def client_ip(request: Request) -> str:
    """Return the real client IP for a request; ``"unknown"`` as a last resort.

    Forwarded headers are only consulted when the direct TCP peer is itself a
    configured trusted proxy. Otherwise the peer is returned and the
    ``X-Forwarded-For`` header is ignored, preventing header spoofing by
    untrusted clients.
    """
    peer = _normalize(request.client.host if request.client else None)

    if _is_trusted(peer):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = (hop.strip() for hop in forwarded.split(",") if hop.strip())
            for hop in reversed(list(hops)):
                if _as_ip(hop) is None:
                    continue
                hop_norm = _normalize(hop)
                if _is_trusted(hop_norm):
                    continue
                assert hop_norm is not None
                return hop_norm

    return peer or "unknown"
