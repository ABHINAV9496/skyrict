"""Memory service - recall context, store episodic memories, extract facts.

Orchestrates the LLM-based memory pipeline:
1. After each chat turn: store the query-response pair (episodic)
2. After each chat turn: extract key facts via LLM and store them (semantic)
3. Before each chat turn: retrieve relevant memories and inject as context

The service uses the same ``LlmRouter`` as the rest of the AI agent - no new
LLM dependency. Fact extraction uses a cheap model call (temperature=0.0).

SKY-100: when an optional ``EmbeddingProvider`` is wired, the service embeds
each query and fact at store time and passes the query embedding at recall
time so the repository can rank by cosine similarity. When no provider is
wired, the store rows and recall path stay byte-identical to pre-embedding
behavior (trigram/recency fallback).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from ai_agent.core.providers.base import LlmRequest

if TYPE_CHECKING:
    import uuid

    from ai_agent.core.embedding import EmbeddingProvider
    from ai_agent.core.llm_router import LlmRouter
    from ai_agent.db.memory_repository import MemoryRepository

logger = structlog.get_logger("ai_agent.memory")

_EXTRACT_FACTS_SYSTEM_PROMPT = (
    "You extract key facts from a CRM conversation. "
    "Return a JSON array of objects, each with 'fact' (string), "
    "'category' (one of: preference, entity, context, instruction), "
    "'entity_type' (lead | opportunity | customer | contact | null), "
    "'entity_id' (UUID string or null), and 'confidence' (0.0-1.0). "
    "Extract at most 5 facts. Only extract genuinely useful facts - "
    "skip generic greetings, thanks, or filler."
)

_RECALL_CONTEXT_HEADER = (
    "The following are relevant memories from previous conversations with "
    "this user. Use them to provide more contextual answers.\n\n"
)


class MemoryService:
    """Recall and store conversation memories for the CRM Assistant."""

    def __init__(
        self,
        *,
        llm_router: LlmRouter,
        repo: MemoryRepository,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._llm = llm_router
        self._repo = repo
        self._embedding_provider = embedding_provider

    async def recall_context(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
    ) -> str:
        """Retrieve relevant memories and format them as context text.

        Returns an empty string if no memories are relevant.
        """
        vectors, _ = await self._embed_texts([query])
        query_embedding = vectors[0] if vectors else None
        episodic = await self._repo.recall_episodic(
            tenant_id=tenant_id,
            user_id=user_id,
            query=query,
            query_embedding=query_embedding,
        )
        semantic = await self._repo.recall_semantic(
            tenant_id=tenant_id,
            user_id=user_id,
            query=query,
            query_embedding=query_embedding,
        )

        if not episodic and not semantic:
            return ""

        parts: list[str] = []

        if semantic:
            parts.append("Known facts about this user/entities:")
            for f in semantic:
                entity = f" ({f['entity_type']})" if f.get("entity_type") else ""
                parts.append(f"- [{f['category']}{entity}] {f['fact']}")

        if episodic:
            parts.append("\nRecent conversation history:")
            for m in episodic:
                parts.append(f"- User asked: {m['query'][:100]}")
                parts.append(f"  AI answered: {m['summary'][:150]}")

        return _RECALL_CONTEXT_HEADER + "\n".join(parts)

    async def store_after_chat(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        response: str,
        module: str | None = None,
    ) -> None:
        """Store the conversation turn and extract facts.

        This is fire-and-forget - failures are logged but never propagate.
        Embedding failures degrade to unembedded rows, never lost data.
        """
        try:
            # 0. Best-effort embedding of the query (SKY-100).
            query_embedding, embedding_model = await self._embed_texts([query])

            # 1. Store episodic memory.
            await self._repo.store_episodic(
                tenant_id=tenant_id,
                user_id=user_id,
                query_text=query,
                response_summary=response[:500],
                module=module,
                embedding=query_embedding[0] if query_embedding else None,
                embedding_model=embedding_model,
            )

            # 2. Extract and store semantic facts.
            facts = await self._extract_facts(query, response)
            if facts:
                fact_embeddings, _ = await self._embed_texts(
                    [str(f.get("fact", "")) for f in facts]
                )
                await self._repo.store_semantic_facts(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    facts=facts,
                    embeddings=fact_embeddings,
                    embedding_model=embedding_model,
                )
        except Exception:
            logger.warning(
                "memory.store_failed",
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                exc_info=True,
            )

    async def _embed_texts(self, texts: list[str]) -> tuple[list[list[float]], str | None]:
        """Embed a batch, returning (vectors, model). Best-effort: a failure
        returns empty vectors so callers keep their unembedded fallback."""
        provider = self._embedding_provider
        if provider is None or not texts:
            return [], None
        try:
            result = await provider.embed(texts)
            if not result.vectors:
                return [], None
            return result.vectors, result.model_used
        except Exception:
            logger.warning(
                "memory.embed_failed",
                provider=provider.name,
                exc_info=True,
            )
            return [], None

    async def _extract_facts(
        self,
        query: str,
        response: str,
    ) -> list[dict[str, Any]]:
        """Use the LLM to extract key facts from a conversation turn."""
        if not self._llm.has_providers:
            return []

        user_prompt = (
            f"User query: {query[:300]}\n\n"
            f"AI response: {response[:500]}\n\n"
            "Extract key facts as a JSON array."
        )

        try:
            completion = await self._llm.complete(
                LlmRequest(
                    system_prompt=_EXTRACT_FACTS_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    max_tokens=256,
                    temperature=0.0,
                )
            )
            text = (completion.text or "").strip()
            # Parse JSON array from the response.
            # Handle markdown code blocks.
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            facts = json.loads(text)
            if isinstance(facts, list):
                return [f for f in facts if isinstance(f, dict) and "fact" in f]
        except Exception:
            logger.warning("memory.fact_extraction_failed", exc_info=True)

        return []
