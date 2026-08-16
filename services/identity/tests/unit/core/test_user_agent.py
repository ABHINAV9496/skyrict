"""Unit tests for the User-Agent parser (structured facts + Client Hints)."""

from __future__ import annotations

from identity.core.user_agent import (
    CLIENT_HINT_HEADERS,
    ClientHints,
    DeviceInfo,
    parse_client_hints,
    parse_user_agent,
)


def test_parse_chrome_on_windows() -> None:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    info = parse_user_agent(ua)

    assert info.browser == "Chrome"
    assert info.browser_version.startswith("126")
    assert info.os == "Windows"
    assert info.device_type == "desktop"
    assert info.browser_name == "Chrome"
    assert info.os_name == "Windows"
    assert info.device_family == "Windows PC"
    assert info.device_model is None


def test_windows_version_is_not_inferred_without_hints() -> None:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    info = parse_user_agent(ua)
    assert info.os_name == "Windows"
    assert info.os_version == ""


def test_windows_11_from_platform_version_hint() -> None:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    )
    hints = parse_client_hints({"Sec-CH-UA-Platform-Version": '"15.0.0"'})
    info = parse_user_agent(ua, hints=hints)

    assert info.os_name == "Windows"
    assert info.os_version == "11"


def test_windows_10_from_platform_version_hint() -> None:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    )
    hints = parse_client_hints({"Sec-CH-UA-Platform-Version": '"13.0.0"'})
    info = parse_user_agent(ua, hints=hints)

    assert info.os_version == "10"


def test_parse_safari_on_macos() -> None:
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    )
    info = parse_user_agent(ua)

    assert info.browser == "Safari"
    assert info.os == "macOS"
    assert info.os_name == "macOS"
    assert info.device_type == "desktop"
    assert info.device_family == "Mac"
    assert info.device_model is None


def test_parse_mobile_chrome_android() -> None:
    ua = (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
    )
    info = parse_user_agent(ua)

    assert info.os == "Android"
    assert info.device_type == "mobile"
    assert info.device.startswith("Pixel")
    assert "Android" in info.device
    assert info.browser_name == "Chrome"
    assert info.device_family == "Pixel 8"
    assert info.device_model == "Pixel 8"


def test_desktop_chrome_gets_browser_device_label() -> None:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    info = parse_user_agent(ua)

    assert info.device_type == "desktop"
    assert info.device.startswith("Chrome")
    assert "Windows" in info.device
    assert info.device != "Unknown"


def test_parse_ipad_is_tablet() -> None:
    ua = (
        "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    )
    info = parse_user_agent(ua)

    assert info.device_type == "tablet"
    assert info.device.startswith("iPad")
    assert info.device_family == "iPad"
    assert info.device_model is None


def test_parse_iphone_never_fabricates_a_model() -> None:
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
    )
    info = parse_user_agent(ua)

    assert info.device_type == "mobile"
    assert info.device_family == "iPhone"
    assert info.device_model is None


def test_empty_ua_yields_unknown() -> None:
    info = parse_user_agent("")
    assert info == DeviceInfo()
    assert info.browser == "Unknown"
    assert info.os == "Unknown"
    assert info.device == "Unknown"
    assert info.browser_version == ""
    assert info.device_type == "unknown"
    assert info.browser_name is None
    assert info.os_name is None
    assert info.device_family is None
    assert info.device_model is None


def test_none_ua_yields_unknown() -> None:
    assert parse_user_agent(None) == DeviceInfo()


def test_bot_ua_marked_bot() -> None:
    info = parse_user_agent(
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    )
    assert info.device_type == "bot"
    assert info.device == "Bot"
    assert info.device_family == "Bot"
    assert info.browser_name is None


def test_node_is_a_service_not_a_desktop() -> None:
    info = parse_user_agent("node")

    assert info.device_type == "service"
    assert info.device_family == "Node.js"
    assert info.browser_name is None
    assert info.os_name is None
    assert info.device == "Node.js"


def test_curl_is_a_service() -> None:
    info = parse_user_agent("curl/8.0")

    assert info.device_type == "service"
    assert info.device_family == "curl"
    assert info.browser_version == "8"


def test_python_requests_is_a_service() -> None:
    info = parse_user_agent("python-requests/2.31.0")

    assert info.device_type == "service"
    assert info.device_family == "Python Requests"
    assert info.browser_version == "2"


def test_garbage_ua_is_unknown_not_desktop() -> None:
    info = parse_user_agent("not a real user agent at all")

    assert info.device_type == "unknown"
    assert info.device == "Unknown"
    assert info.browser_name is None


def test_browser_ua_never_marked_service() -> None:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    info = parse_user_agent(ua)
    assert info.device_type == "desktop"


def test_client_hints_parsing() -> None:
    hints = parse_client_hints(
        {
            "Sec-CH-UA": '"Chromium";v="151", "Google Chrome";v="151"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-CH-UA-Platform-Version": '"15.0.0"',
            "Sec-CH-UA-Model": '""',
        }
    )
    assert hints.brands == (("Chromium", "151"), ("Google Chrome", "151"))
    assert hints.mobile is False
    assert hints.platform == "Windows"
    assert hints.platform_version == "15.0.0"
    assert hints.model is None


def test_client_hints_parse_escaped_values() -> None:
    hints = parse_client_hints({"sec-ch-ua-platform-version": '\\"15.0.0\\"'})
    assert hints.platform_version == "15.0.0"


def test_client_hints_supplement_unknown_os() -> None:
    hints = parse_client_hints(
        {
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-CH-UA-Platform-Version": '"15.0.0"',
        }
    )
    info = parse_user_agent("Mozilla/5.0", hints=hints)
    assert info.os_name == "Windows"
    assert info.os_version == "11"
    assert info.device_type == "desktop"


def test_client_hint_headers_are_lowercased_stable() -> None:
    assert CLIENT_HINT_HEADERS == (
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "sec-ch-ua-platform-version",
        "sec-ch-ua-model",
    )


def test_client_hints_empty_input() -> None:
    assert parse_client_hints(None) == ClientHints()
    assert parse_client_hints({}) == ClientHints()
