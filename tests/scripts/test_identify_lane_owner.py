"""Tests for ``scripts/identify_lane_owner.py`` — Phase A consolidator.

Fixture-driven; never calls the real ``agent_bridge`` subprocess and
never reads the live ``~/.codex/`` / ``~/.claude/`` / ``~/.factory/``
directories. All discovery sources are pointed at ``tmp_path``
fixtures so tests are deterministic and isolated.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_module() -> Any:
    here = Path(__file__).resolve()
    script_path = here.parents[2] / "scripts" / "identify_lane_owner.py"
    spec = importlib.util.spec_from_file_location("identify_lane_owner_under_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ilo = _load_module()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


SAMPLE_LANES: list[dict[str, Any]] = [
    {
        "lane_id": "P19-repair-7292-stage2-blockers",
        "owner_session": "codex-p19-repair-7292",
        "source": "codex",
        "status": "active",
        "branch": "droid/P16-stage2-auto-merge-bucket-a-20260518-002325",
        "worktree": "/private/tmp/p19-fixture-wt",
        "pr_number": 7292,
        "goal": "Repair #7292 Stage 2 auto-merge blockers",
        "updated_at": "2026-05-18T04:19:24Z",
    },
    {
        "lane_id": "P20-model-pins-frontier-aligned",
        "owner_session": "droid-F473CDBF",
        "source": "droid",
        "status": "active",
        "branch": "droid/P20-model-pins-frontier-aligned-20260518-041438",
        "worktree": "/private/tmp/p20-fixture-wt",
        "pr_number": None,
        "updated_at": "2026-05-18T04:14:38Z",
    },
    {
        "lane_id": "P28-with-rich-identity",
        "owner_session": "codex-test-rich",
        "source": "codex",
        "status": "active",
        "branch": "codex/with-identity",
        "worktree": "/private/tmp/p28-rich-wt",
        "pr_number": 9000,
        "codex_thread_id": "019e3942-e27e-7e72-b8d6-b61d981fd532",
        "codex_rollout_path": None,  # set per-test
        "desktop_label": "Test Codex Desktop Tab",
        "session_title": "Rich identity claim",
        "updated_at": "2026-05-18T04:30:00Z",
    },
]


def write_lane_registry(tmp_path: Path, lanes: list[dict[str, Any]] | None = None) -> Path:
    if lanes is None:
        lanes = SAMPLE_LANES
    registry_dir = tmp_path / ".aragora" / "agent-bridge"
    registry_dir.mkdir(parents=True, exist_ok=True)
    p = registry_dir / "lanes.json"
    p.write_text(json.dumps(lanes), encoding="utf-8")
    return p


def fake_snapshot_records(
    records: list[dict[str, Any]],
    *,
    by_role: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fake operator-snapshot payload matching the live contract."""

    return {"process_census": {"by_role": by_role or {}, "records": records}}


def test_default_state_root_prefers_local_lane_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worktree = tmp_path / "worktree"
    local_registry = worktree / ".aragora" / "agent-bridge" / "lanes.json"
    local_registry.parent.mkdir(parents=True)
    local_registry.write_text("[]", encoding="utf-8")

    def fail_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("git lookup should not run when local registry exists")

    monkeypatch.setattr(ilo.subprocess, "run", fail_run)

    assert ilo._default_state_root(worktree) == worktree / ".aragora"


def test_default_state_root_uses_git_common_dir_for_linked_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worktree = tmp_path / "linked" / "aragora"
    canonical = tmp_path / "main" / "aragora"
    worktree.mkdir(parents=True)
    canonical.mkdir(parents=True)

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, f"{canonical / '.git'}\n", "")

    monkeypatch.setattr(ilo.subprocess, "run", fake_run)

    assert ilo._default_state_root(worktree) == canonical / ".aragora"


def test_default_state_root_honors_automation_state_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state_root = tmp_path / "state-root"
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(state_root))

    assert ilo._default_state_root(tmp_path / "worktree") == state_root / ".aragora"


def test_json_output_includes_dev_coordination_lease_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = write_lane_registry(tmp_path)
    monkeypatch.setattr(ilo, "_default_snapshot_provider", lambda: None)
    monkeypatch.setattr(
        ilo,
        "_check_dev_coordination_lease",
        lambda lane, **_kwargs: {
            "status": "valid",
            "reason": None,
            "work_id": "pr:7292",
            "lease_id": "lease-7292",
            "owner_session_id": lane["owner_session"],
        },
        raising=False,
    )

    rc = ilo.main(
        [
            "--pr",
            "7292",
            "--json",
            "--registry-path",
            str(registry),
            "--codex-sessions-root",
            str(tmp_path / "no_codex"),
            "--claude-projects-root",
            str(tmp_path / "no_claude"),
            "--factory-bg-path",
            str(tmp_path / "no_factory.json"),
            "--steering-inbox-root",
            str(tmp_path / "no_steering"),
            "--heartbeat-path",
            str(tmp_path / "no_heartbeats.json"),
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dev_coordination_lease"] == {
        "status": "valid",
        "reason": None,
        "work_id": "pr:7292",
        "lease_id": "lease-7292",
        "owner_session_id": "codex-p19-repair-7292",
    }


# ---------------------------------------------------------------------------
# load_lane_records / find_lane
# ---------------------------------------------------------------------------


class TestLoadAndFind:
    def test_missing_registry_returns_empty_list(self, tmp_path: Path) -> None:
        assert ilo.load_lane_records(tmp_path / "nope.json") == []

    def test_unparseable_registry_returns_empty_list(self, tmp_path: Path) -> None:
        p = tmp_path / "lanes.json"
        p.write_text("not valid json {{{", encoding="utf-8")
        assert ilo.load_lane_records(p) == []

    def test_find_by_exact_lane_id(self) -> None:
        r = ilo.find_lane(SAMPLE_LANES, lane_id="P19-repair-7292-stage2-blockers")
        assert r is not None
        assert r["owner_session"] == "codex-p19-repair-7292"

    def test_find_by_exact_lane_id_preserves_registry_order(self) -> None:
        lanes = [
            {
                "lane_id": "duplicate-lane-id",
                "owner_session": "codex-original",
                "status": "released",
                "updated_at": "2026-05-18T04:00:00Z",
            },
            {
                "lane_id": "duplicate-lane-id",
                "owner_session": "codex-newer-active",
                "status": "active",
                "updated_at": "2026-05-18T05:00:00Z",
            },
        ]
        r = ilo.find_lane(lanes, lane_id="duplicate-lane-id")
        assert r is not None
        assert r["owner_session"] == "codex-original"

    def test_find_by_pr_number(self) -> None:
        r = ilo.find_lane(SAMPLE_LANES, pr=7292)
        assert r is not None
        assert r["lane_id"] == "P19-repair-7292-stage2-blockers"

    def test_find_by_pr_prefers_active_over_stale_history(self) -> None:
        lanes = [
            {
                "lane_id": "old-completed",
                "owner_session": "codex-old",
                "status": "completed",
                "pr_number": 7292,
                "updated_at": "2026-05-18T05:00:00Z",
            },
            {
                "lane_id": "current-active",
                "owner_session": "codex-current",
                "status": "active",
                "pr_number": 7292,
                "updated_at": "2026-05-18T04:00:00Z",
            },
        ]
        r = ilo.find_lane(lanes, pr=7292)
        assert r is not None
        assert r["lane_id"] == "current-active"

    def test_find_by_pr_uses_newest_historical_when_unowned(self) -> None:
        lanes = [
            {
                "lane_id": "older-completed",
                "owner_session": "codex-old",
                "status": "completed",
                "pr_number": 7292,
                "updated_at": "2026-05-18T04:00:00Z",
            },
            {
                "lane_id": "newer-released",
                "owner_session": "codex-new",
                "status": "released",
                "pr_number": 7292,
                "updated_at": "2026-05-18T05:00:00Z",
            },
        ]
        r = ilo.find_lane(lanes, pr=7292)
        assert r is not None
        assert r["lane_id"] == "newer-released"

    def test_find_by_pr_treats_expired_as_historical(self) -> None:
        lanes = [
            {
                "lane_id": "older-released",
                "owner_session": "codex-old",
                "status": "released",
                "pr_number": 7292,
                "updated_at": "2026-05-18T04:00:00Z",
            },
            {
                "lane_id": "newer-expired",
                "owner_session": "codex-expired",
                "status": "expired",
                "pr_number": 7292,
                "updated_at": "2026-05-18T05:00:00Z",
            },
        ]
        r = ilo.find_lane(lanes, pr=7292)
        assert r is not None
        assert r["lane_id"] == "newer-expired"


class TestHeartbeatSummary:
    def test_build_owner_info_includes_fresh_heartbeat(self, tmp_path: Path) -> None:
        heartbeat_path = tmp_path / "heartbeats.json"
        heartbeat_path.write_text(
            json.dumps(
                [
                    {
                        "schema_version": "aragora-agent-heartbeat/1.0",
                        "lane_id": "P19-repair-7292-stage2-blockers",
                        "owner_session": "codex-p19-repair-7292",
                        "pid": 1234,
                        "cwd": "/tmp/aragora",
                        "worktree": "/private/tmp/p19-fixture-wt",
                        "branch": "droid/P16-stage2-auto-merge-bucket-a-20260518-002325",
                        "pr_number": 7292,
                        "last_seen_at": "2026-05-22T00:05:00Z",
                    }
                ]
            ),
            encoding="utf-8",
        )

        info = ilo.build_owner_info(
            SAMPLE_LANES[0],
            snapshot_provider=lambda: None,
            sessions_root=tmp_path / "codex",
            projects_root=tmp_path / "claude",
            bg_path=tmp_path / "factory.json",
            steering_inbox_root=tmp_path / "steering",
            heartbeat_path=heartbeat_path,
            heartbeat_now="2026-05-22T00:10:00Z",
        )

        assert info.latest_heartbeat is not None
        assert info.latest_heartbeat["fresh"] is True
        assert info.latest_heartbeat["age_seconds"] == 300
        assert info.latest_heartbeat["pid"] == 1234
        assert info.latest_heartbeat["cwd"] == "/tmp/aragora"
        assert info.latest_heartbeat["worktree"] == "/private/tmp/p19-fixture-wt"
        assert (
            info.latest_heartbeat["branch"]
            == "droid/P16-stage2-auto-merge-bucket-a-20260518-002325"
        )
        assert info.latest_heartbeat["pr_number"] == 7292
        assert info.owner_state == "owned"
        assert info.liveness_state == "fresh_heartbeat"
        assert info.cleanup_state == "preserve_live_owner"
        assert info.recommended_operator_action == (
            "route work through owner_session; do not cleanup without owner release"
        )

    def test_build_owner_info_marks_stale_heartbeat(self, tmp_path: Path) -> None:
        heartbeat_path = tmp_path / "heartbeats.json"
        heartbeat_path.write_text(
            json.dumps(
                [
                    {
                        "lane_id": "P19-repair-7292-stage2-blockers",
                        "owner_session": "codex-p19-repair-7292",
                        "last_seen_at": "2026-05-22T00:00:00Z",
                    }
                ]
            ),
            encoding="utf-8",
        )

        info = ilo.build_owner_info(
            SAMPLE_LANES[0],
            snapshot_provider=lambda: None,
            sessions_root=tmp_path / "codex",
            projects_root=tmp_path / "claude",
            bg_path=tmp_path / "factory.json",
            steering_inbox_root=tmp_path / "steering",
            heartbeat_path=heartbeat_path,
            heartbeat_now="2026-05-22T00:20:00Z",
        )

        assert info.latest_heartbeat is not None
        assert info.latest_heartbeat["fresh"] is False
        assert info.latest_heartbeat["age_seconds"] == 1200
        assert info.owner_state == "owned"
        assert info.liveness_state == "stale_heartbeat"
        assert info.cleanup_state == "preserve_stale_owner"
        assert info.recommended_operator_action == (
            "preserve; refresh heartbeat or contact owner before mutation or cleanup"
        )

    def test_build_owner_info_prefers_claimed_owner_heartbeat(self, tmp_path: Path) -> None:
        heartbeat_path = tmp_path / "heartbeats.json"
        heartbeat_path.write_text(
            json.dumps(
                [
                    {
                        "lane_id": "P19-repair-7292-stage2-blockers",
                        "owner_session": "other-owner",
                        "branch": "droid/P16-stage2-auto-merge-bucket-a-20260518-002325",
                        "pr_number": 7292,
                        "last_seen_at": "2026-05-22T00:10:00Z",
                    },
                    {
                        "lane_id": "P19-repair-7292-stage2-blockers",
                        "owner_session": "codex-p19-repair-7292",
                        "branch": "droid/P16-stage2-auto-merge-bucket-a-20260518-002325",
                        "pr_number": 7292,
                        "last_seen_at": "2026-05-22T00:05:00Z",
                    },
                ]
            ),
            encoding="utf-8",
        )

        info = ilo.build_owner_info(
            SAMPLE_LANES[0],
            snapshot_provider=lambda: None,
            sessions_root=tmp_path / "codex",
            projects_root=tmp_path / "claude",
            bg_path=tmp_path / "factory.json",
            steering_inbox_root=tmp_path / "steering",
            heartbeat_path=heartbeat_path,
            heartbeat_now="2026-05-22T00:20:00Z",
        )

        assert info.latest_heartbeat is not None
        assert info.latest_heartbeat["owner_session"] == "codex-p19-repair-7292"
        assert info.latest_heartbeat["age_seconds"] == 900

    def test_build_owner_info_requires_target_lane_heartbeat(self, tmp_path: Path) -> None:
        heartbeat_path = tmp_path / "heartbeats.json"
        heartbeat_path.write_text(
            json.dumps(
                [
                    {
                        "lane_id": "other-lane",
                        "owner_session": "codex-p19-repair-7292",
                        "last_seen_at": "2026-05-22T00:10:00Z",
                    },
                    {
                        "lane_id": "P19-repair-7292-stage2-blockers",
                        "owner_session": "codex-p19-repair-7292",
                        "last_seen_at": "2026-05-22T00:00:00Z",
                    },
                ]
            ),
            encoding="utf-8",
        )

        info = ilo.build_owner_info(
            SAMPLE_LANES[0],
            snapshot_provider=lambda: None,
            sessions_root=tmp_path / "codex",
            projects_root=tmp_path / "claude",
            bg_path=tmp_path / "factory.json",
            steering_inbox_root=tmp_path / "steering",
            heartbeat_path=heartbeat_path,
            heartbeat_now="2026-05-22T00:20:00Z",
        )

        assert info.latest_heartbeat is not None
        assert info.latest_heartbeat["lane_id"] == "P19-repair-7292-stage2-blockers"
        assert info.latest_heartbeat["age_seconds"] == 1200

    def test_find_by_pr_prefers_conflict_over_newer_released_history(self) -> None:
        lanes = [
            {
                "lane_id": "newer-released",
                "owner_session": "codex-released",
                "status": "released",
                "pr_number": 7292,
                "updated_at": "2026-05-18T05:00:00Z",
            },
            {
                "lane_id": "older-conflict",
                "owner_session": "codex-conflict",
                "status": "conflict",
                "pr_number": 7292,
                "updated_at": "2026-05-18T04:00:00Z",
            },
        ]
        r = ilo.find_lane(lanes, pr=7292)
        assert r is not None
        assert r["lane_id"] == "older-conflict"

    def test_find_by_pr_treats_bad_or_missing_updated_at_as_oldest(self) -> None:
        lanes = [
            {
                "lane_id": "bad-time",
                "owner_session": "codex-bad",
                "status": "released",
                "pr_number": 7292,
                "updated_at": "not-a-timestamp",
            },
            {
                "lane_id": "missing-time",
                "owner_session": "codex-missing",
                "status": "released",
                "pr_number": 7292,
            },
            {
                "lane_id": "valid-time",
                "owner_session": "codex-valid",
                "status": "completed",
                "pr_number": 7292,
                "updated_at": "2026-05-18T04:00:00Z",
            },
        ]
        r = ilo.find_lane(lanes, pr=7292)
        assert r is not None
        assert r["lane_id"] == "valid-time"

    def test_find_by_branch(self) -> None:
        r = ilo.find_lane(
            SAMPLE_LANES, branch="droid/P20-model-pins-frontier-aligned-20260518-041438"
        )
        assert r is not None
        assert r["lane_id"] == "P20-model-pins-frontier-aligned"

    def test_find_by_branch_uses_duplicate_lane_ranking(self) -> None:
        lanes = [
            {
                "lane_id": "newer-released",
                "owner_session": "codex-released",
                "status": "released",
                "branch": "codex/shared-branch",
                "updated_at": "2026-05-18T05:00:00Z",
            },
            {
                "lane_id": "older-conflict",
                "owner_session": "codex-conflict",
                "status": "conflict",
                "branch": "codex/shared-branch",
                "updated_at": "2026-05-18T04:00:00Z",
            },
        ]
        r = ilo.find_lane(lanes, branch="codex/shared-branch")
        assert r is not None
        assert r["lane_id"] == "older-conflict"

    def test_find_by_worktree_uses_duplicate_lane_ranking(self) -> None:
        lanes = [
            {
                "lane_id": "older-released",
                "owner_session": "codex-released",
                "status": "released",
                "worktree": "/private/tmp/shared-worktree",
                "updated_at": "2026-05-18T05:00:00Z",
            },
            {
                "lane_id": "current-active",
                "owner_session": "codex-active",
                "status": "active",
                "worktree": "/private/tmp/shared-worktree",
                "updated_at": "2026-05-18T04:00:00Z",
            },
        ]
        r = ilo.find_lane(lanes, worktree="/private/tmp/shared-worktree/")
        assert r is not None
        assert r["lane_id"] == "current-active"

    def test_find_by_worktree_path_normalised(self) -> None:
        # Trailing-slash variant must match the registry's path.
        r = ilo.find_lane(SAMPLE_LANES, worktree="/private/tmp/p19-fixture-wt/")
        assert r is not None
        assert r["lane_id"] == "P19-repair-7292-stage2-blockers"

    def test_find_by_worktree_exact(self) -> None:
        r = ilo.find_lane(SAMPLE_LANES, worktree="/private/tmp/p19-fixture-wt")
        assert r is not None
        assert r["lane_id"] == "P19-repair-7292-stage2-blockers"

    def test_no_match_returns_none(self) -> None:
        assert ilo.find_lane(SAMPLE_LANES, lane_id="does-not-exist") is None
        assert ilo.find_lane(SAMPLE_LANES, pr=999999) is None
        assert ilo.find_lane(SAMPLE_LANES, branch="unknown") is None
        assert ilo.find_lane(SAMPLE_LANES, worktree="/nowhere") is None


# ---------------------------------------------------------------------------
# lookup_live_process
# ---------------------------------------------------------------------------


class TestLookupLiveProcess:
    def test_matches_codex_cli_pid_by_cwd(self) -> None:
        lane = {"worktree": "/private/tmp/p19-fixture-wt"}
        snap = fake_snapshot_records(
            [
                {"pid": 12345, "role": "codex_cli", "cwd": "/private/tmp/p19-fixture-wt"},
                {"pid": 12346, "role": "codex_cli", "cwd": "/elsewhere"},
                {"pid": 22222, "role": "claude_code", "cwd": "/another/dir"},
            ],
            by_role={"codex_cli": 2, "claude_code": 1},
        )
        r = ilo.lookup_live_process(lane, snapshot_provider=lambda: snap)
        assert r["found"] is True
        assert r["pid"] == 12345
        assert r["family"] == "codex_cli"

    def test_no_worktree_returns_not_found(self) -> None:
        r = ilo.lookup_live_process({}, snapshot_provider=lambda: fake_snapshot_records([]))
        assert r["found"] is False
        assert "no worktree" in r["reason"]

    def test_snapshot_unavailable_returns_not_found(self) -> None:
        r = ilo.lookup_live_process({"worktree": "/x"}, snapshot_provider=lambda: None)
        assert r["found"] is False
        assert "snapshot unavailable" in r["reason"]

    def test_no_process_match_returns_not_found(self) -> None:
        lane = {"worktree": "/private/tmp/nope"}
        snap = fake_snapshot_records(
            [{"pid": 1, "role": "codex_cli", "cwd": "/elsewhere"}],
            by_role={"codex_cli": 1},
        )
        r = ilo.lookup_live_process(lane, snapshot_provider=lambda: snap)
        assert r["found"] is False
        assert "no process_census entry matched" in r["reason"]

    def test_real_snapshot_shape_without_cwd_fails_closed(self) -> None:
        lane = {"worktree": "/private/tmp/shared-wt"}
        snap = fake_snapshot_records(
            [
                {
                    "pid": 11111,
                    "role": "claude_code",
                    "elapsed": "00:01:00",
                    "summary": "Claude Code local session process",
                },
                {
                    "pid": 22222,
                    "role": "codex_cli",
                    "elapsed": "00:02:00",
                    "summary": "Codex CLI session process",
                },
            ],
            by_role={"claude_code": 1, "codex_cli": 1},
        )
        r = ilo.lookup_live_process(lane, snapshot_provider=lambda: snap)
        assert r["found"] is False
        assert "no cwd-bearing process records" in r["reason"]

    def test_real_summary_snapshot_shape_without_records_fails_closed(self) -> None:
        lane = {"worktree": "/private/tmp/shared-wt"}
        snap = {"process_census": {"by_role": {"claude_code": 1, "codex_cli": 1}}}
        r = ilo.lookup_live_process(lane, snapshot_provider=lambda: snap)
        assert r["found"] is False
        assert "no cwd-bearing process records" in r["reason"]

    def test_multiple_families_same_worktree_uses_lane_source(self) -> None:
        lane = {"source": "claude", "worktree": "/private/tmp/shared-wt"}
        snap = fake_snapshot_records(
            [
                {"pid": 11111, "role": "codex_cli", "cwd": "/private/tmp/shared-wt"},
                {"pid": 22222, "role": "claude_code", "cwd": "/private/tmp/shared-wt"},
            ],
            by_role={"codex_cli": 1, "claude_code": 1},
        )
        r = ilo.lookup_live_process(lane, snapshot_provider=lambda: snap)
        assert r["found"] is True
        assert r["pid"] == 22222
        assert r["family"] == "claude_code"
        assert "disambiguated" in r["matched_via"]

    def test_multiple_families_same_worktree_uses_owner_session_family(self) -> None:
        lane = {"owner_session": "droid-ABC12345", "worktree": "/private/tmp/shared-wt"}
        snap = fake_snapshot_records(
            [
                {"pid": 11111, "role": "codex_cli", "cwd": "/private/tmp/shared-wt"},
                {"pid": 33333, "role": "factory_droid", "cwd": "/private/tmp/shared-wt"},
            ],
            by_role={"codex_cli": 1, "factory_droid": 1},
        )
        r = ilo.lookup_live_process(lane, snapshot_provider=lambda: snap)
        assert r["found"] is True
        assert r["pid"] == 33333
        assert r["family"] == "factory_droid"

    def test_multiple_families_same_worktree_without_hint_fails_closed(self) -> None:
        lane = {"worktree": "/private/tmp/shared-wt"}
        snap = fake_snapshot_records(
            [
                {"pid": 11111, "role": "codex_cli", "cwd": "/private/tmp/shared-wt"},
                {"pid": 22222, "role": "claude_code", "cwd": "/private/tmp/shared-wt"},
            ],
            by_role={"codex_cli": 1, "claude_code": 1},
        )
        r = ilo.lookup_live_process(lane, snapshot_provider=lambda: snap)
        assert r["found"] is False
        assert "ambiguous_same_worktree" in r["reason"]
        assert [m["family"] for m in r["matches"]] == ["claude_code", "codex_cli"]

    def test_multiple_hinted_matches_same_worktree_fails_closed(self) -> None:
        lane = {"source": "codex", "worktree": "/private/tmp/shared-wt"}
        snap = fake_snapshot_records(
            [
                {"pid": 44444, "role": "codex_app_server", "cwd": "/private/tmp/shared-wt"},
                {"pid": 11111, "role": "codex_cli", "cwd": "/private/tmp/shared-wt"},
            ],
            by_role={"codex_app_server": 1, "codex_cli": 1},
        )
        r = ilo.lookup_live_process(lane, snapshot_provider=lambda: snap)
        assert r["found"] is False
        assert "ambiguous_same_worktree" in r["reason"]
        assert "still matched 2 entries" in r["reason"]


# ---------------------------------------------------------------------------
# lookup_codex_thread
# ---------------------------------------------------------------------------


class TestLookupCodexThread:
    def _make_rollout(self, sessions_root: Path, thread_id: str, body: str = "") -> Path:
        # Filename convention: rollout-YYYY-MM-DDTHH-MM-SS-<thread_id>.jsonl
        day_dir = sessions_root / "2026" / "05" / "18"
        day_dir.mkdir(parents=True, exist_ok=True)
        p = day_dir / f"rollout-2026-05-18T04-37-00-{thread_id}.jsonl"
        p.write_text(body or '{"event": "noop"}\n', encoding="utf-8")
        return p

    def test_exact_match_via_codex_rollout_path(self, tmp_path: Path) -> None:
        sessions_root = tmp_path / "codex_sessions"
        p = self._make_rollout(sessions_root, "abcd1234")
        lane = {"codex_rollout_path": str(p), "worktree": "/anywhere"}
        r = ilo.lookup_codex_thread(lane, sessions_root=sessions_root)
        assert r["found"] is True
        assert r["matched_via"] == "lane.codex_rollout_path (exact)"
        assert r["thread_id"] == "abcd1234"

    def test_exact_match_via_codex_thread_id_filename(self, tmp_path: Path) -> None:
        sessions_root = tmp_path / "codex_sessions"
        thread_id = "019e3942-e27e-7e72-b8d6-b61d981fd532"
        self._make_rollout(sessions_root, thread_id)
        lane = {"codex_thread_id": thread_id, "worktree": "/anywhere"}
        r = ilo.lookup_codex_thread(lane, sessions_root=sessions_root)
        assert r["found"] is True
        assert "exact filename match" in r["matched_via"]
        assert r["thread_id"] == thread_id

    def test_fuzzy_match_via_worktree_in_rollout_body(self, tmp_path: Path) -> None:
        sessions_root = tmp_path / "codex_sessions"
        wt = "/private/tmp/p19-fuzzy-target"
        body = '{"event":"tool_call","cwd":"' + wt + '","payload":"..."}\n'
        p = self._make_rollout(sessions_root, "ffff0000", body=body)
        lane = {"worktree": wt}
        r = ilo.lookup_codex_thread(
            lane,
            sessions_root=sessions_root,
            now=p.stat().st_mtime + 60,  # within freshness window
        )
        assert r["found"] is True
        assert "fuzzy" in r["matched_via"]
        assert r["thread_id"] == "ffff0000"

    def test_fuzzy_no_recent_match(self, tmp_path: Path) -> None:
        sessions_root = tmp_path / "codex_sessions"
        wt = "/private/tmp/p19-fuzzy-target"
        p = self._make_rollout(sessions_root, "ffff0001", body=f"cwd:{wt}\n")
        lane = {"worktree": wt}
        # Set now far in the future so the rollout is outside the fuzzy window.
        future_now = p.stat().st_mtime + (10 * 60 * 60)  # 10h later
        r = ilo.lookup_codex_thread(
            lane,
            sessions_root=sessions_root,
            now=future_now,
            fuzzy_max_age_seconds=60,
        )
        assert r["found"] is False
        assert "no recent codex rollout" in r["reason"]

    def test_missing_sessions_root(self, tmp_path: Path) -> None:
        r = ilo.lookup_codex_thread({"worktree": "/x"}, sessions_root=tmp_path / "nope")
        assert r["found"] is False
        assert "sessions root absent" in r["reason"]


# ---------------------------------------------------------------------------
# lookup_claude_session
# ---------------------------------------------------------------------------


class TestLookupClaudeSession:
    def test_finds_session_by_worktree_encoding(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "claude_projects"
        cwd = "/Users/armand/Development/aragora/.worktrees/codex-auto/foo"
        # Claude encodes '/' → '-' and prefixes with a leading '-'.
        encoded = ilo._encode_cwd_for_claude(cwd)
        project_dir = projects_root / encoded
        project_dir.mkdir(parents=True)
        # Two sessions; lookup should return the most-recent.
        older = project_dir / "old-uuid-1111.jsonl"
        older.write_text('{"event":"a"}\n', encoding="utf-8")
        import os as _os
        import time as _time

        _os.utime(older, (_time.time() - 1000, _time.time() - 1000))
        newer = project_dir / "new-uuid-2222.jsonl"
        newer.write_text('{"event":"b"}\n', encoding="utf-8")
        lane = {"worktree": cwd}
        r = ilo.lookup_claude_session(lane, projects_root=projects_root)
        assert r["found"] is True
        assert r["session_uuid"] == "new-uuid-2222"
        assert "most-recent" in r["matched_via"]

    def test_no_matching_project_dir(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "claude_projects"
        projects_root.mkdir()
        lane = {"worktree": "/nowhere/expected"}
        r = ilo.lookup_claude_session(lane, projects_root=projects_root)
        assert r["found"] is False
        assert "no claude project dir matched" in r["reason"]

    def test_project_dir_with_no_session_files(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "claude_projects"
        cwd = "/Users/armand/Development/aragora"
        encoded = ilo._encode_cwd_for_claude(cwd)
        (projects_root / encoded).mkdir(parents=True)
        # No .jsonl files inside.
        r = ilo.lookup_claude_session({"worktree": cwd}, projects_root=projects_root)
        assert r["found"] is False
        assert "no .jsonl session files" in r["reason"]


# ---------------------------------------------------------------------------
# lookup_factory_droid
# ---------------------------------------------------------------------------


class TestLookupFactoryDroid:
    def test_matches_by_branch(self, tmp_path: Path) -> None:
        bg = tmp_path / "background-processes.json"
        bg.write_text(
            json.dumps(
                [
                    {"id": "p1", "branch": "droid/X-1"},
                    {"id": "p2", "branch": "droid/X-2"},
                ]
            ),
            encoding="utf-8",
        )
        lane = {"branch": "droid/X-2"}
        r = ilo.lookup_factory_droid(lane, bg_path=bg)
        assert r["found"] is True
        assert r["process_id"] == "p2"
        assert "branch" in r["matched_via"]

    def test_matches_by_worktree(self, tmp_path: Path) -> None:
        bg = tmp_path / "background-processes.json"
        bg.write_text(
            json.dumps(
                {
                    "processes": [
                        {"id": "p9", "worktree": "/some/where/X"},
                        {"id": "p10", "cwd": "/private/tmp/target"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        lane = {"worktree": "/private/tmp/target"}
        r = ilo.lookup_factory_droid(lane, bg_path=bg)
        assert r["found"] is True
        assert r["process_id"] == "p10"

    def test_missing_file(self, tmp_path: Path) -> None:
        r = ilo.lookup_factory_droid({"branch": "x"}, bg_path=tmp_path / "absent.json")
        assert r["found"] is False
        assert "absent" in r["reason"]


# ---------------------------------------------------------------------------
# steering_inbox_for
# ---------------------------------------------------------------------------


class TestSteeringInbox:
    def test_missing_inbox_dir_returns_zero_count(self, tmp_path: Path) -> None:
        path, count, receipt_summary = ilo.steering_inbox_for(
            "nobody-1", root=tmp_path / "steering"
        )
        assert count == 0
        assert path == tmp_path / "steering" / "nobody-1"
        assert receipt_summary["read_receipt_count"] == 0
        assert receipt_summary["unread_message_count"] == 0
        assert receipt_summary["latest_read_receipt"] is None

    def test_counts_only_dot_json_files(self, tmp_path: Path) -> None:
        inbox = tmp_path / "steering" / "claude-X"
        inbox.mkdir(parents=True)
        (inbox / "msg-a.json").write_text("{}", encoding="utf-8")
        (inbox / "msg-b.json").write_text("{}", encoding="utf-8")
        (inbox / "README.md").write_text("docs only", encoding="utf-8")
        path, count, receipt_summary = ilo.steering_inbox_for(
            "claude-X", root=tmp_path / "steering"
        )
        assert count == 2
        assert path == inbox
        assert receipt_summary["read_receipt_count"] == 0
        assert receipt_summary["unread_message_count"] == 2
        assert receipt_summary["latest_read_receipt"] is None

    def test_summarizes_read_receipts_without_changing_pending_count(self, tmp_path: Path) -> None:
        inbox = tmp_path / "steering" / "claude-X"
        receipts = inbox / "_read_receipts"
        receipts.mkdir(parents=True)
        (inbox / "msg-a.json").write_text(
            json.dumps(
                {
                    "schema_version": "aragora-operator-steering/1.0",
                    "message_sha256": "aaa",
                    "sent_at_utc": "2026-05-18T01:00:00.000Z",
                }
            ),
            encoding="utf-8",
        )
        (inbox / "msg-b.json").write_text(
            json.dumps(
                {
                    "schema_version": "aragora-operator-steering/1.0",
                    "message_sha256": "bbb",
                    "sent_at_utc": "2026-05-18T02:00:00.000Z",
                }
            ),
            encoding="utf-8",
        )
        (receipts / "receipt-a.json").write_text(
            json.dumps(
                {
                    "schema_version": "aragora-operator-steering-read-receipt/1.0",
                    "owner_session": "claude-X",
                    "read_by_session": "reader",
                    "read_at_utc": "2026-05-18T03:00:00.000Z",
                    "message_filename": "msg-a.json",
                    "message_sha256": "aaa",
                    "outcome": "stale",
                    "subject": "msg-a",
                }
            ),
            encoding="utf-8",
        )

        path, count, receipt_summary = ilo.steering_inbox_for(
            "claude-X", root=tmp_path / "steering"
        )

        assert path == inbox
        assert count == 2
        assert receipt_summary["read_receipt_count"] == 1
        assert receipt_summary["unread_message_count"] == 1
        assert receipt_summary["latest_read_receipt"]["message_filename"] == "msg-a.json"
        assert receipt_summary["latest_read_receipt"]["outcome"] == "stale"


# ---------------------------------------------------------------------------
# build_owner_info (composition)
# ---------------------------------------------------------------------------


class TestBuildOwnerInfo:
    def test_composes_all_fields_for_rich_identity_lane(self, tmp_path: Path) -> None:
        # Sources are all tmp dirs so lookups are deterministic.
        sessions_root = tmp_path / "codex_sessions"
        projects_root = tmp_path / "claude_projects"
        bg = tmp_path / "factory_bg.json"
        bg.write_text("[]", encoding="utf-8")
        lane = dict(SAMPLE_LANES[2])  # P28-with-rich-identity
        info = ilo.build_owner_info(
            lane,
            snapshot_provider=lambda: fake_snapshot_records([]),
            sessions_root=sessions_root,
            projects_root=projects_root,
            bg_path=bg,
            steering_inbox_root=tmp_path / "steering",
        )
        assert info.lane_id == "P28-with-rich-identity"
        assert info.owner_session == "codex-test-rich"
        assert info.codex_thread_id == "019e3942-e27e-7e72-b8d6-b61d981fd532"
        assert info.desktop_label == "Test Codex Desktop Tab"
        assert info.session_title == "Rich identity claim"
        assert info.live_prompt_dispatchable is True
        assert info.mailbox_dispatchable is True
        assert info.pending_message_count == 0
        assert info.read_receipt_count == 0
        assert info.unread_message_count == 0
        assert info.latest_read_receipt is None
        # Live lookups all return found=False because tmp dirs are empty.
        assert info.live_process["found"] is False
        assert info.claude_session["found"] is False
        assert info.factory_droid["found"] is False
        assert info.owner_state == "owned"
        assert info.liveness_state == "missing_heartbeat"
        assert info.cleanup_state == "preserve_unverified_owner"
        assert info.owner_state_reason == "active lane has no heartbeat evidence"

    def test_contact_metadata_surfaces_and_controls_dispatch_split(self, tmp_path: Path) -> None:
        bg = tmp_path / "factory_bg.json"
        bg.write_text("[]", encoding="utf-8")
        lane = {
            "lane_id": "tmux-lane",
            "owner_session": "codex-tmux",
            "status": "active",
            "contact_method": "tmux:aragora:2",
            "contact_payload": {"target": "aragora:2"},
            "last_mailbox_check_at": "2026-05-20T01:00:00Z",
            "last_delivery_at": "2026-05-20T01:01:00Z",
            "last_ack_at": "2026-05-20T01:02:00Z",
        }

        info = ilo.build_owner_info(
            lane,
            snapshot_provider=lambda: fake_snapshot_records([]),
            sessions_root=tmp_path / "codex_sessions",
            projects_root=tmp_path / "claude_projects",
            bg_path=bg,
            steering_inbox_root=tmp_path / "steering",
        )

        assert info.contact_method == "tmux:aragora:2"
        assert info.contact_payload == {"target": "aragora:2"}
        assert info.last_mailbox_check_at == "2026-05-20T01:00:00Z"
        assert info.last_delivery_at == "2026-05-20T01:01:00Z"
        assert info.last_ack_at == "2026-05-20T01:02:00Z"
        assert info.mailbox_dispatchable is True
        assert info.live_prompt_dispatchable is True

    def test_owner_state_marks_conflict_as_duplicate_preserve(self, tmp_path: Path) -> None:
        bg = tmp_path / "factory_bg.json"
        bg.write_text("[]", encoding="utf-8")
        lane = {
            "lane_id": "duplicate-lane",
            "owner_session": "codex-conflict",
            "status": "conflict",
            "worktree": "/tmp/duplicate-worktree",
        }

        info = ilo.build_owner_info(
            lane,
            snapshot_provider=lambda: fake_snapshot_records([]),
            sessions_root=tmp_path / "codex_sessions",
            projects_root=tmp_path / "claude_projects",
            bg_path=bg,
            steering_inbox_root=tmp_path / "steering",
        )

        assert info.owner_state == "duplicate"
        assert info.liveness_state == "missing_heartbeat"
        assert info.cleanup_state == "preserve_duplicate_owner"
        assert info.dispatchable is False
        assert info.recommended_operator_action == (
            "resolve the lane conflict before mutation or cleanup"
        )

    def test_owner_state_marks_completed_lane_as_stale_historical(self, tmp_path: Path) -> None:
        bg = tmp_path / "factory_bg.json"
        bg.write_text("[]", encoding="utf-8")
        lane = {
            "lane_id": "completed-lane",
            "owner_session": "codex-finished",
            "status": "completed",
            "worktree": "/tmp/completed-worktree",
        }

        info = ilo.build_owner_info(
            lane,
            snapshot_provider=lambda: fake_snapshot_records([]),
            sessions_root=tmp_path / "codex_sessions",
            projects_root=tmp_path / "claude_projects",
            bg_path=bg,
            steering_inbox_root=tmp_path / "steering",
        )

        assert info.owner_state == "stale"
        assert info.liveness_state == "missing_heartbeat"
        assert info.cleanup_state == "historical_requires_cleanup_inspect"
        assert info.dispatchable is False
        assert info.owner_state_reason == "lane status is completed"
        assert info.recommended_operator_action == (
            "treat as historical; run fresh cleanup inspection before any deletion"
        )

    def test_owner_state_marks_expired_lane_as_stale_historical(self, tmp_path: Path) -> None:
        bg = tmp_path / "factory_bg.json"
        bg.write_text("[]", encoding="utf-8")
        lane = {
            "lane_id": "expired-lane",
            "owner_session": "codex-expired",
            "status": "expired",
            "worktree": "/tmp/expired-worktree",
        }

        info = ilo.build_owner_info(
            lane,
            snapshot_provider=lambda: fake_snapshot_records([]),
            sessions_root=tmp_path / "codex_sessions",
            projects_root=tmp_path / "claude_projects",
            bg_path=bg,
            steering_inbox_root=tmp_path / "steering",
        )

        assert info.owner_state == "stale"
        assert info.liveness_state == "missing_heartbeat"
        assert info.cleanup_state == "historical_requires_cleanup_inspect"
        assert info.dispatchable is False
        assert (
            info.dispatch_blocker == "lane status is expired; claim an active lane before steering"
        )
        assert info.owner_state_reason == "lane status is expired"


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


class TestMainCLI:
    def _cli_args(self, registry: Path, tmp_path: Path) -> list[str]:
        return [
            "--registry-path",
            str(registry),
            "--codex-sessions-root",
            str(tmp_path / "no_codex"),
            "--claude-projects-root",
            str(tmp_path / "no_claude"),
            "--factory-bg-path",
            str(tmp_path / "no_factory.json"),
            "--steering-inbox-root",
            str(tmp_path / "no_steering"),
        ]

    def test_no_criteria_exits_2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        registry = write_lane_registry(tmp_path)
        rc = ilo.main(self._cli_args(registry, tmp_path))
        assert rc == 2
        assert "at least one of" in capsys.readouterr().err

    def test_missing_registry_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = ilo.main(
            [
                "--lane-id",
                "P19-repair-7292-stage2-blockers",
                "--registry-path",
                str(tmp_path / "absent.json"),
            ]
        )
        assert rc == 2
        assert "lane registry empty or missing" in capsys.readouterr().err

    def test_no_match_exits_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        registry = write_lane_registry(tmp_path)
        rc = ilo.main(["--lane-id", "does-not-exist", *self._cli_args(registry, tmp_path)])
        assert rc == 1
        assert "no lane matched" in capsys.readouterr().err

    def test_happy_path_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        registry = write_lane_registry(tmp_path)
        rc = ilo.main(
            [
                "--pr",
                "7292",
                "--json",
                *self._cli_args(registry, tmp_path),
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["lane_id"] == "P19-repair-7292-stage2-blockers"
        assert data["owner_session"] == "codex-p19-repair-7292"
        assert data["pr_number"] == 7292
        assert data["live_process"]["found"] is False  # no snapshot integration in CLI default path
        assert data["pending_message_count"] == 0
        assert data["read_receipt_count"] == 0
        assert data["unread_message_count"] == 0
        assert data["latest_read_receipt"] is None
        assert data["dispatchable"] is True
        assert data["dispatch_blocker"] is None
        assert data["harness_confidence"] == "mailbox_only"
        assert "send_operator_steering.py --to codex-p19-repair-7292" in data["steering_command"]

    def test_completed_lane_reports_mailbox_only_but_not_dispatchable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = write_lane_registry(
            tmp_path,
            [
                {
                    "lane_id": "q25-finished",
                    "owner_session": "codex-finished",
                    "source": "codex",
                    "status": "released",
                    "branch": "codex/finished",
                    "worktree": "/tmp/finished",
                    "pr_number": 7370,
                    "updated_at": "2026-05-19T17:49:14Z",
                }
            ],
        )

        rc = ilo.main(["--pr", "7370", "--json", *self._cli_args(registry, tmp_path)])

        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["owner_session"] == "codex-finished"
        assert data["dispatchable"] is False
        assert data["dispatch_blocker"] == (
            "lane status is released; claim an active lane before steering"
        )
        assert data["steering_command"] is None
        assert data["harness_confidence"] == "mailbox_only"

    def test_happy_path_human(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        registry = write_lane_registry(tmp_path)
        rc = ilo.main(
            [
                "--branch",
                "droid/P20-model-pins-frontier-aligned-20260518-041438",
                *self._cli_args(registry, tmp_path),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "lane_id:" in out
        assert "P20-model-pins-frontier-aligned" in out
        assert "owner_session:" in out
        assert "droid-F473CDBF" in out


# ---------------------------------------------------------------------------
# Encoding helper
# ---------------------------------------------------------------------------


class TestEncodeCwdForClaude:
    def test_basic_encoding(self) -> None:
        assert ilo._encode_cwd_for_claude("/Users/x") == "-Users-x"

    def test_trailing_slash_stripped(self) -> None:
        assert ilo._encode_cwd_for_claude("/Users/x/") == ilo._encode_cwd_for_claude("/Users/x")

    def test_no_leading_slash_gets_dash(self) -> None:
        assert ilo._encode_cwd_for_claude("rel/path") == "-rel-path"


# ---------------------------------------------------------------------------
# Owner-lease liveness + stale-claim advisory (issue #8318)
# ---------------------------------------------------------------------------


LIVENESS_NOW = "2026-06-13T12:00:00Z"


def _liveness_now() -> Any:
    return ilo._parse_iso_utc(LIVENESS_NOW)


def _hours_ago(hours: float) -> str:
    from datetime import timedelta

    return (_liveness_now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _stale_worktree_lane(
    tmp_path: Path,
    *,
    branch: str = "codex/stale-owner",
    desired_head: str = "a" * 40,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    worktree = tmp_path / "missing-owner-worktree"
    lane = {
        "lane_id": "Q-stale-worktree",
        "owner_session": "codex-q-stale",
        "status": "active",
        "branch": branch,
        "worktree": str(worktree),
        "desired_head_sha": desired_head,
        "updated_at": _hours_ago(7.0),
    }
    ledger = {
        "lane": "Q-stale-worktree",
        "status": "in_progress",
        "launched_at": _hours_ago(7.0),
    }
    return lane, ledger, worktree


def write_lane_ledger(tmp_path: Path, entries: list[dict[str, Any]]) -> str:
    """Write lane-ledger fixtures in the lane_janitor layout; return runs glob."""

    lanes_dir = tmp_path / ".aragora" / "run-20260613-liveness" / "lanes"
    lanes_dir.mkdir(parents=True, exist_ok=True)
    for i, entry in enumerate(entries):
        name = str(entry.get("lane") or f"lane-{i}")
        (lanes_dir / f"{name}.json").write_text(json.dumps(entry), encoding="utf-8")
    return str(tmp_path / ".aragora" / "run-*" / "lanes")


def write_preservation_outbox(
    tmp_path: Path,
    *,
    lane_id: str,
    branch: str,
    desired_head_sha: str,
) -> Path:
    outbox = tmp_path / ".aragora" / "automation-outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    path = outbox / f"open-pr-{branch.replace('/', '-')}-{desired_head_sha[:8]}.json"
    path.write_text(
        json.dumps(
            {
                "lane_id": lane_id,
                "branch": branch,
                "desired_head_sha": desired_head_sha,
            }
        ),
        encoding="utf-8",
    )
    return path


def completed(
    cmd: list[str], *, stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")


def safe_inspect_payload(
    *,
    exists: bool,
    branch: str | None = None,
    dirty: bool = False,
    active_session: bool = False,
) -> str:
    blockers = [] if exists else ["missing_path"]
    return json.dumps(
        {
            "exists": exists,
            "tracked_worktree": exists,
            "branch": branch,
            "active_session": active_session,
            "dirty": dirty,
            "blockers": blockers,
            "cleanup_safety": {
                "classification": "cleanup_candidate" if exists else "absent_noop",
                "decision": "cleanup_candidate" if exists else "noop",
            },
        }
    )


def test_absent_worktree_merged_pr_commit_list_paginates_commits(tmp_path: Path) -> None:
    desired_head = "317b94232d3ba41c3a1e546a94010dfdf069f85f"
    lane, ledger, _worktree = _stale_worktree_lane(
        tmp_path,
        branch="codex/large-merged-pr",
        desired_head=desired_head,
    )
    calls: list[list[str]] = []

    def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if "safe_worktree_cleanup.py" in " ".join(cmd):
            return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
        if cmd[:3] == ["git", "ls-remote", "origin"]:
            return completed(cmd, stdout="")
        if cmd == ["git", "remote", "get-url", "origin"]:
            return completed(cmd, stdout="https://github.com/synaptent/aragora.git\n")
        if cmd[:2] == ["gh", "api"] and f"commits/{desired_head}/pulls" in cmd[-1]:
            return completed(
                cmd,
                stdout=json.dumps(
                    [{"number": 7825, "merged_at": LIVENESS_NOW, "base": {"ref": "main"}}]
                ),
            )
        if cmd[:2] == ["gh", "api"] and "pulls/7825/commits" in cmd[-1]:
            if "&page=1" in cmd[-1]:
                return completed(
                    cmd,
                    stdout=json.dumps([{"sha": f"{i:040x}"} for i in range(100)]),
                )
            if "&page=2" in cmd[-1]:
                return completed(cmd, stdout=json.dumps([{"sha": desired_head}]))
        raise AssertionError(f"unexpected command: {cmd}")

    proof = ilo.build_worktree_reference_preservation_proof(
        lane,
        ledger_entry=ledger,
        repo_root=tmp_path,
        state_root=tmp_path / ".aragora",
        runner=runner,
    )

    assert proof["available"] is True
    assert proof["upstream_preservation"]["method"] == "merged_pr_commit_list"
    assert proof["upstream_preservation"]["base_ref"] == "main"
    commit_page_calls = [cmd for cmd in calls if "pulls/7825/commits" in cmd[-1]]
    assert any("&page=1" in cmd[-1] for cmd in commit_page_calls)
    assert any("&page=2" in cmd[-1] for cmd in commit_page_calls)


class TestOwnerLeaseLiveness:
    def test_live_owner_no_advisory(self) -> None:
        lane = {
            "lane_id": "Q1-live",
            "owner_session": "codex-q1",
            "status": "active",
            "branch": "codex/q1",
            "updated_at": _hours_ago(1.0),
        }
        ledger = {"lane": "Q1-live", "status": "in_progress", "launched_at": _hours_ago(1.0)}
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )
        liveness = result["owner_liveness"]
        assert liveness["assessed"] == "live"
        assert liveness["lane_status"] == "in_progress"
        assert liveness["lease_age_seconds"] == 3600
        assert liveness["last_heartbeat_at"] is None
        assert result["owner_blocking_state"] == "live_owner"
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] is None

    def test_terminal_completed_lane_yields_advisory(self) -> None:
        lane = {
            "lane_id": "Q2-done",
            "owner_session": "codex-q2",
            "status": "active",
            "branch": "codex/q2",
            "updated_at": _hours_ago(7.0),
        }
        ledger = {"lane": "Q2-done", "status": "completed", "launched_at": _hours_ago(7.0)}
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )
        assert result["owner_liveness"]["assessed"] == "terminal"
        assert result["owner_liveness"]["lane_status"] == "completed"
        assert result["owner_blocking_state"] == "stale_terminal_owner"
        advisory = result["stale_claim_advisory"]
        assert advisory is not None
        assert advisory["available"] is True
        assert advisory["protocol"] == "stale-claim-override"
        assert advisory["required_ledger_record"] == (
            "overriding lane must write an override entry naming the stale lane id"
        )
        assert any("terminal" in c for c in advisory["conditions_met"])
        assert result["advisory_withheld"] is None

    def test_expired_registry_status_without_ledger_yields_terminal_advisory(self) -> None:
        lane = {
            "lane_id": "Q2-expired",
            "owner_session": "codex-q2",
            "status": "expired",
            "branch": "codex/q2-expired",
            "updated_at": _hours_ago(1.0),
        }
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=None, heartbeat=None, now=_liveness_now()
        )

        assert result["owner_liveness"]["assessed"] == "terminal"
        assert result["owner_liveness"]["lane_status"] == "expired"
        assert result["owner_blocking_state"] == "stale_terminal_owner"
        advisory = result["stale_claim_advisory"]
        assert advisory is not None
        assert advisory["available"] is True
        assert any("lane_status=expired" in c for c in advisory["conditions_met"])
        assert result["advisory_withheld"] is None

    @pytest.mark.parametrize("status", ["failed", "cancelled"])
    def test_failed_and_cancelled_ledger_statuses_are_terminal(self, status: str) -> None:
        lane = {"lane_id": "Q3", "owner_session": "x", "updated_at": _hours_ago(7.0)}
        ledger = {"lane": "Q3", "status": status, "launched_at": _hours_ago(7.0)}
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )
        assert result["owner_liveness"]["assessed"] == "terminal"
        assert result["stale_claim_advisory"] is not None

    def test_stale_in_progress_without_heartbeat_yields_advisory(self) -> None:
        lane = {
            "lane_id": "Q4-stale",
            "owner_session": "codex-q4",
            "status": "active",
            "branch": "codex/q4",
            "updated_at": _hours_ago(7.0),
        }
        ledger = {"lane": "Q4-stale", "status": "in_progress", "launched_at": _hours_ago(7.0)}
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )
        liveness = result["owner_liveness"]
        assert liveness["assessed"] == "stale"
        assert liveness["lane_status"] == "in_progress"
        assert liveness["lease_age_seconds"] == 7 * 3600
        assert result["owner_blocking_state"] == "stale_owner"
        advisory = result["stale_claim_advisory"]
        assert advisory is not None
        assert advisory["available"] is True
        assert any("lease_age_seconds" in c for c in advisory["conditions_met"])
        assert any("no heartbeat" in c for c in advisory["conditions_met"])
        assert result["advisory_withheld"] is None

    def test_terminal_marked_heartbeat_does_not_keep_stale_owner_live(self) -> None:
        lane = {
            "lane_id": "Q4-terminal-heartbeat",
            "owner_session": "codex-q4",
            "status": "active",
            "branch": "codex/q4",
            "updated_at": _hours_ago(7.0),
            "last_heartbeat_at": _hours_ago(0.1),
        }
        ledger = {
            "lane": "Q4-terminal-heartbeat",
            "status": "in_progress",
            "launched_at": _hours_ago(7.0),
            "last_heartbeat_at": _hours_ago(0.1),
        }
        heartbeat = {
            "last_seen_at": _hours_ago(0.1),
            "terminal_outcome": "completed",
            "terminal_finalized_at": _hours_ago(0.05),
        }

        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=heartbeat, now=_liveness_now()
        )

        liveness = result["owner_liveness"]
        assert liveness["assessed"] == "stale"
        assert liveness["last_heartbeat_at"] is None
        assert liveness["terminal_heartbeat_outcome"] == "completed"
        assert result["owner_blocking_state"] == "stale_owner"

    def test_worktree_reference_withholds_advisory(self) -> None:
        lane = {
            "lane_id": "Q5-wt",
            "owner_session": "codex-q5",
            "status": "active",
            "worktree": "/private/tmp/q5-worktree",
            "updated_at": _hours_ago(7.0),
        }
        ledger = {"lane": "Q5-wt", "status": "in_progress", "launched_at": _hours_ago(7.0)}
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )
        assert result["owner_liveness"]["assessed"] == "stale"
        assert result["owner_blocking_state"] == "stale_owner"
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_absent_worktree_with_remote_exact_head_yields_advisory(self, tmp_path: Path) -> None:
        lane, ledger, worktree = _stale_worktree_lane(
            tmp_path,
            branch="codex/measure-work-loss-pending-outbox-primary-20260610",
            desired_head="4966b95bec51fac1ae102443d5e7a2974e03065d",
        )
        calls: list[list[str]] = []

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(
                    cmd,
                    stdout=f"{lane['desired_head_sha']}\trefs/heads/{lane['branch']}\n",
                )
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is True
        assert proof["upstream_preservation"]["method"] == "remote_branch_exact_head"
        assert not any(cmd[:2] == ["gh", "api"] for cmd in calls)
        assert result["owner_liveness"]["assessed"] == "stale"
        assert result["stale_claim_advisory"]["available"] is True
        assert result["advisory_withheld"] is None

    def test_absent_worktree_with_sha_in_merged_pr_yields_advisory(self, tmp_path: Path) -> None:
        desired_head = "317b94232d3ba41c3a1e546a94010dfdf069f85f"
        lane, ledger, worktree = _stale_worktree_lane(
            tmp_path,
            branch="codex/salvage-collect-evidence-quorum-rerun-20260606",
            desired_head=desired_head,
        )

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                return completed(cmd, stdout="https://github.com/synaptent/aragora.git\n")
            if cmd[:2] == ["gh", "api"] and f"commits/{desired_head}/pulls" in cmd[-1]:
                return completed(
                    cmd, stdout=json.dumps([{"number": 7825, "merged_at": LIVENESS_NOW}])
                )
            if cmd[:2] == ["gh", "api"] and "pulls/7825/commits" in cmd[-1]:
                return completed(cmd, stdout=json.dumps([{"sha": desired_head}]))
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is True
        assert proof["upstream_preservation"]["method"] == "merged_pr_commit_list"
        assert result["owner_liveness"]["assessed"] == "stale"
        assert result["stale_claim_advisory"]["available"] is True
        assert result["advisory_withheld"] is None

    def test_existing_worktree_still_withholds_advisory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lane, ledger, worktree = _stale_worktree_lane(tmp_path)
        worktree.mkdir()

        monkeypatch.setattr(
            ilo,
            "_safe_worktree_absent_noop",
            lambda _path: False,
            raising=False,
        )
        monkeypatch.setattr(
            ilo,
            "_upstream_preservation_proof",
            lambda _lane, _ledger: {
                "method": "remote_branch_exact_head",
                "desired_head": "a" * 40,
            },
            raising=False,
        )

        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )

        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_absent_worktree_without_upstream_proof_still_withholds_advisory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lane, ledger, worktree = _stale_worktree_lane(tmp_path)

        monkeypatch.setattr(
            ilo,
            "_safe_worktree_absent_noop",
            lambda path: Path(path) == worktree,
            raising=False,
        )
        monkeypatch.setattr(
            ilo,
            "_upstream_preservation_proof",
            lambda _lane, _ledger: None,
            raising=False,
        )

        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )

        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_dirty_marker_overrides_absent_worktree_upstream_proof(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lane, ledger, worktree = _stale_worktree_lane(tmp_path)
        lane["dirty"] = True

        monkeypatch.setattr(
            ilo,
            "_safe_worktree_absent_noop",
            lambda path: Path(path) == worktree,
            raising=False,
        )
        monkeypatch.setattr(
            ilo,
            "_upstream_preservation_proof",
            lambda _lane, _ledger: {
                "method": "remote_branch_exact_head",
                "desired_head": "a" * 40,
            },
            raising=False,
        )

        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )

        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_upstream_proof_rest_calls_use_bounded_gh_api(self, tmp_path: Path) -> None:
        desired_head = "b" * 40
        lane, ledger, _worktree = _stale_worktree_lane(
            tmp_path,
            branch="codex/app-token-proof",
            desired_head=desired_head,
        )
        calls: list[list[str]] = []

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                return completed(cmd, stdout="https://github.com/synaptent/aragora.git\n")
            if cmd[:2] == ["gh", "api"]:
                assert "graphql" not in cmd
                assert "pr" not in cmd
                assert "list" not in cmd
                if f"commits/{desired_head}/pulls" in cmd[-1]:
                    return completed(
                        cmd,
                        stdout=json.dumps([{"number": 7825, "merged_at": LIVENESS_NOW}]),
                    )
                if "pulls/7825/commits" in cmd[-1]:
                    return completed(cmd, stdout=json.dumps([{"sha": desired_head}]))
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )

        assert proof["available"] is True
        assert proof["upstream_preservation"]["method"] == "merged_pr_commit_list"
        assert any(cmd[:2] == ["gh", "api"] for cmd in calls)
        assert not any(str(ilo.REPO_ROOT / "scripts" / "gh_app_env.py") in cmd for cmd in calls)

    def test_uncommitted_work_claim_withholds_advisory(self) -> None:
        lane = {"lane_id": "Q6-dirty", "owner_session": "codex-q6", "updated_at": _hours_ago(7.0)}
        ledger = {
            "lane": "Q6-dirty",
            "status": "completed",
            "launched_at": _hours_ago(7.0),
            "uncommitted_changes": True,
        }
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )
        assert result["owner_liveness"]["assessed"] == "terminal"
        assert result["owner_blocking_state"] == "stale_owner"
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_unknown_timestamps_never_produce_advisory(self) -> None:
        lane = {"lane_id": "Q7-unknown", "owner_session": "codex-q7", "status": "active"}
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=None, heartbeat=None, now=_liveness_now()
        )
        liveness = result["owner_liveness"]
        assert liveness["assessed"] == "unknown"
        assert liveness["lease_age_seconds"] is None
        assert liveness["lane_status"] == "unknown"
        assert liveness["last_heartbeat_at"] is None
        assert result["owner_blocking_state"] == "unknown_owner"
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] is None

    def test_lease_just_under_stale_hours_is_live(self) -> None:
        # 1 minute inside the default 6h window → live, no advisory.
        from datetime import timedelta

        updated = (_liveness_now() - timedelta(hours=6) + timedelta(minutes=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        lane = {"lane_id": "Q8-boundary", "owner_session": "codex-q8", "updated_at": updated}
        ledger = {"lane": "Q8-boundary", "status": "in_progress", "launched_at": updated}
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=ledger, heartbeat=None, now=_liveness_now()
        )
        assert result["owner_liveness"]["assessed"] == "live"
        assert result["owner_blocking_state"] == "live_owner"
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] is None

    def test_fresh_heartbeat_keeps_old_lease_live(self) -> None:
        lane = {"lane_id": "Q9-hb", "owner_session": "codex-q9", "updated_at": _hours_ago(7.0)}
        heartbeat = {"last_seen_at": _hours_ago(0.1)}
        result = ilo.assess_owner_liveness(
            lane, ledger_entry=None, heartbeat=heartbeat, now=_liveness_now()
        )
        liveness = result["owner_liveness"]
        assert liveness["assessed"] == "live"
        assert liveness["last_heartbeat_at"] == _hours_ago(0.1)
        assert result["stale_claim_advisory"] is None

    def test_find_lane_ledger_entry_matches_by_branch_and_picks_newest(
        self, tmp_path: Path
    ) -> None:
        runs_glob = write_lane_ledger(
            tmp_path,
            [
                {
                    "lane": "older-attempt",
                    "branch": "codex/shared",
                    "status": "dead",
                    "launched_at": _hours_ago(30.0),
                },
                {
                    "lane": "newer-attempt",
                    "branch": "codex/shared",
                    "status": "in_progress",
                    "launched_at": _hours_ago(2.0),
                },
            ],
        )
        lane = {"lane_id": "not-in-ledger", "branch": "codex/shared"}
        entry = ilo.find_lane_ledger_entry(lane, runs_glob=runs_glob)
        assert entry is not None
        assert entry["lane"] == "newer-attempt"
        assert entry["status"] == "in_progress"

    def test_find_lane_ledger_entry_missing_returns_none(self, tmp_path: Path) -> None:
        runs_glob = write_lane_ledger(tmp_path, [])
        assert ilo.find_lane_ledger_entry({"lane_id": "nope"}, runs_glob=runs_glob) is None


class TestWorktreeReferencePreservationProof:
    def test_q467_absent_worktree_remote_branch_exact_head_yields_advisory(
        self, tmp_path: Path
    ) -> None:
        desired_sha = "4966b95bec51fac1ae102443d5e7a2974e03065d"
        branch = "codex/measure-work-loss-pending-outbox-primary-20260610"
        lane = {
            "lane_id": "Q467-primary-measure-work-loss-pending-outbox",
            "owner_session": "codex-q467",
            "branch": branch,
            "worktree": str(tmp_path / "absent-q467"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "in_progress",
            "launched_at": _hours_ago(7.0),
        }
        write_preservation_outbox(
            tmp_path,
            lane_id=lane["lane_id"],
            branch=branch,
            desired_head_sha=desired_sha,
        )
        calls: list[list[str]] = []

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{desired_sha}\trefs/heads/{branch}\n")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        assert proof["available"] is True
        assert proof["upstream_preservation"]["method"] == "remote_branch_exact_head"
        assert not any(cmd[:2] == ["gh", "api"] for cmd in calls)

        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )
        assert result["stale_claim_advisory"]["available"] is True
        assert result["advisory_withheld"] is None

    def test_branch_ahead_marker_discounted_when_remote_exact_head_preserved(
        self, tmp_path: Path
    ) -> None:
        desired_sha = "4966b95bec51fac1ae102443d5e7a2974e03065d"
        branch = "codex/branch-ahead-preserved"
        lane, ledger, _worktree = _stale_worktree_lane(
            tmp_path,
            branch=branch,
            desired_head=desired_sha,
        )
        lane["branch_ahead_of_origin_main"] = True
        ledger["unique_commits_ahead"] = 2

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{desired_sha}\trefs/heads/{branch}\n")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is True
        assert proof["upstream_preservation"]["method"] == "remote_branch_exact_head"
        assert result["stale_claim_advisory"]["available"] is True
        assert result["advisory_withheld"] is None

    def test_clean_dirty_marker_strings_do_not_withhold_advisory(self, tmp_path: Path) -> None:
        desired_sha = "4966b95bec51fac1ae102443d5e7a2974e03065d"
        branch = "codex/clean-marker-preserved"
        lane, ledger, _worktree = _stale_worktree_lane(
            tmp_path,
            branch=branch,
            desired_head=desired_sha,
        )
        lane["dirty_worktree"] = "clean"
        ledger["worktree_dirty"] = "verified-clean"

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{desired_sha}\trefs/heads/{branch}\n")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is True
        assert proof["upstream_preservation"]["method"] == "remote_branch_exact_head"
        assert result["stale_claim_advisory"]["available"] is True
        assert result["advisory_withheld"] is None

    def test_absent_terminal_worktree_remote_branch_without_local_branch_is_reassignable(
        self, tmp_path: Path
    ) -> None:
        remote_sha = "dddddddddddddddddddddddddddddddddddddddd"
        branch = "codex/no-local-record"
        lane = {
            "lane_id": "Q-no-local-record",
            "owner_session": "codex-no-local-record",
            "branch": branch,
            "worktree": str(tmp_path / "absent-no-local-record"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{remote_sha}\trefs/heads/{branch}\n")
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, returncode=1)
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is True
        assert proof["desired_head_sha"] is None
        assert proof["desired_head_source"] == "not_recorded"
        assert proof["lane_status"] == "completed"
        assert proof["local_branch"]["status"] == "missing"
        assert proof["upstream_preservation"]["proven"] is True
        assert proof["upstream_preservation"]["method"] == "remote_branch_only_no_local_record"
        assert proof["upstream_preservation"]["remote_head_sha"] == remote_sha
        assert result["stale_claim_advisory"]["available"] is True
        assert result["owner_blocking_state"] == "stale_terminal_owner"
        assert result["advisory_withheld"] is None

    def test_absent_terminal_worktree_without_recorded_sha_dirty_marker_withholds(
        self, tmp_path: Path
    ) -> None:
        branch = "codex/no-local-record-dirty-marker"
        lane = {
            "lane_id": "Q-no-local-record-dirty",
            "owner_session": "codex-no-local-record-dirty",
            "branch": branch,
            "worktree": str(tmp_path / "absent-no-local-record-dirty"),
            "updated_at": _hours_ago(7.0),
            "dirty_worktree": True,
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is False
        assert proof["reason"] == "local_work_claim_present"
        assert "dirty_worktree" in proof["detail"]
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_absent_terminal_worktree_without_recorded_sha_false_marker_is_reassignable(
        self, tmp_path: Path
    ) -> None:
        remote_sha = "ffffffffffffffffffffffffffffffffffffffff"
        branch = "codex/no-local-record-false-marker"
        lane = {
            "lane_id": "Q-no-local-record-false",
            "owner_session": "codex-no-local-record-false",
            "branch": branch,
            "worktree": str(tmp_path / "absent-no-local-record-false"),
            "updated_at": _hours_ago(7.0),
            "possible_unpushed_work": "false",
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
            "dirty_worktree": False,
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{remote_sha}\trefs/heads/{branch}\n")
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, returncode=1)
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is True
        assert proof["upstream_preservation"]["method"] == "remote_branch_only_no_local_record"
        assert proof["upstream_preservation"]["proven"] is True
        assert result["stale_claim_advisory"]["available"] is True
        assert result["owner_blocking_state"] == "stale_terminal_owner"
        assert result["advisory_withheld"] is None

    def test_absent_terminal_worktree_matching_local_and_remote_branch_is_reassignable(
        self, tmp_path: Path
    ) -> None:
        branch_sha = "abababababababababababababababababababab"
        branch = "codex/no-local-record-matching-branch"
        lane = {
            "lane_id": "Q-no-local-record-matching",
            "owner_session": "codex-no-local-record-matching",
            "branch": branch,
            "worktree": str(tmp_path / "absent-no-local-record-matching"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{branch_sha}\trefs/heads/{branch}\n")
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, stdout=f"{branch_sha}\n")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["upstream_preservation"]["proven"] is True
        assert (
            proof["upstream_preservation"]["method"]
            == "remote_branch_matches_local_branch_no_record"
        )
        assert result["owner_blocking_state"] == "stale_terminal_owner"
        assert result["advisory_withheld"] is None

    def test_absent_terminal_worktree_divergent_local_branch_still_withholds(
        self, tmp_path: Path
    ) -> None:
        remote_sha = "abababababababababababababababababababab"
        local_sha = "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"
        branch = "codex/no-local-record-divergent-branch"
        lane = {
            "lane_id": "Q-no-local-record-divergent",
            "owner_session": "codex-no-local-record-divergent",
            "branch": branch,
            "worktree": str(tmp_path / "absent-no-local-record-divergent"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{remote_sha}\trefs/heads/{branch}\n")
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, stdout=f"{local_sha}\n")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is False
        assert proof["reason"] == "local_remote_branch_head_mismatch"
        assert proof["local"]["head_sha"] == local_sha
        assert proof["remote"]["head_sha"] == remote_sha
        assert result["owner_blocking_state"] == "stale_owner"
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_absent_terminal_worktree_local_branch_lookup_failure_still_withholds(
        self, tmp_path: Path
    ) -> None:
        remote_sha = "abababababababababababababababababababab"
        branch = "codex/no-local-record-lookup-failure"
        lane = {
            "lane_id": "Q-no-local-record-lookup-failure",
            "owner_session": "codex-no-local-record-lookup-failure",
            "branch": branch,
            "worktree": str(tmp_path / "absent-no-local-record-lookup-failure"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{remote_sha}\trefs/heads/{branch}\n")
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, returncode=128)
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is False
        assert proof["reason"] == "local_branch_lookup_failed"
        assert proof["local"]["status"] == "lookup_failed"
        assert result["owner_blocking_state"] == "stale_owner"
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_absent_in_progress_worktree_remote_branch_without_recorded_sha_still_withholds(
        self, tmp_path: Path
    ) -> None:
        remote_sha = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        branch = "codex/no-local-record-in-progress"
        lane = {
            "lane_id": "Q-no-local-record-in-progress",
            "owner_session": "codex-no-local-record-in-progress",
            "branch": branch,
            "worktree": str(tmp_path / "absent-no-local-record-in-progress"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "in_progress",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{remote_sha}\trefs/heads/{branch}\n")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is False
        assert proof["reason"] == "desired_head_unavailable_non_terminal_lane"
        assert proof["remote"]["status"] == "exists"
        assert proof["remote"]["head_sha"] == remote_sha
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_absent_worktree_without_recorded_sha_and_missing_remote_still_withholds(
        self, tmp_path: Path
    ) -> None:
        branch = "codex/no-local-record-missing-remote"
        lane = {
            "lane_id": "Q-no-local-record-missing",
            "owner_session": "codex-no-local-record-missing",
            "branch": branch,
            "worktree": str(tmp_path / "absent-no-local-record-missing"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout="")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is False
        assert proof["reason"] == "desired_head_unavailable"
        assert proof["remote"]["status"] == "missing"
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_present_worktree_without_recorded_sha_still_withholds(self, tmp_path: Path) -> None:
        branch = "codex/no-local-record-present"
        lane = {
            "lane_id": "Q-no-local-record-present",
            "owner_session": "codex-no-local-record-present",
            "branch": branch,
            "worktree": str(tmp_path / "present-no-local-record"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=True))
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is False
        assert proof["reason"] == "worktree_not_absent_noop"
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_clean_inactive_terminal_worktree_exact_remote_branch_is_reassignable(
        self, tmp_path: Path
    ) -> None:
        branch_sha = "abababababababababababababababababababab"
        branch = "codex/no-local-record-clean-present"
        lane = {
            "lane_id": "Q-no-local-record-clean-present",
            "owner_session": "codex-no-local-record-clean-present",
            "branch": branch,
            "worktree": str(tmp_path / "present-no-local-record-clean"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(
                    cmd,
                    stdout=safe_inspect_payload(exists=True, branch=branch),
                    returncode=1,
                )
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout=f"{branch_sha}\trefs/heads/{branch}\n")
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, stdout=f"{branch_sha}\n")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["upstream_preservation"]["proven"] is True
        assert (
            proof["upstream_preservation"]["method"]
            == "remote_branch_matches_clean_worktree_no_record"
        )
        assert proof["worktree_inspections"][0]["clean_inactive"] is True
        assert result["owner_blocking_state"] == "stale_terminal_owner"
        assert result["advisory_withheld"] is None

    def test_dirty_terminal_worktree_still_withholds(self, tmp_path: Path) -> None:
        branch = "codex/no-local-record-dirty-present"
        lane = {
            "lane_id": "Q-no-local-record-dirty-present",
            "owner_session": "codex-no-local-record-dirty-present",
            "branch": branch,
            "worktree": str(tmp_path / "present-no-local-record-dirty"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(
                    cmd,
                    stdout=safe_inspect_payload(exists=True, branch=branch, dirty=True),
                    returncode=1,
                )
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )

        assert proof["available"] is False
        assert proof["reason"] == "worktree_not_absent_noop"
        assert result["owner_blocking_state"] == "stale_owner"
        assert result["advisory_withheld"] == "possible_unpushed_work"

    @pytest.mark.parametrize(
        ("remote_sha", "local_sha"),
        [(None, "a" * 40), (None, "b" * 40), ("a" * 40, "a" * 40), ("a" * 40, "b" * 40)],
    )
    def test_clean_terminal_worktree_recorded_head_requires_live_remote_preservation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        remote_sha: str | None,
        local_sha: str,
    ) -> None:
        desired_sha = "a" * 40
        branch = "codex/clean-recorded-head"
        lane = {
            "lane_id": "Q-clean-recorded-head",
            "owner_session": "codex-clean-recorded-head",
            "branch": branch,
            "worktree": str(tmp_path / "clean-recorded-head"),
            "desired_head_sha": desired_sha,
            "status": "completed",
            "updated_at": _hours_ago(7.0),
        }
        merged_lookup_calls: list[str] = []

        def merged_proof(head: str, **kwargs: Any) -> dict[str, Any]:
            merged_lookup_calls.append(head)
            return {"proven": True, "method": "merged_pr_commit_list"}

        monkeypatch.setattr(ilo, "_merged_pr_commit_list_proof", merged_proof)

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=True, branch=branch))
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                output = f"{remote_sha}\trefs/heads/{branch}\n" if remote_sha else ""
                return completed(cmd, stdout=output)
            if cmd[:3] == ["git", "rev-parse", "--verify"]:
                return completed(cmd, stdout=f"{local_sha}\n")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane, repo_root=tmp_path, state_root=tmp_path / ".aragora", runner=runner
        )
        result = ilo.assess_owner_liveness(lane, now=_liveness_now(), local_work_preservation=proof)

        assert merged_lookup_calls == []
        assert proof["available"] is (remote_sha == local_sha)
        if remote_sha != local_sha:
            assert proof["reason"] == (
                "remote_branch_missing_for_present_worktree"
                if remote_sha is None
                else "clean_worktree_branch_not_preserved"
            )
            assert result["owner_blocking_state"] == "stale_owner"
            assert result["advisory_withheld"] == "possible_unpushed_work"
        else:
            assert proof["upstream_preservation"]["method"] == "remote_branch_exact_head"
            assert result["owner_blocking_state"] == "stale_terminal_owner"

    def test_q379_absent_worktree_merged_pr_commit_yields_advisory_when_remote_gone(
        self, tmp_path: Path
    ) -> None:
        desired_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        branch = "codex/salvage-collect-evidence-quorum-rerun-20260606"
        lane = {
            "lane_id": "Q379-primary-salvage",
            "owner_session": "codex-q379",
            "branch": branch,
            "worktree": str(tmp_path / "absent-q379"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "completed",
            "launched_at": _hours_ago(7.0),
        }
        write_preservation_outbox(
            tmp_path,
            lane_id=lane["lane_id"],
            branch=branch,
            desired_head_sha=desired_sha,
        )

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                return completed(cmd, stdout="https://github.com/synaptent/aragora.git\n")
            if cmd[:2] == ["gh", "api"] and f"commits/{desired_sha}/pulls" in cmd[-1]:
                return completed(
                    cmd, stdout=json.dumps([{"number": 8396, "merged_at": LIVENESS_NOW}])
                )
            if cmd[:2] == ["gh", "api"] and "pulls/8396/commits" in cmd[-1]:
                return completed(cmd, stdout=json.dumps([{"sha": desired_sha}]))
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        assert proof["available"] is True
        assert proof["upstream_preservation"]["method"] == "merged_pr_commit_list"

        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )
        assert result["stale_claim_advisory"]["available"] is True
        assert result["advisory_withheld"] is None

    def test_present_worktree_still_withholds_possible_unpushed_work(self, tmp_path: Path) -> None:
        desired_sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        branch = "codex/present-worktree"
        lane = {
            "lane_id": "Q-present",
            "owner_session": "codex-present",
            "branch": branch,
            "worktree": str(tmp_path / "present-worktree"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "in_progress",
            "launched_at": _hours_ago(7.0),
        }
        write_preservation_outbox(
            tmp_path,
            lane_id=lane["lane_id"],
            branch=branch,
            desired_head_sha=desired_sha,
        )

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=True))
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )
        assert proof["available"] is False
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_absent_worktree_without_upstream_proof_still_withholds(self, tmp_path: Path) -> None:
        desired_sha = "cccccccccccccccccccccccccccccccccccccccc"
        branch = "codex/no-upstream-proof"
        lane = {
            "lane_id": "Q-no-proof",
            "owner_session": "codex-no-proof",
            "branch": branch,
            "worktree": str(tmp_path / "absent-no-proof"),
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "in_progress",
            "launched_at": _hours_ago(7.0),
        }
        write_preservation_outbox(
            tmp_path,
            lane_id=lane["lane_id"],
            branch=branch,
            desired_head_sha=desired_sha,
        )

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            if "safe_worktree_cleanup.py" in " ".join(cmd):
                return completed(cmd, stdout=safe_inspect_payload(exists=False), returncode=1)
            if cmd[:3] == ["git", "ls-remote", "origin"]:
                return completed(cmd, stdout="")
            if cmd == ["git", "remote", "get-url", "origin"]:
                return completed(cmd, stdout="https://github.com/synaptent/aragora.git\n")
            if cmd[:2] == ["gh", "api"] and f"commits/{desired_sha}/pulls" in cmd[-1]:
                return completed(cmd, stdout="[]")
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )
        assert proof["available"] is False
        assert proof["reason"] == "upstream_preservation_unproven"
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"

    def test_dirty_marker_set_still_withholds_possible_unpushed_work(self, tmp_path: Path) -> None:
        branch = "codex/dirty-marker"
        lane = {
            "lane_id": "Q-dirty-marker",
            "owner_session": "codex-dirty-marker",
            "branch": branch,
            "worktree": str(tmp_path / "absent-dirty"),
            "local_work": True,
            "updated_at": _hours_ago(7.0),
        }
        ledger = {
            "lane": lane["lane_id"],
            "branch": branch,
            "status": "in_progress",
            "launched_at": _hours_ago(7.0),
        }

        def runner(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
            raise AssertionError(f"unexpected command: {cmd}")

        proof = ilo.build_worktree_reference_preservation_proof(
            lane,
            ledger_entry=ledger,
            repo_root=tmp_path,
            state_root=tmp_path / ".aragora",
            runner=runner,
        )
        result = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger,
            heartbeat=None,
            now=_liveness_now(),
            local_work_preservation=proof,
        )
        assert proof["available"] is False
        assert proof["reason"] == "local_work_claim_present"
        assert result["stale_claim_advisory"] is None
        assert result["advisory_withheld"] == "possible_unpushed_work"


class TestLivenessCLI:
    def _cli_args(
        self, registry: Path, tmp_path: Path, *, heartbeat_path: Path | None = None
    ) -> list[str]:
        return [
            "--registry-path",
            str(registry),
            "--codex-sessions-root",
            str(tmp_path / "no_codex"),
            "--claude-projects-root",
            str(tmp_path / "no_claude"),
            "--factory-bg-path",
            str(tmp_path / "no_factory.json"),
            "--steering-inbox-root",
            str(tmp_path / "no_steering"),
            "--heartbeat-path",
            str(heartbeat_path or tmp_path / "no_heartbeats.json"),
        ]

    def _stale_fixture(self, tmp_path: Path) -> tuple[Path, str]:
        registry = write_lane_registry(
            tmp_path,
            [
                {
                    "lane_id": "Q379-stale-owner",
                    "owner_session": "codex-q379",
                    "source": "codex",
                    "status": "active",
                    "branch": "codex/q379",
                    "pr_number": 7825,
                    "updated_at": _hours_ago(7.0),
                }
            ],
        )
        runs_glob = write_lane_ledger(
            tmp_path,
            [
                {
                    "lane": "Q379-stale-owner",
                    "branch": "codex/q379",
                    "status": "in_progress",
                    "launched_at": _hours_ago(7.0),
                }
            ],
        )
        return registry, runs_glob

    def _stale_heartbeat_fixture(self, tmp_path: Path) -> tuple[Path, str, Path]:
        registry, runs_glob = self._stale_fixture(tmp_path)
        heartbeat_path = tmp_path / "heartbeats.json"
        heartbeat_path.write_text(
            json.dumps(
                [
                    {
                        "lane_id": "Q379-stale-owner",
                        "owner_session": "codex-q379",
                        "branch": "codex/q379",
                        "pr_number": 7825,
                        "last_seen_at": _hours_ago(1.0),
                    }
                ]
            ),
            encoding="utf-8",
        )
        return registry, runs_glob, heartbeat_path

    def test_json_includes_owner_liveness_and_advisory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry, runs_glob = self._stale_fixture(tmp_path)
        rc = ilo.main(
            [
                "--lane-id",
                "Q379-stale-owner",
                "--json",
                "--runs-glob",
                runs_glob,
                "--now",
                LIVENESS_NOW,
                *self._cli_args(registry, tmp_path),
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        # Existing fields still present and unchanged.
        assert data["lane_id"] == "Q379-stale-owner"
        assert data["owner_session"] == "codex-q379"
        assert data["pr_number"] == 7825
        # New advisory-only enrichment.
        assert data["owner_liveness"]["assessed"] == "stale"
        assert data["owner_liveness"]["lane_status"] == "in_progress"
        assert data["owner_liveness"]["lease_age_seconds"] == 7 * 3600
        assert data["owner_blocking_state"] == "stale_owner"
        assert data["owner_liveness_precedence"] == (
            "owner_blocking_state controls dispatch/reassignment; cleanup_state and "
            "recommended_operator_action control mutation/cleanup"
        )
        assert data["owner_liveness_alignment"]["applied"] is False
        assert data["cleanup_state"] == "preserve_unverified_owner"
        assert data["stale_claim_advisory"]["available"] is True
        assert data["stale_claim_advisory"]["protocol"] == "stale-claim-override"
        assert data["advisory_withheld"] is None

    def test_json_marks_expired_registry_row_as_stale_terminal_owner(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = write_lane_registry(
            tmp_path,
            [
                {
                    "lane_id": "Q-expired-owner",
                    "owner_session": "codex-expired",
                    "source": "codex",
                    "status": "expired",
                    "branch": "codex/expired",
                    "pr_number": 7826,
                    "updated_at": _hours_ago(1.0),
                }
            ],
        )

        rc = ilo.main(
            [
                "--pr",
                "7826",
                "--json",
                "--runs-glob",
                str(tmp_path / "missing" / "lanes"),
                "--now",
                LIVENESS_NOW,
                *self._cli_args(registry, tmp_path),
            ]
        )

        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["dispatchable"] is False
        assert data["dispatch_blocker"] == (
            "lane status is expired; claim an active lane before steering"
        )
        assert data["owner_liveness"]["assessed"] == "terminal"
        assert data["owner_liveness"]["lane_status"] == "expired"
        assert data["owner_blocking_state"] == "stale_terminal_owner"
        assert data["stale_claim_advisory"]["available"] is True
        assert data["advisory_withheld"] is None

    def test_custom_stale_hours_flag_keeps_owner_live(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry, runs_glob = self._stale_fixture(tmp_path)
        rc = ilo.main(
            [
                "--lane-id",
                "Q379-stale-owner",
                "--json",
                "--runs-glob",
                runs_glob,
                "--now",
                LIVENESS_NOW,
                "--stale-hours",
                "8",
                *self._cli_args(registry, tmp_path),
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["owner_liveness"]["assessed"] == "live"
        assert data["owner_liveness"]["stale_threshold_hours"] == 8.0
        assert data["owner_blocking_state"] == "live_owner"
        assert data["liveness_state"] == "missing_heartbeat"
        assert data["cleanup_state"] == "preserve_unverified_owner"
        assert data["owner_liveness_alignment"] == {
            "applied": True,
            "dispatch_field": "owner_blocking_state",
            "dispatch_value": "live_owner",
            "cleanup_field": "cleanup_state",
            "cleanup_value": "preserve_unverified_owner",
            "action_field": "recommended_operator_action",
            "action_value": "preserve; start or refresh agent heartbeat before cleanup decisions",
            "legacy_liveness_state": "missing_heartbeat",
            "lease_assessment": "live",
            "reason": (
                "dispatch/reassignment follows live owner lease evidence; mutation/cleanup "
                "keeps conservative heartbeat-derived guidance"
            ),
        }
        assert data["owner_state_reason"] == (
            "active lane has current owner lease evidence but no matched harness heartbeat row"
        )
        assert data["recommended_operator_action"] == (
            "preserve; start or refresh agent heartbeat before cleanup decisions"
        )
        assert data["stale_claim_advisory"] is None

    def test_live_lease_without_heartbeat_preserves_unverified_cleanup(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry, runs_glob = self._stale_fixture(tmp_path)
        rc = ilo.main(
            [
                "--lane-id",
                "Q379-stale-owner",
                "--json",
                "--runs-glob",
                runs_glob,
                "--now",
                LIVENESS_NOW,
                "--stale-hours",
                "8",
                *self._cli_args(registry, tmp_path),
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["owner_liveness"]["assessed"] == "live"
        assert data["owner_blocking_state"] == "live_owner"
        assert data["liveness_state"] == "missing_heartbeat"
        assert data["cleanup_state"] == "preserve_unverified_owner"
        assert data["owner_liveness_alignment"]["applied"] is True
        assert data["owner_liveness_alignment"]["dispatch_field"] == "owner_blocking_state"
        assert data["owner_liveness_alignment"]["cleanup_field"] == "cleanup_state"
        assert data["owner_state_reason"] == (
            "active lane has current owner lease evidence but no matched harness heartbeat row"
        )
        assert data["recommended_operator_action"] == (
            "preserve; start or refresh agent heartbeat before cleanup decisions"
        )

    def test_live_lease_with_stale_heartbeat_preserves_stale_cleanup(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry, runs_glob, heartbeat_path = self._stale_heartbeat_fixture(tmp_path)
        rc = ilo.main(
            [
                "--lane-id",
                "Q379-stale-owner",
                "--json",
                "--runs-glob",
                runs_glob,
                "--now",
                LIVENESS_NOW,
                "--stale-hours",
                "8",
                *self._cli_args(registry, tmp_path, heartbeat_path=heartbeat_path),
            ]
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["owner_liveness"]["assessed"] == "live"
        assert data["owner_blocking_state"] == "live_owner"
        assert data["liveness_state"] == "stale_heartbeat"
        assert data["cleanup_state"] == "preserve_stale_owner"
        assert data["owner_liveness_alignment"]["applied"] is True
        assert data["owner_liveness_alignment"]["legacy_liveness_state"] == "stale_heartbeat"
        assert data["owner_liveness_alignment"]["cleanup_value"] == "preserve_stale_owner"
        assert data["owner_state_reason"] == (
            "active lane has current owner lease evidence but matched harness heartbeat is stale"
        )
        assert data["recommended_operator_action"] == (
            "preserve; refresh heartbeat or contact owner before mutation or cleanup"
        )

    def test_human_output_uses_liveness_aligned_owner_state(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry, runs_glob = self._stale_fixture(tmp_path)
        rc = ilo.main(
            [
                "--lane-id",
                "Q379-stale-owner",
                "--runs-glob",
                runs_glob,
                "--now",
                LIVENESS_NOW,
                "--stale-hours",
                "8",
                *self._cli_args(registry, tmp_path),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "cleanup_state:  preserve_unverified_owner" in out
        assert (
            "owner_reason:   active lane has current owner lease evidence "
            "but no matched harness heartbeat row"
        ) in out
        assert (
            "recommended_action: preserve; start or refresh agent heartbeat "
            "before cleanup decisions"
        ) in out

    def test_direct_owner_liveness_helper_matches_cli_alignment(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry, runs_glob = self._stale_fixture(tmp_path)
        lane = ilo.find_lane(ilo.load_lane_records(registry), lane_id="Q379-stale-owner")
        assert lane is not None
        info = ilo.build_owner_info(
            lane,
            sessions_root=tmp_path / "no_codex",
            projects_root=tmp_path / "no_claude",
            bg_path=tmp_path / "no_factory.json",
            steering_inbox_root=tmp_path / "no_steering",
            heartbeat_path=tmp_path / "no_heartbeats.json",
        )
        ledger_entry = ilo.find_lane_ledger_entry(lane, runs_glob=runs_glob)
        liveness_payload = ilo.assess_owner_liveness(
            lane,
            ledger_entry=ledger_entry,
            heartbeat=info.latest_heartbeat,
            now=ilo._parse_iso_utc(LIVENESS_NOW),
            stale_hours=8.0,
        )

        aligned_info, payload = ilo.owner_info_with_aligned_liveness(info, liveness_payload)

        assert aligned_info.cleanup_state == "preserve_unverified_owner"
        assert aligned_info.recommended_operator_action == (
            "preserve; start or refresh agent heartbeat before cleanup decisions"
        )
        assert aligned_info.owner_state_reason == (
            "active lane has current owner lease evidence but no matched harness heartbeat row"
        )
        assert payload["owner_blocking_state"] == "live_owner"
        assert payload["owner_liveness_alignment"]["applied"] is True
        assert payload["owner_liveness_alignment"]["dispatch_value"] == "live_owner"
        assert payload["owner_liveness_alignment"]["cleanup_value"] == "preserve_unverified_owner"
        capsys.readouterr()

    def test_no_liveness_output_is_byte_identical_to_legacy_schema(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import dataclasses as _dataclasses

        registry, runs_glob = self._stale_fixture(tmp_path)
        rc = ilo.main(
            [
                "--lane-id",
                "Q379-stale-owner",
                "--json",
                "--no-liveness",
                "--runs-glob",
                runs_glob,
                "--now",
                LIVENESS_NOW,
                *self._cli_args(registry, tmp_path),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        legacy_fields = {f.name for f in _dataclasses.fields(ilo.LaneOwnerInfo)}
        assert set(data.keys()) == legacy_fields
        # Byte-identical to the pre-#8318 serialization of the same info.
        lane = ilo.find_lane(ilo.load_lane_records(registry), lane_id="Q379-stale-owner")
        assert lane is not None
        info = ilo.build_owner_info(
            lane,
            sessions_root=tmp_path / "no_codex",
            projects_root=tmp_path / "no_claude",
            bg_path=tmp_path / "no_factory.json",
            steering_inbox_root=tmp_path / "no_steering",
            heartbeat_path=tmp_path / "no_heartbeats.json",
        )
        expected = json.dumps(_dataclasses.asdict(info), indent=2, sort_keys=True) + "\n"
        assert out == expected

    def test_human_output_gains_single_summary_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry, runs_glob = self._stale_fixture(tmp_path)
        rc = ilo.main(
            [
                "--lane-id",
                "Q379-stale-owner",
                "--runs-glob",
                runs_glob,
                "--now",
                LIVENESS_NOW,
                *self._cli_args(registry, tmp_path),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        summary_lines = [line for line in out.splitlines() if line.startswith("owner_liveness: ")]
        assert len(summary_lines) == 1
        assert "assessed=stale" in summary_lines[0]
        assert "owner_blocking_state=stale_owner" in summary_lines[0]
        assert "stale_claim_advisory=available" in summary_lines[0]

    def test_human_output_omits_summary_with_no_liveness(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry, runs_glob = self._stale_fixture(tmp_path)
        rc = ilo.main(
            [
                "--lane-id",
                "Q379-stale-owner",
                "--no-liveness",
                "--runs-glob",
                runs_glob,
                *self._cli_args(registry, tmp_path),
            ]
        )
        assert rc == 0
        assert "owner_liveness: " not in capsys.readouterr().out
