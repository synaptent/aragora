"""
Debate Metrics for Aragora.

Tracks debate outcomes, consensus, and confidence metrics.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from typing import Any
from collections.abc import Generator

from .api import ACTIVE_DEBATES
from .types import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

# =============================================================================
# Business Metrics (Debate Outcomes)
# =============================================================================

DEBATES_TOTAL = Counter(
    name="aragora_debates_completed_total",
    help="Total completed debates by status and domain",
    label_names=["status", "domain"],
)

CONSENSUS_REACHED = Counter(
    name="aragora_consensus_reached_total",
    help="Total consensus events by domain and type",
    label_names=["domain", "consensus_type"],  # consensus_type: majority, supermajority, unanimous
)

# Debate confidence score distribution
DEBATE_CONFIDENCE = Histogram(
    name="aragora_debate_confidence_score",
    help="Confidence score of debate conclusions",
    label_names=["domain"],
    buckets=[0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0],
)

# Agent participation and outcomes
AGENT_PARTICIPATION = Counter(
    name="aragora_agent_participation_total",
    help="Agent participation in debates by outcome",
    label_names=["agent_name", "outcome"],  # outcome: won, lost, abstained, contributed
)

# Last debate timestamp for staleness detection
LAST_DEBATE_TIMESTAMP = Gauge(
    name="aragora_last_debate_timestamp",
    help="Unix timestamp of the last completed debate",
    label_names=[],
)

DEBATE_DURATION = Histogram(
    name="aragora_debate_duration_seconds",
    help="Debate duration in seconds",
    label_names=["domain", "status"],
    buckets=[5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0],
)

CONSENSUS_QUALITY = Gauge(
    name="aragora_consensus_quality",
    help="Average consensus confidence by domain (0.0-1.0)",
    label_names=["domain"],
)

CIRCUIT_BREAKERS_OPEN = Gauge(
    name="aragora_circuit_breakers_open",
    help="Number of circuit breakers in open state",
    label_names=[],
)

AGENT_ERRORS = Counter(
    name="aragora_agent_errors_total",
    help="Agent error count by agent name and error type",
    label_names=["agent", "error_type"],
)

# Execution safety gate telemetry (signed receipts + diversity + taint)
EXECUTION_GATE_DECISIONS = Counter(
    name="aragora_execution_gate_decisions_total",
    help="Execution safety gate decisions by path/domain/decision",
    label_names=["path", "domain", "decision"],  # decision: allow, deny
)

EXECUTION_GATE_BLOCK_REASONS = Counter(
    name="aragora_execution_gate_blocks_total",
    help="Execution safety gate deny reason counts",
    label_names=["path", "domain", "reason"],
)

EXECUTION_GATE_PROVIDER_DIVERSITY = Histogram(
    name="aragora_execution_gate_provider_diversity",
    help="Provider diversity seen by execution safety gate",
    label_names=["path", "domain"],
    buckets=[1, 2, 3, 4, 5, 6, 8],
)

EXECUTION_GATE_MODEL_FAMILY_DIVERSITY = Histogram(
    name="aragora_execution_gate_model_family_diversity",
    help="Model family diversity seen by execution safety gate",
    label_names=["path", "domain"],
    buckets=[1, 2, 3, 4, 5, 6, 8],
)

EXECUTION_GATE_RECEIPT_VERIFICATION = Counter(
    name="aragora_execution_gate_receipt_verification_total",
    help="Signed consensus receipt verification outcomes",
    label_names=["path", "domain", "status"],  # status: verified, failed
)

EXECUTION_GATE_CONTEXT_TAINT = Counter(
    name="aragora_execution_gate_context_taint_total",
    help="Context taint signal seen by execution safety gate",
    label_names=["path", "domain", "state"],  # state: tainted, clean
)

EXECUTION_GATE_CORRELATED_RISK = Counter(
    name="aragora_execution_gate_correlated_risk_total",
    help="Correlated failure/collusion risk signals seen by execution safety gate",
    label_names=["path", "domain", "state"],  # state: detected, clear
)


# =============================================================================
# Helpers
# =============================================================================


def track_debate_outcome(
    status: str,
    domain: str,
    duration_seconds: float,
    consensus_reached: bool = False,
    confidence: float = 0.0,
    consensus_type: str = "majority",
) -> None:
    """Track debate outcome metrics.

    Args:
        status: Debate status (completed, timeout, error, aborted)
        domain: Debate domain (security, performance, testing, etc)
        duration_seconds: Time taken for the debate
        consensus_reached: Whether consensus was reached
        confidence: Consensus confidence (0.0-1.0)
        consensus_type: Type of consensus (majority, supermajority, unanimous)
    """
    import time as time_module

    # Increment debate counter
    DEBATES_TOTAL.inc(status=status, domain=domain)

    # Record duration
    DEBATE_DURATION.observe(duration_seconds, domain=domain, status=status)

    # Update last debate timestamp
    LAST_DEBATE_TIMESTAMP.set(time_module.time())

    # Track confidence distribution
    if confidence > 0:
        DEBATE_CONFIDENCE.observe(confidence, domain=domain)

    # Track consensus metrics
    if consensus_reached:
        CONSENSUS_REACHED.inc(domain=domain, consensus_type=consensus_type)
        # Update rolling average confidence (simplified: just set to latest)
        if confidence > 0:
            CONSENSUS_QUALITY.set(confidence, domain=domain)


def track_circuit_breaker_state(open_count: int) -> None:
    """Track number of open circuit breakers.

    Args:
        open_count: Number of circuit breakers currently in open state
    """
    CIRCUIT_BREAKERS_OPEN.set(open_count)


def track_agent_error(agent: str, error_type: str = "unknown") -> None:
    """Track an agent error with type classification.

    Args:
        agent: Name of the agent that encountered an error
        error_type: Type of error (timeout, rate_limit, auth, network, api, validation, unknown)
    """
    AGENT_ERRORS.inc(agent=agent, error_type=error_type)


def classify_agent_error(error: Exception) -> str:
    """Classify an exception into an error type for metrics.

    Args:
        error: The exception to classify

    Returns:
        Error type string for metrics labeling
    """
    error_class = type(error).__name__.lower()

    # Check for common error patterns
    if "timeout" in error_class:
        return "timeout"
    if "ratelimit" in error_class or "429" in str(error):
        return "rate_limit"
    if "auth" in error_class or "401" in str(error) or "403" in str(error):
        return "auth"
    if "connection" in error_class or "network" in error_class:
        return "network"
    if "validation" in error_class or "value" in error_class:
        return "validation"
    if "api" in error_class or "500" in str(error):
        return "api"

    return "unknown"


def track_agent_participation(agent_name: str, outcome: str) -> None:
    """Track an agent's participation in a debate.

    Args:
        agent_name: Name of the agent
        outcome: Participation outcome (won, lost, abstained, contributed)
    """
    AGENT_PARTICIPATION.inc(agent_name=agent_name, outcome=outcome)


def track_execution_gate_decision(
    gate: dict[str, Any] | None,
    *,
    path: str = "post_debate",
    domain: str = "general",
) -> None:
    """Track execution safety gate decision and diagnostics.

    Args:
        gate: Execution gate dict from ExecutionSafetyDecision.to_dict()
        path: Emission path (e.g., post_debate_coordinator, arena_auto_execute)
        domain: Debate domain for dashboard segmentation
    """
    if not isinstance(gate, dict):
        return

    decision = "allow" if bool(gate.get("allow_auto_execution", True)) else "deny"
    EXECUTION_GATE_DECISIONS.inc(path=path, domain=domain, decision=decision)

    # Reason-level deny telemetry
    reasons = gate.get("reason_codes", [])
    if isinstance(reasons, list):
        for reason in reasons:
            reason_label = str(reason or "unknown").strip().lower() or "unknown"
            EXECUTION_GATE_BLOCK_REASONS.inc(path=path, domain=domain, reason=reason_label)

    # Diversity observability
    try:
        provider_diversity = float(gate.get("provider_diversity", 0))
        if provider_diversity > 0:
            EXECUTION_GATE_PROVIDER_DIVERSITY.observe(
                provider_diversity,
                path=path,
                domain=domain,
            )
    except (TypeError, ValueError):
        pass

    try:
        model_family_diversity = float(gate.get("model_family_diversity", 0))
        if model_family_diversity > 0:
            EXECUTION_GATE_MODEL_FAMILY_DIVERSITY.observe(
                model_family_diversity,
                path=path,
                domain=domain,
            )
    except (TypeError, ValueError):
        pass

    receipt_verified = (
        bool(gate.get("receipt_signed"))
        and bool(gate.get("receipt_integrity_valid"))
        and bool(gate.get("receipt_signature_valid"))
    )
    EXECUTION_GATE_RECEIPT_VERIFICATION.inc(
        path=path,
        domain=domain,
        status="verified" if receipt_verified else "failed",
    )

    context_taint = bool(gate.get("context_taint_detected"))
    EXECUTION_GATE_CONTEXT_TAINT.inc(
        path=path,
        domain=domain,
        state="tainted" if context_taint else "clean",
    )

    correlated_risk = bool(gate.get("correlated_failure_risk")) or bool(
        gate.get("suspicious_unanimity_risk")
    )
    EXECUTION_GATE_CORRELATED_RISK.inc(
        path=path,
        domain=domain,
        state="detected" if correlated_risk else "clear",
    )


@contextmanager
def track_debate_execution(domain: str = "general") -> Generator[dict, None, None]:
    """Context manager to track debate execution metrics.

    Usage:
        with track_debate_execution(domain="security") as ctx:
            # run debate
            ctx["consensus"] = True
            ctx["confidence"] = 0.85
            ctx["status"] = "completed"

    Args:
        domain: The debate domain

    Yields:
        Dict to populate with outcome data (consensus, confidence, status)
    """
    start = time.perf_counter()
    ctx: dict[str, Any] = {
        "status": "completed",
        "consensus": False,
        "confidence": 0.0,
    }
    ACTIVE_DEBATES.inc()
    try:
        yield ctx
    except asyncio.TimeoutError:
        ctx["status"] = "timeout"
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        # Application-level errors (validation, type issues, missing keys/attrs)
        ctx["status"] = "error"
        logger.warning("Debate execution error: %s", e)
        raise
    except (OSError, ConnectionError) as e:
        # I/O and network-related errors
        ctx["status"] = "error"
        logger.warning("Debate I/O error: %s", e)
        raise
    except RuntimeError as e:
        # Runtime errors (async issues, state errors)
        ctx["status"] = "error"
        logger.warning("Debate runtime error: %s", e)
        raise
    finally:
        ACTIVE_DEBATES.dec()
        duration = time.perf_counter() - start
        track_debate_outcome(
            status=str(ctx["status"]),
            domain=domain,
            duration_seconds=duration,
            consensus_reached=bool(ctx["consensus"]),
            confidence=float(ctx["confidence"]),
        )


__all__ = [
    "DEBATES_TOTAL",
    "CONSENSUS_REACHED",
    "DEBATE_CONFIDENCE",
    "AGENT_PARTICIPATION",
    "LAST_DEBATE_TIMESTAMP",
    "DEBATE_DURATION",
    "CONSENSUS_QUALITY",
    "CIRCUIT_BREAKERS_OPEN",
    "AGENT_ERRORS",
    "EXECUTION_GATE_DECISIONS",
    "EXECUTION_GATE_BLOCK_REASONS",
    "EXECUTION_GATE_PROVIDER_DIVERSITY",
    "EXECUTION_GATE_MODEL_FAMILY_DIVERSITY",
    "EXECUTION_GATE_RECEIPT_VERIFICATION",
    "EXECUTION_GATE_CONTEXT_TAINT",
    "EXECUTION_GATE_CORRELATED_RISK",
    "track_debate_outcome",
    "track_circuit_breaker_state",
    "track_agent_error",
    "classify_agent_error",
    "track_agent_participation",
    "track_execution_gate_decision",
    "track_debate_execution",
]
