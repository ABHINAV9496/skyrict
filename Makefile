.PHONY: help setup dev test lint migrate seed clean benchmark format check \
	core-dev test-core test-unit-core test-integration-core test-cov-core \
	migrate-core migrate-create-core seed-core build-core lint-core \
	ai-agent-dev test-ai-agent test-unit-ai-agent lint-ai-agent \
	migrate-ai-agent build-ai-agent

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------- Setup ----------

setup: ## Install all dependencies and boot infrastructure
	uv sync
	cd apps/web && pnpm install
	docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.dev.yml up -d
	uv run --directory services/identity alembic upgrade head
	uv run --directory services/core alembic upgrade head

# ---------- Development ----------

dev: ## Start all services in dev mode (identity service + frontend)
	docker compose -f infra/docker/docker-compose.yml up -d postgres redis kafka
	uv run --directory services/identity identity serve --reload

dev-web: ## Start frontend dev server
	cd apps/web && pnpm dev

dev-all: ## Start everything (infra + backend + frontend)
	docker compose -f infra/docker/docker-compose.yml up -d
	uv run --directory services/identity identity serve --reload &
	cd apps/web && pnpm dev

# ---------- Testing ----------

test: ## Run all tests
	uv run pytest services/identity/tests/ -v --tb=short

test-unit: ## Run unit tests only
	uv run pytest services/identity/tests/unit/ -v --tb=short -m unit

test-integration: ## Run integration tests (requires Docker)
	uv run pytest services/identity/tests/integration/ -v --tb=short -m integration

test-cov: ## Run tests with coverage report
	uv run pytest services/identity/tests/ -v --cov=services/identity/src --cov-report=html --cov-report=term

# ---------- Core Service ----------

core-dev: ## Start the core service in dev mode (live reload, port 8001)
	uv run --directory services/core core serve --reload

test-core: ## Run all core tests
	uv run pytest services/core/tests/ -v --tb=short

test-unit-core: ## Run core unit tests only
	uv run pytest services/core/tests/unit/ -v --tb=short -m unit

test-integration-core: ## Run core integration tests (requires Docker)
	uv run pytest services/core/tests/integration/ -v --tb=short -m integration

test-cov-core: ## Run core tests with coverage report
	uv run pytest services/core/tests/ -v --cov=services/core/src --cov-report=html --cov-report=term

migrate-core: ## Run core Alembic migrations (shared DB, alembic_version_core)
	uv run --directory services/core core migrate

migrate-create-core: ## Create a new core migration (usage: make migrate-create-core MSG="...")
	uv run --directory services/core alembic revision --autogenerate -m "$(MSG)"

seed-core: ## Verify core reference data seeded by migration 0001
	uv run --directory services/core core seed

lint-core: ## Lint core only (ruff + mypy + import-linter)
	uv run ruff check services/core/ libs/
	uv run ruff format --check services/core/ libs/
	uv run mypy services/core/src/
	uv run lint-imports --config services/core/import-linter.toml

# ---------- AI Agent Service ----------

ai-agent-dev: ## Start the AI agent service in dev mode (live reload, port 8002)
	uv run --directory services/ai-agent ai-agent serve --reload

test-ai-agent: ## Run all AI agent service tests
	uv run pytest services/ai-agent/tests/ -v --tb=short

test-unit-ai-agent: ## Run AI agent unit tests only
	uv run pytest services/ai-agent/tests/unit/ -v --tb=short -m unit

migrate-ai-agent: ## Run AI agent Alembic migrations (shared DB, alembic_version_ai)
	uv run --directory services/ai-agent ai-agent migrate

build-ai-agent: ## Build AI agent service Docker image
	docker build -t skyrict/ai-agent:latest -f services/ai-agent/Dockerfile .

lint-ai-agent: ## Lint AI agent only (ruff + mypy + import-linter)
	uv run ruff check services/ai-agent/
	uv run ruff format --check services/ai-agent/
	uv run mypy services/ai-agent/src/
	uv run lint-imports --config services/ai-agent/import-linter.toml

# ---------- Linting ----------

lint: ## Run ruff check + ruff format check + mypy
	uv run ruff check services/ libs/
	uv run ruff format --check services/ libs/
	uv run mypy services/identity/src/

lint-full: ## Full lint: ruff + flake8 + mypy + bandit
	uv run ruff check services/ libs/
	uv run flake8 services/ libs/
	uv run mypy services/identity/src/
	uv run bandit -r services/ libs/

format: ## Auto-format code (ruff)
	uv run ruff check --fix services/ libs/
	uv run ruff format services/ libs/

format-legacy: ## Auto-format using isort + black
	uv run isort services/ libs/
	uv run black services/ libs/

# ---------- Database ----------

migrate: ## Run pending Alembic migrations
	uv run --directory services/identity identity migrate

migrate-create: ## Create a new migration (usage: make migrate-create MSG="add users table")
	uv run --directory services/identity alembic revision --autogenerate -m "$(MSG)"

seed: ## Load reference data
	uv run --directory services/identity identity seed

# ---------- Build ----------

build: ## Build identity service Docker image
	docker build -t skyrict/identity:latest -f services/identity/Dockerfile .

build-core: ## Build core service Docker image
	docker build -t skyrict/core:latest -f services/core/Dockerfile .

build-web: ## Build frontend
	cd apps/web && pnpm build

# ---------- Cleanup ----------

clean: ## Remove build artifacts, caches, venvs
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .next -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ *.egg-info/

# ---------- Benchmark ----------

benchmark: ## Run performance benchmarks
	uv run pytest services/identity/tests/ -v -m slow --benchmark-only

# ---------- Hooks ----------

hooks: ## Install git hooks
	./scripts/setup-hooks.sh

# ---------- CI ----------

check: lint test lint-core test-core lint-ai-agent test-ai-agent ## Run full CI check locally (lint + test + core + ai-agent)
