"""History-based scoring signals for ``TeamSelector``.

``TeamSelectorHistoryMixin`` holds the scorers that rank agents from their track
record: Knowledge Mound domain expertise, the performance adapter, domain ELO win
rates, task-pattern affinities and Agent CVs, plus the caches and telemetry they use.
``TeamSelector`` (``aragora.debate.team_selector``) inherits the mixin and keeps
selection, filtering and the composite ``_compute_score`` that weighs these signals.
Import the selector from ``aragora.debate.team_selector``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.agents.cv import AgentCV, CVBuilder
    from aragora.core import Agent
    from aragora.debate.team_selector import AgentScorer, TeamSelectionConfig
    from aragora.memory.store import CritiqueStore
    from aragora.ranking.pattern_matcher import TaskPatternMatcher

# The selector's logger name, so log filters and caplog assertions keyed on
# "aragora.debate.team_selector" still see records from these methods.
logger = logging.getLogger("aragora.debate.team_selector")


class TeamSelectorHistoryMixin:
    """Track-record scoring signals for ``TeamSelector``."""

    # Set by TeamSelector.__init__.
    elo_system: AgentScorer | None
    ranking_adapter: Any | None
    critique_store: CritiqueStore | None
    pattern_matcher: TaskPatternMatcher | None
    cv_builder: CVBuilder | None
    config: TeamSelectionConfig
    performance_adapter: Any | None
    _km_expertise_cache: dict[str, tuple[float, list[Any]]]
    _pattern_affinities_cache: dict[str, dict[str, float]]
    _cv_cache: dict[str, tuple[float, AgentCV]]

    def _get_km_domain_experts(self, domain: str) -> list[Any]:
        """Get domain experts from KM with caching.

        Uses the RankingAdapter to query historical expertise data stored in
        the Knowledge Mound, providing organizational learning about which
        agents perform best in specific domains.

        Args:
            domain: Domain to query expertise for

        Returns:
            List of AgentExpertise objects sorted by ELO
        """
        import time

        if not self.ranking_adapter or not self.config.enable_km_expertise:
            return []

        cache_key = domain.lower()
        current_time = time.time()

        # Check cache
        if cache_key in self._km_expertise_cache:
            cached_time, cached_experts = self._km_expertise_cache[cache_key]
            if current_time - cached_time < self.config.km_expertise_cache_ttl:
                return cached_experts

        # Query KM for domain experts
        try:
            experts: list[Any] = self.ranking_adapter.get_domain_experts(
                domain=domain,
                limit=20,
                min_confidence=0.3,
                use_cache=True,
            )
            self._km_expertise_cache[cache_key] = (current_time, experts)
            logger.debug("km_expertise_lookup domain=%s experts=%s", domain, len(experts))
            return experts
        except (AttributeError, TypeError, ValueError, RuntimeError, OSError) as e:
            logger.debug("KM expertise lookup failed for %s: %s", domain, e)
            return []

    def _compute_km_expertise_score(
        self,
        agent: Agent,
        domain: str,
    ) -> float:
        """Compute score bonus based on KM-stored expertise.

        Looks up the agent's historical performance in the domain from the
        Knowledge Mound and provides a score bonus based on their ranking.

        Args:
            agent: Agent to score
            domain: Domain to check expertise for

        Returns:
            Score bonus (0.0 to 1.0) based on KM expertise ranking
        """
        experts = self._get_km_domain_experts(domain)
        if not experts:
            return 0.0

        agent_name_lower = agent.name.lower()

        # Find agent in expert list
        for idx, expert in enumerate(experts):
            expert_name = getattr(expert, "agent_name", "").lower()
            if expert_name and (expert_name in agent_name_lower or agent_name_lower in expert_name):
                # Score based on ranking position (first = 1.0, decreasing)
                max_experts = min(len(experts), 10)
                position_score = 1.0 - (idx / max_experts)

                # Boost by confidence if available
                confidence = getattr(expert, "confidence", 0.8)
                adjusted_score = position_score * (0.5 + confidence * 0.5)

                logger.debug(
                    f"km_expertise_score agent={agent.name} domain={domain} "  # noqa: G004
                    f"rank={idx + 1} score={adjusted_score:.3f}"
                )
                return max(0.0, min(1.0, adjusted_score))

        return 0.0

    def _compute_performance_adapter_score(
        self,
        agent: Agent,
        domain: str,
    ) -> float:
        """Compute score from KM PerformanceAdapter domain expertise.

        Queries the PerformanceAdapter for the agent's domain-specific ELO
        and expertise confidence, producing a composite score that reflects
        both historical win rate and domain familiarity.

        Args:
            agent: Agent to score
            domain: Domain to query

        Returns:
            Score bonus (0.0 to 1.0) based on combined ELO + confidence
        """
        if not self.performance_adapter:
            return 0.0

        try:
            experts = self.performance_adapter.get_domain_experts(
                domain=domain,
                limit=20,
                min_confidence=0.1,
                use_cache=True,
            )
        except (AttributeError, TypeError) as e:
            logger.debug("Performance adapter domain query failed: %s", e)
            return 0.0

        if not experts:
            return 0.0

        agent_name_lower = agent.name.lower()
        for idx, expert in enumerate(experts):
            expert_name = getattr(expert, "agent_name", "").lower()
            if expert_name and (expert_name in agent_name_lower or agent_name_lower in expert_name):
                max_entries = min(len(experts), 10)
                position_score = 1.0 - (idx / max_entries)
                confidence = getattr(expert, "confidence", 0.5)
                weighted = position_score * (0.4 + confidence * 0.6)
                logger.debug(
                    f"performance_adapter_score agent={agent.name} domain={domain} "  # noqa: G004
                    f"rank={idx + 1} confidence={confidence:.2f} score={weighted:.3f}"
                )
                return max(0.0, min(1.0, weighted))

        return 0.0

    def _compute_elo_win_rate_score(
        self,
        agent: Agent,
        domain: str,
    ) -> float:
        """Compute score bonus based on domain-specific win rates from the ELO system.

        Queries get_top_agents_for_domain() and uses the agent's win_rate
        property to boost high-performers and penalize low-performers.

        Args:
            agent: Agent to score
            domain: Domain to check win rates for

        Returns:
            Score adjustment (-0.5 to 1.0) based on domain win rate
        """
        if not self.elo_system or not self.config.enable_elo_win_rate:
            return 0.0

        try:
            if not hasattr(self.elo_system, "get_top_agents_for_domain"):
                return 0.0

            top_agents = self.elo_system.get_top_agents_for_domain(domain, limit=20)  # type: ignore[attr-defined]
            if not top_agents:
                return 0.0

            agent_name_lower = agent.name.lower()
            for rating in top_agents:
                rating_name = getattr(rating, "agent_name", "").lower()
                if rating_name and (
                    rating_name in agent_name_lower or agent_name_lower in rating_name
                ):
                    win_rate = getattr(rating, "win_rate", 0.0)
                    # Center around 0.5: above 50% gets bonus, below gets penalty
                    score = (win_rate - 0.5) * 2.0  # Maps 0.0-1.0 to -1.0..1.0
                    clamped = max(-0.5, min(1.0, score))
                    logger.debug(
                        f"elo_win_rate_score agent={agent.name} domain={domain} "  # noqa: G004
                        f"win_rate={win_rate:.3f} score={clamped:.3f}"
                    )
                    return clamped

        except (AttributeError, TypeError) as e:
            logger.debug("ELO win rate lookup failed for %s: %s", agent.name, e)

        return 0.0

    def _compute_pattern_score(
        self,
        agent: Agent,
        task: str,
    ) -> float:
        """Compute score bonus based on task pattern affinity.

        Uses the TaskPatternMatcher to classify the task and look up
        agent affinities based on historical performance in that pattern.

        Args:
            agent: Agent to score
            task: Task description to classify

        Returns:
            Score bonus (0.0 to 1.0) based on pattern affinity
        """
        if not self.pattern_matcher or not task:
            return 0.0

        try:
            # Classify the task
            pattern = self.pattern_matcher.classify_task(task)

            # Track pattern classification for telemetry
            self._track_pattern_classification(pattern, task)

            if pattern == "general":
                return 0.0

            # Check cache first
            if pattern not in self._pattern_affinities_cache:
                affinities = self.pattern_matcher.get_agent_affinities(pattern, self.critique_store)
                self._pattern_affinities_cache[pattern] = affinities
                # Log cache population for telemetry
                logger.info(
                    "pattern_affinities_loaded pattern=%s agent_count=%s", pattern, len(affinities)
                )

            affinities = self._pattern_affinities_cache.get(pattern, {})
            if not affinities:
                return 0.0

            # Find agent's affinity (partial name matching)
            agent_name_lower = agent.name.lower()
            for affinity_name, affinity_score in affinities.items():
                if (
                    affinity_name.lower() in agent_name_lower
                    or agent_name_lower in affinity_name.lower()
                ):
                    # Structured telemetry log
                    logger.info(
                        f"pattern_score_applied agent={agent.name} pattern={pattern} "  # noqa: G004
                        f"affinity={affinity_score:.3f} weight={self.config.pattern_weight:.2f} "
                        f"contribution={affinity_score * self.config.pattern_weight:.3f}"
                    )
                    return affinity_score

            # No affinity found for this agent
            logger.debug("pattern_no_affinity agent=%s pattern=%s", agent.name, pattern)
            return 0.0
        except (AttributeError, TypeError, ValueError, KeyError, RuntimeError) as e:
            logger.warning("pattern_score_error agent=%s error=%s", agent.name, e)
            return 0.0

    def _track_pattern_classification(self, pattern: str, task: str) -> None:
        """Track pattern classification for telemetry analysis.

        Records pattern classifications to enable calibration analysis.
        """
        if not hasattr(self, "_pattern_classification_counts"):
            self._pattern_classification_counts: dict[str, int] = {}

        self._pattern_classification_counts[pattern] = (
            self._pattern_classification_counts.get(pattern, 0) + 1
        )

        # Log at DEBUG for per-classification, INFO periodically for summary
        total = sum(self._pattern_classification_counts.values())
        if total % 50 == 0:  # Log summary every 50 classifications
            logger.info(
                "pattern_classification_summary total=%s distribution=%s",
                total,
                self._pattern_classification_counts,
            )

    def get_pattern_telemetry(self) -> dict[str, Any]:
        """Get pattern selection telemetry for analysis and calibration.

        Returns:
            Dictionary with pattern classification counts, cache stats, and config
        """
        return {
            "classification_counts": getattr(self, "_pattern_classification_counts", {}),
            "cached_patterns": list(self._pattern_affinities_cache.keys()),
            "config": {
                "pattern_weight": self.config.pattern_weight,
                "enabled": self.config.enable_pattern_selection,
            },
        }

    def _get_agent_cvs_batch(self, agent_names: list[str]) -> dict[str, AgentCV]:
        """Get Agent CVs for multiple agents with caching.

        Uses the CVBuilder to efficiently fetch CV data for multiple agents,
        caching results to avoid repeated lookups.

        Args:
            agent_names: List of agent names to get CVs for

        Returns:
            Dict mapping agent names to their AgentCV instances
        """
        import time

        if not self.cv_builder:
            return {}

        current_time = time.time()
        result: dict[str, AgentCV] = {}
        uncached_agents: list[str] = []

        # Check cache first
        for name in agent_names:
            if name in self._cv_cache:
                cached_time, cv = self._cv_cache[name]
                if current_time - cached_time < self.config.cv_cache_ttl:
                    result[name] = cv
                else:
                    uncached_agents.append(name)
            else:
                uncached_agents.append(name)

        # Batch fetch uncached CVs
        if uncached_agents:
            try:
                if hasattr(self.cv_builder, "build_cvs_batch"):
                    new_cvs = self.cv_builder.build_cvs_batch(uncached_agents)
                else:
                    # Fall back to individual builds
                    new_cvs = {name: self.cv_builder.build_cv(name) for name in uncached_agents}

                # Update cache and result
                for name, cv in new_cvs.items():
                    self._cv_cache[name] = (current_time, cv)
                    result[name] = cv

                logger.debug(
                    "cv_batch_fetch cached=%s fetched=%s total=%s",
                    len(result) - len(new_cvs),
                    len(new_cvs),
                    len(result),
                )
            except (AttributeError, TypeError, ValueError, RuntimeError) as e:
                logger.warning("CV batch fetch failed: %s", e)

        return result

    def _compute_cv_score(
        self,
        cv: AgentCV,
        domain: str | None = None,
    ) -> float:
        """Compute score bonus from Agent CV.

        Uses the CV's composite selection score which incorporates:
        - ELO ratings (overall + domain-specific)
        - Calibration metrics (Brier score, ECE)
        - Reliability stats (success rate)
        - Domain expertise

        Args:
            cv: Agent's CV
            domain: Optional domain for domain-weighted scoring

        Returns:
            Score bonus (0.0 to 1.0) based on CV data
        """
        if not cv.has_meaningful_data:
            # Not enough data for reliable scoring
            return 0.0

        # Use CV's built-in selection score computation
        # Adjust weights to complement existing scoring factors
        selection_score = cv.compute_selection_score(
            domain=domain,
            elo_weight=0.25,  # Reduced since we also use direct ELO
            calibration_weight=0.25,  # Reduced since we also use direct calibration
            reliability_weight=0.30,  # Emphasized - unique to CV
            domain_weight=0.20,
        )

        # Add reliability bonus for highly reliable agents
        reliability_bonus = 0.0
        if cv.reliability.is_reliable:
            reliability_bonus = 0.1

        # Add calibration bonus for well-calibrated agents
        calibration_bonus = 0.0
        if cv.is_well_calibrated:
            calibration_bonus = 0.1

        final_score = min(1.0, selection_score + reliability_bonus + calibration_bonus)

        logger.debug(
            f"cv_score agent={cv.agent_id} domain={domain} "  # noqa: G004
            f"selection={selection_score:.3f} reliability_bonus={reliability_bonus:.1f} "
            f"calibration_bonus={calibration_bonus:.1f} final={final_score:.3f}"
        )

        return final_score

    def get_cv(self, agent_name: str) -> AgentCV | None:
        """Get the CV for a single agent (for external use).

        Args:
            agent_name: Name of the agent

        Returns:
            AgentCV if available, None otherwise
        """
        cvs = self._get_agent_cvs_batch([agent_name])
        return cvs.get(agent_name)
