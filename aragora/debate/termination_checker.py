"""
Debate termination checking.

Extracted from Arena orchestrator to improve code organization and testability.
Handles judge-based termination and early stopping via agent consensus.

RLM Enhancement (arXiv:2512.24601):
This module now supports the RLM "ready signal" pattern where termination
decisions include confidence scores. Instead of binary yes/no decisions,
agents can signal their confidence level, enabling adaptive termination:
- High confidence (>0.8): Ready to terminate
- Medium confidence (0.5-0.8): May benefit from more rounds
- Low confidence (<0.5): Should continue

Usage:
    checker = TerminationChecker(protocol, agents, generate_fn, task)

    # Traditional check (backwards compatible)
    should_continue, reason = await checker.check_judge_termination(round_num, proposals, context)

    # RLM-style check with confidence
    should_terminate, reason, confidence = await checker.check_judge_termination_with_confidence(
        round_num, proposals, context
    )
    if confidence >= 0.8:
        # High confidence - safe to terminate
        pass
"""

from __future__ import annotations

__all__ = [
    "TerminationChecker",
    "TerminationResult",
]

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.core import Agent, Message
    from aragora.protocols.debate import DebateProtocol

logger = logging.getLogger(__name__)

# RLM Ready Signal Configuration
RLM_HIGH_CONFIDENCE_THRESHOLD = 0.8  # Confidence needed for early termination
RLM_MIN_CONFIDENCE_FOR_STOP = 0.6  # Minimum confidence to consider stopping


@dataclass
class TerminationResult:
    """Result of a termination check with RLM-style confidence scoring.

    Based on the RLM paper's ready signal pattern where the model signals
    its confidence rather than just a binary decision.
    """

    should_terminate: bool
    """Whether the debate should terminate."""

    reason: str = ""
    """Explanation for the decision."""

    confidence: float = 0.5
    """Confidence in the decision (0.0 to 1.0)."""

    source: str = "unknown"
    """Source of the decision (judge, early_stop, agent_quorum)."""

    votes: dict[str, bool] | None = None
    """Individual agent votes if applicable."""

    @property
    def is_high_confidence(self) -> bool:
        """Check if this is a high-confidence decision."""
        return self.confidence >= RLM_HIGH_CONFIDENCE_THRESHOLD

    @property
    def should_consider_stopping(self) -> bool:
        """Check if termination should be considered (meets minimum threshold)."""
        return self.should_terminate and self.confidence >= RLM_MIN_CONFIDENCE_FOR_STOP


class TerminationChecker:
    """Checks if a debate should terminate early.

    Implements two termination strategies:
    1. Judge termination: A judge agent evaluates if debate is conclusive
    2. Early stopping: Agents vote on whether more debate would help

    Both strategies respect minimum round requirements and protocol settings.
    """

    def __init__(
        self,
        protocol: DebateProtocol,
        agents: list[Agent],
        generate_fn: Callable[[Agent, str, list[Message]], Any],
        task: str,
        select_judge_fn: Callable[[dict[str, str], list[Message]], Any] | None = None,
        hooks: dict[str, Callable] | None = None,
    ) -> None:
        """Initialize the termination checker.

        Args:
            protocol: Debate protocol with termination settings
            agents: List of participating agents
            generate_fn: Async function to generate agent responses
            task: The debate task description
            select_judge_fn: Async function to select a judge agent
            hooks: Optional hooks for termination events
        """
        self.protocol = protocol
        self.agents = agents
        self.generate_fn = generate_fn
        self.task = task
        self.select_judge_fn = select_judge_fn
        self.hooks = hooks or {}

    async def check_judge_termination(
        self,
        round_num: int,
        proposals: dict[str, str],
        context: list[Message],
    ) -> tuple[bool, str]:
        """Have a judge evaluate if the debate is conclusive.

        Args:
            round_num: Current round number
            proposals: Dict of agent name to proposal text
            context: Recent message context

        Returns:
            Tuple of (should_continue: bool, reason: str)
            - (True, "") means continue the debate
            - (False, reason) means stop with the given reason
        """
        if not self.protocol.judge_termination:
            return True, ""

        if round_num < self.protocol.min_rounds_before_judge_check:
            return True, ""

        if not self.select_judge_fn:
            logger.warning("Judge termination enabled but no judge selector provided")
            return True, ""

        # Select a judge
        judge = await self.select_judge_fn(proposals, context)

        prompt = f"""You are evaluating whether this multi-agent debate (decision stress-test) has reached a conclusive state.

Task: {self.task[:300]}

After {round_num} rounds of debate, the proposals are:
{chr(10).join(f"- {agent}: {prop[:200]}..." for agent, prop in proposals.items())}

Evaluate:
1. Have the key issues been thoroughly discussed?
2. Are there major unresolved disagreements that more debate could resolve?
3. Would additional rounds likely produce meaningful improvements?

Respond with:
CONCLUSIVE: <yes/no>
REASON: <brief explanation>"""

        try:
            response = await self.generate_fn(judge, prompt, context[-5:])
            lines = str(response).strip().split("\n")

            conclusive = False
            reason = ""

            for line in lines:
                if line.upper().startswith("CONCLUSIVE:"):
                    val = line.split(":", 1)[1].strip().lower()
                    conclusive = val in ("yes", "true", "1")
                elif line.upper().startswith("REASON:"):
                    reason = line.split(":", 1)[1].strip()

            if conclusive:
                logger.info("judge_termination judge=%s reason=%s", judge.name, reason[:100])
                # Emit event
                if "on_judge_termination" in self.hooks:
                    self.hooks["on_judge_termination"](judge.name, reason)
                return False, reason

        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.warning("Judge termination check timed out: %s", e)
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("Judge termination check failed to parse response: %s", e)
        except (RuntimeError, OSError, ConnectionError, TimeoutError, KeyError) as e:
            logger.exception("Unexpected error in judge termination check: %s", e)

        return True, ""

    async def check_judge_termination_with_confidence(
        self,
        round_num: int,
        proposals: dict[str, str],
        context: list[Message],
    ) -> TerminationResult:
        """Have a judge evaluate if the debate is conclusive with confidence scoring.

        RLM-enhanced version that returns a confidence score along with the decision,
        enabling adaptive termination based on judge certainty.

        Args:
            round_num: Current round number
            proposals: Dict of agent name to proposal text
            context: Recent message context

        Returns:
            TerminationResult with should_terminate, reason, and confidence
        """
        if not self.protocol.judge_termination:
            return TerminationResult(
                should_terminate=False,
                reason="Judge termination not enabled",
                confidence=1.0,
                source="config",
            )

        if round_num < self.protocol.min_rounds_before_judge_check:
            return TerminationResult(
                should_terminate=False,
                reason=f"Minimum rounds ({self.protocol.min_rounds_before_judge_check}) not reached",
                confidence=1.0,
                source="config",
            )

        if not self.select_judge_fn:
            logger.warning("Judge termination enabled but no judge selector provided")
            return TerminationResult(
                should_terminate=False,
                reason="No judge selector available",
                confidence=0.5,
                source="error",
            )

        # Select a judge
        judge = await self.select_judge_fn(proposals, context)

        # RLM-enhanced prompt that requests confidence score
        prompt = f"""You are evaluating whether this multi-agent debate has reached a conclusive state.

Task: {self.task[:300]}

After {round_num} rounds of debate, the proposals are:
{chr(10).join(f"- {agent}: {prop[:200]}..." for agent, prop in proposals.items())}

Evaluate:
1. Have the key issues been thoroughly discussed?
2. Are there major unresolved disagreements that more debate could resolve?
3. Would additional rounds likely produce meaningful improvements?

Respond in JSON format:
{{"conclusive": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}

Where confidence indicates how certain you are in your assessment:
- 0.9-1.0: Very confident, clear conclusion
- 0.7-0.9: Fairly confident, minor uncertainties
- 0.5-0.7: Moderately confident, some open questions
- Below 0.5: Uncertain, need more discussion"""

        try:
            response = await self.generate_fn(judge, prompt, context[-5:])
            response_str = str(response).strip()

            # Try to parse JSON response
            conclusive = False
            confidence = 0.5
            reason = ""

            # Extract JSON from response (may be surrounded by markdown)
            json_match = re.search(r"\{[^{}]*\}", response_str)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    conclusive = bool(data.get("conclusive", False))
                    confidence = float(data.get("confidence", 0.5))
                    confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]
                    reason = str(data.get("reason", ""))
                except (json.JSONDecodeError, ValueError) as e:
                    logger.debug("Failed to parse judge termination JSON: %s", e)

            # Fallback to text parsing if JSON failed
            if not reason:
                for line in response_str.split("\n"):
                    if "conclusive" in line.lower():
                        conclusive = any(w in line.lower() for w in ["yes", "true"])
                    if "reason" in line.lower():
                        reason = line.split(":", 1)[-1].strip() if ":" in line else line

            result = TerminationResult(
                should_terminate=conclusive,
                reason=reason,
                confidence=confidence,
                source="judge",
            )

            if conclusive and result.is_high_confidence:
                logger.info(
                    "judge_termination_confident judge=%s confidence=%.2f reason=%s",
                    judge.name,
                    confidence,
                    reason[:100],
                )
                if "on_judge_termination" in self.hooks:
                    self.hooks["on_judge_termination"](judge.name, reason)
            elif conclusive:
                logger.info(
                    "judge_termination_low_confidence judge=%s confidence=%.2f (below threshold)",
                    judge.name,
                    confidence,
                )

            return result

        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.warning("Judge termination check timed out: %s", e)
            return TerminationResult(
                should_terminate=False,
                reason=f"Timeout: {e}",
                confidence=0.0,
                source="timeout",
            )
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning("Judge termination check failed to parse response: %s", e)
            return TerminationResult(
                should_terminate=False,
                reason=f"Parse error: {e}",
                confidence=0.0,
                source="parse_error",
            )
        except (RuntimeError, OSError, ConnectionError, TimeoutError, KeyError) as e:
            logger.exception("Unexpected error in judge termination check: %s", e)
            return TerminationResult(
                should_terminate=False,
                reason=f"Error: {e}",
                confidence=0.0,
                source="error",
            )

    async def check_early_stopping(
        self,
        round_num: int,
        proposals: dict[str, str],
        context: list[Message],
    ) -> bool:
        """Check if agents want to stop debate early.

        Args:
            round_num: Current round number
            proposals: Dict of agent name to proposal text (unused, for consistency)
            context: Recent message context

        Returns:
            True if debate should continue, False if it should stop.
        """
        if not self.protocol.early_stopping:
            return True  # Continue

        if round_num < self.protocol.min_rounds_before_early_stop:
            return True  # Continue - haven't met minimum rounds

        # Ask each agent if they think more debate would help
        prompt = f"""After {round_num} round(s) of debate on this task:
Task: {self.task[:200]}

Current proposals have been critiqued and revised. Do you think additional debate
rounds would significantly improve the answer quality?

Respond with only: CONTINUE or STOP
- CONTINUE: More debate rounds would help refine the answer
- STOP: The proposals are mature enough, further debate is unlikely to help"""

        stop_votes = 0
        total_votes = 0

        tasks = [self.generate_fn(agent, prompt, context[-5:]) for agent in self.agents]
        try:
            # Use wait_for for Python 3.10 compatibility (asyncio.timeout is 3.11+)
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.protocol.round_timeout_seconds,
            )
        except asyncio.TimeoutError:
            # Timeout during early stopping check - continue debate (safe default)
            logger.warning(
                "Early stopping check timed out after %ss", self.protocol.round_timeout_seconds
            )
            return True

        for agent, result in zip(self.agents, results):
            if isinstance(result, BaseException):
                continue
            total_votes += 1
            response = str(result).strip().upper()
            if "STOP" in response and "CONTINUE" not in response:
                stop_votes += 1

        if total_votes == 0:
            return True  # Continue if voting failed

        stop_ratio = stop_votes / total_votes
        should_stop = stop_ratio >= self.protocol.early_stop_threshold

        if should_stop:
            logger.info("early_stopping votes=%s/%s", stop_votes, total_votes)
            # Emit early stop event
            if "on_early_stop" in self.hooks:
                self.hooks["on_early_stop"](round_num, stop_votes, total_votes)

        return not should_stop  # Return True to continue, False to stop

    async def should_terminate(
        self,
        round_num: int,
        proposals: dict[str, str],
        context: list[Message],
    ) -> tuple[bool, str]:
        """Check both termination conditions.

        Convenience method that checks both judge termination and early stopping.

        Args:
            round_num: Current round number
            proposals: Dict of agent name to proposal text
            context: Recent message context

        Returns:
            Tuple of (should_stop: bool, reason: str)
            - (True, reason) means stop the debate
            - (False, "") means continue
        """
        # Check judge termination first
        should_continue, reason = await self.check_judge_termination(round_num, proposals, context)
        if not should_continue:
            return True, reason

        # Check early stopping
        should_continue = await self.check_early_stopping(round_num, proposals, context)
        if not should_continue:
            return True, "Agents voted to stop early"

        return False, ""

    async def should_terminate_with_confidence(
        self,
        round_num: int,
        proposals: dict[str, str],
        context: list[Message],
        require_high_confidence: bool = True,
    ) -> TerminationResult:
        """Check termination conditions with RLM-style confidence scoring.

        Enhanced version that only terminates when confidence is high enough,
        implementing the RLM "ready signal" pattern.

        Args:
            round_num: Current round number
            proposals: Dict of agent name to proposal text
            context: Recent message context
            require_high_confidence: If True, only terminate on high confidence (>=0.8)

        Returns:
            TerminationResult with should_terminate, reason, confidence
        """
        # Check judge termination with confidence
        judge_result = await self.check_judge_termination_with_confidence(
            round_num, proposals, context
        )

        if judge_result.should_terminate:
            # Apply confidence requirement
            if require_high_confidence and not judge_result.is_high_confidence:
                logger.info(
                    "termination_rejected_low_confidence confidence=%.2f", judge_result.confidence
                )
                return TerminationResult(
                    should_terminate=False,
                    reason=f"Judge suggested termination but confidence ({judge_result.confidence:.2f}) below threshold",
                    confidence=judge_result.confidence,
                    source="judge_low_confidence",
                )
            return judge_result

        # Check early stopping (no confidence scoring yet, use vote ratio as proxy)
        should_continue = await self.check_early_stopping(round_num, proposals, context)
        if not should_continue:
            # Estimate confidence from early stopping
            # This could be enhanced to collect actual confidence from agents
            return TerminationResult(
                should_terminate=True,
                reason="Agents voted to stop early",
                confidence=self.protocol.early_stop_threshold,  # Use threshold as confidence
                source="early_stop",
            )

        return TerminationResult(
            should_terminate=False,
            reason="Continue debate",
            confidence=1.0,  # High confidence in continuing
            source="no_termination_trigger",
        )
