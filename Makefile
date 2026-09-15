# Aragora Makefile
# Common development tasks for the Aragora multi-agent debate platform

.PHONY: help install dev test test-e2e lint format typecheck check check-all ci ci-required guard guard-strict clean clean-all clean-runtime clean-runtime-dry docs docs-check serve docker demo demo-docker demo-stop quickstart quickstart-live worktree-ensure worktree-reconcile worktree-cleanup worktree-maintain worktree-maintainer-install worktree-maintainer-uninstall worktree-maintainer-status worktree-inspect worktree-safe-remove codex-session branch-start pr-open sweep-stale-lanes sweep-stale-lanes-apply

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
	@echo "  make worktree-inspect WT_PATH=/abs/path"
	@echo "                    Inspect a side worktree for active-session/open-PR blockers"
	@echo "  make worktree-safe-remove WT_PATH=/abs/path [DELETE_BRANCH=1] [PURGE_PATH=1]"
	@echo "                    Safely remove a side worktree after guard checks"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs         Generate documentation"
	@echo "  make docs-check   Run docs consistency lint"
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
	@echo ""
	@echo "Hygiene:"
	@echo "  make sweep-stale-lanes       Dry-run lane-registry staleness sweeper"
	@echo "  make sweep-stale-lanes-apply Apply expirations to stale active lane rows"
	@echo ""
	@echo "Readiness gate (per-app; put .venv/bin on PATH first):"
	@echo "  make readiness-lint      Lint every app (root, debate, verify, live, docs, vscode, operator)"
	@echo "  make readiness-typecheck Typecheck every app"
	@echo "  make readiness-test      Run every app's fast test suite"
	@echo "  make readiness-<kind>-<app>  One app only, e.g. readiness-test-live"
	@echo "                    Absent toolchains print 'SKIP <app>: <reason>' and exit 0"
	@echo "                    READINESS_BASE_REF=origin/main  READINESS_EXTRA_TESTS='tests/<area>'"

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

worktree-inspect:
	@if [ -z "$(WT_PATH)" ]; then \
		echo "Usage: make worktree-inspect WT_PATH=/abs/path"; \
		exit 1; \
	fi
	python3 scripts/safe_worktree_cleanup.py inspect "$(WT_PATH)"

worktree-safe-remove:
	@if [ -z "$(WT_PATH)" ]; then \
		echo "Usage: make worktree-safe-remove WT_PATH=/abs/path [DELETE_BRANCH=1] [PURGE_PATH=1]"; \
		exit 1; \
	fi
	@cmd="python3 scripts/safe_worktree_cleanup.py remove \"$(WT_PATH)\""; \
	if [ -n "$(DELETE_BRANCH)" ]; then cmd="$$cmd --delete-branch"; fi; \
	if [ -n "$(PURGE_PATH)" ]; then cmd="$$cmd --purge-path"; fi; \
	eval "$$cmd"

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

docs-check:
	python3 scripts/check_docs_consistency.py

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

# Hygiene
# ---------------------------------------------------------------------------
# `sweep-stale-lanes` is a dry-run audit of `.aragora/agent-bridge/lanes.json`:
# it detects active claims whose owning branch/worktree/heartbeat indicate the
# session has crashed, and reports them as candidates for expiration.
# `sweep-stale-lanes-apply` is the mutating escalation (rewrites stale rows
# in-place with status=expired). See `docs/dev/LANE_REGISTRY_SWEEP_CADENCE.md`
# for the operating cadence and recovery procedure.
sweep-stale-lanes:
	python3 scripts/sweep_stale_lane_claims.py --dry-run

sweep-stale-lanes-apply:
	python3 scripts/sweep_stale_lane_claims.py --apply

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

# ---------------------------------------------------------------------------
# Readiness gate
# ---------------------------------------------------------------------------
# Three aggregators fan out to one target per app and kind:
#   readiness-{lint,typecheck,test}-{root,debate,verify,live,docs,vscode,operator}
# Contract for every per-app target:
#   * runnable alone from any cwd (`make -C <repo> readiness-lint-live`);
#     recipes `cd <app> && ...` rather than depending on the caller's cwd;
#   * toolchain detected with `command -v` (plus node_modules presence);
#     an absent toolchain prints `SKIP <app>: <reason>` and exits 0 so the
#     aggregate stays usable on any machine;
#   * a present-but-failing tool fails the target, and make names it
#     (`*** [readiness-lint-root] Error 1`);
#   * no hardcoded ports; nothing here starts a server;
#   * prints `[readiness] <target> ok (<seconds>s)` on success.
# Later milestones extend the per-app recipes in place and never rename them.
# Ratchet invocations (`python scripts/ci/check_tool_baseline.py --tool <t>
# --baseline scripts/baselines/<app>-<tool>[-<variant>].json -- <cmd>`) are
# wired into readiness-lint-<app> from M2 onward; keep each `--baseline` path
# on its own physical line so gate wiring stays greppable.
# Heavy steps (`next build`, `docusaurus build`, size-limit, test-electron,
# envtest, golangci-lint, docker build) are NEVER part of these aggregates.
# The names `readiness-heavy-<app>` are reserved for them: readiness-heavy-live
# (M5), readiness-heavy-docs (M7), readiness-heavy-vscode (M8),
# readiness-heavy-operator (M9). They follow the same SKIP contract and are
# run by CI, not by the milestone gate.

# Base ref for the changed-file mypy gate (CI's PR-time typecheck command).
READINESS_BASE_REF ?= origin/main
# Extra pytest paths for readiness-test-root, e.g. READINESS_EXTRA_TESTS="tests/utils".
READINESS_EXTRA_TESTS ?=
# Where readiness-test-<app> writes junit XML. Defaults outside the worktree so
# the gate leaves no untracked artifacts behind.
READINESS_JUNIT_DIR ?= /tmp/aragora-readiness/junit
# Machine-readable ratchet summaries, kept outside the worktree by default.
READINESS_REPORT_DIR ?= /tmp/aragora-readiness/ratchet-reports
# Pinned duplicate-code runner, subject to the root .npmrc release cooldown.
JSCPD_VERSION ?= 5.1.1
# Coverage floor for readiness-test-root, read from [tool.coverage.report]
# fail_under in pyproject.toml so the Makefile and pytest agree on one number.
READINESS_ROOT_COV_FAIL_UNDER = $$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["tool"]["coverage"]["report"]["fail_under"])')
READINESS_DEBATE_COV_FAIL_UNDER = $$(python3 -c 'import tomllib; print(tomllib.load(open("aragora-debate/pyproject.toml","rb"))["tool"]["coverage"]["report"]["fail_under"])')
READINESS_VERIFY_COV_FAIL_UNDER = $$(python3 -c 'import tomllib; print(tomllib.load(open("aragora-verify/pyproject.toml","rb"))["tool"]["coverage"]["report"]["fail_under"])')

READINESS_T0 = start=$$(date +%s)
READINESS_DONE = echo "[readiness] $@ ok ($$(( $$(date +%s) - start ))s)"

.PHONY: readiness-lint readiness-typecheck readiness-test
.PHONY: readiness-lint-root readiness-lint-debate readiness-lint-verify readiness-lint-live readiness-lint-docs readiness-lint-vscode readiness-lint-operator
.PHONY: readiness-typecheck-root readiness-typecheck-debate readiness-typecheck-verify readiness-typecheck-live readiness-typecheck-docs readiness-typecheck-vscode readiness-typecheck-operator
.PHONY: readiness-test-root readiness-test-debate readiness-test-verify readiness-test-live readiness-test-docs readiness-test-vscode readiness-test-operator

readiness-lint: readiness-lint-root readiness-lint-debate readiness-lint-verify readiness-lint-live readiness-lint-docs readiness-lint-vscode readiness-lint-operator
readiness-typecheck: readiness-typecheck-root readiness-typecheck-debate readiness-typecheck-verify readiness-typecheck-live readiness-typecheck-docs readiness-typecheck-vscode readiness-typecheck-operator
readiness-test: readiness-test-root readiness-test-debate readiness-test-verify readiness-test-live readiness-test-docs readiness-test-vscode readiness-test-operator

# --- root (Python package `aragora/`, tests `tests/`, scripts) --------------
readiness-lint-root:
	@$(READINESS_T0); \
	command -v ruff >/dev/null 2>&1 || { echo "SKIP root: ruff not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v python3 >/dev/null 2>&1 || { echo "SKIP root: python3 not found"; exit 0; }; \
	command -v vulture >/dev/null 2>&1 || { echo "SKIP root: vulture not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v deptry >/dev/null 2>&1 || { echo "SKIP root: deptry not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v npx >/dev/null 2>&1 || { echo "SKIP root: npx not found"; exit 0; }; \
	command -v git >/dev/null 2>&1 || { echo "SKIP root: git not found"; exit 0; }; \
	command -v grep >/dev/null 2>&1 || { echo "SKIP root: grep not found"; exit 0; }; \
	ruff check aragora tests scripts && \
	ruff format --check aragora tests scripts && \
	python3 scripts/ci/check_tool_baseline.py --tool ruff \
		--baseline scripts/baselines/root-ruff-naming.json \
		--report-json "$(READINESS_REPORT_DIR)/root-ruff-naming.report.json" \
		-- ruff check aragora --select N --output-format concise && \
	python3 scripts/ci/check_tool_baseline.py --tool ruff \
		--baseline scripts/baselines/root-ruff-complexity.json \
		--report-json "$(READINESS_REPORT_DIR)/root-ruff-complexity.report.json" \
		-- ruff check aragora --select C901 --output-format concise && \
	python3 scripts/ci/check_tool_baseline.py --tool vulture \
		--baseline scripts/baselines/root-vulture.json \
		--report-json "$(READINESS_REPORT_DIR)/root-vulture.report.json" \
		-- vulture aragora --min-confidence 80 && \
	python3 scripts/ci/check_mypy_overrides.py \
		--baseline scripts/baselines/root-mypy-overrides.json \
		--report-json "$(READINESS_REPORT_DIR)/root-mypy-overrides.report.json" && \
	python3 scripts/ci/check_todo_ratchet.py \
		--baseline scripts/baselines/root-todo.json \
		--report-json "$(READINESS_REPORT_DIR)/root-todo.report.json" && \
	deptry . && \
	npx --yes jscpd@$(JSCPD_VERSION) --config .jscpd.json && \
	python3 scripts/ci/check_file_sizes.py \
		--baseline scripts/baselines/file_size_baseline.json && \
	$(READINESS_DONE)

readiness-typecheck-root:
	@$(READINESS_T0); \
	command -v mypy >/dev/null 2>&1 || { echo "SKIP root: mypy not found (put .venv/bin on PATH)"; exit 0; }; \
	[ "$$(mypy --version | awk '{print $$2}')" = "2.1.0" ] || { echo "readiness-typecheck-root: mypy 2.1.0 required (CI pin; put .venv/bin on PATH)"; exit 1; }; \
	git rev-parse --verify -q "$(READINESS_BASE_REF)" >/dev/null || { echo "readiness-typecheck-root: base ref $(READINESS_BASE_REF) not found (set READINESS_BASE_REF)"; exit 1; }; \
	files=$$(git diff --name-only --diff-filter=d "$(READINESS_BASE_REF)...HEAD" -- ':(glob)aragora/**/*.py' ':(glob)scripts/**/*.py'); \
	if [ -z "$$files" ]; then echo "no changed python files ($(READINESS_BASE_REF)...HEAD)"; $(READINESS_DONE); exit 0; fi; \
	echo "mypy $$(mypy --version | awk '{print $$2}') over $$(echo $$files | wc -w | tr -d ' ') changed file(s)"; \
	mypy --ignore-missing-imports --follow-imports=skip --show-error-codes $$files && \
	$(READINESS_DONE)

readiness-test-root:
	@$(READINESS_T0); \
	command -v pytest >/dev/null 2>&1 || { echo "SKIP root: pytest not found (put .venv/bin on PATH)"; exit 0; }; \
	mkdir -p "$(READINESS_JUNIT_DIR)"; \
	fail_under=$(READINESS_ROOT_COV_FAIL_UNDER); \
	pytest tests/ci tests/config tests/observability tests/telemetry $(READINESS_EXTRA_TESTS) -q -p no:randomly -n 4 --timeout=120 --cov=aragora --cov-fail-under=$$fail_under --junitxml="$(READINESS_JUNIT_DIR)/root.xml" && \
	$(READINESS_DONE)

# --- debate (aragora-debate/, src layout) -----------------------------------
readiness-lint-debate:
	@$(READINESS_T0); \
	command -v ruff >/dev/null 2>&1 || { echo "SKIP debate: ruff not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v python3 >/dev/null 2>&1 || { echo "SKIP debate: python3 not found"; exit 0; }; \
	command -v vulture >/dev/null 2>&1 || { echo "SKIP debate: vulture not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v deptry >/dev/null 2>&1 || { echo "SKIP debate: deptry not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v npx >/dev/null 2>&1 || { echo "SKIP debate: npx not found"; exit 0; }; \
	command -v git >/dev/null 2>&1 || { echo "SKIP debate: git not found"; exit 0; }; \
	ruff check aragora-debate && ruff format --check aragora-debate && \
	python3 scripts/ci/check_tool_baseline.py --tool vulture \
		--baseline scripts/baselines/debate-vulture.json \
		--report-json "$(READINESS_REPORT_DIR)/debate-vulture.report.json" \
		-- vulture aragora-debate/src --min-confidence 80 && \
	(cd aragora-debate && deptry src) && \
	npx --yes jscpd@$(JSCPD_VERSION) aragora-debate/src --threshold 4.06 --output "$(READINESS_REPORT_DIR)/debate-jscpd" && \
	python3 scripts/ci/check_file_sizes.py --glob 'aragora-debate/src/**/*.py' \
		--baseline scripts/baselines/debate-file-sizes.json && \
	$(READINESS_DONE)

readiness-typecheck-debate:
	@$(READINESS_T0); \
	command -v mypy >/dev/null 2>&1 || { echo "SKIP debate: mypy not found (put .venv/bin on PATH)"; exit 0; }; \
	[ "$$(mypy --version | awk '{print $$2}')" = "2.1.0" ] || { echo "readiness-typecheck-debate: mypy 2.1.0 required (CI pin; put .venv/bin on PATH)"; exit 1; }; \
	cd aragora-debate && mypy --strict src && \
	$(READINESS_DONE)

readiness-test-debate:
	@$(READINESS_T0); \
	command -v pytest >/dev/null 2>&1 || { echo "SKIP debate: pytest not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v python3 >/dev/null 2>&1 || { echo "SKIP debate: python3 not found"; exit 0; }; \
	mkdir -p "$(READINESS_JUNIT_DIR)" && \
	fail_under=$(READINESS_DEBATE_COV_FAIL_UNDER) && \
	pytest aragora-debate/tests -q -p no:randomly -n 4 --timeout=120 --cov=aragora_debate --cov-config=aragora-debate/pyproject.toml --cov-fail-under=$$fail_under --durations=10 --junitxml="$(READINESS_JUNIT_DIR)/debate.xml" && \
	$(READINESS_DONE)

# --- verify (aragora-verify/, src layout, own [tool.ruff]) ------------------
readiness-lint-verify:
	@$(READINESS_T0); \
	command -v ruff >/dev/null 2>&1 || { echo "SKIP verify: ruff not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v python3 >/dev/null 2>&1 || { echo "SKIP verify: python3 not found"; exit 0; }; \
	command -v vulture >/dev/null 2>&1 || { echo "SKIP verify: vulture not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v deptry >/dev/null 2>&1 || { echo "SKIP verify: deptry not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v npx >/dev/null 2>&1 || { echo "SKIP verify: npx not found"; exit 0; }; \
	command -v git >/dev/null 2>&1 || { echo "SKIP verify: git not found"; exit 0; }; \
	ruff check aragora-verify && ruff format --check aragora-verify && \
	python3 scripts/ci/check_tool_baseline.py --tool vulture \
		--baseline scripts/baselines/verify-vulture.json \
		--report-json "$(READINESS_REPORT_DIR)/verify-vulture.report.json" \
		-- vulture aragora-verify/src --min-confidence 80 && \
	(cd aragora-verify && deptry src) && \
	npx --yes jscpd@$(JSCPD_VERSION) aragora-verify/src --threshold 0.5 --output "$(READINESS_REPORT_DIR)/verify-jscpd" && \
	python3 scripts/ci/check_file_sizes.py --glob 'aragora-verify/src/**/*.py' \
		--baseline scripts/baselines/verify-file-sizes.json && \
	$(READINESS_DONE)

readiness-typecheck-verify:
	@$(READINESS_T0); \
	command -v mypy >/dev/null 2>&1 || { echo "SKIP verify: mypy not found (put .venv/bin on PATH)"; exit 0; }; \
	[ "$$(mypy --version | awk '{print $$2}')" = "2.1.0" ] || { echo "readiness-typecheck-verify: mypy 2.1.0 required (CI pin; put .venv/bin on PATH)"; exit 1; }; \
	cd aragora-verify && mypy --strict src && \
	$(READINESS_DONE)

readiness-test-verify:
	@$(READINESS_T0); \
	command -v pytest >/dev/null 2>&1 || { echo "SKIP verify: pytest not found (put .venv/bin on PATH)"; exit 0; }; \
	command -v python3 >/dev/null 2>&1 || { echo "SKIP verify: python3 not found"; exit 0; }; \
	mkdir -p "$(READINESS_JUNIT_DIR)" && \
	fail_under=$(READINESS_VERIFY_COV_FAIL_UNDER) && \
	pytest aragora-verify/tests -q -p no:randomly -n 4 --timeout=120 --cov=aragora_verify --cov-config=aragora-verify/pyproject.toml --cov-fail-under=$$fail_under --durations=10 --junitxml="$(READINESS_JUNIT_DIR)/verify.xml" && \
	$(READINESS_DONE)

# --- live (aragora/live, Next.js) -------------------------------------------
readiness-lint-live:
	@$(READINESS_T0); \
	command -v npx >/dev/null 2>&1 || { echo "SKIP live: npx not found"; exit 0; }; \
	[ -d aragora/live/node_modules ] || { echo "SKIP live: node_modules missing (npm ci in aragora/live)"; exit 0; }; \
	cd aragora/live && npx eslint . --max-warnings 0 && \
	$(READINESS_DONE)

readiness-typecheck-live:
	@$(READINESS_T0); \
	command -v npx >/dev/null 2>&1 || { echo "SKIP live: npx not found"; exit 0; }; \
	[ -d aragora/live/node_modules ] || { echo "SKIP live: node_modules missing (npm ci in aragora/live)"; exit 0; }; \
	cd aragora/live && npx tsc --noEmit -p tsconfig.json && \
	$(READINESS_DONE)

readiness-test-live:
	@$(READINESS_T0); \
	command -v npx >/dev/null 2>&1 || { echo "SKIP live: npx not found"; exit 0; }; \
	[ -d aragora/live/node_modules ] || { echo "SKIP live: node_modules missing (npm ci in aragora/live)"; exit 0; }; \
	cd aragora/live && npx jest --ci --silent --maxWorkers=4 && \
	$(READINESS_DONE)

# --- docs (docs-site, Docusaurus) -------------------------------------------
# docs-site has no ESLint config, no tsconfig.json and no test suite until M7.
readiness-lint-docs:
	@echo "SKIP docs: no eslint config until M7"

readiness-typecheck-docs:
	@echo "SKIP docs: no tsconfig.json until M7"

readiness-test-docs:
	@echo "SKIP docs: no test suite until M7"

# --- vscode (ide/vscode-aragora + webview-ui) -------------------------------
# The extension root has no ESLint config until M8 (`npm run lint` exits 2),
# so M1 lints only webview-ui, whose config is green today.
readiness-lint-vscode:
	@$(READINESS_T0); \
	command -v npx >/dev/null 2>&1 || { echo "SKIP vscode: npx not found"; exit 0; }; \
	[ -d ide/vscode-aragora/webview-ui/node_modules ] || { echo "SKIP vscode: webview-ui node_modules missing (npm ci in ide/vscode-aragora/webview-ui)"; exit 0; }; \
	cd ide/vscode-aragora/webview-ui && npx eslint src --ext ts,tsx && \
	$(READINESS_DONE)

readiness-typecheck-vscode:
	@$(READINESS_T0); \
	command -v npx >/dev/null 2>&1 || { echo "SKIP vscode: npx not found"; exit 0; }; \
	[ -d ide/vscode-aragora/node_modules ] || { echo "SKIP vscode: node_modules missing (npm ci in ide/vscode-aragora)"; exit 0; }; \
	cd ide/vscode-aragora && npx tsc --noEmit -p . && \
	$(READINESS_DONE)

readiness-test-vscode:
	@$(READINESS_T0); \
	command -v npx >/dev/null 2>&1 || { echo "SKIP vscode: npx not found"; exit 0; }; \
	[ -d ide/vscode-aragora/node_modules ] || { echo "SKIP vscode: node_modules missing (npm ci in ide/vscode-aragora)"; exit 0; }; \
	cd ide/vscode-aragora && npx jest --ci && \
	$(READINESS_DONE)

# --- operator (aragora-operator, Go) ----------------------------------------
# `gofmt -l` is advisory here: two files are unformatted at mission-base and
# M9 owns the operator source; go vet is the gating step.
readiness-lint-operator:
	@$(READINESS_T0); \
	command -v go >/dev/null 2>&1 || { echo "SKIP operator: go not found"; exit 0; }; \
	command -v gofmt >/dev/null 2>&1 || { echo "SKIP operator: gofmt not found"; exit 0; }; \
	cd aragora-operator && \
	unformatted=$$(gofmt -l .) && \
	{ [ -z "$$unformatted" ] || echo "gofmt (advisory until M9) would reformat: $$unformatted"; } && \
	go vet ./... && \
	$(READINESS_DONE)

readiness-typecheck-operator:
	@$(READINESS_T0); \
	command -v go >/dev/null 2>&1 || { echo "SKIP operator: go not found"; exit 0; }; \
	cd aragora-operator && go build ./... && \
	$(READINESS_DONE)

readiness-test-operator:
	@$(READINESS_T0); \
	command -v go >/dev/null 2>&1 || { echo "SKIP operator: go not found"; exit 0; }; \
	cd aragora-operator && go test ./... -count=1 && \
	$(READINESS_DONE)
