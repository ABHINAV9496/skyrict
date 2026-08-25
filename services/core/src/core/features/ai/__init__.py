"""AI assistant proxy — core-side edge for the ai-agent microservice.

Every route here enforces permissions BEFORE forwarding (ticket
[AI-INFRA-001]: "permissionless call rejected 403 at monolith"; spec §1.4:
the JWT is forwarded and re-verified by ai-agent — AI is a proxy, not a
bypass). The router is intentionally thin: all transport behaviour lives
in :mod:`core.features.ai.proxy` so it is unit-testable without FastAPI.
"""
