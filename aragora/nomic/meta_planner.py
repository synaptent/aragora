"""Meta-Planner for debate-driven goal prioritization.

Takes high-level business objectives and uses multi-agent debate to
determine which areas should be improved first.

Includes cross-cycle learning: queries past Nomic Loop outcomes from
the Knowledge Mound to inform planning and avoid repeating failures.

Usage:
    from aragora.nomic.meta_planner import MetaPlanner

    planner = MetaPlanner()
    goals = await planner.prioritize_work(
        objective="Maximize utility for SME businesses",
        available_tracks=[Track.SME, Track.QA],
    )

    for goal in goals:
        print(f"{goal.track}: {goal.description} ({goal.estimated_impact})")
"""

from __future__ import annotations

import logging
import re
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from aragora.nomic.types import Track  # noqa: F401 — re-exported for backward compat
from aragora.nomic.meta_planner_utils import (  # noqa: F401 — re-exported
    build_debate_topic,
    build_goal,
    build_repository_planning_topic,
    gather_file_excerpts,
    infer_track,
    parse_goals_from_debate,
    proposal_failure_provenance,
)
from aragora.config.feature_flags import get_flag, is_enabled

if TYPE_CHECKING:
    from aragora.core_types import DebateResult
    from aragora.gauntlet.receipt_models import DecisionReceipt
    from aragora.nomic.repository_profile import ContextPack

logger = logging.getLogger(__name__)


def _scope_summary(
    affected_files: list[str],
    expected_tests: list[str],
) -> str:
    """Render compact pipeline scope context for planning feedback."""
    parts: list[str] = []
    if affected_files:
        parts.append(f"files: {', '.join(affected_files[:3])}")
    if expected_tests:
        parts.append(f"tests: {'; '.join(expected_tests[:2])}")
    if not parts:
        return ""
    return f" ({'; '.join(parts)})"


@dataclass
class PrioritizedGoal:
    """A prioritized improvement goal."""

    id: str
    track: Track
    description: str
    rationale: str
    estimated_impact: str  # high, medium, low
    priority: int  # 1 = highest
    focus_areas: list[str] = field(default_factory=list)
    file_hints: list[str] = field(default_factory=list)
    criterion_scores: dict[str, float] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the additive planning-goal shape."""
        return {
            "id": self.id,
            "track": self.track.value,
            "description": self.description,
            "rationale": self.rationale,
            "estimated_impact": self.estimated_impact,
            "priority": self.priority,
            "focus_areas": list(self.focus_areas),
            "file_hints": list(self.file_hints),
            "criterion_scores": dict(sorted(self.criterion_scores.items())),
            "evidence_refs": sorted(self.evidence_refs),
            "metadata": dict(self.metadata),
        }


@dataclass
class MetaPlanningResult:
    """Evidence-bearing result from generic repository planning."""

    objective: str
    context_pack: ContextPack
    goals: list[PrioritizedGoal]
    receipt: DecisionReceipt
    evidence_coverage: float
    substantive_debate: bool
    receipt_json_path: Path
    receipt_markdown_path: Path
    debate_result: DebateResult = field(repr=False)

    @property
    def status(self) -> str:
        return "planned" if self.receipt.verdict != "NO_EVIDENCE" else "no_evidence"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "objective": self.objective,
            "repository_id": self.context_pack.repository.repository_id,
            "commit_sha": self.context_pack.revision.commit_sha,
            "profile_hash": self.context_pack.profile_hash,
            "pack_id": self.context_pack.pack_id,
            "pack_reference": self.context_pack.reference,
            "goals": [goal.to_dict() for goal in self.goals],
            "evidence_coverage": self.evidence_coverage,
            "substantive_debate": self.substantive_debate,
            "verdict": self.receipt.verdict,
            "receipt": self.receipt.to_dict(),
            "receipt_json_path": str(self.receipt_json_path),
            "receipt_markdown_path": str(self.receipt_markdown_path),
        }


@dataclass
class HistoricalLearning:
    """Learning from a past Nomic cycle."""

    cycle_id: str
    objective: str
    was_success: bool
    lesson: str
    relevance: float  # 0-1, how relevant to current objective


@dataclass
class PlanningContext:
    """Context for meta-planning decisions."""

    recent_issues: list[str] = field(default_factory=list)
    test_failures: list[str] = field(default_factory=list)
    user_feedback: list[str] = field(default_factory=list)
    recent_changes: list[str] = field(default_factory=list)
    # Externally supplied candidate goals the debate must evaluate and rank.
    # Unlike recent_issues (background context, capped at 5 in the topic),
    # every candidate is rendered into the debate topic.
    candidate_goals: list[str] = field(default_factory=list)
    # Cross-cycle learning
    historical_learnings: list[HistoricalLearning] = field(default_factory=list)
    past_failures_to_avoid: list[str] = field(default_factory=list)
    past_successes_to_build_on: list[str] = field(default_factory=list)
    # CI feedback
    ci_failures: list[str] = field(default_factory=list)
    ci_flaky_tests: list[str] = field(default_factory=list)
    # Debate-sourced improvement suggestions
    recent_improvements: list[dict[str, Any]] = field(default_factory=list)
    # Codebase metrics snapshot (from MetricsCollector)
    metric_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetaPlannerConfig:
    """Configuration for MetaPlanner."""

    agents: list[str] = field(default_factory=lambda: ["claude", "gemini", "deepseek"])
    debate_rounds: int = 2
    max_goals: int = 5
    consensus_threshold: float = 0.6
    # Optional proposal-only timeout; None preserves the Arena default.
    proposal_timeout_seconds: float | None = None
    # Cross-cycle learning
    enable_cross_cycle_learning: bool = True
    max_similar_cycles: int = 5
    min_cycle_similarity: float = 0.5
    # Quick mode: skip debate, use heuristic for concrete goals
    quick_mode: bool = False
    # Use introspection data to select agents for planning debates
    use_introspection_selection: bool = True
    # Trickster: detect hollow consensus in self-improvement debates
    enable_trickster: bool = True
    trickster_sensitivity: float = 0.7
    # Convergence detection for semantic consensus
    enable_convergence: bool = True
    # Generate DecisionReceipts for self-improvement decisions
    enable_receipts: bool = True
    # Inject codebase metrics into planning context
    enable_metrics_collection: bool = True
    # Scan mode: prioritize from codebase signals without LLM calls
    scan_mode: bool = False
    # Auto-execute low-risk goals (test fixes, doc updates, lint) without approval
    auto_execute_low_risk: bool = False
    # Risk threshold: goals scoring below this are considered "low risk"
    low_risk_threshold: float = 0.3
    # Generate self-explanations for planning decisions
    explain_decisions: bool = True
    # Use business context to re-rank goals by impact
    use_business_context: bool = True
    # Objective fidelity recovery
    enforce_objective_fidelity: bool = True
    objective_fidelity_threshold: float = 0.2
    # Opt-in: include OpenRouter Fusion (multi-model council+judge) as an extra
    # participant in planning debates. Default OFF -- Fusion is ~4-5x cost. Also
    # gated globally by the enable_fusion feature flag and a positive
    # fusion_cost_budget_per_debate (set the budget to 0 to hard-disable).
    enable_fusion: bool = False
    # Repository root used by every local scan and by generic planning publication.
    repo_path: str = "."


class MetaPlanner:
    """Debate-driven goal prioritization.

    Uses multi-agent debate to determine which areas should be improved
    to best achieve a high-level objective.
    """

    def __init__(self, config: MetaPlannerConfig | None = None) -> None:
        self.config = config or MetaPlannerConfig()
        self._agent: Any | None = None
        # Receipt from the most recent planning debate, for callers that
        # persist it as a file artifact (KM ingestion is fire-and-forget).
        self.last_receipt: Any | None = None
        self._feedback_loop = None
        try:
            from aragora.debate.selection_feedback import SelectionFeedbackLoop

            self._feedback_loop = SelectionFeedbackLoop()
        except (ImportError, RuntimeError):
            pass

        # Goal proposer: telemetry-driven goal generation
        self._goal_proposer = None
        try:
            from aragora.nomic.goal_proposer import GoalProposer

            # Defer the SQLite telemetry collector until propose_goals() is
            # actually used. Generic plan() must not dirty a clean repository
            # merely by constructing a planner.
            self._goal_proposer = GoalProposer()
        except ImportError:
            pass

    async def plan(
        self,
        objective: str,
        context_pack: ContextPack,
        *,
        constraints: list[str] | None = None,
    ) -> MetaPlanningResult:
        """Run the repository-neutral planning debate and persist its receipt.

        This API is deliberately evidence-bearing: heuristic or single-model
        fallback output is never promoted into settled goals.
        """
        from aragora.gauntlet.receipt_models import DecisionReceipt
        from aragora.nomic.repository_profile import assert_clean_revision

        if not objective.strip():
            raise ValueError("planning objective must be non-empty")
        root = Path(self.config.repo_path).resolve()
        expected_pack_path = (
            root
            / ".nomic"
            / "context"
            / "packs"
            / context_pack.revision.commit_sha
            / context_pack.pack_id
        )
        if context_pack.pack_path.resolve() != expected_pack_path:
            raise ValueError("context pack does not belong to the configured repository root")

        context_markdown = (context_pack.pack_path / "context.md").read_text(encoding="utf-8")
        prompt = build_repository_planning_topic(
            objective=objective,
            repository_name=context_pack.repository.repository_name,
            repository_id=context_pack.repository.repository_id,
            commit_sha=context_pack.revision.commit_sha,
            pack_reference=context_pack.reference,
            roadmap_paths=list(context_pack.repository.roadmap_paths),
            context_entry_files=list(context_pack.repository.context_entry_files),
            evaluation_criteria=[
                (criterion.id, criterion.description)
                for criterion in context_pack.repository.evaluation_criteria
            ],
            context_markdown=context_markdown,
            max_goals=self.config.max_goals,
        )
        if constraints:
            prompt += "\nADDITIONAL CONSTRAINTS:\n" + "\n".join(
                f"- {constraint}" for constraint in constraints
            )

        debate_result = await self._run_repository_planning_debate(prompt, context_pack)
        metadata = getattr(debate_result, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            debate_result.metadata = metadata
        metadata.update(
            {
                "nomic_context_pack": context_pack.reference,
                "nomic_pack_id": context_pack.pack_id,
                "nomic_commit_sha": context_pack.revision.commit_sha,
                "nomic_profile_hash": context_pack.profile_hash,
            }
        )

        substantive = self._has_substantive_multimodel_debate(debate_result)
        goals = self._parse_repository_goals(debate_result.final_answer, context_pack)
        if not substantive:
            goals = []
        evidence_coverage = (
            sum(bool(goal.evidence_refs) for goal in goals) / len(goals) if goals else 0.0
        )
        evidence_by_id = {item.evidence_id: item for item in context_pack.evidence}
        referenced_ids = sorted(
            {evidence_id for goal in goals for evidence_id in goal.evidence_refs}
        )
        evidence_references = [evidence_by_id[item].to_dict() for item in referenced_ids]
        decision_payload = {
            "objective": objective,
            "repository_id": context_pack.repository.repository_id,
            "commit_sha": context_pack.revision.commit_sha,
            "profile_hash": context_pack.profile_hash,
            "pack_id": context_pack.pack_id,
            "evidence_coverage": evidence_coverage,
            "goals": [goal.to_dict() for goal in goals],
        }
        input_hash = self._planning_input_hash(objective, context_pack)
        receipt = DecisionReceipt.from_debate_result(
            debate_result,
            input_hash=input_hash,
            evidence_references=evidence_references,
            decision_payload=decision_payload,
        )
        verdict = receipt.verdict
        reasoning = receipt.verdict_reasoning
        if not substantive:
            verdict = "NO_EVIDENCE"
            reasoning = "NO EVIDENCE: fewer than two models produced substantive planning input."
        elif evidence_coverage == 0.0:
            verdict = "NO_EVIDENCE"
            reasoning = "NO EVIDENCE: no selected goal resolved to context-pack evidence."
        elif evidence_coverage < 1.0 and verdict == "PASS":
            verdict = "CONDITIONAL"
            reasoning = (
                f"Evidence coverage is partial ({evidence_coverage:.1%}); "
                "the planning decision cannot receive a PASS verdict."
            )
        receipt = replace(
            receipt,
            verdict=verdict,
            confidence=0.0 if verdict == "NO_EVIDENCE" else receipt.confidence,
            robustness_score=0.0 if verdict == "NO_EVIDENCE" else receipt.robustness_score,
            verdict_reasoning=reasoning,
            artifact_hash="",
        )

        # The debate may be long-running. Bind publication to the same clean HEAD.
        assert_clean_revision(root, context_pack.revision)
        json_path = context_pack.pack_path / f"decision-receipt-{receipt.receipt_id}.json"
        markdown_path = context_pack.pack_path / f"decision-receipt-{receipt.receipt_id}.md"
        self._persist_planning_receipt(receipt, json_path, markdown_path)
        self._ingest_receipt_to_km(receipt)
        return MetaPlanningResult(
            objective=objective,
            context_pack=context_pack,
            goals=goals,
            receipt=receipt,
            evidence_coverage=evidence_coverage,
            substantive_debate=substantive,
            receipt_json_path=json_path,
            receipt_markdown_path=markdown_path,
            debate_result=debate_result,
        )

    async def _run_repository_planning_debate(
        self,
        prompt: str,
        context_pack: ContextPack,
    ) -> DebateResult:
        """Run a real multi-model debate, returning zero evidence if unavailable."""
        from aragora.core import Environment
        from aragora.core_types import DebateResult
        from aragora.debate.orchestrator import Arena, DebateProtocol

        configured = self._maybe_add_fusion(list(dict.fromkeys(self.config.agents)))
        agents: list[Any] = []
        identities: list[str] = []
        for agent_type in configured:
            try:
                agent = self._create_agent(agent_type)
            except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as exc:
                logger.warning("Could not create planning agent %s: %s", agent_type, exc)
                continue
            if agent is None:
                continue
            agents.append(agent)
            model = str(getattr(agent, "model", "") or agent_type)
            identities.append(model)

        metadata = {
            "nomic_planning_models": sorted(set(identities)),
            "nomic_context_pack": context_pack.reference,
        }
        if len(set(identities)) < 2:
            return DebateResult(task=prompt, participants=[], metadata=metadata)

        protocol = DebateProtocol(
            rounds=self.config.debate_rounds,
            consensus="weighted",
            enable_trickster=self.config.enable_trickster,
            trickster_sensitivity=self.config.trickster_sensitivity,
            convergence_detection=self.config.enable_convergence,
        )
        result = await Arena(Environment(task=prompt), agents, protocol).run()
        result.metadata = dict(getattr(result, "metadata", {}) or {})
        result.metadata.update(metadata)
        return result

    def _parse_repository_goals(
        self,
        response: str,
        context_pack: ContextPack,
    ) -> list[PrioritizedGoal]:
        """Parse strict structured goals and resolve their paths to evidence IDs."""
        payload = self._extract_json_object(response)
        raw_goals = payload.get("goals") if payload else None
        if not isinstance(raw_goals, list):
            return []
        criterion_ids = [item.id for item in context_pack.repository.evaluation_criteria]
        evidence_by_path = {item.path: item.evidence_id for item in context_pack.evidence}
        goals: list[PrioritizedGoal] = []
        for raw_goal in raw_goals[: self.config.max_goals]:
            if not isinstance(raw_goal, dict):
                continue
            description = str(raw_goal.get("description") or "").strip()
            rationale = str(raw_goal.get("rationale") or "").strip()
            raw_scores = raw_goal.get("criterion_scores")
            raw_paths = raw_goal.get("evidence_paths")
            if (
                not description
                or not isinstance(raw_scores, dict)
                or not isinstance(raw_paths, list)
            ):
                continue
            scores: dict[str, float] = {}
            for criterion_id in criterion_ids:
                value = raw_scores.get(criterion_id)
                if isinstance(value, bool) or not isinstance(value, int | float):
                    scores = {}
                    break
                numeric = float(value)
                if not 0.0 <= numeric <= 1.0:
                    scores = {}
                    break
                scores[criterion_id] = numeric
            if len(scores) != len(criterion_ids):
                continue
            evidence_refs: list[str] = []
            file_hints: list[str] = []
            for raw_path in raw_paths:
                if not isinstance(raw_path, str):
                    continue
                path = raw_path.strip().removeprefix("./").split("#L", 1)[0]
                evidence_id = evidence_by_path.get(path)
                if evidence_id and evidence_id not in evidence_refs:
                    evidence_refs.append(evidence_id)
                    file_hints.append(path)
            impact = str(raw_goal.get("estimated_impact") or "medium").lower()
            if impact not in {"high", "medium", "low"}:
                impact = "medium"
            goals.append(
                PrioritizedGoal(
                    id=f"goal_{len(goals)}",
                    track=Track.CORE,
                    description=description,
                    rationale=rationale,
                    estimated_impact=impact,
                    priority=len(goals) + 1,
                    file_hints=file_hints,
                    criterion_scores=scores,
                    evidence_refs=evidence_refs,
                )
            )
        return goals

    @staticmethod
    def _extract_json_object(response: str) -> dict[str, Any] | None:
        decoder = json.JSONDecoder()
        for index, character in enumerate(response or ""):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(response[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _has_substantive_multimodel_debate(result: DebateResult) -> bool:
        from aragora.agents.failure_semantics import looks_like_agent_failure_response

        metadata = getattr(result, "metadata", {}) or {}
        models = {str(item) for item in metadata.get("nomic_planning_models", []) if item}
        response_agents: set[str] = set()
        proposals = getattr(result, "proposals", {}) or {}
        if isinstance(proposals, dict):
            response_agents.update(
                str(agent)
                for agent, text in proposals.items()
                if not looks_like_agent_failure_response(text)
            )
        for item in getattr(result, "agent_responses", []) or []:
            if isinstance(item, dict):
                agent = item.get("agent") or item.get("name")
                text = item.get("response") or item.get("content")
            else:
                agent = getattr(item, "agent", None)
                text = getattr(item, "response", None) or getattr(item, "content", None)
            if agent and not looks_like_agent_failure_response(text):
                response_agents.add(str(agent))
        for message in getattr(result, "messages", []) or []:
            agent = getattr(message, "agent", None)
            text = getattr(message, "content", None)
            if agent and not looks_like_agent_failure_response(text):
                response_agents.add(str(agent))
        return len(models) >= 2 and len(response_agents) >= 2

    @staticmethod
    def _planning_input_hash(objective: str, context_pack: ContextPack) -> str:
        payload = {
            "objective": objective,
            "repository_id": context_pack.repository.repository_id,
            "commit_sha": context_pack.revision.commit_sha,
            "profile_hash": context_pack.profile_hash,
            "pack_id": context_pack.pack_id,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _persist_planning_receipt(
        receipt: DecisionReceipt,
        json_path: Path,
        markdown_path: Path,
    ) -> None:
        """Synchronously publish both native receipt artifacts."""
        json_bytes = (receipt.to_json() + "\n").encode()
        markdown_bytes = (receipt.to_markdown().rstrip() + "\n").encode()
        temporary = Path(tempfile.mkdtemp(prefix=".decision-receipt-", dir=json_path.parent))
        try:
            temp_json = temporary / json_path.name
            temp_markdown = temporary / markdown_path.name
            temp_json.write_bytes(json_bytes)
            temp_markdown.write_bytes(markdown_bytes)
            os.replace(temp_json, json_path)
            os.replace(temp_markdown, markdown_path)
        finally:
            for remaining in temporary.iterdir():
                remaining.unlink()
            temporary.rmdir()

    async def prioritize_work(
        self,
        objective: str | None = None,
        available_tracks: list[Track] | None = None,
        constraints: list[str] | None = None,
        context: PlanningContext | None = None,
    ) -> list[PrioritizedGoal]:
        """Use multi-agent debate to prioritize work.

        Args:
            objective: High-level business objective. None for self-directing
                       scan mode where goals are derived from codebase signals.
            available_tracks: Which tracks can be worked on
            constraints: Constraints like "no breaking changes"
            context: Additional context (issues, feedback, etc.)

        Returns:
            List of prioritized goals ordered by priority
        """
        available_tracks = available_tracks or list(Track)
        constraints = constraints or []
        context = context or PlanningContext()

        # Self-directing mode: when objective is None, force scan mode
        if objective is None:
            if not self.config.scan_mode:
                self.config.scan_mode = True
            logger.info(
                "meta_planner_self_directing tracks=%s",
                [t.value for t in available_tracks],
            )
            return await self._scan_prioritize(None, available_tracks)

        logger.info(
            "meta_planner_started objective=%s tracks=%s",
            objective[:100],
            [t.value for t in available_tracks],
        )

        # Quick mode: skip debate entirely, use heuristic
        if self.config.quick_mode:
            logger.info("meta_planner_quick_mode using heuristic prioritization")
            goals = self._heuristic_prioritize(objective, available_tracks)
            return self._enforce_objective_fidelity(objective, available_tracks, goals)

        # Scan mode: prioritize from codebase signals without LLM calls
        if self.config.scan_mode:
            logger.info("meta_planner_scan_mode using codebase signals")
            goals = await self._scan_prioritize(objective, available_tracks)
            return self._enforce_objective_fidelity(objective, available_tracks, goals)

        # Inject codebase metrics for data-driven planning
        if self.config.enable_metrics_collection:
            context = self._enrich_context_with_metrics(context)

        # Cross-cycle learning: Query past similar cycles
        if self.config.enable_cross_cycle_learning:
            context = await self._enrich_context_with_history(objective, available_tracks, context)

        # Inject findings from cross-agent learning bus
        if self.config.enable_cross_cycle_learning:
            self._inject_learning_bus_findings(context)

        # Inject debate-sourced improvement suggestions (consume from queue)
        try:
            from aragora.nomic.improvement_queue import get_improvement_queue

            queue = get_improvement_queue()
            suggestions = queue.dequeue_batch(10)
            if suggestions:
                context.recent_improvements = [
                    {"task": s.task, "category": s.category, "confidence": s.confidence}
                    for s in suggestions
                ]
                logger.info("meta_planner_consumed_improvements count=%d", len(suggestions))
        except ImportError:
            pass

        # Auto-discover actionable items from codebase signals
        try:
            from aragora.compat.openclaw.next_steps_runner import NextStepsRunner

            runner = NextStepsRunner(
                repo_path=self.config.repo_path,
                scan_code=True,
                scan_issues=False,  # Skip GitHub API calls
                scan_prs=False,
                scan_tests=False,
                scan_deps=False,
                scan_docs=True,
                limit=20,
            )
            scan_result = await runner.scan()
            if scan_result.steps:
                # Feed high-priority items into planning context
                for step in scan_result.steps[:10]:
                    if step.priority in ("critical", "high"):
                        if (
                            step.source == "test-failure"
                            and step.title not in context.test_failures
                        ):
                            context.test_failures.append(step.title)
                        elif step.title not in context.recent_issues:
                            context.recent_issues.append(f"[{step.category}] {step.title}")
                logger.info(
                    "meta_planner_injected_next_steps count=%d",
                    min(len(scan_result.steps), 10),
                )
        except ImportError:
            pass
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("NextStepsRunner scan skipped: %s", e)

        try:
            from aragora.debate.orchestrator import Arena, DebateProtocol
            from aragora.core import Environment

            # Build debate topic
            topic = self._build_debate_topic(objective, available_tracks, constraints, context)

            # Select agents: use introspection ranking if available
            agent_types = (
                self._select_agents_by_introspection(objective)
                if self.config.use_introspection_selection
                else self.config.agents
            )
            # Opt-in: add OpenRouter Fusion as an extra council/judge participant.
            agent_types = self._maybe_add_fusion(list(agent_types))

            # Create agents using get_secret pattern for API key resolution
            agents = []
            for agent_type in agent_types:
                try:
                    agent = self._create_agent(agent_type)
                    if agent is not None:
                        agents.append(agent)
                except (RuntimeError, OSError, ConnectionError, TimeoutError, ValueError) as e:
                    logger.warning("Could not create agent %s: %s", agent_type, e)

            if not agents:
                logger.warning("No agents available, using heuristic prioritization")
                goals = self._heuristic_prioritize(objective, available_tracks)
                return self._enforce_objective_fidelity(objective, available_tracks, goals)

            # Run debate with Trickster and convergence detection
            env = Environment(task=topic)
            protocol = DebateProtocol(
                rounds=self.config.debate_rounds,
                consensus="weighted",
                enable_trickster=self.config.enable_trickster,
                trickster_sensitivity=self.config.trickster_sensitivity,
                convergence_detection=self.config.enable_convergence,
            )

            arena = Arena(env, agents, protocol)
            if self.config.proposal_timeout_seconds is not None:
                arena.proposal_phase.proposal_timeout_seconds = self.config.proposal_timeout_seconds
            result = await arena.run()

            # Generate DecisionReceipt for audit trail
            self._generate_receipt(result)

            # Parse goals from debate result
            expected_proposers = [agent.name for agent in agents]
            goals = self._parse_goals_from_debate(
                result,
                available_tracks,
                objective,
                expected_proposers=expected_proposers,
            )

            # Re-rank goals using business context
            if self.config.use_business_context:
                goals = self._rerank_with_business_context(goals)

            # Self-explanation: annotate goals with rationale from debate
            self._explain_planning_decision(result, goals)

            logger.info(
                "meta_planner_completed goal_count=%s objectives=%s",
                len(goals),
                [g.description[:50] for g in goals],
            )

            return self._enforce_objective_fidelity(objective, available_tracks, goals)

        except ImportError as e:
            logger.warning("Debate infrastructure not available: %s", e)
            goals = self._heuristic_prioritize(objective, available_tracks)
            return self._enforce_objective_fidelity(objective, available_tracks, goals)
        except (RuntimeError, OSError, ValueError) as e:
            logger.exception("Meta-planning failed: %s", e)
            goals = self._heuristic_prioritize(objective, available_tracks)
            return self._enforce_objective_fidelity(objective, available_tracks, goals)

    @staticmethod
    def _significant_tokens(text: str) -> set[str]:
        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "this",
            "that",
            "into",
            "through",
            "make",
            "more",
            "less",
            "very",
            "goal",
            "task",
            "plan",
            "improve",
        }
        words = set(re.findall(r"[a-z][a-z0-9_/-]+", text.lower()))
        return {word for word in words if word not in stop_words and len(word) > 2}

    def _goal_fidelity_score(self, objective: str, description: str) -> float:
        objective_tokens = self._significant_tokens(objective)
        desc_tokens = self._significant_tokens(description)
        if not objective_tokens:
            return 1.0
        if not desc_tokens:
            return 0.0
        overlap = len(objective_tokens & desc_tokens)
        union = len(objective_tokens | desc_tokens)
        return overlap / union if union else 0.0

    def _semantic_goal_key(self, goal: PrioritizedGoal) -> str:
        tokens = sorted(self._significant_tokens(goal.description))
        if tokens:
            return f"{goal.track.value}:{' '.join(tokens[:10])}"
        collapsed = re.sub(r"\s+", " ", goal.description.lower()).strip()
        return f"{goal.track.value}:{collapsed[:120]}"

    def _dedupe_goals_by_semantic_key(
        self,
        goals: list[PrioritizedGoal],
    ) -> list[PrioritizedGoal]:
        seen: set[str] = set()
        unique: list[PrioritizedGoal] = []
        for goal in goals:
            key = self._semantic_goal_key(goal)
            if key in seen:
                continue
            seen.add(key)
            unique.append(goal)
        return unique

    def _enforce_objective_fidelity(
        self,
        objective: str,
        available_tracks: list[Track],
        goals: list[PrioritizedGoal],
    ) -> list[PrioritizedGoal]:
        if not objective or not goals or not self.config.enforce_objective_fidelity:
            return goals[: self.config.max_goals]
        # A surviving substantive proposal must not be silently replaced by an
        # unrelated heuristic after the degradation-aware parser preserved it.
        if any(goal.metadata.get("decision_source") == "surviving_proposals" for goal in goals):
            return goals[: self.config.max_goals]

        threshold = max(0.0, min(1.0, float(self.config.objective_fidelity_threshold)))
        scored = [(self._goal_fidelity_score(objective, goal.description), goal) for goal in goals]
        top_score = max(score for score, _goal in scored)
        if top_score >= threshold:
            return goals[: self.config.max_goals]

        degradation_metadata = next(
            (dict(goal.metadata) for goal in goals if goal.metadata.get("degraded")),
            {},
        )

        constrained_objective = (
            "Maintain strict objective fidelity. "
            f"Objective: {objective}. "
            "Produce goals that directly implement this objective."
        )
        recovered = self._heuristic_prioritize(constrained_objective, available_tracks)
        recovered_scored = [
            (self._goal_fidelity_score(objective, goal.description), goal) for goal in recovered
        ]
        recovered_top = max((score for score, _goal in recovered_scored), default=0.0)
        if recovered and recovered_top > top_score:
            logger.info(
                "meta_planner_objective_fidelity_recovered from=%.2f to=%.2f",
                top_score,
                recovered_top,
            )
            recovered = recovered[: self.config.max_goals]
            for goal in recovered:
                goal.metadata = dict(degradation_metadata)
            return recovered

        best_track = self._infer_track(objective, available_tracks)
        fallback_goal = PrioritizedGoal(
            id="goal_0",
            track=best_track,
            description=f"[{best_track.value}] {objective}",
            rationale=(
                f"Objective-fidelity recovery: top score {top_score:.2f} below threshold "
                f"{threshold:.2f}"
            ),
            estimated_impact="high",
            priority=1,
            metadata=degradation_metadata,
        )
        logger.warning(
            "meta_planner_objective_fidelity_low score=%.2f threshold=%.2f objective=%s",
            top_score,
            threshold,
            objective[:80],
        )
        return [fallback_goal]

    async def propose_goals(
        self,
        available_tracks: list[Track] | None = None,
        min_confidence: float = 0.6,
    ) -> list[PrioritizedGoal]:
        """Autonomously propose improvement goals from telemetry and codebase signals.

        Bridges GoalProposer (telemetry-driven: test failures, slow cycles,
        coverage gaps, lint regressions, calibration drift, knowledge staleness)
        with MetaPlanner's scan mode (codebase-driven: git changes, TODOs,
        pipeline goals, feedback queue, strategic scanner).

        Unlike ``prioritize_work()``, this method requires no human-supplied
        objective — the system chooses its own goals from quality signals.

        Args:
            available_tracks: Tracks to consider. Defaults to all tracks.
            min_confidence: Minimum confidence for GoalProposer candidates.

        Returns:
            Merged, deduplicated, and ranked list of PrioritizedGoal.
        """
        available_tracks = available_tracks or list(Track)
        all_goals: list[PrioritizedGoal] = []

        # Source 1: GoalProposer — telemetry-driven signals
        if self._goal_proposer is not None:
            try:
                if getattr(self._goal_proposer, "_telemetry", None) is None:
                    from aragora.nomic.cycle_telemetry import CycleTelemetryCollector

                    self._goal_proposer._telemetry = CycleTelemetryCollector()
                candidates = self._goal_proposer.propose_goals(
                    max_goals=self.config.max_goals,
                    min_confidence=min_confidence,
                )
                for i, candidate in enumerate(candidates):
                    track = self._infer_track(candidate.goal_text, available_tracks)
                    impact = (
                        "high"
                        if candidate.estimated_impact >= 1.5
                        else "medium"
                        if candidate.estimated_impact >= 0.8
                        else "low"
                    )
                    all_goals.append(
                        PrioritizedGoal(
                            id=f"telemetry_{i}",
                            track=track,
                            description=candidate.goal_text,
                            rationale=(
                                f"Signal: {candidate.signal_source} "
                                f"(confidence={candidate.confidence:.2f}, "
                                f"score={candidate.score:.2f})"
                            ),
                            estimated_impact=impact,
                            priority=i + 1,
                            focus_areas=[candidate.signal_source],
                        )
                    )
                if candidates:
                    logger.info(
                        "propose_goals_telemetry count=%d top=%s",
                        len(candidates),
                        candidates[0].goal_text[:60] if candidates else "none",
                    )
            except (RuntimeError, ValueError, TypeError, AttributeError) as e:
                logger.debug("GoalProposer failed: %s", e)

        # Source 2: Scan mode — codebase-driven signals
        try:
            scan_goals = await self._scan_prioritize(None, available_tracks)
            for goal in scan_goals:
                goal.id = f"scan_{goal.id}" if not goal.id.startswith("scan_") else goal.id
            all_goals.extend(scan_goals)
            if scan_goals:
                logger.info(
                    "propose_goals_scan count=%d",
                    len(scan_goals),
                )
        except (RuntimeError, ValueError, OSError) as e:
            logger.debug("Scan prioritize failed: %s", e)

        # Source 3: Debate outcome patterns
        try:
            outcome_goals = await self.generate_goals_from_debate_outcomes()
            for goal in outcome_goals:
                goal.id = f"outcome_{goal.id}"
            all_goals.extend(outcome_goals)
            if outcome_goals:
                logger.info(
                    "propose_goals_outcomes count=%d",
                    len(outcome_goals),
                )
        except (RuntimeError, ValueError, OSError, TypeError) as e:
            logger.debug("Outcome-based goals failed: %s", e)

        if not all_goals:
            logger.info("propose_goals: no signals detected, using heuristic")
            return self._heuristic_prioritize(
                "self-directed codebase improvement", available_tracks
            )

        # Deduplicate by semantic key (track + normalized token signature)
        unique_goals = self._dedupe_goals_by_semantic_key(all_goals)

        # Re-rank by business context
        if self.config.use_business_context:
            unique_goals = self._rerank_with_business_context(unique_goals)

        # Assign sequential priorities
        for i, goal in enumerate(unique_goals):
            goal.priority = i + 1

        result = unique_goals[: self.config.max_goals]
        logger.info(
            "propose_goals_complete total_candidates=%d unique=%d selected=%d",
            len(all_goals),
            len(unique_goals),
            len(result),
        )
        return result

    def _enrich_context_with_metrics(self, context: PlanningContext) -> PlanningContext:
        """Enrich planning context with codebase metrics.

        Instantiates MetricsCollector, runs a synchronous collection of test/lint/size
        metrics, and injects the snapshot into PlanningContext.metric_snapshot so the
        debate topic can include hard numbers.

        Args:
            context: Existing planning context

        Returns:
            Enriched PlanningContext with metric_snapshot populated
        """
        try:
            from aragora.nomic.metrics_collector import MetricsCollector, MetricsCollectorConfig

            config = MetricsCollectorConfig(
                test_args=["-x", "-q", "--tb=no", "--timeout=60"],
                test_timeout=120,
            )
            collector = MetricsCollector(config)

            # Synchronous collection of size + lint (skip tests for speed in planning)
            from aragora.nomic.metrics_collector import MetricSnapshot
            import time

            snapshot = MetricSnapshot(timestamp=time.time())
            try:
                collector._collect_size_metrics(snapshot, None)
            except (OSError, ValueError) as e:
                logger.debug("metrics_size_collection_failed: %s", e)
            try:
                collector._collect_lint_metrics(snapshot, None)
            except (OSError, ValueError, Exception) as e:  # noqa: BLE001
                logger.debug("metrics_lint_collection_failed: %s", e)

            context.metric_snapshot = snapshot.to_dict()

            # Inject notable issues into recent_issues for debate visibility
            if snapshot.lint_errors > 0:
                context.recent_issues.append(
                    f"[metrics] {snapshot.lint_errors} lint errors detected"
                )
            if snapshot.tests_failed > 0:
                context.recent_issues.append(
                    f"[metrics] {snapshot.tests_failed} test failures detected"
                )

            logger.info(
                "metrics_enrichment_complete files=%d lines=%d lint_errors=%d",
                snapshot.files_count,
                snapshot.total_lines,
                snapshot.lint_errors,
            )

        except ImportError:
            logger.debug("MetricsCollector not available, skipping metrics enrichment")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to enrich context with metrics: %s", e)

        return context

    async def _enrich_context_with_history(
        self,
        objective: str,
        tracks: list[Track],
        context: PlanningContext,
    ) -> PlanningContext:
        """Enrich planning context with learnings from past cycles.

        Queries the Knowledge Mound for similar past cycles and extracts
        relevant learnings to inform the current planning session.

        Args:
            objective: Current planning objective
            tracks: Available tracks
            context: Existing planning context

        Returns:
            Enriched PlanningContext with historical learnings
        """
        try:
            from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                get_nomic_cycle_adapter,
            )

            adapter = get_nomic_cycle_adapter()
            track_names = [t.value for t in tracks]

            similar_cycles = await adapter.find_similar_cycles(
                objective=objective,
                tracks=track_names,
                limit=self.config.max_similar_cycles,
                min_similarity=self.config.min_cycle_similarity,
            )

            if similar_cycles:
                logger.info(
                    "cross_cycle_learning found=%s cycles for objective=%s",
                    len(similar_cycles),
                    objective[:50],
                )

            for cycle in similar_cycles:
                # Add what worked
                for success in cycle.what_worked:
                    context.past_successes_to_build_on.append(f"[{cycle.objective[:30]}] {success}")
                    context.historical_learnings.append(
                        HistoricalLearning(
                            cycle_id=cycle.cycle_id,
                            objective=cycle.objective,
                            was_success=True,
                            lesson=success,
                            relevance=cycle.similarity,
                        )
                    )

                # Add what failed (important to avoid!)
                for failure in cycle.what_failed:
                    context.past_failures_to_avoid.append(f"[{cycle.objective[:30]}] {failure}")
                    context.historical_learnings.append(
                        HistoricalLearning(
                            cycle_id=cycle.cycle_id,
                            objective=cycle.objective,
                            was_success=False,
                            lesson=failure,
                            relevance=cycle.similarity,
                        )
                    )

            # Query high-ROI goal types for smarter prioritization
            try:
                high_roi = await adapter.find_high_roi_goal_types(limit=5)
                for roi_entry in high_roi:
                    if roi_entry.get("avg_improvement_score", 0) > 0.3:
                        context.past_successes_to_build_on.append(
                            f"[high_roi] Pattern '{roi_entry['pattern']}' "
                            f"avg_improvement={roi_entry['avg_improvement_score']:.2f} "
                            f"({roi_entry['cycle_count']} cycles)"
                        )
                if high_roi:
                    logger.info("high_roi_patterns loaded=%d for planning", len(high_roi))
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.debug("High-ROI query failed: %s", e)

            # Query recurring failures to avoid
            try:
                recurring = await adapter.find_recurring_failures(min_occurrences=2, limit=5)
                for rec_failure in recurring:
                    tracks_str = ", ".join(rec_failure.get("affected_tracks", [])[:3])
                    context.past_failures_to_avoid.append(
                        f"[recurring_failure] '{rec_failure['pattern']}' "
                        f"({rec_failure['occurrences']}x"
                        f"{', tracks: ' + tracks_str if tracks_str else ''})"
                    )
                if recurring:
                    logger.info("recurring_failures loaded=%d for planning", len(recurring))
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.debug("Recurring failures query failed: %s", e)

        except ImportError:
            logger.debug("Nomic cycle adapter not available, skipping history enrichment")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to enrich context with history: %s", e)

        # Also query PlanStore for recent pipeline outcomes
        try:
            from aragora.pipeline.plan_store import get_plan_store

            store = get_plan_store()
            outcomes = store.get_recent_outcomes(limit=5) if store else []

            for outcome in outcomes or []:
                status = outcome.get("status", "unknown")
                task = outcome.get("task", "unknown task")
                exec_error = outcome.get("execution_error")
                affected_files = [
                    str(item).strip()
                    for item in outcome.get("affected_files", [])
                    if str(item).strip()
                ]
                expected_tests = [
                    str(item).strip()
                    for item in outcome.get("expected_tests", [])
                    if str(item).strip()
                ]
                scope_suffix = _scope_summary(affected_files, expected_tests)

                if affected_files:
                    change_entry = f"[pipeline:{status}] {', '.join(affected_files[:4])}"
                    if change_entry not in context.recent_changes:
                        context.recent_changes.append(change_entry)

                if status in ("failed", "rejected") or exec_error:
                    for test_cmd in expected_tests[:3]:
                        failure_hint = f"[pipeline:{status}] {test_cmd}"
                        if failure_hint not in context.test_failures:
                            context.test_failures.append(failure_hint)

                if status in ("completed",) and not exec_error:
                    context.past_successes_to_build_on.append(
                        f"[pipeline] {task[:60]}{scope_suffix}"
                    )
                elif status in ("failed", "rejected") or exec_error:
                    error_msg = ""
                    if exec_error and isinstance(exec_error, dict):
                        error_msg = f": {exec_error.get('message', '')[:80]}"
                    context.past_failures_to_avoid.append(
                        f"[pipeline:{status}] {task[:60]}{error_msg}{scope_suffix}"
                    )

            if outcomes:
                logger.info("pipeline_feedback loaded=%s outcomes for planning", len(outcomes))
        except ImportError:
            logger.debug("PlanStore not available, skipping pipeline feedback")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to load pipeline outcomes: %s", e)

        # Outcome tracker feedback: inject regression data from past cycles
        try:
            from aragora.nomic.outcome_tracker import NomicOutcomeTracker

            regressions = NomicOutcomeTracker.get_regression_history(limit=5)
            for reg in regressions:
                regressed = ", ".join(reg["regressed_metrics"])
                context.past_failures_to_avoid.append(
                    f"[outcome_regression] Cycle {reg['cycle_id'][:8]} regressed: {regressed} "
                    f"(recommendation: {reg['recommendation']})"
                )
            if regressions:
                logger.info("outcome_feedback loaded=%d regressions for planning", len(regressions))
        except ImportError:
            logger.debug("OutcomeTracker not available, skipping regression feedback")
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning("Failed to load outcome regressions: %s", e)

        # --- Calibration data enrichment ---
        try:
            from aragora.ranking.elo import get_elo_store
            from aragora.agents.calibration import CalibrationTracker

            elo = get_elo_store()
            calibration = CalibrationTracker()

            # Get agents ranked by calibration quality
            cal_leaders = calibration.get_leaderboard(metric="brier", limit=5)
            if cal_leaders:
                well_calibrated = [name for name, score in cal_leaders if score < 0.25]
                if well_calibrated:
                    context.past_successes_to_build_on.append(
                        f"[calibration] Well-calibrated agents: "
                        f"{', '.join(well_calibrated[:3])} (Brier < 0.25)"
                    )

            # Get domain-specific performance for relevant tracks
            all_ratings = elo.get_all_ratings()
            underperformers = []
            for rating in all_ratings[:10]:  # Top 10 agents by ELO
                if rating.calibration_total >= 5:
                    brier = rating.calibration_brier_score
                    if brier > 0.35:
                        underperformers.append(f"{rating.agent_name} (Brier={brier:.2f})")

            if underperformers:
                context.past_failures_to_avoid.append(
                    f"[calibration] Overconfident agents needing "
                    f"improvement: {', '.join(underperformers[:3])}"
                )

            logger.info(
                "calibration_enrichment leaders=%d underperformers=%d",
                len(cal_leaders) if cal_leaders else 0,
                len(underperformers),
            )
        except ImportError:
            logger.debug("Calibration subsystems not available")
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to enrich with calibration data: %s", e)

        # Strategic memory: query past strategic assessments for this objective
        try:
            from aragora.nomic.strategic_memory import StrategicMemoryStore

            sm_store = StrategicMemoryStore()
            past_assessments = sm_store.get_for_objective(objective, limit=3)
            if past_assessments:
                for assessment in past_assessments:
                    for finding in assessment.findings[:3]:
                        context.recent_issues.append(
                            f"[strategic:{finding.category}] {finding.description[:100]}"
                        )
                logger.info(
                    "strategic_memory_enrichment assessments=%d for objective=%s",
                    len(past_assessments),
                    objective[:50],
                )

            # Boost recurring findings
            recurring_findings = sm_store.get_recurring_findings(min_occurrences=2)
            for finding in recurring_findings[:5]:
                context.recent_issues.append(
                    f"[recurring:{finding.category}] {finding.description[:100]}"
                )
            if recurring_findings:
                logger.info("strategic_memory_recurring count=%d", len(recurring_findings))
        except ImportError:
            logger.debug("Strategic memory not available")
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("Strategic memory query failed: %s", exc)

        return context

    async def approve_changes(
        self,
        changes: str,
        gauntlet_baseline: float | None = None,
        elo_baseline: float | None = None,
    ) -> dict[str, Any]:
        """Approve or reject proposed changes based on quality gates.

        Runs two independent quality gates:
        1. Gauntlet quality gate: robustness_score must be >= 90% of baseline
        2. ELO regression gate: average agent ELO must be >= 95% of baseline

        Either gate failing causes rejection. Both must pass for approval.
        If a gate is unavailable or errors, it defaults to pass (fail-open).

        Args:
            changes: The proposed code/spec changes to evaluate.
            gauntlet_baseline: Expected robustness score baseline (0–1). If None,
                uses an absolute minimum threshold of 0.5.
            elo_baseline: Expected average ELO baseline. If None, ELO gate is
                skipped entirely.

        Returns:
            Dict with keys:
                - approved (bool): True if all gates pass
                - reason (str): Human-readable explanation when rejected
                - gauntlet_score (float | None): Score from gauntlet run
                - gauntlet_skipped (bool): True if gauntlet was unavailable
                - elo_avg (float | None): Average ELO from current ratings
                - elo_skipped (bool): True if ELO check was skipped
        """
        result: dict[str, Any] = {
            "approved": True,
            "reason": "",
            "gauntlet_score": None,
            "gauntlet_skipped": False,
            "elo_avg": None,
            "elo_skipped": False,
        }
        rejection_reasons: list[str] = []

        # --- Gate 1: Gauntlet quality check ---
        # Allow test injection via module-level name
        import aragora.nomic.meta_planner as _self_mod

        _runner_cls = getattr(_self_mod, "_GauntletRunner", None)
        _flag = getattr(_self_mod, "_GAUNTLET_AVAILABLE", None)

        # Determine availability: either injected flag, injected class, or real import
        if _flag is False:
            _gauntlet_available = False
        elif _runner_cls is not None:
            _gauntlet_available = True
        else:
            try:
                import importlib.util

                _gauntlet_available = (
                    importlib.util.find_spec("aragora.gauntlet.runner") is not None
                )
            except (ImportError, ModuleNotFoundError, ValueError):
                _gauntlet_available = False

        if not _gauntlet_available:
            result["gauntlet_skipped"] = True
        else:
            try:
                if _runner_cls is None:
                    from aragora.gauntlet.runner import GauntletRunner as _runner_cls  # type: ignore[no-redef]
                from aragora.gauntlet.config import GauntletConfig

                runner = _runner_cls(  # type: ignore[misc]  # narrowed by import above
                    config=GauntletConfig(
                        attack_rounds=1,
                        probes_per_category=1,
                        run_scenario_matrix=False,
                        max_agents=2,
                    )
                )

                gauntlet_result = await runner.run(input_content=changes)
                score = getattr(gauntlet_result, "robustness_score", None)
                result["gauntlet_score"] = score

                if score is not None:
                    effective_baseline = gauntlet_baseline if gauntlet_baseline is not None else 0.5
                    threshold = effective_baseline * 0.90
                    if score < threshold:
                        rejection_reasons.append(
                            f"gauntlet score {score:.3f} < 90% of baseline {effective_baseline:.3f} "
                            f"(threshold {threshold:.3f})"
                        )
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.warning("Gauntlet quality gate error (skipping): %s", exc)
                result["gauntlet_skipped"] = True

        # --- Gate 2: ELO regression check ---
        if elo_baseline is not None:
            try:
                _elo_store_fn = getattr(_self_mod, "_get_elo_store", None)
                if _elo_store_fn is None:
                    from aragora.ranking.elo import get_elo_store as _elo_store_fn  # type: ignore[no-redef]

                elo_store = _elo_store_fn()  # type: ignore[misc]  # narrowed by import above
                all_ratings = elo_store.get_all_ratings()

                if all_ratings:
                    avg_elo = sum(r.elo for r in all_ratings) / len(all_ratings)
                    result["elo_avg"] = avg_elo
                    threshold = elo_baseline * 0.95
                    if avg_elo < threshold:
                        rejection_reasons.append(
                            f"average ELO {avg_elo:.1f} < 95% of baseline {elo_baseline:.1f} "
                            f"(threshold {threshold:.1f})"
                        )
                else:
                    result["elo_skipped"] = True
            except (ImportError, RuntimeError, ValueError, OSError) as exc:
                logger.warning("ELO regression gate error (skipping): %s", exc)
                result["elo_skipped"] = True

        if rejection_reasons:
            result["approved"] = False
            result["reason"] = "; ".join(rejection_reasons)

        return result

    def _generate_receipt(self, result: Any) -> None:
        """Generate a DecisionReceipt from a debate result and persist to KM.

        Creates an audit-ready receipt from the self-improvement debate and
        ingests it into the Knowledge Mound via the ReceiptAdapter so future
        cycles can query past self-improvement decisions.

        Args:
            result: DebateResult from Arena.run()
        """
        if not self.config.enable_receipts:
            return

        try:
            from aragora.gauntlet.receipt_models import DecisionReceipt

            receipt = DecisionReceipt.from_debate_result(result)
            failures = proposal_failure_provenance(result)
            if failures:
                details = "; ".join(
                    f"{failure['agent']} {failure['error_type']}: {failure['message']}"
                    for failure in failures
                )
                receipt.verdict_reasoning = (
                    f"{receipt.verdict_reasoning}. Degraded proposal roster: {details}"
                ).strip(". ")
            self.last_receipt = receipt
            logger.info(
                "meta_planner_receipt_generated receipt_id=%s verdict=%s",
                receipt.receipt_id,
                receipt.verdict,
            )

            # Persist receipt to Knowledge Mound via ReceiptAdapter
            self._ingest_receipt_to_km(receipt)

        except ImportError:
            logger.debug("DecisionReceipt not available, skipping receipt generation")
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Failed to generate receipt from debate result: %s", e)

    def _ingest_receipt_to_km(self, receipt: Any) -> None:
        """Ingest a DecisionReceipt into the Knowledge Mound.

        Uses the ReceiptAdapter to store the receipt so future Nomic cycles
        can query past self-improvement decisions for context.

        Args:
            receipt: DecisionReceipt to ingest
        """
        try:
            from aragora.knowledge.mound.adapters.receipt_adapter import ReceiptAdapter

            adapter = ReceiptAdapter()
            # Fire-and-forget: schedule async ingestion without blocking
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    adapter.ingest_receipt(
                        receipt,
                        tags=["nomic_loop", "self_improvement", "meta_planner"],
                    )
                )
                logger.info(
                    "meta_planner_receipt_km_ingestion_scheduled receipt_id=%s",
                    receipt.receipt_id,
                )
            except RuntimeError:
                logger.debug("No event loop, skipping async receipt KM ingestion")

        except ImportError:
            logger.debug("ReceiptAdapter not available, skipping KM ingestion")
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Failed to ingest receipt to KM: %s", e)

    def _create_agent(self, agent_type: str) -> Any:
        """Create an agent using get_secret pattern for API key resolution.

        Falls back through multiple import paths to maximize compatibility.
        """
        try:
            from aragora.agents import create_agent
            from aragora.agents.base import AgentType

            return create_agent(cast(AgentType, agent_type))
        except ImportError:
            pass

        # Fallback: try direct agent construction
        try:
            from aragora.config.secrets import get_secret

            # Map agent type to required API key
            key_map = {
                "claude": "ANTHROPIC_API_KEY",
                "anthropic-api": "ANTHROPIC_API_KEY",
                "openai-api": "OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "deepseek": "OPENROUTER_API_KEY",
                "grok": "XAI_API_KEY",
            }
            required_key = key_map.get(agent_type)
            if required_key and not get_secret(required_key):
                logger.debug("No API key for %s, skipping", agent_type)
                return None
        except ImportError:
            pass

        logger.debug("Could not create agent %s via any path", agent_type)
        return None

    def _maybe_add_fusion(self, agent_types: list[str]) -> list[str]:
        """Optionally append the OpenRouter Fusion agent to a planning debate.

        Fusion (a multi-model council+judge) is ~4-5x cost, so it joins planning
        only when explicitly opted in AND there is budget for it:

        - ``MetaPlannerConfig.enable_fusion`` OR the global ``enable_fusion`` flag, and
        - ``fusion_cost_budget_per_debate`` > 0 (set the budget to 0 to hard-disable
          even when the flag is on), and
        - the ``fusion`` agent type is actually registered.

        Fails open: any error leaves ``agent_types`` untouched so planning never
        breaks because of the (optional) Fusion path.
        """
        try:
            if "fusion" in agent_types:
                return agent_types
            if not (self.config.enable_fusion or is_enabled("enable_fusion")):
                return agent_types
            # Budget gate: a non-positive per-debate budget disables Fusion.
            budget = float(get_flag("fusion_cost_budget_per_debate", 50.0))
            if budget <= 0:
                logger.info("Fusion enabled but per-debate budget <= 0; skipping fusion")
                return agent_types
            # Only add it if it can actually be constructed.
            from aragora.agents.registry import AgentRegistry

            if not AgentRegistry.is_registered("fusion"):
                logger.warning("enable_fusion set but 'fusion' agent not registered; skipping")
                return agent_types
            logger.info("Adding OpenRouter Fusion to planning debate (budget=$%.2f/debate)", budget)
            return [*agent_types, "fusion"]
        except Exception as e:  # noqa: BLE001 - fail-open: planning must never break on the optional path
            logger.warning("Fusion participation check failed, proceeding without it: %s", e)
            return agent_types

    def _select_agents_by_introspection(self, domain: str) -> list[str]:
        """Select agents using introspection data for better planning quality.

        Ranks available agents by their reputation_score + calibration_score
        for the given domain, preferring agents with proven track records.

        Args:
            domain: The planning domain or objective keyword to match expertise.

        Returns:
            List of agent names ranked by introspection scores, or the static
            config list if introspection is unavailable.
        """
        try:
            from aragora.introspection.api import get_agent_introspection

            scored_agents: list[tuple[str, float]] = []
            for agent_name in self.config.agents:
                snapshot = get_agent_introspection(agent_name)
                # Combined score: reputation + calibration, with domain expertise bonus
                score = snapshot.reputation_score + snapshot.calibration_score
                if domain and snapshot.top_expertise:
                    domain_lower = domain.lower()
                    if any(
                        domain_lower in exp.lower() or exp.lower() in domain_lower
                        for exp in snapshot.top_expertise
                    ):
                        score += 0.2  # Domain expertise bonus
                # SelectionFeedbackLoop domain adjustment
                if self._feedback_loop:
                    try:
                        fb_adj = self._feedback_loop.get_domain_adjustment(agent_name, domain or "")
                        score += fb_adj * 0.3
                    except (AttributeError, TypeError):
                        pass
                scored_agents.append((agent_name, score))

            if not scored_agents:
                return self.config.agents

            # Sort by score descending
            scored_agents.sort(key=lambda x: x[1], reverse=True)
            selected = [name for name, _ in scored_agents]

            logger.info(
                "introspection_agent_selection domain=%s selected=%s",
                domain[:50] if domain else "general",
                selected,
            )
            return selected

        except ImportError:
            logger.debug("Introspection API not available, using static agent list")
            return self.config.agents
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Introspection selection failed: %s", e)
            return self.config.agents

    def _explain_planning_decision(
        self,
        result: Any,
        goals: list[PrioritizedGoal],
    ) -> None:
        """Generate a self-explanation for the planning decision.

        Builds an explanation from the debate result and attaches the summary
        as rationale to each goal. Persists the explanation to KM.

        Args:
            result: DebateResult from Arena.run()
            goals: Parsed PrioritizedGoal list to annotate with rationale
        """
        if not self.config.explain_decisions:
            return

        try:
            from aragora.explainability.builder import ExplanationBuilder

            builder = ExplanationBuilder()

            # build() is async, but we schedule it fire-and-forget
            import asyncio

            async def _explain() -> None:
                try:
                    decision = await builder.build(result)
                    summary = builder.generate_summary(decision)
                    for goal in goals:
                        if not goal.rationale:
                            goal.rationale = summary[:500]

                    # Persist explanation to KM
                    self._persist_explanation_to_km(summary, goals)
                except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                    logger.debug("Self-explanation build failed: %s", exc)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_explain())
            except RuntimeError:
                logger.debug("No event loop, skipping async self-explanation")

        except ImportError:
            logger.debug("ExplanationBuilder not available, skipping self-explanation")
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Self-explanation unavailable: %s", e)

    def _persist_explanation_to_km(
        self,
        summary: str,
        goals: list[PrioritizedGoal],
    ) -> None:
        """Persist a planning explanation to the Knowledge Mound."""
        try:
            from aragora.knowledge.mound.adapters.receipt_adapter import ReceiptAdapter

            adapter = ReceiptAdapter()
            import asyncio

            async def _ingest() -> None:
                try:
                    item = {
                        "content": summary[:2000],
                        "source": "meta_planner_explanation",
                        "tags": ["self_explanation", "meta_planner"]
                        + [g.track.value for g in goals[:5]],
                    }
                    adapter.ingest(item)
                except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                    logger.debug("KM explanation ingestion failed: %s", exc)

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_ingest())
            except RuntimeError:
                pass

        except ImportError:
            logger.debug("ReceiptAdapter not available for explanation persistence")
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Explanation KM persistence failed: %s", e)

    def _rerank_with_business_context(self, goals: list[PrioritizedGoal]) -> list[PrioritizedGoal]:
        """Re-rank goals using business impact scoring."""
        try:
            from aragora.nomic.business_context import BusinessContext

            ctx = BusinessContext()
            scored_goals = []
            for goal in goals:
                score = ctx.score_goal(
                    goal=goal.description,
                    file_paths=goal.file_hints,
                    metadata={"focus_areas": goal.focus_areas},
                )
                scored_goals.append((goal, score.total))

            # Sort by business score (descending), re-assign priorities
            scored_goals.sort(key=lambda x: x[1], reverse=True)
            for i, (goal, _score) in enumerate(scored_goals):
                goal.priority = i + 1

            reranked = [g for g, _ in scored_goals]
            logger.info(
                "meta_planner_business_rerank reranked=%s",
                [(g.description[:40], g.priority) for g in reranked],
            )
            return reranked
        except ImportError:
            logger.debug("BusinessContext not available, skipping re-ranking")
            return goals
        except (RuntimeError, ValueError) as e:
            logger.warning("Business context re-ranking failed: %s", e)
            return goals

    def _inject_learning_bus_findings(self, context: PlanningContext) -> None:
        """Inject recent findings from the cross-agent learning bus."""
        try:
            from aragora.nomic.learning_bus import LearningBus

            bus = LearningBus.get_instance()
            findings = bus.get_findings()
            if not findings:
                return

            for finding in findings:
                if finding.severity == "critical":
                    if finding.description not in context.recent_issues:
                        context.recent_issues.append(
                            f"[learning_bus:{finding.topic}] {finding.description}"
                        )
                elif finding.topic == "test_failure":
                    if finding.description not in context.test_failures:
                        context.test_failures.append(finding.description)

            logger.info(
                "meta_planner_injected_learning_bus findings=%d critical=%d",
                len(findings),
                sum(1 for f in findings if f.severity == "critical"),
            )
        except ImportError:
            pass

    def _build_debate_topic(
        self,
        objective: str,
        tracks: list[Track],
        constraints: list[str],
        context: PlanningContext,
    ) -> str:
        """Build the debate topic for meta-planning."""
        return build_debate_topic(objective, tracks, constraints, context)

    def _parse_goals_from_debate(
        self,
        debate_result: Any,
        available_tracks: list[Track],
        objective: str,
        expected_proposers: list[str] | None = None,
    ) -> list[PrioritizedGoal]:
        """Parse prioritized goals from debate consensus."""
        return parse_goals_from_debate(
            debate_result,
            available_tracks,
            objective,
            self.config.max_goals,
            self._heuristic_prioritize,
            expected_proposers,
        )

    def _build_goal(
        self,
        goal_dict: dict[str, Any],
        priority: int,
        available_tracks: list[Track],
    ) -> PrioritizedGoal:
        """Build a PrioritizedGoal from parsed data."""
        return build_goal(goal_dict, priority, available_tracks)

    def _infer_track(self, description: str, available_tracks: list[Track]) -> Track:
        """Infer track from goal description."""
        return infer_track(description, available_tracks)

    async def _scan_prioritize(
        self,
        objective: str | None,
        available_tracks: list[Track],
        enrich_goals: bool = False,
    ) -> list[PrioritizedGoal]:
        """Prioritize from codebase signals without any LLM calls.

        Gathers eight signal sources:
        1. ``git log`` — recently changed files mapped to tracks
        2. ``CodebaseIndexer`` — untested modules
        3. ``OutcomeTracker`` — past regression patterns
        4. ``.pytest_cache`` — last-run test failures
        5. ``ruff`` — lint violations
        6. ``grep`` — TODO/FIXME/HACK comments
        7. ``FeedbackStore`` — user NPS score (low NPS boosts user-facing tracks)
        8. ``ImprovementQueue`` — feedback goals from prior cycles

        Each signal contributes a candidate goal. Goals are ranked by signal
        count (more signals = higher priority).

        When *objective* is None (self-directing mode), the scan produces
        goals purely from codebase signals without any human-supplied context.

        Args:
            objective: High-level objective (used to seed descriptions).
                       None for fully self-directing mode.
            available_tracks: Tracks that can receive work.

        Returns:
            List of PrioritizedGoal sorted by priority.
        """
        import subprocess

        # Default objective label for self-directing mode
        effective_objective = objective or "self-directed codebase improvement"

        track_signals: dict[str, list[str]] = {t.value: [] for t in available_tracks}

        # Signal 1: Recent git changes → map files to tracks
        try:
            git_result = subprocess.run(
                ["git", "log", "--oneline", "--name-only", "-20"],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.config.repo_path,
            )
            if git_result.returncode == 0:
                for line in git_result.stdout.splitlines():
                    line = line.strip()
                    if not line or line[0].isalnum() and " " in line:
                        continue  # Skip commit messages
                    track = self._file_to_track(line, available_tracks)
                    if track and track.value in track_signals:
                        track_signals[track.value].append(f"recent_change: {line}")
        except (subprocess.TimeoutExpired, OSError):
            pass

        # Signal 2: Untested modules from CodebaseIndexer
        try:
            import os

            if os.environ.get("PYTEST_CURRENT_TEST"):
                raise RuntimeError("skip in tests")

            from aragora.nomic.codebase_indexer import CodebaseIndexer

            indexer = CodebaseIndexer(repo_path=self.config.repo_path, max_modules=50)
            await indexer.index()
            for module in indexer._modules:
                test_paths = indexer._test_map.get(str(module.path), [])
                if not test_paths:
                    track = self._file_to_track(str(module.path), available_tracks)
                    if track and track.value in track_signals:
                        track_signals[track.value].append(f"untested: {module.path}")
        except (ImportError, RuntimeError, ValueError, OSError):
            pass

        # Signal 3: Past regression patterns
        try:
            from aragora.nomic.outcome_tracker import NomicOutcomeTracker

            regressions = NomicOutcomeTracker.get_regression_history(limit=10)
            for reg in regressions:
                for metric in reg.get("regressed_metrics", []):
                    # Map regression metrics to tracks
                    if "test" in metric.lower() or "coverage" in metric.lower():
                        if Track.QA.value in track_signals:
                            track_signals[Track.QA.value].append(f"regression: {metric}")
                    elif "token" in metric.lower():
                        if Track.CORE.value in track_signals:
                            track_signals[Track.CORE.value].append(f"regression: {metric}")
        except (ImportError, RuntimeError, ValueError, OSError):
            pass

        # Signal 4: pytest last-run failures
        try:
            import json as _json
            from pathlib import Path as _P

            lastfailed_path = _P(self.config.repo_path) / ".pytest_cache/v/cache/lastfailed"
            if lastfailed_path.exists():
                failed = _json.loads(lastfailed_path.read_text())
                for node_id in list(failed.keys())[:20]:
                    # Extract file path from node ID (e.g. "tests/foo.py::TestBar::test_baz")
                    test_file = node_id.split("::")[0] if "::" in node_id else node_id
                    track = self._file_to_track(test_file, available_tracks)
                    if track and track.value in track_signals:
                        track_signals[track.value].append(f"test_failure: {node_id}")
        except (OSError, ValueError, _json.JSONDecodeError):
            pass

        # Signal 5: ruff lint violations
        try:
            ruff_result = subprocess.run(
                ["ruff", "check", "--quiet", "--output-format=concise", "."],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                timeout=15,
                cwd=self.config.repo_path,
            )
            if ruff_result.stdout:
                for i, line in enumerate(ruff_result.stdout.splitlines()):
                    if i >= 20:
                        break
                    # Format: "path/to/file.py:42:1 E501 ..."
                    parts = line.split(":", 1)
                    if parts:
                        track = self._file_to_track(parts[0], available_tracks)
                        if track and track.value in track_signals:
                            track_signals[track.value].append(f"lint: {line.strip()[:100]}")
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            pass

        # Signal 6: TODO/FIXME/HACK comments
        try:
            todo_result = subprocess.run(
                ["grep", "-rn", r"TODO\|FIXME\|HACK", ".", "--include=*.py", "-l"],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.config.repo_path,
            )
            if todo_result.returncode == 0 and todo_result.stdout:
                for i, filepath in enumerate(todo_result.stdout.splitlines()):
                    if i >= 10:
                        break
                    filepath = filepath.strip()
                    if filepath:
                        track = self._file_to_track(filepath, available_tracks)
                        if track and track.value in track_signals:
                            track_signals[track.value].append(f"todo: {filepath}")
        except (subprocess.TimeoutExpired, OSError):
            pass

        # Signal 7: User feedback (NPS score from FeedbackStore)
        try:
            from aragora.server.handlers.feedback import FeedbackStore

            fb_store = FeedbackStore()
            nps = fb_store.get_nps_summary(days=30)
            if nps and nps.get("response_count", 0) > 0:
                nps_score = nps.get("nps_score", 0)
                if nps_score < 30:  # Below "good" threshold
                    if Track.SME.value in track_signals:
                        track_signals[Track.SME.value].append(
                            f"low_nps: score={nps_score} ({nps.get('response_count', 0)} responses)"
                        )
                    if Track.DEVELOPER.value in track_signals:
                        track_signals[Track.DEVELOPER.value].append(
                            f"low_nps: score={nps_score} (detractors={nps.get('detractor_pct', 0):.0f}%)"
                        )
        except (ImportError, RuntimeError, OSError, ValueError):
            pass

        # Signal 8: ImprovementQueue (feedback goals from prior cycles)
        try:
            from aragora.nomic.feedback_orchestrator import ImprovementQueue

            queue = ImprovementQueue.load()
            for queued_goal in queue.goals[:10]:
                track_name = getattr(queued_goal, "track", None)
                if isinstance(track_name, Track):
                    track_name = track_name.value
                elif track_name is not None and hasattr(track_name, "value"):
                    track_name = track_name.value
                else:
                    track_name = str(track_name) if track_name else None

                if track_name and track_name in track_signals:
                    source = getattr(queued_goal, "source", "feedback")
                    desc = getattr(queued_goal, "description", "")[:100]
                    track_signals[track_name].append(f"feedback_queue[{source}]: {desc}")
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError):
            pass

        # Signal 9: StrategicScanner deep codebase analysis
        strategic_assessment = None
        try:
            from aragora.nomic.strategic_scanner import StrategicScanner

            scanner = StrategicScanner()
            strategic_assessment = scanner.scan(objective=effective_objective)
            for finding in strategic_assessment.findings[:15]:
                track_name = finding.track
                if track_name in track_signals:
                    track_signals[track_name].append(
                        f"strategic[{finding.category}]: {finding.description[:100]}"
                    )
            logger.info(
                "scan_mode_strategic_findings count=%d",
                len(strategic_assessment.findings),
            )
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError) as exc:
            logger.debug("StrategicScanner skipped: %s", exc)

        # Persist strategic assessment for cross-session learning
        if strategic_assessment is not None:
            try:
                from aragora.nomic.strategic_memory import StrategicMemoryStore

                mem_store = StrategicMemoryStore()
                mem_store.save(strategic_assessment)
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                logger.debug("Strategic memory persistence skipped: %s", exc)

        # Signal 10: Pipeline Goal Canvas — approved but unexecuted goals
        try:
            from aragora.pipeline.plan_store import get_plan_store as _get_plan_store

            _pstore = _get_plan_store()
            # Query plan store for approved, unexecuted items
            pipeline_goals = _pstore.get_recent_outcomes(limit=10) if _pstore else []
            for pg in (pipeline_goals or [])[:10]:
                pg_data = pg if isinstance(pg, dict) else getattr(pg, "__dict__", {})
                track_name = pg_data.get("track", "core")
                if track_name in track_signals:
                    track_signals[track_name].append(
                        f"pipeline_goal: {(pg_data.get('label') or pg_data.get('description') or '')[:100]}"
                    )
            if pipeline_goals:
                logger.info(
                    "scan_mode_pipeline_goals count=%d",
                    len(pipeline_goals),
                )
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError, TypeError, AttributeError) as exc:
            logger.debug("Pipeline Goal Canvas scan skipped: %s", exc)

        # Signal 11: Feedback-generated goals from previous cycles (SQLite queue)
        try:
            from aragora.nomic.feedback_orchestrator import ImprovementQueue as FeedbackQueue

            queue = FeedbackQueue()
            queued_goals = queue.pop(limit=10)
            if queued_goals:
                for qg in queued_goals:
                    track = self._infer_track(qg.goal, available_tracks)
                    if track and track.value in track_signals:
                        track_signals[track.value].append(
                            f"feedback_goal[{qg.source}]: {qg.goal[:100]}"
                        )
                logger.info("scan_feedback_goals", extra={"count": len(queued_goals)})
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError, TypeError) as exc:
            logger.warning("feedback_queue_unavailable: %s", exc)

        # Signal 12: NextStepsRunner for TODOs, test failures, dep issues
        try:
            from aragora.compat.openclaw.next_steps_runner import NextStepsRunner

            runner = NextStepsRunner(repo_path=self.config.repo_path)
            scan_result = runner.scan() if hasattr(runner, "scan") else None
            if scan_result and hasattr(scan_result, "steps"):
                for step in scan_result.steps[:10]:
                    track = self._infer_track(getattr(step, "title", str(step)), available_tracks)
                    if track and track.value in track_signals:
                        priority = getattr(step, "priority", "medium")
                        category = getattr(step, "category", "misc")
                        track_signals[track.value].append(
                            f"next_step[{category}/{priority}]: "
                            f"{getattr(step, 'title', str(step))[:100]}"
                        )
                logger.info(
                    "scan_next_steps",
                    extra={"count": len(scan_result.steps)},
                )
        except ImportError:
            pass
        except (RuntimeError, ValueError, OSError, TypeError) as exc:
            logger.warning("next_steps_runner_unavailable: %s", exc)

        # Build goals from signals, ranked by signal count
        ranked = sorted(
            track_signals.items(),
            key=lambda kv: len(kv[1]),
            reverse=True,
        )

        goals: list[PrioritizedGoal] = []
        for priority, (track_name, signals) in enumerate(ranked, start=1):
            if not signals:
                continue

            try:
                track = Track(track_name)
            except ValueError:
                continue

            # Build a description from the top signals
            top_signals = signals[:3]
            signal_summary = "; ".join(top_signals)
            description = (
                f"[{effective_objective[:40]}] {track_name}: "
                f"{len(signals)} signals ({signal_summary})"
            )

            # Enrich with file excerpts for grounded execution
            excerpts = self._gather_file_excerpts(top_signals)
            if excerpts:
                excerpt_text = "\n".join(f"--- {p} ---\n{s[:500]}" for p, s in excerpts.items())
                description += f"\n\nRelevant source:\n{excerpt_text}"

            # Opt-in: single cheap LLM call to enrich signal-based description
            agent = getattr(self, "_agent", None)
            if enrich_goals and agent is not None:
                try:
                    enriched = await agent.generate(
                        f"Expand this into a concrete task description "
                        f"(1-2 sentences):\n{description[:500]}",
                        max_tokens=100,
                    )
                    if enriched and len(enriched.strip()) > 20:
                        description = enriched.strip()
                except (RuntimeError, ValueError, TypeError, AttributeError):
                    pass  # Keep original description on any failure

            goals.append(
                PrioritizedGoal(
                    id=f"scan_{priority - 1}",
                    track=track,
                    description=description[:2000],
                    rationale=f"Scan mode: {len(signals)} codebase signals detected",
                    estimated_impact="high" if len(signals) >= 5 else "medium",
                    priority=priority,
                )
            )

        if not goals:
            logger.info("scan_mode_no_signals falling back to heuristic")
            return self._heuristic_prioritize(objective or "", available_tracks)

        # Re-rank goals using business context
        if self.config.use_business_context:
            goals = self._rerank_with_business_context(goals)

        logger.info(
            "scan_mode_complete goals=%d signals=%d",
            len(goals),
            sum(len(s) for s in track_signals.values()),
        )
        return goals[: self.config.max_goals]

    def _file_to_track(self, filepath: str, available_tracks: list[Track]) -> Track | None:
        """Map a file path to a development track."""
        fp = filepath.lower()
        mapping = {
            Track.QA: ["tests/", "test_", "conftest"],
            Track.SME: ["dashboard", "frontend", "live/", "workspace"],
            Track.DEVELOPER: ["sdk", "client", "aragora_sdk/"],
            Track.SELF_HOSTED: ["deploy/", "docker", "k8s", "kubernetes"],
            Track.SECURITY: ["security/", "auth/", "rbac/", "encryption"],
            Track.CORE: ["debate/", "agents/", "memory/", "consensus"],
        }
        for track, patterns in mapping.items():
            if track in available_tracks and any(p in fp for p in patterns):
                return track
        return available_tracks[0] if available_tracks else None

    def _gather_file_excerpts(
        self,
        signals: list[str],
        max_files: int = 3,
        max_chars_per_file: int = 1500,
        max_total_chars: int = 5000,
    ) -> dict[str, str]:
        """Extract file paths from signal strings and read excerpts."""
        return gather_file_excerpts(
            signals,
            max_files,
            max_chars_per_file,
            max_total_chars,
            Path(self.config.repo_path),
        )

    def _gather_codebase_hints(
        self,
        objective: str,
        available_tracks: list[Track],
    ) -> dict[Track, list[str]]:
        """Gather codebase file hints using CodebaseIndexer (synchronous).

        Queries the codebase index for modules relevant to the objective
        and maps results to tracks via _file_to_track().

        Returns:
            Mapping of Track → list of relevant file paths.
        """
        try:
            from aragora.nomic.codebase_indexer import CodebaseIndexer

            indexer = CodebaseIndexer(repo_path=self.config.repo_path, max_modules=50)
            # Synchronous scan of already-indexed modules (lightweight)
            for source_dir in indexer.source_dirs:
                source_path = indexer.repo_path / source_dir
                if not source_path.is_dir():
                    continue
                for py_file in sorted(source_path.rglob("*.py")):
                    if len(indexer._modules) >= indexer.max_modules:
                        break
                    if py_file.name.startswith("_") and py_file.name != "__init__.py":
                        continue
                    try:
                        info = indexer._analyze_module(py_file)
                        if info:
                            indexer._modules.append(info)
                    except (SyntaxError, UnicodeDecodeError):
                        continue

            # Keyword-match modules against objective
            obj_lower = objective.lower()
            hints: dict[Track, list[str]] = {}
            for module in indexer._modules:
                searchable = module.to_km_entry()["searchable_text"].lower()
                if any(word in searchable for word in obj_lower.split()):
                    track = self._file_to_track(module.path, available_tracks)
                    if track:
                        hints.setdefault(track, []).append(module.path)

            return hints
        except (ImportError, RuntimeError, ValueError, OSError):
            return {}

    def _heuristic_prioritize(
        self,
        objective: str,
        available_tracks: list[Track],
    ) -> list[PrioritizedGoal]:
        """Fallback heuristic prioritization when debate is unavailable."""
        # Gather codebase hints before keyword matching
        file_hints = self._gather_codebase_hints(objective, available_tracks)

        goals = []
        obj_lower = objective.lower()

        # Generate goals based on objective keywords
        if "sme" in obj_lower or "small business" in obj_lower:
            if Track.SME in available_tracks:
                goals.append(
                    PrioritizedGoal(
                        id="goal_0",
                        track=Track.SME,
                        description="Improve dashboard usability for small business users",
                        rationale="Directly addresses SME utility objective",
                        estimated_impact="high",
                        priority=1,
                    )
                )

            if Track.QA in available_tracks:
                goals.append(
                    PrioritizedGoal(
                        id="goal_1",
                        track=Track.QA,
                        description="Add E2E tests for critical user flows",
                        rationale="Ensures reliability for SME users",
                        estimated_impact="medium",
                        priority=2,
                    )
                )

        # Security-focused objectives
        if any(kw in obj_lower for kw in ["security", "harden", "vuln", "audit"]):
            if Track.SECURITY in available_tracks:
                goals.append(
                    PrioritizedGoal(
                        id=f"goal_{len(goals)}",
                        track=Track.SECURITY,
                        description="Run security scanner and address critical findings",
                        rationale="Security hardening is critical for production",
                        estimated_impact="high",
                        priority=1,
                        focus_areas=["auth", "secrets", "input validation"],
                    )
                )

        # If no keyword-specific goals were generated, create a single goal
        # on the best-matching track (not all tracks — broadcasting the same
        # objective to every track produces duplicates, not decomposition).
        if not goals:
            best_track = infer_track(objective, available_tracks)
            goals.append(
                PrioritizedGoal(
                    id="goal_0",
                    track=best_track,
                    description=f"[{best_track.value}] {objective}",
                    rationale="Best-matching track for objective via keyword scoring",
                    estimated_impact="medium",
                    priority=1,
                )
            )

        # Enrich goals with codebase file hints
        for goal in goals:
            track_hints = file_hints.get(goal.track, [])
            if track_hints:
                goal.file_hints = track_hints[:10]  # Cap at 10 files per goal

        goals = self._dedupe_goals_by_semantic_key(goals)

        # Re-rank goals using business context
        if self.config.use_business_context:
            goals = self._rerank_with_business_context(goals)

        # Apply self-correction priority adjustments if available
        goals = self._apply_self_correction_adjustments(goals)

        return goals[: self.config.max_goals]

    def _apply_self_correction_adjustments(
        self,
        goals: list[PrioritizedGoal],
    ) -> list[PrioritizedGoal]:
        """Re-rank goals using self-correction engine priority adjustments.

        Queries the SelfCorrectionEngine for track-level adjustments and
        uses them to boost or demote goals. Higher adjustment = higher
        priority (lower number).
        """
        try:
            from aragora.nomic.self_correction import SelfCorrectionEngine

            engine = SelfCorrectionEngine()

            # Query past outcomes from Knowledge Mound
            past_outcomes = self._get_past_outcomes()
            if not past_outcomes:
                return goals

            report = engine.analyze_patterns(past_outcomes)
            adjustments = engine.compute_priority_adjustments(report)

            if not adjustments:
                return goals

            # Apply adjustments: multiply priority by inverse of adjustment
            # (higher adjustment = more important = lower priority number)
            for goal in goals:
                track_key = goal.track.value
                adj = adjustments.get(track_key, 1.0)
                # Adjusted priority: divide by adjustment factor so boosted
                # tracks get lower (higher priority) numbers
                goal.priority = max(1, round(goal.priority / adj))

            # Re-sort by adjusted priority
            goals.sort(key=lambda g: g.priority)

            # Re-assign sequential priority numbers
            for i, goal in enumerate(goals):
                goal.priority = i + 1

            logger.info(
                "self_correction_adjustments_applied tracks=%s",
                {g.track.value: adjustments.get(g.track.value, 1.0) for g in goals},
            )
        except (ImportError, RuntimeError, ValueError, TypeError) as e:
            logger.debug("Self-correction adjustments unavailable: %s", e)

        return goals

    def _get_past_outcomes(self) -> list[dict[str, Any]]:
        """Retrieve past orchestration outcomes for self-correction analysis."""
        try:
            from aragora.nomic.cycle_store import get_recent_cycles

            cycles = get_recent_cycles(n=20)
            outcomes: list[dict[str, Any]] = []
            for cycle in cycles:
                for contrib in getattr(cycle, "agent_contributions", []):
                    outcomes.append(
                        {
                            "track": getattr(contrib, "domain", "unknown"),
                            "success": getattr(contrib, "was_success", False),
                            "agent": getattr(contrib, "agent_name", "unknown"),
                            "timestamp": getattr(cycle, "timestamp", None),
                        }
                    )
            return outcomes
        except (ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug("Past outcomes unavailable: %s", e)
            return []

    def record_outcome(
        self,
        goal_outcomes: list[dict[str, Any]],
        objective: str = "",
    ) -> dict[str, dict[str, Any]]:
        """Record improvement outcomes and log success rates by track.

        Closes the feedback loop: after goals are executed, this method
        aggregates results by Track and logs structured success rates so
        the next planning cycle can learn from what worked.

        Args:
            goal_outcomes: List of dicts with keys:
                - track: str (Track value like "sme", "qa", "core")
                - success: bool
                - description: str (optional)
                - error: str (optional, for failures)
            objective: The original planning objective

        Returns:
            Dict mapping track name to {attempted, succeeded, failed, rate}
        """
        track_stats: dict[str, dict[str, Any]] = {}

        for outcome in goal_outcomes:
            track = outcome.get("track", "unknown")
            if track not in track_stats:
                track_stats[track] = {
                    "attempted": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "failures": [],
                }

            track_stats[track]["attempted"] += 1
            if outcome.get("success"):
                track_stats[track]["succeeded"] += 1
            else:
                track_stats[track]["failed"] += 1
                error = outcome.get("error", outcome.get("description", "unknown"))
                track_stats[track]["failures"].append(error)

        # Compute rates and log
        total_attempted = 0
        total_succeeded = 0
        for track, stats in track_stats.items():
            rate = stats["succeeded"] / stats["attempted"] if stats["attempted"] > 0 else 0.0
            stats["rate"] = rate
            total_attempted += stats["attempted"]
            total_succeeded += stats["succeeded"]

            logger.info(
                "meta_planner_track_outcome track=%s attempted=%d succeeded=%d failed=%d rate=%.2f",
                track,
                stats["attempted"],
                stats["succeeded"],
                stats["failed"],
                rate,
            )

        overall_rate = total_succeeded / total_attempted if total_attempted > 0 else 0.0
        logger.info(
            "meta_planner_outcome_summary objective=%s total_attempted=%d "
            "total_succeeded=%d overall_rate=%.2f tracks=%d",
            objective[:80] if objective else "unspecified",
            total_attempted,
            total_succeeded,
            overall_rate,
            len(track_stats),
        )

        # Persist to KM for cross-cycle learning
        self._persist_outcome_to_km(goal_outcomes, objective, track_stats)

        return track_stats

    def _persist_outcome_to_km(
        self,
        goal_outcomes: list[dict[str, Any]],
        objective: str,
        track_stats: dict[str, dict[str, Any]],
    ) -> None:
        """Persist outcomes to Knowledge Mound via NomicCycleAdapter."""
        try:
            from datetime import datetime, timezone

            from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                CycleStatus,
                GoalOutcome,
                NomicCycleOutcome,
                get_nomic_cycle_adapter,
            )

            total = sum(s["attempted"] for s in track_stats.values())
            succeeded = sum(s["succeeded"] for s in track_stats.values())
            failed = sum(s["failed"] for s in track_stats.values())

            if total == 0:
                return

            if failed == 0:
                status = CycleStatus.SUCCESS
            elif succeeded == 0:
                status = CycleStatus.FAILED
            else:
                status = CycleStatus.PARTIAL

            now = datetime.now(timezone.utc)
            outcomes = []
            for o in goal_outcomes:
                outcomes.append(
                    GoalOutcome(
                        goal_id=o.get("goal_id", ""),
                        description=o.get("description", ""),
                        track=o.get("track", "unknown"),
                        status=CycleStatus.SUCCESS if o.get("success") else CycleStatus.FAILED,
                        error=o.get("error"),
                        learnings=o.get("learnings", []),
                    )
                )

            cycle = NomicCycleOutcome(
                cycle_id=f"meta_{now.strftime('%Y%m%d_%H%M%S')}",
                objective=objective,
                status=status,
                started_at=now,
                completed_at=now,
                goal_outcomes=outcomes,
                goals_attempted=total,
                goals_succeeded=succeeded,
                goals_failed=failed,
                tracks_affected=list(track_stats.keys()),
            )

            adapter = get_nomic_cycle_adapter()
            # Fire-and-forget: don't block on async KM write
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(adapter.ingest_cycle_outcome(cycle))
            except RuntimeError:
                # No running loop - skip async persistence
                logger.debug("No event loop, skipping async KM persistence")

        except ImportError:
            logger.debug("NomicCycleAdapter not available, skipping KM persistence")
        except (ValueError, TypeError, OSError, AttributeError, KeyError) as e:
            logger.warning("Failed to persist outcome to KM: %s", e)

    async def quick_prioritize(
        self,
        goals: list[Any],
    ) -> list["PrioritizedGoal"]:
        """Lightweight goal prioritization without full debate.

        Takes GoalNode objects directly and returns PrioritizedGoal list
        using heuristic scoring. Faster than full prioritize_work().

        Args:
            goals: List of GoalNode objects from GoalExtractor.

        Returns:
            Sorted list of PrioritizedGoal objects.
        """
        prioritized: list[PrioritizedGoal] = []
        for i, goal in enumerate(goals):
            title = getattr(goal, "title", str(goal))
            description = getattr(goal, "description", title)
            priority_attr = getattr(goal, "priority", None)
            goal_type = getattr(goal, "goal_type", "goal")

            # Score by priority and goal type
            if priority_attr == "high" or priority_attr == "critical":
                impact = "high"
                score = 1
            elif priority_attr == "medium":
                impact = "medium"
                score = 2
            else:
                impact = "low"
                score = 3

            # Boost strategies and milestones
            if goal_type in ("strategy", "milestone"):
                score = max(1, score - 1)

            track = self._infer_track(description, list(Track))

            prioritized.append(
                PrioritizedGoal(
                    id=getattr(goal, "id", f"goal_{i}"),
                    track=track,
                    description=description,
                    rationale=f"Derived from {goal_type}: {title}",
                    estimated_impact=impact,
                    priority=score,
                )
            )

        prioritized.sort(key=lambda g: g.priority)
        return prioritized

    async def generate_pipeline_goals(
        self,
        objective: str | None = None,
        available_tracks: list[Track] | None = None,
    ) -> list[Any]:
        """Generate pipeline-compatible GoalNode objects from planning.

        Wraps prioritize_work() and converts results into a format
        compatible with IdeaToExecutionPipeline.

        Returns:
            List of GoalNode-compatible dicts.
        """
        goals = await self.prioritize_work(
            objective=objective,
            available_tracks=available_tracks,
        )
        return [
            {
                "id": g.id,
                "title": g.description,
                "description": g.rationale or g.description,
                "goal_type": "goal",
                "priority": "high" if g.priority <= 1 else "medium" if g.priority <= 3 else "low",
                "track": g.track.value if hasattr(g.track, "value") else str(g.track),
                "estimated_impact": g.estimated_impact,
            }
            for g in goals
        ]

    async def get_system_health_context(self) -> PlanningContext:
        """Query system health metrics and build a PlanningContext.

        Collects test results, CI status, ELO drift, budget burn,
        and KM contradictions for pipeline goal generation.
        """
        context = PlanningContext()

        # Collect test/lint/size metrics if available
        try:
            self._enrich_context_with_metrics(context)
        except (ImportError, OSError, RuntimeError):
            logger.debug("Metrics collection unavailable")

        # Query KM for recent issues
        try:
            from aragora.knowledge.mound import get_knowledge_mound

            km = get_knowledge_mound()
            if km:
                recent = await km.query(query="recent issues bugs failures", limit=5)
                if recent:
                    context.recent_issues = [getattr(r, "title", str(r)) for r in recent]
        except (ImportError, AttributeError, TypeError):
            logger.debug("KM unavailable for system health context")

        # Query CI status from metric snapshot
        if context.metric_snapshot:
            if context.metric_snapshot.get("test_failures"):
                context.test_failures = context.metric_snapshot["test_failures"]
            if context.metric_snapshot.get("ci_failures"):
                context.ci_failures = context.metric_snapshot["ci_failures"]

        return context

    async def generate_goals_from_debate_outcomes(
        self,
        *,
        min_debates: int = 5,
        low_consensus_threshold: float = 0.4,
        time_window_days: int = 30,
    ) -> list[PrioritizedGoal]:
        """Extract improvement goals from debate outcome patterns.

        Analyzes recent debate outcomes for recurring failure modes:
        - Low consensus rate across debates
        - Specific agents consistently underperforming
        - Topics that repeatedly fail to reach consensus
        - High error/timeout rates

        These patterns are translated into actionable Nomic Loop goals.

        Args:
            min_debates: Minimum debate count before generating goals.
            low_consensus_threshold: Consensus rate below which to flag.
            time_window_days: How far back to analyze.

        Returns:
            List of PrioritizedGoal derived from debate outcome patterns.
        """
        goals: list[PrioritizedGoal] = []
        priority = 1

        # Query debate outcomes from cycle store
        outcomes: list[dict[str, Any]] = []
        try:
            from aragora.nomic.cycle_store import get_recent_cycles

            cycles = get_recent_cycles(n=50)
            for cycle in cycles:
                outcomes.append(
                    {
                        "objective": getattr(cycle, "objective", ""),
                        "status": getattr(cycle, "status", "unknown"),
                        "goals_attempted": getattr(cycle, "goals_attempted", 0),
                        "goals_succeeded": getattr(cycle, "goals_succeeded", 0),
                        "goals_failed": getattr(cycle, "goals_failed", 0),
                        "tracks": getattr(cycle, "tracks_affected", []),
                    }
                )
        except (ImportError, RuntimeError, AttributeError, TypeError) as e:
            logger.debug("Cycle store unavailable for outcome analysis: %s", e)

        # Also query PlanStore for pipeline execution outcomes
        try:
            from aragora.pipeline.plan_store import get_plan_store

            store = get_plan_store()
            recent = store.get_recent_outcomes(limit=50) if store else []
            for entry in recent or []:
                outcomes.append(
                    {
                        "objective": entry.get("task", ""),
                        "status": entry.get("status", "unknown"),
                        "goals_attempted": 1,
                        "goals_succeeded": 1 if entry.get("status") == "completed" else 0,
                        "goals_failed": 1 if entry.get("status") in ("failed", "rejected") else 0,
                        "tracks": [],
                        "error": entry.get("execution_error"),
                    }
                )
        except (ImportError, RuntimeError, ValueError) as e:
            logger.debug("PlanStore unavailable for outcome analysis: %s", e)

        # Feed OutcomeFeedbackRecord from backbone runs into goal generation
        try:
            from aragora.pipeline.plan_store import get_plan_store as _get_plan_store

            _store = _get_plan_store()
            if _store is not None:
                terminal_runs = _store.list_runs(status="completed", limit=50)
                terminal_runs += _store.list_runs(status="failed", limit=50)
                for run in terminal_runs:
                    if run.feedback_record is not None:
                        goal_dict = run.feedback_record.to_nomic_goal()
                        track_name = goal_dict.get("module", "")
                        try:
                            track = Track(track_name) if track_name else Track.CORE
                        except ValueError:
                            track = self._infer_track(
                                goal_dict.get("description", ""),
                                list(Track),
                            )
                        goals.append(
                            PrioritizedGoal(
                                id=f"outcome_goal_{priority - 1}",
                                track=track,
                                description=goal_dict.get("description", ""),
                                rationale=goal_dict.get("rationale", ""),
                                estimated_impact=goal_dict.get("priority", "medium"),
                                priority=priority,
                                focus_areas=["outcome_feedback", goal_dict.get("risk", "medium")],
                            )
                        )
                        priority += 1
                        if priority > self.config.max_goals + 1:
                            break
                if any(r.feedback_record for r in terminal_runs):
                    logger.info(
                        "meta_planner_ingested_outcome_feedback count=%d",
                        sum(1 for r in terminal_runs if r.feedback_record),
                    )
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("OutcomeFeedbackRecord ingestion skipped: %s", e)

        if len(outcomes) < min_debates:
            logger.info(
                "generate_goals_from_outcomes: insufficient data (%d < %d)",
                len(outcomes),
                min_debates,
            )
            return goals

        # Analyze patterns
        total = len(outcomes)
        succeeded = sum(1 for o in outcomes if o.get("goals_succeeded", 0) > 0)
        success_rate = succeeded / total if total > 0 else 0.0

        # Pattern 1: Low overall success rate
        if success_rate < low_consensus_threshold:
            goals.append(
                PrioritizedGoal(
                    id=f"outcome_goal_{priority - 1}",
                    track=Track.CORE,
                    description=(
                        f"Improve debate outcome success rate (currently {success_rate:.0%} "
                        f"across {total} recent outcomes, threshold {low_consensus_threshold:.0%})"
                    ),
                    rationale=(
                        f"Only {succeeded}/{total} recent debates/plans succeeded. "
                        f"Investigate agent selection, consensus methods, or prompt quality."
                    ),
                    estimated_impact="high",
                    priority=priority,
                    focus_areas=["consensus", "agent_selection", "prompt_quality"],
                )
            )
            priority += 1

        # Pattern 2: Track-specific failure clustering
        track_failures: dict[str, int] = {}
        track_totals: dict[str, int] = {}
        for o in outcomes:
            for track in o.get("tracks", []):
                track_totals[track] = track_totals.get(track, 0) + 1
                if o.get("goals_failed", 0) > 0:
                    track_failures[track] = track_failures.get(track, 0) + 1

        for track_name, fail_count in sorted(
            track_failures.items(), key=lambda kv: kv[1], reverse=True
        ):
            total_for_track = track_totals.get(track_name, 0)
            if total_for_track < 3:
                continue
            fail_rate = fail_count / total_for_track
            if fail_rate > 0.5:
                try:
                    track = Track(track_name)
                except ValueError:
                    continue
                goals.append(
                    PrioritizedGoal(
                        id=f"outcome_goal_{priority - 1}",
                        track=track,
                        description=(
                            f"Address high failure rate in {track_name} track "
                            f"({fail_count}/{total_for_track} = {fail_rate:.0%} failures)"
                        ),
                        rationale=(
                            f"Track '{track_name}' has {fail_rate:.0%} failure rate "
                            f"over {total_for_track} recent outcomes."
                        ),
                        estimated_impact="high" if fail_rate > 0.7 else "medium",
                        priority=priority,
                        focus_areas=[track_name],
                    )
                )
                priority += 1

        # Pattern 3: Recurring error messages
        error_counts: dict[str, int] = {}
        for o in outcomes:
            err = o.get("error")
            if err:
                # Normalize error to first 80 chars for grouping
                err_key = (
                    str(err)[:80] if isinstance(err, str) else str(err.get("message", ""))[:80]
                )
                if err_key:
                    error_counts[err_key] = error_counts.get(err_key, 0) + 1

        for err_msg, count in sorted(error_counts.items(), key=lambda kv: kv[1], reverse=True):
            if count >= 2:
                goals.append(
                    PrioritizedGoal(
                        id=f"outcome_goal_{priority - 1}",
                        track=Track.QA,
                        description=(f"Fix recurring error ({count}x): {err_msg}"),
                        rationale=f"Error appeared {count} times in recent outcomes.",
                        estimated_impact="high" if count >= 3 else "medium",
                        priority=priority,
                        focus_areas=["error_handling", "reliability"],
                    )
                )
                priority += 1
                if priority > self.config.max_goals + 1:
                    break

        if goals:
            logger.info(
                "generate_goals_from_outcomes: generated %d goals from %d outcomes",
                len(goals),
                total,
            )

        return goals[: self.config.max_goals]

    def classify_goal_risk(self, goal: PrioritizedGoal) -> str:
        """Classify a goal's risk level based on its description and focus areas.

        Returns 'low', 'medium', or 'high'. Low-risk goals include test fixes,
        documentation updates, and lint cleanup. High-risk goals include
        security changes, database migrations, and API contract changes.

        Args:
            goal: The goal to classify.

        Returns:
            Risk category string: 'low', 'medium', or 'high'.
        """
        desc_lower = goal.description.lower()
        focus = " ".join(goal.focus_areas).lower() if goal.focus_areas else ""
        combined = f"{desc_lower} {focus}"

        # High risk: security, auth, database, API changes, breaking changes
        high_risk_patterns = [
            "security",
            "auth",
            "encryption",
            "migration",
            "schema",
            "database",
            "breaking change",
            "api contract",
            "delete",
            "remove",
            "drop",
            "rbac",
            "permission",
        ]
        if any(p in combined for p in high_risk_patterns):
            return "high"

        # Low risk: tests, docs, lint, formatting, typos, comments
        low_risk_patterns = [
            "test",
            "lint",
            "format",
            "typo",
            "comment",
            "docstring",
            "documentation",
            "readme",
            "type hint",
            "type annotation",
            "unused import",
            "whitespace",
            "spelling",
        ]
        if any(p in combined for p in low_risk_patterns):
            return "low"

        return "medium"

    def filter_auto_executable(
        self, goals: list[PrioritizedGoal]
    ) -> tuple[list[PrioritizedGoal], list[PrioritizedGoal]]:
        """Split goals into auto-executable (low risk) and needs-review.

        Only produces auto-executable goals when ``auto_execute_low_risk``
        is enabled in config.

        Args:
            goals: List of prioritized goals to classify.

        Returns:
            Tuple of (auto_execute, needs_review) goal lists.
        """
        if not self.config.auto_execute_low_risk:
            return [], goals

        auto_execute: list[PrioritizedGoal] = []
        needs_review: list[PrioritizedGoal] = []

        for goal in goals:
            risk = self.classify_goal_risk(goal)
            if risk == "low":
                auto_execute.append(goal)
            else:
                needs_review.append(goal)

        if auto_execute:
            logger.info(
                "auto_execute_filter auto=%d review=%d",
                len(auto_execute),
                len(needs_review),
            )

        return auto_execute, needs_review


__all__ = [
    "MetaPlanner",
    "MetaPlannerConfig",
    "MetaPlanningResult",
    "PrioritizedGoal",
    "PlanningContext",
    "HistoricalLearning",
    "Track",
]
