"""Process chat attachments into LLM-ready content.

Converts :class:`AttachmentData` (base64 from the API layer) into:
  - Extracted text context for text-only LLM calls
  - Multimodal content blocks (OpenAI vision format) for image-bearing turns
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import structlog

from ai_agent.features.attachments.extractor import extract_attachments

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = structlog.get_logger("ai_agent.attachments")

# Max total base64 payload per turn to avoid LLM context overflow.
_MAX_TOTAL_ATTACHMENT_BYTES: Final[int] = 20 * 1024 * 1024  # 20 MB


@dataclass(frozen=True, slots=True)
class ProcessedAttachments:
    """Result of processing a list of chat attachments."""

    """Text extracted from document attachments (PDF, DOCX, XLSX, CSV, etc.)."""
    extracted_text: str = ""

    """Multimodal content blocks for images (OpenAI vision API format).

    Each dict is ``{"type": "image_url", "image_url": {"url": "data:<mime>;base64,<data>"}}``.
    """
    image_blocks: list[dict[str, object]] = field(default_factory=list)

    """Human-readable summary of what was attached (for prompt context)."""
    attachment_summary: str = ""


def process_attachments(
    attachments: Sequence[object],
) -> ProcessedAttachments:
    """Process a list of AttachmentData objects into LLM-ready format.

    Args:
        attachments: List of objects with ``name``, ``type``, ``size``, ``base64``
            attributes (typically :class:`AttachmentData` from the API schema).

    Returns:
        :class:`ProcessedAttachments` with extracted text and image content blocks.
    """
    if not attachments:
        return ProcessedAttachments()

    # Decode base64 → raw bytes for each attachment.
    files: list[tuple[str, str, bytes]] = []
    total_bytes = 0
    for att in attachments:
        name = getattr(att, "name", "unknown")
        mime = getattr(att, "type", "application/octet-stream")
        raw_b64 = getattr(att, "base64", "")
        try:
            raw = base64.b64decode(raw_b64)
        except Exception:
            logger.warning("base64_decode_failed", name=name)
            continue
        total_bytes += len(raw)
        if total_bytes > _MAX_TOTAL_ATTACHMENT_BYTES:
            logger.warning("total_attachment_limit_exceeded", total_bytes=total_bytes)
            break
        files.append((name, mime, raw))

    if not files:
        return ProcessedAttachments()

    extracted_text, image_base64s = extract_attachments(files)

    # Build OpenAI-compatible multimodal content blocks for images.
    image_blocks: list[dict[str, object]] = []
    for _img_idx, img_b64 in enumerate(image_base64s):
        # Infer MIME from the original file list.
        mime = "image/jpeg"  # default
        for _name, m, _raw in files:
            if m.startswith("image/"):
                mime = m
                break
        image_blocks.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{img_b64}",
                },
            }
        )

    # Build a human-readable summary.
    doc_count = sum(1 for _, m, _ in files if not m.startswith("image/"))
    img_count = len(image_base64s)
    parts: list[str] = []
    if doc_count:
        parts.append(f"{doc_count} document(s)")
    if img_count:
        parts.append(f"{img_count} image(s)")
    summary = ", ".join(parts) if parts else "attachments"

    return ProcessedAttachments(
        extracted_text=extracted_text,
        image_blocks=image_blocks,
        attachment_summary=summary,
    )
