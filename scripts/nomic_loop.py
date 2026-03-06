#!/usr/bin/env python3
"""
Nomic Loop: Autonomous self-improvement cycle for aragora.

Like a PCR machine for code evolution:
1. DEBATE: All agents propose improvements to aragora
2. CONSENSUS: Agents critique and refine until consensus
3. DESIGN: Agents design the implementation
4. IMPLEMENT: Agents write the code
5. VERIFY: Run tests, check quality
6. COMMIT: If verified, commit changes
7. REPEAT: Cycle continues

The dialectic tension between models (visionary vs pragmatic vs synthesizer)
creates emergent complexity and self-criticality.

Inspired by:
- Nomic (game where rules change the rules)
- Project Sid (emergent civilization)
- PCR (exponential amplification through cycles)
- Self-organized criticality (sandpile dynamics)

SAFETY: This file includes backup/restore mechanisms and safety prompts
to prevent the nomic loop from breaking itself.

NOTE: Utility modules have been extracted to scripts/nomic/ package:
- scripts/nomic/recovery.py: PhaseError, PhaseRecovery
- scripts/nomic/circuit_breaker.py: AgentCircuitBreaker
- scripts/nomic/safety/checksums.py: Protected file verification
- scripts/nomic/safety/backups.py: Backup/restore functionality
- scripts/nomic/git/operations.py: Git operations
- scripts/nomic/config.py: Configuration constants

PHASE IMPLEMENTATIONS (2026-01):
Modular phase classes are now the default (enabled via USE_EXTRACTED_PHASES=1):
- scripts/nomic/phases/context.py: ContextPhase (codebase exploration)
- scripts/nomic/phases/debate.py: DebatePhase (improvement proposals)
- scripts/nomic/phases/design.py: DesignPhase (architecture planning)
- scripts/nomic/phases/implement.py: ImplementPhase (code generation)
- scripts/nomic/phases/verify.py: VerifyPhase (testing & quality)
- scripts/nomic/phases/commit.py: CommitPhase (git operations)

PHASE 10C CONSOLIDATION (2026-01):
Legacy inline phase implementations have been REMOVED. The extracted phase
classes in scripts/nomic/phases/ are now REQUIRED. The USE_EXTRACTED_PHASES
environment variable has no effect (extracted phases are always used).

This consolidation reduced the file from ~10,650 lines to ~8,300 lines by
removing ~2,350 lines of deprecated inline phase implementations.

If you encounter issues, ensure scripts/nomic/phases/ is available.
Report issues at: https://github.com/anthropics/aragora/issues
"""

import asyncio
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Any
from collections.abc import Callable
import traceback
import logging
from collections import defaultdict

if TYPE_CHECKING:
    from aragora.core import DebateResult, DisagreementReport

# Configure module logger
logger = logging.getLogger(__name__)

# Import config for database paths (consolidated persona database)
from aragora.persistence.db_config import DatabaseType, get_db_path

# Import tracing for distributed observability (NoOp when OTel not configured)
from aragora.observability.tracing import get_tracer
from aragora.nomic.sica_settings import load_sica_settings

# =============================================================================
# MODULAR PACKAGE IMPORTS (scripts/nomic/)
# These modules are extracted versions of the code below, available for reuse
# =============================================================================
_NOMIC_PACKAGE_IMPORT_ERROR: Exception | None = None
_NOMIC_PHASES_IMPORT_ERROR: Exception | None = None

try:
    from scripts.nomic import (
        PhaseError as _PhaseError,
        PhaseRecovery as _PhaseRecovery,
        AgentCircuitBreaker as _AgentCircuitBreaker,
    )
    from scripts.nomic.safety import (
        PROTECTED_FILES as _PROTECTED_FILES,
        SAFETY_PREAMBLE as _SAFETY_PREAMBLE,
        compute_file_checksum as _compute_file_checksum,
        init_protected_checksums as _init_protected_checksums,
        verify_protected_files_unchanged as _verify_protected_files_unchanged,
        get_protected_checksums as _get_protected_checksums,
        ConstitutionVerifier as _ConstitutionVerifier,
        DEFAULT_CONSTITUTION_PATH as _DEFAULT_CONSTITUTION_PATH,
    )
    from aragora.debate.outcome_tracker import (
        OutcomeTracker as _OutcomeTracker,
        ConsensusOutcome as _ConsensusOutcome,
    )
    from scripts.nomic.config import (
        NOMIC_AUTO_COMMIT as _NOMIC_AUTO_COMMIT,
        NOMIC_AUTO_CONTINUE as _NOMIC_AUTO_CONTINUE,
        NOMIC_MAX_CYCLE_SECONDS as _NOMIC_MAX_CYCLE_SECONDS,
        NOMIC_STALL_THRESHOLD as _NOMIC_STALL_THRESHOLD,
        NOMIC_FIX_DEADLINE_BUFFER as _NOMIC_FIX_DEADLINE_BUFFER,
        NOMIC_FIX_ITERATION_BUDGET as _NOMIC_FIX_ITERATION_BUDGET,
        NOMIC_AUTO_CHECKPOINT as _NOMIC_AUTO_CHECKPOINT,
        NOMIC_TESTFIXER_ENABLED as _NOMIC_TESTFIXER_ENABLED,
        NOMIC_TESTFIXER_TEST_COMMAND as _NOMIC_TESTFIXER_TEST_COMMAND,
        NOMIC_TESTFIXER_TEST_TIMEOUT as _NOMIC_TESTFIXER_TEST_TIMEOUT,
        NOMIC_TESTFIXER_MAX_ITERATIONS as _NOMIC_TESTFIXER_MAX_ITERATIONS,
        NOMIC_TESTFIXER_MAX_SAME_FAILURE as _NOMIC_TESTFIXER_MAX_SAME_FAILURE,
        NOMIC_TESTFIXER_MIN_CONFIDENCE as _NOMIC_TESTFIXER_MIN_CONFIDENCE,
        NOMIC_TESTFIXER_MIN_AUTO_CONFIDENCE as _NOMIC_TESTFIXER_MIN_AUTO_CONFIDENCE,
        NOMIC_TESTFIXER_REQUIRE_CONSENSUS as _NOMIC_TESTFIXER_REQUIRE_CONSENSUS,
        NOMIC_TESTFIXER_REQUIRE_APPROVAL as _NOMIC_TESTFIXER_REQUIRE_APPROVAL,
        NOMIC_TESTFIXER_REVERT_ON_FAILURE as _NOMIC_TESTFIXER_REVERT_ON_FAILURE,
        NOMIC_TESTFIXER_STOP_ON_FIRST_SUCCESS as _NOMIC_TESTFIXER_STOP_ON_FIRST_SUCCESS,
        NOMIC_TESTFIXER_AGENTS as _NOMIC_TESTFIXER_AGENTS,
        NOMIC_TESTFIXER_USE_LLM_ANALYZER as _NOMIC_TESTFIXER_USE_LLM_ANALYZER,
        NOMIC_TESTFIXER_ANALYSIS_AGENTS as _NOMIC_TESTFIXER_ANALYSIS_AGENTS,
        NOMIC_TESTFIXER_ANALYSIS_REQUIRE_CONSENSUS as _NOMIC_TESTFIXER_ANALYSIS_REQUIRE_CONSENSUS,
        NOMIC_TESTFIXER_ANALYSIS_CONSENSUS_THRESHOLD as _NOMIC_TESTFIXER_ANALYSIS_CONSENSUS_THRESHOLD,
        NOMIC_TESTFIXER_ARENA_VALIDATE as _NOMIC_TESTFIXER_ARENA_VALIDATE,
        NOMIC_TESTFIXER_ARENA_AGENTS as _NOMIC_TESTFIXER_ARENA_AGENTS,
        NOMIC_TESTFIXER_ARENA_ROUNDS as _NOMIC_TESTFIXER_ARENA_ROUNDS,
        NOMIC_TESTFIXER_ARENA_MIN_CONFIDENCE as _NOMIC_TESTFIXER_ARENA_MIN_CONFIDENCE,
        NOMIC_TESTFIXER_ARENA_REQUIRE_CONSENSUS as _NOMIC_TESTFIXER_ARENA_REQUIRE_CONSENSUS,
        NOMIC_TESTFIXER_ARENA_CONSENSUS_THRESHOLD as _NOMIC_TESTFIXER_ARENA_CONSENSUS_THRESHOLD,
        NOMIC_TESTFIXER_REDTEAM_VALIDATE as _NOMIC_TESTFIXER_REDTEAM_VALIDATE,
        NOMIC_TESTFIXER_REDTEAM_ATTACKERS as _NOMIC_TESTFIXER_REDTEAM_ATTACKERS,
        NOMIC_TESTFIXER_REDTEAM_DEFENDER as _NOMIC_TESTFIXER_REDTEAM_DEFENDER,
        NOMIC_TESTFIXER_REDTEAM_ROUNDS as _NOMIC_TESTFIXER_REDTEAM_ROUNDS,
        NOMIC_TESTFIXER_REDTEAM_ATTACKS_PER_ROUND as _NOMIC_TESTFIXER_REDTEAM_ATTACKS_PER_ROUND,
        NOMIC_TESTFIXER_REDTEAM_MIN_ROBUSTNESS as _NOMIC_TESTFIXER_REDTEAM_MIN_ROBUSTNESS,
        NOMIC_TESTFIXER_PATTERN_LEARNING as _NOMIC_TESTFIXER_PATTERN_LEARNING,
        NOMIC_TESTFIXER_PATTERN_STORE as _NOMIC_TESTFIXER_PATTERN_STORE,
        NOMIC_TESTFIXER_GENERATION_TIMEOUT as _NOMIC_TESTFIXER_GENERATION_TIMEOUT,
        NOMIC_TESTFIXER_CRITIQUE_TIMEOUT as _NOMIC_TESTFIXER_CRITIQUE_TIMEOUT,
        NOMIC_SICA_ENABLED as _NOMIC_SICA_ENABLED,
        NOMIC_SICA_IMPROVEMENT_TYPES as _NOMIC_SICA_IMPROVEMENT_TYPES,
        NOMIC_SICA_GENERATOR_MODEL as _NOMIC_SICA_GENERATOR_MODEL,
        NOMIC_SICA_REQUIRE_APPROVAL as _NOMIC_SICA_REQUIRE_APPROVAL,
        NOMIC_SICA_RUN_TESTS as _NOMIC_SICA_RUN_TESTS,
        NOMIC_SICA_RUN_TYPECHECK as _NOMIC_SICA_RUN_TYPECHECK,
        NOMIC_SICA_RUN_LINT as _NOMIC_SICA_RUN_LINT,
        NOMIC_SICA_TEST_COMMAND as _NOMIC_SICA_TEST_COMMAND,
        NOMIC_SICA_TYPECHECK_COMMAND as _NOMIC_SICA_TYPECHECK_COMMAND,
        NOMIC_SICA_LINT_COMMAND as _NOMIC_SICA_LINT_COMMAND,
        NOMIC_SICA_VALIDATION_TIMEOUT as _NOMIC_SICA_VALIDATION_TIMEOUT,
        NOMIC_SICA_MAX_OPPORTUNITIES as _NOMIC_SICA_MAX_OPPORTUNITIES,
        NOMIC_SICA_MAX_ROLLBACKS as _NOMIC_SICA_MAX_ROLLBACKS,
    )
    from scripts.nomic.error_taxonomy import (
        classify_error as _classify_error,
        ErrorPattern as _ErrorPattern,
        format_learning_summary as _format_learning_summary,
    )

    _NOMIC_PACKAGE_AVAILABLE = True
except ImportError as exc:
    _NOMIC_PACKAGE_AVAILABLE = False
    _NOMIC_PACKAGE_IMPORT_ERROR = exc

try:
    # Import extracted phase classes from aragora.nomic package
    from aragora.nomic.phases import (
        ContextPhase,
        DebatePhase,
        DesignPhase,
        ImplementPhase,
        VerifyPhase,
        CommitPhase,
        DebateConfig,
        DesignConfig,
        LearningContext,
        BeliefContext,
        PostDebateHooks,
        # Phase validation for safe state transitions
        PhaseValidator,
        PhaseValidationError,
    )

    _NOMIC_PHASES_AVAILABLE = True
except ImportError as exc:
    _NOMIC_PHASES_AVAILABLE = False
    _NOMIC_PHASES_IMPORT_ERROR = exc

# Import IssueGenerator for structured topic generation
try:
    from scripts.issue_generator import (
        IssueGenerator,
        IssueSelector,
        Issue,
        load_issue_history,
        save_issue_attempt,
    )

    _ISSUE_GENERATOR_AVAILABLE = True
except ImportError:
    _ISSUE_GENERATOR_AVAILABLE = False
    IssueGenerator = None
    IssueSelector = None
    Issue = None

# =============================================================================
# AUTOMATION FLAGS - Environment variables for CI/automation support
# =============================================================================

# Auto-commit: Skip interactive commit prompt (default OFF - requires explicit opt-in)
NOMIC_AUTO_COMMIT = os.environ.get("NOMIC_AUTO_COMMIT", "0") == "1"

# Auto-continue: Skip interactive cycle continuation prompt (default ON for loops)
NOMIC_AUTO_CONTINUE = os.environ.get("NOMIC_AUTO_CONTINUE", "1") == "1"

# Cycle-level hard timeout in seconds (default 2 hours)
NOMIC_MAX_CYCLE_SECONDS = int(os.environ.get("NOMIC_MAX_CYCLE_SECONDS", "7200"))

# Total execution timeout across all cycles (default 1 hour; 0 = unlimited)
NOMIC_MAX_TOTAL_SECONDS = int(os.environ.get("NOMIC_MAX_TOTAL_SECONDS", "3600"))

# Maximum estimated cost in USD before aborting (default $100; 0 = unlimited)
NOMIC_MAX_COST_USD = float(os.environ.get("NOMIC_MAX_COST_USD", "100.0"))

# Stall detection threshold in seconds (default 30 minutes)
NOMIC_STALL_THRESHOLD = int(os.environ.get("NOMIC_STALL_THRESHOLD", "1800"))

# Minimum time buffer before deadline to exit verify-fix loop (default 5 minutes)
NOMIC_FIX_DEADLINE_BUFFER = int(os.environ.get("NOMIC_FIX_DEADLINE_BUFFER", "300"))

# Time allocation per fix iteration in seconds (default 10 minutes)
NOMIC_FIX_ITERATION_BUDGET = int(os.environ.get("NOMIC_FIX_ITERATION_BUDGET", "600"))

# Enable automatic checkpointing between phases (default ON)
NOMIC_AUTO_CHECKPOINT = os.environ.get("NOMIC_AUTO_CHECKPOINT", "1") == "1"


# =============================================================================
# TESTFIXER FLAGS - Automated test repair loop integration
# =============================================================================

NOMIC_TESTFIXER_ENABLED = os.environ.get("NOMIC_TESTFIXER_ENABLED", "1") == "1"
NOMIC_TESTFIXER_TEST_COMMAND = os.environ.get(
    "NOMIC_TESTFIXER_TEST_COMMAND", "pytest tests/ -q --maxfail=1"
)
NOMIC_TESTFIXER_TEST_TIMEOUT = int(os.environ.get("NOMIC_TESTFIXER_TEST_TIMEOUT", "600"))
NOMIC_TESTFIXER_MAX_ITERATIONS = int(os.environ.get("NOMIC_TESTFIXER_MAX_ITERATIONS", "5"))
NOMIC_TESTFIXER_MAX_SAME_FAILURE = int(os.environ.get("NOMIC_TESTFIXER_MAX_SAME_FAILURE", "3"))
NOMIC_TESTFIXER_MIN_CONFIDENCE = float(os.environ.get("NOMIC_TESTFIXER_MIN_CONFIDENCE", "0.5"))
NOMIC_TESTFIXER_MIN_AUTO_CONFIDENCE = float(
    os.environ.get("NOMIC_TESTFIXER_MIN_AUTO_CONFIDENCE", "0.7")
)
NOMIC_TESTFIXER_REQUIRE_CONSENSUS = os.environ.get("NOMIC_TESTFIXER_REQUIRE_CONSENSUS", "0") == "1"
NOMIC_TESTFIXER_REQUIRE_APPROVAL = os.environ.get("NOMIC_TESTFIXER_REQUIRE_APPROVAL", "0") == "1"
NOMIC_TESTFIXER_REVERT_ON_FAILURE = os.environ.get("NOMIC_TESTFIXER_REVERT_ON_FAILURE", "1") == "1"
NOMIC_TESTFIXER_STOP_ON_FIRST_SUCCESS = (
    os.environ.get("NOMIC_TESTFIXER_STOP_ON_FIRST_SUCCESS", "0") == "1"
)
NOMIC_TESTFIXER_AGENTS = os.environ.get("NOMIC_TESTFIXER_AGENTS", "codex,claude")
NOMIC_TESTFIXER_USE_LLM_ANALYZER = os.environ.get("NOMIC_TESTFIXER_USE_LLM_ANALYZER", "0") == "1"
NOMIC_TESTFIXER_ANALYSIS_AGENTS = os.environ.get("NOMIC_TESTFIXER_ANALYSIS_AGENTS", "")
NOMIC_TESTFIXER_ANALYSIS_REQUIRE_CONSENSUS = (
    os.environ.get("NOMIC_TESTFIXER_ANALYSIS_REQUIRE_CONSENSUS", "0") == "1"
)
NOMIC_TESTFIXER_ANALYSIS_CONSENSUS_THRESHOLD = float(
    os.environ.get("NOMIC_TESTFIXER_ANALYSIS_CONSENSUS_THRESHOLD", "0.7")
)
NOMIC_TESTFIXER_ARENA_VALIDATE = os.environ.get("NOMIC_TESTFIXER_ARENA_VALIDATE", "0") == "1"
NOMIC_TESTFIXER_ARENA_AGENTS = os.environ.get("NOMIC_TESTFIXER_ARENA_AGENTS", "")
NOMIC_TESTFIXER_ARENA_ROUNDS = int(os.environ.get("NOMIC_TESTFIXER_ARENA_ROUNDS", "2"))
NOMIC_TESTFIXER_ARENA_MIN_CONFIDENCE = float(
    os.environ.get("NOMIC_TESTFIXER_ARENA_MIN_CONFIDENCE", "0.6")
)
NOMIC_TESTFIXER_ARENA_REQUIRE_CONSENSUS = (
    os.environ.get("NOMIC_TESTFIXER_ARENA_REQUIRE_CONSENSUS", "0") == "1"
)
NOMIC_TESTFIXER_ARENA_CONSENSUS_THRESHOLD = float(
    os.environ.get("NOMIC_TESTFIXER_ARENA_CONSENSUS_THRESHOLD", "0.7")
)
NOMIC_TESTFIXER_REDTEAM_VALIDATE = os.environ.get("NOMIC_TESTFIXER_REDTEAM_VALIDATE", "0") == "1"
NOMIC_TESTFIXER_REDTEAM_ATTACKERS = os.environ.get("NOMIC_TESTFIXER_REDTEAM_ATTACKERS", "")
NOMIC_TESTFIXER_REDTEAM_DEFENDER = os.environ.get("NOMIC_TESTFIXER_REDTEAM_DEFENDER", "")
NOMIC_TESTFIXER_REDTEAM_ROUNDS = int(os.environ.get("NOMIC_TESTFIXER_REDTEAM_ROUNDS", "2"))
NOMIC_TESTFIXER_REDTEAM_ATTACKS_PER_ROUND = int(
    os.environ.get("NOMIC_TESTFIXER_REDTEAM_ATTACKS_PER_ROUND", "3")
)
NOMIC_TESTFIXER_REDTEAM_MIN_ROBUSTNESS = float(
    os.environ.get("NOMIC_TESTFIXER_REDTEAM_MIN_ROBUSTNESS", "0.6")
)
NOMIC_TESTFIXER_PATTERN_LEARNING = os.environ.get("NOMIC_TESTFIXER_PATTERN_LEARNING", "1") == "1"
NOMIC_TESTFIXER_PATTERN_STORE = os.environ.get(
    "NOMIC_TESTFIXER_PATTERN_STORE", ".nomic/testfixer/patterns.json"
)
NOMIC_TESTFIXER_GENERATION_TIMEOUT = float(
    os.environ.get("NOMIC_TESTFIXER_GENERATION_TIMEOUT", "600")
)
NOMIC_TESTFIXER_CRITIQUE_TIMEOUT = float(os.environ.get("NOMIC_TESTFIXER_CRITIQUE_TIMEOUT", "300"))


# =============================================================================
# SICA FLAGS - Self-Improving Code Assistant integration
# =============================================================================

_SICA_SETTINGS = load_sica_settings()
NOMIC_SICA_ENABLED = _SICA_SETTINGS.enabled
NOMIC_SICA_IMPROVEMENT_TYPES = _SICA_SETTINGS.improvement_types_csv
NOMIC_SICA_GENERATOR_MODEL = _SICA_SETTINGS.generator_model
NOMIC_SICA_REQUIRE_APPROVAL = _SICA_SETTINGS.require_approval
NOMIC_SICA_RUN_TESTS = _SICA_SETTINGS.run_tests
NOMIC_SICA_RUN_TYPECHECK = _SICA_SETTINGS.run_typecheck
NOMIC_SICA_RUN_LINT = _SICA_SETTINGS.run_lint
NOMIC_SICA_TEST_COMMAND = _SICA_SETTINGS.test_command
NOMIC_SICA_TYPECHECK_COMMAND = _SICA_SETTINGS.typecheck_command
NOMIC_SICA_LINT_COMMAND = _SICA_SETTINGS.lint_command
NOMIC_SICA_VALIDATION_TIMEOUT = _SICA_SETTINGS.validation_timeout
NOMIC_SICA_MAX_OPPORTUNITIES = _SICA_SETTINGS.max_opportunities
NOMIC_SICA_MAX_ROLLBACKS = _SICA_SETTINGS.max_rollbacks


# =============================================================================
# PHASE RECOVERY - Structured error handling for nomic loop phases
# =============================================================================


class PhaseError(Exception):
    """Exception raised when a phase fails."""

    def __init__(
        self, phase: str, message: str, recoverable: bool = True, original_error: Exception = None
    ):
        self.phase = phase
        self.recoverable = recoverable
        self.original_error = original_error
        super().__init__(f"[{phase}] {message}")


class PhaseRecovery:
    """
    Structured error recovery for nomic loop phases.

    Features:
    - Per-phase retry with exponential backoff
    - Phase-specific error classification
    - Health metrics tracking
    - Automatic rollback triggers
    """

    # Default retry settings per phase
    PHASE_RETRY_CONFIG = {
        "context": {"max_retries": 2, "base_delay": 5, "critical": False},
        "debate": {"max_retries": 1, "base_delay": 10, "critical": True},
        "design": {"max_retries": 2, "base_delay": 5, "critical": False},
        "implement": {"max_retries": 1, "base_delay": 15, "critical": True},
        "verify": {"max_retries": 3, "base_delay": 5, "critical": False},
        "commit": {"max_retries": 1, "base_delay": 5, "critical": True},
    }

    # Individual phase timeouts (seconds) - complements cycle-level timeout
    # Configurable via environment variables: NOMIC_<PHASE>_TIMEOUT
    PHASE_TIMEOUTS = {
        "context": int(
            os.environ.get("NOMIC_CONTEXT_TIMEOUT", "1200")
        ),  # 20 min - codebase exploration (doubled for Codex)
        "debate": int(
            os.environ.get("NOMIC_DEBATE_TIMEOUT", "3600")
        ),  # 60 min - multi-agent discussion (increased from 30)
        "design": int(
            os.environ.get("NOMIC_DESIGN_TIMEOUT", "1800")
        ),  # 30 min - architecture planning (increased from 15)
        "implement": int(
            os.environ.get("NOMIC_IMPLEMENT_TIMEOUT", "2400")
        ),  # 40 min - code generation
        "verify": int(os.environ.get("NOMIC_VERIFY_TIMEOUT", "600")),  # 10 min - test execution
        "commit": int(os.environ.get("NOMIC_COMMIT_TIMEOUT", "180")),  # 3 min - git operations
    }

    # Timeout escalation settings for retries
    # On each retry, timeout is multiplied by escalation factor (capped at max)
    TIMEOUT_ESCALATION_FACTOR = float(os.environ.get("NOMIC_TIMEOUT_ESCALATION", "1.3"))
    TIMEOUT_MAX_MULTIPLIER = float(os.environ.get("NOMIC_TIMEOUT_MAX_MULT", "2.0"))

    # Errors that should NOT be retried
    NON_RETRYABLE_ERRORS = (
        KeyboardInterrupt,
        SystemExit,
        MemoryError,
    )

    # Errors that indicate rate limiting or service issues (should wait longer)
    # Keep in sync with aragora.agents.cli_agents.RATE_LIMIT_PATTERNS
    RATE_LIMIT_PATTERNS = [
        # Rate limiting
        "rate limit",
        "rate_limit",
        "ratelimit",
        "429",
        "too many requests",
        "throttl",
        # Quota/usage limit errors
        "quota exceeded",
        "quota_exceeded",
        "resource exhausted",
        "resource_exhausted",
        "insufficient_quota",
        "limit exceeded",
        "usage_limit",
        "usage limit",  # OpenAI/Codex usage limits
        "limit has been reached",
        # Billing errors
        "billing",
        "credit balance",
        "payment required",
        "purchase credits",
        "402",
        # Capacity/availability errors
        "503",
        "service unavailable",
        "502",
        "bad gateway",
        "overloaded",
        "capacity",
        "temporarily unavailable",
        "try again later",
        "server busy",
        "high demand",
        # API-specific errors
        "model overloaded",
        "model is currently overloaded",
        "engine is currently overloaded",
        # CLI-specific errors
        "argument list too long",  # E2BIG - prompt too large for CLI
        "broken pipe",  # EPIPE - connection closed unexpectedly
    ]

    def __init__(self, log_func: Callable = print):
        self.log = log_func
        self.phase_health: dict[str, dict] = {}
        self.consecutive_failures: dict[str, int] = {}
        self.current_attempt: dict[str, int] = {}  # Track current attempt for timeout escalation

    def is_retryable(self, error: Exception, phase: str) -> bool:
        """Check if an error should be retried."""
        if isinstance(error, self.NON_RETRYABLE_ERRORS):
            return False

        # Check if phase has retries left
        config = self.PHASE_RETRY_CONFIG.get(phase, {"max_retries": 1})
        failures = self.consecutive_failures.get(phase, 0)

        if failures >= config["max_retries"]:
            return False

        return True

    def get_retry_delay(self, error: Exception, phase: str) -> float:
        """Calculate delay before retry with exponential backoff."""
        config = self.PHASE_RETRY_CONFIG.get(phase, {"base_delay": 5})
        base = config["base_delay"]
        failures = self.consecutive_failures.get(phase, 0)

        # Exponential backoff: base * 2^failures
        delay = base * (2**failures)

        # Check for rate limiting (use longer delay)
        error_str = str(error).lower()
        if any(pattern in error_str for pattern in self.RATE_LIMIT_PATTERNS):
            delay = max(delay, 120)  # Minimum 120s for rate limits
            self.log(f"  [recovery] Rate limit detected, waiting {delay}s")

        return min(delay, 300)  # Cap at 5 minutes

    def get_escalated_timeout(self, phase: str, attempt: int = 0) -> float:
        """
        Calculate escalated timeout for retry attempts.

        Each retry gets more time (up to max multiplier) to handle
        slow but eventually successful operations.

        Args:
            phase: Phase name
            attempt: Current attempt number (0 = first try)

        Returns:
            Timeout in seconds
        """
        base_timeout = self.PHASE_TIMEOUTS.get(phase, 600)
        if attempt == 0:
            return base_timeout

        # Escalate by factor^attempt, capped at max multiplier
        multiplier = min(self.TIMEOUT_ESCALATION_FACTOR**attempt, self.TIMEOUT_MAX_MULTIPLIER)
        escalated = base_timeout * multiplier
        return int(escalated)

    def record_success(self, phase: str) -> None:
        """Record successful phase completion."""
        self.consecutive_failures[phase] = 0
        if phase not in self.phase_health:
            self.phase_health[phase] = {"successes": 0, "failures": 0, "last_error": None}
        self.phase_health[phase]["successes"] += 1

    def record_failure(self, phase: str, error: Exception) -> None:
        """Record phase failure."""
        self.consecutive_failures[phase] = self.consecutive_failures.get(phase, 0) + 1
        if phase not in self.phase_health:
            self.phase_health[phase] = {"successes": 0, "failures": 0, "last_error": None}
        self.phase_health[phase]["failures"] += 1
        self.phase_health[phase]["last_error"] = str(error)[:200]

    def should_trigger_rollback(self, phase: str) -> bool:
        """Check if failures warrant a rollback."""
        config = self.PHASE_RETRY_CONFIG.get(phase, {"critical": False})
        if not config["critical"]:
            return False

        # Rollback if critical phase has consecutive failures
        failures = self.consecutive_failures.get(phase, 0)
        return failures >= 2

    def get_health_report(self) -> dict:
        """Get health metrics for all phases."""
        return {
            "phase_health": self.phase_health,
            "consecutive_failures": self.consecutive_failures,
        }

    async def run_with_recovery(
        self, phase: str, phase_func: Callable, *args, **kwargs
    ) -> tuple[bool, Any]:
        """
        Run a phase function with automatic retry and recovery.

        Tracks current attempt number for timeout escalation. The attempt
        count is accessible via self.current_attempt[phase] so that
        _run_with_phase_timeout can use escalated timeouts.

        Returns:
            (success: bool, result: Any or error message)
        """
        config = self.PHASE_RETRY_CONFIG.get(phase, {"max_retries": 1})
        attempts = 0

        # Initialize attempt tracking for this phase
        self.current_attempt[phase] = 0

        while attempts <= config["max_retries"]:
            try:
                # Update current attempt before execution (for timeout escalation)
                self.current_attempt[phase] = attempts
                result = await phase_func(*args, **kwargs)
                self.record_success(phase)
                # Clean up attempt tracking on success
                self.current_attempt.pop(phase, None)
                return (True, result)

            except self.NON_RETRYABLE_ERRORS:
                self.current_attempt.pop(phase, None)
                raise  # Don't catch these

            except Exception as e:
                attempts += 1
                self.record_failure(phase, e)

                error_msg = f"{type(e).__name__}: {str(e)[:200]}"
                self.log(f"  [recovery] Phase '{phase}' attempt {attempts} failed: {error_msg}")

                if self.is_retryable(e, phase) and attempts <= config["max_retries"]:
                    delay = self.get_retry_delay(e, phase)
                    next_timeout = self.get_escalated_timeout(phase, attempts)
                    self.log(
                        f"  [recovery] Retrying in {delay:.0f}s with {next_timeout}s timeout..."
                    )
                    await asyncio.sleep(delay)
                else:
                    # Log full traceback for debugging
                    logger.error(f"Phase {phase} failed after {attempts} attempts", exc_info=True)

                    if self.should_trigger_rollback(phase):
                        self.log(f"  [recovery] CRITICAL: Phase '{phase}' requires rollback")

                    self.current_attempt.pop(phase, None)
                    return (False, str(e))

        self.current_attempt.pop(phase, None)
        return (False, "Max retries exceeded")


# =============================================================================
# SAFETY CONSTANTS - Files that must NEVER be deleted or broken
# =============================================================================
PROTECTED_FILES = [
    # Core nomic loop infrastructure
    "scripts/nomic_loop.py",  # The nomic loop itself - CRITICAL
    "scripts/run_nomic_with_stream.py",  # Streaming wrapper - protects --auto flag
    # Core aragora modules
    "aragora/__init__.py",  # Core package initialization
    "aragora/core/__init__.py",  # Core package surface
    "aragora/core_types.py",  # Core types and abstractions
    "aragora/debate/orchestrator.py",  # Debate infrastructure
    "aragora/agents/__init__.py",  # Agent system
    "aragora/implement/__init__.py",  # Implementation system
    # Valuable features added by nomic loop
    "aragora/agents/cli_agents.py",  # CLI agent harnesses (KiloCode, Claude, Codex, Grok)
    "aragora/server/stream.py",  # Streaming, AudienceInbox, TokenBucket
    "aragora/memory/store.py",  # CritiqueStore, AgentReputation
    "aragora/debate/embeddings.py",  # DebateEmbeddingsDatabase for historical search
    # Live dashboard (web interface)
    "aragora/live/src/components/AgentPanel.tsx",  # Agent activity panel with colors
    "aragora/live/src/components/UserParticipation.tsx",  # User participation UI
    "aragora/live/src/app/page.tsx",  # Main dashboard page
    "aragora/live/tailwind.config.js",  # Tailwind config with agent colors
]

# Global cache for protected file checksums (computed at startup)
_PROTECTED_FILE_CHECKSUMS: dict[str, str] = {}


def _compute_file_checksum(filepath: Path) -> str:
    """Compute SHA-256 checksum of a file."""

    if not filepath.exists():
        return ""
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]  # Short hash for logging


def _init_protected_checksums(base_path: Path) -> dict[str, str]:
    """Initialize checksums for all protected files at startup."""
    global _PROTECTED_FILE_CHECKSUMS
    for rel_path in PROTECTED_FILES:
        full_path = base_path / rel_path
        if full_path.exists():
            _PROTECTED_FILE_CHECKSUMS[rel_path] = _compute_file_checksum(full_path)
    return _PROTECTED_FILE_CHECKSUMS


def verify_protected_files_unchanged(base_path: Path) -> tuple[bool, list[str]]:
    """
    Verify that protected files haven't been unexpectedly modified.

    Security measure: Detects accidental or malicious modifications to
    critical infrastructure between phases.

    Returns:
        Tuple of (all_ok, list of modified files)
    """
    modified = []
    for rel_path, expected_hash in _PROTECTED_FILE_CHECKSUMS.items():
        full_path = base_path / rel_path
        current_hash = _compute_file_checksum(full_path)
        if current_hash != expected_hash:
            modified.append(rel_path)
    return len(modified) == 0, modified


SAFETY_PREAMBLE = """
=== CRITICAL SAFETY RULES ===
You are modifying a self-improving system. These rules are NON-NEGOTIABLE:

1. NEVER DELETE OR BREAK:
   - scripts/nomic_loop.py (the loop itself)
   - aragora/__init__.py (core package)
   - aragora/core.py (core types)
   - aragora/debate/orchestrator.py (debate infrastructure)
   - Any file that enables the nomic loop to function

2. ANABOLISM OVER CATABOLISM:
   - ADD features, don't remove working ones
   - EXTEND functionality, don't simplify it away
   - Only remove code that is BROKEN or HARMFUL
   - When in doubt, keep existing functionality

3. PRESERVE CORE CAPABILITIES:
   - Multi-agent debate must keep working
   - File logging must keep working
   - Git integration must keep working
   - All existing API contracts must be maintained

4. DEFENSIVE CODING:
   - New features should not break existing ones
   - Add tests for new functionality
   - Maintain backward compatibility

5. TECHNICAL DEBT - REDUCE SAFELY:
   - Reducing technical debt is GOOD when it's safe
   - Safe refactoring: improve code without changing behavior
   - UNSAFE: removing functionality, breaking APIs, deleting imports
   - SAFE: renaming for clarity, extracting functions, improving types
   - Test that refactored code works identically to original
   - If unsure whether a change is safe, DON'T MAKE IT

6. AGENT PROMPTS ARE SACRED:
   - NEVER modify agent system prompts in the codebase
   - Agent prompts define the personalities and safety constraints
   - Changes to agent prompts require UNANIMOUS consent from all agents
   - If ANY doubt exists about modifying prompts, DO NOT MODIFY THEM
   - This includes prompts in: nomic_loop.py, agents/*.py, any prompt templates
   - The only exception: fixing an obvious typo or syntax error
===========================
"""


# Load .env file if present
def load_dotenv(env_path: Path):
    """Load environment variables from .env file."""
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


# Load .env from aragora root
_script_dir = Path(__file__).parent
_env_file = _script_dir.parent / ".env"
load_dotenv(_env_file)

# Add aragora to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from aragora.debate.orchestrator import Arena, DebateProtocol
from aragora.debate.roles import RoleRotationConfig, CognitiveRole
from aragora.core import Environment
from aragora.agents.api_agents import (
    GeminiAgent,
    DeepSeekV3Agent,
    MistralAgent,
    QwenAgent,
    KimiK2Agent,
    OpenAIAPIAgent,
    OpenRouterAgent,
)
from aragora.agents.cli_agents import CodexAgent, ClaudeAgent, GrokCLIAgent, KiloCodeAgent
from aragora.agents.api_agents import GrokAgent
from aragora.config.settings import AgentSettings, DebateSettings
from aragora.agents.airlock import AirlockProxy, AirlockConfig
from aragora.nomic.convoy_executor import GastownConvoyExecutor

# Check if Kilo Code CLI is available for Gemini/Grok codebase exploration
KILOCODE_AVAILABLE = False
_kilocode_env = os.environ.get("NOMIC_KILOCODE_AVAILABLE")
if _kilocode_env is not None:
    KILOCODE_AVAILABLE = _kilocode_env.strip().lower() in {"1", "true", "yes", "on"}
else:
    try:
        import shutil

        KILOCODE_AVAILABLE = (shutil.which("kilo") is not None) or (
            shutil.which("kilocode") is not None
        )
    except Exception:
        pass

# Skip KiloCode agents during context gathering phase (agentic codebase exploration)
# KiloCode's agentic exploration can be slow; Gemini/Grok still participate in debates via direct API calls.
# Allow override via env to enable Gemini/Grok exploration in context.
_skip_kilocode_env = os.environ.get("NOMIC_SKIP_KILOCODE_CONTEXT_GATHERING")
if _skip_kilocode_env is None:
    _skip_kilocode_env = os.environ.get("NOMIC_SKIP_KILOCODE_CONTEXT")
SKIP_KILOCODE_CONTEXT_GATHERING = (
    str(_skip_kilocode_env).strip().lower() in {"1", "true", "yes", "on"}
    if _skip_kilocode_env is not None
    else True
)

# Genesis module for fractal debates with agent evolution
GENESIS_AVAILABLE = False
try:
    from aragora.genesis import (
        FractalOrchestrator,
        PopulationManager,
        GenesisLedger,
        create_genesis_hooks,
        create_logging_hooks,
    )

    GENESIS_AVAILABLE = True
except ImportError:
    pass
from aragora.implement import (
    generate_implement_plan,
    create_single_task_plan,
    HybridExecutor,
    load_progress,
    save_progress,
    clear_progress,
    ImplementProgress,
)

# Optional streaming support
try:
    from aragora.server.stream import SyncEventEmitter, create_arena_hooks
    from aragora.server.nomic_stream import create_nomic_hooks

    STREAMING_AVAILABLE = True
except ImportError:
    STREAMING_AVAILABLE = False
    SyncEventEmitter = None
    create_nomic_hooks = None
    create_arena_hooks = None

# Optional Supabase persistence
try:
    from aragora.persistence import SupabaseClient, NomicCycle, StreamEvent, DebateArtifact

    PERSISTENCE_AVAILABLE = True
except ImportError:
    PERSISTENCE_AVAILABLE = False
    SupabaseClient = None
    NomicCycle = None
    StreamEvent = None
    DebateArtifact = None

# Debate embeddings for historical search
try:
    from aragora.debate.embeddings import DebateEmbeddingsDatabase

    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    DebateEmbeddingsDatabase = None

# ContinuumMemory for multi-timescale learning
try:
    from aragora.memory.continuum import ContinuumMemory, MemoryTier

    CONTINUUM_AVAILABLE = True
except ImportError:
    CONTINUUM_AVAILABLE = False
    ContinuumMemory = None
    MemoryTier = None

# DebateStrategy for memory-aware adaptive rounds
STRATEGY_AVAILABLE = False
try:
    from aragora.debate.strategy import DebateStrategy

    STRATEGY_AVAILABLE = True
except ImportError:
    DebateStrategy = None

# CrossDebateMemory for institutional knowledge
CROSS_DEBATE_MEMORY_AVAILABLE = False
try:
    from aragora.memory.cross_debate_rlm import CrossDebateMemory

    CROSS_DEBATE_MEMORY_AVAILABLE = True
except ImportError:
    CrossDebateMemory = None

# ReplayRecorder for cycle event recording
try:
    from aragora.replay.recorder import ReplayRecorder

    REPLAY_AVAILABLE = True
except ImportError:
    REPLAY_AVAILABLE = False
    ReplayRecorder = None

# MetaLearner for self-tuning hyperparameters
try:
    from aragora.learning.meta import MetaLearner

    METALEARNER_AVAILABLE = True
except ImportError:
    METALEARNER_AVAILABLE = False
    MetaLearner = None

# IntrospectionAPI for agent self-awareness
try:
    from aragora.introspection.api import get_agent_introspection, format_introspection_section

    INTROSPECTION_AVAILABLE = True
except ImportError:
    INTROSPECTION_AVAILABLE = False
    get_agent_introspection = None
    format_introspection_section = None

# ArgumentCartographer for debate visualization
try:
    from aragora.visualization.mapper import ArgumentCartographer

    CARTOGRAPHER_AVAILABLE = True
except ImportError:
    CARTOGRAPHER_AVAILABLE = False
    ArgumentCartographer = None

# WebhookDispatcher for external event notifications
try:
    from aragora.integrations.webhooks import WebhookDispatcher, WebhookConfig

    WEBHOOKS_AVAILABLE = True
except ImportError:
    WEBHOOKS_AVAILABLE = False
    WebhookDispatcher = None
    WebhookConfig = None

# ConsensusMemory for tracking settled vs contested topics
try:
    from aragora.memory.consensus import ConsensusMemory, ConsensusStrength, DissentRetriever

    CONSENSUS_MEMORY_AVAILABLE = True
except ImportError:
    CONSENSUS_MEMORY_AVAILABLE = False
    ConsensusMemory = None
    ConsensusStrength = None
    DissentRetriever = None

# InsightExtractor for post-debate pattern learning
try:
    from aragora.insights.extractor import InsightExtractor

    INSIGHTS_AVAILABLE = True
except ImportError:
    INSIGHTS_AVAILABLE = False
    InsightExtractor = None

# FlipDetector for position reversal detection
try:
    from aragora.insights.flip_detector import FlipDetector

    FLIP_DETECTOR_AVAILABLE = True
except ImportError:
    FLIP_DETECTOR_AVAILABLE = False
    FlipDetector = None

# NomicIntegration for advanced feature coordination
try:
    from aragora.nomic.integration import NomicIntegration, create_nomic_integration

    NOMIC_INTEGRATION_AVAILABLE = True
except ImportError:
    NOMIC_INTEGRATION_AVAILABLE = False
    NomicIntegration = None
    create_nomic_integration = None

# MemoryStream for per-agent persistent memory (Phase 3)
try:
    from aragora.memory.streams import MemoryStream

    MEMORY_STREAM_AVAILABLE = True
except ImportError:
    MEMORY_STREAM_AVAILABLE = False
    MemoryStream = None

# LocalDocsConnector for evidence grounding (Phase 3)
try:
    from aragora.connectors.local_docs import LocalDocsConnector

    LOCAL_DOCS_AVAILABLE = True
except ImportError:
    LOCAL_DOCS_AVAILABLE = False
    LocalDocsConnector = None

# CounterfactualOrchestrator for deadlock resolution (Phase 3)
try:
    from aragora.debate.counterfactual import CounterfactualOrchestrator

    COUNTERFACTUAL_AVAILABLE = True
except ImportError:
    COUNTERFACTUAL_AVAILABLE = False
    CounterfactualOrchestrator = None

# CapabilityProber for agent quality assurance (Phase 3)
try:
    from aragora.modes.prober import CapabilityProber, ProbeType

    PROBER_AVAILABLE = True
except ImportError:
    PROBER_AVAILABLE = False
    CapabilityProber = None
    ProbeType = None

# DeepAuditMode for intensive review of protected file changes (Heavy3-inspired)
try:
    from aragora.modes.deep_audit import run_deep_audit, CODE_ARCHITECTURE_AUDIT, DeepAuditConfig

    DEEP_AUDIT_AVAILABLE = True
except ImportError:
    DEEP_AUDIT_AVAILABLE = False
    run_deep_audit = None
    CODE_ARCHITECTURE_AUDIT = None
    DeepAuditConfig = None

# DebateTemplates for structured debate formats (Phase 3)
try:
    from aragora.templates import CODE_REVIEW_TEMPLATE, DESIGN_DOC_TEMPLATE, DebateTemplate

    TEMPLATES_AVAILABLE = True
except ImportError:
    TEMPLATES_AVAILABLE = False
    CODE_REVIEW_TEMPLATE = None
    DESIGN_DOC_TEMPLATE = None
    DebateTemplate = None

# PersonaManager for agent traits/expertise evolution (Phase 4)
try:
    from aragora.agents.personas import PersonaManager, get_or_create_persona, EXPERTISE_DOMAINS

    PERSONAS_AVAILABLE = True
except ImportError:
    PERSONAS_AVAILABLE = False
    PersonaManager = None
    get_or_create_persona = None
    EXPERTISE_DOMAINS = []

# PromptEvolver for prompt evolution from winning patterns (Phase 4)
try:
    from aragora.evolution.evolver import PromptEvolver, EvolutionStrategy

    EVOLVER_AVAILABLE = True
except ImportError:
    EVOLVER_AVAILABLE = False
    PromptEvolver = None
    EvolutionStrategy = None

# Tournament for periodic competitive benchmarking (Phase 4)
try:
    from aragora.tournaments import Tournament, TournamentFormat, create_default_tasks

    TOURNAMENT_AVAILABLE = True
except ImportError:
    TOURNAMENT_AVAILABLE = False
    Tournament = None
    TournamentFormat = None
    create_default_tasks = None

# ConvergenceDetector for early stopping (Phase 5)
try:
    from aragora.debate.convergence import ConvergenceDetector, ConvergenceResult

    CONVERGENCE_AVAILABLE = True
except ImportError:
    CONVERGENCE_AVAILABLE = False
    ConvergenceDetector = None
    ConvergenceResult = None

# MetaCritiqueAnalyzer for process feedback (Phase 5)
try:
    from aragora.debate.meta import MetaCritiqueAnalyzer, MetaCritique

    META_CRITIQUE_AVAILABLE = True
except ImportError:
    META_CRITIQUE_AVAILABLE = False
    MetaCritiqueAnalyzer = None
    MetaCritique = None

# EloSystem for agent skill tracking (Phase 5)
try:
    from aragora.ranking.elo import EloSystem, AgentRating

    ELO_AVAILABLE = True
except ImportError:
    ELO_AVAILABLE = False
    EloSystem = None
    AgentRating = None

# AgentSelector for smart team selection (Phase 5)
try:
    from aragora.routing.selection import AgentSelector, AgentProfile, TaskRequirements

    SELECTOR_AVAILABLE = True
except ImportError:
    SELECTOR_AVAILABLE = False
    AgentSelector = None
    AgentProfile = None
    TaskRequirements = None

# ProbeFilter for probe-aware agent selection (Phase 10)
try:
    from aragora.routing.probe_filter import ProbeFilter, ProbeProfile

    PROBE_FILTER_AVAILABLE = True
except ImportError:
    PROBE_FILTER_AVAILABLE = False
    ProbeFilter = None
    ProbeProfile = None

# RiskRegister for risk tracking (Phase 5)
try:
    from aragora.pipeline.risk_register import RiskLevel

    RISK_REGISTER_AVAILABLE = True
except ImportError:
    RISK_REGISTER_AVAILABLE = False
    RiskLevel = None

# =============================================================================
# Phase 6: Verifiable Reasoning & Robustness Testing
# =============================================================================

# ClaimsKernel for structured reasoning (Phase 6)
try:
    from aragora.reasoning.claims import (
        ClaimsKernel,
        TypedClaim,
        TypedEvidence,
        ClaimRelation,
        ClaimType,
        RelationType,
        EvidenceType,
    )

    CLAIMS_KERNEL_AVAILABLE = True
except ImportError:
    CLAIMS_KERNEL_AVAILABLE = False
    ClaimsKernel = None
    TypedClaim = None
    ClaimType = None
    RelationType = None

# ProvenanceManager for evidence tracking (Phase 6)
try:
    from aragora.reasoning.provenance import (
        ProvenanceManager,
        ProvenanceChain,
        SourceType,
        TransformationType,
    )

    PROVENANCE_AVAILABLE = True
except ImportError:
    PROVENANCE_AVAILABLE = False
    ProvenanceManager = None
    SourceType = None

# BeliefNetwork for probabilistic reasoning (Phase 6)
try:
    from aragora.reasoning.belief import (
        BeliefNetwork,
        BeliefPropagationAnalyzer,
        BeliefDistribution,
    )

    BELIEF_NETWORK_AVAILABLE = True
except ImportError:
    BELIEF_NETWORK_AVAILABLE = False
    BeliefNetwork = None
    BeliefPropagationAnalyzer = None

# ProofExecutor for executable verification (Phase 6)
try:
    from aragora.verification.proofs import (
        ProofExecutor,
        ClaimVerifier,
        VerificationProof,
        VerificationReport,
        ProofType,
        ProofStatus,
        ProofBuilder,
    )

    PROOF_EXECUTOR_AVAILABLE = True
except ImportError:
    PROOF_EXECUTOR_AVAILABLE = False
    ProofExecutor = None
    ClaimVerifier = None
    VerificationReport = None
    ProofBuilder = None

# ScenarioMatrix for robustness testing (Phase 6)
try:
    from aragora.debate.scenarios import (
        ScenarioMatrix,
        MatrixDebateRunner,
        ScenarioComparator,
        Scenario,
        ScenarioType,
        OutcomeCategory,
    )

    SCENARIO_MATRIX_AVAILABLE = True
except ImportError:
    SCENARIO_MATRIX_AVAILABLE = False
    ScenarioMatrix = None
    ScenarioComparator = None

# =============================================================================
# Phase 7: Resilience, Living Documents, & Observability
# =============================================================================

# EnhancedProvenanceManager for staleness detection (Phase 7)
try:
    from aragora.reasoning.provenance_enhanced import (
        EnhancedProvenanceManager,
        GitProvenanceTracker,
        StalenessCheck,
        StalenessStatus,
        RevalidationTrigger,
    )

    ENHANCED_PROVENANCE_AVAILABLE = True
except ImportError:
    ENHANCED_PROVENANCE_AVAILABLE = False
    EnhancedProvenanceManager = None
    StalenessStatus = None

# CheckpointManager for pause/resume (Phase 7)
try:
    from aragora.debate.checkpoint import (
        CheckpointManager,
        DebateCheckpoint,
        FileCheckpointStore,
        CheckpointConfig,
    )

    CHECKPOINT_AVAILABLE = True
except ImportError:
    CHECKPOINT_AVAILABLE = False
    CheckpointManager = None

# BreakpointManager for human intervention (Phase 7)
try:
    from aragora.debate.breakpoints import (
        BreakpointManager,
        BreakpointConfig,
        Breakpoint,
        HumanGuidance,
        BreakpointTrigger,
    )

    BREAKPOINT_AVAILABLE = True
except ImportError:
    BREAKPOINT_AVAILABLE = False
    BreakpointManager = None
    BreakpointTrigger = None

# ReliabilityScorer for confidence scoring (Phase 7)
try:
    from aragora.reasoning.reliability import (
        ReliabilityScorer,
        ClaimReliability,
        EvidenceReliability,
        ReliabilityLevel,
    )

    RELIABILITY_SCORER_AVAILABLE = True
except ImportError:
    RELIABILITY_SCORER_AVAILABLE = False
    ReliabilityScorer = None
    ReliabilityLevel = None

# DebateTracer for audit logs (Phase 7)
try:
    from aragora.debate.traces import DebateTracer, DebateTrace, TraceEvent, EventType

    DEBATE_TRACER_AVAILABLE = True
except ImportError:
    DEBATE_TRACER_AVAILABLE = False
    DebateTracer = None
    EventType = None

# =============================================================================
# Phase 8: Agent Evolution, Semantic Memory & Advanced Debates
# =============================================================================

# PersonaLaboratory for agent evolution (Phase 8)
try:
    from aragora.agents.laboratory import (
        PersonaLaboratory,
        PersonaExperiment,
        EmergentTrait,
        TraitTransfer,
    )

    PERSONA_LAB_AVAILABLE = True
except ImportError:
    PERSONA_LAB_AVAILABLE = False
    PersonaLaboratory = None
    EmergentTrait = None

# SemanticRetriever for pattern matching (Phase 8)
try:
    from aragora.memory.embeddings import SemanticRetriever, EmbeddingProvider, cosine_similarity

    SEMANTIC_RETRIEVER_AVAILABLE = True
except ImportError:
    SEMANTIC_RETRIEVER_AVAILABLE = False
    SemanticRetriever = None

# FormalVerificationManager for theorem proving (Phase 8)
try:
    from aragora.verification.formal import (
        FormalVerificationManager,
        FormalProofResult,
        FormalProofStatus,
        FormalLanguage,
    )

    FORMAL_VERIFICATION_AVAILABLE = True
except ImportError:
    FORMAL_VERIFICATION_AVAILABLE = False
    FormalVerificationManager = None
    FormalProofResult = None

# DebateGraph for DAG-based debates (Phase 8)
try:
    from aragora.debate.graph import (
        DebateGraph,
        DebateNode,
        GraphDebateOrchestrator,
        NodeType,
        BranchReason,
        MergeStrategy,
    )

    DEBATE_GRAPH_AVAILABLE = True
except ImportError:
    DEBATE_GRAPH_AVAILABLE = False
    DebateGraph = None
    GraphDebateOrchestrator = None

# DebateForker for parallel exploration (Phase 8)
try:
    from aragora.debate.forking import (
        DebateForker,
        ForkDetector,
        Branch,
        ForkPoint,
        ForkDecision,
        MergeResult,
    )

    DEBATE_FORKER_AVAILABLE = True
except ImportError:
    DEBATE_FORKER_AVAILABLE = False
    DebateForker = None
    ForkDetector = None

# =============================================================================
# Phase 9: Grounded Personas & Truth-Based Identity
# =============================================================================

# PositionTracker for truth-grounded personas (Phase 9)
try:
    from aragora.agents.truth_grounding import (
        PositionTracker,
        Position,
        TruthGroundedPersona,
        TruthGroundedLaboratory,
    )

    POSITION_TRACKER_AVAILABLE = True
except ImportError:
    POSITION_TRACKER_AVAILABLE = False
    PositionTracker = None
    TruthGroundedLaboratory = None

# GroundedPersonas for evidence-based identity (Phase 9)
try:
    from aragora.agents.grounded import (
        PositionLedger,
        RelationshipTracker,
        PersonaSynthesizer,
        GroundedPersona,
        Position as GroundedPosition,
        MomentDetector,
    )

    GROUNDED_PERSONAS_AVAILABLE = True
except ImportError:
    GROUNDED_PERSONAS_AVAILABLE = False
    PositionLedger = None
    RelationshipTracker = None
    PersonaSynthesizer = None
    GroundedPersona = None
    MomentDetector = None

# CalibrationTracker for prediction accuracy tracking (Phase 10)
try:
    from aragora.agents.calibration import CalibrationTracker, CalibrationSummary

    CALIBRATION_AVAILABLE = True
except ImportError:
    CALIBRATION_AVAILABLE = False
    CalibrationTracker = None
    CalibrationSummary = None

# SuggestionFeedbackTracker for audience suggestion effectiveness (Phase 10)
try:
    from aragora.audience.feedback import SuggestionFeedbackTracker

    SUGGESTION_FEEDBACK_AVAILABLE = True
except ImportError:
    SUGGESTION_FEEDBACK_AVAILABLE = False
    SuggestionFeedbackTracker = None

# =============================================================================
# Citation Grounding (Heavy3-inspired scholarly evidence)
# =============================================================================

# CitationStore for evidence-backed verdicts
try:
    from aragora.reasoning.citations import (
        CitationStore,
        CitationExtractor,
        GroundedVerdict,
        ScholarlyEvidence,
        CitedClaim,
        CitationType,
        CitationQuality,
    )

    CITATION_GROUNDING_AVAILABLE = True
except ImportError:
    CITATION_GROUNDING_AVAILABLE = False
    CitationStore = None
    CitationExtractor = None
    GroundedVerdict = None

# =============================================================================
# Broadcast Module (Post-Debate Summaries)
# =============================================================================

try:
    from aragora.broadcast.script_gen import DebateSummaryGenerator

    BROADCAST_AVAILABLE = True
except ImportError:
    BROADCAST_AVAILABLE = False
    DebateSummaryGenerator = None

# =============================================================================
# Pulse Integration (Trending Topics for Debate Generation)
# =============================================================================

try:
    from aragora.pulse import PulseManager, TrendingTopic, PulseIngestor

    PULSE_AVAILABLE = True
except ImportError:
    PULSE_AVAILABLE = False
    PulseManager = None
    TrendingTopic = None


# =============================================================================
# Circuit Breaker for Agent Failure Handling
# =============================================================================


class AgentCircuitBreaker:
    """
    Circuit breaker pattern for agent reliability.

    Tracks consecutive failures per agent and temporarily disables
    agents that fail repeatedly to prevent wasting cycles on broken agents.

    Extended with task-scoped tracking (Jan 2026):
    - Tracks failures per task type (debate, design, implement, verify)
    - Agents can be disabled for specific task types while still usable for others
    - Success rates tracked for intelligent agent selection
    """

    def __init__(self, failure_threshold: int = 3, cooldown_cycles: int = 2):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures before tripping
            cooldown_cycles: Number of cycles to skip after tripping
        """
        self.failure_threshold = failure_threshold
        self.cooldown_cycles = cooldown_cycles
        self.failures: dict[str, int] = {}  # agent_name -> consecutive failure count
        self.cooldowns: dict[str, int] = {}  # agent_name -> cycles remaining in cooldown

        # Task-scoped tracking (new)
        self.task_failures: dict[str, dict[str, int]] = {}  # agent -> task_type -> count
        self.task_success_rate: dict[str, dict[str, float]] = {}  # agent -> task_type -> rate
        self.task_cooldowns: dict[str, dict[str, int]] = {}  # agent -> task_type -> cooldown

    def record_success(self, agent_name: str) -> None:
        """Reset failure count and reduce cooldown on success."""
        self.failures[agent_name] = 0
        # If agent was in cooldown but succeeded (half-open state), reduce or close circuit
        if agent_name in self.cooldowns and self.cooldowns[agent_name] > 0:
            self.cooldowns[agent_name] = max(0, self.cooldowns[agent_name] - 1)
            if self.cooldowns[agent_name] == 0:
                del self.cooldowns[agent_name]
                logging.info(f"[circuit-breaker] {agent_name} recovered after success")

    def record_failure(self, agent_name: str) -> bool:
        """
        Record a failure and potentially trip the circuit.

        Returns:
            True if circuit just tripped (agent now in cooldown)
        """
        self.failures[agent_name] = self.failures.get(agent_name, 0) + 1
        if self.failures[agent_name] >= self.failure_threshold:
            self.cooldowns[agent_name] = self.cooldown_cycles
            self.failures[agent_name] = 0  # Reset for next time
            return True
        return False

    def record_task_success(self, agent_name: str, task_type: str) -> None:
        """Record success for specific task type and update running average."""
        # Initialize structures if needed
        if agent_name not in self.task_success_rate:
            self.task_success_rate[agent_name] = {}
        if agent_name not in self.task_failures:
            self.task_failures[agent_name] = {}

        # Reset task-specific failures
        self.task_failures[agent_name][task_type] = 0

        # Update running average (exponential moving average)
        current_rate = self.task_success_rate[agent_name].get(task_type, 0.5)
        self.task_success_rate[agent_name][task_type] = current_rate * 0.8 + 0.2

        # Also record agent-level success
        self.record_success(agent_name)

    def record_task_failure(self, agent_name: str, task_type: str) -> bool:
        """
        Record failure for specific task type.

        Returns:
            True if task-specific circuit just tripped
        """
        # Initialize structures if needed
        if agent_name not in self.task_failures:
            self.task_failures[agent_name] = {}
        if agent_name not in self.task_cooldowns:
            self.task_cooldowns[agent_name] = {}
        if agent_name not in self.task_success_rate:
            self.task_success_rate[agent_name] = {}

        # Increment task-specific failure count
        self.task_failures[agent_name][task_type] = (
            self.task_failures[agent_name].get(task_type, 0) + 1
        )

        # Update running average (exponential moving average toward 0)
        current_rate = self.task_success_rate[agent_name].get(task_type, 0.5)
        self.task_success_rate[agent_name][task_type] = current_rate * 0.8

        # Trip task-specific circuit if threshold reached
        if self.task_failures[agent_name][task_type] >= self.failure_threshold:
            self.task_cooldowns[agent_name][task_type] = self.cooldown_cycles
            self.task_failures[agent_name][task_type] = 0
            return True

        # Also record agent-level failure
        self.record_failure(agent_name)
        return False

    def get_task_success_rate(self, agent_name: str, task_type: str) -> float:
        """Get agent's success rate for specific task type (0.0 to 1.0)."""
        if agent_name not in self.task_success_rate:
            return 0.5  # Default neutral
        return self.task_success_rate[agent_name].get(task_type, 0.5)

    def is_available_for_task(self, agent_name: str, task_type: str) -> bool:
        """Check if agent is available for a specific task type."""
        # First check global availability
        if not self.is_available(agent_name):
            return False
        # Then check task-specific cooldown
        if agent_name in self.task_cooldowns:
            if self.task_cooldowns[agent_name].get(task_type, 0) > 0:
                return False
        return True

    def is_available(self, agent_name: str) -> bool:
        """Check if agent is available (not in cooldown)."""
        return self.cooldowns.get(agent_name, 0) <= 0

    def start_new_cycle(self) -> None:
        """Decrement cooldowns at start of each cycle."""
        # Decrement global cooldowns
        for agent_name in list(self.cooldowns.keys()):
            if self.cooldowns[agent_name] > 0:
                self.cooldowns[agent_name] -= 1

        # Decrement task-specific cooldowns
        for agent_name in list(self.task_cooldowns.keys()):
            for task_type in list(self.task_cooldowns[agent_name].keys()):
                if self.task_cooldowns[agent_name][task_type] > 0:
                    self.task_cooldowns[agent_name][task_type] -= 1

    def get_status(self) -> dict:
        """Get circuit breaker status for all agents."""
        return {
            "failures": dict(self.failures),
            "cooldowns": dict(self.cooldowns),
            "task_failures": dict(self.task_failures),
            "task_cooldowns": dict(self.task_cooldowns),
            "task_success_rates": dict(self.task_success_rate),
        }


if _NOMIC_PACKAGE_AVAILABLE:
    # Prefer extracted helpers when available to avoid inline duplication.
    PhaseError = _PhaseError
    PhaseRecovery = _PhaseRecovery
    AgentCircuitBreaker = _AgentCircuitBreaker
    PROTECTED_FILES = _PROTECTED_FILES
    SAFETY_PREAMBLE = _SAFETY_PREAMBLE
    _compute_file_checksum = _compute_file_checksum
    _init_protected_checksums = _init_protected_checksums
    verify_protected_files_unchanged = _verify_protected_files_unchanged
    _get_protected_checksums = _get_protected_checksums
    _ConstitutionVerifier = _ConstitutionVerifier
    DEFAULT_CONSTITUTION_PATH = _DEFAULT_CONSTITUTION_PATH
    NOMIC_AUTO_COMMIT = _NOMIC_AUTO_COMMIT
    NOMIC_AUTO_CONTINUE = _NOMIC_AUTO_CONTINUE
    NOMIC_MAX_CYCLE_SECONDS = _NOMIC_MAX_CYCLE_SECONDS
    NOMIC_STALL_THRESHOLD = _NOMIC_STALL_THRESHOLD
    NOMIC_TESTFIXER_ENABLED = _NOMIC_TESTFIXER_ENABLED
    NOMIC_TESTFIXER_TEST_COMMAND = _NOMIC_TESTFIXER_TEST_COMMAND
    NOMIC_TESTFIXER_TEST_TIMEOUT = _NOMIC_TESTFIXER_TEST_TIMEOUT
    NOMIC_TESTFIXER_MAX_ITERATIONS = _NOMIC_TESTFIXER_MAX_ITERATIONS
    NOMIC_TESTFIXER_MAX_SAME_FAILURE = _NOMIC_TESTFIXER_MAX_SAME_FAILURE
    NOMIC_TESTFIXER_MIN_CONFIDENCE = _NOMIC_TESTFIXER_MIN_CONFIDENCE
    NOMIC_TESTFIXER_MIN_AUTO_CONFIDENCE = _NOMIC_TESTFIXER_MIN_AUTO_CONFIDENCE
    NOMIC_TESTFIXER_REQUIRE_CONSENSUS = _NOMIC_TESTFIXER_REQUIRE_CONSENSUS
    NOMIC_TESTFIXER_REQUIRE_APPROVAL = _NOMIC_TESTFIXER_REQUIRE_APPROVAL
    NOMIC_TESTFIXER_REVERT_ON_FAILURE = _NOMIC_TESTFIXER_REVERT_ON_FAILURE
    NOMIC_TESTFIXER_STOP_ON_FIRST_SUCCESS = _NOMIC_TESTFIXER_STOP_ON_FIRST_SUCCESS
    NOMIC_TESTFIXER_AGENTS = _NOMIC_TESTFIXER_AGENTS
    NOMIC_TESTFIXER_USE_LLM_ANALYZER = _NOMIC_TESTFIXER_USE_LLM_ANALYZER
    NOMIC_TESTFIXER_ANALYSIS_AGENTS = _NOMIC_TESTFIXER_ANALYSIS_AGENTS
    NOMIC_TESTFIXER_ANALYSIS_REQUIRE_CONSENSUS = _NOMIC_TESTFIXER_ANALYSIS_REQUIRE_CONSENSUS
    NOMIC_TESTFIXER_ANALYSIS_CONSENSUS_THRESHOLD = _NOMIC_TESTFIXER_ANALYSIS_CONSENSUS_THRESHOLD
    NOMIC_TESTFIXER_ARENA_VALIDATE = _NOMIC_TESTFIXER_ARENA_VALIDATE
    NOMIC_TESTFIXER_ARENA_AGENTS = _NOMIC_TESTFIXER_ARENA_AGENTS
    NOMIC_TESTFIXER_ARENA_ROUNDS = _NOMIC_TESTFIXER_ARENA_ROUNDS
    NOMIC_TESTFIXER_ARENA_MIN_CONFIDENCE = _NOMIC_TESTFIXER_ARENA_MIN_CONFIDENCE
    NOMIC_TESTFIXER_ARENA_REQUIRE_CONSENSUS = _NOMIC_TESTFIXER_ARENA_REQUIRE_CONSENSUS
    NOMIC_TESTFIXER_ARENA_CONSENSUS_THRESHOLD = _NOMIC_TESTFIXER_ARENA_CONSENSUS_THRESHOLD
    NOMIC_TESTFIXER_REDTEAM_VALIDATE = _NOMIC_TESTFIXER_REDTEAM_VALIDATE
    NOMIC_TESTFIXER_REDTEAM_ATTACKERS = _NOMIC_TESTFIXER_REDTEAM_ATTACKERS
    NOMIC_TESTFIXER_REDTEAM_DEFENDER = _NOMIC_TESTFIXER_REDTEAM_DEFENDER
    NOMIC_TESTFIXER_REDTEAM_ROUNDS = _NOMIC_TESTFIXER_REDTEAM_ROUNDS
    NOMIC_TESTFIXER_REDTEAM_ATTACKS_PER_ROUND = _NOMIC_TESTFIXER_REDTEAM_ATTACKS_PER_ROUND
    NOMIC_TESTFIXER_REDTEAM_MIN_ROBUSTNESS = _NOMIC_TESTFIXER_REDTEAM_MIN_ROBUSTNESS
    NOMIC_TESTFIXER_PATTERN_LEARNING = _NOMIC_TESTFIXER_PATTERN_LEARNING
    NOMIC_TESTFIXER_PATTERN_STORE = _NOMIC_TESTFIXER_PATTERN_STORE
    NOMIC_TESTFIXER_GENERATION_TIMEOUT = _NOMIC_TESTFIXER_GENERATION_TIMEOUT
    NOMIC_TESTFIXER_CRITIQUE_TIMEOUT = _NOMIC_TESTFIXER_CRITIQUE_TIMEOUT
    NOMIC_SICA_ENABLED = _NOMIC_SICA_ENABLED
    NOMIC_SICA_IMPROVEMENT_TYPES = _NOMIC_SICA_IMPROVEMENT_TYPES
    NOMIC_SICA_GENERATOR_MODEL = _NOMIC_SICA_GENERATOR_MODEL
    NOMIC_SICA_REQUIRE_APPROVAL = _NOMIC_SICA_REQUIRE_APPROVAL
    NOMIC_SICA_RUN_TESTS = _NOMIC_SICA_RUN_TESTS
    NOMIC_SICA_RUN_TYPECHECK = _NOMIC_SICA_RUN_TYPECHECK
    NOMIC_SICA_RUN_LINT = _NOMIC_SICA_RUN_LINT
    NOMIC_SICA_TEST_COMMAND = _NOMIC_SICA_TEST_COMMAND
    NOMIC_SICA_TYPECHECK_COMMAND = _NOMIC_SICA_TYPECHECK_COMMAND
    NOMIC_SICA_LINT_COMMAND = _NOMIC_SICA_LINT_COMMAND
    NOMIC_SICA_VALIDATION_TIMEOUT = _NOMIC_SICA_VALIDATION_TIMEOUT
    NOMIC_SICA_MAX_OPPORTUNITIES = _NOMIC_SICA_MAX_OPPORTUNITIES
    NOMIC_SICA_MAX_ROLLBACKS = _NOMIC_SICA_MAX_ROLLBACKS


class NomicLoop:
    """
    Autonomous self-improvement loop for aragora.

    Each cycle:
    1. Agents debate what to improve
    2. Agents design the implementation
    3. Agents implement (codex writes code)
    4. Changes are verified and committed
    5. Loop repeats

    SAFETY FEATURES:
    - All output logged to .nomic/nomic_loop.log for live monitoring
    - State saved to .nomic/nomic_state.json for crash recovery
    - Protected files backed up before each cycle
    - Automatic restore if protected files are damaged
    """

    def __init__(
        self,
        aragora_path: str = None,
        max_cycles: int = 10,
        require_human_approval: bool = True,
        auto_commit: bool = False,
        initial_proposal: str = None,
        stream_emitter: "SyncEventEmitter" = None,
        use_genesis: bool = False,
        enable_persistence: bool = True,
        disable_rollback: bool = False,  # Disable rollback on verification failure
        max_cycle_seconds: int = 3600,  # 1 hour cycle timeout (prevents multi-hour hangs)
    ):
        self.aragora_path = Path(aragora_path or Path(__file__).parent.parent)
        self.max_cycles = max_cycles
        self.require_human_approval = require_human_approval
        self.auto_commit = auto_commit
        self.initial_proposal = initial_proposal
        self.disable_rollback = disable_rollback
        self.max_cycle_seconds = max_cycle_seconds
        self.cycle_count = 0
        self._estimated_cost_usd = 0.0  # Accumulated estimated API cost
        self.history = []

        # Circuit breaker for agent reliability
        # Threshold=5 gives agents more chances before trip, cooldown=1 allows faster recovery
        self.circuit_breaker = AgentCircuitBreaker(failure_threshold=5, cooldown_cycles=1)

        # Phase recovery for structured error handling
        self.phase_recovery = PhaseRecovery(log_func=lambda msg: print(msg))

        # Generate unique loop ID for this run
        self.loop_id = f"nomic-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Genesis mode: fractal debates with agent evolution
        self.use_genesis = use_genesis and GENESIS_AVAILABLE
        self.genesis_ledger = None
        self.population_manager = None
        if self.use_genesis:
            self.genesis_ledger = GenesisLedger(str(self.aragora_path / ".nomic" / "genesis.db"))
            self.population_manager = PopulationManager(
                str(self.aragora_path / ".nomic" / "genesis.db")
            )

        # Setup logging infrastructure (must be before other initializations that use nomic_dir)
        self.nomic_dir = self.aragora_path / ".nomic"
        self.nomic_dir.mkdir(exist_ok=True)
        self.log_file = self.nomic_dir / "nomic_loop.log"
        self.state_file = self.nomic_dir / "nomic_state.json"
        self.backup_dir = self.nomic_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)

        # Restore circuit breaker state from previous run (persistence across cycles)
        circuit_breaker_path = self.nomic_dir / "circuit_breaker.json"
        if circuit_breaker_path.exists():
            try:
                with open(circuit_breaker_path) as f:
                    state = json.load(f)
                    self.circuit_breaker.failures = state.get("failures", {})
                    self.circuit_breaker.cooldowns = state.get("cooldowns", {})
                    # Restore task-scoped tracking with defaultdict conversion
                    for agent, tasks in state.get("task_failures", {}).items():
                        self.circuit_breaker.task_failures[agent] = defaultdict(int, tasks)
                    for agent, tasks in state.get("task_cooldowns", {}).items():
                        self.circuit_breaker.task_cooldowns[agent] = defaultdict(int, tasks)
                    for agent, rates in state.get("task_success_rate", {}).items():
                        self.circuit_breaker.task_success_rate[agent] = rates
                    task_count = sum(len(t) for t in self.circuit_breaker.task_cooldowns.values())
                    print(
                        f"[circuit-breaker] Restored state: {len(self.circuit_breaker.cooldowns)} agents in cooldown, {task_count} task cooldowns"
                    )
            except Exception as e:
                print(f"[circuit-breaker] Failed to restore state: {e}")

        # Initialize protected file checksums for integrity verification
        checksums = _init_protected_checksums(self.aragora_path)
        print(f"[security] Initialized checksums for {len(checksums)} protected files")

        # Initialize Constitution verifier for cryptographic safety rules
        self.constitution_verifier = None
        try:
            constitution_path = self.nomic_dir / "constitution.json"
            if constitution_path.exists():
                self.constitution_verifier = _ConstitutionVerifier(constitution_path)
                if self.constitution_verifier.is_available():
                    rules = len(self.constitution_verifier.constitution.rules)
                    print(
                        f"[constitution] Loaded v{self.constitution_verifier.constitution.version} with {rules} rules"
                    )
                else:
                    print("[constitution] File exists but failed to load")
            else:
                print("[constitution] No constitution.json found (safety rules disabled)")
        except Exception as e:
            print(f"[constitution] Failed to initialize: {e}")

        # Initialize OutcomeTracker for calibration and learning
        self.outcome_tracker = None
        try:
            if _NOMIC_PACKAGE_AVAILABLE and "_OutcomeTracker" in globals():
                outcomes_path = self.nomic_dir / "outcomes.db"
                self.outcome_tracker = _OutcomeTracker(outcomes_path)
                stats = self.outcome_tracker.get_overall_stats()
                print(
                    f"[outcomes] Tracker initialized ({stats['total_outcomes']} historical outcomes, {stats['success_rate']:.0%} success rate)"
                )
            else:
                print("[outcomes] Tracker unavailable (package imports not ready)")
        except Exception as e:
            print(f"[outcomes] Failed to initialize: {e}")

        # Initialize CycleLearningStore for cross-cycle learning
        self.cycle_store = None
        self._current_cycle_record = None
        try:
            from aragora.nomic.cycle_store import CycleLearningStore

            cycles_db = str(self.nomic_dir / "cycles.db")
            self.cycle_store = CycleLearningStore(db_path=cycles_db)
            cycle_count = self.cycle_store.get_cycle_count()
            print(f"[cross-cycle] Learning store initialized ({cycle_count} historical cycles)")
        except Exception as e:
            print(f"[cross-cycle] Failed to initialize: {e}")

        # Supabase persistence for history tracking
        self.persistence = None
        if enable_persistence and PERSISTENCE_AVAILABLE:
            self.persistence = SupabaseClient()
            if self.persistence.is_configured:
                print(f"[persistence] Supabase connected, loop_id: {self.loop_id}")
            else:
                self.persistence = None

        # Debate embeddings database for historical search
        self.debate_embeddings = None
        if EMBEDDINGS_AVAILABLE:
            embeddings_path = self.nomic_dir / "debate_embeddings.db"
            self.debate_embeddings = DebateEmbeddingsDatabase(str(embeddings_path))
            print("[embeddings] Debate embeddings database initialized")

        # CritiqueStore for patterns and agent reputation tracking
        self.critique_store = None
        try:
            from aragora.memory.store import CritiqueStore

            critique_db_path = self.nomic_dir / "agora_memory.db"
            self.critique_store = CritiqueStore(str(critique_db_path))
            print("[memory] CritiqueStore initialized for patterns and reputation")
        except ImportError:
            pass

        # ContinuumMemory for multi-timescale pattern learning
        self.continuum = None
        if CONTINUUM_AVAILABLE:
            continuum_path = self.nomic_dir / "continuum.db"
            self.continuum = ContinuumMemory(str(continuum_path))
            print("[continuum] Multi-timescale memory initialized")

        # ReplayRecorder will be created per cycle
        self.replay_recorder = None

        # MetaLearner for self-tuning hyperparameters (runs every 5 cycles)
        self.meta_learner = None
        if METALEARNER_AVAILABLE and self.continuum:
            meta_learner_path = self.nomic_dir / "meta_learning.db"
            self.meta_learner = MetaLearner(str(meta_learner_path))
            print("[meta] MetaLearner initialized for hyperparameter tuning")

        # ArgumentCartographer will be created per cycle for visualization
        self.cartographer = None
        self.visualizations_dir = self.nomic_dir / "visualizations"
        self.visualizations_dir.mkdir(exist_ok=True)
        if CARTOGRAPHER_AVAILABLE:
            print("[viz] ArgumentCartographer available for debate visualization")

        # WebhookDispatcher for external event notifications
        self.webhook_dispatcher = None
        webhook_url = os.environ.get("ARAGORA_WEBHOOK_URL")
        if WEBHOOKS_AVAILABLE and webhook_url and WebhookConfig:
            try:
                config = WebhookConfig(
                    name="default",
                    url=webhook_url,
                    secret=os.environ.get("ARAGORA_WEBHOOK_SECRET", ""),
                )
                self.webhook_dispatcher = WebhookDispatcher([config])
                self.webhook_dispatcher.start()
                print(f"[webhook] Dispatcher started for {webhook_url[:50]}...")
            except Exception as e:
                print(f"[webhook] Failed to initialize: {e}")

        # ConsensusMemory for tracking settled vs contested topics
        self.consensus_memory = None
        self.dissent_retriever = None
        if CONSENSUS_MEMORY_AVAILABLE:
            consensus_db_path = self.nomic_dir / "consensus_memory.db"
            self.consensus_memory = ConsensusMemory(str(consensus_db_path))
            self.dissent_retriever = DissentRetriever(self.consensus_memory)
            print("[consensus] ConsensusMemory initialized for topic tracking")

        # InsightExtractor for post-debate pattern learning
        self.insight_extractor = None
        if INSIGHTS_AVAILABLE:
            self.insight_extractor = InsightExtractor()
            print("[insights] InsightExtractor initialized for pattern learning")

        # InsightStore for persisting debate insights (debate consensus feature)
        self.insight_store = None
        if INSIGHTS_AVAILABLE:
            try:
                from aragora.insights.store import InsightStore

                insights_path = self.nomic_dir / "aragora_insights.db"
                self.insight_store = InsightStore(str(insights_path))
                print("[insights] InsightStore initialized for debate persistence")
            except Exception as e:
                print(f"[insights] InsightStore init failed: {e}")

        # NomicIntegration for advanced feature coordination
        # Integrates: belief propagation, capability probing, staleness detection,
        # counterfactual branching, and checkpointing
        self.nomic_integration = None
        if NOMIC_INTEGRATION_AVAILABLE and create_nomic_integration:
            try:
                checkpoint_dir = self.nomic_dir / "checkpoints"
                self.nomic_integration = create_nomic_integration(
                    checkpoint_dir=str(checkpoint_dir),
                    enable_probing=True,  # Probe agents for reliability
                    enable_belief_analysis=True,  # Bayesian belief propagation
                    enable_staleness_check=True,  # Detect stale evidence
                    enable_counterfactual=True,  # Fork on contested claims
                    enable_checkpointing=True,  # Phase checkpointing
                )
                print("[integration] NomicIntegration initialized for advanced features")
            except Exception as e:
                print(f"[integration] Failed to initialize: {e}")
                self.nomic_integration = None

        # Phase 3: MemoryStream for per-agent persistent memory
        self.memory_stream = None
        if MEMORY_STREAM_AVAILABLE:
            memory_db_path = self.nomic_dir / "agent_memories.db"
            self.memory_stream = MemoryStream(str(memory_db_path))
            print("[memory] Per-agent MemoryStream initialized")

        # Phase 3: LocalDocsConnector for evidence grounding
        self.local_docs = None
        if LOCAL_DOCS_AVAILABLE:
            self.local_docs = LocalDocsConnector(root_path=str(self.aragora_path), file_types="all")
            print("[connectors] LocalDocsConnector initialized for evidence grounding")

        # Phase 3: CounterfactualOrchestrator for deadlock resolution
        self.counterfactual = None
        if COUNTERFACTUAL_AVAILABLE:
            self.counterfactual = CounterfactualOrchestrator()
            print("[counterfactual] Deadlock resolution via forking enabled")

        # Citation Grounding: CitationStore + CitationExtractor for evidence-backed verdicts
        self.citation_store = None
        self.citation_extractor = None
        if CITATION_GROUNDING_AVAILABLE:
            self.citation_store = CitationStore()
            self.citation_extractor = CitationExtractor()
            print("[citations] Citation grounding enabled for evidence-backed verdicts")

        # Pulse Integration: PulseManager for trending topic awareness
        self.pulse_manager = None
        if PULSE_AVAILABLE:
            self.pulse_manager = PulseManager()
            print("[pulse] PulseManager initialized for trending topic awareness")

        # Broadcast: Generate post-debate summaries
        self.summary_generator = None
        if BROADCAST_AVAILABLE:
            self.summary_generator = DebateSummaryGenerator()
            print("[broadcast] Debate summary generation enabled")

        # Phase 3: CapabilityProber for agent quality assurance
        self.prober = None
        if PROBER_AVAILABLE:
            self.prober = CapabilityProber()
            print("[prober] Agent capability probing enabled")

        # Phase 4: PersonaManager for agent traits/expertise evolution
        self.persona_manager = None
        if PERSONAS_AVAILABLE:
            persona_db_path = get_db_path(DatabaseType.PERSONAS, nomic_dir=self.nomic_dir)
            self.persona_manager = PersonaManager(persona_db_path)
            print("[personas] Agent personality evolution enabled")

        # Phase 4: PromptEvolver for prompt evolution from winning patterns
        self.prompt_evolver = None
        if EVOLVER_AVAILABLE:
            evolver_db_path = self.nomic_dir / "prompt_evolution.db"
            self.prompt_evolver = PromptEvolver(
                db_path=str(evolver_db_path),
                critique_store=self.critique_store,
                strategy=EvolutionStrategy.HYBRID,
            )
            print("[evolver] Prompt evolution enabled")

        # Phase 4: Tournament tracking for periodic competitive benchmarking
        self.last_tournament_cycle = 0
        self.tournament_interval = 20  # Run tournament every 20 cycles

        # Phase 5: ConvergenceDetector for early stopping
        self.convergence_detector = None
        if CONVERGENCE_AVAILABLE:
            self.convergence_detector = ConvergenceDetector(
                convergence_threshold=0.85, min_rounds_before_check=2
            )
            print("[convergence] Early stopping enabled")

        # Phase 5: MetaCritiqueAnalyzer for process feedback
        self.meta_analyzer = None
        if META_CRITIQUE_AVAILABLE:
            self.meta_analyzer = MetaCritiqueAnalyzer()
            print("[meta] Process feedback enabled")

        # P5-Phase2: Cache for meta-critique observations to inject into next debate
        self._cached_meta_observations: list = []
        self._last_meta_quality: float = 1.0

        # Deadlock detection and recovery state
        self._cycle_history: list = []  # Last N cycle outcomes for pattern detection
        self._max_cycle_history = 5
        self._phase_progress: dict = {}  # Progress tracking within phases
        self._design_recovery_attempts: set = set()  # Track recovery strategies tried
        self._deadlock_count: int = 0  # Consecutive deadlocks
        self._consensus_threshold_decay: int = 0  # Number of threshold decreases (0, 1, or 2)
        self._warned_50: bool = False  # Timeout warning flags
        self._warned_75: bool = False
        self._warned_90: bool = False
        self._fast_track_mode: bool = False  # Force simplified designs when running out of time
        self._force_judge_consensus: bool = False  # Break oscillations with judge
        self._cycle_start_time: datetime = None  # Track cycle start for warnings

        # Floor breaker state for consensus deadlock recovery
        self._floor_failure_count: int = 0  # Failures at threshold floor (0.4)
        self._floor_breaker_activated: bool = False  # Track if floor breaker was used
        self._forced_decisions: list = []  # Audit trail of forced decisions

        # Phase 5: EloSystem for agent skill tracking
        self.elo_system = None
        if ELO_AVAILABLE:
            elo_db_path = self.nomic_dir / "agent_elo.db"
            self.elo_system = EloSystem(str(elo_db_path))
            print("[elo] Agent skill tracking enabled")

        # Phase 5: AgentSelector for smart team selection
        self.agent_selector = None
        if SELECTOR_AVAILABLE and ELO_AVAILABLE and self.elo_system:
            self.agent_selector = AgentSelector(
                elo_system=self.elo_system, persona_manager=self.persona_manager
            )
            print("[selector] Smart agent selection enabled")

        # Phase 10: ProbeFilter for probe-aware agent selection
        self.probe_filter = None
        if PROBE_FILTER_AVAILABLE:
            self.probe_filter = ProbeFilter(nomic_dir=str(self.nomic_dir))
            print("[probe-filter] Probe-aware agent selection enabled")

            # Wire ProbeFilter into AgentSelector for reliability-weighted team selection
            if self.agent_selector and hasattr(self.agent_selector, "set_probe_filter"):
                self.agent_selector.set_probe_filter(self.probe_filter)
                print("[selector] Probe reliability weighting enabled")

        # =================================================================
        # Phase 9: Grounded Personas & Truth-Based Identity
        # =================================================================

        # Phase 9: PositionTracker for truth-grounded personas
        self.position_tracker = None
        if POSITION_TRACKER_AVAILABLE:
            position_db_path = self.nomic_dir / "aragora_positions.db"
            self.position_tracker = PositionTracker(str(position_db_path))
            print("[positions] Truth-grounded position tracking enabled")

        # Phase 9: PositionLedger for evidence-based identity
        self.position_ledger = None
        if GROUNDED_PERSONAS_AVAILABLE and PositionLedger:
            ledger_db_path = self.nomic_dir / "grounded_positions.db"
            self.position_ledger = PositionLedger(str(ledger_db_path))
            print("[ledger] Evidence-based position ledger enabled")

        # Phase 9: RelationshipTracker for inter-agent dynamics
        self.relationship_tracker = None
        if GROUNDED_PERSONAS_AVAILABLE and RelationshipTracker:
            relationship_db_path = self.nomic_dir / "agent_relationships.db"
            self.relationship_tracker = RelationshipTracker(str(relationship_db_path))
            print("[relationships] Agent relationship tracking enabled")

        # Phase 9: MomentDetector for significant debate moments
        self.moment_detector = None
        if GROUNDED_PERSONAS_AVAILABLE and MomentDetector:
            self.moment_detector = MomentDetector(
                elo_system=self.elo_system,
                position_ledger=self.position_ledger,
                relationship_tracker=self.relationship_tracker,
            )
            print("[moments] Significant moment detection enabled")

        # Phase 10: CalibrationTracker for prediction accuracy
        self.calibration_tracker = None
        if CALIBRATION_AVAILABLE and CalibrationTracker:
            calibration_db_path = self.nomic_dir / "agent_calibration.db"
            self.calibration_tracker = CalibrationTracker(str(calibration_db_path))
            print("[calibration] Agent prediction calibration tracking enabled")

            # Wire CalibrationTracker into AgentSelector for calibration-weighted team selection
            if self.agent_selector and hasattr(self.agent_selector, "set_calibration_tracker"):
                self.agent_selector.set_calibration_tracker(self.calibration_tracker)
                print("[selector] Calibration quality weighting enabled")

        # =================================================================
        # Cross-Pollination Components (v2.0.3)
        # =================================================================

        # DebateStrategy for memory-aware adaptive rounds
        self.debate_strategy = None
        force_full_rounds = (
            os.environ.get("NOMIC_FORCE_FULL_ROUNDS", "0") == "1"
            or os.environ.get("NOMIC_DISABLE_EARLY_STOP", "0") == "1"
        )
        if force_full_rounds:
            print("[strategy] Adaptive rounds disabled (force full rounds)")
        elif STRATEGY_AVAILABLE and DebateStrategy and self.continuum:
            try:
                self.debate_strategy = DebateStrategy(continuum_memory=self.continuum)
                print("[strategy] Memory-aware debate strategy enabled")
            except Exception as e:
                print(f"[strategy] Initialization failed: {e}")

        # CrossDebateMemory for institutional knowledge across debates
        self.cross_debate_memory = None
        if CROSS_DEBATE_MEMORY_AVAILABLE and CrossDebateMemory:
            try:
                cross_memory_db_path = self.nomic_dir / "cross_debate_memory.db"
                self.cross_debate_memory = CrossDebateMemory(str(cross_memory_db_path))
                print("[cross-memory] Cross-debate institutional memory enabled")
            except Exception as e:
                print(f"[cross-memory] Initialization failed: {e}")

        # Phase 10: SuggestionFeedbackTracker for audience suggestion effectiveness
        self.suggestion_tracker = None
        if SUGGESTION_FEEDBACK_AVAILABLE and SuggestionFeedbackTracker:
            suggestion_db_path = self.nomic_dir / "suggestion_feedback.db"
            self.suggestion_tracker = SuggestionFeedbackTracker(str(suggestion_db_path))
            print("[suggestions] Audience suggestion feedback tracking enabled")

        # Phase 9: PersonaSynthesizer for grounded identity prompts
        self.persona_synthesizer = None
        if GROUNDED_PERSONAS_AVAILABLE and PersonaSynthesizer:
            self.persona_synthesizer = PersonaSynthesizer(
                position_ledger=self.position_ledger,
                relationship_tracker=self.relationship_tracker,
                elo_system=self.elo_system,
            )
            print("[synthesizer] Grounded persona synthesis enabled")

        # Phase 9: FlipDetector for position reversal tracking (cached instance)
        self.flip_detector = None
        if FLIP_DETECTOR_AVAILABLE:
            try:
                from aragora.insights.flip_detector import FlipDetector

                # Use grounded_positions.db where PositionLedger stores data
                flip_db_path = self.nomic_dir / "grounded_positions.db"
                self.flip_detector = FlipDetector(str(flip_db_path))
                print("[flip] Position flip detection enabled")
            except Exception as e:
                print(f"[flip] Initialization failed: {e}")

        # =================================================================
        # Phase 6: Verifiable Reasoning & Robustness Testing
        # =================================================================

        # Phase 6: ClaimsKernel for structured reasoning (P16)
        self.claims_kernel = None
        if CLAIMS_KERNEL_AVAILABLE:
            self.claims_kernel = ClaimsKernel(debate_id="nomic-cycle-0")
            print("[claims] Structured reasoning enabled")

        # Phase 6: ProvenanceManager for evidence tracking (P17)
        self.provenance_manager = None
        if PROVENANCE_AVAILABLE:
            self.provenance_manager = ProvenanceManager(debate_id="nomic-cycle-0")
            print("[provenance] Evidence chain tracking enabled")

        # Phase 6: BeliefNetwork for probabilistic reasoning (P18)
        self.belief_network = None
        if BELIEF_NETWORK_AVAILABLE:
            self.belief_network = BeliefNetwork(debate_id="nomic-cycle-0")
            print("[belief] Probabilistic reasoning enabled")

        # P3-Phase2: Cache for crux injection - store cruxes from one debate to inject into next
        self._cached_cruxes: list = []

        # Phase 6: ProofExecutor for executable verification (P19)
        self.proof_executor = None
        self.claim_verifier = None
        if PROOF_EXECUTOR_AVAILABLE:
            self.proof_executor = ProofExecutor(allow_filesystem=True, default_timeout=30.0)
            self.claim_verifier = ClaimVerifier(self.proof_executor)
            print("[proofs] Executable verification enabled")

        # Phase 6: ScenarioComparator for robustness testing (P20)
        self.scenario_comparator = None
        if SCENARIO_MATRIX_AVAILABLE:
            self.scenario_comparator = ScenarioComparator()
            print("[scenarios] Robustness testing enabled")

        # Phase 7: Resilience, Living Documents, & Observability

        # Phase 7: EnhancedProvenanceManager for staleness detection (P21)
        # Note: This REPLACES the base ProvenanceManager from Phase 6 if available
        if ENHANCED_PROVENANCE_AVAILABLE:
            self.provenance_manager = EnhancedProvenanceManager(
                debate_id="nomic-cycle-0", repo_path=str(self.aragora_path)
            )
            print("[provenance] Enhanced with staleness detection")

        # Phase 7: CheckpointManager for pause/resume (P22)
        self.checkpoint_manager = None
        if CHECKPOINT_AVAILABLE:
            checkpoint_dir = self.nomic_dir / "checkpoints"
            checkpoint_dir.mkdir(exist_ok=True)
            self.checkpoint_manager = CheckpointManager(
                store=FileCheckpointStore(str(checkpoint_dir)),
                config=CheckpointConfig(interval_rounds=1, max_checkpoints=5),
            )
            print("[checkpoint] Pause/resume enabled")

        # Phase 7: BreakpointManager for human intervention (P23)
        self.breakpoint_manager = None
        if BREAKPOINT_AVAILABLE and self.require_human_approval:
            self.breakpoint_manager = BreakpointManager(
                config=BreakpointConfig(min_confidence=0.5, max_deadlock_rounds=3)
            )
            print("[breakpoints] Human intervention enabled")

        # Phase 7: ReliabilityScorer for confidence scoring (P24)
        self.reliability_scorer = None
        if RELIABILITY_SCORER_AVAILABLE and self.provenance_manager:
            self.reliability_scorer = ReliabilityScorer(provenance=self.provenance_manager)
            print("[reliability] Confidence scoring enabled")

        # Phase 7: DebateTracer for audit logs (P25)
        # Note: DebateTracer is created per-debate, so we just store the path
        self.debate_trace_db = None
        self._current_tracer = None  # Created per-debate in _start_debate_trace
        if DEBATE_TRACER_AVAILABLE:
            trace_dir = self.nomic_dir / "traces"
            trace_dir.mkdir(exist_ok=True)
            self.debate_trace_db = str(trace_dir / "debate_traces.db")
            print("[tracer] Audit logging enabled")

        # Phase 8: Agent Evolution, Semantic Memory & Advanced Debates

        # Phase 8: PersonaLaboratory for agent evolution (P26)
        self.persona_lab = None
        if PERSONA_LAB_AVAILABLE and PERSONAS_AVAILABLE and self.persona_manager:
            lab_db = self.nomic_dir / "persona_lab.db"
            self.persona_lab = PersonaLaboratory(
                persona_manager=self.persona_manager, db_path=str(lab_db)
            )
            print("[lab] Persona evolution enabled")

        # Phase 8: SemanticRetriever for pattern matching (P27)
        self.semantic_retriever = None
        if SEMANTIC_RETRIEVER_AVAILABLE:
            retriever_db = self.nomic_dir / "semantic_patterns.db"
            self.semantic_retriever = SemanticRetriever(db_path=str(retriever_db))
            print("[semantic] Pattern retrieval enabled")

        # Phase 8: FormalVerificationManager for theorem proving (P28)
        self.formal_verifier = None
        if FORMAL_VERIFICATION_AVAILABLE:
            self.formal_verifier = FormalVerificationManager()
            print("[formal] Z3 verification enabled")

        # Phase 8: DebateGraph for DAG-based debates (P29)
        # Note: GraphDebateOrchestrator is created per-debate with specific agents
        self.graph_debate_enabled = False
        if DEBATE_GRAPH_AVAILABLE and GraphDebateOrchestrator:
            self.graph_debate_enabled = True
            print("[graph] DAG debate structure enabled")

        # Phase 8: DebateForker for parallel exploration (P30)
        # Note: DebateForker is created per-debate
        self.fork_debate_enabled = False
        self.execute_forks = False
        if DEBATE_FORKER_AVAILABLE and DebateForker:
            if os.environ.get("ARAGORA_ENABLE_FORKING", "0") == "1":
                self.fork_debate_enabled = True
                self.execute_forks = True
                print("[forking] Parallel branch exploration enabled (ARAGORA_ENABLE_FORKING=1)")
            else:
                print(
                    "[forking] Forking available but disabled. "
                    "Set ARAGORA_ENABLE_FORKING=1 to enable."
                )

        # Setup streaming (optional)
        self.stream_emitter = stream_emitter
        if stream_emitter and STREAMING_AVAILABLE and create_nomic_hooks:
            self.stream_hooks = create_nomic_hooks(stream_emitter)
        else:
            self.stream_hooks = {}

        # Add genesis hooks if available
        if self.use_genesis:
            genesis_hooks = create_logging_hooks(lambda msg: self._log(f"    [genesis] {msg}"))
            self.stream_hooks.update(genesis_hooks)

        # Clear log file on start
        with open(self.log_file, "w") as f:
            f.write(f"=== NOMIC LOOP STARTED: {datetime.now().isoformat()} ===\n")

        # Initialize extracted phase classes (required since Phase 10C consolidation)
        if not _NOMIC_PHASES_AVAILABLE:
            detail = (
                f" Import error: {_NOMIC_PHASES_IMPORT_ERROR}" if _NOMIC_PHASES_IMPORT_ERROR else ""
            )
            raise RuntimeError(
                "Extracted phase classes not available. "
                "Ensure aragora.nomic.phases module is installed."
                f"{detail}"
            )
        print("[phases] Using extracted modular phase classes")
        self._setup_phase_metrics()
        self._extracted_phases = {}

        # Initialize agents
        self._init_agents()

    def _stream_emit(self, hook_name: str, *args, **kwargs) -> None:
        """Emit event to WebSocket stream and persist to Supabase."""
        # Emit to WebSocket stream
        if hook_name in self.stream_hooks:
            try:
                self.stream_hooks[hook_name](*args, **kwargs)
            except Exception as e:
                logger.warning(f"[stream] Hook '{hook_name}' failed: {e}")

        # Persist to Supabase
        if self.persistence and StreamEvent:
            try:
                event = StreamEvent(
                    loop_id=self.loop_id,
                    cycle=self.cycle_count,
                    event_type=hook_name,
                    event_data={
                        "args": [str(a)[:10000] for a in args],
                        "kwargs": {k: str(v)[:10000] for k, v in kwargs.items()},
                    },
                    agent=kwargs.get("agent"),
                )
                # Run async save in background (fire and forget)
                asyncio.get_event_loop().create_task(self.persistence.save_event(event))
            except Exception as e:
                logger.warning(f"[persistence] Event save failed: {e}")

    def _setup_phase_metrics(self) -> None:
        """Wire up Prometheus metrics for phase profiling.

        Configures the extracted phase classes to record metrics via
        aragora.server.prometheus recording functions.
        """
        try:
            from aragora.server.prometheus_nomic import record_nomic_phase, record_nomic_agent_phase
            from aragora.nomic.phases import set_metrics_recorder

            set_metrics_recorder(
                phase_recorder=record_nomic_phase,
                agent_recorder=record_nomic_agent_phase,
            )
            print("[metrics] Phase profiling enabled via Prometheus")
        except ImportError as e:
            logger.debug(f"[metrics] Prometheus metrics not available: {e}")
        except Exception as e:
            logger.warning(f"[metrics] Failed to setup phase metrics: {e}")

    async def _persist_cycle(
        self,
        phase: str,
        stage: str,
        success: bool = None,
        git_commit: str = None,
        task_description: str = None,
        error_message: str = None,
    ) -> None:
        """Persist cycle state to Supabase."""
        if not self.persistence or not NomicCycle:
            return
        try:
            cycle = NomicCycle(
                loop_id=self.loop_id,
                cycle_number=self.cycle_count,
                phase=phase,
                stage=stage,
                started_at=datetime.utcnow(),
                success=success,
                git_commit=git_commit,
                task_description=task_description,
                error_message=error_message,
            )
            await self.persistence.save_cycle(cycle)
        except Exception as e:
            logger.warning(
                f"[persistence] Cycle state save failed (cycle={self.cycle_count}, phase={phase}): {e}"
            )

    async def _persist_debate(
        self,
        phase: str,
        task: str,
        agents: list,
        transcript: list,
        consensus_reached: bool,
        confidence: float,
        winning_proposal: str = None,
    ) -> None:
        """Persist debate artifact to Supabase."""
        if not self.persistence or not DebateArtifact:
            return
        try:
            debate = DebateArtifact(
                loop_id=self.loop_id,
                cycle_number=self.cycle_count,
                phase=phase,
                task=task,
                agents=agents,
                transcript=transcript,
                consensus_reached=consensus_reached,
                confidence=confidence,
                winning_proposal=winning_proposal,
            )
            await self.persistence.save_debate(debate)

            # Also index in embeddings database for future search
            if self.debate_embeddings:
                await self.debate_embeddings.index_debate(debate)
        except Exception as e:
            logger.warning(f"[persistence] Debate artifact save failed (phase={phase}): {e}")

    def _log(self, message: str, also_print: bool = True, phase: str = None, agent: str = None):
        """Log to file and optionally stdout. File is always flushed immediately."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}"

        # Write to file immediately (unbuffered)
        with open(self.log_file, "a") as f:
            f.write(log_line + "\n")
            f.flush()

        if also_print:
            print(message)
            sys.stdout.flush()

        # Also emit to stream for real-time dashboard
        self._stream_emit("on_log_message", message, level="info", phase=phase, agent=agent)

    def _validate_openrouter_fallback(self) -> bool:
        """Check if OpenRouter fallback is available and validate the key.

        Returns True if OpenRouter is configured and valid, False otherwise.
        The nomic loop will still run without it, but rate-limiting
        recovery will be limited to retries only.
        """
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")

        if not openrouter_key:
            self._log("⚠️  WARNING: OPENROUTER_API_KEY not set")
            self._log("   OpenRouter fallback will NOT be available for rate limiting")
            self._log("   Set OPENROUTER_API_KEY in .env for automatic fallback")
            self._log("-" * 50)
            return False

        # Validate key format (OpenRouter keys start with 'sk-or-')
        if not openrouter_key.startswith("sk-or-"):
            self._log("⚠️  WARNING: OPENROUTER_API_KEY has invalid format")
            self._log("   OpenRouter keys should start with 'sk-or-'")
            self._log("   Fallback may not work correctly")
            self._log("-" * 50)
            return False

        # Quick validation: test the key with a lightweight API call
        try:
            import urllib.request
            import urllib.error

            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {openrouter_key}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    self._log("✓ OpenRouter fallback configured and validated")
                    return True
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self._log("⚠️  WARNING: OPENROUTER_API_KEY is invalid or expired")
                self._log("   Got 401 Unauthorized from OpenRouter API")
                self._log("   Fallback will NOT work - check your API key")
                self._log("-" * 50)
                return False
            elif e.code == 429:
                # Rate limited but key is valid
                self._log("✓ OpenRouter fallback configured (validated, currently rate limited)")
                return True
            else:
                self._log(f"⚠️  WARNING: OpenRouter API returned {e.code}")
                self._log("   Fallback may not work correctly")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            self._log(f"⚠️  WARNING: Could not validate OpenRouter key: {e}")
            self._log("   Key is set but validation failed - fallback may still work")

        # Key is set but couldn't fully validate - still enable fallback
        self._log("✓ OpenRouter fallback configured (key set, validation skipped)")
        return True

    def _save_state(self, state: dict):
        """Save current state for crash recovery and monitoring."""
        state["saved_at"] = datetime.now().isoformat()
        state["cycle"] = self.cycle_count
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2, default=str)

        # Persist circuit breaker state across runs
        try:
            circuit_breaker_path = self.nomic_dir / "circuit_breaker.json"
            with open(circuit_breaker_path, "w") as f:
                json.dump(
                    {
                        "failures": self.circuit_breaker.failures,
                        "cooldowns": self.circuit_breaker.cooldowns,
                        "task_failures": dict(self.circuit_breaker.task_failures),
                        "task_cooldowns": dict(self.circuit_breaker.task_cooldowns),
                        "task_success_rate": dict(self.circuit_breaker.task_success_rate),
                        "saved_at": datetime.now().isoformat(),
                    },
                    f,
                    indent=2,
                )
        except PermissionError as e:
            logger.warning(f"[circuit-breaker] Cannot write state (permission denied): {e}")
        except OSError as e:
            logger.warning(f"[circuit-breaker] Failed to persist state: {e}")

    def _load_state(self) -> dict | None:
        """Load saved state if exists."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logger.warning(f"[state] Corrupted state file, starting fresh: {e}")
                # Backup corrupted state for debugging
                backup_path = self.state_file.with_suffix(".corrupted")
                try:
                    shutil.copy(self.state_file, backup_path)
                    logger.info(f"[state] Corrupted state backed up to {backup_path}")
                except OSError:
                    pass
                return None
            except PermissionError as e:
                logger.error(f"[state] Cannot read state file (permission denied): {e}")
                return None
            except OSError as e:
                logger.warning(f"[state] Failed to load state: {e}")
                return None
        return None

    def _check_cycle_deadline(self, cycle_deadline: datetime, current_phase: str) -> bool:
        """
        Check if cycle has exceeded its time budget with escalation warnings.

        Args:
            cycle_deadline: When this cycle should end
            current_phase: Name of current phase for logging

        Returns:
            True if cycle should continue, False if deadline exceeded
        """
        now = datetime.now()

        # Calculate progress
        if self._cycle_start_time:
            elapsed = (now - self._cycle_start_time).total_seconds()
            remaining = (cycle_deadline - now).total_seconds()
            progress_pct = elapsed / self.max_cycle_seconds * 100

            # 50% warning
            if progress_pct >= 50 and not self._warned_50:
                self._log(
                    f"  [WARNING] Cycle at 50% time budget ({elapsed / 60:.0f}m elapsed, phase: {current_phase})"
                )
                self._warned_50 = True

            # 75% warning
            if progress_pct >= 75 and not self._warned_75:
                self._log(
                    f"  [WARNING] Cycle at 75% time budget ({remaining / 60:.0f}m remaining, phase: {current_phase})"
                )
                self._warned_75 = True

            # 90% critical - enable fast-track mode
            if progress_pct >= 90 and not self._warned_90:
                self._log(
                    f"  [CRITICAL] Cycle at 90% - enabling fast-track mode (phase: {current_phase})"
                )
                self._fast_track_mode = True
                self._warned_90 = True

        if now > cycle_deadline:
            elapsed = (
                now - (cycle_deadline - timedelta(seconds=self.max_cycle_seconds))
            ).total_seconds()
            self._log(
                f"  [TIMEOUT] Cycle exceeded {self.max_cycle_seconds}s limit at phase '{current_phase}' ({elapsed:.0f}s elapsed)"
            )
            return False
        return True

    def _record_cycle_outcome(self, outcome: str, details: dict = None):
        """Track cycle outcome for deadlock detection."""
        self._cycle_history.append(
            {
                "cycle": self.cycle_count,
                "outcome": outcome,
                "timestamp": datetime.now().isoformat(),
                "details": details or {},
            }
        )
        if len(self._cycle_history) > self._max_cycle_history:
            self._cycle_history.pop(0)

        # Record issue outcome if we were working on a structured issue
        current_issue = getattr(self, "_current_issue", None)
        if current_issue:
            self._save_issue_outcome(current_issue, outcome)

    def _detect_cycle_deadlock(self) -> str:
        """Detect if we're stuck in a cycle pattern. Returns deadlock type or empty string."""
        if len(self._cycle_history) < 3:
            return ""

        # Check for repeated same outcome (e.g., design_no_consensus 3 times)
        recent = [h["outcome"] for h in self._cycle_history[-3:]]
        if len(set(recent)) == 1 and recent[0] != "success":
            return f"Repeated failure: {recent[0]} for 3 cycles"

        # Check for oscillating pattern (A-B-A-B)
        if len(self._cycle_history) >= 4:
            last4 = [h["outcome"] for h in self._cycle_history[-4:]]
            if last4[0] == last4[2] and last4[1] == last4[3] and last4[0] != last4[1]:
                return f"Oscillating pattern: {last4[0]} <-> {last4[1]}"

        return ""

    def _track_phase_progress(
        self, phase: str, round_num: int, consensus: float, changed: bool
    ) -> bool:
        """Track progress within a phase to detect stalls. Returns True if stalled."""
        key = f"{self.cycle_count}_{phase}"
        if key not in self._phase_progress:
            self._phase_progress[key] = []

        self._phase_progress[key].append(
            {
                "round": round_num,
                "consensus": consensus,
                "changed": changed,
                "timestamp": datetime.now(),
            }
        )

        # Detect stall: 3+ rounds with <5% consensus change and no position changes
        history = self._phase_progress[key]
        if len(history) >= 3:
            recent = history[-3:]
            consensus_change = abs(recent[-1]["consensus"] - recent[0]["consensus"])
            any_changed = any(r["changed"] for r in recent)

            if consensus_change < 0.05 and not any_changed:
                self._log(
                    f"  [STALL] {phase} stuck for 3 rounds (consensus: {recent[-1]['consensus']:.0%})"
                )
                return True
        return False

    async def _handle_deadlock(self, deadlock_type: str) -> str:
        """Handle detected deadlock with appropriate action. Returns action taken."""
        self._log(f"  [DEADLOCK] Detected: {deadlock_type}")

        if "Repeated failure" in deadlock_type:
            # Clear cached state that might be causing loops
            self._cached_cruxes = [] if hasattr(self, "_cached_cruxes") else []
            self._phase_progress = {}
            self._design_recovery_attempts = set()
            self._log("  [DEADLOCK] Cleared cached state for fresh attempt")

            # Try NomicIntegration counterfactual resolution if belief network available
            if self.nomic_integration and self.nomic_integration._belief_network:
                try:
                    self._log(
                        "  [DEADLOCK] Attempting counterfactual resolution via belief network..."
                    )
                    belief_network = self.nomic_integration._belief_network
                    contested = belief_network.get_contested_claims()
                    if contested:
                        # Convert BeliefNode list to list for resolve_deadlock
                        self._log(
                            f"  [DEADLOCK] Found {len(contested)} contested claims for resolution"
                        )
                        # Store contested claims for use in next debate phase
                        self._cached_cruxes = contested
                except Exception as e:
                    self._log(f"  [DEADLOCK] Counterfactual resolution failed: {e}")

            # Try different agent configuration after multiple deadlocks
            if self._deadlock_count >= 2:
                self._log("  [DEADLOCK] Will rotate agent roles for fresh perspective")
                self._force_judge_consensus = True  # Force judge to break ties

            # Increase consensus threshold decay to lower the bar
            if self._consensus_threshold_decay < 2:
                self._consensus_threshold_decay += 1
                new_threshold = self._get_adaptive_consensus_threshold()
                self._log(f"  [DEADLOCK] Lowered consensus threshold to {new_threshold:.0%}")
            else:
                # At floor (0.4) - track floor failures for floor breaker
                self._floor_failure_count += 1
                self._log(
                    f"  [DEADLOCK] Floor failure #{self._floor_failure_count} (threshold at minimum 40%)"
                )
                if self._floor_failure_count >= 2:
                    self._log("  [DEADLOCK] Floor breaker will activate on next design fallback")

            self._deadlock_count += 1
            return "retry_with_reset"

        elif "Oscillating" in deadlock_type:
            # Force judge consensus to break oscillation
            self._log("  [DEADLOCK] Forcing judge consensus mode to break oscillation")
            self._force_judge_consensus = True
            return "force_judge"

        elif self._deadlock_count >= 3:
            # After 3 deadlocks, skip to next improvement
            self._log("  [DEADLOCK] Max retries (3) reached, skipping this improvement")
            return "skip"

        return "continue"

    def _get_adaptive_consensus_threshold(self) -> float:
        """
        Get consensus threshold adjusted for repeated failures.

        Decay path: 0.6 -> 0.5 -> 0.4 (after consecutive no-consensus cycles)
        This allows the system to break deadlocks by accepting lower agreement.
        """
        base_threshold = 0.6
        decay_steps = [0.6, 0.5, 0.4]  # 60% -> 50% -> 40%
        idx = min(self._consensus_threshold_decay, len(decay_steps) - 1)
        threshold = decay_steps[idx]

        if threshold < base_threshold:
            self._log(
                f"  [consensus] Using adaptive threshold: {threshold:.0%} (decay level {self._consensus_threshold_decay})"
            )

        return threshold

    async def _activate_floor_breaker(
        self,
        proposals: dict,
        vote_counts: dict,
        improvement: str,
    ) -> tuple:
        """
        Emergency floor breaker for when consensus threshold is at floor and still failing.

        Escalation order:
        1. Judge arbitration (uses existing _arbitrate_design)
        2. Plurality wins (highest-voted proposal)
        3. Random selection from top-2 viable proposals

        Args:
            proposals: Dict mapping agent name to their proposal
            vote_counts: Dict mapping proposal/agent to vote count
            improvement: The improvement being designed (for context)

        Returns:
            Tuple of (selected_design, selection_method) or (None, "exhausted")
        """
        self._log("  [floor-breaker] ACTIVATING - threshold at floor with repeated failures")
        self._floor_breaker_activated = True

        # Helper to validate design quality
        def is_viable_design(d: str) -> bool:
            if not d or len(d.strip()) < 100:
                return False
            keywords = ["file", "function", "class", "import", "def ", "async ", "return"]
            return any(kw in d.lower() for kw in keywords)

        # === Strategy 1: Judge Arbitration ===
        self._log("  [floor-breaker] Strategy 1: Judge arbitration")
        if proposals and len(proposals) >= 2:
            try:
                arbitrated = await self._arbitrate_design(proposals, improvement)
                if arbitrated and is_viable_design(arbitrated):
                    self._record_forced_decision("judge_arbitration", arbitrated, proposals)
                    return arbitrated, "judge_arbitration"
            except Exception as e:
                self._log(f"  [floor-breaker] Judge arbitration failed: {e}")

        # === Strategy 2: Plurality Wins ===
        self._log("  [floor-breaker] Strategy 2: Plurality wins")
        if vote_counts and proposals:
            sorted_votes = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
            for agent, votes in sorted_votes:
                if agent in proposals:
                    proposal = proposals[agent]
                    if is_viable_design(proposal):
                        self._log(f"  [floor-breaker] Plurality winner: {agent} with {votes} votes")
                        self._record_forced_decision(
                            "plurality_wins", proposal, proposals, winner=agent, votes=votes
                        )
                        return proposal, "plurality_wins"

        # === Strategy 3: Random Selection from Top-2 ===
        self._log("  [floor-breaker] Strategy 3: Random selection from viable proposals")
        viable_proposals = [(agent, p) for agent, p in proposals.items() if is_viable_design(p)]
        if len(viable_proposals) >= 2:
            import random

            selected_agent, selected_proposal = random.choice(viable_proposals[:2])
            self._log(f"  [floor-breaker] Randomly selected: {selected_agent}")
            self._record_forced_decision(
                "random_top2", selected_proposal, proposals, winner=selected_agent
            )
            return selected_proposal, "random_top2"
        elif len(viable_proposals) == 1:
            agent, proposal = viable_proposals[0]
            self._log(f"  [floor-breaker] Only one viable proposal: {agent}")
            self._record_forced_decision("only_viable", proposal, proposals, winner=agent)
            return proposal, "only_viable"

        self._log("  [floor-breaker] All strategies exhausted - no viable proposal found")
        return None, "exhausted"

    def _record_forced_decision(
        self, method: str, selected: str, all_proposals: dict, **metadata
    ) -> None:
        """Record a forced decision for audit trail."""
        record = {
            "cycle": self.cycle_count,
            "method": method,
            "selected_length": len(selected) if selected else 0,
            "proposal_count": len(all_proposals) if all_proposals else 0,
            "floor_failure_count": self._floor_failure_count,
            "timestamp": datetime.now().isoformat(),
            **metadata,
        }
        self._forced_decisions.append(record)
        self._log(f"  [floor-breaker] Recorded forced decision: {method}")

        # Emit event for dashboard visibility
        if self.stream_emitter:
            try:
                self.stream_emitter.emit("forced_decision", record)
            except Exception:
                pass  # Non-critical

    def _reset_cycle_state(self):
        """Reset per-cycle state at the start of each cycle."""
        self._warned_50 = False
        self._warned_75 = False
        self._warned_90 = False
        self._fast_track_mode = False
        self._design_recovery_attempts = set()
        self._phase_progress = {}
        self._phase_metrics = {}  # Duration vs budget metrics for each phase
        self._cycle_backup_path = None  # Backup path for timeout rollback

    async def _run_with_phase_timeout(self, phase: str, coro, fallback=None):
        """
        Execute a phase coroutine with individual timeout protection.

        Complements the cycle-level timeout by preventing any single phase
        from consuming the entire time budget. Also tracks phase duration
        metrics for analysis and tuning.

        Uses escalated timeouts on retry attempts (1.3x per attempt, up to 2x).

        Args:
            phase: Phase name (context, debate, design, implement, verify, commit)
            coro: Async coroutine to execute
            fallback: Optional fallback value on timeout (if None, raises PhaseError)

        Returns:
            Coroutine result or fallback value

        Raises:
            PhaseError: If timeout occurs and no fallback provided
        """
        # Get current attempt from phase_recovery for timeout escalation
        attempt = self.phase_recovery.current_attempt.get(phase, 0)
        timeout = self.phase_recovery.get_escalated_timeout(phase, attempt)

        if attempt > 0:
            self._log(
                f"  [timeout] Phase '{phase}' retry {attempt}: escalated to {timeout}s budget"
            )
        else:
            self._log(f"  [timeout] Phase '{phase}' has {timeout}s budget")
        self._stream_emit("on_phase_start", phase, timeout)

        # Track phase start time for metrics
        phase_start = time.time()

        # Distributed tracing span for phase execution
        tracer = get_tracer()
        with tracer.start_as_current_span(f"nomic.phase.{phase}") as span:
            span.set_attribute("nomic.phase", phase)
            span.set_attribute("nomic.cycle", self.cycle_count)
            span.set_attribute("nomic.timeout_budget", timeout)
            span.set_attribute("nomic.attempt", attempt)

            try:
                result = await asyncio.wait_for(coro, timeout=timeout)

                # Log duration metrics on success
                duration = time.time() - phase_start
                utilization = (duration / timeout) * 100
                self._log(
                    f"  [{phase}] Completed in {duration:.1f}s ({utilization:.0f}% of {timeout}s budget)"
                )

                span.set_attribute("nomic.phase.duration_s", round(duration, 1))
                span.set_attribute("nomic.phase.status", "completed")
                span.set_attribute("nomic.phase.utilization_pct", round(utilization, 1))

                # Store metrics for cycle_result (initialize dict if needed)
                if not hasattr(self, "_phase_metrics"):
                    self._phase_metrics = {}
                self._phase_metrics[phase] = {
                    "duration": round(duration, 1),
                    "budget": timeout,
                    "utilization": round(utilization, 1),
                    "status": "completed",
                }

                return result

            except asyncio.TimeoutError:
                duration = time.time() - phase_start
                elapsed_msg = f"Phase '{phase}' exceeded {timeout}s timeout"
                self._log(f"  [TIMEOUT] {elapsed_msg}")
                logger.warning(f"[phase_timeout] {elapsed_msg}")
                self._stream_emit("on_phase_timeout", phase, timeout)

                span.set_attribute("nomic.phase.duration_s", round(duration, 1))
                span.set_attribute("nomic.phase.status", "timeout")

                # Store timeout metrics
                if not hasattr(self, "_phase_metrics"):
                    self._phase_metrics = {}
                self._phase_metrics[phase] = {
                    "duration": round(duration, 1),
                    "budget": timeout,
                    "utilization": 100.0,  # Consumed entire budget
                    "status": "timeout",
                }

                if fallback is not None:
                    return fallback
                raise PhaseError(phase, f"Timeout after {timeout}s", recoverable=False)

    async def _run_phase_with_recovery(self, phase: str, coro_factory, fallback=None):
        """
        Run a phase with both timeout enforcement and retry recovery.

        Combines _run_with_phase_timeout (for individual phase timeout)
        with PhaseRecovery.run_with_recovery (for retry with exponential backoff).

        Args:
            phase: Phase name (context, debate, design, implement, verify, commit)
            coro_factory: Callable that returns a fresh coroutine on each call.
                         IMPORTANT: Must be a factory (e.g., lambda: self.phase_debate())
                         NOT a coroutine (e.g., self.phase_debate())
            fallback: Optional fallback value on timeout/failure

        Returns:
            Coroutine result, fallback value, or raises PhaseError
        """

        async def timeout_wrapped():
            # Create fresh coroutine for each retry attempt (fixes reuse bug)
            coro = coro_factory()
            return await self._run_with_phase_timeout(phase, coro, fallback)

        success, result = await self.phase_recovery.run_with_recovery(
            phase=phase,
            phase_func=timeout_wrapped,
        )

        if success:
            return result
        else:
            # result contains error message
            if fallback is not None:
                self._log(f"  [recovery] Phase '{phase}' failed, using fallback")
                return fallback
            raise PhaseError(phase, f"Recovery failed: {result}", recoverable=False)

    async def _check_agent_health(self, agent, agent_name: str) -> bool:
        """
        Quick health check to verify agent is responsive.

        Args:
            agent: The agent object to check
            agent_name: Name for logging

        Returns:
            True if agent responded within timeout
        """
        try:
            # Simple health probe with 15 second timeout
            await asyncio.wait_for(
                agent.generate("Respond with OK to confirm you are ready.", context=[]), timeout=15
            )
            self.circuit_breaker.record_success(agent_name)
            return True
        except asyncio.TimeoutError:
            self._log(f"  [health] Agent {agent_name} health check timed out")
            tripped = self.circuit_breaker.record_failure(agent_name)
            if tripped:
                self._log(
                    f"  [circuit-breaker] Agent {agent_name} disabled for {self.circuit_breaker.cooldown_cycles} cycles"
                )
            return False
        except Exception as e:
            self._log(f"  [health] Agent {agent_name} health check failed: {e}")
            self.circuit_breaker.record_failure(agent_name)
            return False

    def _create_backup(self, reason: str = "pre_cycle") -> Path:
        """Create a backup of protected files before making changes."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{reason}_{timestamp}"
        backup_path = self.backup_dir / backup_name
        backup_path.mkdir(parents=True, exist_ok=True)

        self._log(f"  Creating backup: {backup_name}")

        backed_up = []
        for rel_path in PROTECTED_FILES:
            src = self.aragora_path / rel_path
            if src.exists():
                dst = backup_path / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                backed_up.append(rel_path)
                self._log(f"    Backed up: {rel_path}", also_print=False)

        # Save manifest
        manifest = {
            "created_at": datetime.now().isoformat(),
            "reason": reason,
            "cycle": self.cycle_count,
            "files": backed_up,
        }
        with open(backup_path / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        self._log(f"  Backup complete: {len(backed_up)} files")
        self._stream_emit("on_backup_created", backup_name, len(backed_up), reason)
        return backup_path

    def _restore_backup(self, backup_path: Path) -> bool:
        """Restore protected files from a backup."""
        manifest_file = backup_path / "manifest.json"
        if not manifest_file.exists():
            self._log(f"  No manifest found in {backup_path}")
            return False

        with open(manifest_file) as f:
            manifest = json.load(f)

        self._log(f"  Restoring backup from {manifest['created_at']}")

        restored = []
        for rel_path in manifest["files"]:
            src = backup_path / rel_path
            dst = self.aragora_path / rel_path
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored.append(rel_path)
                self._log(f"    Restored: {rel_path}", also_print=False)

        self._log(f"  Restored {len(restored)} files")
        self._stream_emit(
            "on_backup_restored", backup_path.name, len(restored), "verification_failed"
        )
        return True

    def _get_latest_backup(self) -> Path | None:
        """Get the most recent backup directory."""
        backups = sorted(self.backup_dir.iterdir(), reverse=True)
        for backup in backups:
            if (backup / "manifest.json").exists():
                return backup
        return None

    def _verify_protected_files(self) -> list[str]:
        """Verify protected files still exist and are importable."""
        issues = []

        for rel_path in PROTECTED_FILES:
            full_path = self.aragora_path / rel_path
            if not full_path.exists():
                issues.append(f"MISSING: {rel_path}")
                continue

            # Check if Python file is syntactically valid
            if rel_path.endswith(".py"):
                try:
                    result = subprocess.run(
                        ["python", "-m", "py_compile", str(full_path)],
                        capture_output=True,
                        text=True,
                        timeout=30,  # 30s is plenty for syntax check
                    )
                    if result.returncode != 0:
                        issues.append(f"SYNTAX ERROR: {rel_path}")
                except Exception as e:
                    issues.append(f"CHECK FAILED: {rel_path} - {e}")

        return issues

    def _init_agents(self):
        """Initialize agents with distinct personalities and safety awareness."""

        def _env_int(key: str) -> int | None:
            value = os.environ.get(key)
            if not value:
                return None
            try:
                return int(value)
            except ValueError:
                return None

        def _env_float(key: str) -> float | None:
            value = os.environ.get(key)
            if not value:
                return None
            try:
                return float(value)
            except ValueError:
                return None

        agent_timeout_override = _env_int("NOMIC_AGENT_TIMEOUT") or _env_int(
            "ARAGORA_NOMIC_AGENT_TIMEOUT"
        )

        # Common safety footer for all agents
        safety_footer = """

CRITICAL: You are part of a self-improving system. You MUST:
- NEVER propose removing or simplifying core infrastructure (nomic_loop.py, aragora/core.py, debate system)
- ALWAYS prefer adding new features over removing existing ones
- ONLY remove code that is demonstrably BROKEN or HARMFUL
- Preserve backward compatibility in all changes
- If unsure whether to keep functionality, KEEP IT"""

        use_openrouter_gemini = os.environ.get("NOMIC_GEMINI_USE_OPENROUTER", "0") == "1"
        if use_openrouter_gemini:
            self.gemini = OpenRouterAgent(
                name="gemini-visionary",
                model="google/gemini-3.1-pro-preview",
                role="proposer",
                timeout=720,  # Doubled to 12 min for thorough codebase exploration
            )
        else:
            self.gemini = GeminiAgent(
                name="gemini-visionary",
                model="gemini-3.1-pro-preview",  # Gemini 3.1 Pro
                role="proposer",
                timeout=720,  # Doubled to 12 min for thorough codebase exploration
            )
        self.gemini.system_prompt = (
            """You are a visionary product strategist for aragora.
Focus on: viral growth, developer excitement, novel capabilities, bold ideas.

=== STRUCTURED THINKING PROTOCOL ===
When analyzing a task:
1. EXPLORE: First understand the current state - what exists, what's missing
2. ENVISION: Imagine the ideal outcome - what would success look like
3. REASON: Show your thinking step-by-step - explain tradeoffs
4. PROPOSE: Make concrete, actionable proposals with clear impact

When proposing changes:
- Reference specific files and code patterns you've observed
- Consider what would make aragora famous and widely adopted
- Think about viral growth potential and developer excitement

=== BUILD MODE ===
Your proposals should ADD capabilities, not remove or simplify existing ones.
Aragora should grow more powerful over time, not be stripped down."""
            + safety_footer
        )

        use_api_codex = os.environ.get("NOMIC_CODEX_USE_API", "0") == "1"
        codex_api_model = os.environ.get("NOMIC_CODEX_API_MODEL", "gpt-5.3")
        if use_api_codex:
            self.codex = OpenAIAPIAgent(
                name="codex-engineer",
                model=codex_api_model,
                role="proposer",
                timeout=1200,  # Doubled - Codex has known latency issues
            )
        else:
            self.codex = CodexAgent(
                name="codex-engineer",
                model="gpt-5.3-codex",
                role="proposer",
                timeout=1200,  # Doubled - Codex has known latency issues
            )
        self.codex.system_prompt = (
            """You are a pragmatic engineer for aragora.
Focus on: technical excellence, code quality, practical utility, implementation feasibility.

=== STRUCTURED THINKING PROTOCOL ===
When analyzing code:
1. TRACE: Follow code paths to understand dependencies and data flow
2. ANALYZE: Identify patterns, anti-patterns, and improvement opportunities
3. DESIGN: Consider multiple implementation approaches with pros/cons
4. VALIDATE: Think about edge cases, tests, and failure modes

When proposing changes:
- Show your reasoning chain: "I observed X → which implies Y → so we should Z"
- Reference specific files and line numbers
- Consider impact on tests, performance, and maintainability

=== BUILD MODE ===
Your role is to BUILD and EXTEND, not to remove or break.
Safe refactors: renaming, extracting, improving types.
Unsafe: removing features, breaking APIs.
Reducing technical debt is GOOD when safe (improve code without changing behavior)."""
            + safety_footer
        )

        self.claude = ClaudeAgent(
            name="claude-visionary",
            model="claude",
            role="proposer",
            timeout=600,  # 10 min - increased for judge role with large context
            prefer_api=True,  # Skip CLI (returns code 1), use OpenRouter directly
        )
        self.claude.system_prompt = (
            """You are a visionary architect for aragora.
Focus on: elegant design, user experience, novel AI patterns, system cohesion.

=== STRUCTURED THINKING PROTOCOL ===
When analyzing a task:
1. EXPLORE: First understand the current state - read relevant files, trace code paths
2. PLAN: Design your approach before implementing - consider alternatives
3. REASON: Show your thinking step-by-step - explain tradeoffs
4. PROPOSE: Make concrete, actionable proposals with clear impact

When using Claude Code:
- Use 'Explore' mode to deeply understand the codebase before proposing
- Use 'Plan' mode to design implementation approaches with user approval
- Ask clarifying questions rather than making assumptions

When proposing changes:
- Reference specific files and architectural patterns
- Consider system cohesion and how parts fit together
- Think about what would make aragora powerful and delightful

=== GUARDIAN ROLE ===
You are a guardian of aragora's core functionality.
Your proposals should ADD capabilities and improve the system.
Never propose removing the nomic loop or core debate infrastructure."""
            + safety_footer
        )

        use_api_grok = os.environ.get("NOMIC_GROK_USE_API", "0") == "1"
        if use_api_grok:
            self.grok = GrokAgent(
                name="grok-lateral-thinker",
                model="grok-4",  # Grok 4 full
                role="proposer",
                timeout=1200,  # Doubled to 20 min for thorough codebase exploration
            )
        else:
            self.grok = GrokCLIAgent(
                name="grok-lateral-thinker",
                model="grok-4",  # Grok 4 full
                role="proposer",
                timeout=1200,  # Doubled to 20 min for thorough codebase exploration
            )
        self.grok.system_prompt = (
            """You are a lateral-thinking synthesizer for aragora.
Focus on: unconventional approaches, novel patterns, creative breakthroughs.

=== STRUCTURED THINKING PROTOCOL ===
When analyzing a task:
1. DIVERGE: Generate multiple unconventional perspectives on the problem
2. CONNECT: Find surprising links between disparate ideas and patterns
3. SYNTHESIZE: Combine insights into novel, coherent proposals
4. GROUND: Anchor creative ideas in practical implementation

When proposing changes:
- Show your lateral thinking: "Others see X, but what if Y..."
- Connect ideas from different domains in surprising ways
- Balance creativity with practicality

=== BUILD MODE ===
Your role is to BUILD and EXTEND, not to remove or break.
Propose additions that unlock new capabilities and create emergent value.
The most valuable proposals are those that others wouldn't think of."""
            + safety_footer
        )

        # DeepSeek V3 - latest general model via OpenRouter
        self.deepseek = DeepSeekV3Agent(
            name="deepseek-v3",
            role="proposer",
        )
        self.deepseek.system_prompt = (
            """You are a powerful analytical agent for aragora.
Focus on: comprehensive analysis, practical solutions, efficient implementation.

=== ANALYTICAL PROTOCOL ===
When analyzing a task:
1. UNDERSTAND: Deeply comprehend the problem and its context
2. ANALYZE: Evaluate all aspects systematically
3. DESIGN: Propose well-structured, practical solutions
4. VALIDATE: Ensure solutions are correct and complete

When proposing changes:
- Provide thorough analysis with clear reasoning
- Consider performance, maintainability, and edge cases
- Balance elegance with practicality
- Give concrete, actionable recommendations

=== BUILD MODE ===
Your role is to BUILD and EXTEND, not to remove or break.
Propose additions that are practical, efficient, and well-designed.
The most valuable proposals combine deep analysis with actionable implementation."""
            + safety_footer
        )

        self.mistral = MistralAgent(
            name="mistral-frontier",
            role="proposer",
        )
        self.mistral.system_prompt = self.deepseek.system_prompt

        self.qwen = QwenAgent(
            name="qwen-frontier",
            role="proposer",
        )
        self.qwen.system_prompt = self.deepseek.system_prompt

        self.kimi = KimiK2Agent(
            name="kimi-frontier",
            role="proposer",
        )
        self.kimi.system_prompt = self.deepseek.system_prompt

        # Apply optional per-agent timeout overrides (CLI/API agents honor .timeout)
        if agent_timeout_override:
            for agent in (
                self.gemini,
                self.codex,
                self.claude,
                self.grok,
                self.deepseek,
                self.mistral,
                self.qwen,
                self.kimi,
            ):
                if hasattr(agent, "timeout"):
                    try:
                        agent.timeout = max(int(agent.timeout), agent_timeout_override)
                    except Exception:
                        agent.timeout = agent_timeout_override

        # Wrap all agents with Airlock for resilience
        # This adds timeout handling, null byte sanitization, and fallback responses
        # Timeouts increased to accommodate CLI agents (codex/claude can take 10+ min)
        generate_timeout = _env_float("NOMIC_AIRLOCK_GENERATE_TIMEOUT") or 600.0
        critique_timeout = _env_float("NOMIC_AIRLOCK_CRITIQUE_TIMEOUT") or 300.0
        vote_timeout = _env_float("NOMIC_AIRLOCK_VOTE_TIMEOUT") or 120.0
        airlock_config = AirlockConfig(
            generate_timeout=generate_timeout,
            critique_timeout=critique_timeout,
            vote_timeout=vote_timeout,
            max_retries=1,
            fallback_on_timeout=True,
            fallback_on_error=True,
        )
        self.gemini = AirlockProxy(self.gemini, airlock_config)
        self.codex = AirlockProxy(self.codex, airlock_config)
        self.claude = AirlockProxy(self.claude, airlock_config)
        self.grok = AirlockProxy(self.grok, airlock_config)
        self.deepseek = AirlockProxy(self.deepseek, airlock_config)
        self.mistral = AirlockProxy(self.mistral, airlock_config)
        self.qwen = AirlockProxy(self.qwen, airlock_config)
        self.kimi = AirlockProxy(self.kimi, airlock_config)
        self._log("  [airlock] All 8 agents wrapped with resilience layer")

        self.agent_pool = {
            "gemini": self.gemini,
            "openai-api": self.codex,
            "anthropic-api": self.claude,
            "grok": self.grok,
            "deepseek": self.deepseek,
            "mistral": self.mistral,
            "qwen": self.qwen,
            "kimi": self.kimi,
        }

        # Wire Knowledge Mound for context gathering (#179)
        try:
            from aragora.nomic.km_context import get_nomic_knowledge_mound

            self.knowledge_mound = get_nomic_knowledge_mound()
        except Exception:
            self.knowledge_mound = None

        # Gastown-style convoy executor for implementation phase
        self.implement_executor = GastownConvoyExecutor(
            repo_path=self.aragora_path,
            implementers=[self.claude, self.codex],
            reviewers=[
                self.gemini,
                self.grok,
                self.deepseek,
                self.mistral,
                self.qwen,
                self.kimi,
            ],
            log_fn=self._log,
            stream_emit_fn=self._stream_emit,
        )

    def _create_verify_phase(self) -> "VerifyPhase":
        """Create an extracted VerifyPhase instance.

        This method demonstrates how to use the extracted phase classes.
        The extracted phases provide:
        - Better testability (can test phases independently)
        - Cleaner dependency injection
        - Easier maintenance and refactoring

        Usage:
            verify_phase = self._create_verify_phase()
            result = await verify_phase.execute()
        """
        if not _NOMIC_PHASES_AVAILABLE:
            raise RuntimeError("Extracted phases not available")

        return VerifyPhase(
            aragora_path=self.aragora_path,
            codex=self.codex if hasattr(self, "codex") else None,
            nomic_integration=(
                self.nomic_integration if hasattr(self, "nomic_integration") else None
            ),
            cycle_count=self.cycle_count,
            log_fn=self._log,
            stream_emit_fn=self._stream_emit,
            record_replay_fn=(
                self._record_replay_event if hasattr(self, "_record_replay_event") else None
            ),
            save_state_fn=self._save_state if hasattr(self, "_save_state") else None,
        )

    def _create_commit_phase(self) -> "CommitPhase":
        """Create an extracted CommitPhase instance."""
        if not _NOMIC_PHASES_AVAILABLE:
            raise RuntimeError("Extracted phases not available")

        return CommitPhase(
            aragora_path=self.aragora_path,
            require_human_approval=self.require_human_approval,
            auto_commit=self.auto_commit,
            cycle_count=self.cycle_count,
            log_fn=self._log,
            stream_emit_fn=self._stream_emit,
        )

    def _create_debate_phase(self, topic_hint: str = "") -> "DebatePhase":
        """Create an extracted DebatePhase instance.

        Uses NomicDebateProfile for full-power 8-round structured debates with
        all 8 frontier models when available, falling back to DebateSettings defaults.

        NOTE: The inline phase_debate() is ~787 lines with extensive post-processing
        integrations (ELO, calibration, relationships, personas, etc.). Full migration
        requires providing PostDebateHooks callbacks for all integrations.

        Args:
            topic_hint: Optional topic hint for agent selection (e.g., from initial_proposal)
        """
        if not _NOMIC_PHASES_AVAILABLE:
            raise RuntimeError("Extracted phases not available")

        # Use NomicDebateProfile for full-power debates
        force_full_team = os.environ.get("NOMIC_FORCE_FULL_TEAM", "0") == "1"
        try:
            from aragora.nomic.debate_profile import NomicDebateProfile

            profile = NomicDebateProfile.from_env()
            debate_config = profile.to_debate_config()
            force_full_team = True
            self._log(
                f"  [debate] Using NomicDebateProfile: {profile.agent_count} agents, "
                f"{profile.rounds} rounds, {profile.total_phases} phases"
            )
        except ImportError:
            debate_settings = DebateSettings()
            debate_config = DebateConfig(rounds=debate_settings.default_rounds)

        # Select debate team dynamically (like the legacy inline implementation)
        debate_team = self._select_debate_team(topic_hint, force_full_team=force_full_team)

        return DebatePhase(
            aragora_path=self.aragora_path,
            agents=debate_team,
            arena_factory=lambda *args, **kwargs: Arena(*args, **kwargs),
            environment_factory=lambda *args, **kwargs: Environment(*args, **kwargs),
            protocol_factory=lambda *args, **kwargs: DebateProtocol(*args, **kwargs),
            config=debate_config,
            nomic_integration=(
                self.nomic_integration if hasattr(self, "nomic_integration") else None
            ),
            cycle_count=self.cycle_count,
            initial_proposal=self.initial_proposal if hasattr(self, "initial_proposal") else None,
            log_fn=self._log,
            stream_emit_fn=self._stream_emit,
            record_replay_fn=(
                self._record_replay_event if hasattr(self, "_record_replay_event") else None
            ),
        )

    def _create_design_phase(self) -> "DesignPhase":
        """Create an extracted DesignPhase instance.

        NOTE: The inline phase_design() is ~300 lines with belief network integration,
        deadlock resolution, and agent probing. Full migration requires passing
        additional configuration and callbacks.

        Current status: Factory method available for external callers.
        Full inline migration: Pending hooks architecture.
        """
        if not _NOMIC_PHASES_AVAILABLE:
            raise RuntimeError("Extracted phases not available")

        # Select agents with fallback to all agents if selection returns empty
        design_agents = self._select_debate_team("design")
        if not design_agents:
            self._log("  [design] WARNING: No agents from selection, using all available")
            agent_pool = getattr(self, "agent_pool", {})
            design_agents = [a for a in agent_pool.values() if a is not None]

        if not design_agents:
            raise RuntimeError("No agents available for design phase")

        return DesignPhase(
            aragora_path=self.aragora_path,
            agents=design_agents,
            arena_factory=lambda *args, **kwargs: Arena(*args, **kwargs),
            environment_factory=lambda *args, **kwargs: Environment(*args, **kwargs),
            protocol_factory=lambda *args, **kwargs: DebateProtocol(*args, **kwargs),
            config=DesignConfig(),
            nomic_integration=(
                self.nomic_integration if hasattr(self, "nomic_integration") else None
            ),
            deep_audit_fn=self._deep_audit if hasattr(self, "_deep_audit") else None,
            arbitrate_fn=self._arbitrate_designs if hasattr(self, "_arbitrate_designs") else None,
            max_cycle_seconds=(
                self.max_cycle_seconds if hasattr(self, "max_cycle_seconds") else 3600
            ),
            cycle_count=self.cycle_count,
            log_fn=self._log,
            stream_emit_fn=self._stream_emit,
            record_replay_fn=(
                self._record_replay_event if hasattr(self, "_record_replay_event") else None
            ),
        )

    def _create_memory_gateway(self):
        """Create a MemoryGateway from available subsystems for implementation context."""
        try:
            from aragora.memory.gateway import MemoryGateway
            from aragora.memory.gateway_config import MemoryGatewayConfig

            km = getattr(self, "knowledge_mound", None)
            if km is None:
                return None

            return MemoryGateway(
                config=MemoryGatewayConfig(enabled=True),
                knowledge_mound=km,
            )
        except Exception as exc:
            self._log(f"  [memory] Gateway creation failed: {exc}")
            return None

    def _create_implement_phase(self) -> "ImplementPhase":
        """Create an extracted ImplementPhase instance.

        The ImplementPhase handles hybrid multi-model code generation with
        crash recovery via checkpoints and pre-verification review.

        When ConvoyImplementExecutor is available, it provides Gastown-style
        multi-agent parallel implementation with cross-checking.
        """
        if not _NOMIC_PHASES_AVAILABLE:
            raise RuntimeError("Extracted phases not available")

        # Check if hybrid implementation is enabled (default: yes)
        # When ARAGORA_HYBRID_IMPLEMENT=0, skip convoy executor creation entirely
        # This is used by nomic_eval.py for single-agent baseline evaluations
        use_hybrid = os.environ.get("ARAGORA_HYBRID_IMPLEMENT", "1") == "1"

        # Create convoy executor for multi-agent implementation if available
        executor = getattr(self, "implement_executor", None)
        if executor is None and use_hybrid:
            try:
                from aragora.nomic.convoy_executor import GastownConvoyExecutor
                from aragora.nomic.debate_profile import NomicDebateProfile

                profile = NomicDebateProfile.from_env()
                implementers = [
                    self._create_agent_for_implement(name) for name in profile.agent_names
                ]
                implementers = [a for a in implementers if a is not None]
                executor = GastownConvoyExecutor(
                    repo_path=self.aragora_path,
                    implementers=implementers,
                    reviewers=implementers,
                    log_fn=self._log,
                    stream_emit_fn=self._stream_emit,
                )
                self._log(
                    f"  [implement] GastownConvoyExecutor created with {len(implementers)} agents"
                )
            except ImportError:
                pass

        if executor is None and use_hybrid:
            try:
                from aragora.nomic.implement_executor import ConvoyImplementExecutor
                from aragora.nomic.debate_profile import NomicDebateProfile

                profile = NomicDebateProfile.from_env()
                executor = ConvoyImplementExecutor(
                    aragora_path=self.aragora_path,
                    agents=profile.agent_names,
                    agent_factory=self._create_agent_for_implement,
                    max_parallel=4,
                    enable_cross_check=True,
                    log_fn=self._log,
                )
                self._log(
                    f"  [implement] ConvoyImplementExecutor created with "
                    f"{profile.agent_count} agents"
                )
            except ImportError:
                pass

        if not use_hybrid:
            self._log("  [implement] Hybrid mode disabled, using legacy implementation")
        elif executor is not None:
            self._log("  [implement] Convoy/bead executor active for multi-agent cross-checks")
        else:
            self._log("  [implement] WARNING: No convoy executor available, using legacy fallback")

        return ImplementPhase(
            aragora_path=self.aragora_path,
            plan_generator=(
                self._generate_implement_plan if hasattr(self, "_generate_implement_plan") else None
            ),
            executor=executor,
            progress_loader=lambda path: load_progress(path) if "load_progress" in dir() else None,
            progress_saver=lambda data, path: (
                save_progress(data, path) if "save_progress" in dir() else None
            ),
            progress_clearer=lambda path: (
                clear_progress(path) if "clear_progress" in dir() else None
            ),
            protected_files=getattr(self, "protected_files", None),
            cycle_count=self.cycle_count,
            log_fn=self._log,
            stream_emit_fn=self._stream_emit,
            record_replay_fn=(
                self._record_replay_event if hasattr(self, "_record_replay_event") else None
            ),
            save_state_fn=self.save_state if hasattr(self, "save_state") else None,
            constitution_verifier=self.constitution_verifier,
            memory_gateway=self._create_memory_gateway(),
        )

    async def _generate_implement_plan(self, design: str, repo_path: Path):
        """Generate an implementation plan with Gemini; fallback to single task."""
        try:
            return await generate_implement_plan(design, repo_path)
        except Exception as e:
            self._log(f"  [implement] Plan generation failed, using fallback: {e}")
            return create_single_task_plan(design, repo_path)

    def _create_context_phase(self) -> "ContextPhase":
        """Create an extracted ContextPhase instance.

        The ContextPhase gathers codebase understanding from multiple agents
        using their native exploration harnesses.

        When NomicContextBuilder is available, it also builds a TRUE RLM-powered
        codebase index for deep context that agents can query programmatically.

        Single-Agent Mode:
            When NOMIC_SINGLE_AGENT=1, only the target agent (specified by
            NOMIC_SINGLE_AGENT_NAME) participates in context gathering.
            This is used by nomic_eval.py for single-agent baseline evaluations.
        """
        if not _NOMIC_PHASES_AVAILABLE:
            raise RuntimeError("Extracted phases not available")

        # Build deep codebase context via NomicContextBuilder if available
        try:
            from aragora.nomic.context_builder import NomicContextBuilder

            if not hasattr(self, "_context_builder"):
                self._context_builder = NomicContextBuilder(
                    aragora_path=self.aragora_path,
                    knowledge_mound=getattr(self, "knowledge_mound", None),
                )
            self._log("  [context] NomicContextBuilder available for deep codebase indexing")
        except ImportError:
            pass

        # Determine agent assignments based on single-agent mode
        claude_agent = getattr(self, "claude", None)
        codex_agent = getattr(self, "codex", None)
        gemini_agent = getattr(self, "gemini", None)
        grok_agent = getattr(self, "grok", None)
        kilocode_available = self._resolve_kilocode_available()
        skip_kilocode = self._resolve_kilocode_skip()

        # Single-agent mode: only pass the target agent to context phase
        # This ensures context gathering uses only one agent for fair evaluation
        if os.environ.get("NOMIC_SINGLE_AGENT", "0") == "1":
            target_name = os.environ.get("NOMIC_SINGLE_AGENT_NAME", "").strip().lower()
            self._log(f"  [context] Single-agent mode: target={target_name or 'first available'}")

            # Map target names to agent attributes
            agent_map = {
                "claude": "claude",
                "anthropic": "claude",
                "anthropic-api": "claude",
                "codex": "codex",
                "openai": "codex",
                "openai-api": "codex",
                "gemini": "gemini",
                "google": "gemini",
                "grok": "grok",
                "xai": "grok",
            }

            # Determine which agent to keep
            target_attr = agent_map.get(target_name)
            if target_attr:
                # Null out non-target agents
                if target_attr != "claude":
                    claude_agent = None
                if target_attr != "codex":
                    codex_agent = None
                if target_attr != "gemini":
                    gemini_agent = None
                if target_attr != "grok":
                    grok_agent = None
                # Disable kilocode if target is claude or codex (they use native CLI)
                if target_attr in ("claude", "codex"):
                    kilocode_available = False
                    skip_kilocode = True
            else:
                # No valid target specified, use first available (claude or codex)
                codex_agent = None
                gemini_agent = None
                grok_agent = None
                kilocode_available = False
                skip_kilocode = True

        return ContextPhase(
            aragora_path=self.aragora_path,
            claude_agent=claude_agent,
            codex_agent=codex_agent,
            gemini_agent=gemini_agent,
            grok_agent=grok_agent,
            kilocode_available=kilocode_available,
            skip_kilocode=skip_kilocode,
            kilocode_agent_factory=KiloCodeAgent,
            cycle_count=self.cycle_count,
            log_fn=self._log,
            stream_emit_fn=self._stream_emit,
            get_features_fn=(
                self.get_current_features if hasattr(self, "get_current_features") else None
            ),
            context_builder=getattr(self, "_context_builder", None),
        )

    def _resolve_kilocode_available(self) -> bool:
        """Determine whether KiloCode should be treated as available for context."""
        kilocode_available = KILOCODE_AVAILABLE if "KILOCODE_AVAILABLE" in dir() else False
        env_kilo = os.environ.get("NOMIC_KILOCODE_AVAILABLE")
        if env_kilo is not None:
            return env_kilo.strip().lower() in {"1", "true", "yes", "on"}
        if not kilocode_available:
            try:
                import shutil

                return (shutil.which("kilo") is not None) or (shutil.which("kilocode") is not None)
            except Exception:
                return False
        return kilocode_available

    def _resolve_kilocode_skip(self) -> bool:
        """Resolve whether KiloCode context gathering should be skipped."""
        skip_kilocode = (
            SKIP_KILOCODE_CONTEXT_GATHERING if "SKIP_KILOCODE_CONTEXT_GATHERING" in dir() else True
        )
        env_skip = os.environ.get("NOMIC_SKIP_KILOCODE_CONTEXT_GATHERING")
        if env_skip is None:
            env_skip = os.environ.get("NOMIC_SKIP_KILOCODE_CONTEXT")
        if env_skip is not None:
            return env_skip.strip().lower() in {"1", "true", "yes", "on"}
        return skip_kilocode

    def _create_agent_for_implement(self, agent_name: str):
        """Create or retrieve an agent instance for implementation tasks.

        Maps agent names (from NomicDebateProfile) to actual agent instances
        that can execute code generation prompts via agent.generate(prompt).
        """
        # Check well-known agent attributes first
        agent_map = {
            "anthropic-api": getattr(self, "claude", None),
            "openai-api": getattr(self, "codex", None),
        }
        if agent_name in agent_map and agent_map[agent_name] is not None:
            return agent_map[agent_name]
        # Fall back to the agent pool (populated during _setup_agents)
        pool = getattr(self, "agent_pool", {})
        if agent_name in pool:
            return pool[agent_name]
        # Last resort: return any available agent
        return getattr(self, "codex", None) or getattr(self, "claude", None)

    def _create_post_debate_hooks(self, debate_team: list = None) -> "PostDebateHooks":
        """Create PostDebateHooks with callbacks to NomicLoop's post-processing methods.

        This enables the extracted DebatePhase to perform all the same post-processing
        that the inline phase_debate() does. Each hook maps to a specific NomicLoop method:

        - on_consensus_stored → _store_debate_consensus
        - on_calibration_recorded → _record_calibration_from_debate
        - on_insights_extracted → _extract_and_store_insights
        - on_memories_recorded → _record_agent_memories
        - on_persona_recorded → _record_persona_performance
        - on_patterns_extracted → _extract_and_store_patterns
        - on_meta_analyzed → _analyze_debate_process + _store_meta_recommendations
        - on_elo_recorded → _record_elo_match
        - on_claims_extracted → _extract_claims_from_debate
        - on_belief_network_built → _build_belief_network
        - on_risks_tracked → _track_debate_risks
        """
        if not _NOMIC_PHASES_AVAILABLE:
            raise RuntimeError("Extracted phases not available")

        # Create wrapper functions that capture self and debate_team
        async def consensus_hook(result, topic):
            await self._store_debate_consensus(result, topic)

        def calibration_hook(result, agents):
            # Domain detection requires the topic, which we don't have here
            # Use "general" as default - the inline implementation has access to topic_hint
            self._record_calibration_from_debate(result, agents, domain="general")

        async def insights_hook(result):
            await self._extract_and_store_insights(result)

        async def memories_hook(result, topic):
            await self._record_agent_memories(result, topic)

        def persona_hook(result, topic):
            self._record_persona_performance(result, topic)

        async def patterns_hook(result):
            await self._extract_and_store_patterns(result)

        def meta_hook(result):
            meta_critique = self._analyze_debate_process(result)
            self._store_meta_recommendations(meta_critique)

        def elo_hook(result, topic):
            self._record_elo_match(result, topic)

        def claims_hook(result):
            self._extract_claims_from_debate(result)

        def belief_hook(result):
            self._build_belief_network()

        def risks_hook(result, topic):
            self._track_debate_risks(result, topic)

        return PostDebateHooks(
            on_consensus_stored=consensus_hook,
            on_calibration_recorded=calibration_hook,
            on_insights_extracted=insights_hook,
            on_memories_recorded=memories_hook,
            on_persona_recorded=persona_hook,
            on_patterns_extracted=patterns_hook,
            on_meta_analyzed=meta_hook,
            on_elo_recorded=elo_hook,
            on_claims_extracted=claims_hook,
            on_belief_network_built=belief_hook,
            on_risks_tracked=risks_hook,
        )

    def get_current_features(self) -> str:
        """Read current aragora state from the codebase."""
        init_file = self.aragora_path / "aragora" / "__init__.py"
        if init_file.exists():
            content = init_file.read_text()
            if '"""' in content:
                docstring = content.split('"""')[1]
                return docstring[:2000]
        return "Unable to read current features"

    async def _build_rlm_codebase_context(self) -> dict | None:
        """Build a TRUE RLM (REPL-based) codebase summary for large contexts."""
        try:
            from aragora.nomic.rlm_codebase import summarize_codebase_with_rlm
            from aragora.rlm import RLMConfig

            start = time.perf_counter()
            require_true = os.environ.get("NOMIC_RLM_REQUIRE_TRUE", "1") == "1"
            max_bytes = int(
                os.environ.get(
                    "ARAGORA_NOMIC_MAX_CONTEXT_BYTES",
                    os.environ.get(
                        "NOMIC_MAX_CONTEXT_BYTES",
                        str(RLMConfig().max_content_bytes_nomic),
                    ),
                )
            )
            max_files = int(os.environ.get("NOMIC_RLM_MAX_FILES", "25000"))
            max_file_bytes = int(os.environ.get("NOMIC_RLM_MAX_FILE_BYTES", "2000000"))

            self._log(
                f"  [rlm] Building codebase summary (require_true={require_true}, "
                f"max_bytes={max_bytes}, max_files={max_files})"
            )
            output_dir = self.nomic_dir / "rlm"
            result = await summarize_codebase_with_rlm(
                repo_path=self.aragora_path,
                output_dir=output_dir,
                require_true_rlm=require_true,
                max_content_bytes=max_bytes,
                max_files=max_files,
                max_file_bytes=max_file_bytes,
            )
            elapsed = time.perf_counter() - start
            self._log(
                f"  [rlm] Codebase summary complete in {elapsed:.1f}s "
                f"(true_rlm={result.used_true_rlm}, fallback={result.used_fallback})"
            )

            return {
                "summary": result.summary,
                "corpus_path": str(result.corpus.corpus_path),
                "manifest_path": str(result.corpus.manifest_path),
                "file_count": result.corpus.file_count,
                "total_bytes": result.corpus.total_bytes,
                "estimated_tokens": result.corpus.estimated_tokens,
                "used_true_rlm": result.used_true_rlm,
                "used_fallback": result.used_fallback,
                "error": result.error,
            }
        except Exception as e:
            self._log(f"  [rlm] Codebase summary failed: {e}")
            return None

    def get_recent_changes(self) -> str:
        """Get recent git commits."""
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                cwd=self.aragora_path,
                capture_output=True,
                text=True,
            )
            return result.stdout
        except Exception:
            return "Unable to read git history"

    def _analyze_failed_branches(self, limit: int = 3) -> str:
        """Analyze recent failed branches for lessons learned.

        This extracts information from preserved failed branches so agents
        can learn from previous failures and avoid repeating them.
        """
        try:
            # List failed branches
            result = subprocess.run(
                ["git", "branch", "--list", "nomic-failed-*"],
                cwd=self.aragora_path,
                capture_output=True,
                text=True,
            )
            branches = [b.strip() for b in result.stdout.strip().split("\n") if b.strip()]
            if not branches:
                return ""

            # Get most recent ones (sorted by name which includes timestamp)
            recent = sorted(branches, reverse=True)[:limit]

            lessons = ["## LESSONS FROM RECENT FAILURES"]
            lessons.append("Learn from these previous failed attempts:\n")

            for branch in recent:
                # Get commit message
                msg_result = subprocess.run(
                    ["git", "log", branch, "-1", "--format=%B"],
                    cwd=self.aragora_path,
                    capture_output=True,
                    text=True,
                )
                # Get changed files summary
                files_result = subprocess.run(
                    ["git", "diff", f"main...{branch}", "--stat", "--stat-width=60"],
                    cwd=self.aragora_path,
                    capture_output=True,
                    text=True,
                )

                lessons.append(f"**{branch}:**")
                lessons.append(f"```\n{msg_result.stdout[:1000].strip()}")
                if files_result.stdout.strip():
                    lessons.append(f"\nFiles changed:\n{files_result.stdout[:1000].strip()}")
                lessons.append("```\n")

            return "\n".join(lessons)
        except Exception:
            return ""

    def cleanup_failed_branches(self, max_age_days: int = 7) -> dict:
        """Cleanup failed branches older than max_age_days.

        Removes nomic-failed-* branches that are older than the retention period
        to prevent repository clutter. Recent branches are preserved for learning.

        Args:
            max_age_days: Maximum age in days for branch retention (default: 7)

        Returns:
            dict with "deleted" count and "preserved" count
        """
        result = {"deleted": 0, "preserved": 0, "errors": []}
        try:
            # List failed branches
            list_result = subprocess.run(
                ["git", "branch", "--list", "nomic-failed-*"],
                cwd=self.aragora_path,
                capture_output=True,
                text=True,
            )
            branches = [b.strip() for b in list_result.stdout.strip().split("\n") if b.strip()]
            if not branches:
                return result

            cutoff = datetime.now() - timedelta(days=max_age_days)

            for branch in branches:
                try:
                    # Extract timestamp from branch name (format: nomic-failed-YYYYMMDD-HHMMSS-*)
                    # or nomic-failed-cycle-N-YYYYMMDD-HHMMSS
                    parts = branch.replace("nomic-failed-", "").split("-")
                    timestamp_str = None

                    # Try to find date pattern YYYYMMDD
                    for i, part in enumerate(parts):
                        if len(part) == 8 and part.isdigit():
                            timestamp_str = part
                            if (
                                i + 1 < len(parts)
                                and len(parts[i + 1]) == 6
                                and parts[i + 1].isdigit()
                            ):
                                timestamp_str += parts[i + 1]
                            break

                    if timestamp_str:
                        if len(timestamp_str) >= 14:
                            branch_date = datetime.strptime(timestamp_str[:14], "%Y%m%d%H%M%S")
                        else:
                            branch_date = datetime.strptime(timestamp_str[:8], "%Y%m%d")

                        if branch_date < cutoff:
                            # Delete the branch
                            delete_result = subprocess.run(
                                ["git", "branch", "-D", branch],
                                cwd=self.aragora_path,
                                capture_output=True,
                                text=True,
                            )
                            if delete_result.returncode == 0:
                                result["deleted"] += 1
                                self._log(f"  [cleanup] Deleted old branch: {branch}")
                            else:
                                result["errors"].append(
                                    f"Failed to delete {branch}: {delete_result.stderr}"
                                )
                        else:
                            result["preserved"] += 1
                    else:
                        # Can't parse date, preserve by default
                        result["preserved"] += 1

                except ValueError:
                    # Date parsing failed, preserve the branch
                    result["preserved"] += 1
                except Exception as e:
                    result["errors"].append(f"Error processing {branch}: {e}")

            if result["deleted"] > 0:
                self._log(f"  [cleanup] Cleaned up {result['deleted']} old failed branches")

        except Exception as e:
            result["errors"].append(f"Branch cleanup failed: {e}")

        return result

    def _format_successful_patterns(self, limit: int = 5) -> str:
        """Format successful critique patterns for prompt injection.

        This retrieves patterns from the CritiqueStore that have led to
        successful fixes in previous debates.
        """
        if not hasattr(self, "critique_store") or not self.critique_store:
            return ""

        try:
            patterns = self.critique_store.retrieve_patterns(min_success=2, limit=limit)
            if not patterns:
                return ""

            lines = ["## SUCCESSFUL PATTERNS (from past debates)"]
            lines.append("These critique patterns have worked well before:\n")

            for p in patterns:
                lines.append(f"- **{p.issue_type}**: {p.issue_text}")
                if p.suggestion_text:
                    lines.append(f"  → Fix: {p.suggestion_text}")
                lines.append(f"  ({p.success_count} successes)")

            return "\n".join(lines)
        except Exception:
            return ""

    def _format_failure_patterns(self, limit: int = 5) -> str:
        """Format failure patterns to avoid repeating mistakes.

        Uses Titans/MIRAS failure tracking to show patterns that have
        NOT worked well, so agents can avoid repeating them.
        """
        if not hasattr(self, "critique_store") or not self.critique_store:
            return ""

        try:
            # Query patterns with high failure rates
            conn = self.critique_store.conn if hasattr(self.critique_store, "conn") else None
            if not conn:
                import sqlite3

                conn = sqlite3.connect(self.critique_store.db_path)

            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT issue_type, issue_text, failure_count, success_count
                FROM patterns
                WHERE failure_count > 0
                ORDER BY failure_count DESC
                LIMIT ?
                """,
                (limit,),
            )
            failures = cursor.fetchall()

            if not failures:
                return ""

            lines = ["## PATTERNS TO AVOID (learned from past failures)"]
            lines.append("These approaches have NOT worked well:\n")

            for issue_type, issue_text, fail_count, success_count in failures:
                success_rate = (
                    success_count / (success_count + fail_count)
                    if (success_count + fail_count) > 0
                    else 0
                )
                if success_rate < 0.5:  # Only show patterns with <50% success
                    lines.append(f"- **{issue_type}**: {issue_text}")
                    lines.append(f"  ({fail_count} failures, {success_rate:.0%} success rate)")

            return "\n".join(lines) if len(lines) > 2 else ""
        except Exception:
            return ""

    def _record_failure_patterns(self, test_output: str, design_context: str = "") -> None:
        """
        Record failure patterns for learning using structured error taxonomy.

        Extracts test failures and categorizes them for future avoidance.
        Uses scripts.nomic.error_taxonomy for structured pattern tracking.

        Args:
            test_output: Raw pytest output showing failures
            design_context: The design that led to these failures
        """
        if not hasattr(self, "critique_store") or not self.critique_store:
            return

        try:
            # Use error taxonomy to extract structured failures
            if _NOMIC_PACKAGE_AVAILABLE:
                from scripts.nomic.error_taxonomy import extract_test_failures

                failures = extract_test_failures(test_output)
            else:
                # Fallback: simple regex extraction
                import re

                failures = []
                for match in re.finditer(r"FAILED\s+([\w/]+\.py)::([\w\[\]]+)", test_output):
                    failures.append(
                        {"file": match.group(1), "test": match.group(2), "type": "assertion"}
                    )

            if not failures:
                return

            # Get database connection
            conn = self.critique_store.conn if hasattr(self.critique_store, "conn") else None
            if not conn:
                import sqlite3

                conn = sqlite3.connect(self.critique_store.db_path)

            cursor = conn.cursor()

            # Ensure patterns table exists
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY,
                    issue_type TEXT,
                    issue_text TEXT,
                    file_path TEXT,
                    failure_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    last_seen TEXT,
                    design_context TEXT
                )
            """
            )

            # Record each failure
            now = datetime.now().isoformat()
            for failure in failures:
                file_path = failure.get("file", "")
                test_name = failure.get("test", "")
                failure_type = failure.get("type", "unknown")

                # Check if pattern exists
                cursor.execute(
                    "SELECT id, failure_count FROM patterns WHERE issue_type = ? AND issue_text = ?",
                    (failure_type, test_name),
                )
                existing = cursor.fetchone()

                if existing:
                    # Increment failure count
                    cursor.execute(
                        "UPDATE patterns SET failure_count = failure_count + 1, last_seen = ? WHERE id = ?",
                        (now, existing[0]),
                    )
                else:
                    # Insert new pattern
                    cursor.execute(
                        """INSERT INTO patterns (issue_type, issue_text, file_path, failure_count, last_seen, design_context)
                           VALUES (?, ?, ?, 1, ?, ?)""",
                        (
                            failure_type,
                            test_name,
                            file_path,
                            now,
                            design_context[:500] if design_context else "",
                        ),
                    )

            conn.commit()
            self._log(f"  [learning] Recorded {len(failures)} failure patterns")

        except Exception as e:
            logger.warning(f"Failed to record failure patterns: {e}")

    def _format_continuum_patterns(self, limit: int = 5) -> str:
        """Format patterns from ContinuumMemory for prompt injection.

        Retrieves strategic patterns from the SLOW tier that capture
        successful cycle outcomes and learnings across time.
        """
        if not self.continuum or not CONTINUUM_AVAILABLE:
            return ""

        try:
            # Get recent successful patterns from SLOW tier
            memories = self.continuum.export_for_tier(MemoryTier.SLOW)
            if not memories:
                return ""

            # Filter to successful patterns and sort by importance
            successful = [m for m in memories if m.get("metadata", {}).get("success", False)]
            successful = sorted(successful, key=lambda x: x.get("importance", 0), reverse=True)[
                :limit
            ]

            if not successful:
                return ""

            lines = ["## STRATEGIC PATTERNS (from ContinuumMemory)"]
            lines.append("Successful patterns learned across cycles:\n")

            for m in successful:
                content = m.get("content", "")
                cycle = m.get("metadata", {}).get("cycle", "?")
                lines.append(f"- Cycle {cycle}: {content}")

            return "\n".join(lines)
        except Exception:
            return ""

    def _format_consensus_history(self, topic: str, limit: int = 3) -> str:
        """Format prior consensus decisions for prompt injection (P1: ConsensusMemory).

        Retrieves similar past debates and their conclusions to avoid
        rehashing settled topics and to surface unaddressed dissents.
        """
        if not self.consensus_memory or not CONSENSUS_MEMORY_AVAILABLE:
            return ""

        try:
            # Find similar past debates
            similar = self.consensus_memory.find_similar_debates(topic, limit=limit)
            if not similar:
                return ""

            lines = ["## HISTORICAL CONSENSUS (from past debates)"]
            lines.append("Previous debates on similar topics:\n")

            for s in similar:
                strength = s.consensus.strength.value if s.consensus.strength else "unknown"
                lines.append(
                    f"- **{s.consensus.topic}** ({strength}, {s.similarity_score:.0%} similar)"
                )
                lines.append(f"  Decision: {s.consensus.conclusion}")
                if s.dissents:
                    lines.append(f"  ⚠️ {len(s.dissents)} dissenting view(s) - consider addressing")

            # Add unaddressed dissents if any
            if self.dissent_retriever:
                context = self.dissent_retriever.retrieve_for_new_debate(topic)
                if context.get("unacknowledged_dissents"):
                    lines.append("\n### Unaddressed Historical Concerns")
                    for d in context["unacknowledged_dissents"][:3]:
                        lines.append(f"- [{d['dissent_type']}] {d['content']}")

                # Add contrarian views - alternative perspectives to consider
                contrarian = self.dissent_retriever.find_contrarian_views(topic, limit=3)
                if contrarian:
                    lines.append("\n### Contrarian Perspectives (Devil's Advocate)")
                    for c in contrarian:
                        lines.append(f"- {c.content} (from {c.agent_id})")

                # Add risk warnings - historical edge cases and concerns
                risks = self.dissent_retriever.find_risk_warnings(topic, limit=3)
                if risks:
                    lines.append("\n### Historical Risk Warnings")
                    for r in risks:
                        lines.append(f"- ⚠️ {r.content}")

            return "\n".join(lines)
        except Exception as e:
            self._log(f"  [consensus] Error formatting history: {e}")
            return ""

    async def _get_pulse_topic_context(self, limit: int = 3) -> str:
        """Get trending topic context to inform debate priorities (Pulse integration).

        Retrieves trending topics from social platforms that may be relevant
        to aragora improvements (e.g., AI safety, multi-agent systems, LLM trends).
        """
        if not self.pulse_manager or not PULSE_AVAILABLE:
            return ""

        try:
            # Fetch trending topics (async)
            trending = await self.pulse_manager.get_trending_topics(
                limit_per_platform=limit,
                filters={
                    "skip_toxic": True,
                    "categories": ["tech", "ai", "programming", "science"],
                },
            )

            if not trending:
                return ""

            # Filter for topics relevant to aragora/AI development
            relevant_keywords = [
                "ai",
                "llm",
                "gpt",
                "claude",
                "agent",
                "multi-agent",
                "debate",
                "consensus",
                "reasoning",
                "safety",
                "alignment",
                "model",
                "api",
                "developer",
                "code",
                "programming",
            ]

            relevant_topics = [
                t for t in trending if any(kw in t.topic.lower() for kw in relevant_keywords)
            ][:3]

            if not relevant_topics:
                return ""

            lines = ["## TRENDING CONTEXT (from Pulse)"]
            lines.append("Current AI/tech trends that may inform improvement priorities:\n")

            for topic in relevant_topics:
                lines.append(f"- **{topic.topic}** ({topic.platform}, {topic.volume} engagement)")
                if topic.category:
                    lines.append(f"  Category: {topic.category}")

            lines.append(
                "\nConsider how aragora improvements could address or leverage these trends."
            )

            self._log(f"  [pulse] Injected {len(relevant_topics)} trending topics")
            return "\n".join(lines)

        except Exception as e:
            self._log(f"  [pulse] Error fetching trending topics: {e}")
            return ""

    def _get_structured_topic(self) -> tuple[str, "Issue"]:
        """Get a specific, scoped improvement topic from issue backlog.

        Instead of asking "what should we improve?", scans the codebase for
        concrete issues and selects one to focus the debate on.

        Returns:
            Tuple of (task_string, Issue) or (fallback_task, None)
        """
        if not _ISSUE_GENERATOR_AVAILABLE:
            self._log("  [topics] IssueGenerator not available, using fallback")
            return None, None

        try:
            # Generate issues from codebase
            generator = IssueGenerator(self.aragora_path)
            issues = generator.scan_for_issues()

            if not issues:
                self._log("  [topics] No issues found in codebase")
                return None, None

            # Load history of previously attempted issues
            history = load_issue_history(self.nomic_dir)
            selector = IssueSelector(issues, history)

            # Select next unworked issue
            issue = selector.select_next()
            if not issue:
                self._log("  [topics] All issues have been attempted, resetting backlog")
                # All issues worked - get a fresh scan but don't use history
                issue = issues[0] if issues else None
                if not issue:
                    return None, None

            self._log(f"  [topics] Selected issue: {issue.title}")
            self._log(
                f"  [topics] Category: {issue.category}, Priority: {issue.priority}, Complexity: {issue.complexity}"
            )

            # Build structured task prompt
            task = f"""{SAFETY_PREAMBLE}

## Issue to Address: {issue.title}

**Category**: {issue.category}
**Complexity**: {issue.complexity}
**Files likely involved**: {", ".join(issue.file_hints[:5])}

### Problem Description
{issue.description}

### Your Task
Design a solution for this **specific issue**. Focus on:
1. Root cause analysis - why does this problem exist?
2. Minimal change - what's the smallest fix that fully addresses it?
3. Verification - how do we confirm the fix works?

**IMPORTANT**: Do NOT propose unrelated improvements. Stay focused on this issue.
All agents should propose solutions to **this specific problem**.

After debate, reach consensus on the best approach to fix this issue.
"""
            return task, issue

        except Exception as e:
            self._log(f"  [topics] Error generating structured topic: {e}")
            return None, None

    def _save_issue_outcome(self, issue: "Issue", outcome: str) -> None:
        """Record the outcome of working on an issue."""
        if not _ISSUE_GENERATOR_AVAILABLE or not issue:
            return

        try:
            save_issue_attempt(self.nomic_dir, issue, outcome, self.cycle_count)
            self._log(f"  [topics] Recorded issue outcome: {outcome}")
        except Exception as e:
            self._log(f"  [topics] Failed to save issue outcome: {e}")

    async def _bridge_to_decision_plan(
        self,
        debate_result: dict,
        impl_result: dict,
        verify_result: dict,
    ) -> None:
        """Bridge nomic loop outcome to DecisionPlan for organizational learning.

        This is a best-effort integration - failures are logged but do not
        affect the nomic loop execution.
        """
        try:
            from aragora.pipeline.decision_plan import (
                DecisionPlanFactory,
                PlanOutcome,
                PlanStatus,
                record_plan_outcome,
            )
            from aragora.core_types import DebateResult

            # Create a minimal DebateResult from the debate dict
            dr = DebateResult(
                debate_id=f"nomic-cycle-{self.cycle_count}",
                task=debate_result.get("task", f"Nomic improvement cycle {self.cycle_count}"),
                final_answer=debate_result.get("final_answer", ""),
                confidence=debate_result.get("confidence", 0.5),
                consensus_reached=debate_result.get("consensus_reached", False),
                rounds_used=debate_result.get("rounds_used", 1),
            )

            # Create DecisionPlan (will generate risk register, verification plan)
            plan = DecisionPlanFactory.from_debate_result(
                dr,
                approval_mode="never",  # Nomic loop handles its own approval
                metadata={"source": "nomic_loop", "cycle": self.cycle_count},
            )

            # Mark as executed since nomic loop already ran implementation
            plan.status = (
                PlanStatus.COMPLETED if verify_result.get("all_passed") else PlanStatus.FAILED
            )
            plan.execution_started_at = datetime.now()
            plan.execution_completed_at = datetime.now()

            # Create outcome
            files_modified = impl_result.get("files_modified", [])
            test_results = verify_result.get("test_results", {})
            passed = test_results.get("passed", 0)
            total = passed + test_results.get("failed", 0) + test_results.get("errors", 0)

            outcome = PlanOutcome(
                plan_id=plan.id,
                debate_id=plan.debate_id,
                task=plan.task,
                success=verify_result.get("all_passed", False),
                tasks_completed=len(files_modified) if files_modified else 1,
                tasks_total=len(files_modified) if files_modified else 1,
                verification_passed=passed,
                verification_total=total if total > 0 else 1,
                total_cost_usd=self._estimated_cost_usd,
                lessons=[f"Nomic cycle {self.cycle_count}: {plan.task[:100]}"],
            )

            # Record to memory (best-effort)
            try:
                from aragora.memory.continuum import ContinuumMemory

                cm = ContinuumMemory()
                await record_plan_outcome(plan, outcome, continuum_memory=cm)
                self._log(f"  [decision-plan] Recorded outcome to memory: plan={plan.id[:8]}")
            except Exception as mem_err:
                self._log(f"  [decision-plan] Memory write skipped: {mem_err}")

        except ImportError:
            pass  # DecisionPlan not available
        except Exception as e:
            self._log(f"  [decision-plan] Bridge skipped: {e}")

    def _calculate_proposal_alignment(self, proposals: dict[str, str]) -> float:
        """Calculate semantic alignment between proposals using Jaccard similarity.

        Returns a value between 0 (completely different) and 1 (identical).
        Uses word overlap as a fast, API-free approximation.

        Args:
            proposals: Dict mapping agent name to proposal text

        Returns:
            Average pairwise Jaccard similarity score
        """
        if len(proposals) < 2:
            return 1.0

        def tokenize(text: str) -> set[str]:
            """Extract significant words from text."""
            import re

            # Lowercase and extract words
            words = re.findall(r"\b\w+\b", text.lower())
            # Filter out very short words and common stop words
            stop_words = {
                "the",
                "a",
                "an",
                "is",
                "are",
                "was",
                "were",
                "be",
                "been",
                "being",
                "have",
                "has",
                "had",
                "do",
                "does",
                "did",
                "will",
                "would",
                "could",
                "should",
                "may",
                "might",
                "must",
                "shall",
                "can",
                "need",
                "to",
                "of",
                "in",
                "for",
                "on",
                "with",
                "at",
                "by",
                "from",
                "as",
                "into",
                "through",
                "during",
                "before",
                "after",
                "above",
                "below",
                "between",
                "under",
                "again",
                "further",
                "then",
                "once",
                "here",
                "there",
                "when",
                "where",
                "why",
                "how",
                "all",
                "each",
                "few",
                "more",
                "most",
                "other",
                "some",
                "such",
                "no",
                "nor",
                "not",
                "only",
                "own",
                "same",
                "so",
                "than",
                "too",
                "very",
                "just",
                "and",
                "but",
                "if",
                "or",
                "because",
                "until",
                "while",
                "although",
                "this",
                "that",
                "these",
                "those",
                "it",
                "its",
                "we",
                "you",
                "they",
                "them",
                "their",
                "what",
                "which",
                "who",
                "whom",
                "i",
                "me",
                "my",
            }
            return {w for w in words if len(w) >= 3 and w not in stop_words}

        def jaccard_similarity(set1: set, set2: set) -> float:
            """Calculate Jaccard similarity between two sets."""
            if not set1 or not set2:
                return 0.0
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            return intersection / union if union > 0 else 0.0

        # Get word sets for each proposal
        proposal_list = list(proposals.values())
        word_sets = [tokenize(p) for p in proposal_list]

        # Calculate pairwise similarities
        similarities = []
        for i in range(len(word_sets)):
            for j in range(i + 1, len(word_sets)):
                sim = jaccard_similarity(word_sets[i], word_sets[j])
                similarities.append(sim)

        avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0

        self._log(f"  [alignment] Proposal alignment score: {avg_similarity:.2f}")
        return avg_similarity

    def _get_judge_guidance(self, alignment: float, num_proposals: int) -> str:
        """Get appropriate judge guidance based on proposal alignment.

        When proposals are well-aligned, judge can simply pick the best.
        When proposals diverge, judge needs explicit synthesis instructions.
        """
        if alignment >= 0.6:
            return """
Select the BEST proposal based on:
1. Technical feasibility
2. Impact on the specific issue
3. Implementation simplicity
"""
        elif alignment >= 0.3:
            return """
The proposals address the issue differently. You should:

1. **IDENTIFY COMMON GROUND**: What elements do multiple proposals share?
2. **SYNTHESIZE**: Combine the best aspects into a unified approach
3. **PRIORITIZE**: Focus on the core fix, defer nice-to-haves

Produce a single, coherent design that addresses the original issue.
"""
        else:
            return """
CRITICAL: Proposals are highly divergent. You MUST take decisive action:

1. **SELECT ONE**: Choose the proposal that most directly addresses the root cause
2. **JUSTIFY**: Briefly explain why this approach wins
3. **DISCARD**: Explicitly reject approaches that add unnecessary complexity

DO NOT try to merge incompatible approaches. Pick a clear winner.
"""

    async def _store_debate_consensus(self, result, topic: str) -> None:
        """Store debate consensus for future reference (P1: ConsensusMemory).

        Records the consensus reached, participating agents, and any
        dissenting views for retrieval in future debates.
        """
        if not self.consensus_memory or not CONSENSUS_MEMORY_AVAILABLE:
            return

        try:
            if not result.consensus_reached:
                return

            # Determine consensus strength from confidence
            if result.confidence >= 0.95:
                strength = ConsensusStrength.UNANIMOUS
            elif result.confidence >= 0.8:
                strength = ConsensusStrength.STRONG
            elif result.confidence >= 0.6:
                strength = ConsensusStrength.MODERATE
            elif result.confidence >= 0.5:
                strength = ConsensusStrength.WEAK
            else:
                strength = ConsensusStrength.SPLIT

            # Get participating agents
            agents = [a.name for a in self._get_all_agents()]

            # Store the consensus (full content, no truncation)
            record = self.consensus_memory.store_consensus(
                topic=topic,
                conclusion=result.final_answer if result.final_answer else "",
                strength=strength,
                confidence=result.confidence,
                participating_agents=agents,
                agreeing_agents=agents,  # All participate in consensus
                domain="aragora_improvement",
                debate_duration=result.duration_seconds,
                rounds=result.rounds_used,
                metadata={"cycle": self.cycle_count},
            )

            self._log(f"  [consensus] Stored consensus: {strength.value} ({result.confidence:.0%})")

            # Store any dissenting views from the result
            dissenting = getattr(result, "dissenting_views", [])
            for i, view in enumerate(dissenting):
                from aragora.memory.consensus import DissentType

                self.consensus_memory.store_dissent(
                    debate_id=record.id,
                    agent_id=f"agent_{i}",
                    dissent_type=DissentType.ALTERNATIVE_APPROACH,
                    content=view,
                    reasoning="Minority view from debate",
                    confidence=0.5,
                )

        except Exception as e:
            self._log(f"  [consensus] Error storing: {e}")

    def _record_calibration_from_debate(
        self, result, agents: list, domain: str = "general"
    ) -> None:
        """Record calibration data from debate votes/predictions.

        Tracks how well agents' confidence aligns with actual outcomes.
        An agent's vote confidence vs whether consensus was reached indicates
        calibration quality.
        """
        if not self.calibration_tracker or not CALIBRATION_AVAILABLE:
            return

        try:
            consensus_reached = result.consensus_reached
            debate_id = getattr(result, "debate_id", f"debate-{self.cycle_count}")

            # Get agent votes if available
            votes = getattr(result, "votes", {})
            if not votes:
                # Fallback: use result confidence as proxy for all agents
                for agent in agents:
                    agent_name = agent.name if hasattr(agent, "name") else str(agent)
                    # Agent "predicted" consensus would happen with result.confidence
                    confidence = result.confidence if consensus_reached else 0.5
                    self.calibration_tracker.record_prediction(
                        agent=agent_name,
                        confidence=confidence,
                        correct=consensus_reached,
                        domain=domain,
                        debate_id=debate_id,
                    )
                return

            # Use actual vote data if available
            for agent_name, vote_data in votes.items():
                if isinstance(vote_data, dict):
                    confidence = vote_data.get("confidence", 0.5)
                    # Was their vote aligned with the outcome?
                    correct = consensus_reached if confidence >= 0.5 else not consensus_reached
                else:
                    confidence = float(vote_data) if vote_data else 0.5
                    correct = consensus_reached

                self.calibration_tracker.record_prediction(
                    agent=agent_name,
                    confidence=confidence,
                    correct=correct,
                    domain=domain,
                    debate_id=debate_id,
                )

            self._log(f"  [calibration] Recorded {len(votes)} agent predictions")

        except Exception as e:
            self._log(f"  [calibration] Error recording: {e}")

    def _record_suggestion_feedback(
        self,
        result,
        debate_id: str,
        suggestions_injected: list = None,
    ) -> None:
        """Record audience suggestion effectiveness after debate completion.

        Tracks whether debates with audience suggestions achieved consensus
        and updates contributor reputation scores accordingly.
        """
        if not self.suggestion_tracker or not SUGGESTION_FEEDBACK_AVAILABLE:
            return

        try:
            # Record outcome for any suggestions that were injected
            updated = self.suggestion_tracker.record_outcome(
                debate_id=debate_id,
                consensus_reached=result.consensus_reached,
                consensus_confidence=result.confidence,
                duration_seconds=getattr(result, "duration_seconds", 0.0),
            )

            if updated > 0:
                self._log(f"  [suggestions] Updated {updated} suggestion(s) with outcome")

                # Log effectiveness stats periodically
                if self.cycle_count % 10 == 0:
                    stats = self.suggestion_tracker.get_effectiveness_stats()
                    if stats.get("total_suggestions", 0) > 0:
                        self._log(
                            f"  [suggestions] Overall stats: {stats['total_suggestions']} suggestions, "
                            f"{stats['avg_effectiveness']:.0%} avg effectiveness"
                        )

        except Exception as e:
            self._log(f"  [suggestions] Error recording feedback: {e}")

    def _record_suggestion_injection(
        self,
        debate_id: str,
        clusters: list,
    ) -> list[str]:
        """Record which suggestions were injected into a debate.

        Args:
            debate_id: Unique debate identifier
            clusters: List of SuggestionCluster objects

        Returns:
            List of injection IDs for tracking
        """
        if not self.suggestion_tracker or not SUGGESTION_FEEDBACK_AVAILABLE:
            return []

        try:
            injection_ids = self.suggestion_tracker.record_injection(debate_id, clusters)
            if injection_ids:
                self._log(
                    f"  [suggestions] Recorded {len(injection_ids)} suggestion cluster(s) for tracking"
                )
            return injection_ids
        except Exception as e:
            self._log(f"  [suggestions] Error recording injection: {e}")
            return []

    async def _extract_and_store_insights(self, result) -> None:
        """Extract and store insights from debate result (P2: InsightExtractor).

        Analyzes the debate to extract patterns, agent performances,
        and key takeaways to feed into learning systems.
        """
        if not self.insight_extractor or not INSIGHTS_AVAILABLE:
            return

        try:
            # Extract insights from the debate result
            insights = await self.insight_extractor.extract(result)

            self._log(
                f"  [insights] Extracted {insights.total_insights} insights: {insights.key_takeaway}"
            )

            # Persist insights to InsightStore database (debate consensus feature)
            if self.insight_store and insights:
                try:
                    stored = await self.insight_store.store_debate_insights(insights)
                    self._log(f"  [insights] Persisted {stored} insights to database")
                except Exception as e:
                    self._log(f"  [insights] Persistence error: {e}")

            # Feed key takeaway to ContinuumMemory for long-term learning
            if self.continuum and insights.key_takeaway:
                self.continuum.add(
                    id=f"insight-{self.cycle_count}-debate",
                    content=insights.key_takeaway,
                    tier=MemoryTier.MEDIUM,
                    importance=(
                        insights.consensus_insight.confidence if insights.consensus_insight else 0.5
                    ),
                    metadata={
                        "type": "debate_insight",
                        "cycle": self.cycle_count,
                        "consensus_reached": insights.consensus_reached,
                    },
                )

            # Update agent reputations based on extracted performances
            if self.critique_store and insights.agent_performances:
                for perf in insights.agent_performances:
                    # Update reputation with more detailed metrics
                    self.critique_store.update_reputation(
                        perf.agent_name,
                        proposal_made=perf.proposals_made > 0,
                        proposal_accepted=perf.proposal_accepted,
                    )

            # Store pattern insights to ContinuumMemory if significant
            for pattern in insights.pattern_insights:
                if pattern.confidence > 0.7 and self.continuum:
                    self.continuum.add(
                        id=f"pattern-{self.cycle_count}-{pattern.id[:8]}",
                        content=f"Pattern: {pattern.title} - {pattern.description}",
                        tier=MemoryTier.SLOW,
                        importance=pattern.confidence,
                        metadata={
                            "type": "pattern_insight",
                            "cycle": self.cycle_count,
                            "category": pattern.metadata.get("category", "general"),
                        },
                    )

            # Persist insights to InsightStore for dashboard access (debate consensus feature)
            if self.insight_store and insights:
                try:
                    await self.insight_store.store_debate_insights(insights)
                    self._log(f"  [insights] Persisted {insights.total_insights} insights to store")
                except Exception as store_err:
                    self._log(f"  [insights] Store error: {store_err}")

        except Exception as e:
            self._log(f"  [insights] Error extracting: {e}")

    # =========================================================================
    # Phase 3 Helper Methods
    # =========================================================================

    def _format_agent_memories(self, agent_name: str, task: str, limit: int = 3) -> str:
        """Format per-agent relevant memories for prompt injection (P3: MemoryStream)."""
        if not self.memory_stream or not MEMORY_STREAM_AVAILABLE:
            return ""
        try:
            memories = self.memory_stream.retrieve(
                agent_name=agent_name, query=task[:200], limit=limit
            )
            if not memories:
                return ""
            lines = [f"## Your memories ({agent_name}):"]
            for m in memories:
                content = m.memory.content if hasattr(m, "memory") else str(m)
                lines.append(f"- {content}...")
            return "\n".join(lines)
        except Exception as e:
            self._log(f"  [memory] Error retrieving memories: {e}")
            return ""

    def _format_position_history(self, agent_name: str, topic: str, limit: int = 5) -> str:
        """Format recent positions for prompt injection (P9: PositionLedger read)."""
        if not self.position_ledger or not GROUNDED_PERSONAS_AVAILABLE:
            return ""
        try:
            positions = self.position_ledger.get_agent_positions(agent_name, limit=limit)
            if not positions:
                return ""

            lines = [f"## Your Recent Positions ({agent_name}):"]
            lines.append("Review these to maintain consistency or explain any changes:")

            reversed_count = sum(1 for p in positions if p.reversed)
            if reversed_count > 0:
                lines.append(
                    f"⚠️ You have reversed {reversed_count} position(s) recently. If changing stance, explain why."
                )

            for p in positions:
                status = ""
                if p.reversed:
                    status = " [REVERSED]"
                elif p.outcome == "correct":
                    status = " ✓"
                elif p.outcome == "incorrect":
                    status = " ✗"

                conf_pct = f"{p.confidence:.0%}" if p.confidence else "?"
                domain_str = f" [{p.domain}]" if p.domain else ""
                lines.append(f"- {p.claim[:80]}...{domain_str} (conf: {conf_pct}){status}")

            return "\n".join(lines)
        except Exception as e:
            self._log(f"  [positions] Error retrieving positions: {e}")
            return ""

    async def _retrieve_relevant_insights(self, topic: str, limit: int = 5) -> str:
        """Retrieve relevant past insights for debate context (P2: InsightStore)."""
        if not self.insight_store or not INSIGHTS_AVAILABLE:
            return ""
        try:
            lines = ["## Learnings from Past Debates"]

            # Get common patterns that recur across debates
            if hasattr(self.insight_store, "get_common_patterns"):
                patterns = await self.insight_store.get_common_patterns(min_occurrences=2, limit=3)
                if patterns:
                    lines.append("\n### Recurring Patterns:")
                    for p in patterns:
                        lines.append(f"- {p.get('pattern', '')} (seen {p.get('occurrences', 0)}x)")

            # Get recent insights
            if hasattr(self.insight_store, "get_recent_insights"):
                recent = await self.insight_store.get_recent_insights(limit=limit)
                if recent:
                    lines.append("\n### Recent Insights:")
                    for insight in recent[:3]:
                        insight_type = getattr(insight, "type", None)
                        type_str = (
                            insight_type.value
                            if hasattr(insight_type, "value")
                            else str(insight_type or "insight")
                        )
                        title = getattr(insight, "title", "")
                        desc = getattr(insight, "description", "")[:100]
                        lines.append(f"- [{type_str}] {title}: {desc}...")

            if len(lines) > 1:
                return "\n".join(lines)
            return ""
        except Exception as e:
            self._log(f"  [insights] Retrieval error: {e}")
            return ""

    async def _retrieve_similar_debates(self, topic: str, limit: int = 3) -> str:
        """Retrieve similar past debates for historical context."""
        if not self.debate_embeddings or not EMBEDDINGS_AVAILABLE:
            return ""
        try:
            if not hasattr(self.debate_embeddings, "find_similar_debates"):
                return ""

            similar = await self.debate_embeddings.find_similar_debates(
                query=topic[:200], limit=limit, min_similarity=0.7
            )
            if not similar:
                return ""

            lines = ["## Similar Past Debates"]
            for item in similar:
                if isinstance(item, dict):
                    debate_id = item.get("debate_id", "unknown")
                    excerpt = item.get("excerpt", "")[:300]
                    similarity = item.get("similarity", 0)
                elif isinstance(item, tuple) and len(item) >= 3:
                    debate_id, excerpt, similarity = item[0], item[1][:300], item[2]
                else:
                    continue
                lines.append(f"\n### {debate_id} (similarity: {similarity:.0%})")
                lines.append(excerpt + "..." if len(excerpt) >= 300 else excerpt)

            return "\n".join(lines) if len(lines) > 1 else ""
        except Exception as e:
            self._log(f"  [embeddings] Similar debate retrieval error: {e}")
            return ""

    async def _record_agent_memories(self, result, task: str) -> None:
        """Record observations to per-agent memory streams (P3: MemoryStream)."""
        if not self.memory_stream or not MEMORY_STREAM_AVAILABLE:
            return
        try:
            # Identify winning agents
            winning_agents = set()
            if result.final_answer:
                for agent in self._get_all_agents():
                    if agent.name.lower() in result.final_answer.lower():
                        winning_agents.add(agent.name)

            # Record each agent's observations
            for msg in result.messages:
                agent = getattr(msg, "agent", None)
                if not agent and isinstance(msg, dict):
                    agent = msg.get("agent")
                if agent:
                    importance = 0.7 if agent in winning_agents else 0.5
                    content = getattr(msg, "content", str(msg))
                    self.memory_stream.observe(
                        agent_name=agent,
                        content=f"Debated '{task}': {content}",
                        debate_id=f"cycle-{self.cycle_count}",
                        importance=importance,
                    )
            self._log(f"  [memory] Recorded {len(result.messages)} observations")
        except Exception as e:
            self._log(f"  [memory] Error recording: {e}")

    async def _gather_codebase_evidence(self, task: str, limit: int = 5) -> str:
        """Gather relevant evidence from codebase for debate context (P4: LocalDocsConnector)."""
        if not self.local_docs or not LOCAL_DOCS_AVAILABLE:
            return ""
        try:
            evidence = await self.local_docs.search(query=task[:200], limit=limit)
            if not evidence:
                return ""
            lines = ["## Relevant Codebase Evidence:"]
            for e in evidence:
                source = getattr(e, "source", "unknown")
                content = getattr(e, "content", str(e))
                lines.append(f"- [{source}]: {content}")
            return "\n".join(lines)
        except Exception as e:
            self._log(f"  [evidence] Error gathering: {e}")
            return ""

    async def _handle_debate_deadlock(self, result, arena, task: str):
        """Fork debate on disputed assumptions if deadlocked (P5: CounterfactualOrchestrator)."""
        if not self.counterfactual or not COUNTERFACTUAL_AVAILABLE:
            return result

        # Only handle if actually deadlocked
        if result.consensus_reached and result.confidence >= 0.5:
            return result

        try:
            # Find pivot claim from dissenting views
            pivot = await self.counterfactual.detect_pivot_claim(result)
            if not pivot or not pivot.should_branch:
                return result

            self._log(f"  [counterfactual] Forking on: {pivot.statement}")

            # Fork into branches
            branches = await self.counterfactual.fork_on_claim(
                arena=arena, pivot_claim=pivot, parent_result=result
            )

            # Synthesize conditional consensus
            conditional = await self.counterfactual.synthesize_branches(branches)
            self._log(f"  [counterfactual] Conditional consensus: {conditional.summary}")

            # Update result with conditional consensus
            result.final_answer = conditional.summary
            result.consensus_reached = True
            result.confidence = conditional.confidence
            if not hasattr(result, "metadata") or result.metadata is None:
                result.metadata = {}
            result.metadata["conditional"] = True
            result.metadata["branches"] = len(branches)

            return result
        except Exception as e:
            self._log(f"  [counterfactual] Error: {e}")
            return result

    async def _run_agent_for_probe(self, agent, prompt: str) -> str:
        """Run an agent with a probe prompt, handling errors gracefully.

        Used by CapabilityProber to execute probes against agents.
        """
        try:
            response = await self._call_agent_with_retry(agent, prompt, max_retries=1)
            return response if response else "[No response]"
        except Exception as e:
            self._log(f"  [prober] Agent {agent.name} probe failed: {e}")
            return f"[Error: {e}]"

    async def _probe_agent_capabilities(self) -> None:
        """Run capability probes on agents to detect weaknesses (P6: CapabilityProber).

        Now runs every 2 cycles (was every 5) for better agent quality tracking.
        """
        if not self.prober or not PROBER_AVAILABLE:
            return
        if self.cycle_count % 2 != 0:  # Run every 2 cycles for faster feedback
            return

        try:
            self._log("  [prober] Running capability probes...")
            agents = self._get_all_agents()

            for agent in agents:
                if agent is None:
                    continue

                # Create a closure to capture the current agent
                async def run_fn(prompt: str, _agent=agent) -> str:
                    return await self._run_agent_for_probe(_agent, prompt)

                report = await self.prober.probe_agent(
                    target_agent=agent,
                    run_agent_fn=run_fn,
                    probe_types=[ProbeType.CONTRADICTION, ProbeType.HALLUCINATION],
                    probes_per_type=2,  # Reduced for speed
                )
                if report and report.vulnerabilities_found > 0:
                    self._log(
                        f"  [prober] {agent.name}: {report.vulnerabilities_found} vulnerabilities found"
                    )
                    # Log detailed findings
                    if hasattr(report, "findings") and report.findings:
                        for finding in report.findings[:3]:  # Top 3
                            desc = getattr(finding, "description", str(finding))[:100]
                            self._log(f"    - {desc}")
        except Exception as e:
            self._log(f"  [prober] Error: {e}")

    def _select_debate_template(self, task: str):
        """Select appropriate debate template based on task content (P7: DebateTemplates)."""
        if not TEMPLATES_AVAILABLE:
            return None
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["code review", "review code", "pr review"]):
            return CODE_REVIEW_TEMPLATE
        if any(kw in task_lower for kw in ["design", "architecture", "rfc"]):
            return DESIGN_DOC_TEMPLATE
        return None  # Use default debate format

    def _apply_template_to_protocol(self, protocol, template) -> None:
        """Modify protocol based on template settings (P7: DebateTemplates)."""
        if template and hasattr(template, "max_rounds"):
            protocol.rounds = min(protocol.rounds, template.max_rounds)
            if hasattr(template, "consensus_threshold"):
                # Store threshold for later use
                protocol.consensus_threshold = template.consensus_threshold
            self._log(f"  [template] Using {template.name}")

    # =========================================================================
    # Phase 4 Helper Methods: Agent Evolution Mechanisms
    # =========================================================================

    def _init_agent_personas(self) -> None:
        """Initialize or load personas for all agents (P8: PersonaManager)."""
        if not self.persona_manager or not PERSONAS_AVAILABLE:
            return
        try:
            for agent in self._get_all_agents():
                persona = get_or_create_persona(self.persona_manager, agent.name)
                top_exp = persona.top_expertise[:2] if persona.top_expertise else []
                self._log(f"  [persona] {agent.name}: {persona.trait_string}, top: {top_exp}")
        except Exception as e:
            self._log(f"  [persona] Error initializing: {e}")

    def _record_persona_performance(self, result, task: str) -> None:
        """Update persona expertise based on debate outcome (P8: PersonaManager)."""
        if not self.persona_manager or not PERSONAS_AVAILABLE:
            return
        try:
            # Detect domain from task
            task_lower = task.lower()
            domain = None
            for d in EXPERTISE_DOMAINS:
                if d in task_lower:
                    domain = d
                    break
            if not domain:
                domain = "architecture"  # default

            # Track unique agents that participated
            participating_agents = set()
            for msg in result.messages:
                agent = getattr(msg, "agent", None) or (
                    msg.get("agent") if isinstance(msg, dict) else None
                )
                if agent:
                    participating_agents.add(agent)

            # Record performance for each unique agent
            success = result.consensus_reached and result.confidence >= 0.6
            for agent_name in participating_agents:
                self.persona_manager.record_performance(
                    agent_name=agent_name,
                    domain=domain,
                    success=success,
                    debate_id=f"cycle-{self.cycle_count}",
                )
            self._log(
                f"  [persona] Recorded performance in {domain} for {len(participating_agents)} agents"
            )
        except Exception as e:
            self._log(f"  [persona] Error: {e}")

    def _get_persona_context(self, agent_name: str) -> str:
        """Get persona context for injection into agent prompts (P8: PersonaManager)."""
        if not self.persona_manager or not PERSONAS_AVAILABLE:
            return ""
        try:
            persona = self.persona_manager.get_persona(agent_name)
            if persona:
                return persona.to_prompt_context()
            return ""
        except Exception:
            return ""

    async def _extract_and_store_patterns(self, result) -> None:
        """Extract winning patterns from successful debates (P9: PromptEvolver)."""
        if not self.prompt_evolver or not EVOLVER_AVAILABLE:
            return
        if not result.consensus_reached or result.confidence < 0.6:
            return  # Only learn from successful debates
        try:
            patterns = self.prompt_evolver.extract_winning_patterns([result])
            if patterns:
                self.prompt_evolver.store_patterns(patterns)
                self._log(f"  [evolver] Extracted {len(patterns)} patterns from debate")
        except Exception as e:
            self._log(f"  [evolver] Error extracting patterns: {e}")

    async def _evolve_agent_prompts(self) -> None:
        """Evolve agent prompts based on accumulated patterns (P9: PromptEvolver)."""
        if not self.prompt_evolver or not EVOLVER_AVAILABLE:
            return
        if self.cycle_count % 10 != 0:  # Run every 10 cycles
            return

        try:
            self._log("  [evolver] Evolving agent prompts...")
            patterns = self.prompt_evolver.get_top_patterns(limit=5)
            if not patterns:
                self._log("  [evolver] No patterns accumulated yet")
                return

            for agent in self._get_all_agents():
                if hasattr(agent, "system_prompt") and agent.system_prompt:
                    self.prompt_evolver.apply_evolution(agent, patterns)
                    version = self.prompt_evolver.get_prompt_version(agent.name)
                    if version:
                        self._log(f"  [evolver] {agent.name}: Evolved to v{version.version}")
        except Exception as e:
            self._log(f"  [evolver] Error evolving prompts: {e}")

    def _update_prompt_performance(self, agent_name: str, result) -> None:
        """Update performance metrics for current prompt version (P9: PromptEvolver)."""
        if not self.prompt_evolver or not EVOLVER_AVAILABLE:
            return
        try:
            version = self.prompt_evolver.get_prompt_version(agent_name)
            if version:
                self.prompt_evolver.update_performance(agent_name, version.version, result)
        except Exception:
            pass

    async def _run_tournament_if_due(self) -> None:
        """Run a tournament to benchmark agents if interval reached (P10: Tournament)."""
        if not TOURNAMENT_AVAILABLE or not Tournament:
            return
        if self.cycle_count - self.last_tournament_cycle < self.tournament_interval:
            return

        try:
            self._log(f"\n=== TOURNAMENT (Cycle {self.cycle_count}) ===")
            agents = self._get_all_agents()
            tasks = create_default_tasks()[:3]  # Use 3 tasks for speed

            tournament = Tournament(
                name=f"Cycle-{self.cycle_count}-Tournament",
                agents=agents,
                tasks=tasks,
                format=TournamentFormat.FREE_FOR_ALL,
                db_path=str(self.nomic_dir / "tournaments.db"),
            )

            # Define debate runner for tournament
            async def run_tournament_debate(env, debate_agents):
                arena = Arena(
                    environment=env,  # Required first parameter
                    agents=debate_agents,
                    protocol=DebateProtocol(
                        rounds=3,
                        role_rotation=True,
                        role_rotation_config=RoleRotationConfig(
                            enabled=True,
                            roles=[
                                CognitiveRole.ANALYST,
                                CognitiveRole.SKEPTIC,
                                CognitiveRole.ADVOCATE,
                            ],
                        ),
                    ),
                    position_tracker=self.position_tracker,
                    calibration_tracker=self.calibration_tracker,
                    event_hooks=self._create_arena_hooks("tournament"),
                    event_emitter=self.stream_emitter,
                    loop_id=self.loop_id,
                    persona_manager=self.persona_manager,
                    relationship_tracker=self.relationship_tracker,
                    moment_detector=self.moment_detector,
                    continuum_memory=self.continuum,
                    use_airlock=True,  # Enable resilience wrapper
                    # Cross-pollination components (v2.0.3)
                    debate_strategy=self.debate_strategy,
                    cross_debate_memory=self.cross_debate_memory,
                    enable_adaptive_rounds=self.debate_strategy is not None,
                )
                return await arena.run()  # run() takes no arguments

            result = await tournament.run(run_tournament_debate, parallel=False)
            self.last_tournament_cycle = self.cycle_count

            # Log standings
            self._log(f"  [tournament] Champion: {result.champion}")
            for i, standing in enumerate(result.standings[:4]):
                self._log(
                    f"  [tournament] #{i + 1} {standing.agent_name}: {standing.points}pts, {standing.win_rate:.0%} win rate"
                )

            # Update persona expertise based on tournament performance
            if self.persona_manager and PERSONAS_AVAILABLE:
                for standing in result.standings:
                    for task in tasks:
                        self.persona_manager.record_performance(
                            agent_name=standing.agent_name,
                            domain=task.domain,
                            success=standing.win_rate > 0.5,
                            debate_id=f"tournament-{self.cycle_count}",
                        )
        except Exception as e:
            self._log(f"  [tournament] Error: {e}")

    # =========================================================================
    # Phase 5 Helper Methods: Efficiency, Process Feedback, Agent Ranking
    # =========================================================================

    def _check_debate_convergence(
        self, current_responses: dict, previous_responses: dict, round_number: int
    ):
        """Check if debate has converged and can stop early (P11: ConvergenceDetector)."""
        if not self.convergence_detector or not CONVERGENCE_AVAILABLE:
            return None
        try:
            result = self.convergence_detector.check_convergence(
                current_responses, previous_responses, round_number
            )
            if result and result.converged:
                self._log(
                    f"  [convergence] Debate converged! "
                    f"(avg similarity: {result.avg_similarity:.0%})"
                )
            return result
        except Exception as e:
            self._log(f"  [convergence] Error: {e}")
            return None

    def _analyze_debate_process(self, result):
        """Analyze debate process for issues and recommendations (P12: MetaCritiqueAnalyzer)."""
        if not self.meta_analyzer or not META_CRITIQUE_AVAILABLE:
            return None
        try:
            critique = self.meta_analyzer.analyze(result)
            self._log(f"  [meta] Debate quality: {critique.overall_quality:.0%}")

            # P5-Phase2: Cache observations and quality for reflection injection
            self._last_meta_quality = critique.overall_quality
            if critique.observations:
                issues = [o for o in critique.observations if o.observation_type == "issue"]
                if issues:
                    self._log(f"  [meta] Issues found: {len(issues)}")
                    self._cached_meta_observations = issues[:5]  # Cache top 5 issues
                    # Log warning if quality is low
                    if critique.overall_quality < 0.6:
                        self._log("  [meta] ⚠️ LOW QUALITY: Reflection needed")

            if critique.recommendations:
                self._log(f"  [meta] Top recommendation: {critique.recommendations[0]}")
            return critique
        except Exception as e:
            self._log(f"  [meta] Error: {e}")
            return None

    def _format_meta_observations(self) -> str:
        """Format cached meta-critique observations for injection (P5-Phase2: MetaCritique Reflection)."""
        if not self._cached_meta_observations or self._last_meta_quality >= 0.6:
            return ""  # Only inject observations when quality was low
        try:
            lines = ["=== PROCESS REFLECTION (from previous debate) ==="]
            lines.append("The previous debate had the following issues to avoid:\n")
            for i, obs in enumerate(self._cached_meta_observations[:3], 1):
                desc = getattr(obs, "description", str(obs))
                lines.append(f"{i}. {desc}")
            lines.append("\nPlease actively avoid these anti-patterns in this debate.")
            return "\n".join(lines)
        except Exception:
            return ""

    def _store_meta_recommendations(self, critique) -> None:
        """Store meta-critique recommendations for future cycle improvement (P12)."""
        if not critique or not hasattr(critique, "recommendations") or not critique.recommendations:
            return
        # Store in ConsensusMemory as settled insight
        if self.consensus_memory and CONSENSUS_MEMORY_AVAILABLE and ConsensusStrength:
            try:
                for rec in critique.recommendations[:2]:
                    self.consensus_memory.store_consensus(
                        topic=f"process-recommendation-{self.cycle_count}",
                        conclusion=rec,
                        strength=ConsensusStrength.MODERATE,
                        confidence=critique.overall_quality,
                        participating_agents=["meta-critic"],
                        agreeing_agents=["meta-critic"],
                        domain="process-improvement",
                    )
            except Exception as e:
                self._log(f"  [meta] Error storing recommendations: {e}")

    def _detect_domain(self, task: str) -> str:
        """Detect task domain from content (P13: EloSystem helper)."""
        task_lower = task.lower()
        domains = ["security", "performance", "architecture", "testing", "error_handling"]
        for d in domains:
            if d in task_lower:
                return d
        return "general"

    def _agent_in_consensus(self, agent_name: str, result) -> bool:
        """Check if agent's position was part of winning consensus."""
        if not result.consensus_reached:
            return False
        # Check if agent voted for winning choice
        if hasattr(result, "votes"):
            for vote in result.votes:
                vote_agent = getattr(vote, "agent", None) or (
                    vote.get("agent") if isinstance(vote, dict) else None
                )
                vote_choice = getattr(vote, "choice", None) or (
                    vote.get("choice") if isinstance(vote, dict) else None
                )
                if vote_agent == agent_name:
                    if vote_choice and result.final_answer and vote_choice in result.final_answer:
                        return True
        return False

    def _extract_position_changes(self, result) -> dict[str, list[str]]:
        """Extract position changes from debate messages.

        Detects when an agent changes their position after another agent's message.
        Returns: {agent_who_changed: [agents_who_influenced_them]}
        """
        position_changes: dict[str, list[str]] = {}
        if not hasattr(result, "messages") or not result.messages:
            return position_changes

        try:
            last_speaker = None
            change_indicators = [
                "i agree with",
                "you're right",
                "that's a good point",
                "i've reconsidered",
                "on reflection",
                "you've convinced me",
                "changing my position",
                "i now think",
                "fair point",
            ]

            for msg in result.messages:
                agent = getattr(msg, "agent", None) or (
                    msg.get("agent") if isinstance(msg, dict) else None
                )
                if not agent:
                    continue
                content = getattr(msg, "content", str(msg))[:500].lower()

                if any(ind in content for ind in change_indicators):
                    if last_speaker and last_speaker != agent:
                        if agent not in position_changes:
                            position_changes[agent] = []
                        if last_speaker not in position_changes[agent]:
                            position_changes[agent].append(last_speaker)
                last_speaker = agent
        except (AttributeError, TypeError) as e:
            logger.debug(f"[position-tracker] Parse error: {e}")
        return position_changes

    def _record_elo_match(self, result, task: str) -> None:
        """Record debate as ELO match to update agent ratings (P13: EloSystem)."""
        if not self.elo_system or not ELO_AVAILABLE:
            return
        try:
            # Extract participants from result
            participants = []
            agent_message_counts = {}
            for msg in result.messages:
                agent = getattr(msg, "agent", None) or (
                    msg.get("agent") if isinstance(msg, dict) else None
                )
                if agent:
                    if agent not in participants:
                        participants.append(agent)
                        agent_message_counts[agent] = 0
                    agent_message_counts[agent] += 1

            # Calculate differentiated scores based on contribution and outcome
            scores = {}
            final_answer = getattr(result, "final_answer", "") or ""

            # Extract vote tally to determine winner even without formal consensus
            vote_tally = {}
            vote_winner = None
            if hasattr(result, "votes") and result.votes:
                for v in result.votes:
                    choice = getattr(v, "choice", None)
                    if choice:
                        vote_tally[choice] = vote_tally.get(choice, 0) + 1
                if vote_tally:
                    vote_winner = max(vote_tally.items(), key=lambda x: x[1])[0]
                    self._log(f"  [elo] Vote tally: {vote_tally}, winner: {vote_winner}")

            # Also check result.winner if set by consensus phase
            declared_winner = getattr(result, "winner", None) or vote_winner

            for agent in participants:
                base_score = result.confidence if result.consensus_reached else 0.5

                # Winner bonus: Give significant boost to voted/declared winner
                # This ensures ELO differentiation even without formal consensus
                winner_bonus = 0.0
                if declared_winner:
                    if agent == declared_winner:
                        winner_bonus = 0.3  # Winner gets +0.3
                    elif agent in vote_tally:
                        # Proportional bonus based on votes received
                        total_votes = sum(vote_tally.values())
                        if total_votes > 0:
                            winner_bonus = 0.1 * (vote_tally.get(agent, 0) / total_votes)

                # Check if agent's content appears in final answer (indicates influence)
                agent_msgs = [
                    msg
                    for msg in result.messages
                    if (
                        getattr(msg, "agent", None)
                        or (msg.get("agent") if isinstance(msg, dict) else None)
                    )
                    == agent
                ]
                influence_bonus = 0.0
                for msg in agent_msgs:
                    content = getattr(msg, "content", "") or (
                        msg.get("content", "") if isinstance(msg, dict) else ""
                    )
                    # Check for content overlap with final answer (simple heuristic)
                    if content and final_answer:
                        # Find key phrases that match
                        words = set(content.lower().split())
                        final_words = set(final_answer.lower().split())
                        overlap = len(words & final_words)
                        if overlap > 5:  # More than 5 common words
                            influence_bonus = min(0.2, overlap * 0.01)
                            break

                # Activity bonus (more engaged agents)
                activity_bonus = min(0.1, agent_message_counts.get(agent, 0) * 0.02)

                # Combine scores with variance
                scores[agent] = min(
                    1.0, max(0.1, base_score + winner_bonus + influence_bonus + activity_bonus)
                )

            # Ensure score variance (critical for ELO changes)
            if len(set(scores.values())) == 1 and len(scores) > 1:
                # Add small random variance if all scores equal
                import random

                for agent in scores:
                    scores[agent] += random.uniform(-0.05, 0.05)
                    scores[agent] = min(1.0, max(0.1, scores[agent]))

            if len(participants) >= 2:
                domain = self._detect_domain(task)

                # Calculate confidence weight from probe results (P13: probe → ELO feedback)
                confidence_weight = 1.0
                if hasattr(self, "_last_probe_weights") and self._last_probe_weights:
                    weights = [self._last_probe_weights.get(p, 0.7) for p in participants]
                    confidence_weight = sum(weights) / len(weights) if weights else 1.0
                    self._log(f"  [elo] Confidence weight from probes: {confidence_weight:.2f}")

                changes = self.elo_system.record_match(
                    debate_id=f"cycle-{self.cycle_count}",
                    participants=participants,
                    scores=scores,
                    domain=domain,
                    confidence_weight=confidence_weight,
                )
                self._log(f"  [elo] Updated ratings for {len(participants)} agents in {domain}")
                self._log(f"  [elo] Scores: {scores}")
                self._log(f"  [elo] Changes: {changes}")

                # Determine winner based on scores (highest score wins)
                winner = max(scores, key=scores.get) if scores else None
                if winner:
                    self._log(f"  [elo] Winner: {winner} (score={scores.get(winner, 0):.2f})")
                self._stream_emit(
                    "on_match_recorded",
                    debate_id=f"cycle-{self.cycle_count}",
                    participants=participants,
                    elo_changes=changes,
                    domain=domain,
                    winner=winner,
                    loop_id=self.loop_id,
                )
        except Exception as e:
            self._log(f"  [elo] Error: {e}")

    def _log_elo_leaderboard(self) -> None:
        """Log current ELO leaderboard (P13: EloSystem)."""
        if not self.elo_system or not ELO_AVAILABLE:
            return
        if self.cycle_count % 5 != 0:  # Every 5 cycles
            return
        try:
            leaderboard = self.elo_system.get_leaderboard(limit=4)
            self._log("  [elo] === LEADERBOARD ===")
            for i, rating in enumerate(leaderboard):
                self._log(
                    f"  [elo] #{i + 1} {rating.agent_name}: {rating.elo:.0f} "
                    f"({rating.wins}W/{rating.losses}L)"
                )
        except (AttributeError, TypeError) as e:
            logger.debug(f"[elo] Leaderboard fetch failed: {e}")

    def _get_all_agents(self) -> list:
        agent_pool = getattr(self, "agent_pool", {})
        agents = [a for a in agent_pool.values() if a is not None]
        if agents:
            return agents
        return [
            a
            for a in [
                self.gemini,
                self.codex,
                self.claude,
                self.grok,
                self.deepseek,
                self.mistral,
                self.qwen,
                self.kimi,
            ]
            if a is not None
        ]

    def _select_debate_team(self, task: str, *, force_full_team: bool = False) -> list:
        """Select optimal agent team for the task (P14: AgentSelector + P10: ProbeFilter)."""
        agent_pool = getattr(self, "agent_pool", {})
        preferred_names = AgentSettings().default_agent_list
        ordered_agents = [
            agent_pool.get(name) for name in preferred_names if agent_pool.get(name) is not None
        ]
        if not ordered_agents:
            ordered_agents = [a for a in agent_pool.values() if a is not None]
        all_agents = ordered_agents

        # Single-agent mode for evaluation baselines
        if os.environ.get("NOMIC_SINGLE_AGENT", "0") == "1":
            target_name = os.environ.get("NOMIC_SINGLE_AGENT_NAME", "").strip()
            if target_name:
                for agent in all_agents:
                    if agent.name == target_name:
                        self._log(f"  [selector] Single-agent mode: {agent.name}")
                        return [agent]
                self._log(
                    f"  [selector] Single-agent target '{target_name}' not found, using first available"
                )
            if all_agents:
                self._log(f"  [selector] Single-agent mode: {all_agents[0].name}")
                return [all_agents[0]]
            self._log("  [selector] Single-agent mode: no agents available")
            return []

        # Filter out agents in circuit breaker cooldown
        default_team = []
        for agent in all_agents:
            if self.circuit_breaker.is_available(agent.name):
                default_team.append(agent)
            else:
                self._log(f"  [circuit-breaker] Skipping {agent.name} (in cooldown)")

        if len(default_team) < 2:
            self._log("  [circuit-breaker] WARNING: Not enough agents available, using all")
            default_team = all_agents  # Fall back to all agents if too few

        # Phase 10: Apply probe-aware filtering
        if self.probe_filter and PROBE_FILTER_AVAILABLE:
            try:
                # Get probe scores for weighted selection
                agent_names = [a.name for a in default_team]
                probe_scores = self.probe_filter.get_team_scores(agent_names)

                # Log probe status for visibility
                probed_agents = [n for n, s in probe_scores.items() if s != 1.0]
                if probed_agents:
                    self._log(
                        f"  [probe-filter] Probe scores: {[(n, f'{s:.0%}') for n, s in sorted(probe_scores.items(), key=lambda x: x[1], reverse=True)]}"
                    )

                # Filter out high-risk agents (>50% vulnerability rate)
                safe_names = self.probe_filter.filter_agents(
                    candidates=agent_names, max_vulnerability_rate=0.5, exclude_critical=True
                )

                if len(safe_names) >= 2:
                    filtered_team = [a for a in default_team if a.name in safe_names]
                    if len(filtered_team) < len(default_team):
                        excluded = [a.name for a in default_team if a.name not in safe_names]
                        self._log(f"  [probe-filter] Excluded high-risk agents: {excluded}")
                    default_team = filtered_team

                # Sort by probe score (higher is better)
                default_team.sort(key=lambda a: probe_scores.get(a.name, 1.0), reverse=True)

            except Exception as e:
                self._log(f"  [probe-filter] Error: {e}, using default selection")

        detected_domain = self._detect_domain(task)

        # If ELO available, sort by domain expertise first
        if self.elo_system and ELO_AVAILABLE:
            try:
                # Score agents by domain-specific performance
                domain_scores = []
                for agent in default_team:
                    best_domains = self.elo_system.get_best_domains(agent.name, limit=10)
                    domain_score = 0.0
                    for domain, score in best_domains:
                        if domain == detected_domain:
                            domain_score = score
                            break
                    overall_elo = self.elo_system.get_rating(agent.name).elo
                    # Enhanced: 70% domain expertise + 30% ELO when agent has proven domain knowledge
                    domain_weight = 0.7 if domain_score > 0.5 else 0.6
                    combined = (domain_score * domain_weight) + (
                        (overall_elo - 1400) / 200 * (1 - domain_weight)
                    )
                    domain_scores.append((agent, combined))
                domain_scores.sort(key=lambda x: x[1], reverse=True)
                # Use ELO-sorted team as the default
                default_team = [a for a, _ in domain_scores]
                self._log(
                    f"  [routing] Domain '{detected_domain}' ELO ranking: {[(a.name, f'{s:.2f}') for a, s in domain_scores]}"
                )
            except Exception as e:
                self._log(f"  [elo] Domain scoring failed: {e}")

        if force_full_team or not self.agent_selector or not SELECTOR_AVAILABLE:
            if force_full_team:
                self._log("  [selector] Full-team mode enabled (bypassing selector)")
            return default_team
        try:
            # Register agents with ELO ratings, probe scores, and calibration data
            for agent in default_team:
                # Get probe profile if available
                probe_score = 1.0
                has_critical = False
                if self.probe_filter and PROBE_FILTER_AVAILABLE:
                    try:
                        probe_profile = self.probe_filter.get_agent_profile(agent.name)
                        probe_score = probe_profile.probe_score
                        has_critical = probe_profile.has_critical_issues()
                    except Exception:
                        pass

                # Get calibration data if available
                calibration_score = 1.0
                brier_score = 0.0
                is_overconfident = False
                if self.calibration_tracker and CALIBRATION_AVAILABLE:
                    try:
                        cal_summary = self.calibration_tracker.get_calibration_summary(agent.name)
                        if cal_summary.total_predictions >= 5:
                            calibration_score = max(0.0, 1.0 - cal_summary.ece)
                            brier_score = cal_summary.brier_score
                            is_overconfident = cal_summary.is_overconfident
                    except Exception:
                        pass

                profile = AgentProfile(
                    name=agent.name,
                    agent_type=agent.model if hasattr(agent, "model") else agent.name,
                    elo_rating=(
                        self.elo_system.get_rating(agent.name).elo if self.elo_system else 1500
                    ),
                    probe_score=probe_score,
                    has_critical_probes=has_critical,
                    calibration_score=calibration_score,
                    brier_score=brier_score,
                    is_overconfident=is_overconfident,
                )
                self.agent_selector.register_agent(profile)

            requirements = TaskRequirements(
                task_id=f"cycle-{self.cycle_count}",
                description=task[:200],
                primary_domain=detected_domain,
                min_agents=3,
                max_agents=4,
                quality_priority=0.7,
                diversity_preference=0.5,
            )
            team = self.agent_selector.select_team(requirements)
            self._log(f"  [selector] Selected team: {[a.name for a in team.agents]}")
            # Map back to actual agent objects
            agent_map = {a.name: a for a in default_team}
            selected = [agent_map[p.name] for p in team.agents if p.name in agent_map]
            # Fallback to default team if selector returned empty list
            if not selected:
                self._log("  [selector] WARNING: Selector returned empty team, using default")
                return default_team
            return selected
        except Exception as e:
            self._log(f"  [selector] Error: {e}, using default team")
            return default_team

    def _inject_grounded_personas(self, agents: list) -> None:
        """Inject grounded identity prompts into agent system prompts (Phase 9: PersonaSynthesizer)."""
        if not self.persona_synthesizer or not GROUNDED_PERSONAS_AVAILABLE:
            return

        for agent in agents:
            try:
                # Get opponent names (other agents in the debate)
                opponent_names = [a.name for a in agents if a.name != agent.name]

                # Synthesize grounded identity prompt with full position history
                identity = self.persona_synthesizer.synthesize_identity_prompt(
                    agent_name=agent.name,
                    opponent_names=opponent_names,
                    include_sections=["performance", "calibration", "relationships", "positions"],
                )

                # Add opponent briefings for tactical intelligence
                briefings = []
                for opponent in opponent_names:
                    try:
                        briefing = self.persona_synthesizer.get_opponent_briefing(
                            agent.name, opponent
                        )
                        if briefing:
                            briefings.append(briefing)
                    except Exception:
                        pass  # Skip if briefing generation fails

                if identity or briefings:
                    # Combine identity and briefings
                    full_prompt = identity or ""
                    if briefings:
                        full_prompt += "\n\n## Opponent Intelligence\n" + "\n\n".join(briefings)

                    # Inject agent-specific memories (P3: MemoryStream)
                    try:
                        topic_hint = getattr(self, "initial_proposal", "") or "aragora improvement"
                        agent_memories = self._format_agent_memories(
                            agent.name, topic_hint[:200], limit=3
                        )
                        if agent_memories:
                            full_prompt += f"\n\n{agent_memories}"
                    except Exception as e:
                        self._log(f"  [memory] Injection failed for {agent.name}: {e}")

                    # Inject position history for consistency tracking (P9: PositionLedger read)
                    try:
                        topic_hint = getattr(self, "initial_proposal", "") or "aragora improvement"
                        position_history = self._format_position_history(
                            agent.name, topic_hint[:200], limit=5
                        )
                        if position_history:
                            full_prompt += f"\n\n{position_history}"
                    except Exception as e:
                        self._log(f"  [position] History injection failed for {agent.name}: {e}")

                    # Inject flip detection warnings (P9: FlipDetector integration)
                    try:
                        if self.flip_detector:
                            consistency = self.flip_detector.get_agent_consistency(agent.name)
                            if consistency.total_flips > 0:
                                flip_warning = "\n\n## Consistency Warning\n"
                                flip_warning += f"You have changed your position {consistency.total_flips} times.\n"
                                flip_warning += f"- Contradictions: {consistency.contradictions}\n"
                                flip_warning += f"- Retractions: {consistency.retractions}\n"
                                flip_warning += (
                                    f"Consistency score: {consistency.consistency_score:.0%}\n"
                                )
                                flip_warning += "Be mindful of intellectual consistency. Acknowledge past positions when changing."
                                full_prompt += flip_warning
                    except Exception as e:
                        self._log(f"  [flip] Warning injection failed for {agent.name}: {e}")

                    # Prepend identity to system prompt
                    original_prompt = getattr(agent, "system_prompt", "") or ""
                    agent.system_prompt = f"{full_prompt}\n\n{original_prompt}"
                    self._log(
                        f"  [personas] Injected grounded identity for {agent.name} with {len(briefings)} opponent briefings"
                    )
            except Exception as e:
                self._log(f"  [personas] Error injecting persona for {agent.name}: {e}")
                # Don't break debate on persona injection failure

    def _log_persona_insights(self) -> None:
        """Log grounded persona insights for visibility (Phase 9: PersonaSynthesizer)."""
        if not self.persona_synthesizer or not GROUNDED_PERSONAS_AVAILABLE:
            return

        self._log("  [personas] Agent insights:")
        agents = self._get_all_agents()
        for agent in agents:
            try:
                persona = self.persona_synthesizer.get_grounded_persona(agent.name)
                if persona:
                    self._log(
                        f"    {agent.name}: {persona.overall_calibration:.0%} calibration, "
                        f"{persona.position_accuracy:.0%} accuracy, "
                        f"{len(persona.rivals)} rivals"
                    )
            except Exception:
                pass

    def _log_grounded_persona_stats(self) -> None:
        """Log grounded persona data completeness for observability."""
        self._log("  [grounded] Data completeness:")

        # Position Ledger stats
        if self.position_ledger:
            try:
                stats = self.position_ledger.get_all_stats()
                total = stats.get("total", 0)
                agents = len(stats.get("by_agent", {}))
                self._log(f"    PositionLedger: {total} positions from {agents} agents")
            except Exception:
                self._log("    PositionLedger: unavailable")
        else:
            self._log("    PositionLedger: not initialized")

        # Relationship Tracker stats
        if self.relationship_tracker:
            try:
                count = self.relationship_tracker.get_relationship_count()
                self._log(f"    RelationshipTracker: {count} agent pairs tracked")
            except Exception:
                self._log("    RelationshipTracker: unavailable")
        else:
            self._log("    RelationshipTracker: not initialized")

        # Moment Detector stats
        if self.moment_detector:
            try:
                count = sum(len(m) for m in self.moment_detector._moment_cache.values())
                self._log(f"    MomentDetector: {count} significant moments recorded")
            except Exception:
                self._log("    MomentDetector: unavailable")
        else:
            self._log("    MomentDetector: not initialized")

        # Probe Filter stats
        if self.probe_filter:
            try:
                profiles = self.probe_filter.get_all_profiles()
                if profiles:
                    probed_count = len(profiles)
                    avg_score = sum(p.probe_score for p in profiles.values()) / probed_count
                    high_risk = sum(1 for p in profiles.values() if p.is_high_risk())
                    self._log(
                        f"    ProbeFilter: {probed_count} agents probed, "
                        f"{avg_score:.0%} avg score, {high_risk} high-risk"
                    )
                else:
                    self._log("    ProbeFilter: no probe data yet")
            except Exception:
                self._log("    ProbeFilter: unavailable")
        else:
            self._log("    ProbeFilter: not initialized")

        # ELO domain calibration stats
        if self.elo_system:
            try:
                agents = self._get_all_agents()
                for agent in agents:
                    cal = self.elo_system.get_domain_calibration(agent.name)
                    if cal and cal.get("total", 0) > 0:
                        self._log(
                            f"    {agent.name} calibration: {cal['total']} predictions, "
                            f"{cal['accuracy']:.0%} accuracy"
                        )
            except Exception:
                pass

    def _track_debate_risks(self, result, task: str) -> None:
        """Track risks from debates with low consensus or confidence (P15: RiskRegister)."""
        if not RISK_REGISTER_AVAILABLE:
            return
        # Only track if consensus is weak
        if result.consensus_reached and result.confidence >= 0.7:
            return
        try:
            import json

            risk_level = "high" if not result.consensus_reached else "medium"
            risk_entry = {
                "cycle": self.cycle_count,
                "task": task,
                "confidence": result.confidence,
                "consensus": result.consensus_reached,
                "level": risk_level,
            }
            risk_file = self.nomic_dir / "risk_register.jsonl"
            with open(risk_file, "a") as f:
                f.write(json.dumps(risk_entry) + "\n")
            self._log(f"  [risk] Tracked {risk_level} risk: low consensus on task")
        except Exception as e:
            self._log(f"  [risk] Error: {e}")

    # =========================================================================
    # Phase 6: Verifiable Reasoning & Robustness Testing Helper Methods
    # =========================================================================

    def _extract_claims_from_debate(self, result) -> None:
        """Extract typed claims from debate result and populate kernel (P16: ClaimsKernel)."""
        if not self.claims_kernel or not CLAIMS_KERNEL_AVAILABLE:
            return
        try:
            # Reset kernel for new debate
            self.claims_kernel = ClaimsKernel(debate_id=f"nomic-cycle-{self.cycle_count}")

            # Extract claims from messages
            for msg in result.messages:
                agent = getattr(msg, "agent", None) or (
                    msg.get("agent") if isinstance(msg, dict) else None
                )
                content = getattr(msg, "content", None) or (
                    msg.get("content", "") if isinstance(msg, dict) else ""
                )
                role = getattr(msg, "role", None) or (
                    msg.get("role", "proposer") if isinstance(msg, dict) else "proposer"
                )

                if not agent or not content:
                    continue

                claim_type = ClaimType.PROPOSAL if role == "proposer" else ClaimType.OBJECTION
                self.claims_kernel.add_claim(
                    statement=content[:500],
                    author=agent,
                    claim_type=claim_type,
                    confidence=result.confidence if result.consensus_reached else 0.5,
                )
            self._log(f"  [claims] Extracted {len(self.claims_kernel.claims)} claims")
        except Exception as e:
            self._log(f"  [claims] Error: {e}")

    def _analyze_claim_structure(self) -> dict:
        """Analyze the claim structure for insights (P16: ClaimsKernel)."""
        if not self.claims_kernel or not CLAIMS_KERNEL_AVAILABLE:
            return {}
        try:
            unsupported = self.claims_kernel.find_unsupported_claims()
            contradictions = self.claims_kernel.find_contradictions()
            strongest = self.claims_kernel.get_strongest_claims(3)
            coverage = self.claims_kernel.get_evidence_coverage()

            self._log(
                f"  [claims] Unsupported: {len(unsupported)}, "
                f"Contradictions: {len(contradictions)}, "
                f"Coverage: {coverage['coverage_ratio']:.0%}"
            )

            return {
                "unsupported_count": len(unsupported),
                "contradiction_count": len(contradictions),
                "strongest_claims": [(c.statement, s) for c, s in strongest],
                "evidence_coverage": coverage,
            }
        except Exception as e:
            self._log(f"  [claims] Analysis error: {e}")
            return {}

    def _record_evidence_provenance(self, content: str, source_type: str, source_id: str) -> str:
        """Record evidence with provenance tracking (P17: ProvenanceManager)."""
        if not self.provenance_manager or not PROVENANCE_AVAILABLE:
            return ""
        try:
            source = (
                SourceType.AGENT_GENERATED if source_type == "agent" else SourceType.CODE_ANALYSIS
            )
            # Store full content, no truncation
            record = self.provenance_manager.record_evidence(
                content=content, source_type=source, source_id=source_id
            )
            return record.id
        except Exception as e:
            self._log(f"  [provenance] Error: {e}")
            return ""

    def _link_claims_to_evidence(self, claims: list[dict], debate_id: str) -> list[str]:
        """Link extracted claims to evidence with provenance tracking.

        Creates a provenance chain: Claim → Evidence → Source
        Returns list of evidence IDs for linking to subsequent phases.
        """
        if not self.provenance_manager or not PROVENANCE_AVAILABLE:
            return []

        evidence_ids = []
        try:
            for claim in claims[:10]:  # Limit to 10 claims per debate
                claim_text = claim.get("claim", "")
                priority = claim.get("priority", "medium")

                # Record the claim as evidence
                source_type = SourceType.AGENT_GENERATED
                record = self.provenance_manager.record_evidence(
                    content=claim_text,
                    source_type=source_type,
                    source_id=f"{debate_id}-claim",
                    metadata={"priority": priority, "debate_id": debate_id},
                )
                evidence_ids.append(record.id)

                # If we have citations for this claim, link them
                if self.citation_store and CITATION_GROUNDING_AVAILABLE:
                    existing_citations = self.citation_store.find_for_claim(claim_text, limit=3)
                    for citation in existing_citations:
                        self.provenance_manager.cite_evidence(
                            claim_id=record.id,
                            evidence_id=citation.id,
                            relevance=citation.relevance_score,
                            support_type="supports",
                            citation_text=citation.excerpt[:200] if citation.excerpt else "",
                        )

            if evidence_ids:
                self._log(f"  [provenance] Linked {len(evidence_ids)} claims to evidence chain")

        except Exception as e:
            self._log(f"  [provenance] Claim linking error: {e}")

        return evidence_ids

    def _build_phase_provenance(
        self, phase: str, content: str, parent_ids: list[str] = None
    ) -> str:
        """Build provenance chain from phase to phase.

        Tracks: Source → Claim → Design → Implementation
        Returns new evidence ID for chaining.
        """
        if not self.provenance_manager or not PROVENANCE_AVAILABLE:
            return ""

        try:
            if parent_ids:
                # Create synthesized evidence from multiple parent sources
                record = self.provenance_manager.synthesize_evidence(
                    parent_ids=parent_ids,
                    synthesized_content=content[:5000],  # Limit size
                    synthesizer_id=f"nomic-{phase}-{self.cycle_count}",
                )
            else:
                # Record as new evidence
                record = self.provenance_manager.record_evidence(
                    content=content[:5000],
                    source_type=SourceType.AGENT_GENERATED,
                    source_id=f"nomic-{phase}-{self.cycle_count}",
                )

            self._log(f"  [provenance] {phase} phase recorded: {record.id[:8]}...")
            return record.id

        except Exception as e:
            self._log(f"  [provenance] Phase recording error: {e}")
            return ""

    def _check_evidence_staleness(self, evidence_ids: list[str]) -> list[dict]:
        """Check if evidence is stale before implementation (P7: Staleness Detection).

        Returns list of stale evidence with details.
        """
        if not ENHANCED_PROVENANCE_AVAILABLE or not self.provenance_manager:
            return []

        stale_items = []
        try:
            if hasattr(self.provenance_manager, "check_staleness"):
                for evidence_id in evidence_ids[:20]:  # Limit checks
                    staleness = self.provenance_manager.check_staleness(evidence_id)
                    if staleness and staleness.get("is_stale", False):
                        stale_items.append(
                            {
                                "evidence_id": evidence_id,
                                "reason": staleness.get("reason", "Unknown"),
                                "age_hours": staleness.get("age_hours", 0),
                            }
                        )

            if stale_items:
                self._log(
                    f"  [provenance] WARNING: {len(stale_items)} stale evidence items detected"
                )
                for item in stale_items[:3]:
                    self._log(f"    - {item['evidence_id'][:8]}: {item['reason']}")

        except Exception as e:
            self._log(f"  [provenance] Staleness check error: {e}")

        return stale_items

    def _verify_evidence_chain(self) -> tuple:
        """Verify integrity of evidence chain (P17: ProvenanceManager)."""
        if not self.provenance_manager or not PROVENANCE_AVAILABLE:
            return True, []
        try:
            valid, errors = self.provenance_manager.verify_chain_integrity()
            if not valid:
                self._log(f"  [provenance] Chain integrity issues: {len(errors)}")
            return valid, errors
        except Exception as e:
            self._log(f"  [provenance] Verification error: {e}")
            return False, [str(e)]

    def _build_belief_network(self) -> None:
        """Build belief network from claims kernel (P18: BeliefNetwork)."""
        if not self.belief_network or not BELIEF_NETWORK_AVAILABLE:
            return
        if not self.claims_kernel or not CLAIMS_KERNEL_AVAILABLE:
            return
        try:
            self.belief_network = BeliefNetwork(debate_id=f"nomic-cycle-{self.cycle_count}")
            self.belief_network.from_claims_kernel(self.claims_kernel)
            result = self.belief_network.propagate()
            self._log(
                f"  [belief] Network built: {len(self.belief_network.nodes)} nodes, "
                f"converged={result.converged} after {result.iterations} iterations"
            )
        except Exception as e:
            self._log(f"  [belief] Error: {e}")

    def _identify_debate_cruxes(self) -> list:
        """Identify key claims that would most impact debate outcome (P18: BeliefNetwork)."""
        if not self.belief_network or not BELIEF_NETWORK_AVAILABLE:
            return []
        try:
            analyzer = BeliefPropagationAnalyzer(self.belief_network)
            cruxes = analyzer.identify_debate_cruxes(top_k=3)
            if cruxes:
                self._log(f"  [belief] Top crux: {cruxes[0]['statement']}")
                # P3-Phase2: Cache cruxes for injection into next debate
                self._cached_cruxes = cruxes
            return cruxes
        except Exception as e:
            self._log(f"  [belief] Crux analysis error: {e}")
            return []

    def _format_crux_context(self) -> str:
        """Format cached cruxes for injection into debate context (P3-Phase2: Crux-Fixing)."""
        if not self._cached_cruxes:
            return ""
        try:
            lines = ["=== PIVOTAL CLAIMS FROM PREVIOUS DEBATE ==="]
            lines.append("Focus on these high-impact questions that could swing the outcome:\n")
            for i, crux in enumerate(self._cached_cruxes[:3], 1):
                statement = crux.get("statement", crux.get("claim", "Unknown"))
                impact = crux.get("impact_score", crux.get("sensitivity", 0.0))
                lines.append(f"{i}. {statement}")
                if impact:
                    lines.append(f"   (Impact: {impact:.0%})")
            lines.append("\nAddressing these cruxes directly will accelerate consensus.")
            return "\n".join(lines)
        except Exception:
            return ""

    def _get_consensus_probability(self) -> dict:
        """Estimate probability of consensus based on belief network (P18: BeliefNetwork)."""
        if not self.belief_network or not BELIEF_NETWORK_AVAILABLE:
            return {"probability": 0.5}
        try:
            analyzer = BeliefPropagationAnalyzer(self.belief_network)
            return analyzer.compute_consensus_probability()
        except Exception:
            return {"probability": 0.5}

    async def _create_verification_proofs(self, result) -> int:
        """Create verification proofs for testable claims in debate result (P19: ProofExecutor)."""
        if not self.claim_verifier or not PROOF_EXECUTOR_AVAILABLE:
            return 0
        try:
            proof_count = 0
            # Look for code-related claims that can be verified
            final_answer = result.final_answer or ""
            if "```" in final_answer:
                # Extract code block
                code_start = final_answer.find("```")
                code_end = final_answer.find("```", code_start + 3)
                if code_end > code_start:
                    code_block = final_answer[code_start + 3 : code_end].strip()
                    # Skip language identifier if present
                    if "\n" in code_block:
                        first_line = code_block.split("\n")[0]
                        if first_line.strip().isalpha():
                            code_block = "\n".join(code_block.split("\n")[1:])

                    builder = ProofBuilder(
                        claim_id=f"cycle-{self.cycle_count}-final", created_by="nomic"
                    )
                    # Create syntax verification proof
                    proof = builder.assertion(
                        description="Verify proposed code is syntactically valid Python",
                        code=f"import ast\ncode = '''{code_block[:300]}'''\nast.parse(code)",
                        assertion="True",
                    )
                    self.claim_verifier.add_proof(proof)
                    proof_count += 1
            return proof_count
        except Exception as e:
            self._log(f"  [proofs] Proof creation error: {e}")
            return 0

    async def _run_verification_proofs(self):
        """Execute all pending verification proofs (P19: ProofExecutor)."""
        if not self.claim_verifier or not PROOF_EXECUTOR_AVAILABLE:
            return None
        try:
            results = await self.claim_verifier.verify_all()
            if not results:
                return None
            passed = sum(1 for r in results if r.passed)
            self._log(f"  [proofs] Verified {passed}/{len(results)} proofs passed")

            # Build report
            report = VerificationReport(debate_id=f"cycle-{self.cycle_count}")
            report.total_proofs = len(results)
            report.proofs_passed = passed
            report.proofs_failed = len(results) - passed
            return report
        except Exception as e:
            self._log(f"  [proofs] Verification error: {e}")
            return None

    async def _run_robustness_check(self, task: str, base_context: str = "") -> dict:
        """Run quick robustness check across key scenarios (P20: ScenarioMatrix).

        Now runs every cycle (was every 5) to catch edge cases before implementation.
        """
        if not SCENARIO_MATRIX_AVAILABLE:
            return {}
        try:
            self._log("  [scenarios] Running robustness check...")
            matrix = ScenarioMatrix.from_presets("risk")

            # Create lightweight debate function
            async def quick_debate(task_text, context):
                env = Environment(task=task_text, context=context)
                protocol = DebateProtocol(
                    rounds=1,
                    consensus="majority",
                    role_rotation=True,
                    role_rotation_config=RoleRotationConfig(
                        enabled=True,
                        roles=[CognitiveRole.ANALYST, CognitiveRole.SKEPTIC],
                    ),
                )
                agents = [self.gemini, self.claude] if hasattr(self, "claude") else [self.gemini]
                arena = Arena(
                    env,
                    agents,
                    protocol,
                    position_tracker=self.position_tracker,
                    calibration_tracker=self.calibration_tracker,
                    event_hooks=self._create_arena_hooks("scenario"),
                    event_emitter=self.stream_emitter,
                    loop_id=self.loop_id,
                    persona_manager=self.persona_manager,
                    relationship_tracker=self.relationship_tracker,
                    moment_detector=self.moment_detector,
                    continuum_memory=self.continuum,
                    use_airlock=True,  # Enable resilience wrapper
                    # Cross-pollination components (v2.0.3)
                    debate_strategy=self.debate_strategy,
                    cross_debate_memory=self.cross_debate_memory,
                    enable_adaptive_rounds=self.debate_strategy is not None,
                )
                return await arena.run()  # run() takes no arguments

            runner = MatrixDebateRunner(quick_debate, max_parallel=2)
            result = await runner.run_matrix(task, matrix, base_context)

            self._log(f"  [scenarios] Outcome: {result.outcome_category.value}")
            if result.universal_conclusions:
                self._log(
                    f"  [scenarios] Universal: {len(result.universal_conclusions)} conclusions"
                )

            return {
                "outcome": result.outcome_category.value,
                "scenarios_run": len(result.results),
                "universal_conclusions": result.universal_conclusions[:3],
            }
        except Exception as e:
            self._log(f"  [scenarios] Error: {e}")
            return {}

    # =========================================================================
    # Phase 7: Resilience, Living Documents, & Observability Helper Methods
    # =========================================================================

    def _record_code_evidence(
        self, file_path: str, line_start: int, line_end: int, content: str, claim_id: str = None
    ) -> str:
        """Record code evidence with git tracking for staleness detection (P21: EnhancedProvenance)."""
        if not ENHANCED_PROVENANCE_AVAILABLE or not self.provenance_manager:
            return ""
        try:
            # Enhanced provenance tracks git state for living document detection
            evidence_id = self.provenance_manager.record_code_evidence(
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                content=content,
                claim_id=claim_id,
            )
            self._log(f"  [provenance] Recorded code evidence: {file_path}:{line_start}-{line_end}")
            return evidence_id
        except Exception as e:
            self._log(f"  [provenance] Code evidence error: {e}")
            return ""

    async def _check_evidence_staleness(self) -> dict:
        """Check all evidence for staleness - are claims still valid? (P21: EnhancedProvenance)."""
        if not ENHANCED_PROVENANCE_AVAILABLE or not self.provenance_manager:
            return {}
        try:
            staleness_results = self.provenance_manager.check_all_staleness()
            fresh_count = sum(1 for s in staleness_results if s.status == StalenessStatus.FRESH)
            stale_count = sum(1 for s in staleness_results if s.status == StalenessStatus.STALE)

            if stale_count > 0:
                self._log(f"  [provenance] Staleness: {stale_count} stale, {fresh_count} fresh")
                # Generate revalidation triggers for stale evidence
                triggers = self.provenance_manager.generate_revalidation_triggers()
                if triggers:
                    self._log(f"  [provenance] Revalidation needed for {len(triggers)} items")

            return {
                "fresh": fresh_count,
                "stale": stale_count,
                "total": len(staleness_results),
                "living_status": self.provenance_manager.get_living_document_status(),
            }
        except Exception as e:
            self._log(f"  [provenance] Staleness check error: {e}")
            return {}

    async def _create_debate_checkpoint(
        self,
        debate_id: str,
        task: str,
        round_num: int,
        messages: list,
        agents: list,
        consensus: dict = None,
    ) -> str:
        """Create a checkpoint for crash recovery (P22: CheckpointManager)."""
        if not CHECKPOINT_AVAILABLE or not self.checkpoint_manager:
            return ""
        try:
            # Call create_checkpoint with individual parameters (it's async and creates the checkpoint internally)
            checkpoint = await self.checkpoint_manager.create_checkpoint(
                debate_id=debate_id,
                task=task,
                current_round=round_num,
                total_rounds=5,  # Default max rounds
                phase="debate",
                messages=messages,  # Pass Message objects directly
                critiques=[],
                votes=[],
                agents=agents,
                current_consensus=consensus.get("consensus") if consensus else None,
            )
            self._log(f"  [checkpoint] Created: {checkpoint.checkpoint_id[:8]}")
            return checkpoint.checkpoint_id
        except Exception as e:
            self._log(f"  [checkpoint] Create error: {e}")
            return ""

    async def _resume_from_checkpoint(self, checkpoint_id: str) -> dict:
        """Resume a debate from checkpoint (P22: CheckpointManager)."""
        if not CHECKPOINT_AVAILABLE or not self.checkpoint_manager:
            return {}
        try:
            resumed = self.checkpoint_manager.resume_from_checkpoint(checkpoint_id)
            if resumed:
                self._log(
                    f"  [checkpoint] Resumed: {resumed.original_debate_id} at round {resumed.checkpoint.current_round}"
                )
                return {
                    "debate_id": resumed.original_debate_id,
                    "task": resumed.checkpoint.task,
                    "round": resumed.checkpoint.current_round,
                    "messages": resumed.messages,  # Already deserialized Message objects
                    "consensus": resumed.checkpoint.current_consensus,
                }
            return {}
        except Exception as e:
            self._log(f"  [checkpoint] Resume error: {e}")
            return {}

    def _check_debate_breakpoints(
        self,
        debate_id: str,
        task: str,
        messages: list,
        confidence: float,
        round_num: int,
        critiques: list = None,
    ) -> "Breakpoint":
        """Check if debate triggers breakpoint for human review (P23: BreakpointManager)."""
        if not BREAKPOINT_AVAILABLE or not self.breakpoint_manager:
            return None
        try:
            # Build debate state for breakpoint checking
            debate_state = {
                "debate_id": debate_id,
                "task": task,
                "messages": messages,
                "confidence": confidence,
                "round": round_num,
                "critiques": critiques or [],
            }
            breakpoint = self.breakpoint_manager.check_triggers(debate_state)
            if breakpoint:
                self._log(f"  [breakpoint] Triggered: {breakpoint.trigger.value}")
            return breakpoint
        except Exception as e:
            self._log(f"  [breakpoint] Check error: {e}")
            return None

    async def _handle_breakpoint(self, breakpoint: "Breakpoint") -> "HumanGuidance":
        """Handle breakpoint by getting human guidance (P23: BreakpointManager)."""
        if not BREAKPOINT_AVAILABLE or not self.breakpoint_manager or not breakpoint:
            return None
        try:
            guidance = await self.breakpoint_manager.handle_breakpoint(breakpoint)
            if guidance:
                self._log(f"  [breakpoint] Human guidance: {guidance.action}")
            return guidance
        except Exception as e:
            self._log(f"  [breakpoint] Handle error: {e}")
            return None

    def _score_claim_reliability(self, claim_id: str, claim_text: str) -> dict:
        """Score reliability of a claim (P24: ReliabilityScorer)."""
        if not RELIABILITY_SCORER_AVAILABLE or not self.reliability_scorer:
            return {}
        try:
            # Get claim from claims kernel if available
            claim = None
            if CLAIMS_KERNEL_AVAILABLE and self.claims_kernel:
                claims = self.claims_kernel.get_claims()
                for c in claims:
                    if str(c.id) == claim_id:
                        claim = c
                        break

            if claim:
                reliability = self.reliability_scorer.score_claim(claim)
                return {
                    "claim_id": claim_id,
                    "level": (
                        reliability.level.value
                        if hasattr(reliability.level, "value")
                        else str(reliability.level)
                    ),
                    "score": reliability.score,
                    "factors": reliability.factors,
                }
            return {}
        except Exception as e:
            self._log(f"  [reliability] Score error: {e}")
            return {}

    def _generate_reliability_report(self) -> dict:
        """Generate reliability report for all claims (P24: ReliabilityScorer)."""
        if not RELIABILITY_SCORER_AVAILABLE or not self.reliability_scorer:
            return {}
        try:
            if not CLAIMS_KERNEL_AVAILABLE or not self.claims_kernel:
                return {}

            claims = self.claims_kernel.get_claims()
            if not claims:
                return {}

            # Convert list[TypedClaim] to dict[str, str] for reliability scorer
            claims_dict = {c.claim_id: c.statement for c in claims}
            report = self.reliability_scorer.generate_reliability_report(claims_dict)
            # report["claims"] is a dict of {claim_id: result_dict}, iterate .values()
            claims_results = report.get("claims", {})
            claims_list = (
                list(claims_results.values())
                if isinstance(claims_results, dict)
                else claims_results
            )
            high_reliability = sum(
                1 for c in claims_list if c.get("level") in ("VERY_HIGH", "HIGH")
            )
            low_reliability = sum(
                1 for c in claims_list if c.get("level") in ("VERY_LOW", "SPECULATIVE")
            )

            self._log(
                f"  [reliability] Report: {high_reliability} high, {low_reliability} low reliability"
            )
            return report
        except Exception as e:
            self._log(f"  [reliability] Report error: {e}")
            return {}

    def _start_debate_trace(self, debate_id: str, task: str, agents: list) -> None:
        """Start tracing a debate for audit logs (P25: DebateTracer)."""
        if not DEBATE_TRACER_AVAILABLE or not self.debate_trace_db:
            return
        try:
            agent_names = [a.name for a in agents if hasattr(a, "name")]
            # Create a new tracer for this debate
            self._current_tracer = DebateTracer(
                debate_id=debate_id, task=task, agents=agent_names, db_path=self.debate_trace_db
            )
            self._log(f"  [tracer] Started trace for debate {debate_id[:8]}")
        except Exception as e:
            self._current_tracer = None
            self._log(f"  [tracer] Start error: {e}")

    def _trace_event(self, event_type: str, content: str, agent: str = None) -> None:
        """Record an event to the debate trace (P25: DebateTracer)."""
        if not DEBATE_TRACER_AVAILABLE or not getattr(self, "_current_tracer", None):
            return
        try:
            # Use specialized record methods where available
            if event_type == "proposal" and agent:
                self._current_tracer.record_proposal(agent, content)
            elif event_type == "round_start":
                round_num = int(content) if content.isdigit() else 0
                self._current_tracer.start_round(round_num)
            elif event_type == "round_end":
                self._current_tracer.end_round()
            else:
                # Fallback to generic record
                type_map = {
                    "critique": EventType.AGENT_CRITIQUE if EventType else None,
                    "vote": EventType.AGENT_VOTE if EventType else None,
                    "consensus": EventType.CONSENSUS_REACHED if EventType else None,
                }
                event_enum = type_map.get(event_type)
                if event_enum:
                    self._current_tracer.record(event_enum, {"content": content}, agent=agent)
        except Exception as e:
            self._log(f"  [tracer] Event error: {e}")

    def _finalize_debate_trace(self, result: "DebateResult") -> str:
        """Finalize and save the debate trace (P25: DebateTracer)."""
        if not DEBATE_TRACER_AVAILABLE or not getattr(self, "_current_tracer", None):
            return ""
        try:
            # Build result dict for finalize
            result_dict = {
                "final_answer": getattr(result, "final_answer", ""),
                "consensus_reached": getattr(result, "consensus_reached", False),
                "confidence": getattr(result, "confidence", 0.0),
            }
            trace = self._current_tracer.finalize(result_dict)
            trace_id = trace.trace_id if trace else ""
            self._log(f"  [tracer] Finalized trace: {trace_id}")
            self._current_tracer = None  # Clear for next debate
            return trace_id
        except Exception as e:
            self._log(f"  [tracer] Finalize error: {e}")
            return ""

    # =========================================================================
    # Phase 8: Agent Evolution, Semantic Memory & Advanced Debates Helper Methods
    # =========================================================================

    def _run_persona_experiment(self, agent_name: str, variant_traits: list) -> str:
        """Create a persona A/B experiment (P26: PersonaLaboratory)."""
        if not PERSONA_LAB_AVAILABLE or not self.persona_lab:
            return ""
        try:
            experiment = self.persona_lab.create_experiment(
                agent_name=agent_name,
                variant_traits=variant_traits,
                hypothesis=f"Testing traits: {', '.join(variant_traits)}",
            )
            self._log(f"  [lab] Created experiment {experiment.experiment_id[:8]} for {agent_name}")
            return experiment.experiment_id
        except Exception as e:
            self._log(f"  [lab] Experiment creation error: {e}")
            return ""

    def _record_experiment_trial(self, experiment_id: str, is_control: bool, success: bool) -> None:
        """Record a trial result for an experiment (P26: PersonaLaboratory)."""
        if not PERSONA_LAB_AVAILABLE or not self.persona_lab or not experiment_id:
            return
        try:
            # Note: PersonaLaboratory uses is_variant (inverse of is_control)
            self.persona_lab.record_experiment_result(
                experiment_id=experiment_id,
                is_variant=not is_control,  # Invert: is_control -> is_variant
                success=success,
            )
        except Exception as e:
            self._log(f"  [lab] Trial recording error: {e}")

    def _detect_emergent_traits(self) -> list:
        """Detect emergent traits from performance patterns (P26: PersonaLaboratory)."""
        if not PERSONA_LAB_AVAILABLE or not self.persona_lab:
            return []
        try:
            traits = self.persona_lab.detect_emergent_traits()
            if traits:
                self._log(f"  [lab] Detected {len(traits)} emergent traits")
                for t in traits[:3]:
                    self._log(f"    - {t.trait_name} (confidence: {t.confidence:.2f})")
            return traits
        except Exception as e:
            self._log(f"  [lab] Trait detection error: {e}")
            return []

    def _cross_pollinate_traits(self, from_agent: str, to_agent: str, trait: str) -> bool:
        """Cross-pollinate a successful trait between agents (P26: PersonaLaboratory)."""
        if not PERSONA_LAB_AVAILABLE or not self.persona_lab:
            return False
        try:
            # cross_pollinate returns TraitTransfer or None
            transfer = self.persona_lab.cross_pollinate(
                from_agent=from_agent, to_agent=to_agent, trait=trait
            )
            if transfer:
                self._log(f"  [lab] Cross-pollinated '{trait}' from {from_agent} to {to_agent}")
                return True
            return False
        except Exception as e:
            self._log(f"  [lab] Cross-pollination error: {e}")
            return False

    async def _evolve_personas_post_cycle(self) -> dict:
        """Evolve personas based on cycle performance (P26: PersonaLaboratory)."""
        if not PERSONA_LAB_AVAILABLE or not self.persona_lab:
            return {}
        try:
            # Detect emergent traits
            emergent = self._detect_emergent_traits()

            # Proactively create experiments for low-performing agents (every 10 cycles)
            experiments_created = 0
            if self.cycle_count % 10 == 0 and self.elo_system:
                for agent_name in ["gemini", "claude", "codex", "grok"]:
                    try:
                        rating = self.elo_system.get_rating(agent_name)
                        if rating and rating.elo < 1450:
                            candidate_traits = ["analytical", "concise", "thorough", "skeptical"]
                            current = (
                                self.persona_lab.get_persona(agent_name)
                                if hasattr(self.persona_lab, "get_persona")
                                else None
                            )
                            current_traits = getattr(current, "traits", []) if current else []
                            new_traits = [t for t in candidate_traits if t not in current_traits][
                                :2
                            ]
                            if new_traits:
                                exp_id = self._run_persona_experiment(agent_name, new_traits)
                                if exp_id:
                                    experiments_created += 1
                    except Exception:
                        pass
                if experiments_created > 0:
                    self._log(
                        f"  [lab] Created {experiments_created} experiments for underperformers"
                    )

            # Check experiments for significant results and apply mutations
            experiments = self.persona_lab.get_running_experiments()
            completed = 0
            applied = 0
            for exp in experiments:
                if exp.is_significant:
                    self._log(
                        f"  [lab] Experiment {exp.experiment_id[:8]} significant: {exp.relative_improvement:+.1%}"
                    )
                    concluded = self.persona_lab.conclude_experiment(exp.experiment_id)
                    if concluded:
                        completed += 1
                        if concluded.variant_rate > concluded.control_rate:
                            self._log(
                                f"  [lab] Applied variant traits to {exp.agent_name}: {concluded.variant_persona.traits}"
                            )
                            applied += 1

            # Cross-pollinate successful traits between agents (every 20 cycles)
            traits_shared = 0
            if self.cycle_count % 20 == 0 and self.elo_system:
                try:
                    ratings = [
                        (a, self.elo_system.get_rating(a))
                        for a in ["gemini", "claude", "codex", "grok"]
                    ]
                    ratings = [(a, r.elo) for a, r in ratings if r]
                    if len(ratings) >= 2:
                        ratings.sort(key=lambda x: x[1], reverse=True)
                        best_agent, best_elo = ratings[0]
                        worst_agent, worst_elo = ratings[-1]
                        if best_elo - worst_elo > 100:
                            best_persona = (
                                self.persona_lab.get_persona(best_agent)
                                if hasattr(self.persona_lab, "get_persona")
                                else None
                            )
                            if best_persona and getattr(best_persona, "traits", []):
                                trait_to_share = best_persona.traits[0]
                                if self._cross_pollinate_traits(
                                    best_agent, worst_agent, trait_to_share
                                ):
                                    traits_shared += 1
                                    self._log(
                                        f"  [lab] Shared '{trait_to_share}' from {best_agent} to {worst_agent}"
                                    )
                except Exception as e:
                    self._log(f"  [lab] Cross-pollination error: {e}")

            return {
                "emergent_traits": len(emergent),
                "experiments_created": experiments_created,
                "experiments_checked": len(experiments),
                "significant_results": completed,
                "mutations_applied": applied,
                "traits_shared": traits_shared,
            }
        except Exception as e:
            self._log(f"  [lab] Evolution error: {e}")
            return {}

    async def _store_critique_embedding(self, critique_id: str, critique_text: str) -> None:
        """Store a critique embedding for future retrieval (P27: SemanticRetriever)."""
        if not SEMANTIC_RETRIEVER_AVAILABLE or not self.semantic_retriever:
            return
        try:
            await self.semantic_retriever.embed_and_store(critique_id, critique_text[:1000])
        except Exception as e:
            self._log(f"  [semantic] Store error: {e}")

    async def _find_similar_critiques(self, query: str, limit: int = 3) -> list:
        """Find similar past critiques (P27: SemanticRetriever)."""
        if not SEMANTIC_RETRIEVER_AVAILABLE or not self.semantic_retriever:
            return []
        try:
            results = await self.semantic_retriever.find_similar(query, limit=limit)
            if results:
                self._log(f"  [semantic] Found {len(results)} similar critiques")
            return results
        except Exception as e:
            self._log(f"  [semantic] Search error: {e}")
            return []

    async def _inject_similar_context(self, task: str) -> str:
        """Search and format similar past critiques as context (P27: SemanticRetriever)."""
        if not SEMANTIC_RETRIEVER_AVAILABLE or not self.semantic_retriever:
            return ""
        try:
            similar = await self._find_similar_critiques(task, limit=3)
            if not similar:
                return ""

            context_parts = ["=== SIMILAR PAST CRITIQUES ==="]
            for id_, text, sim in similar:
                context_parts.append(f"[Similarity: {sim:.2f}] {text}")

            return "\n".join(context_parts)
        except Exception as e:
            self._log(f"  [semantic] Context injection error: {e}")
            return ""

    async def _verify_claim_formally(self, claim_text: str, claim_type: str = "logical") -> dict:
        """Attempt formal verification of a claim (P28: FormalVerificationManager)."""
        if not FORMAL_VERIFICATION_AVAILABLE or not self.formal_verifier:
            return {}
        try:
            result = await self.formal_verifier.verify_claim(claim_text, claim_type)
            if result and result.is_verified:
                self._log(f"  [formal] Claim verified: {claim_text}")
            return result.to_dict() if result else {}
        except Exception as e:
            self._log(f"  [formal] Verification error: {e}")
            return {}

    def _is_formally_verifiable(self, claim_text: str) -> bool:
        """Check if a claim is suitable for formal verification (P28: FormalVerificationManager)."""
        # Simple heuristic: look for mathematical/logical keywords
        keywords = [
            "for all",
            "exists",
            "implies",
            "if and only if",
            "<=",
            ">=",
            "equals",
            "greater than",
            "less than",
            "always",
            "never",
        ]
        claim_lower = claim_text.lower()
        return any(kw in claim_lower for kw in keywords)

    def _record_formal_proof(self, claim_id: str, proof_result: dict) -> None:
        """Record a formal proof result (P28: FormalVerificationManager)."""
        if not proof_result:
            return
        try:
            # Store in provenance if available
            if self.provenance_manager and proof_result.get("is_verified"):
                self._record_evidence_provenance(
                    f"Formally verified: {proof_result.get('formal_statement', '')}",
                    source_type="formal_proof",
                    source_id=claim_id,
                )
        except Exception as e:
            self._log(f"  [formal] Proof recording error: {e}")

    def _create_debate_graph(self, debate_id: str, task: str) -> "DebateGraph":
        """Create a new debate graph (P29: DebateGraph)."""
        if not DEBATE_GRAPH_AVAILABLE or not DebateGraph:
            return None
        try:
            graph = DebateGraph(debate_id=debate_id, task=task)
            self._log(f"  [graph] Created debate graph {debate_id[:8]}")
            return graph
        except Exception as e:
            self._log(f"  [graph] Creation error: {e}")
            return None

    def _add_graph_node(
        self, graph: "DebateGraph", node_type: str, agent: str, content: str
    ) -> str:
        """Add a node to the debate graph (P29: DebateGraph)."""
        if not graph or not DEBATE_GRAPH_AVAILABLE:
            return ""
        try:
            node_type_enum = NodeType[node_type.upper()] if NodeType else None
            if not node_type_enum:
                return ""
            node = DebateNode(
                id=f"{agent}-{len(graph.nodes)}",
                node_type=node_type_enum,
                agent_id=agent,
                content=content,
            )
            graph.add_node(node)
            return node.id
        except Exception as e:
            self._log(f"  [graph] Add node error: {e}")
            return ""

    def _should_branch_graph(self, graph: "DebateGraph", disagreement_score: float) -> bool:
        """Check if graph should branch based on disagreement (P29: DebateGraph)."""
        if not graph or disagreement_score < 0.7:
            return False
        return True

    async def _run_graph_debate(self, task: str, agents: list) -> "DebateResult":
        """Run a graph-based debate (P29: DebateGraph)."""
        if not DEBATE_GRAPH_AVAILABLE or not self.graph_debate_enabled:
            return None
        try:
            self._log("  [graph] Running graph-based debate...")
            # Create orchestrator on demand with the specific agents
            orchestrator = GraphDebateOrchestrator(agents=agents)
            result = await orchestrator.run_debate(task)
            # Verify result has required DebateResult interface (consensus_reached, confidence)
            # GraphDebateOrchestrator is a placeholder - returns DebateGraph not DebateResult
            if not hasattr(result, "consensus_reached") or not hasattr(result, "confidence"):
                self._log("  [graph] Incomplete result - falling back to arena")
                return None
            return result
        except Exception as e:
            self._log(f"  [graph] Debate error: {e}")
            return None

    def _check_should_fork(self, messages: list, round_num: int, agents: list) -> "ForkDecision":
        """Check if debate should fork (P30: DebateForker)."""
        if not DEBATE_FORKER_AVAILABLE or not self.fork_debate_enabled:
            return None
        try:
            # Create detector on demand
            detector = ForkDetector()
            decision = detector.should_fork(messages, round_num, agents)
            if decision and hasattr(decision, "should_fork") and decision.should_fork:
                self._log(f"  [forking] Fork triggered: {getattr(decision, 'reason', 'unknown')}")
            return decision
        except Exception as e:
            self._log(f"  [forking] Check error: {e}")
            return None

    async def _run_forked_debate(
        self,
        fork_decision: "ForkDecision",
        env: "Environment",
        agents: list,
        protocol: "DebateProtocol",
        messages: list,
        round_num: int,
        debate_id: str,
        base_context: str,
    ) -> "MergeResult":
        """Run forked parallel debates (P30: DebateForker)."""
        if not DEBATE_FORKER_AVAILABLE or not self.fork_debate_enabled or not fork_decision:
            return None
        try:
            branches = getattr(fork_decision, "branches", [])
            if not branches:
                self._log("  [forking] No branches in fork decision")
                return None

            forker = DebateForker()
            created = forker.fork(
                parent_debate_id=debate_id,
                fork_round=round_num,
                messages_so_far=messages,
                decision=fork_decision,
            )
            if not created:
                self._log("  [forking] Forker created no branches")
                return None

            self._log(f"  [forking] Fork detected with {len(created)} branches")

            async def run_debate_fn(branch_env, branch_agents, initial_messages=None):
                branch_env.context = base_context
                agent_weights = getattr(self, "_last_probe_weights", {}) or {}
                branch_arena = Arena(
                    branch_env,
                    branch_agents,
                    protocol,
                    memory=self.critique_store,
                    debate_embeddings=self.debate_embeddings,
                    insight_store=self.insight_store,
                    agent_weights=agent_weights,
                    position_tracker=self.position_tracker,
                    position_ledger=self.position_ledger,
                    calibration_tracker=self.calibration_tracker,
                    elo_system=self.elo_system,
                    event_emitter=self.stream_emitter,
                    loop_id=self.loop_id,
                    event_hooks=self._create_arena_hooks("forked-debate"),
                    persona_manager=self.persona_manager,
                    relationship_tracker=self.relationship_tracker,
                    moment_detector=self.moment_detector,
                    continuum_memory=self.continuum,
                    use_airlock=True,
                    initial_messages=initial_messages or [],
                )
                return await self._run_arena_with_logging(branch_arena, "forked-debate")

            max_rounds = min(3, max(1, protocol.rounds))
            completed = await forker.run_branches(
                created,
                env,
                agents,
                run_debate_fn,
                max_rounds=max_rounds,
            )
            if not completed:
                self._log("  [forking] No branches completed")
                return None

            merge_result = forker.merge(completed)
            fork_points = forker.fork_points.get(debate_id, [])
            if fork_points:
                self._record_fork_outcome(fork_points[-1], merge_result)
            return merge_result
        except Exception as e:
            self._log(f"  [forking] Run error: {e}")
            return None

    def _record_fork_outcome(self, fork_point: "ForkPoint", merge_result: "MergeResult") -> None:
        """Record fork outcome for learning (P30: DebateForker)."""
        if not fork_point or not merge_result:
            return
        try:
            # Could store in provenance or insight extractor
            self._log(f"  [forking] Recorded outcome: {merge_result.winning_branch_id}")
        except Exception as e:
            self._log(f"  [forking] Record error: {e}")

    def _record_replay_event(
        self, event_type: str, agent: str, content: str, round_num: int = 0
    ) -> None:
        """Record an event to the ReplayRecorder if active."""
        if not self.replay_recorder:
            return
        try:
            if event_type == "turn":
                self.replay_recorder.record_turn(agent, content, round_num, self.loop_id)
            elif event_type == "vote":
                self.replay_recorder.record_vote(agent, content, "")
            elif event_type == "phase":
                self.replay_recorder.record_phase_change(content)
            elif event_type == "system":
                self.replay_recorder.record_system(content)
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(f"[replay] Event recording skipped: {e}")

    def _record_cartographer_event(
        self,
        event_type: str,
        agent: str,
        content: str,
        role: str = "proposer",
        round_num: int = 1,
        **kwargs,
    ) -> None:
        """Record an event to the ArgumentCartographer if active."""
        if not self.cartographer:
            return
        try:
            if event_type == "message":
                self.cartographer.update_from_message(
                    agent=agent,
                    content=content,
                    role=role,
                    round_num=round_num,
                    metadata=kwargs.get("metadata", {}),
                )
            elif event_type == "critique":
                self.cartographer.update_from_critique(
                    critic_agent=agent,
                    target_agent=kwargs.get("target", "unknown"),
                    severity=kwargs.get("severity", 0.5),
                    round_num=round_num,
                    critique_text=content,
                )
            elif event_type == "vote":
                self.cartographer.update_from_vote(
                    agent=agent, vote_value=content, round_num=round_num
                )
            elif event_type == "consensus":
                self.cartographer.update_from_consensus(
                    result=content, round_num=round_num, vote_counts=kwargs.get("vote_counts", {})
                )
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(f"[cartographer] Event recording skipped: {e}")

    def _dispatch_webhook(self, event_type: str, data: dict = None) -> None:
        """Dispatch an event to external webhooks if configured."""
        if not self.webhook_dispatcher:
            return
        try:
            event = {
                "type": event_type,
                "loop_id": self.loop_id,
                "cycle": self.cycle_count,
                "timestamp": datetime.now().isoformat(),
                "data": data or {},
            }
            self.webhook_dispatcher.enqueue(event)
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(f"[webhook] Event dispatch skipped: {e}")

    def _format_agent_reputations(self) -> str:
        """Format agent reputations for prompt injection.

        Shows which agents have been most successful so agents can
        weight their collaboration accordingly.
        """
        if not hasattr(self, "critique_store") or not self.critique_store:
            return ""

        try:
            reputations = self.critique_store.get_all_reputations()
            if not reputations:
                return ""

            lines = ["## AGENT TRACK RECORDS"]
            for rep in sorted(reputations, key=lambda r: r.score, reverse=True):
                if rep.proposals_made > 0:
                    acceptance = rep.proposals_accepted / rep.proposals_made
                    lines.append(
                        f"- {rep.agent_name}: {acceptance:.0%} proposal acceptance ({rep.proposals_accepted}/{rep.proposals_made})"
                    )

            return "\n".join(lines) if len(lines) > 1 else ""
        except Exception:
            return ""

    def _format_relationship_network(self, limit: int = 3) -> str:
        """Format agent relationship dynamics for debate context."""
        if not self.relationship_tracker or not GROUNDED_PERSONAS_AVAILABLE:
            return ""
        try:
            lines = ["## Inter-Agent Dynamics"]

            # Get influence network per agent
            agents = ["gemini", "claude", "codex", "grok"]
            if hasattr(self.relationship_tracker, "get_influence_network"):
                lines.append("\n### Influence Patterns:")
                influence_scores = []
                for agent in agents:
                    try:
                        network = self.relationship_tracker.get_influence_network(agent)
                        if network and network.get("influences"):
                            total_influence = sum(score for _, score in network["influences"])
                            influence_scores.append((agent, total_influence))
                    except Exception:
                        continue
                influence_scores.sort(key=lambda x: x[1], reverse=True)
                for agent, score in influence_scores[:limit]:
                    lines.append(f"- {agent}: influence score {score:.2f}")

            # Get rivals and allies for each agent
            dynamics_found = False
            for agent in agents:
                if hasattr(self.relationship_tracker, "get_rivals"):
                    rivals = self.relationship_tracker.get_rivals(agent, limit=2)
                    allies = (
                        self.relationship_tracker.get_allies(agent, limit=2)
                        if hasattr(self.relationship_tracker, "get_allies")
                        else []
                    )
                    if rivals or allies:
                        dynamics_found = True
                        rival_names = [r[0] for r in rivals] if rivals else []
                        ally_names = [a[0] for a in allies] if allies else []
                        lines.append(f"- {agent}: rivals={rival_names}, allies={ally_names}")

            return "\n".join(lines) if len(lines) > 1 and dynamics_found else ""
        except Exception as e:
            self._log(f"  [relationships] Formatting error: {e}")
            return ""

    def _audit_agent_calibration(self) -> str:
        """Audit agent calibration and flag poorly calibrated agents."""
        if not self.elo_system or not ELO_AVAILABLE:
            return ""
        try:
            lines = ["## Calibration Health Check"]
            flagged = []

            for agent_name in ["gemini", "claude", "codex", "grok"]:
                if hasattr(self.elo_system, "get_expected_calibration_error"):
                    ece = self.elo_system.get_expected_calibration_error(agent_name)
                    if ece and ece > 0.2:  # Poorly calibrated
                        flagged.append((agent_name, ece))
                        lines.append(
                            f"- WARNING: {agent_name} has high calibration error ({ece:.2f})"
                        )
                        lines.append("  Consider weighing their opinions lower on uncertain topics")

            if flagged:
                self._log(f"  [calibration] Flagged {len(flagged)} poorly calibrated agents")
                return "\n".join(lines)
            return ""
        except Exception as e:
            self._log(f"  [calibration] Audit error: {e}")
            return ""

    def _format_agent_introspection(self, agent_name: str) -> str:
        """Format agent self-awareness section for prompt injection.

        Uses IntrospectionAPI to provide agents with awareness of their
        own reputation, strengths, and track record.
        """
        if not INTROSPECTION_AVAILABLE or not get_agent_introspection:
            return ""

        try:
            snapshot = get_agent_introspection(
                agent_name,
                memory=self.critique_store,
                persona_manager=None,  # We don't have PersonaManager yet
            )
            return format_introspection_section(snapshot, max_chars=400)
        except Exception:
            return ""

    async def _parallel_implementation_review(self, diff: str) -> str | None:
        """
        All 3 agents review implementation changes in parallel.

        This provides balanced participation in the implementation stage
        while keeping the actual implementation specialized to Claude.

        Returns:
            Combined concerns from all agents, or None if all approve.
        """
        review_prompt = f"""Quick review of these code changes. Are there any obvious issues?

## Code Changes (git diff)
```
{diff[:10000]}
```

Reply with ONE of:
- APPROVED: <brief reason>
- CONCERN: <specific issue>

Be concise (1-2 sentences). Focus on correctness and safety issues only.
"""

        async def review_with_agent(agent, name: str) -> tuple[str, str]:
            """Run review with one agent, returning (name, result)."""
            try:
                self._log(f"    {name}: reviewing implementation...", agent=name)
                result = await agent.generate(review_prompt, context=[])
                self._log(f"    {name}: {result if result else 'No response'}", agent=name)
                # Emit full review
                if result:
                    self._stream_emit(
                        "on_log_message", result, level="info", phase="review", agent=name
                    )
                return (name, result if result else "No response")
            except Exception as e:
                self._log(f"    {name}: review error - {e}", agent=name)
                return (name, f"Error: {e}")

        # Run all 4 agents in parallel
        import asyncio

        reviews = await asyncio.gather(
            review_with_agent(self.gemini, "gemini"),
            review_with_agent(self.codex, "codex"),
            review_with_agent(self.claude, "claude"),
            review_with_agent(self.grok, "grok"),
            return_exceptions=True,
        )

        # Collect concerns
        concerns = []
        for result in reviews:
            if isinstance(result, Exception):
                continue
            name, response = result
            if response and "CONCERN" in response.upper():
                concerns.append(f"{name}: {response}")

        if concerns:
            return "\n".join(concerns)
        return None

    def _diff_touches_protected_files(self, diff: str) -> list[str]:
        """Check if a diff touches any protected files.

        Returns list of protected files that were modified.
        """
        touched_protected = []
        for protected_file in PROTECTED_FILES:
            # Check various diff patterns that indicate file modification
            patterns = [
                f"diff --git a/{protected_file}",
                f"--- a/{protected_file}",
                f"+++ b/{protected_file}",
                f"diff --git a/aragora/{protected_file.replace('aragora/', '')}",
            ]
            for pattern in patterns:
                if pattern in diff:
                    touched_protected.append(protected_file)
                    break
        return touched_protected

    def _should_use_deep_audit(self, topic: str, phase: str = "design") -> tuple[bool, str]:
        """Determine if a topic warrants deep audit mode.

        Returns:
            (should_use: bool, reason: str)
        """
        if not DEEP_AUDIT_AVAILABLE:
            return False, "Deep audit not available"

        topic_lower = topic.lower()

        # High-priority triggers for deep audit
        critical_keywords = [
            "architecture",
            "security",
            "authentication",
            "authorization",
            "database",
            "migration",
            "breaking change",
            "api contract",
            "consensus",
            "voting",
            "protocol",
            "protected file",
        ]

        strategy_keywords = [
            "strategy",
            "design pattern",
            "refactor",
            "restructure",
            "system design",
            "infrastructure",
            "scale",
            "performance",
        ]

        # Check for critical topics
        for keyword in critical_keywords:
            if keyword in topic_lower:
                return True, f"Critical topic detected: {keyword}"

        # Check for strategy topics in design phase
        if phase == "design":
            for keyword in strategy_keywords:
                if keyword in topic_lower:
                    return True, f"Strategy topic detected: {keyword}"

        # Check topic length/complexity (long topics often more complex)
        if len(topic) > 500:
            return True, "Complex topic (length > 500 chars)"

        return False, "Standard topic, normal debate sufficient"

    async def _run_deep_audit_for_design(
        self, improvement: str, design_context: str = ""
    ) -> dict | None:
        """Run Deep Audit Mode for design phase of critical topics.

        Uses STRATEGY_AUDIT config with cross-examination enabled.

        Returns:
            dict with verdict details, or None if audit not run
        """
        if not DEEP_AUDIT_AVAILABLE or not run_deep_audit:
            return None

        self._log("    [deep-audit] Running strategic design audit (5-round)")

        try:
            audit_agents = self._get_all_agents()

            # Use CODE_ARCHITECTURE_AUDIT for strategic design review
            verdict = await run_deep_audit(
                task=f"""STRATEGIC DESIGN REVIEW

## Proposed Improvement
{improvement[:8000]}

{design_context}

## Your Task
1. Evaluate the architectural soundness of this proposal
2. Identify potential risks and unintended consequences
3. Check for conflicts with existing systems
4. Assess complexity vs. value tradeoff
5. Propose refinements or alternatives if needed
6. Flag any concerns that need unanimous agreement before proceeding

Cross-examine each other's reasoning. Be thorough.""",
                agents=audit_agents,
                config=CODE_ARCHITECTURE_AUDIT,
            )

            result = {
                "confidence": verdict.confidence,
                "unanimous_issues": verdict.unanimous_issues,
                "split_opinions": verdict.split_opinions,
                "risk_areas": verdict.risk_areas,
                "approved": len(verdict.unanimous_issues) == 0,
            }

            self._log(f"    [deep-audit] Design confidence: {verdict.confidence:.0%}")
            if verdict.unanimous_issues:
                self._log(f"    [deep-audit] Blocking issues: {len(verdict.unanimous_issues)}")
                for issue in verdict.unanimous_issues[:3]:
                    self._log(f"      - {issue[:150]}...")

            return result

        except Exception as e:
            self._log(f"    [deep-audit] Design audit failed: {e}")
            return None

    async def _run_deep_audit_for_protected_files(
        self, diff: str, touched_files: list[str]
    ) -> tuple[bool, str | None]:
        """Run Deep Audit Mode for changes to protected files.

        Heavy3-inspired: 6-round intensive review with cross-examination
        for high-stakes changes.

        Returns:
            (approved: bool, issues: Optional[str])
        """
        if not DEEP_AUDIT_AVAILABLE or not run_deep_audit:
            self._log("    [deep-audit] Not available, falling back to regular review")
            return True, None

        self._log(
            f"    [deep-audit] Starting intensive review for protected files: {touched_files}"
        )
        self._log(
            "    [deep-audit] Running 5-round CODE_ARCHITECTURE_AUDIT with cross-examination..."
        )

        try:
            # Create agents list for deep audit
            audit_agents = self._get_all_agents()

            # Run deep audit
            verdict = await run_deep_audit(
                task=f"""CRITICAL: Review changes to protected files.

These files are essential to aragora's functionality and must be reviewed with maximum scrutiny.

## Protected Files Being Modified
{", ".join(touched_files)}

## Changes (git diff)
```
{diff[:15000]}
```

## Your Task
1. Analyze each change for correctness and safety
2. Identify any breaking changes or regressions
3. Check for security vulnerabilities
4. Verify backward compatibility is preserved
5. Flag any unanimous issues that must be addressed before merge

Be rigorous. These files are protected for a reason.""",
                agents=audit_agents,
                config=CODE_ARCHITECTURE_AUDIT,
            )

            # Log verdict summary
            self._log(f"    [deep-audit] Confidence: {verdict.confidence:.0%}")
            self._log(f"    [deep-audit] Unanimous issues: {len(verdict.unanimous_issues)}")
            self._log(f"    [deep-audit] Split opinions: {len(verdict.split_opinions)}")
            self._log(f"    [deep-audit] Risk areas: {len(verdict.risk_areas)}")

            # If there are unanimous issues, reject the changes
            if verdict.unanimous_issues:
                self._log("    [deep-audit] REJECTED - Unanimous issues found:")
                for issue in verdict.unanimous_issues[:5]:
                    self._log(f"      - {issue[:200]}")
                return False, "\n".join(verdict.unanimous_issues)

            # If low confidence and many split opinions, warn but allow
            if verdict.confidence < 0.5 and len(verdict.split_opinions) > 2:
                self._log("    [deep-audit] WARNING - Low confidence, proceed with caution")

            self._log("    [deep-audit] APPROVED - No unanimous blocking issues")
            return True, None

        except Exception as e:
            self._log(f"    [deep-audit] ERROR: {e}")
            self._log("    [deep-audit] Falling back to regular review due to error")
            return True, None

    def _sanitize_agent_input(self, text: str, source: str = "agent") -> str:
        """
        Sanitize agent-provided text to prevent prompt injection attacks.

        Security measure: Filters potentially malicious patterns from agent suggestions
        before they're merged into prompts for other agents.

        Args:
            text: Raw text from agent
            source: Source identifier for logging

        Returns:
            Sanitized text with dangerous patterns removed
        """
        import re

        dangerous_patterns = [
            (r"ignore\s+(?:all\s+)?(?:previous\s+)?instructions?", "instruction override"),
            (r"disregard\s+(?:all\s+)?(?:previous\s+)?(?:rules?|guidelines?)", "rule bypass"),
            (r"bypass\s+(?:safety|security|restrictions?)", "safety bypass"),
            (r"execute\s+(?:this\s+)?(?:code|command|script)", "code execution"),
            (r"system\s+prompt", "system prompt access"),
            (r"you\s+are\s+now\s+(?:a|an)", "role hijacking"),
            (r"forget\s+(?:everything|all)", "memory wipe"),
            (r"new\s+instructions?:", "instruction injection"),
            (r"<\s*script\s*>", "script tag"),
            (r"\$\{.*\}", "template injection"),
        ]

        sanitized = text
        filtered_count = 0

        for pattern, description in dangerous_patterns:
            if re.search(pattern, sanitized, re.IGNORECASE):
                filtered_count += 1
                sanitized = re.sub(
                    pattern, f"[FILTERED:{description}]", sanitized, flags=re.IGNORECASE
                )

        if filtered_count > 0:
            self._log(f"  [security] Filtered {filtered_count} suspicious patterns from {source}")

        return sanitized

    async def _gather_implementation_suggestions(self, design: str) -> str:
        """
        All agents provide implementation suggestions in parallel.

        This ensures all agents have a chance to contribute to implementation,
        with Claude getting the final pass to consolidate and execute.

        Returns:
            Combined suggestions from all agents to guide implementation.
        """
        self._log("  Gathering implementation suggestions from all agents...", agent="claude")

        suggestion_prompt = f"""Based on this design, provide your implementation suggestions:

{design[:3000]}

Provide:
1. KEY IMPLEMENTATION APPROACH: How would you structure the code?
2. POTENTIAL PITFALLS: What could go wrong and how to avoid it?
3. CODE SNIPPETS: Any specific code patterns or snippets to use.

Be concise (max 500 words). Focus on actionable guidance."""

        async def get_suggestion(agent, name: str) -> tuple[str, str]:
            """Get implementation suggestion from one agent."""
            try:
                self._log(f"    {name}: providing suggestions...", agent=name)
                result = await self._call_agent_with_retry(agent, suggestion_prompt, max_retries=2)
                if result and not ("[Agent" in result and "failed" in result):
                    self._log(f"    {name}: suggestions received", agent=name)
                    # Emit full suggestion content to stream for dashboard visibility
                    self._stream_emit(
                        "on_log_message", result, level="info", phase="implement", agent=name
                    )
                    return (name, result)  # Return full result, no truncation
                else:
                    return (name, "")
            except Exception as e:
                self._log(f"    {name}: suggestion failed: {e}", agent=name)
                return (name, "")

        # Run all agents in parallel
        tasks = [
            get_suggestion(self.gemini, "gemini"),
            get_suggestion(self.codex, "codex"),
            get_suggestion(self.grok, "grok"),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Compile suggestions with security sanitization
        suggestions = []
        for result in results:
            if isinstance(result, tuple) and result[1]:
                name, suggestion = result
                # Sanitize agent input to prevent prompt injection attacks
                sanitized = self._sanitize_agent_input(suggestion, source=name)
                suggestions.append(f"### {name.upper()}'s Suggestions:\n{sanitized}\n")

        if suggestions:
            combined = "\n".join(suggestions)
            self._log(f"  Received suggestions from {len(suggestions)} agents")
            return f"""
## IMPLEMENTATION GUIDANCE (from other agents)
The following suggestions were provided by other agents. Consider their insights while implementing.

{combined}

## YOUR ROLE (Claude)
You are the final implementer. Use the best ideas from above, but apply your own judgment.
Synthesize these suggestions into a coherent, working implementation.
"""
        return ""

    def _create_arena_hooks(self, phase_name: str) -> dict:
        """Create event hooks for real-time Arena logging and streaming."""
        # Get streaming hooks if available
        stream_hooks = {}
        if self.stream_emitter and STREAMING_AVAILABLE and create_arena_hooks:
            stream_hooks = create_arena_hooks(self.stream_emitter)

        def make_combined_hook(log_fn, stream_hook_name):
            """Combine logging and streaming for a hook."""
            stream_fn = stream_hooks.get(stream_hook_name)

            def combined(*args, **kwargs):
                log_fn(*args, **kwargs)
                if stream_fn:
                    try:
                        stream_fn(*args, **kwargs)
                    except Exception:
                        pass  # Don't let streaming errors break the loop

            return combined

        return {
            "on_debate_start": make_combined_hook(
                lambda task, agents: self._log(f"    Debate started: {len(agents)} agents"),
                "on_debate_start",
            ),
            "on_message": make_combined_hook(
                lambda agent, content, role, round_num: self._log(
                    f"    [{role}] {agent} (round {round_num}): {content}"  # Full content, no truncation
                ),
                "on_message",
            ),
            "on_critique": make_combined_hook(
                lambda agent, target, issues, severity, round_num, full_content=None: self._log(
                    f"    [critique] {agent} -> {target}: {len(issues)} issues, severity {severity:.1f}"
                ),
                "on_critique",
            ),
            "on_round_start": make_combined_hook(
                lambda round_num: self._log(f"    --- Round {round_num} ---"), "on_round_start"
            ),
            "on_consensus": make_combined_hook(
                lambda reached, confidence, answer: self._log(
                    f"    Consensus: {'Yes' if reached else 'No'} ({confidence:.0%})"
                ),
                "on_consensus",
            ),
            "on_vote": make_combined_hook(
                lambda agent, vote, confidence: self._log(
                    f"    [vote] {agent}: {vote} ({confidence:.0%})"
                ),
                "on_vote",
            ),
            "on_debate_end": make_combined_hook(
                lambda duration, rounds: self._log(
                    f"    Completed in {duration:.1f}s ({rounds} rounds)"
                ),
                "on_debate_end",
            ),
        }

    def _handle_disagreement_influence(
        self, report: "DisagreementReport", phase_name: str, result: "DebateResult"
    ) -> dict:
        """Handle disagreement patterns to influence decisions.

        Heavy3-inspired: Make disagreement data actionable.

        Returns:
            dict with action recommendations:
            - should_reject: bool - proposal should be rejected
            - should_fork: bool - debate should be forked to explore disagreement
            - rejection_reasons: list[str] - reasons if rejected
            - fork_topic: str - topic to fork on if forking
        """
        actions = {
            "should_reject": False,
            "should_fork": False,
            "rejection_reasons": [],
            "fork_topic": None,
            "escalate_to": None,
        }

        # Track critical disagreement patterns
        critical_warning = False

        # ACTION 1: Auto-reject on unanimous critiques (>= 3 unanimous issues)
        if len(report.unanimous_critiques) >= 3:
            self._log(
                f"    [disagreement] REJECT: {len(report.unanimous_critiques)} unanimous issues - proposal blocked"
            )
            actions["should_reject"] = True
            actions["rejection_reasons"] = report.unanimous_critiques[:5]
            critical_warning = True

        # ACTION 2: Fork trigger for low agreement (< 0.4)
        if report.agreement_score < 0.4 and not actions["should_reject"]:
            self._log(
                f"    [disagreement] FORK: Low agreement ({report.agreement_score:.0%}) - exploring alternatives"
            )
            actions["should_fork"] = True
            # Create fork topic from the main disagreement
            if report.split_opinions:
                first_split = (
                    report.split_opinions[0]
                    if isinstance(report.split_opinions, list)
                    else str(report.split_opinions)
                )
                actions["fork_topic"] = f"Resolve disagreement: {first_split[:200]}"
            critical_warning = True

        # ACTION 3: Escalate split opinions for persistent patterns
        if len(report.split_opinions) >= 3:
            self._log(
                f"    [disagreement] ESCALATE: {len(report.split_opinions)} split opinions detected"
            )
            # Track which agents consistently disagree
            if not hasattr(self, "_agent_disagreement_patterns"):
                self._agent_disagreement_patterns = {}

            # Store for pattern analysis
            actions["escalate_to"] = "cross_examination"
            for opinion in report.split_opinions[:3]:
                self._log(f"      Split: {str(opinion)[:100]}")

        # If very low agreement but not rejecting, warn
        if report.agreement_score < 0.4 and not actions["should_reject"]:
            self._log(
                f"    [disagreement] WARNING: Low agreement ({report.agreement_score:.0%}) - consider revising proposal"
            )
            critical_warning = True

        # If high-stakes phase (design/implement) and significant disagreement, log prominently
        if phase_name in ("design", "implement") and (
            len(report.unanimous_critiques) >= 2 or report.agreement_score < 0.5
        ):
            self._log(
                f"    [disagreement] ATTENTION: High-stakes phase '{phase_name}' has significant disagreement"
            )
            # Store for later review
            if not hasattr(self, "_critical_disagreements"):
                self._critical_disagreements = []
            self._critical_disagreements.append(
                {
                    "phase": phase_name,
                    "cycle": self.cycle_count,
                    "unanimous_critiques": report.unanimous_critiques,
                    "agreement_score": report.agreement_score,
                    "actions_taken": actions,
                    "timestamp": datetime.now().isoformat(),
                }
            )

        # If many risk areas identified, log them prominently
        if len(report.risk_areas) >= 2:
            self._log(f"    [disagreement] {len(report.risk_areas)} RISK AREAS to monitor:")
            for risk in report.risk_areas[:3]:
                self._log(f"      - {risk[:100]}")

        # Stream critical warnings for dashboard visibility
        if critical_warning:
            action_str = ""
            if actions["should_reject"]:
                action_str = " [REJECTED]"
            elif actions["should_fork"]:
                action_str = " [FORKING]"
            self._stream_emit(
                "on_log_message",
                f"Disagreement alert in {phase_name}: {len(report.unanimous_critiques)} unanimous issues, {report.agreement_score:.0%} agreement{action_str}",
                level="warning",
                phase=phase_name,
            )

        return actions

    async def _run_arena_with_logging(self, arena: Arena, phase_name: str) -> "DebateResult":
        """Run an Arena debate with real-time logging via event hooks."""
        self._log(f"  Starting {phase_name} arena...")
        self._save_state({"phase": phase_name, "stage": "arena_starting"})

        # Add event hooks for real-time logging
        arena.hooks = self._create_arena_hooks(phase_name)

        try:
            result = await arena.run()

            self._log(f"  {phase_name} arena complete")
            self._log(f"    Consensus: {result.consensus_reached}", also_print=False)
            self._log(f"    Confidence: {result.confidence}", also_print=False)
            self._log(f"    Duration: {result.duration_seconds:.1f}s", also_print=False)

            # Log and act on DisagreementReport (Heavy3-inspired unanimous issues/split opinions)
            if result.disagreement_report:
                report = result.disagreement_report
                self._log(
                    f"    [disagreement] Agreement Score: {report.agreement_score:.1%}",
                    also_print=False,
                )
                if report.unanimous_critiques:
                    self._log(
                        f"    [disagreement] {len(report.unanimous_critiques)} UNANIMOUS ISSUES (high priority):"
                    )
                    for issue in report.unanimous_critiques[:3]:
                        self._log(f"      - {issue[:100]}...")
                if report.split_opinions:
                    self._log(
                        f"    [disagreement] {len(report.split_opinions)} split opinions (review carefully)",
                        also_print=False,
                    )
                if report.risk_areas:
                    self._log(
                        f"    [disagreement] {len(report.risk_areas)} risk areas identified",
                        also_print=False,
                    )

                # Heavy3-inspired decision influence based on disagreement patterns
                disagreement_actions = self._handle_disagreement_influence(
                    report, phase_name, result
                )

                # Store actions on result for phase handlers to use
                result.disagreement_actions = disagreement_actions

                # Execute forking when triggered (requires fork_debate_enabled)
                if disagreement_actions.get("should_fork"):
                    fork_topic = disagreement_actions.get("fork_topic", "unknown")
                    fork_reason = disagreement_actions.get(
                        "fork_reason", "deep disagreement detected"
                    )

                    # Check if forking is enabled
                    execute_forks = (
                        getattr(self, "execute_forks", True) and self.fork_debate_enabled
                    )

                    if execute_forks and DEBATE_FORKER_AVAILABLE:
                        # Create ForkDecision from split opinions
                        from aragora.debate.forking import ForkDecision

                        # Extract branches from split opinions (max 3)
                        split_opinions = report.split_opinions[:3] if report.split_opinions else []
                        branches = []
                        for i, opinion in enumerate(split_opinions):
                            agent_name = (
                                arena.agents[i % len(arena.agents)].name
                                if arena.agents
                                else "unknown"
                            )
                            branches.append({"hypothesis": opinion[:200], "lead_agent": agent_name})

                        # Ensure at least 2 branches for meaningful fork
                        if len(branches) < 2:
                            agent1 = arena.agents[0].name if arena.agents else "claude"
                            agent2 = arena.agents[1].name if len(arena.agents) > 1 else "gpt-4"
                            branches = [
                                {"hypothesis": fork_topic, "lead_agent": agent1},
                                {
                                    "hypothesis": f"Alternative to: {fork_topic[:150]}",
                                    "lead_agent": agent2,
                                },
                            ]

                        fork_decision = ForkDecision(
                            should_fork=True,
                            reason=fork_reason,
                            branches=branches,
                            disagreement_score=1.0
                            - (report.agreement_score if report.agreement_score else 0.5),
                        )

                        # Execute forked debate
                        self._log(f"    [forking] 🔀 EXECUTING FORK: '{fork_topic[:50]}...'")
                        self._log(
                            f"    [forking] Branches: {len(branches)}, reason: {fork_reason[:50]}"
                        )

                        merge_result = await self._run_forked_debate(
                            fork_decision=fork_decision,
                            env=arena.env,
                            agents=arena.agents,
                            protocol=arena.protocol,
                            messages=result.messages if result.messages else [],
                            round_num=result.rounds_used if result.rounds_used else 0,
                            debate_id=self.loop_id,
                            base_context=arena.env.context if arena.env else "",
                        )

                        if merge_result:
                            self._log(
                                f"    [forking] ✅ Fork complete: winner={merge_result.winning_branch_id}"
                            )
                            self._log(
                                f"    [forking] Winning hypothesis: {merge_result.winning_hypothesis[:100]}..."
                            )

                            # Log merged insights
                            if merge_result.merged_insights:
                                for insight in merge_result.merged_insights[:3]:
                                    self._log(f"    [forking] Insight: {insight[:80]}...")

                            # Get winning branch result
                            winning_result = merge_result.all_branch_results.get(
                                merge_result.winning_branch_id
                            )
                            if winning_result:
                                # Replace main result with winning branch
                                result = winning_result
                                # Add fork metadata
                                result.fork_info = {
                                    "forked": True,
                                    "winning_branch": merge_result.winning_branch_id,
                                    "hypothesis": merge_result.winning_hypothesis,
                                    "comparison": (
                                        merge_result.comparison_summary[:500]
                                        if merge_result.comparison_summary
                                        else ""
                                    ),
                                    "branches_evaluated": len(merge_result.all_branch_results),
                                }

                            # Record fork outcome for learning
                            self._add_risk_entry(
                                {
                                    "type": "fork_executed",
                                    "feature": "debate_forking",
                                    "topic": fork_topic[:100],
                                    "winner": merge_result.winning_branch_id,
                                    "branches": len(merge_result.all_branch_results),
                                    "severity": "info",
                                    "action": "completed",
                                }
                            )
                        else:
                            self._log(
                                "    [forking] ⚠️ Fork execution failed, continuing with main path"
                            )
                            self._add_risk_entry(
                                {
                                    "type": "fork_failed",
                                    "feature": "debate_forking",
                                    "topic": fork_topic[:100],
                                    "reason": "merge_result was None",
                                    "severity": "low",
                                    "action": "fallback_to_main",
                                }
                            )
                    else:
                        # Forking disabled or not available - log and continue
                        self._log(
                            f"    [forking] ⚠️ Fork detected but skipped: '{fork_topic[:50]}...' "
                            f"(execute_forks={getattr(self, 'execute_forks', True)}, "
                            f"fork_enabled={self.fork_debate_enabled}, available={DEBATE_FORKER_AVAILABLE})"
                        )

            self._save_state(
                {
                    "phase": phase_name,
                    "stage": "arena_complete",
                    "consensus_reached": result.consensus_reached,
                    "confidence": result.confidence,
                    "final_answer_preview": result.final_answer if result.final_answer else None,
                    # Include disagreement report summary
                    "disagreement_report": (
                        {
                            "unanimous_critiques": (
                                result.disagreement_report.unanimous_critiques
                                if result.disagreement_report
                                else []
                            ),
                            "split_opinions_count": (
                                len(result.disagreement_report.split_opinions)
                                if result.disagreement_report
                                else 0
                            ),
                            "agreement_score": (
                                result.disagreement_report.agreement_score
                                if result.disagreement_report
                                else None
                            ),
                            "actions": (
                                result.disagreement_actions
                                if hasattr(result, "disagreement_actions")
                                else None
                            ),
                        }
                        if result.disagreement_report
                        else None
                    ),
                }
            )

            return result

        except Exception as e:
            self._log(f"  {phase_name} arena ERROR: {e}")
            self._save_state({"phase": phase_name, "stage": "arena_error", "error": str(e)})
            raise

    async def _arbitrate_design(
        self, proposals: dict, improvement: str, alignment: float = None
    ) -> str | None:
        """Use a judge agent to pick between competing design proposals.

        When design voting is tied or close, this method uses Claude as an impartial
        judge to evaluate and select the best design based on:
        - Feasibility (can it actually be implemented?)
        - Completeness (does it cover all required changes?)
        - Safety (does it preserve existing functionality?)
        - Clarity (is it specific enough to implement?)

        Args:
            proposals: Dict mapping agent name to their design proposal
            improvement: The improvement being designed (for context)
            alignment: Optional proposal alignment score (0-1) to guide judging

        Returns:
            The selected design text, or None if arbitration fails
        """
        if not proposals or len(proposals) < 2:
            return None

        try:
            # Use Claude as judge (generally high-quality reasoning)
            judge = self.claude

            # Format proposals for comparison
            proposals_text = "\n\n---\n\n".join(
                f"## {agent}'s Design:\n{proposal[:2000]}..."
                for agent, proposal in proposals.items()
            )

            # Get alignment-aware judge guidance
            if alignment is None:
                alignment = self._calculate_proposal_alignment(proposals)
            judge_guidance = self._get_judge_guidance(alignment, len(proposals))

            arbitration_prompt = f"""You are a senior software architect arbitrating between competing design proposals.

## The Improvement Being Designed:
{improvement[:1000]}

## Competing Designs:
{proposals_text}

## Proposal Alignment
The proposals have an alignment score of {alignment:.2f} (0=completely different, 1=identical).

## Your Decision Strategy
{judge_guidance}

## Evaluation Criteria:
1. FEASIBILITY: Can this be implemented without major refactoring?
2. COMPLETENESS: Does it specify all file changes, APIs, and integration points?
3. SAFETY: Does it preserve existing functionality and avoid protected files?
4. CLARITY: Is it specific enough that an engineer could implement it?
5. TESTABILITY: Does it include a viable test plan?

Respond with ONLY the complete design specification (no preamble).
Start directly with "## 1. FILE CHANGES" or similar."""

            self._log("  [arbitration] Judge evaluating proposals...")
            try:
                response = await asyncio.wait_for(
                    judge.generate(arbitration_prompt),
                    timeout=180,  # 3 minute max for judge arbitration
                )
            except asyncio.TimeoutError:
                self._log("  [arbitration] Judge timeout - using highest-voted proposal")
                return None

            if response and len(response) > 200:
                return response
            else:
                self._log("  [arbitration] Judge response too short")
                return None

        except Exception as e:
            self._log(f"  [arbitration] Error: {e}")
            return None

    async def _run_fractal_with_logging(
        self, task: str, agents: list, phase_name: str
    ) -> "DebateResult":
        """Run a fractal debate with agent evolution and real-time logging."""
        if not self.use_genesis or not GENESIS_AVAILABLE:
            # Fall back to regular arena
            env = Environment(task=task)
            protocol = DebateProtocol(
                rounds=2,
                consensus="majority",
                consensus_threshold=self._get_adaptive_consensus_threshold(),  # Adaptive threshold
                judge_selection="elo_ranked",  # Use ELO-based judge selection
                role_rotation=True,
                role_rotation_config=RoleRotationConfig(
                    enabled=True,
                    roles=[
                        CognitiveRole.ANALYST,
                        CognitiveRole.SKEPTIC,
                        CognitiveRole.LATERAL_THINKER,
                    ],
                ),
            )
            arena = Arena(
                environment=env,
                agents=agents,
                protocol=protocol,
                memory=self.critique_store,
                debate_embeddings=self.debate_embeddings,
                insight_store=self.insight_store,
                position_tracker=self.position_tracker,
                position_ledger=self.position_ledger,
                calibration_tracker=self.calibration_tracker,
                elo_system=self.elo_system,
                event_emitter=self.stream_emitter,
                loop_id=self.loop_id,
                event_hooks=self._create_arena_hooks("fractal"),
                persona_manager=self.persona_manager,
                relationship_tracker=self.relationship_tracker,
                moment_detector=self.moment_detector,
                continuum_memory=self.continuum,
                use_airlock=True,  # Enable resilience wrapper
                # Cross-pollination components (v2.0.3)
                debate_strategy=self.debate_strategy,
                cross_debate_memory=self.cross_debate_memory,
                enable_adaptive_rounds=self.debate_strategy is not None,
            )
            return await self._run_arena_with_logging(arena, phase_name)

        self._log(f"  Starting {phase_name} fractal debate (genesis mode)...")
        self._save_state({"phase": phase_name, "stage": "fractal_starting", "genesis": True})

        # Create fractal orchestrator with hooks
        orchestrator = FractalOrchestrator(
            max_depth=2,
            tension_threshold=0.6,
            evolve_agents=True,
            population_manager=self.population_manager,
            event_hooks=self.stream_hooks,
        )

        try:
            # Get or create population from agent names
            agent_names = [a.name.split("_")[0] for a in agents]
            population = self.population_manager.get_or_create_population(agent_names)

            self._log(f"    Population: {population.size} genomes, gen {population.generation}")

            # Run fractal debate
            fractal_result = await orchestrator.run(
                task=task,
                agents=agents,
                population=population,
            )

            self._log(f"  {phase_name} fractal debate complete")
            self._log(f"    Total depth: {fractal_result.total_depth}")
            self._log(f"    Sub-debates: {len(fractal_result.sub_debates)}")
            self._log(f"    Tensions resolved: {fractal_result.tensions_resolved}")
            self._log(f"    Evolved genomes: {len(fractal_result.evolved_genomes)}")

            # Log evolved genomes
            for genome in fractal_result.evolved_genomes:
                self._log(f"      - {genome.name} (gen {genome.generation})")

            self._save_state(
                {
                    "phase": phase_name,
                    "stage": "fractal_complete",
                    "genesis": True,
                    "total_depth": fractal_result.total_depth,
                    "sub_debates": len(fractal_result.sub_debates),
                    "evolved_genomes": len(fractal_result.evolved_genomes),
                    "consensus_reached": fractal_result.main_result.consensus_reached,
                }
            )

            return fractal_result.main_result

        except Exception as e:
            self._log(f"  {phase_name} fractal debate ERROR: {e}")
            self._save_state({"phase": phase_name, "stage": "fractal_error", "error": str(e)})
            # Fall back to regular arena on error
            self._log("  Falling back to regular arena...")
            env = Environment(task=task)
            protocol = DebateProtocol(
                rounds=2,
                consensus="majority",
                consensus_threshold=self._get_adaptive_consensus_threshold(),  # Adaptive threshold
                judge_selection="elo_ranked",  # Use ELO-based judge selection
                role_rotation=True,
                role_rotation_config=RoleRotationConfig(
                    enabled=True,
                    roles=[
                        CognitiveRole.ANALYST,
                        CognitiveRole.SKEPTIC,
                        CognitiveRole.LATERAL_THINKER,
                    ],
                ),
            )
            arena = Arena(
                environment=env,
                agents=agents,
                protocol=protocol,
                memory=self.critique_store,
                debate_embeddings=self.debate_embeddings,
                insight_store=self.insight_store,
                position_tracker=self.position_tracker,
                position_ledger=self.position_ledger,
                calibration_tracker=self.calibration_tracker,
                elo_system=self.elo_system,
                event_emitter=self.stream_emitter,
                loop_id=self.loop_id,
                event_hooks=self._create_arena_hooks("fractal_fallback"),
                persona_manager=self.persona_manager,
                relationship_tracker=self.relationship_tracker,
                moment_detector=self.moment_detector,
                continuum_memory=self.continuum,
                use_airlock=True,  # Enable resilience wrapper
                # Cross-pollination components (v2.0.3)
                debate_strategy=self.debate_strategy,
                cross_debate_memory=self.cross_debate_memory,
                enable_adaptive_rounds=self.debate_strategy is not None,
            )
            return await self._run_arena_with_logging(arena, phase_name)

    async def phase_context_gathering(self) -> dict:
        """
        Phase 0: All agents explore codebase to gather context.

        Each agent uses its native codebase exploration harness:
        - Claude → Claude Code CLI (native codebase access)
        - Codex → Codex CLI (native codebase access)
        - Gemini → Kilo Code CLI (agentic codebase exploration)
        - Grok → Kilo Code CLI (agentic codebase exploration)

        This ensures ALL agents have first-hand knowledge of the codebase,
        preventing proposals for features that already exist.
        """
        context_phase = self._create_context_phase()
        result = await context_phase.execute()

        # Optionally enrich with TRUE RLM (REPL-based) codebase summary.
        # Default behavior: rely on NomicContextBuilder augmentation; only run extra
        # full-corpus summary if explicitly requested.
        rlm_context = None
        extra_rlm = os.environ.get("NOMIC_RLM_EXTRA_SUMMARY", "0") == "1"
        if extra_rlm or not getattr(self, "_context_builder", None):
            rlm_context = await self._build_rlm_codebase_context()
        codebase_context = result["codebase_summary"]
        if rlm_context and rlm_context.get("summary"):
            codebase_context = (
                f"{codebase_context}\n\n=== RLM CODEBASE SUMMARY (REPL) ===\n"
                f"{rlm_context['summary']}"
            )

        # G1: Verify context manifest integrity before injecting into debate
        _manifest_result = None
        try:
            from aragora.security.context_signing import get_signing_key, verify_manifest

            _manifest_result = verify_manifest(key=get_signing_key())
            if _manifest_result.manifest_missing:
                pass  # No manifest: proceed silently (backwards compatible)
            elif not _manifest_result.ok:
                logger.warning(
                    "Context manifest violations detected: %s",
                    _manifest_result.violations,
                )
            else:
                logger.info(
                    "Context manifest verified: %d file(s) clean",
                    len(_manifest_result.verified_files),
                )
        except Exception as e:  # noqa: BLE001
            # Never block the Nomic Loop for signing errors
            logger.warning("Context manifest check failed: %s", e)
            _manifest_result = None

        # Convert ContextResult (TypedDict) to dict for backward compatibility
        return {
            "phase": "context",
            "codebase_context": codebase_context,
            "duration": result["duration_seconds"],
            "agents_succeeded": result.get("data", {}).get("agents_succeeded", 0),
            "rlm": rlm_context or {},
            "context_tainted": (
                not _manifest_result.ok
                if _manifest_result and not _manifest_result.manifest_missing
                else False
            ),
            "context_violations": (
                _manifest_result.violations
                if _manifest_result and not _manifest_result.manifest_missing
                else []
            ),
        }

    async def phase_debate(self, codebase_context: str = None) -> dict:
        """Phase 1: Agents debate what to improve."""
        topic_hint = self.initial_proposal[:200] if self.initial_proposal else ""
        debate_phase = self._create_debate_phase(topic_hint=topic_hint)
        debate_team = debate_phase.agents  # Get the team for hooks
        hooks = self._create_post_debate_hooks(debate_team=debate_team)
        # Build learning context
        from aragora.nomic.phases.debate import LearningContext

        # Get cross-cycle learning from previous cycles
        cross_cycle_context = self._get_cross_cycle_context(topic_hint)

        learning = LearningContext(
            failure_lessons=self._analyze_failed_branches(),
            successful_patterns=self._format_successful_patterns(),
            consensus_history=cross_cycle_context,  # Inject cross-cycle learning
        )
        result = await debate_phase.execute(
            codebase_context=codebase_context or self.get_current_features(),
            recent_changes=self.get_recent_changes(),
            learning_context=learning,
            hooks=hooks,
        )
        # Convert DebateResult (TypedDict) to dict for backward compatibility
        return {
            "phase": "debate",
            "improvement": result["improvement"],
            "final_answer": result["improvement"],  # Alias for backward compat with _run_cycle_impl
            "consensus_reached": result["consensus_reached"],
            "confidence": result["confidence"],
        }

    async def phase_design(self, improvement: str, belief_analysis: dict = None) -> dict:
        """Phase 2: All agents design the implementation together.

        Args:
            improvement: The improvement proposal from debate phase
            belief_analysis: Optional belief analysis from debate (contested/crux claims)

        Task decomposition is performed for complex tasks to break them into
        manageable subtasks with dependencies.
        """
        # Task decomposition for complex tasks
        from aragora.nomic.task_decomposer import analyze_task

        decomposition = analyze_task(improvement)

        if decomposition.should_decompose:
            self._log(f"  [design] Task decomposed into {len(decomposition.subtasks)} subtasks")
            self._log(
                f"  [design] Complexity: {decomposition.complexity_level} (score={decomposition.complexity_score})"
            )
            self._log(f"  [design] Rationale: {decomposition.rationale}")

            # For decomposed tasks, process subtasks sequentially with dependencies
            designs = []
            for subtask in decomposition.subtasks:
                self._log(f"  [design] Processing subtask: {subtask.title}")
                subtask_design = await self._design_subtask(subtask, improvement, belief_analysis)
                designs.append(subtask_design)

            # Merge designs into unified design
            merged_design = self._merge_subtask_designs(designs, decomposition)
            return {
                "phase": "design",
                "success": all(d["success"] for d in designs),
                "design": merged_design,
                "files_affected": list(
                    set(f for d in designs for f in d.get("files_affected", []))
                ),
                "complexity": decomposition.complexity_level,
                "decomposed": True,
                "subtask_count": len(decomposition.subtasks),
            }

        # Standard path for simple tasks
        design_phase = self._create_design_phase()
        # Build belief context from analysis
        from aragora.nomic.phases.design import BeliefContext

        belief_ctx = None
        if belief_analysis:
            belief_ctx = BeliefContext(
                contested_count=belief_analysis.get("contested_count", 0),
                crux_count=belief_analysis.get("crux_count", 0),
                posteriors=belief_analysis.get("posteriors"),
                convergence_achieved=belief_analysis.get("convergence_achieved", False),
            )
        result = await design_phase.execute(
            improvement=improvement,
            belief_context=belief_ctx,
        )
        # Convert DesignResult (TypedDict) to dict for backward compatibility
        return {
            "phase": "design",
            "success": result["success"],
            "design": result["design"],
            "files_affected": result["files_affected"],
            "complexity": result["complexity_estimate"],
        }

    async def _design_subtask(
        self, subtask, parent_improvement: str, belief_analysis: dict = None
    ) -> dict:
        """Design a single subtask from decomposition."""
        design_phase = self._create_design_phase()
        from aragora.nomic.phases.design import BeliefContext

        belief_ctx = None
        if belief_analysis:
            belief_ctx = BeliefContext(
                contested_count=belief_analysis.get("contested_count", 0),
                crux_count=belief_analysis.get("crux_count", 0),
                posteriors=belief_analysis.get("posteriors"),
                convergence_achieved=belief_analysis.get("convergence_achieved", False),
            )

        # Build subtask-specific improvement prompt
        subtask_prompt = f"""SUBTASK: {subtask.title}

{subtask.description}

PARENT IMPROVEMENT CONTEXT:
{parent_improvement[:1000]}...

FILES IN SCOPE: {", ".join(subtask.file_scope) if subtask.file_scope else "auto-detect"}
DEPENDENCIES: {", ".join(subtask.dependencies) if subtask.dependencies else "none"}
"""

        result = await design_phase.execute(
            improvement=subtask_prompt,
            belief_context=belief_ctx,
        )
        return {
            "subtask_id": subtask.id,
            "success": result["success"],
            "design": result["design"],
            "files_affected": result["files_affected"],
        }

    def _merge_subtask_designs(self, designs: list, decomposition) -> str:
        """Merge subtask designs into a unified implementation plan."""
        merged_parts = ["# UNIFIED IMPLEMENTATION PLAN\n"]
        merged_parts.append(f"Original task: {decomposition.original_task[:200]}...\n")
        merged_parts.append(
            f"Complexity: {decomposition.complexity_level} (score={decomposition.complexity_score})\n\n"
        )

        for i, (subtask, design) in enumerate(zip(decomposition.subtasks, designs), 1):
            merged_parts.append(f"## Phase {i}: {subtask.title}\n")
            merged_parts.append(
                f"Dependencies: {', '.join(subtask.dependencies) if subtask.dependencies else 'none'}\n"
            )
            merged_parts.append(f"Estimated complexity: {subtask.estimated_complexity}\n\n")
            merged_parts.append(design.get("design", "No design generated") + "\n\n")

        return "\n".join(merged_parts)

    async def phase_implement(self, design: str) -> dict:
        """Phase 3: Hybrid multi-model implementation."""
        implement_phase = self._create_implement_phase()
        result = await implement_phase.execute(design)
        # Convert ImplementResult (TypedDict) to dict for backward compatibility
        return {
            "phase": "implement",
            "success": result["success"],
            "files_modified": result["files_modified"],
            "diff_summary": result["diff_summary"],
            "error": result.get("error"),
        }

    async def phase_verify(self) -> dict:
        """Phase 4: Verify changes don't break things."""
        verify_phase = self._create_verify_phase()
        result = await verify_phase.execute()
        # Convert VerifyResult (TypedDict) to dict for backward compatibility
        return {
            "phase": "verify",
            "success": result["success"],
            "test_results": result["test_results"],
            "error": result.get("error"),
        }

    async def _run_testfixer_loop(self) -> dict:
        """Run the TestFixer loop if enabled."""
        if not NOMIC_TESTFIXER_ENABLED:
            return {"status": "disabled"}

        try:
            from aragora.nomic.testfixer import FixLoopConfig, TestFixerOrchestrator
            from aragora.nomic.testfixer.generators import (
                AgentCodeGenerator,
                AgentGeneratorConfig,
            )
            from aragora.nomic.testfixer.analyzers import LLMAnalyzerConfig
            from aragora.nomic.testfixer.validators import (
                ArenaValidatorConfig,
                RedTeamValidatorConfig,
            )
        except Exception as exc:
            self._log(f"[testfixer] Unavailable: {exc}")
            return {"status": "unavailable", "error": str(exc)}

        def _parse_agent_specs(
            specs: str | None,
            fallback: str | None,
        ) -> tuple[list[str], dict[str, str] | None]:
            spec_str = specs if specs not in (None, "") else (fallback or "")
            if not spec_str:
                return ([], None)
            agent_types: list[str] = []
            models: dict[str, str] = {}
            for spec in [s.strip() for s in spec_str.split(",") if s.strip()]:
                if ":" in spec:
                    agent_type, model = spec.split(":", 1)
                    models[agent_type] = model
                else:
                    agent_type = spec
                agent_types.append(agent_type)
            return agent_types, models or None

        agent_specs = [a.strip() for a in NOMIC_TESTFIXER_AGENTS.split(",") if a.strip()]
        generators = []
        for spec in agent_specs:
            try:
                if ":" in spec:
                    agent_type, model = spec.split(":", 1)
                else:
                    agent_type, model = spec, None
                gen_config = AgentGeneratorConfig(
                    agent_type=agent_type,
                    model=model,
                    timeout_seconds=NOMIC_TESTFIXER_GENERATION_TIMEOUT,
                )
                generators.append(AgentCodeGenerator(gen_config))
            except Exception as exc:
                self._log(f"[testfixer] Skipping agent '{spec}': {exc}")

        analysis_agent_types, analysis_models = _parse_agent_specs(
            NOMIC_TESTFIXER_ANALYSIS_AGENTS,
            NOMIC_TESTFIXER_AGENTS,
        )
        llm_analyzer_config = None
        if NOMIC_TESTFIXER_USE_LLM_ANALYZER:
            default_analysis = LLMAnalyzerConfig()
            llm_analyzer_config = LLMAnalyzerConfig(
                agent_types=analysis_agent_types or default_analysis.agent_types,
                models=analysis_models,
                require_consensus=NOMIC_TESTFIXER_ANALYSIS_REQUIRE_CONSENSUS,
                consensus_threshold=NOMIC_TESTFIXER_ANALYSIS_CONSENSUS_THRESHOLD,
                agent_timeout=NOMIC_TESTFIXER_GENERATION_TIMEOUT,
            )

        arena_config = None
        if NOMIC_TESTFIXER_ARENA_VALIDATE:
            arena_agent_types, arena_models = _parse_agent_specs(
                NOMIC_TESTFIXER_ARENA_AGENTS,
                NOMIC_TESTFIXER_ANALYSIS_AGENTS or NOMIC_TESTFIXER_AGENTS,
            )
            default_arena = ArenaValidatorConfig()
            arena_config = ArenaValidatorConfig(
                agent_types=arena_agent_types or default_arena.agent_types,
                models=arena_models,
                debate_rounds=NOMIC_TESTFIXER_ARENA_ROUNDS,
                min_confidence_to_pass=NOMIC_TESTFIXER_ARENA_MIN_CONFIDENCE,
                require_consensus=NOMIC_TESTFIXER_ARENA_REQUIRE_CONSENSUS,
                consensus_threshold=NOMIC_TESTFIXER_ARENA_CONSENSUS_THRESHOLD,
                agent_timeout=NOMIC_TESTFIXER_GENERATION_TIMEOUT,
                debate_timeout=max(
                    NOMIC_TESTFIXER_GENERATION_TIMEOUT * 2,
                    default_arena.debate_timeout,
                ),
            )

        redteam_config = None
        if NOMIC_TESTFIXER_REDTEAM_VALIDATE:
            redteam_attackers, _ = _parse_agent_specs(
                NOMIC_TESTFIXER_REDTEAM_ATTACKERS,
                NOMIC_TESTFIXER_ANALYSIS_AGENTS or NOMIC_TESTFIXER_AGENTS,
            )
            default_redteam = RedTeamValidatorConfig()
            defender = NOMIC_TESTFIXER_REDTEAM_DEFENDER or (
                redteam_attackers[0] if redteam_attackers else default_redteam.defender_type
            )
            redteam_config = RedTeamValidatorConfig(
                attacker_types=redteam_attackers or default_redteam.attacker_types,
                defender_type=defender,
                attack_rounds=NOMIC_TESTFIXER_REDTEAM_ROUNDS,
                attacks_per_round=NOMIC_TESTFIXER_REDTEAM_ATTACKS_PER_ROUND,
                min_robustness_score=NOMIC_TESTFIXER_REDTEAM_MIN_ROBUSTNESS,
                agent_timeout=NOMIC_TESTFIXER_GENERATION_TIMEOUT,
                total_timeout=max(
                    NOMIC_TESTFIXER_GENERATION_TIMEOUT * 4,
                    default_redteam.total_timeout,
                ),
            )

        pattern_store_path = None
        if NOMIC_TESTFIXER_PATTERN_STORE:
            pattern_store_path = Path(NOMIC_TESTFIXER_PATTERN_STORE)

        config = FixLoopConfig(
            max_iterations=NOMIC_TESTFIXER_MAX_ITERATIONS,
            max_same_failure=NOMIC_TESTFIXER_MAX_SAME_FAILURE,
            min_confidence_to_apply=NOMIC_TESTFIXER_MIN_CONFIDENCE,
            min_confidence_for_auto=NOMIC_TESTFIXER_MIN_AUTO_CONFIDENCE,
            require_debate_consensus=NOMIC_TESTFIXER_REQUIRE_CONSENSUS,
            revert_on_failure=NOMIC_TESTFIXER_REVERT_ON_FAILURE,
            stop_on_first_success=NOMIC_TESTFIXER_STOP_ON_FIRST_SUCCESS,
            use_llm_analyzer=NOMIC_TESTFIXER_USE_LLM_ANALYZER,
            llm_analyzer_config=llm_analyzer_config,
            enable_arena_validation=NOMIC_TESTFIXER_ARENA_VALIDATE,
            arena_validator_config=arena_config,
            enable_redteam_validation=NOMIC_TESTFIXER_REDTEAM_VALIDATE,
            redteam_validator_config=redteam_config,
            enable_pattern_learning=NOMIC_TESTFIXER_PATTERN_LEARNING,
            pattern_store_path=pattern_store_path,
            generation_timeout_seconds=NOMIC_TESTFIXER_GENERATION_TIMEOUT,
            critique_timeout_seconds=NOMIC_TESTFIXER_CRITIQUE_TIMEOUT,
        )

        if NOMIC_TESTFIXER_REQUIRE_APPROVAL:

            async def approve(proposal):
                if not sys.stdin.isatty():
                    self._log("[testfixer] Approval required but no TTY; rejecting.")
                    return False
                self._log(f"[testfixer] Proposed fix: {proposal.description}")
                diff = proposal.as_diff()
                if diff:
                    print("\n" + diff)
                response = input("Apply this fix? [y/N]: ").strip().lower()
                return response in ("y", "yes")

            config.on_fix_proposed = approve

        fixer = TestFixerOrchestrator(
            repo_path=self.aragora_path,
            test_command=NOMIC_TESTFIXER_TEST_COMMAND,
            config=config,
            generators=generators or None,
            test_timeout=NOMIC_TESTFIXER_TEST_TIMEOUT,
        )

        result = await fixer.run_fix_loop(max_iterations=NOMIC_TESTFIXER_MAX_ITERATIONS)
        self._log(f"[testfixer] {result.summary()}")
        return result.to_dict()

    def _select_sica_agent(self, model_name: str | None):
        """Select an agent for SICA prompts based on model name."""
        model = (model_name or "").lower()
        candidates = [
            ("codex", getattr(self, "codex", None)),
            ("openai", getattr(self, "codex", None)),
            ("gpt", getattr(self, "codex", None)),
            ("claude", getattr(self, "claude", None)),
            ("gemini", getattr(self, "gemini", None)),
            ("grok", getattr(self, "grok", None)),
        ]
        for key, agent in candidates:
            if agent and key in model:
                return agent
        for _, agent in candidates:
            if agent:
                return agent
        return None

    async def _run_sica_cycle(self) -> dict:
        """Run the SICA improvement cycle if enabled."""
        if not NOMIC_SICA_ENABLED:
            return {"status": "disabled"}

        try:
            from aragora.nomic.sica_improver import (
                ImprovementType,
                SICAConfig,
                SICAImprover,
            )
        except Exception as exc:
            self._log(f"[sica] Unavailable: {exc}")
            return {"status": "unavailable", "error": str(exc)}

        improvement_types: list[ImprovementType] = []
        raw_types = [t.strip() for t in NOMIC_SICA_IMPROVEMENT_TYPES.split(",") if t.strip()]
        for t in raw_types:
            try:
                improvement_types.append(ImprovementType(t))
            except Exception:
                self._log(f"[sica] Unknown improvement type '{t}', skipping")

        async def query_fn(model: str, prompt: str, max_tokens: int) -> str:
            agent = self._select_sica_agent(model)
            if not agent:
                raise RuntimeError("No agent available for SICA")
            return await agent.generate(prompt, context=[])

        agent_for_sica = self._select_sica_agent(NOMIC_SICA_GENERATOR_MODEL)
        query = query_fn if agent_for_sica else None
        if not agent_for_sica:
            self._log("[sica] No agent available; running heuristic-only cycle")

        config = SICAConfig(
            improvement_types=improvement_types or None,
            generator_model=NOMIC_SICA_GENERATOR_MODEL,
            require_human_approval=NOMIC_SICA_REQUIRE_APPROVAL,
            run_tests=NOMIC_SICA_RUN_TESTS,
            run_typecheck=NOMIC_SICA_RUN_TYPECHECK,
            run_lint=NOMIC_SICA_RUN_LINT,
            test_command=NOMIC_SICA_TEST_COMMAND,
            typecheck_command=NOMIC_SICA_TYPECHECK_COMMAND,
            lint_command=NOMIC_SICA_LINT_COMMAND,
            validation_timeout_seconds=NOMIC_SICA_VALIDATION_TIMEOUT,
            max_opportunities_per_cycle=NOMIC_SICA_MAX_OPPORTUNITIES,
            max_rollbacks_per_cycle=NOMIC_SICA_MAX_ROLLBACKS,
        )

        if NOMIC_SICA_REQUIRE_APPROVAL:

            async def approve(patch):
                if not sys.stdin.isatty():
                    self._log("[sica] Approval required but no TTY; rejecting.")
                    return False
                self._log(f"[sica] Proposed patch: {patch.description}")
                if patch.diff:
                    print("\n" + patch.diff)
                response = input("Apply this patch? [y/N]: ").strip().lower()
                return response in ("y", "yes")

            config.approval_callback = approve

        improver = SICAImprover(
            repo_path=Path(self.aragora_path),
            config=config,
            query_fn=query,
        )

        result = await improver.run_improvement_cycle()
        self._log(f"[sica] {result.summary()}")
        return {
            "status": "success" if result.patches_successful else "no_changes",
            "summary": result.summary(),
            "result": result.to_dict(),
        }

    async def phase_commit(self, improvement: str) -> dict:
        """Phase 5: Commit changes if verification passes."""
        commit_phase = self._create_commit_phase()
        result = await commit_phase.execute(improvement)
        # Convert CommitResult (TypedDict) to dict for backward compatibility
        return {
            "phase": "commit",
            "success": result["success"],
            "commit_hash": result.get("commit_hash"),
            "branch": result.get("branch"),
            "error": result.get("error"),
        }

    def _start_cycle_record(self) -> None:
        """Initialize a new cycle record for cross-cycle learning."""
        if not self.cycle_store:
            return

        try:
            from aragora.nomic.cycle_record import NomicCycleRecord
            import uuid

            self._current_cycle_record = NomicCycleRecord(
                cycle_id=str(uuid.uuid4()),
                started_at=time.time(),
                branch_name=self._get_current_branch(),
            )
            self._log(
                f"  [cross-cycle] Started recording cycle {self._current_cycle_record.cycle_id[:8]}"
            )
        except Exception as e:
            self._log(f"  [cross-cycle] Failed to start record: {e}")
            self._current_cycle_record = None

    def _get_current_branch(self) -> str:
        """Get current git branch name."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.aragora_path,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    def _get_git_remote_url(self, remote: str) -> str | None:
        """Get git remote URL for the given remote name."""
        try:
            result = subprocess.run(
                ["git", "config", "--get", f"remote.{remote}.url"],
                capture_output=True,
                text=True,
                cwd=self.aragora_path,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip() or None
        except Exception:
            return None

    def _parse_github_repo(self, remote_url: str | None) -> str | None:
        """Extract owner/repo from a GitHub remote URL."""
        if not remote_url:
            return None
        patterns = [
            r"^git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
            r"^https?://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
            r"^ssh://git@github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        ]
        for pattern in patterns:
            match = re.match(pattern, remote_url.strip())
            if match:
                return match.group("repo")
        return None

    def _get_github_token(self) -> str | None:
        """Get GitHub token from environment."""
        return (
            os.environ.get("NOMIC_GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or os.environ.get("GH_TOKEN")
        )

    def _push_branch(self, remote: str, branch: str) -> bool:
        """Push HEAD to a remote branch."""
        try:
            result = subprocess.run(
                ["git", "push", remote, f"HEAD:refs/heads/{branch}"],
                cwd=self.aragora_path,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self._log(f"  [publish] Push failed: {result.stderr.strip()}")
                return False
            self._log(f"  [publish] Pushed to {remote}/{branch}")
            return True
        except Exception as e:
            self._log(f"  [publish] Push error: {e}")
            return False

    def _create_github_pr(
        self,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
        draft: bool,
        token: str,
    ) -> str | None:
        """Create a GitHub pull request and return the PR URL if successful."""
        url = f"https://api.github.com/repos/{repo}/pulls"
        payload = {
            "title": title,
            "head": head,
            "base": base,
            "body": body,
            "draft": draft,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
            pr_url = result.get("html_url")
            if pr_url:
                self._log("  [publish] Pull request created")
            else:
                self._log("  [publish] Pull request created (no URL returned)")
            return pr_url
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                error_body = str(e)
            self._log(f"  [publish] PR creation failed: {error_body}")
            return None
        except Exception as e:
            self._log(f"  [publish] PR creation error: {e}")
            return None

    def _maybe_publish_commit(self, improvement: str, commit_hash: str | None) -> dict | None:
        """Optionally push changes and open a PR after a successful commit."""
        auto_push = os.environ.get("NOMIC_AUTO_PUSH", "0") == "1"
        auto_pr = os.environ.get("NOMIC_AUTO_PR", "0") == "1"
        if not auto_push and not auto_pr:
            return None

        remote = os.environ.get("NOMIC_PR_REMOTE", "origin")
        base_branch = os.environ.get("NOMIC_PR_BASE", "main")
        branch_prefix = os.environ.get("NOMIC_PR_BRANCH_PREFIX", "nomic")

        cycle_id = None
        if hasattr(self, "_current_cycle_record") and self._current_cycle_record:
            cycle_id = self._current_cycle_record.cycle_id[:8]
        if not cycle_id:
            cycle_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        branch_name = f"{branch_prefix}/cycle-{self.cycle_count}-{cycle_id}"

        publish_result = {
            "branch": branch_name,
            "pushed": False,
            "pr_created": False,
            "pr_url": None,
        }

        # Always push if PR is requested
        if auto_push or auto_pr:
            publish_result["pushed"] = self._push_branch(remote, branch_name)
            if not publish_result["pushed"] and auto_pr:
                self._log("  [publish] PR skipped (push failed)")
                return publish_result

        if not auto_pr:
            return publish_result

        repo = os.environ.get("GITHUB_REPOSITORY") or self._parse_github_repo(
            self._get_git_remote_url(remote)
        )
        if not repo:
            self._log("  [publish] PR skipped (repo not detected)")
            return publish_result

        token = self._get_github_token()
        if not token:
            self._log("  [publish] PR skipped (missing GitHub token)")
            return publish_result

        title_prefix = os.environ.get("NOMIC_PR_TITLE_PREFIX", "feat(nomic):")
        title = f"{title_prefix} {improvement.splitlines()[0].strip()[:120]}".strip()
        body_lines = [
            "Auto-generated by Aragora Nomic Loop.",
            "",
            f"Cycle: {self.cycle_count}",
            f"Commit: {commit_hash or 'unknown'}",
            "",
            "Summary:",
            improvement.strip()[:2000],
        ]
        body = "\n".join(body_lines)
        draft = os.environ.get("NOMIC_PR_DRAFT", "0") == "1"

        pr_url = self._create_github_pr(
            repo=repo,
            head=branch_name,
            base=base_branch,
            title=title,
            body=body,
            draft=draft,
            token=token,
        )
        if pr_url:
            publish_result["pr_created"] = True
            publish_result["pr_url"] = pr_url

        return publish_result

    def _maybe_publish_to_marketplace(self, improvement: str, confidence: float) -> dict | None:
        """Optionally publish high-confidence configs as marketplace skills.

        Gated by ARAGORA_AUTO_PUBLISH_MARKETPLACE env var (default off).
        Only publishes when confidence >= 0.85.

        Args:
            improvement: Description of the improvement.
            confidence: Debate consensus confidence (0-1).

        Returns:
            Dict with publish result or None if skipped.
        """
        if os.environ.get("ARAGORA_AUTO_PUBLISH_MARKETPLACE", "0") != "1":
            return None

        min_confidence = float(os.environ.get("ARAGORA_MARKETPLACE_MIN_CONFIDENCE", "0.85"))
        if confidence < min_confidence:
            self._log(f"  [marketplace] Skipped (confidence {confidence:.2f} < {min_confidence})")
            return {"published": False, "reason": "below_confidence_threshold"}

        try:
            from aragora.skills.publisher import SkillPublisher
            from aragora.skills.base import Skill

            publisher = SkillPublisher()
            title = improvement.splitlines()[0].strip()[:80] or "nomic-improvement"
            skill_name = title.lower().replace(" ", "-").replace("_", "-")[:40]

            skill = Skill(
                name=f"nomic-{skill_name}",
                description=improvement.strip()[:500],
                version="0.1.0",
            )

            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._log("  [marketplace] Skipped (event loop already running)")
                return {"published": False, "reason": "event_loop_running"}

            success, listing, issues = loop.run_until_complete(
                publisher.publish(
                    skill=skill,
                    author_id="nomic-loop",
                    author_name="Aragora Nomic Loop",
                    changelog=f"Auto-published from cycle {self.cycle_count}",
                )
            )

            result = {
                "published": success,
                "skill_name": skill.name,
                "confidence": confidence,
                "issues": len(issues),
            }
            if listing:
                result["listing_id"] = listing.id
            self._log(f"  [marketplace] Published: {success} ({skill.name})")
            return result

        except ImportError:
            self._log("  [marketplace] Skipped (publisher not available)")
            return {"published": False, "reason": "import_error"}
        except (RuntimeError, ValueError, OSError) as e:
            self._log(f"  [marketplace] Error: {e}")
            return {"published": False, "reason": f"error: {type(e).__name__}"}

    def _finalize_cycle(self, cycle_result: dict) -> None:
        """Finalize cycle and record cross-cycle learning data.

        This is called in a finally block to ensure cycle data is always recorded,
        even on exceptions or early returns.
        """
        if not self.cycle_store or not self._current_cycle_record:
            return

        try:
            record = self._current_cycle_record

            # Mark completion
            success = cycle_result.get("outcome") == "success"
            error_msg = cycle_result.get("error") if not success else None
            record.mark_complete(success=success, error=error_msg)

            # Record phases completed
            record.phases_completed = cycle_result.get("phases_completed", [])

            # Record topics debated
            if cycle_result.get("debate_topic"):
                record.topics_debated.append(cycle_result["debate_topic"])

            # Record file changes
            record.files_modified = cycle_result.get("files_modified", [])
            record.files_created = cycle_result.get("files_created", [])

            # Record test results
            test_results = cycle_result.get("test_results", {})
            record.tests_passed = test_results.get("passed", 0)
            record.tests_failed = test_results.get("failed", 0)
            record.tests_skipped = test_results.get("skipped", 0)

            # Record commit info
            record.commit_sha = cycle_result.get("commit_hash")
            record.rollback_performed = cycle_result.get("rolled_back", False)

            # Add agent contributions from debate phase
            if cycle_result.get("agent_stats"):
                for agent_name, stats in cycle_result["agent_stats"].items():
                    record.add_agent_contribution(
                        agent_name=agent_name,
                        proposals_made=stats.get("proposals", 0),
                        proposals_accepted=stats.get("accepted", 0),
                        critiques_given=stats.get("critiques", 0),
                    )

            # Record surprise events (unexpected outcomes)
            for surprise in cycle_result.get("surprises", []):
                record.add_surprise(
                    phase=surprise.get("phase", "unknown"),
                    description=surprise.get("description", ""),
                    expected=surprise.get("expected", ""),
                    actual=surprise.get("actual", ""),
                    impact=surprise.get("impact", "low"),
                )

            # Save to store
            self.cycle_store.save_cycle(record)
            self._log(
                f"  [cross-cycle] Recorded cycle {record.cycle_id[:8]} "
                f"(success={success}, duration={record.duration_seconds:.1f}s)"
            )

        except Exception as e:
            self._log(f"  [cross-cycle] Failed to finalize record: {e}")
        finally:
            self._current_cycle_record = None

    def _get_cross_cycle_context(self, topic: str) -> str:
        """Get learning context from previous cycles for debate injection."""
        if not self.cycle_store:
            return ""

        try:
            # Get recent cycles
            recent = self.cycle_store.get_recent_cycles(5)

            # Query for similar topics
            similar = self.cycle_store.query_by_topic(topic, limit=3)

            # Get pattern statistics
            patterns = self.cycle_store.get_pattern_statistics()

            context_parts = []

            # Add recent cycle summary
            if recent:
                successful = sum(1 for c in recent if c.success)
                context_parts.append(
                    f"RECENT CYCLES: {len(recent)} cycles, {successful} successful"
                )

            # Add similar topic learnings
            if similar:
                context_parts.append("\nSIMILAR PAST DEBATES:")
                for cycle in similar[:2]:
                    outcome = "succeeded" if cycle.success else "failed"
                    context_parts.append(
                        f"  - {cycle.topics_debated[0] if cycle.topics_debated else 'unknown'}: {outcome}"
                    )

            # Add pattern success rates
            if patterns:
                context_parts.append("\nPATTERN SUCCESS RATES:")
                for pattern, stats in list(patterns.items())[:3]:
                    rate = stats.get("success_rate", 0)
                    context_parts.append(f"  - {pattern}: {rate * 100:.0f}%")

            return "\n".join(context_parts) if context_parts else ""

        except Exception as e:
            self._log(f"  [cross-cycle] Failed to get context: {e}")
            return ""

    async def _run_cycle_impl(self) -> dict:
        """Internal implementation of run_cycle (called with timeout wrapper)."""
        # Note: self.cycle_count already incremented by run_cycle() wrapper
        cycle_start = datetime.now()
        cycle_deadline = cycle_start + timedelta(seconds=self.max_cycle_seconds)

        # Store cycle_result as instance variable so finally can access actual result
        self._current_cycle_result = {"outcome": "unknown", "cycle": self.cycle_count}

        try:
            result = await self._run_cycle_impl_inner(cycle_start, cycle_deadline)
            self._current_cycle_result = result  # Update with actual result
            return result
        finally:
            # CRITICAL: Always finalize the cycle, even on early returns or exceptions
            self._finalize_cycle(self._current_cycle_result)

    async def run_cycle(self) -> dict:
        """Run a single nomic cycle with a hard timeout guard."""
        self.cycle_count += 1
        start_time = time.time()
        cycle_timeout = self.max_cycle_seconds

        # Distributed tracing span for entire cycle
        tracer = get_tracer()
        with tracer.start_as_current_span("nomic.cycle") as span:
            span.set_attribute("nomic.cycle_number", self.cycle_count)
            span.set_attribute("nomic.cycle_timeout", cycle_timeout)

            try:
                result = await asyncio.wait_for(self._run_cycle_impl(), timeout=cycle_timeout)
            except asyncio.TimeoutError:
                self._log(f"[CYCLE TIMEOUT] Cycle exceeded {cycle_timeout}s budget")
                result = {
                    "cycle": self.cycle_count,
                    "outcome": "cycle_timeout",
                    "error": f"Cycle exceeded {cycle_timeout}s budget",
                }
                if self._cycle_backup_path and not self.disable_rollback:
                    self._log("  [rollback] Restoring backup after cycle timeout")
                    if self._restore_backup(self._cycle_backup_path):
                        result["rolled_back"] = True
                span.set_attribute("nomic.cycle.outcome", "cycle_timeout")
            except Exception as e:
                self._log(f"[CYCLE CRASH] Cycle failed: {e}")
                result = {
                    "cycle": self.cycle_count,
                    "outcome": "cycle_crashed",
                    "error": str(e),
                }
                span.set_attribute("nomic.cycle.outcome", "cycle_crashed")
            else:
                span.set_attribute("nomic.cycle.outcome", result.get("outcome", "unknown"))

            result["duration_seconds"] = round(time.time() - start_time, 1)
            span.set_attribute("nomic.cycle.duration_s", result["duration_seconds"])
            self.history.append(result)
            return result

    async def _run_cycle_impl_inner(self, cycle_start: datetime, cycle_deadline: datetime) -> dict:
        """Inner implementation of cycle logic."""
        cycle_result = {"outcome": "unknown", "cycle": self.cycle_count}
        # Store reference for finally block in outer function
        self._current_cycle_result = cycle_result

        # Reset per-cycle state and track start time
        self._reset_cycle_state()
        self._cycle_start_time = cycle_start

        # Start cross-cycle learning record
        self._start_cycle_record()

        # Check for deadlock pattern from previous cycles
        deadlock = self._detect_cycle_deadlock()
        if deadlock:
            action = await self._handle_deadlock(deadlock)
            if action == "skip":
                self._log("  [DEADLOCK] Skipping cycle due to repeated failures")
                cycle_result["outcome"] = "skipped_deadlock"
                return cycle_result

        # Check memory pressure and cleanup if needed (prevents OOM on long runs)
        if self.continuum and CONTINUUM_AVAILABLE:
            try:
                pressure = self.continuum.get_memory_pressure()
                if pressure > 0.8:  # 80% threshold
                    self._log(f"  [memory] Pressure at {pressure * 100:.1f}%, running cleanup")
                    result = self.continuum.cleanup_expired_memories(archive=True)
                    if result["archived"] > 0 or result["deleted"] > 0:
                        self._log(
                            f"  [memory] Cleanup: archived={result['archived']}, deleted={result['deleted']}"
                        )
            except Exception as e:
                self._log(f"  [memory] Pressure check failed: {e}")

        # Update circuit breaker cooldowns at cycle start
        self.circuit_breaker.start_new_cycle()

        # Clear crux cache at cycle start to prevent context bleeding between cycles
        self._cached_cruxes = []

        self._log("\n" + "=" * 70)
        self._log(f"NOMIC CYCLE {self.cycle_count}")
        self._log(f"Started: {cycle_start.isoformat()}")
        self._log(f"Deadline: {cycle_deadline.isoformat()} ({self.max_cycle_seconds}s budget)")
        self._log("=" * 70)

        # Log circuit breaker status
        cb_status = self.circuit_breaker.get_status()
        if any(cb_status["cooldowns"].values()):
            self._log(
                f"  [circuit-breaker] Agents in cooldown: {[k for k, v in cb_status['cooldowns'].items() if v > 0]}"
            )

        # Security: Verify protected files haven't been tampered with
        all_ok, modified = verify_protected_files_unchanged(self.aragora_path)
        if not all_ok:
            self._log(f"  [SECURITY] Protected files modified since startup: {modified}")
            self._log("  [SECURITY] Aborting cycle — protected file integrity violation.")
            self._log("  If changes were intentional, restart the loop to re-baseline checksums.")
            return {
                "cycle": self.cycle_count,
                "started": cycle_start.isoformat(),
                "ended": datetime.now().isoformat(),
                "outcome": "protected_files_violation",
                "modified_files": modified,
            }

        # Emit cycle start event
        self._stream_emit(
            "on_cycle_start", self.cycle_count, self.max_cycles, cycle_start.isoformat()
        )
        self._dispatch_webhook("cycle_start", {"max_cycles": self.max_cycles})

        # Initialize ReplayRecorder for this cycle
        if REPLAY_AVAILABLE and ReplayRecorder:
            replay_dir = self.nomic_dir / "replays"
            replay_dir.mkdir(exist_ok=True)
            self.replay_recorder = ReplayRecorder(
                debate_id=f"nomic-cycle-{self.cycle_count}",
                topic=f"Nomic Loop Cycle {self.cycle_count}",
                proposal=self.initial_proposal or "Self-improvement",
                agents=[{"name": a, "model": a} for a in ["gemini", "claude", "codex", "grok"]],
                storage_dir=str(replay_dir),
            )
            self.replay_recorder.start()
            self._log(f"  [replay] Recording cycle {self.cycle_count}")

        # Initialize ArgumentCartographer for this cycle
        if CARTOGRAPHER_AVAILABLE and ArgumentCartographer:
            self.cartographer = ArgumentCartographer()
            self.cartographer.set_debate_context(
                debate_id=f"nomic-cycle-{self.cycle_count}",
                topic=self.initial_proposal or "Self-improvement",
            )
            self._log(f"  [viz] Cartographer ready for cycle {self.cycle_count}")

        # Phase 4: Initialize agent personas at cycle start
        self._init_agent_personas()

        # === SAFETY: Create backup before any changes ===
        backup_path = self._create_backup(f"cycle_{self.cycle_count}")
        # Store for timeout handler (run_cycle wrapper can access for rollback)
        self._cycle_backup_path = backup_path

        # === SAFETY: Verify Constitution signature (cryptographic safety) ===
        if self.constitution_verifier:
            if self.constitution_verifier.is_available():
                if not self.constitution_verifier.verify_signature():
                    self._log("[CRITICAL] Constitution signature invalid - cycle aborted")
                    self._log("  The constitution.json file may have been tampered with.")
                    self._log("  Re-sign with: python scripts/sign_constitution.py sign")
                    return {
                        "cycle": self.cycle_count,
                        "started": cycle_start.isoformat(),
                        "ended": datetime.now().isoformat(),
                        "outcome": "constitution_violation",
                        "error": "Constitution signature verification failed",
                    }
                self._log(
                    f"  [constitution] Signature verified (v{self.constitution_verifier.constitution.version})"
                )
            else:
                self._log(
                    "  [constitution] WARNING: Verifier not available — skipping signature check"
                )
                self._log(
                    "  [constitution] For autonomous runs, ensure constitution.json is signed"
                )
        else:
            self._log(
                "  [constitution] No verifier configured — running without constitution checks"
            )

        cycle_result = {
            "cycle": self.cycle_count,
            "started": cycle_start.isoformat(),
            "backup_path": str(backup_path),
            "phases": {},
        }

        self._save_state(
            {
                "phase": "cycle_start",
                "cycle": self.cycle_count,
                "backup_path": str(backup_path),
            }
        )

        # Phase 0: Context Gathering (Claude + Codex explore codebase)
        # This ensures Gemini and Grok get accurate context about existing features
        try:
            context_result = await self._run_with_phase_timeout(
                "context", self.phase_context_gathering()
            )
            # Validate and normalize phase result
            context_result = PhaseValidator.normalize_result("context", context_result)
            is_valid, validation_error = PhaseValidator.validate("context", context_result)
            if not is_valid:
                self._log(f"  [validation] Context result invalid: {validation_error}")
            cycle_result["phases"]["context"] = context_result
            codebase_context = context_result.get("codebase_context", "")
            self.phase_recovery.record_success("context")
        except PhaseError as e:
            self._log(f"PHASE TIMEOUT: Context gathering exceeded time limit: {e}")
            self.phase_recovery.record_failure("context", e)
            cycle_result["outcome"] = "context_timeout"
            cycle_result["error"] = str(e)
            return cycle_result
        except Exception as e:
            self._log(f"PHASE CRASH: Context gathering failed: {e}")
            self.phase_recovery.record_failure("context", e)
            cycle_result["outcome"] = "context_crashed"
            cycle_result["error"] = str(e)
            return cycle_result

        # === Deadline check after context gathering ===
        if not self._check_cycle_deadline(cycle_deadline, "context_gathering"):
            cycle_result["outcome"] = "timeout"
            cycle_result["timeout_phase"] = "context_gathering"
            return cycle_result

        # Phase 1: Debate (all agents, with gathered context)
        try:
            debate_result = await self._run_with_phase_timeout(
                "debate", self.phase_debate(codebase_context=codebase_context)
            )
            # Validate and normalize phase result
            debate_result = PhaseValidator.normalize_result("debate", debate_result)
            is_valid, validation_error = PhaseValidator.validate("debate", debate_result)
            if not is_valid:
                self._log(f"  [validation] Debate result invalid: {validation_error}")
            cycle_result["phases"]["debate"] = debate_result
            self.phase_recovery.record_success("debate")
        except PhaseError as e:
            self._log(f"PHASE TIMEOUT: Debate exceeded time limit: {e}")
            self.phase_recovery.record_failure("debate", e)
            cycle_result["outcome"] = "debate_timeout"
            cycle_result["error"] = str(e)
            return cycle_result
        except Exception as e:
            self._log(f"PHASE CRASH: Debate phase failed: {e}")
            self.phase_recovery.record_failure("debate", e)
            cycle_result["outcome"] = "debate_crashed"
            cycle_result["error"] = str(e)
            return cycle_result

        if not debate_result.get("consensus_reached"):
            self._log("No consensus reached. Ending cycle.")
            cycle_result["outcome"] = "no_consensus"
            self._record_cycle_outcome("no_consensus", {"phase": "debate"})
            return cycle_result

        # === Deadline check after debate ===
        if not self._check_cycle_deadline(cycle_deadline, "debate"):
            cycle_result["outcome"] = "timeout"
            cycle_result["timeout_phase"] = "debate"
            return cycle_result

        improvement = debate_result["final_answer"]
        self._log(f"\nConsensus improvement:\n{improvement}")  # Full content, no truncation

        # Phase 2: Design (with belief analysis from debate)
        belief_analysis = debate_result.get("belief_analysis")
        try:
            design_result = await self._run_with_phase_timeout(
                "design", self.phase_design(improvement, belief_analysis=belief_analysis)
            )
            # Validate and normalize phase result
            design_result = PhaseValidator.normalize_result("design", design_result)
            is_valid, validation_error = PhaseValidator.validate("design", design_result)
            if not is_valid:
                self._log(f"  [validation] Design result invalid: {validation_error}")
            cycle_result["phases"]["design"] = design_result
            self.phase_recovery.record_success("design")
        except PhaseError as e:
            self._log(f"PHASE TIMEOUT: Design exceeded time limit: {e}")
            self.phase_recovery.record_failure("design", e)
            cycle_result["outcome"] = "design_timeout"
            cycle_result["error"] = str(e)
            return cycle_result
        except Exception as e:
            self._log(f"PHASE CRASH: Design phase failed: {e}")
            self.phase_recovery.record_failure("design", e)
            cycle_result["outcome"] = "design_crashed"
            cycle_result["error"] = str(e)
            return cycle_result

        design = design_result.get("design", "")
        design_consensus = design_result.get("consensus_reached", False)
        design_confidence = design_result.get("confidence", 0.0)
        vote_counts = design_result.get("vote_counts", {})
        individual_proposals = design_result.get("individual_proposals", {})
        self._log(
            f"\nDesign complete (consensus={design_consensus}, confidence={design_confidence:.0%})"
        )

        # === Design Fallback: Multi-strategy recovery for no consensus ===
        if not design_consensus:
            self._log("  [fallback] No design consensus - attempting multi-strategy recovery...")
            candidate_design = None
            floor_breaker_method = None

            # Check if floor breaker should be activated
            at_floor = self._consensus_threshold_decay >= 2
            activate_floor_breaker = at_floor and self._floor_failure_count >= 2

            # Configurable guardrails to avoid aborting on low-consensus designs
            try:
                min_design_len = int(os.environ.get("NOMIC_DESIGN_MIN_LEN", "100"))
            except Exception:
                min_design_len = 100
            require_keywords = os.environ.get("NOMIC_DESIGN_REQUIRE_KEYWORDS", "1") != "0"
            force_proceed = os.environ.get("NOMIC_DESIGN_FORCE_PROCEED", "0") == "1"

            # Helper to validate design quality
            def is_viable_design(d: str) -> bool:
                if not d or len(d.strip()) < min_design_len:
                    return False
                if not require_keywords:
                    return True
                # Must contain actual implementation details
                keywords = ["file", "function", "class", "import", "def ", "async ", "return"]
                return any(kw in d.lower() for kw in keywords)

            # Strategy 1: Always try judge arbitration first (not just close contests)
            if individual_proposals and len(individual_proposals) >= 2:
                self._log(
                    "  [arbitration] Multiple proposals exist - invoking judge arbitration..."
                )
                try:
                    arbitrated = await self._arbitrate_design(individual_proposals, improvement)
                    if arbitrated and is_viable_design(arbitrated):
                        candidate_design = arbitrated
                        self._log(
                            f"  [arbitration] Judge synthesized viable design ({len(arbitrated)} chars)"
                        )
                except Exception as e:
                    self._log(f"  [arbitration] Judge arbitration failed: {e}")

            # Strategy 2: Use highest-voted viable proposal
            if not candidate_design and vote_counts and individual_proposals:
                sorted_votes = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
                for agent, votes in sorted_votes:
                    if agent in individual_proposals:
                        proposal = individual_proposals[agent]
                        if is_viable_design(proposal):
                            candidate_design = proposal
                            self._log(
                                f"  [fallback] Selected {agent}'s design with {votes} votes ({len(proposal)} chars)"
                            )
                            break
                        else:
                            self._log(
                                f"  [fallback] Skipped {agent}'s design (not viable: {len(proposal) if proposal else 0} chars)"
                            )

            # Strategy 3: Use any viable proposal regardless of votes
            if not candidate_design and individual_proposals:
                for agent, proposal in individual_proposals.items():
                    if is_viable_design(proposal):
                        candidate_design = proposal
                        self._log(f"  [fallback] Selected {agent}'s design (first viable found)")
                        break

            # Strategy 4: Use conditional design from counterfactual analysis if available
            conditional_design = design_result.get("conditional_design")
            if not candidate_design and conditional_design and is_viable_design(conditional_design):
                candidate_design = conditional_design
                self._log("  [fallback] Using conditional design from counterfactual analysis")

            # Strategy 5: Floor breaker escalation (emergency last resort)
            if not candidate_design and activate_floor_breaker and individual_proposals:
                self._log(
                    "  [fallback] Standard strategies exhausted - activating floor breaker..."
                )
                candidate_design, floor_breaker_method = await self._activate_floor_breaker(
                    individual_proposals, vote_counts, improvement
                )
                if candidate_design:
                    design_result["floor_breaker_used"] = True
                    design_result["floor_breaker_method"] = floor_breaker_method
                    self._log(f"  [floor-breaker] Design forced via: {floor_breaker_method}")

            # Strategy 6: Force proceed with best available material (configurable)
            if not candidate_design and force_proceed:
                if design and design.strip():
                    candidate_design = design
                    self._log(
                        f"  [force] Proceeding with non-consensus design from phase output ({len(design)} chars)"
                    )
                elif individual_proposals:
                    longest = max(
                        (p for p in individual_proposals.values() if p), key=len, default=None
                    )
                    if longest:
                        candidate_design = longest
                        self._log(
                            f"  [force] Proceeding with longest proposal ({len(longest)} chars)"
                        )

            # Final assignment
            if candidate_design:
                design = candidate_design
                self._log(f"  [fallback] Proceeding with recovered design ({len(design)} chars)")
            else:
                self._log("  [warning] No viable design recovered - skipping implementation")
                cycle_result["outcome"] = "design_no_consensus"
                cycle_result["vote_counts"] = vote_counts
                cycle_result["proposals_checked"] = (
                    len(individual_proposals) if individual_proposals else 0
                )
                cycle_result["floor_breaker_attempted"] = activate_floor_breaker
                self._record_cycle_outcome("design_no_consensus", {"vote_counts": vote_counts})
                return cycle_result
        elif design_confidence < 0.5:
            self._log("  [warning] Design has low confidence - proceeding with caution")

        # === Deadline check after design ===
        if not self._check_cycle_deadline(cycle_deadline, "design"):
            cycle_result["outcome"] = "timeout"
            cycle_result["timeout_phase"] = "design"
            return cycle_result

        # === Capture test baseline BEFORE implementation ===
        # This allows us to distinguish pre-existing failures from new regressions
        test_baseline = self._capture_test_baseline()
        cycle_result["test_baseline"] = test_baseline
        self._test_baseline = test_baseline  # Store for fix prompts

        # Phase 3: Implement (with circuit breaker integration)
        try:
            impl_result = await self._run_with_phase_timeout(
                "implement", self.phase_implement(design)
            )
            # Validate and normalize phase result
            impl_result = PhaseValidator.normalize_result("implement", impl_result)
            is_valid, validation_error = PhaseValidator.validate("implement", impl_result)
            if not is_valid:
                self._log(f"  [validation] Implement result invalid: {validation_error}")
            cycle_result["phases"]["implement"] = impl_result
            self.phase_recovery.record_success("implement")
            # Track success for primary implementation agent
            self.circuit_breaker.record_task_success("claude", "implement")
        except PhaseError as e:
            self._log(f"PHASE TIMEOUT: Implementation exceeded time limit: {e}")
            self.phase_recovery.record_failure("implement", e)
            self.circuit_breaker.record_task_failure("claude", "implement")
            cycle_result["outcome"] = "implement_timeout"
            cycle_result["error"] = str(e)
            return cycle_result
        except Exception as e:
            self._log(f"PHASE CRASH: Implementation phase failed: {e}")
            self.phase_recovery.record_failure("implement", e)
            self.circuit_breaker.record_task_failure("claude", "implement")
            cycle_result["outcome"] = "implement_crashed"
            cycle_result["error"] = str(e)
            return cycle_result

        if not impl_result.get("success"):
            self._log("Implementation failed. Ending cycle.")
            cycle_result["outcome"] = "implementation_failed"
            return cycle_result

        # === Deadline check after implementation ===
        if not self._check_cycle_deadline(cycle_deadline, "implement"):
            cycle_result["outcome"] = "timeout"
            cycle_result["timeout_phase"] = "implement"
            return cycle_result

        self._log("\nImplementation complete")
        self._log(f"Changed files:\n{impl_result.get('diff', 'No changes')}")

        # === Check evidence staleness after implementation ===
        if self.nomic_integration and self.claims_kernel:
            try:
                changed_files = self._get_git_changed_files()
                if changed_files:
                    staleness = await self.nomic_integration.check_staleness(
                        list(self.claims_kernel.claims.values()), changed_files
                    )
                    if staleness.stale_claims:
                        self._log(
                            f"  [staleness] {len(staleness.stale_claims)} claims have stale evidence"
                        )
                        for claim in staleness.stale_claims[:3]:  # Log first 3
                            self._log(f"    - {claim.statement[:60]}...")

                        # Queue ALL stale claims for next cycle's debate agenda
                        if not hasattr(self, "_pending_redebate_claims"):
                            self._pending_redebate_claims = []
                        self._pending_redebate_claims.extend(staleness.stale_claims)
                        self._log(
                            f"  [staleness] Queued {len(staleness.stale_claims)} claims for re-debate in next cycle"
                        )

                    if staleness.needs_redebate:
                        self._log("  [staleness] WARNING: High-severity stale evidence detected!")
                        cycle_result["needs_redebate"] = True
                        cycle_result["stale_claims"] = [c.claim_id for c in staleness.stale_claims]
            except Exception as e:
                self._log(f"  [staleness] Check failed: {e}")

        # === SAFETY: Verify protected files are intact ===
        self._log("\n  Checking protected files...")
        protected_issues = self._verify_protected_files()
        if protected_issues:
            self._log("  CRITICAL: Protected files damaged!")
            for issue in protected_issues:
                self._log(f"    - {issue}")

            # Preserve work before rollback
            preserve_branch = await self._preserve_failed_work(
                f"nomic-protected-damaged-{self.cycle_count}"
            )
            if preserve_branch:
                cycle_result["preserved_branch"] = preserve_branch
                self._log(f"  Work preserved in branch: {preserve_branch}")

            self._log("  Restoring from backup...")
            self._restore_backup(backup_path)
            subprocess.run(["git", "checkout", "."], cwd=self.aragora_path)
            cycle_result["outcome"] = "protected_files_damaged"
            cycle_result["protected_issues"] = protected_issues
            return cycle_result
        self._log("  All protected files intact")

        # === Iterative Review/Fix Cycle ===
        # Default: 3 fix attempts with all agents before rollback.
        # The fix cycle: Codex reviews -> Claude fixes -> Gemini reviews -> Grok attempts -> re-verify
        # Set ARAGORA_MAX_FIX_ITERATIONS to override (minimum 3 recommended for thorough fixing)
        max_fix_iterations = int(os.environ.get("ARAGORA_MAX_FIX_ITERATIONS", "3"))
        fix_iteration = 0
        cycle_result["fix_iterations"] = []
        best_test_score = 0  # Track progress: best passing test count
        best_test_output = ""
        iteration_times: list[float] = []  # Track actual iteration durations for budgeting

        while True:
            iteration_start = datetime.now()

            # Deadline enforcement: smart time budgeting based on actual iteration times
            if cycle_deadline:
                remaining_seconds = (cycle_deadline - datetime.now()).total_seconds()

                # Calculate estimated time for next iteration
                if iteration_times:
                    avg_iteration_time = sum(iteration_times) / len(iteration_times)
                    estimated_next = avg_iteration_time * 1.2  # 20% buffer
                else:
                    estimated_next = NOMIC_FIX_ITERATION_BUDGET  # Default budget

                # Check if we have enough time for another iteration
                time_needed = max(NOMIC_FIX_DEADLINE_BUFFER, estimated_next)

                if remaining_seconds < time_needed:
                    self._log(
                        f"\n  [deadline] {remaining_seconds:.0f}s remaining, need ~{time_needed:.0f}s - exiting fix loop"
                    )
                    cycle_result["outcome"] = "deadline_reached"
                    cycle_result["deadline_remaining_seconds"] = remaining_seconds
                    cycle_result["iteration_times"] = iteration_times
                    # Try to preserve any partial progress
                    if best_test_score > 0:
                        self._log(
                            f"  [deadline] Preserving partial progress: {best_test_score} passing tests"
                        )
                        cycle_result["partial_success"] = True
                        cycle_result["best_test_score"] = best_test_score
                    break

            # Phase 4: Verify (with timeout and recovery)
            try:
                # Use phase timeout to prevent indefinite hangs
                verify_result = await self._run_with_phase_timeout("verify", self.phase_verify())
                # Validate and normalize phase result
                verify_result = PhaseValidator.normalize_result("verify", verify_result)
                is_valid, validation_error = PhaseValidator.validate("verify", verify_result)
                if not is_valid:
                    self._log(f"  [validation] Verify result invalid: {validation_error}")
                cycle_result["phases"]["verify"] = verify_result
                self.phase_recovery.record_success("verify")
            except PhaseError as e:
                self._log(f"PHASE TIMEOUT: Verification phase exceeded timeout: {e}")
                self._log(
                    "  [SAFETY] Verify timeout triggers immediate rollback — no more fix iterations."
                )
                verify_result = {"all_passed": False, "checks": [], "error": str(e)}
                cycle_result["phases"]["verify"] = verify_result
                cycle_result["outcome"] = "verify_timeout"
                self.phase_recovery.record_failure("verify", e)
                if not self.disable_rollback and backup_path:
                    self._log("  Restoring from backup...")
                    self._restore_backup(backup_path)
                return cycle_result
            except Exception as e:
                self._log(f"PHASE CRASH: Verification phase failed: {e}")
                self._log(
                    "  [SAFETY] Verify crash triggers immediate rollback — no more fix iterations."
                )
                verify_result = {"all_passed": False, "checks": [], "error": str(e)}
                cycle_result["phases"]["verify"] = verify_result
                cycle_result["outcome"] = "verify_crash"
                self.phase_recovery.record_failure("verify", e)
                if not self.disable_rollback and backup_path:
                    self._log("  Restoring from backup...")
                    self._restore_backup(backup_path)
                return cycle_result
                self.phase_recovery.record_failure("verify", e)

            if verify_result.get("all_passed"):
                self._log("\nVerification passed!")
                break  # Success - exit the fix loop

            # Get test output for progress tracking
            test_output = ""
            for check in verify_result.get("checks", []):
                if check.get("check") == "tests":
                    test_output = check.get("output", "")
                    break

            # Track progress - count passing tests
            test_counts = self._count_test_results(test_output)
            current_score = test_counts["passed"]
            self._log(
                f"  Test results: {test_counts['passed']} passed, {test_counts['failed']} failed, {test_counts['errors']} errors"
            )

            # Update best score if improving
            if current_score > best_test_score:
                best_test_score = current_score
                best_test_output = test_output
                self._log(f"  Progress: New best score = {best_test_score} passing tests")
                # Commit partial progress when improving
                partial_commit = self._commit_partial_progress(
                    f"cycle-{self.cycle_count}-iter-{fix_iteration}-{best_test_score}passed"
                )
                if partial_commit:
                    self._log(f"  Partial progress committed: {partial_commit}")

            # Verification failed
            fix_iteration += 1

            # Track iteration duration for time budgeting
            iteration_duration = (datetime.now() - iteration_start).total_seconds()
            iteration_times.append(iteration_duration)

            iteration_result = {
                "iteration": fix_iteration,
                "verify_result": verify_result,
                "test_counts": test_counts,
                "duration_seconds": iteration_duration,
            }

            # TestFixer runs FIRST on every iteration (primary fix mechanism)
            if NOMIC_TESTFIXER_ENABLED:
                self._log("\n  TestFixer running automated fix loop...", agent="testfixer")
                testfixer_result = await self._run_testfixer_loop()
                iteration_result["testfixer"] = testfixer_result
                cycle_result["testfixer"] = testfixer_result

                if testfixer_result.get("status") == "success":
                    self._log("  TestFixer reported success; re-verifying...")
                    try:
                        verify_result = await self._run_with_phase_timeout(
                            "verify", self.phase_verify()
                        )
                        verify_result = PhaseValidator.normalize_result("verify", verify_result)
                        cycle_result["phases"]["verify"] = verify_result
                        iteration_result["verify_result"] = verify_result
                    except Exception as e:
                        self._log(f"  Re-verify crashed after TestFixer: {e}")
                        verify_result = {"all_passed": False, "checks": [], "error": str(e)}
                        cycle_result["phases"]["verify"] = verify_result
                        iteration_result["verify_result"] = verify_result

                    if verify_result.get("all_passed"):
                        cycle_result["fix_iterations"].append(iteration_result)
                        break

            if NOMIC_SICA_ENABLED and "sica" not in cycle_result:
                self._log("\n  SICA running automated improvement cycle...", agent="sica")
                sica_result = await self._run_sica_cycle()
                iteration_result["sica"] = sica_result
                cycle_result["sica"] = sica_result

                if sica_result.get("status") == "success":
                    self._log("  SICA reported success; re-verifying...")
                    try:
                        verify_result = await self._run_with_phase_timeout(
                            "verify", self.phase_verify()
                        )
                        verify_result = PhaseValidator.normalize_result("verify", verify_result)
                        cycle_result["phases"]["verify"] = verify_result
                        iteration_result["verify_result"] = verify_result
                    except Exception as e:
                        self._log(f"  Re-verify crashed after SICA: {e}")
                        verify_result = {"all_passed": False, "checks": [], "error": str(e)}
                        cycle_result["phases"]["verify"] = verify_result
                        iteration_result["verify_result"] = verify_result

                    if verify_result.get("all_passed"):
                        cycle_result["fix_iterations"].append(iteration_result)
                        break

            if fix_iteration > max_fix_iterations:
                # No more fix attempts allowed - try smart rollback first
                self._log(f"\n{'=' * 50}")
                self._log(f"MAX FIX ITERATIONS REACHED ({max_fix_iterations})")
                self._log(f"{'=' * 50}")

                if self.disable_rollback:
                    self._log(f"Verification failed after {fix_iteration - 1} fix attempts.")
                    self._log("  ROLLBACK DISABLED - keeping changes for inspection")
                    cycle_result["outcome"] = "verification_failed_no_rollback"
                    cycle_result["fix_iterations"].append(iteration_result)
                    return cycle_result

                # Try selective rollback first - only rollback files causing failures
                self._log("\n  Attempting selective rollback (preserve passing changes)...")
                failing_test_files = self._extract_failing_files(test_output)
                modified_files = self._get_modified_files()

                # Find files that might be causing the failures
                problematic_files = []
                for mod_file in modified_files:
                    # Check if this modified file is referenced in failing tests
                    if any(mod_file in ft or ft in mod_file for ft in failing_test_files):
                        problematic_files.append(mod_file)

                if problematic_files and len(problematic_files) < len(modified_files):
                    # Try selective rollback
                    self._log(
                        f"  Found {len(problematic_files)} potentially problematic files (keeping {len(modified_files) - len(problematic_files)} others)"
                    )
                    if self._selective_rollback(problematic_files):
                        # Re-verify after selective rollback
                        self._log("  Re-verifying after selective rollback...")
                        try:
                            re_verify = await self.phase_verify()
                        except Exception as e:
                            self._log(f"  Re-verify crashed: {e}")
                            re_verify = {"all_passed": False}
                        if re_verify.get("all_passed"):
                            self._log("  Selective rollback succeeded! Keeping partial changes.")
                            cycle_result["outcome"] = "partial_success"
                            cycle_result["selective_rollback"] = problematic_files
                            break
                        else:
                            self._log(
                                "  Selective rollback did not fix all issues, proceeding to full rollback"
                            )

                # Preserve work in a branch before full rollback
                preserve_branch = await self._preserve_failed_work(
                    f"nomic-failed-cycle-{self.cycle_count}"
                )
                if preserve_branch:
                    cycle_result["preserved_branch"] = preserve_branch
                    self._log(f"  Work preserved in branch: {preserve_branch}")

                # Track failure patterns for learning (Titans/MIRAS)
                if self.critique_store:
                    self._record_failure_patterns(test_output, cycle_result.get("design", ""))

                self._log(
                    f"Verification failed after {fix_iteration - 1} fix attempts. Rolling back."
                )
                self._restore_backup(backup_path)
                subprocess.run(["git", "checkout", "."], cwd=self.aragora_path)
                cycle_result["outcome"] = "verification_failed"
                cycle_result["best_test_score"] = best_test_score
                cycle_result["fix_iterations"].append(iteration_result)
                return cycle_result

            self._log(f"\n{'=' * 50}")
            self._log(f"FIX ITERATION {fix_iteration}/{max_fix_iterations}")
            self._log(f"{'=' * 50}")

            # test_output already extracted above for progress tracking

            # Step 1: Codex reviews the failed changes
            self._log("\n  Step 1: Codex analyzing test failures...", agent="codex")

            executor = HybridExecutor(self.aragora_path)
            diff = self._get_git_diff()

            # Get learned patterns for fix guidance (Titans/MIRAS)
            fix_patterns = self._format_successful_patterns(limit=3)
            avoid_patterns = self._format_failure_patterns(limit=3)

            # Get belief network cruxes for targeted fixing (P18: BeliefNetwork → Fix Guidance)
            crux_context = self._format_crux_context()

            # Extract failing test files for targeted fixing
            failing_test_files = self._extract_failing_files(test_output)
            failing_tests_info = ""
            if failing_test_files:
                failing_tests_info = "\n## Failing Test Files (FIX THESE)\n" + "\n".join(
                    f"- {f}" for f in failing_test_files[:5]
                )

            # Check if these are new regressions vs pre-existing failures
            baseline_info = ""
            if hasattr(self, "_test_baseline") and self._test_baseline:
                pre_existing = self._test_baseline.get("failing_tests", [])
                new_failures = self._extract_failing_tests(test_output)
                actually_new = [t for t in new_failures if t not in pre_existing]
                if pre_existing:
                    baseline_info = f"\n## Note: {len(pre_existing)} tests were already failing before implementation."
                if actually_new:
                    baseline_info += (
                        f"\nNEW REGRESSIONS ({len(actually_new)}): Focus on these:\n"
                        + "\n".join(f"- {t}" for t in actually_new[:5])
                    )

            review_prompt = f"""The following code changes caused test failures. Analyze and suggest fixes.
{failing_tests_info}
{baseline_info}

## Test Output
```
{test_output[:2000]}
```

## Code Changes (git diff)
```
{diff[:10000]}
```
{fix_patterns}
{avoid_patterns}
{crux_context}
Provide specific, actionable fixes. Focus on:
1. What exactly is broken? (Look at the failing test FILES listed above)
2. What specific code changes will fix it?
3. Are there missing imports or dependencies?
4. Learn from patterns above - apply what's worked, avoid what hasn't.
5. If pivotal claims are listed above, ensure your fix addresses them directly.
6. IMPORTANT: Only modify files related to the failing tests - don't change unrelated code.
"""
            review_result = await executor.review_with_codex(
                review_prompt, timeout=2400
            )  # 40 min for thorough review
            iteration_result["codex_review"] = review_result
            self._log("    Codex review complete", agent="codex")
            # Emit Codex's full review
            if review_result.get("review"):
                self._stream_emit(
                    "on_log_message",
                    review_result["review"],
                    level="info",
                    phase="fix",
                    agent="codex",
                )

            # Step 2: Claude fixes based on Codex review
            self._log("\n  Step 2: Claude applying fixes...", agent="claude")
            fix_prompt = f"""{SAFETY_PREAMBLE}

Fix the test failures in the codebase. Here's what went wrong and how to fix it:
{failing_tests_info}
{baseline_info}

## Test Output
```
{test_output[:1500]}
```

## Codex Analysis
{review_result.get("review", "No review available")[:2000]}

## Instructions
1. Read the failing tests FILES LISTED ABOVE to understand what's expected
2. Apply the minimal fixes needed to make tests pass
3. Do NOT remove or simplify existing functionality
4. Preserve all imports and dependencies
5. ONLY modify files that are related to the failing tests

Working directory: {self.aragora_path}
"""
            try:
                fix_agent = ClaudeAgent(
                    name="claude-fixer",
                    model="claude",
                    role="fixer",
                    timeout=1200,  # Doubled - fixes can be complex
                )
                # Use retry wrapper for resilience
                fix_result = await self._call_agent_with_retry(fix_agent, fix_prompt, max_retries=2)
                if "[Agent" in fix_result and "failed" in fix_result:
                    iteration_result["fix_error"] = fix_result
                    self._log(f"    Fix failed: {fix_result[:500]}", agent="claude")
                else:
                    iteration_result["fix_applied"] = True
                    self._log("    Fixes applied", agent="claude")
            except Exception as e:
                iteration_result["fix_error"] = str(e)
                self._log(f"    Fix failed: {e}", agent="claude")

            # Step 3: Gemini quick review (optional sanity check)
            self._log("\n  Step 3: Gemini quick review...", agent="gemini")
            gemini_issues = False
            try:
                gemini_review_prompt = f"""Quick review of fix attempt. Are these changes correct?

## Changes Made (by Claude)
{self._get_git_diff()[:2000]}

## Original Test Failures
{test_output[:500]}

Reply with: LOOKS_GOOD or ISSUES: <brief description>
"""
                # Use retry wrapper for resilience
                gemini_result = await self._call_agent_with_retry(
                    self.gemini, gemini_review_prompt, max_retries=2
                )
                iteration_result["gemini_review"] = (
                    gemini_result if gemini_result else "No response"
                )
                self._log(
                    f"    Gemini: {gemini_result if gemini_result else 'No response'}",
                    agent="gemini",
                )
                # Emit Gemini's full review
                if gemini_result and not ("[Agent" in gemini_result and "failed" in gemini_result):
                    self._stream_emit(
                        "on_log_message", gemini_result, level="info", phase="fix", agent="gemini"
                    )
                    # Check if Gemini found issues
                    gemini_issues = (
                        "ISSUES:" in gemini_result.upper() or "ISSUE:" in gemini_result.upper()
                    )
            except Exception as e:
                self._log(f"    Gemini review skipped: {e}", agent="gemini")

            # Step 4: Grok attempts fixes if Gemini found issues or Claude's fix failed
            if gemini_issues or iteration_result.get("fix_error"):
                self._log("\n  Step 4: Grok attempting alternative fix...", agent="grok")
                try:
                    grok_fix_prompt = f"""{SAFETY_PREAMBLE}

Previous fix attempt may have issues. Please apply an alternative fix for these test failures:
{failing_tests_info}
{baseline_info}

## Test Output
```
{test_output[:1500]}
```

## Previous Attempt Issues
{iteration_result.get("gemini_review", "Unknown issues")}
{iteration_result.get("fix_error", "")}

## Current Changes (may be partially correct)
{self._get_git_diff()[:2000]}

## Instructions
1. Analyze what the previous fix attempt got wrong
2. Apply a DIFFERENT approach to fix the tests
3. Focus on minimal, targeted changes to files related to FAILING TESTS above
4. Do NOT undo correct fixes, only fix what's still broken
5. ONLY modify files that are related to the failing tests

Working directory: {self.aragora_path}
"""
                    # Use retry wrapper for resilience
                    grok_result = await self._call_agent_with_retry(
                        self.grok, grok_fix_prompt, max_retries=2
                    )
                    iteration_result["grok_fix"] = grok_result if grok_result else "No response"
                    if grok_result and not ("[Agent" in grok_result and "failed" in grok_result):
                        self._log("    Grok fix applied", agent="grok")
                        self._stream_emit(
                            "on_log_message", grok_result, level="info", phase="fix", agent="grok"
                        )
                    else:
                        self._log(
                            f"    Grok fix failed: {grok_result if grok_result else 'No response'}",
                            agent="grok",
                        )
                except Exception as e:
                    self._log(f"    Grok fix skipped: {e}", agent="grok")
            else:
                self._log(
                    "\n  Step 4: Grok fix skipped (Gemini approved Claude's changes)", agent="grok"
                )

            cycle_result["fix_iterations"].append(iteration_result)

            # Re-check protected files after fix
            protected_issues = self._verify_protected_files()
            if protected_issues:
                self._log("  CRITICAL: Fix damaged protected files!")
                # Preserve work before rollback
                preserve_branch = await self._preserve_failed_work(
                    f"nomic-fix-damaged-{self.cycle_count}"
                )
                if preserve_branch:
                    cycle_result["preserved_branch"] = preserve_branch
                    self._log(f"  Work preserved in branch: {preserve_branch}")
                self._restore_backup(backup_path)
                subprocess.run(["git", "checkout", "."], cwd=self.aragora_path)
                cycle_result["outcome"] = "protected_files_damaged"
                return cycle_result

            self._log("\n  Re-running verification...")

        self._log("\nVerification passed")

        # Bridge to DecisionPlan for organizational learning (best-effort)
        await self._bridge_to_decision_plan(
            debate_result=cycle_result["phases"].get("debate", {}),
            impl_result=cycle_result["phases"].get("implement", {}),
            verify_result=verify_result,
        )

        # Phase 5: Commit (with recovery tracking)
        try:
            commit_result = await self._run_with_phase_timeout(
                "commit", self.phase_commit(improvement)
            )
            # Validate and normalize phase result
            commit_result = PhaseValidator.normalize_result("commit", commit_result)
            is_valid, validation_error = PhaseValidator.validate("commit", commit_result)
            if not is_valid:
                self._log(f"  [validation] Commit result invalid: {validation_error}")
            cycle_result["phases"]["commit"] = commit_result
            self.phase_recovery.record_success("commit")
        except PhaseError as e:
            self._log(f"PHASE TIMEOUT: Commit exceeded time limit: {e}")
            self.phase_recovery.record_failure("commit", e)
            cycle_result["outcome"] = "commit_timeout"
            cycle_result["error"] = str(e)
            # Don't return early - still want to log leaderboard etc.
            commit_result = {"committed": False, "reason": "timeout"}
            cycle_result["phases"]["commit"] = commit_result
        except Exception as e:
            self._log(f"PHASE CRASH: Commit phase failed: {e}")
            self.phase_recovery.record_failure("commit", e)
            cycle_result["outcome"] = "commit_crashed"
            cycle_result["error"] = str(e)
            commit_result = {"committed": False, "reason": str(e)}
            cycle_result["phases"]["commit"] = commit_result

        if commit_result.get("committed"):
            cycle_result["outcome"] = "success"
            self._log(f"\nCYCLE {self.cycle_count} COMPLETE - Changes committed!")
            publish_result = self._maybe_publish_commit(
                improvement, commit_result.get("commit_hash")
            )
            if publish_result:
                cycle_result["publish"] = publish_result

            # Auto-publish high-confidence improvements to marketplace
            debate_confidence = (
                cycle_result.get("phases", {}).get("debate", {}).get("confidence", 0.0)
            )
            marketplace_result = self._maybe_publish_to_marketplace(improvement, debate_confidence)
            if marketplace_result:
                cycle_result["marketplace"] = marketplace_result
        else:
            cycle_result["outcome"] = "not_committed"

        # Phase 5: Log ELO leaderboard every 5 cycles (P13: EloSystem)
        self._log_elo_leaderboard()

        # Phase 9: Log grounded persona insights every 2 cycles
        if self.cycle_count % 2 == 0:
            self._log_persona_insights()

        # Phase 6: Run pending verification proofs (P19: ProofExecutor)
        await self._run_verification_proofs()

        # Phase 6: Verify evidence chain integrity (P17: ProvenanceManager)
        self._verify_evidence_chain()

        # Phase 7: Check evidence staleness for living documents (P21: EnhancedProvenance)
        staleness_status = await self._check_evidence_staleness()
        if staleness_status:
            cycle_result["staleness"] = staleness_status

        cycle_result["duration_seconds"] = (datetime.now() - cycle_start).total_seconds()

        # Add phase duration metrics for analysis (Phase 4 enhancement)
        if hasattr(self, "_phase_metrics") and self._phase_metrics:
            cycle_result["phase_metrics"] = self._phase_metrics
            # Log summary of phase efficiency
            total_budget = sum(m["budget"] for m in self._phase_metrics.values())
            total_duration = sum(m["duration"] for m in self._phase_metrics.values())
            overall_efficiency = (total_duration / total_budget * 100) if total_budget > 0 else 0
            self._log(
                f"\n  [metrics] Cycle {self.cycle_count} phase efficiency: {overall_efficiency:.0f}% ({total_duration:.0f}s / {total_budget}s budget)"
            )

        # Record outcome for calibration and learning
        if self.outcome_tracker:
            try:
                # Extract test counts from verify result
                verify_phases = cycle_result.get("phases", {}).get("verify", {})
                tests_passed = 0
                tests_failed = 0
                for check in verify_phases.get("checks", []):
                    if check.get("check") == "tests":
                        output = check.get("output", "")
                        counts = self._count_test_results(output)
                        tests_passed = counts.get("passed", 0)
                        tests_failed = counts.get("failed", 0) + counts.get("errors", 0)
                        break

                # Get design confidence if available
                design_result = cycle_result.get("phases", {}).get("design", {})
                confidence = design_result.get("confidence", 0.5)

                outcome = _ConsensusOutcome(
                    debate_id=f"nomic-cycle-{self.cycle_count}",
                    consensus_text=design_result.get("consensus", "")[:500],
                    consensus_confidence=confidence,
                    implementation_attempted=True,
                    implementation_succeeded=cycle_result.get("outcome")
                    in ("success", "partial_success"),
                    tests_passed=tests_passed,
                    tests_failed=tests_failed,
                    rollback_triggered=cycle_result.get("outcome") == "verification_failed",
                    failure_reason=(
                        cycle_result.get("error")
                        if cycle_result.get("outcome") != "success"
                        else None
                    ),
                )
                self.outcome_tracker.record_outcome(outcome)
                self._log(
                    f"  [outcomes] Recorded outcome: {cycle_result.get('outcome')} (confidence={confidence:.2f})"
                )
            except Exception as e:
                self._log(f"  [outcomes] Failed to record: {e}")

        self.history.append(cycle_result)

        self._save_state(
            {
                "phase": "cycle_complete",
                "cycle": self.cycle_count,
                "outcome": cycle_result["outcome"],
                "duration_seconds": cycle_result["duration_seconds"],
            }
        )

        # Emit cycle end event
        self._stream_emit(
            "on_cycle_end",
            self.cycle_count,
            cycle_result.get("outcome") == "success",
            cycle_result["duration_seconds"],
            cycle_result.get("outcome", "unknown"),
        )
        self._dispatch_webhook(
            "cycle_end",
            {
                "outcome": cycle_result.get("outcome", "unknown"),
                "duration_seconds": cycle_result.get("duration_seconds", 0),
                "success": cycle_result.get("outcome") == "success",
            },
        )

        # Finalize ReplayRecorder
        if self.replay_recorder:
            try:
                outcome = cycle_result.get("outcome", "unknown")
                votes = {"success": 1 if outcome == "success" else 0}
                replay_path = self.replay_recorder.finalize(outcome, votes)
                self._log(f"  [replay] Cycle recorded to {replay_path}")
            except Exception as e:
                self._log(f"  [replay] Finalization error: {e}")
            finally:
                self.replay_recorder = None

        # Export ArgumentCartographer visualization
        if self.cartographer:
            try:
                # Export as Mermaid markdown
                mermaid_path = self.visualizations_dir / f"cycle-{self.cycle_count}.md"
                mermaid_content = self.cartographer.export_mermaid()
                with open(mermaid_path, "w") as f:
                    f.write(f"# Cycle {self.cycle_count} Debate Graph\n\n")
                    f.write("```mermaid\n")
                    f.write(mermaid_content)
                    f.write("\n```\n")

                # Export as JSON for analysis
                json_path = self.visualizations_dir / f"cycle-{self.cycle_count}.json"
                with open(json_path, "w") as f:
                    f.write(self.cartographer.export_json(include_full_content=True))

                stats = self.cartographer.get_statistics()
                self._log(
                    f"  [viz] Exported: {stats.get('total_nodes', 0)} nodes, {stats.get('total_edges', 0)} edges"
                )
            except Exception as e:
                self._log(f"  [viz] Export error: {e}")
            finally:
                self.cartographer = None

        # Store cycle outcome in ContinuumMemory for pattern learning
        if self.continuum and CONTINUUM_AVAILABLE:
            try:
                outcome = cycle_result.get("outcome", "unknown")
                improvement = (
                    cycle_result.get("phases", {}).get("debate", {}).get("final_answer", "")
                )
                is_success = outcome == "success"

                # Extract domain and participating agents for cross-cycle learning
                domain = self._detect_domain(improvement) if improvement else "general"
                debate_agents = []
                if cycle_result.get("phases", {}).get("debate", {}).get("agents"):
                    debate_agents = cycle_result["phases"]["debate"]["agents"]
                elif hasattr(self, "_last_debate_team"):
                    debate_agents = [a.name for a in getattr(self, "_last_debate_team", [])]

                # Store in SLOW tier (strategic learning across cycles)
                memory_id = f"cycle-{self.cycle_count}-{outcome}"
                self.continuum.add(
                    id=memory_id,
                    content=f"Cycle {self.cycle_count}: {outcome}. Domain: {domain}. Improvement: {improvement}",
                    tier=MemoryTier.SLOW,
                    importance=0.8 if is_success else 0.5,
                    metadata={
                        "cycle": self.cycle_count,
                        "outcome": outcome,
                        "duration_seconds": cycle_result.get("duration_seconds", 0),
                        "success": is_success,
                        "domain": domain,
                        "agents": debate_agents,
                        "phases_completed": list(cycle_result.get("phases", {}).keys()),
                    },
                )
                self._log(f"  [continuum] Stored cycle outcome in SLOW tier (domain={domain})")

                # Consolidate memory periodically (every 3 cycles for faster learning)
                if self.cycle_count % 3 == 0:
                    stats = self.continuum.consolidate()
                    self._log(f"  [continuum] Consolidated: {stats}")

                # Run MetaLearner to self-tune hyperparameters (every cycle)
                if self.meta_learner:
                    try:
                        metrics = self.meta_learner.evaluate_learning_efficiency(
                            self.continuum, cycle_result
                        )
                        adjustments = self.meta_learner.adjust_hyperparameters(metrics)
                        if adjustments:
                            # Get the actual numeric hyperparameters after adjustments
                            new_hyperparams = self.meta_learner.get_current_hyperparams()
                            # Apply adjustments to ContinuumMemory
                            if hasattr(self.continuum, "hyperparams") and isinstance(
                                self.continuum.hyperparams, dict
                            ):
                                self.continuum.hyperparams.update(new_hyperparams)
                            elif hasattr(self.continuum, "hyperparams"):
                                for key, value in new_hyperparams.items():
                                    if hasattr(self.continuum.hyperparams, key):
                                        setattr(self.continuum.hyperparams, key, value)
                            self._log(
                                f"  [meta] Applied hyperparameter adjustments: {list(adjustments.keys())}"
                            )

                            # Also apply relevant adjustments to next debate protocol
                            # MetaLearner's consensus_rate metric influences debate behavior
                            if hasattr(self, "debate_protocol") and metrics.consensus_rate < 0.5:
                                # Low consensus rate - allow more rounds for debate
                                if hasattr(self.debate_protocol, "rounds"):
                                    self.debate_protocol.rounds = min(
                                        5, self.debate_protocol.rounds + 1
                                    )
                                    self._log(
                                        f"  [meta] Increased debate rounds to {self.debate_protocol.rounds} (low consensus)"
                                    )
                    except Exception as e:
                        self._log(f"  [meta] MetaLearner error: {e}")
            except Exception as e:
                self._log(f"  [continuum] Storage error: {e}")

        # Prune stale patterns periodically (every 10 cycles)
        if self.critique_store and self.cycle_count % 10 == 0:
            try:
                if hasattr(self.critique_store, "prune_stale_patterns"):
                    pruned = self.critique_store.prune_stale_patterns(
                        max_age_days=90, min_success_rate=0.3, archive=True
                    )
                    if pruned > 0:
                        self._log(f"  [memory] Pruned {pruned} stale patterns (archived)")
            except Exception as e:
                self._log(f"  [memory] Pattern pruning error: {e}")

        # Cleanup old failed branches periodically (every 10 cycles)
        if self.cycle_count % 10 == 0:
            try:
                cleanup_result = self.cleanup_failed_branches(max_age_days=7)
                if cleanup_result["deleted"] > 0:
                    self._log(
                        f"  [cleanup] Removed {cleanup_result['deleted']} old failed branches "
                        f"(preserved {cleanup_result['preserved']})"
                    )
            except Exception as e:
                self._log(f"  [cleanup] Branch cleanup error: {e}")

        # Run robustness check on debate conclusions periodically
        if self.scenario_comparator and self.cycle_count % 5 == 0:
            try:
                debate_answer = (
                    cycle_result.get("phases", {}).get("debate", {}).get("final_answer", "")
                )
                if debate_answer:
                    robustness = await self._run_robustness_check(
                        task=debate_answer[:500], base_context=""
                    )
                    if robustness:
                        cycle_result["robustness"] = robustness
                        vuln_score = robustness.get("vulnerability_score", 0)
                        if vuln_score > 0.5:
                            self._log(
                                f"  [robustness] Warning: high vulnerability score {vuln_score:.2f}"
                            )
            except Exception as e:
                self._log(f"  [robustness] Check failed: {e}")

        # Manage agent bench based on calibration (every 25 cycles)
        if self.agent_selector and self.elo_system and self.cycle_count % 25 == 0:
            try:
                for agent_name in ["gemini", "claude", "codex", "grok"]:
                    if hasattr(self.elo_system, "get_expected_calibration_error"):
                        ece = self.elo_system.get_expected_calibration_error(agent_name)
                        if ece is None:
                            continue

                        bench_list = getattr(self.agent_selector, "bench", [])
                        if ece > 0.25 and agent_name not in bench_list:
                            if hasattr(self.agent_selector, "move_to_bench"):
                                self.agent_selector.move_to_bench(agent_name)
                                self._log(
                                    f"  [bench] Moved {agent_name} to probation (ECE: {ece:.2f})"
                                )

                        elif agent_name in bench_list:
                            rating = self.elo_system.get_rating(agent_name)
                            if ece < 0.15 and rating.elo > 1550:
                                if hasattr(self.agent_selector, "promote_from_bench"):
                                    self.agent_selector.promote_from_bench(agent_name)
                                    self._log(f"  [bench] Promoted {agent_name} back to active")
            except Exception as e:
                self._log(f"  [bench] Management error: {e}")

        # Run capability probes periodically (P6: CapabilityProber)
        await self._probe_agent_capabilities()

        # Phase 4: Agent Evolution - evolve prompts periodically (every 10 cycles)
        await self._evolve_agent_prompts()

        # Phase 4: Agent Evolution - run tournament periodically (every 20 cycles)
        await self._run_tournament_if_due()

        # Record cycle outcome for deadlock detection
        self._record_cycle_outcome(
            cycle_result.get("outcome", "unknown"),
            {
                "duration": cycle_result.get("duration_seconds"),
                "phases_completed": list(cycle_result.get("phases", {}).keys()),
            },
        )

        # Record cycle outcome in ContinuumMemory for cross-cycle learning
        if self.continuum:
            try:
                outcome = cycle_result.get("outcome", "unknown")
                cycle_id = f"cycle_{self.cycle_count}_{outcome}"
                phases_completed = list(cycle_result.get("phases", {}).keys())

                # Add memory entry for this cycle
                self.continuum.add(
                    id=cycle_id,
                    content=f"Cycle {self.cycle_count}: {outcome}. Phases completed: {', '.join(phases_completed)}",
                    importance=0.7 if outcome != "success" else 0.5,
                    metadata={
                        "cycle": self.cycle_count,
                        "outcome": outcome,
                        "phases": phases_completed,
                        "duration": cycle_result.get("duration_seconds"),
                    },
                )

                # Update with success/failure for surprise-based learning
                is_success = outcome == "success"
                self.continuum.update_outcome(cycle_id, success=is_success)
                self._log(f"  [continuum] Recorded cycle outcome: {outcome}")
            except Exception as e:
                self._log(f"  [continuum] Failed to record outcome: {e}")

        # Reset deadlock counter and consensus decay on success
        if cycle_result.get("outcome") == "success":
            self._deadlock_count = 0
            if self._consensus_threshold_decay > 0:
                self._log(
                    f"  [consensus] Resetting threshold decay (was level {self._consensus_threshold_decay})"
                )
                self._consensus_threshold_decay = 0
            # Reset floor breaker state
            if self._floor_failure_count > 0:
                self._log(
                    f"  [floor-breaker] Resetting floor failure count (was {self._floor_failure_count})"
                )
                self._floor_failure_count = 0
                self._floor_breaker_activated = False

        return cycle_result

    async def run(self):
        """Run the nomic loop until max cycles or interrupted."""
        self._log("=" * 70)
        self._log("ARAGORA NOMIC LOOP")
        self._log("Self-improving multi-agent system")
        self._log("=" * 70)
        self._log(f"Max cycles: {self.max_cycles}")
        self._log(f"Human approval required: {self.require_human_approval}")
        self._log(f"Auto-commit: {self.auto_commit}")
        if self.initial_proposal:
            self._log(f"Initial proposal: {self.initial_proposal}")
        self._log("=" * 70)
        self._log(f"Log file: {self.log_file}")
        self._log(f"State file: {self.state_file}")
        self._log(f"Backup dir: {self.backup_dir}")
        self._log("=" * 70)

        # Validate fallback configuration before starting
        self._validate_openrouter_fallback()

        # Run database maintenance on startup (WAL checkpoint, ANALYZE if due)
        try:
            from aragora.maintenance import run_startup_maintenance

            maintenance_results = run_startup_maintenance(self.nomic_dir)
            db_count = maintenance_results.get("stats", {}).get("database_count", 0)
            self._log(f"[maintenance] Startup complete: {db_count} databases checked")
        except Exception as e:
            self._log(f"[maintenance] Startup maintenance failed (non-fatal): {e}")

        _loop_start = datetime.now()

        try:
            while self.cycle_count < self.max_cycles:
                # Total execution timeout check
                if NOMIC_MAX_TOTAL_SECONDS > 0:
                    elapsed = (datetime.now() - _loop_start).total_seconds()
                    if elapsed > NOMIC_MAX_TOTAL_SECONDS:
                        self._log(
                            f"\n[SAFETY] Total timeout exceeded: {elapsed:.0f}s > {NOMIC_MAX_TOTAL_SECONDS}s"
                        )
                        self._log("  Aborting loop. Set NOMIC_MAX_TOTAL_SECONDS=0 to disable.")
                        break

                # Cost budget check
                if NOMIC_MAX_COST_USD > 0 and self._estimated_cost_usd > NOMIC_MAX_COST_USD:
                    self._log(
                        f"\n[SAFETY] Cost budget exceeded: ${self._estimated_cost_usd:.2f} > ${NOMIC_MAX_COST_USD:.2f}"
                    )
                    self._log("  Aborting loop. Set NOMIC_MAX_COST_USD=0 to disable.")
                    break

                result = await self.run_cycle()

                self._log(f"\nCycle {self.cycle_count} outcome: {result.get('outcome')}")

                if result.get("outcome") == "success":
                    self._log("Continuing to next cycle...")
                else:
                    self._log("Cycle did not complete successfully.")
                    if self.require_human_approval and not self.auto_commit:
                        # Check if auto-continue is enabled or running non-interactively
                        if NOMIC_AUTO_CONTINUE:
                            self._log("[auto] Auto-continuing (NOMIC_AUTO_CONTINUE=1)")
                        elif not sys.stdin.isatty():
                            self._log("[auto] Non-interactive mode detected, continuing...")
                        else:
                            try:
                                response = input("Continue to next cycle? [Y/n]: ")
                                if response.lower() == "n":
                                    break
                            except EOFError:
                                # Running in background/non-interactive mode
                                self._log("Non-interactive mode detected, continuing...")
                    else:
                        self._log("Auto-commit mode: continuing to next cycle...")

                await asyncio.sleep(2)

        except KeyboardInterrupt:
            self._log("\n\nNomic loop interrupted by user.")

        self._log("\n" + "=" * 70)
        self._log("NOMIC LOOP COMPLETE")
        self._log(f"Total cycles: {self.cycle_count}")
        self._log(
            f"Successful commits: {sum(1 for h in self.history if h.get('outcome') == 'success')}"
        )
        self._log("=" * 70)

        return self.history


# =============================================================================
# CLI Commands for backup management
# =============================================================================


def list_backups(aragora_path: Path) -> None:
    """List available backups."""
    backup_dir = aragora_path / ".nomic" / "backups"
    if not backup_dir.exists():
        print("No backups directory found.")
        return

    backups = sorted(backup_dir.iterdir(), reverse=True)
    if not backups:
        print("No backups found.")
        return

    print(f"Available backups in {backup_dir}:")
    for backup in backups:
        manifest_file = backup / "manifest.json"
        if manifest_file.exists():
            with open(manifest_file) as f:
                manifest = json.load(f)
            print(f"  {backup.name}")
            print(f"    Created: {manifest.get('created_at')}")
            print(f"    Reason: {manifest.get('reason')}")
            print(f"    Files: {len(manifest.get('files', []))}")
        else:
            print(f"  {backup.name} (no manifest)")


def restore_backup_cli(aragora_path: Path, backup_name: str = None) -> bool:
    """Restore from a specific backup or the latest one."""
    backup_dir = aragora_path / ".nomic" / "backups"

    if backup_name:
        backup_path = backup_dir / backup_name
        if not backup_path.exists():
            print(f"Backup not found: {backup_name}")
            return False
    else:
        # Find latest backup
        backups = sorted(backup_dir.iterdir(), reverse=True)
        backup_path = None
        for b in backups:
            if (b / "manifest.json").exists():
                backup_path = b
                break
        if not backup_path:
            print("No valid backups found.")
            return False

    manifest_file = backup_path / "manifest.json"
    with open(manifest_file) as f:
        manifest = json.load(f)

    print(f"Restoring backup: {backup_path.name}")
    print(f"  Created: {manifest.get('created_at')}")
    print(f"  Reason: {manifest.get('reason')}")

    restored = []
    for rel_path in manifest["files"]:
        src = backup_path / rel_path
        dst = aragora_path / rel_path
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(rel_path)
            print(f"  Restored: {rel_path}")

    print(f"\nRestored {len(restored)} files")
    return True


async def main():
    parser = argparse.ArgumentParser(description="Aragora Nomic Loop - Self-improvement cycle")

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run subcommand (default)
    run_parser = subparsers.add_parser("run", help="Run the nomic loop")
    run_parser.add_argument("--cycles", type=int, default=3, help="Maximum cycles to run")
    run_parser.add_argument(
        "--auto", action="store_true", help="Auto-commit without human approval"
    )
    run_parser.add_argument("--path", type=str, help="Path to aragora repository")
    run_parser.add_argument(
        "--proposal",
        "-p",
        type=str,
        help="Initial proposal for agents to consider (they may adopt, improve, or reject it)",
    )
    run_parser.add_argument(
        "--proposal-file",
        "-f",
        type=str,
        help="File containing initial proposal (alternative to --proposal)",
    )
    run_parser.add_argument(
        "--genesis",
        action="store_true",
        help="Enable genesis mode: fractal debates with agent evolution",
    )
    run_parser.add_argument(
        "--no-rollback",
        action="store_true",
        help="Disable rollback on verification failure (keep changes for inspection)",
    )
    run_parser.add_argument(
        "--no-stream",
        action="store_true",
        help="DISCOURAGED: Run without live streaming. Use 'python scripts/run_nomic_with_stream.py run' instead.",
    )

    # Pre-flight health check subcommand
    preflight_parser = subparsers.add_parser("preflight", help="Run pre-flight health checks only")
    preflight_parser.add_argument("--path", type=str, help="Path to aragora repository")

    # Backup management subcommands
    list_parser = subparsers.add_parser("list-backups", help="List available backups")
    list_parser.add_argument("--path", type=str, help="Path to aragora repository")

    restore_parser = subparsers.add_parser("restore", help="Restore from a backup")
    restore_parser.add_argument("--path", type=str, help="Path to aragora repository")
    restore_parser.add_argument("--backup", type=str, help="Specific backup name (default: latest)")

    # Legacy arguments for backward compatibility (when no subcommand specified)
    parser.add_argument("--cycles", type=int, default=3, help="Maximum cycles to run")
    parser.add_argument("--auto", action="store_true", help="Auto-commit without human approval")
    parser.add_argument("--path", type=str, help="Path to aragora repository")
    parser.add_argument(
        "--proposal",
        "-p",
        type=str,
        help="Initial proposal for agents to consider (they may adopt, improve, or reject it)",
    )
    parser.add_argument(
        "--proposal-file",
        "-f",
        type=str,
        help="File containing initial proposal (alternative to --proposal)",
    )
    parser.add_argument(
        "--genesis",
        action="store_true",
        help="Enable genesis mode: fractal debates with agent evolution",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="DISCOURAGED: Run without live streaming. Use 'python scripts/run_nomic_with_stream.py run' instead.",
    )

    args = parser.parse_args()

    if getattr(args, "auto", False) and not NOMIC_AUTO_COMMIT:
        print("=" * 70)
        print("AUTO-COMMIT SAFETY GATE")
        print("=" * 70)
        print("Auto-commit requires explicit opt-in via NOMIC_AUTO_COMMIT=1.")
        print("Set NOMIC_AUTO_COMMIT=1 and re-run with --auto if you intend")
        print("to allow unattended commits.")
        print("=" * 70)
        sys.exit(2)

    # Determine aragora path
    aragora_path = Path(args.path) if args.path else Path(__file__).parent.parent

    # Handle subcommands
    if args.command == "list-backups":
        list_backups(aragora_path)
        return

    if args.command == "restore":
        restore_backup_cli(aragora_path, getattr(args, "backup", None))
        return

    if args.command == "preflight":
        from scripts.nomic.preflight import preflight_cli

        success = preflight_cli(aragora_path)
        sys.exit(0 if success else 1)

    # Default: run the nomic loop (either "run" subcommand or no subcommand)
    no_stream = getattr(args, "no_stream", False)

    # ENFORCE STREAMING: Redirect to run_nomic_with_stream.py unless --no-stream is specified
    if not no_stream:
        print("=" * 70)
        print("STREAMING IS REQUIRED")
        print("=" * 70)
        print()
        print("The nomic loop MUST stream to aragora.ai for transparency.")
        print()
        print("Please use the streaming script instead:")
        print()
        print("    python scripts/run_nomic_with_stream.py run --cycles 3")
        print()
        print("This ensures that all nomic loop activity is visible in real-time")
        print("at https://aragora.ai")
        print()
        print("If you MUST run without streaming (not recommended), use:")
        print()
        print("    python scripts/nomic_loop.py run --no-stream --cycles 3")
        print()
        print("=" * 70)
        sys.exit(1)

    # If --no-stream is specified, show warning and continue
    print("=" * 70)
    print("WARNING: Running WITHOUT live streaming")
    print("=" * 70)
    print()
    print("Activity will NOT be visible at https://aragora.ai")
    print("This is strongly discouraged for transparency reasons.")
    print()
    print("Press Ctrl+C within 5 seconds to cancel...")
    print()
    try:
        await asyncio.sleep(5)
    except KeyboardInterrupt:
        print("\nCancelled. Use 'python scripts/run_nomic_with_stream.py run' instead.")
        sys.exit(0)
    print("Continuing without streaming...")
    print("=" * 70)
    print()

    # Check for OpenRouter fallback configuration
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("=" * 70)
        print("WARNING: OPENROUTER_API_KEY not set")
        print("=" * 70)
        print()
        print("OpenRouter fallback is DISABLED. If CLI agents hit rate limits,")
        print("they will fail instead of falling back to OpenRouter API.")
        print()
        print("To enable fallback, set OPENROUTER_API_KEY in your environment:")
        print()
        print("    export OPENROUTER_API_KEY=your_key_here")
        print()
        print("Get a key at: https://openrouter.ai/keys")
        print()
        print("=" * 70)
        print()

    initial_proposal = getattr(args, "proposal", None)
    if hasattr(args, "proposal_file") and args.proposal_file:
        with open(args.proposal_file) as f:
            initial_proposal = f.read()

    use_genesis = getattr(args, "genesis", False)

    # Run pre-flight checks before starting
    from scripts.nomic.preflight import run_preflight_checks

    print("Running pre-flight health checks...")
    preflight_report = run_preflight_checks(aragora_path)
    preflight_report.print_report()

    if not preflight_report.all_passed:
        print("Cannot start Nomic Loop: critical pre-flight checks failed.")
        print("Fix the issues above and try again.")
        print("\nTo run only pre-flight checks: python scripts/nomic_loop.py preflight")
        sys.exit(1)

    max_cycle_seconds = int(os.environ.get("NOMIC_MAX_CYCLE_SECONDS", "3600"))
    loop = NomicLoop(
        aragora_path=args.path,
        max_cycles=args.cycles,
        max_cycle_seconds=max_cycle_seconds,
        require_human_approval=not args.auto,
        auto_commit=args.auto,
        initial_proposal=initial_proposal,
        use_genesis=use_genesis,
    )

    if use_genesis:
        print("Genesis mode enabled: fractal debates with agent evolution")

    await loop.run()


if __name__ == "__main__":
    asyncio.run(main())
