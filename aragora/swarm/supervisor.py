"""Supervisor-driven Codex/Claude swarm orchestration.

Builds bounded work orders from a SwarmSpec, provisions managed worktrees for
Codex/Claude execution targets, claims bounded leases, and persists a
SupervisorRun in the existing development coordination store.
"""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.nomic.approval import ApprovalLevel, ApprovalPolicy
from aragora.docs_only import (
    canonical_docs_container_scope,
    infer_docs_safe_hints,
    is_docs_safe_path,
    is_docs_safe_top_level_file,
)
from aragora.pipeline.execution_mode import ExecutionMode
from aragora.nomic.dev_coordination import (
    DevCoordinationStore,
)
from aragora.nomic.pipeline_bridge import BoundedWorkOrder, NomicPipelineBridge
from aragora.nomic.task_decomposer import SubTask, TaskDecomposer
from aragora.swarm.dependency_context import (
    build_dependency_context_payload,
    compose_dependency_description,
    dependency_ids_for_work_order,
)
from aragora.swarm.lane_telemetry import LaneTelemetryCollector
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.supervisor_duplicates import (
    DEFAULT_RECEIPTLESS_DUPLICATE_STALE_SECONDS,  # noqa: F401
    SwarmSupervisorDuplicateWorkMixin,
    _parse_iso_timestamp,  # noqa: F401
    _path_in_scope,
)
from aragora.swarm.supervisor_requeue import SwarmSupervisorRequeueMixin
from aragora.swarm.supervisor_waiting import SwarmSupervisorWaitingStateMixin
from aragora.swarm.terminal_truth import (
    extract_work_order_deliverable,
    qualify_run_terminal_state,
)
from aragora.swarm.worker_launcher import (
    LaunchConfig,
    WorkerLauncher,
    WorkerProcess,
)
from aragora.worktree.lifecycle import WorktreeLifecycleService

if TYPE_CHECKING:
    from aragora.swarm.pr_registry import PullRequestRegistry

UTC = timezone.utc
logger = logging.getLogger(__name__)
_LANE_TELEMETRY = LaneTelemetryCollector()

WORKER_TYPE_CIRCUIT_BREAKERS_KEY = "worker_type_circuit_breakers"
WORKER_TYPE_CIRCUIT_BREAKER_POLICY_KEY = "worker_type_circuit_breaker_policy"
CAMPAIGN_OUTCOME_METADATA_KEY = "campaign_outcome"
CAMPAIGN_REQUEUE_ELIGIBLE_METADATA_KEY = "campaign_requeue_eligible"
CAMPAIGN_BLOCKERS_METADATA_KEY = "campaign_blockers"
LAUNCHER_CONFIG_METADATA_KEY = "worker_launcher_config"
MAX_WORKER_LOG_TAIL_CHARS = 4000
DEFAULT_BREAKER_FAILURE_THRESHOLD = 2
DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS = 900.0
SESSION_LOCK_FILES = (
    ".claude-session-active",
    ".codex_session_active",
    ".nomic-session-active",
)
_TRUTHY_BOOL_STRINGS = {"1", "true", "yes", "y", "on"}
_FALSY_BOOL_STRINGS = {"0", "false", "no", "n", "off"}


def _is_concrete_repo_path(path: str) -> bool:
    return SwarmSpec.is_concrete_repo_path_hint(path)


def _strict_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUTHY_BOOL_STRINGS:
            return True
        if normalized in _FALSY_BOOL_STRINGS:
            return False
    return default


def _docs_only_scope_supports_hint(path: str, original_scope: list[str]) -> bool:
    if any(_path_in_scope(path, scope) or _path_in_scope(scope, path) for scope in original_scope):
        return True
    if not is_docs_safe_top_level_file(path):
        return False
    return any(canonical_docs_container_scope(scope) == "docs" for scope in original_scope)


def _narrow_scope_to_explicit_paths(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
) -> BoundedWorkOrder:
    """Replace broad container scopes with explicit file paths named in task text."""
    if not item.file_scope:
        return item
    inference_text = " ".join(
        filter(
            None,
            [
                spec.refined_goal or "",
                spec.raw_goal or "",
                item.title or "",
                item.description or "",
            ],
        )
    )
    explicit_paths = [
        path
        for path in SwarmSpec.infer_file_scope_hints(inference_text)
        if _is_concrete_repo_path(path)
    ]
    if not explicit_paths:
        return item

    original_scope = [str(path).strip() for path in item.file_scope if str(path).strip()]
    if not original_scope:
        return item

    narrowed_scope: list[str] = []
    replaced = False
    for scope in original_scope:
        contains_explicit = any(_path_in_scope(path, scope) for path in explicit_paths)
        if contains_explicit and scope not in explicit_paths and not _is_concrete_repo_path(scope):
            replaced = True
            continue
        narrowed_scope.append(scope)
    if not replaced:
        return item

    item.file_scope = list(dict.fromkeys(narrowed_scope + explicit_paths))
    logger.info(
        "Narrowed broad file_scope on work order %s using explicit path hints: %s -> %s",
        item.work_order_id,
        original_scope,
        item.file_scope,
    )
    return item


def _narrow_docs_only_scope(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
) -> BoundedWorkOrder:
    constraints = [str(value).strip() for value in spec.constraints if str(value).strip()]
    if not any("documentation only" in value.lower() for value in constraints):
        return item

    original_scope = [str(path).strip() for path in item.file_scope if str(path).strip()]
    if not original_scope:
        return item

    inference_text = " ".join(
        filter(
            None,
            [
                spec.refined_goal or "",
                spec.raw_goal or "",
                item.title or "",
                item.description or "",
                *list(spec.acceptance_criteria),
                *constraints,
            ],
        )
    )
    doc_hints: list[str] = []
    for path in infer_docs_safe_hints(inference_text):
        clean = path.strip().removeprefix("./").rstrip("/")
        if _docs_only_scope_supports_hint(clean, original_scope):
            doc_hints.append(clean)
    if any(
        is_docs_safe_path(hint) and canonical_docs_container_scope(hint) is None
        for hint in doc_hints
    ):
        doc_hints = [hint for hint in doc_hints if canonical_docs_container_scope(hint) is None]
    narrowed_scope = list(dict.fromkeys(doc_hints))
    if not narrowed_scope:
        narrowed_scope = list(
            dict.fromkeys(
                scope
                for scope in (canonical_docs_container_scope(path) for path in original_scope)
                if scope is not None
            )
        )
    if not narrowed_scope or tuple(narrowed_scope) == tuple(original_scope):
        return item

    item.file_scope = narrowed_scope
    logger.info(
        "Narrowed docs-only file_scope on work order %s: %s -> %s",
        item.work_order_id,
        original_scope,
        item.file_scope,
    )
    return item


_NON_ACTIONABLE_EXPLICIT_SPEC_TITLES = {
    "validation changes",
    "acceptance criteria changes",
    "stop conditions changes",
    "scope changes",
    "goal changes",
    "context changes",
    "source issue context changes",
}


def _looks_like_non_actionable_explicit_spec_work_order(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
) -> bool:
    title = " ".join(str(item.title or "").strip().lower().split())
    description = " ".join(str(item.description or "").strip().lower().split())
    if title not in _NON_ACTIONABLE_EXPLICIT_SPEC_TITLES and not description.startswith("## "):
        return False
    if any(
        _is_concrete_repo_path(path)
        for path in (
            *SwarmSpec.infer_file_scope_hints(item.title or ""),
            *SwarmSpec.infer_file_scope_hints(item.description or ""),
        )
    ):
        return False
    expected_tests = [str(test).strip() for test in item.expected_tests if str(test).strip()]
    if expected_tests:
        return False
    success_tests = item.success_criteria.get("tests")
    if isinstance(success_tests, str) and success_tests.strip():
        return False
    if isinstance(success_tests, list) and any(str(test).strip() for test in success_tests):
        return False
    scope_key = {path.strip() for path in item.file_scope if path.strip()}
    spec_scope = {path.strip() for path in spec.file_scope_hints if path.strip()}
    if scope_key and spec_scope and scope_key != spec_scope:
        return False
    return True


def _looks_like_umbrella_explicit_spec_work_order(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
    siblings: list[BoundedWorkOrder],
) -> bool:
    normalized_title = " ".join(str(item.title or "").strip().lower().split())
    normalized_description = " ".join(str(item.description or "").strip().lower().split())
    normalized_goals = {
        " ".join(str(value or "").strip().lower().split())
        for value in (spec.refined_goal, spec.raw_goal)
        if str(value or "").strip()
    }
    if not normalized_goals:
        return False
    if normalized_title not in normalized_goals and normalized_description not in normalized_goals:
        return False
    item_scope = {path.strip() for path in item.file_scope if path.strip()}
    for sibling in siblings:
        if sibling is item:
            continue
        sibling_scope = {path.strip() for path in sibling.file_scope if path.strip()}
        if item_scope != sibling_scope:
            continue
        sibling_title = " ".join(str(sibling.title or "").strip().lower().split())
        if sibling_title and sibling_title != normalized_title:
            return True
    return False


def _ensure_work_order_scope(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
) -> BoundedWorkOrder:
    """Ensure a work order has non-empty file_scope through a 3-tier fallback.

    1. If the work order already has ``file_scope`` entries, merge in spec hints
       (preserving deduplication) so the worker can touch any file the project
       declares.
    2. If the work order has empty ``file_scope`` but the spec carries
       ``file_scope_hints``, backfill them directly.
    3. If both are empty, attempt keyword-based inference from the work order
       title and description via ``SwarmSpec.infer_file_scope_hints()``.

    A warning is logged when scope remains empty after all attempts — this is
    advisory, not blocking, to maintain backward compatibility.

    Returns the (mutated) work order for convenience.
    """
    spec_hints = list(spec.file_scope_hints) if spec.file_scope_hints else []

    if item.file_scope and spec_hints:
        # Merge: keep work order scope, append any new spec hints
        merged = list(dict.fromkeys(item.file_scope + spec_hints))
        if set(merged) != set(item.file_scope):
            logger.info(
                "Merged spec hints into work order %s file_scope: %s -> %s",
                item.work_order_id,
                item.file_scope,
                merged,
            )
        item.file_scope = merged
    elif not item.file_scope and spec_hints:
        # Backfill from spec hints
        item.file_scope = list(spec_hints)
        logger.info(
            "Backfilled empty file_scope on work order %s from spec hints: %s",
            item.work_order_id,
            spec_hints,
        )
    elif not item.file_scope and not spec_hints:
        # Last resort: infer from task title + description
        inference_text = " ".join(filter(None, [item.title or "", item.description or ""]))
        inferred = SwarmSpec.infer_file_scope_hints(inference_text)
        if inferred:
            item.file_scope = inferred
            logger.info(
                "Inferred file_scope on work order %s from title/description: %s",
                item.work_order_id,
                inferred,
            )
        else:
            logger.warning(
                "Work order %s has empty file_scope after all inference attempts "
                "(spec hints empty, keyword inference found nothing). "
                "Scope enforcement will be open for this work order.",
                item.work_order_id,
            )

    item = _narrow_scope_to_explicit_paths(item, spec)
    return _narrow_docs_only_scope(item, spec)


class SupervisorRunStatus(str, Enum):
    """Lifecycle state for a supervised swarm run."""

    PLANNED = "planned"
    ACTIVE = "active"
    NEEDS_HUMAN = "needs_human"
    COMPLETED = "completed"


class WorkerOutcome(str, Enum):
    """Structured classification of a worker's terminal state.

    Set on each work-order item as ``worker_outcome`` so operators and
    higher-level orchestrators (campaign, boss loop) can distinguish between
    fundamentally different failure modes without parsing free-text fields.
    """

    COMPLETED = "completed"
    CLEAN_EXIT_NO_EFFECT = "clean_exit_no_effect"
    CRASH = "crash"
    CRASH_WITH_SALVAGE = "crash_with_salvage"
    TIMEOUT_NO_PROGRESS = "timeout_no_progress"
    TIMEOUT_WITH_SALVAGE = "timeout_with_salvage"
    SCOPE_VIOLATION = "scope_violation"
    MERGE_GATE_FAILED = "merge_gate_failed"


@dataclass(slots=True)
class SwarmApprovalPolicy:
    """Explicit human-gating policy for supervised swarm runs."""

    require_merge_approval: bool = True
    require_external_action_approval: bool = True
    protected_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "require_merge_approval": self.require_merge_approval,
            "require_external_action_approval": self.require_external_action_approval,
            "protected_patterns": list(self.protected_patterns),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SwarmApprovalPolicy:
        payload = dict(data or {})
        require_merge_approval = _strict_bool(payload.get("require_merge_approval"))
        require_external_action_approval = _strict_bool(
            payload.get("require_external_action_approval")
        )
        return cls(
            require_merge_approval=(
                require_merge_approval if require_merge_approval is not None else True
            ),
            require_external_action_approval=(
                require_external_action_approval
                if require_external_action_approval is not None
                else True
            ),
            protected_patterns=[
                str(item) for item in payload.get("protected_patterns", []) if str(item).strip()
            ],
        )


@dataclass(slots=True)
class SupervisorRun:
    """Top-level artifact for one supervised swarm execution."""

    run_id: str
    goal: str
    target_branch: str
    status: str
    supervisor_agents: dict[str, Any]
    approval_policy: SwarmApprovalPolicy
    spec: SwarmSpec
    work_orders: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "target_branch": self.target_branch,
            "status": self.status,
            "supervisor_agents": dict(self.supervisor_agents),
            "approval_policy": self.approval_policy.to_dict(),
            "spec": self.spec.to_dict(),
            "work_orders": [dict(item) for item in self.work_orders],
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> SupervisorRun:
        return cls(
            run_id=str(record.get("run_id", "")),
            goal=str(record.get("goal", "")),
            target_branch=str(record.get("target_branch", "main")),
            status=str(record.get("status", SupervisorRunStatus.PLANNED.value)),
            supervisor_agents=dict(record.get("supervisor_agents") or {}),
            approval_policy=SwarmApprovalPolicy.from_dict(record.get("approval_policy")),
            spec=SwarmSpec.from_dict(dict(record.get("spec") or {})),
            work_orders=[dict(item) for item in record.get("work_orders", [])],
            metadata=dict(record.get("metadata") or {}),
            created_at=str(record.get("created_at", datetime.now(UTC).isoformat())),
            updated_at=str(record.get("updated_at", datetime.now(UTC).isoformat())),
        )


class SwarmSupervisor(
    SwarmSupervisorRequeueMixin,
    SwarmSupervisorWaitingStateMixin,
    SwarmSupervisorDuplicateWorkMixin,
):
    """Coordinate a bounded Codex/Claude worker pool using existing primitives."""

    _LLM_CALL_TIMEOUT: float = 60.0  # seconds for LLM adjudication/evaluation calls
    _DEPENDENCY_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")

    def __init__(
        self,
        repo_root: Path | None = None,
        *,
        store: DevCoordinationStore | None = None,
        lifecycle: WorktreeLifecycleService | None = None,
        bridge: NomicPipelineBridge | None = None,
        decomposer: TaskDecomposer | None = None,
        approval_policy: ApprovalPolicy | None = None,
        launcher: WorkerLauncher | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.store = store or DevCoordinationStore(repo_root=self.repo_root)
        self.lifecycle = lifecycle or WorktreeLifecycleService(repo_root=self.repo_root)
        self.bridge = bridge or NomicPipelineBridge(repo_path=self.repo_root)
        self.decomposer = decomposer or TaskDecomposer()
        self.approval_policy = approval_policy or ApprovalPolicy()
        self.launcher = launcher or WorkerLauncher()
        self._pr_registry: PullRequestRegistry | None = None

    def _get_pr_registry(self) -> PullRequestRegistry:
        """Lazily create and return the shared PullRequestRegistry."""
        if self._pr_registry is None:
            from aragora.swarm.pr_registry import PullRequestRegistry

            state_dir = self.repo_root / ".aragora"
            self._pr_registry = PullRequestRegistry(state_dir=state_dir)
        return self._pr_registry

    @staticmethod
    def _launcher_config_snapshot(config: LaunchConfig) -> dict[str, Any]:
        return {
            "claude_path": str(config.claude_path),
            "codex_path": str(config.codex_path),
            "timeout_seconds": float(config.timeout_seconds),
            "no_progress_timeout_seconds": float(config.no_progress_timeout_seconds),
            "claude_model": config.claude_model,
            "codex_model": config.codex_model,
            "claude_profile": config.claude_profile,
            "claude_profile_script": config.claude_profile_script,
            "auto_commit": bool(config.auto_commit),
            "use_managed_session_script": bool(config.use_managed_session_script),
            "base_branch": str(config.base_branch),
            "detach": bool(config.detach),
            "require_explicit_approval": bool(config.require_explicit_approval),
            "allow_claude_dangerously_skip_permissions": bool(
                config.allow_claude_dangerously_skip_permissions
            ),
            "allow_codex_full_auto": bool(config.allow_codex_full_auto),
            "execution_mode": (
                config.execution_mode.value
                if isinstance(config.execution_mode, ExecutionMode)
                else str(config.execution_mode)
            ),
        }

    @staticmethod
    def _optional_snapshot_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"none", "null"}:
            return None
        return text

    def _apply_launcher_config_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        if not isinstance(snapshot, dict) or not snapshot:
            return
        config = self.launcher.config
        if "claude_path" in snapshot:
            config.claude_path = str(snapshot["claude_path"])
        if "codex_path" in snapshot:
            config.codex_path = str(snapshot["codex_path"])
        if "timeout_seconds" in snapshot:
            config.timeout_seconds = float(snapshot["timeout_seconds"])
        if "no_progress_timeout_seconds" in snapshot:
            config.no_progress_timeout_seconds = float(snapshot["no_progress_timeout_seconds"])
        if "claude_model" in snapshot:
            config.claude_model = self._optional_snapshot_text(snapshot["claude_model"])
        if "codex_model" in snapshot:
            config.codex_model = self._optional_snapshot_text(snapshot["codex_model"])
        if "claude_profile" in snapshot:
            config.claude_profile = self._optional_snapshot_text(snapshot["claude_profile"])
        if "claude_profile_script" in snapshot:
            config.claude_profile_script = self._optional_snapshot_text(
                snapshot["claude_profile_script"]
            )
        auto_commit = _strict_bool(snapshot.get("auto_commit"))
        if auto_commit is not None:
            config.auto_commit = auto_commit
        use_managed_session_script = _strict_bool(snapshot.get("use_managed_session_script"))
        if use_managed_session_script is not None:
            config.use_managed_session_script = use_managed_session_script
        if "base_branch" in snapshot:
            config.base_branch = str(snapshot["base_branch"]).strip() or config.base_branch
        detach = _strict_bool(snapshot.get("detach"))
        if detach is not None:
            config.detach = detach
        require_explicit_approval = _strict_bool(snapshot.get("require_explicit_approval"))
        if require_explicit_approval is not None:
            config.require_explicit_approval = require_explicit_approval
        allow_claude_dangerously_skip_permissions = _strict_bool(
            snapshot.get("allow_claude_dangerously_skip_permissions")
        )
        if allow_claude_dangerously_skip_permissions is not None:
            config.allow_claude_dangerously_skip_permissions = (
                allow_claude_dangerously_skip_permissions
            )
        allow_codex_full_auto = _strict_bool(snapshot.get("allow_codex_full_auto"))
        if allow_codex_full_auto is not None:
            config.allow_codex_full_auto = allow_codex_full_auto
        if "execution_mode" in snapshot:
            try:
                config.execution_mode = ExecutionMode(str(snapshot["execution_mode"]).strip())
            except ValueError:
                logger.debug(
                    "Ignoring unknown execution mode in launcher snapshot: %r",
                    snapshot.get("execution_mode"),
                )

    def _launcher_config(self) -> LaunchConfig:
        config = getattr(self.launcher, "config", None)
        if isinstance(config, LaunchConfig):
            return config
        fallback = LaunchConfig()
        try:
            self.launcher.config = fallback
        except Exception:
            logger.debug("Unable to attach fallback LaunchConfig to launcher", exc_info=True)
        return fallback

    def start_run(
        self,
        *,
        spec: SwarmSpec,
        target_branch: str = "main",
        max_concurrency: int = 8,
        managed_dir_pattern: str = ".worktrees/{agent}-auto",
        approval_policy: SwarmApprovalPolicy | None = None,
        refresh_scaling: bool = True,
        default_target_agent: str | None = None,
        default_reviewer_agent: str | None = None,
        worker_env: dict[str, str] | None = None,
    ) -> SupervisorRun:
        goal = spec.refined_goal or spec.raw_goal
        policy = approval_policy or SwarmApprovalPolicy()
        policy.require_merge_approval = True
        work_orders = [item.to_dict() for item in self._build_supervised_work_orders(spec)]
        if default_target_agent:
            for item in work_orders:
                item["target_agent"] = default_target_agent
                if not default_reviewer_agent and not str(item.get("reviewer_agent", "")).strip():
                    item["reviewer_agent"] = (
                        "claude" if default_target_agent == "codex" else "codex"
                    )
        if default_reviewer_agent:
            for item in work_orders:
                item["reviewer_agent"] = default_reviewer_agent
        normalized_worker_env = {
            str(key).strip(): str(value)
            for key, value in dict(worker_env or {}).items()
            if str(key).strip()
        }
        for item in work_orders:
            item.setdefault("status", "queued")
            item.setdefault("lease_id", None)
            item.setdefault("receipt_id", None)
            item.setdefault("review_status", "pending")
            if default_target_agent:
                metadata = dict(item.get("metadata") or {})
                metadata.setdefault(
                    "requested_target_agent",
                    str(default_target_agent).strip().lower(),
                )
                requested_reviewer_agent = str(item.get("reviewer_agent", "")).strip().lower()
                if requested_reviewer_agent:
                    metadata.setdefault("requested_reviewer_agent", requested_reviewer_agent)
                metadata.setdefault("sticky_target_agent", True)
                item["metadata"] = metadata
            if normalized_worker_env:
                metadata = dict(item.get("metadata") or {})
                metadata["worker_env"] = normalized_worker_env
                item["metadata"] = metadata
        self._suppress_duplicate_open_work_orders(goal, work_orders)

        record = self.store.create_supervisor_run(
            goal=goal,
            target_branch=target_branch,
            supervisor_agents={"planner": "codex", "judge": "claude"},
            approval_policy=policy.to_dict(),
            spec=spec.to_dict(),
            work_orders=work_orders,
            status=SupervisorRunStatus.PLANNED.value,
            metadata={
                "max_concurrency": min(max(1, int(max_concurrency)), 8),
                "managed_dir_pattern": managed_dir_pattern,
                LAUNCHER_CONFIG_METADATA_KEY: self._launcher_config_snapshot(
                    self._launcher_config()
                ),
                WORKER_TYPE_CIRCUIT_BREAKERS_KEY: {},
                WORKER_TYPE_CIRCUIT_BREAKER_POLICY_KEY: {
                    "failure_threshold": DEFAULT_BREAKER_FAILURE_THRESHOLD,
                    "reset_timeout_seconds": DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS,
                },
            },
        )
        run = SupervisorRun.from_record(record)
        if refresh_scaling:
            return self.refresh_run(run.run_id)
        return run

    def refresh_run(self, run_id: str) -> SupervisorRun:
        from aragora.swarm.supervisor_workers import refresh_run as _impl

        return _impl(self, run_id)

    def _collect_finished_workers_sync(self, run_id: str) -> None:
        from aragora.swarm.supervisor_workers import _collect_finished_workers_sync as _impl

        return _impl(self, run_id)

    @staticmethod
    def _run_git_capture_sync(
        worktree_path: str,
        *args: str,
        timeout: float = 10.0,
    ) -> subprocess.CompletedProcess[str]:
        from aragora.swarm.supervisor_workers import _run_git_capture_sync as _impl

        return _impl(worktree_path, *args, timeout=timeout)

    def _build_dead_worker_salvage_result(
        self,
        item: dict[str, Any],
        *,
        worktree_path: str,
        initial_head: str,
    ) -> WorkerProcess | None:
        from aragora.swarm.supervisor_workers import _build_dead_worker_salvage_result as _impl

        return _impl(self, item, worktree_path=worktree_path, initial_head=initial_head)

    def _collect_finished_results_before_reap(
        self,
        run_id: str,
        record: dict[str, Any],
    ) -> None:
        from aragora.swarm.supervisor_workers import _collect_finished_results_before_reap as _impl

        return _impl(self, run_id, record)

    def _should_precollect_finished_result(self, item: dict[str, Any]) -> bool:
        from aragora.swarm.supervisor_workers import _should_precollect_finished_result as _impl

        return _impl(self, item)

    def _reconcile_stale_work_order_state(
        self,
        work_orders: list[dict[str, Any]],
        *,
        worker_type_circuit_breakers: dict[str, dict[str, Any]] | None = None,
        worker_type_circuit_breaker_policy: dict[str, Any] | None = None,
    ) -> None:
        from aragora.swarm.supervisor_workers import _reconcile_stale_work_order_state as _impl

        return _impl(
            self,
            work_orders,
            worker_type_circuit_breakers=worker_type_circuit_breakers,
            worker_type_circuit_breaker_policy=worker_type_circuit_breaker_policy,
        )

    @staticmethod
    def _worker_result_from_persisted_work_order(item: dict[str, Any]) -> WorkerProcess | None:
        from aragora.swarm.supervisor_probes import (
            _worker_result_from_persisted_work_order as _impl,
        )

        return _impl(item)

    def _rehabilitate_validation_marker_crash_work_order(
        self,
        item: dict[str, Any],
        *,
        worker_type_circuit_breakers: dict[str, dict[str, Any]] | None = None,
        worker_type_circuit_breaker_policy: dict[str, Any] | None = None,
    ) -> None:
        from aragora.swarm.supervisor_probes import (
            _rehabilitate_validation_marker_crash_work_order as _impl,
        )

        return _impl(
            self,
            item,
            worker_type_circuit_breakers=worker_type_circuit_breakers,
            worker_type_circuit_breaker_policy=worker_type_circuit_breaker_policy,
        )

    def _recover_reaped_needs_human_deliverables(
        self,
        work_orders: list[dict[str, Any]],
        *,
        worker_type_circuit_breakers: dict[str, dict[str, Any]] | None = None,
        worker_type_circuit_breaker_policy: dict[str, Any] | None = None,
    ) -> None:
        from aragora.swarm.supervisor_workers import (
            _recover_reaped_needs_human_deliverables as _impl,
        )

        return _impl(
            self,
            work_orders,
            worker_type_circuit_breakers=worker_type_circuit_breakers,
            worker_type_circuit_breaker_policy=worker_type_circuit_breaker_policy,
        )

    @staticmethod
    def _dependencies_ready_for_dispatch(
        item: dict[str, Any],
        work_orders: list[dict[str, Any]],
    ) -> bool:
        return bool(build_dependency_context_payload(item, work_orders)["ready_for_dispatch"])

    @staticmethod
    def _sync_dependency_context_metadata(
        item: dict[str, Any],
        work_orders: list[dict[str, Any]],
        *,
        prompt_ready: bool = False,
    ) -> dict[str, Any]:
        metadata = dict(item.get("metadata") or {})
        dependency_ids = dependency_ids_for_work_order(item)
        base_description = str(
            metadata.get("dependency_context_base_description", item.get("description", "")) or ""
        ).strip()

        if not dependency_ids:
            for key in (
                "dependency_context",
                "dependency_context_prompt",
                "dependency_context_ready",
                "dependency_missing_ids",
                "dependency_terminal_failure",
                "dependency_context_base_description",
            ):
                metadata.pop(key, None)
            if metadata:
                item["metadata"] = metadata
            else:
                item.pop("metadata", None)
            item["description"] = base_description
            return {
                "dependency_ids": [],
                "contexts": [],
                "missing_dependency_ids": [],
                "ready_for_dispatch": True,
                "base_reference": None,
                "base_reference_dependency_id": None,
                "terminal_failure": None,
                "prompt_summary": "",
            }

        payload = build_dependency_context_payload(item, work_orders)
        metadata["dependency_context_base_description"] = base_description
        metadata["dependency_context"] = list(payload["contexts"])
        metadata["dependency_context_ready"] = bool(payload["ready_for_dispatch"])
        if payload["missing_dependency_ids"]:
            metadata["dependency_missing_ids"] = list(payload["missing_dependency_ids"])
        else:
            metadata.pop("dependency_missing_ids", None)
        if payload["terminal_failure"] is not None:
            metadata["dependency_terminal_failure"] = dict(payload["terminal_failure"])
        else:
            metadata.pop("dependency_terminal_failure", None)
        prompt_summary = str(payload["prompt_summary"]).strip()
        if prompt_summary:
            metadata["dependency_context_prompt"] = prompt_summary
        else:
            metadata.pop("dependency_context_prompt", None)
        item["metadata"] = metadata
        item["description"] = (
            compose_dependency_description(base_description, prompt_summary)
            if prompt_ready
            else base_description
        )
        return payload

    @staticmethod
    def _replacement_active_lease(
        item: dict[str, Any],
        active_leases: dict[str, Any],
    ) -> Any | None:
        current_lease_id = str(item.get("lease_id", "")).strip()
        if current_lease_id in active_leases:
            return None

        owner_session_id = str(item.get("owner_session_id", "")).strip()
        work_order_id = str(item.get("work_order_id", "")).strip()
        task_key = str(item.get("task_key", "")).strip()
        branch = str(item.get("branch", "")).strip()
        worktree_path = str(item.get("worktree_path", "")).strip()

        candidates = []
        for lease in active_leases.values():
            if str(getattr(lease, "lease_id", "")).strip() == current_lease_id:
                continue
            if (
                owner_session_id
                and str(getattr(lease, "owner_session_id", "")).strip() != owner_session_id
            ):
                continue
            metadata = getattr(lease, "metadata", {}) or {}
            lease_work_order_id = (
                str(metadata.get("work_order_id", "")).strip()
                or str(getattr(lease, "task_id", "")).strip()
            )
            lease_task_key = str(metadata.get("task_key", "")).strip()
            if work_order_id and lease_work_order_id and lease_work_order_id != work_order_id:
                continue
            if task_key and lease_task_key and lease_task_key != task_key:
                continue
            if branch and str(getattr(lease, "branch", "")).strip() not in {"", branch}:
                continue
            if worktree_path and str(getattr(lease, "worktree_path", "")).strip() not in {
                "",
                worktree_path,
            }:
                continue
            candidates.append(lease)

        if not candidates:
            return None
        return max(candidates, key=lambda lease: str(getattr(lease, "updated_at", "")).strip())

    @staticmethod
    def _apply_active_lease_binding(item: dict[str, Any], lease: Any) -> None:
        item["lease_id"] = str(getattr(lease, "lease_id", "")).strip() or item.get("lease_id")
        item["owner_session_id"] = str(getattr(lease, "owner_session_id", "")).strip() or item.get(
            "owner_session_id"
        )
        item["branch"] = str(getattr(lease, "branch", "")).strip() or item.get("branch")
        item["worktree_path"] = str(getattr(lease, "worktree_path", "")).strip() or item.get(
            "worktree_path"
        )
        if getattr(lease, "owner_agent", None):
            item["target_agent"] = str(getattr(lease, "owner_agent")).strip()
        target_agent = str(item.get("target_agent", "")).strip()
        target_agent_normalized = target_agent.lower()
        lease_metadata = getattr(lease, "metadata", {}) or {}
        reviewer_agent = (
            str(lease_metadata.get("reviewer_agent", "")).strip()
            or str(lease_metadata.get("requested_reviewer_agent", "")).strip()
            or str((item.get("metadata") or {}).get("requested_reviewer_agent", "")).strip()
            or str(item.get("reviewer_agent", "")).strip()
        )
        if reviewer_agent.lower() == target_agent_normalized:
            reviewer_agent = ""
        if not reviewer_agent:
            reviewer_agent = SwarmSupervisor._alternate_agent(target_agent) or ""
        if reviewer_agent:
            item["reviewer_agent"] = reviewer_agent
        expected_tests = [
            str(test).strip() for test in getattr(lease, "expected_tests", []) if str(test).strip()
        ]
        item["expected_tests"] = expected_tests
        item["review_status"] = "pending"
        for key in (
            "dispatch_error",
            "resource_error",
            "blocking_question",
            "failure_reason",
            "blocker",
            "conflicts",
            "receipt_id",
            "confidence",
            "worker_outcome",
            "completed_at",
            "exit_code",
            "initial_head",
            "head_sha",
            "commit_shas",
            "changed_paths",
            "diff",
            "diff_lines",
            "stdout_tail",
            "stderr_tail",
            "tests_run",
            "verification_results",
            "merge_gate",
            "verification_missing_reason",
            "pr_url",
            "adopted_pr",
            "scope_violation",
            "pid",
            "dispatched_at",
            "last_observed_at",
            "last_progress_at",
            "first_output_at",
            "last_output_at",
            "progress_fingerprint",
            "output_fingerprint",
        ):
            item.pop(key, None)
        item.pop("blockers", None)
        metadata = getattr(lease, "metadata", {}) or {}
        raw_worker_pid = metadata.get("worker_pid")
        pid_value: int | None = None
        if raw_worker_pid is not None and not isinstance(raw_worker_pid, bool):
            try:
                pid_value = int(str(raw_worker_pid))
            except ValueError:
                pid_value = None
        if pid_value and pid_value > 0:
            item["pid"] = pid_value
            item["status"] = "dispatched"
            return

        # Rebinding onto an active lease with no worker PID means the lease is
        # live but not yet dispatched. Drop stale dispatch-only state from the
        # replaced lease so the lane can launch cleanly on the next iteration.
        item["status"] = "leased"

    def _prune_stale_conflicts(
        self,
        item: dict[str, Any],
        active_leases: dict[str, Any],
        live_claims: list[dict[str, Any]],
    ) -> None:
        raw_conflicts = item.get("conflicts")
        if not isinstance(raw_conflicts, list) or not raw_conflicts:
            return

        current_lease_id = str(item.get("lease_id", "")).strip()
        live_claim_keys = {
            (
                str(claim.get("session_id", "")).strip(),
                str(claim.get("path", "")).strip(),
            )
            for claim in live_claims
        }
        live_claim_sessions = {
            str(claim.get("session_id", "")).strip()
            for claim in live_claims
            if claim.get("session_id")
        }

        kept: list[dict[str, Any]] = []
        for conflict in raw_conflicts:
            if not isinstance(conflict, dict):
                continue
            source = str(conflict.get("source", "lease")).strip()
            if source in {"lease", ""}:
                conflict_lease_id = str(conflict.get("lease_id", "")).strip()
                if conflict_lease_id == current_lease_id:
                    continue
                if conflict_lease_id and conflict_lease_id in active_leases:
                    kept.append(conflict)
                    continue
                worktree_path = str(conflict.get("worktree_path", "")).strip()
                if worktree_path and self._orphaned_conflict_reason(worktree_path):
                    continue
                if conflict_lease_id and conflict_lease_id not in active_leases:
                    continue
                kept.append(conflict)
                continue
            if source == "fleet_claim":
                session_id = str(conflict.get("session_id", "")).strip()
                path = str(conflict.get("path", "")).strip()
                if (session_id, path) in live_claim_keys:
                    kept.append(conflict)
                    continue
                if session_id and session_id in live_claim_sessions:
                    kept.append(conflict)
                continue
            kept.append(conflict)

        if kept:
            item["conflicts"] = kept
        else:
            item.pop("conflicts", None)

    def _backfill_missing_completion_receipt(self, item: dict[str, Any]) -> None:
        from aragora.swarm.supervisor_workers import _backfill_missing_completion_receipt as _impl

        return _impl(self, item)

    def status_summary(
        self,
        *,
        run_id: str | None = None,
        limit: int = 20,
        refresh_scaling: bool = False,
    ) -> dict[str, Any]:
        records = (
            [self.store.get_supervisor_run(run_id)]
            if run_id
            else self.store.list_supervisor_runs(limit=limit)
        )
        runs: list[SupervisorRun] = []
        for record in records:
            if not record:
                continue
            current = (
                self.refresh_run(record["run_id"])
                if refresh_scaling
                else SupervisorRun.from_record(record)
            )
            runs.append(current)
        coordination = self.store.status_summary(include_integrator_artifacts=True)
        return {
            "runs": [run.to_dict() for run in runs],
            "counts": {
                "runs": len(runs),
                "queued_work_orders": sum(
                    1
                    for run in runs
                    for item in run.work_orders
                    if str(item.get("status", "")) == "queued"
                ),
                "leased_work_orders": sum(
                    1
                    for run in runs
                    for item in run.work_orders
                    if str(item.get("status", "")) == "leased"
                ),
                "completed_work_orders": sum(
                    1
                    for run in runs
                    for item in run.work_orders
                    if str(item.get("status", "")) == "completed"
                ),
            },
            "coordination": coordination,
        }

    def reset_worker_type_circuit_breaker(
        self,
        run_id: str,
        worker_type: str,
    ) -> SupervisorRun:
        from aragora.swarm.supervisor_workers import reset_worker_type_circuit_breaker as _impl

        return _impl(self, run_id, worker_type)

    async def dispatch_workers(self, run_id: str) -> list[WorkerProcess]:
        from aragora.swarm.supervisor_workers import dispatch_workers as _impl

        return await _impl(self, run_id)

    async def collect_results(
        self,
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> list[WorkerProcess]:
        from aragora.swarm.supervisor_workers import collect_results as _impl

        return await _impl(self, run_id, timeout=timeout)

    async def collect_finished_results(self, run_id: str) -> list[WorkerProcess]:
        from aragora.swarm.supervisor_workers import collect_finished_results as _impl

        return await _impl(self, run_id)

    def _build_supervised_work_orders(self, spec: SwarmSpec) -> list[BoundedWorkOrder]:
        explicit = self._explicit_work_orders_from_spec(spec)
        if explicit:
            return explicit

        goal = spec.refined_goal or spec.raw_goal
        spec_hints = list(spec.file_scope_hints) if spec.file_scope_hints else []
        decomposition = self.decomposer.analyze(
            goal,
            file_scope_hints=spec_hints or None,
            acceptance_criteria=list(spec.acceptance_criteria) or None,
            constraints=list(spec.constraints) or None,
        )
        subtasks = list(decomposition.subtasks)
        if not subtasks:
            subtasks = [
                SubTask(
                    id=f"work-{uuid.uuid4().hex[:8]}",
                    title=goal[:80] or "Swarm task",
                    description=goal,
                    file_scope=list(spec.file_scope_hints),
                    success_criteria={
                        "tests": self._tests_from_acceptance(spec.acceptance_criteria),
                        "acceptance_criteria": list(spec.acceptance_criteria),
                    },
                )
            ]
        work_orders = self.bridge.build_work_orders(subtasks)
        work_orders = self._collapse_redundant_work_orders(work_orders, spec)
        if len(work_orders) == 1:
            work_orders[0].description = goal
        for item in work_orders:
            _ensure_work_order_scope(item, spec)
            item.expected_tests = self._default_tests(item, spec)
            item.risk_level = self._risk_level_for_scope(item.file_scope)
            item.approval_required = True
            item.metadata = {
                **dict(item.metadata),
                "acceptance_criteria": list(spec.acceptance_criteria),
                "constraints": list(spec.constraints),
            }
        return work_orders

    @staticmethod
    def _dependency_base_reference(
        item: dict[str, Any],
        work_orders: list[dict[str, Any]],
    ) -> tuple[str, str] | None:
        payload = build_dependency_context_payload(item, work_orders)
        base_reference = str(payload.get("base_reference") or "").strip()
        dependency_id = str(payload.get("base_reference_dependency_id") or "").strip()
        if base_reference and dependency_id:
            return base_reference, dependency_id
        return None

    def _reseed_dependent_session_branch(
        self,
        *,
        session: Any,
        work_order: dict[str, Any],
        dependency_ref: str,
        dependency_id: str,
    ) -> bool:
        def _clear_stale_deliverable_state() -> None:
            for key in (
                "dispatch_error",
                "failure_reason",
                "blocking_question",
                "blocker",
                "resource_error",
                "conflicts",
                "receipt_id",
                "confidence",
                "worker_outcome",
                "completed_at",
                "exit_code",
                "head_sha",
                "commit_shas",
                "changed_paths",
                "diff",
                "diff_lines",
                "stdout_tail",
                "stderr_tail",
                "tests_run",
                "verification_results",
                "merge_gate",
                "verification_missing_reason",
                "pr_url",
                "adopted_pr",
                "scope_violation",
            ):
                work_order.pop(key, None)
            work_order.pop("blockers", None)

        if not self._is_safe_dependency_ref(str(session.path), dependency_ref):
            _clear_stale_deliverable_state()
            self._mark_needs_human(
                work_order,
                (
                    "Dependent lane received an invalid prerequisite branch reference; "
                    "reconcile the dependency chain before rerunning."
                ),
                failure_reason="dependency_base_conflict",
                blocking_question=(
                    "Which completed dependency branch or commit should this lane build on?"
                ),
            )
            work_order["dispatch_error"] = f"unsafe dependency base reference: {dependency_ref!r}"
            work_order["dependency_base_ref"] = dependency_ref
            work_order["dependency_base_source"] = dependency_id
            return False

        session_path = str(session.path)
        status_proc = self._run_git_capture_sync(session_path, "status", "--porcelain")
        if status_proc.returncode != 0:
            _clear_stale_deliverable_state()
            self._mark_needs_human(
                work_order,
                (
                    "Dependent lane could not inspect its managed worktree before applying the "
                    "prerequisite branch; reconcile the dependency chain before rerunning."
                ),
                failure_reason="dependency_base_conflict",
                blocking_question=(
                    "Which completed dependency branch or commit should this lane build on?"
                ),
            )
            work_order["dispatch_error"] = (
                status_proc.stderr.strip()
                or status_proc.stdout.strip()
                or "unable to inspect dependent lane worktree before applying dependency base"
            )
            work_order["dependency_base_ref"] = dependency_ref
            work_order["dependency_base_source"] = dependency_id
            return False
        if status_proc.stdout.strip():
            _clear_stale_deliverable_state()
            self._mark_needs_human(
                work_order,
                (
                    "Dependent lane already has unmanaged worktree changes; reconcile the "
                    "dependency chain before rerunning."
                ),
                failure_reason="dependency_base_conflict",
                blocking_question=(
                    "Which completed dependency branch or commit should this lane build on?"
                ),
            )
            work_order["dispatch_error"] = (
                "managed dependent lane worktree is dirty before applying dependency base"
            )
            work_order["dependency_base_ref"] = dependency_ref
            work_order["dependency_base_source"] = dependency_id
            return False

        checkout_proc = self._run_git_capture_sync(
            session_path,
            "checkout",
            "-B",
            str(session.branch),
            dependency_ref,
        )
        if checkout_proc.returncode != 0:
            _clear_stale_deliverable_state()
            self._mark_needs_human(
                work_order,
                (
                    "Dependent lane could not start from its prerequisite branch; "
                    "reconcile the dependency chain before rerunning."
                ),
                failure_reason="dependency_base_conflict",
                blocking_question=(
                    "Which completed dependency branch or commit should this lane build on?"
                ),
            )
            work_order["dispatch_error"] = (
                checkout_proc.stderr.strip()
                or checkout_proc.stdout.strip()
                or f"unable to reseed dependent lane onto {dependency_ref}"
            )
            work_order["dependency_base_ref"] = dependency_ref
            work_order["dependency_base_source"] = dependency_id
            return False

        work_order["dependency_base_ref"] = dependency_ref
        work_order["dependency_base_source"] = dependency_id
        return True

    @classmethod
    def _is_safe_dependency_ref(cls, worktree_path: str, dependency_ref: str) -> bool:
        """Allow completed dependency references that are valid SHAs or git branch names."""
        reference = dependency_ref.strip()
        if not reference or reference.startswith("-"):
            return False
        if cls._DEPENDENCY_SHA_PATTERN.fullmatch(reference):
            return True
        check_proc = cls._run_git_capture_sync(
            worktree_path,
            "check-ref-format",
            "--branch",
            reference,
        )
        return check_proc.returncode == 0

    def _explicit_work_orders_from_spec(self, spec: SwarmSpec) -> list[BoundedWorkOrder]:
        if not spec.work_orders:
            return []

        work_orders: list[BoundedWorkOrder] = []
        pipeline_id_by_work_order: dict[str, str] = {}
        normalized_payloads = [
            dict(payload) for payload in spec.work_orders if isinstance(payload, dict)
        ]
        explicit_ids: list[str] = []

        for index, payload in enumerate(normalized_payloads, start=1):
            work_order_id = str(payload.get("work_order_id", "")).strip() or f"work-{index}"
            explicit_ids.append(work_order_id)
            pipeline_id_by_work_order[work_order_id] = (
                str(payload.get("pipeline_task_id", "")).strip() or f"task-{index}"
            )

        for index, payload in enumerate(normalized_payloads, start=1):
            work_order_id = explicit_ids[index - 1]
            pipeline_task_id = pipeline_id_by_work_order[work_order_id]
            target_agent = str(payload.get("target_agent", "")).strip()
            reviewer_agent = str(payload.get("reviewer_agent", "")).strip()
            if not target_agent:
                target_agent = "codex" if (index - 1) % 2 == 0 else "claude"
            if not reviewer_agent:
                reviewer_agent = "claude" if target_agent == "codex" else "codex"

            success_criteria = dict(payload.get("success_criteria") or {})
            expected_tests = [
                str(item).strip() for item in payload.get("expected_tests", []) if str(item).strip()
            ]
            if expected_tests and "tests" not in success_criteria:
                success_criteria["tests"] = list(expected_tests)

            estimated_complexity = (
                str(payload.get("estimated_complexity", "medium")).strip() or "medium"
            )
            risk_level = str(payload.get("risk_level", "")).strip() or self._risk_level_for_scope(
                [str(item) for item in payload.get("file_scope", []) if str(item).strip()]
            )

            dependency_ids = [
                str(dep).strip() for dep in payload.get("dependency_ids", []) if str(dep).strip()
            ]
            if not dependency_ids:
                dependency_ids = [
                    pipeline_id_by_work_order.get(str(dep).strip(), str(dep).strip())
                    for dep in payload.get("dependencies", [])
                    if str(dep).strip()
                ]

            work_orders.append(
                BoundedWorkOrder(
                    work_order_id=work_order_id,
                    pipeline_task_id=pipeline_task_id,
                    title=str(payload.get("title", "")).strip() or work_order_id,
                    description=str(payload.get("description", "")).strip()
                    or str(payload.get("title", "")).strip()
                    or spec.refined_goal
                    or spec.raw_goal,
                    file_scope=[
                        normalized
                        for item in payload.get("file_scope", [])
                        if (normalized := SwarmSpec.sanitize_file_scope_entry(item))
                    ],
                    dependency_ids=dependency_ids,
                    success_criteria=success_criteria,
                    expected_tests=expected_tests,
                    estimated_complexity=estimated_complexity,
                    risk_level=risk_level,
                    target_agent=target_agent,
                    reviewer_agent=reviewer_agent,
                    approval_required=_coerce_bool(
                        payload.get("approval_required"),
                        default=True,
                    ),
                    mission_id=str(payload.get("mission_id", "")).strip() or spec.mission_id,
                    stage_id=str(payload.get("stage_id", "")).strip() or spec.stage_id,
                    assertion_ids=[
                        str(item).strip()
                        for item in payload.get("assertion_ids", [])
                        if str(item).strip()
                    ]
                    or list(spec.assertion_ids),
                    roadmap_refs=[
                        str(item).strip()
                        for item in payload.get("roadmap_refs", [])
                        if str(item).strip()
                    ]
                    or list(spec.roadmap_refs),
                    evidence_expectations=[
                        str(item).strip()
                        for item in payload.get("evidence_expectations", [])
                        if str(item).strip()
                    ]
                    or list(spec.evidence_expectations),
                    gate_expectations=dict(payload.get("gate_expectations") or {})
                    or dict(spec.gate_expectations),
                    mission_context_policies=dict(payload.get("mission_context_policies") or {})
                    or dict(spec.mission_context_policies),
                    metadata={
                        **dict(payload.get("metadata") or {}),
                        "source": "explicit_spec_work_order",
                    },
                )
            )

        # Merge spec.file_scope_hints into explicit work orders so scope
        # enforcement is never bypassed when the upstream planner leaves
        # file_scope empty on individual work orders (fixes #884).
        spec_hints = list(spec.file_scope_hints) if spec.file_scope_hints else []
        for item in work_orders:
            if spec_hints:
                if not item.file_scope:
                    item.file_scope = list(spec_hints)
                    logger.info(
                        "Backfilled empty file_scope on explicit work order %s from spec hints: %s",
                        item.work_order_id,
                        spec_hints,
                    )
                else:
                    merged = list(dict.fromkeys(item.file_scope + list(spec_hints)))
                    if set(merged) != set(item.file_scope):
                        logger.info(
                            "Merged spec hints into explicit work order %s file_scope: %s -> %s",
                            item.work_order_id,
                            item.file_scope,
                            merged,
                        )
                    item.file_scope = merged
            _narrow_scope_to_explicit_paths(item, spec)
            item.expected_tests = self._default_tests(item, spec)
            item.risk_level = str(item.risk_level).strip() or self._risk_level_for_scope(
                item.file_scope
            )
            item.metadata = {
                **dict(item.metadata),
                "acceptance_criteria": list(spec.acceptance_criteria),
                "constraints": list(spec.constraints),
            }

        filtered_work_orders = [
            item
            for item in work_orders
            if not _looks_like_non_actionable_explicit_spec_work_order(item, spec)
        ]
        filtered_work_orders = [
            item
            for item in filtered_work_orders
            if not _looks_like_umbrella_explicit_spec_work_order(item, spec, filtered_work_orders)
        ]
        if filtered_work_orders:
            dropped = len(work_orders) - len(filtered_work_orders)
            if dropped:
                logger.info(
                    "Dropped %d non-actionable explicit spec work orders from %d total payloads",
                    dropped,
                    len(work_orders),
                )
            work_orders = filtered_work_orders

        return work_orders

    def _lease_work_order(
        self,
        *,
        run_id: str,
        target_branch: str,
        work_order: dict[str, Any],
        work_orders: list[dict[str, Any]],
        managed_dir_pattern: str,
        approval_policy: SwarmApprovalPolicy,
    ) -> bool:
        from aragora.swarm.supervisor_workers import _lease_work_order as _impl

        return _impl(
            self,
            run_id=run_id,
            target_branch=target_branch,
            work_order=work_order,
            work_orders=work_orders,
            managed_dir_pattern=managed_dir_pattern,
            approval_policy=approval_policy,
        )

    @staticmethod
    def _strip_session_artifacts(paths: list[str]) -> list[str]:
        from aragora.swarm.supervisor_probes import _strip_session_artifacts as _impl

        return _impl(paths)

    def _campaign_metadata(
        self,
        metadata: dict[str, Any],
        work_orders: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = dict(metadata)
        outcome, blockers = self._campaign_outcome_for_work_orders(work_orders)
        has_deliverable = any(self._work_order_deliverable_type(item) for item in work_orders)
        if not outcome:
            payload.pop(CAMPAIGN_OUTCOME_METADATA_KEY, None)
            payload.pop(CAMPAIGN_REQUEUE_ELIGIBLE_METADATA_KEY, None)
            payload.pop(CAMPAIGN_BLOCKERS_METADATA_KEY, None)
            return payload

        payload[CAMPAIGN_OUTCOME_METADATA_KEY] = outcome
        payload[CAMPAIGN_REQUEUE_ELIGIBLE_METADATA_KEY] = (
            self._campaign_requeue_eligible(outcome) and not has_deliverable
        )
        if blockers:
            payload[CAMPAIGN_BLOCKERS_METADATA_KEY] = blockers[:10]
        else:
            payload.pop(CAMPAIGN_BLOCKERS_METADATA_KEY, None)

        # Attach chain execution summary when a work chain is present
        if outcome and "work_chain" in payload:
            try:
                chain_summary = self._build_chain_summary(payload, work_orders)
                if chain_summary:
                    payload["chain_summary"] = chain_summary
            except (KeyError, TypeError, ValueError):
                logger.debug("chain summary generation skipped", exc_info=True)

        return payload

    @staticmethod
    def _build_chain_summary(
        metadata: dict[str, Any],
        work_orders: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Build a chain execution summary from work_chain metadata."""
        chain_data = metadata.get("work_chain")
        if not isinstance(chain_data, dict):
            return None
        total = len(chain_data.get("steps", []))
        if total == 0:
            return None
        completed = sum(
            1 for wo in work_orders if str(wo.get("status", "")).strip() in {"completed", "merged"}
        )
        failed = sum(
            1
            for wo in work_orders
            if str(wo.get("status", "")).strip()
            in {"failed", "discarded", "scope_violation", "timed_out"}
        )
        skipped = sum(1 for wo in work_orders if str(wo.get("status", "")).strip() == "skipped")
        return {
            "total_steps": total,
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "remaining": max(0, total - completed - failed - skipped),
            "waves": len(chain_data.get("waves", [])),
        }

    @classmethod
    def _campaign_outcome_for_work_orders(
        cls,
        work_orders: list[dict[str, Any]],
    ) -> tuple[str | None, list[str]]:
        statuses = {
            str(item.get("status", "")).strip().lower()
            for item in work_orders
            if isinstance(item, dict) and str(item.get("status", "")).strip()
        }
        worker_outcomes = {
            str(item.get("worker_outcome", "")).strip().lower()
            for item in work_orders
            if isinstance(item, dict) and str(item.get("worker_outcome", "")).strip()
        }
        # Definitive terminal signals take precedence over stalled — a crash
        # or scope_violation is a concrete outcome that trumps waiting states.
        crash_outcomes = {
            WorkerOutcome.CRASH.value,
            WorkerOutcome.CRASH_WITH_SALVAGE.value,
        }
        if worker_outcomes & crash_outcomes:
            blockers = cls._campaign_blockers_from_work_orders(work_orders)
            return "crash", blockers
        if "scope_violation" in statuses:
            blockers = cls._campaign_blockers_from_work_orders(work_orders)
            return "blocked", blockers

        forward_progress_statuses = {"queued", "leased", "dispatched"}
        stalled_wait_statuses = {"waiting_conflict", "waiting_resource"}
        stalled_dead_end = bool(statuses & stalled_wait_statuses) and not (
            statuses & forward_progress_statuses
        )
        if stalled_dead_end or WorkerOutcome.TIMEOUT_NO_PROGRESS.value in worker_outcomes:
            blockers = cls._campaign_blockers_from_work_orders(work_orders)
            return "stalled", blockers

        qualification = qualify_run_terminal_state(
            {
                "status": cls._derive_status(work_orders),
                "work_orders": [dict(item) for item in work_orders if isinstance(item, dict)],
            }
        )
        if qualification.terminal_outcome == "unknown":
            return None, qualification.reasons
        return qualification.terminal_outcome, qualification.reasons

    @staticmethod
    def _campaign_blockers_from_work_orders(work_orders: list[dict[str, Any]]) -> list[str]:
        blockers: list[str] = []
        for item in work_orders:
            if not isinstance(item, dict):
                continue
            for value in item.get("blockers", []):
                text = str(value).strip()
                if text and text not in blockers:
                    blockers.append(text)
            dispatch_error = str(item.get("dispatch_error", "")).strip()
            if dispatch_error and dispatch_error not in blockers:
                blockers.append(dispatch_error)
        return blockers

    @staticmethod
    def _campaign_requeue_eligible(outcome: str) -> bool:
        return outcome in {
            "clean_exit_no_deliverable",
            "timeout",
            "crash",
        }

    @staticmethod
    def _work_order_deliverable_type(item: dict[str, Any]) -> str | None:
        deliverable = extract_work_order_deliverable(item, require_terminal_status=False)
        if not deliverable:
            return None
        deliverable_type = str(deliverable.get("type", "")).strip()
        if deliverable_type == "adopted_pr":
            return "pr_adopted"
        return "deliverable_created"

    @classmethod
    def _latest_commit_subject(cls, worktree_path: str, commit_shas: list[str]) -> str:
        from aragora.swarm.supervisor_probes import _latest_commit_subject as _impl

        return _impl(cls, worktree_path, commit_shas)

    @classmethod
    def _should_accept_validation_marker_commit(
        cls,
        item: dict[str, Any],
        result: WorkerProcess,
        clean_paths: list[str],
    ) -> bool:
        from aragora.swarm.supervisor_probes import _should_accept_validation_marker_commit as _impl

        return _impl(cls, item, result, clean_paths)

    @staticmethod
    def _synthesized_validation_marker_verification(
        item: dict[str, Any],
        result: WorkerProcess,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        from aragora.swarm.supervisor_probes import (
            _synthesized_validation_marker_verification as _impl,
        )

        return _impl(item, result)

    def _finalize_completed_work_order_result(
        self,
        item: dict[str, Any],
        result: WorkerProcess,
        *,
        clean_paths: list[str],
        worker_type_circuit_breakers: dict[str, dict[str, Any]] | None = None,
        worker_type_circuit_breaker_policy: dict[str, Any] | None = None,
    ) -> bool:
        from aragora.swarm.supervisor_probes import _finalize_completed_work_order_result as _impl

        return _impl(
            self,
            item,
            result,
            clean_paths=clean_paths,
            worker_type_circuit_breakers=worker_type_circuit_breakers,
            worker_type_circuit_breaker_policy=worker_type_circuit_breaker_policy,
        )

    def _apply_worker_result(
        self,
        item: dict[str, Any],
        result: WorkerProcess,
        *,
        worker_type_circuit_breakers: dict[str, dict[str, Any]] | None = None,
        worker_type_circuit_breaker_policy: dict[str, Any] | None = None,
    ) -> None:
        # Strip session artifacts before any qualification logic runs
        from aragora.swarm.supervisor_probes import _apply_worker_result as _impl

        return _impl(
            self,
            item,
            result,
            worker_type_circuit_breakers=worker_type_circuit_breakers,
            worker_type_circuit_breaker_policy=worker_type_circuit_breaker_policy,
        )

    def _release_terminal_lease(self, item: dict[str, Any]) -> None:
        from aragora.swarm.supervisor_workers import _release_terminal_lease as _impl

        return _impl(self, item)

    def _record_terminal_work_order_telemetry(
        self,
        run_id: str,
        work_orders: list[dict[str, Any]],
    ) -> None:
        from aragora.swarm.supervisor_workers import _record_terminal_work_order_telemetry as _impl

        return _impl(self, run_id, work_orders)

    def _register_pr_if_present(self, item: dict[str, Any], result: WorkerProcess) -> None:
        from aragora.swarm.supervisor_workers import _register_pr_if_present as _impl

        return _impl(self, item, result)

    @staticmethod
    def _extract_pr_number(pr_reference: str) -> int | None:
        text = str(pr_reference or "").strip().rstrip("/")
        if not text:
            return None
        tail = text.rsplit("/", 1)[-1]
        return int(tail) if tail.isdigit() else None

    def _requeue_after_dispatch_error(
        self,
        item: dict[str, Any],
        exc: Exception,
        *,
        worker_type_circuit_breakers: dict[str, dict[str, Any]] | None = None,
    ) -> bool:
        from aragora.swarm.supervisor_workers import _requeue_after_dispatch_error as _impl

        return _impl(self, item, exc, worker_type_circuit_breakers=worker_type_circuit_breakers)

    def _requeue_after_worker_failure(
        self,
        item: dict[str, Any],
        result: WorkerProcess,
        *,
        worker_type_circuit_breakers: dict[str, dict[str, Any]] | None = None,
    ) -> bool:
        from aragora.swarm.supervisor_workers import _requeue_after_worker_failure as _impl

        return _impl(self, item, result, worker_type_circuit_breakers=worker_type_circuit_breakers)

    def _requeue_with_fallback(
        self,
        item: dict[str, Any],
        *,
        reason: str,
        detail: str,
        worker_type_circuit_breakers: dict[str, dict[str, Any]] | None = None,
    ) -> bool:
        from aragora.swarm.supervisor_workers import _requeue_with_fallback as _impl

        return _impl(
            self,
            item,
            reason=reason,
            detail=detail,
            worker_type_circuit_breakers=worker_type_circuit_breakers,
        )

    @staticmethod
    def _dispatch_failure_reason(exc: Exception) -> str:
        from aragora.swarm.supervisor_workers import _dispatch_failure_reason as _impl

        return _impl(exc)

    def _capacity_failure_detail(self, result: WorkerProcess) -> str:
        from aragora.swarm.supervisor_probes import _capacity_failure_detail as _impl

        return _impl(self, result)

    @staticmethod
    def _keyword_capacity_failure_detail(combined: str, agent_name: str) -> str:
        from aragora.swarm.supervisor_probes import _keyword_capacity_failure_detail as _impl

        return _impl(combined, agent_name)

    def _worker_type_circuit_breaker_policy(self, metadata: dict[str, Any]) -> dict[str, Any]:
        from aragora.swarm.supervisor_workers import _worker_type_circuit_breaker_policy as _impl

        return _impl(self, metadata)

    def _worker_type_circuit_breakers(
        self,
        metadata: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        from aragora.swarm.supervisor_workers import _worker_type_circuit_breakers as _impl

        return _impl(self, metadata)

    def _worker_type_circuit_breaker_metadata(
        self,
        metadata: dict[str, Any],
        circuit_breakers: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        from aragora.swarm.supervisor_workers import _worker_type_circuit_breaker_metadata as _impl

        return _impl(self, metadata, circuit_breakers)

    @staticmethod
    def _default_worker_type_circuit_breaker(policy: dict[str, Any]) -> dict[str, Any]:
        from aragora.swarm.supervisor_workers import _default_worker_type_circuit_breaker as _impl

        return _impl(policy)

    @staticmethod
    def _normalized_timestamp(value: Any) -> str | None:
        from aragora.swarm.supervisor_workers import _normalized_timestamp as _impl

        return _impl(value)

    @staticmethod
    def _worker_type_circuit_breaker_is_open(
        circuit_breakers: dict[str, dict[str, Any]],
        worker_type: str,
    ) -> bool:
        from aragora.swarm.supervisor_workers import _worker_type_circuit_breaker_is_open as _impl

        return _impl(circuit_breakers, worker_type)

    def _worker_type_circuit_breaker_detail(
        self,
        worker_type: str,
        breaker: dict[str, Any],
    ) -> str:
        from aragora.swarm.supervisor_workers import _worker_type_circuit_breaker_detail as _impl

        return _impl(self, worker_type, breaker)

    def _record_worker_type_failure(
        self,
        circuit_breakers: dict[str, dict[str, Any]],
        worker_type: str,
        *,
        reason: str,
        detail: str,
        open_immediately: bool = False,
        policy: dict[str, Any] | None = None,
    ) -> None:
        from aragora.swarm.supervisor_workers import _record_worker_type_failure as _impl

        return _impl(
            self,
            circuit_breakers,
            worker_type,
            reason=reason,
            detail=detail,
            open_immediately=open_immediately,
            policy=policy,
        )

    def _record_worker_type_success(
        self,
        circuit_breakers: dict[str, dict[str, Any]],
        worker_type: str,
    ) -> None:
        from aragora.swarm.supervisor_workers import _record_worker_type_success as _impl

        return _impl(self, circuit_breakers, worker_type)

    def _reset_worker_type_circuit_breaker_entry(
        self,
        circuit_breakers: dict[str, dict[str, Any]],
        worker_type: str,
        *,
        now: datetime | None = None,
    ) -> None:
        from aragora.swarm.supervisor_workers import (
            _reset_worker_type_circuit_breaker_entry as _impl,
        )

        return _impl(self, circuit_breakers, worker_type, now=now)

    def _expire_worker_type_circuit_breakers(
        self,
        circuit_breakers: dict[str, dict[str, Any]],
    ) -> None:
        from aragora.swarm.supervisor_workers import _expire_worker_type_circuit_breakers as _impl

        return _impl(self, circuit_breakers)

    def _mark_worker_type_blocked(
        self,
        item: dict[str, Any],
        *,
        worker_type: str,
        detail: str,
    ) -> None:
        from aragora.swarm.supervisor_workers import _mark_worker_type_blocked as _impl

        return _impl(self, item, worker_type=worker_type, detail=detail)

    @staticmethod
    def _mark_dispatch_failed(item: dict[str, Any], reason: str) -> None:
        from aragora.swarm.supervisor_workers import _mark_dispatch_failed as _impl

        return _impl(item, reason)

    @staticmethod
    def _clear_stale_prelaunch_deliverable_state(item: dict[str, Any]) -> None:
        from aragora.swarm.supervisor_workers import (
            _clear_stale_prelaunch_deliverable_state as _impl,
        )

        return _impl(item)

    @staticmethod
    def _clear_stale_runtime_deliverable_state(item: dict[str, Any]) -> None:
        from aragora.swarm.supervisor_workers import _clear_stale_runtime_deliverable_state as _impl

        return _impl(item)

    def _release_orphaned_conflict_leases(self, conflicts: list[dict[str, Any]]) -> int:
        from aragora.swarm.supervisor_workers import _release_orphaned_conflict_leases as _impl

        return _impl(self, conflicts)

    def _orphaned_conflict_reason(self, worktree_path: str) -> str | None:
        from aragora.swarm.supervisor_workers import _orphaned_conflict_reason as _impl

        return _impl(self, worktree_path)

    def _is_managed_worktree(self, path: Path) -> bool:
        from aragora.swarm.supervisor_workers import _is_managed_worktree as _impl

        return _impl(self, path)

    @classmethod
    def _session_lock_state(cls, worktree_path: Path) -> str:
        from aragora.swarm.supervisor_workers import _session_lock_state as _impl

        return _impl(cls, worktree_path)

    @staticmethod
    def _parse_session_lock_pids(lock_path: Path) -> list[int]:
        from aragora.swarm.supervisor_workers import _parse_session_lock_pids as _impl

        return _impl(lock_path)

    @staticmethod
    def _is_resource_constraint_error(exc: Exception) -> bool:
        from aragora.swarm.supervisor_workers import _is_resource_constraint_error as _impl

        return _impl(exc)

    @staticmethod
    def _alternate_agent(agent: str | None) -> str | None:
        from aragora.swarm.supervisor_workers import _alternate_agent as _impl

        return _impl(agent)

    @staticmethod
    def _completion_confidence(item: dict[str, Any], result: WorkerProcess) -> float:
        from aragora.swarm.supervisor_probes import _completion_confidence as _impl

        return _impl(item, result)

    @staticmethod
    def _verification_results_from_result(result: WorkerProcess) -> list[dict[str, Any]]:
        from aragora.swarm.supervisor_probes import _verification_results_from_result as _impl

        return _impl(result)

    @staticmethod
    def _canonical_verification_command(command: Any) -> str:
        from aragora.swarm.supervisor_probes import _canonical_verification_command as _impl

        return _impl(command)

    @classmethod
    def _pytest_command_targets(cls, command: Any) -> list[str]:
        from aragora.swarm.supervisor_probes import _pytest_command_targets as _impl

        return _impl(cls, command)

    @classmethod
    def _pytest_command_has_selectors(cls, command: Any) -> bool:
        from aragora.swarm.supervisor_probes import _pytest_command_has_selectors as _impl

        return _impl(cls, command)

    @classmethod
    def _verification_command_covers_expected(
        cls, recorded_command: Any, expected_command: Any
    ) -> bool:
        from aragora.swarm.supervisor_probes import _verification_command_covers_expected as _impl

        return _impl(cls, recorded_command, expected_command)

    @staticmethod
    def _merge_gate_entry_passed(entry: dict[str, Any]) -> bool:
        from aragora.swarm.supervisor_probes import _merge_gate_entry_passed as _impl

        return _impl(entry)

    @classmethod
    def _merge_gate_state(cls, item: dict[str, Any]) -> dict[str, Any]:
        from aragora.swarm.supervisor_probes import _merge_gate_state as _impl

        return _impl(cls, item)

    @staticmethod
    def _is_docs_only_path(path: Any) -> bool:
        from aragora.swarm.supervisor_probes import _is_docs_only_path as _impl

        return _impl(path)

    @classmethod
    def _work_order_is_docs_only(cls, item: dict[str, Any]) -> bool:
        from aragora.swarm.supervisor_probes import _work_order_is_docs_only as _impl

        return _impl(cls, item)

    @staticmethod
    def _merge_gate_failure_reason(merge_gate: dict[str, Any]) -> str:
        from aragora.swarm.supervisor_probes import _merge_gate_failure_reason as _impl

        return _impl(merge_gate)

    @staticmethod
    def _merge_gate_blocking_question(merge_gate: dict[str, Any]) -> str:
        from aragora.swarm.supervisor_probes import _merge_gate_blocking_question as _impl

        return _impl(merge_gate)

    @classmethod
    def _update_log_tails(
        cls,
        item: dict[str, Any],
        *,
        stdout: str,
        stderr: str,
    ) -> bool:
        from aragora.swarm.supervisor_probes import _update_log_tails as _impl

        return _impl(cls, item, stdout=stdout, stderr=stderr)

    @staticmethod
    def _log_tail(text: str, *, max_chars: int = MAX_WORKER_LOG_TAIL_CHARS) -> str:
        from aragora.swarm.supervisor_probes import _log_tail as _impl

        return _impl(text, max_chars=max_chars)

    @staticmethod
    def _progress_fingerprint(source: Any) -> dict[str, Any]:
        from aragora.swarm.supervisor_probes import _progress_fingerprint as _impl

        return _impl(source)

    @staticmethod
    def _output_fingerprint(source: Any) -> dict[str, Any]:
        from aragora.swarm.supervisor_probes import _output_fingerprint as _impl

        return _impl(source)

    def _no_progress_timeout_seconds(self) -> float:
        from aragora.swarm.supervisor_probes import _no_progress_timeout_seconds as _impl

        return _impl(self)

    def _no_progress_anchor(self, item: dict[str, Any]) -> datetime | None:
        from aragora.swarm.supervisor_probes import _no_progress_anchor as _impl

        return _impl(self, item)

    def _exceeded_no_progress_timeout(self, item: dict[str, Any]) -> bool:
        from aragora.swarm.supervisor_probes import _exceeded_no_progress_timeout as _impl

        return _impl(self, item)

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    def _mark_scope_violation(
        self,
        item: dict[str, Any],
        violations: list[dict[str, Any]],
        *,
        extra_reason: str = "",
    ) -> None:
        from aragora.swarm.supervisor_probes import _mark_scope_violation as _impl

        return _impl(self, item, violations, extra_reason=extra_reason)

    def _llm_adjudicate_scope(
        self,
        item: dict[str, Any],
        violations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        from aragora.swarm.supervisor_probes import _llm_adjudicate_scope as _impl

        return _impl(self, item, violations)

    def _llm_override_merge_gate(
        self,
        item: dict[str, Any],
        merge_gate: dict[str, Any],
    ) -> bool:
        from aragora.swarm.supervisor_probes import _llm_override_merge_gate as _impl

        return _impl(self, item, merge_gate)

    @staticmethod
    def _check_file_scope_violations(
        work_order: dict[str, Any],
        changed_paths: list[str],
    ) -> list[dict[str, Any]]:
        from aragora.swarm.supervisor_probes import _check_file_scope_violations as _impl

        return _impl(work_order, changed_paths)

    async def _kill_worker(self, item: dict[str, Any]) -> None:
        from aragora.swarm.supervisor_workers import _kill_worker as _impl

        return await _impl(self, item)

    @staticmethod
    def _derive_status(work_orders: list[dict[str, Any]]) -> str:
        statuses = {str(item.get("status", "")).strip() for item in work_orders if item}
        if not statuses:
            return SupervisorRunStatus.PLANNED.value
        terminal = {
            "merged",
            "discarded",
            "salvage",
            "completed",
            "failed",
            "timed_out",
            "scope_violation",
        }
        if statuses <= terminal:
            return SupervisorRunStatus.COMPLETED.value
        if "needs_human" in statuses or "changes_requested" in statuses:
            return SupervisorRunStatus.NEEDS_HUMAN.value
        if "dispatch_failed" in statuses:
            return SupervisorRunStatus.NEEDS_HUMAN.value
        # Deadlocked: only waiting_conflict/waiting_resource remain with no
        # forward-progress statuses (queued/leased/dispatched).  Escalate
        # instead of polling indefinitely.
        forward_progress = {"queued", "leased", "dispatched"}
        non_terminal = statuses - terminal
        if non_terminal and not (non_terminal & forward_progress):
            return SupervisorRunStatus.NEEDS_HUMAN.value
        return SupervisorRunStatus.ACTIVE.value

    @staticmethod
    def _managed_dir_for_agent(pattern: str, agent: str) -> str:
        if "{agent}" in pattern:
            return pattern.format(agent=agent)
        cleaned = pattern.rstrip("/")
        if cleaned.endswith("-auto"):
            return cleaned.replace("codex-auto", f"{agent}-auto")
        return f"{cleaned}/{agent}-auto"

    @staticmethod
    def _looks_like_glob(path: str) -> bool:
        return any(token in path for token in ("*", "?", "["))

    @staticmethod
    def _validate_file_scope(file_scope: list[str], worktree_path: str) -> list[str]:
        from aragora.swarm.supervisor_probes import _validate_file_scope as _impl

        return _impl(file_scope, worktree_path)

    @staticmethod
    def _tests_from_acceptance(acceptance_criteria: list[str]) -> list[str]:
        tests: list[str] = []
        for item in acceptance_criteria:
            text = str(item).strip()
            if text.startswith("python -m pytest") or text.startswith("pytest"):
                tests.append(text)
        return tests

    def _default_tests(self, work_order: BoundedWorkOrder, spec: SwarmSpec) -> list[str]:
        tests = [str(item) for item in work_order.expected_tests if str(item).strip()]
        if tests:
            return tests
        for path in work_order.file_scope:
            if path.startswith("tests/") and path.endswith(".py"):
                tests.append(f"python -m pytest {path} -q")
        if tests:
            return tests
        return self._tests_from_acceptance(spec.acceptance_criteria)

    def _risk_level_for_scope(self, file_scope: list[str]) -> str:
        if not file_scope:
            return "review"
        level = ApprovalLevel.INFO
        for path in file_scope:
            next_level = self.approval_policy.get_approval_level(path)
            if next_level == ApprovalLevel.CRITICAL:
                return "critical"
            if next_level == ApprovalLevel.REVIEW:
                level = ApprovalLevel.REVIEW
        return "review" if level == ApprovalLevel.REVIEW else "info"

    @staticmethod
    def _scope_overlaps_hints(file_scope: list[str], hints: list[str]) -> bool:
        """Check whether any decomposer-assigned scope overlaps with spec hints.

        Delegates to the coordination layer's ``_glob_overlap`` which supports
        exact paths, directory prefixes with ``/`` boundary checks, ``/**``
        recursive globs, and ``PurePosixPath.match()`` for standard glob
        patterns — the same semantics used by file-scope enforcement.

        Pre-strips ``./`` prefixes that ``_glob_overlap`` does not normalize.
        """
        from aragora.nomic.dev_coordination import _glob_overlap

        for scope_path in file_scope:
            clean_scope = scope_path.strip().removeprefix("./")
            if not clean_scope:
                continue
            for hint in hints:
                clean_hint = hint.strip().removeprefix("./")
                if not clean_hint:
                    continue
                if _glob_overlap(clean_scope, clean_hint):
                    return True
        return False

    @staticmethod
    def _task_prompt(spec: SwarmSpec) -> str:
        parts = [spec.refined_goal or spec.raw_goal]
        if spec.file_scope_hints:
            parts.append("File scope hints: " + ", ".join(spec.file_scope_hints))
        if spec.constraints:
            parts.append("Constraints: " + "; ".join(spec.constraints))
        if spec.acceptance_criteria:
            parts.append("Acceptance: " + "; ".join(spec.acceptance_criteria))
        return "\n".join(part for part in parts if part)
