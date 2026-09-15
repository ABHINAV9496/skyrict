"""Supervisor graph - routes Agents-shell questions to registered module agents.

Composition root for the supervisor feature: reads the global ``agent_registry``
to decide which leaves are provisioned (enabled), then delegates through the
leaf services the API layer already composes. Unlike the checkpointed
:class:`AgentRuntime` (SKY-59) this is a STATELESS streaming facade - no
checkpointer, no HITL pause; SKY-60 chats render tokens live.

Route contract (SKY-60 Q&A decision #6): registry rows are seeded by migration
0009 - ``inventory_monitor`` and ``hr_copilot`` start enabled, while
``crm_assistant`` and ``finance_assistant`` start disabled so the supervisor
streams a clean "not provisioned yet" abstention instead of erroring. Migrations
flip those flags when the module backends land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_agent.db.agent_registry_repository import AgentRegistryRepository
from ai_agent.db.conversation_repository import ConversationRepository
from ai_agent.features.conversation_summary import schedule_summary_regeneration
from ai_agent.features.supervisor.schemas import (
    AGENT_AUDIT_GUARDIAN,
    AGENT_CRM,
    AGENT_FINANCE,
    AGENT_HR,
    AGENT_INVENTORY,
    AGENT_SALES_COACH,
    SupervisorEvent,
)
from ai_agent.features.supervisor.service import SupervisorService

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from ai_agent.api.v1.schemas.chat import AttachmentData
    from ai_agent.cache.response_cache import ResponseCache
    from ai_agent.core.llm_router import LlmRouter
    from ai_agent.features.conversation_summary import ConversationSummaryStore
    from ai_agent.features.crm.gateway import CrmGatewayPort
    from ai_agent.features.crm.memory import MemoryService
    from ai_agent.features.finance.gateway import FinanceGatewayPort
    from ai_agent.features.hr_copilot.service import HrCopilotService
    from ai_agent.features.nl_query.gateway import InventoryGatewayPort
    from ai_agent.features.rag.retrieval.service import RagRetrievalService
    from ai_agent.features.supervisor.delegates import (
        CoachSuggestionPort,
        ForecastPort,
        GuardianReportPort,
    )


class _ConversationSummaryStore:
    """Graph-layer adapter from :class:`ConversationRepository` to the summary store.

    Owns the session and its commit, so the ``features`` layer never imports
    ``ai_agent.db`` (import-linter contract). The same adapter is reused for
    the fire-and-forget regeneration path with a fresh background session.
    """

    def __init__(self, repo: ConversationRepository, session: AsyncSession) -> None:
        self._repo = repo
        self._session = session

    async def get_summary(self, *, tenant_id: Any, conversation_id: Any) -> dict[str, Any] | None:
        return await self._repo.get_summary(tenant_id=tenant_id, conversation_id=conversation_id)

    async def get_messages(
        self, *, tenant_id: Any, conversation_id: Any, limit: int | None = None
    ) -> list[dict[str, Any]]:
        return await self._repo.get_messages(
            tenant_id=tenant_id, conversation_id=conversation_id, limit=limit
        )

    async def update_summary(
        self, *, tenant_id: Any, conversation_id: Any, summary_text: str
    ) -> bool:
        return await self._repo.update_summary(
            tenant_id=tenant_id, conversation_id=conversation_id, summary_text=summary_text
        )

    async def commit(self) -> None:
        await self._session.commit()


class SupervisorRuntime:
    """Resolves registry-provisioned leaves and streams one supervisor turn."""

    REGISTERED_AGENTS: tuple[str, ...] = (
        AGENT_INVENTORY,
        AGENT_HR,
        AGENT_CRM,
        AGENT_FINANCE,
        AGENT_SALES_COACH,
        AGENT_AUDIT_GUARDIAN,
    )

    def __init__(
        self,
        *,
        session: AsyncSession,
        llm_router: LlmRouter,
        gateway_factory: Callable[[], Awaitable[InventoryGatewayPort]],
        rag: RagRetrievalService | None = None,
        hr_copilot: HrCopilotService | None = None,
        crm_gateway_factory: Callable[[], Awaitable[CrmGatewayPort]] | None = None,
        finance_gateway_factory: Callable[[], Awaitable[FinanceGatewayPort]] | None = None,
        memory_service: MemoryService | None = None,
        forecast: ForecastPort | None = None,
        coach_suggestions: CoachSuggestionPort | None = None,
        guardian_reports: GuardianReportPort | None = None,
        confidence_threshold: float = 0.75,
        classification_cache: ResponseCache | None = None,
        response_cache: ResponseCache | None = None,
        tool_cache: ResponseCache | None = None,
        classification_cache_ttl_seconds: int = 300,
        response_cache_ttl_seconds: int = 300,
        tool_cache_ttl_seconds: int = 60,
    ) -> None:
        self._session = session
        self._llm_router = llm_router
        self._gateway_factory = gateway_factory
        self._rag = rag
        self._hr_copilot = hr_copilot
        self._crm_gateway_factory = crm_gateway_factory
        self._finance_gateway_factory = finance_gateway_factory
        self._memory_service = memory_service
        self._forecast = forecast
        self._coach_suggestions = coach_suggestions
        self._guardian_reports = guardian_reports
        self._confidence_threshold = confidence_threshold
        self._classification_cache = classification_cache
        self._response_cache = response_cache
        self._tool_cache = tool_cache
        self._classification_cache_ttl_seconds = classification_cache_ttl_seconds
        self._response_cache_ttl_seconds = response_cache_ttl_seconds
        self._tool_cache_ttl_seconds = tool_cache_ttl_seconds

    async def stream_answer(
        self,
        *,
        query: str,
        attachments: list[AttachmentData] | None = None,
        conversation_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AsyncIterator[SupervisorEvent]:
        """Stream one full turn; registry provisioned-state is read per turn."""
        service = await self._build_service()
        async for event in service.stream_answer(
            query=query,
            attachments=attachments,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
        ):
            yield event

    async def _build_service(self) -> SupervisorService:
        repo = AgentRegistryRepository(self._session)
        provisioned = {name: await repo.get_enabled(name) for name in self.REGISTERED_AGENTS}

        # Rolling conversation summary (SKY-100): the request-bound store reads
        # the summary for the current turn; regeneration runs on a fresh
        # session so it survives the request scope and never touches this
        # session's transaction.
        conversation_repo = ConversationRepository(self._session)
        summary_store = _ConversationSummaryStore(conversation_repo, self._session)

        async def _fresh_summary_store() -> ConversationSummaryStore:
            from ai_agent.db.session import async_session_factory

            session = async_session_factory()
            return _ConversationSummaryStore(ConversationRepository(session), session)

        def _schedule_summary(conversation_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
            schedule_summary_regeneration(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                llm_router=self._llm_router,
                store_factory=_fresh_summary_store,
            )

        return SupervisorService(
            llm_router=self._llm_router,
            gateway_factory=self._gateway_factory,
            rag=self._rag,
            hr_copilot=self._hr_copilot,
            crm_gateway_factory=self._crm_gateway_factory,
            finance_gateway_factory=self._finance_gateway_factory,
            memory_service=self._memory_service,
            forecast=self._forecast,
            coach_suggestions=self._coach_suggestions,
            guardian_reports=self._guardian_reports,
            conversation_history=conversation_repo,
            conversation_summary=summary_store,
            summary_regenerator=_schedule_summary,
            provisioned=provisioned,
            confidence_threshold=self._confidence_threshold,
            classification_cache=self._classification_cache,
            response_cache=self._response_cache,
            tool_cache=self._tool_cache,
            classification_cache_ttl_seconds=self._classification_cache_ttl_seconds,
            response_cache_ttl_seconds=self._response_cache_ttl_seconds,
            tool_cache_ttl_seconds=self._tool_cache_ttl_seconds,
        )
