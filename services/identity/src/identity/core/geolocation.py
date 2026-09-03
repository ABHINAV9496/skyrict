"""Approximate IP geolocation backed by MaxMind GeoLite2-City.

A thin, defensive wrapper around ``geoip2``:

* Lazy-loads ``GeoLite2-City.mmdb`` once and caches the reader.
* Never raises - missing DB, unknown/private/reserved IPs and corrupt records
  all resolve to ``None`` so login and alert flows degrade gracefully.
* ``mask_ip`` returns a display-safe IP (kept on the server, never sent to
  MaxMind - the DB is local and lookup is offline).
"""

from __future__ import annotations

import ipaddress
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from geoip2.database import Reader
from geoip2.errors import AddressNotFoundError

from identity.core.config import settings

logger = structlog.get_logger("identity.geolocation")


@dataclass(frozen=True)
class Location:
    """Approximate location derived from an IP address."""

    country: str | None = None
    region: str | None = None
    city: str | None = None

    def __bool__(self) -> bool:
        return any((self.country, self.region, self.city))


class GeoIP:
    """Offline GeoLite2-City lookup with graceful degradation.

    The reader is opened on first use and reused for the process lifetime.
    Lookups are thread-safe (geoip2 readers are safe for concurrent reads).
    """

    _reader: Reader | None = None
    _load_error: str | None = None
    _lock = threading.Lock()

    @classmethod
    def _reader_or_none(cls) -> Reader | None:
        if cls._reader is not None or cls._load_error is not None:
            return cls._reader

        with cls._lock:
            if cls._reader is not None or cls._load_error is not None:
                return cls._reader
            path = Path(settings.GEOIP_DB_PATH).expanduser()
            if not path.is_file():
                cls._load_error = f"GEOIP_DB_PATH not found: {path}"
                return None
            try:
                cls._reader = Reader(str(path))
            except Exception as exc:  # corrupt/unreadable DB must not break logins
                cls._load_error = f"cannot open GeoLite2 DB: {exc}"
                logger.warning("geoip.db.load_failed", path=str(path), error=str(exc))
                return None
            logger.info("geoip.db.loaded", path=str(path))
            return cls._reader

    @classmethod
    def lookup(cls, ip_address: str | None) -> Location | None:
        """Resolve an IP to a best-effort :class:`Location`, or ``None``."""
        if not ip_address or not cls._usable_ip(ip_address):
            return None

        reader = cls._reader_or_none()
        if reader is None:
            return None

        try:
            record = reader.city(ip_address)
        except (AddressNotFoundError, ValueError) as exc:
            logger.debug("geoip.lookup.not_found", ip=cls._safe_ip(ip_address), error=str(exc))
            return None
        except Exception as exc:  # any lookup failure degrades to None
            logger.warning("geoip.lookup.failed", error=str(exc))
            return None

        country = record.country.name or record.country.iso_code
        region = record.subdivisions.most_specific.name or None
        city = record.city.name or None
        location = Location(country=country, region=region, city=city)
        return location if location else None

    @staticmethod
    def _usable_ip(ip_address: str) -> bool:
        """True for public, routable IPs that a GeoIP DB can resolve."""
        try:
            addr = ipaddress.ip_address(ip_address.split("%")[0])
        except ValueError:
            return False
        return not (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_unspecified
            or addr.is_reserved
        )

    @staticmethod
    def _safe_ip(ip_address: str) -> str:
        return mask_ip(ip_address)


def format_location(location: Location | None) -> str:
    """Render a location as 'City, Region, Country', omitting unknown parts."""
    if not location:
        return "Unknown"
    parts = [p for p in (location.city, location.region, location.country) if p]
    return ", ".join(parts) if parts else "Unknown"


def mask_ip(ip_address: str | None) -> str:
    """Mask an IP for display: IPv4 keeps 3 octets, IPv6 keeps /48, else 'Unknown'."""
    if not ip_address:
        return "Unknown"
    raw = ip_address.split("%")[0]
    try:
        addr: Any = ipaddress.ip_address(raw)
    except ValueError:
        return "Unknown"

    if isinstance(addr, ipaddress.IPv4Address):
        octets = str(addr).split(".")
        return f"{'.'.join(octets[:3])}.***"
    # IPv6: keep the first 48 bits (three hextets), mask the rest.
    groups = str(addr).split(":")
    return ":".join(groups[:3]) + "::***"


# Process-wide singleton; lazy so tests can run without a GeoLite2 DB.
geoip = GeoIP()
