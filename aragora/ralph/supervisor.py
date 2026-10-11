"""Ralph campaign supervisor — step-based autonomous incident commander.

Owns the outer loop above CampaignExecutor: run iterations, classify blockers,
generate repair tasks, track PR state, and resume after merge.  Each ``step()``
call advances the state machine by exactly one action.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from aragora.ralph.github_control import GitHubControl, GitHubControlError
from aragora.ralph.classifier import BlockerKind, classify_blocker
from aragora.ralph.repair import RepairTask, generate_repair_task
from aragora.triage.auto_handle_calibration import (
    AUTO_HANDLE_PATH_ADMIN_MERGE_ALLOWED,
    AutoHandleCalibrationStore,
    OUTCOME_SUCCESS,
    auto_handle_decision_id,
    fingerprint_admin_merge_class,
)

logger = logging.getLogger(__name__)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SupervisorStatus(str, Enum):
    RUNNING = "running"
    WAITING_FOR_PR = "waiting_for_pr"
    WAITING_FOR_MERGE = "waiting_for_merge"
    RESUMING = "resuming"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    STOPPED = "stopped"


class SupervisorAction(str, Enum):
    """The action taken by the last ``step()`` call."""

    CAMPAIGN_ITERATION = "campaign_iteration"
    BLOCKER_CLASSIFIED = "blocker_classified"
    REPAIR_GENERATED = "repair_generated"
    REPAIR_DISPATCHED = "repair_dispatched"
    PR_CHECKED = "pr_checked"
    CAMPAIGN_RESUMED = "campaign_resumed"
    CAMPAIGN_COMPLETED = "campaign_completed"
    ESCALATED = "escalated"
    NOOP = "noop"


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------

_DEFAULT_MAX_REPAIR_ATTEMPTS = 2
_MAX_RESUME_ATTEMPTS = 5


@dataclass(slots=True)
class SupervisorState:
    """Persistent state for the ralph campaign supervisor."""

    supervisor_id: str = ""
    campaign_manifest_path: str = ""
    campaign_id: str = ""
    status: str = SupervisorStatus.RUNNING.value
    current_step: int = 0
    last_campaign_result: dict[str, Any] = field(default_factory=dict)
    last_stop_reason: str = ""
    active_blocker: str | None = None
    blocker_history: list[dict[str, Any]] = field(default_factory=list)
    repair_attempts: int = 0
    max_repair_attempts: int = _DEFAULT_MAX_REPAIR_ATTEMPTS
    active_merge_target: dict[str, Any] | None = None
    active_repair_pr: str | None = None
    active_repair_branch: str | None = None
    active_repair_task: dict[str, Any] | None = None
    merge_commit_sha: str | None = None
    resume_attempts: int = 0
    resume_cursor: str | None = None
    budget_spent_usd: float = 0.0
    escalation_reason: str | None = None
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        compat = _compat_repair_fields_from_target(self.active_merge_target)
        return {
            "supervisor_id": self.supervisor_id,
            "campaign_manifest_path": self.campaign_manifest_path,
            "campaign_id": self.campaign_id,
            "status": self.status,
            "current_step": self.current_step,
            "last_campaign_result": self.last_campaign_result,
            "last_stop_reason": self.last_stop_reason,
            "active_blocker": self.active_blocker,
            "blocker_history": list(self.blocker_history),
            "repair_attempts": self.repair_attempts,
            "max_repair_attempts": self.max_repair_attempts,
            "active_merge_target": dict(self.active_merge_target)
            if isinstance(self.active_merge_target, dict) and self.active_merge_target
            else None,
            "active_repair_pr": self.active_repair_pr or compat["pr_url"],
            "active_repair_branch": self.active_repair_branch or compat["branch"],
            "active_repair_task": self.active_repair_task or compat["task"],
            "merge_commit_sha": self.merge_commit_sha,
            "resume_attempts": self.resume_attempts,
            "resume_cursor": self.resume_cursor,
            "budget_spent_usd": self.budget_spent_usd,
            "escalation_reason": self.escalation_reason,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SupervisorState:
        active_merge_target = data.get("active_merge_target")
        if not isinstance(active_merge_target, dict) or not active_merge_target:
            active_merge_target = _synthesize_merge_target_from_legacy_fields(data)
        compat = _compat_repair_fields_from_target(active_merge_target)
        compat_pr = _optional_text(compat.get("pr_url"))
        compat_branch = _optional_text(compat.get("branch"))
        compat_task = compat.get("task")
        if not isinstance(compat_task, dict):
            compat_task = None
        active_repair_task = data.get("active_repair_task")
        if not isinstance(active_repair_task, dict):
            active_repair_task = None
        return cls(
            supervisor_id=str(data.get("supervisor_id", "")),
            campaign_manifest_path=str(data.get("campaign_manifest_path", "")),
            campaign_id=str(data.get("campaign_id", "")),
            status=str(data.get("status", SupervisorStatus.RUNNING.value)),
            current_step=int(data.get("current_step", 0)),
            last_campaign_result=dict(data.get("last_campaign_result") or {}),
            last_stop_reason=str(data.get("last_stop_reason", "")),
            active_blocker=data.get("active_blocker"),
            blocker_history=list(data.get("blocker_history") or []),
            repair_attempts=int(data.get("repair_attempts", 0)),
            max_repair_attempts=int(data.get("max_repair_attempts", _DEFAULT_MAX_REPAIR_ATTEMPTS)),
            active_merge_target=active_merge_target,
            active_repair_pr=_optional_text(data.get("active_repair_pr")) or compat_pr,
            active_repair_branch=_optional_text(data.get("active_repair_branch")) or compat_branch,
            active_repair_task=active_repair_task or compat_task,
            merge_commit_sha=data.get("merge_commit_sha"),
            resume_attempts=int(data.get("resume_attempts", 0)),
            resume_cursor=data.get("resume_cursor"),
            budget_spent_usd=float(data.get("budget_spent_usd", 0.0)),
            escalation_reason=data.get("escalation_reason"),
            updated_at=str(data.get("updated_at", "")),
        )


def _compat_repair_fields_from_target(
    target: dict[str, Any] | None,
) -> dict[str, dict[str, Any] | str | None]:
    if not isinstance(target, dict) or target.get("kind") != "repair":
        return {"pr_url": None, "branch": None, "task": None}
    task = target.get("repair_task")
    if not isinstance(task, dict):
        task = None
    return {
        "pr_url": _optional_text(target.get("pr_url")),
        "branch": _optional_text(target.get("branch")),
        "task": task,
    }


def _synthesize_merge_target_from_legacy_fields(data: dict[str, Any]) -> dict[str, Any] | None:
    pr_url = _optional_text(data.get("active_repair_pr"))
    branch = _optional_text(data.get("active_repair_branch"))
    task = data.get("active_repair_task")
    if not pr_url and not branch and not isinstance(task, dict):
        return None
    target: dict[str, Any] = {
        "kind": "repair",
        "project_id": None,
        "run_id": _optional_text(task.get("run_id")) if isinstance(task, dict) else None,
        "branch": branch,
        "pr_url": pr_url,
        "target_branch": "main",
        "auto_merge_requested": bool(task.get("auto_merge_requested"))
        if isinstance(task, dict)
        else False,
        "last_gate_snapshot": None,
        "last_merge_action": None,
    }
    if isinstance(task, dict):
        target["repair_task"] = dict(task)
    return target


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


def load_supervisor_state(path: Path) -> SupervisorState:
    if not path.exists():
        raise FileNotFoundError(f"Supervisor state not found: {path}")
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid supervisor state: expected dict, got {type(data).__name__}")
    return SupervisorState.from_dict(data)


def save_supervisor_state(path: Path, state: SupervisorState) -> None:
    state.updated_at = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(state.to_dict(), default_flow_style=False, sort_keys=False)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Step result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StepResult:
    action: str
    status: str
    detail: str = ""
    repair_task: RepairTask | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "action": self.action,
            "status": self.status,
            "detail": self.detail,
        }
        if self.repair_task:
            d["repair_task"] = self.repair_task.to_dict()
        return d


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


class RalphSupervisor:
    """Step-based campaign supervisor.

    Each call to :meth:`step` reads the current state, performs exactly one
    action, saves the updated state, and returns a :class:`StepResult`.

    Designed for cron/ralph-loop invocation::

        while True:
            result = supervisor.step()
            if result.status in ("completed", "escalated", "stopped"):
                break
    """

    def __init__(
        self,
        *,
        state_path: Path,
        repo_root: Path | None = None,
        merge_policy: str = "manual_review_required",
        repair_budget_usd: float = 2.0,
        auto_handle_calibration_store: AutoHandleCalibrationStore | Any | None = None,
    ) -> None:
        self.state_path = state_path.resolve()
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.merge_policy = merge_policy
        self.repair_budget_usd = repair_budget_usd
        self.github = GitHubControl(repo_root=self.repo_root)
        self._pr_registry: Any = None  # lazy PullRequestRegistry
        self._auto_handle_calibration_store = (
            auto_handle_calibration_store or AutoHandleCalibrationStore()
        )

    def _get_pr_registry(self) -> Any:
        """Lazily create and return the shared PullRequestRegistry."""
        if self._pr_registry is None:
            from aragora.swarm.pr_registry import PullRequestRegistry

            state_dir = self.repo_root / ".aragora"
            self._pr_registry = PullRequestRegistry(state_dir=state_dir)
        return self._pr_registry

    def _emit_operational_receipt(
        self,
        *,
        state: SupervisorState,
        action: str,
        verdict: str,
        outputs: dict[str, Any],
    ) -> None:
        try:
            from aragora.receipts.provenance import emit_operational_receipt

            emit_operational_receipt(
                source="ralph",
                action=action,
                actor=state.supervisor_id or "ralph-supervisor",
                inputs={
                    "campaign_id": state.campaign_id,
                    "campaign_manifest_path": state.campaign_manifest_path,
                    "supervisor_id": state.supervisor_id,
                    "current_step": state.current_step,
                },
                outputs=outputs,
                verdict=verdict,
            )
        except Exception as exc:
            logger.debug("Ralph operational receipt skipped: %s", exc)

    def _emit_lane_receipt(
        self,
        *,
        state: SupervisorState,
        outcome: str,
        outputs: dict[str, Any],
    ) -> None:
        try:
            from aragora.receipts.lane import LaneCompletionReceipt, emit_lane_receipt

            receipt = LaneCompletionReceipt(
                task_id=state.campaign_id or "unknown",
                lease_id=state.supervisor_id or "unknown",
                agent_id=state.supervisor_id or "ralph-supervisor",
                outcome=outcome,
                metadata={
                    "campaign_manifest_path": state.campaign_manifest_path,
                    "current_step": state.current_step,
                    **outputs,
                },
            )
            emit_lane_receipt(receipt)
        except Exception as exc:
            logger.debug("Ralph lane receipt skipped: %s", exc)

    # -- public API --

    @classmethod
    def start(
        cls,
        *,
        manifest_path: Path,
        state_path: Path,
        repo_root: Path | None = None,
        merge_policy: str = "manual_review_required",
        max_repair_attempts: int = _DEFAULT_MAX_REPAIR_ATTEMPTS,
        repair_budget_usd: float = 2.0,
    ) -> "RalphSupervisor":
        """Initialize a new supervisor run and persist state."""
        manifest_path = manifest_path.resolve()
        if not manifest_path.exists():
            raise FileNotFoundError(f"Campaign manifest not found: {manifest_path}")

        # Read campaign_id from manifest.
        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        campaign_id = str(manifest_data.get("campaign_id", "unknown"))

        state = SupervisorState(
            supervisor_id=f"ralph-{uuid.uuid4().hex[:12]}",
            campaign_manifest_path=str(manifest_path),
            campaign_id=campaign_id,
            status=SupervisorStatus.RUNNING.value,
            max_repair_attempts=max_repair_attempts,
        )
        state_path = state_path.resolve()
        save_supervisor_state(state_path, state)

        supervisor = cls(
            state_path=state_path,
            repo_root=repo_root,
            merge_policy=merge_policy,
            repair_budget_usd=repair_budget_usd,
        )
        logger.info(
            "Ralph supervisor started: %s (campaign=%s)",
            state.supervisor_id,
            campaign_id,
        )
        return supervisor

    def step(self) -> StepResult:
        """Advance the supervisor state machine by one action."""
        state = load_supervisor_state(self.state_path)
        state.current_step += 1

        if state.status in (
            SupervisorStatus.COMPLETED.value,
            SupervisorStatus.ESCALATED.value,
            SupervisorStatus.STOPPED.value,
        ):
            return StepResult(
                action=SupervisorAction.NOOP.value,
                status=state.status,
                detail="Supervisor is in terminal state.",
            )

        if state.status == SupervisorStatus.WAITING_FOR_MERGE.value:
            result = self._step_check_merge(state)
            save_supervisor_state(self.state_path, state)
            self._emit_step_metrics(state, result)
            return result

        if state.status == SupervisorStatus.WAITING_FOR_PR.value:
            result = self._step_check_pr(state)
            save_supervisor_state(self.state_path, state)
            self._emit_step_metrics(state, result)
            return result

        if state.status == SupervisorStatus.RESUMING.value:
            result = self._step_resume(state)
            save_supervisor_state(self.state_path, state)
            self._emit_step_metrics(state, result)
            return result

        # status == RUNNING: run one campaign iteration.
        if state.active_blocker:
            result = self._step_handle_blocker(state)
            save_supervisor_state(self.state_path, state)
            self._emit_step_metrics(state, result)
            return result

        result = self._step_campaign_iteration(state)
        save_supervisor_state(self.state_path, state)
        self._emit_step_metrics(state, result)
        return result

    @staticmethod
    def _emit_step_metrics(state: SupervisorState, result: StepResult) -> None:
        """Emit Prometheus metrics after each step."""
        try:
            from aragora.observability.metrics.ralph import (
                record_blocker_classified,
                record_budget_spent,
                record_campaign_status,
                record_campaign_step,
                record_repair_attempt,
            )

            cid = state.campaign_id or state.supervisor_id
            record_campaign_step(cid, result.action)
            record_campaign_status(cid, state.status)
            record_budget_spent(cid, state.budget_spent_usd)
            if result.action == SupervisorAction.BLOCKER_CLASSIFIED.value and state.active_blocker:
                try:
                    bk = BlockerKind(state.active_blocker)
                    record_blocker_classified(bk.value, bk.is_deterministic)
                except ValueError:
                    record_blocker_classified(state.active_blocker, False)
            if result.action == SupervisorAction.REPAIR_DISPATCHED.value:
                record_repair_attempt(state.active_blocker or "unknown")
        except Exception:
            logger.debug("Failed to emit ralph metrics", exc_info=True)

    def status(self) -> dict[str, Any]:
        """Return current supervisor state as dict."""
        state = load_supervisor_state(self.state_path)
        return state.to_dict()

    def stop(self) -> StepResult:
        """Gracefully stop the supervisor."""
        state = load_supervisor_state(self.state_path)
        state.status = SupervisorStatus.STOPPED.value
        save_supervisor_state(self.state_path, state)
        return StepResult(
            action=SupervisorAction.NOOP.value,
            status=SupervisorStatus.STOPPED.value,
            detail="Supervisor stopped by operator.",
        )

    def _merge_target(self, state: SupervisorState) -> dict[str, Any] | None:
        target = state.active_merge_target
        return dict(target) if isinstance(target, dict) and target else None

    def _set_merge_target(self, state: SupervisorState, target: dict[str, Any] | None) -> None:
        state.active_merge_target = dict(target) if isinstance(target, dict) and target else None
        compat = _compat_repair_fields_from_target(state.active_merge_target)
        state.active_repair_pr = compat["pr_url"] if isinstance(compat["pr_url"], str) else None
        state.active_repair_branch = compat["branch"] if isinstance(compat["branch"], str) else None
        state.active_repair_task = compat["task"] if isinstance(compat["task"], dict) else None

    def _clear_merge_target(self, state: SupervisorState) -> None:
        self._set_merge_target(state, None)

    def _merge_target_run_id(self, state: SupervisorState) -> str | None:
        target = self._merge_target(state)
        return _optional_text(target.get("run_id")) if target else None

    def _persist_merge_target_pr(
        self,
        state: SupervisorState,
        *,
        pr_url: str,
        branch: str | None = None,
    ) -> None:
        target = self._merge_target(state)
        if not target:
            return
        target["pr_url"] = pr_url
        if branch:
            target["branch"] = branch
        self._set_merge_target(state, target)

        if target.get("kind") == "project" and target.get("project_id"):
            from aragora.swarm.campaign import CampaignExecutor

            executor = CampaignExecutor(
                manifest_path=Path(state.campaign_manifest_path),
                repo_root=self.repo_root,
                target_branch=str(target.get("target_branch") or "main"),
            )
            executor.record_project_pr(str(target["project_id"]), pr_url=pr_url)

        # Register in canonical PR registry
        reg_branch = branch or (target.get("branch") if target else None)
        if pr_url and reg_branch:
            try:
                creator = f"ralph-{target.get('kind', 'unknown')}"
                self._get_pr_registry().register(reg_branch, pr_url, creator=creator)
            except Exception:
                logger.debug("Failed to register PR %s in registry", pr_url, exc_info=True)

    def _register_project_merge_target(
        self,
        state: SupervisorState,
        target: dict[str, Any],
    ) -> tuple[str, str]:
        merge_target = {
            "kind": "project",
            "project_id": _optional_text(target.get("project_id")),
            "run_id": _optional_text(target.get("run_id")),
            "branch": _optional_text(target.get("branch")),
            "pr_url": _optional_text(target.get("pr_url")),
            "target_branch": _optional_text(target.get("target_branch")) or "main",
            "auto_merge_requested": False,
            "last_gate_snapshot": None,
            "last_merge_action": None,
        }
        self._set_merge_target(state, merge_target)
        if merge_target["pr_url"]:
            state.status = SupervisorStatus.WAITING_FOR_MERGE.value
            return state.status, f"Project PR ready: {merge_target['pr_url']}"
        state.status = SupervisorStatus.WAITING_FOR_PR.value
        return state.status, (
            f"Project {merge_target['project_id']} awaiting PR creation for branch "
            f"{merge_target['branch']}."
        )

    def _register_repair_merge_target(
        self,
        state: SupervisorState,
        *,
        task_payload: dict[str, Any],
        branch: str | None,
        pr_url: str | None,
        run_id: str | None,
    ) -> None:
        target = {
            "kind": "repair",
            "project_id": None,
            "run_id": run_id,
            "branch": branch,
            "pr_url": pr_url,
            "target_branch": "main",
            "auto_merge_requested": False,
            "last_gate_snapshot": None,
            "last_merge_action": None,
            "repair_task": dict(task_payload),
        }
        self._set_merge_target(state, target)

    # -- step implementations --

    def _step_campaign_iteration(self, state: SupervisorState) -> StepResult:
        """Run one CampaignExecutor.execute_once() iteration."""
        from aragora.swarm.campaign import CampaignExecutor

        manifest_path = Path(state.campaign_manifest_path)
        executor = CampaignExecutor(
            manifest_path=manifest_path,
            repo_root=self.repo_root,
        )

        try:
            result = asyncio.run(executor.execute_once())
        except Exception as exc:
            logger.warning("Campaign iteration failed: %s", exc)
            state.last_campaign_result = {"error": str(exc)}
            state.active_blocker = BlockerKind.INFRA_FAILURE.value
            state.blocker_history.append(
                {
                    "step": state.current_step,
                    "kind": BlockerKind.INFRA_FAILURE.value,
                    "detail": str(exc),
                }
            )
            return StepResult(
                action=SupervisorAction.BLOCKER_CLASSIFIED.value,
                status=state.status,
                detail=f"Campaign iteration raised: {type(exc).__name__}: {exc}",
            )

        state.last_campaign_result = result
        stop_reason = str(result.get("stop_reason", ""))
        state.last_stop_reason = stop_reason
        merge_ready_projects = [
            item for item in result.get("merge_ready_projects", []) if isinstance(item, dict)
        ]

        # Update budget from manifest.
        try:
            manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            exec_state = manifest_data.get("execution_state", {})
            state.budget_spent_usd = float(exec_state.get("total_cost_usd", 0.0))
        except Exception:
            pass

        if merge_ready_projects and not self._merge_target(state):
            next_status, detail = self._register_project_merge_target(
                state, merge_ready_projects[0]
            )
            return StepResult(
                action=SupervisorAction.CAMPAIGN_ITERATION.value,
                status=next_status,
                detail=detail,
            )

        if stop_reason == "campaign_complete":
            state.status = SupervisorStatus.COMPLETED.value
            completion_outputs = {
                "status": SupervisorStatus.COMPLETED.value,
                "stop_reason": stop_reason,
                "budget_spent_usd": state.budget_spent_usd,
                "merge_ready_projects": len(merge_ready_projects),
            }
            self._emit_operational_receipt(
                state=state,
                action=SupervisorAction.CAMPAIGN_COMPLETED.value,
                verdict="pass",
                outputs=completion_outputs,
            )
            self._emit_lane_receipt(
                state=state,
                outcome="pass",
                outputs=completion_outputs,
            )
            return StepResult(
                action=SupervisorAction.CAMPAIGN_COMPLETED.value,
                status=SupervisorStatus.COMPLETED.value,
                detail="All projects completed or skipped.",
            )

        if stop_reason == "still_running":
            return StepResult(
                action=SupervisorAction.CAMPAIGN_ITERATION.value,
                status=SupervisorStatus.RUNNING.value,
                detail=f"Dispatched: {result.get('dispatched_projects', [])}",
            )

        # Campaign is blocked. Classify.
        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        blocker = classify_blocker(
            stop_reason=stop_reason,
            manifest_dict=manifest_data,
        )

        if blocker is None:
            return StepResult(
                action=SupervisorAction.CAMPAIGN_ITERATION.value,
                status=SupervisorStatus.RUNNING.value,
                detail="No blocker classified; will retry.",
            )

        state.active_blocker = blocker.value
        state.blocker_history.append(
            {"step": state.current_step, "kind": blocker.value, "stop_reason": stop_reason}
        )

        return StepResult(
            action=SupervisorAction.BLOCKER_CLASSIFIED.value,
            status=state.status,
            detail=f"Blocker classified: {blocker.value}",
        )

    def _step_handle_blocker(self, state: SupervisorState) -> StepResult:
        """Generate and dispatch a repair task for a deterministic blocker, or escalate."""
        blocker_kind_str = state.active_blocker or ""
        try:
            blocker_kind = BlockerKind(blocker_kind_str)
        except ValueError:
            return self._escalate(state, f"Unknown blocker kind: {blocker_kind_str}")

        if not blocker_kind.is_deterministic:
            return self._escalate(state, f"Non-deterministic blocker: {blocker_kind.value}")

        if state.repair_attempts >= state.max_repair_attempts:
            return self._escalate(
                state,
                f"Exceeded max repair attempts ({state.max_repair_attempts}) "
                f"for blocker: {blocker_kind.value}",
            )

        # Find affected project IDs.
        affected: list[str] = []
        try:
            manifest_path = Path(state.campaign_manifest_path)
            manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            for proj in manifest_data.get("projects", []):
                if proj.get("status") in ("blocked", "failed", "skipped", "stalled"):
                    affected.append(str(proj.get("project_id", "")))
        except Exception:
            pass

        repair = generate_repair_task(blocker_kind, affected_project_ids=affected)
        if repair is None:
            return self._escalate(state, f"No repair template for: {blocker_kind.value}")

        state.repair_attempts += 1
        task_payload = repair.to_dict()

        # Dispatch the repair lane.
        spec = self._build_repair_spec(repair)
        try:
            from aragora.swarm.boss_loop import dispatch_bounded_spec

            dispatch_result = asyncio.run(
                dispatch_bounded_spec(
                    spec,
                    repo_path=self.repo_root,
                    budget_limit_usd=self.repair_budget_usd,
                )
            )
        except Exception as exc:
            logger.warning("Repair dispatch failed: %s", exc)
            dispatch_result = {"status": "failed", "outcome": "crash"}

        # Extract deliverable info.
        run_id = str(dispatch_result.get("run_id", "")).strip() or None
        deliverable = dispatch_result.get("deliverable") or {}

        pr_url = str(deliverable.get("pr_url", "")).strip()
        branch = str(deliverable.get("branch", "")).strip()
        if run_id:
            task_payload["run_id"] = run_id
        if branch:
            task_payload["branch"] = branch
        if pr_url:
            task_payload["pr_url"] = pr_url

        self._register_repair_merge_target(
            state,
            task_payload=task_payload,
            branch=branch or None,
            pr_url=pr_url or None,
            run_id=run_id,
        )
        if pr_url:
            state.status = SupervisorStatus.WAITING_FOR_MERGE.value
        elif branch:
            state.status = SupervisorStatus.WAITING_FOR_PR.value
        elif run_id:
            state.status = SupervisorStatus.WAITING_FOR_PR.value
        # else: no trackable output — stay RUNNING for retry via max_repair_attempts

        detail = f"Repair dispatched: {repair.title} (status={dispatch_result.get('status')})"
        if pr_url:
            detail += f" PR: {pr_url}"

        return StepResult(
            action=SupervisorAction.REPAIR_DISPATCHED.value,
            status=state.status,
            detail=detail,
            repair_task=repair,
        )

    def _step_check_pr(self, state: SupervisorState) -> StepResult:
        """Check if the active merge target has a PR yet, creating one if needed."""
        target = self._merge_target(state)
        if not target:
            return self._escalate(state, "No active merge target while waiting for PR.")

        run_id = self._merge_target_run_id(state)
        if run_id and not (
            _optional_text(target.get("pr_url")) or _optional_text(target.get("branch"))
        ):
            run_dict = self._refresh_dispatch_run(run_id)
            if run_dict:
                branch, pr_url = self._update_repair_tracking_from_run(state, run_dict)
                if pr_url:
                    self._persist_merge_target_pr(state, pr_url=pr_url, branch=branch)
                    state.status = SupervisorStatus.WAITING_FOR_MERGE.value
                    return StepResult(
                        action=SupervisorAction.PR_CHECKED.value,
                        status=SupervisorStatus.WAITING_FOR_MERGE.value,
                        detail=f"PR discovered from run: {pr_url}. Waiting for merge.",
                    )
                if branch:
                    target = self._merge_target(state) or target
                    state.status = SupervisorStatus.WAITING_FOR_PR.value
                    return StepResult(
                        action=SupervisorAction.PR_CHECKED.value,
                        status=SupervisorStatus.WAITING_FOR_PR.value,
                        detail=f"Branch discovered from run: {branch}. Waiting for PR.",
                    )
                if str(run_dict.get("status", "")).strip() in {
                    "completed",
                    "needs_human",
                }:
                    return self._escalate(
                        state,
                        "Tracked run reached a terminal state without a branch or PR.",
                    )

        target = self._merge_target(state) or target
        pr_url = _optional_text(target.get("pr_url"))
        branch = _optional_text(target.get("branch"))

        if pr_url:
            state.status = SupervisorStatus.WAITING_FOR_MERGE.value
            return StepResult(
                action=SupervisorAction.PR_CHECKED.value,
                status=SupervisorStatus.WAITING_FOR_MERGE.value,
                detail=f"PR found: {pr_url}. Waiting for merge.",
            )

        if branch:
            discovered = self._find_pr_for_branch(branch)
            if discovered:
                self._persist_merge_target_pr(state, pr_url=discovered, branch=branch)
                state.status = SupervisorStatus.WAITING_FOR_MERGE.value
                return StepResult(
                    action=SupervisorAction.PR_CHECKED.value,
                    status=SupervisorStatus.WAITING_FOR_MERGE.value,
                    detail=f"PR discovered: {discovered}. Waiting for merge.",
                )
            # Ensure the branch is on the remote before creating a PR.
            # The worker's auto-push may have succeeded, but if not (e.g.
            # network issues at worker exit), push now from the repo root.
            self._ensure_branch_pushed(branch)
            try:
                created = self._create_pr_for_branch(
                    branch=branch,
                    target_branch=str(target.get("target_branch") or "main"),
                )
            except GitHubControlError as exc:
                return self._escalate(state, f"PR creation failed: {exc}")
            self._persist_merge_target_pr(state, pr_url=created, branch=branch)
            state.status = SupervisorStatus.WAITING_FOR_MERGE.value
            return StepResult(
                action=SupervisorAction.PR_CHECKED.value,
                status=SupervisorStatus.WAITING_FOR_MERGE.value,
                detail=f"PR created: {created}. Waiting for merge.",
            )

        return StepResult(
            action=SupervisorAction.PR_CHECKED.value,
            status=SupervisorStatus.WAITING_FOR_PR.value,
            detail="No PR found yet. Still waiting.",
        )

    def _step_check_merge(self, state: SupervisorState) -> StepResult:
        """Check gate truth and merge status for the active PR target."""
        target = self._merge_target(state)
        if not target:
            return self._escalate(state, "No active merge target while waiting for merge.")

        pr_url = _optional_text(target.get("pr_url"))
        if not pr_url:
            state.status = SupervisorStatus.WAITING_FOR_PR.value
            return StepResult(
                action=SupervisorAction.PR_CHECKED.value,
                status=SupervisorStatus.WAITING_FOR_PR.value,
                detail="No PR URL. Reverting to waiting_for_pr.",
            )

        try:
            snapshot = self._fetch_pr_gate_snapshot(pr_url)
        except GitHubControlError as exc:
            return self._escalate(state, f"GitHub gate lookup failed: {exc}")

        target["last_gate_snapshot"] = snapshot.to_dict()
        self._set_merge_target(state, target)

        if snapshot.disposition == "merged":
            self._record_confirmed_admin_merge(target=target, pr_url=pr_url, snapshot=snapshot)
            state.merge_commit_sha = snapshot.merge_commit_sha
            if target.get("kind") == "repair":
                state.status = SupervisorStatus.RESUMING.value
                return StepResult(
                    action=SupervisorAction.PR_CHECKED.value,
                    status=SupervisorStatus.RESUMING.value,
                    detail=f"PR merged (SHA: {snapshot.merge_commit_sha}). Ready to resume campaign.",
                )
            project_id = _optional_text(target.get("project_id"))
            if not project_id:
                return self._escalate(state, "Merged project target is missing project_id.")
            if snapshot.merge_commit_sha:
                sync_result = self._synchronize_merged_commit(snapshot.merge_commit_sha)
                if not sync_result["ok"]:
                    return StepResult(
                        action=SupervisorAction.NOOP.value,
                        status=SupervisorStatus.WAITING_FOR_MERGE.value,
                        detail=str(sync_result["detail"]),
                    )
            from aragora.swarm.campaign import CampaignExecutor

            executor = CampaignExecutor(
                manifest_path=Path(state.campaign_manifest_path),
                repo_root=self.repo_root,
                target_branch=str(target.get("target_branch") or "main"),
            )
            executor.complete_project(
                project_id,
                pr_url=pr_url,
                merge_sha=snapshot.merge_commit_sha,
            )
            self._clear_merge_target(state)
            state.merge_commit_sha = None
            state.resume_attempts = 0
            state.status = SupervisorStatus.RUNNING.value
            return StepResult(
                action=SupervisorAction.CAMPAIGN_ITERATION.value,
                status=SupervisorStatus.RUNNING.value,
                detail=f"Project {project_id} completed after merge {pr_url}.",
            )

        if snapshot.disposition == "blocked_nonreviewable":
            return self._escalate(
                state,
                snapshot.blocker_detail or f"PR {pr_url} is blocked in a non-reviewable state.",
            )

        if snapshot.disposition in {"wait_for_review", "wait_for_required_checks"}:
            # When admin merge is allowed and required checks are green,
            # bypass the review gate (can't self-approve own PRs on GitHub).
            if (
                snapshot.disposition == "wait_for_review"
                and snapshot.required_checks_green
                and self.merge_policy == "admin_merge_allowed"
            ):
                target = self._merge_target(state) or target
                if not target.get("auto_merge_requested"):
                    calibration_gate = self._get_or_record_admin_merge_calibration_gate(
                        target=target,
                        pr_url=pr_url,
                        snapshot=snapshot,
                        state=state,
                    )
                    if not calibration_gate["allowed"]:
                        return StepResult(
                            action=SupervisorAction.PR_CHECKED.value,
                            status=SupervisorStatus.WAITING_FOR_MERGE.value,
                            detail=(
                                "Admin merge blocked by calibration gate: "
                                + str(calibration_gate["reason"])
                            ),
                        )
                    merge_result = self._merge_pr(
                        pr_url,
                        required_checks_green=True,
                        allow_admin=True,
                        head_sha=snapshot.head_sha,
                    )
                    target["auto_merge_requested"] = True
                    target["last_merge_action"] = merge_result.to_dict()
                    self._set_merge_target(state, target)
                    if merge_result.merged:
                        return StepResult(
                            action=SupervisorAction.PR_CHECKED.value,
                            status=SupervisorStatus.WAITING_FOR_MERGE.value,
                            detail=f"Admin merge initiated for {pr_url}; waiting for GitHub to confirm.",
                        )
                    return self._escalate(
                        state, merge_result.detail or f"Admin merge failed for {pr_url}."
                    )
            reason = snapshot.blocker_detail
            if not reason:
                if snapshot.disposition == "wait_for_review":
                    reason = f"PR {pr_url} awaiting code review approval."
                else:
                    pending = [c.name for c in snapshot.required_checks if c.status != "COMPLETED"]
                    reason = (
                        f"PR {pr_url} waiting on required checks: {', '.join(pending)}"
                        if pending
                        else f"PR {pr_url} waiting on merge gates."
                    )
            return StepResult(
                action=SupervisorAction.PR_CHECKED.value,
                status=SupervisorStatus.WAITING_FOR_MERGE.value,
                detail=reason,
            )

        if snapshot.disposition == "merge_now":
            if self.merge_policy != "admin_merge_allowed":
                return StepResult(
                    action=SupervisorAction.PR_CHECKED.value,
                    status=SupervisorStatus.WAITING_FOR_MERGE.value,
                    detail=f"PR {pr_url} is merge-ready and awaiting manual merge.",
                )
            target = self._merge_target(state) or target
            if target.get("auto_merge_requested"):
                return StepResult(
                    action=SupervisorAction.PR_CHECKED.value,
                    status=SupervisorStatus.WAITING_FOR_MERGE.value,
                    detail=f"Merge already requested for {pr_url}; waiting for GitHub to confirm.",
                )
            calibration_gate = self._get_or_record_admin_merge_calibration_gate(
                target=target,
                pr_url=pr_url,
                snapshot=snapshot,
                state=state,
            )
            if not calibration_gate["allowed"]:
                return StepResult(
                    action=SupervisorAction.PR_CHECKED.value,
                    status=SupervisorStatus.WAITING_FOR_MERGE.value,
                    detail="Admin merge blocked by calibration gate: "
                    + str(calibration_gate["reason"]),
                )
            merge_result = self._merge_pr(
                pr_url,
                required_checks_green=snapshot.required_checks_green,
                allow_admin=True,
                head_sha=snapshot.head_sha,
            )
            target["auto_merge_requested"] = True
            target["last_merge_action"] = merge_result.to_dict()
            self._set_merge_target(state, target)
            if merge_result.merged:
                return StepResult(
                    action=SupervisorAction.PR_CHECKED.value,
                    status=SupervisorStatus.WAITING_FOR_MERGE.value,
                    detail=f"Merge initiated for {pr_url}; waiting for GitHub to confirm.",
                )
            return self._escalate(state, merge_result.detail or f"Failed to merge {pr_url}.")

        return StepResult(
            action=SupervisorAction.PR_CHECKED.value,
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            detail=f"PR {pr_url} not yet merged.",
        )

    def _step_resume(self, state: SupervisorState) -> StepResult:
        """Resume campaign after a repair PR was merged.

        Fail-closed: the worktree must be verified as synchronized with the
        merged repair before clearing blocker state and transitioning to
        RUNNING.  ``git fetch`` alone only updates refs — it does NOT update
        checked-out files, so we must also confirm the merge commit SHA is
        reachable and attempt a fast-forward merge to pull the changes in.
        """
        merge_sha = state.merge_commit_sha

        # 0. Escalate if we have been stuck in RESUMING too many times.
        state.resume_attempts += 1
        if state.resume_attempts > _MAX_RESUME_ATTEMPTS:
            return self._escalate(
                state,
                f"Failed to synchronize worktree after {_MAX_RESUME_ATTEMPTS} "
                "resume attempts; manual intervention required.",
            )

        # 1. Fetch latest origin/main.
        try:
            fetch = subprocess.run(
                ["git", "fetch", "origin", "main"],
                capture_output=True,
                cwd=str(self.repo_root),
                timeout=30,
            )
            if fetch.returncode != 0:
                logger.warning(
                    "git fetch origin main failed (rc=%d): %s",
                    fetch.returncode,
                    fetch.stderr[:200] if isinstance(fetch.stderr, (str, bytes)) else "",
                )
                return StepResult(
                    action=SupervisorAction.NOOP.value,
                    status=SupervisorStatus.RESUMING.value,
                    detail="git fetch origin main failed; staying in RESUMING.",
                )
        except Exception as exc:
            logger.warning("git fetch origin main raised: %s", exc)
            return StepResult(
                action=SupervisorAction.NOOP.value,
                status=SupervisorStatus.RESUMING.value,
                detail=f"git fetch origin main raised: {type(exc).__name__}; staying in RESUMING.",
            )

        # 2. If we have a merge SHA, verify it landed on origin/main.
        if merge_sha:
            if not self._is_ancestor(merge_sha, "origin/main"):
                logger.warning(
                    "Merge commit %s not found on origin/main after fetch; staying in RESUMING.",
                    merge_sha,
                )
                return StepResult(
                    action=SupervisorAction.NOOP.value,
                    status=SupervisorStatus.RESUMING.value,
                    detail=(
                        f"Merge commit {merge_sha} is not an ancestor of "
                        f"origin/main; staying in RESUMING."
                    ),
                )

            # 3. Try to incorporate the repair into the worktree.
            if not self._is_ancestor(merge_sha, "HEAD"):
                # Worktree doesn't include the merge yet — try ff-only merge.
                try:
                    ff = subprocess.run(
                        ["git", "merge", "--ff-only", "origin/main"],
                        capture_output=True,
                        cwd=str(self.repo_root),
                        timeout=30,
                    )
                    if ff.returncode != 0:
                        logger.warning(
                            "git merge --ff-only origin/main failed (rc=%d); staying in RESUMING.",
                            ff.returncode,
                        )
                        return StepResult(
                            action=SupervisorAction.NOOP.value,
                            status=SupervisorStatus.RESUMING.value,
                            detail=(
                                "Worktree could not fast-forward to include "
                                f"merge commit {merge_sha}; staying in RESUMING."
                            ),
                        )
                except Exception as exc:
                    logger.warning("git merge --ff-only raised: %s", exc)
                    return StepResult(
                        action=SupervisorAction.NOOP.value,
                        status=SupervisorStatus.RESUMING.value,
                        detail=(
                            f"git merge --ff-only raised: {type(exc).__name__}; "
                            "staying in RESUMING."
                        ),
                    )

                # Verify again after the merge attempt.
                if not self._is_ancestor(merge_sha, "HEAD"):
                    logger.warning(
                        "Merge commit %s still not in HEAD after ff-merge; staying in RESUMING.",
                        merge_sha,
                    )
                    return StepResult(
                        action=SupervisorAction.NOOP.value,
                        status=SupervisorStatus.RESUMING.value,
                        detail=(
                            f"Merge commit {merge_sha} not reachable from HEAD "
                            "even after ff-merge; staying in RESUMING."
                        ),
                    )

        # All checks passed — reconcile manifest then clear blocker state.
        affected_ids = self._affected_project_ids(state)
        reconciled = self._reconcile_manifest_projects(state, affected_ids)

        state.active_blocker = None
        self._clear_merge_target(state)
        state.merge_commit_sha = None
        state.repair_attempts = 0
        state.resume_attempts = 0
        state.status = SupervisorStatus.RUNNING.value

        detail = "Campaign resumed after repair merge."
        if reconciled:
            detail += f" Reset {len(reconciled)} projects to ready: {reconciled}"
        detail += " Next step will run iteration."

        return StepResult(
            action=SupervisorAction.CAMPAIGN_RESUMED.value,
            status=SupervisorStatus.RUNNING.value,
            detail=detail,
        )

    def _is_ancestor(self, commit: str, ref: str) -> bool:
        """Check if *commit* is an ancestor of *ref* using ``git merge-base --is-ancestor``."""
        try:
            result = subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit, ref],
                capture_output=True,
                cwd=str(self.repo_root),
                timeout=15,
            )
            return result.returncode == 0
        except Exception as exc:
            logger.debug("git merge-base --is-ancestor failed: %s", exc)
            return False

    def _synchronize_merged_commit(self, merge_sha: str) -> dict[str, Any]:
        """Fetch origin/main and fast-forward the worktree until *merge_sha* is present."""
        try:
            fetch = subprocess.run(
                ["git", "fetch", "origin", "main"],
                capture_output=True,
                cwd=str(self.repo_root),
                timeout=30,
            )
            if fetch.returncode != 0:
                return {"ok": False, "detail": "git fetch origin main failed."}
        except Exception as exc:
            return {"ok": False, "detail": f"git fetch origin main raised: {type(exc).__name__}."}

        if not self._is_ancestor(merge_sha, "origin/main"):
            return {
                "ok": False,
                "detail": f"Merge commit {merge_sha} is not an ancestor of origin/main yet.",
            }

        if self._is_ancestor(merge_sha, "HEAD"):
            return {"ok": True, "detail": f"Merge commit {merge_sha} already present in HEAD."}

        try:
            ff = subprocess.run(
                ["git", "merge", "--ff-only", "origin/main"],
                capture_output=True,
                cwd=str(self.repo_root),
                timeout=30,
            )
            if ff.returncode != 0:
                return {
                    "ok": False,
                    "detail": f"Worktree could not fast-forward to include {merge_sha}.",
                }
        except Exception as exc:
            return {
                "ok": False,
                "detail": f"git merge --ff-only raised: {type(exc).__name__}.",
            }

        if not self._is_ancestor(merge_sha, "HEAD"):
            return {
                "ok": False,
                "detail": f"Merge commit {merge_sha} still not reachable from HEAD.",
            }
        return {"ok": True, "detail": f"Merge commit {merge_sha} synchronized into HEAD."}

    # -- resume reconciliation --

    @staticmethod
    def _affected_project_ids(state: SupervisorState) -> list[str]:
        """Extract affected project IDs from the active repair task."""
        task = state.active_repair_task if isinstance(state.active_repair_task, dict) else {}
        if not task and isinstance(state.active_merge_target, dict):
            maybe_task = state.active_merge_target.get("repair_task")
            if isinstance(maybe_task, dict):
                task = maybe_task
        ids = task.get("affected_project_ids", [])
        return [str(pid) for pid in ids if str(pid).strip()] if isinstance(ids, list) else []

    def _reconcile_manifest_projects(
        self,
        state: SupervisorState,
        affected_ids: list[str],
    ) -> list[str]:
        """Reset affected projects in the manifest so they are retryable.

        After a repair merge, stale blocked/failed project outcomes would cause
        the classifier to re-trigger the same blocker.  This method resets those
        projects to ``ready`` with cleared review and outcome fields.

        Returns the list of project IDs that were actually reset.
        """
        if not affected_ids:
            return []

        manifest_path = Path(state.campaign_manifest_path)
        try:
            manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read manifest for reconciliation: %s", exc)
            return []

        if not isinstance(manifest_data, dict):
            return []

        affected_set = set(affected_ids)
        reconciled: list[str] = []
        for project in manifest_data.get("projects", []):
            if not isinstance(project, dict):
                continue
            pid = str(project.get("project_id", ""))
            if pid not in affected_set:
                continue
            if project.get("status") not in ("blocked", "failed"):
                continue

            project["status"] = "ready"
            project["last_run_outcome"] = None
            if isinstance(project.get("review"), dict):
                project["review"]["status"] = "pending"
                project["review"]["findings"] = []
                project["review"]["raw_review"] = {}
                project["review"]["reviewed_at"] = None
            reconciled.append(pid)

        if not reconciled:
            return []

        # Refresh execution_state lists to match new project statuses.
        _blocked_like = {"blocked", "failed"}
        exec_state = manifest_data.get("execution_state", {})
        projects = manifest_data.get("projects", [])
        exec_state["ready_queue"] = [
            p["project_id"] for p in projects if p.get("status") == "ready"
        ]
        exec_state["failed_projects"] = [
            p["project_id"] for p in projects if p.get("status") in _blocked_like
        ]

        try:
            text = yaml.dump(manifest_data, default_flow_style=False, sort_keys=False)
            tmp = manifest_path.with_suffix(".yaml.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(manifest_path)
        except Exception as exc:
            logger.warning("Could not write reconciled manifest: %s", exc)
            return []

        logger.info("Reconciled %d projects to ready: %s", len(reconciled), reconciled)
        return reconciled

    # -- helpers --

    def _build_repair_spec(self, repair: RepairTask) -> Any:
        """Convert a RepairTask to a dispatch-bounded SwarmSpec."""
        from aragora.swarm.spec import SwarmSpec

        goal = f"{repair.title}\n\n{repair.problem_statement}"
        spec = SwarmSpec.from_direct_goal(
            goal,
            budget_limit_usd=self.repair_budget_usd,
            requires_approval=False,
            user_expertise="developer",
        )
        # Override inferred hints with the repair's explicit allowed_paths.
        spec.file_scope_hints = list(repair.allowed_paths)
        # Set acceptance criteria from done_condition + required_tests.
        spec.acceptance_criteria = [repair.done_condition]
        if repair.required_tests:
            spec.acceptance_criteria.append(f"Tests pass: {', '.join(repair.required_tests)}")
        return spec

    def _auto_merge_pr(self, pr_url: str) -> bool:
        """Backward-compatible wrapper around GitHubControl.merge_pr()."""
        snapshot = self._fetch_pr_gate_snapshot(pr_url)
        result = self._merge_pr(
            pr_url,
            required_checks_green=snapshot.required_checks_green,
            allow_admin=True,
            head_sha=snapshot.head_sha,
        )
        return result.merged

    def _repair_run_id(self, state: SupervisorState) -> str | None:
        return self._merge_target_run_id(state)

    def _refresh_dispatch_run(self, run_id: str) -> dict[str, Any] | None:
        from aragora.swarm.supervisor import SwarmSupervisor

        supervisor = SwarmSupervisor(repo_root=self.repo_root)
        try:
            return supervisor.refresh_run(run_id).to_dict()
        except Exception as exc:
            logger.debug("refresh_run failed for repair run %s: %s", run_id, exc)
            return None

    def _update_repair_tracking_from_run(
        self,
        state: SupervisorState,
        run_dict: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        target = self._merge_target(state) or {}
        task = dict(state.active_repair_task or target.get("repair_task") or {})
        branch: str | None = None
        pr_url: str | None = None
        for item in run_dict.get("work_orders", []):
            if not isinstance(item, dict):
                continue
            branch = branch or str(item.get("branch", "")).strip() or None
            pr_url = pr_url or str(item.get("pull_request_url", "")).strip() or None
            meta = item.get("metadata")
            if isinstance(meta, dict):
                pr_url = pr_url or str(meta.get("pull_request_url", "")).strip() or None
        if branch:
            target["branch"] = branch
            task["branch"] = branch
        if pr_url:
            target["pr_url"] = pr_url
            task["pr_url"] = pr_url
        task["run_status"] = str(run_dict.get("status", "")).strip()
        target["repair_task"] = task
        self._set_merge_target(state, target)
        return branch, pr_url

    def _escalate(self, state: SupervisorState, reason: str) -> StepResult:
        state.status = SupervisorStatus.ESCALATED.value
        state.escalation_reason = reason
        logger.warning("Ralph supervisor escalating: %s", reason)
        self._emit_operational_receipt(
            state=state,
            action=SupervisorAction.ESCALATED.value,
            verdict="escalated",
            outputs={
                "status": SupervisorStatus.ESCALATED.value,
                "reason": reason,
                "active_blocker": state.active_blocker,
                "repair_attempts": state.repair_attempts,
            },
        )
        return StepResult(
            action=SupervisorAction.ESCALATED.value,
            status=SupervisorStatus.ESCALATED.value,
            detail=reason,
        )

    def _ensure_branch_pushed(self, branch: str) -> None:
        """Best-effort push of the branch to origin.

        If the branch is already on the remote, this is a no-op.  If not,
        it pushes from the repo root (which sees all worktree branches).
        """
        try:
            result = subprocess.run(
                ["git", "push", "origin", branch],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                logger.info("Branch %s pushed to origin", branch)
            else:
                logger.info(
                    "Push of %s returned rc=%s: %s",
                    branch,
                    result.returncode,
                    (result.stderr or "").strip()[:200],
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.warning("Failed to push branch %s: %s", branch, exc)

    def _find_pr_for_branch(self, branch: str) -> str | None:
        return self.github.find_pr_for_branch(branch)

    def _create_pr_for_branch(self, *, branch: str, target_branch: str) -> str:
        return self.github.create_pr_for_branch(branch, target_branch)

    def _fetch_pr_gate_snapshot(self, pr_url: str) -> Any:
        return self.github.fetch_gate_snapshot(pr_url)

    def _merge_pr(
        self,
        pr_url: str,
        *,
        required_checks_green: bool,
        allow_admin: bool,
        head_sha: str | None,
    ) -> Any:
        return self.github.merge_pr(
            pr_url,
            required_checks_green=required_checks_green,
            allow_admin=allow_admin,
            head_sha=head_sha,
        )

    def _evaluate_admin_merge_calibration_gate(
        self,
        *,
        target: dict[str, Any],
        pr_url: str,
        snapshot: Any,
    ) -> dict[str, Any]:
        decision_class = fingerprint_admin_merge_class(
            base_branch=getattr(snapshot, "base_branch", None),
            required_checks_count=len(getattr(snapshot, "required_checks", []) or []),
            target_kind=target.get("kind"),
        )
        gate = self._auto_handle_calibration_store.evaluate_gate(
            auto_handle_path=AUTO_HANDLE_PATH_ADMIN_MERGE_ALLOWED,
            decision_class=decision_class,
        )
        result = gate.to_dict()
        result["decision_id"] = auto_handle_decision_id(
            auto_handle_path=AUTO_HANDLE_PATH_ADMIN_MERGE_ALLOWED,
            pr_url=pr_url,
            decision_class=decision_class,
        )
        result["decision_class"] = decision_class
        return result

    def _get_or_record_admin_merge_calibration_gate(
        self,
        *,
        target: dict[str, Any],
        pr_url: str,
        snapshot: Any,
        state: SupervisorState,
    ) -> dict[str, Any]:
        existing = target.get("auto_handle_calibration")
        if isinstance(existing, dict):
            decision_id = _optional_text(existing.get("decision_id"))
            decision_class = _optional_text(existing.get("decision_class"))
            if decision_id and decision_class:
                return existing
        calibration_gate = self._evaluate_admin_merge_calibration_gate(
            target=target,
            pr_url=pr_url,
            snapshot=snapshot,
        )
        target["auto_handle_calibration"] = calibration_gate
        self._set_merge_target(state, target)
        return calibration_gate

    def _record_confirmed_admin_merge(
        self, *, target: dict[str, Any], pr_url: str, snapshot: Any
    ) -> None:
        calibration = target.get("auto_handle_calibration")
        if not isinstance(calibration, dict):
            return
        decision_id = _optional_text(calibration.get("decision_id"))
        decision_class = _optional_text(calibration.get("decision_class"))
        if not decision_id or not decision_class:
            return
        self._auto_handle_calibration_store.record_outcome(
            decision_id=decision_id,
            auto_handle_path=AUTO_HANDLE_PATH_ADMIN_MERGE_ALLOWED,
            decision_class=decision_class,
            outcome=OUTCOME_SUCCESS,
            pr_url=pr_url,
            metadata={
                "base_branch": getattr(snapshot, "base_branch", None),
                "target_kind": target.get("kind"),
            },
            repo_root=self.repo_root,
        )

    def _check_pr_merged(self, pr_url: str) -> tuple[bool, str | None]:
        """Backward-compatible merge-status helper used by existing tests."""
        snapshot = self._fetch_pr_gate_snapshot(pr_url)
        return snapshot.disposition == "merged", snapshot.merge_commit_sha
