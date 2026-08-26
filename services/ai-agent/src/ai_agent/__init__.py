"""Skyrict AI agent service — provider-agnostic AI infrastructure boundary.

The service owns:
  - provider-agnostic LLM routing (configurable providers, fallback chain)
  - the shared AI tables (ai_query_log, ai_suggestions, ai_anomalies,
    agent_registry, ai_audit_log) and their Alembic chain (alembic_version_ai)
  - the thin-but-real inventory AI engines (NL queries, restock suggestions,
    anomaly detection)
  - audit logging for every AI action

It is reached through the core monolith proxy at ``/api/v1/ai/*``, which
enforces authentication and permissions BEFORE forwarding. AI is a controlled
proxy — never an authorization bypass.
"""

from __future__ import annotations

__version__ = "0.1.0"
