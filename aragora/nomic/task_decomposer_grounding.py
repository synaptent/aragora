"""Codebase grounding and vague-goal expansion for task decomposition.

``TaskDecomposer`` (``aragora.nomic.task_decomposer``) inherits these members: they map goal
keywords to repository directories, render a live directory listing for prompts, and expand
vague goals into concrete subtasks from deliberation templates and development tracks.
Import the decomposer from ``aragora.nomic.task_decomposer``.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

from aragora.nomic.task_decomposer_models import SubTask, TaskDecomposition

if TYPE_CHECKING:
    from aragora.nomic.task_decomposer import DecomposerConfig

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.task_decomposer" still see records from the moved methods.
logger = logging.getLogger("aragora.nomic.task_decomposer")


class TaskDecomposerGroundingMixin:
    """Codebase relevance, grounding and vague-goal expansion inherited by ``TaskDecomposer``."""

    config: DecomposerConfig

    # =========================================================================
    # Codebase module mapping for relevance scoring
    # =========================================================================

    _CODEBASE_MODULES: dict[str, list[str]] = {
        "debate": ["aragora/debate/"],
        "agents": ["aragora/agents/"],
        "analytics": ["aragora/analytics/"],
        "audit": ["aragora/audit/"],
        "billing": ["aragora/billing/"],
        "cli": ["aragora/cli/"],
        "compliance": ["aragora/compliance/"],
        "connectors": ["aragora/connectors/"],
        "gateway": ["aragora/gateway/"],
        "knowledge": ["aragora/knowledge/"],
        "memory": ["aragora/memory/"],
        "nomic": ["aragora/nomic/"],
        "pipeline": ["aragora/pipeline/"],
        "rbac": ["aragora/rbac/"],
        "security": ["aragora/security/"],
        "server": ["aragora/server/"],
        "skills": ["aragora/skills/"],
        "storage": ["aragora/storage/"],
        "workflow": ["aragora/workflow/"],
        "frontend": ["aragora/live/src/"],
        "sdk": ["sdk/"],
        "tests": ["tests/"],
    }

    def _score_codebase_relevance(self, goal: str) -> list[str]:
        """Find relevant codebase directories for a goal using keyword matching.

        Parses the goal against the CLAUDE.md module table to suggest file
        scopes for matched templates, turning abstract matches into
        actionable subtasks with file_scope populated.

        Args:
            goal: The goal string to find relevant directories for

        Returns:
            List of up to 5 relevant codebase directory paths
        """
        goal_lower = goal.lower()
        relevant: list[str] = []
        for module, paths in self._CODEBASE_MODULES.items():
            if module in goal_lower:
                relevant.extend(paths)
        return relevant[:5]

    def _ground_to_codebase(self, goal: str, repo_root: str | None = None) -> str:
        """Generate live codebase structure from actual filesystem for goal-relevant modules."""
        from pathlib import Path

        root = Path(repo_root or os.getcwd())
        relevant_dirs = self._score_codebase_relevance(goal)

        lines = ["CODEBASE STRUCTURE (live scan):"]
        for rel_dir in relevant_dirs:
            dir_path = root / rel_dir
            if not dir_path.is_dir():
                continue
            # List top-level .py files in this directory (not recursive to keep it short)
            py_files = sorted(
                f.name for f in dir_path.iterdir() if f.suffix == ".py" and f.is_file()
            )
            if py_files:
                lines.append(f"\n{rel_dir}:")
                for fname in py_files[:20]:  # Cap at 20 files per directory
                    lines.append(f"  - {fname}")
                if len(py_files) > 20:
                    lines.append(f"  ... and {len(py_files) - 20} more")

        if len(lines) == 1:
            # Fallback if no relevant dirs found
            lines.append("  (no matching directories found for this goal)")

        lines.append("\nFILE PATH CONVENTIONS:")
        lines.append("- Python backend: aragora/module/file.py")
        lines.append("- TypeScript frontend: aragora/live/src/components/, aragora/live/src/app/")
        lines.append("- Tests: tests/module/test_file.py")

        return "\n".join(lines)

    # =========================================================================
    # Vague goal expansion (cross-references templates + track configs)
    # =========================================================================

    def _expand_vague_goal(self, goal: str) -> TaskDecomposition | None:
        """Expand a vague goal into concrete subtasks using templates and tracks.

        When a goal like "maximize utility for SMEs" scores low on the heuristic
        complexity check (no file mentions, few keywords), this method cross-
        references deliberation templates and development track configs to
        generate concrete, actionable subtasks.

        Args:
            goal: The vague goal string

        Returns:
            TaskDecomposition with expanded subtasks, or None if expansion
            didn't produce useful results
        """
        subtasks: list[SubTask] = []
        matched_sources: list[str] = []

        # Compute codebase-relevant directories from the goal text
        goal_relevant_paths = self._score_codebase_relevance(goal)

        # 1. Cross-reference against deliberation templates
        try:
            from aragora.deliberation.templates.registry import match_templates

            matched = match_templates(goal, limit=3)
            for i, template in enumerate(matched):
                # Derive file_scope from template tags + codebase module mapping
                tag_paths: list[str] = []
                for tag in template.tags:
                    tag_lower = tag.lower()
                    if tag_lower in self._CODEBASE_MODULES:
                        tag_paths.extend(self._CODEBASE_MODULES[tag_lower])
                # Combine tag-derived paths with goal-derived paths, deduplicate
                combined_paths = list(dict.fromkeys(tag_paths + goal_relevant_paths))[:5]

                subtasks.append(
                    SubTask(
                        id=f"subtask_{len(subtasks) + 1}",
                        title=f"{template.name.replace('_', ' ').title()}",
                        description=(
                            f"{template.description}. "
                            f"Suggested personas: {', '.join(template.personas[:3])}."
                            if template.personas
                            else template.description
                        ),
                        dependencies=[f"subtask_{len(subtasks)}"] if subtasks else [],
                        estimated_complexity="medium",
                        file_scope=combined_paths,
                    )
                )
                matched_sources.append(f"template:{template.name}")
        except ImportError:
            logger.debug("Deliberation templates not available for expansion")

        # 2. Cross-reference against development track configs
        try:
            from aragora.nomic.autonomous_orchestrator import (
                DEFAULT_TRACK_CONFIGS,
                Track,
            )

            goal_lower = goal.lower()
            track_keywords = {
                Track.SME: ["sme", "small business", "dashboard", "user experience", "utility"],
                Track.DEVELOPER: ["sdk", "api", "developer", "documentation", "package"],
                Track.SELF_HOSTED: ["deploy", "docker", "self-hosted", "ops", "backup"],
                Track.QA: ["test", "quality", "coverage", "ci", "reliability"],
                Track.CORE: ["debate", "agent", "consensus", "engine", "core"],
                Track.SECURITY: ["security", "auth", "vulnerability", "harden", "owasp"],
            }
            # Count how many tracks match explicitly
            matched_tracks = [
                track
                for track in DEFAULT_TRACK_CONFIGS
                if any(kw in goal_lower for kw in track_keywords.get(track, []))
            ]
            # If 0-1 tracks match, the goal is so broad it affects all tracks.
            # Strategic terms like "maximize", "improve", "optimize" are
            # inherently cross-cutting — include all tracks.
            broad_terms = {
                "maximize",
                "minimise",
                "minimize",
                "improve",
                "enhance",
                "optimize",
                "optimise",
                "scale",
                "transform",
                "grow",
                "utility",
                "value",
                "business",
            }
            is_broad = any(t in goal_lower for t in broad_terms)
            # Also check if the goal mentions a specific path/directory
            has_path = bool(re.search(r"aragora/\w+|tests/\w+|sdk/\w+|scripts/\w+", goal_lower))
            if len(matched_tracks) == 0 and is_broad and not has_path:
                # Truly broad goal with no specific track or path — all tracks
                tracks_to_expand = list(DEFAULT_TRACK_CONFIGS.keys())[:4]
            elif len(matched_tracks) == 1 and is_broad and not has_path:
                # Broad but slightly focused — matched track + 2 adjacent
                all_tracks = list(DEFAULT_TRACK_CONFIGS.keys())
                idx = all_tracks.index(matched_tracks[0])
                extra = [t for i, t in enumerate(all_tracks) if i != idx][:2]
                tracks_to_expand = matched_tracks + extra
            else:
                tracks_to_expand = matched_tracks

            for track in tracks_to_expand:
                config = DEFAULT_TRACK_CONFIGS[track]
                folders_str = ", ".join(config.folders[:3])
                subtasks.append(
                    SubTask(
                        id=f"subtask_{len(subtasks) + 1}",
                        title=f"Improve {config.name} Track",
                        description=(
                            f"Enhance capabilities in the {config.name} track. "
                            f"Key folders: {folders_str}. "
                            f"Preferred agents: {', '.join(config.agent_types)}."
                        ),
                        dependencies=[],
                        estimated_complexity="medium",
                        file_scope=config.folders[:3],
                    )
                )
                matched_sources.append(f"track:{track.value}")
        except ImportError:
            logger.debug("Track configs not available for expansion")

        # Only return expansion if we found meaningful matches
        if len(subtasks) < 2:
            return None

        # Cap at max_subtasks
        subtasks = subtasks[: self.config.max_subtasks]

        rationale = (
            f"Vague goal expanded via semantic matching (sources: {', '.join(matched_sources)})"
        )

        return TaskDecomposition(
            original_task=goal,
            complexity_score=5,  # Elevated: vague goals are inherently complex
            complexity_level="medium",
            should_decompose=True,
            subtasks=subtasks,
            rationale=rationale,
        )
