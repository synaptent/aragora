#!/usr/bin/env bash
# Test Tier Runner for Aragora
#
# Tiers:
#   smoke    - Critical smoke tests
#   fast     - Quick unit tests (<5 min) - no slow/load/e2e/integration
#   unit     - Unit tests only with extended timeout
#   ci       - CI tests with coverage (no slow/e2e tests)
#   full     - All tests with extended timeouts
#   slow     - Only slow-marked tests
#   integration - Integration tests (require services)
#   nightly  - Slow/load/e2e/benchmark suite (scheduled)
#   benchmark - Benchmark-only tests
#   handlers - Only handler tests
#   security - Only security tests
#   lint     - Linting checks
#   typecheck - Type checking
#   frontend - Frontend tests
#   e2e      - End-to-end tests
#
# Usage: ./scripts/test_tiers.sh <tier>
#
set -euo pipefail

tier="${1:-fast}"
PYTEST_BIN="${PYTEST_BIN:-python -m pytest}"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Running test tier: ${tier}${NC}"

case "$tier" in
  smoke)
    ${PYTEST_BIN} -m smoke \
      --timeout=60 \
      -v \
      --tb=short \
      -x \
      --no-header
    ;;

  fast)
    # Quick tests for local dev - exclude slow, load, e2e, integration
    ${PYTEST_BIN} tests/ -m "not slow and not load and not e2e and not integration and not integration_minimal and not benchmark and not performance" \
      --timeout=30 \
      -q \
      --tb=line \
      --ignore=tests/integration \
      --ignore=tests/e2e \
      --ignore=tests/benchmarks \
      --ignore=tests/load \
      --ignore=tests/performance
    ;;

  unit)
    # Unit tests with extended timeout - ideal for quick feedback
    ${PYTEST_BIN} tests/ -m "not slow and not load and not e2e and not integration and not integration_minimal and not benchmark and not performance" \
      --timeout=120 \
      -v \
      --tb=short \
      --ignore=tests/integration \
      --ignore=tests/e2e \
      --ignore=tests/benchmarks \
      --ignore=tests/load \
      --ignore=tests/performance
    ;;

  ci)
    # CI tier - balanced coverage vs speed
    # Skip slow/e2e/load/benchmark/integration tests
    # Coverage threshold: 50% (raised from 30%)
    ${PYTEST_BIN} tests/ \
      -m "not slow and not load and not e2e and not benchmark and not integration and not integration_minimal" \
      --timeout=120 \
      --cov=aragora \
      --cov-report=term-missing \
      --cov-report=xml \
      --cov-report=html \
      --cov-fail-under=50 \
      -v \
      --tb=short \
      -x
    ;;

  full)
    # Full test suite with extended timeouts
    ${PYTEST_BIN} tests/ \
      --timeout=300 \
      --cov=aragora \
      --cov-report=term-missing \
      --cov-report=xml \
      -v \
      --tb=short
    ;;

  slow)
    # Only slow-marked tests
    ${PYTEST_BIN} tests/ -m "slow" \
      --timeout=600 \
      -v \
      --tb=short
    ;;

  integration)
    # Integration tests (services required)
    ${PYTEST_BIN} tests/integration/ -m "integration or integration_minimal" \
      --timeout=180 \
      -v \
      --tb=short
    ;;

  nightly)
    # Nightly tier: slow/load/e2e/benchmark
    ${PYTEST_BIN} tests/ -m "slow or load or e2e or benchmark" \
      --timeout=600 \
      -v \
      --tb=short
    ;;

  benchmark)
    # Benchmark-only tests
    ${PYTEST_BIN} tests/ -m "benchmark" \
      --benchmark-only \
      --benchmark-sort=mean \
      --benchmark-warmup=on \
      -v
    ;;

  handlers)
    # Handler tests only - quick feedback on API changes
    ${PYTEST_BIN} tests/server/handlers/ \
      --timeout=120 \
      -v \
      --tb=short
    ;;

  security)
    # Security-related tests
    ${PYTEST_BIN} tests/security/ tests/server/handlers/test_admin.py tests/server/handlers/test_privacy.py tests/server/middleware/ \
      --timeout=120 \
      -v \
      --tb=short
    ;;

  storage)
    # Storage/database tests
    ${PYTEST_BIN} tests/storage/ tests/ranking/ tests/memory/ \
      --timeout=120 \
      -v \
      --tb=short
    ;;

  privacy)
    # Privacy handler tests only
    ${PYTEST_BIN} tests/server/handlers/test_privacy.py \
      --timeout=60 \
      -v \
      --tb=short
    ;;

  lint)
    echo -e "${YELLOW}Running linting checks...${NC}"
    # Use ruff format (not black) to match pre-commit config
    ruff_cmd="ruff"
    if ! command -v ruff >/dev/null 2>&1; then
      if command -v python3 >/dev/null 2>&1; then
        ruff_cmd="python3 -m ruff"
      else
        ruff_cmd="python -m ruff"
      fi
    fi
    $ruff_cmd format --check aragora/ tests/ scripts/
    $ruff_cmd check aragora/ tests/ scripts/
    echo -e "${GREEN}Linting passed!${NC}"
    ;;

  typecheck)
    # Run mypy on aragora - REQUIRED (0 errors as of Phase 5)
    echo -e "${YELLOW}=== Type checking aragora (REQUIRED) ===${NC}"

    # Count actual errors (not notes) - pattern: "file:line:col: error:"
    # Disable pipefail for this pipeline since mypy returns non-zero on errors
    ERROR_COUNT=$(set +o pipefail; mypy aragora/ --ignore-missing-imports --show-error-codes 2>/dev/null | { grep -cE "^[^:]+:[0-9]+:[0-9]+: error:" || true; } | tr -d '[:space:]')
    ERROR_COUNT=${ERROR_COUNT:-0}

    if [ "$ERROR_COUNT" -gt 0 ]; then
      echo -e "${RED}Found $ERROR_COUNT mypy error(s)!${NC}"
      mypy aragora/ --ignore-missing-imports --show-error-codes
      echo ""
      echo -e "${RED}=== Type check FAILED ===${NC}"
      echo "mypy error count must remain at 0 (currently: $ERROR_COUNT)"
      exit 1
    fi

    echo -e "${GREEN}=== Type check passed (0 errors) ===${NC}"
    ;;

  frontend)
    (cd aragora/live && npm test)
    ;;

  e2e)
    (cd aragora/live && npm run test:e2e)
    ;;

  help|--help|-h)
    echo "Test Tier Runner for Aragora"
    echo ""
    echo "Usage: $0 <tier>"
    echo ""
    echo "Available tiers:"
    echo "  smoke     Critical smoke tests"
    echo "  fast      Quick unit tests, 30s timeout (~2 min)"
    echo "  unit      Unit tests, 120s timeout (~5 min)"
    echo "  ci        CI tests with coverage, excludes slow/e2e (~10 min)"
    echo "  full      All tests, 300s timeout (~30 min)"
    echo "  slow      Only slow-marked tests"
    echo "  integration Integration tests (services required)"
    echo "  nightly   Slow/load/e2e/benchmark suite (scheduled)"
    echo "  benchmark Benchmark-only tests"
    echo "  handlers  Handler tests only"
    echo "  security  Security-related tests"
    echo "  storage   Storage/database tests"
    echo "  privacy   Privacy handler tests only"
    echo "  lint      Run linting (ruff format, ruff check)"
    echo "  typecheck Run type checking (mypy)"
    echo "  frontend  Frontend unit tests"
    echo "  e2e       End-to-end tests"
    echo ""
    echo "Examples:"
    echo "  $0 fast       # Quick local dev feedback"
    echo "  $0 ci         # Run as CI would"
    echo "  $0 handlers   # Test API handlers only"
    ;;

  *)
    echo -e "${RED}Unknown tier: $tier${NC}"
    echo "Run '$0 help' for available tiers"
    exit 2
    ;;
esac

echo -e "${GREEN}Test tier '$tier' completed successfully!${NC}"
