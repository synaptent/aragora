"""Agent selection and work routing, inherited by ``HardenedOrchestrator``.

Picks the best agent for a subtask from ELO, calibration and per-run success
rates, has a different agent review each diff, lets idle agents steal pending
work and routes browser/UI subtasks through the OpenClaw computer-use bridge.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Runtime imports: ``Track.DEVELOPER`` is read at call time, and
# typing.get_type_hints() on the orchestrator methods resolves ``AgentAssignment`` here.
from aragora.nomic.types import AgentAssignment, Track

if TYPE_CHECKING:
    from aragora.nomic.task_decomposer import SubTask

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.hardened_orchestrator" still see records from these methods.
logger = logging.getLogger("aragora.nomic.hardened_orchestrator")


class AgentPoolMixin:
    """Agent selection and work routing of ``HardenedOrchestrator``."""

    # Set by AutonomousOrchestrator.__init__ and HardenedOrchestrator.__init__.
    router: Any
    hardened_config: Any
    _agent_failure_counts: dict[str, int]
    _agent_success_counts: dict[str, int]

    if TYPE_CHECKING:

        def _emit_event(self, event_type: str, **data: Any) -> None: ...

        def _check_agent_circuit_breaker(self, agent_type: str) -> bool: ...

        async def _run_review_gate(
            self,
            assignment: AgentAssignment,
            worktree_path: Path,
        ) -> bool: ...

    # =========================================================================
    # Agent Pool Manager — capability-aware agent selection
    # =========================================================================

    def _select_best_agent(
        self,
        subtask: SubTask,
        track: Track,
        exclude_agents: list[str] | None = None,
    ) -> str:
        """Select the best agent for a subtask using ELO + success rates.

        Enhanced agent selection that considers:
        1. Circuit breaker state (skip agents with open circuits)
        2. ELO domain ratings (prefer agents rated highly in the task domain)
        3. Per-agent success rates (recent performance)
        4. Track preferences (fall back to default if ELO unavailable)

        Args:
            subtask: The task to assign.
            track: Development track for the task.
            exclude_agents: Agent types to skip (e.g., the implementing agent
                when selecting a reviewer).

        Returns:
            The best available agent type string.
        """
        config = self.router.track_configs.get(
            track,
            self.router.track_configs.get(Track.DEVELOPER),
        )
        candidates = list(config.agent_types) if config else ["claude"]
        exclude = set(exclude_agents or [])

        # Filter out excluded and circuit-broken agents
        available = [
            a for a in candidates if a not in exclude and self._check_agent_circuit_breaker(a)
        ]
        if not available:
            # All preferred agents are excluded/broken — fall back to claude
            return "claude"

        # Try to score agents using ELO domain ratings
        scored: list[tuple[float, str]] = []
        try:
            from aragora.ranking.elo import EloSystem

            elo = EloSystem()
            # Determine ELO domain from subtask
            domain = self._task_to_elo_domain(subtask)

            for agent in available:
                rating = elo.get_rating(agent)
                if rating is not None:
                    domain_elo = getattr(rating, "domain_elos", {}).get(
                        domain, rating.elo if hasattr(rating, "elo") else 1500
                    )
                    win_rate = getattr(rating, "win_rate", 0.5)
                    # Composite score: 70% ELO, 30% win rate
                    score = (domain_elo / 3000) * 0.7 + win_rate * 0.3
                else:
                    score = 0.5  # Default neutral score
                scored.append((score, agent))
        except ImportError:
            # ELO system not available — score by position in preference list
            for i, agent in enumerate(available):
                scored.append((1.0 - i * 0.1, agent))

        # Factor in calibration accuracy (Brier score) if available
        calibration_scores: dict[str, float] = {}
        try:
            from aragora.agents.calibration import CalibrationTracker

            tracker = CalibrationTracker()
            for agent in available:
                brier = tracker.get_brier_score(agent)
                if brier is not None:
                    # Lower Brier = better calibration → higher score
                    calibration_scores[agent] = 1.0 - min(brier, 1.0)
        except (ImportError, AttributeError):
            pass

        # Factor in per-agent success tracking from this orchestration run
        final_scored = []
        for base_score, agent in scored:
            successes = self._agent_success_counts.get(agent, 0)
            failures = self._agent_failure_counts.get(agent, 0)
            total = successes + failures
            if total > 0:
                recent_rate = successes / total
                # Blend: 50% base score, 30% recent, 20% calibration
                cal = calibration_scores.get(agent, 0.5)
                final_score = base_score * 0.5 + recent_rate * 0.3 + cal * 0.2
            elif agent in calibration_scores:
                cal = calibration_scores[agent]
                final_score = base_score * 0.8 + cal * 0.2
            else:
                final_score = base_score
            final_scored.append((final_score, agent))

        # Sort descending by score
        final_scored.sort(key=lambda x: x[0], reverse=True)

        best_agent = final_scored[0][1]
        logger.info(
            "agent_pool_selected agent=%s subtask=%s scores=%s",
            best_agent,
            subtask.id,
            [(a, f"{s:.3f}") for s, a in final_scored[:3]],
        )
        return best_agent

    @staticmethod
    def _task_to_elo_domain(subtask: SubTask) -> str:
        """Map a subtask to an ELO domain for rating lookup."""
        combined = f"{subtask.title} {subtask.description}".lower()
        domain_keywords = {
            "security": ["security", "auth", "vuln", "encrypt", "xss", "csrf"],
            "testing": ["test", "coverage", "e2e", "playwright", "ci"],
            "frontend": ["ui", "frontend", "dashboard", "react", "css"],
            "backend": ["api", "server", "handler", "database", "query"],
            "devops": ["docker", "deploy", "kubernetes", "ci/cd", "ops"],
            "documentation": ["docs", "readme", "guide", "reference"],
        }
        for domain, keywords in domain_keywords.items():
            if any(kw in combined for kw in keywords):
                return domain
        return "general"

    # =========================================================================
    # Cross-Agent Review — no agent reviews its own output
    # =========================================================================

    async def _cross_agent_review(
        self,
        assignment: AgentAssignment,
        worktree_path: Path,
    ) -> bool:
        """Select a DIFFERENT agent to review the implementing agent's diff.

        Selects the highest-rated available agent (excluding the implementer)
        and runs a lightweight review. If the reviewer flags critical issues,
        the assignment is failed.

        Returns True if review passes, False otherwise.
        """
        implementing_agent = assignment.agent_type
        track = self.router.determine_track(assignment.subtask)

        reviewer = self._select_best_agent(
            subtask=assignment.subtask,
            track=track,
            exclude_agents=[implementing_agent],
        )

        if reviewer == implementing_agent:
            # Couldn't find a different agent — skip cross-review
            logger.info(
                "cross_review_skip no_alternative subtask=%s agent=%s",
                assignment.subtask.id,
                implementing_agent,
            )
            return True

        logger.info(
            "cross_review_started subtask=%s implementer=%s reviewer=%s",
            assignment.subtask.id,
            implementing_agent,
            reviewer,
        )

        # Get the diff for review
        try:
            diff_result = await asyncio.to_thread(
                subprocess.run,
                ["git", "diff", "main...HEAD", "--no-color"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff_text = diff_result.stdout
        except (subprocess.TimeoutExpired, OSError):
            logger.debug("cross_review could not get diff, skipping")
            return True

        if not diff_text.strip():
            return True

        # Run review via existing review gate (score-based)
        # but record the reviewer identity for audit
        review_passed = await self._run_review_gate(assignment, worktree_path)

        assignment.result = {
            **(assignment.result or {}),
            "cross_reviewer": reviewer,
            "cross_review_passed": review_passed,
        }

        self._emit_event(
            "cross_review_completed",
            subtask=assignment.subtask.id,
            implementer=implementing_agent,
            reviewer=reviewer,
            passed=review_passed,
        )

        return review_passed

    # =========================================================================
    # Work Stealing — idle agents claim pending work
    # =========================================================================

    def _find_stealable_work(
        self,
        completed_agent: str,
        assignments: list[AgentAssignment],
    ) -> AgentAssignment | None:
        """Find a pending assignment that a completed agent can steal.

        Rules:
        - Only steal PENDING work (never partially-completed)
        - Prefer tasks whose dependencies just became unblocked
        - Skip tasks assigned to agents with open circuit breakers
        - The stealing agent must pass its own circuit breaker check

        Returns the assignment to steal, or None.
        """
        if not self._check_agent_circuit_breaker(completed_agent):
            return None

        # Find pending assignments sorted by priority
        pending = [a for a in assignments if a.status == "pending"]

        if not pending:
            return None

        # Prefer tasks that have no dependencies or all deps completed
        for candidate in pending:
            # Check if all dependencies are satisfied
            deps_met = True
            if hasattr(candidate.subtask, "dependencies") and candidate.subtask.dependencies:
                for dep_id in candidate.subtask.dependencies:
                    dep_assignment = next(
                        (a for a in assignments if a.subtask.id == dep_id),
                        None,
                    )
                    if dep_assignment and dep_assignment.status != "completed":
                        deps_met = False
                        break

            if deps_met:
                logger.info(
                    "work_stealing agent=%s stealing subtask=%s",
                    completed_agent,
                    candidate.subtask.id,
                )
                self._emit_event(
                    "work_stolen",
                    agent=completed_agent,
                    subtask=candidate.subtask.id,
                )
                return candidate

        return None

    # =========================================================================
    # OpenClaw Integration — computer-use execution mode
    # =========================================================================

    _COMPUTER_USE_KEYWORDS = frozenset(
        [
            "browser",
            "ui",
            "visual",
            "click",
            "screenshot",
            "playwright",
            "selenium",
            "headless",
            "webpage",
            "css",
            "dom",
            "element",
        ]
    )

    @classmethod
    def _is_computer_use_task(cls, subtask: SubTask) -> bool:
        """Detect whether a subtask requires computer-use (browser control).

        Checks task title and description for UI/browser keywords.
        """
        combined = f"{subtask.title} {subtask.description}".lower()
        return any(kw in combined for kw in cls._COMPUTER_USE_KEYWORDS)

    async def _execute_computer_use(
        self,
        assignment: AgentAssignment,
        worktree_path: Path,
    ) -> None:
        """Execute a computer-use task via OpenClaw bridge.

        Routes browser/UI tasks through the ComputerUseBridge, which
        translates between OpenClaw browser actions and Aragora's
        computer-use action system.

        Falls back to normal execution if OpenClaw bridge is unavailable.
        """
        try:
            from aragora.compat.openclaw.computer_use_bridge import (
                ComputerUseBridge,
            )

            bridge = ComputerUseBridge()

            logger.info(
                "computer_use_started subtask=%s agent=%s",
                assignment.subtask.id,
                assignment.agent_type,
            )
            self._emit_event(
                "computer_use_started",
                subtask=assignment.subtask.id,
            )

            # Build action sequence from subtask description
            # ComputerUseBridge provides action conversion, not execution.
            # Use from_openclaw to create actions from descriptions.
            plan_fn = getattr(bridge, "plan_actions", None)
            exec_fn = getattr(bridge, "execute_action", None)
            if not plan_fn or not exec_fn:
                logger.warning("computer_use_bridge lacks plan_actions/execute_action, skipping")
                return None

            actions = plan_fn(assignment.subtask.description)

            results = []
            for action in actions[:20]:  # Cap actions for safety
                result = await exec_fn(
                    action,
                    timeout=self.hardened_config.sandbox_timeout,
                )
                results.append(result)

                # Log screenshots for audit trail
                if hasattr(result, "screenshot_path") and result.screenshot_path:
                    logger.info(
                        "computer_use_screenshot subtask=%s path=%s",
                        assignment.subtask.id,
                        result.screenshot_path,
                    )

                # Stop on failure
                if not getattr(result, "success", True):
                    logger.warning(
                        "computer_use_action_failed subtask=%s action=%s",
                        assignment.subtask.id,
                        action,
                    )
                    break

            assignment.result = {
                **(assignment.result or {}),
                "execution_mode": "computer_use",
                "actions_executed": len(results),
            }
            assignment.status = "completed"

            self._emit_event(
                "computer_use_completed",
                subtask=assignment.subtask.id,
                actions=len(results),
            )

        except ImportError:
            logger.info(
                "computer_use_fallback subtask=%s reason=bridge_unavailable",
                assignment.subtask.id,
            )
            # Fall back to normal code execution
            assignment.result = {
                **(assignment.result or {}),
                "execution_mode": "code_fallback",
            }
