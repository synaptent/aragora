"""Pipeline CLI command -- idea-to-execution pipeline operations.

Runs the full four-stage pipeline:
  Stage 1 (Ideas) -> Stage 2 (Goals) -> Stage 3 (Actions) -> Stage 4 (Orchestration)

Also supports a self-improve subcommand that combines TaskDecomposer +
MetaPlanner + IdeaToExecutionPipeline for goal-driven self-improvement.

Usage:
    aragora pipeline run "Build rate limiter, Add caching"
    aragora pipeline run "Improve error handling" --dry-run
    aragora pipeline self-improve "Maximize utility for SMEs" --budget-limit 5
    aragora pipeline status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SIMILARITY_BACKEND_CACHE = None


def _pipeline_similarity_backend():
    """Lazy-initialize a module-level similarity backend for pipeline use."""
    global _SIMILARITY_BACKEND_CACHE
    if _SIMILARITY_BACKEND_CACHE is None:
        from aragora.debate.similarity.factory import get_backend

        _SIMILARITY_BACKEND_CACHE = get_backend(preferred="auto")
    return _SIMILARITY_BACKEND_CACHE


_GOAL_PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def _goal_priority_value(goal: Any) -> int:
    """Map goal priority text to sortable rank (lower is higher priority)."""
    priority = str(getattr(goal, "priority", "medium")).lower()
    return _GOAL_PRIORITY_ORDER.get(priority, _GOAL_PRIORITY_ORDER["medium"])


def _normalize_objective_text(value: str) -> str:
    """Normalize text for loose duplication checks."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _check_objective_fidelity(
    original_goal: str,
    objectives: list[str],
) -> list[float]:
    """Score how well each objective relates to the original goal.

    Uses LLM semantic assessment as primary method, falling back to
    word-overlap scoring when LLM is unavailable.

    Returns a list of scores in [0.0, 1.0], one per objective.
    """
    # Try LLM-based fidelity scoring first
    try:
        scores = _check_fidelity_llm(original_goal, objectives)
        if scores is not None:
            return scores
    except (ImportError, ValueError, TypeError, RuntimeError, OSError) as exc:
        logger.debug("LLM fidelity scoring unavailable, falling back to keywords: %s", exc)

    # Fallback: keyword-based Jaccard similarity
    return _check_fidelity_keywords(original_goal, objectives)


def _check_fidelity_llm(
    original_goal: str,
    objectives: list[str],
) -> list[float] | None:
    """Use LLM to score semantic alignment between goal and objectives."""
    import asyncio
    import json as _json

    try:
        from aragora.agents import create_agent
        from aragora.agents.base import AgentType
    except ImportError as exc:
        logger.debug("Agent modules not available for LLM fidelity scoring: %s", exc)
        return None

    agent = None
    for agent_type in ("anthropic-api", "openai-api", "deepseek"):
        try:
            agent = create_agent(AgentType(agent_type))  # type: ignore[arg-type]
            if agent is not None:
                break
        except (ImportError, ValueError, TypeError) as exc:
            logger.debug("Agent type %s unavailable: %s", agent_type, exc)
            continue

    if agent is None:
        return None

    obj_list = "\n".join(f"{i + 1}. {obj}" for i, obj in enumerate(objectives))
    prompt = (
        f"Rate how well each objective addresses the original goal.\n\n"
        f"Original goal: {original_goal}\n\n"
        f"Objectives:\n{obj_list}\n\n"
        f"Reply with ONLY a JSON array of scores from 0.0 to 1.0, "
        f"one per objective. Example: [0.9, 0.3, 0.7]"
    )

    try:
        response = asyncio.run(agent.generate(prompt))
        # Extract JSON array from response
        match = re.search(r"\[[\d.,\s]+\]", response)
        if match:
            scores = _json.loads(match.group())
            if len(scores) == len(objectives):
                return [max(0.0, min(1.0, float(s))) for s in scores]
    except (ValueError, TypeError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        logger.debug("LLM fidelity response parsing failed: %s", exc)

    return None


def _check_fidelity_keywords(
    original_goal: str,
    objectives: list[str],
) -> list[float]:
    """Fallback: score fidelity using Jaccard word overlap."""
    _STOP_WORDS = frozenset(
        "a an the and or but in on of to for is are was were be been "
        "being have has had do does did will would shall should may might "
        "can could with at by from as into through during before after "
        "above below between this that these those it its".split()
    )

    def _significant_words(text: str) -> set[str]:
        words = set(re.findall(r"[a-z][a-z_/.-]+", text.lower()))
        return words - _STOP_WORDS

    goal_words = _significant_words(original_goal)
    if not goal_words:
        return [1.0] * len(objectives)

    scores: list[float] = []
    for obj in objectives:
        obj_words = _significant_words(obj)
        if not obj_words:
            scores.append(0.0)
            continue
        intersection = goal_words & obj_words
        union = goal_words | obj_words
        scores.append(len(intersection) / len(union) if union else 0.0)

    return scores


def _extract_pipeline_objectives(
    pipeline_result: Any | None,
    max_goals: int,
) -> list[str]:
    """Extract ranked objective strings from an idea-to-execution PipelineResult."""
    if pipeline_result is None:
        return []

    goal_graph = getattr(pipeline_result, "goal_graph", None)
    goals = getattr(goal_graph, "goals", None)
    if not goals:
        return []

    ranked = sorted(
        goals,
        key=lambda g: (
            _goal_priority_value(g),
            -float(getattr(g, "confidence", 0.0) or 0.0),
            str(getattr(g, "title", "")),
        ),
    )

    objectives: list[str] = []
    for g in ranked[: max(1, max_goals)]:
        title = str(getattr(g, "title", "")).strip()
        description = str(getattr(g, "description", "")).strip()

        if title and description:
            normalized_title = _normalize_objective_text(title)
            normalized_description = _normalize_objective_text(description)
            if (
                normalized_title
                and normalized_description
                and (
                    normalized_title in normalized_description
                    or normalized_description in normalized_title
                    or _pipeline_similarity_backend().compute_similarity(
                        normalized_title, normalized_description
                    )
                    >= 0.7
                )
            ):
                objectives.append(description)
            else:
                objectives.append(f"{title}: {description}")
        elif description:
            objectives.append(description)
        elif title:
            objectives.append(title)

    return objectives


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _dogfood_pipeline_payload(pipeline_result: Any) -> dict[str, Any]:
    if hasattr(pipeline_result, "to_dict"):
        return pipeline_result.to_dict()
    if isinstance(pipeline_result, dict):
        return dict(pipeline_result)
    return {
        "pipeline_id": getattr(pipeline_result, "pipeline_id", None),
        "duration": getattr(pipeline_result, "duration", None),
        "metadata": dict(getattr(pipeline_result, "metadata", {}) or {}),
    }


def _dogfood_summary_text(summary: dict[str, Any]) -> str:
    lines = [
        "",
        "DOGFOOD HANDOFF",
        "-" * 60,
        f"Source kind:    {summary['source_kind']}",
        f"Source ref:     {summary['source_ref']}",
        f"Pipeline ID:    {summary['pipeline_id']}",
        f"Output dir:     {summary['output_dir']}",
        f"Manifest:       {summary['manifest_path']}",
        f"Objectives:     {len(summary['objectives'])}",
    ]
    assessment_id = summary.get("assessment_id")
    if assessment_id:
        lines.append(f"Assessment ID:  {assessment_id}")
    if summary["objectives"]:
        lines.append("")
        lines.append("Selected objectives:")
        for i, objective in enumerate(summary["objectives"], 1):
            lines.append(f"  {i}. {objective}")
    if summary.get("ralph_state_path"):
        lines.append("")
        lines.append(f"Ralph state:    {summary['ralph_state_path']}")
        lines.append(f"Ralph status:   {summary.get('ralph_status', 'unknown')}")
    lines.append("")
    return "\n".join(lines)


async def _run_pipeline_dogfood(args: argparse.Namespace) -> dict[str, Any]:
    from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline
    from aragora.swarm.campaign import CampaignPlanner, save_campaign_manifest

    source_file = getattr(args, "source_file", None)
    assessment_id = getattr(args, "assessment_id", None)
    latest_assessment = bool(getattr(args, "latest_assessment", False))
    save_assessment_flag = bool(getattr(args, "save_assessment", False))
    max_goals = max(1, int(getattr(args, "max_goals", 1)))

    if source_file and (assessment_id or latest_assessment):
        raise ValueError(
            "--source-file cannot be combined with --assessment-id or --latest-assessment"
        )

    assessment = None
    assessment_payload: dict[str, Any] | None = None

    if source_file:
        from aragora.pipeline.brain_dump_parser import BrainDumpParser

        source_path = Path(source_file).resolve()
        source_kind = "source_file"
        source_ref = str(source_path)
        enriched = BrainDumpParser().parse_enriched(source_path.read_text(encoding="utf-8"))
        if not getattr(enriched, "ideas", None):
            raise ValueError(f"No pipeline-ready ideas could be parsed from {source_path}")
        pipeline_result = IdeaToExecutionPipeline().from_ideas(
            list(enriched.ideas),
            auto_advance=True,
        )
    else:
        from aragora.nomic.canonical_assessment import (
            CanonicalAssessmentCompiler,
            load_assessment,
            load_latest_assessment,
            save_assessment,
        )

        if assessment_id:
            assessment = load_assessment(assessment_id)
            if assessment is None:
                raise ValueError(f"Assessment not found: {assessment_id}")
        elif latest_assessment:
            assessment = load_latest_assessment()
            if assessment is None:
                raise ValueError("No saved canonical assessment found")
        else:
            compiler = CanonicalAssessmentCompiler()
            assessment = await compiler.compile()
            if save_assessment_flag:
                save_assessment(assessment)

        source_kind = "assessment"
        source_ref = assessment.assessment_id
        assessment_payload = assessment.to_dict()
        pipeline_result = await IdeaToExecutionPipeline.from_assessment(assessment)

    objectives = _extract_pipeline_objectives(pipeline_result, max_goals=max_goals)
    if not objectives:
        raise ValueError("No dogfood objectives could be extracted from the pipeline result")

    pipeline_id = str(getattr(pipeline_result, "pipeline_id", "")).strip() or "dogfood-pipeline"
    output_dir_arg = getattr(args, "output_dir", None)
    output_dir = (
        Path(output_dir_arg).resolve()
        if output_dir_arg
        else (Path.cwd() / ".aragora" / "dogfood" / pipeline_id).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    planner = CampaignPlanner(
        repo_root=Path.cwd(),
        planner_model=getattr(args, "planner_model", "claude"),
        worker_model=getattr(args, "worker_model", "codex"),
        review_model=getattr(args, "review_model", "claude"),
        budget_limit_usd=float(getattr(args, "budget_limit", 10.0)),
        max_parallel_ready_projects=max(
            1,
            int(getattr(args, "max_parallel_ready_projects", 1)),
        ),
    )
    manifest = planner.plan_from_items(
        objectives,
        source_kind=source_kind,
        source_ref=source_ref,
    )
    manifest.budget_limit_usd = float(getattr(args, "budget_limit", manifest.budget_limit_usd))
    manifest.time_limit_hours = float(getattr(args, "time_limit_hours", manifest.time_limit_hours))
    manifest.max_parallel_ready_projects = max(
        1,
        int(
            getattr(
                args,
                "max_parallel_ready_projects",
                manifest.max_parallel_ready_projects,
            )
        ),
    )
    manifest.max_retries_per_project = max(
        0,
        int(
            getattr(
                args,
                "max_retries_per_project",
                manifest.max_retries_per_project,
            )
        ),
    )
    manifest.planning_findings.append(f"dogfood_pipeline_id={pipeline_id}")
    if assessment is not None:
        manifest.planning_findings.append(f"dogfood_assessment_id={assessment.assessment_id}")

    manifest_path = output_dir / "campaign_manifest.yaml"
    state_path = output_dir / "supervisor_state.yaml"
    save_campaign_manifest(manifest_path, manifest)

    _json_dump(output_dir / "pipeline_result.json", _dogfood_pipeline_payload(pipeline_result))
    _json_dump(output_dir / "objectives.json", {"objectives": objectives})
    _json_dump(output_dir / "manifest.json", manifest.to_dict())
    if assessment_payload is not None:
        _json_dump(output_dir / "assessment.json", assessment_payload)

    summary: dict[str, Any] = {
        "source_kind": source_kind,
        "source_ref": source_ref,
        "assessment_id": getattr(assessment, "assessment_id", None),
        "pipeline_id": pipeline_id,
        "output_dir": str(output_dir),
        "manifest_path": str(manifest_path),
        "state_path": str(state_path),
        "objectives": objectives,
        "project_count": len(manifest.projects),
    }

    if getattr(args, "start_ralph", False):
        from aragora.ralph.supervisor import RalphSupervisor

        supervisor = RalphSupervisor.start(
            manifest_path=manifest_path,
            state_path=state_path,
            repo_root=Path.cwd(),
            merge_policy=getattr(args, "merge_policy", "manual_review_required"),
            max_repair_attempts=max(0, int(getattr(args, "max_repair_attempts", 2))),
        )
        ralph_state = supervisor.status()
        summary["ralph_state_path"] = str(state_path)
        summary["ralph_status"] = ralph_state.get("status")
        summary["ralph_supervisor_id"] = ralph_state.get("supervisor_id")

    return summary


def _count_live_stages_completed(pipeline_result: Any) -> int:
    """Count completed stages from a live pipeline result."""
    stage_results = getattr(pipeline_result, "stage_results", None) or []
    return sum(1 for sr in stage_results if getattr(sr, "status", "") == "completed")


def _detect_provider_calls(pipeline_result: Any) -> bool:
    """Best-effort marker indicating whether live providers were likely used."""
    stage_results = getattr(pipeline_result, "stage_results", None) or []
    if not stage_results:
        return False

    for sr in stage_results:
        duration = float(getattr(sr, "duration", 0.0) or 0.0)
        if duration > 0.0:
            output = getattr(sr, "output", None)
            if isinstance(output, dict) and (
                "debate_result" in output or "workflow" in output or "orchestration" in output
            ):
                return True
            if getattr(sr, "stage_name", "") in {"ideation", "workflow", "orchestration"}:
                return True
    return False


def _run_self_improve_handoff(
    objectives: list[str],
    *,
    dry_run: bool,
    require_approval: bool,
    budget_limit: float | None,
    quick_mode: bool,
    max_parallel: int,
) -> None:
    """Run extracted pipeline objectives through the self-improvement engine."""
    try:
        from aragora.nomic.self_improve import SelfImproveConfig, SelfImprovePipeline
    except ImportError as exc:
        logger.debug("SelfImprovePipeline import failed: %s", exc)
        print("\nSelfImprovePipeline unavailable.")
        print('Install nomic dependencies or use: aragora self-improve "<objective>"')
        return

    default_budget = SelfImproveConfig().budget_limit_usd
    effective_budget = budget_limit if budget_limit is not None else default_budget

    for i, objective in enumerate(objectives, 1):
        print("-" * 60)
        print(f"SELF-IMPROVE OBJECTIVE {i}/{len(objectives)}")
        print("-" * 60)
        print(f"Objective: {objective}")
        print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
        print(f"Quick mode: {'ON' if quick_mode else 'OFF'}")
        print(f"Max parallel: {max_parallel}")
        print(f"Budget limit: ${effective_budget:.2f}")
        print()

        cfg = SelfImproveConfig(
            quick_mode=quick_mode,
            scan_mode=False,  # Pipeline already produced explicit objectives.
            max_goals=1,
            max_parallel=max_parallel,
            budget_limit_usd=effective_budget,
            require_approval=require_approval,
            autonomous=not require_approval,
            auto_mode=not require_approval,
        )
        runner = SelfImprovePipeline(config=cfg)

        if dry_run:
            plan = asyncio.run(runner.dry_run(objective=objective))
            goals_count = len(plan.get("goals", []))
            subtasks_count = len(plan.get("subtasks", []))
            print(f"Planned goals: {goals_count}")
            print(f"Planned subtasks: {subtasks_count}")
            if goals_count:
                print("Top goal:")
                top = plan["goals"][0]
                print(f"  - {top.get('description', top.get('goal', 'unknown'))}")
            print()
            continue

        result = asyncio.run(runner.run(objective=objective))
        print(f"Cycle: {result.cycle_id}")
        print(f"Subtasks: {result.subtasks_completed}/{result.subtasks_total} completed")
        print(f"Failed: {result.subtasks_failed}")
        print(f"Improvement score: {result.improvement_score:.3f}")
        print(f"Cost: ${result.total_cost_usd:.4f}")
        print(f"Duration: {result.duration_seconds:.1f}s")
        _err = getattr(result, "error", None)
        if _err:
            print(f"Error: {_err}")
        print()


def cmd_pipeline(args: argparse.Namespace) -> None:
    """Handle 'pipeline' command -- route to subcommand."""
    subcommand = getattr(args, "pipeline_action", None)
    if subcommand == "run":
        _cmd_pipeline_run(args)
    elif subcommand == "self-improve":
        _cmd_pipeline_self_improve(args)
    elif subcommand == "dogfood":
        _cmd_pipeline_dogfood(args)
    elif subcommand == "status":
        _cmd_pipeline_status(args)
    else:
        print("Usage: aragora pipeline {run,self-improve,dogfood,status}")
        print("Run 'aragora pipeline --help' for details.")


def _cmd_pipeline_run(args: argparse.Namespace) -> None:
    """Run the full idea-to-execution pipeline from raw ideas."""
    ideas_raw = args.ideas
    dry_run = args.dry_run
    require_approval = args.require_approval
    budget_limit = args.budget_limit

    # Split comma-separated ideas
    ideas = [i.strip() for i in ideas_raw.split(",") if i.strip()]
    if not ideas:
        print("\nError: No ideas provided. Pass comma-separated ideas.")
        print('  Example: aragora pipeline run "Build rate limiter, Add caching"')
        return

    print("\n" + "=" * 60)
    print("IDEA-TO-EXECUTION PIPELINE")
    print("=" * 60)
    print(f"\nIdeas ({len(ideas)}):")
    for i, idea in enumerate(ideas, 1):
        print(f"  {i}. {idea}")
    if dry_run:
        print("\nMode: DRY RUN (preview only)")
    if budget_limit:
        print(f"Budget limit: ${budget_limit:.2f}")
    if require_approval:
        print("Approval: Required at gates")
    print()

    if dry_run:
        _run_pipeline_dry_run(ideas)
    else:
        _run_pipeline_execute(ideas, require_approval, budget_limit)


def _run_pipeline_dry_run(ideas: list[str]) -> None:
    """Preview the pipeline stages without executing."""
    print("-" * 60)
    print("PIPELINE PREVIEW")
    print("-" * 60)

    try:
        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
        )

        _config = PipelineConfig(dry_run=True)  # reserved for async run()
        pipeline = IdeaToExecutionPipeline()
        result = pipeline.from_ideas(ideas)

        print(f"\nPipeline ID: {result.pipeline_id}")

        # Stage 1: Ideas
        if result.ideas_canvas:
            node_count = (
                len(result.ideas_canvas.nodes) if hasattr(result.ideas_canvas, "nodes") else 0
            )
            print(f"\nStage 1 - Ideas Canvas: {node_count} nodes")

        # Stage 2: Goals
        if result.goal_graph:
            goal_count = len(result.goal_graph.goals) if hasattr(result.goal_graph, "goals") else 0
            print(f"Stage 2 - Goal Graph: {goal_count} goals")
            if hasattr(result.goal_graph, "goals"):
                for g in result.goal_graph.goals[:5]:
                    title = getattr(g, "title", getattr(g, "description", str(g)))
                    print(f"  - {title}")

        # Stage results
        if result.stage_results:
            print("\nStage Results:")
            for sr in result.stage_results:
                print(f"  [{sr.status}] {sr.stage_name} ({sr.duration:.2f}s)")

        print(f"\nProvenance chain: {len(result.provenance)} links")

    except ImportError as exc:
        logger.debug("IdeaToExecutionPipeline import failed: %s", exc)
        print("\nIdeaToExecutionPipeline unavailable.")
        print("Install required dependencies or check aragora/pipeline/.")
        return

    print()
    print("To execute this pipeline:")
    ideas_str = ", ".join(ideas)
    print(f'  aragora pipeline run "{ideas_str}"')
    print()


def _run_pipeline_execute(
    ideas: list[str],
    require_approval: bool,
    budget_limit: float | None,
) -> None:
    """Execute the full pipeline."""
    try:
        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
        )

        _config = PipelineConfig(
            dry_run=False,
            enable_receipts=True,
        )  # reserved for async run()
        pipeline = IdeaToExecutionPipeline()

        print("-" * 60)
        print("EXECUTING PIPELINE")
        print("-" * 60)

        result = pipeline.from_ideas(ideas)

        print(f"\nPipeline ID: {result.pipeline_id}")
        print(f"Duration: {result.duration:.1f}s")

        if result.stage_results:
            print("\nStage Results:")
            for sr in result.stage_results:
                status_icon = "OK" if sr.status == "completed" else sr.status.upper()
                print(f"  [{status_icon}] {sr.stage_name} ({sr.duration:.2f}s)")
                if sr.error:
                    print(f"         Error: {sr.error}")

        if result.receipt:
            print(f"\nReceipt: {json.dumps(result.receipt, indent=2, default=str)[:200]}...")

        print()

    except ImportError as exc:
        logger.debug("IdeaToExecutionPipeline import failed: %s", exc)
        print("\nError: IdeaToExecutionPipeline unavailable.")
        print("Check that aragora/pipeline/ is properly installed.")

    except (OSError, RuntimeError, ValueError) as e:
        logger.debug("Pipeline execution failed: %s", e)
        print(f"\nPipeline failed: {e}")


def _cmd_pipeline_self_improve(args: argparse.Namespace) -> None:
    """Run self-improvement using TaskDecomposer + MetaPlanner + Pipeline."""
    goal = args.goal
    dry_run = args.dry_run
    require_approval = args.require_approval
    budget_limit = args.budget_limit
    execute = getattr(args, "execute", False)
    max_goals = max(1, int(getattr(args, "max_goals", 1)))
    quick_mode = bool(getattr(args, "quick_mode", False))
    max_parallel = max(1, int(getattr(args, "max_parallel", 4)))
    pipeline_mode = getattr(args, "pipeline_mode", "live")
    plan_quality_contract_file = getattr(args, "plan_quality_contract_file", None)
    plan_quality_min_score = max(
        0.0,
        float(getattr(args, "plan_quality_min_score", 6.0)),
    )
    plan_quality_min_practicality = max(
        0.0,
        float(getattr(args, "plan_quality_min_practicality", 5.0)),
    )
    fail_closed_requested = bool(getattr(args, "plan_quality_fail_closed", False))
    ci_or_dogfood = bool(os.environ.get("CI") or os.environ.get("ARAGORA_DOGFOOD_CI"))
    plan_quality_fail_closed = fail_closed_requested or ci_or_dogfood

    print("\n" + "=" * 60)
    print("PIPELINE SELF-IMPROVEMENT")
    print("=" * 60)
    print(f"\nGoal: {goal}")
    print(f"Pipeline mode: {pipeline_mode}")
    print(
        f"Plan quality gate: min_score={plan_quality_min_score:.1f} min_practicality={plan_quality_min_practicality:.1f}"
    )
    print(f"Plan quality policy: {'fail-closed' if plan_quality_fail_closed else 'warn-only'}")
    if dry_run:
        print("Mode: DRY RUN (preview only)")
    if budget_limit:
        print(f"Budget limit: ${budget_limit:.2f}")
    if require_approval:
        print("Approval: Required at gates")
    print(f"Handoff execute: {'ON' if execute else 'OFF (planning only)'}")
    if execute:
        print(f"Handoff max goals: {max_goals}")
        print(f"Handoff quick mode: {'ON' if quick_mode else 'OFF'}")
        print(f"Handoff max parallel: {max_parallel}")
    print()

    # Step 1: TaskDecomposer analyzes the goal
    print("-" * 60)
    print("STEP 1: TASK DECOMPOSITION")
    print("-" * 60)

    subtasks = []
    try:
        from aragora.nomic.task_decomposer import DecomposerConfig, TaskDecomposer

        decomposer = TaskDecomposer(config=DecomposerConfig(complexity_threshold=4))
        decomposition = decomposer.analyze(goal)

        print(
            f"\nComplexity: {decomposition.complexity_score}/10 ({decomposition.complexity_level})"
        )
        print(f"Subtasks: {len(decomposition.subtasks)}")

        for i, subtask in enumerate(decomposition.subtasks, 1):
            print(f"  {i}. {subtask.title}")
            print(f"     Complexity: {subtask.estimated_complexity}")
            if subtask.file_scope:
                files = ", ".join(subtask.file_scope[:3])
                extra = f" +{len(subtask.file_scope) - 3}" if len(subtask.file_scope) > 3 else ""
                print(f"     Files: {files}{extra}")

        subtasks = decomposition.subtasks
        print()

    except ImportError as exc:
        logger.debug("TaskDecomposer import failed: %s", exc)
        print("\nTaskDecomposer unavailable, skipping decomposition.")
        print()

    # Step 2: MetaPlanner debates improvement priorities
    print("-" * 60)
    print("STEP 2: META-PLANNING (priority debate)")
    print("-" * 60)

    prioritized_goals = []
    try:
        from aragora.nomic.meta_planner import MetaPlanner, MetaPlannerConfig

        planner = MetaPlanner(MetaPlannerConfig(quick_mode=quick_mode))
        prioritized_goals = asyncio.run(planner.prioritize_work(objective=goal))

        print(f"\nPrioritized goals ({len(prioritized_goals)}):")
        for pg in prioritized_goals:
            print(f"  {pg.priority}. [{pg.track.value}] {pg.description}")
            print(f"     Impact: {pg.estimated_impact}")
            if pg.rationale:
                print(f"     Rationale: {pg.rationale}")
        print()

    except ImportError as exc:
        logger.debug("MetaPlanner import failed: %s", exc)
        print("\nMetaPlanner unavailable, skipping priority debate.")
        print()

    # Step 3: IdeaToExecutionPipeline structures ideas into goals -> actions
    print("-" * 60)
    print("STEP 3: IDEA-TO-EXECUTION PIPELINE")
    print("-" * 60)

    # Build ideas from decomposition + prioritization
    ideas = []
    for pg in prioritized_goals:
        ideas.append(pg.description)
    if not ideas:
        # Fall back to subtask titles
        for st in subtasks:
            ideas.append(st.title)
    if not ideas:
        ideas = [goal]

    pipeline_result = None
    execution_path = "unknown"
    live_stages_completed = 0
    provider_calls_detected = False
    try:
        from aragora.pipeline.idea_to_execution import (
            IdeaToExecutionPipeline,
            PipelineConfig,
        )

        config = PipelineConfig(
            dry_run=dry_run,
            enable_receipts=not dry_run,
            plan_quality_contract_file=plan_quality_contract_file,
            plan_quality_fail_closed=plan_quality_fail_closed,
            plan_quality_min_score=plan_quality_min_score,
            plan_quality_min_practicality=plan_quality_min_practicality,
        )
        pipeline = IdeaToExecutionPipeline()
        ideas_text = "\n".join(ideas)

        result = None

        if pipeline_mode == "live":
            # Live mode: async pipeline with debate/API stages
            try:
                result = asyncio.run(pipeline.run(ideas_text, config=config))
                stage_results = getattr(result, "stage_results", None) or []
                if not stage_results:
                    raise RuntimeError("Live pipeline returned no stage results.")
                if all(float(getattr(sr, "duration", 0.0) or 0.0) == 0.0 for sr in stage_results):
                    raise RuntimeError("Live pipeline returned only 0.0s stages.")
                execution_path = "live"
            except (RuntimeError, OSError, ConnectionError) as exc:
                logger.debug("Live pipeline failed in strict mode: %s", exc)
                print(f"\n[WARN] Live pipeline failed ({exc}), no fallback in strict mode.")
                raise
        elif pipeline_mode == "hybrid":
            # Hybrid: try live, fall back to heuristic on failure
            try:
                result = asyncio.run(pipeline.run(ideas_text, config=config))
                stage_results = getattr(result, "stage_results", None) or []
                if not stage_results:
                    raise RuntimeError("Live pipeline returned no stage results.")
                if all(float(getattr(sr, "duration", 0.0) or 0.0) == 0.0 for sr in stage_results):
                    raise RuntimeError("Live pipeline returned only 0.0s stages.")
                execution_path = "live"
            except (RuntimeError, OSError, ConnectionError) as exc:
                logger.warning("Live pipeline unavailable (%s), falling back to heuristic", exc)
                print("\n[INFO] Live pipeline unavailable, using heuristic fallback.")
                result = pipeline.from_ideas(ideas)
                execution_path = "heuristic-fallback"
        else:
            # Heuristic mode: fast sync path (from_ideas)
            result = pipeline.from_ideas(ideas)
            execution_path = "heuristic"

        pipeline_result = result
        live_stages_completed = (
            _count_live_stages_completed(result)
            if execution_path in {"live", "heuristic-fallback"}
            else 0
        )
        provider_calls_detected = (
            _detect_provider_calls(result)
            if execution_path in {"live", "heuristic-fallback"}
            else False
        )
        if not hasattr(result, "metadata") or getattr(result, "metadata", None) is None:
            setattr(result, "metadata", {})
        result.metadata["execution_path"] = execution_path
        result.metadata["live_stages_completed"] = live_stages_completed
        result.metadata["provider_calls_detected"] = provider_calls_detected

        print(f"\nPipeline ID: {result.pipeline_id}")
        print(f"Execution path: {execution_path}")
        print(f"Live stages completed: {live_stages_completed}")
        print(f"Provider calls detected: {provider_calls_detected}")

        if result.goal_graph and hasattr(result.goal_graph, "goals"):
            print(f"Goals extracted: {len(result.goal_graph.goals)}")
            for g in result.goal_graph.goals[:5]:
                title = getattr(g, "title", getattr(g, "description", str(g)))
                print(f"  - {title}")

        if result.stage_results:
            print("\nStage Results:")
            for sr in result.stage_results:
                status_icon = "OK" if sr.status == "completed" else sr.status.upper()
                print(f"  [{status_icon}] {sr.stage_name} ({sr.duration:.2f}s)")
                # Flag 0.0s durations as suspicious (heuristic path indicator)
                if sr.duration == 0.0 and execution_path == "live":
                    print(
                        "         [WARN] 0.0s duration on live path — stage may not have executed"
                    )

        print(f"\nProvenance chain: {len(result.provenance)} links")
        print(f"Duration: {result.duration:.1f}s")

    except ImportError as exc:
        logger.debug("IdeaToExecutionPipeline import failed: %s", exc)
        print("\nIdeaToExecutionPipeline unavailable.")
        print("Showing decomposition results only.")

    print()
    objectives = _extract_pipeline_objectives(pipeline_result, max_goals=max_goals)
    if not objectives:
        objectives = [goal]

    # Step 3b: Objective-fidelity check — verify extracted objectives
    # still relate to the original goal (detect intent drift)
    fidelity_scores = _check_objective_fidelity(goal, objectives)
    drifted = [obj for obj, score in zip(objectives, fidelity_scores) if score < 0.1]
    if drifted:
        print(
            f"[FIDELITY WARNING] {len(drifted)}/{len(objectives)} objectives "
            f"may have drifted from original goal."
        )
        for obj in drifted:
            print(f"  - {obj[:80]}...")
        # Replace drifted objectives with original goal
        objectives = [
            obj if score >= 0.1 else goal for obj, score in zip(objectives, fidelity_scores)
        ]
        # Deduplicate
        seen: set[str] = set()
        deduped: list[str] = []
        for obj in objectives:
            if obj not in seen:
                seen.add(obj)
                deduped.append(obj)
        objectives = deduped
        print(
            f"  Replaced drifted objectives with original goal. "
            f"{len(objectives)} unique objectives remaining."
        )
        print()

    # Step 3c: Plan quality gate — validate pipeline output meets minimum quality
    quality_verdict = "skip"
    quality_score_10 = -1.0
    practicality_score_10 = -1.0
    quality_gate_failed = False
    if pipeline_result is not None:
        quality_meta = None
        result_metadata = getattr(pipeline_result, "metadata", None)
        if isinstance(result_metadata, dict):
            quality_meta = result_metadata.get("plan_quality")
        if quality_meta is None:
            quality_meta = getattr(pipeline_result, "plan_quality_report", None)

        if isinstance(quality_meta, dict):
            quality_score_10 = float(quality_meta.get("quality_score_10", -1.0) or -1.0)
            practicality_score_10 = float(quality_meta.get("practicality_score_10", -1.0) or -1.0)
            gate_passed = bool(quality_meta.get("gate_passed", False))
            quality_verdict = "pass" if gate_passed else "fail"
            quality_gate_failed = not gate_passed
            verdict_label = "PASS" if gate_passed else "FAIL"
            print(
                "[QUALITY GATE] {label} — quality={quality:.2f} practicality={practicality:.2f} "
                "thresholds=({min_q:.2f}, {min_p:.2f})".format(
                    label=verdict_label,
                    quality=quality_score_10,
                    practicality=practicality_score_10,
                    min_q=float(quality_meta.get("min_quality_score_10", plan_quality_min_score)),
                    min_p=float(
                        quality_meta.get(
                            "min_practicality_score_10",
                            plan_quality_min_practicality,
                        )
                    ),
                )
            )
        else:
            try:
                from aragora.debate.output_quality import (
                    OutputContract,
                    load_output_contract_from_file,
                    validate_output_against_contract,
                )

                plan_text_parts = [
                    "## Ranked High-Level Tasks",
                    *[f"- {obj}" for obj in objectives],
                    "",
                    "## Gate Criteria",
                    f"- quality_score_10 >= {plan_quality_min_score:.1f}",
                    f"- practicality_score_10 >= {plan_quality_min_practicality:.1f}",
                ]
                if pipeline_result.goal_graph and hasattr(pipeline_result.goal_graph, "goals"):
                    plan_text_parts.extend(["", "## Suggested Subtasks"])
                    for g in pipeline_result.goal_graph.goals[:10]:
                        title = getattr(g, "title", getattr(g, "description", str(g)))
                        plan_text_parts.append(f"- {title}")
                plan_text = "\n".join(plan_text_parts)

                if plan_quality_contract_file:
                    contract = load_output_contract_from_file(plan_quality_contract_file)
                else:
                    contract = OutputContract(
                        required_sections=[
                            "Ranked High-Level Tasks",
                            "Suggested Subtasks",
                            "Gate Criteria",
                        ],
                        require_json_payload=False,
                        require_gate_thresholds=True,
                        require_rollback_triggers=False,
                        require_owner_paths=False,
                        require_repo_path_existence=False,
                        require_practicality_checks=True,
                    )

                report = validate_output_against_contract(plan_text, contract)
                quality_score_10 = float(getattr(report, "quality_score_10", 0.0) or 0.0)
                practicality_score_10 = float(getattr(report, "practicality_score_10", 0.0) or 0.0)
                quality_gate_failed = (
                    getattr(report, "verdict", "needs_work") != "good"
                    or quality_score_10 < plan_quality_min_score
                    or practicality_score_10 < plan_quality_min_practicality
                )
                quality_verdict = "fail" if quality_gate_failed else "pass"
                print(
                    "[QUALITY GATE] {label} — quality={quality:.2f} practicality={practicality:.2f} "
                    "thresholds=({min_q:.2f}, {min_p:.2f})".format(
                        label="FAIL" if quality_gate_failed else "PASS",
                        quality=quality_score_10,
                        practicality=practicality_score_10,
                        min_q=plan_quality_min_score,
                        min_p=plan_quality_min_practicality,
                    )
                )
            except ImportError as exc:
                logger.debug("Output quality module unavailable, skipping quality gate: %s", exc)
            except (RuntimeError, ValueError, TypeError, AttributeError) as e:
                logger.warning("Quality gate check failed: %s", e)
                print(f"[QUALITY GATE] Check failed ({e}), skipping gate.")

    if quality_gate_failed and plan_quality_fail_closed:
        print("[QUALITY GATE] Blocking handoff because fail-closed policy is active.")
        return
    if quality_gate_failed and not plan_quality_fail_closed:
        print("[QUALITY GATE] Continuing in warn-only mode.")

    avg_fidelity = sum(fidelity_scores) / len(fidelity_scores) if fidelity_scores else -1.0
    print(
        "[self-improve-metrics] "
        f"execution_path={execution_path} "
        f"live_stages_completed={live_stages_completed} "
        f"provider_calls_detected={provider_calls_detected} "
        f"quality_verdict={quality_verdict} "
        f"quality_score_10={quality_score_10:.2f} "
        f"practicality_score_10={practicality_score_10:.2f} "
        f"avg_objective_fidelity={avg_fidelity:.2f}"
    )

    # Enqueue pipeline results to improvement queue for bidirectional handoff
    if pipeline_result is not None:
        try:
            from aragora.nomic.improvement_queue import (
                ImprovementSuggestion,
                get_improvement_queue,
            )

            queue = get_improvement_queue()
            file_hints: list[str] = []
            goal_graph = getattr(pipeline_result, "goal_graph", None)
            if goal_graph is not None and hasattr(goal_graph, "goals"):
                for g in goal_graph.goals[:20]:
                    hints = getattr(g, "file_hints", None)
                    if isinstance(hints, list):
                        for hint in hints:
                            if isinstance(hint, str) and hint:
                                file_hints.append(hint)

            for obj in objectives:
                suggestion = ImprovementSuggestion(
                    debate_id="",
                    task=obj,
                    suggestion=f"Pipeline-derived objective from goal: {goal}",
                    category="code_quality",
                    confidence=0.7,
                    source_system="pipeline",
                    source_id=getattr(pipeline_result, "pipeline_id", ""),
                    files=file_hints[:10],
                    gate_verdict=quality_verdict,
                    fidelity_score=avg_fidelity,
                )
                queue.enqueue(suggestion)
        except ImportError as exc:
            logger.debug("Suggestion queue unavailable, skipping enqueue: %s", exc)

    print("-" * 60)
    print("STEP 4: HANDOFF TO SELF-IMPROVEMENT ENGINE")
    print("-" * 60)
    print("\nSelected objectives:")
    for i, objective in enumerate(objectives, 1):
        print(f"  {i}. {objective}")
    print()

    if not execute:
        if dry_run:
            print("Handoff skipped in dry-run mode unless --execute is set.")
        else:
            print("Handoff not executed (planning mode).")
        print("\nTo execute the handoff:")
        cmd = f'aragora pipeline self-improve "{goal}" --execute'
        if budget_limit is not None:
            cmd += f" --budget-limit {budget_limit}"
        if require_approval:
            cmd += " --require-approval"
        cmd += f" --max-goals {max_goals}"
        if quick_mode:
            cmd += " --quick-mode"
        cmd += f" --max-parallel {max_parallel}"
        cmd += f" --pipeline-mode {pipeline_mode}"
        cmd += f" --plan-quality-min-score {plan_quality_min_score}"
        cmd += f" --plan-quality-min-practicality {plan_quality_min_practicality}"
        if plan_quality_contract_file:
            cmd += f" --plan-quality-contract-file {plan_quality_contract_file}"
        if plan_quality_fail_closed:
            cmd += " --plan-quality-fail-closed"
        print(f"  {cmd}")
        print("\nTo preview the handoff plan only:")
        print(f"  {cmd} --dry-run")
        print()
        return

    _run_self_improve_handoff(
        objectives,
        dry_run=dry_run,
        require_approval=require_approval,
        budget_limit=budget_limit,
        quick_mode=quick_mode,
        max_parallel=max_parallel,
    )


def _cmd_pipeline_status(args: argparse.Namespace) -> None:
    """Show active pipeline status."""
    print("\n" + "=" * 60)
    print("PIPELINE STATUS")
    print("=" * 60)

    try:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline = IdeaToExecutionPipeline()
        # Check if there's a status method or active pipelines
        active = getattr(pipeline, "active_pipelines", None)
        if active:
            print(f"\nActive pipelines: {len(active)}")
            for pid, info in active.items():
                print(f"  {pid}: {info}")
        else:
            print("\nNo active pipelines.")
            print("\nStart one with:")
            print('  aragora pipeline run "Build rate limiter, Add caching"')
            print('  aragora pipeline self-improve "Improve test coverage"')

    except ImportError as exc:
        logger.debug("Pipeline module import failed: %s", exc)
        print("\nPipeline module unavailable.")
        print("Check that aragora/pipeline/ is properly installed.")

    print()


def _cmd_pipeline_dogfood(args: argparse.Namespace) -> None:
    """Compile a dogfood handoff directory and optionally start Ralph."""
    summary = asyncio.run(_run_pipeline_dogfood(args))
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2, default=str))
        return
    print(_dogfood_summary_text(summary))


def add_pipeline_parser(subparsers) -> None:
    """Register the 'pipeline' subcommand parser."""
    pipeline_parser = subparsers.add_parser(
        "pipeline",
        help="Run idea-to-execution pipeline operations",
        description="""
Run the four-stage idea-to-execution pipeline:

  Stage 1 (Ideas) -> Stage 2 (Goals) -> Stage 3 (Actions) -> Stage 4 (Orchestration)

Subcommands:
  run           - Run the pipeline from raw ideas
  self-improve  - Combine TaskDecomposer + MetaPlanner + Pipeline for self-improvement
  dogfood       - Build a Ralph-ready handoff from assessment or roadmap input
  status        - Show active pipeline status

Examples:
  aragora pipeline run "Build rate limiter, Add caching"
  aragora pipeline run "Improve error handling" --dry-run
  aragora pipeline self-improve "Maximize utility for SMEs" --budget-limit 5
  aragora pipeline dogfood --latest-assessment --start-ralph
  aragora pipeline status
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    pipeline_sub = pipeline_parser.add_subparsers(dest="pipeline_action")

    # pipeline run
    run_parser = pipeline_sub.add_parser(
        "run",
        help="Run the full pipeline from ideas",
    )
    run_parser.add_argument(
        "ideas",
        help="Comma-separated ideas to process (e.g. 'Build rate limiter, Add caching')",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview pipeline stages without executing",
    )
    run_parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require human approval at stage gates",
    )
    run_parser.add_argument(
        "--budget-limit",
        type=float,
        default=None,
        help="Maximum budget in USD for pipeline execution",
    )

    # pipeline self-improve
    si_parser = pipeline_sub.add_parser(
        "self-improve",
        help="Run self-improvement via TaskDecomposer + MetaPlanner + Pipeline",
    )
    si_parser.add_argument(
        "goal",
        help="The improvement goal (e.g. 'Maximize utility for SMEs')",
    )
    si_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the plan without executing",
    )
    si_parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Require human approval at gates",
    )
    si_parser.add_argument(
        "--budget-limit",
        type=float,
        default=None,
        help="Maximum budget in USD",
    )
    si_parser.add_argument(
        "--execute",
        action="store_true",
        help="Run extracted pipeline goals through the self-improvement engine",
    )
    si_parser.add_argument(
        "--max-goals",
        type=int,
        default=1,
        help="Maximum number of extracted goals to hand off (default: 1)",
    )
    si_parser.add_argument(
        "--quick-mode",
        action="store_true",
        help="Use quick/heuristic planning mode in self-improvement handoff",
    )
    si_parser.add_argument(
        "--max-parallel",
        type=int,
        default=4,
        help="Maximum parallel subtasks during self-improvement handoff (default: 4)",
    )
    si_parser.add_argument(
        "--pipeline-mode",
        choices=["live", "hybrid", "heuristic"],
        default="live",
        help=(
            "Pipeline execution mode: "
            "'live' runs async pipeline with debate/API stages (default), "
            "'hybrid' tries live then falls back to heuristic, "
            "'heuristic' uses fast sync from_ideas() path"
        ),
    )
    si_parser.add_argument(
        "--plan-quality-contract-file",
        default=None,
        help="Optional JSON OutputContract for plan quality validation.",
    )
    si_parser.add_argument(
        "--plan-quality-fail-closed",
        action="store_true",
        help="Block handoff when the plan quality gate fails (default: warn-only except CI).",
    )
    si_parser.add_argument(
        "--plan-quality-min-score",
        type=float,
        default=6.0,
        help="Minimum deterministic quality score (0-10) required for handoff (default: 6.0).",
    )
    si_parser.add_argument(
        "--plan-quality-min-practicality",
        type=float,
        default=5.0,
        help="Minimum practicality score (0-10) required for handoff (default: 5.0).",
    )

    dogfood_parser = pipeline_sub.add_parser(
        "dogfood",
        help="Compile pipeline artifacts into a Ralph-ready handoff",
    )
    dogfood_parser.add_argument(
        "--source-file",
        help="Optional roadmap/source document to parse into ideas instead of using a canonical assessment",
    )
    dogfood_parser.add_argument(
        "--assessment-id",
        help="Specific saved canonical assessment ID to use",
    )
    dogfood_parser.add_argument(
        "--latest-assessment",
        action="store_true",
        help="Use the latest saved canonical assessment instead of compiling a new one",
    )
    dogfood_parser.add_argument(
        "--save-assessment",
        action="store_true",
        help="Persist a newly compiled canonical assessment before handoff",
    )
    dogfood_parser.add_argument(
        "--output-dir",
        help="Directory to write assessment, pipeline, objectives, and manifest artifacts",
    )
    dogfood_parser.add_argument(
        "--max-goals",
        type=int,
        default=1,
        help="Maximum number of ranked pipeline objectives to hand off (default: 1)",
    )
    dogfood_parser.add_argument(
        "--budget-limit",
        type=float,
        default=10.0,
        help="Campaign budget limit in USD (default: 10.0)",
    )
    dogfood_parser.add_argument(
        "--time-limit-hours",
        type=float,
        default=4.0,
        help="Campaign time limit in hours (default: 4.0)",
    )
    dogfood_parser.add_argument(
        "--max-parallel-ready-projects",
        type=int,
        default=1,
        help="Maximum ready projects Ralph may run in parallel (default: 1)",
    )
    dogfood_parser.add_argument(
        "--max-retries-per-project",
        type=int,
        default=2,
        help="Maximum retries per project in the generated manifest (default: 2)",
    )
    dogfood_parser.add_argument(
        "--planner-model",
        default="claude",
        help="Campaign planner model (default: claude)",
    )
    dogfood_parser.add_argument(
        "--worker-model",
        default="codex",
        help="Worker model for generated projects (default: codex)",
    )
    dogfood_parser.add_argument(
        "--review-model",
        default="claude",
        help="Review model for generated projects (default: claude)",
    )
    dogfood_parser.add_argument(
        "--start-ralph",
        action="store_true",
        help="Start Ralph supervisor immediately against the generated manifest",
    )
    dogfood_parser.add_argument(
        "--merge-policy",
        default="manual_review_required",
        choices=["manual_review_required", "admin_merge_allowed"],
        help="Ralph merge policy when --start-ralph is used (default: manual_review_required)",
    )
    dogfood_parser.add_argument(
        "--max-repair-attempts",
        type=int,
        default=2,
        help="Ralph max repair attempts when --start-ralph is used (default: 2)",
    )
    dogfood_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON summary",
    )

    # pipeline status
    pipeline_sub.add_parser(
        "status",
        help="Show active pipeline status",
    )

    pipeline_parser.set_defaults(func=cmd_pipeline)
