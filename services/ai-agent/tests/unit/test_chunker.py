"""Unit tests for the parent-child chunker (SKY-58).

Uses a deterministic in-memory tiktoken encoding (tokens 'aa','ab','cb',' ')
so chunk boundaries, overlaps, and grouping can be asserted on exact ids -
no network, no flakiness.
"""

from __future__ import annotations

import tiktoken

from ai_agent.core.chunker import chunk_document
from ai_agent.core.token_counter import TokenCounter


def _counter_for(text: str) -> tuple[TokenCounter, list[int]]:
    mergeable_ranks = {b"aa": 0, b"ab": 1, b"cb": 2, b" ": 3}
    encoding = tiktoken.Encoding(
        name="tiny-test",
        pat_str="aa|ab|cb| ",
        mergeable_ranks=mergeable_ranks,
        special_tokens={},
    )
    counter = TokenCounter(encoding=encoding)
    return counter, encoding.encode(text)


def _token_text(counter: TokenCounter, text: str) -> list[int]:
    return counter.encode(text)


class TestChunkDocument:
    def test_empty_and_blank_texts_yield_no_chunks(self) -> None:
        counter, _ = _counter_for("")
        assert chunk_document("", counter=counter) == []
        assert chunk_document("   \n  ", counter=counter) == []

    def test_tiny_document_is_one_child_in_one_parent(self) -> None:
        counter, tokens = _counter_for("aa ab cb")
        parents = chunk_document("aa ab cb", counter=counter, child_tokens=400, parent_tokens=2000)
        assert len(parents) == 1
        assert len(parents[0].children) == 1
        assert parents[0].children[0].token_count == len(tokens)

    def test_child_token_count_never_exceeds_budget(self) -> None:
        text = " aa".join(f"ab{i}" for i in range(40)) + " cb"
        counter, _ = _counter_for(text)
        parents = chunk_document(text, counter=counter, child_tokens=10, parent_tokens=200)
        children = [c for p in parents for c in p.children]
        assert len(children) > 1
        assert all(c.token_count <= 10 for c in children)

    def test_consecutive_children_overlap_by_requested_tokens(self) -> None:
        # 100 tokens, child=10, overlap=3 -> windows start every 7 ids.
        text = " ".join(["aa"] * 99) + " cb"
        counter, _ = _counter_for(text)
        parents = chunk_document(
            text, counter=counter, child_tokens=10, parent_tokens=500, overlap_tokens=3
        )
        children = [c for p in parents for c in p.children]
        first = _token_text(counter, children[0].text)
        second = _token_text(counter, children[1].text)
        # Second window starts at id 7; its first 3 ids repeat the tail of
        # the first window (ids 7,8,9).
        assert first[7:] == second[:3]

    def test_overlap_clamped_to_half_the_child_window(self) -> None:
        text = " ".join(["aa"] * 30) + " cb"
        counter, _ = _counter_for(text)
        parents = chunk_document(
            text, counter=counter, child_tokens=5, parent_tokens=200, overlap_tokens=50
        )
        children = [c for p in parents for c in p.children]
        # overlap clamps to child_tokens // 2 = 2 -> every window starts 3 ids
        # later; the second window's first 2 ids repeat the tail of the first.
        assert (
            _token_text(counter, children[0].text)[3:] == _token_text(counter, children[1].text)[:2]
        )

    def test_parents_group_children_until_budget(self) -> None:
        text = " ".join(["aa"] * 60) + " cb"
        counter, _ = _counter_for(text)
        parents = chunk_document(text, counter=counter, child_tokens=5, parent_tokens=15)
        assert len(parents) > 1
        # Every finished parent stays within budget (the trailing single-child
        # parent may exceed it only when a child alone is over budget).
        assert all(p.token_count <= 15 or len(p.children) == 1 for p in parents)

    def test_giant_children_never_dropped_when_over_parent_budget(self) -> None:
        # 101 tokens, child=50 -> 3 children, parent budget 5: every child
        # exceeds the budget, so each becomes a single-child parent. Content
        # is preserved exactly once - nothing is dropped, nothing is split
        # mid-token.
        text = " ".join(["aa"] * 50) + " cb"
        counter, tokens = _counter_for(text)
        parents = chunk_document(
            text, counter=counter, child_tokens=50, parent_tokens=5, overlap_tokens=0
        )
        assert len(parents) == 3
        assert all(len(p.children) == 1 for p in parents)
        children = [c for p in parents for c in p.children]
        assert sum(c.token_count for c in children) == len(tokens)

    def test_unsplittable_content_over_budget_is_still_kept(self) -> None:
        text = " ".join(["aa"] * 40) + " cb"  # 41+ tokens
        counter, _ = _counter_for(text)
        parents = chunk_document(
            text, counter=counter, child_tokens=100, parent_tokens=30, overlap_tokens=0
        )
        # One child of 41+ tokens cannot fit a 30-token parent; it must still
        # be emitted (never silently dropped).
        assert len(parents) == 1
        assert parents[0].token_count > 30

    def test_deterministic_output(self) -> None:
        text = " ".join(["aa"] * 40) + " cb"
        counter, _ = _counter_for(text)
        first = chunk_document(text, counter=counter, child_tokens=8, parent_tokens=20)
        second = chunk_document(text, counter=counter, child_tokens=8, parent_tokens=20)
        assert first == second

    def test_negative_budget_rejected(self) -> None:
        counter, _ = _counter_for("aa ab")
        try:
            chunk_document("aa ab", counter=counter, child_tokens=0, parent_tokens=200)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError("child_tokens=0 must be rejected")
