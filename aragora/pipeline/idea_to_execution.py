"""
Idea-to-Execution Pipeline.

Orchestrates the full four-stage flow:
  Stage 1 (Ideas) → Stage 2 (Goals) → Stage 3 (Actions) → Stage 4 (Orchestration)

Each transition is a pipeline stage with:
- AI-generated best-effort output
- Human-in-the-loop gate for review/modification
- Provenance chain linking every output to its origins
- SHA-256 content hashes for integrity verification

Usage:
    pipeline = IdeaToExecutionPipeline()

    # From debate
    result = pipeline.from_debate(cartographer_data)

    # From raw ideas
    result = pipeline.from_ideas(["idea 1", "idea 2", ...])

    # Access each stage
    result.ideas_canvas      # Stage 1
    result.goal_graph         # Stage 2
    result.workflow            # Stage 3
    result.execution_plan      # Stage 4
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aragora.canvas.converters import (
    debate_to_ideas_canvas,
    execution_to_orchestration_canvas,
    ideas_to_principles_canvas,
    to_react_flow,
    workflow_to_actions_canvas,
)
from aragora.canvas.models import Canvas
from aragora.canvas.stages import (
    PipelineStage,
    ProvenanceLink,
    StageEdgeType,
    StageTransition,
    content_hash,
)
from aragora.goals.extractor import GoalExtractionConfig, GoalExtractor, GoalGraph

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from aragora.workflow.types import WorkflowDefinition


def _spectate(event_type: str, details: str) -> None:
    """Emit a SpectatorStream event using the graceful degradation pattern.

    This is a fire-and-forget helper: if the spectate module is unavailable
    or the stream is not enabled, the call silently does nothing.  A cached
    module-level instance is reused across calls to avoid repeated allocations.
    """
    try:
        from aragora.spectate.stream import SpectatorStream  # noqa: F401

        stream = _get_spectator_stream()
        stream.emit(event_type=event_type, details=details)
    except (ImportError, TypeError):
        logger.debug("SpectatorStream unavailable, event skipped")


def _get_spectator_stream() -> Any:
    """Return a cached SpectatorStream instance (lazy-init)."""
    global _spectator_stream_cache
    if _spectator_stream_cache is None:
        from aragora.spectate.stream import SpectatorStream

        _spectator_stream_cache = SpectatorStream(enabled=True)
    return _spectator_stream_cache


_spectator_stream_cache: Any = None

# Stages included in default pipeline status (PRINCIPLES is opt-in)
_DEFAULT_STAGES = [s for s in PipelineStage if s != PipelineStage.PRINCIPLES]


def _initial_stage_status(enable_principles: bool = False) -> dict[str, str]:
    """Build the initial stage_status dict, including PRINCIPLES only when enabled."""
    stages = list(PipelineStage) if enable_principles else _DEFAULT_STAGES
    return {s.value: "pending" for s in stages}


@dataclass
class PipelineConfig:
    """Configuration for async pipeline execution."""

    stages_to_run: list[str] = field(
        default_factory=lambda: ["ideation", "goals", "workflow", "orchestration"]
    )
    debate_rounds: int = 3
    goal_extraction_config: GoalExtractionConfig | None = None
    workflow_mode: str = "quick"  # "quick" or "debate"
    orchestration_tracks: list[str] | None = None
    max_orchestration_cycles: int = 5
    dry_run: bool = False
    enable_receipts: bool = True
    event_callback: Any | None = None  # callable(event_type: str, data: dict)
    worktree_path: str | None = None  # Git worktree for agent execution
    enable_smart_goals: bool = True
    enable_elo_assignment: bool = True
    enable_km_precedents: bool = True
    human_approval_required: bool = False  # Require human approval between stages
    enable_km_persistence: bool = True  # Auto-persist results to KnowledgeMound
    use_arena_orchestration: bool = True  # Use Arena mini-debate in Stage 4 (gracefully degrades)
    use_hardened_orchestrator: bool = False  # Use HardenedOrchestrator in Stage 4
    template: Any | None = None  # DeliberationTemplate for Arena defaults
    spectator: Any | None = None  # SpectatorStream for real-time observation
    enable_principles: bool = False  # Insert Principles stage between Ideas and Goals
    enable_beads: bool = False  # Map Stage 4 tasks to Bead lifecycle objects
    enable_fractal: bool = False  # Use FractalOrchestrator for recursive ideation
    enable_meta_tuning: bool = False  # MetaLearner self-tuning
    enable_workspace_context: bool = True  # Check workspace for existing work
    # Plan quality gate (applies to stage-3/4 handoff artifacts)
    plan_quality_contract_file: str | None = None
    plan_quality_fail_closed: bool = False
    plan_quality_min_score: float = 0.0
    plan_quality_min_practicality: float = 0.0
    # Mode map: pipeline stage → operational mode name
    mode_map: dict[str, str] = field(
        default_factory=lambda: {
            "ideation": "architect",
            "goals": "architect",
            "workflow": "coder",
            "orchestration": "orchestrator",
        }
    )
    # Transient state: introspection data captured during debate for agent ranking
    _introspection_data: Any | None = field(default=None, repr=False)


@dataclass
class StageResult:
    """Result of a single pipeline stage."""

    stage_name: str
    status: str = "pending"  # pending, running, completed, failed, skipped
    output: Any = None
    duration: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "stage_name": self.stage_name,
            "status": self.status,
            "duration": self.duration,
        }
        if self.error:
            result["error"] = self.error
        if self.output is not None and hasattr(self.output, "to_dict"):
            result["output_summary"] = {"type": type(self.output).__name__}
        return result


@dataclass
class PipelineResult:
    """Complete result of the idea-to-execution pipeline.

    Contains the output of each stage as both structured data
    and React Flow-compatible canvas representations.
    """

    pipeline_id: str
    # Stage outputs
    ideas_canvas: Canvas | None = None
    principles_canvas: Canvas | None = None
    goal_graph: GoalGraph | None = None
    actions_canvas: Canvas | None = None
    orchestration_canvas: Canvas | None = None
    # Stage transitions
    transitions: list[StageTransition] = field(default_factory=list)
    # Full provenance chain
    provenance: list[ProvenanceLink] = field(default_factory=list)
    # Human review status per stage
    stage_status: dict[str, str] = field(default_factory=dict)
    # Async pipeline fields
    stage_results: list[StageResult] = field(default_factory=list)
    final_workflow: dict[str, Any] | None = None
    orchestration_result: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    plan_quality_report: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0
    # Universal graph (populated when use_universal=True)
    universal_graph: Any | None = None  # UniversalGraph
    # Workspace context (populated when enable_workspace_context=True)
    workspace_context: Any | None = None  # WorkspaceContext

    def to_dict(self) -> dict[str, Any]:
        result = {
            "pipeline_id": self.pipeline_id,
            "ideas": to_react_flow(self.ideas_canvas) if self.ideas_canvas else None,
            "principles": (
                to_react_flow(self.principles_canvas) if self.principles_canvas else None
            ),
            "goals": self.goal_graph.to_dict() if self.goal_graph else None,
            "actions": to_react_flow(self.actions_canvas) if self.actions_canvas else None,
            "orchestration": (
                to_react_flow(self.orchestration_canvas) if self.orchestration_canvas else None
            ),
            "transitions": [t.to_dict() for t in self.transitions],
            "provenance": [p.to_dict() for p in self.provenance],
            "provenance_count": len(self.provenance),
            "stage_status": self.stage_status,
            "integrity_hash": self._compute_integrity_hash(),
        }
        if self.stage_results:
            result["stage_results"] = [sr.to_dict() for sr in self.stage_results]
        if self.final_workflow is not None:
            result["final_workflow"] = self.final_workflow
        if self.orchestration_result is not None:
            result["orchestration_result"] = self.orchestration_result
        if self.receipt is not None:
            result["receipt"] = self.receipt
        if self.plan_quality_report is not None:
            result["plan_quality_report"] = self.plan_quality_report
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        if self.duration > 0:
            result["duration"] = self.duration
        if self.universal_graph is not None and hasattr(self.universal_graph, "to_dict"):
            result["universal_graph"] = self.universal_graph.to_dict()
        if self.workspace_context is not None and hasattr(self.workspace_context, "to_dict"):
            result["workspace_context"] = self.workspace_context.to_dict()
        return result

    def _compute_integrity_hash(self) -> str:
        """Compute a pipeline-wide integrity hash."""
        parts = []
        for link in self.provenance:
            parts.append(link.content_hash)
        combined = ":".join(sorted(parts))
        return hashlib.sha256(combined.encode()).hexdigest()[:16]


class IdeaToExecutionPipeline:
    """Orchestrates the four-stage idea-to-execution flow.

    Each stage produces a Canvas with typed nodes and provenance links.
    The pipeline can be run end-to-end or stage-by-stage with human
    review gates between stages.
    """

    def __init__(
        self,
        goal_extractor: GoalExtractor | None = None,
        agent: Any | None = None,
        use_universal: bool = False,
    ):
        """Initialize the pipeline.

        Args:
            goal_extractor: Custom GoalExtractor (defaults to structural mode)
            agent: Optional AI agent for synthesis across stages
            use_universal: If True, build a UniversalGraph alongside Canvas outputs
        """
        self._goal_extractor = goal_extractor or GoalExtractor(agent=agent)
        self._agent = agent
        self._use_universal = use_universal

    @classmethod
    def from_prioritized_goals(
        cls,
        goals: list[Any],
        auto_advance: bool = True,
        pipeline_id: str | None = None,
    ) -> PipelineResult:
        """Create a pipeline from MetaPlanner PrioritizedGoal objects.

        Bridges the self-improvement system (MetaPlanner) into the visual
        pipeline by converting each PrioritizedGoal into a formatted idea
        string and running ``from_ideas()``.

        Args:
            goals: List of PrioritizedGoal objects from MetaPlanner.prioritize_work()
            auto_advance: If True, auto-generate all stages
            pipeline_id: Optional pipeline ID

        Returns:
            PipelineResult with all stages populated
        """
        ideas: list[str] = []
        for goal in goals:
            impact = getattr(goal, "estimated_impact", "medium")
            description = getattr(goal, "description", str(goal))
            rationale = getattr(goal, "rationale", "")
            track = getattr(goal, "track", None)
            track_str = track.value if hasattr(track, "value") else str(track or "core")

            parts = [f"[{impact}]"]
            if track_str:
                parts.append(f"({track_str})")
            parts.append(description)
            if rationale:
                parts.append(f"— {rationale}")

            ideas.append(" ".join(parts))

        pipeline = cls()
        return pipeline.from_ideas(
            ideas,
            auto_advance=auto_advance,
            pipeline_id=pipeline_id,
        )

    @classmethod
    def from_demo(cls) -> tuple[PipelineResult, PipelineConfig]:
        """Create a pre-built demo pipeline showcasing all flywheel features.

        The seed ideas are specifically crafted to exercise every flywheel
        stage so the demo output is self-documenting:

        - **Semantic clustering**: Ideas #3-#5 share API/latency/response
          vocabulary and will be grouped into a performance cluster.
        - **Goal conflict detection**: Ideas #1 and #2 contain the
          contradictory pair ``increase``/``decrease`` applied to deployment
          frequency.  The extractor flags the resulting goals as conflicting
          and attaches resolution guidance.
        - **SMART scoring**: Idea #6 is intentionally rich in specific,
          measurable, and time-bound language (``99.9 %``, ``Q3 2026``) so
          it scores high, demonstrating the contrast between well-defined
          and vaguely-worded goals.
        - **ELO-aware agent assignment**: When the TeamSelector is available,
          orchestration tasks are assigned to agents ranked by domain ELO.
        - **KM precedent lookup**: Goals are enriched with prior decisions
          from the Knowledge Mound when the bridge is available.
        - **Human approval gate**: ``human_approval_required=True`` signals
          that a review checkpoint exists between stages.
        - **Dry-run mode**: No real execution engines are invoked.

        Returns:
            Tuple of (PipelineResult, PipelineConfig) so callers can
            inspect both the demo output and the config that produced it.
        """
        config = PipelineConfig(
            enable_smart_goals=True,
            enable_elo_assignment=True,
            enable_km_precedents=True,
            human_approval_required=True,
            dry_run=True,
        )

        pipeline = cls()
        # NB: order matters — the structural extractor picks top-N by score
        # (equal scores → insertion order).  The contradictory pair is placed
        # first so both ideas become separate goals and trigger conflict
        # detection.
        ideas = [
            # Conflict pair — contradictory deployment cadence
            "Increase API deployment frequency to ship features faster every sprint",
            "Decrease API deployment frequency to improve stability and reduce risk",
            # Cluster: API performance (share "api", "latency", "response")
            "Implement Redis caching to reduce API response latency by 40%",
            "Add rate limiting to API endpoints to prevent overload and improve response times",
            "Deploy API performance monitoring with response time and latency dashboards",
            # SMART-rich idea (specific + measurable + time-bound)
            "Achieve 99.9% API uptime by Q3 2026 by implementing circuit breakers and failover",
        ]
        result = pipeline.from_ideas(ideas, auto_advance=True)
        return result, config

    @classmethod
    async def from_brain_dump(
        cls,
        text: str,
        automation_level: str = "guided",
        pipeline_id: str | None = None,
        event_callback: Any | None = None,
    ) -> PipelineResult:
        """Create and run a pipeline from unstructured brain dump text.

        Chains: BrainDumpParser.parse_enriched() → cluster ideas → extract
        principles → debate-prioritize goals → decompose tasks → assign agents.

        Args:
            text: Raw unstructured text (brain dump).
            automation_level: One of "full", "guided", "manual".
                - "full": Runs entire pipeline with AI transitions.
                - "guided": Pauses at each stage for approval.
                - "manual": Generates ideas only.
            pipeline_id: Optional pipeline ID (generated if not provided).
            event_callback: Optional callback for real-time progress events.

        Returns:
            PipelineResult with stages populated based on automation_level.
        """
        from aragora.pipeline.brain_dump_parser import BrainDumpParser

        pid = pipeline_id or f"braindump-{uuid.uuid4().hex[:12]}"

        parser = BrainDumpParser()
        enriched = parser.parse_enriched(text)
        logger.info(
            "Brain dump parsed: %d ideas, themes=%s, urgency=%s",
            len(enriched.ideas),
            enriched.detected_themes,
            enriched.urgency_signals,
        )

        if not enriched.ideas:
            return PipelineResult(
                pipeline_id=pid,
                stage_status=_initial_stage_status(),
            )

        pipeline = cls()

        if automation_level == "manual":
            return pipeline.from_ideas(
                enriched.ideas,
                auto_advance=False,
                pipeline_id=pid,
            )

        # For "full" and "guided", run the full pipeline
        cfg = PipelineConfig(
            stages_to_run=["ideation", "principles", "goals", "workflow", "orchestration"],
            enable_principles=True,
        )

        if automation_level == "guided":
            # In guided mode we still run all stages but flag for approval
            cfg.stages_to_run = ["ideation"]  # Start with just ideation

        result = await pipeline.run(
            input_text=text,
            config=cfg,
            pipeline_id=pid,
        )

        return result

    @classmethod
    async def from_system_metrics(
        cls,
        pipeline_id: str | None = None,
    ) -> PipelineResult:
        """Create a pipeline from system health metrics.

        Queries system health (test pass rate, ELO drift, budget burn,
        KM contradictions) and auto-generates improvement ideas.

        Returns:
            PipelineResult with system-generated improvement ideas.
        """
        pid = pipeline_id or f"sysmetrics-{uuid.uuid4().hex[:12]}"
        ideas: list[str] = []

        try:
            from aragora.nomic.meta_planner import MetaPlanner

            planner = MetaPlanner()
            context = await planner.get_system_health_context()

            if context.test_failures:
                for tf in context.test_failures[:5]:
                    ideas.append(f"[high] Fix test failure: {tf}")
            if context.recent_issues:
                for issue in context.recent_issues[:5]:
                    ideas.append(f"[medium] Address issue: {issue}")
            if context.ci_failures:
                for ci in context.ci_failures[:3]:
                    ideas.append(f"[high] Fix CI failure: {ci}")
            if context.ci_flaky_tests:
                for flaky in context.ci_flaky_tests[:3]:
                    ideas.append(f"[medium] Stabilize flaky test: {flaky}")
        except (ImportError, AttributeError):
            logger.debug("MetaPlanner unavailable for system metrics")

        if not ideas:
            ideas = [
                "[low] Review and update test coverage",
                "[low] Check for dependency updates",
                "[low] Review error logs for recurring issues",
            ]

        pipeline = cls()
        result = pipeline.from_ideas(
            ideas,
            auto_advance=True,
            pipeline_id=pid,
        )
        return result

    def from_debate(
        self,
        cartographer_data: dict[str, Any],
        auto_advance: bool = True,
        pipeline_id: str | None = None,
        event_callback: Any | None = None,
    ) -> PipelineResult:
        """Run the full pipeline starting from a debate graph.

        Args:
            cartographer_data: ArgumentCartographer.to_dict() output
            auto_advance: If True, auto-generate all stages.
                          If False, stop after Stage 1 for human review.
            pipeline_id: Optional external pipeline ID (generated if not provided)
            event_callback: Optional callable(event_type, data) for progress events
        """
        pipeline_id = pipeline_id or f"pipe-{uuid.uuid4().hex[:8]}"
        result = PipelineResult(
            pipeline_id=pipeline_id,
            stage_status=_initial_stage_status(),
        )
        _spectate("pipeline.started", f"pipeline_id={pipeline_id} source=debate")

        # Stage 1: Ideas
        _spectate("pipeline.stage_started", "stage=ideation")
        result.ideas_canvas = debate_to_ideas_canvas(
            cartographer_data,
            canvas_name="Ideas from Debate",
        )
        result.stage_status[PipelineStage.IDEAS.value] = "complete"
        self._emit_sync(event_callback, "stage_completed", {"stage": "ideas"})
        _spectate("pipeline.stage_completed", "stage=ideation")
        logger.info(
            "Pipeline %s: Stage 1 complete — %d idea nodes",
            pipeline_id,
            len(result.ideas_canvas.nodes),
        )

        if not auto_advance:
            return result

        # Stage 2: Goals
        _spectate("pipeline.stage_started", "stage=goals")
        self._emit_sync(event_callback, "stage_started", {"stage": "goals"})
        result = self._advance_to_goals(result)
        self._emit_sync(event_callback, "stage_completed", {"stage": "goals"})
        _spectate("pipeline.stage_completed", "stage=goals")
        # Emit node-level events for goals
        if result.goal_graph:
            for goal in result.goal_graph.goals:
                self._emit_sync(
                    event_callback,
                    "goal_extracted",
                    {"goal": goal.to_dict()},
                )
                self._emit_sync(
                    event_callback,
                    "pipeline_node_added",
                    {
                        "stage": "goals",
                        "node_id": goal.id,
                        "node_type": goal.goal_type.value,
                        "label": goal.title,
                    },
                )

        # Stage 3: Actions
        _spectate("pipeline.stage_started", "stage=actions")
        self._emit_sync(event_callback, "stage_started", {"stage": "actions"})
        result = self._advance_to_actions(result)
        self._emit_sync(event_callback, "stage_completed", {"stage": "actions"})
        _spectate("pipeline.stage_completed", "stage=actions")
        # Emit node-level events for action steps
        if result.actions_canvas:
            for node_id, node in result.actions_canvas.nodes.items():
                self._emit_sync(
                    event_callback,
                    "pipeline_node_added",
                    {
                        "stage": "actions",
                        "node_id": node_id,
                        "node_type": node.data.get("step_type", "task"),
                        "label": node.label,
                    },
                )

        # Stage 4: Orchestration
        _spectate("pipeline.stage_started", "stage=orchestration")
        self._emit_sync(event_callback, "stage_started", {"stage": "orchestration"})
        result = self._advance_to_orchestration(result)
        self._emit_sync(event_callback, "stage_completed", {"stage": "orchestration"})
        _spectate("pipeline.stage_completed", "stage=orchestration")
        # Emit node-level events for orchestration tasks
        if result.orchestration_canvas:
            for node_id, node in result.orchestration_canvas.nodes.items():
                self._emit_sync(
                    event_callback,
                    "pipeline_node_added",
                    {
                        "stage": "orchestration",
                        "node_id": node_id,
                        "node_type": node.data.get("orch_type", "agent_task"),
                        "label": node.label,
                    },
                )

        self._build_universal_graph(result)

        # Persist pipeline result to KM for future precedent queries
        try:
            from aragora.pipeline.km_bridge import PipelineKMBridge

            bridge = PipelineKMBridge()
            if bridge.available:
                bridge.store_pipeline_result(result)
        except (ImportError, RuntimeError, TypeError) as exc:
            logger.debug("KM pipeline result storage unavailable: %s", exc)

        _spectate("pipeline.completed", f"pipeline_id={pipeline_id}")
        return result

    def from_ideas(
        self,
        ideas: list[str],
        auto_advance: bool = True,
        pipeline_id: str | None = None,
        event_callback: Any | None = None,
    ) -> PipelineResult:
        """Run the full pipeline from raw idea strings.

        Simpler entry point for users who just have a list of thoughts.

        Args:
            ideas: List of idea/thought strings
            auto_advance: If True, auto-generate all stages
            pipeline_id: Optional external pipeline ID (generated if not provided)
            event_callback: Optional callable(event_type, data) for progress events
        """
        pipeline_id = pipeline_id or f"pipe-{uuid.uuid4().hex[:8]}"
        result = PipelineResult(
            pipeline_id=pipeline_id,
            stage_status=_initial_stage_status(),
        )
        _spectate("pipeline.started", f"pipeline_id={pipeline_id} source=ideas")

        # Stage 1: Convert raw ideas to canvas
        _spectate("pipeline.stage_started", "stage=ideation")
        result.goal_graph = self._goal_extractor.extract_from_raw_ideas(ideas)
        result.ideas_canvas = Canvas(
            id=f"ideas-raw-{uuid.uuid4().hex[:8]}",
            name="Raw Ideas",
            metadata={"stage": PipelineStage.IDEAS.value, "source": "raw"},
        )
        # Add idea nodes to canvas
        from aragora.canvas.converters import _radial_layout
        from aragora.canvas.models import CanvasNode, CanvasNodeType, Position

        positions = _radial_layout(len(ideas))
        for i, idea in enumerate(ideas):
            pos = positions[i] if i < len(positions) else Position(0, 0)
            node = CanvasNode(
                id=f"raw-idea-{i}",
                node_type=CanvasNodeType.KNOWLEDGE,
                position=pos,
                label=idea[:80],
                data={
                    "stage": PipelineStage.IDEAS.value,
                    "idea_type": "concept",
                    "full_content": idea,
                    "content_hash": content_hash(idea),
                    "rf_type": "ideaNode",
                },
            )
            result.ideas_canvas.nodes[node.id] = node

        result.stage_status[PipelineStage.IDEAS.value] = "complete"
        self._emit_sync(event_callback, "stage_completed", {"stage": "ideas"})
        _spectate("pipeline.stage_completed", "stage=ideation")
        # Emit node-level events for ideas
        for node_id, node in result.ideas_canvas.nodes.items():
            self._emit_sync(
                event_callback,
                "pipeline_node_added",
                {
                    "stage": "ideas",
                    "node_id": node_id,
                    "node_type": "idea",
                    "label": node.label,
                },
            )

        # SMART score goals and detect conflicts
        if result.goal_graph and result.goal_graph.goals:
            try:
                conflicts = self._goal_extractor.detect_goal_conflicts(result.goal_graph)
                if conflicts:
                    result.goal_graph.metadata["conflicts"] = conflicts
            except (TypeError, ValueError, KeyError):
                logger.debug("Conflict detection skipped for goal graph")

            for goal in result.goal_graph.goals:
                try:
                    smart_scores = self._goal_extractor.score_smart(goal)
                    goal.metadata["smart_scores"] = smart_scores
                    overall = smart_scores.get("overall", 0.5)
                    if overall >= 0.7:
                        goal.priority = "high"
                    elif overall < 0.4:
                        goal.priority = "low"
                except (TypeError, ValueError, KeyError):
                    logger.debug("SMART scoring skipped for goal %s", goal.id)

        # Enrich goal graph with past strategic findings
        try:
            from aragora.nomic.strategic_memory import StrategicMemoryStore

            sm_store = StrategicMemoryStore()
            past = sm_store.get_latest(limit=2)
            if past:
                hints = [f.description for a in past for f in a.findings[:3]]
                if hints and result.goal_graph:
                    result.goal_graph.metadata["strategic_hints"] = hints[:6]
                    logger.debug("Pipeline enriched with %d strategic hints", len(hints))
        except (ImportError, RuntimeError, ValueError, OSError) as exc:
            logger.debug("Strategic hints enrichment skipped: %s", exc)

        # Merge goal provenance into pipeline provenance
        if result.goal_graph:
            if result.goal_graph.transition:
                result.transitions.append(result.goal_graph.transition)
            result.provenance.extend(result.goal_graph.provenance)

        # Goals already extracted via extract_from_raw_ideas
        result.stage_status[PipelineStage.GOALS.value] = "complete"
        self._emit_sync(event_callback, "stage_completed", {"stage": "goals"})
        _spectate("pipeline.stage_completed", "stage=goals")
        # Emit individual goal_extracted events and node-level events
        if result.goal_graph:
            for goal in result.goal_graph.goals:
                self._emit_sync(
                    event_callback,
                    "goal_extracted",
                    {"goal": goal.to_dict()},
                )
                self._emit_sync(
                    event_callback,
                    "pipeline_node_added",
                    {
                        "stage": "goals",
                        "node_id": goal.id,
                        "node_type": goal.goal_type.value,
                        "label": goal.title,
                    },
                )

        if not auto_advance:
            return result

        # Stage 3: Actions
        _spectate("pipeline.stage_started", "stage=actions")
        self._emit_sync(event_callback, "stage_started", {"stage": "actions"})
        result = self._advance_to_actions(result)
        self._emit_sync(event_callback, "stage_completed", {"stage": "actions"})
        _spectate("pipeline.stage_completed", "stage=actions")
        # Emit node-level events for action steps
        if result.actions_canvas:
            for node_id, node in result.actions_canvas.nodes.items():
                self._emit_sync(
                    event_callback,
                    "pipeline_node_added",
                    {
                        "stage": "actions",
                        "node_id": node_id,
                        "node_type": node.data.get("step_type", "task"),
                        "label": node.label,
                    },
                )

        # Stage 4: Orchestration
        _spectate("pipeline.stage_started", "stage=orchestration")
        self._emit_sync(event_callback, "stage_started", {"stage": "orchestration"})
        result = self._advance_to_orchestration(result)
        self._emit_sync(event_callback, "stage_completed", {"stage": "orchestration"})
        _spectate("pipeline.stage_completed", "stage=orchestration")
        # Emit node-level events for orchestration tasks
        if result.orchestration_canvas:
            for node_id, node in result.orchestration_canvas.nodes.items():
                self._emit_sync(
                    event_callback,
                    "pipeline_node_added",
                    {
                        "stage": "orchestration",
                        "node_id": node_id,
                        "node_type": node.data.get("orch_type", "agent_task"),
                        "label": node.label,
                    },
                )

        self._build_universal_graph(result)

        # Close the feedback loop: persist pipeline result to KM for future
        # precedent queries. This means the next pipeline run can learn from
        # past goal/action patterns via query_similar_goals/actions.
        try:
            from aragora.pipeline.km_bridge import PipelineKMBridge

            bridge = PipelineKMBridge()
            if bridge.available:
                bridge.store_pipeline_result(result)
        except (ImportError, RuntimeError, TypeError) as exc:
            logger.debug("KM pipeline result storage unavailable: %s", exc)

        _spectate("pipeline.completed", f"pipeline_id={pipeline_id}")
        return result

    def advance_stage(
        self,
        result: PipelineResult,
        target_stage: PipelineStage,
    ) -> PipelineResult:
        """Advance the pipeline to a specific stage.

        Used when humans have reviewed and approved a stage,
        and want to advance to the next one.
        """
        if target_stage == PipelineStage.PRINCIPLES:
            return self._advance_to_principles(result)
        elif target_stage == PipelineStage.GOALS:
            return self._advance_to_goals(result)
        elif target_stage == PipelineStage.ACTIONS:
            return self._advance_to_actions(result)
        elif target_stage == PipelineStage.ORCHESTRATION:
            return self._advance_to_orchestration(result)
        return result

    # =========================================================================
    # Async pipeline execution
    # =========================================================================

    async def run(
        self,
        input_text: str,
        config: PipelineConfig | None = None,
        pipeline_id: str | None = None,
    ) -> PipelineResult:
        """Run the full async pipeline from input text.

        Executes each configured stage in sequence, emitting events via
        config.event_callback at each stage boundary. Supports dry_run
        mode (skips orchestration) and receipt generation.

        Args:
            input_text: The input idea/question/problem statement
            config: Pipeline configuration
            pipeline_id: Optional external pipeline ID (generated if not provided)

        Returns:
            PipelineResult with all stage outputs
        """
        cfg = config or PipelineConfig()
        pipeline_id = pipeline_id or f"pipe-{uuid.uuid4().hex[:8]}"
        start_time = time.monotonic()

        # Auto-wire PipelineStreamEmitter for WebSocket delivery if no callback set
        if cfg.event_callback is None:
            try:
                from aragora.server.stream.pipeline_stream import get_pipeline_emitter

                cfg.event_callback = get_pipeline_emitter().as_event_callback(pipeline_id)
            except (ImportError, RuntimeError):
                pass  # No server context, skip WebSocket emission

        result = PipelineResult(
            pipeline_id=pipeline_id,
            stage_status=_initial_stage_status(enable_principles=cfg.enable_principles),
        )
        _spectate("pipeline.started", f"pipeline_id={pipeline_id} source=async")

        # Create ProvenanceChain for cryptographic audit trail
        provenance_chain = None
        try:
            from aragora.reasoning.provenance import (
                ProvenanceChain as ReasoningProvenanceChain,
                SourceType,
            )

            provenance_chain = ReasoningProvenanceChain()
        except ImportError:
            pass

        # MetaLearner self-tuning: adjust debate rounds based on past performance
        if cfg.enable_meta_tuning:
            try:
                from aragora.knowledge.bridges import KnowledgeBridgeHub
                from aragora.knowledge.mound import get_knowledge_mound

                mound = get_knowledge_mound()
                if mound:
                    hub = KnowledgeBridgeHub(mound)
                    # Query past pipeline runs for debate round tuning hints
                    precedents = await hub.query_precedents(  # type: ignore[attr-defined]
                        topic="debate rounds optimal count", limit=3
                    )
                    if precedents:
                        # Extract rounds from most recent successful precedent
                        for p in precedents:
                            meta = getattr(p, "metadata", {}) or {}
                            rounds = meta.get("debate_rounds")
                            if rounds and isinstance(rounds, int):
                                cfg.debate_rounds = rounds
                                logger.info(
                                    "MetaLearner tuned debate_rounds to %d", cfg.debate_rounds
                                )
                                break
            except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                logger.debug("MetaLearner tuning unavailable: %s", exc)

        # Workspace context: check for existing execution history
        workspace_ctx = None
        if cfg.enable_workspace_context:
            try:
                from aragora.pipeline.workspace_bridge import WorkspacePipelineBridge

                ws_bridge = WorkspacePipelineBridge()
                workspace_ctx = await ws_bridge.query_context(input_text)
                if workspace_ctx and workspace_ctx.has_context:
                    logger.info(
                        "Workspace context: %d related beads, %d completed goals",
                        len(workspace_ctx.related_beads),
                        len(workspace_ctx.completed_goals),
                    )
                    _spectate(
                        "pipeline.workspace_context",
                        f"found {len(workspace_ctx.related_beads)} related beads",
                    )
            except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                logger.debug("Workspace context unavailable: %s", exc)

        if workspace_ctx and workspace_ctx.has_context:
            result.workspace_context = workspace_ctx

        # KM precedent enrichment: query similar past pipelines and high-ROI patterns
        km_context: dict[str, Any] = {}
        if cfg.enable_km_precedents:
            try:
                from aragora.knowledge.mound.adapters.pipeline_adapter import (
                    get_pipeline_adapter,
                )

                pipeline_adapter = get_pipeline_adapter()
                similar = await pipeline_adapter.find_similar_pipelines(input_text, limit=3)
                if similar:
                    km_context["similar_pipelines"] = [s.to_dict() for s in similar]
                    logger.info(
                        "Pipeline %s: found %d similar past pipelines",
                        pipeline_id,
                        len(similar),
                    )
                    _spectate(
                        "pipeline.km_context",
                        f"found {len(similar)} similar pipelines",
                    )

                patterns = await pipeline_adapter.get_high_roi_patterns(limit=3)
                if patterns:
                    km_context["high_roi_patterns"] = patterns
            except (
                ImportError,
                RuntimeError,
                ValueError,
                TypeError,
                AttributeError,
                OSError,
            ) as exc:
                logger.debug("Pipeline KM context enrichment unavailable: %s", exc)

        # Enrich input with KM context for ideation (non-destructive append)
        enriched_input = input_text
        if km_context.get("similar_pipelines"):
            lessons = []
            for sp in km_context["similar_pipelines"][:3]:
                desc = sp.get("description", "")[:150]
                status = sp.get("status", "unknown")
                if desc:
                    lessons.append(f"- [{status}] {desc}")
            if lessons:
                enriched_input += "\n\nContext from similar past pipelines:\n" + "\n".join(lessons)

        self._emit(cfg, "started", {"pipeline_id": pipeline_id, "stages": cfg.stages_to_run})

        try:
            quality_gate_blocked = False
            # Stage 1: Ideation
            if "ideation" in cfg.stages_to_run:
                sr = await self._run_ideation(pipeline_id, enriched_input, cfg)
                result.stage_results.append(sr)
                if sr.status == "completed" and sr.output:
                    result.ideas_canvas = sr.output.get("canvas")
                    result.stage_status[PipelineStage.IDEAS.value] = "complete"
                    # Emit node-level events for idea nodes
                    canvas = sr.output.get("canvas")
                    if canvas and hasattr(canvas, "nodes"):
                        nodes = canvas.nodes
                        if isinstance(nodes, dict):
                            nodes = nodes.values()
                        for node in nodes:
                            self._emit(
                                cfg,
                                "pipeline_node_added",
                                {
                                    "stage": "ideation",
                                    "node_id": getattr(node, "id", ""),
                                    "node_type": "idea",
                                    "label": getattr(node, "label", ""),
                                },
                            )
                    # Capture introspection data for Stage 4 agent ranking
                    debate_result = sr.output.get("debate_result")
                    if debate_result:
                        tracker = getattr(debate_result, "introspection_tracker", None)
                        if tracker:
                            try:
                                introspection_data = tracker.get_all_summaries()
                                cfg._introspection_data = introspection_data
                            except (AttributeError, TypeError):
                                pass
                elif sr.status == "failed":
                    result.stage_status[PipelineStage.IDEAS.value] = "failed"

            # Record provenance after ideation
            if provenance_chain and result.provenance:
                try:
                    for link in result.provenance:
                        provenance_chain.add_record(
                            content=getattr(link, "content_hash", ""),
                            source_type=SourceType.SYNTHESIS,
                            source_id=getattr(link, "id", "pipeline"),
                        )
                except (AttributeError, TypeError, ValueError):
                    pass

            # Stage 1.5: Principles extraction (opt-in)
            if cfg.enable_principles and "principles" in cfg.stages_to_run:
                sr = await self._run_principles_extraction(
                    pipeline_id,
                    result.stage_results[0].output if result.stage_results else None,
                    cfg,
                )
                result.stage_results.append(sr)
                if sr.status == "completed" and sr.output:
                    result.principles_canvas = sr.output.get("canvas")
                    result.stage_status[PipelineStage.PRINCIPLES.value] = "complete"
                elif sr.status == "failed":
                    result.stage_status[PipelineStage.PRINCIPLES.value] = "failed"

            # Stage 2: Goal extraction
            if "goals" in cfg.stages_to_run:
                debate_output = result.stage_results[0].output if result.stage_results else None
                sr = await self._run_goal_extraction(pipeline_id, debate_output, cfg)
                result.stage_results.append(sr)
                if sr.status == "completed" and sr.output:
                    goal_graph = sr.output.get("goal_graph")
                    if goal_graph:
                        result.goal_graph = goal_graph
                        if goal_graph.transition:
                            result.transitions.append(goal_graph.transition)
                        result.provenance.extend(goal_graph.provenance)
                        # Emit node-level events for extracted goals
                        for goal in goal_graph.goals:
                            self._emit(
                                cfg,
                                "pipeline_node_added",
                                {
                                    "stage": "goals",
                                    "node_id": goal.id,
                                    "node_type": getattr(goal.goal_type, "value", "goal"),
                                    "label": goal.title,
                                },
                            )
                    # Mark goals already completed in workspace
                    if workspace_ctx and workspace_ctx.has_context and goal_graph:
                        try:
                            from aragora.pipeline.workspace_bridge import (
                                WorkspacePipelineBridge,
                            )

                            ws_bridge = WorkspacePipelineBridge()
                            marked = await ws_bridge.mark_completed_goals(goal_graph, workspace_ctx)
                            if marked:
                                logger.info(
                                    "Marked %d goals as already done from workspace",
                                    marked,
                                )
                        except (ImportError, RuntimeError, TypeError, AttributeError) as exc:
                            logger.debug("Workspace goal marking unavailable: %s", exc)

                    result.stage_status[PipelineStage.GOALS.value] = "complete"
                elif sr.status == "failed":
                    result.stage_status[PipelineStage.GOALS.value] = "failed"

            # Record provenance after goals
            if provenance_chain and result.provenance:
                try:
                    for link in result.provenance:
                        provenance_chain.add_record(
                            content=getattr(link, "content_hash", ""),
                            source_type=SourceType.SYNTHESIS,
                            source_id=getattr(link, "id", "pipeline"),
                        )
                except (AttributeError, TypeError, ValueError):
                    pass

            # Stage 3: Workflow generation
            if "workflow" in cfg.stages_to_run:
                sr = await self._run_workflow_generation(pipeline_id, result.goal_graph, cfg)
                result.stage_results.append(sr)
                if sr.status == "completed" and sr.output:
                    result.final_workflow = sr.output.get("workflow")
                    # Also advance canvas pipeline
                    if result.goal_graph:
                        result = self._advance_to_actions(result)
                    result.stage_status[PipelineStage.ACTIONS.value] = "complete"
                    # Emit node-level events for action nodes
                    if result.actions_canvas and hasattr(result.actions_canvas, "nodes"):
                        nodes = result.actions_canvas.nodes
                        if isinstance(nodes, dict):
                            nodes = nodes.values()
                        for node in nodes:
                            self._emit(
                                cfg,
                                "pipeline_node_added",
                                {
                                    "stage": "actions",
                                    "node_id": getattr(node, "id", ""),
                                    "node_type": getattr(node, "data", {}).get("step_type", "task"),
                                    "label": getattr(node, "label", ""),
                                },
                            )

                    gate_passed, gate_summary = self._evaluate_plan_quality_gate(
                        result=result,
                        objective=input_text,
                        cfg=cfg,
                    )
                    if gate_summary is not None:
                        result.plan_quality_report = gate_summary
                        result.metadata["plan_quality"] = gate_summary
                        gate_stage_status = "completed" if gate_passed else "failed"
                        result.stage_results.append(
                            StageResult(
                                stage_name="plan_quality",
                                status=gate_stage_status,
                                output=gate_summary,
                                error=None
                                if gate_passed
                                else "Plan quality gate did not meet thresholds",
                            )
                        )
                        if not gate_passed and cfg.plan_quality_fail_closed:
                            quality_gate_blocked = True
                            result.stage_status["plan_quality"] = "failed"
                            self._emit(
                                cfg,
                                "quality_gate_failed",
                                {
                                    "pipeline_id": pipeline_id,
                                    "quality_score_10": gate_summary.get("quality_score_10", 0.0),
                                    "practicality_score_10": gate_summary.get(
                                        "practicality_score_10", 0.0
                                    ),
                                },
                            )
                            logger.warning(
                                "Pipeline %s blocked by plan quality gate (score=%.2f, practicality=%.2f)",
                                pipeline_id,
                                float(gate_summary.get("quality_score_10", 0.0)),
                                float(gate_summary.get("practicality_score_10", 0.0)),
                            )
                        elif not gate_passed:
                            logger.warning(
                                "Pipeline %s plan quality below thresholds; continuing in fail-open mode",
                                pipeline_id,
                            )
                elif sr.status == "failed":
                    result.stage_status[PipelineStage.ACTIONS.value] = "failed"

            # Stage 4: Orchestration
            if "orchestration" in cfg.stages_to_run:
                if quality_gate_blocked:
                    result.stage_results.append(
                        StageResult(
                            stage_name="orchestration",
                            status="skipped",
                            error="Blocked by plan quality gate (fail-closed)",
                        )
                    )
                    result.stage_status[PipelineStage.ORCHESTRATION.value] = "failed"
                elif cfg.dry_run:
                    sr = StageResult(stage_name="orchestration", status="skipped")
                    result.stage_results.append(sr)
                else:
                    sr = await self._run_orchestration(
                        pipeline_id,
                        result.final_workflow,
                        result.goal_graph,
                        cfg,
                    )
                    result.stage_results.append(sr)
                    if sr.status == "completed" and sr.output:
                        result.orchestration_result = sr.output.get("orchestration")
                        if result.actions_canvas:
                            result = self._advance_to_orchestration(result)
                        result.stage_status[PipelineStage.ORCHESTRATION.value] = "complete"

            # Generate receipt (skip in dry_run mode)
            if cfg.enable_receipts and not cfg.dry_run:
                result.receipt = self._generate_receipt(result)
                # Verify provenance chain integrity
                if provenance_chain:
                    try:
                        chain_valid = provenance_chain.verify_chain()
                        if result.receipt is None:
                            result.receipt = {}
                        result.receipt["provenance_chain_valid"] = chain_valid
                    except (AttributeError, TypeError, ValueError):
                        pass

            # Feed pipeline metrics back to MetaLearner
            if cfg.enable_meta_tuning:
                try:
                    from aragora.knowledge.bridges import KnowledgeBridgeHub
                    from aragora.knowledge.mound import get_knowledge_mound

                    _mound = get_knowledge_mound()
                    if not _mound:
                        raise ImportError("Knowledge Mound not available")
                    hub = KnowledgeBridgeHub(_mound)
                    await hub.store_pipeline_run(  # type: ignore[attr-defined]
                        pipeline_id=pipeline_id,
                        topic=getattr(result, "topic", "pipeline"),
                        duration=result.duration,
                        stages_completed=sum(
                            1 for s in result.stage_status.values() if s == "complete"
                        ),
                    )
                except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                    logger.debug("MetaLearner feedback failed: %s", exc)

            # Auto-persist to KnowledgeMound
            if cfg.enable_km_persistence and not cfg.dry_run:
                try:
                    from aragora.pipeline.km_bridge import PipelineKMBridge

                    km_bridge = PipelineKMBridge()
                    if km_bridge.available:
                        stored = km_bridge.store_pipeline_result(result)
                        if stored:
                            logger.info(
                                "Pipeline %s: results persisted to KnowledgeMound",
                                pipeline_id,
                            )
                        else:
                            logger.warning(
                                "Pipeline %s: KM persistence returned False",
                                pipeline_id,
                            )
                except ImportError:
                    logger.debug("KM persistence skipped: PipelineKMBridge not available")
                except (RuntimeError, ValueError, OSError) as exc:
                    logger.warning("Pipeline %s: KM persistence failed: %s", pipeline_id, exc)

            # Record outcome for cross-session learning
            self._record_pipeline_outcome(result)

            result.duration = time.monotonic() - start_time
            self._emit(
                cfg,
                "completed",
                {
                    "pipeline_id": pipeline_id,
                    "duration": result.duration,
                    "receipt": result.receipt,
                },
            )
            _spectate("pipeline.completed", f"pipeline_id={pipeline_id}")

        except BaseException as exc:
            result.duration = time.monotonic() - start_time
            import asyncio

            is_cancelled = isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt))
            event_type = "cancelled" if is_cancelled else "failed"
            error_label = "Pipeline cancelled" if is_cancelled else "Pipeline execution failed"

            logger.warning("Pipeline %s %s: %s", pipeline_id, event_type, exc)
            self._emit(
                cfg,
                event_type,
                {
                    "pipeline_id": pipeline_id,
                    "error": error_label,
                },
            )
            _spectate(f"pipeline.{event_type}", f"pipeline_id={pipeline_id}")
            # Record outcome so MetaPlanner can learn from failures/cancellations
            self._record_pipeline_outcome(result)

            # Re-raise cancellation so callers can handle it; swallow others
            if is_cancelled:
                raise

        return result

    async def _run_ideation(
        self,
        pipeline_id: str,
        input_text: str,
        cfg: PipelineConfig,
    ) -> StageResult:
        """Stage 1: Run debate or extract raw ideas."""
        sr = StageResult(stage_name="ideation", status="running")
        start = time.monotonic()
        self._emit(cfg, "stage_started", {"stage": "ideation"})
        _spectate("pipeline.stage_started", "stage=ideation")

        # Pre-initialize locals to survive exception paths
        canvas = None
        debate_data: dict[str, Any] = {}
        explanation_summary = None

        try:
            try:
                from aragora.debate.orchestrator import Arena
                from aragora.debate.models import DebateProtocol, Environment

                env = Environment(task=input_text)
                protocol = DebateProtocol(rounds=cfg.debate_rounds)
                # Apply DeliberationTemplate defaults if provided
                if cfg.template:
                    getattr(cfg.template, "default_agents", None)
                    consensus = getattr(cfg.template, "consensus_threshold", None)
                    max_rounds = getattr(cfg.template, "max_rounds", None)
                    if consensus is not None:
                        protocol = DebateProtocol(
                            rounds=max_rounds or cfg.debate_rounds,
                            min_consensus=consensus,
                        )
                arena = Arena(env, [], protocol)
                debate_result = await arena.run()
                # Generate explanation from debate result
                explanation_summary = None
                try:
                    from aragora.explainability.builder import ExplanationBuilder

                    explanation = ExplanationBuilder().build(debate_result)
                    explanation_summary = {
                        "conclusion": getattr(explanation, "conclusion", ""),
                        "confidence": getattr(explanation, "confidence", 0.0),
                        "evidence_count": len(getattr(explanation, "evidence", [])),
                        "vote_pivots": getattr(explanation, "vote_pivots", []),
                        "counterfactuals": getattr(explanation, "counterfactuals", []),
                    }
                except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                    logger.debug("ExplanationBuilder unavailable: %s", exc)
                debate_data = {
                    "debate_result": debate_result,
                    "nodes": getattr(debate_result, "argument_graph", {}).get("nodes", []),
                }
                canvas = debate_to_ideas_canvas(
                    debate_data,
                    canvas_name="Ideas from Debate",
                )
            except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                logger.debug("Debate ideation unavailable, using text extraction: %s", exc)
                # Fallback: extract ideas from raw text
                ideas = [s.strip() for s in input_text.split(".") if s.strip()]
                if not ideas:
                    ideas = [input_text]
                goal_graph = self._goal_extractor.extract_from_raw_ideas(ideas)
                debate_data = {"raw_ideas": ideas, "goal_graph_preview": goal_graph}

                from aragora.canvas.models import Canvas as CanvasModel

                canvas = CanvasModel(
                    id=f"ideas-{uuid.uuid4().hex[:8]}",
                    name="Ideas from Text",
                    metadata={"stage": PipelineStage.IDEAS.value, "source": "text"},
                )

            # Optional: use FractalOrchestrator for recursive sub-debates
            if cfg.enable_fractal:
                try:
                    from aragora.genesis.fractal import FractalOrchestrator

                    fractal = FractalOrchestrator(max_depth=2)
                    fractal_result = await fractal.run(task=input_text, agents=[])
                    # Map sub-debates to additional canvas nodes
                    sub_debates = getattr(fractal_result, "sub_debates", [])
                    for i, sub in enumerate(sub_debates):
                        debate_data.setdefault("fractal_nodes", []).append(
                            {
                                "id": f"fractal-{i}",
                                "content": getattr(sub, "summary", str(sub)[:200]),
                                "depth": getattr(sub, "depth", 1),
                            }
                        )
                except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                    logger.debug("FractalOrchestrator unavailable: %s", exc)

            sr.output = {"canvas": canvas, "explanation": explanation_summary, **debate_data}
            sr.status = "completed"
            sr.duration = time.monotonic() - start
            self._emit(
                cfg,
                "stage_completed",
                {
                    "stage": "ideation",
                    "summary": {"source": "debate" if "debate_result" in debate_data else "text"},
                },
            )
            _spectate("pipeline.stage_completed", "stage=ideation")
        except (
            ImportError,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
            KeyError,
            ConnectionError,
            TimeoutError,
        ) as exc:
            sr.status = "failed"
            sr.error = "Ideation stage failed"
            sr.duration = time.monotonic() - start
            logger.warning("Ideation failed: %s", exc)
            self._emit(
                cfg,
                "stage_completed",
                {"stage": "ideation", "status": "failed", "error": "Ideation stage failed"},
            )
            _spectate("pipeline.stage_failed", "stage=ideation")

        return sr

    async def _run_principles_extraction(
        self,
        pipeline_id: str,
        ideas_output: dict[str, Any] | None,
        cfg: PipelineConfig,
    ) -> StageResult:
        """Stage 1.5: Extract principles/values from ideas canvas."""
        sr = StageResult(stage_name="principles", status="running")
        start = time.monotonic()
        self._emit(cfg, "stage_started", {"stage": "principles"})
        _spectate("pipeline.stage_started", "stage=principles")

        try:
            canvas = None
            if ideas_output and ideas_output.get("canvas"):
                src_canvas = ideas_output["canvas"]
                canvas_data = src_canvas.to_dict() if hasattr(src_canvas, "to_dict") else {}
            else:
                canvas_data = {}

            if canvas_data:
                canvas = ideas_to_principles_canvas(canvas_data)

            sr.output = {"canvas": canvas}
            sr.status = "completed"
            sr.duration = time.monotonic() - start
            self._emit(
                cfg,
                "stage_completed",
                {
                    "stage": "principles",
                    "summary": {
                        "principle_count": len(canvas.nodes) if canvas else 0,
                    },
                },
            )
            _spectate("pipeline.stage_completed", "stage=principles")
        except (
            ImportError,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
            KeyError,
            ConnectionError,
            TimeoutError,
        ) as exc:
            sr.status = "failed"
            sr.error = "Principles extraction failed"
            sr.duration = time.monotonic() - start
            logger.warning("Principles extraction failed: %s", exc)
            self._emit(
                cfg,
                "stage_completed",
                {
                    "stage": "principles",
                    "status": "failed",
                    "error": "Principles extraction failed",
                },
            )
            _spectate("pipeline.stage_failed", "stage=principles")

        return sr

    async def _run_goal_extraction(
        self,
        pipeline_id: str,
        debate_output: dict[str, Any] | None,
        cfg: PipelineConfig,
    ) -> StageResult:
        """Stage 2: Extract goals from debate analysis."""
        sr = StageResult(stage_name="goals", status="running")
        start = time.monotonic()
        self._emit(cfg, "stage_started", {"stage": "goals"})
        _spectate("pipeline.stage_started", "stage=goals")

        try:
            goal_graph = None

            # If we have debate data with argument nodes, use debate analysis
            if debate_output and debate_output.get("nodes"):
                cartographer_data = {
                    "nodes": debate_output["nodes"],
                    "edges": debate_output.get("edges", []),
                }

                # Build BeliefNetwork from debate nodes/edges for centrality scoring
                belief_result = None
                try:
                    from aragora.reasoning.belief import BeliefNetwork, RelationType

                    bn = BeliefNetwork()
                    for node in debate_output["nodes"]:
                        node_id = node.get("id", "")
                        statement = node.get("label", node.get("content", ""))
                        author = node.get("author", node.get("agent", "unknown"))
                        confidence = node.get("weight", node.get("confidence", 0.5))
                        if node_id and statement:
                            bn.add_claim(
                                node_id,
                                statement,
                                author,
                                initial_confidence=float(confidence),
                            )

                    _EDGE_TO_RELATION = {
                        "supports": RelationType.SUPPORTS,
                        "support": RelationType.SUPPORTS,
                        "contradicts": RelationType.CONTRADICTS,
                        "refutes": RelationType.CONTRADICTS,
                        "refines": RelationType.REFINES,
                        "modifies": RelationType.REFINES,
                    }
                    for edge in debate_output.get("edges", []):
                        src = edge.get("source", edge.get("source_id", ""))
                        tgt = edge.get("target", edge.get("target_id", ""))
                        rel = edge.get("type", edge.get("relation", "supports")).lower()
                        relation = _EDGE_TO_RELATION.get(rel, RelationType.SUPPORTS)
                        strength = float(edge.get("weight", edge.get("strength", 1.0)))
                        if src and tgt:
                            bn.add_factor(src, tgt, relation, strength=strength)

                    if bn.nodes:  # Only propagate if we added claims
                        belief_result = bn.propagate()
                        logger.debug(
                            "BeliefNetwork propagated: converged=%s, iterations=%d",
                            belief_result.converged,
                            belief_result.iterations,
                        )
                except (ImportError, RuntimeError, ValueError) as exc:
                    logger.warning("BeliefNetwork integration skipped: %s", exc)

                goal_graph = self._goal_extractor.extract_from_debate_analysis(
                    cartographer_data,
                    belief_result=belief_result,
                    config=cfg.goal_extraction_config,
                )
            elif debate_output and debate_output.get("goal_graph_preview"):
                # Already extracted via raw ideas
                goal_graph = debate_output["goal_graph_preview"]
            elif debate_output and debate_output.get("canvas"):
                # Use canvas data for structural extraction
                canvas = debate_output["canvas"]
                canvas_data = canvas.to_dict() if hasattr(canvas, "to_dict") else {}
                goal_graph = self._goal_extractor.extract_from_ideas(canvas_data)
            else:
                goal_graph = GoalGraph(id=f"goals-{uuid.uuid4().hex[:8]}")

            # SMART scoring and conflict detection
            if goal_graph and goal_graph.goals:
                # Detect conflicts
                try:
                    conflicts = self._goal_extractor.detect_goal_conflicts(goal_graph)
                    if conflicts:
                        goal_graph.metadata["conflicts"] = conflicts
                except (TypeError, ValueError, KeyError):
                    logger.debug("Conflict detection skipped during goal extraction")

                # SMART score each goal
                for goal in goal_graph.goals:
                    try:
                        smart_scores = self._goal_extractor.score_smart(goal)
                        goal.metadata["smart_scores"] = smart_scores
                        overall = smart_scores.get("overall", 0.5)
                        if overall >= 0.7:
                            goal.priority = "high"
                        elif overall < 0.4:
                            goal.priority = "low"
                    except (TypeError, ValueError, KeyError):
                        logger.debug("SMART scoring skipped for goal %s", goal.id)

                # Query KM for precedents
                try:
                    from aragora.pipeline.km_bridge import PipelineKMBridge

                    bridge = PipelineKMBridge()
                    if bridge.available:
                        precedents = bridge.query_similar_goals(goal_graph)
                        bridge.enrich_with_precedents(goal_graph, precedents)
                except (ImportError, RuntimeError, ValueError, TypeError) as exc:
                    logger.debug("KM precedent query unavailable: %s", exc)

                # Query Receipt/Outcome/Debate adapters for decision precedents
                try:
                    from aragora.pipeline.km_bridge import PipelineKMBridge as _KMBridge

                    adapter_bridge = _KMBridge()
                    adapter_bridge.enrich_goals_with_adapter_precedents(goal_graph)
                except (ImportError, RuntimeError, ValueError, TypeError) as exc:
                    logger.debug("Adapter precedent enrichment unavailable: %s", exc)

                # Cross-cycle learning: query past Nomic cycles for similar objectives
                try:
                    from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                        NomicCycleAdapter,
                    )

                    adapter = NomicCycleAdapter()
                    objective = " | ".join(g.title for g in goal_graph.goals[:5])
                    # NomicCycleAdapter.find_similar_cycles is async; use sync wrapper
                    import asyncio

                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None

                    if loop and loop.is_running():
                        # Already in async context — schedule directly
                        similar_cycles = await adapter.find_similar_cycles(
                            objective,
                            limit=3,
                        )
                    else:
                        similar_cycles = asyncio.run(
                            adapter.find_similar_cycles(objective, limit=3)
                        )

                    if similar_cycles:
                        recommendations: list[str] = []
                        past_failures: list[str] = []
                        for cycle in similar_cycles:
                            recommendations.extend(getattr(cycle, "recommendations", []))
                            past_failures.extend(getattr(cycle, "what_failed", []))
                        goal_graph.metadata["cross_cycle_learning"] = {
                            "similar_cycles": len(similar_cycles),
                            "recommendations": recommendations[:10],
                            "past_failures": past_failures[:10],
                        }
                        # Boost confidence of goals aligned with past successes
                        for goal in goal_graph.goals:
                            for cycle in similar_cycles:
                                if getattr(cycle, "success_rate", 0) > 0.7:
                                    for tip in getattr(cycle, "what_worked", []):
                                        if any(
                                            w in goal.title.lower() for w in tip.lower().split()[:3]
                                        ):
                                            goal.confidence = min(1.0, goal.confidence + 0.05)
                                            break
                        logger.debug(
                            "Cross-cycle learning: %d similar cycles found",
                            len(similar_cycles),
                        )
                except (ImportError, RuntimeError, ValueError) as exc:
                    logger.debug("Cross-cycle learning skipped: %s", exc)

            # Emit individual goals
            if goal_graph:
                for goal in goal_graph.goals:
                    self._emit(cfg, "goal_extracted", {"goal": goal.to_dict()})

            sr.output = {"goal_graph": goal_graph}
            sr.status = "completed"
            sr.duration = time.monotonic() - start
            self._emit(
                cfg,
                "stage_completed",
                {
                    "stage": "goals",
                    "summary": {"goal_count": len(goal_graph.goals) if goal_graph else 0},
                },
            )
            _spectate("pipeline.stage_completed", "stage=goals")
        except (
            ImportError,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
            KeyError,
            ConnectionError,
            TimeoutError,
        ) as exc:
            sr.status = "failed"
            sr.error = "Goal extraction failed"
            sr.duration = time.monotonic() - start
            logger.warning("Goal extraction failed: %s", exc)
            self._emit(
                cfg,
                "stage_completed",
                {"stage": "goals", "status": "failed", "error": "Goal extraction failed"},
            )
            _spectate("pipeline.stage_failed", "stage=goals")

        return sr

    async def _run_workflow_generation(
        self,
        pipeline_id: str,
        goal_graph: GoalGraph | None,
        cfg: PipelineConfig,
    ) -> StageResult:
        """Stage 3: Generate workflow from goals."""
        sr = StageResult(stage_name="workflow", status="running")
        start = time.monotonic()
        self._emit(cfg, "stage_started", {"stage": "workflow"})
        _spectate("pipeline.stage_started", "stage=actions")

        try:
            workflow: dict[str, Any] | None = None

            if goal_graph and goal_graph.goals:
                # Try NLWorkflowBuilder
                try:
                    from aragora.workflow.nl_builder import NLWorkflowBuilder

                    builder = NLWorkflowBuilder()
                    goal_texts = [g.title for g in goal_graph.goals]
                    nl_input = ". ".join(goal_texts)

                    if cfg.workflow_mode == "quick":
                        nl_result = builder.build_quick(nl_input)
                    else:
                        nl_result = await builder.build(nl_input)

                    workflow = (
                        nl_result.to_dict()
                        if hasattr(nl_result, "to_dict")
                        else {"steps": [], "name": "generated"}
                    )
                except (ImportError, RuntimeError, ValueError, TypeError) as exc:
                    logger.debug("NLWorkflowBuilder unavailable, using fallback: %s", exc)
                    # Fallback: use internal goal-to-workflow conversion
                    workflow = self._goals_to_workflow(goal_graph)

                self._emit(cfg, "workflow_generated", {"workflow": workflow})
            else:
                workflow = {"steps": [], "name": "empty"}

            sr.output = {"workflow": workflow}
            sr.status = "completed"
            sr.duration = time.monotonic() - start
            self._emit(
                cfg,
                "stage_completed",
                {
                    "stage": "workflow",
                    "summary": {"step_count": len(workflow.get("steps", []))},
                },
            )
            _spectate("pipeline.stage_completed", "stage=actions")
        except (
            ImportError,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
            KeyError,
            ConnectionError,
            TimeoutError,
        ) as exc:
            sr.status = "failed"
            sr.error = "Workflow generation failed"
            sr.duration = time.monotonic() - start
            logger.warning("Workflow generation failed: %s", exc)
            self._emit(
                cfg,
                "stage_completed",
                {
                    "stage": "workflow",
                    "status": "failed",
                    "error": "Workflow generation failed",
                },
            )
            _spectate("pipeline.stage_failed", "stage=workflow")

        return sr

    async def _run_orchestration(
        self,
        pipeline_id: str,
        workflow: dict[str, Any] | None,
        goal_graph: GoalGraph | None,
        cfg: PipelineConfig,
    ) -> StageResult:
        """Stage 4: Run orchestration on workflow.

        Builds an execution plan from the workflow/goal_graph, then executes
        each task using DebugLoop (with graceful fallback). Emits node-level
        events for real-time frontend updates.
        """
        sr = StageResult(stage_name="orchestration", status="running")
        start = time.monotonic()
        self._emit(cfg, "stage_started", {"stage": "orchestration"})
        _spectate("pipeline.stage_started", "stage=orchestration")

        try:
            execution_plan = self._build_execution_plan(workflow, goal_graph)

            if not execution_plan.get("tasks"):
                sr.output = {"orchestration": {"status": "skipped", "reason": "no tasks"}}
                sr.status = "completed"
                sr.duration = time.monotonic() - start
                return sr

            # Create Bead objects for task lifecycle tracking if enabled
            bead_manager = None
            if cfg.enable_beads:
                try:
                    from aragora.workspace.manager import WorkspaceManager

                    ws_mgr = WorkspaceManager()
                    rig = await ws_mgr.create_rig(f"pipeline-{pipeline_id}")
                    bead_specs = [
                        {"name": t["name"], "description": t.get("description", "")}
                        for t in execution_plan["tasks"]
                        if t["type"] != "human_gate"
                    ]
                    rig_id = rig.id if hasattr(rig, "id") else str(rig)
                    convoy = await ws_mgr.create_convoy(rig_id, bead_specs=bead_specs)
                    bead_manager = {"convoy": convoy, "rig": rig, "ws_mgr": ws_mgr}

                    # Use topological order from bead dependencies
                    convoy_id = convoy.id if hasattr(convoy, "id") else str(convoy)
                    ready = await ws_mgr.get_ready_beads(convoy_id)
                    if ready:
                        logger.info("Bead order: %d ready of %d total", len(ready), len(bead_specs))
                except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                    logger.debug("Bead lifecycle unavailable: %s", exc)
                    bead_manager = None

            results: list[dict[str, Any]] = []
            for task in execution_plan["tasks"]:
                if task["type"] == "human_gate":
                    results.append(
                        {
                            "task_id": task["id"],
                            "status": "awaiting_approval",
                            "name": task["name"],
                        }
                    )
                    self._emit(
                        cfg,
                        "pipeline_node_added",
                        {
                            "stage": "orchestration",
                            "node_id": task["id"],
                            "node_type": "human_gate",
                            "label": task["name"],
                        },
                    )
                    continue

                self._emit(
                    cfg,
                    "pipeline_agent_started",
                    {
                        "task_id": task["id"],
                        "name": task["name"],
                    },
                )

                task_result = await self._execute_task(task, cfg)
                results.append(task_result)

                # Update bead lifecycle
                if bead_manager:
                    try:
                        ws_mgr = bead_manager["ws_mgr"]  # type: ignore[assignment]
                        if task_result["status"] == "completed":
                            await ws_mgr.complete_bead(task["id"])
                        else:
                            await ws_mgr.fail_bead(
                                task["id"], error=task_result.get("error", "failed")
                            )
                    except (AttributeError, KeyError, TypeError, RuntimeError):
                        pass

                self._emit(
                    cfg,
                    "pipeline_agent_completed",
                    {
                        "task_id": task["id"],
                        "status": task_result["status"],
                    },
                )
                self._emit(
                    cfg,
                    "pipeline_node_added",
                    {
                        "stage": "orchestration",
                        "node_id": task["id"],
                        "node_type": "agent_task",
                        "label": task["name"],
                    },
                )

            completed = sum(1 for r in results if r["status"] == "completed")
            total = len(results)

            # Finalize convoy lifecycle if beads were used
            if bead_manager and completed > 0:
                try:
                    ws_mgr = bead_manager["ws_mgr"]  # type: ignore[assignment]
                    convoy_id = (
                        bead_manager["convoy"].id
                        if hasattr(bead_manager["convoy"], "id")
                        else str(bead_manager["convoy"])
                    )
                    merge_result = {"completed": completed, "failed": total - completed}
                    await ws_mgr.complete_convoy(convoy_id, merge_result)
                    logger.info("convoy_completed convoy_id=%s tasks=%d", convoy_id, completed)
                except (AttributeError, KeyError, TypeError, RuntimeError):
                    pass

            orch_result: dict[str, Any] = {
                "status": "executed",
                "tasks_completed": completed,
                "tasks_total": total,
                "results": results,
            }

            sr.output = {"orchestration": orch_result}
            sr.status = "completed"
            sr.duration = time.monotonic() - start
            self._emit(
                cfg,
                "stage_completed",
                {
                    "stage": "orchestration",
                    "summary": orch_result,
                },
            )
            _spectate("pipeline.stage_completed", "stage=orchestration")
        except (
            ImportError,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
            KeyError,
            ConnectionError,
            TimeoutError,
        ) as exc:
            sr.status = "failed"
            sr.error = "Orchestration failed"
            sr.duration = time.monotonic() - start
            logger.warning("Orchestration failed: %s", exc)
            self._emit(
                cfg,
                "stage_completed",
                {
                    "stage": "orchestration",
                    "status": "failed",
                    "error": "Orchestration failed",
                },
            )
            _spectate("pipeline.stage_failed", "stage=orchestration")

        return sr

    def _build_execution_plan(
        self,
        workflow: dict[str, Any] | None,
        goal_graph: GoalGraph | None,
    ) -> dict[str, Any]:
        """Build a flat task list from workflow steps or goal graph nodes.

        Extracts tasks from the workflow (preferred) or falls back to the
        goal graph. Each task has an id, name, description, type, and
        optional test_scope.
        """
        tasks: list[dict[str, Any]] = []
        if workflow and workflow.get("steps"):
            for step in workflow["steps"]:
                tasks.append(
                    {
                        "id": step["id"],
                        "name": step["name"],
                        "description": step.get("description", ""),
                        "type": (
                            "human_gate"
                            if step.get("step_type") == "human_checkpoint"
                            else "agent_task"
                        ),
                        "test_scope": step.get("config", {}).get("test_scope", []),
                    }
                )
        elif goal_graph and goal_graph.goals:
            for goal in goal_graph.goals:
                tasks.append(
                    {
                        "id": goal.id,
                        "name": goal.title,
                        "description": goal.description,
                        "type": "agent_task",
                        "test_scope": [],
                    }
                )
        return {"tasks": tasks}

    async def _execute_task(
        self,
        task: dict[str, Any],
        cfg: PipelineConfig,
    ) -> dict[str, Any]:
        """Execute a single task using the best available backend.

        Tries backends in order of preference:
        1. HardenedOrchestrator (if ``use_hardened_orchestrator`` enabled)
        2. Arena mini-debate (if ``use_arena_orchestration`` enabled)
        3. DebugLoop (default)
        4. Falls back to ``planned`` status when no engine is available.
        """
        instruction = f"Implement: {task['name']}\n\n{task.get('description', '')}"

        # Pipeline KM feedback: query historical performance to enrich instruction
        try:
            from aragora.knowledge.mound.adapters.pipeline_adapter import get_pipeline_adapter

            pipeline_adapter = get_pipeline_adapter()
            task_type = task.get("type", task.get("track", "general"))

            # Get precedents for this task type
            precedents = await pipeline_adapter.query_precedents(task_type, limit=3)
            if precedents:
                lessons = []
                for p in precedents:
                    outcome = p.get("outcome", "")
                    if outcome:
                        lessons.append(f"- {outcome}")
                if lessons:
                    instruction += "\n\nHistorical insights from similar tasks:\n" + "\n".join(
                        lessons
                    )

            # Get agent performance data to suggest best agents
            agent_perf = await pipeline_adapter.get_agent_performance(
                agent_type=task.get("assigned_agent", ""),
                domain=task_type,
            )
            if agent_perf and agent_perf.get("success_rate", 0) > 0:
                rate = agent_perf["success_rate"]
                instruction += f"\n\nAgent historical success rate for this domain: {rate:.0%}"
        except (ImportError, AttributeError, TypeError, RuntimeError, ValueError) as exc:
            logger.debug("Pipeline KM feedback skipped: %s", exc)

        # Mode enforcement: resolve operational mode for orchestration stage
        mode_name = cfg.mode_map.get("orchestration")
        if mode_name:
            try:
                from aragora.modes.base import ModeRegistry

                mode = ModeRegistry.get(mode_name)
                if mode is not None:
                    mode_prompt = mode.get_system_prompt()
                    if mode_prompt:
                        instruction = f"{mode_prompt}\n\n{instruction}"
            except (ImportError, AttributeError, TypeError, RuntimeError) as exc:
                logger.debug("Mode enforcement skipped for orchestration: %s", exc)

        # Append preferred agents from introspection data
        preferred = getattr(cfg, "_introspection_data", None)
        if preferred:
            try:
                ranked = sorted(
                    preferred.items(),
                    key=lambda x: x[1].get("average_influence", 0),
                    reverse=True,
                )
                top_agents = [name for name, _ in ranked[:3]]
                if top_agents:
                    instruction += f"\n\nPreferred agents: {', '.join(top_agents)}"
            except (AttributeError, TypeError, ValueError):
                pass

        # Backend 1: HardenedOrchestrator (worktree isolation + gauntlet)
        if cfg.use_hardened_orchestrator:
            try:
                from aragora.nomic.hardened_orchestrator import HardenedOrchestrator

                orchestrator = HardenedOrchestrator(
                    use_worktree_isolation=True,
                    enable_gauntlet_validation=True,
                    generate_receipts=cfg.enable_receipts,
                )
                result = await orchestrator.execute_goal(instruction)
                return {
                    "task_id": task["id"],
                    "name": task["name"],
                    "status": "completed" if getattr(result, "success", False) else "failed",
                    "output": result.to_dict() if hasattr(result, "to_dict") else {},
                    "backend": "hardened_orchestrator",
                }
            except ImportError:
                logger.debug("HardenedOrchestrator not available, trying next backend")
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("HardenedOrchestrator failed: %s", exc)

        # Backend 2: Arena mini-debate for consensus-driven execution
        if cfg.use_arena_orchestration:
            try:
                from aragora.debate.orchestrator import Arena
                from aragora.debate import DebateProtocol
                from aragora.core_types import Environment

                from aragora.agents.cli_agents import get_default_agents

                env = Environment(task=instruction)
                protocol = DebateProtocol(rounds=2)
                agents = get_default_agents()[:3]
                arena = Arena(env, agents, protocol)
                debate_result = await arena.run()
                arena_rationale = getattr(debate_result, "summary", str(debate_result))
                return {
                    "task_id": task["id"],
                    "name": task["name"],
                    "status": "completed",
                    "output": {
                        "arena_rationale": arena_rationale[:500],
                        "consensus_reached": getattr(debate_result, "consensus_reached", False),
                    },
                    "backend": "arena",
                }
            except ImportError:
                logger.debug("Arena not available, falling back to next backend")
            except (
                RuntimeError,
                ValueError,
                OSError,
                TypeError,
                AttributeError,
                ConnectionError,
                TimeoutError,
            ) as exc:
                logger.warning("Arena mini-debate failed, falling back: %s", exc)

        # Backend 3: DebugLoop (default)
        try:
            from aragora.nomic.debug_loop import DebugLoop, DebugLoopConfig

            loop_cfg = DebugLoopConfig(max_retries=2)
            loop = DebugLoop(loop_cfg)
            debug_result = await loop.execute_with_retry(
                instruction=instruction,
                worktree_path=getattr(cfg, "worktree_path", None)
                or os.path.join(tempfile.gettempdir(), "aragora-worktree"),
                test_scope=task.get("test_scope", []),
            )
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "completed" if debug_result.success else "failed",
                "output": debug_result.to_dict() if hasattr(debug_result, "to_dict") else {},
                "backend": "debug_loop",
            }
        except (ImportError, AttributeError):
            # DebugLoop not available — fall back to planned status
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "planned",
                "output": {"reason": "execution_engine_unavailable"},
            }
        except (
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
            KeyError,
            ConnectionError,
            TimeoutError,
        ) as exc:
            # Harness config errors, path validation, etc.
            # Individual task failures must not crash the entire stage.
            logger.warning("Task %s failed: %s", task["id"], exc)
            return {
                "task_id": task["id"],
                "name": task["name"],
                "status": "failed",
                "output": {"error": "Task execution failed"},
            }

    def _emit(self, cfg: PipelineConfig, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event via the configured callback."""
        if cfg.event_callback:
            try:
                cfg.event_callback(event_type, data)
            except (TypeError, ValueError, RuntimeError, OSError):
                pass  # Event callbacks must not crash the pipeline

        # Also emit to SpectatorStream if configured
        if cfg.spectator:
            try:
                cfg.spectator.emit(event_type, details=str(data))
            except (TypeError, ValueError, RuntimeError, OSError, AttributeError):
                pass  # SpectatorStream must not crash the pipeline

    @staticmethod
    def _emit_sync(
        callback: Any | None,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Emit an event via a standalone callback (for sync methods)."""
        if callback:
            try:
                callback(event_type, data)
            except (TypeError, ValueError, RuntimeError, OSError):
                pass  # Event callbacks must not crash the pipeline

    @staticmethod
    def _build_plan_quality_markdown(result: PipelineResult, objective: str) -> str:
        """Render a deterministic markdown artifact for plan-quality validation."""
        lines: list[str] = [
            "# Pipeline Plan",
            "",
            "## Objective",
            objective.strip() or "n/a",
            "",
            "## Ranked High-Level Tasks",
        ]

        goals = []
        if result.goal_graph is not None and getattr(result.goal_graph, "goals", None):
            goals = list(result.goal_graph.goals)[:10]
        if goals:
            for idx, goal in enumerate(goals, start=1):
                title = getattr(goal, "title", "") or getattr(goal, "description", "")
                if not title:
                    continue
                lines.append(f"{idx}. {str(title).strip()}")
        else:
            lines.append("- [missing] No goals extracted.")

        lines.extend(["", "## Suggested Subtasks"])
        action_nodes: list[Any] = []
        if result.actions_canvas is not None and hasattr(result.actions_canvas, "nodes"):
            nodes = result.actions_canvas.nodes
            if isinstance(nodes, dict):
                action_nodes = list(nodes.values())
            elif isinstance(nodes, list):
                action_nodes = nodes
        if action_nodes:
            for node in action_nodes[:12]:
                label = getattr(node, "label", "")
                if label:
                    lines.append(f"- {str(label).strip()}")
        else:
            lines.append("- [missing] No action steps generated.")

        lines.extend(["", "## Owner module / file paths"])
        file_paths: list[str] = []
        for goal in goals:
            goal_hints = getattr(goal, "file_hints", None)
            if isinstance(goal_hints, list):
                for hint in goal_hints:
                    if isinstance(hint, str) and hint:
                        file_paths.append(hint)
        for link in result.provenance[:20]:
            source_id = getattr(link, "source_id", "")
            if isinstance(source_id, str) and "/" in source_id:
                file_paths.append(source_id)
        deduped_paths: list[str] = []
        seen: set[str] = set()
        for path in file_paths:
            key = path.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped_paths.append(key)
        if deduped_paths:
            for path in deduped_paths[:10]:
                lines.append(f"- {path}")
        else:
            lines.append("- [missing] No concrete file ownership hints produced.")

        lines.extend(
            [
                "",
                "## Test Plan",
                "- Run targeted unit tests for changed modules.",
                "- Run integration tests for pipeline handoff behavior.",
                "",
                "## Rollback Plan",
                "- Trigger: quality gate regressions or execution errors exceed threshold.",
                "- Action: revert staged changes and replay previous approved plan.",
                "",
                "## Gate Criteria",
                "- quality_score_10 >= 6.0",
                "- practicality_score_10 >= 5.0",
                "- no unresolved critical defects",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _evaluate_plan_quality_gate(
        *,
        result: PipelineResult,
        objective: str,
        cfg: PipelineConfig,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Evaluate deterministic plan-quality gates.

        Returns (gate_passed, summary_dict). Summary is None when quality tooling
        is unavailable.
        """
        if (
            not cfg.plan_quality_contract_file
            and cfg.plan_quality_min_score <= 0
            and cfg.plan_quality_min_practicality <= 0
        ):
            return True, None

        try:
            from aragora.debate.output_quality import (
                OutputContract,
                load_output_contract_from_file,
                validate_output_against_contract,
            )
        except ImportError:
            logger.debug("plan_quality_gate skipped: output quality module unavailable")
            return True, None

        if cfg.plan_quality_contract_file:
            contract = load_output_contract_from_file(cfg.plan_quality_contract_file)
        else:
            contract = OutputContract(
                required_sections=[
                    "Ranked High-Level Tasks",
                    "Suggested Subtasks",
                    "Owner module / file paths",
                    "Test Plan",
                    "Rollback Plan",
                    "Gate Criteria",
                ],
                require_json_payload=False,
                require_gate_thresholds=True,
                require_rollback_triggers=True,
                require_owner_paths=False,
                require_repo_path_existence=False,
                require_practicality_checks=True,
            )

        markdown = IdeaToExecutionPipeline._build_plan_quality_markdown(result, objective)
        quality_report = validate_output_against_contract(markdown, contract)
        score = float(getattr(quality_report, "quality_score_10", 0.0) or 0.0)
        practicality = float(getattr(quality_report, "practicality_score_10", 0.0) or 0.0)
        defects = list(getattr(quality_report, "defects", []) or [])

        min_score = max(0.0, float(cfg.plan_quality_min_score or 0.0))
        min_practicality = max(0.0, float(cfg.plan_quality_min_practicality or 0.0))
        meets_numeric_thresholds = score >= min_score and practicality >= min_practicality
        gate_passed = meets_numeric_thresholds and quality_report.verdict == "good"
        summary = {
            "verdict": quality_report.verdict,
            "quality_score_10": score,
            "practicality_score_10": practicality,
            "gate_passed": gate_passed,
            "min_quality_score_10": min_score,
            "min_practicality_score_10": min_practicality,
            "fail_closed": bool(cfg.plan_quality_fail_closed),
            "contract_file": cfg.plan_quality_contract_file,
            "defects": defects,
        }
        return gate_passed, summary

    def _generate_receipt(self, result: PipelineResult) -> dict[str, Any] | None:
        """Generate a decision receipt for the completed pipeline.

        Collects participants from orchestration results, evidence from
        each stage, and builds a rich receipt. Falls back to a lightweight
        dict when the gauntlet receipt module is unavailable.
        """
        # Collect participants from orchestration result
        participants: list[str] = []
        if result.orchestration_result and isinstance(result.orchestration_result, dict):
            for task_result in result.orchestration_result.get("results", []):
                name = task_result.get("name", "unknown")
                if name not in participants:
                    participants.append(name)

        # Collect evidence from stage results
        evidence: list[dict[str, Any]] = []
        for sr in result.stage_results:
            evidence.append(
                {
                    "stage": sr.stage_name,
                    "status": sr.status,
                    "duration": sr.duration,
                }
            )

        # Collect precedent references from goal metadata for audit trail
        precedent_refs: list[dict[str, Any]] = []
        if result.goal_graph:
            for goal in result.goal_graph.goals:
                precs = goal.metadata.get("precedents", [])
                for p in precs:
                    precedent_refs.append(
                        {
                            "goal_id": goal.id,
                            "goal_title": goal.title,
                            "precedent_title": p.get("title", ""),
                            "precedent_outcome": p.get("outcome", "unknown"),
                            "similarity": p.get("similarity", 0.0),
                        }
                    )

        stages_completed = sum(1 for sr in result.stage_results if sr.status == "completed")

        try:
            from aragora.gauntlet.receipts import DecisionReceipt

            receipt = DecisionReceipt(
                decision_id=result.pipeline_id,
                decision_summary=(
                    f"Pipeline completed: {len(result.stage_results)} stages, "
                    f"{len(result.provenance)} provenance links"
                ),
                confidence=result.transitions[-1].confidence if result.transitions else 0.5,
                participants=participants,
                evidence=evidence,
            )
            receipt_dict = receipt.to_dict()
            if precedent_refs:
                receipt_dict["precedent_references"] = precedent_refs
            return receipt_dict
        except (ImportError, RuntimeError, ValueError, TypeError) as exc:
            logger.debug("Receipt generation fell back to dict: %s", exc)
            receipt_dict = {
                "pipeline_id": result.pipeline_id,
                "integrity_hash": result._compute_integrity_hash(),
                "stages_completed": stages_completed,
                "provenance_count": len(result.provenance),
                "participants": participants,
                "evidence": evidence,
            }
            if precedent_refs:
                receipt_dict["precedent_references"] = precedent_refs
            return receipt_dict

    def _record_pipeline_outcome(self, result: PipelineResult) -> None:
        """Record pipeline outcome for cross-session learning.

        Feeds stage completion data back through the MetaPlanner so future
        planning cycles can learn which kinds of pipeline runs succeed.
        """
        try:
            from aragora.nomic.meta_planner import MetaPlanner

            planner = MetaPlanner()
            stages = ["ideas", "goals", "actions", "orchestration"]
            goal_outcomes = []
            for stage in stages:
                status = result.stage_status.get(stage, "pending")
                goal_outcomes.append(
                    {
                        "track": "core",
                        "success": status == "complete",
                        "description": f"pipeline_stage_{stage}",
                    }
                )
            planner.record_outcome(
                goal_outcomes=goal_outcomes,
                objective=f"pipeline:{result.pipeline_id}",
            )
        except (ImportError, RuntimeError, ValueError, OSError) as exc:
            logger.debug("Pipeline outcome recording skipped: %s", exc)

    # =========================================================================
    # Stage transition methods (sync, for from_debate/from_ideas)
    # =========================================================================

    def _advance_to_principles(self, result: PipelineResult) -> PipelineResult:
        """Stage 1 → Stage 1.5: Extract principles/values from ideas."""
        if not result.ideas_canvas:
            logger.warning("Cannot advance to principles: no ideas canvas")
            return result

        canvas_data = result.ideas_canvas.to_dict()
        result.principles_canvas = ideas_to_principles_canvas(canvas_data)

        # Create provenance links from ideas to principles
        provenance: list[ProvenanceLink] = []
        if result.principles_canvas:
            for node_id, node in result.principles_canvas.nodes.items():
                src_idea_id = node.data.get("source_idea_id", "")
                if src_idea_id:
                    provenance.append(
                        ProvenanceLink(
                            source_node_id=src_idea_id,
                            source_stage=PipelineStage.IDEAS,
                            target_node_id=node_id,
                            target_stage=PipelineStage.PRINCIPLES,
                            content_hash=content_hash(node.label),
                            method="principle_extraction",
                        )
                    )

        result.provenance.extend(provenance)

        transition = StageTransition(
            id=f"trans-ideas-principles-{uuid.uuid4().hex[:8]}",
            from_stage=PipelineStage.IDEAS,
            to_stage=PipelineStage.PRINCIPLES,
            provenance=provenance,
            status="pending",
            confidence=0.7,
            ai_rationale=(
                f"Extracted {len(result.principles_canvas.nodes)} principle nodes "
                f"from {len(result.ideas_canvas.nodes)} ideas"
            ),
        )
        result.transitions.append(transition)
        result.stage_status[PipelineStage.PRINCIPLES.value] = "complete"

        logger.info(
            "Pipeline %s: Principles stage complete — %d principle nodes",
            result.pipeline_id,
            len(result.principles_canvas.nodes),
        )
        return result

    def _advance_to_goals(self, result: PipelineResult) -> PipelineResult:
        """Stage 1 (or 1.5) → Stage 2: Extract goals from ideas or principles."""
        if not result.ideas_canvas:
            logger.warning("Cannot advance to goals: no ideas canvas")
            return result

        # When principles are available, use them to inform goal extraction
        if result.principles_canvas:
            try:
                principles_data = result.principles_canvas.to_dict()
                ideas_data = result.ideas_canvas.to_dict()
                result.goal_graph = self._goal_extractor.extract_from_principles(
                    principles_data,
                    ideas_canvas_data=ideas_data,
                )
                if result.goal_graph and result.goal_graph.goals:
                    logger.info(
                        "Pipeline %s: Goals extracted from principles — %d goals",
                        result.pipeline_id,
                        len(result.goal_graph.goals),
                    )
            except (TypeError, ValueError, AttributeError) as exc:
                logger.debug("Principle-based goal extraction failed, falling back: %s", exc)
                # Fall through to standard extraction below
                result.goal_graph = None

            if result.goal_graph and result.goal_graph.goals:
                # Skip standard extraction, jump to post-processing
                return self._finalize_goals(result)

        canvas_data = result.ideas_canvas.to_dict()

        # Pre-cluster related ideas semantically
        try:
            canvas_data = self._goal_extractor.cluster_ideas_semantically(canvas_data)
        except (TypeError, ValueError, KeyError):
            logger.debug("Semantic clustering skipped, continuing with unclustered data")

        # Enrich goal extraction with past strategic findings
        strategic_hints: list[str] = []
        try:
            from aragora.nomic.strategic_memory import StrategicMemoryStore

            store = StrategicMemoryStore()
            past = store.get_latest(limit=2)
            if past:
                strategic_hints = [f.description for a in past for f in a.findings[:3]]
                if strategic_hints:
                    logger.debug("Pipeline enriched with %d strategic hints", len(strategic_hints))
        except (ImportError, RuntimeError, ValueError, OSError) as exc:
            logger.debug("Strategic hints enrichment skipped: %s", exc)

        result.goal_graph = self._goal_extractor.extract_from_ideas(canvas_data)

        return self._finalize_goals(result)

    def _finalize_goals(self, result: PipelineResult) -> PipelineResult:
        """Post-process goal graph: conflicts, SMART scoring, KM precedents."""
        if not result.goal_graph:
            return result

        # Detect conflicts between goals
        try:
            conflicts = self._goal_extractor.detect_goal_conflicts(result.goal_graph)
            if conflicts:
                result.goal_graph.metadata["conflicts"] = conflicts
        except (TypeError, ValueError, KeyError):
            logger.debug("Conflict detection skipped during stage advance")

        # SMART score each goal and adjust priority
        for goal in result.goal_graph.goals:
            try:
                smart_scores = self._goal_extractor.score_smart(goal)
                goal.metadata["smart_scores"] = smart_scores
                overall = smart_scores.get("overall", 0.5)
                if overall >= 0.7:
                    goal.priority = "high"
                elif overall < 0.4:
                    goal.priority = "low"
            except (TypeError, ValueError, KeyError):
                logger.debug("SMART scoring skipped for goal %s", goal.id)

        # Query KM for precedents and use them to influence goal confidence
        try:
            from aragora.pipeline.km_bridge import PipelineKMBridge

            bridge = PipelineKMBridge()
            if bridge.available:
                precedents = bridge.query_similar_goals(result.goal_graph)
                bridge.enrich_with_precedents(result.goal_graph, precedents)

                # Consume precedents: adjust goal confidence based on outcomes
                for goal in result.goal_graph.goals:
                    precs = goal.metadata.get("precedents", [])
                    if not precs:
                        continue
                    successes = sum(1 for p in precs if p.get("outcome") == "successful")
                    failures = sum(1 for p in precs if p.get("outcome") == "failed")
                    if successes > failures:
                        # Boost confidence for goals similar to past successes
                        goal.confidence = min(1.0, goal.confidence + 0.1)
                    elif failures > successes:
                        # Add warning for goals similar to past failures
                        goal.confidence = max(0.1, goal.confidence - 0.1)
                        goal.metadata.setdefault("warnings", []).append(
                            f"Similar past goals failed ({failures}/{len(precs)})"
                        )
        except (ImportError, RuntimeError, ValueError, TypeError) as exc:
            logger.debug("KM precedent query unavailable: %s", exc)

        # Query Receipt/Outcome/Debate adapters for decision precedents
        try:
            from aragora.pipeline.km_bridge import PipelineKMBridge as _KMBridge

            adapter_bridge = _KMBridge()
            adapter_bridge.enrich_goals_with_adapter_precedents(result.goal_graph)
        except (ImportError, RuntimeError, ValueError, TypeError) as exc:
            logger.debug("Adapter precedent enrichment unavailable: %s", exc)

        if result.goal_graph.transition:
            result.transitions.append(result.goal_graph.transition)
        result.provenance.extend(result.goal_graph.provenance)
        result.stage_status[PipelineStage.GOALS.value] = "complete"

        logger.info(
            "Pipeline %s: Stage 2 complete — %d goals extracted",
            result.pipeline_id,
            len(result.goal_graph.goals),
        )
        return result

    def _advance_to_actions(self, result: PipelineResult) -> PipelineResult:
        """Stage 2 → Stage 3: Generate workflow from goals."""
        if not result.goal_graph or not result.goal_graph.goals:
            logger.warning("Cannot advance to actions: no goals")
            return result

        # Convert goals into a WorkflowDefinition-like structure
        workflow_data = self._goals_to_workflow(result.goal_graph)

        # Create provenance links
        provenance: list[ProvenanceLink] = []
        for goal in result.goal_graph.goals:
            for step in workflow_data.get("steps", []):
                if step.get("source_goal_id") == goal.id:
                    provenance.append(
                        ProvenanceLink(
                            source_node_id=goal.id,
                            source_stage=PipelineStage.GOALS,
                            target_node_id=step["id"],
                            target_stage=PipelineStage.ACTIONS,
                            content_hash=content_hash(goal.title),
                            method="goal_decomposition",
                        )
                    )

        result.actions_canvas = workflow_to_actions_canvas(
            workflow_data,
            provenance=provenance,
            canvas_name="Action Plan",
        )
        result.provenance.extend(provenance)

        # Enrich action nodes with KM precedents (similar actions from past runs)
        try:
            from aragora.pipeline.km_bridge import PipelineKMBridge

            bridge = PipelineKMBridge()
            if bridge.available and result.actions_canvas:
                action_precedents = bridge.query_similar_actions(result.actions_canvas)
                for node_id, precs in action_precedents.items():
                    if precs and node_id in result.actions_canvas.nodes:
                        result.actions_canvas.nodes[node_id].data["precedents"] = precs
        except (ImportError, RuntimeError, TypeError) as exc:
            logger.debug("KM action precedent query unavailable: %s", exc)

        transition = StageTransition(
            id=f"trans-goals-actions-{uuid.uuid4().hex[:8]}",
            from_stage=PipelineStage.GOALS,
            to_stage=PipelineStage.ACTIONS,
            provenance=provenance,
            status="pending",
            confidence=0.7,
            ai_rationale=(
                f"Decomposed {len(result.goal_graph.goals)} goals into "
                f"{len(workflow_data.get('steps', []))} action steps"
            ),
        )
        result.transitions.append(transition)
        result.stage_status[PipelineStage.ACTIONS.value] = "complete"

        logger.info(
            "Pipeline %s: Stage 3 complete — %d action steps",
            result.pipeline_id,
            len(result.actions_canvas.nodes),
        )
        return result

    def _advance_to_orchestration(self, result: PipelineResult) -> PipelineResult:
        """Stage 3 → Stage 4: Create multi-agent execution plan."""
        if not result.actions_canvas:
            logger.warning("Cannot advance to orchestration: no actions canvas")
            return result

        # Build execution plan from action steps
        execution_plan = self._actions_to_execution_plan(result.actions_canvas)

        # Create provenance links
        provenance: list[ProvenanceLink] = []
        for task in execution_plan.get("tasks", []):
            source_id = task.get("source_action_id", "")
            if source_id:
                provenance.append(
                    ProvenanceLink(
                        source_node_id=source_id,
                        source_stage=PipelineStage.ACTIONS,
                        target_node_id=task["id"],
                        target_stage=PipelineStage.ORCHESTRATION,
                        content_hash=content_hash(task.get("name", "")),
                        method="agent_assignment",
                    )
                )

        result.orchestration_canvas = execution_to_orchestration_canvas(
            execution_plan,
            canvas_name="Orchestration Plan",
        )
        result.provenance.extend(provenance)

        transition = StageTransition(
            id=f"trans-actions-orch-{uuid.uuid4().hex[:8]}",
            from_stage=PipelineStage.ACTIONS,
            to_stage=PipelineStage.ORCHESTRATION,
            provenance=provenance,
            status="pending",
            confidence=0.6,
            ai_rationale=(
                f"Assigned {len(execution_plan.get('tasks', []))} tasks "
                f"across {len(execution_plan.get('agents', []))} agents"
            ),
        )
        result.transitions.append(transition)
        result.stage_status[PipelineStage.ORCHESTRATION.value] = "complete"

        logger.info(
            "Pipeline %s: Stage 4 complete — %d agents, %d tasks",
            result.pipeline_id,
            len(execution_plan.get("agents", [])),
            len(execution_plan.get("tasks", [])),
        )
        return result

    # =========================================================================
    # Universal graph integration
    # =========================================================================

    def _build_universal_graph(self, result: PipelineResult) -> None:
        """Build a UniversalGraph from completed pipeline stages."""
        if not self._use_universal:
            return
        try:
            from aragora.pipeline.adapters import (
                canvas_to_universal_graph,
                from_goal_node,
            )
            from aragora.pipeline.universal_node import UniversalGraph

            graph = UniversalGraph(
                id=f"ugraph-{result.pipeline_id}",
                name=f"Pipeline {result.pipeline_id}",
            )

            # Stage 1: Ideas
            if result.ideas_canvas:
                ideas_ug = canvas_to_universal_graph(result.ideas_canvas, PipelineStage.IDEAS)
                for node in ideas_ug.nodes.values():
                    graph.add_node(node)
                for edge in ideas_ug.edges.values():
                    graph.edges[edge.id] = edge

            # Stage 2: Goals
            if result.goal_graph:
                for goal in result.goal_graph.goals:
                    unode = from_goal_node(goal)
                    graph.add_node(unode)

            # Stage 3: Actions
            if result.actions_canvas:
                actions_ug = canvas_to_universal_graph(result.actions_canvas, PipelineStage.ACTIONS)
                for node in actions_ug.nodes.values():
                    graph.add_node(node)
                for edge in actions_ug.edges.values():
                    graph.edges[edge.id] = edge

            # Stage 4: Orchestration
            if result.orchestration_canvas:
                orch_ug = canvas_to_universal_graph(
                    result.orchestration_canvas, PipelineStage.ORCHESTRATION
                )
                for node in orch_ug.nodes.values():
                    graph.add_node(node)
                for edge in orch_ug.edges.values():
                    graph.edges[edge.id] = edge

            # Create cross-stage edges from parent_ids provenance
            try:
                from aragora.pipeline.universal_node import UniversalEdge

                for node in list(graph.nodes.values()):
                    for parent_id in node.parent_ids:
                        if parent_id in graph.nodes:
                            parent = graph.nodes[parent_id]
                            if parent.stage == node.stage:
                                continue  # Skip same-stage edges
                            edge_type = StageEdgeType.DERIVED_FROM
                            if (
                                parent.stage == PipelineStage.GOALS
                                and node.stage == PipelineStage.ACTIONS
                            ):
                                edge_type = StageEdgeType.IMPLEMENTS
                            elif (
                                parent.stage == PipelineStage.ACTIONS
                                and node.stage == PipelineStage.ORCHESTRATION
                            ):
                                edge_type = StageEdgeType.EXECUTES
                            edge_id = f"xstage-{parent_id[:8]}-{node.id[:8]}"
                            if edge_id not in graph.edges:
                                graph.edges[edge_id] = UniversalEdge(
                                    id=edge_id,
                                    source_id=parent_id,
                                    target_id=node.id,
                                    edge_type=edge_type,
                                    label=edge_type.value,
                                )
            except ImportError:
                logger.debug("UniversalEdge not available for cross-stage edges")

            graph.transitions = list(result.transitions)
            result.universal_graph = graph
        except (
            ImportError,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
            KeyError,
        ) as exc:
            logger.warning("Failed to build universal graph: %s", exc)

    # =========================================================================
    # Conversion helpers
    # =========================================================================

    def _goals_to_workflow(self, goal_graph: GoalGraph) -> dict[str, Any]:
        """Convert goals into a workflow definition.

        Each goal decomposes into multiple workflow steps based on type:
        - Goals → research + implement + test + review
        - Milestones → checkpoint + verification
        - Principles → define + validate
        - Strategies → research + design + implement
        - Metrics → instrument + baseline + monitor
        - Risks → assess + mitigate + verify
        """
        steps: list[dict[str, Any]] = []
        transitions: list[dict[str, Any]] = []

        # Decomposition templates by goal type
        decomposition = {
            "goal": [
                ("research", "task", "Research: {title}"),
                ("implement", "task", "Implement: {title}"),
                ("test", "verification", "Test: {title}"),
                ("review", "human_checkpoint", "Review: {title}"),
            ],
            "milestone": [
                ("checkpoint", "human_checkpoint", "Checkpoint: {title}"),
                ("verify", "verification", "Verify: {title}"),
            ],
            "principle": [
                ("define", "task", "Define: {title}"),
                ("validate", "verification", "Validate: {title}"),
            ],
            "strategy": [
                ("research", "task", "Research: {title}"),
                ("design", "task", "Design: {title}"),
                ("implement", "task", "Implement: {title}"),
            ],
            "metric": [
                ("instrument", "task", "Instrument: {title}"),
                ("baseline", "verification", "Baseline: {title}"),
                ("monitor", "task", "Monitor: {title}"),
            ],
            "risk": [
                ("assess", "task", "Assess: {title}"),
                ("mitigate", "task", "Mitigate: {title}"),
                ("verify", "verification", "Verify mitigation: {title}"),
            ],
        }

        for goal in goal_graph.goals:
            template = decomposition.get(
                goal.goal_type.value,
                [
                    ("execute", "task", "{title}"),
                ],
            )

            goal_step_ids: list[str] = []
            for phase, step_type, name_fmt in template:
                step_id = f"step-{goal.id}-{phase}"
                step = {
                    "id": step_id,
                    "name": name_fmt.format(title=goal.title),
                    "description": goal.description,
                    "step_type": step_type,
                    "source_goal_id": goal.id,
                    "phase": phase,
                    "config": {
                        "priority": goal.priority,
                        "measurable": goal.measurable,
                    },
                    "timeout_seconds": 3600,
                    "retries": 1,
                    "optional": goal.priority == "low",
                }
                steps.append(step)

                # Chain phases within a goal sequentially
                if goal_step_ids:
                    transitions.append(
                        {
                            "id": f"seq-{goal_step_ids[-1]}-{step_id}",
                            "from_step": goal_step_ids[-1],
                            "to_step": step_id,
                            "condition": "",
                            "label": "then",
                            "priority": 0,
                        }
                    )

                goal_step_ids.append(step_id)

            # Create transitions from goal dependencies (link last step of dep
            # to first step of this goal)
            for dep_goal_id in goal.dependencies:
                dep_steps = [s for s in steps if s.get("source_goal_id") == dep_goal_id]
                if dep_steps and goal_step_ids:
                    transitions.append(
                        {
                            "id": f"dep-{dep_goal_id}-{goal.id}",
                            "from_step": dep_steps[-1]["id"],
                            "to_step": goal_step_ids[0],
                            "condition": "",
                            "label": "after",
                            "priority": 0,
                        }
                    )

        # Chain independent goal groups sequentially (link last step of one
        # to first step of next, only for goals with no explicit dependencies)
        prev_last_step: str | None = None
        for goal in goal_graph.goals:
            g_steps = [s for s in steps if s.get("source_goal_id") == goal.id]
            if not g_steps:
                continue
            first_id = g_steps[0]["id"]
            last_id = g_steps[-1]["id"]
            has_dep = any(t["to_step"] == first_id for t in transitions)
            if not has_dep and prev_last_step:
                transitions.append(
                    {
                        "id": f"seq-{prev_last_step}-{first_id}",
                        "from_step": prev_last_step,
                        "to_step": first_id,
                        "condition": "",
                        "label": "then",
                        "priority": 0,
                    }
                )
            prev_last_step = last_id

        return {
            "id": f"wf-{goal_graph.id}",
            "name": "Goal Implementation Workflow",
            "steps": steps,
            "transitions": transitions,
            "entry_step": steps[0]["id"] if steps else None,
        }

    # Domain mapping for TeamSelector scoring: maps step types/phases to
    # domains understood by TeamSelector's DOMAIN_CAPABILITY_MAP.
    _STEP_TYPE_TO_DOMAIN: dict[str, str] = {
        "task": "implementation",
        "research": "research",
        "verification": "testing",
        "human_checkpoint": "review",
        "review": "review",
        "design": "architecture",
        "implement": "implementation",
        "test": "testing",
        "assess": "analysis",
        "mitigate": "implementation",
        "instrument": "infrastructure",
        "baseline": "testing",
        "monitor": "infrastructure",
        "define": "architecture",
        "validate": "testing",
        "execute": "implementation",
        "checkpoint": "review",
    }

    def _actions_to_execution_plan(self, actions_canvas: Canvas) -> dict[str, Any]:
        """Convert action canvas nodes into a multi-agent execution plan.

        Assigns tasks to specialized agents based on step phase and type,
        using Aragora's agent archetypes for heterogeneous model consensus.
        When available, uses ELO-ranked, calibration-aware TeamSelector for
        data-driven assignment instead of basic keyword matching.
        """
        # ------------------------------------------------------------------
        # Try to instantiate TeamSelector for calibration-aware scoring
        # ------------------------------------------------------------------
        team_selector = None
        try:
            from aragora.debate.team_selector import TeamSelector

            team_selector = TeamSelector()
        except (ImportError, RuntimeError, TypeError, ValueError):
            logger.debug("TeamSelector not available, using static agent map")

        # ------------------------------------------------------------------
        # Agent pool with diverse model providers for adversarial vetting
        # ------------------------------------------------------------------
        agents: list[dict[str, Any]] = [
            {
                "id": "agent-researcher",
                "name": "Researcher",
                "type": "anthropic-api",
                "model": "claude-opus-4",
                "capabilities": ["research", "analysis", "synthesis"],
            },
            {
                "id": "agent-designer",
                "name": "Designer",
                "type": "openai-api",
                "model": "gpt-4o",
                "capabilities": ["design", "architecture", "planning"],
            },
            {
                "id": "agent-implementer",
                "name": "Implementer",
                "type": "codex",
                "model": "codex",
                "capabilities": ["code", "implementation", "debugging"],
            },
            {
                "id": "agent-tester",
                "name": "Tester",
                "type": "anthropic-api",
                "model": "claude-opus-4",
                "capabilities": ["testing", "verification", "validation"],
            },
            {
                "id": "agent-reviewer",
                "name": "Reviewer",
                "type": "gemini",
                "model": "gemini",
                "capabilities": ["review", "critique", "quality"],
            },
            {
                "id": "agent-monitor",
                "name": "Monitor",
                "type": "mistral",
                "model": "mistral",
                "capabilities": ["monitoring", "metrics", "observability"],
            },
        ]

        # ------------------------------------------------------------------
        # Build lightweight agent proxies for TeamSelector scoring.
        # TeamSelector.select() requires Agent-like objects with at least
        # ``name``, ``model``, and ``agent_type`` attributes.
        # ------------------------------------------------------------------
        _agent_proxies: list[Any] = []
        _proxy_to_pool_id: dict[str, str] = {}  # proxy.name -> pool agent id
        if team_selector:
            try:
                from aragora.pipeline._agent_proxy import _AgentProxy  # noqa: F811

                for a in agents:
                    proxy = _AgentProxy(
                        name=a["name"],
                        model=a.get("model", "unknown"),
                        agent_type=a.get("type", "unknown"),
                    )
                    _agent_proxies.append(proxy)
                    _proxy_to_pool_id[a["name"]] = a["id"]
            except (ImportError, TypeError):
                # If proxy class isn't available, fall back to static map
                team_selector = None
                logger.debug("Agent proxy not available, falling back to static map")

        # ------------------------------------------------------------------
        # Pre-compute domain-sorted agent rankings via TeamSelector.
        # For each unique domain we call ``selector.select(...)`` once and
        # cache the ranked list.  This gives us ELO + calibration-aware
        # ordering per domain.
        # ------------------------------------------------------------------
        _domain_rankings: dict[str, list[Any]] = {}  # domain -> sorted proxy list
        _domain_reasoning: dict[str, dict[str, dict[str, float]]] = {}
        elo_used = False
        if team_selector and _agent_proxies:
            unique_domains = set(self._STEP_TYPE_TO_DOMAIN.values())
            for domain in unique_domains:
                try:
                    ranked = team_selector.select(
                        _agent_proxies,
                        domain=domain,
                        task=f"Pipeline stage: {domain}",
                    )
                    if ranked:
                        _domain_rankings[domain] = ranked
                        elo_used = True
                        # Capture per-agent scoring breakdown for transparency
                        reasoning = getattr(team_selector, "_last_selection_reasoning", {})
                        if reasoning:
                            _domain_reasoning[domain] = dict(reasoning)
                except (TypeError, AttributeError, ValueError, RuntimeError) as exc:
                    logger.debug("TeamSelector scoring failed for domain %s: %s", domain, exc)

        # ------------------------------------------------------------------
        # Static fallback: map step phases to best-fit agent id
        # ------------------------------------------------------------------
        phase_agent_map = {
            "research": "agent-researcher",
            "design": "agent-designer",
            "implement": "agent-implementer",
            "test": "agent-tester",
            "verify": "agent-tester",
            "review": "agent-reviewer",
            "checkpoint": "",  # human gate
            "define": "agent-researcher",
            "validate": "agent-tester",
            "assess": "agent-researcher",
            "mitigate": "agent-implementer",
            "instrument": "agent-implementer",
            "baseline": "agent-tester",
            "monitor": "agent-monitor",
            "execute": "agent-implementer",
        }

        tasks: list[dict[str, Any]] = []
        used_agents: set[str] = set()

        for node_id, node in actions_canvas.nodes.items():
            step_type = node.data.get("step_type", "task")
            phase = node.data.get("phase", "")

            # Determine task type first (human gates skip agent assignment)
            if step_type == "human_checkpoint":
                task_type = "human_gate"
            elif step_type == "verification":
                task_type = "verification"
            else:
                task_type = "agent_task"

            # ----------------------------------------------------------
            # Agent assignment: prefer TeamSelector-ranked agents, then
            # fall back to the static phase_agent_map.
            # ----------------------------------------------------------
            assigned = ""
            elo_score: float | None = None
            selection_rationale: str | None = None
            alternative_agents: list[dict[str, Any]] | None = None

            # Resolve the domain for this step/phase
            lookup_key = phase if phase else step_type
            domain = self._STEP_TYPE_TO_DOMAIN.get(lookup_key, "general")

            if task_type == "human_gate":
                assigned = ""
            elif _domain_rankings and domain in _domain_rankings:
                # --- TeamSelector path: use calibration-aware ranking ---
                ranked = _domain_rankings[domain]
                best = ranked[0]
                best_name = getattr(best, "name", str(best))
                assigned = _proxy_to_pool_id.get(best_name, best_name)

                # Extract score from reasoning breakdown if available
                reasoning_for_domain = _domain_reasoning.get(domain, {})
                best_breakdown = reasoning_for_domain.get(best_name, {})
                elo_score = best_breakdown.get("total") if best_breakdown else None
                if elo_score is None:
                    # Try elo component specifically
                    elo_score = best_breakdown.get("elo")

                if elo_score is not None:
                    selection_rationale = (
                        f"TeamSelector top-ranked for {domain} (score={elo_score:.4f})"
                    )
                else:
                    selection_rationale = f"TeamSelector top-ranked for {domain}"

                # Collect alternative agents (next 2 in ranking)
                if len(ranked) > 1:
                    alternative_agents = []
                    for alt in ranked[1:3]:
                        alt_name = getattr(alt, "name", str(alt))
                        alt_breakdown = reasoning_for_domain.get(alt_name, {})
                        alt_score = alt_breakdown.get("total")
                        alternative_agents.append(
                            {
                                "name": alt_name,
                                "score": alt_score,
                                "agentId": _proxy_to_pool_id.get(alt_name, alt_name),
                            }
                        )
            else:
                # --- Static fallback path ---
                if phase and phase in phase_agent_map:
                    assigned = phase_agent_map[phase]
                elif step_type == "verification":
                    assigned = "agent-tester"
                elif step_type == "task":
                    assigned = "agent-implementer"
                else:
                    assigned = "agent-researcher"

            if assigned:
                used_agents.add(assigned)

            # Find dependencies from canvas edges
            deps = [
                edge.source_id
                for edge in actions_canvas.edges.values()
                if edge.target_id == node_id
            ]

            task_dict: dict[str, Any] = {
                "id": f"exec-{node_id}",
                "name": node.label,
                "type": task_type,
                "assigned_agent": assigned,
                "depends_on": [f"exec-{d}" for d in deps],
                "source_action_id": node_id,
            }
            if elo_score is not None:
                task_dict["elo_score"] = elo_score
            if selection_rationale is not None:
                task_dict["selection_rationale"] = selection_rationale
            if alternative_agents:
                task_dict["alternative_agents"] = alternative_agents

            # Surface precedent context from KM so agents get historical hints
            precs = node.data.get("precedents", [])
            if precs:
                task_dict["precedent_hints"] = [
                    {
                        "title": p.get("title", ""),
                        "outcome": p.get("outcome", "unknown"),
                        "similarity": p.get("similarity", 0.0),
                    }
                    for p in precs[:3]
                ]

            tasks.append(task_dict)

        # Only include agents that are actually assigned tasks
        active_agents = [a for a in agents if a["id"] in used_agents]

        return {
            "agents": active_agents,
            "tasks": tasks,
            "elo_used": elo_used,
        }


def canvas_to_workflow(result: PipelineResult) -> WorkflowDefinition:
    """Convert a PipelineResult into an executable WorkflowDefinition.

    Reads goal nodes from ``result.goal_graph`` and edges from
    ``result.actions_canvas`` (when available) to build a DAG of
    workflow task steps compatible with the WorkflowEngine.

    Goal dependencies become ``next_steps`` links and TransitionRules
    so the engine respects execution ordering.

    Args:
        result: A populated PipelineResult (at minimum with a goal_graph).

    Returns:
        A WorkflowDefinition ready for ``WorkflowEngine.execute()``.
    """
    from aragora.workflow.types import (
        StepDefinition,
        TransitionRule,
        WorkflowDefinition,
    )

    goals = result.goal_graph.goals if result.goal_graph else []

    if not goals:
        return WorkflowDefinition(
            id=f"wf-{result.pipeline_id}",
            name=f"Workflow from pipeline {result.pipeline_id}",
            description="Auto-generated from canvas pipeline (empty)",
            steps=[],
            transitions=[],
            metadata={"source_pipeline_id": result.pipeline_id},
        )

    # Build a set of valid goal IDs for dependency filtering
    goal_ids = {g.id for g in goals}

    steps: list[StepDefinition] = []
    transitions: list[TransitionRule] = []

    for goal in goals:
        # Filter dependencies to only reference goals that exist in this graph
        valid_deps = [d for d in goal.dependencies if d in goal_ids]

        step = StepDefinition(
            id=goal.id,
            name=goal.title,
            step_type="task",
            description=goal.description,
            config={
                "goal_type": goal.goal_type.value,
                "priority": goal.priority,
                "measurable": goal.measurable,
                "source_idea_ids": goal.source_idea_ids,
            },
            next_steps=[],  # Populated via transitions below
        )
        steps.append(step)

    # Build transitions from dependency edges.
    # If goal B depends on goal A, then A -> B (A must complete before B).
    for goal in goals:
        valid_deps = [d for d in goal.dependencies if d in goal_ids]
        for dep_id in valid_deps:
            tr = TransitionRule(
                id=f"tr-{dep_id}-to-{goal.id}",
                from_step=dep_id,
                to_step=goal.id,
                condition="True",
                label=f"{dep_id} -> {goal.id}",
            )
            transitions.append(tr)

            # Also wire next_steps on the source step
            for s in steps:
                if s.id == dep_id and goal.id not in s.next_steps:
                    s.next_steps.append(goal.id)

    # Determine entry step: a goal with no dependencies is a root
    root_ids = [g.id for g in goals if not any(d in goal_ids for d in g.dependencies)]
    entry_step = root_ids[0] if root_ids else goals[0].id

    return WorkflowDefinition(
        id=f"wf-{result.pipeline_id}",
        name=f"Workflow from pipeline {result.pipeline_id}",
        description="Auto-generated from canvas pipeline goal graph",
        steps=steps,
        transitions=transitions,
        entry_step=entry_step,
        metadata={"source_pipeline_id": result.pipeline_id},
    )
