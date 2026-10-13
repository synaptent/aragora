"""Characterization tests that pin the full output of ``build_integrator_view``.

The fixture reaches every lane source (developer tasks, run work orders without a
task, worktree rows without a task, and merge-queue items without a task) plus branch
collisions, an expired lease, a scope violation, a salvage candidate and a recorded
integration decision. ``now`` and the ledger status are fixed and lane telemetry uses
an in-memory collector, so the output is deterministic. If a deliberate behavior change
moves the digest, update ``EXPECTED_DIGEST`` in the same change.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from aragora.swarm.lane_telemetry import LaneTelemetryCollector
from aragora.swarm.reporter import build_integrator_view

NOW = datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc)
EXPECTED_DIGEST = "78c37634c400a30ff8aed5d5184ba2c542086faf38575bf78515f973cec544fd"


def _at(minutes: int) -> str:
    return (NOW + timedelta(minutes=minutes)).isoformat()


def _fixture() -> dict[str, Any]:
    integrator_branch = "codex/integrator-lane"
    integrator_path = "/tmp/repo/.worktrees/integrator"
    return {
        "runs": [
            {
                "run_id": "run-1",
                "status": "active",
                "goal": "Ship the integrator lane",
                "work_orders": [
                    {
                        "work_order_id": "wo-1",
                        "title": "Build integrator lane",
                        "status": "completed",
                        "branch": integrator_branch,
                        "worktree_path": integrator_path,
                        "target_agent": "codex",
                        "reviewer_agent": "claude",
                    },
                    {
                        "work_order_id": "wo-2",
                        "title": "Retry the flaky lane",
                        "status": "needs_human",
                        "branch": "codex/flaky-lane",
                        "worktree_path": "/tmp/repo/.worktrees/flaky",
                        "target_agent": "claude",
                        "failure_reason": "worker_exited_without_receipt",
                    },
                ],
            }
        ],
        "worktrees": [
            {
                "session_id": "sess-1",
                "path": integrator_path,
                "branch": integrator_branch,
                "has_lock": True,
                "pid_alive": True,
                "agent": "codex",
                "last_activity": _at(-2),
            },
            {
                "session_id": "sess-orphan",
                "path": "/tmp/repo/.worktrees/orphan",
                "branch": "codex/orphan-lane",
                "has_lock": False,
                "pid_alive": False,
                "agent": "claude",
                "last_activity": _at(-600),
            },
        ],
        "claims": [
            {"session_id": "sess-1", "path": "aragora/swarm/reporter.py"},
            {"session_id": "sess-orphan", "path": "aragora/swarm/reporter.py"},
        ],
        "merge_queue": [
            {
                "id": "mq-1",
                "branch": integrator_branch,
                "session_id": "sess-1",
                "status": "needs_human",
                "metadata": {
                    "receipt_id": "rcpt-1",
                    "task_id": "wo-1",
                    "pr_url": "https://github.com/synaptent/aragora/pull/1051",
                    "pr_number": 1051,
                },
            },
            {
                "id": "mq-2",
                "branch": "codex/queue-only",
                "session_id": "sess-queue",
                "status": "queued",
                "metadata": {
                    "pr_url": "https://github.com/synaptent/aragora/pull/1052",
                    "head_sha": "queue-head",
                },
            },
        ],
        "coordination": {
            "counts": {"active_leases": 2, "fleet_merge_queue": 2},
            "scope_violations": [
                {
                    "lease_id": "lease-1",
                    "owner_session_id": "sess-1",
                    "branch": integrator_branch,
                    "paths": ["aragora/cli/main.py"],
                }
            ],
            "integrator": {
                "developer_tasks": [
                    {
                        "task_key": "run-1:wo-1",
                        "task_id": "wo-1",
                        "run_id": "run-1",
                        "goal": "Ship the integrator lane",
                        "title": "Build integrator lane",
                        "status": "completed",
                        "owner_agent": "codex",
                        "reviewer_agent": "claude",
                        "owner_session_id": "sess-1",
                        "branch": integrator_branch,
                        "worktree_path": integrator_path,
                        "lease_id": "lease-1",
                        "receipt_id": "rcpt-1",
                        "allowed_paths": ["aragora/swarm/reporter.py"],
                        "updated_at": _at(-3),
                    },
                    {
                        "task_key": "run-0:wo-old",
                        "task_id": "wo-old",
                        "run_id": "run-0",
                        "goal": "Old integrator attempt",
                        "title": "Old integrator attempt",
                        "status": "active",
                        "owner_agent": "codex",
                        "owner_session_id": "sess-old",
                        "branch": integrator_branch,
                        "lease_id": "lease-old",
                        "updated_at": _at(-300),
                    },
                ],
                "leases": [
                    {
                        "lease_id": "lease-1",
                        "task_id": "wo-1",
                        "owner_agent": "codex",
                        "owner_session_id": "sess-1",
                        "branch": integrator_branch,
                        "worktree_path": integrator_path,
                        "claimed_paths": ["aragora/swarm/reporter.py"],
                        "status": "completed",
                        "updated_at": _at(-4),
                        "expires_at": _at(120),
                        "metadata": {"task_key": "run-1:wo-1"},
                    },
                    {
                        "lease_id": "lease-old",
                        "task_id": "wo-old",
                        "owner_agent": "codex",
                        "owner_session_id": "sess-old",
                        "branch": integrator_branch,
                        "status": "active",
                        "updated_at": _at(-300),
                        "expires_at": _at(-60),
                    },
                ],
                "completion_receipts": [
                    {
                        "receipt_id": "rcpt-1",
                        "lease_id": "lease-1",
                        "task_id": "wo-1",
                        "owner_agent": "codex",
                        "owner_session_id": "sess-1",
                        "branch": integrator_branch,
                        "worktree_path": integrator_path,
                        "base_sha": "abc123base",
                        "head_sha": "def456head",
                        "commit_shas": ["def456head"],
                        "changed_paths": ["aragora/swarm/reporter.py"],
                        "confidence": 0.94,
                        "outcome": "deliverable_created",
                        "tests_run": ["python -m pytest tests/swarm/test_reporter.py -q"],
                        "risks": ["Need integrator review before merge"],
                        "created_at": _at(-5),
                        "metadata": {"task_key": "run-1:wo-1", "reviewer_agent": "claude"},
                        "pr_url": "https://github.com/synaptent/aragora/pull/1051",
                        "pr_number": 1051,
                    }
                ],
                "integration_decisions": [
                    {
                        "decision_id": "dec-1",
                        "lease_id": "lease-1",
                        "receipt_id": "rcpt-1",
                        "decision": "pending_review",
                        "target_branch": "main",
                        "rationale": "Awaiting integrator review",
                        "created_at": _at(-4),
                    }
                ],
                "salvage_candidates": [
                    {
                        "candidate_id": "salv-1",
                        "branch": "codex/orphan-lane",
                        "worktree_path": "/tmp/repo/.worktrees/orphan",
                        "status": "pending",
                        "reason": "dirty worktree",
                        "updated_at": _at(-30),
                    }
                ],
            },
        },
        "ledger_status": {
            "available": True,
            "current_queue_size": 2,
            "current_open_prs": 1,
            "current_boss_running": False,
            "current_merge_running": False,
            "current_benchmark_fresh": True,
            "prs_merged": 1,
            "pr_numbers_merged": [1049],
            "last_stop_reason": "queue_empty",
        },
        "now": NOW,
    }


def _payload() -> dict[str, Any]:
    with patch(
        "aragora.swarm.reporter._LANE_TELEMETRY", LaneTelemetryCollector(db_path=":memory:")
    ):
        return build_integrator_view(**_fixture())


def test_full_output_matches_the_pinned_digest() -> None:
    canonical = json.dumps(_payload(), sort_keys=True, default=str, indent=1)
    assert hashlib.sha256(canonical.encode()).hexdigest() == EXPECTED_DIGEST, canonical


def test_every_lane_source_produces_a_lane() -> None:
    payload = _payload()
    lanes = {
        lane["lane_id"]: (lane["source"], lane["merge_readiness"], lane["lane_health"])
        for lane in payload["lanes"]
    }
    assert lanes == {
        "run-0:wo-old": ("task", "blocked", "stalled"),
        "run-1:wo-1": ("task", "blocked", "blocked"),
        "wo-2": ("swarm", "blocked", "blocked"),
        "codex/orphan-lane": ("fleet", "blocked", "blocked"),
        "mq-2": ("merge_queue", "blocked", "blocked"),
    }
    summary = payload["summary"]
    assert (summary["total_lanes"], summary["canonical_lanes"], summary["orphan_lanes"]) == (
        5,
        2,
        3,
    )
    assert (summary["collision_lanes"], summary["scope_violation_lanes"]) == (3, 1)
    assert {name: len(items) for name, items in payload["alerts"].items() if items} == {
        "collisions": 3,
        "stalled_lanes": 1,
        "stale_heartbeats": 1,
        "orphan_lanes": 3,
        "needs_decision": 2,
        "missing_receipts": 1,
        "scope_violations": 1,
    }
