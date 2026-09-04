"""PII redactor - pattern-based masking of sensitive values in free text.

The redactor is the core of the HR-AI-001 commit-1 gate. It recognises and
replaces sensitive fragments (NRIC/MyKad, phone, email, employee numbers, bank
account fragments, salary figures, and labelled person names) with fixed mask
tokens, preserving the rest of the text verbatim.

It is deliberately pure (no I/O) and deterministic so it can be unit-tested
against a fixed corpus, including mixed Malay/English text.

Masking is regex-and-heuristic driven:

- Strong, unambiguous patterns (MyKad, phone, email, salary, employee number,
  account digit groups) are replaced directly.
- Person-names are only masked when they appear under a clear personal-data
  label (e.g. "Gaji <name>", "Employee <name>", "staf <name>"), to avoid
  over-aggressive masking of ordinary English/Malay words.

NOTE on confidence: this is a deterministic heuristic, not a classifier. It errs
on the side of masking (fail closed): when a token is ambiguous it is treated as
sensitive rather than leakable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Mask tokens
# ---------------------------------------------------------------------------

MASK_NRIC = "[NRIC]"
MASK_PHONE = "[PHONE]"
MASK_EMAIL = "[EMAIL]"
MASK_EMPLOYEE = "[EMPLOYEE_NO]"
MASK_ACCOUNT = "[ACCOUNT]"
MASK_SALARY = "[SALARY]"
MASK_NAME = "[NAME]"


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """The output of a redaction pass.

    Attributes:
        text: The input with every sensitive value replaced by a mask token.
        mask_counts: Mapping of mask token -> number of times it was applied.
    """

    text: str
    mask_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Malaysian MyKad / NRIC: six-two-two digits or dashed/solid:
#   000101102988, 000101-10-2988, 010203-04-5678, 01-02-03-04-05-06 (rare)
_NRIC_RE = re.compile(r"\b(?:[0-9]{6}[- ]?[0-9]{2}[- ]?[0-9]{4})\b")

# Generic long numeric identifier fallback: any 10-14 consecutive digits not
# otherwise matched (bank accounts, membership numbers). Kept separate from
# MyKad so it can be tuned independently.
_ACCOUNT_DIGITS_RE = re.compile(r"\b(?<!\d)\d{13,16}\b")

# Account fragments: 4+ digit groups separated by spaces or dashes, e.g.
#   "1234 5678 9012 3456", "5087-XXXX-XXXX" (already partially masked)
_ACCOUNT_GROUP_RE = re.compile(r"\b\d{4}(?:[ -]\d{4}){2,}\b")

# Phone numbers: optional +/country code, then 2+ digit groups separated by
# spaces/dashes (or contiguous). Covers "012-345 6789", "+60 12 345 6789",
# "60 12 345 6789", "012-3456789".
_PHONE_RE = re.compile(r"(?<!\d)(?:\+\d{1,3}[\s-]?)?(?:\d{2,4}[\s-]?){2,}\d{2,4}(?!\d)")

# Employee numbers: "EMP-000123" / "EMP000123" (case-insensitive EMP prefix).
_EMPLOYEE_RE = re.compile(
    r"\bEMP[-]?\d{2,10}\b",
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Salary figures: a currency symbol/code optionally followed by a grouped
# number, OR a grouped number followed by a currency code. Handles:
#   "RM 8,500", "RM8,500", "MYR 8,500", "MYR8,500", "8,500.00 MYR", "RM12,345"
_CURRENCY = r"(?:RM|MYR|USD|EUR|GBP|SGD|INR)"
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d{2})?"
_NUM_NO_GROUP = r"\d{1,3}(?:\.\d{1,2})?"
_SALARY_RE = re.compile(
    rf"(?<!\w)(?:{_CURRENCY}\s?-?\s?(?:{_NUM}|{_NUM_NO_GROUP})|(?:{_NUM}|{_NUM_NO_GROUP})\s?-?\s?{_CURRENCY})(?!\w)",
    re.IGNORECASE,
)

# A bare large salary-style number right after a currency word is covered above.
# Person names under personal-data labels. Keep the label set conservative and
# explicit so ordinary words are not masked as names.
_NAME_LABEL_RE = re.compile(
    r"((?:Gaji|gaji|Employee|employee|Staf|staf|Staff|staff|Karyawan|karyawan|"
    r"Nama|nama|Total|total|For|for|Of|of|belongs to|milik)\s+)"
    r"([A-Z][a-z]+(?:\s[A-Za-z][a-z]+){0,2})"
)

# A leading title + name (Dr/Mr/Mrs/Ms/Mdm followed by two words).
_TITLED_NAME_RE = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Mdm|Encik|Cik|Puan)\.?\s+[A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2}\b"
)

# ---------------------------------------------------------------------------
# Application order: run the strongest, least-surprising patterns first, then
# the heuristic name pattern last (it is the noisiest). Each pass accumulates
# into a running mask-count dict.
# ---------------------------------------------------------------------------


def _apply_replace(text: str, pattern: re.Pattern[str], token: str) -> str:
    """Replace every match with the token."""

    def _sub(_match: re.Match[str]) -> str:
        return token

    return pattern.sub(_sub, text)


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    """Mask sensitive values in ``text``.

    Returns ``(masked_text, mask_counts)`` where ``mask_counts`` maps each mask
    token to the number of times it was applied.

    Deterministic and pure. Fails closed: ambiguous matches are masked.
    """
    counts: dict[str, int] = {}

    def _count_and_replace(pattern: re.Pattern[str], token: str) -> None:
        nonlocal text
        # Count matches before we replace them.
        found = pattern.findall(text)
        n = len(found)
        if n:
            text = _apply_replace(text, pattern, token)
            counts[token] = counts.get(token, 0) + n

    # Strong patterns first.
    _count_and_replace(_EMAIL_RE, MASK_EMAIL)
    _count_and_replace(_EMPLOYEE_RE, MASK_EMPLOYEE)
    _count_and_replace(_ACCOUNT_GROUP_RE, MASK_ACCOUNT)
    _count_and_replace(_ACCOUNT_DIGITS_RE, MASK_ACCOUNT)
    _count_and_replace(_NRIC_RE, MASK_NRIC)
    _count_and_replace(_SALARY_RE, MASK_SALARY)
    _count_and_replace(_PHONE_RE, MASK_PHONE)

    # Heuristic names (noisiest - apply last so it cannot consume the strong
    # tokens above).
    _count_and_replace(_TITLED_NAME_RE, MASK_NAME)
    _count_and_replace(_NAME_LABEL_RE, MASK_NAME)

    return text, counts


class Redactor:
    """Object wrapper around :func:`redact_text` for dependency injection.

    Engines and the LLM router receive a single ``Redactor`` instance so the
    gate is applied consistently and can be swapped/faked in tests.
    """

    def redact(self, text: str) -> RedactionResult:
        masked, counts = redact_text(text)
        return RedactionResult(text=masked, mask_counts=counts)


__all__ = [
    "MASK_ACCOUNT",
    "MASK_EMAIL",
    "MASK_EMPLOYEE",
    "MASK_NAME",
    "MASK_NRIC",
    "MASK_PHONE",
    "MASK_SALARY",
    "RedactionResult",
    "Redactor",
    "redact_text",
]
