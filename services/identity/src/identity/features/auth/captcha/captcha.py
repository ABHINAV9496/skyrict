"""Server-side text CAPTCHA generation — text, styles, noise, and PNG export.

Pipeline (one instance of each component, per the design):

    RandomTextGenerator -> BaseRenderer -> StyleRenderer -> NoiseEngine
        -> PNG Export

Everything renders with Pillow. Challenge text uses ``secrets`` (it is the
secret that gates the password step); visual distortion uses ``random`` (it
is purely cosmetic). The plaintext answer never leaves this module except
through :func:`generate_captcha`, whose caller hashes it before storage —
the store never sees the raw text.

The renderer recreates the philosophy of classic enterprise CAPTCHA libraries
(BotDetect / Yahoo / phpBB): pure black & white, high contrast, old-school
printer/scanner texture, and retro OCR-style typography.

Segmentation resistance comes from the *algorithm*, not from unreadable text:

* every character is rendered independently — random font, stroke, shear,
  perspective, scale, rotation, baseline and kerning per glyph;
* the ``overlap`` layout advances glyphs past each other so their separation
  outlines (in the background color) intersect without the glyph bodies
  fusing;
* guide lines are drawn *through* the text, and some characters carry broken
  strokes (internal cuts), top-edge clipping and partial mask bands;
* the background is a structured tiled pattern (hatch / grid / plus / scan)
  plus layered artifacts — dust, dashes, ink blobs, edge fragments, paper
  grain — drawn both behind and above the characters.

All distortion is lightweight (per-glyph perspective and a small local wave,
plus a subtle final skew) — no giant warps that destroy the glyphs. Output is
strictly grayscale. The single rendering pipeline is reused by every style
preset.
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
from typing import Final, Literal, NotRequired, TypedDict, cast

from PIL import Image, ImageDraw, ImageFont

CAPTCHA_ALPHABET: Final[str] = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CAPTCHA_LENGTH: Final[int] = 5
CAPTCHA_WIDTH: Final[int] = 300
CAPTCHA_HEIGHT: Final[int] = 76
CAPTCHA_FONT_SIZE: Final[int] = 54

_STYLE_NAMES: Final[tuple[str, ...]] = ("classic", "outline", "bullet", "chalk", "neon")


# One reusable pipeline; each preset tweaks how the same building blocks are
# combined. All palettes are pure grays (R == G == B). ``layout`` is either
# "spaced" (measured gap, no contact) or "overlap" (glyphs advance past each
# other; the background-color stroke keeps them distinct). ``cuts_chance`` is
# the per-glyph probability of broken strokes; ``local_wave`` enables the
# small per-glyph sine warp.
class _StyleConfig(TypedDict):
    bg: tuple[int, int, int]
    fg: tuple[int, int, int]
    stroke: int
    stroke_fill: tuple[int, int, int] | None
    angle_min: int
    angle_max: int
    layout: Literal["spaced", "overlap"]
    gap_min: NotRequired[int]
    gap_max: NotRequired[int]
    overlap_min: NotRequired[int]
    overlap_max: NotRequired[int]
    jitter: int
    background: Literal["hatch", "grid", "plus", "scan"]
    guide_lines: int
    mask_band: bool
    cuts_chance: float
    local_wave: bool
    halo: bool
    jail_bars: bool
    ink_blobs: bool


_STYLES: Final[dict[str, _StyleConfig]] = {
    "classic": {  # Wave — hatch paper, light warp, thin guide lines
        "bg": (247, 247, 245),
        "fg": (22, 22, 22),
        "stroke": 0,
        "stroke_fill": None,
        "angle_min": -6,
        "angle_max": 6,
        "layout": "spaced",
        "gap_min": 2,
        "gap_max": 4,
        "jitter": 2,
        "background": "hatch",
        "guide_lines": 2,
        "mask_band": False,
        "cuts_chance": 0.08,
        "local_wave": True,
        "halo": False,
        "jail_bars": False,
        "ink_blobs": False,
    },
    "outline": {  # Halo — outlined glyphs on a clean white halo over a grid
        "bg": (255, 255, 255),
        "fg": (255, 255, 255),
        "stroke": 2,
        "stroke_fill": (20, 20, 20),
        "angle_min": -5,
        "angle_max": 5,
        "layout": "spaced",
        "gap_min": 2,
        "gap_max": 4,
        "jitter": 2,
        "background": "grid",
        "guide_lines": 1,
        "mask_band": False,
        "cuts_chance": 0.05,
        "local_wave": False,
        "halo": True,
        "jail_bars": False,
        "ink_blobs": False,
    },
    "bullet": {  # Spaced glyphs, faint plus background
        "bg": (255, 255, 255),
        "fg": (15, 15, 15),
        "stroke": 0,
        "stroke_fill": None,
        "angle_min": -6,
        "angle_max": 6,
        "layout": "spaced",
        "gap_min": 2,
        "gap_max": 4,
        "jitter": 2,
        "background": "plus",
        "guide_lines": 1,
        "mask_band": False,
        "cuts_chance": 0.08,
        "local_wave": False,
        "halo": False,
        "jail_bars": False,
        "ink_blobs": True,
    },
    "chalk": {  # Scan paper, single thin guide line
        "bg": (225, 225, 225),
        "fg": (15, 15, 15),
        "stroke": 0,
        "stroke_fill": None,
        "angle_min": -5,
        "angle_max": 5,
        "layout": "spaced",
        "gap_min": 2,
        "gap_max": 4,
        "jitter": 2,
        "background": "scan",
        "guide_lines": 1,
        "mask_band": False,
        "cuts_chance": 0.08,
        "local_wave": False,
        "halo": False,
        "jail_bars": False,
        "ink_blobs": True,
    },
    "neon": {  # Inverted — bright glyphs on dark pixel noise
        "bg": (12, 12, 12),
        "fg": (235, 235, 235),
        "stroke": 0,
        "stroke_fill": None,
        "angle_min": -6,
        "angle_max": 6,
        "layout": "spaced",
        "gap_min": 2,
        "gap_max": 4,
        "jitter": 2,
        "background": "grid",
        "guide_lines": 1,
        "mask_band": False,
        "cuts_chance": 0.08,
        "local_wave": True,
        "halo": False,
        "jail_bars": False,
        "ink_blobs": False,
    },
}

# Bundled fonts restricted to simple, high-weight faces: bold sans/serif,
# monospace, stencil, and heavy display fonts. Script, engraved, distressed,
# and decorative faces are excluded — they read as damaged glyphs rather than
# OCR-averse type, and hurt human legibility (the real requirement is that a
# person can reliably transcribe the code).
_EXCLUDED_FONTS: Final[frozenset[str]] = frozenset(
    {
        "OLDENGL.TTF",  # blackletter — unreadable
        "MATURASC.TTF",  # matura script — cursive
        "VINERITC.TTF",  # cursive vine
        "CHILLER.TTF",  # distressed
        "HATTEN.TTF",  # distressed
        "VLADIMIR.TTF",  # script cursive
        "BROADW.TTF",  # decorative
        "NIAGENG.TTF",  # engraved / thin
        "PAPYRUS.TTF",  # decorative
    }
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
    re-read from disk per request. Each font must cover the whole challenge
    alphabet; fonts with missing glyphs (e.g. scripts without digits) are
    skipped so a random pick can never produce a "tofu" box.
    """

    def __init__(
        self,
        fonts_dir: Path | None = None,
        *,
        size: int = CAPTCHA_FONT_SIZE,
    ) -> None:
        self._fonts_dir = fonts_dir if fonts_dir is not None else Path(__file__).parent / "fonts"
        self._size = size
        self._fonts_by_size: dict[int, tuple[ImageFont.FreeTypeFont, ...]] = {}

    def pick(self, size: int | None = None) -> ImageFont.FreeTypeFont:
        """Return a random cached font at ``size`` (defaults to the manager size)."""
        font_size = size if size is not None else self._size
        fonts = self._fonts_by_size.get(font_size)
        if fonts is None:
            fonts = self._load(font_size)
            self._fonts_by_size[font_size] = fonts
        return secrets.choice(fonts)

    def _load(self, size: int) -> tuple[ImageFont.FreeTypeFont, ...]:
        fonts: list[ImageFont.FreeTypeFont] = []
        for path in sorted(p for p in self._fonts_dir.iterdir() if p.suffix.lower() == ".ttf"):
            if path.name.upper() in _EXCLUDED_FONTS:
                continue
            try:
                font = ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
            if self._covers_alphabet(font):
                fonts.append(font)
        if fonts:
            return tuple(fonts)
        # Last-resort fallback keeps the endpoint alive even when no font
        # shipped with the deployment.
        return (self._default_font(size),)

    @staticmethod
    def _covers_alphabet(font: ImageFont.FreeTypeFont) -> bool:
        for ch in CAPTCHA_ALPHABET:
            left, top, right, bottom = font.getbbox(ch)
            if right <= left or bottom <= top:
                return False
        return True

    @staticmethod
    def _default_font(size: int = CAPTCHA_FONT_SIZE) -> ImageFont.FreeTypeFont:
        try:
            return cast("ImageFont.FreeTypeFont", ImageFont.load_default(size=size))
        except (TypeError, ValueError):
            return cast("ImageFont.FreeTypeFont", ImageFont.load_default())


class NoiseEngine:
    """Reusable layered noise primitives — drawn behind and above the text."""

    def add_lines(
        self,
        image: Image.Image,
        *,
        count: int,
        color: tuple[int, int, int],
        width: int = 1,
    ) -> None:
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
                width=width,
            )

    def add_broken_lines(
        self,
        image: Image.Image,
        *,
        count: int,
        color: tuple[int, int, int],
        width: int = 1,
    ) -> None:
        """Thin lines split into 2-3 dashed segments with gaps (scanner streaks)."""
        draw = ImageDraw.Draw(image)
        for _ in range(count):
            x1 = random.randint(0, image.width)
            y1 = random.randint(0, image.height)
            x2 = random.randint(0, image.width)
            y2 = random.randint(0, image.height)
            for _ in range(random.randint(2, 3)):
                t0 = random.uniform(0.0, 0.4)
                t1 = t0 + random.uniform(0.25, 0.45)
                sx = x1 + (x2 - x1) * t0
                sy = y1 + (y2 - y1) * t0
                ex = x1 + (x2 - x1) * t1
                ey = y1 + (y2 - y1) * t1
                draw.line((sx, sy, ex, ey), fill=color, width=width)

    def add_guide_lines(
        self,
        image: Image.Image,
        *,
        count: int,
        color: tuple[int, int, int],
        width: int = 1,
    ) -> None:
        """Full-width lines crossing the text area (BotDetect signature)."""
        draw = ImageDraw.Draw(image)
        for _ in range(count):
            y = random.randint(8, image.height - 8)
            x0 = random.randint(-12, 4)
            x1 = image.width + random.randint(-4, 12)
            draw.line((x0, y, x1, y + random.randint(-4, 4)), fill=color, width=width)

    def add_dashes(
        self,
        image: Image.Image,
        *,
        count: int,
        color: tuple[int, int, int],
        width: int = 1,
    ) -> None:
        """Short mostly-horizontal scratches (printer artifacts)."""
        draw = ImageDraw.Draw(image)
        for _ in range(count):
            x = random.randint(0, image.width)
            y = random.randint(0, image.height)
            length = random.randint(4, 14)
            angle = random.uniform(-0.35, 0.35)
            dx = math.cos(angle) * length
            dy = math.sin(angle) * length
            draw.line((x, y, x + dx, y + dy), fill=color, width=width)

    def add_edge_fragments(
        self,
        image: Image.Image,
        *,
        count: int,
        color: tuple[int, int, int],
        width: int = 1,
    ) -> None:
        """Short strokes hugging the borders — photocopy edge artifacts."""
        draw = ImageDraw.Draw(image)
        for _ in range(count):
            edge = random.choice(("top", "bottom", "left", "right"))
            length = random.randint(6, 18)
            if edge == "top":
                x = random.randint(0, image.width)
                draw.line((x, 0, x + random.randint(-2, 2), length), fill=color, width=width)
            elif edge == "bottom":
                x = random.randint(0, image.width)
                y = image.height - 1
                draw.line((x, y, x + random.randint(-2, 2), y - length), fill=color, width=width)
            elif edge == "left":
                y = random.randint(0, image.height)
                draw.line((0, y, length, y + random.randint(-2, 2)), fill=color, width=width)
            else:
                y = random.randint(0, image.height)
                x = image.width - 1
                draw.line((x, y, x - length, y + random.randint(-2, 2)), fill=color, width=width)

    def add_ink_blobs(
        self,
        image: Image.Image,
        *,
        count: int,
        color: tuple[int, int, int],
    ) -> None:
        """Small solid blotches — photocopy toner artifacts."""
        draw = ImageDraw.Draw(image)
        for _ in range(count):
            x = random.randint(0, image.width)
            y = random.randint(0, image.height)
            rx = random.randint(2, 5)
            ry = random.randint(2, 4)
            draw.ellipse((x - rx, y - ry, x + rx, y + ry), fill=color)

    def add_dust(
        self,
        image: Image.Image,
        *,
        count: int,
        color: tuple[int, int, int],
    ) -> None:
        draw = ImageDraw.Draw(image)
        for _ in range(count):
            draw.point(
                (random.randint(0, image.width - 1), random.randint(0, image.height - 1)),
                fill=color,
            )

    def add_scanlines(
        self,
        image: Image.Image,
        *,
        color: tuple[int, int, int],
        spacing: int,
        width: int = 1,
    ) -> None:
        draw = ImageDraw.Draw(image)
        for y in range(spacing, image.height, spacing):
            draw.line((0, y, image.width, y), fill=color, width=width)

    def add_grain(self, image: Image.Image, *, sigma: int = 10, alpha: float = 0.08) -> Image.Image:
        noise = Image.effect_noise(image.size, sigma).convert("RGB")
        return Image.blend(image, noise, alpha)


class RandomTextGenerator:
    """Cryptographically random CAPTCHA text from the confusion-free alphabet."""

    def generate(self) -> str:
        return "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(CAPTCHA_LENGTH))


def _glyph_perspective(layer: Image.Image, *, spread: int = 1) -> Image.Image:
    """Small per-character perspective: corners wander a few pixels."""
    width, height = layer.size
    dst = (
        random.randint(0, spread),
        random.randint(0, spread),
        width - random.randint(0, spread),
        random.randint(0, spread),
        width - random.randint(0, spread),
        height - random.randint(0, spread),
        random.randint(0, spread),
        height - random.randint(0, spread),
    )
    return layer.transform(layer.size, Image.QUAD, dst, resample=Image.BICUBIC)


def _apply_cuts(layer: Image.Image, cuts: list[tuple[int, int, int, int]]) -> None:
    """Erase short segments across a glyph — broken strokes / internal cuts."""
    if not cuts:
        return
    mask = Image.new("L", layer.size, 0)
    draw = ImageDraw.Draw(mask)
    for x1, y1, x2, y2 in cuts:
        draw.line((x1, y1, x2, y2), fill=255, width=2)
    layer.paste(Image.new("RGBA", layer.size, (0, 0, 0, 0)), (0, 0), mask)


def _gen_cuts(width: int, height: int) -> list[tuple[int, int, int, int]]:
    cuts: list[tuple[int, int, int, int]] = []
    for _ in range(random.randint(1, 2)):
        if random.random() < 0.6:  # horizontal cut
            y = random.randint(int(height * 0.3), int(height * 0.7))
            x0 = random.randint(2, max(3, width // 3))
            span = random.randint(max(3, width // 4), max(4, width - x0))
            cuts.append((x0, y, min(width - 2, x0 + span), y))
        else:  # vertical cut
            x = random.randint(int(width * 0.3), int(width * 0.7))
            y0 = random.randint(2, max(3, height // 3))
            span = random.randint(max(3, height // 4), max(4, height - y0))
            cuts.append((x, y0, x, min(height - 2, y0 + span)))
    return cuts


def _render_character(
    ch: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: tuple[int, int, int],
    stroke_width: int,
    stroke_fill: tuple[int, int, int] | None,
    angle: float,
    scale_x: float,
    scale_y: float,
    shear: float,
    perspective: bool,
    wave: bool,
    cuts: bool,
) -> Image.Image:
    left, top, right, bottom = font.getbbox(ch)
    pad = stroke_width * 2 + 12
    width = right - left + pad
    height = bottom - top + pad
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.text(
        (pad // 2 - left, pad // 2 - top),
        ch,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
    if perspective:
        layer = _glyph_perspective(layer)
    if shear:
        layer = layer.transform(
            layer.size, Image.AFFINE, (1, shear, 0, 0, 1, 0), resample=Image.BICUBIC
        )
    if scale_x != 1.0 or scale_y != 1.0:
        new_width = max(1, round(layer.width * scale_x))
        new_height = max(1, round(layer.height * scale_y))
        layer = layer.resize((new_width, new_height), Image.BICUBIC)
    if wave:
        _wave_shift(layer, axis="y", amplitude=random.randint(1, 2), period=random.randint(18, 30))
    layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    if cuts:
        _apply_cuts(layer, _gen_cuts(layer.width, layer.height))
    max_width = CAPTCHA_WIDTH // CAPTCHA_LENGTH
    max_height = CAPTCHA_HEIGHT - 12
    if layer.width > max_width or layer.height > max_height:
        factor = min(max_width / layer.width, max_height / layer.height)
        layer = layer.resize(
            (max(1, round(layer.width * factor)), max(1, round(layer.height * factor))),
            Image.BICUBIC,
        )
    return layer

def _wave_shift(image: Image.Image, *, axis: str, amplitude: int, period: int) -> None:
    """Sine-warp an image along one axis, wrapping so nothing is lost."""
    phase = random.uniform(0, 2 * math.pi)
    if axis == "y":
        for x in range(image.width):
            dy = int(amplitude * math.sin(2 * math.pi * x / period + phase))
            if dy == 0:
                continue
            column = image.crop((x, 0, x + 1, image.height))
            image.paste(column, (x, dy % image.height))
    else:
        for y in range(image.height):
            dx = int(amplitude * math.sin(2 * math.pi * y / period + phase))
            if dx == 0:
                continue
            row = image.crop((0, y, image.width, y + 1))
            image.paste(row, (dx % image.width, y))


def _scan_skew(image: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    """Subtle parallelogram tilt, like a slightly crooked scan (lightweight)."""
    skew = random.uniform(-0.02, 0.02)
    if abs(skew) < 0.01:
        return image
    return image.transform(
        image.size,
        Image.AFFINE,
        (1, skew, 0, skew, 1, 0),
        resample=Image.BICUBIC,
        fillcolor=bg,
    )


def _pattern_color(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    dark = sum(bg) // 3 < 128
    return (42, 42, 42) if dark else (206, 206, 206)


def _pattern_hatch(image: Image.Image, *, step: int, color: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for i in range(-height, width + height, step):
        draw.line((i, 0, i + height, height), fill=color, width=1)


def _pattern_grid(image: Image.Image, *, step: int, color: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    for x in range(0, image.width, step):
        draw.line((x, 0, x, image.height), fill=color, width=1)
    for y in range(0, image.height, step):
        draw.line((0, y, image.width, y), fill=color, width=1)


def _pattern_plus(image: Image.Image, *, step: int, color: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    for x in range(step // 2, image.width, step):
        for y in range(step // 2, image.height, step):
            draw.line((x - 2, y, x + 2, y), fill=color, width=1)
            draw.line((x, y - 2, x, y + 2), fill=color, width=1)


def _pattern_scan(image: Image.Image, *, step: int, color: tuple[int, int, int]) -> None:
    for y in range(step, image.height, step):
        ImageDraw.Draw(image).line((0, y, image.width, y), fill=color, width=1)


def _paint_background(image: Image.Image, cfg: _StyleConfig) -> Image.Image:
    color = _pattern_color(cfg["bg"])
    preset = cfg["background"]
    if preset == "hatch":
        _pattern_hatch(image, step=9, color=color)
        image = noise_engine.add_grain(image, sigma=8, alpha=0.06)
    elif preset == "grid":
        _pattern_grid(image, step=8, color=color)
    elif preset == "plus":
        _pattern_plus(image, step=10, color=color)
    elif preset == "scan":
        _pattern_scan(image, step=8, color=color)
        image = noise_engine.add_grain(image, sigma=10, alpha=0.07)
    return image


def _line_color(cfg: _StyleConfig, *, behind: bool = False) -> tuple[int, int, int]:
    dark = sum(cfg["bg"]) // 3 < 128
    if dark:
        return (85, 85, 85) if behind else (165, 165, 165)
    return (150, 150, 150) if behind else (115, 115, 115)


def _draw_halo(
    layer: Image.Image, x: int, y: int, width: int, height: int, bg: tuple[int, int, int]
) -> None:
    pad = 4
    ImageDraw.Draw(layer).rounded_rectangle(
        (x - pad, y - pad, x + width + pad, y + height + pad), radius=6, fill=bg
    )


def _add_jail_bars(image: Image.Image, color: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    for i in range(3):
        y = 8 + i * 18 + random.randint(-3, 3)
        draw.line(
            (random.randint(-6, 6), y, image.width + random.randint(-6, 6), y), fill=color, width=3
        )


def _add_mask_band(image: Image.Image, bg: tuple[int, int, int]) -> None:
    y0 = random.randint(12, image.height - 24)
    band_height = random.randint(8, 14)
    region = image.crop((0, y0, image.width, y0 + band_height))
    fill = Image.new("RGB", region.size, bg)
    region = Image.blend(region, fill, 0.45)
    image.paste(region, (0, y0))


def _layout(
    glyphs: list[Image.Image],
    cfg: _StyleConfig,
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    if cfg["layout"] == "overlap":
        overlaps = [random.randint(cfg["overlap_min"], cfg["overlap_max"]) for _ in glyphs]
        total = sum(g.width - o for g, o in zip(glyphs, overlaps, strict=False)) + overlaps[-1]
        margin = max(8, (width - total) // 2)
        x = margin
        xs = [margin]
        for g, o in zip(glyphs[:-1], overlaps[:-1], strict=False):
            x += g.width - o
            xs.append(x)
    else:
        gaps = [random.randint(cfg["gap_min"], cfg["gap_max"]) for _ in glyphs]
        total = sum(g.width for g in glyphs) + sum(gaps) - gaps[-1]
        margin = max(8, (width - total) // 2)
        x = margin
        xs = []
        for g, gap in zip(glyphs, gaps, strict=False):
            xs.append(x)
            x += g.width + gap

    baseline = height - 10
    ys = []
    for glyph in glyphs:
        y = baseline - glyph.height + random.randint(-cfg["jitter"], cfg["jitter"])
        y = max(2, min(y, height - 2 - glyph.height))
        ys.append(y)
    return list(zip(xs, ys, strict=False))


font_manager = FontManager()
noise_engine = NoiseEngine()
text_generator = RandomTextGenerator()


def _render(text: str, style: str) -> Image.Image:
    cfg = _STYLES[style]
    width, height = CAPTCHA_WIDTH, CAPTCHA_HEIGHT
    font_size = CAPTCHA_FONT_SIZE

    image = Image.new("RGB", (width, height), cfg["bg"])
    image = _paint_background(image, cfg)

    if cfg["guide_lines"]:  # one broken line behind the text
        noise_engine.add_broken_lines(image, count=1, color=_line_color(cfg, behind=True))

    glyphs: list[Image.Image] = []
    for ch in text:
        cuts_chance = cfg["cuts_chance"]
        glyphs.append(
            _render_character(
                ch,
                font_manager.pick(size=font_size),
                fill=cfg["fg"],
                stroke_width=cfg["stroke"],
                stroke_fill=cfg["stroke_fill"],
                angle=random.uniform(cfg["angle_min"], cfg["angle_max"]),
                scale_x=random.uniform(0.97, 1.05),
                scale_y=random.uniform(0.97, 1.05),
                shear=random.uniform(-0.03, 0.03),
                perspective=random.random() < 0.35,
                wave=bool(cfg["local_wave"]) and random.random() < 0.4,
                cuts=random.random() < cuts_chance,
            )
        )

    total_width = sum(g.width for g in glyphs)
    if total_width > width - 20:
        factor = (width - 20) / total_width
        glyphs = [
            g.resize(
                (max(1, round(g.width * factor)), max(1, round(g.height * factor))),
                Image.BICUBIC,
            )
            for g in glyphs
        ]

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for glyph, (x, y) in zip(glyphs, _layout(glyphs, cfg, width, height), strict=False):
        x = max(2, min(x, width - 2 - glyph.width))
        if cfg["halo"]:
            _draw_halo(layer, x, y, glyph.width, glyph.height, cfg["bg"])
        layer.alpha_composite(glyph, (x, y))
    image.paste(layer, (0, 0), layer)

    if cfg["guide_lines"]:
        noise_engine.add_guide_lines(image, count=cfg["guide_lines"], color=_line_color(cfg))
    if cfg["jail_bars"]:
        _add_jail_bars(image, cfg["fg"])
    if cfg["mask_band"]:
        _add_mask_band(image, cfg["bg"])

    dark = sum(cfg["bg"]) // 3 < 128
    noise = noise_engine
    if cfg["ink_blobs"]:
        noise.add_ink_blobs(image, count=2, color=(200, 200, 200) if dark else (70, 70, 70))
    noise.add_dust(image, count=24, color=(150, 150, 150) if dark else (120, 120, 120))
    noise.add_dashes(image, count=6, color=(130, 130, 130) if dark else (140, 140, 140))
    noise.add_edge_fragments(image, count=3, color=(150, 150, 150) if dark else (130, 130, 130))

    if style in ("classic", "neon"):
        _wave_shift(image, axis="y", amplitude=random.randint(0, 1), period=random.randint(60, 90))
    return _scan_skew(image, cfg["bg"]).convert("L").convert("RGB")


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
