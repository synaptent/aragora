"""Tests for the native mission CLI commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aragora.cli.commands.mission import (
    _admission_decision,
    _artifact_with_merge_packet_fields,
    _merge_packet_for_pr,
    _operator_tier_for,
    cmd_mission,
)
from aragora.cli.parser import build_parser
from aragora.missions import Feature, MissionState, Status, WorkArtifact


def test_mission_parser_accepts_public_subcommands(tmp_path: Path) -> None:
    parser = build_parser()
    state_path = tmp_path / "mission.json"

    seed = parser.parse_args(
        [
            "mission",
            "seed",
            "Refactor auth",
            "--state",
            str(state_path),
            "--budget",
            "150.50",
            "--max-hours",
            "6.5",
            "--relay",
            "slack",
            "--auto-settle-max-tier",
            "1",
            "--tracks",
            "sme,qa",
            "--paths",
            "aragora/missions,tests/missions",
        ]
    )
    assert seed.command == "mission"
    assert seed.mission_action == "seed"
    assert seed.goal == ["Refactor auth"]
    assert seed.state == str(state_path)
    assert seed.autonomy == "report"
    assert seed.admission_max_unresolved == 0
    assert seed.paths == "aragora/missions,tests/missions"

    run = parser.parse_args(
        [
            "mission",
            "run",
            "--state",
            str(state_path),
            "--autonomy",
            "auto-drain",
            "--max-ticks",
            "2",
        ]
    )
    assert run.mission_action == "run"
    assert run.state == str(state_path)
    assert run.autonomy == "auto-drain"
    assert run.max_ticks == 2

    reconcile = parser.parse_args(["mission", "reconcile", "--autonomy", "safe-clean"])
    assert reconcile.mission_action == "reconcile"
    assert reconcile.autonomy == "safe-clean"

    auto_drain = parser.parse_args(
        [
            "mission",
            "run",
            "--state",
            str(state_path),
            "--autonomy",
            "auto-drain",
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert auto_drain.repo_root == str(tmp_path)


def test_mission_parser_keeps_legacy_goal_alias() -> None:
    parser = build_parser()

    args = parser.parse_args(["mission", "Do something"])

    assert args.command == "mission"
    assert args.mission_action == "Do something"
    assert args.goal == []


def test_cmd_mission_without_action_reports_missing_seed_goal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser()
    args = parser.parse_args(["mission"])

    assert cmd_mission(args) == 1

    assert "mission seed requires a goal" in capsys.readouterr().err


def test_mission_parser_rejects_invalid_relay() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["mission", "seed", "goal", "--relay", "invalid-relay"])


def test_cmd_mission_seed_writes_native_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    monkeypatch.setattr("aragora.cli.commands.mission._load_artifacts", lambda *a, **k: [])
    parser = build_parser()
    state_path = tmp_path / "state.json"
    args = parser.parse_args(
        [
            "mission",
            "seed",
            "Refactor auth",
            "--state",
            str(state_path),
            "--budget",
            "50",
            "--relay",
            "email",
            "--tracks",
            "sme",
            "--paths",
            "./aragora/missions, tests/missions",
        ]
    )

    exit_code = cmd_mission(args)

    assert exit_code == 0
    loaded = MissionState.load(state_path)
    assert loaded.goal == "Refactor auth"
    assert loaded.features[0].metadata["budget_usd"] == 50.0
    assert loaded.features[0].metadata["relay"] == "email"
    assert loaded.features[0].metadata["tracks"] == ["sme"]
    assert loaded.features[0].metadata["paths"] == ["aragora/missions", "tests/missions"]
    assert loaded.features[0].metadata["admission_max_unresolved"] == 0
    captured = capsys.readouterr()
    assert "Seeded mission" in captured.out
    assert str(state_path) in captured.out


def test_cmd_mission_legacy_alias_seeds_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    monkeypatch.setattr("aragora.cli.commands.mission._load_artifacts", lambda *a, **k: [])
    parser = build_parser()
    state_path = tmp_path / "state.json"
    args = parser.parse_args(["mission", "Refactor auth", "--state", str(state_path)])

    assert cmd_mission(args) == 0
    assert MissionState.load(state_path).goal == "Refactor auth"
    assert "Seeded mission" in capsys.readouterr().out


def test_cmd_mission_seed_refuses_existing_state_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    monkeypatch.setattr("aragora.cli.commands.mission._load_artifacts", lambda *a, **k: [])
    parser = build_parser()
    state_path = tmp_path / "state.json"
    state_path.write_text('{"mission_id": "old"}', encoding="utf-8")
    args = parser.parse_args(["mission", "Refactor auth", "--state", str(state_path)])

    assert cmd_mission(args) == 1

    assert json.loads(state_path.read_text(encoding="utf-8"))["mission_id"] == "old"
    assert "refusing to overwrite" in capsys.readouterr().err


def test_cmd_mission_seed_blocks_producer_work_under_backlog_pressure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    fixture = tmp_path / "artifacts.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "artifact_id": "valuable",
                    "kind": "branch",
                    "clean": True,
                    "unique_commits": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    parser = build_parser()
    args = parser.parse_args(
        [
            "mission",
            "seed",
            "Build new dashboard",
            "--state",
            str(state_path),
            "--artifact-fixture",
            str(fixture),
        ]
    )

    assert cmd_mission(args) == 1

    assert not state_path.exists()
    assert "mission admission blocked" in capsys.readouterr().err


def test_admission_decision_includes_github_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def fake_load_artifacts(args, *, include_github, repo_root):
        calls.append(include_github)
        return []

    monkeypatch.setattr("aragora.cli.commands.mission._load_artifacts", fake_load_artifacts)
    monkeypatch.setattr(
        "aragora.cli.commands.mission._repo_root_for", lambda args, state_path: tmp_path
    )
    parser = build_parser()
    args = parser.parse_args(["mission", "seed", "Build new dashboard"])

    decision = _admission_decision(args, "Build new dashboard")

    assert decision.allowed
    assert calls == [True]


def test_cmd_mission_seed_allows_cleanup_goal_under_backlog_pressure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    fixture = tmp_path / "artifacts.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "artifact_id": "valuable",
                    "kind": "branch",
                    "clean": True,
                    "unique_commits": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    parser = build_parser()
    args = parser.parse_args(
        [
            "mission",
            "seed",
            "Reconcile and drain queued work",
            "--state",
            str(state_path),
            "--artifact-fixture",
            str(fixture),
        ]
    )

    assert cmd_mission(args) == 0

    assert MissionState.load(state_path).goal == "Reconcile and drain queued work"
    assert "Seeded mission" in capsys.readouterr().out


def test_cmd_mission_status_prints_progress(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "state.json"
    MissionState(
        mission_id="mission-test",
        goal="g",
        milestones=["m"],
        features=[
            Feature(id="done", description="done", milestone="m", status=Status.COMPLETED),
            Feature(id="blocked", description="blocked", milestone="m", status=Status.BLOCKED),
            Feature(id="parked", description="parked", milestone="m", status=Status.PARKED),
            Feature(id="terminal", description="terminal", milestone="m", status=Status.TERMINAL),
        ],
    ).save(state_path)
    parser = build_parser()
    args = parser.parse_args(["mission", "status", "--state", str(state_path)])

    assert cmd_mission(args) == 0

    out = capsys.readouterr().out
    assert "mission-test" in out
    assert "1/4 completed" in out
    assert "1 blocked" in out
    assert "1 parked" in out
    assert "1 terminal" in out


def test_cmd_mission_seed_refuses_when_native_mission_flag_is_off(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARAGORA_ENABLE_NATIVE_MISSION", raising=False)
    parser = build_parser()
    state_path = tmp_path / "state.json"
    args = parser.parse_args(["mission", "seed", "Refactor auth", "--state", str(state_path)])

    assert cmd_mission(args) == 1

    assert not state_path.exists()
    assert "Native mission engine is disabled" in capsys.readouterr().err


def test_cmd_mission_run_report_mode_does_not_mutate_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    state_path = tmp_path / "state.json"
    MissionState(
        mission_id="mission-test",
        goal="g",
        milestones=["m"],
        features=[Feature(id="f1", description="inspect", milestone="m")],
    ).save(state_path)
    parser = build_parser()
    args = parser.parse_args(
        ["mission", "run", "--state", str(state_path), "--autonomy", "report", "--max-ticks", "2"]
    )

    assert cmd_mission(args) == 1

    feature = MissionState.load(state_path).get("f1")
    assert feature.status == Status.PENDING
    assert feature.notes == ""
    assert "Mission run (report): no dispatch performed; 0/1 completed" in capsys.readouterr().out


def test_cmd_mission_auto_drain_parks_seeded_intake_without_branch_metadata(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # With the intake→decomposition bridge disabled (#8758 kill-switch), a
    # seeded intake still parks gracefully instead of hitting live git — and
    # per the #8758 design decision the park is RETRYABLE (Status.PARKED,
    # reconciler-owned), never terminal. The default (bridge ON) path is
    # covered by tests/missions/test_intake.py.
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    monkeypatch.setenv("ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE", "1")
    monkeypatch.setattr("aragora.cli.commands.mission._load_artifacts", lambda *a, **k: [])
    parser = build_parser()
    state_path = tmp_path / "state.json"
    seed = parser.parse_args(
        [
            "mission",
            "seed",
            "Refactor auth",
            "--state",
            str(state_path),
        ]
    )

    assert cmd_mission(seed) == 0

    run = parser.parse_args(
        [
            "mission",
            "run",
            "--state",
            str(state_path),
            "--autonomy",
            "auto-drain",
            "--max-ticks",
            "1",
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert cmd_mission(run) == 1

    feature = MissionState.load(state_path).features[0]
    assert feature.status == Status.PARKED  # retryable, reconciler-owned — not dead
    assert "metadata.branch" in feature.notes
    assert "metadata.branch" in feature.metadata["parked_reason"]
    assert "Mission run: 0/1 completed" in capsys.readouterr().out


def test_cmd_mission_run_refuses_paused_mission(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    state_path = tmp_path / "state.json"
    state_path.with_name("PAUSED").write_text("operator pause\n", encoding="utf-8")
    MissionState(
        mission_id="mission-test",
        goal="g",
        milestones=["m"],
        features=[Feature(id="f1", description="inspect", milestone="m")],
    ).save(state_path)
    parser = build_parser()
    args = parser.parse_args(["mission", "run", "--state", str(state_path)])

    assert cmd_mission(args) == 1

    assert MissionState.load(state_path).get("f1").status == Status.PENDING
    assert "mission is paused" in capsys.readouterr().err


def test_cmd_mission_resume_reclaims_under_owner_lock_and_crash_cap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    state_path = tmp_path / "state.json"
    MissionState(
        mission_id="mission-test",
        goal="g",
        milestones=["m"],
        features=[
            Feature(
                id="f1",
                description="inspect",
                milestone="m",
                status=Status.IN_PROGRESS,
                crash_count=4,
            )
        ],
    ).save(state_path)
    parser = build_parser()
    args = parser.parse_args(
        [
            "mission",
            "resume",
            "--state",
            str(state_path),
            "--autonomy",
            "auto-drain",
            "--max-ticks",
            "2",
        ]
    )

    assert cmd_mission(args) == 1

    feature = MissionState.load(state_path).get("f1")
    assert feature.status == Status.BLOCKED
    assert "crashed 4x" in feature.notes
    out = capsys.readouterr().out
    assert "Resume requested" in out
    assert "Mission run: 0/1 completed" in out


def test_auto_drain_operator_tier_honors_seeded_auto_settle_ceiling(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    MissionState(
        mission_id="mission-test",
        goal="g",
        milestones=["m"],
        features=[
            Feature(
                id="f1",
                description="inspect",
                milestone="m",
                metadata={"auto_settle_max_tier": 1},
            )
        ],
    ).save(state_path)
    parser = build_parser()
    args = parser.parse_args(
        [
            "mission",
            "run",
            "--state",
            str(state_path),
            "--autonomy",
            "auto-drain",
            "--auto-settle-max-tier",
            "2",
        ]
    )

    assert _operator_tier_for(args, state_path) == 2


def test_inventory_artifact_enrichment_uses_merge_packet_for_auto_drain(monkeypatch) -> None:
    artifact = WorkArtifact(
        "wt",
        kind="worktree",
        clean=True,
        open_pr=True,
        evidence=["inventory"],
    )
    candidate = {"git": {"head": "abc123"}, "links": {"open_prs": [{"number": 8655}]}}
    monkeypatch.setattr(
        "aragora.cli.commands.mission._merge_packet_for_pr",
        lambda pr, **kwargs: {
            "entries": [
                {
                    "pr_number": pr,
                    "head_sha": "abc123",
                    "tier": 2,
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "requires_human_preapproval": False,
                    "unresolved_dissent": False,
                    "check_surfaces": {"required_pr_checks": {"summary": "5/5 required green"}},
                }
            ]
        },
    )

    enriched = _artifact_with_merge_packet_fields(artifact, candidate)

    assert enriched.tier == 2
    assert enriched.head_sha == "abc123"
    assert enriched.checks_green
    assert enriched.quorum_satisfied
    assert "merge-packet PR 8655: satisfied / admin_squash_allowed" in enriched.evidence


def test_inventory_artifact_enrichment_refuses_human_blockers(monkeypatch) -> None:
    artifact = WorkArtifact("wt", kind="worktree", clean=True, open_pr=True)
    candidate = {"git": {"head": "abc123"}, "links": {"open_prs": [{"number": 8655}]}}
    monkeypatch.setattr(
        "aragora.cli.commands.mission._merge_packet_for_pr",
        lambda pr, **kwargs: {
            "entries": [
                {
                    "pr_number": pr,
                    "head_sha": "abc123",
                    "tier": 2,
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": True,
                    "requires_human_preapproval": False,
                    "unresolved_dissent": False,
                    "check_surfaces": {"required_pr_checks": {"summary": "5/5 required green"}},
                }
            ]
        },
    )

    enriched = _artifact_with_merge_packet_fields(artifact, candidate)

    assert enriched.checks_green
    assert not enriched.quorum_satisfied


def test_inventory_artifact_enrichment_requires_satisfied_packet(monkeypatch) -> None:
    artifact = WorkArtifact("wt", kind="worktree", clean=True, open_pr=True)
    candidate = {"git": {"head": "abc123"}, "links": {"open_prs": [{"number": 8655}]}}
    monkeypatch.setattr(
        "aragora.cli.commands.mission._merge_packet_for_pr",
        lambda pr, **kwargs: {
            "entries": [
                {
                    "pr_number": pr,
                    "head_sha": "abc123",
                    "tier": 2,
                    "status": "repair_or_wait",
                    "verdict": "not_ready_for_settlement",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "requires_human_preapproval": False,
                    "unresolved_dissent": False,
                    "check_surfaces": {"required_pr_checks": {"summary": "5/5 required green"}},
                }
            ]
        },
    )

    enriched = _artifact_with_merge_packet_fields(artifact, candidate)

    assert enriched.checks_green
    assert not enriched.quorum_satisfied


def test_inventory_artifact_enrichment_parks_missing_inventory_head(monkeypatch) -> None:
    artifact = WorkArtifact("wt", kind="worktree", clean=True, open_pr=True)
    candidate = {"links": {"open_prs": [{"number": 8655}]}}
    monkeypatch.setattr(
        "aragora.cli.commands.mission._merge_packet_for_pr",
        lambda pr, **kwargs: {
            "entries": [
                {
                    "pr_number": pr,
                    "head_sha": "abc123",
                    "tier": 2,
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "requires_human_preapproval": False,
                    "unresolved_dissent": False,
                    "check_surfaces": {"required_pr_checks": {"summary": "5/5 required green"}},
                }
            ]
        },
    )

    enriched = _artifact_with_merge_packet_fields(artifact, candidate)

    assert enriched.tier == 2
    assert enriched.head_sha == "abc123"
    assert not enriched.checks_green
    assert not enriched.quorum_satisfied
    assert "inventory omitted candidate head" in enriched.evidence[-1]


def test_inventory_artifact_enrichment_parks_stale_inventory_head(monkeypatch) -> None:
    artifact = WorkArtifact("wt", kind="worktree", clean=True, open_pr=True)
    candidate = {"git": {"head": "old123"}, "links": {"open_prs": [{"number": 8655}]}}
    monkeypatch.setattr(
        "aragora.cli.commands.mission._merge_packet_for_pr",
        lambda pr, **kwargs: {
            "entries": [
                {
                    "pr_number": pr,
                    "head_sha": "new456",
                    "tier": 2,
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "requires_human_preapproval": False,
                    "unresolved_dissent": False,
                    "check_surfaces": {"required_pr_checks": {"summary": "5/5 required green"}},
                }
            ]
        },
    )

    enriched = _artifact_with_merge_packet_fields(artifact, candidate)

    assert enriched.tier == 2
    assert enriched.head_sha == "old123"
    assert not enriched.checks_green
    assert not enriched.quorum_satisfied
    assert "inventory head old123 != packet head new456" in enriched.evidence[-1]


def test_merge_packet_for_pr_uses_explicit_repo_and_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], Path]] = []

    class Proc:
        returncode = 0
        stdout = '{"entries": [{"pr_number": 8655}]}'
        stderr = ""

    def fake_run(cmd, *, cwd, text, capture_output, check, timeout):
        calls.append((cmd, cwd))
        return Proc()

    monkeypatch.setattr("aragora.cli.commands.mission.subprocess.run", fake_run)

    payload = _merge_packet_for_pr(8655, repo_root=tmp_path, repo_slug="owner/repo")

    assert payload["entries"][0]["pr_number"] == 8655
    assert calls == [
        (
            [
                sys.executable,
                "-m",
                "aragora.cli.main",
                "review-queue",
                "merge-packet",
                "--pr",
                "8655",
                "--repo",
                "owner/repo",
                "--json",
            ],
            tmp_path,
        )
    ]


def test_cmd_mission_reconcile_outputs_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARAGORA_ENABLE_NATIVE_MISSION", "1")
    fixture = tmp_path / "artifacts.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "artifact_id": "wt-merged",
                    "kind": "worktree",
                    "clean": True,
                    "already_merged": True,
                },
                {"artifact_id": "wt-dirty", "kind": "worktree", "clean": False},
            ]
        ),
        encoding="utf-8",
    )
    parser = build_parser()
    args = parser.parse_args(
        [
            "mission",
            "reconcile",
            "--autonomy",
            "safe-clean",
            "--artifact-fixture",
            str(fixture),
            "--json",
        ]
    )

    assert cmd_mission(args) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "safe-clean"
    assert payload["mutations_executed"] is False
    assert [item["artifact_id"] for item in payload["authorized_cleanup"]] == ["wt-merged"]
    assert [item["artifact_id"] for item in payload["parked"]] == ["wt-dirty"]
