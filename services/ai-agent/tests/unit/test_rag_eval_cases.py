"""Structural validation of the curated RAGAS eval cases (SKY-58).

These invariants keep the nightly gate meaningful: a large enough set, spread
across modules, with unique questions and non-empty ground-truth answers. The
test file exists so a reviewer can shrink/duplicate the corpus accidentally
without the nightly workflow noticing.
"""

from __future__ import annotations

from ai_agent.rag_eval_cases import RAG_EVAL_CASES


class TestRagEvalCases:
    def test_at_least_twenty_cases(self) -> None:
        assert len(RAG_EVAL_CASES) >= 20

    def test_questions_are_unique(self) -> None:
        questions = [case.question for case in RAG_EVAL_CASES]
        assert len(questions) == len(set(questions))

    def test_questions_and_answers_are_non_empty(self) -> None:
        for case in RAG_EVAL_CASES:
            assert case.question.strip(), case
            assert case.answer.strip(), case

    def test_modules_are_known_and_balanced(self) -> None:
        modules = {case.module for case in RAG_EVAL_CASES}
        assert modules <= {"docs", "products"}, modules
        # A single-module set would let one broken corpus slice pass silently.
        assert len(modules) >= 2

    def test_every_module_has_a_minimum_of_cases(self) -> None:
        counts: dict[str, int] = {}
        for case in RAG_EVAL_CASES:
            counts[case.module] = counts.get(case.module, 0) + 1
        assert all(count >= 5 for count in counts.values()), counts
