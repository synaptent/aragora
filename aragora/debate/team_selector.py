"""Team selection for debate participation.

Extracted from orchestrator.py to reduce complexity and improve testability.
Handles agent scoring based on ELO, calibration, and circuit breaker filtering.

Enhanced with DelegationStrategy integration for intelligent task routing
and domain/capability-based agent filtering for optimal team composition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from aragora.agents.cv import AgentCV, CVBuilder
    from aragora.billing.budget_manager import BudgetManager
    from aragora.core import Agent
    from aragora.debate.context import DebateContext
    from aragora.debate.delegation import DelegationStrategy
    from aragora.debate.hierarchy import AgentHierarchy
    from aragora.debate.protocol import CircuitBreaker
    from aragora.memory.continuum.core import ContinuumMemory
    from aragora.memory.store import CritiqueStore
    from aragora.ranking.pattern_matcher import TaskPatternMatcher

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when a debate cannot proceed due to budget constraints."""


# Domain-to-capability mapping for intelligent agent routing
# Maps task domains to agent name patterns that excel in those areas
DOMAIN_CAPABILITY_MAP: dict[str, list[str]] = {
    # Code-related tasks - prefer coding specialists
    "code": ["claude", "codex", "codestral", "deepseek", "gpt"],
    "programming": ["claude", "codex", "codestral", "deepseek", "gpt"],
    "technical": ["claude", "codex", "codestral", "deepseek", "gpt", "gemini"],
    # Research and analysis tasks
    "research": ["claude", "gemini", "gpt", "deepseek-r1"],
    "analysis": ["claude", "gemini", "gpt", "deepseek-r1"],
    "science": ["claude", "gemini", "gpt", "deepseek-r1"],
    # Creative tasks
    "creative": ["claude", "gpt", "gemini", "llama"],
    "writing": ["claude", "gpt", "gemini"],
    "storytelling": ["claude", "gpt", "gemini", "llama"],
    # Reasoning-heavy tasks
    "reasoning": ["claude", "deepseek-r1", "gpt", "gemini"],
    "logic": ["claude", "deepseek-r1", "gpt"],
    "math": ["claude", "deepseek-r1", "gpt", "gemini"],
    # General/default - no filtering
    "general": [],
}


class AgentScorer(Protocol):
    """Protocol for agent scoring systems."""

    def get_rating(self, agent_name: str) -> float:
        """Get agent's rating score."""
        ...


class CalibrationScorer(Protocol):
    """Protocol for calibration scoring systems."""

    def get_brier_score(self, agent_name: str, domain: str | None = None) -> float:
        """Get agent's Brier score (lower is better).

        Args:
            agent_name: Name of the agent
            domain: Optional domain for domain-specific calibration
        """
        ...

    def get_brier_scores_batch(
        self, agent_names: list[str], domain: str | None = None
    ) -> dict[str, float]:
        """Get Brier scores for multiple agents in a single query.

        This is an optional optimization method. Implementations may fall back
        to calling get_brier_score individually if not implemented.

        Args:
            agent_names: List of agent names to query
            domain: Optional domain for domain-specific calibration

        Returns:
            Dict mapping agent names to their Brier scores
        """
        # Default implementation falls back to individual calls
        return {name: self.get_brier_score(name, domain) for name in agent_names}


@dataclass
class TeamSelectionConfig:
    """Configuration for team selection behavior."""

    elo_weight: float = 0.3
    calibration_weight: float = 0.2
    delegation_weight: float = 0.2  # Weight for delegation strategy scoring
    domain_capability_weight: float = 0.25  # Weight for domain expertise matching
    culture_weight: float = 0.15  # Weight for culture-based agent recommendations
    km_expertise_weight: float = 0.25  # Weight for KM-stored historical expertise
    pattern_weight: float = 0.2  # Weight for task pattern-based selection
    base_score: float = 1.0
    elo_baseline: int = 1000
    enable_domain_filtering: bool = True  # Enable domain-based agent filtering
    domain_filter_fallback: bool = True  # Fall back to all agents if no match
    domain_filter_mode: str = "hard"  # "hard" (filter out), "soft" (penalty), "disabled"
    domain_soft_penalty: float = 0.3  # Penalty applied to non-preferred agents in "soft" mode
    enable_culture_selection: bool = False  # Enable culture-based agent scoring
    enable_km_expertise: bool = True  # Enable KM-based expertise lookup
    enable_pattern_selection: bool = True  # Enable task pattern-based selection
    km_expertise_cache_ttl: int = 300  # Cache TTL in seconds (5 minutes)
    custom_domain_map: dict[str, list[str]] = field(default_factory=dict)
    # Gastown hierarchy role filtering
    enable_hierarchy_filtering: bool = False  # Enable Gastown role-based filtering
    hierarchy_filter_fallback: bool = True  # Fall back to all agents if no role match
    # Agent CV-based selection (unified capability profiles)
    enable_cv_selection: bool = True  # Enable CV-based agent scoring
    cv_weight: float = 0.35  # Weight for CV composite score
    cv_reliability_threshold: float = 0.7  # Min reliability for agent inclusion
    cv_filter_unreliable: bool = False  # Filter out unreliable agents entirely
    cv_cache_ttl: int = 60  # CV cache TTL in seconds (1 minute)
    # ELO win rate scoring (domain-specific win rates from ELO system)
    enable_elo_win_rate: bool = True  # Enable domain win rate scoring
    elo_win_rate_weight: float = 0.2  # Weight for domain win rate contribution
    # Budget-aware selection
    enable_budget_filtering: bool = True  # Enable budget-aware agent filtering
    budget_cheap_agent_patterns: list[str] = field(
        default_factory=lambda: ["llama", "qwen", "yi", "deepseek", "mistral", "gemini"]
    )
    budget_warn_max_agents: int | None = None  # Max agents under WARN (None = no limit)
    budget_soft_limit_max_agents: int = 3  # Max agents under SOFT_LIMIT
    # Reliability budget routing (calibration + settled outcomes)
    enable_reliability_budget_routing: bool = True
    reliability_budget_share_weight: float = 0.2
    reliability_budget_min_share: float = 0.05
    # Feedback loop integration
    enable_feedback_weights: bool = True  # Enable selection feedback loop scoring
    feedback_weight: float = 0.5  # Weight for feedback-based score adjustment
    # Specialist registry (domain experts from ELO + Genesis breeding)
    enable_specialist_bonus: bool = True  # Enable specialist registry scoring
    specialist_weight: float = 0.25  # Weight for specialist bonus
    # Exploration bonus (UCB1-style)
    enable_exploration_bonus: bool = True  # Boost underexplored agents
    exploration_weight: float = 0.15  # Weight for exploration bonus
    exploration_min_debates: int = 50  # Total debates before exploration decays significantly
    # ContinuumMemory-informed selection
    memory_weight: float = 0.15  # Weight for memory-based score contribution
    enable_memory_selection: bool = True  # Enable ContinuumMemory-based agent scoring
    # Pulse (trending topic) relevance scoring
    enable_pulse_selection: bool = True  # Boost agents with expertise matching trending topics
    pulse_weight: float = 0.1  # Weight for pulse relevance contribution
    # Regression penalty (penalize agents involved in Nomic Loop regressions)
    enable_regression_penalty: bool = True
    regression_penalty_weight: float = 0.15
    # Introspection scoring (reputation + calibration from introspection snapshots)
    enable_introspection_scoring: bool = True
    introspection_weight: float = 0.2
    # Control Plane health filtering (agent availability from AgentRegistry)
    enable_health_filtering: bool = True
    health_weight: float = 0.3


class TeamSelector:
    """Selects and scores agents for debate participation.

    Uses ELO ratings, calibration scores, delegation strategies, and
    circuit breaker status to prioritize high-performing, reliable agents.

    Example:
        selector = TeamSelector(
            elo_system=elo,
            calibration_tracker=tracker,
            circuit_breaker=breaker,
            delegation_strategy=ContentBasedDelegation(),
        )
        team = selector.select(agents, domain="technical", task="Review security")
    """

    def __init__(
        self,
        elo_system: AgentScorer | None = None,
        calibration_tracker: CalibrationScorer | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        delegation_strategy: DelegationStrategy | None = None,
        knowledge_mound: Any | None = None,
        ranking_adapter: Any | None = None,
        critique_store: CritiqueStore | None = None,
        pattern_matcher: TaskPatternMatcher | None = None,
        cv_builder: CVBuilder | None = None,
        agent_hierarchy: AgentHierarchy | None = None,
        budget_manager: BudgetManager | None = None,
        org_id: str | None = None,
        config: TeamSelectionConfig | None = None,
        performance_adapter: Any | None = None,
        feedback_loop: Any | None = None,
        continuum_memory: ContinuumMemory | None = None,
        control_plane_registry: Any | None = None,
        marketplace_registry: Any | None = None,
    ):
        self.elo_system = elo_system
        # Auto-detect default CalibrationTracker if none provided.
        # CalibrationTracker from aragora.agents.calibration implements the
        # CalibrationScorer protocol (get_brier_score) and provides SDPO-compatible
        # Brier scoring backed by SQLite persistence.
        if calibration_tracker is None:
            try:
                from aragora.agents.calibration import CalibrationTracker

                calibration_tracker = CalibrationTracker()  # type: ignore[assignment]  # CalibrationTracker satisfies CalibrationScorer at runtime
                logger.debug("Auto-detected CalibrationTracker as default calibration scorer")
            except (ImportError, RuntimeError, TypeError, OSError, ValueError):
                # Graceful degradation: calibration scoring is optional.
                # ImportError: module not available
                # RuntimeError/TypeError: instantiation issues
                # OSError: database file access (includes sqlite3.OperationalError)
                # ValueError: configuration issues
                logger.debug(
                    "CalibrationTracker not available for auto-detection, "
                    "proceeding without calibration scoring"
                )
        self.calibration_tracker = calibration_tracker
        self.circuit_breaker = circuit_breaker
        self.delegation_strategy = delegation_strategy
        self.knowledge_mound = knowledge_mound
        self.ranking_adapter = ranking_adapter
        self.critique_store = critique_store
        self.pattern_matcher = pattern_matcher
        self.cv_builder = cv_builder
        self.agent_hierarchy = agent_hierarchy
        self.budget_manager = budget_manager
        self.org_id = org_id
        self.config = config or TeamSelectionConfig()
        self.performance_adapter = performance_adapter
        self.feedback_loop = feedback_loop
        self.continuum_memory = continuum_memory
        # Control Plane AgentRegistry for health/availability checks
        if control_plane_registry is None:
            try:
                from aragora.control_plane.registry import AgentRegistry

                control_plane_registry = AgentRegistry()
                logger.debug("Auto-detected AgentRegistry as default control plane registry")
            except (ImportError, RuntimeError, TypeError, OSError, ValueError):
                logger.debug(
                    "AgentRegistry not available for auto-detection, "
                    "proceeding without health filtering"
                )
        self.control_plane_registry = control_plane_registry
        # Marketplace registry for template-based team selection
        self.marketplace_registry = marketplace_registry
        self.pulse_manager: Any = None  # Set externally or via Arena
        self.specialist_registry: Any = None  # Set externally or via Arena
        self._culture_recommendations_cache: dict[str, list[str]] = {}
        self._km_expertise_cache: dict[str, tuple[float, list[Any]]] = {}
        self._pattern_affinities_cache: dict[str, dict[str, float]] = {}
        # Agents that don't match domain patterns (populated in soft filter mode)
        self._domain_non_preferred: set[str] = set()
        # CV cache: agent_id -> (timestamp, AgentCV)
        self._cv_cache: dict[str, tuple[float, AgentCV]] = {}
        # Hierarchy role assignments cache: debate_id -> {agent_name -> RoleAssignment}
        self._hierarchy_assignments: dict[str, dict[str, Any]] = {}
        # Last selection reasoning: agent_name -> {component: score_contribution}
        self._last_selection_reasoning: dict[str, dict[str, float]] = {}

    def select(
        self,
        agents: list[Agent],
        domain: str = "general",
        task: str = "",
        context: DebateContext | None = None,
        required_hierarchy_roles: set[str] | None = None,
        debate_id: str | None = None,
    ) -> list[Agent]:
        """Select and rank agents for debate participation.

        Args:
            agents: List of candidate agents
            domain: Task domain for context-aware selection
            task: Task description for delegation-based routing
            context: Optional debate context for state-aware selection
            required_hierarchy_roles: Optional set of Gastown hierarchy roles to filter by
                                      (e.g., {"orchestrator", "worker"} for coordinators and workers)
            debate_id: Optional debate ID for hierarchy role assignment caching

        Returns:
            Agents sorted by performance score (highest first)
        """
        # 0. Assign hierarchy roles if AgentHierarchy is available
        if self.agent_hierarchy and debate_id:
            self._assign_hierarchy_roles(agents, debate_id, domain)

        # 0.5. Filter by Gastown hierarchy role if specified
        hierarchy_filtered = self._filter_by_hierarchy_role(
            agents, required_hierarchy_roles, debate_id
        )

        # 1. Filter by domain capability first (before circuit breaker)
        domain_filtered = self._filter_by_domain_capability(hierarchy_filtered, domain)

        # 1.5. Apply budget-aware filtering
        domain_filtered = self._apply_budget_filter(domain_filtered)

        # 2. Filter unavailable agents via circuit breaker
        available_names = self._filter_available(domain_filtered)

        # 3. Pre-fetch calibration scores in batch for performance
        calibration_scores: dict[str, float] = {}
        if self.calibration_tracker:
            try:
                agent_names = [a.name for a in domain_filtered if a.name in available_names]
                if hasattr(self.calibration_tracker, "get_brier_scores_batch"):
                    calibration_scores = self.calibration_tracker.get_brier_scores_batch(
                        agent_names, domain=domain
                    )
                else:
                    # Fall back to individual lookups if batch not available
                    for name in agent_names:
                        try:
                            calibration_scores[name] = self.calibration_tracker.get_brier_score(
                                name, domain=domain
                            )
                        except (KeyError, AttributeError, TypeError) as e:
                            logger.debug("Calibration lookup failed for %s: %s", name, e)
            except (KeyError, AttributeError, TypeError, ValueError) as e:
                logger.debug("Batch calibration lookup failed: %s", e)

        # 3.5. Pre-fetch Agent CVs in batch for performance
        agent_cvs: dict[str, AgentCV] = {}
        if self.cv_builder and self.config.enable_cv_selection:
            try:
                agent_names = [a.name for a in domain_filtered if a.name in available_names]
                agent_cvs = self._get_agent_cvs_batch(agent_names)
            except (AttributeError, TypeError, ValueError, RuntimeError) as e:
                logger.debug("Batch CV lookup failed: %s", e)

        # 3.6. Filter unreliable agents if configured
        if self.config.cv_filter_unreliable and agent_cvs:
            reliable_names = set()
            for name, cv in agent_cvs.items():
                if cv.reliability.success_rate >= self.config.cv_reliability_threshold:
                    reliable_names.add(name)
                else:
                    logger.info(
                        f"agent_filtered_by_reliability agent={name} "
                        f"success_rate={cv.reliability.success_rate:.2f} "
                        f"threshold={self.config.cv_reliability_threshold}"
                    )
            available_names = available_names & reliable_names

        # 3.7. Compute reliability-informed budget shares for live routing
        selected_agent_names = [a.name for a in domain_filtered if a.name in available_names]
        budget_shares = self._compute_reliability_budget_shares(
            selected_agent_names,
            calibration_scores,
        )

        # 4. Score remaining agents (using ELO, calibration, delegation, domain, and CV)
        scored: list[tuple[Agent, float]] = []
        selection_breakdowns: dict[str, dict[str, float]] = {}
        for agent in domain_filtered:
            if agent.name not in available_names:
                logger.info("agent_filtered_by_circuit_breaker agent=%s", agent.name)
                continue

            agent_breakdown: dict[str, float] = {}
            score = self._compute_score(
                agent,
                domain=domain,
                task=task,
                context=context,
                calibration_scores=calibration_scores,
                agent_cvs=agent_cvs,
                budget_shares=budget_shares,
                breakdown=agent_breakdown,
            )
            scored.append((agent, score))
            agent_breakdown["total"] = round(score, 4)
            selection_breakdowns[agent.name] = agent_breakdown

        if not scored:
            logger.warning("No agents available after performance filtering")
            return agents  # Fall back to original list

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Store breakdowns for transparency (accessible via last_selection_reasoning)
        self._last_selection_reasoning = selection_breakdowns

        selected = [agent for agent, _ in scored]
        logger.info(
            "performance_selection domain=%s selected=%s scores=%s",
            domain,
            [a.name for a in selected],
            [f"{s:.2f}" for _, s in scored],
        )

        return selected

    def _filter_available(self, agents: list[Agent]) -> set[str]:
        """Filter agents through circuit breaker."""
        available_names = {a.name for a in agents}

        if self.circuit_breaker:
            try:
                available_names = set(
                    self.circuit_breaker.filter_available_agents([a.name for a in agents])
                )
            except (AttributeError, TypeError) as e:
                logger.debug("circuit_breaker filter error: %s", e)

        return available_names

    def _filter_by_domain_capability(
        self,
        agents: list[Agent],
        domain: str,
    ) -> list[Agent]:
        """Filter agents by domain expertise/capability.

        Uses DOMAIN_CAPABILITY_MAP to identify agents that excel in specific domains.
        Supports three modes via ``domain_filter_mode``:
        - "hard": Remove non-matching agents (original behavior)
        - "soft": Keep all agents but tag non-matching for a scoring penalty
        - "disabled": Skip domain filtering entirely

        Falls back to all agents if no matches found (configurable).

        Args:
            agents: List of candidate agents
            domain: Task domain (e.g., "code", "research", "creative")

        Returns:
            Filtered list of agents suited for the domain
        """
        # Clear previous non-preferred set
        self._domain_non_preferred = set()

        if not self.config.enable_domain_filtering:
            return agents

        # Resolve effective filter mode — auto-switch to soft when feedback data exists
        mode = self._resolve_domain_filter_mode(domain)

        if mode == "disabled":
            return agents

        # Check custom domain map first, then default
        domain_lower = domain.lower()
        preferred_patterns = self.config.custom_domain_map.get(
            domain_lower,
            DOMAIN_CAPABILITY_MAP.get(domain_lower, []),
        )

        if not preferred_patterns:
            logger.debug("No domain mapping for '%s', using all agents", domain)
            return agents

        # Classify agents into matching / non-matching
        matching_agents: list[Agent] = []
        non_matching_agents: list[Agent] = []
        for agent in agents:
            if self._agent_matches_capability(agent, preferred_patterns):
                matching_agents.append(agent)
            else:
                non_matching_agents.append(agent)

        if mode == "soft":
            # Keep all agents but mark non-matching for scoring penalty
            self._domain_non_preferred = {a.name for a in non_matching_agents}
            if self._domain_non_preferred:
                logger.info(
                    "domain_soft_filter domain=%s preferred=%s penalized=%s",
                    domain,
                    [a.name for a in matching_agents],
                    [a.name for a in non_matching_agents],
                )
            return agents

        # Hard mode: filter out non-matching agents
        if not matching_agents:
            if self.config.domain_filter_fallback:
                logger.info(
                    "No agents match domain '%s' patterns %s, falling back to all %s agents",
                    domain,
                    preferred_patterns,
                    len(agents),
                )
                return agents
            else:
                logger.warning("No agents match domain '%s', returning empty list", domain)
                return []

        logger.info(
            "domain_capability_filter domain=%s matched=%s from=%s",
            domain,
            [a.name for a in matching_agents],
            [a.name for a in agents],
        )
        return matching_agents

    def _resolve_domain_filter_mode(self, domain: str) -> str:
        """Resolve the effective domain filter mode.

        Auto-switches from "hard" to "soft" when the feedback loop has
        domain-specific data, allowing ELO/performance to override domain
        heuristics.

        Args:
            domain: Current task domain

        Returns:
            Effective filter mode: "hard", "soft", or "disabled"
        """
        mode = self.config.domain_filter_mode
        if mode == "disabled":
            return "disabled"

        if mode == "hard" and self.feedback_loop:
            try:
                domain_weights = self.feedback_loop.get_domain_weights(domain)
                if domain_weights:
                    logger.debug(
                        "domain_filter_auto_soft domain=%s feedback_agents=%s",
                        domain,
                        len(domain_weights),
                    )
                    return "soft"
            except (AttributeError, TypeError):
                pass

        return mode

    def _apply_budget_filter(self, agents: list[Agent]) -> list[Agent]:
        """Apply budget-aware filtering to the agent list.

        Checks the organization's budget status and adjusts the agent pool:
        - WARN: Prefer cheaper agents (filter to cheap patterns if available)
        - SOFT_LIMIT: Reduce agent count to budget_soft_limit_max_agents
        - HARD_LIMIT: Raise BudgetExceededError to block the debate

        Args:
            agents: List of candidate agents

        Returns:
            Filtered list of agents based on budget constraints

        Raises:
            BudgetExceededError: If budget is at HARD_LIMIT
        """
        if not self.budget_manager or not self.org_id or not self.config.enable_budget_filtering:
            return agents

        try:
            from aragora.billing.budget_manager import BudgetAction

            # Check budget with zero cost to get current action level
            _allowed, _reason, action = self.budget_manager.check_budget(
                self.org_id, estimated_cost_usd=0.0
            )

            if action is None:
                return agents

            if action == BudgetAction.HARD_LIMIT or action == BudgetAction.SUSPEND:
                logger.warning(
                    "budget_hard_limit org=%s action=%s agents_blocked=%s",
                    self.org_id,
                    action.value,
                    len(agents),
                )
                raise BudgetExceededError(
                    f"Budget {action.value} reached for org {self.org_id}. "
                    "Debate cannot proceed until budget is increased or reset."
                )

            if action == BudgetAction.SOFT_LIMIT:
                max_agents = self.config.budget_soft_limit_max_agents
                if len(agents) > max_agents:
                    reduced = agents[:max_agents]
                    logger.info(
                        "budget_soft_limit org=%s reduced_agents=%s->%s",
                        self.org_id,
                        len(agents),
                        len(reduced),
                    )
                    return reduced
                return agents

            if action == BudgetAction.WARN:
                # Prefer cheaper agents when budget is in warning zone
                cheap_patterns = self.config.budget_cheap_agent_patterns
                cheap_agents = [
                    a for a in agents if self._agent_matches_capability(a, cheap_patterns)
                ]
                if cheap_agents:
                    # Apply max_agents limit if configured
                    max_agents = self.config.budget_warn_max_agents
                    if max_agents and len(cheap_agents) > max_agents:
                        cheap_agents = cheap_agents[:max_agents]
                    logger.info(
                        "budget_warn_prefer_cheap org=%s cheap_agents=%s from=%s",
                        self.org_id,
                        [a.name for a in cheap_agents],
                        [a.name for a in agents],
                    )
                    return cheap_agents
                # No cheap agents available, return all
                return agents

        except BudgetExceededError:
            raise
        except (ImportError, AttributeError, TypeError) as e:
            logger.debug("Budget filter skipped: %s", e)

        return agents

    def _filter_by_hierarchy_role(
        self,
        agents: list[Agent],
        required_roles: set[str] | None = None,
        debate_id: str | None = None,
    ) -> list[Agent]:
        """Filter agents by Gastown hierarchy role.

        Uses the Gastown-inspired role system (orchestrator, monitor, worker)
        to filter agents based on their hierarchy role assignment.

        Args:
            agents: List of candidate agents
            required_roles: Set of hierarchy roles to include (e.g., {"orchestrator", "worker"})
                           If None or empty, returns all agents (no filtering)
            debate_id: Optional debate ID to look up role assignments from AgentHierarchy

        Returns:
            Filtered list of agents with matching hierarchy roles
        """
        if not required_roles or not self.config.enable_hierarchy_filtering:
            return agents

        # Normalize roles to lowercase
        required_roles_lower = {r.lower() for r in required_roles}

        matching_agents: list[Agent] = []
        for agent in agents:
            # Check hierarchy role using AgentHierarchy if available
            hierarchy_role = self._get_agent_hierarchy_role(agent, debate_id)
            if hierarchy_role and hierarchy_role.lower() in required_roles_lower:
                matching_agents.append(agent)

        if not matching_agents:
            if self.config.hierarchy_filter_fallback:
                logger.info(
                    "No agents match hierarchy roles %s, falling back to all %s agents",
                    required_roles,
                    len(agents),
                )
                return agents
            else:
                logger.warning(
                    "No agents match hierarchy roles %s, returning empty list", required_roles
                )
                return []

        logger.info(
            "hierarchy_role_filter roles=%s matched=%s from=%s",
            required_roles,
            [a.name for a in matching_agents],
            [a.name for a in agents],
        )
        return matching_agents

    def _assign_hierarchy_roles(
        self,
        agents: list[Agent],
        debate_id: str,
        domain: str = "general",
    ) -> None:
        """Assign hierarchy roles to agents using AgentHierarchy.

        Creates role assignments for the debate and caches them for lookup.

        Args:
            agents: List of agents to assign roles to
            debate_id: Debate identifier
            domain: Task domain for affinity matching
        """
        if not self.agent_hierarchy:
            return

        # Check if already assigned for this debate
        if debate_id in self._hierarchy_assignments:
            return

        try:
            # Convert agents to AgentProfile for hierarchy
            from aragora.routing.selection import AgentProfile

            profiles = []
            for agent in agents:
                profile = AgentProfile(
                    name=agent.name,
                    agent_type=getattr(agent, "agent_type", "unknown"),
                    elo_rating=self._get_agent_elo(agent),
                    capabilities=self._get_agent_capabilities(agent),
                    task_affinity={domain: 0.5},  # Default affinity
                )
                profiles.append(profile)

            # Assign roles using AgentHierarchy
            assignments = self.agent_hierarchy.assign_roles(
                debate_id=debate_id,
                agents=profiles,
                task_type=domain,
            )

            # Cache assignments
            self._hierarchy_assignments[debate_id] = assignments

            logger.info(
                "hierarchy_roles_assigned debate=%s orchestrator=%s monitors=%s workers=%s",
                debate_id,
                self.agent_hierarchy.get_orchestrator(debate_id),
                self.agent_hierarchy.get_monitors(debate_id),
                self.agent_hierarchy.get_workers(debate_id),
            )
        except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.warning("Failed to assign hierarchy roles: %s", e)

    def _get_agent_elo(self, agent: Agent) -> float:
        """Get ELO rating for an agent."""
        if self.elo_system:
            try:
                rating = self.elo_system.get_rating(agent.name)
                # Handle both AgentRating objects and raw float values
                return rating.elo if hasattr(rating, "elo") else float(rating)
            except (KeyError, AttributeError, TypeError) as e:
                logger.debug("ELO lookup failed for %s: %s", agent.name, e)
        return 1000.0  # Default ELO

    def _get_agent_capabilities(self, agent: Agent) -> set[str]:
        """Get capabilities for an agent."""
        if hasattr(agent, "capabilities") and agent.capabilities:
            return set(agent.capabilities)
        # Infer basic capabilities from agent type/name
        name_lower = agent.name.lower()
        caps = {"reasoning"}
        if "claude" in name_lower:
            caps.update({"synthesis", "coordination", "analysis", "creativity"})
        elif "gpt" in name_lower:
            caps.update({"synthesis", "coordination", "analysis"})
        elif "codex" in name_lower or "codestral" in name_lower:
            caps.update({"coding", "analysis"})
        elif "gemini" in name_lower:
            caps.update({"analysis", "quality_assessment"})
        return caps

    def _get_agent_hierarchy_role(self, agent: Agent, debate_id: str | None = None) -> str | None:
        """Get the Gastown hierarchy role for an agent.

        Checks multiple sources for the hierarchy role:
        1. AgentHierarchy assignments for this debate (if available)
        2. Direct hierarchy_role attribute
        3. AgentSpec.hierarchy_role if agent has spec
        4. Agent metadata

        Args:
            agent: Agent to get role for
            debate_id: Optional debate ID for hierarchy lookup

        Returns:
            Hierarchy role string (orchestrator, monitor, worker) or None
        """
        # First check AgentHierarchy assignments
        if debate_id and self.agent_hierarchy:
            role = self.agent_hierarchy.get_role(debate_id, agent.name)
            if role:
                return role.value

        # Try direct attribute
        if hasattr(agent, "hierarchy_role") and agent.hierarchy_role:
            return agent.hierarchy_role

        # Try spec attribute
        if hasattr(agent, "spec") and hasattr(agent.spec, "hierarchy_role"):
            return agent.spec.hierarchy_role

        # Try metadata
        if hasattr(agent, "metadata") and isinstance(agent.metadata, dict):
            return agent.metadata.get("hierarchy_role")

        return None

    def get_hierarchy_status(self, debate_id: str) -> dict | None:
        """Get the hierarchy status for a debate.

        Args:
            debate_id: Debate identifier

        Returns:
            Hierarchy status dict or None if not available
        """
        if not self.agent_hierarchy:
            return None
        return self.agent_hierarchy.get_hierarchy_status(debate_id)

    def clear_hierarchy_cache(self, debate_id: str) -> None:
        """Clear hierarchy cache for a completed debate.

        Args:
            debate_id: Debate identifier
        """
        self._hierarchy_assignments.pop(debate_id, None)
        if self.agent_hierarchy:
            self.agent_hierarchy.clear_debate(debate_id)

    def _agent_matches_capability(
        self,
        agent: Agent,
        patterns: list[str],
    ) -> bool:
        """Check if an agent matches any of the capability patterns.

        Args:
            agent: Agent to check
            patterns: List of name/type patterns to match against

        Returns:
            True if agent matches any pattern
        """
        agent_identifiers = [
            agent.name.lower(),
            getattr(agent, "agent_type", "").lower(),
            getattr(agent, "model", "").lower(),
        ]

        for pattern in patterns:
            pattern_lower = pattern.lower()
            for identifier in agent_identifiers:
                if pattern_lower in identifier:
                    return True
        return False

    def _compute_domain_score(
        self,
        agent: Agent,
        domain: str,
    ) -> float:
        """Compute a bonus score for domain expertise.

        Args:
            agent: Agent to score
            domain: Task domain

        Returns:
            Score bonus (0.0 to 1.0) based on domain match quality
        """
        domain_lower = domain.lower()
        preferred_patterns = self.config.custom_domain_map.get(
            domain_lower,
            DOMAIN_CAPABILITY_MAP.get(domain_lower, []),
        )

        if not preferred_patterns:
            return 0.0

        # Score based on position in preference list (earlier = better)
        for idx, pattern in enumerate(preferred_patterns):
            if self._agent_matches_capability(agent, [pattern]):
                # First in list gets 1.0, decreasing for later positions
                position_score = 1.0 - (idx * 0.15)
                return max(0.0, position_score)

        return 0.0

    def _compute_culture_score(
        self,
        agent: Agent,
        task_type: str,
    ) -> float:
        """Compute a bonus score based on organizational culture patterns.

        Uses the Knowledge Mound's culture accumulator to get agent recommendations
        based on historical success patterns for the given task type.

        Args:
            agent: Agent to score
            task_type: Type of task (e.g., "code_review", "analysis", "creative")

        Returns:
            Score bonus (0.0 to 1.0) based on culture-based ranking
        """
        if not self.knowledge_mound or not self.config.enable_culture_selection:
            return 0.0

        # Check cache first
        cache_key = task_type.lower()
        if cache_key not in self._culture_recommendations_cache:
            try:
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None and loop.is_running():
                    # Already in async context — schedule cache warm-up
                    # and return 0.0 this time. Next call will use cache.
                    future = asyncio.ensure_future(self._warm_culture_cache(cache_key, task_type))
                    # Suppress unhandled exception warnings
                    future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
                    return 0.0
                else:
                    recommendations = asyncio.run(self.knowledge_mound.recommend_agents(task_type))
                    self._culture_recommendations_cache[cache_key] = recommendations or []
            except (AttributeError, TypeError, ValueError, RuntimeError, OSError) as e:
                logger.debug("Culture recommendation failed for %s: %s", task_type, e)
                self._culture_recommendations_cache[cache_key] = []

        recommendations = self._culture_recommendations_cache.get(cache_key, [])
        if not recommendations:
            return 0.0

        # Score based on position in recommendation list
        agent_name_lower = agent.name.lower()
        for idx, rec_name in enumerate(recommendations):
            if rec_name.lower() in agent_name_lower or agent_name_lower in rec_name.lower():
                # First recommended gets 1.0, decreasing for later positions
                position_score = 1.0 - (idx * 0.2)
                return max(0.0, position_score)

        return 0.0

    async def compute_culture_score_async(
        self,
        agent: Agent,
        task_type: str,
    ) -> float:
        """Async version of culture score computation.

        Call this from async contexts to avoid event loop issues.
        """
        if not self.knowledge_mound or not self.config.enable_culture_selection:
            return 0.0

        cache_key = task_type.lower()
        if cache_key not in self._culture_recommendations_cache:
            try:
                recommendations = await self.knowledge_mound.recommend_agents(task_type)
                self._culture_recommendations_cache[cache_key] = recommendations or []
            except (
                AttributeError,
                TypeError,
                ValueError,
                RuntimeError,
                OSError,
                KeyError,
                Exception,
            ) as e:
                logger.debug("Culture recommendation failed for %s: %s", task_type, e)
                self._culture_recommendations_cache[cache_key] = []

        recommendations = self._culture_recommendations_cache.get(cache_key, [])
        if not recommendations:
            return 0.0

        agent_name_lower = agent.name.lower()
        for idx, rec_name in enumerate(recommendations):
            if rec_name.lower() in agent_name_lower or agent_name_lower in rec_name.lower():
                position_score = 1.0 - (idx * 0.2)
                return max(0.0, position_score)

        return 0.0

    def _compute_exploration_bonus(
        self,
        agent: Agent,
        domain: str | None = None,
    ) -> float:
        """Compute UCB1-style exploration bonus for underexplored agents.

        Agents with fewer debates get a temporary score boost to ensure
        they are tested.  The bonus decays as sqrt(ln(N) / n_i) where
        N is total debates across all agents and n_i is this agent's
        debate count.  This is the classic Upper Confidence Bound formula
        from multi-armed bandit theory.

        Returns:
            Score bonus (0.0 to 1.0), higher for less-tested agents.
        """
        import math

        try:
            rating = self.elo_system.get_rating(agent.name)
            agent_debates = getattr(rating, "total_matches", 0)
            if isinstance(rating, (int, float)):
                agent_debates = 0
            elif not isinstance(agent_debates, (int, float)):
                agent_debates = 0
        except (KeyError, AttributeError, TypeError):
            # No data = maximum exploration bonus
            return 1.0

        if agent_debates <= 0:
            return 1.0  # Never tested → max exploration

        # Total debates across all agents (approximate from config)
        total_debates = max(self.config.exploration_min_debates, agent_debates * 3)

        # UCB1: sqrt(ln(N) / n_i), normalized to [0, 1]
        ucb = math.sqrt(math.log(total_debates) / agent_debates)
        return min(1.0, ucb)

    def _compute_memory_score(
        self,
        agent: Any,
        domain: str,
        task: str,
    ) -> float:
        """Score bonus based on ContinuumMemory of agent performance.

        Queries slow/glacial memory tiers for patterns matching this agent
        on similar tasks, computing weighted average success rate.

        Args:
            agent: Agent to score
            domain: Task domain for query context
            task: Task description for query context

        Returns:
            Score bonus (0.0 to 1.0) based on historical memory data
        """
        if not self.continuum_memory or not self.config.enable_memory_selection:
            return 0.0

        try:
            agent_name = getattr(agent, "name", str(agent))
            query = f"{agent_name} {domain} {task}"

            memories = self.continuum_memory.retrieve(
                query=query,
                limit=20,
                min_importance=0.3,
            )

            if not memories:
                return 0.0

            # Filter to memories about this specific agent
            agent_memories = [m for m in memories if m.metadata.get("agent_name") == agent_name]

            if not agent_memories:
                return 0.0

            # Weighted average success rate
            total_weight = 0.0
            weighted_success = 0.0
            for mem in agent_memories:
                weight = mem.importance * getattr(mem, "consolidation_score", 1.0)
                weighted_success += mem.success_rate * weight
                total_weight += weight

            avg_success = weighted_success / total_weight if total_weight > 0 else 0.5

            # Confidence scaling based on observation count
            total_obs = sum(getattr(m, "update_count", 1) for m in agent_memories)
            confidence = min(1.0, total_obs / 20.0)

            # Scale to 0-1 range centered at 0.5
            score = (avg_success - 0.5) * 2.0 * confidence
            return max(0.0, min(1.0, 0.5 + score * 0.5))

        except (AttributeError, TypeError, ValueError, KeyError, RuntimeError) as e:
            logger.debug("Memory score failed for %s: %s", getattr(agent, "name", agent), e)
            return 0.0

    def _compute_pulse_relevance(
        self,
        agent: Any,
        task: str,
        domain: str | None = None,
    ) -> float:
        """Score bonus for agents with expertise matching trending pulse topics.

        When a debate task relates to a trending topic tracked by the Pulse
        system, agents whose expertise aligns with that topic receive a score
        boost. This makes the team composition responsive to real-world trends.

        Args:
            agent: Agent to score
            task: Task description to match against trending topics
            domain: Optional domain for additional context

        Returns:
            Score bonus (0.0 to 1.0) based on pulse topic relevance
        """
        if not self.pulse_manager or not self.config.enable_pulse_selection:
            return 0.0

        try:
            # Get trending topics from pulse manager
            topics: list[Any] = []
            if hasattr(self.pulse_manager, "get_trending_topics"):
                topics = self.pulse_manager.get_trending_topics(limit=10) or []
            elif hasattr(self.pulse_manager, "trending_topics"):
                topics = self.pulse_manager.trending_topics or []

            if not topics:
                return 0.0

            # Check if task relates to any trending topic
            task_lower = task.lower()
            matching_topics = []
            for topic in topics:
                topic_text = ""
                if isinstance(topic, str):
                    topic_text = topic.lower()
                elif hasattr(topic, "title"):
                    topic_text = topic.title.lower()
                elif hasattr(topic, "name"):
                    topic_text = topic.name.lower()

                if not topic_text:
                    continue

                # Simple keyword overlap check
                topic_words = set(topic_text.split())
                task_words = set(task_lower.split())
                overlap = len(topic_words & task_words)
                if overlap >= 2 or any(w in task_lower for w in topic_words if len(w) > 4):
                    freshness = getattr(topic, "freshness_score", 0.5)
                    matching_topics.append(freshness)

            if not matching_topics:
                return 0.0

            # Agent expertise alignment: boost agents whose domain/expertise
            # matches the trending topic
            getattr(agent, "name", str(agent))
            expertise = getattr(agent, "expertise", []) or []
            if isinstance(expertise, str):
                expertise = [expertise]

            expertise_bonus = 0.0
            if domain and expertise:
                for exp in expertise:
                    if isinstance(exp, str) and domain.lower() in exp.lower():
                        expertise_bonus = 0.3
                        break

            # Combine: topic freshness * match quality + expertise alignment
            topic_score = max(matching_topics)  # Best matching topic's freshness
            return min(1.0, topic_score * 0.7 + expertise_bonus)

        except (AttributeError, TypeError, ValueError, KeyError, RuntimeError) as e:
            logger.debug(
                "Pulse relevance score failed for %s: %s", getattr(agent, "name", agent), e
            )
            return 0.0

    def _compute_regression_penalty(self, agent: Any, domain: str | None = None) -> float:
        """Penalize agents that participated in recent Nomic Loop regressions.

        Queries NomicOutcomeTracker for recent regression history and applies
        a penalty scaled by regression count and recency.

        Returns:
            Penalty from 0.0 (no regressions) to -0.5 (many recent regressions).
        """
        try:
            from aragora.nomic.outcome_tracker import NomicOutcomeTracker

            regressions = NomicOutcomeTracker.get_regression_history(limit=5)
            if not regressions:
                return 0.0

            agent_name = getattr(agent, "name", str(agent))
            agent_hits = 0.0
            for i, reg in enumerate(regressions):
                # Check if agent is mentioned in recommendation or regressed metrics
                rec = reg.get("recommendation", "")
                if agent_name.lower() in rec.lower():
                    # More recent regressions (lower index) get higher weight
                    recency_weight = 1.0 - (i * 0.15)
                    agent_hits += max(0.1, recency_weight)

            if agent_hits == 0:
                return 0.0

            # Scale: 1 hit = -0.1, 5 hits = -0.5
            return max(-0.5, -0.1 * agent_hits)

        except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.debug("Regression penalty failed for %s: %s", getattr(agent, "name", agent), e)
            return 0.0

    def _compute_introspection_score(self, agent: Any, domain: str | None = None) -> float:
        """Score agent using introspection snapshot (reputation + calibration).

        Queries the introspection API for agent reputation and calibration
        scores, returning the average as a 0-1 score.

        Returns:
            Score from 0.0 to 1.0 based on reputation and calibration.
        """
        try:
            from aragora.introspection.api import get_agent_introspection

            agent_name = getattr(agent, "name", str(agent))
            snapshot = get_agent_introspection(agent_name)
            # Only score agents with actual debate data to avoid default bias
            if getattr(snapshot, "debate_count", 0) == 0:
                return 0.0
            rep = getattr(snapshot, "reputation_score", 0.0)
            cal = getattr(snapshot, "calibration_score", 0.0)
            return (rep + cal) / 2.0

        except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.debug("Introspection score failed for %s: %s", getattr(agent, "name", agent), e)
            return 0.0

    def _compute_health_score(self, agent: Any, domain: str | None = None) -> float:
        """Score agent based on Control Plane health/availability status.

        Queries the AgentRegistry for the agent's current status and liveness,
        returning a score from 0.0 to 1.0.

        Returns:
            1.0 for READY agents with recent heartbeat,
            0.5 for BUSY agents,
            0.0 for OFFLINE/FAILED/unknown agents.
        """
        try:
            from aragora.control_plane.registry import AgentStatus

            agent_name = getattr(agent, "name", str(agent))
            # AgentRegistry.get() may be sync or async; handle both
            registry = self.control_plane_registry
            info = None
            if hasattr(registry, "get_sync"):
                info = registry.get_sync(agent_name)
            elif hasattr(registry, "_agents"):
                # Direct local cache access for synchronous scoring
                info = registry._agents.get(agent_name)

            if info is None:
                # Agent not registered in control plane — neutral score
                return 0.0

            # Check liveness (heartbeat within timeout)
            if hasattr(info, "is_alive") and not info.is_alive():
                return 0.0

            status = getattr(info, "status", None)
            if status == AgentStatus.READY:
                return 1.0
            elif status == AgentStatus.BUSY:
                return 0.5
            else:
                # OFFLINE, FAILED, STARTING, etc.
                return 0.0

        except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.debug("Health score failed for %s: %s", getattr(agent, "name", agent), e)
            return 0.0

    async def _warm_culture_cache(self, cache_key: str, task_type: str) -> None:
        """Warm culture recommendation cache from async context.

        Called via ensure_future when _compute_culture_score detects an
        already-running event loop.  The first call returns 0.0 while
        this fires in the background; subsequent calls in the same
        debate will hit the warm cache.
        """
        try:
            recommendations = await self.knowledge_mound.recommend_agents(task_type)
            self._culture_recommendations_cache[cache_key] = recommendations or []
        except (AttributeError, TypeError, ValueError, RuntimeError, OSError) as e:
            logger.debug("Culture cache warm-up failed for %s: %s", task_type, e)
            self._culture_recommendations_cache[cache_key] = []

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
            experts = self.ranking_adapter.get_domain_experts(
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
                    f"km_expertise_score agent={agent.name} domain={domain} "
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
                    f"performance_adapter_score agent={agent.name} domain={domain} "
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
                        f"elo_win_rate_score agent={agent.name} domain={domain} "
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
                        f"pattern_score_applied agent={agent.name} pattern={pattern} "
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
            f"cv_score agent={cv.agent_id} domain={domain} "
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

    def _compute_score(
        self,
        agent: Agent,
        domain: str | None = None,
        task: str = "",
        context: DebateContext | None = None,
        calibration_scores: dict[str, float] | None = None,
        agent_cvs: dict[str, AgentCV] | None = None,
        budget_shares: dict[str, float] | None = None,
        breakdown: dict[str, float] | None = None,
    ) -> float:
        """Compute composite score for an agent.

        Args:
            agent: Agent to score
            domain: Optional domain for domain-specific calibration lookup
            task: Task description for delegation-based scoring
            context: Optional debate context for state-aware scoring
            calibration_scores: Pre-fetched calibration scores (for batch performance)
            agent_cvs: Pre-fetched Agent CVs (for batch performance)
            budget_shares: Reliability-informed budget shares by agent
            breakdown: Optional dict to populate with per-component score contributions
        """
        score = self.config.base_score
        if breakdown is not None:
            breakdown["base"] = score

        # ELO contribution
        _prev = score
        if self.elo_system:
            try:
                rating = self.elo_system.get_rating(agent.name)
                # Handle both AgentRating objects and raw float values
                elo = rating.elo if hasattr(rating, "elo") else float(rating)
                # Normalize: baseline is average, each 100 points = weight bonus
                score += (elo - self.config.elo_baseline) / 1000 * self.config.elo_weight
            except (KeyError, AttributeError, TypeError) as e:
                logger.debug("ELO rating not found for %s: %s", agent.name, e)
        if breakdown is not None:
            breakdown["elo"] = round(score - _prev, 4)

        # Calibration contribution (well-calibrated agents get a bonus)
        # Uses pre-fetched scores when available for batch performance
        _prev = score
        if calibration_scores and agent.name in calibration_scores:
            brier = calibration_scores[agent.name]
            # Lower Brier = better calibration = higher score
            score += (1 - brier) * self.config.calibration_weight
        elif self.calibration_tracker:
            try:
                brier = self.calibration_tracker.get_brier_score(agent.name, domain=domain)
                # Lower Brier = better calibration = higher score
                score += (1 - brier) * self.config.calibration_weight
            except (KeyError, AttributeError, TypeError) as e:
                logger.debug("Calibration score not found for %s: %s", agent.name, e)
        if breakdown is not None:
            breakdown["calibration"] = round(score - _prev, 4)

        # Delegation strategy contribution
        _prev = score
        if self.delegation_strategy and task:
            try:
                delegation_score = self.delegation_strategy.score_agent(agent, task, context)
                # Normalize delegation score (assuming 0-5 range typical)
                normalized = min(delegation_score / 5.0, 1.0)
                score += normalized * self.config.delegation_weight
            except (AttributeError, TypeError) as e:
                logger.debug("Delegation score failed for %s: %s", agent.name, e)
        if breakdown is not None:
            breakdown["delegation"] = round(score - _prev, 4)

        # Domain capability contribution (agents matching domain get bonus)
        _prev = score
        if domain and self.config.enable_domain_filtering:
            domain_score = self._compute_domain_score(agent, domain)
            score += domain_score * self.config.domain_capability_weight
        if breakdown is not None:
            breakdown["domain"] = round(score - _prev, 4)

        # Culture-based contribution (agents recommended by org culture patterns)
        _prev = score
        if self.knowledge_mound and self.config.enable_culture_selection and domain:
            culture_score = self._compute_culture_score(agent, domain)
            score += culture_score * self.config.culture_weight
        if breakdown is not None:
            breakdown["culture"] = round(score - _prev, 4)

        # KM expertise contribution (historical performance from Knowledge Mound)
        _prev = score
        if self.ranking_adapter and self.config.enable_km_expertise and domain:
            km_expertise_score = self._compute_km_expertise_score(agent, domain)
            score += km_expertise_score * self.config.km_expertise_weight
        if breakdown is not None:
            breakdown["km_expertise"] = round(score - _prev, 4)

        # PerformanceAdapter contribution (combined ELO + expertise from KM)
        _prev = score
        if self.performance_adapter and self.config.enable_km_expertise and domain:
            perf_score = self._compute_performance_adapter_score(agent, domain)
            score += perf_score * self.config.km_expertise_weight
        if breakdown is not None:
            breakdown["performance_adapter"] = round(score - _prev, 4)

        # ELO domain win rate contribution (win/loss record in specific domains)
        _prev = score
        if self.elo_system and self.config.enable_elo_win_rate and domain:
            win_rate_score = self._compute_elo_win_rate_score(agent, domain)
            score += win_rate_score * self.config.elo_win_rate_weight
        if breakdown is not None:
            breakdown["elo_win_rate"] = round(score - _prev, 4)

        # Pattern-based contribution (historical success on task patterns)
        _prev = score
        if self.pattern_matcher and self.config.enable_pattern_selection and task:
            pattern_score = self._compute_pattern_score(agent, task)
            score += pattern_score * self.config.pattern_weight
        if breakdown is not None:
            breakdown["pattern"] = round(score - _prev, 4)

        # CV-based contribution (unified capability profile scoring)
        _prev = score
        if self.config.enable_cv_selection and agent_cvs and agent.name in agent_cvs:
            cv_score = self._compute_cv_score(agent_cvs[agent.name], domain)
            score += cv_score * self.config.cv_weight
        if breakdown is not None:
            breakdown["cv"] = round(score - _prev, 4)

        # Feedback loop contribution (domain-specific win/loss adjustment)
        _prev = score
        if self.feedback_loop and self.config.enable_feedback_weights and domain:
            try:
                adjustment = self.feedback_loop.get_domain_adjustment(agent.name, domain)
                score += adjustment * self.config.feedback_weight
            except (AttributeError, TypeError) as e:
                logger.debug("Feedback adjustment failed for %s: %s", agent.name, e)
        if breakdown is not None:
            breakdown["feedback"] = round(score - _prev, 4)

        # Reliability budget routing contribution
        _prev = score
        if (
            self.config.enable_reliability_budget_routing
            and budget_shares
            and agent.name in budget_shares
        ):
            score += float(budget_shares[agent.name]) * self.config.reliability_budget_share_weight
        if breakdown is not None:
            breakdown["budget_routing"] = round(score - _prev, 4)
            if budget_shares and agent.name in budget_shares:
                breakdown["budget_share"] = round(float(budget_shares[agent.name]), 4)

        # Specialist registry bonus (domain experts from ELO + Genesis breeding)
        _prev = score
        if self.specialist_registry and self.config.enable_specialist_bonus and domain:
            try:
                specialist_bonus = self.specialist_registry.score_bonus(
                    agent.name,
                    domain,
                    weight=self.config.specialist_weight,
                )
                score += specialist_bonus
            except (AttributeError, TypeError) as e:
                logger.debug("Specialist bonus failed for %s: %s", agent.name, e)
        if breakdown is not None:
            breakdown["specialist"] = round(score - _prev, 4)

        # UCB1 exploration bonus (agents with fewer debates get a temporary
        # score boost so the system explores new/underused agents rather than
        # always exploiting known winners.  Decays as data accumulates.)
        _prev = score
        if self.elo_system and self.config.enable_exploration_bonus:
            exploration_bonus = self._compute_exploration_bonus(agent, domain)
            score += exploration_bonus * self.config.exploration_weight
        if breakdown is not None:
            breakdown["exploration"] = round(score - _prev, 4)

        # ContinuumMemory contribution (historical agent performance on similar tasks)
        _prev = score
        if self.continuum_memory and self.config.enable_memory_selection and domain:
            memory_score = self._compute_memory_score(agent, domain, task)
            score += memory_score * self.config.memory_weight
        if breakdown is not None:
            breakdown["memory"] = round(score - _prev, 4)

        # Pulse (trending topic) relevance (agents with expertise in trending areas get a boost)
        _prev = score
        if self.pulse_manager and self.config.enable_pulse_selection and task:
            pulse_score = self._compute_pulse_relevance(agent, task, domain)
            score += pulse_score * self.config.pulse_weight
        if breakdown is not None:
            breakdown["pulse"] = round(score - _prev, 4)

        # Regression penalty (penalize agents involved in recent Nomic Loop regressions)
        _prev = score
        if self.config.enable_regression_penalty:
            regression_penalty = self._compute_regression_penalty(agent, domain)
            score += regression_penalty * self.config.regression_penalty_weight
        if breakdown is not None:
            breakdown["regression_penalty"] = round(score - _prev, 4)

        # Introspection scoring (reputation + calibration from introspection snapshots)
        _prev = score
        if self.config.enable_introspection_scoring:
            introspection_score = self._compute_introspection_score(agent, domain)
            score += introspection_score * self.config.introspection_weight
        if breakdown is not None:
            breakdown["introspection"] = round(score - _prev, 4)

        # Control Plane health contribution (agent availability/liveness)
        _prev = score
        if self.control_plane_registry and self.config.enable_health_filtering:
            health_score = self._compute_health_score(agent, domain)
            score += health_score * self.config.health_weight
        if breakdown is not None:
            breakdown["health"] = round(score - _prev, 4)

        # Soft domain filter penalty (non-preferred agents get penalized)
        _prev = score
        if agent.name in self._domain_non_preferred:
            score -= self.config.domain_soft_penalty
        if breakdown is not None:
            breakdown["domain_penalty"] = round(score - _prev, 4)

        # Meta-tuning diversity weight adjustment
        # When MetaLearner provides diversity tuning, adjust the domain capability
        # score contribution based on diversity_weight to encourage model heterogeneity.
        _prev = score
        meta_tuning = None
        if context is not None:
            arena = getattr(context, "arena", None)
            if arena is not None:
                meta_tuning = getattr(arena, "_meta_tuning", None)
        if meta_tuning and domain:
            diversity_weight = meta_tuning.get("diversity_weight", 0.5)
            # Apply a small bonus/penalty proportional to how far diversity_weight
            # deviates from the 0.5 default, scaled by domain capability weight
            diversity_adjustment = (diversity_weight - 0.5) * self.config.domain_capability_weight
            score += diversity_adjustment
        if breakdown is not None:
            breakdown["diversity"] = round(score - _prev, 4)

        return score

    def _compute_reliability_budget_shares(
        self,
        agent_names: list[str],
        calibration_scores: dict[str, float],
    ) -> dict[str, float]:
        """Compute per-agent budget shares from calibration and settled outcomes."""
        if not self.config.enable_reliability_budget_routing or not agent_names:
            return {}

        try:
            from aragora.debate.epistemic_outcomes import get_epistemic_outcome_store
            from aragora.debate.reliability_scheduler import ReliabilityScheduler

            scheduler = ReliabilityScheduler(min_share=self.config.reliability_budget_min_share)
            calibration_map: dict[str, dict[str, float | int]] = {}
            for name in agent_names:
                calibration_map[name] = {
                    "brier_score": float(calibration_scores.get(name, 0.5)),
                    "ece": 0.25,
                    "prediction_count": 0,
                }
                if self.calibration_tracker and hasattr(
                    self.calibration_tracker, "get_calibration_summary"
                ):
                    try:
                        summary = self.calibration_tracker.get_calibration_summary(name)
                        calibration_map[name]["ece"] = float(getattr(summary, "ece", 0.25))
                        calibration_map[name]["prediction_count"] = int(
                            getattr(summary, "total_predictions", 0)
                        )
                    except (AttributeError, TypeError, ValueError):
                        pass

            settled_outcomes = get_epistemic_outcome_store().list_outcomes(
                status="resolved",
                limit=500,
            )
            settlement_deltas = scheduler.build_settlement_deltas(settled_outcomes)
            return scheduler.allocate_budget(agent_names, calibration_map, settlement_deltas)
        except (ImportError, TypeError, ValueError, OSError) as e:
            logger.debug("reliability_budget_shares_skipped: %s", e)
            return {}

    def score_agent(
        self,
        agent: Agent,
        domain: str | None = None,
        task: str = "",
        context: DebateContext | None = None,
    ) -> float:
        """Get score for a single agent (for external use).

        Args:
            agent: Agent to score
            domain: Optional domain for domain-specific calibration
            task: Optional task for delegation-based scoring
            context: Optional debate context for state-aware scoring
        """
        return self._compute_score(agent, domain=domain, task=task, context=context)

    def apply_feedback_weights(
        self,
        agents: list[Agent],
        domain: str = "general",
    ) -> dict[str, float]:
        """Get feedback-based weight adjustments for a set of agents.

        Convenience method that returns domain-specific feedback weights
        for the given agents. Requires a feedback_loop to be configured.

        Args:
            agents: List of agents to get weights for
            domain: Domain to compute weights in

        Returns:
            Dict mapping agent names to weight adjustments
        """
        if not self.feedback_loop or not self.config.enable_feedback_weights:
            return {}
        try:
            return self.feedback_loop.get_domain_weights(domain)
        except (AttributeError, TypeError):
            return {}

    def set_delegation_strategy(self, strategy: DelegationStrategy) -> None:
        """Set or update the delegation strategy.

        Args:
            strategy: New delegation strategy to use
        """
        self.delegation_strategy = strategy

    def select_from_template(self, template_name: str) -> list[str]:
        """Return agent names (or role names) derived from a marketplace template.

        Looks up ``template_name`` in the marketplace registry and extracts the
        set of agent/role identifiers that the template prescribes.

        - For :class:`~aragora.marketplace.models.DebateTemplate`: returns the
          ``role`` value from each entry in ``agent_roles``.
        - For :class:`~aragora.marketplace.models.AgentTemplate`: returns a
          single-element list containing the ``agent_type``.
        - If the template is not found, logs a warning and returns ``[]``.

        Args:
            template_name: The ``metadata.id`` of the marketplace template to
                           look up (e.g. ``"oxford-style"``).

        Returns:
            A list of agent/role name strings, or ``[]`` on failure.
        """
        if not template_name:
            return []

        # Resolve the registry to use: prefer the one injected at construction
        # time, but fall back to constructing a default TemplateRegistry so the
        # method works even without explicit injection.
        registry = self.marketplace_registry
        if registry is None:
            try:
                from aragora.marketplace.registry import TemplateRegistry

                registry = TemplateRegistry()
            except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
                logger.warning(
                    "select_from_template: could not initialise TemplateRegistry: %s", exc
                )
                return []

        try:
            template = registry.get(template_name)
        except (OSError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            logger.warning(
                "select_from_template: registry lookup failed for %r: %s", template_name, exc
            )
            return []

        if template is None:
            logger.warning(
                "select_from_template: template %r not found in marketplace registry",
                template_name,
            )
            return []

        try:
            from aragora.marketplace.models import DebateTemplate, AgentTemplate

            if isinstance(template, DebateTemplate):
                # Extract the 'role' key from each agent_roles entry
                roles: list[str] = []
                for entry in template.agent_roles:
                    role = entry.get("role") if isinstance(entry, dict) else str(entry)
                    if role:
                        roles.append(role)
                return roles

            if isinstance(template, AgentTemplate):
                return [template.agent_type]

            # WorkflowTemplate or unknown type — return empty list
            logger.warning(
                "select_from_template: template %r has unsupported type %s",
                template_name,
                type(template).__name__,
            )
            return []
        except (ImportError, AttributeError, TypeError) as exc:
            logger.warning(
                "select_from_template: failed to extract agents from template %r: %s",
                template_name,
                exc,
            )
            return []

    def resolve_agents_from_template(
        self,
        template_name: str,
        available_agents: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Resolve agent assignments for a marketplace template.

        Calls :meth:`select_from_template` to obtain the role names prescribed
        by the template, then maps each role to a suggested agent provider
        using :data:`DOMAIN_CAPABILITY_MAP` when a matching domain keyword is
        found in the role name.

        Args:
            template_name: The ``metadata.id`` of the marketplace template
                           (e.g. ``"oxford-style"``).
            available_agents: Optional whitelist of agent names.  When provided,
                              the returned ``agent`` value is constrained to
                              entries in this list.

        Returns:
            A list of dicts, each with ``"role"`` and ``"agent"`` keys.  If no
            suitable agent can be determined, ``"agent"`` defaults to
            ``"claude"``.
        """
        roles = self.select_from_template(template_name)
        if not roles:
            return []

        result: list[dict[str, str]] = []
        for role in roles:
            agent = self._match_agent_for_role(role, available_agents)
            result.append({"role": role, "agent": agent})
        return result

    # ------------------------------------------------------------------
    # Internal helper for resolve_agents_from_template
    # ------------------------------------------------------------------

    @staticmethod
    def _match_agent_for_role(
        role: str,
        available_agents: list[str] | None = None,
    ) -> str:
        """Return the best agent name for a given role string.

        Scans the role name for keywords present in
        :data:`DOMAIN_CAPABILITY_MAP` and returns the first matching agent
        that is also in *available_agents* (if provided).  Falls back to
        ``"claude"`` when no match is found.
        """
        role_lower = role.lower()
        default = "claude"

        for domain, preferred in DOMAIN_CAPABILITY_MAP.items():
            if domain in role_lower and preferred:
                if available_agents is not None:
                    for agent in preferred:
                        if agent in available_agents:
                            return agent
                else:
                    return preferred[0]

        # Fallback: pick first available or default
        if available_agents:
            return available_agents[0]
        return default
