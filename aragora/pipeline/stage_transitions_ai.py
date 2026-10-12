"""AI-assisted promotion of pipeline ideas to goals and goals to actions.

Split out of :mod:`aragora.pipeline.stage_transitions`, which re-exports the
public functions so existing imports keep working.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

# Keep the pre-split logger name so existing log routing and filters still apply.
logger = logging.getLogger("aragora.pipeline.stage_transitions")


def _cluster_ideas_by_similarity(
    ideas: list[dict[str, Any]],
    max_cluster_size: int = 5,
) -> list[list[dict[str, Any]]]:
    """Group ideas by keyword overlap.

    Uses simple word-set intersection to cluster related ideas together.
    Each cluster has at most *max_cluster_size* members.

    Args:
        ideas: List of idea dicts with at least ``label`` and optionally
               ``description`` fields.
        max_cluster_size: Maximum ideas per cluster.

    Returns:
        List of clusters, where each cluster is a list of idea dicts.
    """
    if not ideas:
        return []

    # Tokenize each idea
    import re as _re

    stop_words = frozenset(
        {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "and",
            "but",
            "or",
            "not",
            "this",
            "that",
            "it",
            "its",
        }
    )

    def _tokens(idea: dict[str, Any]) -> set[str]:
        text = f"{idea.get('label', '')} {idea.get('description', '')}"
        words = _re.split(r"[^a-zA-Z0-9]+", text.lower())
        return {w for w in words if w and len(w) > 2 and w not in stop_words}

    idea_tokens = [_tokens(idea) for idea in ideas]

    # Greedy clustering: assign each idea to the first cluster it overlaps with
    clusters: list[list[int]] = []
    cluster_tokens: list[set[str]] = []
    assigned: set[int] = set()

    for i, tokens in enumerate(idea_tokens):
        if i in assigned:
            continue

        best_cluster = -1
        best_overlap = 0
        for ci, ct in enumerate(cluster_tokens):
            if len(clusters[ci]) >= max_cluster_size:
                continue
            overlap = len(tokens & ct)
            if overlap > best_overlap:
                best_overlap = overlap
                best_cluster = ci

        if best_cluster >= 0 and best_overlap >= 2:
            clusters[best_cluster].append(i)
            cluster_tokens[best_cluster] |= tokens
            assigned.add(i)
        else:
            clusters.append([i])
            cluster_tokens.append(set(tokens))
            assigned.add(i)

    return [[ideas[idx] for idx in cluster] for cluster in clusters]


def _simple_goal_from_cluster(
    cluster: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a simple goal dict from a cluster of ideas.

    Picks the first idea label as the base and references all cluster
    member IDs as parent ideas.

    Returns:
        A goal dict with keys: id, label, description, parent_idea_ids,
        confidence, priority.
    """
    if not cluster:
        return {
            "id": f"goal-{uuid.uuid4().hex[:8]}",
            "label": "Empty goal",
            "description": "",
            "parent_idea_ids": [],
            "confidence": 0.0,
            "priority": "low",
        }

    labels = [idea.get("label", "") for idea in cluster if idea.get("label")]
    combined_label = labels[0] if labels else "Untitled goal"

    # Synthesize a description from all cluster members
    descriptions = [idea.get("description") or idea.get("label", "") for idea in cluster]
    combined_desc = "; ".join(d for d in descriptions if d)

    parent_ids = [idea.get("id", "") for idea in cluster if idea.get("id")]

    # Priority heuristic: larger clusters are higher priority
    priority = "high" if len(cluster) >= 4 else "medium" if len(cluster) >= 2 else "low"

    return {
        "id": f"goal-{uuid.uuid4().hex[:8]}",
        "label": f"Achieve: {combined_label}"
        if not combined_label.startswith("Achieve")
        else combined_label,
        "description": combined_desc,
        "parent_idea_ids": parent_ids,
        "confidence": min(1.0, 0.3 + len(cluster) * 0.1),
        "priority": priority,
    }


async def ai_promote_ideas_to_goals(
    ideas: list[dict[str, Any]],
    agent: Any | None = None,
) -> list[dict[str, Any]]:
    """AI-powered promotion of ideas to SMART goals.

    Groups ideas by keyword similarity, then uses a GoalExtractor (if
    available) to create SMART goals for each cluster.  Falls back to
    simple structural goal creation when the extractor is unavailable or
    fails.

    Args:
        ideas: List of idea dicts, each with at least ``id``, ``label``,
               and optionally ``description``.
        agent: Optional AI agent passed to GoalExtractor for synthesis.

    Returns:
        List of goal dicts, each containing ``id``, ``label``,
        ``description``, ``parent_idea_ids``, ``confidence``, and
        ``priority``.
    """
    if not ideas:
        return []

    # Step 1: Cluster ideas by keyword similarity
    clusters = _cluster_ideas_by_similarity(ideas)
    logger.info("Clustered %d ideas into %d groups", len(ideas), len(clusters))

    goals: list[dict[str, Any]] = []

    # Step 2: Try GoalExtractor for each cluster
    extractor = None
    if agent is not None:
        try:
            from aragora.goals.extractor import GoalExtractor

            extractor = GoalExtractor(agent=agent)
        except (ImportError, RuntimeError, TypeError) as exc:
            logger.warning(
                "GoalExtractor unavailable, using simple goal creation: %s",
                exc,
            )

    for cluster in clusters:
        if extractor is not None:
            try:
                # Build minimal canvas data for the extractor
                canvas_data = {
                    "nodes": [
                        {
                            "id": idea.get("id", f"idea-{i}"),
                            "label": idea.get("label", ""),
                            "data": {
                                "idea_type": idea.get("type", "concept"),
                                "full_content": idea.get("description") or idea.get("label", ""),
                            },
                        }
                        for i, idea in enumerate(cluster)
                    ],
                    "edges": [],
                }
                goal_graph = extractor.extract_from_ideas(canvas_data)
                for goal_node in goal_graph.goals:
                    goals.append(
                        {
                            "id": goal_node.id,
                            "label": goal_node.title,
                            "description": goal_node.description,
                            "parent_idea_ids": goal_node.source_idea_ids,
                            "confidence": goal_node.confidence,
                            "priority": goal_node.priority,
                        }
                    )
                continue
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                logger.warning(
                    "GoalExtractor failed for cluster, falling back to simple: %s",
                    exc,
                )

        # Fallback: simple goal creation
        goals.append(_simple_goal_from_cluster(cluster))

    logger.info("Promoted %d ideas into %d goals", len(ideas), len(goals))
    return goals


async def ai_promote_goals_to_actions(
    goals: list[dict[str, Any]],
    agent: Any | None = None,
) -> list[dict[str, Any]]:
    """AI-powered promotion of goals to structured action plans.

    Takes goal objects and creates action items with descriptions,
    estimated effort, and parent goal references.

    Args:
        goals: List of goal dicts, each with at least ``id``, ``label``,
               and optionally ``description`` and ``priority``.
        agent: Optional AI agent (reserved for future AI-assisted
               decomposition).

    Returns:
        List of action dicts, each containing ``id``, ``description``,
        ``estimated_effort``, ``parent_goal``, and ``priority``.
    """
    if not goals:
        return []

    actions: list[dict[str, Any]] = []

    for goal in goals:
        goal_id = goal.get("id", "")
        goal_label = goal.get("label", "")
        goal_desc = goal.get("description", "") or goal_label
        goal_priority = goal.get("priority", "medium")

        # Strip "Achieve: " / "Maintain: " prefixes for the action label
        action_label = goal_label
        for prefix in ("Achieve: ", "Maintain: ", "Implement: ", "Complete: "):
            if action_label.startswith(prefix):
                action_label = action_label[len(prefix) :]
                break

        # Estimate effort based on description length and priority
        desc_len = len(goal_desc)
        if goal_priority == "critical":
            estimated_effort = "large"
        elif goal_priority == "high" or desc_len > 200:
            estimated_effort = "medium"
        else:
            estimated_effort = "small"

        actions.append(
            {
                "id": f"action-{uuid.uuid4().hex[:8]}",
                "description": action_label,
                "estimated_effort": estimated_effort,
                "parent_goal": goal_id,
                "priority": goal_priority,
            }
        )

    logger.info("Created %d actions from %d goals", len(actions), len(goals))
    return actions


__all__ = [
    "ai_promote_ideas_to_goals",
    "ai_promote_goals_to_actions",
]
