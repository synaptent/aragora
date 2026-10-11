"""Tests for ralph campaign supervisor state machine."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from aragora.ralph.classifier import BlockerKind
from aragora.ralph.github_control import GitHubGateSnapshot
from aragora.ralph.supervisor import (
    RalphSupervisor,
    StepResult,
    SupervisorAction,
    SupervisorState,
    SupervisorStatus,
    load_supervisor_state,
    save_supervisor_state,
)
from aragora.swarm.campaign import load_campaign_manifest
from aragora.triage.auto_handle_calibration import (
    AUTO_HANDLE_PATH_ADMIN_MERGE_ALLOWED,
    AutoHandleCalibrationStore,
    OUTCOME_HUMAN_OVERRIDE,
    auto_handle_decision_id,
    fingerprint_admin_merge_class,
)

_GATE_HEAD_SHA = "a" * 40


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_manifest(path: Path, campaign_id: str = "test-campaign") -> Path:
    manifest = {
        "campaign_id": campaign_id,
        "created_at": "2026-03-10T00:00:00Z",
        "source_kind": "manual",
        "source_ref": "test",
        "worker_model": "codex",
        "review_model": "claude",
        "max_parallel_ready_projects": 1,
        "max_retries_per_project": 2,
        "budget_limit_usd": 20.0,
        "time_limit_hours": 4.0,
        "projects": [],
        "execution_state": {
            "ready_queue": [],
            "active_projects": [],
            "completed_projects": [],
            "failed_projects": [],
            "skipped_projects": [],
            "total_cost_usd": 0.0,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(manifest), encoding="utf-8")
    return path


def _write_state(path: Path, **overrides) -> SupervisorState:
    state = SupervisorState(
        supervisor_id="ralph-test123",
        campaign_manifest_path=str(overrides.pop("campaign_manifest_path", "/tmp/manifest.yaml")),
        campaign_id="test-campaign",
        **overrides,
    )
    save_supervisor_state(path, state)
    return state


def _gate_snapshot(
    *,
    pr_url: str = "https://github.com/org/repo/pull/1",
    disposition: str,
    state: str = "OPEN",
    merge_commit_sha: str | None = None,
    blocker_detail: str | None = None,
    required_checks_green: bool = True,
    required_checks_known: bool = True,
    head_sha: str | None = _GATE_HEAD_SHA,
) -> GitHubGateSnapshot:
    return GitHubGateSnapshot(
        pr_url=pr_url,
        state=state,
        draft=False,
        head_branch="codex/test",
        base_branch="main",
        review_decision="APPROVED",
        merge_state_status="CLEAN",
        merge_commit_sha=merge_commit_sha,
        required_checks=[],
        advisory_checks=[],
        required_checks_green=required_checks_green,
        required_checks_known=required_checks_known,
        required_checks_source="ruleset" if required_checks_known else None,
        disposition=disposition,
        blocker_detail=blocker_detail,
        head_sha=head_sha,
    )


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


class TestSupervisorStatePersistence:
    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        state_path = tmp_path / ".aragora" / "supervisor_state.yaml"
        state = SupervisorState(
            supervisor_id="ralph-abc",
            campaign_manifest_path="/foo/manifest.yaml",
            campaign_id="camp-1",
            status=SupervisorStatus.RUNNING.value,
            current_step=3,
            repair_attempts=1,
            budget_spent_usd=5.5,
        )
        save_supervisor_state(state_path, state)
        loaded = load_supervisor_state(state_path)

        assert loaded.supervisor_id == "ralph-abc"
        assert loaded.campaign_id == "camp-1"
        assert loaded.current_step == 3
        assert loaded.repair_attempts == 1
        assert loaded.budget_spent_usd == 5.5
        assert loaded.updated_at  # should be set by save

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_supervisor_state(tmp_path / "nonexistent.yaml")

    def test_to_dict_from_dict_round_trip(self) -> None:
        state = SupervisorState(
            supervisor_id="ralph-xyz",
            campaign_manifest_path="/p",
            campaign_id="c1",
            active_blocker="unknown",
            blocker_history=[{"step": 1, "kind": "unknown"}],
        )
        d = state.to_dict()
        restored = SupervisorState.from_dict(d)
        assert restored.supervisor_id == state.supervisor_id
        assert restored.active_blocker == "unknown"
        assert len(restored.blocker_history) == 1


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


class TestSupervisorStart:
    def test_start_creates_state_file(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / ".aragora" / "supervisor_state.yaml"

        supervisor = RalphSupervisor.start(
            manifest_path=manifest_path,
            state_path=state_path,
            repo_root=tmp_path,
        )
        assert state_path.exists()
        state = load_supervisor_state(state_path)
        assert state.campaign_id == "test-campaign"
        assert state.status == SupervisorStatus.RUNNING.value
        assert state.supervisor_id.startswith("ralph-")

    def test_start_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            RalphSupervisor.start(
                manifest_path=tmp_path / "nonexistent.yaml",
                state_path=tmp_path / "state.yaml",
            )


# ---------------------------------------------------------------------------
# Step: terminal states
# ---------------------------------------------------------------------------


class TestStepTerminalStates:
    def test_completed_state_returns_noop(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(state_path, status=SupervisorStatus.COMPLETED.value)

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
        result = supervisor.step()

        assert result.action == SupervisorAction.NOOP.value
        assert result.status == SupervisorStatus.COMPLETED.value

    def test_escalated_state_returns_noop(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(state_path, status=SupervisorStatus.ESCALATED.value)

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
        result = supervisor.step()

        assert result.action == SupervisorAction.NOOP.value

    def test_stopped_state_returns_noop(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(state_path, status=SupervisorStatus.STOPPED.value)

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
        result = supervisor.step()

        assert result.action == SupervisorAction.NOOP.value


# ---------------------------------------------------------------------------
# Step: campaign iteration
# ---------------------------------------------------------------------------


class TestStepCampaignIteration:
    def test_still_running_continues(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
        )

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={"stop_reason": "still_running", "dispatched_projects": ["p1"]},
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.action == SupervisorAction.CAMPAIGN_ITERATION.value
        assert result.status == SupervisorStatus.RUNNING.value
        assert "p1" in result.detail

    def test_campaign_complete_transitions(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
        )

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={"stop_reason": "campaign_complete", "dispatched_projects": []},
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.action == SupervisorAction.CAMPAIGN_COMPLETED.value
        assert result.status == SupervisorStatus.COMPLETED.value
        state = load_supervisor_state(state_path)
        assert state.status == SupervisorStatus.COMPLETED.value

    def test_blocked_classifies_blocker(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.yaml"
        manifest_data = {
            "campaign_id": "test",
            "created_at": "2026-01-01",
            "source_kind": "manual",
            "source_ref": "test",
            "worker_model": "codex",
            "review_model": "claude",
            "max_parallel_ready_projects": 1,
            "max_retries_per_project": 2,
            "budget_limit_usd": 20.0,
            "time_limit_hours": 4.0,
            "projects": [
                {
                    "project_id": "p1",
                    "status": "blocked",
                    "last_run_outcome": "deliverable_created",
                    "review": {"status": "changes_requested", "findings": ["bad"]},
                }
            ],
            "execution_state": {
                "ready_queue": [],
                "active_projects": [],
                "completed_projects": [],
                "failed_projects": [],
                "skipped_projects": [],
                "total_cost_usd": 3.0,
            },
        }
        manifest_path.write_text(yaml.dump(manifest_data), encoding="utf-8")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
        )

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={"stop_reason": "campaign_blocked", "dispatched_projects": []},
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.action == SupervisorAction.BLOCKER_CLASSIFIED.value
        state = load_supervisor_state(state_path)
        assert state.active_blocker == BlockerKind.REVIEWER_MISSING_DIFF.value
        assert len(state.blocker_history) == 1

    def test_campaign_iteration_exception_classifies_as_infra(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
        )

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            side_effect=RuntimeError("connection failed"),
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.action == SupervisorAction.BLOCKER_CLASSIFIED.value
        state = load_supervisor_state(state_path)
        assert state.active_blocker == BlockerKind.INFRA_FAILURE.value


# ---------------------------------------------------------------------------
# Step: handle blocker
# ---------------------------------------------------------------------------


class TestStepHandleBlocker:
    def test_deterministic_blocker_generates_repair(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
            active_blocker=BlockerKind.REVIEWER_MISSING_DIFF.value,
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)

        # Mock dispatch to return a branch (no PR).
        mock_dispatch = {
            "status": "completed",
            "outcome": "deliverable_created",
            "run_id": "run-test",
            "deliverable": {"type": "branch", "branch": "fix/test", "commit_shas": ["sha1"]},
        }
        with patch("aragora.ralph.supervisor.asyncio.run", return_value=mock_dispatch):
            result = supervisor.step()

        assert result.action == SupervisorAction.REPAIR_DISPATCHED.value
        assert result.status == SupervisorStatus.WAITING_FOR_PR.value
        assert result.repair_task is not None
        assert (
            "reviewer" in result.repair_task.title.lower()
            or "diff" in result.repair_task.title.lower()
        )

        state = load_supervisor_state(state_path)
        assert state.status == SupervisorStatus.WAITING_FOR_PR.value
        assert state.repair_attempts == 1

    def test_non_deterministic_blocker_escalates(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
            active_blocker=BlockerKind.BUDGET_EXHAUSTION.value,
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
        result = supervisor.step()

        assert result.action == SupervisorAction.ESCALATED.value
        assert result.status == SupervisorStatus.ESCALATED.value

    def test_max_repair_attempts_escalates(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
            active_blocker=BlockerKind.REVIEWER_MISSING_DIFF.value,
            repair_attempts=2,
            max_repair_attempts=2,
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
        result = supervisor.step()

        assert result.action == SupervisorAction.ESCALATED.value


# ---------------------------------------------------------------------------
# Step: PR and merge checking
# ---------------------------------------------------------------------------


class TestStepPRChecking:
    def test_waiting_for_pr_with_pr_set(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.WAITING_FOR_PR.value,
            active_repair_pr="https://github.com/org/repo/pull/1",
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
        result = supervisor.step()

        assert result.action == SupervisorAction.PR_CHECKED.value
        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value

    def test_waiting_for_pr_discovers_pr(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.WAITING_FOR_PR.value,
            active_repair_branch="fix/reviewer-diff",
        )

        with patch.object(
            RalphSupervisor,
            "_find_pr_for_branch",
            return_value="https://github.com/org/repo/pull/42",
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value
        state = load_supervisor_state(state_path)
        assert state.active_repair_pr == "https://github.com/org/repo/pull/42"

    def test_waiting_for_pr_no_pr_found(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.WAITING_FOR_PR.value,
            active_repair_branch="fix/reviewer-diff",
        )

        with (
            patch.object(RalphSupervisor, "_find_pr_for_branch", return_value=None),
            patch.object(
                RalphSupervisor,
                "_create_pr_for_branch",
                return_value="https://github.com/org/repo/pull/42",
            ),
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value

    def test_waiting_for_pr_refreshes_run_tracking(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.WAITING_FOR_PR.value,
            active_repair_task={"title": "fix", "run_id": "run-123"},
        )

        run_dict = {
            "status": "active",
            "work_orders": [
                {
                    "branch": "fix/reviewer-diff",
                    "metadata": {"pull_request_url": "https://github.com/org/repo/pull/77"},
                }
            ],
        }

        with patch.object(RalphSupervisor, "_refresh_dispatch_run", return_value=run_dict):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value
        state = load_supervisor_state(state_path)
        assert state.active_repair_branch == "fix/reviewer-diff"
        assert state.active_repair_pr == "https://github.com/org/repo/pull/77"
        assert state.active_repair_task is not None
        assert state.active_repair_task["run_status"] == "active"

    def test_waiting_for_pr_escalates_when_run_finishes_without_tracking(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.WAITING_FOR_PR.value,
            active_repair_task={"title": "fix", "run_id": "run-123"},
        )

        run_dict = {
            "status": "needs_human",
            "work_orders": [{"status": "blocked"}],
        }

        with patch.object(RalphSupervisor, "_refresh_dispatch_run", return_value=run_dict):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.action == SupervisorAction.ESCALATED.value
        assert result.status == SupervisorStatus.ESCALATED.value

    def test_waiting_for_merge_not_merged(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            active_repair_pr="https://github.com/org/repo/pull/1",
        )

        with patch.object(
            RalphSupervisor,
            "_fetch_pr_gate_snapshot",
            return_value=_gate_snapshot(
                pr_url="https://github.com/org/repo/pull/1",
                disposition="wait_for_required_checks",
                blocker_detail="checks pending",
                required_checks_green=False,
            ),
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value

    def test_waiting_for_merge_merged_transitions_to_resuming(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            active_repair_pr="https://github.com/org/repo/pull/1",
        )

        with patch.object(
            RalphSupervisor,
            "_fetch_pr_gate_snapshot",
            return_value=_gate_snapshot(
                pr_url="https://github.com/org/repo/pull/1",
                disposition="merged",
                state="MERGED",
                merge_commit_sha="abc123",
            ),
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.status == SupervisorStatus.RESUMING.value
        state = load_supervisor_state(state_path)
        assert state.merge_commit_sha == "abc123"


class TestProjectMergeTargets:
    def test_campaign_iteration_registers_project_merge_target(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
        )

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={
                "stop_reason": "still_running",
                "dispatched_projects": [],
                "merge_ready_projects": [
                    {
                        "project_id": "proj-001",
                        "kind": "project",
                        "status": "waiting_for_pr",
                        "pr_url": None,
                        "branch": "codex/proj-001",
                        "run_id": "run-001",
                        "target_branch": "main",
                    }
                ],
            },
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_PR.value
        state = load_supervisor_state(state_path)
        assert state.active_merge_target is not None
        assert state.active_merge_target["kind"] == "project"
        assert state.active_merge_target["project_id"] == "proj-001"

    def test_waiting_for_pr_creates_project_pr_and_updates_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.yaml"
        manifest_data = {
            "campaign_id": "project-pr-create",
            "created_at": "2026-01-01",
            "source_kind": "manual",
            "source_ref": "test",
            "worker_model": "codex",
            "review_model": "claude",
            "max_parallel_ready_projects": 1,
            "max_retries_per_project": 2,
            "budget_limit_usd": 20.0,
            "time_limit_hours": 4.0,
            "projects": [
                {
                    "project_id": "proj-001",
                    "title": "Branch ready",
                    "status": "waiting_for_pr",
                    "branch": "codex/proj-001",
                    "run_id": "run-001",
                    "spec": {
                        "raw_goal": "x",
                        "refined_goal": "x",
                        "acceptance_criteria": ["pass"],
                        "constraints": ["stay in scope"],
                        "file_scope_hints": ["README.md"],
                    },
                    "review": {"status": "passed", "findings": []},
                }
            ],
            "execution_state": {
                "ready_queue": [],
                "active_projects": ["proj-001"],
                "completed_projects": [],
                "failed_projects": [],
                "skipped_projects": [],
                "total_cost_usd": 0.0,
            },
        }
        manifest_path.write_text(yaml.dump(manifest_data), encoding="utf-8")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.WAITING_FOR_PR.value,
            active_merge_target={
                "kind": "project",
                "project_id": "proj-001",
                "run_id": "run-001",
                "branch": "codex/proj-001",
                "pr_url": None,
                "target_branch": "main",
                "auto_merge_requested": False,
                "last_gate_snapshot": None,
                "last_merge_action": None,
            },
        )

        with (
            patch.object(RalphSupervisor, "_find_pr_for_branch", return_value=None),
            patch.object(
                RalphSupervisor,
                "_create_pr_for_branch",
                return_value="https://github.com/org/repo/pull/201",
            ),
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value
        manifest = load_campaign_manifest(manifest_path)
        project = manifest.project_map()["proj-001"]
        assert project.status == "waiting_for_merge"
        assert project.pr_url == "https://github.com/org/repo/pull/201"

    def test_waiting_for_merge_waits_on_review_without_merging(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            active_merge_target={
                "kind": "project",
                "project_id": "proj-001",
                "pr_url": "https://github.com/org/repo/pull/301",
                "branch": "codex/proj-001",
                "target_branch": "main",
                "auto_merge_requested": False,
                "last_gate_snapshot": None,
                "last_merge_action": None,
            },
        )

        supervisor = RalphSupervisor(
            state_path=state_path,
            repo_root=tmp_path,
            merge_policy="admin_merge_allowed",
        )
        with (
            patch.object(
                supervisor,
                "_fetch_pr_gate_snapshot",
                return_value=_gate_snapshot(
                    pr_url="https://github.com/org/repo/pull/301",
                    disposition="wait_for_review",
                    blocker_detail="review required",
                    required_checks_green=False,
                ),
            ),
            patch.object(supervisor, "_merge_pr") as mock_merge,
        ):
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value
        mock_merge.assert_not_called()

    def test_merged_project_pr_completes_project_and_clears_target(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.yaml"
        manifest_data = {
            "campaign_id": "project-pr-merged",
            "created_at": "2026-01-01",
            "source_kind": "manual",
            "source_ref": "test",
            "worker_model": "codex",
            "review_model": "claude",
            "max_parallel_ready_projects": 1,
            "max_retries_per_project": 2,
            "budget_limit_usd": 20.0,
            "time_limit_hours": 4.0,
            "projects": [
                {
                    "project_id": "proj-001",
                    "title": "PR ready",
                    "status": "waiting_for_merge",
                    "pr_url": "https://github.com/org/repo/pull/401",
                    "run_id": "run-401",
                    "last_run_outcome": "deliverable_created",
                    "spec": {
                        "raw_goal": "x",
                        "refined_goal": "x",
                        "acceptance_criteria": ["pass"],
                        "constraints": ["stay in scope"],
                        "file_scope_hints": ["README.md"],
                    },
                    "review": {"status": "passed", "findings": []},
                }
            ],
            "execution_state": {
                "ready_queue": [],
                "active_projects": ["proj-001"],
                "completed_projects": [],
                "failed_projects": [],
                "skipped_projects": [],
                "total_cost_usd": 0.0,
            },
        }
        manifest_path.write_text(yaml.dump(manifest_data), encoding="utf-8")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            active_merge_target={
                "kind": "project",
                "project_id": "proj-001",
                "run_id": "run-401",
                "pr_url": "https://github.com/org/repo/pull/401",
                "branch": "codex/proj-001",
                "target_branch": "main",
                "auto_merge_requested": False,
                "last_gate_snapshot": None,
                "last_merge_action": None,
            },
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
        with (
            patch.object(
                supervisor,
                "_fetch_pr_gate_snapshot",
                return_value=_gate_snapshot(
                    pr_url="https://github.com/org/repo/pull/401",
                    disposition="merged",
                    state="MERGED",
                    merge_commit_sha="merge-sha-401",
                ),
            ),
            patch.object(
                supervisor,
                "_synchronize_merged_commit",
                return_value={"ok": True, "detail": "synced"},
            ),
            patch(
                "aragora.swarm.campaign.CampaignExecutor._refresh_run_dict",
                return_value={"work_orders": []},
            ),
        ):
            result = supervisor.step()

        assert result.status == SupervisorStatus.RUNNING.value
        state = load_supervisor_state(state_path)
        assert state.active_merge_target is None
        manifest = load_campaign_manifest(manifest_path)
        project = manifest.project_map()["proj-001"]
        assert project.status == "completed"
        assert project.receipt_id is not None


# ---------------------------------------------------------------------------
# Step: resume
# ---------------------------------------------------------------------------


def _mock_subprocess_for_resume(
    *,
    fetch_rc: int = 0,
    ancestor_origin_rc: int = 0,
    ancestor_head_rc: int = 0,
    ff_merge_rc: int = 0,
    ancestor_post_ff_rc: int = 0,
    fetch_raises: Exception | None = None,
    ff_merge_raises: Exception | None = None,
):
    """Build a side_effect function for subprocess.run that simulates the
    multi-step resume sync: fetch, merge-base checks, and ff-merge.

    Call order expected by _step_resume():
      1. git fetch origin main
      2. git merge-base --is-ancestor <sha> origin/main
      3. git merge-base --is-ancestor <sha> HEAD
      4. (if HEAD check fails) git merge --ff-only origin/main
      5. (if ff succeeds) git merge-base --is-ancestor <sha> HEAD  (post-ff)
    """
    call_index = 0

    def side_effect(cmd, **kwargs):
        nonlocal call_index
        call_index += 1

        if cmd[:3] == ["git", "fetch", "origin"]:
            if fetch_raises:
                raise fetch_raises
            return MagicMock(returncode=fetch_rc, stderr=b"")

        if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
            ref = cmd[-1] if len(cmd) > 4 else ""
            if ref == "origin/main":
                return MagicMock(returncode=ancestor_origin_rc)
            # HEAD check — distinguish first vs post-ff-merge
            if ref == "HEAD":
                # If ancestor_head_rc != 0 (worktree doesn't have it yet),
                # the first HEAD check fails; after ff-merge the post-ff check
                # uses ancestor_post_ff_rc.
                if ancestor_head_rc != 0 and call_index > 4:
                    return MagicMock(returncode=ancestor_post_ff_rc)
                return MagicMock(returncode=ancestor_head_rc)
            return MagicMock(returncode=ancestor_head_rc)

        if cmd[:3] == ["git", "merge", "--ff-only"]:
            if ff_merge_raises:
                raise ff_merge_raises
            return MagicMock(returncode=ff_merge_rc)

        return MagicMock(returncode=0)

    return side_effect


class TestStepResume:
    def test_resume_resets_repair_attempts(self, tmp_path: Path) -> None:
        """After successful repair->merge->resume, repair_attempts resets to 0."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            active_blocker=BlockerKind.REVIEWER_MISSING_DIFF.value,
            active_repair_pr="https://github.com/org/repo/pull/1",
            merge_commit_sha="abc123",
            repair_attempts=2,
            max_repair_attempts=2,
        )

        # SHA already on origin/main AND already in HEAD -> direct resume.
        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=0,
            ),
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        state = load_supervisor_state(state_path)
        assert state.repair_attempts == 0

    def test_resume_clears_blocker_and_sets_running(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            active_blocker=BlockerKind.REVIEWER_MISSING_DIFF.value,
            active_repair_pr="https://github.com/org/repo/pull/1",
            active_repair_branch="fix/branch",
            active_repair_task={"title": "fix"},
            merge_commit_sha="abc",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=0,
            ),
        ):
            supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = supervisor.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        assert result.status == SupervisorStatus.RUNNING.value

        state = load_supervisor_state(state_path)
        assert state.active_blocker is None
        assert state.active_repair_pr is None
        assert state.active_repair_branch is None
        assert state.active_repair_task is None
        assert state.merge_commit_sha is None
        assert state.status == SupervisorStatus.RUNNING.value


# ---------------------------------------------------------------------------
# Resume sync verification (fail-closed)
# ---------------------------------------------------------------------------


class TestResumeSyncVerification:
    """Verify that _step_resume() fails closed: the campaign worktree must be
    synchronized to the merged repair before transitioning to RUNNING."""

    def test_sync_success_sha_already_in_head(self, tmp_path: Path) -> None:
        """Happy path: merge SHA on origin/main AND already in HEAD -> RUNNING."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
            active_repair_pr="https://github.com/org/repo/pull/1",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=0,
            ),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        assert result.status == SupervisorStatus.RUNNING.value
        state = load_supervisor_state(state_path)
        assert state.status == SupervisorStatus.RUNNING.value
        assert state.active_blocker is None
        assert state.merge_commit_sha is None

    def test_sync_success_ff_merge_needed(self, tmp_path: Path) -> None:
        """SHA on origin/main but not in HEAD; ff-merge succeeds -> RUNNING."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=1,  # not in HEAD yet
                ff_merge_rc=0,  # ff succeeds
                ancestor_post_ff_rc=0,  # now reachable
            ),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        assert result.status == SupervisorStatus.RUNNING.value

    def test_sync_failure_fetch_fails(self, tmp_path: Path) -> None:
        """git fetch fails -> stay RESUMING, do NOT clear state."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
            active_repair_pr="https://github.com/org/repo/pull/1",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(fetch_rc=128),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.action == SupervisorAction.NOOP.value
        assert result.status == SupervisorStatus.RESUMING.value
        state = load_supervisor_state(state_path)
        assert state.status == SupervisorStatus.RESUMING.value
        assert state.active_blocker == "reviewer_missing_diff"
        assert state.merge_commit_sha == "deadbeef"

    def test_sync_failure_fetch_raises(self, tmp_path: Path) -> None:
        """git fetch raises exception -> stay RESUMING."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                fetch_raises=OSError("network down"),
            ),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.status == SupervisorStatus.RESUMING.value
        state = load_supervisor_state(state_path)
        assert state.merge_commit_sha == "deadbeef"

    def test_sync_failure_sha_not_on_origin_main(self, tmp_path: Path) -> None:
        """Merge SHA not ancestor of origin/main -> stay RESUMING."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=1,  # not on origin/main
            ),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.status == SupervisorStatus.RESUMING.value
        assert "not an ancestor" in result.detail
        state = load_supervisor_state(state_path)
        assert state.active_blocker == "reviewer_missing_diff"

    def test_sync_failure_ff_merge_fails(self, tmp_path: Path) -> None:
        """SHA on origin/main, not in HEAD, ff-merge fails -> stay RESUMING."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=1,  # not in HEAD
                ff_merge_rc=128,  # ff-merge fails (diverged)
            ),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.status == SupervisorStatus.RESUMING.value
        assert "could not fast-forward" in result.detail.lower()
        state = load_supervisor_state(state_path)
        assert state.merge_commit_sha == "deadbeef"

    def test_sync_failure_ff_merge_raises(self, tmp_path: Path) -> None:
        """ff-merge raises exception -> stay RESUMING."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=1,
                ff_merge_raises=subprocess.TimeoutExpired(cmd="git", timeout=30),
            ),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.status == SupervisorStatus.RESUMING.value

    def test_sync_failure_post_ff_head_check_fails(self, tmp_path: Path) -> None:
        """ff-merge returns 0 but merge-base still shows SHA not in HEAD -> stay RESUMING."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=1,  # not in HEAD initially
                ff_merge_rc=0,  # ff reports success
                ancestor_post_ff_rc=1,  # but still not reachable!
            ),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.status == SupervisorStatus.RESUMING.value
        assert "not reachable from HEAD" in result.detail

    def test_no_premature_running_when_blocker_state_present(self, tmp_path: Path) -> None:
        """Even with a successful fetch, if sync verification fails the
        blocker state must NOT be cleared and status must NOT be RUNNING."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
            active_repair_pr="https://github.com/org/repo/pull/1",
            active_repair_branch="fix/branch",
            active_repair_task={"title": "fix something"},
            repair_attempts=1,
        )

        # Fetch succeeds but SHA not on origin/main.
        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(ancestor_origin_rc=1),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.status == SupervisorStatus.RESUMING.value
        state = load_supervisor_state(state_path)
        # All repair state must be preserved.
        assert state.status == SupervisorStatus.RESUMING.value
        assert state.active_blocker == "reviewer_missing_diff"
        assert state.active_repair_pr == "https://github.com/org/repo/pull/1"
        assert state.active_repair_branch == "fix/branch"
        assert state.active_repair_task == {"title": "fix something"}
        assert state.merge_commit_sha == "deadbeef"
        assert state.repair_attempts == 1

    def test_resume_without_merge_sha_proceeds(self, tmp_path: Path) -> None:
        """Backward compat: if merge_commit_sha is None (legacy state),
        fetch-only is sufficient and resume proceeds to RUNNING."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            active_blocker="reviewer_missing_diff",
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        assert result.status == SupervisorStatus.RUNNING.value

    def test_resume_escalates_after_max_attempts(self, tmp_path: Path) -> None:
        """Stuck RESUMING escalates after _MAX_RESUME_ATTEMPTS failed syncs."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
            active_repair_pr="https://github.com/org/repo/pull/1",
            resume_attempts=5,  # already at the limit
        )

        # Fetch will fail — but escalation fires first due to resume_attempts > 5
        sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
        result = sup.step()

        assert result.action == SupervisorAction.ESCALATED.value
        assert result.status == SupervisorStatus.ESCALATED.value
        assert "resume attempts" in result.detail.lower()
        state = load_supervisor_state(state_path)
        assert state.status == SupervisorStatus.ESCALATED.value

    def test_resume_attempts_increments_on_each_failure(self, tmp_path: Path) -> None:
        """Each failed resume sync increments resume_attempts toward the limit."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
            active_repair_pr="https://github.com/org/repo/pull/1",
            resume_attempts=0,
        )

        sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)

        # Fetch fails on every attempt
        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(fetch_rc=1),
        ):
            result = sup.step()

        assert result.status == SupervisorStatus.RESUMING.value
        state = load_supervisor_state(state_path)
        assert state.resume_attempts == 1  # incremented from 0

    def test_resume_attempts_resets_on_success(self, tmp_path: Path) -> None:
        """Successful resume resets resume_attempts to 0."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="deadbeef",
            active_blocker="reviewer_missing_diff",
            active_repair_pr="https://github.com/org/repo/pull/1",
            resume_attempts=3,
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        state = load_supervisor_state(state_path)
        assert state.resume_attempts == 0


# ---------------------------------------------------------------------------
# Resume reconciliation (manifest project reset)
# ---------------------------------------------------------------------------


def _write_blocked_manifest_with_projects(path: Path, project_ids: list[str]) -> Path:
    """Write a manifest with blocked projects for reconciliation tests."""
    projects = [
        {
            "project_id": pid,
            "title": f"Project {pid}",
            "status": "blocked",
            "last_run_outcome": "deliverable_created",
            "review": {
                "required": True,
                "review_model": "claude",
                "status": "blocked_nonreviewable",
                "findings": ["Review failed: CLI error"],
                "reviewed_at": "2026-03-11T01:00:00Z",
                "raw_review": {"error": "some error"},
            },
            "retry_count": 1,
        }
        for pid in project_ids
    ]
    manifest = {
        "campaign_id": "test-reconcile",
        "created_at": "2026-03-10T00:00:00Z",
        "source_kind": "manual",
        "source_ref": "test",
        "worker_model": "codex",
        "review_model": "claude",
        "max_parallel_ready_projects": 1,
        "max_retries_per_project": 2,
        "budget_limit_usd": 20.0,
        "time_limit_hours": 4.0,
        "projects": projects,
        "execution_state": {
            "ready_queue": [],
            "active_projects": [],
            "completed_projects": [],
            "failed_projects": list(project_ids),
            "skipped_projects": [],
            "total_cost_usd": 5.0,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(manifest), encoding="utf-8")
    return path


class TestResumeReconciliation:
    """Verify that resume resets affected projects in the manifest."""

    def test_resume_resets_affected_projects_to_ready(self, tmp_path: Path) -> None:
        """After repair merge, affected blocked projects become ready."""
        manifest_path = _write_blocked_manifest_with_projects(
            tmp_path / "manifest.yaml", ["p1", "p2"]
        )
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="abc123",
            active_blocker="reviewer_missing_diff_context",
            active_repair_pr="https://github.com/org/repo/pull/1",
            active_repair_task={
                "title": "fix reviewer",
                "affected_project_ids": ["p1", "p2"],
            },
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(ancestor_origin_rc=0, ancestor_head_rc=0),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        assert result.status == SupervisorStatus.RUNNING.value
        assert "Reset 2 projects" in result.detail

        # Verify manifest was updated.
        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        for proj in manifest_data["projects"]:
            assert proj["status"] == "ready"
            assert proj["last_run_outcome"] is None
            assert proj["review"]["status"] == "pending"
            assert proj["review"]["findings"] == []

        # Verify execution_state was refreshed.
        exec_state = manifest_data["execution_state"]
        assert set(exec_state["ready_queue"]) == {"p1", "p2"}
        assert exec_state["failed_projects"] == []

    def test_resume_does_not_reclassify_same_blocker(self, tmp_path: Path) -> None:
        """After resume+reconciliation, next iteration must NOT re-classify
        the same blocker from stale manifest state."""
        manifest_path = _write_blocked_manifest_with_projects(tmp_path / "manifest.yaml", ["p1"])
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="abc123",
            active_blocker="reviewer_missing_diff_context",
            active_repair_pr="https://github.com/org/repo/pull/1",
            active_repair_task={
                "title": "fix reviewer",
                "affected_project_ids": ["p1"],
            },
        )

        # Step 1: resume (reconciles manifest).
        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(ancestor_origin_rc=0, ancestor_head_rc=0),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            r1 = sup.step()
        assert r1.action == SupervisorAction.CAMPAIGN_RESUMED.value

        # Step 2: next campaign iteration — should NOT re-classify same blocker.
        # Mock execute_once to return still_running (projects are dispatchable now).
        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={"stop_reason": "still_running", "dispatched_projects": ["p1"]},
        ):
            r2 = sup.step()

        assert r2.action == SupervisorAction.CAMPAIGN_ITERATION.value
        assert r2.status == SupervisorStatus.RUNNING.value
        # The blocker must NOT have been re-set.
        state = load_supervisor_state(state_path)
        assert state.active_blocker is None

    def test_resume_preserves_non_affected_projects(self, tmp_path: Path) -> None:
        """Projects NOT in affected_project_ids remain unchanged."""
        manifest_path = _write_blocked_manifest_with_projects(
            tmp_path / "manifest.yaml", ["p1", "p2", "p3"]
        )
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="abc123",
            active_blocker="reviewer_missing_diff_context",
            active_repair_task={
                "title": "fix",
                "affected_project_ids": ["p1", "p3"],
            },
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(ancestor_origin_rc=0, ancestor_head_rc=0),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value

        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        by_id = {p["project_id"]: p for p in manifest_data["projects"]}

        # p1 and p3 reset.
        assert by_id["p1"]["status"] == "ready"
        assert by_id["p3"]["status"] == "ready"
        # p2 still blocked.
        assert by_id["p2"]["status"] == "blocked"
        assert by_id["p2"]["last_run_outcome"] == "deliverable_created"

    def test_resume_without_affected_ids_still_works(self, tmp_path: Path) -> None:
        """Resume with no affected_project_ids (legacy state) clears blocker state
        without modifying the manifest."""
        manifest_path = _write_blocked_manifest_with_projects(tmp_path / "manifest.yaml", ["p1"])
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="abc123",
            active_blocker="reviewer_missing_diff_context",
            active_repair_task={"title": "fix"},  # no affected_project_ids
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(ancestor_origin_rc=0, ancestor_head_rc=0),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        # Manifest unchanged — p1 still blocked (no affected_ids to reset).
        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert manifest_data["projects"][0]["status"] == "blocked"

    def test_resume_skips_already_completed_projects(self, tmp_path: Path) -> None:
        """If a project was already completed, don't regress it to ready."""
        manifest_path = _write_blocked_manifest_with_projects(
            tmp_path / "manifest.yaml", ["p1", "p2"]
        )
        # Manually set p2 to completed.
        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest_data["projects"][1]["status"] = "completed"
        manifest_path.write_text(yaml.dump(manifest_data), encoding="utf-8")

        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="abc123",
            active_blocker="reviewer_missing_diff_context",
            active_repair_task={
                "title": "fix",
                "affected_project_ids": ["p1", "p2"],
            },
        )

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(ancestor_origin_rc=0, ancestor_head_rc=0),
        ):
            sup = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
            result = sup.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        assert "Reset 1 projects" in result.detail

        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        by_id = {p["project_id"]: p for p in manifest_data["projects"]}
        assert by_id["p1"]["status"] == "ready"
        assert by_id["p2"]["status"] == "completed"  # preserved


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


class TestStop:
    def test_stop_sets_stopped(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.yaml"
        _write_state(state_path, status=SupervisorStatus.RUNNING.value)

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)
        result = supervisor.stop()

        assert result.status == SupervisorStatus.STOPPED.value
        state = load_supervisor_state(state_path)
        assert state.status == SupervisorStatus.STOPPED.value


# ---------------------------------------------------------------------------
# Full loop simulation
# ---------------------------------------------------------------------------


class TestFullLoopSimulation:
    def test_run_classify_repair_merge_resume_complete(self, tmp_path: Path) -> None:
        """Simulate: run -> blocked -> classify -> repair -> PR -> merge -> resume -> complete."""
        manifest_path = tmp_path / "manifest.yaml"
        manifest_data = {
            "campaign_id": "sim-campaign",
            "created_at": "2026-01-01",
            "source_kind": "manual",
            "source_ref": "test",
            "worker_model": "codex",
            "review_model": "claude",
            "max_parallel_ready_projects": 1,
            "max_retries_per_project": 2,
            "budget_limit_usd": 20.0,
            "time_limit_hours": 4.0,
            "projects": [
                {
                    "project_id": "p1",
                    "status": "blocked",
                    "last_run_outcome": "deliverable_created",
                    "review": {"status": "changes_requested", "findings": ["insufficient"]},
                }
            ],
            "execution_state": {
                "ready_queue": [],
                "active_projects": [],
                "completed_projects": [],
                "failed_projects": [],
                "skipped_projects": [],
                "total_cost_usd": 2.0,
            },
        }
        manifest_path.write_text(yaml.dump(manifest_data), encoding="utf-8")
        state_path = tmp_path / "state.yaml"

        supervisor = RalphSupervisor.start(
            manifest_path=manifest_path,
            state_path=state_path,
            repo_root=tmp_path,
        )

        # Step 1: campaign iteration -> blocked
        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={"stop_reason": "campaign_blocked", "dispatched_projects": []},
        ):
            r1 = supervisor.step()
        assert r1.action == SupervisorAction.BLOCKER_CLASSIFIED.value
        state = load_supervisor_state(state_path)
        assert state.active_blocker == BlockerKind.REVIEWER_MISSING_DIFF.value

        # Step 2: handle blocker -> dispatch repair (with PR)
        dispatch_result = {
            "status": "completed",
            "outcome": "deliverable",
            "run_id": "run-full-loop",
            "deliverable": {
                "pr_url": "https://github.com/org/repo/pull/99",
                "branch": "codex/repair-branch",
            },
        }
        with patch("aragora.ralph.supervisor.asyncio.run", return_value=dispatch_result):
            r2 = supervisor.step()
        assert r2.action == SupervisorAction.REPAIR_DISPATCHED.value
        assert r2.repair_task is not None
        assert r2.status == SupervisorStatus.WAITING_FOR_MERGE.value

        # Step 4: check merge -> merged
        with patch.object(
            RalphSupervisor,
            "_fetch_pr_gate_snapshot",
            return_value=_gate_snapshot(
                pr_url="https://github.com/org/repo/pull/99",
                disposition="merged",
                state="MERGED",
                merge_commit_sha="merged-sha",
            ),
        ):
            r4 = supervisor.step()
        assert r4.status == SupervisorStatus.RESUMING.value

        # Step 5: resume -> running (with sync verification)
        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=0,
            ),
        ):
            r5 = supervisor.step()
        assert r5.action == SupervisorAction.CAMPAIGN_RESUMED.value
        assert r5.status == SupervisorStatus.RUNNING.value

        # Step 6: campaign iteration -> complete
        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={"stop_reason": "campaign_complete", "dispatched_projects": []},
        ):
            r6 = supervisor.step()
        assert r6.action == SupervisorAction.CAMPAIGN_COMPLETED.value
        assert r6.status == SupervisorStatus.COMPLETED.value

        # Verify terminal.
        r7 = supervisor.step()
        assert r7.action == SupervisorAction.NOOP.value

    def test_unknown_blocker_escalates_immediately(self, tmp_path: Path) -> None:
        """Simulate: run -> blocked with unknown cause -> escalate."""
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"

        supervisor = RalphSupervisor.start(
            manifest_path=manifest_path,
            state_path=state_path,
            repo_root=tmp_path,
        )

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={"stop_reason": "campaign_blocked", "dispatched_projects": []},
        ):
            r1 = supervisor.step()

        # No projects in manifest → unknown blocker
        assert r1.action == SupervisorAction.BLOCKER_CLASSIFIED.value
        state = load_supervisor_state(state_path)
        assert state.active_blocker == BlockerKind.UNKNOWN.value

        # Step 2: unknown blocker → escalate
        r2 = supervisor.step()
        assert r2.action == SupervisorAction.ESCALATED.value
        assert r2.status == SupervisorStatus.ESCALATED.value


# ---------------------------------------------------------------------------
# Dispatch integration tests
# ---------------------------------------------------------------------------


def _write_blocked_manifest(path: Path) -> Path:
    """Write a manifest with a blocked project that triggers reviewer_missing_diff."""
    manifest = {
        "campaign_id": "test-campaign",
        "created_at": "2026-03-10T00:00:00Z",
        "source_kind": "manual",
        "source_ref": "test",
        "worker_model": "codex",
        "review_model": "claude",
        "max_parallel_ready_projects": 1,
        "max_retries_per_project": 2,
        "budget_limit_usd": 20.0,
        "time_limit_hours": 4.0,
        "projects": [
            {
                "project_id": "proj-001",
                "title": "Test project",
                "status": "blocked",
                "last_run_outcome": "deliverable_created",
                "review": {
                    "status": "changes_requested",
                    "findings": ["Scope violation detected"],
                },
            }
        ],
        "execution_state": {
            "ready_queue": [],
            "active_projects": [],
            "completed_projects": [],
            "failed_projects": [],
            "skipped_projects": [],
            "total_cost_usd": 0.0,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(manifest), encoding="utf-8")
    return path


class TestStepDispatch:
    """Tests for the dispatch wiring in _step_handle_blocker."""

    def test_handle_blocker_dispatches_and_stores_pr(self, tmp_path: Path) -> None:
        manifest_path = _write_blocked_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
            active_blocker=BlockerKind.REVIEWER_MISSING_DIFF.value,
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)

        mock_dispatch_result = {
            "status": "completed",
            "outcome": "deliverable_created",
            "run_id": "run-abc123",
            "deliverable": {
                "type": "pr",
                "pr_url": "https://github.com/org/repo/pull/55",
                "branch": "fix/reviewer-diff",
                "commit_shas": ["sha1"],
            },
        }

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value=mock_dispatch_result,
        ):
            result = supervisor.step()

        assert result.action == SupervisorAction.REPAIR_DISPATCHED.value
        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value
        assert "PR: https://github.com/org/repo/pull/55" in result.detail

        state = load_supervisor_state(state_path)
        assert state.active_repair_pr == "https://github.com/org/repo/pull/55"
        assert state.active_repair_branch == "fix/reviewer-diff"
        assert state.active_repair_task is not None
        assert state.active_repair_task["run_id"] == "run-abc123"

    def test_handle_blocker_dispatches_branch_only(self, tmp_path: Path) -> None:
        manifest_path = _write_blocked_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
            active_blocker=BlockerKind.REVIEWER_MISSING_DIFF.value,
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)

        mock_dispatch_result = {
            "status": "completed",
            "outcome": "deliverable_created",
            "run_id": "run-def456",
            "deliverable": {
                "type": "branch",
                "branch": "fix/reviewer-diff-v2",
                "commit_shas": ["sha2"],
            },
        }

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value=mock_dispatch_result,
        ):
            result = supervisor.step()

        assert result.action == SupervisorAction.REPAIR_DISPATCHED.value
        assert result.status == SupervisorStatus.WAITING_FOR_PR.value

        state = load_supervisor_state(state_path)
        assert state.active_repair_pr is None
        assert state.active_repair_branch == "fix/reviewer-diff-v2"

    def test_handle_blocker_dispatch_failure_stays_running(self, tmp_path: Path) -> None:
        """Dispatch returns no trackable output → stays RUNNING for retry."""
        manifest_path = _write_blocked_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
            active_blocker=BlockerKind.REVIEWER_MISSING_DIFF.value,
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)

        mock_dispatch_result = {
            "status": "failed",
            "outcome": "crash",
        }

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value=mock_dispatch_result,
        ):
            result = supervisor.step()

        assert result.action == SupervisorAction.REPAIR_DISPATCHED.value
        # No run_id, branch, or PR — stays RUNNING for retry
        assert result.status == SupervisorStatus.RUNNING.value
        state = load_supervisor_state(state_path)
        assert state.active_blocker is not None

    def test_handle_blocker_dispatch_exception_stays_running(self, tmp_path: Path) -> None:
        """Dispatch raises exception with no trackable output → stays RUNNING."""
        manifest_path = _write_blocked_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
            active_blocker=BlockerKind.REVIEWER_MISSING_DIFF.value,
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)

        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            side_effect=RuntimeError("dispatch exploded"),
        ):
            result = supervisor.step()

        assert result.action == SupervisorAction.REPAIR_DISPATCHED.value
        assert result.status == SupervisorStatus.RUNNING.value

    def test_dispatch_crash_eventually_escalates_via_max_attempts(self, tmp_path: Path) -> None:
        """Repeated dispatch crashes exhaust max_repair_attempts → escalate."""
        manifest_path = _write_blocked_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RUNNING.value,
            active_blocker=BlockerKind.REVIEWER_MISSING_DIFF.value,
            repair_attempts=0,
            max_repair_attempts=2,
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)

        # Two dispatch crashes — uses up all attempts
        for _ in range(2):
            with patch(
                "aragora.ralph.supervisor.asyncio.run",
                side_effect=RuntimeError("crash"),
            ):
                result = supervisor.step()
            assert result.status == SupervisorStatus.RUNNING.value

        # Third attempt: max_repair_attempts exceeded → escalate
        result = supervisor.step()
        assert result.action == SupervisorAction.ESCALATED.value
        assert result.status == SupervisorStatus.ESCALATED.value

    def test_auto_merge_not_called_twice(self, tmp_path: Path) -> None:
        """Auto-merge is only requested once per PR, not on every poll tick."""
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            active_repair_pr="https://github.com/org/repo/pull/99",
            active_repair_task={"title": "fix", "auto_merge_requested": True},
        )

        supervisor = RalphSupervisor(
            state_path=state_path,
            repo_root=tmp_path,
            merge_policy="admin_merge_allowed",
        )

        with (
            patch.object(
                supervisor,
                "_fetch_pr_gate_snapshot",
                return_value=_gate_snapshot(
                    pr_url="https://github.com/org/repo/pull/99",
                    disposition="merge_now",
                ),
            ),
            patch.object(supervisor, "_merge_pr") as mock_merge,
        ):
            supervisor.step()

        mock_merge.assert_not_called()

    def test_wait_for_review_admin_merge_allows_pristine_warmup_class(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            active_repair_pr="https://github.com/org/repo/pull/99",
        )

        supervisor = RalphSupervisor(
            state_path=state_path,
            repo_root=tmp_path,
            merge_policy="admin_merge_allowed",
            auto_handle_calibration_store=AutoHandleCalibrationStore(
                db_path=":memory:",
                min_samples=2,
                min_success_rate=0.75,
            ),
        )

        with (
            patch.object(
                supervisor,
                "_fetch_pr_gate_snapshot",
                return_value=_gate_snapshot(
                    pr_url="https://github.com/org/repo/pull/99",
                    disposition="wait_for_review",
                    required_checks_green=True,
                ),
            ),
            patch.object(
                supervisor,
                "_merge_pr",
                return_value=MagicMock(merged=True, to_dict=lambda: {"merged": True}),
            ) as mock_merge,
        ):
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value
        assert "Admin merge initiated" in result.detail
        mock_merge.assert_called_once_with(
            "https://github.com/org/repo/pull/99",
            required_checks_green=True,
            allow_admin=True,
            head_sha=_GATE_HEAD_SHA,
        )

    def test_wait_for_review_admin_merge_blocks_uncalibrated_class_after_failure(
        self, tmp_path: Path
    ) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            active_repair_pr="https://github.com/org/repo/pull/99",
        )

        store = AutoHandleCalibrationStore(
            db_path=":memory:",
            min_samples=2,
            min_success_rate=0.75,
        )
        decision_class = fingerprint_admin_merge_class(
            base_branch="main",
            required_checks_count=0,
            target_kind="repair",
        )
        store.record_outcome(
            decision_id=auto_handle_decision_id(
                auto_handle_path=AUTO_HANDLE_PATH_ADMIN_MERGE_ALLOWED,
                pr_url="https://github.com/org/repo/pull/1",
                decision_class=decision_class,
            ),
            auto_handle_path=AUTO_HANDLE_PATH_ADMIN_MERGE_ALLOWED,
            decision_class=decision_class,
            outcome=OUTCOME_HUMAN_OVERRIDE,
            pr_url="https://github.com/org/repo/pull/1",
        )

        supervisor = RalphSupervisor(
            state_path=state_path,
            repo_root=tmp_path,
            merge_policy="admin_merge_allowed",
            auto_handle_calibration_store=store,
        )

        with (
            patch.object(
                supervisor,
                "_fetch_pr_gate_snapshot",
                return_value=_gate_snapshot(
                    pr_url="https://github.com/org/repo/pull/99",
                    disposition="wait_for_review",
                    required_checks_green=True,
                ),
            ),
            patch.object(supervisor, "_merge_pr") as mock_merge,
        ):
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value
        assert "calibration gate" in result.detail
        mock_merge.assert_not_called()

    def test_auto_merge_called_when_policy_allows(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            active_repair_pr="https://github.com/org/repo/pull/99",
        )

        supervisor = RalphSupervisor(
            state_path=state_path,
            repo_root=tmp_path,
            merge_policy="admin_merge_allowed",
        )

        with (
            patch.object(
                supervisor,
                "_fetch_pr_gate_snapshot",
                return_value=_gate_snapshot(
                    pr_url="https://github.com/org/repo/pull/99",
                    disposition="merge_now",
                ),
            ),
            patch.object(
                supervisor,
                "_merge_pr",
                return_value=MagicMock(merged=True, to_dict=lambda: {"merged": True}),
            ) as mock_merge,
        ):
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value
        mock_merge.assert_called_once_with(
            "https://github.com/org/repo/pull/99",
            required_checks_green=True,
            allow_admin=True,
            head_sha=_GATE_HEAD_SHA,
        )

    def test_backward_auto_merge_wrapper_merges_the_snapshot_head(self, tmp_path: Path) -> None:
        supervisor = RalphSupervisor(
            state_path=tmp_path / "state.yaml",
            repo_root=tmp_path,
            merge_policy="admin_merge_allowed",
        )
        snapshot = _gate_snapshot(
            pr_url="https://github.com/org/repo/pull/99",
            disposition="merge_now",
            required_checks_green=False,
            head_sha="b" * 40,
        )

        with (
            patch.object(supervisor, "_fetch_pr_gate_snapshot", return_value=snapshot),
            patch.object(supervisor, "_merge_pr", return_value=MagicMock(merged=False)) as merge,
        ):
            assert supervisor._auto_merge_pr("https://github.com/org/repo/pull/99") is False

        merge.assert_called_once_with(
            "https://github.com/org/repo/pull/99",
            required_checks_green=False,
            allow_admin=True,
            head_sha="b" * 40,
        )

    def test_auto_merge_not_called_for_manual_policy(self, tmp_path: Path) -> None:
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.WAITING_FOR_MERGE.value,
            active_repair_pr="https://github.com/org/repo/pull/99",
        )

        supervisor = RalphSupervisor(
            state_path=state_path,
            repo_root=tmp_path,
            merge_policy="manual_review_required",
        )

        with (
            patch.object(
                supervisor,
                "_fetch_pr_gate_snapshot",
                return_value=_gate_snapshot(
                    pr_url="https://github.com/org/repo/pull/99",
                    disposition="merge_now",
                ),
            ),
            patch.object(supervisor, "_merge_pr") as mock_merge,
        ):
            result = supervisor.step()

        assert result.status == SupervisorStatus.WAITING_FOR_MERGE.value
        mock_merge.assert_not_called()

    def test_resume_uses_fetch_not_pull(self, tmp_path: Path) -> None:
        """Resume uses git fetch (worktree-safe), not git pull."""
        manifest_path = _write_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"
        _write_state(
            state_path,
            campaign_manifest_path=str(manifest_path),
            status=SupervisorStatus.RESUMING.value,
            merge_commit_sha="abc123",
        )

        supervisor = RalphSupervisor(state_path=state_path, repo_root=tmp_path)

        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=0,
            ),
        ) as mock_run:
            result = supervisor.step()

        assert result.action == SupervisorAction.CAMPAIGN_RESUMED.value
        assert result.status == SupervisorStatus.RUNNING.value
        # First call must be fetch.
        first_call = mock_run.call_args_list[0]
        assert first_call[0][0] == ["git", "fetch", "origin", "main"]
        # No git pull in any call.
        for call in mock_run.call_args_list:
            assert "pull" not in call[0][0]

    def test_full_loop_with_dispatch(self, tmp_path: Path) -> None:
        """Full loop: RUNNING → classify → dispatch(PR) → merge → resume → complete."""
        manifest_path = _write_blocked_manifest(tmp_path / "manifest.yaml")
        state_path = tmp_path / "state.yaml"

        supervisor = RalphSupervisor.start(
            manifest_path=manifest_path,
            state_path=state_path,
            repo_root=tmp_path,
            merge_policy="admin_merge_allowed",
        )

        # Step 1: Campaign iteration → blocked
        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={"stop_reason": "campaign_blocked", "dispatched_projects": []},
        ):
            r1 = supervisor.step()
        assert r1.action == SupervisorAction.BLOCKER_CLASSIFIED.value

        # Step 2: Handle blocker → dispatch repair → gets PR
        mock_dispatch = {
            "status": "completed",
            "outcome": "deliverable_created",
            "run_id": "run-loop-1",
            "deliverable": {
                "type": "pr",
                "pr_url": "https://github.com/org/repo/pull/100",
                "branch": "fix/reviewer-fidelity",
                "commit_shas": ["sha1"],
            },
        }
        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value=mock_dispatch,
        ):
            r2 = supervisor.step()
        assert r2.action == SupervisorAction.REPAIR_DISPATCHED.value
        assert r2.status == SupervisorStatus.WAITING_FOR_MERGE.value

        # Step 3: Check merge → merged
        with (
            patch.object(
                supervisor,
                "_fetch_pr_gate_snapshot",
                return_value=_gate_snapshot(
                    pr_url="https://github.com/org/repo/pull/100",
                    disposition="merged",
                    state="MERGED",
                    merge_commit_sha="abc123def",
                ),
            ),
            patch.object(supervisor, "_auto_merge_pr"),
        ):
            r3 = supervisor.step()
        assert r3.status == SupervisorStatus.RESUMING.value

        # Step 4: Resume → sync verification → RUNNING
        with patch(
            "aragora.ralph.supervisor.subprocess.run",
            side_effect=_mock_subprocess_for_resume(
                ancestor_origin_rc=0,
                ancestor_head_rc=0,
            ),
        ):
            r4 = supervisor.step()
        assert r4.action == SupervisorAction.CAMPAIGN_RESUMED.value
        assert r4.status == SupervisorStatus.RUNNING.value

        # Step 5: Campaign iteration → complete
        with patch(
            "aragora.ralph.supervisor.asyncio.run",
            return_value={"stop_reason": "campaign_complete", "dispatched_projects": []},
        ):
            r5 = supervisor.step()
        assert r5.action == SupervisorAction.CAMPAIGN_COMPLETED.value
        assert r5.status == SupervisorStatus.COMPLETED.value


# ---------------------------------------------------------------------------
# Repair spec
# ---------------------------------------------------------------------------


class TestBuildRepairSpec:
    def test_repair_spec_does_not_require_approval(self, tmp_path: Path) -> None:
        """Repair specs are autonomous — requires_approval must be False."""
        from aragora.ralph.repair import generate_repair_task

        supervisor = RalphSupervisor(state_path=tmp_path / "s.yaml", repo_root=tmp_path)
        repair = generate_repair_task(BlockerKind.REVIEWER_MISSING_DIFF)
        assert repair is not None
        spec = supervisor._build_repair_spec(repair)
        assert spec.requires_approval is False
