"""Unit tests for the text-CAPTCHA generator and its Redis store."""

from __future__ import annotations

import pytest

from identity.features.auth.captcha.captcha import (
    CAPTCHA_ALPHABET,
    CAPTCHA_LENGTH,
    FontManager,
    generate_captcha,
    hash_answer,
)
from identity.features.auth.captcha.captcha_store import CaptchaStore

STYLES = ("classic", "outline", "bullet", "chalk", "neon")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class FakeRedis:
    """In-memory Redis double with the subset of commands the store uses."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self._store[key] = value
        if ex is not None:
            self._ttls[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def incr(self, key: str) -> int:
        count = int(self._store.get(key, "0")) + 1
        self._store[key] = str(count)
        return count

    async def ttl(self, key: str) -> int:
        return self._ttls.get(key, -1)

    async def expire(self, key: str, seconds: int) -> bool:
        self._ttls[key] = seconds
        return True

    async def delete(self, *keys: str) -> int:
        for key in keys:
            self._store.pop(key, None)
            self._ttls.pop(key, None)
        return 1


class TestGenerator:
    def test_generate_returns_png_and_valid_text(self) -> None:
        captcha = generate_captcha()
        assert captcha.image_png[:8] == PNG_MAGIC
        assert len(captcha.text) == CAPTCHA_LENGTH
        assert all(ch in CAPTCHA_ALPHABET for ch in captcha.text)
        assert captcha.style in STYLES

    @pytest.mark.parametrize("style", STYLES)
    def test_all_styles_render(self, style: str) -> None:
        captcha = generate_captcha(style=style)
        assert captcha.style == style
        assert captcha.image_png[:8] == PNG_MAGIC

    def test_hash_answer_normalizes_case_and_whitespace(self) -> None:
        assert hash_answer(" abc34 ") == hash_answer("ABC34")

    def test_font_manager_falls_back_without_bundled_fonts(self, tmp_path) -> None:
        manager = FontManager(fonts_dir=tmp_path)
        assert manager.pick() is not None


class TestStore:
    def _store(self, *, max_attempts: int = 5, ttl: int = 60) -> tuple[CaptchaStore, FakeRedis]:
        client = FakeRedis()
        return CaptchaStore(client=client, ttl_seconds=ttl, max_attempts=max_attempts), client

    async def test_issue_stores_only_the_digest_with_a_ttl(self) -> None:
        store, client = self._store()
        captcha_id = await store.issue("ABC34")
        assert captcha_id
        stored = client._store[f"signup_captcha:{captcha_id}"]
        assert "ABC34" not in stored
        assert stored == hash_answer("ABC34")
        assert client._ttls[f"signup_captcha:{captcha_id}"] == 60

    async def test_correct_answer_succeeds_then_challenge_is_single_use(self) -> None:
        store, _ = self._store()
        captcha_id = await store.issue("ABC34")
        assert await store.verify(captcha_id, "abc34") is True
        assert await store.verify(captcha_id, "ABC34") is False

    async def test_wrong_answer_consumes_an_attempt(self) -> None:
        store, _ = self._store()
        captcha_id = await store.issue("ABC34")
        assert await store.verify(captcha_id, "WRONG") is False
        assert await store.verify(captcha_id, "ABC34") is True

    async def test_attempt_budget_exhaustion_revokes_challenge(self) -> None:
        store, _ = self._store(max_attempts=2)
        captcha_id = await store.issue("ABC34")
        assert await store.verify(captcha_id, "X") is False
        assert await store.verify(captcha_id, "X") is False
        assert await store.verify(captcha_id, "ABC34") is False

    async def test_unknown_challenge_never_succeeds(self) -> None:
        store, _ = self._store()
        assert await store.verify("missing", "ABC34") is False
