"""Pin the worker-type circuit breaker and stale worker-state split.

The worker-type circuit breaker helpers and the stale/orphaned worker-state
helpers live in ``aragora.swarm.supervisor_worker_state``.
``aragora.swarm.supervisor_workers`` re-exports them unchanged, so the
``SwarmSupervisor`` delegates and any direct importer keep working.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aragora.swarm import supervisor as supervisor_module
from aragora.swarm import supervisor_worker_state, supervisor_workers
from aragora.swarm.supervisor import SwarmSupervisor

MOVED_HELPERS = """
    _persist_terminal_blocker_evidence _dispatch_failure_reason
    _worker_type_circuit_breaker_policy _worker_type_circuit_breakers
    _worker_type_circuit_breaker_metadata _default_worker_type_circuit_breaker
    _normalized_timestamp _worker_type_circuit_breaker_is_open
    _worker_type_circuit_breaker_detail _record_worker_type_failure
    _record_worker_type_success _reset_worker_type_circuit_breaker_entry
    _expire_worker_type_circuit_breakers _mark_worker_type_blocked _mark_dispatch_failed
    _clear_stale_prelaunch_deliverable_state _clear_stale_runtime_deliverable_state
    _release_orphaned_conflict_leases _orphaned_conflict_reason _is_managed_worktree
    _session_lock_state _parse_session_lock_pids _is_resource_constraint_error
    _alternate_agent _kill_worker
""".split()


@pytest.mark.parametrize("name", MOVED_HELPERS)
def test_helper_is_defined_in_worker_state_and_reexported(name: str) -> None:
    helper = getattr(supervisor_worker_state, name)
    assert helper.__module__ == "aragora.swarm.supervisor_worker_state"
    assert getattr(supervisor_workers, name) is helper


def test_supervisor_workers_is_below_the_file_size_cap() -> None:
    path = Path(supervisor_workers.__file__)
    assert len(path.read_text(encoding="utf-8").splitlines()) < 2000


def test_worker_state_module_shares_supervisor_logger_and_constants() -> None:
    assert supervisor_worker_state.logger is supervisor_module.logger
    assert supervisor_worker_state.UTC is supervisor_module.UTC
    for name in (
        "DEFAULT_BREAKER_FAILURE_THRESHOLD",
        "DEFAULT_BREAKER_RESET_TIMEOUT_SECONDS",
        "SESSION_LOCK_FILES",
        "WORKER_TYPE_CIRCUIT_BREAKERS_KEY",
        "WORKER_TYPE_CIRCUIT_BREAKER_POLICY_KEY",
    ):
        assert getattr(supervisor_worker_state, name) == getattr(supervisor_module, name)


def test_breaker_opens_at_threshold_and_resets_through_supervisor(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    supervisor = SwarmSupervisor(repo_root=tmp_path)
    metadata = {
        supervisor_module.WORKER_TYPE_CIRCUIT_BREAKER_POLICY_KEY: {
            "failure_threshold": 2,
            "reset_timeout_seconds": 60,
        }
    }
    policy = supervisor._worker_type_circuit_breaker_policy(metadata)
    breakers: dict[str, dict] = {}

    supervisor._record_worker_type_failure(
        breakers, "Codex", reason="agent_capacity", detail="busy", policy=policy
    )
    assert not supervisor._worker_type_circuit_breaker_is_open(breakers, "codex")

    supervisor._record_worker_type_failure(
        breakers, "codex", reason="agent_capacity", detail="busy", policy=policy
    )
    assert supervisor._worker_type_circuit_breaker_is_open(breakers, "codex")
    assert breakers["codex"]["trip_count"] == 1
    detail = supervisor._worker_type_circuit_breaker_detail("codex", breakers["codex"])
    assert detail.startswith("codex breaker open until ")
    assert detail.endswith(" after agent_capacity")

    persisted = supervisor._worker_type_circuit_breaker_metadata(metadata, breakers)
    restored = supervisor._worker_type_circuit_breakers(persisted)
    assert restored["codex"]["status"] == "open"
    assert restored["codex"]["failure_threshold"] == 2

    supervisor._reset_worker_type_circuit_breaker_entry(breakers, "codex")
    assert not supervisor._worker_type_circuit_breaker_is_open(breakers, "codex")
    assert breakers["codex"]["failure_count"] == 0
    assert breakers["codex"]["last_reset_at"]


def test_dispatch_and_agent_helpers_keep_their_behavior(tmp_path: Path) -> None:
    assert SwarmSupervisor._alternate_agent("Claude") == "codex"
    assert SwarmSupervisor._alternate_agent("codex") == "claude"
    assert SwarmSupervisor._alternate_agent("gemini") is None
    assert SwarmSupervisor._dispatch_failure_reason(RuntimeError("codex CLI not found")) == (
        "agent_unavailable"
    )
    assert SwarmSupervisor._dispatch_failure_reason(RuntimeError("boom")) == ("agent_launch_failed")

    lock = tmp_path / ".codex_session_active"
    lock.write_text("pid=123\nholder_pid=456\nppid=789\nworktree=/tmp/x\n", encoding="utf-8")
    assert SwarmSupervisor._parse_session_lock_pids(lock) == [123, 789]
