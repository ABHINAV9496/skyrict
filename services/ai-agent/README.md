# Skyrict AI Agent Service

Provider-agnostic AI infrastructure for the Skyrict platform (SKY-57).

The ai-agent service owns:

- **LLM routing** — configurable providers (OpenRouter, Groq, OpenAI-compatible,
  and others) behind one abstract interface, with a primary → fallback chain
  and a typed `ai_unavailable` error contract when every provider fails.
- **Shared AI tables** — `ai_query_log`, `ai_suggestions`, `ai_anomalies`,
  `agent_registry`, `ai_audit_log` in the shared PostgreSQL database, migrated
  by this service under its own Alembic chain (`alembic_version_ai`).
- **Inventory AI engines** — thin-but-real NL query parsing, restock
  suggestions, and anomaly detection (RAG/LangGraph arrive in SKY-58/SKY-59).
- **Audit logging** — every AI action recorded per the inventory AI spec,
  Appendix B.

## Architecture boundary

```
Core monolith (/api/v1/ai/*)          ai-agent service
┌───────────────────────────┐   ┌─────────────────────────────────────┐
│ JWT auth                  │   │ routers → engines → llm_router      │
│ Permission checks         │──▶│        → provider registry          │
│ (BEFORE forwarding)       │   │        → provider adapter → LLM API │
└───────────────────────────┘   └─────────────────────────────────────┘
```

- The core monolith is the **only** ingress: it verifies permissions before
  forwarding. AI never bypasses human authorization.
- Business modules (`nl_engine`, `restock_analyzer`, `anomaly_detector`) never
  know which provider or model served a request.
- Provider adapters are the only code that talks to vendor APIs.

## Local development

Prerequisites: Python 3.12+ (uv workspace), Docker (Postgres + Redis), and the
shared dev JWT keys.

```bash
# 1. Generate dev JWT keys once (same keypair identity/core use)
uv run python -m skyrict_testing.generate_keys

# 2. Start infrastructure
docker compose -f infra/docker/docker-compose.yml up -d postgres redis

# 3. Sync the workspace (picks up services/ai-agent automatically)
uv sync --all-packages --group dev

# 4. Run migrations (once the Alembic chain lands in this service)
#    uv run --directory services/ai-agent ai-agent migrate

# 5. Serve on http://localhost:8002
uv run --directory services/ai-agent ai-agent serve --reload
```

Health probes:

```bash
curl http://localhost:8002/api/v1/health   # liveness — {"status":"healthy","service":"ai-agent"}
curl http://localhost:8002/api/v1/ready    # readiness — db_ok / redis_ok checks
```

Dev tenant routing uses the `X-Tenant-Slug` header (injected by nginx in the
full compose stack) exactly like core/identity.

## Configuration

All variables are prefixed `AI_` (see `.env.example`). Required:
`AI_DATABASE_URL`, `AI_REDIS_URL`, `AI_JWT_PUBLIC_KEY_PATH`,
`AI_JWKS_ISSUER`, `AI_JWKS_AUDIENCE`.

Providers are **optional by design**: with none configured the service boots
and serves health; AI requests return typed `503 ai_unavailable`. Provider
configuration (`AI_PROVIDER`/`AI_MODEL`/`AI_BASE_URL`/`AI_API_KEY` plus the
`AI_FALLBACK_*` quartet) is documented alongside the routing layer.

## Testing

```bash
uv run pytest services/ai-agent/tests/unit/
```

Integration tests requiring Postgres skip automatically when the database is
unavailable locally.
