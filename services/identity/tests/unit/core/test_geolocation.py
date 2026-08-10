"""Unit tests for IP geolocation helpers (mask, format, lookup degradation)."""

from __future__ import annotations

import pytest

from identity.core.config import settings
from identity.core.geolocation import GeoIP, Location, format_location, geoip, mask_ip


@pytest.fixture(autouse=True)
def _reset_geoip_state() -> None:
    """Clear the cached reader so tests never leak state across runs."""
    GeoIP._reader = None
    GeoIP._load_error = None
    yield
    GeoIP._reader = None
    GeoIP._load_error = None


def test_mask_ipv4_keeps_three_octets() -> None:
    assert mask_ip("203.0.113.7") == "203.0.113.***"


def test_mask_ipv6_keeps_first_hextets() -> None:
    assert mask_ip("2001:db8:85a3:8d3:1319:8a2e:370:7348") == "2001:db8:85a3::***"


def test_mask_ip_unknown_inputs() -> None:
    assert mask_ip(None) == "Unknown"
    assert mask_ip("") == "Unknown"
    assert mask_ip("not-an-ip") == "Unknown"


def test_format_location_full() -> None:
    loc = Location(city="Bengaluru", region="Karnataka", country="India")
    assert format_location(loc) == "Bengaluru, Karnataka, India"


def test_format_location_partial() -> None:
    assert format_location(Location(country="India")) == "India"
    assert format_location(Location(region="California", country="US")) == "California, US"


def test_format_location_empty_and_none() -> None:
    assert format_location(Location()) == "Unknown"
    assert format_location(None) == "Unknown"


def test_lookup_ignores_private_and_loopback_ips() -> None:
    for ip in ("127.0.0.1", "192.168.1.10", "10.0.0.5", "::1", "fe80::1"):
        assert geoip.lookup(ip) is None


def test_lookup_without_db_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GEOIP_DB_PATH", "/nonexistent/GeoLite2-City.mmdb")
    assert geoip.lookup("8.8.8.8") is None
    assert GeoIP._load_error is not None


def test_lookup_empty_ip_returns_none() -> None:
    assert geoip.lookup(None) is None
    assert geoip.lookup("") is None
