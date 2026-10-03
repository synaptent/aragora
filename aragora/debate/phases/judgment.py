"""
Judgment phase logic extracted from Arena.

Provides utilities for:
- Judge selection based on various strategies
- Judge termination checks
- Synthesis and final verdict generation
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.core import Agent, Message
    from aragora.protocols.debate import DebateProtocol
    from aragora.ranking.elo import EloSystem

logger = logging.getLogger(__name__)


class JudgmentPhase:
    """Handles judge selection and judgment logic.

    Supports multiple judge selection strategies:
    - last: Use the synthesizer or last agent
    - random: Random selection from all agents
    - voted: Agents vote on who should judge
    - elo_ranked: Select highest ELO-rated agent
    - calibrated: Select based on composite ELO + calibration score
    """

    def __init__(
        self,
        protocol: DebateProtocol,
        agents: list[Agent],
        elo_system: EloSystem | None = None,
        calibration_weight_fn: Callable[[str], float] | None = None,
        composite_score_fn: Callable[[str], float] | None = None,
    ):
        """Initialize judgment phase.

        Args:
            protocol: Debate protocol with judge configuration
            agents: List of all agents in the debate
            elo_system: Optional ELO system for ranking-based selection
            calibration_weight_fn: Optional function to get calibration weight for agent
            composite_score_fn: Optional function to compute composite judge score
        """
        self.protocol = protocol
        self.agents = agents
        self.elo_system = elo_system
        self._get_calibration_weight = calibration_weight_fn
        self._compute_composite_score = composite_score_fn

    def _require_agents(self) -> list[Agent]:
        """Ensure agents list is not empty."""
        if not self.agents:
            raise ValueError("No agents available for judgment")
        return self.agents

    def select_judge(
        self,
        proposals: dict[str, str],
        context: list[Message],
        vote_for_judge_fn: Callable[..., Any] | None = None,
    ) -> Agent:
        """Select judge based on protocol.judge_selection setting.

        Args:
            proposals: Dict of agent name -> proposal text
            context: Conversation context
            vote_for_judge_fn: Optional async function for voted selection

        Returns:
            Selected judge agent
        """
        selection = self.protocol.judge_selection

        if selection == "last":
            return self._select_last()

        elif selection == "random":
            return random.choice(self._require_agents())  # noqa: S311 -- non-security random selection

        elif selection == "voted":
            # Voting requires async - return None to signal caller should use async method
            if vote_for_judge_fn:
                # This is a sync method, can't await
                logger.warning("voted selection requires async; falling back to random")
            return random.choice(self._require_agents())  # noqa: S311 -- non-security random selection

        elif selection == "elo_ranked":
            return self._select_elo_ranked()

        elif selection == "calibrated":
            return self._select_calibrated()

        # Default fallback
        return random.choice(self._require_agents())  # noqa: S311 -- non-security random selection

    def _select_last(self) -> Agent:
        """Select synthesizer or last agent as judge."""
        synthesizers = [a for a in self.agents if a.role == "synthesizer"]
        return synthesizers[0] if synthesizers else self._require_agents()[-1]

    def _select_elo_ranked(self) -> Agent:
        """Select highest ELO-rated agent as judge."""
        if not self.elo_system:
            logger.warning("elo_ranked judge selection requires elo_system; falling back to random")
            return random.choice(self._require_agents())  # noqa: S311 -- non-security random selection

        agent_names = [a.name for a in self.agents]

        try:
            leaderboard = self.elo_system.get_leaderboard(limit=len(agent_names))
            for entry in leaderboard:
                if entry.agent_name in agent_names:
                    top_agent_name = entry.agent_name
                    top_elo = entry.elo
                    judge = next((a for a in self.agents if a.name == top_agent_name), None)
                    if judge:
                        logger.debug("Selected %s (ELO: %s) as judge", top_agent_name, top_elo)
                        return judge
        except Exception as e:  # noqa: BLE001
            logger.warning("ELO query failed: %s; falling back to random", e)

        return random.choice(self._require_agents())  # noqa: S311 -- non-security random selection

    def _select_calibrated(self) -> Agent:
        """Select based on composite score (ELO + calibration)."""
        if not self.elo_system:
            logger.warning("calibrated judge selection requires elo_system; falling back to random")
            return random.choice(self._require_agents())  # noqa: S311 -- non-security random selection

        if not self._compute_composite_score:
            logger.warning(
                "calibrated selection requires composite_score_fn; falling back to elo_ranked"
            )
            return self._select_elo_ranked()

        agent_scores = []
        for agent in self.agents:
            try:
                score = self._compute_composite_score(agent.name)
                agent_scores.append((agent, score))
            except (ValueError, KeyError, TypeError) as e:  # noqa: BLE001
                logger.debug("Score computation failed for %s: %s", agent.name, e)

        if agent_scores:
            agent_scores.sort(key=lambda x: x[1], reverse=True)
            best_agent, best_score = agent_scores[0]
            logger.debug(f"Selected {best_agent.name} (composite: {best_score:.3f}) as judge")
            return best_agent

        return random.choice(self._require_agents())  # noqa: S311 -- non-security random selection

    def should_terminate(
        self,
        round_num: int,
        proposals: dict[str, str],
        judge_response: str | None = None,
    ) -> tuple[bool, str]:
        """Determine if the debate should terminate based on judge evaluation.

        Args:
            round_num: Current round number
            proposals: Current proposals
            judge_response: Optional response from judge evaluation

        Returns:
            Tuple of (should_continue: bool, reason: str)
        """
        if not self.protocol.judge_termination:
            return True, ""

        if round_num < self.protocol.min_rounds_before_judge_check:
            return True, ""

        if not judge_response:
            return True, ""

        # Parse judge response for conclusive determination
        lines = judge_response.strip().split("\n")
        conclusive = False
        reason = ""

        for line in lines:
            line_lower = line.lower()
            if "conclusive:" in line_lower:
                conclusive = "yes" in line_lower
            elif "reason:" in line_lower:
                reason = line.split(":", 1)[1].strip() if ":" in line else ""

        if conclusive:
            return False, reason  # Stop debate
        return True, ""  # Continue debate

    def get_judge_stats(self, judge: Agent) -> dict[str, Any]:
        """Get statistics about the selected judge.

        Args:
            judge: The selected judge agent

        Returns:
            Dict with judge statistics
        """
        stats: dict[str, Any] = {
            "name": judge.name,
            "role": judge.role,
            "selection_method": self.protocol.judge_selection,
        }

        if self.elo_system:
            try:
                rating = self.elo_system.get_rating(judge.name)
                stats["elo"] = rating.elo
            except (KeyError, AttributeError) as e:
                logger.debug("Could not get ELO rating for %s: %s", judge.name, e)

        if self._get_calibration_weight:
            try:
                stats["calibration_weight"] = self._get_calibration_weight(judge.name)
            except (KeyError, AttributeError, TypeError) as e:
                logger.debug("Could not get calibration weight for %s: %s", judge.name, e)

        return stats
