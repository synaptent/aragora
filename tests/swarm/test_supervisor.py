"""Tests for supervisor-backed swarm execution."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aragora.nomic.dev_coordination import DevCoordinationStore
from aragora.nomic.task_decomposer import SubTask, TaskDecomposition
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.supervisor import SwarmSupervisor
from aragora.worktree.lifecycle import ManagedWorktreeSession


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main")
    _run(repo, "git", "config", "user.email", "test@example.com")
    _run(repo, "git", "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _run(repo, "git", "add", "README.md")
    _run(repo, "git", "commit", "-m", "initial")
    _run(repo, "git", "remote", "add", "origin", str(repo))
    _run(repo, "git", "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


@pytest.fixture()
def store(repo: Path) -> DevCoordinationStore:
    return DevCoordinationStore(repo_root=repo)


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def test_start_run_creates_leased_work_orders(repo: Path, store: DevCoordinationStore) -> None:
    sessions = [
        ManagedWorktreeSession(
            session_id="swarm-a",
            agent="codex",
            branch="codex/swarm-a",
            path=repo / "wt-a",
            created=True,
            reconcile_status="up_to_date",
            payload={},
        ),
        ManagedWorktreeSession(
            session_id="swarm-b",
            agent="claude",
            branch="codex/swarm-b",
            path=repo / "wt-b",
            created=True,
            reconcile_status="up_to_date",
            payload={},
        ),
    ]
    sessions[0].path.mkdir()
    sessions[1].path.mkdir()

    lifecycle = MagicMock()
    lifecycle.ensure_managed_worktree.side_effect = sessions
    decomposer = MagicMock()
    decomposer.analyze.return_value = TaskDecomposition(
        original_task="Goal",
        complexity_score=8,
        complexity_level="high",
        should_decompose=True,
        subtasks=[
            SubTask(
                id="wo-1",
                title="Server lane",
                description="Implement server lane",
                file_scope=["aragora/server/handlers/foo.py"],
            ),
            SubTask(
                id="wo-2",
                title="Test lane",
                description="Implement test lane",
                file_scope=["tests/server/test_foo.py"],
            ),
        ],
    )
    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        lifecycle=lifecycle,
        decomposer=decomposer,
    )
    spec = SwarmSpec(raw_goal="Goal", refined_goal="Goal")

    run = supervisor.start_run(spec=spec, max_concurrency=2)

    assert run.status == "active"
    assert len(run.work_orders) == 2
    assert {item["status"] for item in run.work_orders} == {"leased"}
    assert store.status_summary()["counts"]["supervisor_runs"] == 1
    assert store.status_summary()["counts"]["active_leases"] == 2


def test_refresh_run_scales_queued_work_after_completion(
    repo: Path, store: DevCoordinationStore
) -> None:
    counter = {"value": 0}

    def _ensure_session(**_kwargs: object) -> ManagedWorktreeSession:
        counter["value"] += 1
        path = repo / f"wt-{counter['value']}"
        path.mkdir(exist_ok=True)
        return ManagedWorktreeSession(
            session_id=f"swarm-{counter['value']}",
            agent="codex" if counter["value"] % 2 else "claude",
            branch=f"codex/swarm-{counter['value']}",
            path=path,
            created=True,
            reconcile_status="up_to_date",
            payload={},
        )

    lifecycle = MagicMock()
    lifecycle.ensure_managed_worktree.side_effect = _ensure_session
    decomposer = MagicMock()
    decomposer.analyze.return_value = TaskDecomposition(
        original_task="Goal",
        complexity_score=8,
        complexity_level="high",
        should_decompose=True,
        subtasks=[
            SubTask(
                id="wo-1",
                title="Lane one",
                description="Lane one",
                file_scope=["aragora/server/handlers/foo.py"],
            ),
            SubTask(
                id="wo-2",
                title="Lane two",
                description="Lane two",
                file_scope=["tests/server/test_foo.py"],
            ),
        ],
    )
    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        lifecycle=lifecycle,
        decomposer=decomposer,
    )
    spec = SwarmSpec(raw_goal="Goal", refined_goal="Goal")

    run = supervisor.start_run(spec=spec, max_concurrency=1)
    leased = [item for item in run.work_orders if item["status"] == "leased"]
    queued = [item for item in run.work_orders if item["status"] == "queued"]
    assert len(leased) == 1
    assert len(queued) == 1

    first = leased[0]
    store.record_completion(
        lease_id=str(first["lease_id"]),
        owner_agent=str(first["target_agent"]),
        owner_session_id=str(first["owner_session_id"]),
        branch=str(first["branch"]),
        worktree_path=str(first["worktree_path"]),
        commit_shas=["abc12345"],
        changed_paths=["aragora/server/handlers/foo.py"],
    )

    refreshed = supervisor.refresh_run(run.run_id)
    leased_after = [item for item in refreshed.work_orders if item["status"] == "leased"]
    completed_after = [item for item in refreshed.work_orders if item["status"] == "completed"]

    assert len(leased_after) == 1
    assert len(completed_after) == 1
    assert counter["value"] >= 2


def test_refresh_run_releases_orphaned_conflicts_and_retries(
    repo: Path, store: DevCoordinationStore
) -> None:
    missing_path = repo / "missing-docs-worktree"
    orphaned = store.claim_lease(
        task_id="old-docs-lane",
        title="Old docs lane",
        owner_agent="codex",
        owner_session_id="stale-session",
        branch="codex/stale-docs",
        worktree_path=str(missing_path),
        claimed_paths=["docs/guides/SWARM_DOGFOOD_OPERATOR.md"],
    )

    lifecycle = MagicMock()
    session_path = repo / "wt-docs"
    session_path.mkdir()
    lifecycle.ensure_managed_worktree.return_value = ManagedWorktreeSession(
        session_id="fresh-docs",
        agent="codex",
        branch="codex/fresh-docs",
        path=session_path,
        created=True,
        reconcile_status="up_to_date",
        payload={},
    )

    decomposer = MagicMock()
    decomposer.analyze.return_value = TaskDecomposition(
        original_task="Goal",
        complexity_score=2,
        complexity_level="low",
        should_decompose=True,
        subtasks=[
            SubTask(
                id="docs-lane",
                title="Write operator guide",
                description="Add operator guide.",
                file_scope=["docs/guides/SWARM_DOGFOOD_OPERATOR.md"],
            )
        ],
    )

    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        lifecycle=lifecycle,
        decomposer=decomposer,
    )
    run = supervisor.start_run(spec=SwarmSpec(raw_goal="Goal", refined_goal="Goal"))

    work_order = run.work_orders[0]
    assert work_order["status"] == "leased"
    assert work_order["lease_id"]
    active_lease_ids = {lease.lease_id for lease in store.list_active_leases()}
    assert orphaned.lease_id not in active_lease_ids


def test_refresh_run_marks_resource_wait_on_disk_full(
    repo: Path, store: DevCoordinationStore
) -> None:
    lifecycle = MagicMock()
    lifecycle.ensure_managed_worktree.side_effect = RuntimeError("No space left on device")
    decomposer = MagicMock()
    decomposer.analyze.return_value = TaskDecomposition(
        original_task="Goal",
        complexity_score=2,
        complexity_level="low",
        should_decompose=True,
        subtasks=[
            SubTask(
                id="cli-tests-lane",
                title="Run CLI coverage",
                description="Add CLI coverage.",
                file_scope=["tests/cli/test_swarm_command.py"],
            )
        ],
    )

    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        lifecycle=lifecycle,
        decomposer=decomposer,
    )
    run = supervisor.start_run(spec=SwarmSpec(raw_goal="Goal", refined_goal="Goal"))

    assert run.status == "active"
    work_order = run.work_orders[0]
    assert work_order["status"] == "waiting_resource"
    assert "No space left on device" in work_order["resource_error"]


def test_start_run_prefers_explicit_spec_work_orders(
    repo: Path, store: DevCoordinationStore
) -> None:
    session_path = repo / "wt-explicit"
    session_path.mkdir()
    lifecycle = MagicMock()
    lifecycle.ensure_managed_worktree.return_value = ManagedWorktreeSession(
        session_id="swarm-explicit",
        agent="codex",
        branch="codex/swarm-explicit",
        path=session_path,
        created=True,
        reconcile_status="up_to_date",
        payload={},
    )
    decomposer = MagicMock()

    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        lifecycle=lifecycle,
        decomposer=decomposer,
    )
    spec = SwarmSpec(
        raw_goal="Dogfood the supervised swarm",
        refined_goal="Dogfood the supervised swarm",
        acceptance_criteria=["python -m pytest tests/swarm/test_commander.py -q"],
        work_orders=[
            {
                "work_order_id": "docs-lane",
                "title": "Write operator guide",
                "description": "Add the operator guide.",
                "file_scope": ["docs/guides/SWARM_DOGFOOD_OPERATOR.md"],
                "expected_tests": [],
                "target_agent": "codex",
                "reviewer_agent": "claude",
                "metadata": {"lane": "docs"},
            }
        ],
    )

    run = supervisor.start_run(spec=spec, max_concurrency=1)

    decomposer.analyze.assert_not_called()
    assert run.status == "active"
    assert len(run.work_orders) == 1
    work_order = run.work_orders[0]
    assert work_order["work_order_id"] == "docs-lane"
    assert work_order["target_agent"] == "codex"
    assert work_order["reviewer_agent"] == "claude"
    assert work_order["file_scope"] == ["docs/guides/SWARM_DOGFOOD_OPERATOR.md"]
    assert work_order["metadata"]["lane"] == "docs"
    assert work_order["metadata"]["source"] == "explicit_spec_work_order"


# ---------- dispatch_workers / collect_results tests ----------

from unittest.mock import AsyncMock, patch
from aragora.swarm.worker_launcher import WorkerLauncher, WorkerProcess

UTC = timezone.utc


@pytest.mark.asyncio
async def test_dispatch_workers_launches_leased_orders(
    repo: Path, store: DevCoordinationStore
) -> None:
    """dispatch_workers should call launcher.launch for each leased work order."""
    sessions = [
        ManagedWorktreeSession(
            path=repo,
            branch="swarm-dispatch-1",
            session_id="dispatch-sess-1",
            agent="claude",
            created=True,
            reconcile_status=None,
            payload={},
        )
    ]
    session_iter = iter(sessions)

    lifecycle = MagicMock()
    lifecycle.ensure_managed_worktree = MagicMock(side_effect=lambda **kw: next(session_iter))

    decomposer = MagicMock()
    decomposer.analyze.return_value = TaskDecomposition(
        original_task="dispatch test",
        complexity_score=3,
        complexity_level="moderate",
        should_decompose=True,
        subtasks=[
            SubTask(
                id="dispatch-task",
                title="Dispatch test",
                description="Test dispatch",
                file_scope=["aragora/test.py"],
            )
        ],
    )

    mock_launcher = MagicMock(spec=WorkerLauncher)
    mock_worker = WorkerProcess(
        work_order_id="dispatch-task",
        agent="claude",
        worktree_path=str(repo),
        branch="swarm-dispatch-1",
        pid=999,
    )
    mock_launcher.launch = AsyncMock(return_value=mock_worker)

    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        lifecycle=lifecycle,
        decomposer=decomposer,
        launcher=mock_launcher,
    )

    spec = SwarmSpec.from_dict(
        {
            "raw_goal": "dispatch test",
            "refined_goal": "dispatch test",
        }
    )

    run = supervisor.start_run(spec=spec, refresh_scaling=True)
    leased = [w for w in run.work_orders if w.get("status") == "leased"]
    assert len(leased) >= 1

    launched = await supervisor.dispatch_workers(run.run_id)
    assert len(launched) >= 1
    assert launched[0].pid == 999
    mock_launcher.launch.assert_called()


@pytest.mark.asyncio
async def test_collect_results_updates_work_orders(repo: Path, store: DevCoordinationStore) -> None:
    """collect_results should wait for dispatched workers and update statuses."""
    # Create a run with one dispatched work order
    run_record = store.create_supervisor_run(
        goal="collect test",
        target_branch="main",
        supervisor_agents={"planner": "codex"},
        approval_policy={},
        spec={"raw_goal": "collect test"},
        work_orders=[
            {
                "work_order_id": "wo-collect",
                "status": "dispatched",
                "worktree_path": str(repo),
                "branch": "main",
                "target_agent": "claude",
            }
        ],
        status="active",
    )
    run_id = run_record["run_id"]

    # Mock launcher with a completed worker
    mock_launcher = MagicMock(spec=WorkerLauncher)
    completed_worker = WorkerProcess(
        work_order_id="wo-collect",
        agent="claude",
        worktree_path=str(repo),
        branch="main",
        pid=100,
        exit_code=0,
        completed_at="2026-03-06T20:00:00+00:00",
        diff="diff --git a/test.py",
    )
    mock_launcher.get_worker = MagicMock(return_value=completed_worker)
    mock_launcher.wait = AsyncMock(return_value=completed_worker)

    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        launcher=mock_launcher,
    )

    results = await supervisor.collect_results(run_id)
    assert len(results) == 1
    assert results[0].exit_code == 0

    # Verify the run was updated
    updated = store.get_supervisor_run(run_id)
    wo = updated["work_orders"][0]
    assert wo["status"] == "completed"


@pytest.mark.asyncio
async def test_collect_results_marks_scope_violation_needs_human(
    repo: Path, store: DevCoordinationStore
) -> None:
    lease = store.claim_lease(
        task_id="scope-lane",
        title="Scope lane",
        owner_agent="claude",
        owner_session_id="scope-session",
        branch="main",
        worktree_path=str(repo),
        claimed_paths=["aragora/server/auth_checks.py"],
    )
    run_record = store.create_supervisor_run(
        goal="scope violation",
        target_branch="main",
        supervisor_agents={},
        approval_policy={},
        spec={"raw_goal": "scope violation"},
        work_orders=[
            {
                "work_order_id": "wo-scope",
                "status": "dispatched",
                "worktree_path": str(repo),
                "branch": "main",
                "target_agent": "claude",
                "owner_session_id": "scope-session",
                "lease_id": lease.lease_id,
                "review_status": "pending",
            }
        ],
        status="active",
    )
    run_id = run_record["run_id"]

    mock_launcher = MagicMock(spec=WorkerLauncher)
    completed_worker = WorkerProcess(
        work_order_id="wo-scope",
        agent="claude",
        worktree_path=str(repo),
        branch="main",
        session_id="scope-session",
        pid=100,
        exit_code=0,
        completed_at="2026-03-06T20:00:00+00:00",
        diff="diff --git a/aragora/server/handlers/playground.py",
        changed_paths=["aragora/server/handlers/playground.py"],
        commit_shas=["abc12345"],
        tests_run=["pytest -q tests/swarm/test_supervisor.py"],
    )
    mock_launcher.get_worker = MagicMock(return_value=completed_worker)
    mock_launcher.wait = AsyncMock(return_value=completed_worker)

    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        launcher=mock_launcher,
    )

    results = await supervisor.collect_results(run_id)
    assert len(results) == 1
    assert results[0].exit_code == 0

    updated = store.get_supervisor_run(run_id)
    assert updated is not None
    wo = updated["work_orders"][0]
    assert wo["status"] == "needs_human"
    assert wo["review_status"] == "changes_requested"
    assert "file-scope ownership" in wo["dispatch_error"]
    assert wo["receipt_id"] is None
    assert wo["lease_id"] == lease.lease_id
    assert wo["scope_violation"]["violations"][0]["type"] == "out_of_scope"

    summary = store.status_summary()
    assert summary["counts"]["scope_violations"] == 1
    assert summary["counts"]["active_leases"] == 1


@pytest.mark.asyncio
async def test_dispatch_handles_missing_cli(repo: Path, store: DevCoordinationStore) -> None:
    """dispatch_workers should requeue onto the fallback agent when one CLI is unavailable."""
    run_record = store.create_supervisor_run(
        goal="missing cli test",
        target_branch="main",
        supervisor_agents={},
        approval_policy={},
        spec={"raw_goal": "test"},
        work_orders=[
            {
                "work_order_id": "wo-fail",
                "status": "leased",
                "worktree_path": str(repo),
                "branch": "main",
                "target_agent": "claude",
            }
        ],
        status="active",
    )
    run_id = run_record["run_id"]

    mock_launcher = MagicMock(spec=WorkerLauncher)
    mock_launcher.launch = AsyncMock(side_effect=FileNotFoundError("claude CLI not found"))

    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        launcher=mock_launcher,
    )

    launched = await supervisor.dispatch_workers(run_id)
    assert len(launched) == 0

    updated = store.get_supervisor_run(run_id)
    wo = updated["work_orders"][0]
    assert wo["status"] == "leased"
    assert wo["target_agent"] == "codex"
    assert wo["reviewer_agent"] == "claude"
    assert wo["metadata"]["last_failure_reason"] == "agent_unavailable"
    assert "CLI not found" in wo["metadata"]["last_failure_detail"]
    assert wo.get("lease_id") is None


@pytest.mark.asyncio
async def test_collect_finished_results_requeues_capacity_failure_to_fallback_agent(
    repo: Path, store: DevCoordinationStore
) -> None:
    lifecycle = MagicMock()
    lifecycle.ensure_managed_worktree.return_value = ManagedWorktreeSession(
        path=repo,
        branch="swarm-fallback-1",
        session_id="dispatch-sess-fallback",
        agent="claude",
        created=True,
        reconcile_status=None,
        payload={},
    )

    mock_launcher = MagicMock(spec=WorkerLauncher)
    mock_launcher.collect_finished = AsyncMock(
        return_value=[
            WorkerProcess(
                work_order_id="fallback-task",
                agent="claude",
                worktree_path=str(repo),
                branch="swarm-fallback-1",
                pid=777,
                session_id="dispatch-sess-fallback",
                lease_id="lease-1",
                exit_code=1,
                completed_at="2026-03-06T00:00:00+00:00",
                stdout="Credit balance is too low\n",
                stderr="",
            )
        ]
    )
    mock_launcher.collect_detached_finished = AsyncMock(return_value=None)

    decomposer = MagicMock()
    decomposer.analyze.return_value = TaskDecomposition(
        original_task="Goal",
        complexity_score=2,
        complexity_level="low",
        should_decompose=True,
        subtasks=[
            SubTask(
                id="fallback-task",
                title="Fallback test",
                description="Test capacity fallback",
                file_scope=["tests/swarm/test_commander.py"],
            )
        ],
    )

    supervisor = SwarmSupervisor(
        repo_root=repo,
        store=store,
        lifecycle=lifecycle,
        launcher=mock_launcher,
        decomposer=decomposer,
    )
    run = supervisor.start_run(spec=SwarmSpec(raw_goal="Goal", refined_goal="Goal"))
    run.work_orders[0]["status"] = "dispatched"
    run.work_orders[0]["target_agent"] = "claude"
    run.work_orders[0]["reviewer_agent"] = "codex"
    run.work_orders[0]["pid"] = 777
    store.update_supervisor_run(run.run_id, work_orders=run.work_orders, status="active")

    completed = await supervisor.collect_finished_results(run.run_id)

    assert len(completed) == 1
    refreshed = store.get_supervisor_run(run.run_id)
    assert refreshed is not None
    work_order = refreshed["work_orders"][0]
    assert work_order["status"] == "leased"
    assert work_order["target_agent"] == "codex"
    assert work_order["reviewer_agent"] == "claude"
    assert work_order["metadata"]["last_failure_reason"] == "agent_capacity"
    assert work_order["metadata"]["attempted_agents"] == ["claude"]
    assert work_order["lease_id"] == run.work_orders[0]["lease_id"]
    assert store.status_summary()["counts"]["active_leases"] == 1


@pytest.mark.asyncio
async def test_collect_finished_results_updates_progress_heartbeat(
    repo: Path, store: DevCoordinationStore
) -> None:
    old_progress = "2026-03-06T00:00:00+00:00"
    run_record = store.create_supervisor_run(
        goal="progress heartbeat",
        target_branch="main",
        supervisor_agents={},
        approval_policy={},
        spec={"raw_goal": "progress heartbeat"},
        work_orders=[
            {
                "work_order_id": "wo-progress",
                "status": "dispatched",
                "worktree_path": str(repo),
                "branch": "main",
                "target_agent": "codex",
                "pid": 321,
                "initial_head": "abc123",
                "dispatched_at": old_progress,
                "last_progress_at": old_progress,
                "progress_fingerprint": {
                    "head_sha": "abc123",
                    "changed_paths": [],
                    "diff_lines": 0,
                },
            }
        ],
        status="active",
    )

    mock_launcher = MagicMock(spec=WorkerLauncher)
    mock_launcher.collect_finished = AsyncMock(return_value=[])
    mock_launcher.snapshot_progress = AsyncMock(
        return_value={
            "pid_alive": True,
            "head_sha": "def456",
            "changed_paths": ["aragora/swarm/supervisor.py"],
            "diff_lines": 12,
        }
    )
    mock_launcher.config = SimpleNamespace(auto_commit=True, no_progress_timeout_seconds=120.0)

    supervisor = SwarmSupervisor(repo_root=repo, store=store, launcher=mock_launcher)

    with patch.object(WorkerLauncher, "collect_detached_result", new=AsyncMock(return_value=None)):
        completed = await supervisor.collect_finished_results(run_record["run_id"])

    assert completed == []
    updated = store.get_supervisor_run(run_record["run_id"])
    assert updated is not None
    work_order = updated["work_orders"][0]
    assert work_order["status"] == "dispatched"
    assert work_order["last_progress_at"] != old_progress
    assert work_order["head_sha"] == "def456"
    assert work_order["changed_paths"] == ["aragora/swarm/supervisor.py"]
    assert work_order["diff_lines"] == 12


@pytest.mark.asyncio
async def test_collect_finished_results_marks_dead_dispatched_worker_needs_human(
    repo: Path, store: DevCoordinationStore
) -> None:
    run_record = store.create_supervisor_run(
        goal="dead worker",
        target_branch="main",
        supervisor_agents={},
        approval_policy={},
        spec={"raw_goal": "dead worker"},
        work_orders=[
            {
                "work_order_id": "wo-dead",
                "status": "dispatched",
                "worktree_path": str(repo),
                "branch": "main",
                "target_agent": "codex",
                "pid": 9999,
                "initial_head": "abc123",
                "dispatched_at": "2026-03-06T00:00:00+00:00",
                "last_progress_at": "2026-03-06T00:00:00+00:00",
                "progress_fingerprint": {
                    "head_sha": "abc123",
                    "changed_paths": [],
                    "diff_lines": 0,
                },
            }
        ],
        status="active",
    )

    mock_launcher = MagicMock(spec=WorkerLauncher)
    mock_launcher.collect_finished = AsyncMock(return_value=[])
    mock_launcher.snapshot_progress = AsyncMock(
        return_value={
            "pid_alive": False,
            "head_sha": "abc123",
            "changed_paths": [],
            "diff_lines": 0,
        }
    )
    mock_launcher.config = SimpleNamespace(auto_commit=True, no_progress_timeout_seconds=120.0)

    supervisor = SwarmSupervisor(repo_root=repo, store=store, launcher=mock_launcher)

    with patch.object(WorkerLauncher, "collect_detached_result", new=AsyncMock(return_value=None)):
        completed = await supervisor.collect_finished_results(run_record["run_id"])

    assert completed == []
    updated = store.get_supervisor_run(run_record["run_id"])
    assert updated is not None
    work_order = updated["work_orders"][0]
    assert work_order["status"] == "needs_human"
    assert "without receipt or exit marker" in work_order["dispatch_error"]
    assert "pid" not in work_order


@pytest.mark.asyncio
async def test_collect_finished_results_marks_no_progress_timeout_needs_human(
    repo: Path, store: DevCoordinationStore
) -> None:
    stale_time = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    run_record = store.create_supervisor_run(
        goal="no progress timeout",
        target_branch="main",
        supervisor_agents={},
        approval_policy={},
        spec={"raw_goal": "no progress timeout"},
        work_orders=[
            {
                "work_order_id": "wo-stalled",
                "status": "dispatched",
                "worktree_path": str(repo),
                "branch": "main",
                "target_agent": "claude",
                "pid": 4242,
                "initial_head": "abc123",
                "dispatched_at": stale_time,
                "last_progress_at": stale_time,
                "progress_fingerprint": {
                    "head_sha": "abc123",
                    "changed_paths": [],
                    "diff_lines": 0,
                },
            }
        ],
        status="active",
    )

    mock_launcher = MagicMock(spec=WorkerLauncher)
    mock_launcher.collect_finished = AsyncMock(return_value=[])
    mock_launcher.snapshot_progress = AsyncMock(
        return_value={
            "pid_alive": True,
            "head_sha": "abc123",
            "changed_paths": [],
            "diff_lines": 0,
        }
    )
    mock_launcher.config = SimpleNamespace(auto_commit=True, no_progress_timeout_seconds=60.0)

    supervisor = SwarmSupervisor(repo_root=repo, store=store, launcher=mock_launcher)

    with patch.object(WorkerLauncher, "collect_detached_result", new=AsyncMock(return_value=None)):
        completed = await supervisor.collect_finished_results(run_record["run_id"])

    assert completed == []
    updated = store.get_supervisor_run(run_record["run_id"])
    assert updated is not None
    work_order = updated["work_orders"][0]
    assert work_order["status"] == "needs_human"
    assert "no-progress timeout" in work_order["dispatch_error"]
