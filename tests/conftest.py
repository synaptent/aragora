"""Shared pytest configuration for the Aragora test suite.

Fixtures live in ``tests/fixtures/*.py`` plugin modules loaded via
``pytest_plugins`` below; their import paths are stable for every test. This
module retains test-suite bootstrap (sys.path wiring + Slack preload),
optional-dependency skip markers, custom marker registration, and skip-count
reporting.
"""

import importlib.util
import os
import sys
from pathlib import Path

# Ensure local monorepo package imports resolve during test collection.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MONOREPO_IMPORT_ROOTS = [
    _PROJECT_ROOT / "sdk" / "python",
    _PROJECT_ROOT / "aragora-debate" / "src",
]
for _import_root in _MONOREPO_IMPORT_ROOTS:
    if _import_root.is_dir():
        _import_root_str = str(_import_root)
        if _import_root_str not in sys.path:
            sys.path.insert(0, _import_root_str)

# Ensure local aragora-debate sources resolve during checkout-based test collection.
_DEBATE_SRC_ROOT = _PROJECT_ROOT / "aragora-debate" / "src"
if _DEBATE_SRC_ROOT.is_dir():
    _debate_src = str(_DEBATE_SRC_ROOT)
    if _debate_src not in sys.path:
        sys.path.insert(0, _debate_src)

# Preload the real Slack handler package before test modules install lightweight
# sys.modules stubs, so nested imports like social.slack.responses still resolve.
try:
    import aragora.server.handlers.social.slack  # noqa: F401
except Exception:
    pass

# Fixture plugins (extracted from this conftest; import paths stable for tests)
# and the skip-governance plugin. Order of autouse fixtures is preserved inside
# tests/fixtures/autouse.py.
pytest_plugins = [
    "tests.plugins.skip_governance",
    "tests.fixtures.autouse",
    "tests.fixtures.tempfiles",
    "tests.fixtures.mocks",
    "tests.fixtures.services",
    "tests.fixtures.env",
    "tests.fixtures.sample_data",
    "tests.fixtures.api_responses",
    "tests.fixtures.clients",
]


# ============================================================================
# Optional Dependency Skip Markers
# ============================================================================


def _check_import(module_name: str) -> bool:
    """Check if a module is available without fully importing it.

    Uses ``importlib.util.find_spec`` to avoid executing module-level code
    that may trigger heavy side-effects (e.g. ``sentence_transformers``
    pulls in ``transformers`` which imports ``huggingface_hub``, potentially
    blocking on network downloads in CI).
    """
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


# Z3 solver for formal verification
HAS_Z3 = _check_import("z3")
REQUIRES_Z3 = "z3-solver not installed (pip install z3-solver)"
requires_z3 = not HAS_Z3

# Redis for caching and pub/sub
HAS_REDIS = _check_import("redis")
REQUIRES_REDIS = "redis not installed (pip install redis)"
requires_redis = not HAS_REDIS

# PostgreSQL async driver
HAS_ASYNCPG = _check_import("asyncpg")
REQUIRES_ASYNCPG = "asyncpg not installed (pip install asyncpg)"
requires_asyncpg = not HAS_ASYNCPG

# Supabase client
HAS_SUPABASE = _check_import("supabase")
REQUIRES_SUPABASE = "supabase not installed (pip install supabase)"
requires_supabase = not HAS_SUPABASE

# HTTPX async client
HAS_HTTPX = _check_import("httpx")
REQUIRES_HTTPX = "httpx not installed (pip install httpx)"
requires_httpx = not HAS_HTTPX

# WebSockets
HAS_WEBSOCKETS = _check_import("websockets")
REQUIRES_WEBSOCKETS = "websockets not installed (pip install websockets)"
requires_websockets = not HAS_WEBSOCKETS

# PyJWT
HAS_PYJWT = _check_import("jwt")
REQUIRES_PYJWT = "PyJWT not installed (pip install PyJWT)"
requires_pyjwt = not HAS_PYJWT

# Scikit-learn for ML features - now always available
HAS_SKLEARN = True
REQUIRES_SKLEARN = "scikit-learn not installed (pip install scikit-learn)"
requires_sklearn = False  # sklearn is always installed

# SentenceTransformers for embeddings
HAS_SENTENCE_TRANSFORMERS = _check_import("sentence_transformers")
REQUIRES_SENTENCE_TRANSFORMERS = "sentence-transformers not installed"
requires_sentence_transformers = not HAS_SENTENCE_TRANSFORMERS

# MCP (Model Context Protocol)
HAS_MCP = _check_import("mcp")
REQUIRES_MCP = "mcp not installed (pip install mcp)"
requires_mcp = not HAS_MCP

# aiosqlite for async SQLite
HAS_AIOSQLITE = _check_import("aiosqlite")
REQUIRES_AIOSQLITE = "aiosqlite not installed (pip install aiosqlite)"
requires_aiosqlite = not HAS_AIOSQLITE

# Twilio for SMS/voice
HAS_TWILIO = _check_import("twilio")
REQUIRES_TWILIO = "twilio not installed (pip install twilio)"
requires_twilio = not HAS_TWILIO

# PyOTP for TOTP/HOTP
HAS_PYOTP = _check_import("pyotp")
REQUIRES_PYOTP = "pyotp not installed (pip install pyotp)"
requires_pyotp = not HAS_PYOTP

# psycopg2 for PostgreSQL
HAS_PSYCOPG2 = _check_import("psycopg2")
REQUIRES_PSYCOPG2 = "psycopg2 not installed (pip install psycopg2-binary)"
requires_psycopg2 = not HAS_PSYCOPG2

# NetworkX for graph operations
HAS_NETWORKX = _check_import("networkx")
REQUIRES_NETWORKX = "networkx not installed (pip install networkx)"
requires_networkx = not HAS_NETWORKX

# ============================================================================
# Composite Skip Markers
# ============================================================================
# These combine multiple requirements for common test scenarios

# Requires any database backend
HAS_DATABASE = HAS_ASYNCPG or HAS_PSYCOPG2 or HAS_AIOSQLITE
REQUIRES_DATABASE = "No database driver installed (asyncpg, psycopg2, or aiosqlite)"
requires_database = not HAS_DATABASE

# Requires async database support
HAS_ASYNC_DB = HAS_ASYNCPG or HAS_AIOSQLITE
REQUIRES_ASYNC_DB = "No async database driver installed (asyncpg or aiosqlite)"
requires_async_db = not HAS_ASYNC_DB


def _check_aragora_module(module_path: str) -> bool:
    """Check if an Aragora module can be imported."""
    try:
        __import__(module_path)
        return True
    except (ImportError, AttributeError):
        return False


# Aragora optional modules
HAS_RLM = _check_aragora_module("aragora.rlm")
REQUIRES_RLM = "RLM module not available"
requires_rlm = not HAS_RLM

HAS_RBAC = _check_aragora_module("aragora.rbac")
REQUIRES_RBAC = "RBAC module not available"
requires_rbac = not HAS_RBAC

HAS_TRICKSTER = _check_aragora_module("aragora.debate.trickster")
REQUIRES_TRICKSTER = "Trickster module not available"
requires_trickster = not HAS_TRICKSTER

HAS_PLUGINS = _check_aragora_module("aragora.plugins")
REQUIRES_PLUGINS = "Plugins module not available"
requires_plugins = not HAS_PLUGINS

HAS_BROADCAST = _check_aragora_module("aragora.broadcast.pipeline")
REQUIRES_BROADCAST = "Broadcast module not available (see #134)"
requires_broadcast = not HAS_BROADCAST


# Broadcast E2E tests require specific APIs not yet implemented
def _check_broadcast_e2e_api() -> bool:
    """Check if broadcast E2E test API is available."""
    try:
        from aragora.broadcast.audio_engine import AudioEngine, get_voice_for_agent
        from aragora.broadcast.rss_gen import create_episode, generate_feed

        return True
    except ImportError:
        return False


HAS_BROADCAST_E2E_API = _check_broadcast_e2e_api()
REQUIRES_BROADCAST_E2E_API = "Broadcast E2E API not fully implemented (AudioEngine, create_episode)"
requires_broadcast_e2e_api = not HAS_BROADCAST_E2E_API

HAS_BROADCAST_STORAGE = _check_aragora_module("aragora.broadcast.storage")
REQUIRES_BROADCAST_STORAGE = "Broadcast storage not available (see #134)"
requires_broadcast_storage = not HAS_BROADCAST_STORAGE

# Security and encryption modules
HAS_ENCRYPTION = _check_aragora_module("aragora.security.encryption")
REQUIRES_ENCRYPTION = "Encryption service not available"
requires_encryption = not HAS_ENCRYPTION

HAS_INTEGRATION_STORE = _check_aragora_module("aragora.storage.integration_store")
REQUIRES_INTEGRATION_STORE = "IntegrationStore not available"
requires_integration_store = not HAS_INTEGRATION_STORE

HAS_GMAIL_TOKEN_STORE = _check_aragora_module("aragora.storage.gmail_token_store")
REQUIRES_GMAIL_TOKEN_STORE = "GmailTokenStore not available"
requires_gmail_token_store = not HAS_GMAIL_TOKEN_STORE

HAS_SYNC_STORE = _check_aragora_module("aragora.storage.sync_store")
REQUIRES_SYNC_STORE = "SyncStore not available"
requires_sync_store = not HAS_SYNC_STORE

HAS_KEY_ROTATION = _check_aragora_module("aragora.security.migration")
REQUIRES_KEY_ROTATION = "Key rotation not available"
requires_key_rotation = not HAS_KEY_ROTATION

HAS_SECURITY_HANDLER = _check_aragora_module("aragora.server.handlers.admin.security")
REQUIRES_SECURITY_HANDLER = "SecurityHandler not available"
requires_security_handler = not HAS_SECURITY_HANDLER

HAS_SECURITY_METRICS = _check_aragora_module("aragora.observability.metrics.security")
REQUIRES_SECURITY_METRICS = "Security metrics not available"
requires_security_metrics = not HAS_SECURITY_METRICS

# Debate and evolution modules (commonly skipped)
HAS_RHETORICAL_OBSERVER = _check_aragora_module("aragora.debate.rhetorical_observer")
REQUIRES_RHETORICAL_OBSERVER = "RhetoricalObserver module not available"
requires_rhetorical_observer = not HAS_RHETORICAL_OBSERVER

HAS_INTROSPECTION = _check_aragora_module("aragora.introspection")
REQUIRES_INTROSPECTION = "Introspection module not available"
requires_introspection = not HAS_INTROSPECTION

HAS_EVOLUTION = _check_aragora_module("aragora.evolution")
REQUIRES_EVOLUTION = "Evolution module not available"
requires_evolution = not HAS_EVOLUTION

HAS_BREEDING = _check_aragora_module("aragora.evolution.breeding")
REQUIRES_BREEDING = "Breeding module not available"
requires_breeding = not HAS_BREEDING

HAS_GENESIS = _check_aragora_module("aragora.genesis")
REQUIRES_GENESIS = "Genesis module not available"
requires_genesis = not HAS_GENESIS

HAS_PHASES = _check_aragora_module("aragora.debate.phases")
REQUIRES_PHASES = "Phase modules not available"
requires_phases = not HAS_PHASES

HAS_NOVELTY_TRACKER = _check_aragora_module("aragora.evolution.novelty")
REQUIRES_NOVELTY_TRACKER = "NoveltyTracker module not available"
requires_novelty_tracker = not HAS_NOVELTY_TRACKER

HAS_CULTURE_MANAGER = _check_aragora_module("aragora.organization.culture")
REQUIRES_CULTURE_MANAGER = "OrganizationCultureManager not available"
requires_culture_manager = not HAS_CULTURE_MANAGER

HAS_MEMORY_ANALYTICS = _check_aragora_module("aragora.server.handlers.memory")
REQUIRES_MEMORY_ANALYTICS = "MemoryAnalyticsHandler not available"
requires_memory_analytics = not HAS_MEMORY_ANALYTICS


def _check_handlers_available() -> bool:
    """Check if handler registry is available."""
    try:
        from aragora.server.handler_registry import HANDLERS_AVAILABLE

        return HANDLERS_AVAILABLE
    except ImportError:
        return False


HAS_HANDLERS = _check_handlers_available()
REQUIRES_HANDLERS = "Handlers not available"
requires_handlers = not HAS_HANDLERS


# ============================================================================
# CI Environment Detection
# ============================================================================
# Detect common CI environment variables
RUNNING_IN_CI = any(
    os.environ.get(var)
    for var in [
        "CI",  # Generic CI flag (GitHub Actions, GitLab CI, etc.)
        "GITHUB_ACTIONS",  # GitHub Actions
        "GITLAB_CI",  # GitLab CI
        "CIRCLECI",  # CircleCI
        "JENKINS_URL",  # Jenkins
        "TRAVIS",  # Travis CI
        "BUILDKITE",  # Buildkite
    ]
)
REQUIRES_NO_CI = "Test skipped in CI environment"
requires_no_ci = RUNNING_IN_CI


# ============================================================================
# Additional Skip Markers for Common Scenarios
# ============================================================================

HAS_CRYPTOGRAPHY = _check_import("cryptography")
REQUIRES_CRYPTOGRAPHY = "cryptography not installed (pip install cryptography)"
requires_cryptography = not HAS_CRYPTOGRAPHY

# Tree-sitter for code parsing
HAS_TREE_SITTER = _check_import("tree_sitter")
REQUIRES_TREE_SITTER = "tree-sitter not installed"
requires_tree_sitter = not HAS_TREE_SITTER

# Whisper for transcription
HAS_WHISPER = _check_import("whisper")
REQUIRES_WHISPER = "whisper not installed"
requires_whisper = not HAS_WHISPER

# Z3 solver (expanded from existing)
# Note: HAS_Z3 defined earlier in file


def _has_z3_binary() -> bool:
    """Check if Z3 binary is available and working."""
    try:
        import z3

        solver = z3.Solver()
        x = z3.Int("x")
        solver.add(x > 0)
        return solver.check() == z3.sat
    except (ImportError, Exception):
        return False


HAS_Z3_WORKING = _has_z3_binary()
REQUIRES_Z3_WORKING = "Z3 solver not installed or not working"
requires_z3_working = not HAS_Z3_WORKING

# Lean theorem prover
HAS_LEAN = _check_import("lean")
REQUIRES_LEAN = "Lean theorem prover not installed"
requires_lean = not HAS_LEAN

# pydub for audio processing
HAS_PYDUB = _check_import("pydub")
REQUIRES_PYDUB = "pydub not installed (pip install pydub)"
requires_pydub = not HAS_PYDUB

# WeasyPrint for PDF generation
HAS_WEASYPRINT = _check_import("weasyprint")
REQUIRES_WEASYPRINT = "WeasyPrint not installed (pip install weasyprint)"
requires_weasyprint = not HAS_WEASYPRINT

# Milvus vector database
HAS_MILVUS = _check_import("pymilvus")
REQUIRES_MILVUS = "pymilvus not installed"
requires_milvus = not HAS_MILVUS

# aiohttp for async HTTP
HAS_AIOHTTP = _check_import("aiohttp")
REQUIRES_AIOHTTP = "aiohttp not installed (pip install aiohttp)"
requires_aiohttp = not HAS_AIOHTTP


# FFmpeg for video processing
def _has_ffmpeg() -> bool:
    """Check if FFmpeg is available on PATH."""
    import shutil

    return shutil.which("ffmpeg") is not None


HAS_FFMPEG = _has_ffmpeg()
REQUIRES_FFMPEG = "FFmpeg not available in PATH"
requires_ffmpeg = not HAS_FFMPEG


def _has_git() -> bool:
    """Check if git is available on PATH."""
    import shutil

    return shutil.which("git") is not None


HAS_GIT = _has_git()
REQUIRES_GIT = "git not available in PATH"
requires_git = not HAS_GIT


# Platform-specific capabilities
def _supports_symlinks() -> bool:
    """Check if the system supports symlinks."""
    import os
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test")
            link_path = os.path.join(tmpdir, "link")
            with open(test_file, "w") as f:
                f.write("test")
            os.symlink(test_file, link_path)
            return True
    except (OSError, NotImplementedError):
        return False


HAS_SYMLINKS = _supports_symlinks()
REQUIRES_SYMLINKS = "Symlink creation not supported on this platform"
requires_symlinks = not HAS_SYMLINKS


def _supports_signals() -> bool:
    """Check if the system supports signal-based timeouts (Unix-like)."""
    import os

    return os.name != "nt"  # Not Windows


HAS_SIGNALS = _supports_signals()
REQUIRES_SIGNALS = "Signal-based timeout not available on Windows"
requires_signals = not HAS_SIGNALS


# PostgreSQL database availability
def _has_postgres_configured() -> bool:
    """Check if PostgreSQL is configured via environment."""
    database_url = os.environ.get("DATABASE_URL", "")
    return "postgres" in database_url.lower()


HAS_POSTGRES_CONFIGURED = _has_postgres_configured()
REQUIRES_POSTGRES = "PostgreSQL not configured (set DATABASE_URL)"
requires_postgres = not HAS_POSTGRES_CONFIGURED


# Helper function for use in skipif decorators
def _z3_installed() -> bool:
    """Check if Z3 is installed (for use in decorators)."""
    try:
        import z3

        return True
    except ImportError:
        return False


# Make this available at module level for skipif decorators
Z3_AVAILABLE = _z3_installed()


# ============================================================================
# Test Tier Configuration
# ============================================================================

_CUSTOM_PYTEST_MARKERS: dict[str, str] = {
    "smoke": "quick sanity tests for fast CI feedback",
    "integration": "tests requiring external dependencies (APIs, databases)",
    "integration_minimal": "minimal integration coverage with lighter external setup",
    "slow": "long-running tests (>30 seconds)",
    "unit": "isolated unit tests with no external dependencies",
    "network": "tests requiring external network calls (skip with -m 'not network')",
    "e2e": "end-to-end tests that exercise full user or system flows",
    "knowledge": "knowledge mound and retrieval focused tests",
    "performance": "performance-sensitive scenarios and SLA checks",
    "load": "load or stress scenarios that may be heavier than standard tests",
    "audit": "audit trail, retention, or compliance evidence scenarios",
    "compliance": "regulatory or policy compliance workflows",
    "enterprise": "enterprise-specific features such as SSO or tenant controls",
    "new_features": "coverage for newly introduced product surfaces",
    "serial": "must run serially to avoid shared-state contention",
    "benchmark": "benchmark-style tests, often exercised in nightly or perf runs",
    "flaky": "tests using retry semantics for known intermittent environments",
    "rate_limit_test": "opt out of auth-time rate-limit bypass and exercise real rate limiting",
    "no_auto_auth": "disable automatic auth bypass for handler tests",
}


def pytest_configure(config):
    """Register custom pytest markers and configure test environment.

    Test Tiers:
    - smoke: Quick sanity tests for CI (<5 min total)
    - integration: Tests requiring external dependencies (APIs, DBs)
    - slow: Long-running tests (>30s each)

    CI Strategy:
    - PR CI: pytest -m "not slow and not integration" (~5 min)
    - Nightly: pytest (full suite)

    Environment Configuration:
    - Sets ARAGORA_AUTH_CLEANUP_INTERVAL to 1 second for fast test cleanup.
      This prevents the 300-second default from blocking test completion.

    Usage:
        @pytest.mark.smoke
        def test_basic_import():
            ...

        @pytest.mark.slow
        def test_full_debate_with_all_agents():
            ...

        @pytest.mark.integration
        def test_supabase_connection():
            ...
    """
    # Set fast auth cleanup interval for tests (1 second instead of 300)
    # This prevents test timeouts caused by long cleanup waits
    if "ARAGORA_AUTH_CLEANUP_INTERVAL" not in os.environ:
        os.environ["ARAGORA_AUTH_CLEANUP_INTERVAL"] = "1"

    for marker, description in _CUSTOM_PYTEST_MARKERS.items():
        config.addinivalue_line("markers", f"{marker}: {description}")


# ============================================================================
# Skip Count Monitoring
# ============================================================================

SKIP_THRESHOLD = 200  # Raised from 150 to accommodate contract matrix parametrized skips
UNCONDITIONAL_SKIP_THRESHOLD = (
    0  # No unconditional @pytest.mark.skip allowed (was 1, converted last one to xfail)
)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Warn if skip count exceeds threshold."""
    skipped = len(terminalreporter.stats.get("skipped", []))

    if skipped > SKIP_THRESHOLD:
        terminalreporter.write_line("")
        terminalreporter.write_line(
            f"WARNING: Skip count ({skipped}) exceeds threshold ({SKIP_THRESHOLD})",
            yellow=True,
            bold=True,
        )
        terminalreporter.write_line(
            "  Review tests/SKIP_AUDIT.md and reduce skipped tests.", yellow=True
        )
        terminalreporter.write_line("")
