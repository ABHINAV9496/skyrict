"""Server-side text CAPTCHA generation — text, styles, noise, and PNG export.

Pipeline (one instance of each component, per the design):

    RandomTextGenerator -> BaseRenderer -> StyleRenderer -> NoiseEngine
        -> PNG Export

Everything renders with Pillow. Challenge text uses ``secrets`` (it is the
secret that gates the password step); visual distortion uses ``random`` (it
is purely cosmetic). The plaintext answer never leaves this module except
through :func:`generate_captcha`, whose caller hashes it before storage —
the store never sees the raw text.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import random
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

CAPTCHA_ALPHABET: Final[str] = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CAPTCHA_LENGTH: Final[int] = 5
CAPTCHA_WIDTH: Final[int] = 240
CAPTCHA_HEIGHT: Final[int] = 64
CAPTCHA_FONT_SIZE: Final[int] = 42

_STYLE_NAMES: Final[tuple[str, ...]] = ("classic", "outline", "bullet", "chalk", "neon")

_STYLES: Final[dict[str, dict[str, object]]] = {
    "classic": {
        "bg": (247, 247, 245),
        "fg": (38, 38, 38),
        "stroke": 0,
        "stroke_fill": None,
        "angle_min": -14,
        "angle_max": 14,
    },
    "outline": {
        "bg": (246, 246, 246),
        "fg": (255, 255, 255),
        "stroke": 2,
        "stroke_fill": (35, 35, 35),
        "angle_min": -12,
        "angle_max": 12,
    },
    "bullet": {
        "bg": (250, 250, 250),
        "fg": (30, 30, 30),
        "stroke": 0,
        "stroke_fill": None,
        "angle_min": -10,
        "angle_max": 10,
    },
    "chalk": {
        "bg": (34, 40, 34),
        "fg": (238, 238, 228),
        "stroke": 0,
        "stroke_fill": None,
        "angle_min": -8,
        "angle_max": 8,
    },
    "neon": {
        "bg": (10, 10, 18),
        "fg": (80, 255, 220),
        "stroke": 0,
        "stroke_fill": None,
        "angle_min": -12,
        "angle_max": 12,
    },
}

_BULLET_COLORS: Final[tuple[tuple[int, int, int], ...]] = (
    (255, 200, 200),
    (200, 230, 255),
    (220, 255, 210),
    (255, 240, 200),
    (235, 215, 255),
)


def hash_answer(text: str) -> str:
    """Return the SHA-256 digest of a normalized (uppercased) answer."""
    return hashlib.sha256(text.strip().upper().encode("utf-8")).hexdigest()


def png_data_uri(image_png: bytes) -> str:
    """Encode PNG bytes as a base64 data URI for direct ``<img src>`` use."""
    encoded = base64.b64encode(image_png).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@dataclass(frozen=True)
class RenderedCaptcha:
    """A generated challenge — the answer and its PNG encoding."""

    text: str
    image_png: bytes
    style: str


class FontManager:
    """Loads the bundled TrueType fonts once and caches them for the process.

    Font files ship inside this package (``fonts/*.ttf``) so they travel with
    the source and the wheel. Fonts are loaded lazily on first use — never
    re-read from disk per request.
    """

    def __init__(
        self,
        fonts_dir: Path | None = None,
        *,
        size: int = CAPTCHA_FONT_SIZE,
    ) -> None:
        self._fonts_dir = fonts_dir if fonts_dir is not None else Path(__file__).parent / "fonts"
        self._size = size
        self._fonts: tuple[ImageFont.FreeTypeFont, ...] = ()

    def pick(self) -> ImageFont.FreeTypeFont:
        """Return a random cached font, loading the set on first call."""
        if not self._fonts:
            paths = sorted(self._fonts_dir.glob("*.ttf"))
            if paths:
                self._fonts = tuple(
                    ImageFont.truetype(str(path), size=self._size) for path in paths
                )
            else:
                # Last-resort fallback keeps the endpoint alive even when no
                # font shipped with the deployment.
                self._fonts = (self._default_font(),)
        return secrets.choice(self._fonts)

    @staticmethod
    def _default_font() -> ImageFont.FreeTypeFont:
        try:
            return ImageFont.load_default(size=40)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return ImageFont.load_default()  # type: ignore[return-value]


class NoiseEngine:
    """Visual noise layered on top of the rendered text (anti-OCR, human-OK)."""

    def add_lines(self, image: Image.Image, *, count: int, color: tuple[int, int, int]) -> None:
        draw = ImageDraw.Draw(image)
        for _ in range(count):
            draw.line(
                (
                    random.randint(0, image.width),
                    random.randint(0, image.height),
                    random.randint(0, image.width),
                    random.randint(0, image.height),
                ),
                fill=color,
                width=1,
            )

    def add_dots(
        self,
        image: Image.Image,
        *,
        count: int,
        color: tuple[int, int, int],
        radius: int = 1,
    ) -> None:
        draw = ImageDraw.Draw(image)
        for _ in range(count):
            x = random.randint(0, image.width)
            y = random.randint(0, image.height)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

    def add_grain(self, image: Image.Image, *, sigma: int = 12, alpha: float = 0.2) -> Image.Image:
        noise = Image.effect_noise(image.size, sigma).convert("RGB")
        return Image.blend(image, noise, alpha)

    def add_wave(
        self,
        image: Image.Image,
        *,
        amplitude: int = 2,
        period: int = 36,
        phase: float | None = None,
    ) -> None:
        phase = random.uniform(0, 2 * math.pi) if phase is None else phase
        for x in range(image.width):
            dy = int(amplitude * math.sin(2 * math.pi * x / period + phase))
            if dy == 0:
                continue
            column = image.crop((x, 0, x + 1, image.height))
            image.paste(column, (x, max(0, dy)))

    def add_speckles(
        self,
        image: Image.Image,
        *,
        count: int,
        color: tuple[int, int, int],
    ) -> None:
        draw = ImageDraw.Draw(image)
        for _ in range(count):
            x = random.randint(0, image.width)
            y = random.randint(0, image.height)
            length = random.randint(3, 9)
            angle = random.uniform(0, 2 * math.pi)
            dx = math.cos(angle) * length
            dy = math.sin(angle) * length
            draw.line((x, y, x + dx, y + dy), fill=color, width=1)


class RandomTextGenerator:
    """Cryptographically random CAPTCHA text from the confusion-free alphabet."""

    def generate(self) -> str:
        return "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(CAPTCHA_LENGTH))


def _render_character(
    ch: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: tuple[int, int, int],
    stroke_width: int,
    stroke_fill: tuple[int, int, int] | None,
    angle: float,
) -> Image.Image:
    left, top, right, bottom = font.getbbox(ch)
    pad = stroke_width * 2 + 10
    layer = Image.new("RGBA", (right - left + pad, bottom - top + pad), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.text(
        (pad // 2 - left, pad // 2 - top),
        ch,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
    return layer.rotate(angle, resample=Image.BICUBIC, expand=True)


def _draw_bullet(image: Image.Image, index: int, char_slot: int) -> None:
    color = secrets.choice(_BULLET_COLORS)
    radius = random.randint(11, 15)
    cx = index * char_slot + char_slot // 2
    cy = CAPTCHA_HEIGHT // 2 + random.randint(-5, 5)
    ImageDraw.Draw(image).ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)


font_manager = FontManager()


def _render(text: str, style: str) -> Image.Image:
    cfg = _STYLES[style]
    image = Image.new("RGB", (CAPTCHA_WIDTH, CAPTCHA_HEIGHT), cfg["bg"])
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    font = font_manager.pick()
    char_slot = CAPTCHA_WIDTH // len(text)
    for index, ch in enumerate(text):
        if style == "bullet":
            _draw_bullet(image, index, char_slot)
        char_image = _render_character(
            ch,
            font,
            fill=cfg["fg"],
            stroke_width=cfg["stroke"],
            stroke_fill=cfg["stroke_fill"],
            angle=random.uniform(cfg["angle_min"], cfg["angle_max"]),
        )
        upper = max(2, CAPTCHA_HEIGHT - char_image.height - 2)
        y = random.randint(2, upper)
        x = index * char_slot + (char_slot - char_image.width) // 2 + random.randint(-3, 3)
        layer.alpha_composite(char_image, (x, y))
    image.paste(layer, (0, 0), layer)
    return _apply_noise(image, style)


noise_engine = NoiseEngine()


def _apply_noise(image: Image.Image, style: str) -> Image.Image:
    noise = noise_engine
    if style == "classic":
        noise.add_lines(image, count=3, color=(110, 110, 110))
        noise.add_dots(image, count=30, color=(150, 150, 150))
        noise.add_wave(image, amplitude=2)
        return image
    if style == "outline":
        noise.add_lines(image, count=2, color=(205, 205, 205))
        noise.add_dots(image, count=18, color=(215, 215, 215))
        return image
    if style == "bullet":
        noise.add_speckles(image, count=14, color=(80, 80, 80))
        noise.add_dots(image, count=14, color=(190, 190, 190))
        return image
    if style == "chalk":
        image = noise.add_grain(image, sigma=12, alpha=0.2)
        noise.add_lines(image, count=4, color=(95, 115, 100))
        noise.add_dots(image, count=50, color=(130, 150, 130))
        return image
    glow = image.filter(ImageFilter.GaussianBlur(radius=3))
    image = ImageChops.screen(image, glow)
    noise.add_speckles(image, count=10, color=(90, 90, 140))
    noise.add_dots(image, count=12, color=(120, 120, 180))
    return image


text_generator = RandomTextGenerator()


def generate_captcha(style: str | None = None) -> RenderedCaptcha:
    """Generate a CAPTCHA — the plaintext answer plus its PNG bytes.

    ``style`` selects one of the five looks; ``None`` picks a random one per
    challenge. The answer is returned to the caller ONLY so it can be stored
    as a digest; it must never be sent to the client.
    """
    chosen = style if style in _STYLE_NAMES else secrets.choice(_STYLE_NAMES)
    text = text_generator.generate()
    image = _render(text, chosen)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return RenderedCaptcha(text=text, image_png=buffer.getvalue(), style=chosen)
