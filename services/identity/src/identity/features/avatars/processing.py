"""Avatar image processing - validate, normalize, and encode to WebP.

All Pillow work is isolated here so services and tests depend on a pure
``bytes -> bytes`` function and never on image internals.
"""

from __future__ import annotations

import io

from PIL import Image

from skyrict_common.exceptions import ValidationError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF"})
AVATAR_SIZE = (256, 256)
AVATAR_MIME = "image/webp"


def normalize_avatar(data: bytes) -> bytes:
    """Validate raw upload bytes and return a 256x256 WebP encoded avatar.

    Accepts JPEG/PNG/WebP/GIF, enforces a size and pixel ceiling, and cover-
    crops to a square. Raises ``ValidationError`` for non-image content,
    unsupported formats, or oversized uploads.
    """
    if not data:
        raise ValidationError("No image file provided")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError("Image exceeds the 10 MB size limit")

    try:
        source = Image.open(io.BytesIO(data))
        source.load()
    except Exception as exc:  # any Pillow failure means "not an image"
        raise ValidationError("Uploaded file is not a valid image") from exc

    if source.format not in ALLOWED_FORMATS:
        raise ValidationError(f"Unsupported image format: {source.format}")

    if source.width * source.height > MAX_IMAGE_PIXELS:
        raise ValidationError("Image dimensions are too large")

    square = _cover_resize(source.convert("RGBA"), AVATAR_SIZE)

    buffer = io.BytesIO()
    square.save(buffer, format="WEBP", quality=85, method=6)
    return buffer.getvalue()


def _cover_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize an image to cover ``size`` (center crop), preserving aspect."""
    target_w, target_h = size
    image_w, image_h = image.size
    scale = max(target_w / image_w, target_h / image_h)
    new_w, new_h = int(image_w * scale), int(image_h * scale)
    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))
