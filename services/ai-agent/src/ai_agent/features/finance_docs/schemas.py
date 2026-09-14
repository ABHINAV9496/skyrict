"""ai-agent finance-docs feature (FIN-AI-004) - domain shapes.

Plain dataclasses for the three LLM interactions of the document & tax suite:
A5 tax summaries, A10 audit narration, A12 grounded document Q&A. These mirror
``account_suggest.schemas``: the HTTP request/response models live in the
router and the feature layer stays framework-free.

All three stay *stateless*: core serializes the tenant's data (period +
posted entries / question) in the request body, ai-agent runs the LLM, and
returns strict JSON or abstains (``None``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaxCategory:
    """One per-category tax line for a fiscal period."""

    category: str
    detail: str
    input_tax: float
    output_tax: float
    net: float


@dataclass(frozen=True, slots=True)
class TaxSummary:
    """LLM-computed input/output tax broken down by category."""

    categories: tuple[TaxCategory, ...]
    total_input: float
    total_output: float
    model_used: str


@dataclass(frozen=True, slots=True)
class RiskArea:
    """One flagged risk in an audit narration."""

    entry_id: str | None
    risk_type: str
    description: str
    severity: str  # low | medium | high


@dataclass(frozen=True, slots=True)
class AuditNarration:
    """Plain-English narrative over a range of posted entries + risks."""

    narration: str
    risk_areas: tuple[RiskArea, ...]
    model_used: str


@dataclass(frozen=True, slots=True)
class QaCitation:
    """One evidence chunk the generated answer is grounded on."""

    source_ref: str
    chunk_text: str
    score: float


@dataclass(frozen=True, slots=True)
class DocAnswer:
    """Grounded answer + the retrieved chunks it cites."""

    answer: str
    citations: tuple[QaCitation, ...]
    model_used: str
