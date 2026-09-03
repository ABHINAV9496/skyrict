"""Deterministic token counting on the cl100k_base BPE encoding (tiktoken).

Used by the chunker so chunk boundaries land on real token boundaries -
word/char-count heuristics drift from every embedding tokenizer and produce
ragged chunks. ``cl100k_base`` is the closest public approximation for both
OpenAI ``text-embedding-3-small`` (cl100k family) and common OSS embedders.

The production encoding is loaded lazily on first use (tiktoken downloads the
BPE file once and caches it), so constructing a :class:`TokenCounter` never
blocks imports. Tests may inject a tiny in-memory :class:`~tiktoken.Encoding`
for fully deterministic, network-free assertions.
"""

from __future__ import annotations

import tiktoken

_ENCODING_NAME = "cl100k_base"

# Process-global lazy cache: tiktoken encodings are heavy; build once.
_encoding: tiktoken.Encoding | None = None


class TokenCounter:
    """Lazy, cached access to a tiktoken BPE encoder.

    One instance is passed down the ingestion pipeline so the chunker and the
    service share the same view of the encoding.
    """

    def __init__(
        self,
        *,
        encoding: tiktoken.Encoding | None = None,
        encoding_name: str = _ENCODING_NAME,
    ) -> None:
        self.encoding_name = encoding_name
        self._encoding = encoding

    def _get_encoding(self) -> tiktoken.Encoding:
        if self._encoding is not None:
            return self._encoding
        global _encoding  # process-global lazy cache
        if _encoding is None or _encoding.name != self.encoding_name:
            _encoding = tiktoken.get_encoding(self.encoding_name)
        return _encoding

    def encode(self, text: str) -> list[int]:
        """Token ids for *text* (empty text -> no tokens)."""
        if not text:
            return []
        # Apply NO special-token rules: ERP docs may contain literal strings
        # that collide with BPE control tokens; they are content, not markers.
        return self._get_encoding().encode(text, disallowed_special=())

    def decode(self, ids: list[int]) -> str:
        """Decode token ids back to text (round-trips the encode)."""
        if not ids:
            return ""
        return self._get_encoding().decode(ids)

    def count(self, text: str) -> int:
        """Exact token count of *text*."""
        return len(self.encode(text))
