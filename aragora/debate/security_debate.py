"""
Security Debate Module.

Provides specialized debate functionality for security events.
Extracted from orchestrator.py for better modularity.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from aragora.agents.base import Agent
    from aragora.core_types import DebateResult
    from aragora.events.security_events import SecurityEvent

logger = logging.getLogger(__name__)


def _apply_security_confidence_threshold(
    result: DebateResult,
    confidence_threshold: float,
) -> DebateResult:
    """Reflect the security confidence threshold in the returned debate result."""
    threshold_met = result.confidence >= confidence_threshold
    metadata = dict(getattr(result, "metadata", {}) or {})
    metadata["security_confidence_threshold"] = confidence_threshold
    metadata["security_confidence_threshold_met"] = threshold_met
    result.metadata = metadata
    if not threshold_met:
        result.consensus_reached = False
    return result


def _security_safe_finding_dict(
    finding: Any,
    *,
    event_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize finding context without exposing secret material to model agents."""
    from aragora.events.security_events import redacted_security_finding_dict

    return redacted_security_finding_dict(finding, event_metadata=event_metadata)


async def run_security_debate(
    event: SecurityEvent,
    agents: list[Agent] | None = None,
    confidence_threshold: float = 0.7,
    timeout_seconds: int = 300,
    org_id: str = "default",
) -> DebateResult:
    """
    Run a multi-agent debate on a security event.

    This function creates a specialized debate focused on security remediation,
    using security-focused agents and protocols optimized for vulnerability analysis.

    Args:
        event: SecurityEvent containing findings to debate
        agents: Optional list of agents to use (defaults to security-auditor, compliance-auditor)
        confidence_threshold: Minimum consensus confidence required
        timeout_seconds: Maximum debate duration
        org_id: Organization ID for multi-tenancy

    Returns:
        DebateResult with remediation recommendations

    Example:
        from aragora.events.security_events import SecurityEvent, SecurityEventType
        from aragora.debate.security_debate import run_security_debate

        event = SecurityEvent(
            event_type=SecurityEventType.CRITICAL_CVE,
            severity=SecuritySeverity.CRITICAL,
            repository="my-repo",
            findings=[...],
        )
        result = await run_security_debate(event)
        print(result.final_answer)  # Remediation recommendations
    """
    from aragora.core_types import DebateResult, Environment
    from aragora.debate.orchestrator import Arena
    from aragora.debate.protocol import DebateProtocol
    from aragora.debate.security_question import build_security_debate_question

    # Build the debate question from security findings
    question = build_security_debate_question(event)
    event.debate_question = question
    event_metadata = getattr(event, "metadata", None)
    if not isinstance(event_metadata, dict) or len(event.findings) != 1:
        event_metadata = None

    # Create environment with security context
    env = Environment(
        task=question,
        context=json.dumps(
            {
                "security_event_id": event.id,
                "security_event_type": event.event_type.value,
                "repository": event.repository,
                "scan_id": event.scan_id,
                "source": event.source,
                "findings": [
                    _security_safe_finding_dict(f, event_metadata=event_metadata)
                    for f in event.findings
                ],
                "severity": event.severity.value,
            }
        ),
    )

    # Create security-focused protocol using centralized defaults
    from aragora.debate.config.defaults import DEBATE_DEFAULTS

    protocol = DebateProtocol(
        rounds=DEBATE_DEFAULTS.security_debate_rounds,
        consensus=cast(Any, DEBATE_DEFAULTS.security_debate_consensus),
        convergence_detection=True,
        convergence_threshold=DEBATE_DEFAULTS.convergence_threshold,
        timeout_seconds=timeout_seconds,
    )

    # Get security-focused agents if none provided
    if agents is None:
        agents = await get_security_debate_agents()

    if not agents:
        logger.warning("[security_debate] No agents available, returning empty result")
        return _apply_security_confidence_threshold(
            DebateResult(
                task=question,
                consensus_reached=False,
                confidence=0.0,
                messages=[],
                critiques=[],
                votes=[],
                rounds_used=0,
                final_answer="No agents available for security debate",
            ),
            confidence_threshold,
        )

    # Create and run the arena
    arena = Arena(
        environment=env,
        agents=agents,
        protocol=protocol,
        org_id=org_id,
    )

    logger.info(
        "[security_debate] Starting debate for event %s with %s findings",
        event.id,
        len(event.findings),
    )

    result = _apply_security_confidence_threshold(await arena.run(), confidence_threshold)

    logger.info(
        f"[security_debate] Debate {result.debate_id} completed: "
        f"consensus={result.consensus_reached}, confidence={result.confidence:.2f}"
    )

    event.debate_requested = True
    event.debate_id = result.debate_id

    return result


async def get_security_debate_agents() -> list[Agent]:
    """Get agents suitable for security debates.

    Returns agents with security expertise. Tries to use a diverse set
    of models for better debate quality.
    """

    agents: list[Agent] = []

    # Try to get security-focused agents
    try:
        from aragora.agents.factory import get_available_agents

        agents = await get_available_agents(
            capabilities=["security", "code_analysis"],
            min_count=2,
            max_count=4,
        )
        if agents:
            return agents
    except ImportError:
        logger.debug("Security agent pool not available")

    # Fallback: create agents directly
    try:
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agents.append(
            AnthropicAPIAgent(
                name="security-auditor",
                model="claude-opus-5",
            )
        )
    except (ImportError, Exception) as e:
        logger.debug("Could not create Anthropic agent: %s", e)

    try:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agents.append(
            OpenAIAPIAgent(
                name="compliance-auditor",
                model="gpt-4o",
            )
        )
    except (ImportError, Exception) as e:
        logger.debug("Could not create OpenAI agent: %s", e)

    return agents
