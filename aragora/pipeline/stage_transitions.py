"""
Stage transition functions for the Universal Pipeline.

Promotes nodes from one pipeline stage to the next, generating
provenance links and cross-stage edges along the way.

Each function reads source nodes, creates target-stage nodes with
parent_ids provenance, and records a StageTransition on the graph.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from aragora.canvas.stages import (
    PipelineStage,
    ProvenanceLink,
    StageEdgeType,
    StageTransition,
    content_hash,
)
from aragora.pipeline.adapters import from_goal_node
from aragora.pipeline.stage_transitions_ai import (
    ai_promote_goals_to_actions,
    ai_promote_ideas_to_goals,
)
from aragora.pipeline.universal_node import (
    UniversalEdge,
    UniversalGraph,
    UniversalNode,
)

logger = logging.getLogger(__name__)


@dataclass
class ClarifyingQuestion:
    """A focused question used to sharpen a stage transition."""

    id: str
    text: str
    why: str
    category: str
    target_node_ids: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    impact: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "why": self.why,
            "category": self.category,
            "target_node_ids": list(self.target_node_ids),
            "options": list(self.options),
            "impact": self.impact,
        }


@dataclass
class InteractiveTransitionResult:
    """The result of an interactive transition synthesis."""

    transition: StageTransition
    generated_nodes: list[UniversalNode]
    questions: list[ClarifyingQuestion] = field(default_factory=list)


def generate_ideas_to_goals_questions(
    graph: UniversalGraph,
    idea_node_ids: list[str],
    *,
    max_questions: int = 3,
) -> list[ClarifyingQuestion]:
    """Generate the minimum useful questions before idea→goal synthesis."""
    source_nodes = _collect_stage_nodes(graph, idea_node_ids, PipelineStage.IDEAS)
    if not source_nodes:
        return []

    question_targets = [node.id for node in source_nodes]
    subtype_counts = _count_subtypes(source_nodes)
    questions: list[ClarifyingQuestion] = []

    if _needs_outcome_question(source_nodes):
        questions.append(
            ClarifyingQuestion(
                id="primary_outcome",
                text="What concrete outcome should these ideas optimize for first?",
                why="The source ideas are broad enough that different goal framings would lead to different downstream plans.",
                category="outcome",
                target_node_ids=question_targets,
                options=[
                    "Ship customer-visible value quickly",
                    "Reduce delivery risk first",
                    "Clarify architecture before building",
                ],
                impact=0.95,
            )
        )

    if subtype_counts.get("constraint", 0) == 0:
        questions.append(
            ClarifyingQuestion(
                id="non_negotiable_constraints",
                text="What constraints are non-negotiable for this work?",
                why="Explicit constraints prevent the goal graph from drifting into solutions that are attractive but unacceptable.",
                category="constraint",
                target_node_ids=question_targets,
                options=[
                    "Protect delivery speed",
                    "Protect quality and reviewability",
                    "Protect cost or scope limits",
                ],
                impact=0.9,
            )
        )

    if subtype_counts.get("evidence", 0) == 0 and subtype_counts.get("observation", 0) == 0:
        questions.append(
            ClarifyingQuestion(
                id="success_signal",
                text="How will we know this transition produced the right goals?",
                why="Downstream task/spec generation needs a measurable success signal to write acceptance criteria well.",
                category="success",
                target_node_ids=question_targets,
                options=[
                    "Working user flow",
                    "Passing tests and checks",
                    "Documented spec and clear approvals",
                ],
                impact=0.85,
            )
        )

    if subtype_counts.get("question", 0) > 0 or subtype_counts.get("assumption", 0) > 0:
        questions.append(
            ClarifyingQuestion(
                id="critical_unknown",
                text="Which unresolved assumption or question should stay visible in the goal graph?",
                why="If the most important unknown is hidden, the resulting goals can look certain when they are not.",
                category="risk",
                target_node_ids=[
                    node.id
                    for node in source_nodes
                    if node.node_subtype in {"question", "assumption", "hypothesis"}
                ],
                options=[
                    "Keep it as an explicit constraint",
                    "Turn it into a validating goal",
                    "Defer it to implementation",
                ],
                impact=0.75,
            )
        )

    return questions[:max_questions]


def generate_goals_to_actions_questions(
    graph: UniversalGraph,
    goal_node_ids: list[str],
    *,
    max_questions: int = 3,
) -> list[ClarifyingQuestion]:
    """Generate focused questions before goal→task/spec synthesis."""
    source_nodes = _collect_stage_nodes(graph, goal_node_ids, PipelineStage.GOALS)
    if not source_nodes:
        return []

    question_targets = [node.id for node in source_nodes]
    questions: list[ClarifyingQuestion] = []

    if any(not node.data.get("acceptance_criteria") for node in source_nodes):
        questions.append(
            ClarifyingQuestion(
                id="done_definition",
                text="What must be true for these generated tasks to count as done?",
                why="Acceptance criteria should come from explicit human judgment, not only synthesis defaults.",
                category="acceptance",
                target_node_ids=question_targets,
                options=[
                    "User-visible behavior works",
                    "Tests and docs are complete",
                    "Swarm lane can execute without more clarification",
                ],
                impact=0.95,
            )
        )

    if any(not node.data.get("dependencies") for node in source_nodes) and len(source_nodes) > 1:
        questions.append(
            ClarifyingQuestion(
                id="execution_order",
                text="Which dependency or sequencing constraint matters most before execution starts?",
                why="Without explicit ordering, the system may generate parallel tasks that should actually block each other.",
                category="dependency",
                target_node_ids=question_targets,
                options=[
                    "Do discovery/spec work first",
                    "Start implementation immediately",
                    "Gate execution on review checkpoints",
                ],
                impact=0.9,
            )
        )

    if not any(node.data.get("constraints") for node in source_nodes):
        questions.append(
            ClarifyingQuestion(
                id="delivery_constraints",
                text="What delivery constraints must every generated task or spec respect?",
                why="Constraints need to propagate into every action node so swarm execution inherits the right guardrails.",
                category="constraint",
                target_node_ids=question_targets,
                options=[
                    "Keep scope narrow",
                    "Preserve current behavior",
                    "Prefer fast validation loops",
                ],
                impact=0.85,
            )
        )

    return questions[:max_questions]


def interactive_ideas_to_goals(
    graph: UniversalGraph,
    idea_node_ids: list[str],
    *,
    answers: dict[str, Any] | None = None,
    max_questions: int = 3,
) -> InteractiveTransitionResult:
    """Interactively upgrade vague ideas into editable goal/principle/constraint nodes."""
    source_nodes = _collect_stage_nodes(graph, idea_node_ids, PipelineStage.IDEAS)
    if not source_nodes:
        transition = StageTransition(
            id=f"trans-ideas-goals-{uuid.uuid4().hex[:8]}",
            from_stage=PipelineStage.IDEAS,
            to_stage=PipelineStage.GOALS,
            questions=[],
            answers={},
        )
        graph.transitions.append(transition)
        return InteractiveTransitionResult(transition=transition, generated_nodes=[], questions=[])

    resolved_answers = _normalize_answers(answers)
    questions = generate_ideas_to_goals_questions(graph, idea_node_ids, max_questions=max_questions)
    transition_id = f"trans-ideas-goals-{uuid.uuid4().hex[:8]}"
    created: list[UniversalNode] = []
    provenance_links: list[ProvenanceLink] = []

    shared_constraints = _collect_constraints_from_answers_or_nodes(source_nodes, resolved_answers)
    success_signal = _string_value(resolved_answers.get("success_signal"))
    primary_outcome = _string_value(resolved_answers.get("primary_outcome"))
    critical_unknown = _string_value(resolved_answers.get("critical_unknown"))

    for source in source_nodes:
        semantic_type, node_subtype = _interactive_goal_shape(source)
        label = _build_goal_transition_label(
            source,
            semantic_type=semantic_type,
            primary_outcome=primary_outcome,
        )
        description = _build_goal_transition_description(
            source,
            semantic_type=semantic_type,
            success_signal=success_signal,
            critical_unknown=critical_unknown,
        )
        transition_questions = [
            question.id for question in questions if source.id in question.target_node_ids
        ]

        new_node = UniversalNode(
            id=f"goal-{uuid.uuid4().hex[:8]}",
            stage=PipelineStage.GOALS,
            node_subtype=node_subtype,
            label=label,
            description=description,
            content_hash=content_hash(label + description),
            previous_hash=source.content_hash,
            parent_ids=[source.id],
            source_stage=PipelineStage.IDEAS,
            confidence=_interactive_confidence(source, resolved_answers),
            approval_status="pending",
            data={
                "priority": source.data.get("priority", "medium"),
                "semantic_type": semantic_type,
                "transition_questions": transition_questions,
                "constraints": shared_constraints if semantic_type != "constraint" else [],
                "acceptance_signal": success_signal,
                "editable": True,
                "source_idea_id": source.id,
            },
            metadata={
                "promoted_from": source.id,
                "generated_by_transition_id": transition_id,
                "transition_kind": "interactive_ideas_to_goals",
            },
        )
        graph.add_node(new_node)
        created.append(new_node)

        graph.add_edge(
            UniversalEdge(
                id=f"edge-{uuid.uuid4().hex[:8]}",
                source_id=source.id,
                target_id=new_node.id,
                edge_type=StageEdgeType.DERIVED_FROM,
                label="derived_from",
            )
        )

        provenance_links.append(
            ProvenanceLink(
                source_node_id=source.id,
                source_stage=PipelineStage.IDEAS,
                target_node_id=new_node.id,
                target_stage=PipelineStage.GOALS,
                content_hash=source.content_hash,
                method="interactive_synthesis",
            )
        )

    _link_goal_semantics(graph, created)

    transition = StageTransition(
        id=transition_id,
        from_stage=PipelineStage.IDEAS,
        to_stage=PipelineStage.GOALS,
        provenance=provenance_links,
        status="pending",
        confidence=sum(node.confidence for node in created) / len(created),
        ai_rationale=f"Interactively synthesized {len(created)} editable goal nodes from {len(source_nodes)} ideas",
        generated_node_ids=[node.id for node in created],
        questions=[question.to_dict() for question in questions],
        answers=resolved_answers,
    )
    graph.transitions.append(transition)
    return InteractiveTransitionResult(
        transition=transition,
        generated_nodes=created,
        questions=questions,
    )


def interactive_goals_to_actions(
    graph: UniversalGraph,
    goal_node_ids: list[str],
    *,
    answers: dict[str, Any] | None = None,
    max_questions: int = 3,
) -> InteractiveTransitionResult:
    """Interactively upgrade goals into editable task/spec nodes."""
    source_nodes = _collect_stage_nodes(graph, goal_node_ids, PipelineStage.GOALS)
    if not source_nodes:
        transition = StageTransition(
            id=f"trans-goals-actions-{uuid.uuid4().hex[:8]}",
            from_stage=PipelineStage.GOALS,
            to_stage=PipelineStage.ACTIONS,
            questions=[],
            answers={},
        )
        graph.transitions.append(transition)
        return InteractiveTransitionResult(transition=transition, generated_nodes=[], questions=[])

    resolved_answers = _normalize_answers(answers)
    questions = generate_goals_to_actions_questions(
        graph, goal_node_ids, max_questions=max_questions
    )
    transition_id = f"trans-goals-actions-{uuid.uuid4().hex[:8]}"
    created: list[UniversalNode] = []
    provenance_links: list[ProvenanceLink] = []
    goal_to_action: dict[str, str] = {}

    shared_constraints = _collect_constraints_from_goal_nodes(source_nodes, resolved_answers)
    done_definition = _string_value(resolved_answers.get("done_definition"))
    execution_order = _string_value(resolved_answers.get("execution_order"))

    for source in source_nodes:
        semantic_type, node_subtype = _interactive_action_shape(source)
        acceptance_criteria = _build_acceptance_criteria(
            source,
            semantic_type=semantic_type,
            done_definition=done_definition,
        )
        node_constraints = _merge_unique(
            shared_constraints,
            _string_list(source.data.get("constraints")),
        )
        transition_questions = [
            question.id for question in questions if source.id in question.target_node_ids
        ]

        action_node = UniversalNode(
            id=f"action-{uuid.uuid4().hex[:8]}",
            stage=PipelineStage.ACTIONS,
            node_subtype=node_subtype,
            label=_build_action_transition_label(source, semantic_type=semantic_type),
            description=_build_action_transition_description(source, semantic_type=semantic_type),
            content_hash=content_hash(
                _build_action_transition_label(source, semantic_type=semantic_type)
                + _build_action_transition_description(source, semantic_type=semantic_type)
            ),
            previous_hash=source.content_hash,
            parent_ids=[source.id],
            source_stage=PipelineStage.GOALS,
            confidence=_interactive_confidence(source, resolved_answers, decay=0.92),
            approval_status="pending",
            data={
                "priority": source.data.get("priority", "medium"),
                "semantic_type": semantic_type,
                "transition_questions": transition_questions,
                "acceptance_criteria": acceptance_criteria,
                "constraints": node_constraints,
                "dependency_ids": [],
                "editable": True,
                "source_goal_id": source.id,
                "owner_role": source.data.get("owner_role", "engineer"),
                "allowed_write_scope": list(source.data.get("allowed_write_scope", [])),
                "verification_commands": list(source.data.get("verification_commands", [])),
            },
            metadata={
                "promoted_from": source.id,
                "generated_by_transition_id": transition_id,
                "transition_kind": "interactive_goals_to_actions",
                "execution_order_hint": execution_order,
            },
        )
        graph.add_node(action_node)
        created.append(action_node)
        goal_to_action[source.id] = action_node.id

        graph.add_edge(
            UniversalEdge(
                id=f"edge-{uuid.uuid4().hex[:8]}",
                source_id=source.id,
                target_id=action_node.id,
                edge_type=StageEdgeType.IMPLEMENTS,
                label="implements",
            )
        )

        provenance_links.append(
            ProvenanceLink(
                source_node_id=source.id,
                source_stage=PipelineStage.GOALS,
                target_node_id=action_node.id,
                target_stage=PipelineStage.ACTIONS,
                content_hash=source.content_hash,
                method="interactive_decomposition",
            )
        )

    _propagate_action_dependencies(graph, source_nodes, created, goal_to_action)

    transition = StageTransition(
        id=transition_id,
        from_stage=PipelineStage.GOALS,
        to_stage=PipelineStage.ACTIONS,
        provenance=provenance_links,
        status="pending",
        confidence=sum(node.confidence for node in created) / len(created),
        ai_rationale=f"Interactively synthesized {len(created)} editable task/spec nodes from {len(source_nodes)} goals",
        generated_node_ids=[node.id for node in created],
        questions=[question.to_dict() for question in questions],
        answers=resolved_answers,
    )
    graph.transitions.append(transition)
    return InteractiveTransitionResult(
        transition=transition,
        generated_nodes=created,
        questions=questions,
    )


def revise_generated_node(
    graph: UniversalGraph,
    node_id: str,
    *,
    label: str | None = None,
    description: str | None = None,
    data_updates: dict[str, Any] | None = None,
    editor_id: str = "human",
) -> UniversalNode:
    """Apply an inline revision while preserving provenance history."""
    node = _get_existing_node(graph, node_id)
    original_hash = node.content_hash

    if label is not None:
        node.label = label
    if description is not None:
        node.description = description
    if data_updates:
        node.data.update(data_updates)

    node.previous_hash = original_hash
    node.content_hash = content_hash(node.label + node.description)
    node.updated_at = time.time()
    node.approval_status = "revised"
    node.metadata.setdefault("revision_history", []).append(
        {
            "editor_id": editor_id,
            "edited_at": node.updated_at,
            "previous_hash": original_hash,
        }
    )
    _mark_transition_revised(graph, node)
    return node


def split_generated_node(
    graph: UniversalGraph,
    node_id: str,
    *,
    splits: list[dict[str, Any]],
    editor_id: str = "human",
) -> list[UniversalNode]:
    """Split one generated node into several editable descendants."""
    source = _get_existing_node(graph, node_id)
    if not splits:
        return []

    created: list[UniversalNode] = []
    for split in splits:
        label = str(split.get("label", "")).strip()
        if not label:
            continue
        description = str(split.get("description", source.description)).strip()
        child = UniversalNode(
            id=f"{source.stage.value[:-1] if source.stage.value.endswith('s') else source.stage.value}-{uuid.uuid4().hex[:8]}",
            stage=source.stage,
            node_subtype=str(split.get("node_subtype", source.node_subtype)),
            label=label,
            description=description,
            previous_hash=source.content_hash,
            parent_ids=_merge_unique(source.parent_ids, [source.id]),
            source_stage=source.source_stage,
            confidence=min(1.0, source.confidence),
            approval_status="pending",
            data={**source.data, **dict(split.get("data", {}))},
            metadata={
                **source.metadata,
                "split_from": source.id,
                "generated_by_editor": editor_id,
            },
        )
        graph.add_node(child)
        created.append(child)
        graph.add_edge(
            UniversalEdge(
                id=f"edge-{uuid.uuid4().hex[:8]}",
                source_id=source.id,
                target_id=child.id,
                edge_type=StageEdgeType.DECOMPOSES_INTO,
                label="split_into",
            )
        )

    if created:
        source.status = "archived"
        source.approval_status = "revised"
        source.metadata["split_into"] = [node.id for node in created]
        source.updated_at = time.time()
        _mark_transition_revised(graph, source)
    return created


def merge_generated_nodes(
    graph: UniversalGraph,
    node_ids: list[str],
    *,
    label: str,
    description: str = "",
    node_subtype: str | None = None,
    data_updates: dict[str, Any] | None = None,
    editor_id: str = "human",
) -> UniversalNode:
    """Merge several generated nodes into one provenance-preserving node."""
    nodes = [_get_existing_node(graph, node_id) for node_id in node_ids]
    if not nodes:
        raise ValueError("At least one node is required to merge")
    stage = nodes[0].stage
    if any(node.stage != stage for node in nodes):
        raise ValueError("Merged nodes must belong to the same stage")

    merged = UniversalNode(
        id=f"{stage.value[:-1] if stage.value.endswith('s') else stage.value}-{uuid.uuid4().hex[:8]}",
        stage=stage,
        node_subtype=node_subtype or nodes[0].node_subtype,
        label=label,
        description=description,
        previous_hash=content_hash(":".join(sorted(node.content_hash for node in nodes))),
        parent_ids=_merge_unique(
            [parent_id for node in nodes for parent_id in node.parent_ids],
            [node.id for node in nodes],
        ),
        source_stage=nodes[0].source_stage,
        confidence=max(node.confidence for node in nodes),
        approval_status="pending",
        data=_merged_node_data(nodes, data_updates=data_updates),
        metadata={
            "merged_from": [node.id for node in nodes],
            "generated_by_editor": editor_id,
            "generated_by_transition_id": _shared_transition_id(nodes),
        },
    )
    graph.add_node(merged)

    for node in nodes:
        node.status = "archived"
        node.approval_status = "revised"
        node.metadata["merged_into"] = merged.id
        node.updated_at = time.time()
        graph.add_edge(
            UniversalEdge(
                id=f"edge-{uuid.uuid4().hex[:8]}",
                source_id=node.id,
                target_id=merged.id,
                edge_type=StageEdgeType.RELATES_TO,
                label="merged_into",
            )
        )
        _mark_transition_revised(graph, node)

    return merged


def reject_generated_node(
    graph: UniversalGraph,
    node_id: str,
    *,
    reviewer_id: str = "human",
    reason: str = "",
) -> UniversalNode:
    """Reject a generated node without deleting its provenance."""
    node = _get_existing_node(graph, node_id)
    node.status = "rejected"
    node.approval_status = "rejected"
    node.updated_at = time.time()
    node.metadata["rejection"] = {
        "reviewer_id": reviewer_id,
        "reason": reason,
        "rejected_at": node.updated_at,
    }
    transition = _transition_for_node(graph, node)
    if transition is not None and all(
        graph.nodes[target_id].approval_status == "rejected"
        for target_id in transition.generated_node_ids
        if target_id in graph.nodes
    ):
        transition.status = "rejected"
        transition.human_notes = reason or transition.human_notes
        transition.reviewed_at = time.time()
    return node


def approve_generated_node(
    graph: UniversalGraph,
    node_id: str,
    *,
    approver_id: str,
    notes: str = "",
) -> UniversalNode:
    """Approve a generated node and advance transition status when complete."""
    node = _get_existing_node(graph, node_id)
    node.approval_status = "approved"
    node.updated_at = time.time()
    node.metadata["approval"] = {
        "approver_id": approver_id,
        "notes": notes,
        "approved_at": node.updated_at,
    }
    transition = _transition_for_node(graph, node)
    if transition is not None and _all_non_rejected_nodes_approved(graph, transition):
        transition.status = "approved"
        transition.human_notes = notes or transition.human_notes
        transition.reviewed_at = time.time()
    return node


def approve_transition(
    graph: UniversalGraph,
    transition_id: str,
    *,
    approver_id: str,
    notes: str = "",
) -> StageTransition:
    """Approve every non-rejected node generated by a transition."""
    transition = _get_existing_transition(graph, transition_id)
    for node_id in transition.generated_node_ids:
        if node_id not in graph.nodes:
            continue
        node = graph.nodes[node_id]
        if node.approval_status == "rejected":
            continue
        approve_generated_node(graph, node_id, approver_id=approver_id, notes=notes)
    transition.status = "approved"
    transition.human_notes = notes or transition.human_notes
    transition.reviewed_at = time.time()
    return transition


def submit_approved_actions_to_swarm(
    graph: UniversalGraph,
    *,
    repo_root: str = ".",
    node_ids: list[str] | None = None,
    submission_callback: Any | None = None,
    planner: Any | None = None,
    reference_client: Any | None = None,
    skip_github_resolution: bool = True,
) -> dict[str, Any]:
    """Submit approved task/spec nodes directly to swarm execution."""
    selected_ids = set(node_ids or [])
    approved_nodes = [
        node
        for node in graph.get_stage(PipelineStage.ACTIONS)
        if node.approval_status == "approved"
        and node.data.get("semantic_type") in {"task", "spec"}
        and (not selected_ids or node.id in selected_ids)
    ]
    if not approved_nodes:
        raise ValueError("No approved action/spec nodes are ready for swarm submission")

    bundle = {
        "objective": graph.metadata.get("objective") or graph.name,
        "candidate_lanes": [_swarm_lane_from_node(node) for node in approved_nodes],
    }

    if submission_callback is not None:
        submit = submission_callback
    else:
        from aragora.swarm.tranche_submit import submit_intake_bundle

        submit = submit_intake_bundle

    result = submit(
        bundle,
        repo_root=repo_root,
        planner=planner,
        reference_client=reference_client,
        skip_github_resolution=skip_github_resolution,
    )

    submitted_ids = [node.id for node in approved_nodes]
    submitted_at = time.time()
    for node in approved_nodes:
        node.execution_status = "submitted"
        node.updated_at = submitted_at
        node.metadata["swarm_submission"] = dict(result)

        transition = _transition_for_node(graph, node)
        if transition is not None:
            transition.submission = {
                "submitted_node_ids": submitted_ids,
                "submitted_at": submitted_at,
                **dict(result),
            }

    return {
        "bundle": bundle,
        "submission": result,
        "submitted_node_ids": submitted_ids,
    }


def _collect_stage_nodes(
    graph: UniversalGraph,
    node_ids: list[str],
    stage: PipelineStage,
) -> list[UniversalNode]:
    return [
        graph.nodes[node_id]
        for node_id in node_ids
        if node_id in graph.nodes and graph.nodes[node_id].stage == stage
    ]


def _count_subtypes(nodes: list[UniversalNode]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node.node_subtype] = counts.get(node.node_subtype, 0) + 1
    return counts


def _needs_outcome_question(nodes: list[UniversalNode]) -> bool:
    return len(nodes) > 1 or any(len(node.description.strip()) < 20 for node in nodes)


def _normalize_answers(answers: dict[str, Any] | None) -> dict[str, Any]:
    if not answers:
        return {}
    return {
        str(key).strip(): value
        for key, value in answers.items()
        if str(key).strip() and value not in (None, "", [])
    }


def _string_value(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _merge_unique(*parts: list[str]) -> list[str]:
    merged: list[str] = []
    for part in parts:
        for item in part:
            if item and item not in merged:
                merged.append(item)
    return merged


def _collect_constraints_from_answers_or_nodes(
    nodes: list[UniversalNode],
    answers: dict[str, Any],
) -> list[str]:
    constraints = _string_list(answers.get("non_negotiable_constraints"))
    constraints.extend(node.label for node in nodes if node.node_subtype == "constraint")
    return _merge_unique(constraints)


def _collect_constraints_from_goal_nodes(
    nodes: list[UniversalNode],
    answers: dict[str, Any],
) -> list[str]:
    constraints = _string_list(answers.get("delivery_constraints"))
    for node in nodes:
        if node.data.get("semantic_type") == "constraint":
            constraints.append(node.label)
        constraints.extend(_string_list(node.data.get("constraints")))
    return _merge_unique(constraints)


def _interactive_goal_shape(source: UniversalNode) -> tuple[str, str]:
    if source.node_subtype == "constraint":
        return "constraint", "principle"
    if source.node_subtype in {"insight", "observation", "evidence", "hypothesis"}:
        return "principle", "principle"
    return "goal", "goal"


def _interactive_action_shape(source: UniversalNode) -> tuple[str, str]:
    if source.data.get("semantic_type") in {"principle", "constraint"} or source.node_subtype in {
        "principle",
        "risk",
        "metric",
    }:
        return "spec", "deliverable"
    return "task", _goal_to_action_subtype(source.node_subtype)


def _interactive_confidence(
    source: UniversalNode,
    answers: dict[str, Any],
    *,
    decay: float = 1.0,
) -> float:
    base = source.confidence or 0.45
    if answers:
        base += 0.1
    if source.description:
        base += 0.05
    return min(0.98, round(base * decay, 4))


def _build_goal_transition_label(
    source: UniversalNode,
    *,
    semantic_type: str,
    primary_outcome: str,
) -> str:
    if semantic_type == "constraint":
        return f"Constraint: {source.label}"
    if semantic_type == "principle":
        return f"Principle: {source.label}"
    if primary_outcome:
        return f"Goal: {primary_outcome}"
    return f"Goal: {source.label}"


def _build_goal_transition_description(
    source: UniversalNode,
    *,
    semantic_type: str,
    success_signal: str,
    critical_unknown: str,
) -> str:
    description = source.description or source.label
    if semantic_type == "principle":
        description = f"Use this principle to guide later task/spec generation. {description}"
    elif semantic_type == "constraint":
        description = f"Treat this as a non-negotiable boundary. {description}"
    else:
        description = f"Advance this idea toward execution. {description}"
    if success_signal:
        description = f"{description} Success signal: {success_signal}."
    if critical_unknown and semantic_type == "goal":
        description = f"{description} Keep this unknown visible: {critical_unknown}."
    return description.strip()


def _build_action_transition_label(source: UniversalNode, *, semantic_type: str) -> str:
    prefix = "Spec" if semantic_type == "spec" else "Task"
    raw_label = source.label
    for candidate in ("Goal: ", "Principle: ", "Constraint: ", "Achieve: ", "Maintain: "):
        if raw_label.startswith(candidate):
            raw_label = raw_label[len(candidate) :]
            break
    return f"{prefix}: {raw_label}"


def _build_action_transition_description(source: UniversalNode, *, semantic_type: str) -> str:
    if semantic_type == "spec":
        return source.description or f"Document the execution contract for {source.label}."
    return source.description or f"Implement {source.label}."


def _build_acceptance_criteria(
    source: UniversalNode,
    *,
    semantic_type: str,
    done_definition: str,
) -> list[str]:
    criteria = _string_list(source.data.get("acceptance_criteria"))
    if done_definition:
        criteria.append(done_definition)
    if not criteria and source.data.get("acceptance_signal"):
        criteria.append(str(source.data["acceptance_signal"]))
    if not criteria:
        if semantic_type == "spec":
            criteria.append(f"{source.label} is explicit enough for a worker lane to execute.")
        else:
            criteria.append(f"{source.label} is implemented and reviewable.")
    return _merge_unique(criteria)


def _link_goal_semantics(graph: UniversalGraph, created: list[UniversalNode]) -> None:
    goals = [node for node in created if node.data.get("semantic_type") == "goal"]
    principles = [node for node in created if node.data.get("semantic_type") == "principle"]
    constraints = [node for node in created if node.data.get("semantic_type") == "constraint"]

    for principle in principles:
        for goal in goals:
            graph.add_edge(
                UniversalEdge(
                    id=f"edge-{uuid.uuid4().hex[:8]}",
                    source_id=principle.id,
                    target_id=goal.id,
                    edge_type=StageEdgeType.INFORMS,
                    label="informs",
                )
            )

    for constraint in constraints:
        for goal in goals:
            graph.add_edge(
                UniversalEdge(
                    id=f"edge-{uuid.uuid4().hex[:8]}",
                    source_id=constraint.id,
                    target_id=goal.id,
                    edge_type=StageEdgeType.CONSTRAINS,
                    label="constrains",
                )
            )


def _propagate_action_dependencies(
    graph: UniversalGraph,
    source_nodes: list[UniversalNode],
    created: list[UniversalNode],
    goal_to_action: dict[str, str],
) -> None:
    spec_nodes = [node for node in created if node.data.get("semantic_type") == "spec"]
    task_nodes = [node for node in created if node.data.get("semantic_type") == "task"]

    # Specs gate tasks by default.
    for task in task_nodes:
        dependency_ids = _string_list(task.data.get("dependency_ids"))
        for spec in spec_nodes:
            if spec.id == task.id or spec.id in dependency_ids:
                continue
            dependency_ids.append(spec.id)
            graph.add_edge(
                UniversalEdge(
                    id=f"edge-{uuid.uuid4().hex[:8]}",
                    source_id=task.id,
                    target_id=spec.id,
                    edge_type=StageEdgeType.REQUIRES,
                    label="requires",
                )
            )
        task.data["dependency_ids"] = dependency_ids

    source_ids = {node.id for node in source_nodes}
    for edge in list(graph.edges.values()):
        if edge.source_id not in source_ids or edge.target_id not in source_ids:
            continue
        mapped_source = goal_to_action.get(edge.source_id)
        mapped_target = goal_to_action.get(edge.target_id)
        if not mapped_source or not mapped_target or mapped_source == mapped_target:
            continue
        target_node = graph.nodes[mapped_source]
        dependency_ids = _string_list(target_node.data.get("dependency_ids"))
        if mapped_target in dependency_ids:
            continue
        dependency_ids.append(mapped_target)
        target_node.data["dependency_ids"] = dependency_ids
        graph.add_edge(
            UniversalEdge(
                id=f"edge-{uuid.uuid4().hex[:8]}",
                source_id=mapped_source,
                target_id=mapped_target,
                edge_type=StageEdgeType.REQUIRES,
                label="requires",
            )
        )


def _get_existing_node(graph: UniversalGraph, node_id: str) -> UniversalNode:
    node = graph.nodes.get(node_id)
    if node is None:
        raise ValueError(f"Node {node_id} not found in graph")
    return node


def _transition_for_node(graph: UniversalGraph, node: UniversalNode) -> StageTransition | None:
    transition_id = node.metadata.get("generated_by_transition_id")
    if not transition_id:
        return None
    for transition in graph.transitions:
        if transition.id == transition_id:
            return transition
    return None


def _mark_transition_revised(graph: UniversalGraph, node: UniversalNode) -> None:
    transition = _transition_for_node(graph, node)
    if transition is None:
        return
    transition.status = "revised"
    transition.reviewed_at = time.time()


def _get_existing_transition(graph: UniversalGraph, transition_id: str) -> StageTransition:
    for transition in graph.transitions:
        if transition.id == transition_id:
            return transition
    raise ValueError(f"Transition {transition_id} not found in graph")


def _all_non_rejected_nodes_approved(graph: UniversalGraph, transition: StageTransition) -> bool:
    relevant_nodes = [
        graph.nodes[node_id]
        for node_id in transition.generated_node_ids
        if node_id in graph.nodes and graph.nodes[node_id].approval_status != "rejected"
    ]
    return bool(relevant_nodes) and all(
        node.approval_status == "approved" for node in relevant_nodes
    )


def _merged_node_data(
    nodes: list[UniversalNode],
    *,
    data_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    semantic_types: list[str] = []
    constraints: list[str] = []
    acceptance_criteria: list[str] = []
    dependency_ids: list[str] = []
    allowed_write_scope: list[str] = []
    verification_commands: list[str] = []
    owner_role = ""

    for node in nodes:
        semantic_type = _string_value(node.data.get("semantic_type"))
        if semantic_type:
            semantic_types.append(semantic_type)
        constraints.extend(_string_list(node.data.get("constraints")))
        acceptance_criteria.extend(_string_list(node.data.get("acceptance_criteria")))
        dependency_ids.extend(_string_list(node.data.get("dependency_ids")))
        allowed_write_scope.extend(_string_list(node.data.get("allowed_write_scope")))
        verification_commands.extend(_string_list(node.data.get("verification_commands")))
        owner_role = owner_role or _string_value(node.data.get("owner_role"))

    if semantic_types:
        merged["semantic_type"] = semantic_types[0]
    if constraints:
        merged["constraints"] = _merge_unique(constraints)
    if acceptance_criteria:
        merged["acceptance_criteria"] = _merge_unique(acceptance_criteria)
    if dependency_ids:
        merged["dependency_ids"] = _merge_unique(dependency_ids)
    if allowed_write_scope:
        merged["allowed_write_scope"] = _merge_unique(allowed_write_scope)
    if verification_commands:
        merged["verification_commands"] = _merge_unique(verification_commands)
    if owner_role:
        merged["owner_role"] = owner_role
    if data_updates:
        merged.update(data_updates)
    return merged


def _shared_transition_id(nodes: list[UniversalNode]) -> str:
    transition_ids = {
        _string_value(node.metadata.get("generated_by_transition_id"))
        for node in nodes
        if _string_value(node.metadata.get("generated_by_transition_id"))
    }
    return transition_ids.pop() if len(transition_ids) == 1 else ""


def _swarm_lane_from_node(node: UniversalNode) -> dict[str, Any]:
    acceptance = _string_list(node.data.get("acceptance_criteria"))
    constraints = _string_list(node.data.get("constraints"))
    prompt_sections = [node.description or node.label]
    if acceptance:
        prompt_sections.append("Acceptance criteria:\n- " + "\n- ".join(acceptance))
    if constraints:
        prompt_sections.append("Constraints:\n- " + "\n- ".join(constraints))
    return {
        "lane_id": node.id,
        "title": node.label,
        "prompt": "\n\n".join(prompt_sections),
        "owner_role": str(node.data.get("owner_role", "engineer")),
        "allowed_write_scope": list(node.data.get("allowed_write_scope", [])),
        "verification_commands": list(node.data.get("verification_commands", [])),
        "dependencies": _string_list(node.data.get("dependency_ids")),
    }


def promote_node(
    graph: UniversalGraph,
    node_id: str,
    target_stage: PipelineStage,
    new_subtype: str,
    new_label: str = "",
) -> UniversalNode:
    """Generic single-node promotion with provenance chain.

    Creates a new node in target_stage derived from node_id.
    """
    source = graph.nodes.get(node_id)
    if source is None:
        raise ValueError(f"Source node {node_id} not found in graph")

    label = new_label or source.label
    new_id = f"{target_stage.value}-{uuid.uuid4().hex[:8]}"

    new_node = UniversalNode(
        id=new_id,
        stage=target_stage,
        node_subtype=new_subtype,
        label=label,
        description=source.description,
        content_hash=content_hash(label + source.description),
        previous_hash=source.content_hash,
        parent_ids=[source.id],
        source_stage=source.stage,
        confidence=source.confidence,
        data=dict(source.data),
        metadata={"promoted_from": source.id},
    )
    graph.add_node(new_node)

    # Cross-stage edge
    edge_type = _promotion_edge_type(source.stage, target_stage)
    edge = UniversalEdge(
        id=f"edge-{uuid.uuid4().hex[:8]}",
        source_id=source.id,
        target_id=new_node.id,
        edge_type=edge_type,
        label=edge_type.value,
    )
    graph.add_edge(edge)

    return new_node


def ideas_to_goals(
    graph: UniversalGraph,
    idea_node_ids: list[str],
    extractor: Any | None = None,
) -> list[UniversalNode]:
    """Promote idea nodes to goal nodes.

    If a GoalExtractor is provided, uses it for AI-assisted synthesis.
    Otherwise, does a 1:1 structural promotion.
    """
    if extractor is not None:
        return _ideas_to_goals_with_extractor(graph, idea_node_ids, extractor)

    created: list[UniversalNode] = []
    provenance_links: list[ProvenanceLink] = []

    for idea_id in idea_node_ids:
        source = graph.nodes.get(idea_id)
        if source is None or source.stage != PipelineStage.IDEAS:
            continue

        goal_subtype = _idea_to_goal_subtype(source.node_subtype)
        goal_label = (
            f"Achieve: {source.label}" if not source.label.startswith("Achieve") else source.label
        )

        goal_node = UniversalNode(
            id=f"goal-{uuid.uuid4().hex[:8]}",
            stage=PipelineStage.GOALS,
            node_subtype=goal_subtype,
            label=goal_label,
            description=source.description,
            content_hash=content_hash(goal_label + source.description),
            previous_hash=source.content_hash,
            parent_ids=[source.id],
            source_stage=PipelineStage.IDEAS,
            confidence=source.confidence,
            data=dict(source.data),
            metadata={"promoted_from": source.id},
        )
        graph.add_node(goal_node)
        created.append(goal_node)

        # Cross-stage edge
        edge = UniversalEdge(
            id=f"edge-{uuid.uuid4().hex[:8]}",
            source_id=source.id,
            target_id=goal_node.id,
            edge_type=StageEdgeType.DERIVED_FROM,
            label="derived_from",
        )
        graph.add_edge(edge)

        provenance_links.append(
            ProvenanceLink(
                source_node_id=source.id,
                source_stage=PipelineStage.IDEAS,
                target_node_id=goal_node.id,
                target_stage=PipelineStage.GOALS,
                content_hash=source.content_hash,
                method="structural_promotion",
            )
        )

    # Record transition
    if created:
        transition = StageTransition(
            id=f"trans-ideas-goals-{uuid.uuid4().hex[:8]}",
            from_stage=PipelineStage.IDEAS,
            to_stage=PipelineStage.GOALS,
            provenance=provenance_links,
            status="pending",
            confidence=sum(n.confidence for n in created) / len(created) if created else 0,
            ai_rationale=f"Promoted {len(created)} idea nodes to goals",
        )
        graph.transitions.append(transition)

    return created


def _ideas_to_goals_with_extractor(
    graph: UniversalGraph,
    idea_node_ids: list[str],
    extractor: Any,
) -> list[UniversalNode]:
    """Use GoalExtractor for richer idea→goal synthesis."""
    # Build a minimal canvas dict for the extractor
    nodes_data = []
    for nid in idea_node_ids:
        node = graph.nodes.get(nid)
        if node and node.stage == PipelineStage.IDEAS:
            nodes_data.append(
                {
                    "id": node.id,
                    "label": node.label,
                    "data": {
                        "idea_type": node.node_subtype,
                        "full_content": node.description or node.label,
                        **node.data,
                    },
                }
            )

    if not nodes_data:
        return []

    canvas_data = {"nodes": nodes_data, "edges": []}
    goal_graph = extractor.extract_from_ideas(canvas_data)

    created: list[UniversalNode] = []
    for goal in goal_graph.goals:
        unode = from_goal_node(goal)
        graph.add_node(unode)
        created.append(unode)

        # Cross-stage edges
        for src_id in goal.source_idea_ids:
            if src_id in graph.nodes:
                edge = UniversalEdge(
                    id=f"edge-{uuid.uuid4().hex[:8]}",
                    source_id=src_id,
                    target_id=unode.id,
                    edge_type=StageEdgeType.DERIVED_FROM,
                    label="derived_from",
                )
                graph.add_edge(edge)

    if goal_graph.transition:
        graph.transitions.append(goal_graph.transition)

    return created


def goals_to_actions(
    graph: UniversalGraph,
    goal_node_ids: list[str],
    meta_planner: Any | None = None,
) -> list[UniversalNode]:
    """Derive action/task nodes from goal nodes.

    If a MetaPlanner is provided, uses it to prioritize and enrich the
    decomposition with debate-driven rationale.  Falls back to structural
    decomposition when MetaPlanner is None or raises.
    """
    if meta_planner is not None:
        try:
            return _goals_to_actions_with_planner(graph, goal_node_ids, meta_planner)
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning(
                "MetaPlanner enrichment failed, falling back to structural decomposition: %s",
                exc,
                exc_info=True,
            )

    return _goals_to_actions_structural(graph, goal_node_ids)


def _goals_to_actions_with_planner(
    graph: UniversalGraph,
    goal_node_ids: list[str],
    meta_planner: Any,
) -> list[UniversalNode]:
    """Use MetaPlanner for prioritized goal→action decomposition."""
    # Collect goal descriptions for the planner
    goal_descriptions: list[str] = []
    valid_ids: list[str] = []
    for goal_id in goal_node_ids:
        source = graph.nodes.get(goal_id)
        if source is not None and source.stage == PipelineStage.GOALS:
            goal_descriptions.append(source.description or source.label)
            valid_ids.append(goal_id)

    if not valid_ids:
        return []

    objective = "; ".join(goal_descriptions)

    # prioritize_work is async — run synchronously
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            prioritized = pool.submit(
                asyncio.run, meta_planner.prioritize_work(objective=objective)
            ).result()
    else:
        prioritized = asyncio.run(meta_planner.prioritize_work(objective=objective))

    # Build a priority map from MetaPlanner results (keyed by description similarity)
    priority_map: dict[str, Any] = {}
    for pg in prioritized:
        priority_map[pg.description.lower()] = pg

    created: list[UniversalNode] = []
    provenance_links: list[ProvenanceLink] = []

    for goal_id in valid_ids:
        source = graph.nodes[goal_id]
        action_subtype = _goal_to_action_subtype(source.node_subtype)
        action_label = source.label.replace("Achieve: ", "").replace("Maintain: ", "")

        # Try to match this goal to a MetaPlanner result for enrichment
        matched_pg = _match_prioritized_goal(source, priority_map)

        if matched_pg is not None:
            priority_val = matched_pg.estimated_impact
            rationale = matched_pg.rationale
            planner_priority = matched_pg.priority
        else:
            priority_val = source.data.get("priority", "medium")
            rationale = ""
            planner_priority = None

        metadata: dict[str, Any] = {"promoted_from": source.id}
        if rationale:
            metadata["meta_planner_rationale"] = rationale
        if planner_priority is not None:
            metadata["meta_planner_priority"] = planner_priority

        action_node = UniversalNode(
            id=f"action-{uuid.uuid4().hex[:8]}",
            stage=PipelineStage.ACTIONS,
            node_subtype=action_subtype,
            label=action_label,
            description=source.description,
            content_hash=content_hash(action_label + source.description),
            previous_hash=source.content_hash,
            parent_ids=[source.id],
            source_stage=PipelineStage.GOALS,
            confidence=source.confidence * 0.9,
            data={
                "priority": priority_val,
                "source_goal_id": source.id,
            },
            metadata=metadata,
        )
        graph.add_node(action_node)
        created.append(action_node)

        edge = UniversalEdge(
            id=f"edge-{uuid.uuid4().hex[:8]}",
            source_id=source.id,
            target_id=action_node.id,
            edge_type=StageEdgeType.IMPLEMENTS,
            label="implements",
        )
        graph.add_edge(edge)

        provenance_links.append(
            ProvenanceLink(
                source_node_id=source.id,
                source_stage=PipelineStage.GOALS,
                target_node_id=action_node.id,
                target_stage=PipelineStage.ACTIONS,
                content_hash=source.content_hash,
                method="meta_planner_decomposition",
            )
        )

    # Sort created nodes by MetaPlanner priority when available
    created.sort(
        key=lambda n: n.metadata.get("meta_planner_priority", 999),
    )

    if created:
        transition = StageTransition(
            id=f"trans-goals-actions-{uuid.uuid4().hex[:8]}",
            from_stage=PipelineStage.GOALS,
            to_stage=PipelineStage.ACTIONS,
            provenance=provenance_links,
            status="pending",
            confidence=sum(n.confidence for n in created) / len(created),
            ai_rationale=(f"MetaPlanner-prioritized decomposition of {len(created)} goals"),
        )
        graph.transitions.append(transition)

    return created


def _match_prioritized_goal(
    source: UniversalNode,
    priority_map: dict[str, Any],
) -> Any | None:
    """Best-effort match a goal node to a MetaPlanner PrioritizedGoal."""
    desc_lower = (source.description or source.label).lower()
    # Exact description match
    if desc_lower in priority_map:
        return priority_map[desc_lower]
    # Substring containment
    for key, pg in priority_map.items():
        if key in desc_lower or desc_lower in key:
            return pg
    return None


def _goals_to_actions_structural(
    graph: UniversalGraph,
    goal_node_ids: list[str],
) -> list[UniversalNode]:
    """Structural goal→action decomposition (original logic)."""
    created: list[UniversalNode] = []
    provenance_links: list[ProvenanceLink] = []

    for goal_id in goal_node_ids:
        source = graph.nodes.get(goal_id)
        if source is None or source.stage != PipelineStage.GOALS:
            continue

        action_subtype = _goal_to_action_subtype(source.node_subtype)
        action_label = source.label.replace("Achieve: ", "").replace("Maintain: ", "")

        action_node = UniversalNode(
            id=f"action-{uuid.uuid4().hex[:8]}",
            stage=PipelineStage.ACTIONS,
            node_subtype=action_subtype,
            label=action_label,
            description=source.description,
            content_hash=content_hash(action_label + source.description),
            previous_hash=source.content_hash,
            parent_ids=[source.id],
            source_stage=PipelineStage.GOALS,
            confidence=source.confidence * 0.9,
            data={
                "priority": source.data.get("priority", "medium"),
                "source_goal_id": source.id,
            },
            metadata={"promoted_from": source.id},
        )
        graph.add_node(action_node)
        created.append(action_node)

        edge = UniversalEdge(
            id=f"edge-{uuid.uuid4().hex[:8]}",
            source_id=source.id,
            target_id=action_node.id,
            edge_type=StageEdgeType.IMPLEMENTS,
            label="implements",
        )
        graph.add_edge(edge)

        provenance_links.append(
            ProvenanceLink(
                source_node_id=source.id,
                source_stage=PipelineStage.GOALS,
                target_node_id=action_node.id,
                target_stage=PipelineStage.ACTIONS,
                content_hash=source.content_hash,
                method="goal_decomposition",
            )
        )

    if created:
        transition = StageTransition(
            id=f"trans-goals-actions-{uuid.uuid4().hex[:8]}",
            from_stage=PipelineStage.GOALS,
            to_stage=PipelineStage.ACTIONS,
            provenance=provenance_links,
            status="pending",
            confidence=sum(n.confidence for n in created) / len(created) if created else 0,
            ai_rationale=f"Decomposed {len(created)} goals into action tasks",
        )
        graph.transitions.append(transition)

    return created


def actions_to_orchestration(
    graph: UniversalGraph,
    action_node_ids: list[str],
) -> list[UniversalNode]:
    """Create orchestration nodes from action items."""
    created: list[UniversalNode] = []
    provenance_links: list[ProvenanceLink] = []

    for action_id in action_node_ids:
        source = graph.nodes.get(action_id)
        if source is None or source.stage != PipelineStage.ACTIONS:
            continue

        orch_subtype = _action_to_orch_subtype(source.node_subtype)
        agent_type = _assign_agent_type(source)

        orch_node = UniversalNode(
            id=f"orch-{uuid.uuid4().hex[:8]}",
            stage=PipelineStage.ORCHESTRATION,
            node_subtype=orch_subtype,
            label=source.label,
            description=source.description,
            content_hash=content_hash(source.label + source.description),
            previous_hash=source.content_hash,
            parent_ids=[source.id],
            source_stage=PipelineStage.ACTIONS,
            confidence=source.confidence * 0.85,
            data={
                "agent_type": agent_type,
                "source_action_id": source.id,
                "priority": source.data.get("priority", "medium"),
            },
            metadata={"promoted_from": source.id},
        )
        graph.add_node(orch_node)
        created.append(orch_node)

        edge = UniversalEdge(
            id=f"edge-{uuid.uuid4().hex[:8]}",
            source_id=source.id,
            target_id=orch_node.id,
            edge_type=StageEdgeType.EXECUTES,
            label="executes",
        )
        graph.add_edge(edge)

        provenance_links.append(
            ProvenanceLink(
                source_node_id=source.id,
                source_stage=PipelineStage.ACTIONS,
                target_node_id=orch_node.id,
                target_stage=PipelineStage.ORCHESTRATION,
                content_hash=source.content_hash,
                method="agent_assignment",
            )
        )

    if created:
        transition = StageTransition(
            id=f"trans-actions-orch-{uuid.uuid4().hex[:8]}",
            from_stage=PipelineStage.ACTIONS,
            to_stage=PipelineStage.ORCHESTRATION,
            provenance=provenance_links,
            status="pending",
            confidence=sum(n.confidence for n in created) / len(created) if created else 0,
            ai_rationale=(f"Assigned {len(created)} action tasks to orchestration agents"),
        )
        graph.transitions.append(transition)

    return created


# ── Mapping helpers ─────────────────────────────────────────────────────


def _promotion_edge_type(from_stage: PipelineStage, to_stage: PipelineStage) -> StageEdgeType:
    if from_stage == PipelineStage.IDEAS and to_stage == PipelineStage.GOALS:
        return StageEdgeType.DERIVED_FROM
    if from_stage == PipelineStage.GOALS and to_stage == PipelineStage.ACTIONS:
        return StageEdgeType.IMPLEMENTS
    if from_stage == PipelineStage.ACTIONS and to_stage == PipelineStage.ORCHESTRATION:
        return StageEdgeType.EXECUTES
    return StageEdgeType.DERIVED_FROM


def _idea_to_goal_subtype(idea_subtype: str) -> str:
    return {
        "concept": "goal",
        "cluster": "goal",
        "question": "milestone",
        "insight": "strategy",
        "evidence": "metric",
        "assumption": "risk",
        "constraint": "principle",
        "observation": "metric",
        "hypothesis": "strategy",
    }.get(idea_subtype, "goal")


def _goal_to_action_subtype(goal_subtype: str) -> str:
    return {
        "goal": "task",
        "principle": "checkpoint",
        "strategy": "epic",
        "milestone": "checkpoint",
        "metric": "deliverable",
        "risk": "checkpoint",
    }.get(goal_subtype, "task")


def _action_to_orch_subtype(action_subtype: str) -> str:
    return {
        "task": "agent_task",
        "epic": "parallel_fan",
        "checkpoint": "human_gate",
        "deliverable": "verification",
        "dependency": "merge",
    }.get(action_subtype, "agent_task")


def _assign_agent_type(action_node: UniversalNode) -> str:
    """Pick an agent archetype based on action content."""
    subtype = action_node.node_subtype
    if subtype == "checkpoint":
        return "reviewer"
    if subtype == "deliverable":
        return "verifier"
    label_lower = action_node.label.lower()
    if any(w in label_lower for w in ("implement", "build", "code", "create")):
        return "implementer"
    if any(w in label_lower for w in ("review", "verify", "test", "check")):
        return "reviewer"
    return "analyst"


def suggest_transitions(
    graph: UniversalGraph,
    stage: PipelineStage,
) -> list[dict[str, Any]]:
    """Suggest candidate transitions from the given stage to the next.

    Analyzes nodes at *stage* and returns a list of suggestions with
    confidence scores indicating how ready each node is for promotion.

    Returns a list of dicts::

        {
            "node_id": str,
            "node_label": str,
            "from_stage": str,        # e.g. "ideas"
            "to_stage": str,           # e.g. "goals"
            "confidence": float,       # 0.0 – 1.0
            "reason": str,
        }
    """
    next_stage = _next_stage(stage)
    if next_stage is None:
        return []

    nodes = graph.get_stage(stage)
    if not nodes:
        return []

    # Check which nodes already have children in the next stage
    promoted_ids: set[str] = set()
    for node in graph.get_stage(next_stage):
        promoted_ids.update(node.parent_ids)

    suggestions: list[dict[str, Any]] = []
    for node in nodes:
        # Skip nodes that were already promoted
        if node.id in promoted_ids:
            continue

        confidence = _transition_confidence(node, stage, graph)
        if confidence < 0.1:
            continue

        suggestions.append(
            {
                "node_id": node.id,
                "node_label": node.label,
                "from_stage": stage.value,
                "to_stage": next_stage.value,
                "confidence": round(confidence, 2),
                "reason": _transition_reason(node, stage, confidence),
            }
        )

    suggestions.sort(key=lambda s: s["confidence"], reverse=True)
    return suggestions


def _next_stage(stage: PipelineStage) -> PipelineStage | None:
    """Return the next stage in the pipeline, or None for orchestration."""
    order = [
        PipelineStage.IDEAS,
        PipelineStage.GOALS,
        PipelineStage.ACTIONS,
        PipelineStage.ORCHESTRATION,
    ]
    try:
        idx = order.index(stage)
    except ValueError:
        return None
    return order[idx + 1] if idx + 1 < len(order) else None


def _transition_confidence(
    node: UniversalNode,
    stage: PipelineStage,
    graph: UniversalGraph,
) -> float:
    """Heuristic confidence score for promoting a node."""
    score = 0.3  # Base score for any active node

    # Nodes with descriptions are more ready
    if node.description and len(node.description) > 10:
        score += 0.2

    # Higher-confidence nodes are more ready
    if node.confidence > 0.5:
        score += 0.15
    elif node.confidence > 0.3:
        score += 0.1

    # Nodes with inbound edges (i.e. connected to other nodes) are more mature
    inbound = sum(1 for e in graph.edges.values() if e.target_id == node.id)
    if inbound > 0:
        score += min(0.15, inbound * 0.05)

    # Active nodes are promotable; archived/rejected are not
    if node.status in ("archived", "rejected"):
        return 0.0
    if node.status == "completed":
        score += 0.2

    return min(1.0, score)


def _transition_reason(
    node: UniversalNode,
    stage: PipelineStage,
    confidence: float,
) -> str:
    """Generate a human-readable reason for the transition suggestion."""
    next_s = _next_stage(stage)
    next_label = next_s.value.title() if next_s else "next stage"

    if confidence >= 0.7:
        return f"Strong candidate for {next_label} — well-defined with supporting context"
    if confidence >= 0.5:
        return f"Ready for promotion to {next_label}"
    return f"May benefit from further refinement before promoting to {next_label}"


__all__ = [
    "ClarifyingQuestion",
    "InteractiveTransitionResult",
    "promote_node",
    "ideas_to_goals",
    "goals_to_actions",
    "actions_to_orchestration",
    "suggest_transitions",
    "generate_ideas_to_goals_questions",
    "generate_goals_to_actions_questions",
    "interactive_ideas_to_goals",
    "interactive_goals_to_actions",
    "revise_generated_node",
    "split_generated_node",
    "merge_generated_nodes",
    "reject_generated_node",
    "approve_generated_node",
    "approve_transition",
    "submit_approved_actions_to_swarm",
    "ai_promote_ideas_to_goals",
    "ai_promote_goals_to_actions",
]
