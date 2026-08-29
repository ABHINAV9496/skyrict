"""Curated RAGAS evaluation cases for the nightly RAG quality gate (SKY-58).

Each case is a (question, model answer, module) triple. The runner resolves the
question through the REAL production retrieval pipeline (embed provider →
vector search → parent fetch), generates an answer from the retrieved context,
and scores the pair with RAGAS. ``module`` routes the case to the matching
corpus slice so docs questions never search product chunks and vice versa.

Ground-truth answers are phrased as claims the corpus should contain —
``context_recall`` measures what fraction of those claims the retriever found.
Tuning notes for operators:

- Cases whose answers describe PROCESS (policies, formats, retention rules)
  are answerable from any well-ingested docs corpus — they never change.
- Cases whose answers name SPECIFIC records (a product, a SKU, a reorder
  point) gate corpus freshness: a nightly failure on one of these means the
  ingested snapshot is stale or missing that record.

Keep at least 20+ cases and spread them across ingested modules — a smaller
or single-module set produces noisy metric means.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RagEvalCase:
    """One evaluation case: question, model answer, and target corpus module."""

    question: str
    answer: str
    module: str


RAG_EVAL_CASES: tuple[RagEvalCase, ...] = (
    # ------------------------------------------------------------------
    # docs module — processes, policies, and platform guarantees (16)
    # ------------------------------------------------------------------
    RagEvalCase(
        question="What is the approval workflow for purchase orders above $10,000?",
        answer=(
            "Purchase orders above $10,000 require approval from the finance "
            "director before the order is placed."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="How are inventory adjustments recorded?",
        answer=(
            "Inventory adjustments are recorded as a signed movement with the "
            "reason code and the user responsible for the adjustment."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="What is the reorder policy for fast-moving items?",
        answer=(
            "Fast-moving items are reordered when the on-hand quantity falls "
            "below the reorder point, with a safety stock of two weeks of "
            "average demand."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="When are periodic inventory counts scheduled?",
        answer=(
            "Periodic inventory counts are scheduled quarterly at month end "
            "for all active warehouses."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="What happens to reserved stock at the end of the day?",
        answer=(
            "Reserved stock that is not shipped by end of day is released "
            "back to available inventory automatically."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="How are receiving discrepancies handled?",
        answer=(
            "Receiving discrepancies greater than one percent of the order "
            "quantity are flagged for review by the warehouse supervisor."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="What data does the AI agent store about queries?",
        answer=(
            "The AI agent stores the query text, response summary, module, "
            "token usage, and timestamps with a 90-day retention period."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="How long are query cache entries kept?",
        answer=(
            "Query cache entries expire after one hour in both the hot cache "
            "and the durable database layer before being swept."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="What happens when the embedding provider is unavailable?",
        answer=(
            "When the embedding provider is unavailable the service returns a "
            "typed unavailable error instead of silently degrading results."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="Which modules does RAG ingestion support?",
        answer=(
            "RAG ingestion supports the docs module and the products module "
            "from the core inventory service."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="How does tenant isolation work in the AI service?",
        answer=(
            "Every AI-owned table is tenant-scoped with row-level security; "
            "policies constrain all reads and writes to the tenant pinned in "
            "the session context."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="What is a parent chunk in the RAG pipeline?",
        answer=(
            "A parent chunk is a roughly two-thousand-token text block that is "
            "returned to the language model as generation context and is never "
            "embedded."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="What is a child chunk in the RAG pipeline?",
        answer=(
            "A child chunk is a roughly four-hundred-token embedded text block "
            "used for similarity search, and several children belong to one "
            "parent chunk."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="How are duplicate documents handled during ingestion?",
        answer=(
            "Ingesting a document that already exists replaces its rows "
            "idempotently, and both incremental and full modes are safe to "
            "re-run."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="What rate limits apply to AI queries?",
        answer=(
            "AI queries are limited per user per minute and per tenant per "
            "minute, failing open with a warning when Redis is unavailable."
        ),
        module="docs",
    ),
    RagEvalCase(
        question="What should the agent do when the answer is not in the retrieved context?",
        answer=(
            "The agent must state that the answer is not present in the "
            "retrieved context rather than fabricating a response."
        ),
        module="docs",
    ),
    # ------------------------------------------------------------------
    # products module — product records rendered from the core catalog (8)
    # ------------------------------------------------------------------
    RagEvalCase(
        question="Which product records include a reorder point?",
        answer=("Every product record includes its name, SKU, and reorder point."),
        module="products",
    ),
    RagEvalCase(
        question="How can I find the SKU of a product from its name?",
        answer=(
            "The product record lists the SKU next to the product name, so a "
            "name search returns the matching SKU."
        ),
        module="products",
    ),
    RagEvalCase(
        question="What fields are stored for each product record?",
        answer=(
            "Each product record stores the product name, its SKU, and the "
            "reorder point for stock replenishment."
        ),
        module="products",
    ),
    RagEvalCase(
        question="Which products are flagged for low-stock risk?",
        answer=(
            "Products whose on-hand quantity is at or below the reorder point "
            "are flagged as low-stock risk."
        ),
        module="products",
    ),
    RagEvalCase(
        question="What does the reorder point tell a buyer?",
        answer=(
            "The reorder point is the quantity threshold that triggers a "
            "replenishment order for that product."
        ),
        module="products",
    ),
    RagEvalCase(
        question="How are product names and SKUs related?",
        answer=(
            "Each product has exactly one SKU, which is a unique identifier "
            "paired with the human-readable product name."
        ),
        module="products",
    ),
    RagEvalCase(
        question="Where can I find a product's reorder threshold?",
        answer=(
            "The reorder threshold is stored in the product record alongside the name and SKU."
        ),
        module="products",
    ),
    RagEvalCase(
        question="What information is available for stock planning?",
        answer=(
            "For stock planning each product record provides the name, SKU, and reorder point."
        ),
        module="products",
    ),
)
