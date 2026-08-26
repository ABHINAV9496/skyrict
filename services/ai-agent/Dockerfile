# =============================================================================
# Skyrict AI Agent Service — Production Dockerfile
#
# Stages:
#   base        Shared deps install (uv sync --no-dev)
#   production  Minimal final image, non-root, no dev deps, no tests
#
# Build:
#   docker build --target production -f services/ai-agent/Dockerfile .
# =============================================================================

# ---------------------------------------------------------------------------
# Stage: base — shared dependency install
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

WORKDIR /app

# System deps needed for asyncpg, cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace root files
COPY pyproject.toml uv.lock ./

# Copy every workspace member pyproject.toml file (for dependency resolution).
# The workspace glob is services/* and libs/* — uv --frozen refuses to resolve
# if a member manifest is missing. READMEs too: hatchling requires the `readme`
# file declared in each pyproject.toml to be present when building the members.
COPY services/identity/pyproject.toml services/identity/
COPY services/identity/README.md services/identity/
COPY services/core/pyproject.toml services/core/
COPY services/core/README.md services/core/
COPY services/ai-agent/pyproject.toml services/ai-agent/
COPY services/ai-agent/README.md services/ai-agent/
COPY libs/skyrict-common/pyproject.toml libs/skyrict-common/
COPY libs/skyrict-common/README.md libs/skyrict-common/
COPY libs/skyrict-events/pyproject.toml libs/skyrict-events/
COPY libs/skyrict-events/README.md libs/skyrict-events/
COPY libs/skyrict-testing/pyproject.toml libs/skyrict-testing/
COPY libs/skyrict-testing/README.md libs/skyrict-testing/

# Install production deps only
RUN uv sync --frozen --no-dev --directory services/ai-agent

# ---------------------------------------------------------------------------
# Stage: production — minimal final image, non-root
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS production

# Security: non-root user
RUN groupadd --gid 1000 skyrict && \
    useradd --uid 1000 --gid skyrict --create-home skyrict

WORKDIR /app

# System deps for runtime (asyncpg, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY the virtual environment from base (no source tree, no tests)
COPY --from=base /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application source (no tests)
COPY services/ai-agent/src services/ai-agent/src
COPY services/ai-agent/alembic.ini services/ai-agent/
COPY services/ai-agent/alembic services/ai-agent/alembic
COPY libs/skyrict-common/src libs/skyrict-common/src

# Set ownership
RUN chown -R skyrict:skyrict /app

USER skyrict

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"]

CMD ["uvicorn", "ai_agent.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--no-access-log"]
