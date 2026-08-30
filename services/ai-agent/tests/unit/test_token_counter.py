"""Unit tests for the deterministic token counter (SKY-58)."""

from __future__ import annotations

import tiktoken

from ai_agent.core.token_counter import TokenCounter


def _tiny_encoding() -> tiktoken.Encoding:
    """Deterministic, network-free encoding: tokens 'aa','ab','cb',' '."""
    mergeable_ranks = {b"aa": 0, b"ab": 1, b"cb": 2, b" ": 3}
    return tiktoken.Encoding(
        name="tiny-test",
        pat_str="aa|ab|cb| ",
        mergeable_ranks=mergeable_ranks,
        special_tokens={},
    )


class TestTokenCounter:
    def test_empty_text_has_zero_tokens(self) -> None:
        counter = TokenCounter(encoding=_tiny_encoding())
        assert counter.count("") == 0
        assert counter.encode("") == []

    def test_counts_exact_tokens(self) -> None:
        counter = TokenCounter(encoding=_tiny_encoding())
        assert counter.count("aa ab cb") == 5  # aa ' ' ab ' ' cb

    def test_encode_decode_round_trips(self) -> None:
        counter = TokenCounter(encoding=_tiny_encoding())
        text = "aa ab cb aa"
        ids = counter.encode(text)
        assert ids == [0, 3, 1, 3, 2, 3, 0]
        assert counter.decode(ids) == text

    def test_special_token_lookalikes_are_content_not_markers(self) -> None:
        # Uses the real cl100k encoding: '<|endoftext|>' must be treated as
        # document content, not a BPE control token (no exception raised).
        counter = TokenCounter()
        n = counter.count("<|endoftext|>")
        assert n > 0

    def test_production_encoding_smoke(self) -> None:
        counter = TokenCounter()
        assert counter.count("Laptop charger 65W with USB-C") > 0
        assert counter.encode("hello world") == counter.encode("hello world")
