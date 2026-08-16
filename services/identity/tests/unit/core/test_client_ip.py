"""Unit tests for trusted-proxy client IP extraction."""

from __future__ import annotations

import types
from typing import TYPE_CHECKING

from identity.core.client_ip import _is_trusted, _normalize, client_ip
from identity.core.config import settings

if TYPE_CHECKING:
    import pytest


class _Request:
    """Minimal stand-in exposing the two attributes ``client_ip`` touches."""

    def __init__(
        self,
        *,
        client_host: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.client = types.SimpleNamespace(host=client_host) if client_host is not None else None
        self.headers = headers or {}


def _trust_proxies(monkeypatch: pytest.MonkeyPatch, *entries: str) -> None:
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", list(entries))


def test_no_trusted_proxies_returns_peer() -> None:
    request = _Request(client_host="172.20.0.1")
    assert client_ip(request) == "172.20.0.1"


def test_no_trusted_proxies_ignores_spoofed_xff(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch)  # explicit empty list
    request = _Request(
        client_host="172.20.0.1",
        headers={"x-forwarded-for": "8.8.8.8"},
    )
    assert client_ip(request) == "172.20.0.1"


def test_no_trusted_proxies_ignores_trusted_looking_xff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trust_proxies(monkeypatch)
    request = _Request(
        client_host="203.0.113.9",
        headers={"x-forwarded-for": "6.6.6.6, 10.0.0.1"},
    )
    assert client_ip(request) == "203.0.113.9"


def test_untrusted_peer_never_uses_forwarded_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _trust_proxies(monkeypatch, "10.0.0.0/8")
    request = _Request(
        client_host="203.0.113.9",
        headers={"x-forwarded-for": "6.6.6.6"},
    )
    assert client_ip(request) == "203.0.113.9"


def test_trusted_peer_reads_rightmost_ff_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch, "10.0.0.0/8")
    request = _Request(
        client_host="10.0.0.1",
        headers={"x-forwarded-for": "203.0.113.7"},
    )
    assert client_ip(request) == "203.0.113.7"


def test_chain_skips_trusted_hops(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch, "10.0.0.0/8")
    request = _Request(
        client_host="10.0.0.1",
        headers={"x-forwarded-for": "203.0.113.7, 10.0.0.5, 10.0.0.1"},
    )
    assert client_ip(request) == "203.0.113.7"


def test_spoofed_leading_entries_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch, "10.0.0.0/8")
    request = _Request(
        client_host="10.0.0.1",
        headers={"x-forwarded-for": "1.2.3.4, 6.6.6.6, 10.0.0.1"},
    )
    assert client_ip(request) == "6.6.6.6"


def test_entirely_trusted_chain_falls_back_to_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch, "10.0.0.0/8")
    request = _Request(
        client_host="10.0.0.1",
        headers={"x-forwarded-for": "10.0.0.9, 10.0.0.1"},
    )
    assert client_ip(request) == "10.0.0.1"


def test_trusted_peer_without_xff_returns_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch, "10.0.0.1")
    request = _Request(client_host="10.0.0.1")
    assert client_ip(request) == "10.0.0.1"


def test_ipv6_chain_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch, "2001:db8::/64")
    request = _Request(
        client_host="2001:db8::1",
        headers={"x-forwarded-for": "2001:db9::5"},
    )
    assert client_ip(request) == "2001:db9::5"


def test_malformed_chain_entries_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch, "10.0.0.0/8")
    request = _Request(
        client_host="10.0.0.1",
        headers={"x-forwarded-for": "not-an-ip, 198.51.100.3, 10.0.0.1"},
    )
    assert client_ip(request) == "198.51.100.3"


def test_no_client_info_yields_unknown() -> None:
    assert client_ip(_Request()) == "unknown"


def test_non_ip_peer_passes_through() -> None:
    request = _Request(client_host="testclient")
    assert client_ip(request) == "testclient"


def test_ipv4_mapped_peer_matches_ipv4_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch, "127.0.0.0/8")
    request = _Request(
        client_host="::ffff:127.0.0.1",
        headers={"x-forwarded-for": "203.0.113.20"},
    )
    assert client_ip(request) == "203.0.113.20"


def test_normalize_unwraps_ipv4_mapped_ipv6() -> None:
    assert _normalize("::ffff:1.2.3.4") == "1.2.3.4"
    assert _normalize("::1") == "::1"
    assert _normalize(" 10.0.0.5 ") == "10.0.0.5"
    assert _normalize("testclient") == "testclient"


def test_is_trusted_respects_networks(monkeypatch: pytest.MonkeyPatch) -> None:
    _trust_proxies(monkeypatch, "10.0.0.0/8", "192.0.2.10")
    assert _is_trusted("10.1.2.3")
    assert _is_trusted("192.0.2.10")
    assert not _is_trusted("192.0.2.11")
    assert not _is_trusted("203.0.113.1")
    assert not _is_trusted("testclient")
    assert not _is_trusted(None)
