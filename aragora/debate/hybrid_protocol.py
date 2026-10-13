"""
Hybrid Debate Protocol - Combine external agents with Aragora verification.

Provides enterprise-grade verification for external agent decisions:
- Get initial proposal from external framework (OpenClaw, CrewAI, etc.)
- Run adversarial debate on proposal with internal agents
- Generate cryptographic receipt for verified decisions

Example:
    >>> from aragora.agents.api_agents.external_framework import ExternalFrameworkAgent
    >>> from aragora.agents.api_agents.anthropic import AnthropicAgent
    >>> from aragora.debate.hybrid_protocol import HybridDebateProtocol, HybridDebateConfig
    >>>
    >>> external = ExternalFrameworkAgent(base_url="http://localhost:8000")
    >>> verifiers = [AnthropicAgent("claude-verifier-1"), AnthropicAgent("claude-verifier-2")]
    >>>
    >>> config = HybridDebateConfig(
    ...     external_agent=external,
    ...     verification_agents=verifiers,
    ...     consensus_threshold=0.7,
    ... )
    >>> protocol = HybridDebateProtocol(config)
    >>> result = await protocol.run_with_external("Design a rate limiter")
    >>> if result.verified:
    ...     print(f"Verified proposal: {result.proposal}")
    ...     print(f"Receipt: {result.receipt_hash}")
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.core_types import Agent, Message

if TYPE_CHECKING:
    from aragora.agents.api_agents.external_framework import ExternalFrameworkAgent

logger = logging.getLogger(__name__)


@dataclass
class HybridDebateConfig:
    """Configuration for hybrid debate.

    Attributes:
        external_agent: The external framework agent providing initial proposals.
        verification_agents: Internal agents used to verify/critique proposals.
        consensus_threshold: Fraction of verifiers that must approve (0.0-1.0).
        max_refinement_rounds: Maximum rounds to refine before giving up.
        require_receipt: Generate cryptographic receipt for audit trail.
        auto_execute_on_consensus: Execute the proposal if consensus is reached.
        critique_concurrency: Number of critiques to collect in parallel.
        refinement_feedback_limit: Max critiques to include in refinement prompt.
    """

    external_agent: ExternalFrameworkAgent
    verification_agents: list[Agent]
    consensus_threshold: float = 0.7
    max_refinement_rounds: int = 3
    require_receipt: bool = True
    auto_execute_on_consensus: bool = False
    critique_concurrency: int = 5
    refinement_feedback_limit: int = 5
    min_verification_quorum: int = 1  # Minimum critiques needed for valid consensus


@dataclass
class VerificationResult:
    """Result of proposal verification.

    Attributes:
        proposal: The final (possibly refined) proposal.
        verified: Whether consensus was reached.
        consensus_score: Fraction of verifiers that approved.
        critiques: All critiques collected during verification.
        refinements: List of refined proposals (if refinement occurred).
        receipt_hash: SHA-256 hash of receipt data (if require_receipt=True).
        debate_id: Unique identifier for this verification session.
        timestamp: When verification completed.
        rounds_used: Number of refinement rounds executed.
        external_agent: Name of the external agent that provided the proposal.
        verification_agent_names: Names of agents that participated in verification.
    """

    proposal: str
    verified: bool
    consensus_score: float
    critiques: list[str]
    refinements: list[str]
    receipt_hash: str | None = None
    debate_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    rounds_used: int = 0
    external_agent: str = ""
    verification_agent_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON export."""
        return {
            "debate_id": self.debate_id,
            "proposal": self.proposal,
            "verified": self.verified,
            "consensus_score": self.consensus_score,
            "critiques": self.critiques,
            "refinements": self.refinements,
            "receipt_hash": self.receipt_hash,
            "timestamp": self.timestamp.isoformat(),
            "rounds_used": self.rounds_used,
            "external_agent": self.external_agent,
            "verification_agent_names": self.verification_agent_names,
        }


class HybridDebateProtocol:
    """
    Combine external agents with Aragora verification.

    This protocol bridges external agent frameworks (OpenClaw, CrewAI, AutoGPT,
    LangChain agents, etc.) with Aragora's adversarial verification system.

    Workflow:
    1. Get initial proposal from external agent (OpenClaw, etc.)
    2. Run adversarial critique on proposal with internal verification agents
    3. If consensus NOT reached, refine proposal with debate feedback
    4. Repeat until consensus or max rounds
    5. Generate cryptographic receipt for audit trail

    The protocol ensures that decisions from external agents are vetted through
    Aragora's multi-agent verification before being acted upon.

    Example:
        >>> protocol = HybridDebateProtocol(config)
        >>> result = await protocol.run_with_external("Design API architecture")
        >>> if result.verified:
        ...     print(f"Consensus reached: {result.consensus_score:.0%}")
        ...     print(f"Receipt: {result.receipt_hash}")
    """

    # Pre-compiled consensus keyword sets for efficient lookup in _calculate_consensus
    _SUPPORTIVE_KEYWORDS: frozenset[str] = frozenset(
        {
            "agree",
            "correct",
            "good",
            "valid",
            "approve",
            "sound",
            "solid",
            "excellent",
            "well-reasoned",
            "comprehensive",
            "thorough",
            "effective",
            "appropriate",
        }
    )

    _CRITICAL_KEYWORDS: frozenset[str] = frozenset(
        {
            "disagree",
            "incorrect",
            "wrong",
            "invalid",
            "reject",
            "flawed",
            "missing",
            "inadequate",
            "problematic",
            "concern",
            "issue",
            "error",
            "weakness",
            "overlook",
        }
    )

    def __init__(self, config: HybridDebateConfig) -> None:
        """Initialize hybrid debate protocol.

        Args:
            config: Configuration including external agent and verification agents.

        Raises:
            ValueError: If no verification agents are provided or consensus_threshold
                is out of range.
            SSRFValidationError: If external agent URL is unsafe.
        """
        if not config.verification_agents:
            raise ValueError("At least one verification agent is required")

        if not (0.0 <= config.consensus_threshold <= 1.0):
            raise ValueError(
                f"consensus_threshold must be between 0.0 and 1.0, got {config.consensus_threshold}"
            )

        # Validate external agent URL if it's an ExternalFrameworkAgent
        if hasattr(config.external_agent, "base_url") and config.external_agent.base_url:
            from aragora.security.ssrf_protection import SSRFValidationError, validate_url

            result = validate_url(config.external_agent.base_url, resolve_dns=True)
            if not result.is_safe:
                raise SSRFValidationError(
                    f"External agent URL is unsafe: {result.error}",
                    url=config.external_agent.base_url,
                )

        self.config = config
        self.external_agent = config.external_agent
        self.verification_agents = config.verification_agents

    async def _check_agents_health(self) -> dict[str, bool]:
        """Check health of all agents in parallel.

        Queries the ``is_available`` method on the external agent and each
        verification agent concurrently.  Agents that do not expose
        ``is_available`` are silently skipped.

        Returns:
            Dict mapping agent name to health status (True = healthy).
        """
        agents_to_check: list[tuple[str, Any]] = []

        # External agent
        if hasattr(self.external_agent, "is_available"):
            agents_to_check.append(("external", self.external_agent))

        # Verification agents
        for agent in self.verification_agents:
            if hasattr(agent, "is_available"):
                name = agent.name if hasattr(agent, "name") else str(agent)
                agents_to_check.append((name, agent))

        if not agents_to_check:
            return {}

        async def _check_one(name: str, agent: Any) -> tuple[str, bool]:
            try:
                available = await agent.is_available()
                return name, available
            except (
                RuntimeError,
                ValueError,
                TypeError,
                AttributeError,
                OSError,
                ConnectionError,
                TimeoutError,
            ) as exc:
                logger.warning("Health check failed for %s: %s", name, exc)
                return name, False

        results = await asyncio.gather(
            *[_check_one(name, agent) for name, agent in agents_to_check],
            return_exceptions=True,
        )

        health: dict[str, bool] = {}
        for result in results:
            if isinstance(result, BaseException):
                # gather with return_exceptions=True wraps unexpected errors
                continue
            # result is tuple[str, bool] after BaseException check
            if not isinstance(result, tuple):
                raise TypeError(f"Expected tuple from health check, got {type(result).__name__}")
            name, available = result
            health[name] = available

        return health

    async def run_with_external(
        self,
        task: str,
        context: list[Message] | None = None,
        decision_id: str | None = None,
    ) -> VerificationResult:
        """
        Run hybrid debate with external proposal.

        Gets an initial proposal from the external agent, then runs adversarial
        verification with internal agents. If consensus is not reached, refines
        the proposal and tries again.

        Args:
            task: The task/question to address.
            context: Optional conversation context for additional grounding.
            decision_id: Optional ID for tracking (auto-generated if not provided).

        Returns:
            VerificationResult with verified proposal and optional receipt.

        Raises:
            Exception: If external agent fails to generate proposal.
        """
        debate_id = decision_id or str(uuid.uuid4())
        refinements: list[str] = []
        critiques_all: list[str] = []
        consensus_score = 0.0

        logger.info("Starting hybrid debate %s for task: %s...", debate_id[:8], task[:100])

        # 0. Parallel health check on all agents
        health = await self._check_agents_health()
        if health:
            unhealthy = [name for name, ok in health.items() if not ok]
            if unhealthy:
                logger.warning(
                    "[%s] Unhealthy agents detected before debate: %s",
                    debate_id[:8],
                    ", ".join(unhealthy),
                )
            healthy_count = sum(1 for ok in health.values() if ok)
            logger.debug(
                "[%s] Agent health: %d/%d healthy",
                debate_id[:8],
                healthy_count,
                len(health),
            )

        # 1. Get initial proposal from external agent
        try:
            proposal = await self.external_agent.generate(task, context)
            logger.debug("[%s] External proposal received: %s chars", debate_id[:8], len(proposal))
        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
            logger.error("[%s] External agent failed: %s", debate_id[:8], e)
            raise

        quorum_met = False

        for round_num in range(self.config.max_refinement_rounds):
            logger.debug(
                "[%s] Verification round %s/%s",
                debate_id[:8],
                round_num + 1,
                self.config.max_refinement_rounds,
            )

            # 2. Collect critiques from verification agents
            critiques = await self._collect_critiques(proposal, task, context)
            critiques_all.extend(critiques)

            # 2b. Check verification quorum
            if len(critiques) < self.config.min_verification_quorum:
                logger.warning(
                    "[%s] Insufficient critiques (%s/%s)",
                    debate_id[:8],
                    len(critiques),
                    self.config.min_verification_quorum,
                )
                # On final round with insufficient quorum, mark as unverified
                if round_num == self.config.max_refinement_rounds - 1:
                    break
                continue
            else:
                quorum_met = True

            # 3. Calculate consensus score
            consensus_score = await self._calculate_consensus(proposal, critiques)
            logger.debug("[%s] Consensus score: %.2f%%", debate_id[:8], consensus_score * 100)

            # 4. Check if consensus reached
            if consensus_score >= self.config.consensus_threshold:
                logger.info(
                    "[%s] Consensus reached (%.0f%%) after %s rounds",
                    debate_id[:8],
                    consensus_score * 100,
                    round_num + 1,
                )

                receipt_hash = None
                if self.config.require_receipt:
                    receipt_hash = self._generate_receipt(
                        proposal=proposal,
                        task=task,
                        consensus_score=consensus_score,
                        critiques=critiques,
                        decision_id=debate_id,
                    )

                return VerificationResult(
                    proposal=proposal,
                    verified=True,
                    consensus_score=consensus_score,
                    critiques=critiques_all,
                    refinements=refinements,
                    receipt_hash=receipt_hash,
                    debate_id=debate_id,
                    rounds_used=round_num + 1,
                    external_agent=self.external_agent.name,
                    verification_agent_names=[a.name for a in self.verification_agents],
                )

            # 5. If not consensus, refine proposal with feedback
            if round_num < self.config.max_refinement_rounds - 1:
                refined = await self._refine_proposal(
                    proposal=proposal,
                    task=task,
                    critiques=critiques,
                    context=context,
                )
                refinements.append(refined)
                proposal = refined
                logger.debug(
                    "[%s] Proposal refined, new length: %s chars", debate_id[:8], len(refined)
                )

        # Max rounds reached without consensus
        if not quorum_met:
            logger.warning(
                "[%s] Verification quorum never met across %s rounds",
                debate_id[:8],
                self.config.max_refinement_rounds,
            )
        else:
            logger.warning(
                "[%s] Max rounds (%s) reached without consensus (score: %.0f%%)",
                debate_id[:8],
                self.config.max_refinement_rounds,
                consensus_score * 100,
            )

        return VerificationResult(
            proposal=proposal,
            verified=False,
            consensus_score=consensus_score,
            critiques=critiques_all,
            refinements=refinements,
            debate_id=debate_id,
            rounds_used=self.config.max_refinement_rounds,
            external_agent=self.external_agent.name,
            verification_agent_names=[a.name for a in self.verification_agents],
        )

    async def _collect_critiques(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None,
    ) -> list[str]:
        """Collect critiques from all verification agents.

        Args:
            proposal: The proposal to critique.
            task: The original task description.
            context: Optional conversation context.

        Returns:
            List of critique strings from all verification agents.
        """
        critiques: list[str] = []

        # Run critiques concurrently
        async def get_critique(agent: Agent) -> str | None:
            try:
                critique = await agent.critique(
                    proposal=proposal,
                    task=task,
                    context=context,
                    target_agent=self.external_agent.name,
                )
                return critique.content
            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
                ConnectionError,
                TimeoutError,
            ) as e:
                logger.warning("Critique from %s failed: %s", agent.name, e)
                return None

        # Limit concurrency
        semaphore = asyncio.Semaphore(self.config.critique_concurrency)

        async def bounded_critique(agent: Agent) -> str | None:
            async with semaphore:
                return await get_critique(agent)

        tasks = [bounded_critique(agent) for agent in self.verification_agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, str):
                critiques.append(result)
            elif isinstance(result, Exception):
                logger.warning("Critique task failed: %s", result)

        return critiques

    async def _calculate_consensus(
        self,
        proposal: str,
        critiques: list[str],
    ) -> float:
        """Calculate consensus score from critiques.

        Uses keyword-based heuristic scoring. Critiques containing supportive
        language contribute positively, while critical language contributes
        negatively.

        Args:
            proposal: The proposal being evaluated.
            critiques: List of critique strings.

        Returns:
            Consensus score from 0.0 (no support) to 1.0 (full support).
        """
        if not critiques:
            logger.warning("No critiques received - defaulting to zero consensus (fail-safe)")
            return 0.0  # Fail-safe: no verification means no consensus

        supportive_count: float = 0.0
        for critique in critiques:
            critique_lower = critique.lower()
            support_score = sum(1 for k in self._SUPPORTIVE_KEYWORDS if k in critique_lower)
            critical_score = sum(1 for k in self._CRITICAL_KEYWORDS if k in critique_lower)

            # Net positive sentiment counts as supportive
            if support_score > critical_score:
                supportive_count += 1
            elif support_score == critical_score and support_score > 0:
                # Tie with some positive words = weak support
                supportive_count += 0.5

        return supportive_count / len(critiques)

    async def _refine_proposal(
        self,
        proposal: str,
        task: str,
        critiques: list[str],
        context: list[Message] | None,
    ) -> str:
        """Refine proposal based on critiques.

        Sends the critiques back to the external agent to generate an
        improved proposal that addresses the feedback.

        Args:
            proposal: Current proposal to refine.
            task: Original task description.
            critiques: Critiques to address.
            context: Optional conversation context.

        Returns:
            Refined proposal string.
        """
        # Limit critiques to avoid prompt overflow
        limited_critiques = critiques[: self.config.refinement_feedback_limit]

        critiques_text = "\n".join(f"- {c}" for c in limited_critiques)

        refinement_prompt = f"""Original task: {task}

Current proposal:
{proposal}

Critiques received from verification agents:
{critiques_text}

Please refine the proposal to address the critiques while maintaining the core solution approach. Focus on:
1. Addressing the specific issues raised
2. Incorporating valid suggestions
3. Maintaining clarity and completeness
4. Preserving the strengths of the original proposal

Provide only the refined proposal, without meta-commentary."""

        return await self.external_agent.generate(refinement_prompt, context)

    def _generate_receipt(
        self,
        proposal: str,
        task: str,
        consensus_score: float,
        critiques: list[str],
        decision_id: str,
    ) -> str:
        """Generate cryptographic receipt for verified decision.

        Creates a SHA-256 hash of the decision data for audit trail purposes.
        The receipt provides tamper-evident proof of the verification process.

        Args:
            proposal: The verified proposal.
            task: The original task.
            consensus_score: Final consensus score.
            critiques: Critiques collected during verification.
            decision_id: Unique decision identifier.

        Returns:
            SHA-256 hex digest of the receipt data.
        """
        receipt_data = {
            "decision_id": decision_id,
            "task": task,
            "proposal": proposal,
            "consensus_score": consensus_score,
            "num_critiques": len(critiques),
            "verification_agents": [a.name for a in self.verification_agents],
            "external_agent": self.external_agent.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "protocol_version": "1.0",
        }

        # Sort keys for deterministic hashing
        receipt_json = json.dumps(receipt_data, sort_keys=True)
        return hashlib.sha256(receipt_json.encode("utf-8")).hexdigest()


def create_hybrid_protocol(
    external_agent: ExternalFrameworkAgent,
    verification_agents: list[Agent],
    consensus_threshold: float = 0.7,
    max_refinement_rounds: int = 3,
    require_receipt: bool = True,
    auto_execute_on_consensus: bool = False,
) -> HybridDebateProtocol:
    """Factory function to create a hybrid debate protocol.

    Args:
        external_agent: External framework agent for proposals.
        verification_agents: Agents for verification.
        consensus_threshold: Required agreement level (0.0-1.0).
        max_refinement_rounds: Max refinement iterations.
        require_receipt: Generate audit receipt.
        auto_execute_on_consensus: Execute on success.

    Returns:
        Configured HybridDebateProtocol instance.

    Example:
        >>> protocol = create_hybrid_protocol(
        ...     external_agent=openclawAgent,
        ...     verification_agents=[claude1, claude2, gpt4],
        ...     consensus_threshold=0.8,
        ... )
    """
    config = HybridDebateConfig(
        external_agent=external_agent,
        verification_agents=verification_agents,
        consensus_threshold=consensus_threshold,
        max_refinement_rounds=max_refinement_rounds,
        require_receipt=require_receipt,
        auto_execute_on_consensus=auto_execute_on_consensus,
    )
    return HybridDebateProtocol(config)


__all__ = [
    "HybridDebateConfig",
    "HybridDebateProtocol",
    "VerificationResult",
    "create_hybrid_protocol",
]
