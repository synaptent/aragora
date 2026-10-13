"""
Arena-based validator for TestFixer proposed fixes.

Uses the Aragora Arena debate system to have multiple LLM agents
validate a proposed fix through structured debate. This ensures
fixes are cross-checked by multiple perspectives before being applied.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from aragora.agents.base import create_agent
from aragora.core import Agent
from aragora.core_types import Environment
from aragora.protocols.debate import DebateProtocol
from aragora.nomic.testfixer.analyzer import FailureAnalysis
from aragora.nomic.testfixer.proposer import PatchProposal

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of Arena-based fix validation."""

    # Overall verdict
    is_valid: bool
    confidence: float  # 0.0 to 1.0

    # Consensus details
    consensus_reached: bool
    agreement_ratio: float  # Fraction of agents that agreed

    # Agent feedback
    supporting_agents: list[str] = field(default_factory=list)
    dissenting_agents: list[str] = field(default_factory=list)
    critiques: list[str] = field(default_factory=list)

    # Suggested improvements
    improvements: list[str] = field(default_factory=list)

    # Debug info
    debate_rounds: int = 0
    raw_responses: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable summary."""
        status = "VALID" if self.is_valid else "INVALID"
        consensus = "consensus" if self.consensus_reached else "no consensus"
        return (
            f"{status} ({self.confidence:.0%} confidence, {consensus}, "
            f"{len(self.supporting_agents)} support / {len(self.dissenting_agents)} dissent)"
        )


@dataclass
class ArenaValidatorConfig:
    """Configuration for Arena-based validation."""

    # Agent types to use for validation
    agent_types: list[str] = field(
        default_factory=lambda: ["anthropic-api", "openai-api", "gemini-api"]
    )

    # Models to use (optional - uses defaults if None)
    models: dict[str, str] | None = None

    # Debate settings
    debate_rounds: int = 2
    consensus_threshold: float = 0.7  # Fraction for consensus

    # Validation thresholds
    min_confidence_to_pass: float = 0.6
    require_consensus: bool = False

    # Timeouts
    agent_timeout: float = 60.0
    debate_timeout: float = 180.0

    # Context limits
    max_context_chars: int = 50_000


class ArenaValidator:
    """Validates proposed fixes using Arena debate.

    Uses multiple LLM agents to review a proposed fix and reach
    consensus on whether it's correct and safe to apply.

    Example:
        config = ArenaValidatorConfig(
            agent_types=["anthropic-api", "openai-api"],
            debate_rounds=2,
        )
        validator = ArenaValidator(config)

        result = await validator.validate(proposal, analysis)

        if result.is_valid and result.confidence >= 0.7:
            proposal.apply_all(repo_path)
    """

    def __init__(self, config: ArenaValidatorConfig | None = None):
        """Initialize the Arena validator.

        Args:
            config: Validator configuration. Uses defaults if None.
        """
        self.config = config or ArenaValidatorConfig()
        self.agents: list[Agent] = []
        self._initialized = False

    def _ensure_agents(self) -> None:
        """Lazily initialize agents on first use."""
        if self._initialized:
            return

        for agent_type in self.config.agent_types:
            try:
                model = None
                if self.config.models:
                    model = self.config.models.get(agent_type)

                agent = create_agent(
                    model_type=agent_type,  # type: ignore[arg-type]
                    name=f"validator_{agent_type}",
                    role="critic",
                    model=model,
                    timeout=self.config.agent_timeout,
                )
                self.agents.append(agent)
                logger.info("arena_validator.agent_created type=%s", agent_type)
            except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
                logger.warning(
                    "arena_validator.agent_create_failed type=%s: %s",
                    agent_type,
                    e,
                )

        if not self.agents:
            raise RuntimeError("No agents could be initialized for validation")

        self._initialized = True

    def _truncate(self, text: str, limit: int) -> str:
        """Truncate text with middle ellipsis."""
        if len(text) <= limit:
            return text
        head = limit // 2 - 100
        tail = limit // 2 - 100
        return f"{text[:head]}\n\n[... {len(text) - limit} chars truncated ...]\n\n{text[-tail:]}"

    def _build_validation_prompt(
        self,
        proposal: PatchProposal,
        analysis: FailureAnalysis,
    ) -> str:
        """Build the validation debate prompt."""
        patches_summary = []
        for patch in proposal.patches[:5]:  # Limit to 5 patches
            patch_info = (
                f"**{patch.file_path}**:\n```\n{self._truncate(patch.patched_content, 5000)}\n```"
            )
            patches_summary.append(patch_info)

        patches_text = "\n\n".join(patches_summary)

        return f"""## Fix Validation Task

You are validating a proposed fix for a test failure. Review the fix carefully
and determine if it is:
1. **Correct**: Does it actually fix the root cause?
2. **Safe**: Does it introduce any new bugs, regressions, or security issues?
3. **Complete**: Does it handle all edge cases mentioned in the error?
4. **Appropriate**: Is this the right way to fix the issue (vs a workaround)?

## Original Failure

**Test:** {analysis.failure.test_name}
**File:** {analysis.failure.test_file}
**Error Type:** {analysis.failure.error_type}
**Error Message:** {analysis.failure.error_message}

**Root Cause Analysis:**
{analysis.root_cause}

## Proposed Fix

**Description:** {proposal.description}
**Confidence from proposer:** {proposal.post_debate_confidence:.0%}
**Fix Target:** {analysis.fix_target.value}

### Patches:

{patches_text}

## Your Task

Evaluate this fix and respond with:

1. **VERDICT**: "APPROVE" or "REJECT"
2. **CONFIDENCE**: Your confidence in this verdict (0.0 to 1.0)
3. **REASONING**: Why you approve or reject
4. **CONCERNS**: Any issues, edge cases, or risks you see
5. **IMPROVEMENTS**: Suggestions for making the fix better (if any)

Format your response as:

VERDICT: [APPROVE/REJECT]
CONFIDENCE: [0.0-1.0]
REASONING: [Your analysis]
CONCERNS: [Any issues]
IMPROVEMENTS: [Suggestions]
"""

    def _parse_validation_response(
        self,
        response: str,
        agent_name: str,
    ) -> dict[str, Any]:
        """Parse a validation response from an agent."""
        result = {
            "agent": agent_name,
            "approves": False,
            "confidence": 0.5,
            "reasoning": "",
            "concerns": [],
            "improvements": [],
            "raw": response,
        }

        # Parse verdict
        response_upper = response.upper()
        if "VERDICT:" in response_upper:
            verdict_line = response_upper.split("VERDICT:")[1].split("\n")[0].strip()
            result["approves"] = "APPROVE" in verdict_line
        elif "APPROVE" in response_upper[:200]:
            result["approves"] = True

        # Parse confidence
        import re

        conf_match = re.search(r"CONFIDENCE:\s*([0-9.]+)", response, re.IGNORECASE)
        if conf_match:
            try:
                result["confidence"] = max(0.0, min(1.0, float(conf_match.group(1))))
            except ValueError as e:
                logger.debug("Failed to parse numeric value: %s", e)

        # Parse reasoning
        if "REASONING:" in response.upper():
            reasoning_start = response.upper().index("REASONING:") + 10
            reasoning_end = len(response)
            for marker in ["CONCERNS:", "IMPROVEMENTS:"]:
                if marker in response.upper():
                    end_idx = response.upper().index(marker)
                    if end_idx > reasoning_start:
                        reasoning_end = min(reasoning_end, end_idx)
            result["reasoning"] = response[reasoning_start:reasoning_end].strip()

        # Parse concerns
        if "CONCERNS:" in response.upper():
            concerns_start = response.upper().index("CONCERNS:") + 9
            concerns_end = len(response)
            if "IMPROVEMENTS:" in response.upper():
                concerns_end = response.upper().index("IMPROVEMENTS:")
            concerns_text = response[concerns_start:concerns_end].strip()
            if concerns_text and concerns_text.lower() not in ["none", "n/a", "-"]:
                result["concerns"] = [concerns_text]

        # Parse improvements
        if "IMPROVEMENTS:" in response.upper():
            improvements_start = response.upper().index("IMPROVEMENTS:") + 13
            improvements_text = response[improvements_start:].strip()
            if improvements_text and improvements_text.lower() not in ["none", "n/a", "-"]:
                result["improvements"] = [improvements_text]

        return result

    async def _get_agent_validation(
        self,
        agent: Agent,
        prompt: str,
    ) -> dict[str, Any] | None:
        """Get validation from a single agent."""
        try:
            response = await asyncio.wait_for(
                agent.generate(prompt),
                timeout=self.config.agent_timeout,
            )
            return self._parse_validation_response(response, agent.name)

        except asyncio.TimeoutError:
            logger.warning(
                "arena_validator.timeout agent=%s",
                agent.name,
            )
            return None
        except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
            logger.warning(
                "arena_validator.agent_error agent=%s: %s",
                agent.name,
                e,
            )
            return None

    async def validate(
        self,
        proposal: PatchProposal,
        analysis: FailureAnalysis,
    ) -> ValidationResult:
        """Validate a proposed fix using Arena debate.

        Args:
            proposal: The proposed fix to validate
            analysis: The failure analysis that led to this fix

        Returns:
            ValidationResult with consensus information
        """
        self._ensure_agents()

        logger.info(
            "arena_validator.start proposal_id=%s num_agents=%d",
            proposal.id,
            len(self.agents),
        )

        # Build validation prompt
        prompt = self._build_validation_prompt(proposal, analysis)

        # Get validations from all agents in parallel
        validation_tasks = [self._get_agent_validation(agent, prompt) for agent in self.agents]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*validation_tasks),
                timeout=self.config.debate_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("arena_validator.debate_timeout")
            results = []

        # Filter successful validations
        validations = [r for r in results if r is not None]

        if not validations:
            logger.warning("arena_validator.no_valid_responses")
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                consensus_reached=False,
                agreement_ratio=0.0,
                critiques=["No agents provided valid responses"],
            )

        # Calculate consensus
        approvals = [v for v in validations if v["approves"]]
        rejections = [v for v in validations if not v["approves"]]

        agreement_ratio = len(approvals) / len(validations)
        consensus_reached = (
            agreement_ratio >= self.config.consensus_threshold
            or agreement_ratio <= (1 - self.config.consensus_threshold)
        )

        # Calculate overall confidence (weighted by agent confidence)
        if validations:
            total_confidence = sum(v["confidence"] for v in validations)
            avg_confidence = total_confidence / len(validations)

            # Boost confidence if there's consensus
            if consensus_reached:
                confidence = avg_confidence * 1.1
            else:
                confidence = avg_confidence * 0.8
            confidence = min(1.0, max(0.0, confidence))
        else:
            confidence = 0.0

        # Determine validity
        is_valid = len(approvals) > len(rejections)

        if self.config.require_consensus and not consensus_reached:
            is_valid = False
            confidence *= 0.7  # Penalize lack of consensus

        # Collect critiques and improvements
        all_critiques = []
        all_improvements = []
        raw_responses = {}

        for v in validations:
            if v.get("concerns"):
                all_critiques.extend(v["concerns"])
            if v.get("improvements"):
                all_improvements.extend(v["improvements"])
            if v.get("reasoning"):
                all_critiques.append(f"{v['agent']}: {v['reasoning'][:500]}")
            raw_responses[v["agent"]] = v.get("raw", "")

        result = ValidationResult(
            is_valid=is_valid,
            confidence=confidence,
            consensus_reached=consensus_reached,
            agreement_ratio=agreement_ratio,
            supporting_agents=[v["agent"] for v in approvals],
            dissenting_agents=[v["agent"] for v in rejections],
            critiques=all_critiques[:10],  # Limit
            improvements=all_improvements[:5],
            debate_rounds=1,  # Simple single-round for now
            raw_responses=raw_responses,
        )

        logger.info(
            "arena_validator.complete proposal_id=%s valid=%s confidence=%.2f consensus=%s",
            proposal.id,
            result.is_valid,
            result.confidence,
            result.consensus_reached,
        )

        return result

    async def validate_with_debate(
        self,
        proposal: PatchProposal,
        analysis: FailureAnalysis,
    ) -> ValidationResult:
        """Validate using full Arena debate (multiple rounds).

        This uses the actual Arena class for structured multi-round debate.
        More thorough but also more expensive and slower.

        Args:
            proposal: The proposed fix to validate
            analysis: The failure analysis that led to this fix

        Returns:
            ValidationResult with full debate information
        """
        from aragora.debate.orchestrator import Arena

        self._ensure_agents()

        logger.info(
            "arena_validator.debate_start proposal_id=%s rounds=%d",
            proposal.id,
            self.config.debate_rounds,
        )

        # Build the task for debate
        task = self._build_validation_prompt(proposal, analysis)

        # Create environment
        env = Environment(
            task=task,
            roles=["critic", "analyst", "judge"],
            max_rounds=self.config.debate_rounds,
            require_consensus=self.config.require_consensus,
            consensus_threshold=self.config.consensus_threshold,
        )

        # Create protocol
        protocol = DebateProtocol(
            rounds=self.config.debate_rounds,
            consensus="majority",
            consensus_threshold=self.config.consensus_threshold,
        )

        try:
            # Run Arena debate
            arena = Arena(
                environment=env,
                agents=self.agents,
                protocol=protocol,
            )

            debate_result = await asyncio.wait_for(
                arena.run(),
                timeout=self.config.debate_timeout,
            )

            # Convert debate result to ValidationResult
            is_valid = "APPROVE" in debate_result.final_answer.upper()
            confidence = debate_result.confidence or 0.5

            return ValidationResult(
                is_valid=is_valid,
                confidence=confidence,
                consensus_reached=debate_result.consensus_reached,
                agreement_ratio=confidence,
                supporting_agents=[
                    v.agent for v in debate_result.votes if "approve" in v.choice.lower()
                ]
                if debate_result.votes
                else [],
                dissenting_agents=[
                    v.agent for v in debate_result.votes if "reject" in v.choice.lower()
                ]
                if debate_result.votes
                else [],
                critiques=[c.reasoning for c in debate_result.critiques[:5]]
                if debate_result.critiques
                else [],
                debate_rounds=self.config.debate_rounds,
            )

        except asyncio.TimeoutError:
            logger.warning("arena_validator.arena_timeout")
            return ValidationResult(
                is_valid=False,
                confidence=0.0,
                consensus_reached=False,
                agreement_ratio=0.0,
                critiques=["Arena debate timed out"],
            )
        except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
            logger.warning(
                "arena_validator.arena_error: %s",
                e,
            )
            # Fall back to simple validation
            return await self.validate(proposal, analysis)
