"""HR Copilot agent (spec §9, feature 5).

Registered in ``agent_registry`` as
``{name: "hr_copilot", module: "ai_agent.features.hr_copilot.engine",
enabled: true}``. The tool surface is deliberately narrow: aggregate (L1) HR
reads and the tenant's leave policy — never individual rows. All exchanges
pass through the LLM redaction gate inside ``LlmRouter``.
"""

from __future__ import annotations

from ai_agent.features.hr_copilot.engine import HrCopilotEngine, HrCopilotResult
from ai_agent.features.hr_copilot.gateway import (
    HrGatewayPort,
    HrLeavePolicyCtx,
    HrOverviewCtx,
    HrTenureCtx,
    HttpHrGateway,
)
from ai_agent.features.hr_copilot.service import HrCopilotService

__all__ = [
    "HrCopilotEngine",
    "HrCopilotResult",
    "HrCopilotService",
    "HrGatewayPort",
    "HrLeavePolicyCtx",
    "HrOverviewCtx",
    "HrTenureCtx",
    "HttpHrGateway",
]
