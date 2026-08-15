"""Unit tests for the User-Agent parser."""

from __future__ import annotations

from identity.core.user_agent import DeviceInfo, parse_user_agent


def test_parse_chrome_on_windows() -> None:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    info = parse_user_agent(ua)

    assert info.browser == "Chrome"
    assert info.browser_version.startswith("126")
    assert info.os == "Windows"
    assert info.device_type == "Desktop"


def test_parse_safari_on_macos() -> None:
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    )
    info = parse_user_agent(ua)

    assert info.browser == "Safari"
    assert info.os == "Mac OS X"
    assert info.device_type == "Desktop"


def test_parse_mobile_chrome_android() -> None:
    ua = (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
    )
    info = parse_user_agent(ua)

    assert info.os == "Android"
    assert info.device_type == "Mobile"
    assert info.device.startswith("Pixel")
    assert "Android" in info.device


def test_desktop_chrome_gets_browser_device_label() -> None:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    info = parse_user_agent(ua)

    assert info.device_type == "Desktop"
    assert info.device.startswith("Chrome")
    assert "Windows" in info.device
    assert info.device != "Unknown"


def test_parse_ipad_is_tablet() -> None:
    ua = (
        "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    )
    info = parse_user_agent(ua)

    assert info.device_type == "Tablet"
    assert info.device.startswith("iPad")


def test_empty_ua_yields_unknown() -> None:
    info = parse_user_agent("")
    assert info == DeviceInfo()
    assert info.browser == "Unknown"
    assert info.os == "Unknown"
    assert info.device == "Unknown"
    assert info.browser_version == ""


def test_none_ua_yields_unknown() -> None:
    assert parse_user_agent(None) == DeviceInfo()


def test_bot_ua_marked_bot() -> None:
    info = parse_user_agent(
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    )
    assert info.device_type == "Bot"
    assert info.device == "Bot"
