"""Unit tests for the text-CAPTCHA generator and its Redis store."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from identity.features.auth.captcha import captcha as captcha_module
from identity.features.auth.captcha.captcha import (
    CAPTCHA_ALPHABET,
    CAPTCHA_FONT_SIZE,
    CAPTCHA_HEIGHT,
    CAPTCHA_LENGTH,
    CAPTCHA_WIDTH,
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

    @pytest.mark.parametrize("style", STYLES)
    def test_all_styles_are_grayscale_with_expected_size(self, style: str) -> None:
        captcha = generate_captcha(style=style)
        image = Image.open(io.BytesIO(captcha.image_png)).convert("RGB")
        assert image.size == (CAPTCHA_WIDTH, CAPTCHA_HEIGHT)
        pixels = list(image.getdata())
        assert all(r == g == b for r, g, b in pixels), f"{style} contains color pixels"

    def test_render_varies_between_challenges_of_same_style(self) -> None:
        assert generate_captcha(style="classic").image_png != generate_captcha(style="classic").image_png

    def test_background_is_not_blank(self) -> None:
        captcha = generate_captcha(style="classic")
        image = Image.open(io.BytesIO(captcha.image_png)).convert("L")
        assert len(set(image.getdata())) >= 5

    def test_font_manager_falls_back_without_bundled_fonts(self, tmp_path) -> None:
        manager = FontManager(fonts_dir=tmp_path)
        assert manager.pick() is not None

    def test_font_coverage_probe_rejects_missing_glyphs(self) -> None:
        class EmptyFont:
            def getbbox(self, ch: str) -> tuple[int, int, int, int]:
                return (0, 0, 0, 0)

        class FullFont:
            def getbbox(self, ch: str) -> tuple[int, int, int, int]:
                return (0, 0, 12, 12)

        assert FontManager._covers_alphabet(EmptyFont()) is False
        assert FontManager._covers_alphabet(FullFont()) is True

    def test_all_bundled_fonts_cover_the_alphabet(self) -> None:
        fonts_dir = Path(captcha_module.__file__).parent / "fonts"
        manager = FontManager(fonts_dir=fonts_dir)
        fonts = manager._load(CAPTCHA_FONT_SIZE)
        assert len(fonts) >= 15
        assert all(FontManager._covers_alphabet(font) for font in fonts)


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
