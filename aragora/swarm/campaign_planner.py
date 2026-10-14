"""Campaign planning: turn documents or GitHub issues into a persistent campaign manifest.

``CampaignPlanner`` decomposes each source item into dispatch-bounded projects, adds
dependencies between projects whose file scopes overlap, orders them topologically and
can cross-check the plan with a model. ``aragora.swarm.campaign`` re-exports every name
here, so importing from either module yields the same objects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import uuid
from pathlib import Path
from typing import Any, cast

from aragora.agents.base import create_agent
from aragora.nomic.task_decomposer import SubTask, TaskDecomposer
from aragora.swarm.campaign_models import (
    CampaignDependency,
    CampaignManifest,
    CampaignProject,
    CampaignReviewGate,
    _canonical_planner_strategy,
    _canonical_review_model,
)
from aragora.swarm.campaign_state import (
    _extract_json_list,
    _now_iso,
    _refresh_execution_state,
)
from aragora.swarm.spec import SwarmSpec

logger = logging.getLogger(__name__)


def _complexity_cost(label: str) -> float:
    lowered = str(label or "").strip().lower()
    return {"low": 0.5, "medium": 1.0, "moderate": 1.0, "high": 2.0}.get(lowered, 1.0)


def _success_criteria_to_list(success_criteria: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for key, value in sorted(success_criteria.items()):
        text = str(value).strip()
        if text:
            items.append(f"{key}: {text}")
    return items


def _normalized_scope(scope: list[str]) -> list[str]:
    return sorted({str(item).strip() for item in scope if str(item).strip()})


def _parse_source_items(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines()]
    items: list[str] = []
    current: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            if current:
                items.append("\n".join(current).strip())
                current = []
            continue
        if line.startswith(("-", "*")) or line[:2].isdigit() and line[2:3] == ".":
            if current:
                items.append("\n".join(current).strip())
                current = []
            item = line.lstrip("-*0123456789. ").strip()
            if item:
                items.append(item)
            continue
        if line.startswith("#"):
            if current:
                items.append("\n".join(current).strip())
                current = []
            current.append(line.lstrip("# ").strip())
            continue
        current.append(line)
    if current:
        items.append("\n".join(current).strip())
    return [item for item in items if item]


def _gh_json(cmd: list[str]) -> Any:
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=30, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "GitHub command failed")
    return json.loads(proc.stdout)


class CampaignPlanner:
    """Build a persistent campaign manifest from documents or GitHub issues."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        planner_model: str = "claude",
        planner_strategy: str = "heuristic",
        worker_model: str = "codex",
        review_model: str = "claude",
        enforce_cross_model_review: bool = True,
        budget_limit_usd: float = 50.0,
        max_parallel_ready_projects: int = 2,
        decomposer: TaskDecomposer | None = None,
        enable_model_crosscheck: bool = False,
        experiment_id: str | None = None,
        experiment_label: str | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.planner_model = planner_model
        self.planner_strategy = _canonical_planner_strategy(planner_strategy)
        self.worker_model = worker_model
        self.enforce_cross_model_review = bool(enforce_cross_model_review)
        self.review_model = _canonical_review_model(
            worker_model,
            review_model,
            enforce_cross_model_review=self.enforce_cross_model_review,
        )
        self.budget_limit_usd = budget_limit_usd
        self.max_parallel_ready_projects = max(1, int(max_parallel_ready_projects))
        self.decomposer = decomposer or TaskDecomposer()
        self.enable_model_crosscheck = enable_model_crosscheck
        self.experiment_id = experiment_id
        self.experiment_label = experiment_label
        self._planner_fallbacks: list[str] = []

    def plan_from_source_file(self, path: Path) -> CampaignManifest:
        text = path.read_text(encoding="utf-8")
        items = _parse_source_items(text)
        return self.plan_from_items(items, source_kind="source_file", source_ref=str(path))

    def plan_from_issue_list(
        self, issue_numbers: list[int], *, repo: str | None = None
    ) -> CampaignManifest:
        items: list[str] = []
        source_refs: list[str] = []
        for number in issue_numbers:
            cmd = [
                "gh",
                "issue",
                "view",
                str(number),
                "--json",
                "number,title,body,url",
            ]
            if repo:
                cmd.extend(["--repo", repo])
            data = _gh_json(cmd)
            title = str(data.get("title", "")).strip()
            body = str(data.get("body", "")).strip()
            url = str(data.get("url", "")).strip()
            items.append(f"[Issue #{number}] {title}\n\n{body}".strip())
            source_refs.append(url or f"issue:{number}")
        manifest = self.plan_from_items(
            items,
            source_kind="issue_list",
            source_ref=",".join(str(num) for num in issue_numbers),
        )
        for project, source_ref in zip(manifest.projects, source_refs, strict=False):
            if source_ref not in project.source_refs:
                project.source_refs.append(source_ref)
        return manifest

    def plan_from_github_query(self, query: str, *, repo: str | None = None) -> CampaignManifest:
        cmd = [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "100",
            "--search",
            query,
            "--json",
            "number,title,body,url",
        ]
        if repo:
            cmd.extend(["--repo", repo])
        data = _gh_json(cmd)
        items = []
        for item in data:
            if not isinstance(item, dict):
                continue
            items.append(
                f"[Issue #{item.get('number')}] {item.get('title', '')}\n\n{item.get('body', '')}".strip()
            )
        return self.plan_from_items(items, source_kind="github_query", source_ref=query)

    def plan_from_items(
        self, items: list[str], *, source_kind: str, source_ref: str
    ) -> CampaignManifest:
        projects: list[CampaignProject] = []
        source_findings: list[str] = []
        self._planner_fallbacks = []
        source_index = 0
        for item in items:
            source_index += 1
            created = self._projects_from_item(item, source_index)
            if not created:
                source_findings.append(f"Skipped under-specified candidate: {item[:80]}")
                continue
            projects.extend(created)
        source_findings.extend(self._planner_fallbacks)
        self._apply_overlap_dependencies(projects, findings=source_findings)
        projects = self._topological_sort_projects(projects)
        self._renumber_projects(projects)
        crosscheck_findings = self._crosscheck_projects(projects)
        source_findings.extend(crosscheck_findings)
        manifest = CampaignManifest(
            campaign_id=f"campaign-{uuid.uuid4().hex[:12]}",
            created_at=_now_iso(),
            source_kind=source_kind,
            source_ref=source_ref,
            planner_model=self.planner_model,
            planner_strategy=self.planner_strategy,
            worker_model=self.worker_model,
            review_model=self.review_model,
            enforce_cross_model_review=self.enforce_cross_model_review,
            experiment_id=self.experiment_id,
            experiment_label=self.experiment_label,
            max_parallel_ready_projects=self.max_parallel_ready_projects,
            budget_limit_usd=self.budget_limit_usd,
            projects=projects,
            planning_findings=source_findings,
        )
        _refresh_execution_state(manifest)
        return manifest

    def _projects_from_item(self, item: str, source_index: int) -> list[CampaignProject]:
        base_spec = SwarmSpec.from_direct_goal(
            item,
            budget_limit_usd=self.budget_limit_usd,
            requires_approval=True,
            user_expertise="developer",
        )
        if self.planner_strategy == "model":
            try:
                decomposition = self.decomposer.analyze_with_model_sync(
                    item,
                    planner_model=self.planner_model,
                    file_scope_hints=base_spec.file_scope_hints or None,
                    acceptance_criteria=base_spec.acceptance_criteria,
                    constraints=base_spec.constraints,
                )
            except (RuntimeError, ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
                self._planner_fallbacks.append(
                    f"planner fallback to heuristic for source item {source_index}: "
                    f"{type(exc).__name__}: {exc}"
                )
                decomposition = self.decomposer.analyze(item)
        else:
            decomposition = self.decomposer.analyze(item)
        projects: list[CampaignProject] = []
        if decomposition.should_decompose and decomposition.subtasks:
            subtask_id_map: dict[str, str] = {}
            for sub_index, subtask in enumerate(decomposition.subtasks, start=1):
                spec = self._spec_from_subtask(subtask, base_spec)
                if not spec.is_dispatch_bounded():
                    continue
                project_id = f"proj-{source_index:03d}-{sub_index:02d}"
                subtask_id_map[subtask.id] = project_id
                projects.append(
                    CampaignProject(
                        project_id=project_id,
                        title=subtask.title or project_id,
                        source_refs=[f"{source_index}:{subtask.id}"],
                        spec=spec,
                        file_scope_hints=list(spec.file_scope_hints),
                        acceptance_criteria=list(spec.acceptance_criteria),
                        constraints=list(spec.constraints),
                        estimated_cost_usd=_complexity_cost(subtask.estimated_complexity),
                        review=CampaignReviewGate(
                            required=True,
                            review_model=self.review_model,
                        ),
                    )
                )
            for project, subtask in zip(projects, decomposition.subtasks, strict=False):
                project.dependencies = [
                    CampaignDependency(project_id=subtask_id_map[dep], reason="subtask_dependency")
                    for dep in subtask.dependencies
                    if dep in subtask_id_map
                ]
            if projects:
                return projects

        if not base_spec.is_dispatch_bounded():
            return []
        return [
            CampaignProject(
                project_id=f"proj-{source_index:03d}",
                title=item.splitlines()[0][:120],
                source_refs=[f"{source_index}"],
                spec=base_spec,
                file_scope_hints=list(base_spec.file_scope_hints),
                acceptance_criteria=list(base_spec.acceptance_criteria),
                constraints=list(base_spec.constraints),
                estimated_cost_usd=_complexity_cost(decomposition.complexity_level),
                review=CampaignReviewGate(required=True, review_model=self.review_model),
            )
        ]

    def _spec_from_subtask(self, subtask: SubTask, base_spec: SwarmSpec) -> SwarmSpec:
        criteria = _success_criteria_to_list(subtask.success_criteria)
        if not criteria:
            criteria = [f"Complete bounded task: {subtask.title}"]
        return SwarmSpec(
            raw_goal=subtask.description or base_spec.raw_goal,
            refined_goal=subtask.title or subtask.description or base_spec.refined_goal,
            acceptance_criteria=criteria,
            constraints=list(base_spec.constraints),
            budget_limit_usd=base_spec.budget_limit_usd,
            file_scope_hints=_normalized_scope(subtask.file_scope or base_spec.file_scope_hints),
            work_orders=[],
            estimated_complexity=subtask.estimated_complexity or "medium",
            requires_approval=True,
            user_expertise="developer",
        )

    def _apply_overlap_dependencies(
        self, projects: list[CampaignProject], *, findings: list[str]
    ) -> None:
        for index, project in enumerate(projects):
            current_scope = set(project.file_scope_hints)
            if not current_scope:
                continue
            for later in projects[index + 1 :]:
                overlap = sorted(current_scope & set(later.file_scope_hints))
                if not overlap:
                    continue
                existing = {dep.project_id for dep in later.dependencies}
                if project.project_id in existing:
                    continue
                later.dependencies.append(
                    CampaignDependency(
                        project_id=project.project_id,
                        reason=f"file_scope_overlap:{', '.join(overlap[:3])}",
                    )
                )
                findings.append(
                    f"Added dependency {later.project_id} -> {project.project_id} due to overlapping scope."
                )

    def _topological_sort_projects(self, projects: list[CampaignProject]) -> list[CampaignProject]:
        by_id = {project.project_id: project for project in projects}
        incoming = {
            project.project_id: {
                dep.project_id for dep in project.dependencies if dep.project_id in by_id
            }
            for project in projects
        }
        ready = [project.project_id for project in projects if not incoming[project.project_id]]
        ordered: list[CampaignProject] = []
        while ready:
            ready.sort()
            project_id = ready.pop(0)
            ordered.append(by_id[project_id])
            for other_id, deps in incoming.items():
                if project_id in deps:
                    deps.remove(project_id)
                    if not deps and by_id[other_id] not in ordered and other_id not in ready:
                        ready.append(other_id)
        leftovers = [project for project in projects if project not in ordered]
        return ordered + sorted(leftovers, key=lambda item: item.project_id)

    def _crosscheck_projects(self, projects: list[CampaignProject]) -> list[str]:
        findings: list[str] = []
        for project in projects:
            if not project.acceptance_criteria:
                findings.append(f"{project.project_id} has no acceptance criteria.")
        if self.enable_model_crosscheck:
            prompt = {
                "projects": [
                    {
                        "project_id": project.project_id,
                        "title": project.title,
                        "dependencies": [dep.to_dict() for dep in project.dependencies],
                        "file_scope_hints": project.file_scope_hints,
                        "acceptance_criteria": project.acceptance_criteria,
                    }
                    for project in projects
                ]
            }
            try:
                agent = cast(Any, create_agent)(
                    self.review_model,
                    name="campaign-crosscheck",
                    role="critic",
                )
                response = asyncio.run(agent.generate(json.dumps(prompt, sort_keys=True)))
                for finding in _extract_json_list(response):
                    findings.append(f"crosscheck: {finding}")
            except (RuntimeError, ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
                logger.debug("campaign_crosscheck_fallback: %s", exc)
        return findings

    @staticmethod
    def _renumber_projects(projects: list[CampaignProject]) -> None:
        id_map = {
            project.project_id: f"proj-{index:03d}"
            for index, project in enumerate(projects, start=1)
        }
        for project in projects:
            project.project_id = id_map[project.project_id]
        for project in projects:
            for dependency in project.dependencies:
                if dependency.project_id in id_map:
                    dependency.project_id = id_map[dependency.project_id]
