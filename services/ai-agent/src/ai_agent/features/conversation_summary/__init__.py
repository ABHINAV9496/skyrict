"""Rolling conversation summary (SKY-100).

A background service folds OLDER conversation messages - everything before the
supervisor's recent history window - into a compact rolling summary when the
conversation overflows the supervisor's context budget. The stored summary is
injected at the top of the supervisor prompt and the recent window is trimmed
with the ``ContextBudgetManager``, so long conversations keep working within
budget.

The summary is internal context-compaction state: it is stored on the
conversation row but deliberately excluded from the conversation API payloads,
so it never surfaces to the UI.

This package is the pure feature slice: it depends only on injected ports
(repository store + LLM router) and never imports ``ai_agent.db`` directly
(import-linter contract).
"""

from ai_agent.features.conversation_summary.service import (
    ConversationSummaryStore,
    is_summary_fresh,
    schedule_summary_regeneration,
)

__all__ = [
    "ConversationSummaryStore",
    "is_summary_fresh",
    "schedule_summary_regeneration",
]
