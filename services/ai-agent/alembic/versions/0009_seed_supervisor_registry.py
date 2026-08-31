"""Register the supervisor + module agents for the Agents shell chat (SKY-60).

The ``agent_registry`` now serves TWO purposes (documented here so operators
can tell them apart):

1. LangGraph module agents — rows the checkpointed runtime invokes
   (``restock_advisor``, etc.). ``module`` must expose ``build_graph(deps)``.
2. Streaming chat agents — supervisor leaves. ``enabled`` gates provisioning:
   the supervisor's ``stream_answer`` reads ``get_enabled(name)`` per turn and
   streams a clean "not provisioned yet" abstention for disabled rows
   (Q&A decision #6). ``module`` records the owning feature package for
   operator visibility; these agents are never invoked through the
   checkpointed runtime.

Seeds (all ``ON CONFLICT (name) DO NOTHING`` — operator edits win):

- ``supervisor``             enabled  — the routing facade itself.
- ``inventory_monitor``      enabled  — delegates via nl_query gateway +
  forecast + RAG (backends exist).
- ``hr_copilot``             enabled  — delegates through the grounded HR
  Copilot service (backends exist).
- ``crm_assistant``          disabled — leaves stream the provisioned
  abstention until the CRM backend lands (migration flips ``enabled``).
- ``finance_assistant``      disabled — same slot-based rollout.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_SUPERVISOR_AGENTS = (
    "supervisor",
    "inventory_monitor",
    "hr_copilot",
    "crm_assistant",
    "finance_assistant",
)


def upgrade() -> None:
    op.execute(
        "INSERT INTO agent_registry (name, module, graph_id, enabled, tools) VALUES "
        "('supervisor', 'ai_agent.graphs.supervisor', 'supervisor', true, '[]'::jsonb), "
        "('inventory_monitor', 'ai_agent.features.supervisor.delegates', "
        "'inventory_monitor', true, '[]'::jsonb), "
        "('hr_copilot', 'ai_agent.features.supervisor.delegates', 'hr_copilot', "
        "true, '[]'::jsonb), "
        "('crm_assistant', 'ai_agent.features.supervisor.delegates', "
        "'crm_assistant', false, '[]'::jsonb), "
        "('finance_assistant', 'ai_agent.features.supervisor.delegates', "
        "'finance_assistant', false, '[]'::jsonb) "
        "ON CONFLICT (name) DO NOTHING"
    )


def downgrade() -> None:
    names = ", ".join(f"'{name}'" for name in _SUPERVISOR_AGENTS)
    op.execute(f"DELETE FROM agent_registry WHERE name IN ({names})")
