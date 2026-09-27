"""Persistent campaign planning and execution on top of the Boss loop."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from collections.abc import Generator
from typing import Any, cast

from aragora.agents.base import create_agent
from aragora.agents.errors import AgentConnectionError, CLISubprocessError
from aragora.nomic.pipeline_bridge import NomicPipelineBridge
from aragora.swarm.lane_telemetry import LaneTelemetryCollector, LaneTelemetryRecord
from aragora.nomic.task_decomposer import SubTask, TaskDecomposer
from aragora.swarm.boss_loop import (
    _extract_deliverable,
    dispatch_bounded_spec,
)
from aragora.swarm.review_routing import ReviewRoutingError, generate_review_response
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.supervisor import (
    CAMPAIGN_OUTCOME_METADATA_KEY,
    CAMPAIGN_REQUEUE_ELIGIBLE_METADATA_KEY,
    SwarmSupervisor,
    WorkerOutcome,
)
from aragora.swarm.terminal_truth import collect_run_blockers, qualify_run_terminal_state
from aragora.swarm.worker_launcher import MAX_WORKER_LOG_TAIL_CHARS, WorkerLauncher

logger = logging.getLogger(__name__)

UTC = timezone.utc
_LANE_TELEMETRY = LaneTelemetryCollector()
DEFAULT_CAMPAIGN_MANIFEST = ".aragora/campaign_manifest.yaml"
_BUDGET_EPSILON = 1e-9


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


def _coerce_boolish(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


# Statuses that represent terminal project transitions (no further retries).
# Receipt emission fires only for these statuses.
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "completed",
        "failed",
        "stalled",
        "blocked",
        "skipped",
    }
)


class CampaignProjectStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    ACTIVE = "active"
    DELIVERED = "delivered"
    WAITING_FOR_PR = "waiting_for_pr"
    WAITING_FOR_MERGE = "waiting_for_merge"
    NEEDS_REVISION = "needs_revision"
    COMPLETED = "completed"
    FAILED = "failed"
    STALLED = "stalled"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class CampaignRunOutcome(str, Enum):
    DELIVERABLE_CREATED = "deliverable_created"
    PR_ADOPTED = "pr_adopted"
    CLEAN_EXIT_NO_DELIVERABLE = "clean_exit_no_deliverable"
    STALLED = "stalled"
    NEEDS_HUMAN = "needs_human"
    TIMEOUT = "timeout"
    CRASH = "crash"
    BLOCKED = "blocked"


class CampaignStopReason(str, Enum):
    STILL_RUNNING = "still_running"
    CAMPAIGN_COMPLETE = "campaign_complete"
    CAMPAIGN_STALLED = "campaign_stalled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIME_LIMIT_EXCEEDED = "time_limit_exceeded"
    CAMPAIGN_BLOCKED = "campaign_blocked"


class CampaignReviewStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    CHANGES_REQUESTED = "changes_requested"
    BLOCKED_NONREVIEWABLE = "blocked_nonreviewable"


@dataclass(slots=True)
class CampaignDependency:
    project_id: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CampaignDependency:
        return cls(
            project_id=str(data.get("project_id", "")).strip(),
            reason=str(data.get("reason", "")).strip(),
        )


@dataclass(slots=True)
class CampaignReviewGate:
    required: bool = True
    review_model: str = "claude"
    status: str = CampaignReviewStatus.PENDING.value
    findings: list[str] = field(default_factory=list)
    reviewed_at: str | None = None
    raw_review: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "review_model": self.review_model,
            "status": self.status,
            "findings": list(self.findings),
            "reviewed_at": self.reviewed_at,
            "raw_review": dict(self.raw_review),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CampaignReviewGate:
        data = data or {}
        return cls(
            required=bool(data.get("required", True)),
            review_model=str(data.get("review_model", "claude")).strip() or "claude",
            status=str(data.get("status", CampaignReviewStatus.PENDING.value)).strip()
            or CampaignReviewStatus.PENDING.value,
            findings=[str(item) for item in data.get("findings", []) if str(item).strip()],
            reviewed_at=_optional_text(data.get("reviewed_at")),
            raw_review=dict(data.get("raw_review") or {}),
        )


@dataclass(slots=True)
class CampaignExecutionState:
    ready_queue: list[str] = field(default_factory=list)
    active_projects: list[str] = field(default_factory=list)
    completed_projects: list[str] = field(default_factory=list)
    failed_projects: list[str] = field(default_factory=list)
    skipped_projects: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    reserved_cost_usd: float = 0.0
    last_run_at: str | None = None
    last_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_queue": list(self.ready_queue),
            "active_projects": list(self.active_projects),
            "completed_projects": list(self.completed_projects),
            "failed_projects": list(self.failed_projects),
            "skipped_projects": list(self.skipped_projects),
            "total_cost_usd": self.total_cost_usd,
            "reserved_cost_usd": self.reserved_cost_usd,
            "last_run_at": self.last_run_at,
            "last_result": dict(self.last_result),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CampaignExecutionState:
        data = data or {}
        return cls(
            ready_queue=[str(item) for item in data.get("ready_queue", []) if str(item).strip()],
            active_projects=[
                str(item) for item in data.get("active_projects", []) if str(item).strip()
            ],
            completed_projects=[
                str(item) for item in data.get("completed_projects", []) if str(item).strip()
            ],
            failed_projects=[
                str(item) for item in data.get("failed_projects", []) if str(item).strip()
            ],
            skipped_projects=[
                str(item) for item in data.get("skipped_projects", []) if str(item).strip()
            ],
            total_cost_usd=float(data.get("total_cost_usd", 0.0) or 0.0),
            reserved_cost_usd=float(data.get("reserved_cost_usd", 0.0) or 0.0),
            last_run_at=str(data.get("last_run_at", "")).strip() or None,
            last_result=dict(data.get("last_result") or {}),
        )


@dataclass(slots=True)
class CampaignProject:
    project_id: str
    title: str
    source_refs: list[str] = field(default_factory=list)
    milestone: str | None = None
    spec: SwarmSpec = field(default_factory=SwarmSpec)
    file_scope_hints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    dependencies: list[CampaignDependency] = field(default_factory=list)
    feature_flag: str | None = None
    feature_flag_required: bool = False
    estimated_cost_usd: float = 0.0
    status: str = CampaignProjectStatus.PENDING.value
    retry_count: int = 0
    last_run_outcome: str | None = None
    run_id: str | None = None
    worker_receipt_id: str | None = None
    receipt_id: str | None = None
    pr_url: str | None = None
    adopted_pr: str | None = None
    branch: str | None = None
    commit_shas: list[str] = field(default_factory=list)
    attempt_history: list[dict[str, Any]] = field(default_factory=list)
    review: CampaignReviewGate = field(default_factory=CampaignReviewGate)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "source_refs": list(self.source_refs),
            "milestone": self.milestone,
            "spec": self.spec.to_dict(),
            "file_scope_hints": list(self.file_scope_hints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "constraints": list(self.constraints),
            "dependencies": [item.to_dict() for item in self.dependencies],
            "feature_flag": self.feature_flag,
            "feature_flag_required": self.feature_flag_required,
            "estimated_cost_usd": self.estimated_cost_usd,
            "status": self.status,
            "retry_count": self.retry_count,
            "last_run_outcome": self.last_run_outcome,
            "run_id": self.run_id,
            "worker_receipt_id": self.worker_receipt_id,
            "receipt_id": self.receipt_id,
            "pr_url": self.pr_url,
            "adopted_pr": self.adopted_pr,
            "branch": self.branch,
            "commit_shas": list(self.commit_shas),
            "attempt_history": [dict(item) for item in self.attempt_history],
            "review": self.review.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CampaignProject:
        return cls(
            project_id=str(data.get("project_id", "")).strip(),
            title=str(data.get("title", "")).strip(),
            source_refs=[str(item) for item in data.get("source_refs", []) if str(item).strip()],
            milestone=_optional_text(data.get("milestone")),
            spec=SwarmSpec.from_dict(dict(data.get("spec") or {})),
            file_scope_hints=[
                str(item) for item in data.get("file_scope_hints", []) if str(item).strip()
            ],
            acceptance_criteria=[
                str(item) for item in data.get("acceptance_criteria", []) if str(item).strip()
            ],
            constraints=[str(item) for item in data.get("constraints", []) if str(item).strip()],
            dependencies=[
                CampaignDependency.from_dict(item)
                for item in data.get("dependencies", [])
                if isinstance(item, dict)
            ],
            feature_flag=_optional_text(data.get("feature_flag")),
            feature_flag_required=_coerce_boolish(
                data.get("feature_flag_required"),
                default=False,
            ),
            estimated_cost_usd=float(data.get("estimated_cost_usd", 0.0) or 0.0),
            status=str(data.get("status", CampaignProjectStatus.PENDING.value)).strip()
            or CampaignProjectStatus.PENDING.value,
            retry_count=int(data.get("retry_count", 0) or 0),
            last_run_outcome=_optional_text(data.get("last_run_outcome")),
            run_id=_optional_text(data.get("run_id")),
            worker_receipt_id=_optional_text(data.get("worker_receipt_id")),
            receipt_id=_optional_text(data.get("receipt_id")),
            pr_url=_optional_text(data.get("pr_url")),
            adopted_pr=_optional_text(data.get("adopted_pr")),
            branch=_optional_text(data.get("branch")),
            commit_shas=[str(item) for item in data.get("commit_shas", []) if str(item).strip()],
            attempt_history=[
                dict(item) for item in data.get("attempt_history", []) if isinstance(item, dict)
            ],
            review=CampaignReviewGate.from_dict(data.get("review")),
        )


@dataclass(slots=True)
class CampaignManifest:
    campaign_id: str
    created_at: str
    source_kind: str
    source_ref: str
    planner_model: str = "claude"
    planner_strategy: str = "heuristic"
    worker_model: str = "codex"
    review_model: str = "claude"
    enforce_cross_model_review: bool = True
    experiment_id: str | None = None
    experiment_label: str | None = None
    max_parallel_ready_projects: int = 2
    max_retries_per_project: int = 2
    budget_limit_usd: float = 50.0
    time_limit_hours: float = 8.0
    projects: list[CampaignProject] = field(default_factory=list)
    execution_state: CampaignExecutionState = field(default_factory=CampaignExecutionState)
    planning_findings: list[str] = field(default_factory=list)
    manifest_version: int = 1

    def __post_init__(self) -> None:
        self.planner_strategy = _canonical_planner_strategy(self.planner_strategy)
        self.review_model = _canonical_review_model(
            self.worker_model,
            self.review_model,
            enforce_cross_model_review=self.enforce_cross_model_review,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "planner_model": self.planner_model,
            "planner_strategy": self.planner_strategy,
            "worker_model": self.worker_model,
            "review_model": self.review_model,
            "enforce_cross_model_review": self.enforce_cross_model_review,
            "experiment_id": self.experiment_id,
            "experiment_label": self.experiment_label,
            "max_parallel_ready_projects": self.max_parallel_ready_projects,
            "max_retries_per_project": self.max_retries_per_project,
            "budget_limit_usd": self.budget_limit_usd,
            "time_limit_hours": self.time_limit_hours,
            "projects": [project.to_dict() for project in self.projects],
            "execution_state": self.execution_state.to_dict(),
            "planning_findings": list(self.planning_findings),
            "manifest_version": self.manifest_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CampaignManifest:
        planner_model = str(data.get("planner_model", "claude")).strip() or "claude"
        planner_strategy = _canonical_planner_strategy(data.get("planner_strategy"))
        worker_model = str(data.get("worker_model", "codex")).strip() or "codex"
        enforce_cross_model_review = bool(data.get("enforce_cross_model_review", True))
        review_model = _canonical_review_model(
            worker_model,
            str(data.get("review_model", "claude")).strip() or "claude",
            enforce_cross_model_review=enforce_cross_model_review,
        )
        return cls(
            campaign_id=str(data.get("campaign_id", "")).strip(),
            created_at=str(data.get("created_at", "")).strip(),
            source_kind=str(data.get("source_kind", "")).strip(),
            source_ref=str(data.get("source_ref", "")).strip(),
            planner_model=planner_model,
            planner_strategy=planner_strategy,
            worker_model=worker_model,
            review_model=review_model,
            enforce_cross_model_review=enforce_cross_model_review,
            experiment_id=_optional_text(data.get("experiment_id")),
            experiment_label=_optional_text(data.get("experiment_label")),
            max_parallel_ready_projects=max(
                1, int(data.get("max_parallel_ready_projects", 2) or 2)
            ),
            max_retries_per_project=max(0, int(data.get("max_retries_per_project", 2) or 2)),
            budget_limit_usd=float(data.get("budget_limit_usd", 50.0) or 50.0),
            time_limit_hours=float(data.get("time_limit_hours", 8.0) or 8.0),
            projects=[
                CampaignProject.from_dict(item)
                for item in data.get("projects", [])
                if isinstance(item, dict)
            ],
            execution_state=CampaignExecutionState.from_dict(data.get("execution_state")),
            planning_findings=[
                str(item) for item in data.get("planning_findings", []) if str(item).strip()
            ],
            manifest_version=int(data.get("manifest_version", 1) or 1),
        )

    def to_yaml(self) -> str:
        data = self.to_dict()
        try:
            import yaml

            return yaml.safe_dump(data, sort_keys=True, allow_unicode=False)
        except ImportError:
            return json.dumps(data, indent=2, sort_keys=True)

    @classmethod
    def from_text(cls, text: str) -> CampaignManifest:
        try:
            import yaml

            loaded = yaml.safe_load(text) or {}
        except ImportError:
            loaded = json.loads(text)
        if not isinstance(loaded, dict):
            raise ValueError("Campaign manifest must deserialize to an object.")
        return cls.from_dict(loaded)

    def project_map(self) -> dict[str, CampaignProject]:
        return {project.project_id: project for project in self.projects}


@contextlib.contextmanager
def locked_manifest_path(path: Path) -> Generator[None, None, None]:
    """Hold an exclusive lock around manifest operations."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        handle.close()


def load_campaign_manifest(path: Path) -> CampaignManifest:
    text = path.read_text(encoding="utf-8")
    manifest = CampaignManifest.from_text(text)
    _validate_campaign_manifest(manifest)
    return manifest


def save_campaign_manifest(path: Path, manifest: CampaignManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.to_yaml(), encoding="utf-8")


def _validate_campaign_manifest(manifest: CampaignManifest) -> None:
    if not manifest.campaign_id:
        raise ValueError("Campaign manifest is missing campaign_id.")
    if not manifest.source_kind:
        raise ValueError("Campaign manifest is missing source_kind.")
    seen: set[str] = set()
    for project in manifest.projects:
        if not project.project_id:
            raise ValueError("Campaign manifest contains a project without project_id.")
        if project.project_id in seen:
            raise ValueError(
                f"Campaign manifest contains duplicate project_id {project.project_id}."
            )
        seen.add(project.project_id)
        if not project.spec.is_dispatch_bounded():
            raise ValueError(f"Project {project.project_id} is not dispatch-bounded.")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_planner_strategy(value: Any) -> str:
    strategy = str(value or "heuristic").strip().lower()
    return "model" if strategy == "model" else "heuristic"


def _canonical_review_model(
    worker_model: str,
    requested: str | None = None,
    *,
    enforce_cross_model_review: bool = True,
) -> str:
    candidate = str(requested or "").strip() or ("claude" if worker_model == "codex" else "codex")
    if enforce_cross_model_review and candidate == worker_model:
        return "claude" if worker_model == "codex" else "codex"
    return candidate


def _complexity_cost(label: str) -> float:
    lowered = str(label or "").strip().lower()
    return {"low": 0.5, "medium": 1.0, "moderate": 1.0, "high": 2.0}.get(lowered, 1.0)


def _project_estimated_cost(project: CampaignProject) -> float:
    return max(0.0, float(project.estimated_cost_usd or 0.0))


def _campaign_budget_snapshot(manifest: CampaignManifest) -> dict[str, float | bool]:
    spent = max(0.0, float(manifest.execution_state.total_cost_usd or 0.0))
    reserved = sum(
        _project_estimated_cost(project)
        for project in manifest.projects
        if project.status == CampaignProjectStatus.ACTIVE.value
    )
    limit = max(0.0, float(manifest.budget_limit_usd or 0.0))
    committed = spent + reserved
    available = max(0.0, limit - committed)
    return {
        "budget_limit_usd": round(limit, 4),
        "spent_cost_usd": round(spent, 4),
        "reserved_cost_usd": round(reserved, 4),
        "committed_cost_usd": round(committed, 4),
        "available_budget_usd": round(available, 4),
        "budget_exhausted": bool(available <= _BUDGET_EPSILON),
    }


def _dispatchable_projects(manifest: CampaignManifest) -> list[CampaignProject]:
    completed = {
        project.project_id
        for project in manifest.projects
        if project.status == CampaignProjectStatus.COMPLETED.value
    }
    candidates: list[CampaignProject] = []
    for project in manifest.projects:
        if project.status not in {
            CampaignProjectStatus.PENDING.value,
            CampaignProjectStatus.READY.value,
            CampaignProjectStatus.NEEDS_REVISION.value,
        }:
            continue
        if project.retry_count > manifest.max_retries_per_project:
            continue
        deps = {dep.project_id for dep in project.dependencies}
        if deps.issubset(completed):
            candidates.append(project)
    return candidates


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


_DIFF_MAX_CHARS = 50_000


def _fetch_diff_content(
    run_dict: dict[str, Any],
    *,
    repo_root: Path | None = None,
    target_branch: str = "main",
    max_chars: int = _DIFF_MAX_CHARS,
) -> str | None:
    """Fetch the actual git diff between the worker branch and the target branch.

    Returns the diff text (truncated to *max_chars*), or ``None`` if the diff
    cannot be obtained (missing branch, no repo_root, git error).
    """
    if repo_root is None:
        return None
    deliverable = _extract_deliverable(run_dict)
    if not deliverable or deliverable.get("type") not in ("branch", "pr"):
        return None
    branch = deliverable.get("branch")
    if not branch:
        # For PR-type deliverables, try extracting the branch from work orders.
        for wo in run_dict.get("work_orders", []):
            if isinstance(wo, dict) and str(wo.get("branch", "")).strip():
                branch = str(wo["branch"]).strip()
                break
    if not branch:
        return None
    # Use origin/ prefix to avoid stale local refs in worktrees.
    diff_base = target_branch if "/" in target_branch else f"origin/{target_branch}"
    try:
        # Fetch to ensure the remote ref is current.
        subprocess.run(
            ["git", "fetch", "origin", target_branch],
            capture_output=True,
            cwd=str(repo_root),
            timeout=15,
        )
        result = subprocess.run(
            ["git", "diff", f"{diff_base}...{branch}"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=30,
        )
        if result.returncode != 0:
            logger.debug("_fetch_diff_content git diff failed: %s", result.stderr)
            return None
        diff = result.stdout
        if len(diff) > max_chars:
            diff = diff[:max_chars] + f"\n\n... [truncated at {max_chars} chars]"
        return diff if diff.strip() else None
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("_fetch_diff_content error: %s", exc)
        return None


class CampaignReviewer:
    """Blocking heterogeneous review gate for completed campaign projects."""

    async def review(
        self,
        *,
        project: CampaignProject,
        worker_model: str,
        review_model: str,
        enforce_cross_model_review: bool = True,
        run_dict: dict[str, Any],
        budget_context: dict[str, Any] | None = None,
        repo_root: Path | None = None,
        target_branch: str = "main",
    ) -> CampaignReviewGate:
        chosen_review_model = _canonical_review_model(
            worker_model,
            review_model,
            enforce_cross_model_review=enforce_cross_model_review,
        )
        diff_content = _fetch_diff_content(
            run_dict, repo_root=repo_root, target_branch=target_branch
        )
        prompt = self._build_prompt(
            project,
            run_dict,
            chosen_review_model,
            diff_content=diff_content,
            budget_context=budget_context,
        )
        try:
            routing = await generate_review_response(
                prompt,
                worker_model=worker_model,
                preferred_review_model=chosen_review_model,
                repo_root=(repo_root or Path.cwd()).resolve(),
            )
            raw = str(routing.get("response", "")).strip()
            parsed = _extract_first_json_object(raw)
            status = str(parsed.get("status", "")).strip().lower()
            findings = [str(item) for item in parsed.get("findings", []) if str(item).strip()]
            if status not in {
                CampaignReviewStatus.PASSED.value,
                CampaignReviewStatus.CHANGES_REQUESTED.value,
                CampaignReviewStatus.BLOCKED_NONREVIEWABLE.value,
            }:
                status = CampaignReviewStatus.BLOCKED_NONREVIEWABLE.value
                findings = findings or ["Review model returned an invalid decision payload."]
            return CampaignReviewGate(
                required=True,
                review_model=chosen_review_model,
                status=status,
                findings=findings,
                reviewed_at=_now_iso(),
                raw_review={
                    "response": raw,
                    "routing": {
                        "candidate": routing.get("candidate"),
                        "attempts": routing.get("attempts", []),
                    },
                },
            )
        except ReviewRoutingError as exc:
            logger.warning("review routing failed for project %s: %s", project.project_id, exc)
            if exc.category == "billing_exhausted":
                detail = (
                    "CLI subscription usage exhausted. "
                    "Run 'claude auth status' to check the active account, "
                    "then 'claude auth logout && claude auth login' to switch "
                    "to an account with available capacity."
                )
                findings = [f"Review blocked (billing): {detail}"]
            else:
                findings = [
                    "Review blocked: no configured reviewer candidate succeeded. Check logs for detail."
                ]
            return CampaignReviewGate(
                required=True,
                review_model=chosen_review_model,
                status=CampaignReviewStatus.BLOCKED_NONREVIEWABLE.value,
                findings=findings,
                reviewed_at=_now_iso(),
                raw_review={
                    "error": type(exc).__name__,
                    "detail": exc.public_message,
                    "attempts": exc.attempts,
                },
            )
        except CLISubprocessError as exc:
            error_str = str(exc).lower()
            is_billing = any(
                p in error_str
                for p in ("credit balance", "billing", "payment required", "purchase credits")
            )
            if is_billing:
                detail = (
                    "CLI subscription usage exhausted. "
                    "Run 'claude auth status' to check the active account, "
                    "then 'claude auth logout && claude auth login' to switch "
                    "to an account with available capacity."
                )
                findings = [f"Review blocked (billing): {detail}"]
            else:
                findings = [f"Review failed: {type(exc).__name__}"]
            return CampaignReviewGate(
                required=True,
                review_model=chosen_review_model,
                status=CampaignReviewStatus.BLOCKED_NONREVIEWABLE.value,
                findings=findings,
                reviewed_at=_now_iso(),
                raw_review={"error": type(exc).__name__, "detail": str(exc)[:500]},
            )
        except (
            AgentConnectionError,
            RuntimeError,
            ValueError,
            OSError,
            KeyError,
            TypeError,
        ) as exc:
            return CampaignReviewGate(
                required=True,
                review_model=chosen_review_model,
                status=CampaignReviewStatus.BLOCKED_NONREVIEWABLE.value,
                findings=[f"Review failed: {type(exc).__name__}"],
                reviewed_at=_now_iso(),
                raw_review={"error": type(exc).__name__, "detail": str(exc)[:500]},
            )

    @staticmethod
    def _build_prompt(
        project: CampaignProject,
        run_dict: dict[str, Any],
        review_model: str,
        *,
        diff_content: str | None = None,
        budget_context: dict[str, Any] | None = None,
    ) -> str:
        deliverable = _extract_deliverable(run_dict)
        work_orders = run_dict.get("work_orders", [])
        summary = {
            "review_model": review_model,
            "project_id": project.project_id,
            "title": project.title,
            "acceptance_criteria": project.acceptance_criteria,
            "file_scope_hints": project.file_scope_hints,
            "budget": dict(
                budget_context or {"project_estimated_cost_usd": project.estimated_cost_usd}
            ),
            "deliverable": deliverable,
            "work_orders": work_orders,
        }
        parts = [
            "Review this completed implementation against the project specification.\n"
            "Respond with strict JSON only: "
            '{"status":"passed|changes_requested|blocked_nonreviewable","findings":["..."]}'
        ]
        if diff_content:
            parts.append(
                f"\n\n--- ACTUAL DIFF (worker branch vs base) ---\n{diff_content}\n--- END DIFF ---"
            )
        parts.append(json.dumps(summary, sort_keys=True))
        return "\n".join(parts)


class CampaignExecutor:
    """Replay-safe campaign executor for one invocation."""

    def __init__(
        self,
        *,
        manifest_path: Path,
        repo_root: Path | None = None,
        target_branch: str = "main",
        reviewer: CampaignReviewer | None = None,
        decomposer: TaskDecomposer | None = None,
        bridge: NomicPipelineBridge | None = None,
    ) -> None:
        self.manifest_path = manifest_path.resolve()
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.target_branch = target_branch
        self.reviewer = reviewer or CampaignReviewer()
        self.decomposer = decomposer or TaskDecomposer()
        self.bridge = bridge or NomicPipelineBridge(repo_path=self.repo_root)

    async def execute_once(self) -> dict[str, Any]:
        await self._reconcile_delivered_projects()
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            self._reconcile_active_projects(manifest)
            _refresh_execution_state(manifest)
            stop_reason = _compute_stop_reason(manifest)
            if stop_reason != CampaignStopReason.STILL_RUNNING.value:
                budget_snapshot = _campaign_budget_snapshot(manifest)
                blocked_projects: list[str] = []
                if stop_reason == CampaignStopReason.BUDGET_EXHAUSTED.value:
                    available_budget = float(budget_snapshot["available_budget_usd"])
                    blocked_projects = [
                        project.project_id
                        for project in _dispatchable_projects(manifest)
                        if _project_estimated_cost(project) > available_budget + _BUDGET_EPSILON
                    ]
                manifest.execution_state.last_run_at = _now_iso()
                manifest.execution_state.last_result = {
                    "stop_reason": stop_reason,
                    "dispatched_projects": [],
                    "budget": budget_snapshot,
                    "merge_ready_projects": _merge_ready_projects(
                        manifest, target_branch=self.target_branch
                    ),
                }
                if blocked_projects:
                    manifest.execution_state.last_result["budget_blocked_projects"] = (
                        blocked_projects
                    )
                _refresh_execution_state(manifest)
                save_campaign_manifest(self.manifest_path, manifest)
                return manifest.execution_state.last_result

            ready = self._ready_projects(manifest)
            active_count = len(
                [
                    project
                    for project in manifest.projects
                    if project.status == CampaignProjectStatus.ACTIVE.value
                ]
            )
            capacity = max(0, manifest.max_parallel_ready_projects - active_count)
            budget_snapshot = _campaign_budget_snapshot(manifest)
            if capacity <= 0:
                manifest.execution_state.last_result = {
                    "stop_reason": CampaignStopReason.STILL_RUNNING.value,
                    "dispatched_projects": [],
                    "budget": budget_snapshot,
                    "merge_ready_projects": _merge_ready_projects(
                        manifest, target_branch=self.target_branch
                    ),
                }
                _refresh_execution_state(manifest)
                save_campaign_manifest(self.manifest_path, manifest)
                return manifest.execution_state.last_result

            selected_projects, budget_blocked_ids = self._select_projects_for_dispatch(
                manifest,
                ready,
                capacity=capacity,
            )
            selected_ids = [project.project_id for project in selected_projects]
            if not selected_ids and not ready:
                # No ready projects: distinguish "waiting for in-flight" from "truly blocked"
                if active_count > 0:
                    stop_reason = CampaignStopReason.STILL_RUNNING.value
                else:
                    stop_reason = CampaignStopReason.CAMPAIGN_BLOCKED.value
                manifest.execution_state.last_result = {
                    "stop_reason": stop_reason,
                    "dispatched_projects": [],
                    "budget": budget_snapshot,
                    "merge_ready_projects": _merge_ready_projects(
                        manifest, target_branch=self.target_branch
                    ),
                }
                _refresh_execution_state(manifest)
                save_campaign_manifest(self.manifest_path, manifest)
                return manifest.execution_state.last_result
            if not selected_ids:
                stop_reason = (
                    CampaignStopReason.STILL_RUNNING.value
                    if active_count > 0
                    else CampaignStopReason.BUDGET_EXHAUSTED.value
                )
                manifest.execution_state.last_result = {
                    "stop_reason": stop_reason,
                    "dispatched_projects": [],
                    "budget": budget_snapshot,
                    "budget_blocked_projects": budget_blocked_ids,
                    "merge_ready_projects": _merge_ready_projects(
                        manifest, target_branch=self.target_branch
                    ),
                }
                _refresh_execution_state(manifest)
                save_campaign_manifest(self.manifest_path, manifest)
                return manifest.execution_state.last_result
            for project in manifest.projects:
                if project.project_id in selected_ids:
                    project.status = CampaignProjectStatus.ACTIVE.value
                    project.review.status = CampaignReviewStatus.PENDING.value
            manifest.execution_state.last_run_at = _now_iso()
            manifest.execution_state.last_result = {
                "stop_reason": CampaignStopReason.STILL_RUNNING.value,
                "dispatched_projects": list(selected_ids),
                "budget": _campaign_budget_snapshot(manifest),
                "merge_ready_projects": _merge_ready_projects(
                    manifest, target_branch=self.target_branch
                ),
            }
            _refresh_execution_state(manifest)
            save_campaign_manifest(self.manifest_path, manifest)

        dispatched = await asyncio.gather(
            *(self._execute_project_id(project_id) for project_id in selected_ids)
        )

        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            manifest.execution_state.last_run_at = _now_iso()
            manifest.execution_state.last_result = {
                "stop_reason": _compute_stop_reason(manifest),
                "dispatched_projects": dispatched,
                "budget": _campaign_budget_snapshot(manifest),
                "merge_ready_projects": _merge_ready_projects(
                    manifest, target_branch=self.target_branch
                ),
            }
            _refresh_execution_state(manifest)
            save_campaign_manifest(self.manifest_path, manifest)
            return manifest.execution_state.last_result

    async def _reconcile_delivered_projects(self) -> None:
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            pending_ids = [
                project.project_id
                for project in manifest.projects
                if project.status == CampaignProjectStatus.DELIVERED.value
                and project.run_id
                and project.review.status == CampaignReviewStatus.PENDING.value
            ]

        for project_id in pending_ids:
            await self._reconcile_delivered_project(project_id)

    async def _reconcile_delivered_project(self, project_id: str) -> None:
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            project = manifest.project_map().get(project_id)
            if (
                project is None
                or project.status != CampaignProjectStatus.DELIVERED.value
                or not project.run_id
                or project.review.status != CampaignReviewStatus.PENDING.value
            ):
                return
            run_id = str(project.run_id).strip()
            worker_model = manifest.worker_model
            review_model = manifest.review_model
            enforce_cross_model_review = manifest.enforce_cross_model_review

        run_dict = self._refresh_run_dict(run_id)
        if not run_dict:
            return

        gate = self._review_gate_from_run_metadata(
            run_dict,
            review_model=review_model,
        )
        if gate is None:
            with locked_manifest_path(self.manifest_path):
                manifest = load_campaign_manifest(self.manifest_path)
                project = manifest.project_map().get(project_id)
                if project is None:
                    return
                budget_context = self._review_budget_context(manifest, project)
            gate = await self.reviewer.review(
                project=project,
                worker_model=worker_model,
                review_model=review_model,
                enforce_cross_model_review=enforce_cross_model_review,
                run_dict=dict(run_dict),
                budget_context=budget_context,
                repo_root=self.repo_root,
                target_branch=self.target_branch,
            )

        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            project = manifest.project_map().get(project_id)
            if (
                project is None
                or project.status != CampaignProjectStatus.DELIVERED.value
                or project.review.status != CampaignReviewStatus.PENDING.value
            ):
                return
            self._hydrate_project_deliverable(project, run_dict)
            project.review = gate
            self._apply_review_result(manifest, project, gate, run_dict=dict(run_dict))
            _refresh_execution_state(manifest)
            save_campaign_manifest(self.manifest_path, manifest)

    @staticmethod
    def _hydrate_project_deliverable(project: CampaignProject, run_dict: dict[str, Any]) -> None:
        deliverable = _extract_deliverable(run_dict)
        if deliverable:
            if deliverable.get("type") == "pr":
                project.pr_url = str(deliverable.get("pr_url", "")).strip() or project.pr_url
            elif deliverable.get("type") == "adopted_pr":
                project.adopted_pr = (
                    str(deliverable.get("adopted_pr", "")).strip() or project.adopted_pr
                )
            elif deliverable.get("type") == "branch":
                project.branch = str(deliverable.get("branch", "")).strip() or project.branch
                commit_shas = [
                    str(item).strip()
                    for item in deliverable.get("commit_shas", [])
                    if str(item).strip()
                ]
                if commit_shas:
                    project.commit_shas = commit_shas

        # Recovery runs can persist branch/commit metadata on work orders even
        # when the top-level deliverable blob is absent or incomplete.
        project.branch = _worker_branch_from_run(project, run_dict) or project.branch
        commit_shas = _worker_commits_from_run(project, run_dict)
        if commit_shas:
            project.commit_shas = commit_shas
        project.worker_receipt_id = _first_receipt_id(run_dict) or project.worker_receipt_id

    @staticmethod
    def _review_gate_from_run_metadata(
        run_dict: dict[str, Any],
        *,
        review_model: str,
    ) -> CampaignReviewGate | None:
        blockers = CampaignExecutor._dispatch_blockers(run_dict)
        verification_missing_reason = _verification_missing_reason_from_run(run_dict)
        if verification_missing_reason or blockers:
            findings = list(blockers)
            if verification_missing_reason:
                findings.append(f"Worker verification incomplete: {verification_missing_reason}.")
            deduped_findings = [
                item for item in dict.fromkeys(str(f).strip() for f in findings) if item
            ]
            return CampaignReviewGate(
                required=True,
                review_model=review_model,
                status=CampaignReviewStatus.CHANGES_REQUESTED.value,
                findings=deduped_findings or ["Worker reported an unresolved merge-gate issue."],
                reviewed_at=_now_iso(),
                raw_review={
                    "source": "run_metadata_recovery",
                    "blockers": blockers,
                    "verification_missing_reason": verification_missing_reason,
                },
            )
        return None

    def status(self) -> dict[str, Any]:
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            _refresh_execution_state(manifest)
            return _manifest_summary(manifest)

    async def review_project(self, project_id: str) -> dict[str, Any]:
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            project = manifest.project_map().get(project_id)
            if project is None:
                raise KeyError(f"Unknown project_id: {project_id}")
            if not project.run_id:
                raise ValueError(f"Project {project_id} has no recorded run_id.")
            run_dict = self._refresh_run_dict(project.run_id)
            if not run_dict:
                raise ValueError(f"Project {project_id} run {project.run_id} is not available.")
            budget_context = self._review_budget_context(manifest, project)
        gate = await self.reviewer.review(
            project=project,
            worker_model=manifest.worker_model,
            review_model=manifest.review_model,
            enforce_cross_model_review=manifest.enforce_cross_model_review,
            run_dict=run_dict,
            budget_context=budget_context,
            repo_root=self.repo_root,
            target_branch=self.target_branch,
        )
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            project = manifest.project_map()[project_id]
            project.review = gate
            self._apply_review_result(manifest, project, gate, run_dict=run_dict)
            _refresh_execution_state(manifest)
            save_campaign_manifest(self.manifest_path, manifest)
            return {"project_id": project_id, "review": gate.to_dict(), "status": project.status}

    def record_project_pr(self, project_id: str, *, pr_url: str) -> dict[str, Any]:
        """Persist PR discovery or creation for a project awaiting merge."""
        normalized_pr_url = str(pr_url).strip()
        if not normalized_pr_url:
            raise ValueError("pr_url is required")

        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            project = manifest.project_map().get(project_id)
            if project is None:
                raise KeyError(f"Unknown project_id: {project_id}")
            if project.status not in {
                CampaignProjectStatus.WAITING_FOR_PR.value,
                CampaignProjectStatus.WAITING_FOR_MERGE.value,
            }:
                raise ValueError(
                    f"Project {project_id} is not waiting for PR/merge (status={project.status})."
                )

            project.pr_url = normalized_pr_url
            project.status = CampaignProjectStatus.WAITING_FOR_MERGE.value
            _refresh_execution_state(manifest)
            save_campaign_manifest(self.manifest_path, manifest)
            return {
                "project_id": project.project_id,
                "status": project.status,
                "pr_url": project.pr_url,
            }

    def complete_project(
        self,
        project_id: str,
        *,
        pr_url: str | None = None,
        merge_sha: str | None = None,
    ) -> dict[str, Any]:
        """Mark a PR-backed project completed after the merge lands."""
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            project = manifest.project_map().get(project_id)
            if project is None:
                raise KeyError(f"Unknown project_id: {project_id}")
            if project.status not in {
                CampaignProjectStatus.WAITING_FOR_PR.value,
                CampaignProjectStatus.WAITING_FOR_MERGE.value,
            }:
                raise ValueError(
                    f"Project {project_id} is not waiting for PR/merge (status={project.status})."
                )

            normalized_pr_url = str(pr_url or "").strip()
            normalized_merge_sha = str(merge_sha or "").strip()
            if normalized_pr_url:
                project.pr_url = normalized_pr_url
            if normalized_merge_sha and normalized_merge_sha not in project.commit_shas:
                project.commit_shas.append(normalized_merge_sha)
            project.status = CampaignProjectStatus.COMPLETED.value

            run_dict = self._refresh_run_dict(project.run_id) if project.run_id else None
            self._emit_receipt(manifest, project, run_dict)
            _refresh_execution_state(manifest)
            save_campaign_manifest(self.manifest_path, manifest)
            return {
                "project_id": project.project_id,
                "status": project.status,
                "pr_url": project.pr_url,
                "merge_sha": normalized_merge_sha or None,
                "receipt_id": project.receipt_id,
            }

    def sync_issue_plan(self) -> dict[str, Any]:
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            items = []
            for project in manifest.projects:
                issue_refs = [
                    ref
                    for ref in project.source_refs
                    if "github.com" in ref or ref.startswith("issue:")
                ]
                items.append(
                    {
                        "project_id": project.project_id,
                        "title": project.title,
                        "existing_issue_refs": issue_refs,
                        "needs_issue_materialization": not bool(issue_refs),
                        "status": project.status,
                    }
                )
            return {
                "mode": "campaign-sync-issues",
                "campaign_id": manifest.campaign_id,
                "source_kind": manifest.source_kind,
                "items": items,
            }

    @staticmethod
    def _select_projects_for_dispatch(
        manifest: CampaignManifest,
        ready_projects: list[CampaignProject],
        *,
        capacity: int,
    ) -> tuple[list[CampaignProject], list[str]]:
        available_budget = float(_campaign_budget_snapshot(manifest)["available_budget_usd"])
        selected: list[CampaignProject] = []
        blocked_ids: list[str] = []
        for project in ready_projects:
            if len(selected) >= capacity:
                break
            project_cost = _project_estimated_cost(project)
            if project_cost <= available_budget + _BUDGET_EPSILON:
                selected.append(project)
                available_budget = max(0.0, available_budget - project_cost)
            else:
                blocked_ids.append(project.project_id)
        return selected, blocked_ids

    @staticmethod
    def _review_budget_context(
        manifest: CampaignManifest,
        project: CampaignProject,
    ) -> dict[str, Any]:
        return {
            **_campaign_budget_snapshot(manifest),
            "project_estimated_cost_usd": round(_project_estimated_cost(project), 4),
        }

    async def _execute_project_id(self, project_id: str) -> dict[str, Any]:
        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            project = manifest.project_map().get(project_id)
            if project is None:
                raise KeyError(f"Unknown project_id: {project_id}")
            worker_model = manifest.worker_model
            review_model = _canonical_review_model(
                worker_model,
                manifest.review_model,
                enforce_cross_model_review=manifest.enforce_cross_model_review,
            )
            budget_limit = project.spec.budget_limit_usd or manifest.budget_limit_usd
            manifest_snapshot = CampaignManifest.from_dict(manifest.to_dict())
            project_snapshot = CampaignProject.from_dict(project.to_dict())

        retry_spec = await self._spec_for_retry(manifest_snapshot, project_snapshot)

        result = await dispatch_bounded_spec(
            retry_spec,
            target_branch=self.target_branch,
            budget_limit_usd=budget_limit,
            max_ticks=360,
            repo_path=self.repo_root,
            default_target_agent=worker_model,
            default_reviewer_agent=review_model,
            use_managed_session_script=False,
        )

        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            project = manifest.project_map()[project_id]
            self._apply_dispatch_result(manifest, project, result)
            _refresh_execution_state(manifest)
            save_campaign_manifest(self.manifest_path, manifest)
            current_status = project.status

        if current_status == CampaignProjectStatus.DELIVERED.value and isinstance(
            result.get("run"), dict
        ):
            with locked_manifest_path(self.manifest_path):
                manifest = load_campaign_manifest(self.manifest_path)
                project = manifest.project_map()[project_id]
                worker_model = manifest.worker_model
                review_model = manifest.review_model
                budget_context = self._review_budget_context(manifest, project)
            gate = await self.reviewer.review(
                project=project,
                worker_model=worker_model,
                review_model=review_model,
                enforce_cross_model_review=manifest.enforce_cross_model_review,
                run_dict=dict(result["run"]),
                budget_context=budget_context,
                repo_root=self.repo_root,
                target_branch=self.target_branch,
            )
            with locked_manifest_path(self.manifest_path):
                manifest = load_campaign_manifest(self.manifest_path)
                project = manifest.project_map()[project_id]
                project.review = gate
                self._apply_review_result(
                    manifest, project, gate, run_dict=dict(result.get("run") or {})
                )
                _refresh_execution_state(manifest)
                save_campaign_manifest(self.manifest_path, manifest)

        with locked_manifest_path(self.manifest_path):
            manifest = load_campaign_manifest(self.manifest_path)
            project = manifest.project_map()[project_id]
            return {
                "project_id": project.project_id,
                "status": project.status,
                "outcome": project.last_run_outcome,
                "run_id": project.run_id,
                "pr_url": project.pr_url,
                "adopted_pr": project.adopted_pr,
            }

    def _apply_dispatch_result(
        self, manifest: CampaignManifest, project: CampaignProject, result: dict[str, Any]
    ) -> None:
        run_dict = dict(result.get("run") or {})
        qualification = qualify_run_terminal_state(run_dict) if run_dict else None
        project.run_id = str(result.get("run_id", "")).strip() or project.run_id
        deliverable = dict(result.get("deliverable") or {})
        if not deliverable and qualification and qualification.deliverable:
            deliverable = dict(qualification.deliverable)
        outcome = self._resolve_dispatch_outcome(
            result,
            run_dict=run_dict,
            deliverable=deliverable,
        )
        run_blockers = self._dispatch_blockers(run_dict)
        project.last_run_outcome = outcome
        project.worker_receipt_id = _first_receipt_id(run_dict) or project.worker_receipt_id
        if deliverable.get("type") == "pr":
            project.pr_url = str(deliverable.get("pr_url", "")).strip() or project.pr_url
        elif deliverable.get("type") == "adopted_pr":
            project.adopted_pr = (
                str(deliverable.get("adopted_pr", "")).strip() or project.adopted_pr
            )
        elif deliverable.get("type") == "branch":
            project.branch = str(deliverable.get("branch", "")).strip() or project.branch
            project.commit_shas = [
                str(item) for item in deliverable.get("commit_shas", []) if str(item).strip()
            ]

        project.retry_count += 1
        manifest.execution_state.total_cost_usd += float(project.estimated_cost_usd or 0.0)
        deliverable_requires_review = bool(deliverable) and outcome not in {
            CampaignRunOutcome.DELIVERABLE_CREATED.value,
            CampaignRunOutcome.PR_ADOPTED.value,
        }
        if outcome in {
            CampaignRunOutcome.DELIVERABLE_CREATED.value,
            CampaignRunOutcome.PR_ADOPTED.value,
        }:
            project.status = CampaignProjectStatus.DELIVERED.value
        elif outcome == CampaignRunOutcome.CLEAN_EXIT_NO_DELIVERABLE.value:
            project.status = CampaignProjectStatus.NEEDS_REVISION.value
        elif outcome == CampaignRunOutcome.STALLED.value:
            project.status = CampaignProjectStatus.STALLED.value
        elif outcome == CampaignRunOutcome.NEEDS_HUMAN.value:
            project.status = CampaignProjectStatus.BLOCKED.value
        elif outcome in {CampaignRunOutcome.TIMEOUT.value, CampaignRunOutcome.CRASH.value}:
            if deliverable_requires_review:
                project.status = CampaignProjectStatus.BLOCKED.value
            elif project.retry_count <= manifest.max_retries_per_project:
                project.status = CampaignProjectStatus.NEEDS_REVISION.value
            else:
                project.status = CampaignProjectStatus.FAILED.value
        else:
            project.status = CampaignProjectStatus.BLOCKED.value

        if project.retry_count > manifest.max_retries_per_project and project.status in {
            CampaignProjectStatus.NEEDS_REVISION.value,
            CampaignProjectStatus.FAILED.value,
        }:
            project.status = CampaignProjectStatus.SKIPPED.value

        if project.status in _TERMINAL_STATUSES:
            self._emit_receipt(manifest, project, run_dict)

        self._record_attempt(
            project,
            run_dict=run_dict,
            outcome=outcome,
            blockers=run_blockers,
            budget_snapshot=self._review_budget_context(manifest, project),
            requeue_eligible=self._run_requeue_eligible(run_dict, outcome)
            and self._project_recovery_eligible(manifest, project),
        )

    def _apply_review_result(
        self,
        manifest: CampaignManifest,
        project: CampaignProject,
        gate: CampaignReviewGate,
        run_dict: dict[str, Any] | None = None,
    ) -> None:
        project.review = gate

        if gate.status == CampaignReviewStatus.PASSED.value:
            if _project_pr_reference(project):
                project.status = CampaignProjectStatus.WAITING_FOR_MERGE.value
            elif project.branch:
                project.status = CampaignProjectStatus.WAITING_FOR_PR.value
            else:
                project.status = CampaignProjectStatus.COMPLETED.value
        elif gate.status == CampaignReviewStatus.CHANGES_REQUESTED.value:
            project.status = CampaignProjectStatus.NEEDS_REVISION.value
        else:
            project.status = CampaignProjectStatus.BLOCKED.value

        if project.status in _TERMINAL_STATUSES:
            self._emit_receipt(manifest, project, run_dict)

    def _resolve_dispatch_outcome(
        self,
        result: dict[str, Any],
        *,
        run_dict: dict[str, Any],
        deliverable: dict[str, Any],
    ) -> str:
        metadata = dict(run_dict.get("metadata") or {})
        metadata_outcome = str(metadata.get(CAMPAIGN_OUTCOME_METADATA_KEY, "")).strip()
        statuses = {
            str(item.get("status", "")).strip().lower()
            for item in run_dict.get("work_orders", [])
            if isinstance(item, dict) and str(item.get("status", "")).strip()
        }
        worker_outcomes = {
            str(item.get("worker_outcome", "")).strip().lower()
            for item in run_dict.get("work_orders", [])
            if isinstance(item, dict) and str(item.get("worker_outcome", "")).strip()
        }
        if (
            not metadata_outcome and WorkerOutcome.TIMEOUT_NO_PROGRESS.value in worker_outcomes
        ) or (
            statuses & {"waiting_conflict", "waiting_resource"}
            and not (statuses & {"queued", "leased", "dispatched"})
        ):
            return CampaignRunOutcome.STALLED.value

        qualification = qualify_run_terminal_state(run_dict) if run_dict else None
        if qualification and qualification.terminal_outcome != "unknown":
            if (
                metadata_outcome == CampaignRunOutcome.STALLED.value
                and qualification.terminal_outcome
                in {
                    CampaignRunOutcome.NEEDS_HUMAN.value,
                    CampaignRunOutcome.TIMEOUT.value,
                }
            ):
                return metadata_outcome
            if (
                deliverable
                and qualification.terminal_outcome
                == CampaignRunOutcome.CLEAN_EXIT_NO_DELIVERABLE.value
            ):
                return (
                    CampaignRunOutcome.PR_ADOPTED.value
                    if str(deliverable.get("type", "")).strip() == "adopted_pr"
                    else CampaignRunOutcome.DELIVERABLE_CREATED.value
                )
            return qualification.terminal_outcome

        if metadata_outcome:
            return metadata_outcome

        inferred_outcome, _ = SwarmSupervisor._campaign_outcome_for_work_orders(
            list(run_dict.get("work_orders", []))
        )
        if inferred_outcome:
            return inferred_outcome

        return str(result.get("outcome", CampaignRunOutcome.BLOCKED.value)).strip()

    @staticmethod
    def _dispatch_blockers(run_dict: dict[str, Any]) -> list[str]:
        blockers = collect_run_blockers(run_dict)
        if blockers:
            return blockers
        _, fallback_blockers = SwarmSupervisor._campaign_outcome_for_work_orders(
            list(run_dict.get("work_orders", []))
        )
        return fallback_blockers

    @staticmethod
    def _project_recovery_eligible(
        manifest: CampaignManifest,
        project: CampaignProject,
    ) -> bool:
        if project.status != CampaignProjectStatus.NEEDS_REVISION.value:
            return False
        if project.retry_count > manifest.max_retries_per_project:
            return False
        return project.last_run_outcome in {
            CampaignRunOutcome.CLEAN_EXIT_NO_DELIVERABLE.value,
            CampaignRunOutcome.TIMEOUT.value,
            CampaignRunOutcome.CRASH.value,
        }

    @staticmethod
    def _run_requeue_eligible(run_dict: dict[str, Any], outcome: str) -> bool:
        qualification = qualify_run_terminal_state(run_dict) if run_dict else None
        if qualification and qualification.deliverable is not None:
            return False
        metadata = dict(run_dict.get("metadata") or {})
        if CAMPAIGN_REQUEUE_ELIGIBLE_METADATA_KEY in metadata:
            return bool(metadata.get(CAMPAIGN_REQUEUE_ELIGIBLE_METADATA_KEY))
        return outcome in {
            CampaignRunOutcome.CLEAN_EXIT_NO_DELIVERABLE.value,
            CampaignRunOutcome.TIMEOUT.value,
            CampaignRunOutcome.CRASH.value,
        }

    @staticmethod
    def _record_attempt(
        project: CampaignProject,
        *,
        run_dict: dict[str, Any],
        outcome: str,
        blockers: list[str],
        budget_snapshot: dict[str, Any] | None,
        requeue_eligible: bool,
    ) -> None:
        record = {
            "attempt": int(project.retry_count),
            "recorded_at": _now_iso(),
            "run_id": project.run_id,
            "run_status": str(run_dict.get("status", "")).strip() or None,
            "outcome": outcome,
            "project_status": project.status,
            "worker_receipt_id": project.worker_receipt_id,
            "campaign_receipt_id": project.receipt_id,
            "review_status": project.review.status,
            "requeue_eligible": requeue_eligible,
        }
        if budget_snapshot:
            record["budget_limit_usd"] = budget_snapshot.get("budget_limit_usd")
            record["budget_spent_usd"] = budget_snapshot.get("spent_cost_usd")
            record["budget_reserved_usd"] = budget_snapshot.get("reserved_cost_usd")
            record["budget_available_usd"] = budget_snapshot.get("available_budget_usd")
        if blockers:
            record["blockers"] = list(blockers[:10])
            record["failure_detail"] = blockers[0]
        planner_metadata = _planner_metadata_from_run(run_dict)
        if planner_metadata.get("planner_strategy_requested"):
            record["planner_strategy_requested"] = planner_metadata["planner_strategy_requested"]
        if planner_metadata.get("planner_strategy_used"):
            record["planner_strategy_used"] = planner_metadata["planner_strategy_used"]
        if planner_metadata.get("planner_fallback_reason"):
            record["planner_fallback_reason"] = planner_metadata["planner_fallback_reason"]
        verification_missing_reason = _verification_missing_reason_from_run(run_dict)
        if verification_missing_reason:
            record["verification_missing_reason"] = verification_missing_reason
        project.attempt_history.append(record)

    async def _spec_for_retry(
        self,
        manifest: CampaignManifest,
        project: CampaignProject,
    ) -> SwarmSpec:
        spec = SwarmSpec.from_dict(project.spec.to_dict())
        if project.review.findings:
            extra_constraints = [
                f"Address prior review finding: {finding}" for finding in project.review.findings
            ]
            spec.constraints = list(dict.fromkeys(list(spec.constraints) + extra_constraints))
        if spec.work_orders or manifest.planner_strategy != "model":
            return spec

        planning_prompt = self._planner_task_prompt(project, spec)
        planner_metadata = {
            "planner_model": manifest.planner_model,
            "planner_strategy_requested": manifest.planner_strategy,
            "planner_strategy_used": "model",
            "planner_fallback_reason": None,
            "experiment_id": manifest.experiment_id,
            "experiment_label": manifest.experiment_label,
        }
        try:
            decomposition = await self.decomposer.analyze_with_model(
                planning_prompt,
                planner_model=manifest.planner_model,
                file_scope_hints=spec.file_scope_hints or None,
                acceptance_criteria=spec.acceptance_criteria,
                constraints=spec.constraints,
            )
        except (RuntimeError, ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            planner_metadata["planner_strategy_used"] = "heuristic"
            planner_metadata["planner_fallback_reason"] = f"{type(exc).__name__}: {exc}"[:500]
            decomposition = self.decomposer.analyze(
                planning_prompt,
                file_scope_hints=spec.file_scope_hints or None,
            )

        spec.work_orders = self._planned_work_orders_from_decomposition(
            decomposition,
            spec=spec,
            worker_model=manifest.worker_model,
            review_model=manifest.review_model,
            enforce_cross_model_review=manifest.enforce_cross_model_review,
            planner_metadata=planner_metadata,
        )
        return spec

    @staticmethod
    def _planner_task_prompt(project: CampaignProject, spec: SwarmSpec) -> str:
        parts = [spec.refined_goal or spec.raw_goal or project.title]
        if spec.file_scope_hints:
            parts.append("File scope hints: " + ", ".join(spec.file_scope_hints))
        if spec.acceptance_criteria:
            parts.append(
                "Acceptance criteria: " + "; ".join(str(c) for c in spec.acceptance_criteria)
            )
        if spec.constraints:
            parts.append("Constraints: " + "; ".join(str(c) for c in spec.constraints))
        return "\n".join(parts)

    def _planned_work_orders_from_decomposition(
        self,
        decomposition: Any,
        *,
        spec: SwarmSpec,
        worker_model: str,
        review_model: str,
        enforce_cross_model_review: bool,
        planner_metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        subtasks = list(getattr(decomposition, "subtasks", []) or [])
        if not subtasks:
            subtasks = [
                SubTask(
                    id="subtask_1",
                    title=(spec.refined_goal or spec.raw_goal or "Planned work")[:80],
                    description=spec.refined_goal or spec.raw_goal or "Planned work",
                    file_scope=list(spec.file_scope_hints),
                    success_criteria={
                        "tests": (
                            spec.acceptance_criteria[0]
                            if spec.acceptance_criteria
                            and (
                                spec.acceptance_criteria[0].startswith("pytest")
                                or spec.acceptance_criteria[0].startswith("python -m pytest")
                            )
                            else ""
                        ),
                        "definition_of_done": spec.acceptance_criteria[0]
                        if spec.acceptance_criteria
                        else "Complete the bounded task.",
                    },
                )
            ]
        chosen_review_model = _canonical_review_model(
            worker_model,
            review_model,
            enforce_cross_model_review=enforce_cross_model_review,
        )
        work_orders = [item.to_dict() for item in self.bridge.build_work_orders(subtasks)]
        for item in work_orders:
            # Ensure each work order's file_scope is a superset of the project's
            # file_scope_hints.  The LLM planner may assign a narrower scope per
            # subtask, but the supervisor enforces scope against the work order —
            # so hints must be included or the worker is blocked for editing the
            # files it was told to edit.
            wo_scope = [str(s).strip() for s in item.get("file_scope", []) if str(s).strip()]
            for hint in spec.file_scope_hints:
                if hint not in wo_scope:
                    wo_scope.append(hint)
            item["file_scope"] = wo_scope

            inherited_tests = self._inherited_expected_tests_for_planned_work_order(item, spec)
            if inherited_tests:
                item["expected_tests"] = inherited_tests
                success_criteria = dict(item.get("success_criteria") or {})
                if "tests" not in success_criteria:
                    success_criteria["tests"] = (
                        inherited_tests[0] if len(inherited_tests) == 1 else list(inherited_tests)
                    )
                item["success_criteria"] = success_criteria
            item["target_agent"] = worker_model
            item["reviewer_agent"] = chosen_review_model
            item["metadata"] = {
                **dict(item.get("metadata") or {}),
                **{
                    key: value
                    for key, value in planner_metadata.items()
                    if value is not None and value != ""
                },
                "requested_target_agent": worker_model,
                "requested_reviewer_agent": chosen_review_model,
            }
        return work_orders

    @staticmethod
    def _inherited_expected_tests_for_planned_work_order(
        work_order: dict[str, Any],
        spec: SwarmSpec,
    ) -> list[str]:
        existing = [
            str(item).strip() for item in work_order.get("expected_tests", []) if str(item).strip()
        ]
        if existing:
            return list(dict.fromkeys(existing))

        inferred: list[str] = []
        for raw_path in work_order.get("file_scope", []):
            path = str(raw_path).strip()
            if path.startswith("tests/") and path.endswith(".py"):
                inferred.append(f"python -m pytest {path} -q")
        if inferred:
            return list(dict.fromkeys(inferred))

        return _tests_from_acceptance_criteria(spec.acceptance_criteria)

    def _reconcile_active_projects(self, manifest: CampaignManifest) -> None:
        for project in manifest.projects:
            if project.status != CampaignProjectStatus.ACTIVE.value or not project.run_id:
                continue
            run_dict = self._refresh_run_dict(project.run_id)
            if not run_dict:
                continue
            # Only classify runs that have reached a terminal status.
            # _classify_terminal_run_outcome falls back to "blocked" for
            # unknown statuses (including "running"), which would
            # incorrectly transition in-flight projects out of ACTIVE.
            run_status = str(run_dict.get("status", "")).strip().lower()
            if run_status in {"running", "in_progress", "pending", "queued", ""}:
                continue
            outcome = self._resolve_dispatch_outcome(
                {"run": run_dict},
                run_dict=run_dict,
                deliverable=cast(dict[str, Any], _extract_deliverable(run_dict)),
            )
            if outcome in {
                CampaignRunOutcome.DELIVERABLE_CREATED.value,
                CampaignRunOutcome.PR_ADOPTED.value,
                CampaignRunOutcome.CLEAN_EXIT_NO_DELIVERABLE.value,
                CampaignRunOutcome.STALLED.value,
                CampaignRunOutcome.NEEDS_HUMAN.value,
                CampaignRunOutcome.TIMEOUT.value,
                CampaignRunOutcome.CRASH.value,
                CampaignRunOutcome.BLOCKED.value,
            }:
                self._apply_dispatch_result(
                    manifest,
                    project,
                    {
                        "run": run_dict,
                        "run_id": run_dict.get("run_id"),
                        "outcome": outcome,
                        "deliverable": _extract_deliverable(run_dict),
                    },
                )

    def _ready_projects(self, manifest: CampaignManifest) -> list[CampaignProject]:
        completed = {
            project.project_id
            for project in manifest.projects
            if project.status == CampaignProjectStatus.COMPLETED.value
        }
        ready: list[CampaignProject] = []
        for project in manifest.projects:
            if project.status not in {
                CampaignProjectStatus.PENDING.value,
                CampaignProjectStatus.READY.value,
                CampaignProjectStatus.NEEDS_REVISION.value,
            }:
                continue
            if project.retry_count > manifest.max_retries_per_project:
                project.status = CampaignProjectStatus.SKIPPED.value
                self._emit_receipt(manifest, project, None)
                continue
            deps = {dep.project_id for dep in project.dependencies}
            if deps.issubset(completed):
                if project.status == CampaignProjectStatus.PENDING.value:
                    project.status = CampaignProjectStatus.READY.value
                ready.append(project)
        return ready

    def _refresh_run_dict(self, run_id: str) -> dict[str, Any] | None:
        supervisor = SwarmSupervisor(repo_root=self.repo_root)
        try:
            return supervisor.refresh_run(run_id).to_dict()
        except (RuntimeError, ValueError, KeyError, OSError, TypeError):
            record = supervisor.store.get_supervisor_run(run_id)
            return dict(record) if isinstance(record, dict) else None

    def _emit_receipt(
        self,
        manifest: CampaignManifest,
        project: CampaignProject,
        run_dict: dict[str, Any] | None,
    ) -> Path:
        """Write an authoritative receipt file at terminal project transition.

        Receipts are written to docs/receipts/<campaign_id>/<project_id>.yaml
        atomically (temp file + replace). Raises RuntimeError on failure so
        the caller knows the receipt was not persisted.
        """
        receipt_dir = self.repo_root / "docs" / "receipts" / manifest.campaign_id
        receipt_path = receipt_dir / f"{project.project_id}.yaml"
        try:
            try:
                manifest_input = str(self.manifest_path.relative_to(self.repo_root))
            except ValueError:
                manifest_input = str(self.manifest_path)
            planner_metadata = _planner_metadata_from_run(run_dict)
            verification_missing_reason = _verification_missing_reason_from_run(run_dict)
            worker_branches = _worker_branches_from_run(project, run_dict)
            worker_commits = _worker_commits_from_run(project, run_dict)

            payload: dict[str, Any] = {
                "task_id": project.project_id,
                "campaign_id": manifest.campaign_id,
                "phase": _derive_phase(manifest.campaign_id),
                "manifest_input": manifest_input,
                "planner_strategy_requested": planner_metadata.get("planner_strategy_requested")
                or manifest.planner_strategy,
                "planner_strategy_used": planner_metadata.get("planner_strategy_used")
                or manifest.planner_strategy,
                "planner_fallback_reason": planner_metadata.get("planner_fallback_reason"),
                "verification_missing_reason": verification_missing_reason,
                "worker_receipt_id": project.worker_receipt_id,
                "worker_branch": worker_branches[0] if worker_branches else None,
                "worker_commit": worker_commits[-1] if worker_commits else None,
                "worker_branches": worker_branches,
                "worker_commits": worker_commits,
                "changed_files": _changed_files_from_run(run_dict),
                "work_orders": _work_order_snapshots_from_run(run_dict),
                "review_gate": project.review.to_dict(),
                "review_verdict": _receipt_review_verdict(project.review.status),
                "verification_results": {
                    "pytest_exit_code": None,
                    "syntax_check": None,
                    "truth_suite": None,
                },
                "final_status": _receipt_final_status(project.status),
                "failure_classification": _failure_classification_from_outcome(
                    project.last_run_outcome
                ),
                "rescue_required": False,
                "rescue_description": None,
                "cost_usd": project.estimated_cost_usd,
                "budget": self._review_budget_context(manifest, project),
                "duration_seconds": _duration_seconds_from_run(run_dict),
                "created_at": datetime.now(UTC).isoformat(),
            }

            try:
                import yaml

                content = yaml.safe_dump(payload, sort_keys=True, allow_unicode=False)
            except ImportError:
                content = json.dumps(payload, indent=2, sort_keys=True)

            receipt_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = receipt_path.with_suffix(".yaml.tmp")
            tmp_path.write_text(content, encoding="utf-8")
            tmp_path.replace(receipt_path)

            project.receipt_id = str(receipt_path.relative_to(self.repo_root))
            qualification = qualify_run_terminal_state(run_dict) if run_dict else None
            deliverable_type = ""
            pr_reference = str(project.pr_url or project.adopted_pr or "").strip()
            if qualification and qualification.deliverable_type:
                deliverable_type = qualification.deliverable_type
                pr_reference = (
                    str(
                        qualification.deliverable.get("pr_url")
                        if isinstance(qualification.deliverable, dict)
                        else ""
                    ).strip()
                    or pr_reference
                )
            elif project.adopted_pr:
                deliverable_type = "adopted_pr"
            elif project.pr_url:
                deliverable_type = "pr"
            elif worker_branches and worker_commits:
                deliverable_type = "branch"
            terminal_outcome = str(project.last_run_outcome or "").strip()
            if not terminal_outcome and qualification is not None:
                terminal_outcome = str(qualification.terminal_outcome or "").strip()
            if not terminal_outcome:
                if deliverable_type == "adopted_pr":
                    terminal_outcome = CampaignRunOutcome.PR_ADOPTED.value
                elif deliverable_type in {"pr", "branch"}:
                    terminal_outcome = CampaignRunOutcome.DELIVERABLE_CREATED.value
                elif project.status == CampaignProjectStatus.STALLED.value:
                    terminal_outcome = CampaignRunOutcome.STALLED.value
                elif project.status == CampaignProjectStatus.BLOCKED.value:
                    terminal_outcome = CampaignRunOutcome.BLOCKED.value
                elif project.status == CampaignProjectStatus.FAILED.value:
                    terminal_outcome = CampaignRunOutcome.CRASH.value
                elif project.status == CampaignProjectStatus.COMPLETED.value:
                    terminal_outcome = CampaignRunOutcome.CLEAN_EXIT_NO_DELIVERABLE.value
                else:
                    terminal_outcome = "unknown"
            false_success_candidate = (
                terminal_outcome
                in {
                    CampaignRunOutcome.DELIVERABLE_CREATED.value,
                    CampaignRunOutcome.PR_ADOPTED.value,
                }
                and not deliverable_type
            )
            try:
                _LANE_TELEMETRY.record_lane(
                    LaneTelemetryRecord(
                        lane_kind="campaign_project",
                        lane_id=f"{manifest.campaign_id}:{project.project_id}",
                        run_id=str(project.run_id or ""),
                        task_id=project.project_id,
                        project_id=project.project_id,
                        terminal_outcome=terminal_outcome,
                        worker_outcome=str(
                            qualification.worker_outcome if qualification else ""
                        ).strip(),
                        deliverable_type=deliverable_type,
                        receipt_id=str(project.receipt_id or ""),
                        human_intervention_required=project.status
                        != CampaignProjectStatus.COMPLETED.value,
                        duration_seconds=float(payload.get("duration_seconds") or 0.0),
                        pr_url=pr_reference,
                        pr_number=SwarmSupervisor._extract_pr_number(pr_reference),
                        false_success_candidate=false_success_candidate,
                        metadata={
                            "campaign_id": manifest.campaign_id,
                            "project_status": project.status,
                            "worker_receipt_id": project.worker_receipt_id,
                            "review_status": project.review.status,
                        },
                    )
                )
            except (RuntimeError, ValueError, TypeError, OSError, KeyError):
                logger.debug("Campaign lane telemetry emission skipped", exc_info=True)
            logger.info(
                "receipt_emitted: project=%s status=%s path=%s",
                project.project_id,
                project.status,
                project.receipt_id,
            )
            return receipt_path

        except (RuntimeError, ValueError, TypeError, OSError, KeyError) as exc:
            logger.error(
                "receipt_emit_failed: project=%s status=%s error=%s",
                project.project_id,
                project.status,
                exc,
            )
            raise RuntimeError(f"Failed to emit receipt for {project.project_id}: {exc}") from exc


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _first_receipt_id(run_dict: dict[str, Any]) -> str | None:
    for item in run_dict.get("work_orders", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("receipt_id", "")).strip()
        if text:
            return text
    return None


def _refresh_execution_state(manifest: CampaignManifest) -> None:
    manifest.execution_state.ready_queue = [
        project.project_id
        for project in manifest.projects
        if project.status == CampaignProjectStatus.READY.value
    ]
    manifest.execution_state.active_projects = [
        project.project_id
        for project in manifest.projects
        if project.status
        in {
            CampaignProjectStatus.ACTIVE.value,
            CampaignProjectStatus.WAITING_FOR_PR.value,
            CampaignProjectStatus.WAITING_FOR_MERGE.value,
        }
    ]
    manifest.execution_state.completed_projects = [
        project.project_id
        for project in manifest.projects
        if project.status == CampaignProjectStatus.COMPLETED.value
    ]
    manifest.execution_state.failed_projects = [
        project.project_id
        for project in manifest.projects
        if project.status
        in {
            CampaignProjectStatus.FAILED.value,
            CampaignProjectStatus.STALLED.value,
            CampaignProjectStatus.BLOCKED.value,
        }
    ]
    manifest.execution_state.skipped_projects = [
        project.project_id
        for project in manifest.projects
        if project.status == CampaignProjectStatus.SKIPPED.value
    ]
    manifest.execution_state.reserved_cost_usd = float(
        _campaign_budget_snapshot(manifest)["reserved_cost_usd"]
    )


def _manifest_summary(manifest: CampaignManifest) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for project in manifest.projects:
        counts[project.status] = counts.get(project.status, 0) + 1
    budget = _campaign_budget_snapshot(manifest)
    return {
        "mode": "campaign-status",
        "campaign_id": manifest.campaign_id,
        "source_kind": manifest.source_kind,
        "source_ref": manifest.source_ref,
        "planner_model": manifest.planner_model,
        "planner_strategy": manifest.planner_strategy,
        "worker_model": manifest.worker_model,
        "review_model": manifest.review_model,
        "enforce_cross_model_review": manifest.enforce_cross_model_review,
        "experiment_id": manifest.experiment_id,
        "experiment_label": manifest.experiment_label,
        "budget_limit_usd": manifest.budget_limit_usd,
        "total_cost_usd": manifest.execution_state.total_cost_usd,
        "reserved_cost_usd": manifest.execution_state.reserved_cost_usd,
        "budget_available_usd": budget["available_budget_usd"],
        "budget": budget,
        "counts": counts,
        "stop_reason": _compute_stop_reason(manifest),
        "projects": [
            {
                "project_id": project.project_id,
                "title": project.title,
                "status": project.status,
                "estimated_cost_usd": project.estimated_cost_usd,
                "retry_count": project.retry_count,
                "run_id": project.run_id,
                "last_run_outcome": project.last_run_outcome,
                "worker_receipt_id": project.worker_receipt_id,
                "receipt_id": project.receipt_id,
                "pr_url": project.pr_url,
                "adopted_pr": project.adopted_pr,
                "review_status": project.review.status,
                "attempt_count": len(project.attempt_history),
                "last_failure_reason": project.last_run_outcome,
                "last_failure_detail": _project_last_failure_detail(project),
                "recovery_eligible": _project_recovery_eligible(manifest, project),
                "dependencies": [dep.to_dict() for dep in project.dependencies],
            }
            for project in manifest.projects
        ],
    }


def _project_last_failure_detail(project: CampaignProject) -> str | None:
    if not project.attempt_history:
        return None
    detail = str(project.attempt_history[-1].get("failure_detail", "")).strip()
    return detail or None


def _project_recovery_eligible(manifest: CampaignManifest, project: CampaignProject) -> bool:
    if project.status != CampaignProjectStatus.NEEDS_REVISION.value:
        return False
    if project.retry_count > manifest.max_retries_per_project:
        return False
    return project.last_run_outcome in {
        CampaignRunOutcome.CLEAN_EXIT_NO_DELIVERABLE.value,
        CampaignRunOutcome.TIMEOUT.value,
        CampaignRunOutcome.CRASH.value,
    }


def _compute_stop_reason(manifest: CampaignManifest) -> str:
    statuses = {project.status for project in manifest.projects}
    blocked_like = {
        CampaignProjectStatus.STALLED.value,
        CampaignProjectStatus.BLOCKED.value,
        CampaignProjectStatus.FAILED.value,
        CampaignProjectStatus.SKIPPED.value,
    }
    active_statuses = {
        CampaignProjectStatus.ACTIVE.value,
        CampaignProjectStatus.DELIVERED.value,
        CampaignProjectStatus.WAITING_FOR_PR.value,
        CampaignProjectStatus.WAITING_FOR_MERGE.value,
    }
    active_present = bool(statuses & active_statuses)

    if statuses and statuses.issubset(
        {
            CampaignProjectStatus.COMPLETED.value,
            CampaignProjectStatus.SKIPPED.value,
        }
    ):
        return CampaignStopReason.CAMPAIGN_COMPLETE.value

    dispatchable = _dispatchable_projects(manifest)
    terminal_blockers = [project for project in manifest.projects if project.status in blocked_like]
    if (
        terminal_blockers
        and len(terminal_blockers)
        == sum(
            1
            for project in terminal_blockers
            if project.last_run_outcome == CampaignRunOutcome.STALLED.value
        )
        and not active_present
        and not dispatchable
    ):
        return CampaignStopReason.CAMPAIGN_STALLED.value

    if statuses and statuses.issubset(blocked_like | {CampaignProjectStatus.COMPLETED.value}):
        return CampaignStopReason.CAMPAIGN_BLOCKED.value

    budget = _campaign_budget_snapshot(manifest)
    if (
        dispatchable
        and not active_present
        and not any(
            _project_estimated_cost(project)
            <= float(budget["available_budget_usd"]) + _BUDGET_EPSILON
            for project in dispatchable
        )
    ):
        return CampaignStopReason.BUDGET_EXHAUSTED.value
    if (
        dispatchable
        and not active_present
        and float(budget["available_budget_usd"]) <= _BUDGET_EPSILON
    ):
        return CampaignStopReason.BUDGET_EXHAUSTED.value

    started_at = _parse_dt(manifest.execution_state.last_run_at)
    if started_at and manifest.time_limit_hours > 0:
        elapsed_hours = (datetime.now(UTC) - started_at).total_seconds() / 3600.0
        if elapsed_hours >= manifest.time_limit_hours:
            return CampaignStopReason.TIME_LIMIT_EXCEEDED.value

    # Check for unreachable pending projects: if every non-terminal project
    # has at least one dependency in a terminal-but-not-completed state, the
    # campaign is effectively blocked even though raw statuses include pending.
    terminal_not_completed = blocked_like
    if not statuses & active_statuses:
        project_status_map = {p.project_id: p.status for p in manifest.projects}
        reachable = [
            p
            for p in manifest.projects
            if p.status
            in {
                CampaignProjectStatus.PENDING.value,
                CampaignProjectStatus.READY.value,
                CampaignProjectStatus.NEEDS_REVISION.value,
            }
        ]
        if reachable and all(
            any(
                project_status_map.get(d.project_id) in terminal_not_completed
                for d in p.dependencies
            )
            for p in reachable
            if p.dependencies
        ):
            # Every remaining non-terminal project with dependencies has at least
            # one dependency that will never complete.  If there are also no
            # dependency-free pending projects that could still make progress,
            # the campaign is blocked.
            dependency_free = [p for p in reachable if not p.dependencies]
            if not dependency_free:
                return CampaignStopReason.CAMPAIGN_BLOCKED.value
    return CampaignStopReason.STILL_RUNNING.value


def _project_pr_reference(project: CampaignProject) -> str | None:
    for candidate in (project.pr_url, project.adopted_pr):
        text = str(candidate or "").strip()
        if text:
            return text
    return None


def _merge_ready_projects(
    manifest: CampaignManifest,
    *,
    target_branch: str,
) -> list[dict[str, Any]]:
    ready: list[dict[str, Any]] = []
    for project in manifest.projects:
        if project.status not in {
            CampaignProjectStatus.WAITING_FOR_PR.value,
            CampaignProjectStatus.WAITING_FOR_MERGE.value,
        }:
            continue
        ready.append(
            {
                "project_id": project.project_id,
                "kind": "project",
                "status": project.status,
                "pr_url": _project_pr_reference(project),
                "branch": project.branch,
                "run_id": project.run_id,
                "target_branch": target_branch,
            }
        )
    return ready


def _extract_first_json_object(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _extract_json_list(text: str) -> list[str]:
    payload = _extract_first_json_object(text)
    findings = payload.get("findings")
    if isinstance(findings, list):
        return [str(item) for item in findings if str(item).strip()]
    return []


# ---------------------------------------------------------------------------
# Receipt emission helpers
# ---------------------------------------------------------------------------


def _derive_phase(campaign_id: str) -> str | None:
    cid = str(campaign_id or "").lower()
    for prefix, label in (
        ("phase0a", "0a"),
        ("phase0b", "0b"),
        ("phase1", "1"),
        ("phase2", "2"),
    ):
        if cid.startswith(prefix):
            return label
    return None


def _failure_classification_from_outcome(outcome: str | None) -> str | None:
    mapping = {
        CampaignRunOutcome.CRASH.value: "worker_crash",
        CampaignRunOutcome.TIMEOUT.value: "timeout",
        CampaignRunOutcome.STALLED.value: "stall",
        CampaignRunOutcome.BLOCKED.value: "stall",
        CampaignRunOutcome.NEEDS_HUMAN.value: "stall",
        CampaignRunOutcome.CLEAN_EXIT_NO_DELIVERABLE.value: "stall",
    }
    return mapping.get(str(outcome or ""))


def _receipt_final_status(project_status: str) -> str:
    return {
        "completed": "completed",
        "failed": "failed",
        "skipped": "failed",
        "stalled": "rejected",
        "blocked": "rejected",
    }.get(project_status, "failed")


def _receipt_review_verdict(review_status: str) -> str:
    return {
        CampaignReviewStatus.PASSED.value: "passed",
        CampaignReviewStatus.CHANGES_REQUESTED.value: "failed",
        CampaignReviewStatus.BLOCKED_NONREVIEWABLE.value: "failed",
        CampaignReviewStatus.PENDING.value: "skipped",
    }.get(review_status, "skipped")


def _duration_seconds_from_run(run_dict: dict[str, Any] | None) -> int | None:
    if not run_dict:
        return None
    for wo in run_dict.get("work_orders", []):
        if not isinstance(wo, dict):
            continue
        started = str(wo.get("started_at", "")).strip()
        ended = str(wo.get("completed_at", "")).strip()
        if started and ended:
            try:
                t_start = datetime.fromisoformat(started)
                t_end = datetime.fromisoformat(ended)
                return max(0, int((t_end - t_start).total_seconds()))
            except (ValueError, TypeError):
                continue
    return None


def _changed_files_from_run(run_dict: dict[str, Any] | None) -> list[str]:
    if not run_dict:
        return []
    paths: list[str] = []
    seen: set[str] = set()
    for wo in run_dict.get("work_orders", []):
        if not isinstance(wo, dict):
            continue
        for p in wo.get("changed_paths", []):
            text = str(p).strip()
            if text and text not in seen:
                seen.add(text)
                paths.append(text)
    return paths


def _tests_from_acceptance_criteria(acceptance_criteria: list[str]) -> list[str]:
    tests: list[str] = []
    for item in acceptance_criteria:
        text = str(item).strip()
        if text.startswith("python -m pytest") or text.startswith("pytest"):
            tests.append(text)
    return list(dict.fromkeys(tests))


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _worker_branches_from_run(
    project: CampaignProject, run_dict: dict[str, Any] | None
) -> list[str]:
    branches: list[str] = []
    if project.branch:
        branches.append(project.branch)
    if run_dict:
        for wo in run_dict.get("work_orders", []):
            if not isinstance(wo, dict):
                continue
            branch = str(wo.get("branch", "")).strip()
            if branch:
                branches.append(branch)
    return _ordered_unique(branches)


def _worker_commits_from_run(
    project: CampaignProject, run_dict: dict[str, Any] | None
) -> list[str]:
    commits: list[str] = [str(sha).strip() for sha in project.commit_shas if str(sha).strip()]
    if run_dict:
        for wo in run_dict.get("work_orders", []):
            if not isinstance(wo, dict):
                continue
            commits.extend(
                str(sha).strip() for sha in wo.get("commit_shas", []) if str(sha).strip()
            )
            head_sha = str(wo.get("head_sha", "")).strip()
            if head_sha:
                commits.append(head_sha)
    return _ordered_unique(commits)


def _worker_branch_from_run(
    project: CampaignProject, run_dict: dict[str, Any] | None
) -> str | None:
    branches = _worker_branches_from_run(project, run_dict)
    return branches[0] if branches else None


def _worker_commit_from_run(
    project: CampaignProject, run_dict: dict[str, Any] | None
) -> str | None:
    commits = _worker_commits_from_run(project, run_dict)
    return commits[-1] if commits else None


def _truncate_receipt_text(
    value: Any,
    *,
    max_chars: int = MAX_WORKER_LOG_TAIL_CHARS,
    tail: bool = False,
) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:] if tail else text[:max_chars]


def _receipt_debug_value(value: Any, *, tail: bool = False) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_receipt_text(value, tail=tail)
    if isinstance(value, list):
        return [_receipt_debug_value(item, tail=tail) for item in value]
    if isinstance(value, dict):
        return {str(key): _receipt_debug_value(item, tail=tail) for key, item in value.items()}
    return _truncate_receipt_text(value, tail=tail)


def _receipt_verification_results(
    work_order: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        command = str(entry.get("command", "")).strip()
        if not command:
            continue
        result: dict[str, Any] = {
            "command": command,
            "passed": bool(entry.get("passed", False)),
            "stdout_tail": _truncate_receipt_text(entry.get("stdout", ""), tail=True),
            "stderr_tail": _truncate_receipt_text(entry.get("stderr", ""), tail=True),
        }
        try:
            result["exit_code"] = int(entry.get("exit_code", 0))
        except (TypeError, ValueError):
            result["exit_code"] = -1
        try:
            result["duration_seconds"] = float(entry.get("duration_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            result["duration_seconds"] = 0.0
        results.append(result)
    return results


def _receipt_merge_gate(work_order: dict[str, Any]) -> dict[str, Any] | None:
    merge_gate = work_order.get("merge_gate")
    if not isinstance(merge_gate, dict) or not merge_gate:
        return None
    return {
        "enabled": bool(merge_gate.get("enabled", True)),
        "checks_passed": bool(merge_gate.get("checks_passed", False)),
        "human_approval_required": bool(merge_gate.get("human_approval_required", False)),
        "merge_eligible": bool(merge_gate.get("merge_eligible", False)),
        "verification_missing_reason": _optional_text(
            merge_gate.get("verification_missing_reason")
        ),
        "expected_checks": [
            str(item).strip() for item in merge_gate.get("expected_checks", []) if str(item).strip()
        ],
        "blocked_reasons": [
            _truncate_receipt_text(item)
            for item in merge_gate.get("blocked_reasons", [])
            if str(item).strip()
        ],
    }


def _work_order_snapshot_for_receipt(work_order: dict[str, Any]) -> dict[str, Any]:
    prompt_preview = _truncate_receipt_text(
        WorkerLauncher._build_prompt(work_order),
        max_chars=MAX_WORKER_LOG_TAIL_CHARS,
    )
    stdout_tail = _truncate_receipt_text(work_order.get("stdout_tail", ""), tail=True)
    stderr_tail = _truncate_receipt_text(work_order.get("stderr_tail", ""), tail=True)
    return {
        "work_order_id": _optional_text(work_order.get("work_order_id")),
        "title": _optional_text(work_order.get("title")),
        "description": _optional_text(work_order.get("description")),
        "status": _optional_text(work_order.get("status")),
        "target_agent": _optional_text(work_order.get("target_agent")),
        "reviewer_agent": _optional_text(work_order.get("reviewer_agent")),
        "file_scope": [
            str(item).strip() for item in work_order.get("file_scope", []) if str(item).strip()
        ],
        "expected_tests": [
            str(item).strip() for item in work_order.get("expected_tests", []) if str(item).strip()
        ],
        "success_criteria": _receipt_debug_value(work_order.get("success_criteria")),
        "metadata": _receipt_debug_value(work_order.get("metadata") or {}),
        "prompt_preview": prompt_preview,
        "branch": _optional_text(work_order.get("branch")),
        "commit_shas": [
            str(item).strip() for item in work_order.get("commit_shas", []) if str(item).strip()
        ],
        "head_sha": _optional_text(work_order.get("head_sha")),
        "changed_paths": [
            str(item).strip() for item in work_order.get("changed_paths", []) if str(item).strip()
        ],
        "receipt_id": _optional_text(work_order.get("receipt_id")),
        "review_status": _optional_text(work_order.get("review_status")),
        "worker_outcome": _optional_text(work_order.get("worker_outcome")),
        "dispatch_error": _optional_text(work_order.get("dispatch_error")),
        "blockers": [
            _truncate_receipt_text(item)
            for item in work_order.get("blockers", [])
            if str(item).strip()
        ],
        "verification_missing_reason": _optional_text(
            work_order.get("verification_missing_reason")
        ),
        "verification_results": _receipt_verification_results(work_order),
        "merge_gate": _receipt_merge_gate(work_order),
        "stdout_tail": stdout_tail or None,
        "stderr_tail": stderr_tail or None,
        "dispatched_at": _optional_text(work_order.get("dispatched_at")),
        "started_at": _optional_text(work_order.get("started_at")),
        "completed_at": _optional_text(work_order.get("completed_at")),
        "last_progress_at": _optional_text(work_order.get("last_progress_at")),
        "last_observed_at": _optional_text(work_order.get("last_observed_at")),
    }


def _work_order_snapshots_from_run(run_dict: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not run_dict:
        return []
    snapshots: list[dict[str, Any]] = []
    for work_order in run_dict.get("work_orders", []):
        if not isinstance(work_order, dict):
            continue
        snapshots.append(_work_order_snapshot_for_receipt(work_order))
    return snapshots


def _planner_metadata_from_run(run_dict: dict[str, Any] | None) -> dict[str, Any]:
    if not run_dict:
        return {}
    for wo in run_dict.get("work_orders", []):
        if not isinstance(wo, dict):
            continue
        metadata = dict(wo.get("metadata") or {})
        if any(
            key in metadata
            for key in (
                "planner_strategy_requested",
                "planner_strategy_used",
                "planner_fallback_reason",
            )
        ):
            return {
                "planner_strategy_requested": str(
                    metadata.get("planner_strategy_requested", "")
                ).strip()
                or None,
                "planner_strategy_used": str(metadata.get("planner_strategy_used", "")).strip()
                or None,
                "planner_fallback_reason": str(metadata.get("planner_fallback_reason", "")).strip()
                or None,
            }
    return {}


def _verification_missing_reason_from_run(run_dict: dict[str, Any] | None) -> str | None:
    if not run_dict:
        return None
    for wo in run_dict.get("work_orders", []):
        if not isinstance(wo, dict):
            continue
        reason = str(wo.get("verification_missing_reason", "")).strip()
        if reason:
            return reason
        merge_gate = dict(wo.get("merge_gate") or {})
        reason = str(merge_gate.get("verification_missing_reason", "")).strip()
        if reason:
            return reason
    return None
