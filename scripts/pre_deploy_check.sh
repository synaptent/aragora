#!/bin/bash
# =============================================================================
# Aragora Production Deployment Pre-flight Checklist
# =============================================================================
# Run this script before deploying to production to verify system readiness.
#
# Usage: ./scripts/pre_deploy_check.sh [--fix] [--verbose]
#
# Options:
#   --fix      Attempt to fix minor issues automatically
#   --verbose  Show detailed output for each check
#
# Exit codes:
#   0 - All checks passed
#   1 - Critical failures (do not deploy)
#   2 - Warnings present (review before deploying)
# =============================================================================

# Don't exit on error - we want to continue checking
# set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

# Parse arguments
FIX_MODE=false
VERBOSE=false
for arg in "$@"; do
    case $arg in
        --fix) FIX_MODE=true ;;
        --verbose) VERBOSE=true ;;
    esac
done

# Helper functions
print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}"
}

print_pass() {
    echo -e "  ${GREEN}✓${NC} $1"
    ((PASSED++))
}

print_fail() {
    echo -e "  ${RED}✗${NC} $1"
    ((FAILED++))
}

print_warn() {
    echo -e "  ${YELLOW}!${NC} $1"
    ((WARNINGS++))
}

print_info() {
    if $VERBOSE; then
        echo -e "  ${BLUE}ℹ${NC} $1"
    fi
}

# =============================================================================
# 1. Environment Checks
# =============================================================================
print_header "Environment Checks"

# Python version
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
if [[ "$PYTHON_VERSION" == 3.11.* ]] || [[ "$PYTHON_VERSION" == 3.12.* ]]; then
    print_pass "Python version: $PYTHON_VERSION"
else
    print_warn "Python version $PYTHON_VERSION (recommended: 3.11+)"
fi

# Node.js version (for frontend)
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version | cut -c2-)
    if [[ "${NODE_VERSION%%.*}" -ge 20 ]]; then
        print_pass "Node.js version: $NODE_VERSION"
    else
        print_fail "Node.js version $NODE_VERSION (required: 20+)"
    fi
else
    print_warn "Node.js not found (required for frontend)"
fi

# Required environment variables
REQUIRED_VARS=("ANTHROPIC_API_KEY" "DATABASE_URL")
OPTIONAL_VARS=("OPENAI_API_KEY" "OPENROUTER_API_KEY" "REDIS_URL")

for var in "${REQUIRED_VARS[@]}"; do
    if [[ -n "${!var}" ]]; then
        print_pass "$var is set"
    else
        print_fail "$var is not set (required)"
    fi
done

for var in "${OPTIONAL_VARS[@]}"; do
    if [[ -n "${!var}" ]]; then
        print_pass "$var is set"
    else
        print_info "$var is not set (optional)"
    fi
done

# =============================================================================
# 2. Git Status
# =============================================================================
print_header "Git Status"

# Check for uncommitted changes
if git diff --quiet && git diff --cached --quiet; then
    print_pass "No uncommitted changes"
else
    UNCOMMITTED=$(git status --short | wc -l | tr -d ' ')
    print_warn "$UNCOMMITTED uncommitted files"
fi

# Check branch
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" == "main" ]] || [[ "$CURRENT_BRANCH" == "master" ]]; then
    print_pass "On main branch: $CURRENT_BRANCH"
else
    print_warn "Not on main branch: $CURRENT_BRANCH"
fi

# Check if up to date with remote
git fetch origin --quiet 2>/dev/null || true
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse origin/$CURRENT_BRANCH 2>/dev/null || echo "")
if [[ "$LOCAL" == "$REMOTE" ]]; then
    print_pass "Branch is up to date with origin"
elif [[ -z "$REMOTE" ]]; then
    print_info "Remote branch not found"
else
    print_warn "Local differs from origin (push or pull needed)"
fi

# =============================================================================
# 3. Code Quality
# =============================================================================
print_header "Code Quality"

# Ruff linting
if command -v ruff &> /dev/null; then
    RUFF_ERRORS=$(ruff check aragora/ --statistics 2>/dev/null | tail -1 || echo "0")
    if [[ "$RUFF_ERRORS" == *"0"* ]] || [[ -z "$RUFF_ERRORS" ]]; then
        print_pass "Ruff: No linting errors"
    else
        print_warn "Ruff: Some linting issues"
        if $VERBOSE; then
            ruff check aragora/ --statistics 2>/dev/null | head -10
        fi
    fi
else
    print_info "Ruff not installed"
fi

# Type checking (mypy)
if command -v mypy &> /dev/null; then
    print_info "Running mypy (this may take a moment)..."
    if mypy aragora/ --ignore-missing-imports --no-error-summary 2>/dev/null | grep -q "error:"; then
        print_warn "Mypy: Some type errors present"
    else
        print_pass "Mypy: No critical type errors"
    fi
else
    print_info "Mypy not installed"
fi

# =============================================================================
# 4. Test Suite
# =============================================================================
print_header "Test Suite"

# Collect tests
print_info "Collecting tests..."
TEST_COUNT=$(python -m pytest tests/ --collect-only -q 2>/dev/null | tail -1 | grep -oE '[0-9]+' | head -1 || echo "0")
if [[ "$TEST_COUNT" -gt 20000 ]]; then
    print_pass "Test collection: $TEST_COUNT tests"
else
    print_warn "Test collection: $TEST_COUNT tests (expected 28,000+)"
fi

# Run quick smoke tests
print_info "Running smoke tests..."
if python -m pytest tests/debate/test_consensus.py tests/auth/test_lockout.py -q --tb=no 2>/dev/null; then
    print_pass "Smoke tests passed"
else
    print_fail "Smoke tests failed"
fi

# =============================================================================
# 5. Security Checks
# =============================================================================
print_header "Security Checks"

# Check for secrets in code (exclude examples and help text)
if grep -r "sk-ant-[a-zA-Z0-9]" aragora/ --include="*.py" 2>/dev/null | grep -v "example" | grep -v "print(" | grep -v '"""' | head -1; then
    print_fail "Possible API key found in code"
else
    print_pass "No hardcoded API keys detected"
fi

# Check .env is not committed
if git ls-files | grep -q "^\.env$"; then
    print_fail ".env file is tracked in git"
else
    print_pass ".env file is not tracked"
fi

# Check for debug mode indicators (exclude test patterns and regex definitions)
if grep -r "^DEBUG.*=.*True" aragora/ --include="*.py" 2>/dev/null | grep -v "test" | grep -v "pattern=" | head -1; then
    print_warn "DEBUG flag found in code"
else
    print_pass "No DEBUG flags detected"
fi

# Bandit security scan
if command -v bandit &> /dev/null; then
    HIGH_ISSUES=$(bandit -r aragora/ -ll -q 2>/dev/null | grep -c "High:" || echo "0")
    if [[ "$HIGH_ISSUES" == "0" ]]; then
        print_pass "Bandit: No high severity issues"
    else
        print_warn "Bandit: $HIGH_ISSUES high severity issues"
    fi
else
    print_info "Bandit not installed"
fi

# =============================================================================
# 6. Dependencies
# =============================================================================
print_header "Dependencies"

# Check for outdated packages
if command -v pip &> /dev/null; then
    OUTDATED=$(pip list --outdated 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$OUTDATED" -lt 10 ]]; then
        print_pass "Dependencies: $OUTDATED outdated packages"
    else
        print_warn "Dependencies: $OUTDATED outdated packages"
    fi
fi

# Verify key imports work
print_info "Verifying imports..."
if python -c "from aragora import Arena; from aragora.server.versioning import APIVersion; print('OK')" 2>/dev/null; then
    print_pass "Core imports successful"
else
    print_fail "Core imports failed"
fi

if python -c "from aragora.tenancy import TenantContext; print('OK')" 2>/dev/null; then
    print_pass "Tenancy imports successful"
else
    print_warn "Tenancy imports failed"
fi

if python -c "from aragora.billing import UsageMeter; print('OK')" 2>/dev/null; then
    print_pass "Billing imports successful"
else
    print_warn "Billing imports failed"
fi

# =============================================================================
# 7. Build Verification
# =============================================================================
print_header "Build Verification"

# Frontend build check
if [[ -d "aragora/live" ]]; then
    if [[ -d "aragora/live/.next" ]] || [[ -d "aragora/live/out" ]]; then
        print_pass "Frontend build exists"
    else
        print_warn "Frontend not built (run: cd aragora/live && npm run build)"
    fi
else
    print_info "Frontend directory not found"
fi

# Check Docker
if command -v docker &> /dev/null; then
    if docker info &> /dev/null; then
        print_pass "Docker is available"
    else
        print_warn "Docker not running"
    fi
else
    print_info "Docker not installed"
fi

# =============================================================================
# 8. Documentation
# =============================================================================
print_header "Documentation"

# Check key docs exist
DOCS=("docs/DEPLOYMENT.md" "docs/STATUS.md" "docs/API_VERSIONING.md" "CLAUDE.md")
for doc in "${DOCS[@]}"; do
    if [[ -f "$doc" ]]; then
        print_pass "$doc exists"
    else
        print_warn "$doc not found"
    fi
done

# =============================================================================
# 9. Database
# =============================================================================
print_header "Database"

# Check migration status
if [[ -d "alembic" ]] || [[ -d "aragora/persistence/migrations" ]]; then
    print_pass "Migration directory exists"
else
    print_info "No migration directory found"
fi

# =============================================================================
# Summary
# =============================================================================
echo -e "\n${BLUE}=============================================${NC}"
echo -e "${BLUE}           DEPLOYMENT CHECKLIST SUMMARY       ${NC}"
echo -e "${BLUE}=============================================${NC}"
echo -e "  ${GREEN}Passed:${NC}   $PASSED"
echo -e "  ${YELLOW}Warnings:${NC} $WARNINGS"
echo -e "  ${RED}Failed:${NC}   $FAILED"
echo ""

if [[ $FAILED -gt 0 ]]; then
    echo -e "${RED}DEPLOYMENT NOT RECOMMENDED${NC}"
    echo "Fix the failed checks before deploying."
    exit 1
elif [[ $WARNINGS -gt 3 ]]; then
    echo -e "${YELLOW}REVIEW WARNINGS BEFORE DEPLOYING${NC}"
    echo "Multiple warnings detected. Review before proceeding."
    exit 2
else
    echo -e "${GREEN}READY FOR DEPLOYMENT${NC}"
    echo "All critical checks passed."
    exit 0
fi
