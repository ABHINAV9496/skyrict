"""Unit tests for the PII redaction gate (HR-AI-001, Commit 1).

Covers:
- The redactor's masking of individual sensitive patterns (NRIC/MyKad, phone,
  email, employee numbers, bank fragments, salaries).
- The Gherkin scenario "Redaction protects providers": a free-text corpus
  (including mixed Malay/English) passed through the pipeline before an LLM
  shows masked tokens present and raw values ABSENT from the outbound payload.
- The router-level gate: LlmRouter redacts the request before it reaches a
  provider adapter.
"""

from __future__ import annotations

from ai_agent.core.llm_router import LlmRouter
from ai_agent.core.providers.base import LlmCompletion, LlmRequest
from ai_agent.redaction import Redactor
from ai_agent.redaction.redactor import (
    MASK_ACCOUNT,
    MASK_EMAIL,
    MASK_EMPLOYEE,
    MASK_NAME,
    MASK_NRIC,
    MASK_PHONE,
    MASK_SALARY,
    redact_text,
)


class _RecordingProvider:
    """A provider that captures the exact request it was handed."""

    name = "recorder"
    model = "rec"
    local_only = False

    def __init__(self) -> None:
        self.received: LlmRequest | None = None

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        self.received = request
        return LlmCompletion(text="ok", model_used="rec", latency_ms=1)


# ---------------------------------------------------------------------------
# Individual patterns
# ---------------------------------------------------------------------------


class TestIndividualPatterns:
    def test_mykad_masked(self) -> None:
        masked, counts = redact_text("NRIC 000101102988 and 010203-04-5678 here")
        assert MASK_NRIC in masked
        assert "000101102988" not in masked
        assert "010203-04-5678" not in masked
        assert counts[MASK_NRIC] == 2

    def test_phone_masked(self) -> None:
        masked, _ = redact_text("Call 012-345 6789 or +60 12 345 6789 today")
        assert MASK_PHONE in masked
        assert "012-345 6789" not in masked
        assert "+60 12 345 6789" not in masked

    def test_email_masked(self) -> None:
        masked, counts = redact_text("reach me at wong.kar.wai@example.com ASAP")
        assert MASK_EMAIL in masked
        assert "wong.kar.wai@example.com" not in masked
        assert counts[MASK_EMAIL] == 1

    def test_employee_number_masked(self) -> None:
        masked, counts = redact_text("check EMP-004201 record")
        assert MASK_EMPLOYEE in masked
        assert "EMP-004201" not in masked
        assert counts[MASK_EMPLOYEE] == 1

    def test_bank_account_group_masked(self) -> None:
        masked, counts = redact_text("refunds to 5087 1111 2222 3333")
        assert MASK_ACCOUNT in masked
        assert "5087 1111 2222 3333" not in masked
        assert counts[MASK_ACCOUNT] == 1

    def test_salary_masked(self) -> None:
        for raw in ("RM 8,500", "RM8,500", "MYR 12,000.00", "8,500.00 MYR"):
            masked, counts = redact_text(f"pays {raw} monthly")
            assert MASK_SALARY in masked, f"expected salary mask for {raw!r}"
            assert raw not in masked
            assert counts[MASK_SALARY] >= 1

    def test_titled_name_masked(self) -> None:
        masked, counts = redact_text("review by Dr Wong Kar Wai")
        assert MASK_NAME in masked
        assert "Wong Kar Wai" not in masked
        assert counts[MASK_NAME] >= 1


# ---------------------------------------------------------------------------
# Mixed-language corpus (Gherkin: redaction protects providers)
# ---------------------------------------------------------------------------


class TestRedactionCorpus:
    """Covers the corpus requirement incl. Malay/English mixed text."""

    def test_mixed_malay_english_salary_and_mykad(self) -> None:
        text = "Gaji Wong Kar Wai RM 8,500 sebulan, kad pengenalan 000101-10-1234"
        masked, counts = redact_text(text)
        # Masked tokens present...
        assert MASK_NAME in masked
        assert MASK_SALARY in masked
        assert MASK_NRIC in masked
        # ...raw values absent.
        assert "Wong Kar Wai" not in masked
        assert "RM 8,500" not in masked
        assert "000101-10-1234" not in masked
        assert counts[MASK_NAME] >= 1
        assert counts[MASK_SALARY] >= 1
        assert counts[MASK_NRIC] == 1

    def test_english_salary_and_account(self) -> None:
        text = "Net pay 6,500.00 MYR to account 5087-1111-2222-3333"
        masked, _ = redact_text(text)
        assert MASK_SALARY in masked
        assert MASK_ACCOUNT in masked
        assert "6,500.00" not in masked
        assert "5087-1111-2222-3333" not in masked

    def test_outbound_payload_has_no_raw_values(self) -> None:
        """The corpus assertion: raw values absent from the outbound payload."""
        # (text, expected_present_tokens) - each entry's expected tokens are
        # the sensitive categories that entry genuinely contains.
        corpus = [
            (
                "Gaji Wong Kar Wai RM 8,500 sebulan, kad pengenalan 000101-10-1234",
                {MASK_NAME, MASK_SALARY, MASK_NRIC},
            ),
            (
                "Tel 012-345 6789, email wong@example.com, EMP-0042",
                {MASK_PHONE, MASK_EMAIL, MASK_EMPLOYEE},
            ),
            (
                "Refund 5087 1111 2222 3333, Dr Lim Siti Amanah, MYR 12,000",
                {MASK_ACCOUNT, MASK_NAME, MASK_SALARY},
            ),
        ]
        raw_values = [
            "Wong Kar Wai",
            "012-345 6789",
            "wong@example.com",
            "EMP-0042",
            "5087 1111 2222 3333",
            "Dr Lim Siti Amanah",
            "000101-10-1234",
        ]
        for text, expected in corpus:
            masked = redact_text(text)[0]
            # Every raw value in the corpus must be absent from every payload.
            for value in raw_values:
                assert value not in masked, f"raw {value!r} leaked: {masked!r}"
            # The tokens this entry is expected to carry are present.
            for token in expected:
                assert token in masked, f"expected {token} in {masked!r}"

    def test_deterministic(self) -> None:
        text = "Gaji Wong Kar Wai RM 8,500, kad pengenalan 000101-10-1234"
        assert redact_text(text) == redact_text(text)

    def test_plain_text_untouched(self) -> None:
        text = "Please review the leave balance for the finance team next month"
        masked, counts = redact_text(text)
        assert masked == text
        assert counts == {}


# ---------------------------------------------------------------------------
# Router-level gate
# ---------------------------------------------------------------------------


class TestRouterGate:
    def test_router_redacts_before_provider(self) -> None:
        provider = _RecordingProvider()
        router = LlmRouter([provider])
        prompt = "Gaji Wong Kar Wai RM 8,500, kad pengenalan 000101-10-1234"

        import asyncio

        asyncio.run(router.complete(LlmRequest(system_prompt="sys", user_prompt=prompt)))

        assert provider.received is not None
        received_prompt = provider.received.user_prompt
        assert "Wong Kar Wai" not in received_prompt
        assert "RM 8,500" not in received_prompt
        assert "000101-10-1234" not in received_prompt
        assert MASK_NAME in received_prompt
        assert MASK_SALARY in received_prompt
        assert MASK_NRIC in received_prompt

    def test_router_without_pii_passes_through_unchanged(self) -> None:
        provider = _RecordingProvider()
        router = LlmRouter([provider])
        prompt = "How many engineers are there?"

        import asyncio

        asyncio.run(router.complete(LlmRequest(system_prompt="sys", user_prompt=prompt)))

        assert provider.received is not None
        assert provider.received.user_prompt == prompt

    def test_injectable_redactor(self) -> None:
        """A custom redactor can be injected for testing the gate wiring."""
        provider = _RecordingProvider()
        router = LlmRouter([provider], redactor=Redactor())
        prompt = "gaji RM 9,000"

        import asyncio

        asyncio.run(router.complete(LlmRequest(system_prompt="sys", user_prompt=prompt)))

        assert provider.received is not None
        assert "9,000" not in provider.received.user_prompt
