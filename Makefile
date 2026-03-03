# Aragora Makefile
# Common development tasks for the Aragora multi-agent debate platform

.PHONY: help install dev test test-e2e lint format typecheck check check-all ci ci-required guard guard-strict clean clean-all clean-runtime clean-runtime-dry docs serve docker demo demo-docker demo-stop quickstart quickstart-live worktree-ensure worktree-reconcile worktree-cleanup worktree-maintain worktree-maintainer-install worktree-maintainer-uninstall worktree-maintainer-status codex-session branch-start pr-open

# Default target
help:
	@echo "Aragora Development Commands"
	@echo "============================"
	@echo ""
	@echo "Setup:"
	@echo "  make install      Install production dependencies"
	@echo "  make dev          Install development dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test         Run all tests"
	@echo "  make test-fast    Run fast tests only (no slow/e2e/integration/benchmarks/load/performance)"
	@echo "  make test-fast-log Run fast tests with tee'd log under .nomic/logs"
	@echo "  make test-unit    Run unit tests only (fastest)"
	@echo "  make test-core    Run core module tests (debate/core/memory)"
	@echo "  make test-parallel Run tests in parallel (-n auto)"
	@echo "  make test-cov     Run tests with coverage"
	@echo "  make test-watch   Run tests in watch mode"
	@echo "  make test-e2e     Run end-to-end tests"
	@echo "  make test-smoke   Quick import smoke test"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint         Run linter (ruff)"
	@echo "  make format       Format code (ruff format)"
	@echo "  make typecheck    Run type checker (mypy)"
	@echo "  make check        Run all checks (lint + typecheck)"
	@echo "  make check-all    Run lint + typecheck + tests with coverage"
	@echo "  make ci           CI pipeline (lint + typecheck + fast tests)"
	@echo "  make ci-required  Run required GitHub checks locally"
	@echo "  make guard        Check repo hygiene (tracked artifacts)"
	@echo "  make guard-strict Check repo hygiene (tracked + untracked artifacts)"
	@echo ""
	@echo "Demo:"
	@echo "  make demo         Launch full-stack demo locally (backend + frontend)"
	@echo "  make demo-docker  Launch demo via Docker Compose"
	@echo "  make demo-stop    Stop running demo"
	@echo "  make quickstart   Docker quickstart (mock agents, zero config)"
	@echo "  make quickstart-live Docker quickstart with real agents (needs .env)"
	@echo ""
	@echo "Development:"
	@echo "  make serve        Start development server"
	@echo "  make repl         Start interactive debate REPL"
	@echo "  make doctor       Run system health checks"
	@echo "  make branch-start TYPE=feat SLUG=my-change [BASE=origin/main]"
	@echo "                    Create and switch to a feature branch from base ref"
	@echo "  make pr-open [BASE=main] [ARGS='--draft']"
	@echo "                    Push current branch and open/update PR via gh"
	@echo "  make codex-session Start Codex in an auto-managed worktree"
	@echo "  make worktree-ensure Ensure/reuse a managed Codex worktree"
	@echo "  make worktree-reconcile Rebase managed Codex worktrees onto main"
	@echo "  make worktree-cleanup Cleanup stale managed Codex worktrees"
	@echo "  make worktree-maintain Reconcile+cleanup managed Codex worktrees"
	@echo "  make worktree-maintainer-install Install launchd auto-maintainer (macOS)"
	@echo "  make worktree-maintainer-uninstall Uninstall launchd auto-maintainer"
	@echo "  make worktree-maintainer-status Show launchd auto-maintainer status"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs         Generate documentation"
	@echo "  make docs-serve   Serve documentation locally"
	@echo "  make openapi      Export OpenAPI schema to docs/api"
	@echo ""
	@echo "Docker:"
	@echo "  make docker       Build Docker image"
	@echo "  make docker-run   Run Docker container"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean        Remove build artifacts"
	@echo "  make clean-all    Remove all generated files"
	@echo "  make clean-runtime Move runtime DB artifacts to ARAGORA_DATA_DIR"
	@echo "  make clean-runtime-dry Preview runtime cleanup actions"

# Setup
install:
	pip install -e .

dev:
	pip install -e ".[dev,research,mcp]"
	pre-commit install

# Testing
test:
	pytest tests/ -v --timeout=120

test-fast:
	pytest tests/ -v --timeout=60 -m "not slow and not e2e and not load and not integration and not integration_minimal and not benchmark and not performance" --ignore=tests/integration --ignore=tests/benchmarks --ignore=tests/load --ignore=tests/performance

test-fast-log:
	@mkdir -p .nomic/logs
	@LOG_FILE=.nomic/logs/test-fast-$$(date +%Y%m%d-%H%M%S).log; \
		echo "Logging to $$LOG_FILE"; \
		LOG_FILE="$$LOG_FILE" bash -lc 'set -o pipefail; pytest tests/ -v --timeout=60 -m "not slow and not e2e and not load and not integration and not integration_minimal and not benchmark and not performance" --ignore=tests/integration --ignore=tests/benchmarks --ignore=tests/load --ignore=tests/performance 2>&1 | tee "$$LOG_FILE"'; \
		echo "Done. Log: $$LOG_FILE"

test-unit:
	pytest tests/ -v --timeout=30 -m unit --ignore=tests/integration --ignore=tests/e2e --ignore=tests/benchmarks -q

test-core:
	pytest tests/debate/ tests/core/ tests/memory/ -v --timeout=60

test-parallel:
	pytest tests/ -v --timeout=120 -n auto -m "not serial"

test-cov:
	pytest tests/ -v --timeout=120 --cov=aragora --cov-report=html --cov-report=term

test-watch:
	pytest tests/ -v --timeout=60 -f

test-e2e:
	pytest tests/e2e/ -v --timeout=120 -m "not slow and not load"

test-smoke:
	@echo "Running smoke tests..."
	python3 -c "from aragora.debate.orchestrator import Arena; from aragora.core import Environment; print('Core imports OK')"
	python3 -c "from aragora.server.unified_server import run_unified_server; print('Server imports OK')"
	python3 -c "from aragora.memory.continuum import ContinuumMemory; print('Memory imports OK')"
	@echo "Smoke tests passed!"

# Code Quality
lint:
	ruff check aragora/ tests/

format:
	ruff format aragora/ tests/
	ruff check --fix aragora/ tests/

typecheck:
	mypy aragora/ --ignore-missing-imports

check: lint typecheck

check-all: lint typecheck test-cov

ci: lint typecheck test-fast

ci-required:
	@echo "Running required GitHub checks locally..."
	ruff check aragora/ tests/ scripts/
	mypy aragora/ --ignore-missing-imports
	python scripts/check_version_alignment.py
	python scripts/check_sdk_parity.py --strict --baseline scripts/baselines/check_sdk_parity.json --budget scripts/baselines/check_sdk_parity_budget.json
	python scripts/check_sdk_namespace_parity.py --strict --baseline scripts/baselines/check_sdk_namespace_parity.json
	python scripts/check_cross_sdk_parity.py --strict --baseline scripts/baselines/cross_sdk_parity.json
	python scripts/generate_openapi.py --output /tmp/openapi_ci_required.json --format json --quiet
	python scripts/add_openapi_operation_ids.py --spec /tmp/openapi_ci_required.json
	python scripts/add_openapi_param_descriptions.py --spec /tmp/openapi_ci_required.json
	python scripts/add_openapi_descriptions.py --spec /tmp/openapi_ci_required.json
	python scripts/verify_sdk_contracts.py --strict --baseline scripts/baselines/verify_sdk_contracts.json --extra-spec /tmp/openapi_ci_required.json
	python scripts/validate_openapi_routes.py --spec /tmp/openapi_ci_required.json --fail-on-missing --baseline scripts/baselines/validate_openapi_routes.json

guard:
	python3 scripts/guard_repo_clean.py

guard-strict:
	python3 scripts/guard_repo_clean.py --check-working-tree

# Demo
demo:
	@bash scripts/demo.sh

demo-docker:
	docker compose -f deploy/demo/docker-compose.yml up --build

demo-stop:
	@bash scripts/demo.sh --stop

quickstart:
	docker compose -f docker-compose.quickstart.yml up --build

quickstart-live:
	docker compose -f docker-compose.simple.yml up --build

# Development
serve:
	python -m aragora.server --api-port 8080 --ws-port 8765

repl:
	python -m aragora.cli.main repl

doctor:
	python -m aragora.cli.doctor

claude-wt:
	./scripts/claude-wt

codex-session:
	./scripts/codex_session.sh

worktree-ensure:
	python -m aragora.cli.main worktree autopilot ensure --agent codex --base main

worktree-reconcile:
	python -m aragora.cli.main worktree autopilot reconcile --all --base main

worktree-cleanup:
	python -m aragora.cli.main worktree autopilot cleanup --base main --ttl-hours 24

worktree-maintain:
	python -m aragora.cli.main worktree autopilot maintain --base main --strategy merge --ttl-hours 24 --no-delete-branches

worktree-maintainer-install:
	./scripts/install_worktree_maintainer_launchd.sh --interval-seconds 300 --base main --strategy merge --ttl-hours 24

worktree-maintainer-uninstall:
	./scripts/uninstall_worktree_maintainer_launchd.sh

worktree-maintainer-status:
	./scripts/status_worktree_maintainer_launchd.sh

branch-start:
	@if [ -z "$(TYPE)" ] || [ -z "$(SLUG)" ]; then \
		echo "Usage: make branch-start TYPE=feat SLUG=my-change [BASE=origin/main]"; \
		exit 1; \
	fi
	@if [ -n "$(BASE)" ]; then \
		bash scripts/start_feature_branch.sh "$(TYPE)" "$(SLUG)" --base "$(BASE)"; \
	else \
		bash scripts/start_feature_branch.sh "$(TYPE)" "$(SLUG)"; \
	fi

pr-open:
	@cmd="bash scripts/open_pr.sh"; \
	if [ -n "$(BASE)" ]; then cmd="$$cmd --base \"$(BASE)\""; fi; \
	if [ -n "$(ARGS)" ]; then cmd="$$cmd $(ARGS)"; fi; \
	eval "$$cmd"

# Documentation
docs:
	cd docs && mkdocs build

docs-serve:
	cd docs && mkdocs serve

openapi:
	python scripts/export_openapi.py --output-dir docs/api

# Docker
docker:
	docker build -t aragora:latest .

docker-run:
	docker run -p 8080:8080 -p 8765:8765 --env-file .env aragora:latest

# Cleanup
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

clean-all: clean
	rm -rf .venv/
	rm -rf node_modules/
	rm -rf coverage.xml
	rm -rf .coverage

clean-runtime:
	python3 scripts/cleanup_runtime_artifacts.py --apply

clean-runtime-dry:
	python3 scripts/cleanup_runtime_artifacts.py

# Benchmarks
bench:
	pytest tests/ -v --benchmark-only --benchmark-group-by=func

bench-save:
	pytest tests/ -v --benchmark-only --benchmark-save=baseline

# Database
db-migrate:
	python -m aragora.migrations.run

db-reset:
	rm -f ~/.aragora/*.db
	python -m aragora.migrations.run

# Marketplace
marketplace-list:
	python -m aragora.cli.main marketplace list

marketplace-search:
	@read -p "Search query: " query; \
	python -m aragora.cli.main marketplace search "$$query"
