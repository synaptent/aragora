"""
Budget coordination for debate orchestration.

Provides budget enforcement before, during, and after debates to ensure
organizations stay within their allocated spending limits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aragora.logging_config import get_logger

if TYPE_CHECKING:
    from aragora.core import DebateResult

logger = get_logger(__name__)


class BudgetCoordinator:
    """Coordinates budget checks and cost recording for debates.

    This coordinator handles:
    - Pre-debate budget validation
    - Mid-debate budget checks for graceful pauses
    - Post-debate cost recording

    Args:
        org_id: Organization identifier for budget tracking
        user_id: Optional user identifier for per-user tracking
    """

    # Cost estimates for budget planning
    ESTIMATED_DEBATE_COST_USD = 0.10  # Conservative estimate for 3-round debate
    ESTIMATED_ROUND_COST_USD = 0.03  # Per-round estimate for mid-debate checks
    ESTIMATED_MESSAGE_COST_USD = 0.01  # Fallback per-message estimate

    def __init__(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        extensions: Any | None = None,
        autotuner: Any | None = None,
    ) -> None:
        """Initialize budget coordinator.

        Args:
            org_id: Organization identifier for budget tracking
            user_id: Optional user identifier for per-user tracking
            extensions: Optional ArenaExtensions for per-debate budget checks
            autotuner: Optional Autotuner for budget-aware debate optimization
        """
        self.org_id = org_id
        self.user_id = user_id
        self.extensions = extensions
        self.autotuner = autotuner
        self._debate_cost_limit_usd: float | None = None

    def set_debate_cost_limit(self, limit_usd: float | None) -> None:
        """Set a per-debate cost limit. None = no limit."""
        self._debate_cost_limit_usd = limit_usd

    def _estimate_debate_cost_so_far(self, rounds_completed: int) -> float:
        """Estimate cost incurred so far based on rounds completed."""
        return rounds_completed * self.ESTIMATED_ROUND_COST_USD

    def estimate_debate_cost(
        self,
        num_agents: int = 3,
        rounds: int = 3,
    ) -> float:
        """Estimate debate cost based on agent count and rounds.

        Uses per-round cost scaled by agent count for a more accurate
        estimate than the flat ESTIMATED_DEBATE_COST_USD constant.

        Args:
            num_agents: Number of agents participating
            rounds: Number of debate rounds

        Returns:
            Estimated cost in USD
        """
        return max(
            self.ESTIMATED_DEBATE_COST_USD,
            num_agents * rounds * self.ESTIMATED_MESSAGE_COST_USD * 2,  # propose + critique
        )

    def check_budget_before_debate(
        self,
        debate_id: str,
        num_agents: int = 0,
        rounds: int = 0,
    ) -> None:
        """Check if organization has sufficient budget before starting debate.

        Args:
            debate_id: Debate identifier for logging
            num_agents: Number of participating agents (for cost estimation)
            rounds: Number of debate rounds (for cost estimation)

        Raises:
            BudgetExceededError: If budget is exhausted and hard-stop is enforced.
        """
        if not self.org_id:
            return  # No org context - skip budget check

        estimated_cost = (
            self.estimate_debate_cost(num_agents, rounds)
            if num_agents > 0 and rounds > 0
            else self.ESTIMATED_DEBATE_COST_USD
        )

        try:
            from aragora.billing.budget_manager import BudgetAction, get_budget_manager

            manager = get_budget_manager()

            allowed, reason, action = manager.check_budget(
                org_id=self.org_id,
                estimated_cost_usd=estimated_cost,
                user_id=self.user_id or None,
            )

            if not allowed:
                logger.warning(
                    "budget_check_failed org_id=%s debate_id=%s reason=%s",
                    self.org_id,
                    debate_id,
                    reason,
                )
                from aragora.exceptions import BudgetExceededError

                raise BudgetExceededError(f"Budget limit reached for organization: {reason}")

            if action == BudgetAction.SOFT_LIMIT:
                logger.warning(
                    "budget_soft_limit_warning org_id=%s debate_id=%s reason=%s",
                    self.org_id,
                    debate_id,
                    reason,
                )

        except ImportError:
            # Budget manager not available - proceed without check
            logger.debug("Budget manager not available, skipping pre-debate check")

    def check_budget_mid_debate(
        self,
        debate_id: str,
        round_num: int,
        round_tokens: int = 0,
        round_messages: int = 0,
        support_scores: list[float] | None = None,
    ) -> tuple[bool, str]:
        """Check if organization has sufficient budget to continue debate mid-execution.

        Unlike check_budget_before_debate(), this method returns a tuple instead of
        raising an exception, allowing the debate to pause gracefully rather than
        fail abruptly.

        When an autotuner is configured, feeds round data via ``record_round()``
        and consults ``should_continue()`` to decide whether to stop early.

        Args:
            debate_id: Debate identifier for logging
            round_num: Current round number for logging
            round_tokens: Tokens used in the current round (for autotuner)
            round_messages: Messages sent in the current round (for autotuner)
            support_scores: Per-agent support scores for the round (for autotuner)

        Returns:
            Tuple of (allowed: bool, reason: str)
            - allowed: True if debate can continue, False if budget exceeded
            - reason: Human-readable reason if budget check failed
        """
        # Feed round data to autotuner if available
        if self.autotuner is not None:
            try:
                self.autotuner.record_round(
                    round_num=round_num,
                    tokens=round_tokens,
                    messages=round_messages,
                    support_scores=support_scores or [],
                )
                decision = self.autotuner.should_continue()
                if not decision.should_continue:
                    reason = (
                        f"Autotuner stop: {decision.stop_reason.value}"
                        if decision.stop_reason
                        else "Autotuner recommends stopping"
                    )
                    logger.info(
                        "autotuner_stop debate_id=%s round=%s reason=%s",
                        debate_id,
                        round_num,
                        reason,
                    )
                    return False, reason
            except (AttributeError, TypeError) as e:
                logger.debug("Autotuner check failed (continuing): %s", e)

        # Per-debate cost limit check (from DebateProtocol.debate_cost_limit_usd)
        if self._debate_cost_limit_usd is not None:
            estimated_cost = self._estimate_debate_cost_so_far(round_num)
            if estimated_cost >= self._debate_cost_limit_usd:
                reason = (
                    f"Debate cost limit reached: ~${estimated_cost:.2f} "
                    f"(limit: ${self._debate_cost_limit_usd:.2f})"
                )
                logger.info(
                    "debate_cost_limit_reached debate_id=%s round=%s cost=%.2f limit=%.2f",
                    debate_id,
                    round_num,
                    estimated_cost,
                    self._debate_cost_limit_usd,
                )
                return False, reason

        if not self.org_id:
            return True, ""  # No org context - allow continuation

        try:
            from aragora.billing.budget_manager import BudgetAction, get_budget_manager

            manager = get_budget_manager()

            allowed, reason, action = manager.check_budget(
                org_id=self.org_id,
                estimated_cost_usd=self.ESTIMATED_ROUND_COST_USD,
                user_id=self.user_id or None,
            )

            if not allowed:
                logger.warning(
                    "budget_exceeded_mid_debate org_id=%s debate_id=%s round=%s reason=%s",
                    self.org_id,
                    debate_id,
                    round_num,
                    reason,
                )
                return False, reason

            if action == BudgetAction.SOFT_LIMIT:
                logger.info(
                    "budget_soft_limit_mid_debate org_id=%s debate_id=%s round=%s reason=%s",
                    self.org_id,
                    debate_id,
                    round_num,
                    reason,
                )
                # Continue but warn - could be logged for alerting

        except ImportError:
            # Budget manager not available - skip org-level check
            pass
        except (ConnectionError, OSError, ValueError, TypeError, AttributeError) as e:
            # On any error, allow continuation (fail open for availability)
            logger.debug("Budget check error (continuing): %s", e)

        # Per-debate budget check via extensions
        if self.extensions is not None and hasattr(self.extensions, "check_debate_budget"):
            try:
                status = self.extensions.check_debate_budget(debate_id)
                if not status.get("allowed", True):
                    reason = status.get("message", "Per-debate budget exceeded")
                    logger.warning(
                        "per_debate_budget_exceeded debate_id=%s round=%s reason=%s",
                        debate_id,
                        round_num,
                        reason,
                    )
                    return False, reason
            except (ConnectionError, OSError, ValueError, TypeError, AttributeError) as e:
                logger.debug("Per-debate budget check error (continuing): %s", e)

        return True, ""

    def record_debate_cost(
        self,
        debate_id: str,
        result: DebateResult,
        extensions: Any | None = None,
    ) -> None:
        """Record actual debate cost against organization budget.

        Args:
            debate_id: Debate identifier
            result: Completed debate result with token usage info
            extensions: Optional extensions object with cost tracking
        """
        if not self.org_id:
            return  # No org context - skip cost recording

        try:
            from aragora.billing.budget_manager import get_budget_manager

            manager = get_budget_manager()

            # Calculate actual cost from usage metrics
            actual_cost_usd = self._calculate_actual_cost(result, extensions)

            if actual_cost_usd > 0:
                manager.record_spend(
                    org_id=self.org_id,
                    amount_usd=actual_cost_usd,
                    description=f"Debate: {result.task[:50] if result.task else 'Unknown'}",
                    debate_id=debate_id,
                    user_id=self.user_id or None,
                )
                logger.info(
                    "debate_cost_recorded org_id=%s debate_id=%s cost=$%.4f",
                    self.org_id,
                    debate_id,
                    actual_cost_usd,
                )

        except ImportError:
            logger.debug("Budget manager not available, skipping cost recording")

    def _calculate_actual_cost(
        self,
        result: DebateResult,
        extensions: Any | None = None,
    ) -> float:
        """Calculate actual cost from debate result and extensions.

        Priority:
        1. Extensions total_cost_usd attribute
        2. Result metadata total_cost_usd
        3. Fallback: message count * per-message estimate

        Args:
            result: Completed debate result
            extensions: Optional extensions with cost tracking

        Returns:
            Estimated cost in USD
        """
        # Check if extensions recorded usage
        if extensions is not None and hasattr(extensions, "total_cost_usd"):
            cost = getattr(extensions, "total_cost_usd", 0.0)
            if cost > 0:
                return cost

        # Check result metadata
        if hasattr(result, "metadata") and isinstance(result.metadata, dict):
            cost = float(result.metadata.get("total_cost_usd", 0.0))
            if cost > 0:
                return cost

        # Fallback: estimate from message count
        message_count = len(result.messages) if result.messages else 0
        critique_count = len(result.critiques) if result.critiques else 0
        return (message_count + critique_count) * self.ESTIMATED_MESSAGE_COST_USD
