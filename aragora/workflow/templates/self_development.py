"""Self-Development Workflow Template.

Enables Aragora to orchestrate its own development using heterogeneous
agent groups that debate priorities, develop specs, implement features,
and coordinate merges.

Usage:
    from aragora.workflow.engine import WorkflowEngine
    from aragora.workflow.templates.self_development import (
        create_self_development_workflow,
    )

    engine = WorkflowEngine()
    workflow = create_self_development_workflow(
        objective="Maximize utility for SME businesses",
        tracks=["sme", "qa"],
    )
    result = await engine.execute(workflow, inputs={"max_cycles": 3})
"""

import logging
from typing import Any

from aragora.workflow.types import (
    WorkflowDefinition,
    StepDefinition,
    TransitionRule,
    WorkflowCategory,
)

logger = logging.getLogger(__name__)


def create_self_development_workflow(
    objective: str,
    tracks: list[str] | None = None,
    require_approval: bool = True,
    max_parallel: int = 2,
) -> WorkflowDefinition:
    """Create a workflow definition for self-development.

    Args:
        objective: High-level business objective
        tracks: Tracks to work on (default: all)
        require_approval: Whether to require human approval
        max_parallel: Maximum parallel branches

    Returns:
        WorkflowDefinition for self-development
    """
    tracks = tracks or ["sme", "developer", "qa"]

    steps = [
        # Step 1: Meta-planning - Debate what to improve
        StepDefinition(
            id="meta_plan",
            name="Meta-Planning",
            step_type="debate",
            config={
                "agents": ["claude", "gemini", "deepseek"],
                "rounds": 2,
                "consensus_mechanism": "weighted",
                "topic_template": f"""You are planning improvements for the Aragora project.

OBJECTIVE: {objective}

AVAILABLE TRACKS: {", ".join(tracks)}

Propose 3-5 specific improvement goals that would best achieve the objective.
For each goal, specify:
1. Which track it belongs to
2. A clear, actionable description
3. Why this should be prioritized (rationale)
4. Expected impact: high, medium, or low

Consider dependencies and order goals by priority.""",
            },
            next_steps=["extract_goals"],
        ),
        # Step 2: Extract goals from debate
        StepDefinition(
            id="extract_goals",
            name="Extract Prioritized Goals",
            step_type="task",
            config={
                "task_type": "function",
                "handler": "self_dev_extract_goals",
                "args": {"tracks": tracks},
            },
            next_steps=["create_branches"],
        ),
        # Step 3: Create branches for parallel work
        StepDefinition(
            id="create_branches",
            name="Create Development Branches",
            step_type="task",
            config={
                "task_type": "function",
                "handler": "self_dev_create_branches",
                "args": {"max_parallel": max_parallel},
            },
            next_steps=["parallel_nomic"],
        ),
        # Step 4: Run nomic loops in parallel
        StepDefinition(
            id="parallel_nomic",
            name="Parallel Development",
            step_type="parallel",
            config={
                "branch_key": "branches",
                "step_template": {
                    "type": "nomic",
                    "phases": ["context", "debate", "design", "implement", "verify"],
                    "cycles": 1,
                },
            },
            next_steps=["review_gate"] if require_approval else ["merge_branches"],
        ),
        # Step 5: Human checkpoint (if required)
        StepDefinition(
            id="review_gate",
            name="Review Gate",
            step_type="human_checkpoint",
            config={
                "approval_type": "sign_off",
                "required_role": "developer",
                "checklist": [
                    "All tests pass",
                    "No breaking changes introduced",
                    "Code quality acceptable",
                    "Changes align with objective",
                ],
            },
            optional=not require_approval,
            next_steps=["merge_branches"],
        ),
        # Step 6: Merge branches
        StepDefinition(
            id="merge_branches",
            name="Merge Branches",
            step_type="task",
            config={
                "task_type": "function",
                "handler": "self_dev_merge_branches",
            },
            next_steps=["final_commit"],
        ),
        # Step 7: Final commit
        StepDefinition(
            id="final_commit",
            name="Final Commit",
            step_type="nomic",
            config={
                "phases": ["commit"],
                "require_approval": require_approval,
            },
            next_steps=["store_knowledge"],
        ),
        # Step 8: Store in Knowledge Mound
        StepDefinition(
            id="store_knowledge",
            name="Store Development Record",
            step_type="memory_write",
            config={
                "domain": "development/self-improvement",
                "metadata_keys": [
                    "objective",
                    "tracks",
                    "goals_completed",
                    "duration",
                ],
            },
            next_steps=[],
        ),
    ]

    transitions = [
        TransitionRule(
            id="t1",
            from_step="meta_plan",
            to_step="extract_goals",
            condition="true",
        ),
        TransitionRule(
            id="t2",
            from_step="extract_goals",
            to_step="create_branches",
            condition="true",
        ),
        TransitionRule(
            id="t3",
            from_step="create_branches",
            to_step="parallel_nomic",
            condition="true",
        ),
        TransitionRule(
            id="t4",
            from_step="parallel_nomic",
            to_step="review_gate" if require_approval else "merge_branches",
            condition="true",
        ),
    ]

    if require_approval:
        transitions.append(
            TransitionRule(
                id="t5",
                from_step="review_gate",
                to_step="merge_branches",
                condition="true",
            )
        )

    transitions.extend(
        [
            TransitionRule(
                id="t6",
                from_step="merge_branches",
                to_step="final_commit",
                condition="true",
            ),
            TransitionRule(
                id="t7",
                from_step="final_commit",
                to_step="store_knowledge",
                condition="true",
            ),
        ]
    )

    return WorkflowDefinition(
        id="self_development_pipeline",
        name="Self-Development Pipeline",
        description=f"Autonomous self-improvement targeting: {objective}",
        steps=steps,
        transitions=transitions,
        entry_step="meta_plan",
        category=WorkflowCategory.CODE,
        tags=["self-development", "nomic", "autonomous", "meta-improvement"],
        metadata={
            "objective": objective,
            "tracks": tracks,
            "require_approval": require_approval,
            "max_parallel": max_parallel,
        },
    )


# Template dictionary for registration
SELF_DEVELOPMENT_TEMPLATE: dict[str, Any] = {
    "name": "Self-Development Pipeline",
    "description": "Autonomous self-improvement using heterogeneous agent groups",
    "category": "automation",
    "version": "1.0",
    "tags": ["self-development", "nomic", "autonomous", "meta-improvement"],
    "factory": "create_self_development_workflow",
    "parameters": {
        "objective": {
            "type": "string",
            "required": True,
            "description": "High-level business objective to achieve",
        },
        "tracks": {
            "type": "list",
            "default": ["sme", "developer", "qa"],
            "description": "Development tracks to work on",
        },
        "require_approval": {
            "type": "boolean",
            "default": True,
            "description": "Require human approval before merging",
        },
        "max_parallel": {
            "type": "integer",
            "default": 2,
            "description": "Maximum parallel development branches",
        },
    },
}


# Register task handlers
def _register_self_dev_handlers():
    """Register self-development task handlers."""
    try:
        from aragora.workflow.nodes.task import register_task_handler

        async def self_dev_extract_goals(context, tracks=None):
            """Extract goals from meta-planning debate."""
            from aragora.nomic.meta_planner import MetaPlanner, Track

            debate_result = context.step_outputs.get("meta_plan", {})
            objective = context.inputs.get("objective", "")

            planner = MetaPlanner()

            # Parse available tracks
            available_tracks = []
            tracks = tracks or ["sme", "developer", "qa"]
            for t in tracks:
                try:
                    available_tracks.append(Track(t.lower()))
                except ValueError as e:
                    logger.debug("self dev extract goals encountered an error: %s", e)

            # Parse goals from debate
            goals = planner._parse_goals_from_debate(
                debate_result,
                available_tracks,
                objective,
            )

            return {
                "goals": [
                    {
                        "id": g.id,
                        "track": g.track.value,
                        "description": g.description,
                        "rationale": g.rationale,
                        "impact": g.estimated_impact,
                        "priority": g.priority,
                    }
                    for g in goals
                ],
                "count": len(goals),
            }

        async def self_dev_create_branches(context, max_parallel=2):
            """Create development branches for goals."""
            from aragora.nomic.branch_coordinator import (
                BranchCoordinator,
                TrackAssignment,
            )
            from aragora.nomic.meta_planner import PrioritizedGoal, Track

            goals_data = context.step_outputs.get("extract_goals", {}).get("goals", [])

            # Limit to max parallel
            goals_data = goals_data[:max_parallel]

            # Convert to PrioritizedGoal objects
            assignments = []
            for g in goals_data:
                goal = PrioritizedGoal(
                    id=g["id"],
                    track=Track(g["track"]),
                    description=g["description"],
                    rationale=g.get("rationale", ""),
                    estimated_impact=g.get("impact", "medium"),
                    priority=g.get("priority", 1),
                )
                assignments.append(TrackAssignment(goal=goal))

            # Create branches
            coordinator = BranchCoordinator()
            assignments = await coordinator.create_track_branches(assignments)

            return {
                "branches": [
                    {
                        "branch_name": a.branch_name,
                        "track": a.goal.track.value,
                        "goal": a.goal.description,
                        "worktree_path": str(a.worktree_path) if a.worktree_path else None,
                    }
                    for a in assignments
                ],
                "count": len(assignments),
            }

        async def self_dev_merge_branches(context):
            """Merge completed branches back to main."""
            from aragora.nomic.branch_coordinator import BranchCoordinator

            branches_data = context.step_outputs.get("create_branches", {}).get("branches", [])
            _parallel_results = context.step_outputs.get("parallel_nomic", {})  # For debugging

            coordinator = BranchCoordinator()
            merged = []
            failed = []
            use_worktrees = coordinator.config.use_worktrees

            for branch_info in branches_data:
                branch_name = branch_info.get("branch_name")
                if not branch_name:
                    continue

                if use_worktrees and branch_info.get("worktree_path"):
                    result = await coordinator.merge_worktree_back(branch_name)
                else:
                    result = await coordinator.safe_merge(branch_name)
                if result.success:
                    merged.append(branch_name)
                else:
                    failed.append(
                        {
                            "branch": branch_name,
                            "error": result.error,
                            "conflicts": result.conflicts,
                        }
                    )

            # Cleanup merged branches (worktree cleanup already handled by merge_worktree_back)
            if not use_worktrees:
                coordinator.cleanup_branches(merged)

            return {
                "merged": merged,
                "failed": failed,
                "success": len(failed) == 0,
            }

        register_task_handler("self_dev_extract_goals", self_dev_extract_goals)
        register_task_handler("self_dev_create_branches", self_dev_create_branches)
        register_task_handler("self_dev_merge_branches", self_dev_merge_branches)

    except ImportError:
        pass


_register_self_dev_handlers()

__all__ = [
    "create_self_development_workflow",
    "SELF_DEVELOPMENT_TEMPLATE",
]
