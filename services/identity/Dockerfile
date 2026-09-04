# =============================================================================
# Skyrict Identity Service - Production Dockerfile
#
# Stages:
#   base        Shared deps install (uv sync --no-dev)
#   production  Minimal final image, non-root, no dev deps, no tests
#
# Local development uses services/identity/Dockerfile.dev (live reload,
# dev deps, tests) via docker-compose.dev.yml.
#
# Build:
#   docker build --target production -f services/identity/Dockerfile .
# =============================================================================

# ---------------------------------------------------------------------------
# Stage: base - shared dependency install
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

WORKDIR /app

# System deps needed for asyncpg, cryptography (RSA), argon2-cffi
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace root files
COPY pyproject.toml uv.lock ./

# Copy every workspace member pyproject.toml file (for dependency resolution).
# The workspace glob is services/* and libs/* - uv --frozen refuses to resolve
# if a member manifest is missing. READMEs too: hatchling requires the `readme`
# file declared in each pyproject.toml to be present when building the members.
COPY services/identity/pyproject.toml services/identity/
COPY services/identity/README.md services/identity/
COPY services/core/pyproject.toml services/core/
COPY services/core/README.md services/core/
COPY libs/skyrict-common/pyproject.toml libs/skyrict-common/
COPY libs/skyrict-common/README.md libs/skyrict-common/
COPY libs/skyrict-events/pyproject.toml libs/skyrict-events/
COPY libs/skyrict-events/README.md libs/skyrict-events/
COPY libs/skyrict-testing/pyproject.toml libs/skyrict-testing/
COPY libs/skyrict-testing/README.md libs/skyrict-testing/

# Install production deps only
RUN uv sync --frozen --no-dev --directory services/identity

# ---------------------------------------------------------------------------
# Stage: production - minimal final image, non-root
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS production

# Security: non-root user
RUN groupadd --gid 1000 skyrict && \
    useradd --uid 1000 --gid skyrict --create-home skyrict

WORKDIR /app

# System deps for runtime (asyncpg, argon2-cffi, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY the virtual environment from base (no source tree, no tests)
COPY --from=base /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application source (no tests, no tests/fixtures/)
COPY services/identity/src services/identity/src
COPY libs/skyrict-common/src libs/skyrict-common/src

# Copy alembic migrations (needed at runtime for DB migrations)
COPY services/identity/alembic services/identity/alembic
COPY services/identity/alembic.ini services/identity/alembic.ini

# Set ownership
RUN chown -R skyrict:skyrict /app

USER skyrict

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"]

CMD ["uvicorn", "identity.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--no-access-log", "--no-proxy-headers"]
