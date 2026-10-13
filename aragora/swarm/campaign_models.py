"""Campaign manifest data models.

The campaign status enums, the dependency / review-gate / execution-state / project /
manifest dataclasses, and the small value helpers their ``from_dict`` constructors use.
``aragora.swarm.campaign`` re-exports every name here, so importing from either module
yields the same objects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aragora.swarm.spec import SwarmSpec


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
