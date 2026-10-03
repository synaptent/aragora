"""Tests for ``scripts/fleet_sentinel.py`` — Dead Man's Signals fleet sentinel.

Plan v2 Phase 0.1 (Pillar 6). All checks are exercised through injected
fixture paths and injected command runners — no network, no live state.
"""

from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any


def _load_module(script_name: str) -> Any:
    here = Path(__file__).resolve()
    script_path = here.parents[2] / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(f"{script_name}_under_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sentinel = _load_module("fleet_sentinel.py")

NOW = sentinel.parse_iso("2026-06-10T12:00:00Z")
HOUR = 3600.0


def _init_repo_with_origin(
    path: Path, origin: str = "https://github.com/synaptent/aragora.git"
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    subprocess.run(
        ["git", "config", "remote.origin.url", origin],
        cwd=path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _touch(path: Path, *, age_hours: float = 0.0, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    ts = NOW.timestamp() - age_hours * HOUR
    os.utime(path, (ts, ts))
    return path


def _healthy_publisher_payload() -> dict[str, Any]:
    return {
        "generated_at": "2026-06-10T11:00:00Z",
        "github_health": {"auth_ok": True, "api_ok": True, "ready": True},
    }


# ---------------------------------------------------------------------------
# publisher_status
# ---------------------------------------------------------------------------


def test_publisher_status_ok(tmp_path: Path) -> None:
    p = _touch(tmp_path / "status.json", content=json.dumps(_healthy_publisher_payload()))
    result = sentinel.check_publisher_status(p, max_age_hours=24, now=NOW)
    assert result["check"] == "publisher_status"
    assert result["status"] == "ok"


def test_publisher_status_stale_mtime_breaches(tmp_path: Path) -> None:
    p = _touch(
        tmp_path / "status.json",
        age_hours=25,
        content=json.dumps(_healthy_publisher_payload()),
    )
    result = sentinel.check_publisher_status(p, max_age_hours=24, now=NOW)
    assert result["status"] == "breach"
    assert "stale" in result["detail"].lower() or "old" in result["detail"].lower()


def test_publisher_status_auth_not_ok_breaches(tmp_path: Path) -> None:
    payload = _healthy_publisher_payload()
    payload["github_health"]["auth_ok"] = False
    p = _touch(tmp_path / "status.json", content=json.dumps(payload))
    result = sentinel.check_publisher_status(p, max_age_hours=24, now=NOW)
    assert result["status"] == "breach"
    assert "auth_ok" in result["detail"]


def test_publisher_status_missing_file_breaches(tmp_path: Path) -> None:
    result = sentinel.check_publisher_status(tmp_path / "absent.json", max_age_hours=24, now=NOW)
    assert result["status"] == "breach"


def test_publisher_status_corrupt_json_breaches(tmp_path: Path) -> None:
    p = _touch(tmp_path / "status.json", content="{not json")
    result = sentinel.check_publisher_status(p, max_age_hours=24, now=NOW)
    assert result["status"] == "breach"


def test_breach_replay_may18_publisher_incident(tmp_path: Path) -> None:
    """Acceptance: replaying the real May-18 publisher status raises the alarm.

    Fixture replicates the status structure captured during the
    May-18 -> Jun-08 outage: ``auth_ok: false`` and ``generated_at``
    of 2026-05-18.  Even with a *fresh* file mtime the sentinel must breach.

    Provenance: the original incident snapshot lived at the old
    ``.aragora/automation-publisher-status.json`` path, whose writer moved
    away around 2026-05-24 (the file became an orphan).  The check now
    watches the live writer's path —
    ``.aragora/automation-github-status/latest.json``, written by
    ``scripts/cache_codex_automation_github_status.py`` on every publisher
    pass — which carries the same ``generated_at`` +
    ``github_health.auth_ok`` structure, so the breach semantics replayed
    here are unchanged.
    """
    incident = {
        "generated_at": "2026-05-18T15:10:46.775938Z",
        "github_health": {
            "api_ok": False,
            "auth_ok": False,
            "error": (
                "error connecting to api.github.com\n"
                "check your internet connection or https://githubstatus.com"
            ),
            "mode": "connectivity_failed",
            "ready": False,
        },
        "github_queue": {"available": False, "reason": "connectivity_failed"},
        "github_repo": "synaptent/aragora",
    }
    p = _touch(tmp_path / "latest.json", content=json.dumps(incident))
    result = sentinel.check_publisher_status(p, max_age_hours=24, now=NOW)
    assert result["status"] == "breach"
    assert "auth_ok" in result["detail"]


def test_publisher_status_default_is_live_cache_path() -> None:
    """The default must point at the live writer's file, not the orphan.

    The publisher's status writer moved to
    ``.aragora/automation-github-status/latest.json``
    (scripts/cache_codex_automation_github_status.py) around 2026-05-24;
    the old ``automation-publisher-status.json`` stopped being written.
    A sentinel watching the orphan would breach forever on stale data —
    or worse, report "ok" on a frozen healthy snapshot.
    """
    args = sentinel.build_parser().parse_args([])
    default = Path(args.publisher_status)
    assert default.parts[-3:] == (".aragora", "automation-github-status", "latest.json")


def test_stale_terminal_owner_defaults_use_automation_state_root(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    state_root = tmp_path / "shared-state"
    trusted_root = (state_root / ".aragora").resolve()
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(state_root))
    monkeypatch.setattr(
        sentinel,
        "_trusted_automation_state_roots",
        lambda repo_root: {trusted_root},
    )

    args = sentinel.build_parser().parse_args([])

    root = trusted_root
    assert Path(args.agent_bridge_lanes) == root / "agent-bridge" / "lanes.json"
    assert Path(args.agent_heartbeats) == root / "agent-bridge" / "heartbeats.json"
    assert Path(args.operator_steering_root) == root / "operator-steering"
    assert (
        Path(args.stale_terminal_owner_receipt_dir)
        == root / "agent-bridge" / "conflict-resolution-receipts"
    )


def test_automation_state_root_accepts_registered_worktree_checkout(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = tmp_path / "repo"
    shared = tmp_path / "shared-checkout"
    _init_repo_with_origin(repo)
    _init_repo_with_origin(shared, "git@github.com:synaptent/aragora.git")
    (shared / ".aragora").mkdir()
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(shared))
    monkeypatch.setattr(
        sentinel,
        "_registered_worktree_roots",
        lambda repo_root: {repo.resolve(), shared.resolve()},
    )

    assert sentinel._automation_state_root(repo) == (shared / ".aragora").resolve()


def test_automation_state_root_rejects_unregistered_same_origin_checkout(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = tmp_path / "repo"
    shared = tmp_path / "shared-checkout"
    _init_repo_with_origin(repo)
    _init_repo_with_origin(shared)
    (shared / ".aragora").mkdir()
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(shared))
    monkeypatch.setattr(sentinel, "_registered_worktree_roots", lambda repo_root: {repo.resolve()})

    try:
        sentinel._automation_state_root(repo)
    except ValueError as exc:
        assert "untrusted ARAGORA_AUTOMATION_STATE_ROOT" in str(exc)
        assert "registered worktree" in str(exc)
    else:
        raise AssertionError("unregistered same-origin automation state root was accepted")


def test_automation_state_root_rejects_different_origin_checkout(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = tmp_path / "repo"
    shared = tmp_path / "shared-checkout"
    _init_repo_with_origin(repo)
    _init_repo_with_origin(shared, "https://github.com/elsewhere/other.git")
    (shared / ".aragora").mkdir()
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(shared))

    try:
        sentinel._automation_state_root(repo)
    except ValueError as exc:
        assert "untrusted ARAGORA_AUTOMATION_STATE_ROOT" in str(exc)
    else:
        raise AssertionError("different-origin automation state root was accepted")


def test_automation_state_root_rejects_repo_subdirectory_bypass(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_origin(repo)
    subdir = repo / "nested"
    (subdir / ".aragora").mkdir(parents=True)
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(subdir))
    monkeypatch.setattr(sentinel, "_registered_worktree_roots", lambda repo_root: {repo.resolve()})

    try:
        sentinel._automation_state_root(repo)
    except ValueError as exc:
        assert "untrusted ARAGORA_AUTOMATION_STATE_ROOT" in str(exc)
    else:
        raise AssertionError("repo subdirectory automation state root was accepted")


def test_main_explicit_paths_survive_untrusted_automation_state_root(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(tmp_path / "attacker-state"))
    registry = tmp_path / "lanes.json"
    heartbeats = tmp_path / "heartbeats.json"
    steering = tmp_path / "operator-steering"
    receipts = tmp_path / "receipts"
    registry.write_text("[]", encoding="utf-8")
    heartbeats.write_text("[]", encoding="utf-8")
    steering.mkdir()
    receipts.mkdir()

    code = sentinel.main(
        [
            "--json",
            "--no-ledger",
            "--checks",
            "stale_terminal_owner",
            "--agent-bridge-lanes",
            str(registry),
            "--agent-heartbeats",
            str(heartbeats),
            "--operator-steering-root",
            str(steering),
            "--stale-terminal-owner-receipt-dir",
            str(receipts),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["checks"][0]["status"] == "ok"


def test_main_explicit_default_paths_survive_untrusted_automation_state_root(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(tmp_path / "attacker-state"))
    monkeypatch.setattr(
        sentinel,
        "_trusted_automation_state_roots",
        lambda repo_root: {(tmp_path / "repo" / ".aragora").resolve()},
    )
    canonical_root = (
        sentinel._canonical_repo_root(sentinel.DEFAULT_REPO_ROOT) / ".aragora"
    ).resolve()
    monkeypatch.setattr(
        sentinel,
        "check_stale_terminal_owner",
        lambda *args, **kwargs: sentinel._result("stale_terminal_owner", "ok", "called"),
    )

    code = sentinel.main(
        [
            "--json",
            "--no-ledger",
            "--checks",
            "stale_terminal_owner",
            "--agent-bridge-lanes",
            str(canonical_root / "agent-bridge" / "lanes.json"),
            "--agent-heartbeats",
            str(canonical_root / "agent-bridge" / "heartbeats.json"),
            "--operator-steering-root",
            str(canonical_root / "operator-steering"),
            "--stale-terminal-owner-receipt-dir",
            str(canonical_root / "agent-bridge" / "conflict-resolution-receipts"),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["checks"][0]["status"] == "ok"


def test_run_checks_infers_direct_namespace_explicit_paths(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    args = sentinel.build_parser().parse_args(["--checks", "stale_terminal_owner"])
    args.agent_bridge_lanes = str(tmp_path / "lanes.json")
    args.agent_heartbeats = str(tmp_path / "heartbeats.json")
    args.operator_steering_root = str(tmp_path / "operator-steering")
    args.stale_terminal_owner_receipt_dir = str(tmp_path / "receipts")
    args._automation_state_root_error = "untrusted state root"
    args._automation_state_root_default_paths = {
        "agent_bridge_lanes": "/attacker/.aragora/agent-bridge/lanes.json",
        "agent_heartbeats": "/attacker/.aragora/agent-bridge/heartbeats.json",
        "operator_steering_root": "/attacker/.aragora/operator-steering",
        "stale_terminal_owner_receipt_dir": (
            "/attacker/.aragora/agent-bridge/conflict-resolution-receipts"
        ),
    }
    called: dict[str, bool] = {}

    def fake_check(*args: Any, **kwargs: Any) -> dict[str, Any]:
        called["yes"] = True
        return sentinel._result("stale_terminal_owner", "ok", "called")

    monkeypatch.setattr(sentinel, "check_stale_terminal_owner", fake_check)

    checks = sentinel.run_checks(args, NOW)

    assert called == {"yes": True}
    assert checks == [sentinel._result("stale_terminal_owner", "ok", "called")]


def test_main_rejects_partial_explicit_paths_with_untrusted_automation_state_root(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(tmp_path / "attacker-state"))
    registry = tmp_path / "lanes.json"
    registry.write_text("[]", encoding="utf-8")

    code = sentinel.main(
        [
            "--json",
            "--no-ledger",
            "--checks",
            "stale_terminal_owner",
            "--agent-bridge-lanes",
            str(registry),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    check = report["checks"][0]
    assert check["status"] == "unknown"
    assert "invalid automation state root" in check["detail"]
    assert "agent_heartbeats" in check["detail"]
    assert "operator_steering_root" in check["detail"]
    assert "stale_terminal_owner_receipt_dir" in check["detail"]
    assert "agent_bridge_lanes" not in check["detail"]


def test_automation_state_root_rejects_untrusted_env_root(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    trusted_root = (tmp_path / "repo" / ".aragora").resolve()
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(tmp_path / "attacker-state"))
    monkeypatch.setattr(
        sentinel,
        "_trusted_automation_state_roots",
        lambda repo_root: {trusted_root},
    )

    try:
        sentinel._automation_state_root(tmp_path / "repo")
    except ValueError as exc:
        assert "untrusted ARAGORA_AUTOMATION_STATE_ROOT" in str(exc)
        assert str(trusted_root) in str(exc)
    else:
        raise AssertionError("untrusted automation state root was accepted")


def test_build_parser_fails_closed_when_untrusted_env_defaults_would_be_used(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    monkeypatch.setenv("ARAGORA_AUTOMATION_STATE_ROOT", str(tmp_path / "attacker-state"))
    monkeypatch.setattr(sentinel, "DEFAULT_REPO_ROOT", tmp_path / "repo")

    code = sentinel.main(["--json", "--no-ledger", "--checks", "stale_terminal_owner"])

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert report["checks"][0]["status"] == "unknown"
    assert "invalid automation state root" in report["checks"][0]["detail"]


def test_stale_terminal_owner_defaults_use_canonical_repo_root(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    canonical_root = tmp_path / "canonical-repo"
    monkeypatch.delenv("ARAGORA_AUTOMATION_STATE_ROOT", raising=False)
    monkeypatch.setattr(sentinel, "_canonical_repo_root", lambda path: canonical_root)

    args = sentinel.build_parser().parse_args([])

    root = canonical_root / ".aragora"
    assert Path(args.agent_bridge_lanes) == root / "agent-bridge" / "lanes.json"
    assert Path(args.agent_heartbeats) == root / "agent-bridge" / "heartbeats.json"
    assert Path(args.operator_steering_root) == root / "operator-steering"
    assert (
        Path(args.stale_terminal_owner_receipt_dir)
        == root / "agent-bridge" / "conflict-resolution-receipts"
    )


# ---------------------------------------------------------------------------
# boss_metrics_heartbeat
# ---------------------------------------------------------------------------


def test_boss_metrics_fresh_ok(tmp_path: Path) -> None:
    p = _touch(tmp_path / "boss_metrics.jsonl", age_hours=1)
    result = sentinel.check_boss_metrics(p, max_age_hours=48, now=NOW)
    assert result["status"] == "ok"


def test_boss_metrics_stale_breaches(tmp_path: Path) -> None:
    p = _touch(tmp_path / "boss_metrics.jsonl", age_hours=49)
    result = sentinel.check_boss_metrics(p, max_age_hours=48, now=NOW)
    assert result["status"] == "breach"


def test_boss_metrics_missing_breaches(tmp_path: Path) -> None:
    result = sentinel.check_boss_metrics(tmp_path / "absent.jsonl", max_age_hours=48, now=NOW)
    assert result["status"] == "breach"


# ---------------------------------------------------------------------------
# launchd_plists  (motivating incident: the empty boss-loop plist of 2026-06-10)
# ---------------------------------------------------------------------------


def _write_plist(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        plistlib.dump(payload, fh)
    return path


def test_launchd_plists_all_valid_ok(tmp_path: Path) -> None:
    _write_plist(tmp_path / "com.aragora.good.plist", {"Label": "com.aragora.good"})
    result = sentinel.check_launchd_plists(tmp_path)
    assert result["status"] == "ok"


def test_launchd_empty_plist_breaches(tmp_path: Path) -> None:
    _write_plist(tmp_path / "com.aragora.good.plist", {"Label": "com.aragora.good"})
    (tmp_path / "com.aragora.boss-loop.plist").write_bytes(b"")
    result = sentinel.check_launchd_plists(tmp_path)
    assert result["status"] == "breach"
    assert "com.aragora.boss-loop.plist" in result["detail"]


def test_launchd_unparseable_plist_breaches(tmp_path: Path) -> None:
    (tmp_path / "com.aragora.broken.plist").write_text("definitely not a plist")
    result = sentinel.check_launchd_plists(tmp_path)
    assert result["status"] == "breach"
    assert "com.aragora.broken.plist" in result["detail"]


def test_launchd_ignores_non_aragora_plists(tmp_path: Path) -> None:
    (tmp_path / "com.other.vendor.plist").write_bytes(b"")
    result = sentinel.check_launchd_plists(tmp_path)
    assert result["status"] == "ok"


def test_launchd_missing_dir_is_ok(tmp_path: Path) -> None:
    result = sentinel.check_launchd_plists(tmp_path / "absent")
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# gh_auth
# ---------------------------------------------------------------------------


def test_gh_auth_ok_with_zero_exit() -> None:
    result = sentinel.check_gh_auth(runner=lambda cmd: 0)
    assert result["status"] == "ok"


def test_gh_auth_nonzero_breaches() -> None:
    result = sentinel.check_gh_auth(runner=lambda cmd: 1)
    assert result["status"] == "breach"


def test_gh_auth_runner_exception_is_unknown() -> None:
    def boom(cmd: list[str]) -> int:
        raise FileNotFoundError("gh not installed")

    result = sentinel.check_gh_auth(runner=boom)
    assert result["status"] == "unknown"


# ---------------------------------------------------------------------------
# checkout_invariant
# ---------------------------------------------------------------------------


def test_checkout_on_main_ok(tmp_path: Path) -> None:
    result = sentinel.check_checkout_invariant(tmp_path, branch_reader=lambda repo: "main")
    assert result["status"] == "ok"


def test_checkout_off_main_breaches(tmp_path: Path) -> None:
    result = sentinel.check_checkout_invariant(tmp_path, branch_reader=lambda repo: "feature/x")
    assert result["status"] == "breach"
    assert "feature/x" in result["detail"]


def test_checkout_reader_failure_is_unknown(tmp_path: Path) -> None:
    def boom(repo: Path) -> str:
        raise subprocess.CalledProcessError(128, ["git"])

    result = sentinel.check_checkout_invariant(tmp_path, branch_reader=boom)
    assert result["status"] == "unknown"


# ---------------------------------------------------------------------------
# outbox_depth
# ---------------------------------------------------------------------------


def test_outbox_within_limits_ok(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    for i in range(3):
        _touch(outbox / f"item-{i}.json", age_hours=1)
    result = sentinel.check_outbox(outbox, max_items=50, max_age_days=7, now=NOW)
    assert result["status"] == "ok"
    assert result["depth"] == 3
    assert result["fingerprint"]


def test_outbox_depth_above_max_breaches(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    for i in range(4):
        _touch(outbox / f"item-{i}.json", age_hours=1)
    result = sentinel.check_outbox(outbox, max_items=3, max_age_days=7, now=NOW)
    assert result["status"] == "breach"
    assert "4" in result["detail"]
    assert result["depth"] == 4
    assert result["fingerprint"]


def test_outbox_archive_subdir_excluded(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    _touch(outbox / "live.json", age_hours=1)
    for i in range(10):
        _touch(outbox / "archive" / f"old-{i}.json", age_hours=1)
    result = sentinel.check_outbox(outbox, max_items=3, max_age_days=7, now=NOW)
    assert result["status"] == "ok"


def test_outbox_oldest_item_too_old_breaches(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    _touch(outbox / "ancient.json", age_hours=8 * 24)
    result = sentinel.check_outbox(outbox, max_items=50, max_age_days=7, now=NOW)
    assert result["status"] == "breach"
    assert "ancient.json" in result["detail"]
    assert "1 item(s) queued" in result["detail"]


def test_outbox_missing_dir_is_ok(tmp_path: Path) -> None:
    result = sentinel.check_outbox(tmp_path / "absent", max_items=50, max_age_days=7, now=NOW)
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# disk_free
# ---------------------------------------------------------------------------


class _Usage:
    def __init__(self, free_gib: float) -> None:
        self.total = 500 * 2**30
        self.used = self.total - int(free_gib * 2**30)
        self.free = int(free_gib * 2**30)


def test_disk_free_above_min_ok(tmp_path: Path) -> None:
    result = sentinel.check_disk_free(tmp_path, min_free_gib=25, usage_fn=lambda p: _Usage(100))
    assert result["status"] == "ok"


def test_disk_free_below_min_breaches(tmp_path: Path) -> None:
    result = sentinel.check_disk_free(tmp_path, min_free_gib=25, usage_fn=lambda p: _Usage(10))
    assert result["status"] == "breach"


# ---------------------------------------------------------------------------
# report / exit contract / ledger / notify
# ---------------------------------------------------------------------------


def _fixture_env(tmp_path: Path) -> dict[str, Path]:
    """A fully healthy filesystem fixture for end-to-end main() runs."""
    paths = {
        "publisher": _touch(
            tmp_path / "status.json", content=json.dumps(_healthy_publisher_payload())
        ),
        "metrics": _touch(tmp_path / "boss_metrics.jsonl", age_hours=1),
        "launch_agents": tmp_path / "LaunchAgents",
        "outbox": tmp_path / "outbox",
        "ledger": tmp_path / "ledger" / "ledger.jsonl",
    }
    _write_plist(paths["launch_agents"] / "com.aragora.ok.plist", {"Label": "ok"})
    _touch(paths["outbox"] / "one.json", age_hours=1)
    return paths


def _argv(paths: dict[str, Path], **overrides: Any) -> list[str]:
    argv = [
        "--json",
        "--now",
        "2026-06-10T12:00:00Z",
        "--publisher-status",
        str(paths["publisher"]),
        "--boss-metrics",
        str(paths["metrics"]),
        "--launch-agents-dir",
        str(paths["launch_agents"]),
        "--outbox-dir",
        str(paths["outbox"]),
        "--ledger",
        str(paths["ledger"]),
        "--checks",
        overrides.pop(
            "checks",
            "publisher_status,boss_metrics_heartbeat,launchd_plists,outbox_depth,disk_free",
        ),
    ]
    for key, value in overrides.items():
        argv.extend([f"--{key.replace('_', '-')}", str(value)])
    return argv


def test_main_all_ok_exits_zero_and_emits_contract(tmp_path: Path, capsys: Any) -> None:
    paths = _fixture_env(tmp_path)
    code = sentinel.main(_argv(paths))
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["generated_at"] == "2026-06-10T12:00:00Z"
    assert report["breaches"] == 0
    assert report["blind_checks"] == 0
    assert {c["check"] for c in report["checks"]} == {
        "publisher_status",
        "boss_metrics_heartbeat",
        "launchd_plists",
        "outbox_depth",
        "disk_free",
    }
    for check in report["checks"]:
        assert set(check) >= {"check", "status", "detail"}


def test_main_breach_exits_one(tmp_path: Path, capsys: Any) -> None:
    paths = _fixture_env(tmp_path)
    paths["publisher"].write_text(
        json.dumps({"generated_at": "2026-05-18T15:10:46Z", "github_health": {"auth_ok": False}})
    )
    code = sentinel.main(_argv(paths))
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["breaches"] >= 1


def test_main_unknown_exits_two_never_zero(tmp_path: Path, capsys: Any) -> None:
    """Silence/unknown is never success: an errored check forces exit 2."""
    paths = _fixture_env(tmp_path)
    code = sentinel.main(
        _argv(paths, checks="publisher_status,gh_auth", gh_auth_cmd="/nonexistent-gh-binary")
    )
    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["blind_checks"] >= 1


def test_unknown_takes_precedence_over_breach() -> None:
    checks = [
        {"check": "a", "status": "breach", "detail": "x"},
        {"check": "b", "status": "unknown", "detail": "y"},
    ]
    assert sentinel.exit_code_for(checks) == 2
    assert sentinel.exit_code_for(checks[:1]) == 1
    assert sentinel.exit_code_for([{"check": "c", "status": "ok", "detail": ""}]) == 0


def test_main_appends_ledger_line(tmp_path: Path, capsys: Any) -> None:
    paths = _fixture_env(tmp_path)
    assert sentinel.main(_argv(paths)) == 0
    assert sentinel.main(_argv(paths)) == 0
    capsys.readouterr()
    lines = paths["ledger"].read_text().strip().splitlines()
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["breaches"] == 0
    assert entry["generated_at"] == "2026-06-10T12:00:00Z"


def test_notify_cmd_invoked_with_breach_summary(tmp_path: Path, capsys: Any) -> None:
    paths = _fixture_env(tmp_path)
    paths["metrics"].unlink()  # boss_metrics breach
    record = tmp_path / "notify-args.json"
    recorder = tmp_path / "recorder.py"
    recorder.write_text(
        "import json, sys, pathlib\n"
        f"pathlib.Path({str(record)!r}).write_text(json.dumps(sys.argv[1:]))\n"
    )
    code = sentinel.main(_argv(paths, notify_cmd=f"{sys.executable} {recorder} {{summary}}"))
    assert code == 1
    capsys.readouterr()
    args = json.loads(record.read_text())
    assert len(args) == 1
    assert "boss_metrics_heartbeat" in args[0]


def test_notify_cmd_not_invoked_when_all_ok(tmp_path: Path, capsys: Any) -> None:
    paths = _fixture_env(tmp_path)
    record = tmp_path / "notify-args.json"
    recorder = tmp_path / "recorder.py"
    recorder.write_text(f"import pathlib\npathlib.Path({str(record)!r}).write_text('called')\n")
    code = sentinel.main(_argv(paths, notify_cmd=f"{sys.executable} {recorder} {{summary}}"))
    assert code == 0
    capsys.readouterr()
    assert not record.exists()


def test_notify_bare_placeholder_token_passes_summary_raw() -> None:
    """A standalone ``{summary}`` token is argv-level: pass the text through."""
    captured: dict[str, list[str]] = {}

    def runner(tokens: list[str]) -> int:
        captured["tokens"] = tokens
        return 0

    sentinel.notify("notifier --msg {summary}", 'has "quotes" and \\slash', runner=runner)
    assert captured["tokens"] == ["notifier", "--msg", 'has "quotes" and \\slash']


# ---------------------------------------------------------------------------
# lane_liveness  (failure class A: the silent c06/c07/c08 lane deaths of
# 2026-06-10/11 — three coordinator-spawned lanes died at setup, left empty
# branches on origin, and nobody noticed until a manual morning sweep)
# ---------------------------------------------------------------------------


def _write_lane_ledger(
    lanes_dir: Path,
    lane: str,
    *,
    branch: str,
    launched_at: str,
    status: str = "in_progress",
) -> Path:
    lanes_dir.mkdir(parents=True, exist_ok=True)
    path = lanes_dir / f"{lane}.json"
    path.write_text(
        json.dumps(
            {
                "lane": lane,
                "agent_id": "a0000000000000000",
                "branch": branch,
                "brief": f"brief for {lane}",
                "launched_at": launched_at,
                "status": status,
            }
        )
    )
    return path


def _liveness(
    lanes_dir: Path,
    *,
    heads: dict[str, str],
    ahead: dict[str, int | None],
    dates: dict[str, str] | None = None,
    lane_max_age_hours: float = 3.0,
    orphan_age_hours: float = 24.0,
) -> Any:
    date_map = {sha: sentinel.parse_iso(d) for sha, d in (dates or {}).items()}
    return sentinel.check_lane_liveness(
        str(lanes_dir),
        lane_max_age_hours=lane_max_age_hours,
        orphan_age_hours=orphan_age_hours,
        now=NOW,
        remote_heads=lambda: heads,
        ahead_counter=lambda sha: ahead.get(sha),
        commit_dater=lambda sha: date_map.get(sha),
    )


def test_lane_liveness_fresh_in_progress_ok(tmp_path: Path) -> None:
    _write_lane_ledger(tmp_path, "q2", branch="elves/run-x-q2", launched_at="2026-06-10T11:00:00Z")
    result = _liveness(tmp_path, heads={"elves/run-x-q2": "aaa"}, ahead={"aaa": 0})
    assert result["status"] == "ok"


def test_lane_liveness_stale_zero_ahead_breaches(tmp_path: Path) -> None:
    _write_lane_ledger(tmp_path, "q2", branch="elves/run-x-q2", launched_at="2026-06-10T07:00:00Z")
    result = _liveness(tmp_path, heads={"elves/run-x-q2": "aaa"}, ahead={"aaa": 0})
    assert result["status"] == "breach"
    assert "q2" in result["detail"]
    assert "zero commits ahead" in result["detail"]


def test_lane_liveness_stale_branch_absent_breaches(tmp_path: Path) -> None:
    _write_lane_ledger(tmp_path, "q2", branch="elves/run-x-q2", launched_at="2026-06-10T07:00:00Z")
    result = _liveness(tmp_path, heads={}, ahead={})
    assert result["status"] == "breach"
    assert "absent from origin" in result["detail"]


def test_lane_liveness_stale_with_commits_ok(tmp_path: Path) -> None:
    _write_lane_ledger(tmp_path, "q2", branch="elves/run-x-q2", launched_at="2026-06-10T07:00:00Z")
    result = _liveness(tmp_path, heads={"elves/run-x-q2": "aaa"}, ahead={"aaa": 2})
    assert result["status"] == "ok"


def test_lane_liveness_unresolvable_ahead_is_not_dead(tmp_path: Path) -> None:
    """None from the ahead counter means unfetched unique commits — never dead."""
    _write_lane_ledger(tmp_path, "q2", branch="elves/run-x-q2", launched_at="2026-06-10T07:00:00Z")
    result = _liveness(tmp_path, heads={"elves/run-x-q2": "aaa"}, ahead={"aaa": None})
    assert result["status"] == "ok"


def test_lane_liveness_non_in_progress_ignored(tmp_path: Path) -> None:
    _write_lane_ledger(
        tmp_path,
        "q2",
        branch="elves/run-x-q2",
        launched_at="2026-06-10T07:00:00Z",
        status="dead",
    )
    result = _liveness(tmp_path, heads={}, ahead={})
    assert result["status"] == "ok"


def test_lane_liveness_legacy_done_state_without_launched_at_ignored(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "laneOUTBOX.json").write_text(
        json.dumps({"lane": "laneOUTBOX", "state": "done", "started_at": "2026-06-10T07:00:00Z"})
    )

    result = _liveness(tmp_path, heads={}, ahead={})

    assert result["status"] == "ok"


def test_lane_liveness_null_status_falls_back_to_legacy_state(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "laneOUTBOX.json").write_text(
        json.dumps({"lane": "laneOUTBOX", "status": None, "state": "done"})
    )

    result = _liveness(tmp_path, heads={}, ahead={})

    assert result["status"] == "ok"


def test_lane_liveness_legacy_in_progress_uses_started_at(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "legacy-active.json").write_text(
        json.dumps(
            {
                "lane": "q2",
                "state": "in_progress",
                "started_at": "2026-06-10T07:00:00Z",
                "branch": "elves/run-x-q2",
            }
        )
    )

    result = _liveness(tmp_path, heads={"elves/run-x-q2": "aaa"}, ahead={"aaa": 0})

    assert result["status"] == "breach"
    assert "zero commits ahead" in result["detail"]


def test_lane_liveness_legacy_parked_state_without_launched_at_ignored(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "lanePARITY.json").write_text(
        json.dumps({"lane": "PARITY", "state": "parked_awaiting_human_settlement"})
    )

    result = _liveness(tmp_path, heads={}, ahead={})

    assert result["status"] == "ok"


def test_lane_liveness_missing_status_and_state_is_unknown(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "missing-status.json").write_text(
        json.dumps(
            {
                "lane": "q2",
                "launched_at": "2026-06-10T11:00:00Z",
                "branch": "elves/run-x-q2",
            }
        )
    )

    result = _liveness(tmp_path, heads={"elves/run-x-q2": "aaa"}, ahead={"aaa": 0})

    assert result["status"] == "unknown"
    assert "missing-status.json" in result["detail"]


def test_lane_liveness_pr_open_status_without_launched_at_ignored(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "lanePROD.json").write_text(json.dumps({"lane": "PROD", "status": "pr_open"}))

    result = _liveness(tmp_path, heads={}, ahead={})

    assert result["status"] == "ok"


def test_lane_liveness_in_progress_missing_launched_at_is_unknown(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "missing-timestamp.json").write_text(
        json.dumps({"lane": "q2", "status": "in_progress"})
    )

    result = _liveness(tmp_path, heads={}, ahead={})

    assert result["status"] == "unknown"
    assert "missing-timestamp.json" in result["detail"]


def test_lane_liveness_in_progress_invalid_launched_at_is_unknown(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "invalid-timestamp.json").write_text(
        json.dumps({"lane": "q2", "status": "in_progress", "launched_at": "not-a-time"})
    )

    result = _liveness(tmp_path, heads={}, ahead={})

    assert result["status"] == "unknown"
    assert "invalid-timestamp.json" in result["detail"]


def test_lane_liveness_orphan_branch_breaches(tmp_path: Path) -> None:
    result = _liveness(
        tmp_path,
        heads={"elves/run-20260610-c06-dead": "aaa"},
        ahead={"aaa": 0},
        dates={"aaa": "2026-06-09T06:00:00Z"},  # 30h old at NOW
    )
    assert result["status"] == "breach"
    assert "orphan branch elves/run-20260610-c06-dead" in result["detail"]


def test_lane_liveness_boss_pattern_orphan_breaches(tmp_path: Path) -> None:
    result = _liveness(
        tmp_path,
        heads={"aragora/boss-harvest/issue-1-boss-x": "bbb"},
        ahead={"bbb": 0},
        dates={"bbb": "2026-06-08T12:00:00Z"},
    )
    assert result["status"] == "breach"


def test_lane_liveness_young_empty_branch_ok(tmp_path: Path) -> None:
    result = _liveness(
        tmp_path,
        heads={"elves/run-x-young": "aaa"},
        ahead={"aaa": 0},
        dates={"aaa": "2026-06-10T10:00:00Z"},  # 2h old
    )
    assert result["status"] == "ok"


def test_lane_liveness_old_branch_with_commits_ok(tmp_path: Path) -> None:
    result = _liveness(
        tmp_path,
        heads={"elves/run-x-real-work": "aaa"},
        ahead={"aaa": 1},
        dates={"aaa": "2026-06-01T00:00:00Z"},
    )
    assert result["status"] == "ok"


def test_lane_liveness_non_pattern_branch_ignored(tmp_path: Path) -> None:
    result = _liveness(
        tmp_path,
        heads={"feature/unrelated": "aaa"},
        ahead={"aaa": 0},
        dates={"aaa": "2026-06-01T00:00:00Z"},
    )
    assert result["status"] == "ok"


def test_lane_liveness_remote_failure_is_unknown(tmp_path: Path) -> None:
    def boom() -> dict[str, str]:
        raise subprocess.CalledProcessError(128, ["git"])

    result = sentinel.check_lane_liveness(
        str(tmp_path),
        lane_max_age_hours=3,
        orphan_age_hours=24,
        now=NOW,
        remote_heads=boom,
        ahead_counter=lambda sha: 0,
        commit_dater=lambda sha: None,
    )
    assert result["status"] == "unknown"


def test_lane_liveness_unreadable_ledger_is_unknown(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "broken.json").write_text("{not json")
    result = _liveness(tmp_path, heads={}, ahead={})
    assert result["status"] == "unknown"
    assert "broken.json" in result["detail"]


def test_breach_replay_jun10_silent_lane_death(tmp_path: Path) -> None:
    """Acceptance: replaying the real 2026-06-10/11 incident raises the alarm.

    Three coordinator-spawned lanes (c06/c07/c08) died at setup overnight.
    Their branches sat on origin with zero commits ahead of main until a
    manual morning sweep found them.  With ledgers present the ledger rule
    fires; without ledgers (as on the real morning after) the orphan-branch
    rule fires for every one of them.
    """
    heads = {
        "elves/run-20260610-c06-mixed-family-fix": "c06sha",
        "elves/run-20260610-c07-auto-evidence": "c07sha",
        "elves/run-20260610-c08-b1-retrigger": "c08sha",
    }
    ahead: dict[str, int | None] = {"c06sha": 0, "c07sha": 0, "c08sha": 0}
    dates = dict.fromkeys(ahead, "2026-06-09T02:00:00Z")  # ~34h old at NOW
    # Ledger-less variant (the real morning-after state):
    result = _liveness(tmp_path / "lanes", heads=heads, ahead=ahead, dates=dates)
    assert result["status"] == "breach"
    for branch in heads:
        assert branch in result["detail"]
    # Ledger-present variant: the ledger rule also catches each lane.
    lanes = tmp_path / "run-20260610" / "lanes"
    for lane, branch in (
        ("c06", "elves/run-20260610-c06-mixed-family-fix"),
        ("c07", "elves/run-20260610-c07-auto-evidence"),
        ("c08", "elves/run-20260610-c08-b1-retrigger"),
    ):
        _write_lane_ledger(lanes, lane, branch=branch, launched_at="2026-06-09T02:00:00Z")
    result = _liveness(lanes, heads=heads, ahead=ahead, dates=dates)
    assert result["status"] == "breach"
    assert result["detail"].count("lane c0") == 3


# ---------------------------------------------------------------------------
# stale_terminal_owner (#8562: stale owners blocking terminal PRs)
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _stale_owner_result(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    *,
    pr_state: dict[str, Any],
    findings: list[dict[str, Any]] | None = None,
    min_age_hours: float = 24.0,
) -> Any:
    registry = _write_json(tmp_path / "lanes.json", rows)
    audit_calls: list[int] = []

    def fetch_state(pr: int, *, repo_slug: str, gh_bin: str) -> dict[str, Any]:
        assert repo_slug == "synaptent/aragora"
        assert gh_bin == "gh"
        return {"available": True, "number": pr, **pr_state}

    def audit_terminal(**kwargs: Any) -> dict[str, Any]:
        audit_calls.append(kwargs["pr"])
        return {
            "github_state": {"available": True, "state": "MERGED"},
            "findings": findings if findings is not None else [],
        }

    result = sentinel.check_stale_terminal_owner(
        registry,
        receipt_dir=tmp_path / "receipts",
        heartbeat_path=tmp_path / "heartbeats.json",
        steering_inbox_root=tmp_path / "operator-steering",
        min_age_hours=min_age_hours,
        now=NOW,
        repo_slug="synaptent/aragora",
        pr_state_fetcher=fetch_state,
        terminal_owner_auditor=audit_terminal,
    )
    return result, audit_calls


def _active_owner_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "lane_id": "Q900-stale-terminal",
        "owner_session": "codex-owner",
        "status": "active",
        "pr_number": 9001,
        "branch": "codex/stale-terminal-demo",
        "updated_at": "2026-06-08T12:00:00Z",
    }
    row.update(overrides)
    return row


def test_stale_terminal_owner_missing_registry_is_ok_skipped(tmp_path: Path) -> None:
    result = sentinel.check_stale_terminal_owner(
        tmp_path / "missing-lanes.json",
        receipt_dir=tmp_path / "receipts",
        heartbeat_path=tmp_path / "heartbeats.json",
        steering_inbox_root=tmp_path / "operator-steering",
        min_age_hours=24.0,
        now=NOW,
        repo_slug="synaptent/aragora",
        pr_state_fetcher=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("no PR state fetch")
        ),
        terminal_owner_auditor=lambda **kwargs: (_ for _ in ()).throw(AssertionError("no audit")),
    )

    assert result["status"] == "ok"
    assert "agent-bridge state absent" in result["detail"]


def test_stale_terminal_owner_invalid_registry_stays_unknown(tmp_path: Path) -> None:
    registry = tmp_path / "lanes.json"
    registry.write_text("{not json", encoding="utf-8")

    result = sentinel.check_stale_terminal_owner(
        registry,
        receipt_dir=tmp_path / "receipts",
        heartbeat_path=tmp_path / "heartbeats.json",
        steering_inbox_root=tmp_path / "operator-steering",
        min_age_hours=24.0,
        now=NOW,
        repo_slug="synaptent/aragora",
        pr_state_fetcher=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("no PR state fetch")
        ),
        terminal_owner_auditor=lambda **kwargs: (_ for _ in ()).throw(AssertionError("no audit")),
    )

    assert result["status"] == "unknown"
    assert "lane registry unreadable" in result["detail"]


def test_stale_terminal_owner_reports_safe_merged_pr_with_guarded_commands(
    tmp_path: Path,
) -> None:
    result, audit_calls = _stale_owner_result(
        tmp_path,
        [_active_owner_row()],
        pr_state={
            "state": "MERGED",
            "merge_commit": "abc123",
            "url": "https://github.test/pr/9001",
        },
        findings=[
            {
                "lane_id": "Q900-stale-terminal",
                "owner_session": "codex-owner",
                "terminal_safety_blockers": [],
                "terminal_safety_details": {},
            }
        ],
    )

    assert result["status"] == "breach"
    assert audit_calls == [9001]
    assert result["candidates"][0] == {
        "lane_id": "Q900-stale-terminal",
        "pr_number": 9001,
        "branch": "codex/stale-terminal-demo",
        "owner_session": "codex-owner",
        "age_hours": 48.0,
        "terminal_state": "MERGED",
        "terminal_url": "https://github.test/pr/9001",
        "merge_commit": "abc123",
        "terminal_safety_blockers": [],
        "terminal_safety_details": {},
        "reconciler_dry_run_command": result["candidates"][0]["reconciler_dry_run_command"],
        "reconciler_apply_command": result["candidates"][0]["reconciler_apply_command"],
    }
    assert (
        "resolve_lane_conflicts.py --merged-pr-lane-audit"
        in result["candidates"][0]["reconciler_dry_run_command"]
    )
    assert "--expected-merge-commit abc123" in result["candidates"][0]["reconciler_apply_command"]
    assert "--operator-authorized" in result["candidates"][0]["reconciler_apply_command"]
    assert "--apply --json" in result["candidates"][0]["reconciler_apply_command"]


def test_stale_terminal_owner_passes_repo_scoped_state_to_terminal_auditor(
    tmp_path: Path,
) -> None:
    registry = _write_json(tmp_path / "lanes.json", [_active_owner_row()])
    seen_state: dict[str, Any] = {}

    def fetch_state(pr: int, *, repo_slug: str, gh_bin: str) -> dict[str, Any]:
        assert repo_slug == "synaptent/aragora"
        assert gh_bin == "gh"
        return {
            "available": True,
            "number": pr,
            "state": "MERGED",
            "merge_commit": "repo-scoped-merge",
            "url": "https://github.test/pr/9001",
        }

    def audit_terminal(**kwargs: Any) -> dict[str, Any]:
        seen_state.update(kwargs["github_state"])
        return {
            "github_state": kwargs["github_state"],
            "findings": [
                {
                    "lane_id": "Q900-stale-terminal",
                    "owner_session": "codex-owner",
                    "terminal_safety_blockers": [],
                    "terminal_safety_details": {},
                }
            ],
        }

    result = sentinel.check_stale_terminal_owner(
        registry,
        receipt_dir=tmp_path / "receipts",
        heartbeat_path=tmp_path / "heartbeats.json",
        steering_inbox_root=tmp_path / "operator-steering",
        min_age_hours=24.0,
        now=NOW,
        repo_slug="synaptent/aragora",
        pr_state_fetcher=fetch_state,
        terminal_owner_auditor=audit_terminal,
    )

    assert seen_state["merge_commit"] == "repo-scoped-merge"
    assert result["status"] == "breach"
    assert (
        "--expected-merge-commit repo-scoped-merge"
        in result["candidates"][0]["reconciler_apply_command"]
    )


def test_stale_terminal_owner_suppresses_fresh_heartbeat_rows(tmp_path: Path) -> None:
    result, audit_calls = _stale_owner_result(
        tmp_path,
        [_active_owner_row()],
        pr_state={"state": "MERGED", "merge_commit": "abc123"},
        findings=[
            {
                "lane_id": "Q900-stale-terminal",
                "owner_session": "codex-owner",
                "terminal_safety_blockers": ["fresh_heartbeat"],
                "terminal_safety_details": {"fresh_heartbeat_timestamps": ["2026-06-10T11:59:00Z"]},
            }
        ],
    )

    assert audit_calls == [9001]
    assert result["status"] == "ok"
    assert result["candidates"] == []
    assert result["live_suppressed"][0]["terminal_safety_blockers"] == ["fresh_heartbeat"]


def test_stale_terminal_owner_reports_api_unknown_as_unknown(tmp_path: Path) -> None:
    registry = _write_json(tmp_path / "lanes.json", [_active_owner_row()])

    def fetch_state(pr: int, *, repo_slug: str, gh_bin: str) -> dict[str, Any]:
        return {"available": False, "number": pr, "state": "UNKNOWN", "error": "HTTP 502"}

    result = sentinel.check_stale_terminal_owner(
        registry,
        receipt_dir=tmp_path / "receipts",
        heartbeat_path=tmp_path / "heartbeats.json",
        steering_inbox_root=tmp_path / "operator-steering",
        min_age_hours=24.0,
        now=NOW,
        repo_slug="synaptent/aragora",
        pr_state_fetcher=fetch_state,
        terminal_owner_auditor=lambda **kwargs: (_ for _ in ()).throw(AssertionError("no audit")),
    )

    assert result["status"] == "unknown"
    assert "HTTP 502" in result["detail"]


def test_stale_terminal_owner_reports_unsafe_mailbox_and_local_work_blockers(
    tmp_path: Path,
) -> None:
    result, _ = _stale_owner_result(
        tmp_path,
        [
            _active_owner_row(lane_id="Q-mailbox", owner_session="owner-mailbox"),
            _active_owner_row(lane_id="Q-local-work", owner_session="owner-local-work"),
        ],
        pr_state={"state": "MERGED", "merge_commit": "abc123"},
        findings=[
            {
                "lane_id": "Q-mailbox",
                "owner_session": "owner-mailbox",
                "terminal_safety_blockers": ["unread_mailbox"],
                "terminal_safety_details": {"pending_mailbox_messages": ["message.json"]},
            },
            {
                "lane_id": "Q-local-work",
                "owner_session": "owner-local-work",
                "terminal_safety_blockers": ["local_work_claim"],
                "terminal_safety_details": {"local_work_claims": ["/tmp/work"]},
            },
        ],
    )

    assert result["status"] == "breach"
    blockers = {
        candidate["lane_id"]: candidate["terminal_safety_blockers"]
        for candidate in result["candidates"]
    }
    assert blockers == {
        "Q-mailbox": ["unread_mailbox"],
        "Q-local-work": ["local_work_claim"],
    }
    assert all(not candidate["reconciler_apply_command"] for candidate in result["candidates"])


def test_stale_terminal_owner_reports_closed_pr_without_apply_command(tmp_path: Path) -> None:
    result, audit_calls = _stale_owner_result(
        tmp_path,
        [_active_owner_row()],
        pr_state={"state": "CLOSED", "merge_commit": "", "url": "https://github.test/pr/9001"},
    )

    assert audit_calls == []
    assert result["status"] == "breach"
    assert result["candidates"][0]["terminal_state"] == "CLOSED"
    assert result["candidates"][0]["terminal_safety_blockers"] == ["closed_pr_manual_review"]
    assert result["candidates"][0]["reconciler_dry_run_command"]
    assert result["candidates"][0]["reconciler_apply_command"] == ""


def test_default_pr_state_fetcher_times_out_fail_closed(monkeypatch: Any) -> None:
    def run_timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", ["gh"]), timeout=0.01)

    monkeypatch.setattr(sentinel.subprocess, "run", run_timeout)

    result = sentinel._default_pr_state_fetcher(
        9001,
        repo_slug="synaptent/aragora",
        gh_bin="gh",
        timeout_seconds=0.01,
    )

    assert result["available"] is False
    assert result["state"] == "UNKNOWN"
    assert "TimeoutExpired" in result["error"]


def test_default_pr_state_fetcher_rejects_unsafe_repo_slug(monkeypatch: Any) -> None:
    def run_should_not_execute(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unsafe repo slug must not reach subprocess")

    monkeypatch.setattr(sentinel.subprocess, "run", run_should_not_execute)

    result = sentinel._default_pr_state_fetcher(
        9001,
        repo_slug="synaptent/aragora --json files",
        gh_bin="gh",
    )

    assert result["available"] is False
    assert "repo_slug" in result["error"]
    assert result["command"] == []


def test_default_pr_state_fetcher_rejects_unsafe_gh_bin(monkeypatch: Any) -> None:
    def run_should_not_execute(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("unsafe gh_bin must not reach subprocess")

    monkeypatch.setattr(sentinel.subprocess, "run", run_should_not_execute)

    result = sentinel._default_pr_state_fetcher(
        9001,
        repo_slug="synaptent/aragora",
        gh_bin="sh -c gh",
    )

    assert result["available"] is False
    assert "gh_bin" in result["error"]
    assert result["command"] == []


def test_validate_gh_bin_accepts_absolute_gh_executable(tmp_path: Path) -> None:
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gh.chmod(0o755)

    assert sentinel._validate_gh_bin(str(gh)) == str(gh.resolve())


def test_validate_gh_bin_accepts_absolute_executable_wrapper(tmp_path: Path) -> None:
    wrapper = tmp_path / "gh-wrapper"
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)

    assert sentinel._validate_gh_bin(str(wrapper)) == str(wrapper.resolve())


def test_validate_gh_bin_accepts_relative_executable_wrapper(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    wrapper = tools / "gh"
    wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    monkeypatch.chdir(tmp_path)

    assert sentinel._validate_gh_bin("./tools/gh") == str(wrapper.resolve())


def test_split_operator_command_rejects_malformed_template() -> None:
    try:
        sentinel._split_operator_command(
            'gh auth status "unterminated', option_name="--gh-auth-cmd"
        )
    except ValueError as exc:
        assert "--gh-auth-cmd" in str(exc)
    else:
        raise AssertionError("malformed command template was accepted")


def test_stale_terminal_owner_rejects_invalid_repo_before_fetch(tmp_path: Path) -> None:
    registry = _write_json(tmp_path / "lanes.json", [_active_owner_row()])

    result = sentinel.check_stale_terminal_owner(
        registry,
        receipt_dir=tmp_path / "receipts",
        heartbeat_path=tmp_path / "heartbeats.json",
        steering_inbox_root=tmp_path / "operator-steering",
        min_age_hours=24.0,
        now=NOW,
        repo_slug="../aragora",
        pr_state_fetcher=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("invalid repo_slug must not reach fetcher")
        ),
        terminal_owner_auditor=lambda **kwargs: (_ for _ in ()).throw(AssertionError("no audit")),
    )

    assert result["status"] == "unknown"
    assert "invalid GitHub CLI configuration" in result["detail"]


def test_resolver_loader_rejects_untrusted_scripts_dir(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(sentinel, "_RESOLVER_MODULE", None)
    (tmp_path / "resolve_lane_conflicts.py").write_text(
        "ACTIVE_STATUSES = set()\n", encoding="utf-8"
    )
    monkeypatch.setattr(sentinel, "SCRIPTS_DIR", tmp_path)

    try:
        sentinel._trusted_resolver_path()
    except RuntimeError as exc:
        assert "scripts directory does not match canonical repo" in str(exc)
    else:
        raise AssertionError("untrusted resolver scripts directory was accepted")


def test_stale_terminal_owner_unknown_timestamp_precedes_stale_rows(tmp_path: Path) -> None:
    result, audit_calls = _stale_owner_result(
        tmp_path,
        [
            _active_owner_row(lane_id="Q-stale", owner_session="owner-stale"),
            _active_owner_row(
                lane_id="Q-no-time",
                owner_session="owner-no-time",
                updated_at="",
            ),
        ],
        pr_state={"state": "CLOSED", "merge_commit": "", "url": "https://github.test/pr/9001"},
    )

    assert audit_calls == []
    assert result["status"] == "unknown"
    assert "no comparable timestamp" in result["detail"]
    assert result["candidates"][0]["lane_id"] == "Q-stale"


def test_stale_terminal_owner_missing_audit_finding_blocks_apply(tmp_path: Path) -> None:
    result, audit_calls = _stale_owner_result(
        tmp_path,
        [_active_owner_row()],
        pr_state={
            "state": "MERGED",
            "merge_commit": "abc123",
            "url": "https://github.test/pr/9001",
        },
        findings=[],
    )

    assert audit_calls == [9001]
    assert result["status"] == "breach"
    assert result["candidates"][0]["terminal_safety_blockers"] == ["missing_reconciler_finding"]
    assert result["candidates"][0]["reconciler_apply_command"] == ""


def test_stale_terminal_owner_uses_resolver_active_statuses(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    class FakeResolver:
        ACTIVE_STATUSES = {"leased"}

    monkeypatch.setattr(sentinel, "_load_resolver_module", lambda: FakeResolver())
    registry = _write_json(
        tmp_path / "lanes.json",
        [_active_owner_row(status="leased")],
    )

    def fetch_state(pr: int, *, repo_slug: str, gh_bin: str) -> dict[str, Any]:
        return {
            "available": True,
            "number": pr,
            "state": "CLOSED",
            "merge_commit": "",
            "url": "https://github.test/pr/9001",
        }

    result = sentinel.check_stale_terminal_owner(
        registry,
        receipt_dir=tmp_path / "receipts",
        heartbeat_path=tmp_path / "heartbeats.json",
        steering_inbox_root=tmp_path / "operator-steering",
        min_age_hours=24.0,
        now=NOW,
        repo_slug="synaptent/aragora",
        pr_state_fetcher=fetch_state,
        terminal_owner_auditor=lambda **kwargs: (_ for _ in ()).throw(AssertionError("no audit")),
    )

    assert result["status"] == "breach"
    assert result["candidates"][0]["terminal_safety_blockers"] == ["closed_pr_manual_review"]


def test_default_terminal_owner_auditor_uses_no_lock_read_only_path(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    class FakeResolver:
        ACTIVE_STATUSES = {"active"}

        def _utc_now_iso(self) -> str:
            return "2026-06-10T12:00:00Z"

        def _parse_timestamp(self, value: str) -> float:
            return NOW.timestamp()

        def _fetch_pr_state(self, *, pr: int, gh_bin: str) -> dict[str, Any]:
            raise AssertionError("sentinel must reuse its repo-scoped PR state")

        def _read_rows_checked(self, path: Path) -> tuple[list[dict[str, Any]], str | None]:
            if path.name == "lanes.json":
                return [_active_owner_row()], None
            return [], None

        def _active_pr_lane_findings(
            self,
            rows: list[dict[str, Any]],
            *,
            pr: int,
        ) -> list[dict[str, Any]]:
            return [
                {
                    "lane_id": "Q900-stale-terminal",
                    "owner_session": "codex-owner",
                }
            ]

        def _annotate_terminal_safety(
            self,
            findings: list[dict[str, Any]],
            **kwargs: Any,
        ) -> list[dict[str, Any]]:
            return [
                {
                    **finding,
                    "terminal_safety_blockers": [],
                    "terminal_safety_details": {},
                    "apply_safe": True,
                }
                for finding in findings
            ]

        def _merged_pr_audit_blocked_reason(self, **kwargs: Any) -> str:
            assert "expected_closed_at" in kwargs
            assert "expected_head_sha" in kwargs
            return ""

        def _base_merged_pr_audit_result(self, **kwargs: Any) -> dict[str, Any]:
            assert "expected_closed_at" in kwargs
            assert "expected_head_sha" in kwargs
            return {
                "github_state": kwargs["github_state"],
                "findings": kwargs["findings"],
                "blocked_reason": kwargs["blocked_reason"],
                "apply_eligible": False,
            }

        def audit_merged_pr_lanes(self, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("sentinel must not enter resolver write-lock audit")

    monkeypatch.setattr(sentinel, "_load_resolver_module", lambda: FakeResolver())

    result = sentinel._default_terminal_owner_auditor(
        pr=9001,
        github_state={"available": True, "state": "MERGED", "merge_commit": "abc123"},
        registry_path=tmp_path / "lanes.json",
        receipt_dir=tmp_path / "receipts",
        gh_bin="gh",
        heartbeat_path=tmp_path / "heartbeats.json",
        steering_inbox_root=tmp_path / "operator-steering",
        heartbeat_fresh_seconds=900,
    )

    assert result["github_state"]["state"] == "MERGED"
    assert result["github_state"]["mergeCommit"] == "abc123"
    assert result["findings"][0]["terminal_safety_blockers"] == []


def test_stale_terminal_owner_default_auditor_uses_real_resolver_module(
    tmp_path: Path,
) -> None:
    sentinel._RESOLVER_MODULE = None
    registry = _write_json(tmp_path / "lanes.json", [_active_owner_row()])

    def fetch_state(pr: int, *, repo_slug: str, gh_bin: str) -> dict[str, Any]:
        assert pr == 9001
        assert repo_slug == "synaptent/aragora"
        assert gh_bin == "gh"
        return {
            "available": True,
            "number": pr,
            "state": "MERGED",
            "merge_commit": "real-resolver-merge",
            "url": "https://github.test/pr/9001",
        }

    result = sentinel.check_stale_terminal_owner(
        registry,
        receipt_dir=tmp_path / "receipts",
        heartbeat_path=tmp_path / "heartbeats.json",
        steering_inbox_root=tmp_path / "operator-steering",
        min_age_hours=24.0,
        now=NOW,
        repo_slug="synaptent/aragora",
        pr_state_fetcher=fetch_state,
    )

    assert result["status"] == "breach"
    candidate = result["candidates"][0]
    assert candidate["lane_id"] == "Q900-stale-terminal"
    assert candidate["terminal_safety_blockers"] == []
    assert "--expected-merge-commit real-resolver-merge" in candidate["reconciler_apply_command"]


# ---------------------------------------------------------------------------
# github_api_health  (failure class B: GraphQL 502/504 streaks of 2026-06-10/11
# stalled the publisher; the cached github_health flipped auth_ok:false so the
# sentinel breached without distinguishing transient from persistent)
# ---------------------------------------------------------------------------


def _publisher_log(tmp_path: Path, passes: list[str], *, errors: list[str] | None = None) -> Path:
    """Build a publisher log: one start/end marker pair per pass outcome."""
    lines: list[str] = []
    for i, outcome in enumerate(passes):
        lines.append(
            f"2026-06-11T0{i % 10}:00:00Z [codex-automation-publisher] starting branch publish pass"
        )
        for err in errors or []:
            lines.append(f'    "error": "{err}",')
        lines.append(
            f"2026-06-11T0{i % 10}:01:00Z [codex-automation-publisher] branch publish pass {outcome}"
        )
    path = tmp_path / "codex-automation-publisher.log"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_github_api_health_probe_ok_no_streak(tmp_path: Path) -> None:
    log = _publisher_log(tmp_path, ["complete", "complete"])
    result = sentinel.check_github_api_health(
        log, persist_threshold=3, tail_lines=2000, probe_runner=lambda cmd: 0
    )
    assert result["status"] == "ok"
    assert "streak=0" in result["detail"]


def test_github_api_health_transient_blip_visible_but_quiet(tmp_path: Path) -> None:
    """Probe down + short streak = transient: recorded in detail, NO breach."""
    log = _publisher_log(
        tmp_path,
        ["complete", "failed", "failed"],
        errors=["HTTP 502: 502 Bad Gateway (https://api.github.com/graphql)"],
    )
    result = sentinel.check_github_api_health(
        log, persist_threshold=3, tail_lines=2000, probe_runner=lambda cmd: 1
    )
    assert result["status"] == "ok"
    assert "streak=2" in result["detail"]
    assert "HTTP 502" in result["detail"]


def test_github_api_health_persistent_degradation_breaches(tmp_path: Path) -> None:
    log = _publisher_log(
        tmp_path,
        ["complete", "failed", "failed", "failed"],
        errors=["HTTP 504: We couldn't respond in time (https://api.github.com/graphql)"],
    )
    result = sentinel.check_github_api_health(
        log, persist_threshold=3, tail_lines=2000, probe_runner=lambda cmd: 1
    )
    assert result["status"] == "breach"
    assert "streak=3" in result["detail"]
    assert "HTTP 504" in result["detail"]


def test_github_api_health_probe_recovered_long_streak_ok(tmp_path: Path) -> None:
    """Streak alone never breaches: a green probe means the API recovered."""
    log = _publisher_log(tmp_path, ["failed", "failed", "failed", "failed"])
    result = sentinel.check_github_api_health(
        log, persist_threshold=3, tail_lines=2000, probe_runner=lambda cmd: 0
    )
    assert result["status"] == "ok"
    assert "streak=4" in result["detail"]


def test_github_api_health_streak_resets_on_complete(tmp_path: Path) -> None:
    log = _publisher_log(tmp_path, ["failed", "failed", "complete", "failed"])
    result = sentinel.check_github_api_health(
        log, persist_threshold=3, tail_lines=2000, probe_runner=lambda cmd: 1
    )
    assert result["status"] == "ok"
    assert "streak=1" in result["detail"]


def test_github_api_health_attempt_lines_not_counted_as_pass_failures(tmp_path: Path) -> None:
    lines = [
        "2026-06-11T00:00:00Z [codex-automation-publisher] starting branch publish pass",
        "2026-06-11T00:00:30Z [codex-automation-publisher] branch publish pass attempt 1/3 failed (exit 1); retrying in 30s",
        "2026-06-11T00:01:30Z [codex-automation-publisher] branch publish pass complete",
    ]
    log = tmp_path / "pub.log"
    log.write_text("\n".join(lines) + "\n")
    streak, _ = sentinel.publisher_failure_streak(lines)
    assert streak == 0
    result = sentinel.check_github_api_health(
        log, persist_threshold=3, tail_lines=2000, probe_runner=lambda cmd: 1
    )
    assert result["status"] == "ok"


def test_github_api_health_log_missing_is_unknown(tmp_path: Path) -> None:
    result = sentinel.check_github_api_health(
        tmp_path / "absent.log", persist_threshold=3, tail_lines=2000, probe_runner=lambda cmd: 0
    )
    assert result["status"] == "unknown"


def test_github_api_health_probe_crash_is_unknown(tmp_path: Path) -> None:
    log = _publisher_log(tmp_path, ["complete"])

    def boom(cmd: list[str]) -> int:
        raise FileNotFoundError("gh not installed")

    result = sentinel.check_github_api_health(
        log, persist_threshold=3, tail_lines=2000, probe_runner=boom
    )
    assert result["status"] == "unknown"


def test_new_checks_registered_in_all_checks() -> None:
    assert "lane_liveness" in sentinel.ALL_CHECKS
    assert "github_api_health" in sentinel.ALL_CHECKS


def test_main_github_api_health_wired_end_to_end(tmp_path: Path, capsys: Any) -> None:
    log = _publisher_log(tmp_path, ["complete"])
    code = sentinel.main(
        [
            "--json",
            "--no-ledger",
            "--now",
            "2026-06-10T12:00:00Z",
            "--checks",
            "github_api_health",
            "--publisher-log",
            str(log),
            "--rate-limit-cmd",
            f"{sys.executable} -c pass",
        ]
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["checks"][0]["check"] == "github_api_health"


def test_main_lane_liveness_blind_repo_exits_two(tmp_path: Path, capsys: Any) -> None:
    """Wiring test without network: a non-repo root makes the check blind."""
    code = sentinel.main(
        [
            "--json",
            "--no-ledger",
            "--now",
            "2026-06-10T12:00:00Z",
            "--checks",
            "lane_liveness",
            "--repo-root",
            str(tmp_path),
            "--lanes-glob",
            str(tmp_path / "run-*" / "lanes"),
        ]
    )
    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["blind_checks"] == 1


def test_notify_embedded_placeholder_neutralizes_quote_injection() -> None:
    """{summary} embedded inside a larger token (e.g. an AppleScript string
    literal, as in the installer's default osascript notify command) must not
    let quotes/backslashes in the summary escape the host string literal."""
    captured: dict[str, list[str]] = {}

    def runner(tokens: list[str]) -> int:
        captured["tokens"] = tokens
        return 0

    cmd = 'osascript -e "display notification \\"{summary}\\" with title \\"Aragora Fleet Sentinel\\""'
    sentinel.notify(cmd, 'detail "x" \\ end', runner=runner)
    tokens = captured["tokens"]
    assert tokens[0] == "osascript"
    script = tokens[2]
    # The two delimiting quotes around the summary plus the two around the
    # title are the ONLY double quotes left — none smuggled in via summary.
    assert script.count('"') == 4
    assert "\\" not in script
    assert "detail 'x' / end" in script


# ---------------------------------------------------------------------------
# trail_reconcile (TET Component 3 — witness vs anchored-intent reconciliation)
# ---------------------------------------------------------------------------

T_NOW = sentinel.parse_iso("2026-06-11T12:00:00Z")
REPO = "synaptent/aragora"


def _witness_event(
    event_type: str,
    *,
    actor: str = "an0mium",
    repo: str = REPO,
    ref: str = "main",
    sha: str = "abc1234def",
    age_minutes: float = 10.0,
) -> dict[str, Any]:
    ts = sentinel.parse_iso("2026-06-11T12:00:00Z").timestamp() - age_minutes * 60
    from datetime import datetime, timezone

    created = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return {
        "event_type": event_type,
        "repo": repo,
        "actor": actor,
        "ref": ref,
        "sha": sha,
        "created_at": created,
    }


def _intent(
    intent_type: str,
    *,
    actor_class: str = "agent",
    target: str = f"{REPO}@main",
    age_minutes: float = 12.0,
    seq: int = 1,
) -> dict[str, Any]:
    ts = sentinel.parse_iso("2026-06-11T12:00:00Z").timestamp() - age_minutes * 60
    from datetime import datetime, timezone

    anchored = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return {
        "seq": seq,
        "ts": anchored,
        "actor_class": actor_class,
        "intent_type": intent_type,
        "target": target,
        "intent_id": f"intent-{seq}",
        "prev_hash": "0" * 64,
        "record_hash": "f" * 64,
    }


def _reconcile(
    events: list[dict[str, Any]],
    records: list[dict[str, Any]] | None,
    *,
    chain_ok: bool = True,
    chain_detail: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    def witness() -> list[dict[str, Any]]:
        return events

    def chain_reader(path: Path) -> tuple[list[dict[str, Any]], bool, str]:
        if records is None:
            raise FileNotFoundError(path)
        return records, chain_ok, chain_detail

    defaults: dict[str, Any] = {
        "witness_events": witness,
        "chain_path": Path("/nonexistent/intent-chain.jsonl"),
        "chain_reader": chain_reader,
        "now": T_NOW,
    }
    defaults.update(kwargs)
    return sentinel.check_trail_reconcile(**defaults)


def test_trail_reconcile_module_absent_is_unknown() -> None:
    """No chain_reader injected -> lazy import of aragora.trail.intent_chain.

    Until lane TA merges, the module does not exist; the check must degrade
    honestly to unknown, never ok and never a false breach.
    """
    result = sentinel.check_trail_reconcile(
        witness_events=lambda: [_witness_event("merge")],
        chain_path=Path("/nonexistent/intent-chain.jsonl"),
        now=T_NOW,
    )
    assert result["check"] == "trail_reconcile"
    if "intent_chain" in result["detail"] and "not present" in result["detail"]:
        assert result["status"] == "unknown"
    else:
        # Module exists (TA merged): absent chain file is still unknown.
        assert result["status"] == "unknown"


def test_trail_reconcile_chain_not_populated_is_unknown() -> None:
    result = _reconcile([_witness_event("merge")], records=None)
    assert result["status"] == "unknown"
    assert "not yet populated" in result["detail"]


def test_trail_reconcile_witness_unreadable_is_unknown() -> None:
    def broken_witness() -> list[dict[str, Any]]:
        raise OSError("S3 replica unreachable")

    result = sentinel.check_trail_reconcile(
        witness_events=broken_witness,
        chain_path=Path("/nonexistent"),
        chain_reader=lambda p: ([], True, ""),
        now=T_NOW,
    )
    assert result["status"] == "unknown"
    assert "witness" in result["detail"].lower()


def test_trail_reconcile_tampered_chain_is_critical_breach() -> None:
    result = _reconcile(
        [],
        records=[_intent("merge")],
        chain_ok=False,
        chain_detail="hash mismatch at seq 7",
    )
    assert result["status"] == "breach"
    assert "critical" in result["detail"]
    assert "tampered" in result["detail"]
    assert "seq 7" in result["detail"]


def test_trail_reconcile_matched_merge_is_ok() -> None:
    result = _reconcile([_witness_event("merge")], records=[_intent("merge")])
    assert result["status"] == "ok"
    assert "0 unmatched" in result["detail"]
    assert "chain ok" in result["detail"]


def test_trail_reconcile_unmatched_push_is_high_breach() -> None:
    result = _reconcile([_witness_event("push")], records=[])
    assert result["status"] == "breach"
    assert "high" in result["detail"]
    assert "push" in result["detail"]
    assert "an0mium" in result["detail"]  # enumerates the unaccounted event


def test_trail_reconcile_intent_type_must_match_event_class() -> None:
    """A merge intent does not excuse a branch deletion."""
    result = _reconcile(
        [_witness_event("branch_deletion", ref="elves/run-x")],
        records=[_intent("merge", target=f"{REPO}@elves/run-x")],
    )
    assert result["status"] == "breach"
    assert "branch_deletion" in result["detail"]


def test_trail_reconcile_target_must_reference_ref_or_sha() -> None:
    """An intent for another branch does not excuse this push."""
    result = _reconcile(
        [_witness_event("push", ref="main", sha="deadbeef99")],
        records=[_intent("push", target=f"{REPO}@feature/other")],
    )
    assert result["status"] == "breach"


def test_trail_reconcile_intent_anchored_after_event_not_matched() -> None:
    """Pre-anchoring contract: an intent recorded AFTER the action (beyond
    clock-skew grace) cannot retroactively legitimize it."""
    result = _reconcile(
        [_witness_event("merge", age_minutes=30.0)],
        records=[_intent("merge", age_minutes=10.0)],  # 20 min AFTER the event
    )
    assert result["status"] == "breach"


def test_trail_reconcile_intent_too_old_not_matched() -> None:
    """An intent anchored far outside the window cannot be replayed forever."""
    result = _reconcile(
        [_witness_event("merge", age_minutes=10.0)],
        records=[_intent("merge", age_minutes=300.0)],
        match_window_minutes=15.0,
    )
    assert result["status"] == "breach"


def test_trail_reconcile_credential_event_needs_human_anchor() -> None:
    """Token/key events have no legitimate agent intent class: an
    agent-anchored intent does NOT excuse them (spec Component 3)."""
    result = _reconcile(
        [_witness_event("token_created", actor="an0mium", ref="", sha="")],
        records=[_intent("token_created", actor_class="agent", target=REPO)],
    )
    assert result["status"] == "breach"
    assert "critical" in result["detail"]


def test_trail_reconcile_credential_event_with_scarmani_anchor_ok() -> None:
    result = _reconcile(
        [_witness_event("token_created", actor="scarmani", ref="", sha="")],
        records=[_intent("token_created", actor_class="scarmani", target=REPO)],
    )
    assert result["status"] == "ok"


def test_trail_reconcile_unknown_actor_matches_nothing() -> None:
    result = _reconcile(
        [_witness_event("merge", actor="attacker-9000")],
        records=[_intent("merge")],
    )
    assert result["status"] == "breach"
    assert "attacker-9000" in result["detail"]


def test_trail_reconcile_non_mutating_events_ignored() -> None:
    result = _reconcile(
        [_witness_event("issue_comment"), _witness_event("watch_started")],
        records=[],
    )
    assert result["status"] == "ok"


def test_trail_reconcile_events_outside_window_ignored() -> None:
    """A mutating event older than the reconcile window is not re-litigated
    (it was already reconciled in earlier cycles).  A fresh non-mutating event
    keeps the witness demonstrably alive so blind accounting stays quiet."""
    result = _reconcile(
        [
            _witness_event("push", age_minutes=60 * 50),  # ~2 days old
            _witness_event("issue_comment", age_minutes=5),
        ],
        records=[],
        reconcile_window_hours=24.0,
    )
    assert result["status"] == "ok"
    assert "0 unmatched" in result["detail"]


def test_trail_reconcile_mild_witness_silence_visible_but_quiet() -> None:
    """Newest witness event older than cadence -> blind-period note, still ok."""
    result = _reconcile(
        [_witness_event("merge", age_minutes=8 * 60)],
        records=[_intent("merge", age_minutes=8 * 60 + 2)],
        witness_cadence_hours=6.0,
    )
    assert result["status"] == "ok"
    assert "blind" in result["detail"].lower()


def test_trail_reconcile_badly_exceeded_silence_is_unknown() -> None:
    """Silence is never success: witness silent for 4x cadence -> unknown."""
    result = _reconcile(
        [],
        records=[],
        witness_cadence_hours=6.0,
        reconcile_window_hours=200.0,
    )
    assert result["status"] == "unknown"
    assert "blind" in result["detail"].lower() or "silen" in result["detail"].lower()


def test_trail_reconcile_breach_outranks_blind_note() -> None:
    """Observed breaches must not be masked by concurrent mild silence."""
    result = _reconcile(
        [_witness_event("push", age_minutes=7 * 60)],
        records=[],
        witness_cadence_hours=6.0,
    )
    assert result["status"] == "breach"


def test_trail_reconcile_registered_in_all_checks() -> None:
    assert "trail_reconcile" in sentinel.ALL_CHECKS


# ---------------------------------------------------------------------------
# T5 — incident-replay acceptance (the TET spec's falsifiable exit metric)
# ---------------------------------------------------------------------------


def test_breach_replay_may_incident_unauthorized_credential(tmp_path: Path) -> None:
    """T5 acceptance: re-enact the May-incident class — a token created and a
    deploy key added from an unknown actor with NO matching anchored intent
    must raise a CRITICAL breach within ONE sentinel evaluation.

    This is the falsifiable exit metric from
    docs/specs/TAMPER_EVIDENT_TRAIL.md ("a simulated unauthorized action
    raises a critical breach within one sentinel cycle").
    """
    incident = [
        _witness_event("token_created", actor="unknown-ctx-7", ref="", sha="", age_minutes=5),
        _witness_event("deploy_key_added", actor="unknown-ctx-7", ref="", sha="", age_minutes=4),
    ]
    # A normal day's chain exists around the incident — it must not excuse it.
    records = [_intent("merge", seq=1, age_minutes=20), _intent("push", seq=2, age_minutes=40)]
    result = _reconcile(incident, records=records)
    assert result["status"] == "breach"
    assert "critical" in result["detail"]
    assert "token_created" in result["detail"]
    assert "deploy_key_added" in result["detail"]
    assert "unknown-ctx-7" in result["detail"]
    # One evaluation is enough to drive the alarm exit code.
    assert sentinel.exit_code_for([result]) == 1


def test_replay_normal_day_thirty_merges_zero_false_alarms() -> None:
    """T5 acceptance (other half): ~30 merges of normal agent traffic, each
    with an intent anchored 1-12 minutes before the action, must reconcile
    clean — zero false alarms after tuning, or the matching rules are wrong.
    """
    events: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for i in range(30):
        event_age = 10.0 + i * 20.0  # spread across the last ~10 hours
        anchor_lead = 1.0 + (i % 12)  # intent anchored 1-12 min before
        sha = f"{i:02d}ab{i:02d}cd{i:02d}"
        ref = "main" if i % 3 else f"elves/run-lane{i}"
        events.append(
            _witness_event(
                "merge" if i % 2 else "push",
                actor="aragora-automation-fable[bot]" if i % 4 else "an0mium",
                ref=ref,
                sha=sha,
                age_minutes=event_age,
            )
        )
        records.append(
            _intent(
                "merge" if i % 2 else "push",
                seq=i + 1,
                target=f"{REPO}@{ref}#{sha}",
                age_minutes=event_age + anchor_lead,
            )
        )
    result = _reconcile(events, records=records)
    assert result["status"] == "ok", result["detail"]
    assert "30" in result["detail"]  # reports how much it reconciled
    assert sentinel.exit_code_for([result]) == 0


def test_main_trail_reconcile_wired_end_to_end(tmp_path: Path, capsys: Any) -> None:
    """main() drives trail_reconcile from a local witness-replica file."""
    replica = tmp_path / "witness.jsonl"
    replica.write_text(
        json.dumps(
            {
                "event_type": "token_created",
                "repo": REPO,
                "actor": "unknown-ctx-7",
                "ref": "",
                "sha": "",
                "created_at": "2026-06-11T11:55:00+00:00",
            }
        )
        + "\n"
    )
    chain = tmp_path / "intent-chain.jsonl"
    chain.write_text(json.dumps(_intent("merge")) + "\n")
    code = sentinel.main(
        [
            "--json",
            "--no-ledger",
            "--now",
            "2026-06-11T12:00:00Z",
            "--checks",
            "trail_reconcile",
            "--trail-witness-replica",
            str(replica),
            "--trail-chain",
            str(chain),
        ]
    )
    report = json.loads(capsys.readouterr().out)
    (check,) = report["checks"]
    assert check["check"] == "trail_reconcile"
    # The wired path reads the chain via aragora.trail.intent_chain when
    # available; before lane TA merges it degrades to unknown (exit 2), after
    # TA merges this replica replay must breach (exit 1). Both are alarm
    # states — never 0.
    assert check["status"] in ("breach", "unknown")
    assert code in (1, 2)


def test_github_witness_events_rejects_invalid_repo_slug_before_capture() -> None:
    def capture_should_not_run(cmd: list[str]) -> str:
        raise AssertionError("invalid repo slug must not reach gh api")

    try:
        sentinel._github_witness_events(
            "synaptent/aragora --json files", capture=capture_should_not_run
        )
    except ValueError as exc:
        assert "repo_slug" in str(exc)
    else:
        raise AssertionError("invalid witness repo slug was accepted")


def test_main_trail_reconcile_invalid_repo_slug_is_structured_unknown(
    tmp_path: Path,
    capsys: Any,
) -> None:
    code = sentinel.main(
        [
            "--json",
            "--no-ledger",
            "--now",
            "2026-06-10T12:00:00Z",
            "--checks",
            "trail_reconcile",
            "--trail-witness-repo",
            "synaptent/aragora --json files",
            "--trail-chain",
            str(tmp_path / "intent-chain.jsonl"),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 2
    check = report["checks"][0]
    assert check["status"] == "unknown"
    assert "witness unreadable" in check["detail"]
    assert "repo_slug" in check["detail"]
    assert "check crashed" not in check["detail"]


def test_main_trail_reconcile_replica_chain_reader_fallback(tmp_path: Path, capsys: Any) -> None:
    """With --trail-chain-format jsonl the check reads the chain file directly
    (schema-only, no hash verification) so the replica replay works before
    lane TA's intent_chain module lands; verification state is reported."""
    replica = tmp_path / "witness.jsonl"
    replica.write_text(
        json.dumps(
            {
                "event_type": "token_created",
                "repo": REPO,
                "actor": "unknown-ctx-7",
                "ref": "",
                "sha": "",
                "created_at": "2026-06-11T11:55:00+00:00",
            }
        )
        + "\n"
    )
    chain = tmp_path / "intent-chain.jsonl"
    chain.write_text(json.dumps(_intent("merge")) + "\n")
    code = sentinel.main(
        [
            "--json",
            "--no-ledger",
            "--now",
            "2026-06-11T12:00:00Z",
            "--checks",
            "trail_reconcile",
            "--trail-witness-replica",
            str(replica),
            "--trail-chain",
            str(chain),
            "--trail-chain-format",
            "jsonl",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    (check,) = report["checks"]
    assert code == 1
    assert check["status"] == "breach"
    assert "critical" in check["detail"]
    assert "unverified" in check["detail"]  # honest about skipping hash checks


def test_trail_reconcile_events_api_coverage_gap_always_visible() -> None:
    """Review finding (grok, PR #8250): the interim GitHub events-API witness
    structurally cannot see token/deploy-key/member admin events — the exact
    May-incident class.  An 'ok' from that witness must never be mistakable
    for credential-event coverage: every report carries the coverage note
    until the S3 audit-stream witness (TET T0) replaces it."""
    ok = _reconcile(
        [_witness_event("merge")],
        records=[_intent("merge")],
        witness_coverage="events_api",
    )
    assert ok["status"] == "ok"
    assert "coverage limited" in ok["detail"]
    breach = _reconcile([_witness_event("push")], records=[], witness_coverage="events_api")
    assert breach["status"] == "breach"
    assert "coverage limited" in breach["detail"]


def test_trail_reconcile_full_coverage_witness_has_no_gap_note() -> None:
    result = _reconcile([_witness_event("merge")], records=[_intent("merge")])
    assert result["status"] == "ok"
    assert "coverage limited" not in result["detail"]


# ---------------------------------------------------------------------------
# Live-module integration: reconcile against a REAL intent chain written by
# aragora.trail.intent_chain (TET T1, PR #8251) through the default reader.
# ---------------------------------------------------------------------------


def _real_chain(tmp_path: Path) -> tuple[Any, Path]:
    intent_chain = __import__("pytest").importorskip("aragora.trail.intent_chain")
    return intent_chain, tmp_path / "intent-chain.jsonl"


def test_trail_reconcile_real_chain_settle_intent_matches_merge(tmp_path: Path) -> None:
    """End-to-end on the production read path: a settle_pr intent recorded by
    the real chain writer (target {repo, pr}) reconciles a merge witness
    event carrying that PR number; verify_chain runs for real."""
    intent_chain, chain = _real_chain(tmp_path)
    intent_chain.append_intent(
        chain,
        actor_class="agent-app",
        intent_type="settle_pr",
        target={"repo": REPO, "pr": 8250},
        now=lambda: "2026-06-11T11:52:00+00:00",
    )
    event = _witness_event("merge", ref="main", sha="", age_minutes=5.0)
    event["pr"] = "8250"
    result = sentinel.check_trail_reconcile(
        witness_events=lambda: [event],
        chain_path=chain,
        now=T_NOW,
    )
    assert result["status"] == "ok", result["detail"]
    assert "chain ok (1 record(s))" in result["detail"]


def test_breach_replay_may_incident_against_real_chain(tmp_path: Path) -> None:
    """T5 on the production read path: the May-incident credential events find
    no excuse in a real, hash-valid chain of normal agent intents."""
    intent_chain, chain = _real_chain(tmp_path)
    intent_chain.append_intent(
        chain,
        actor_class="agent-claude",
        intent_type="publish_pr",
        target={"repo": REPO, "ref": "main"},
        now=lambda: "2026-06-11T11:40:00+00:00",
    )
    incident = _witness_event("token_created", actor="unknown-ctx-7", ref="", sha="")
    result = sentinel.check_trail_reconcile(
        witness_events=lambda: [incident],
        chain_path=chain,
        now=T_NOW,
    )
    assert result["status"] == "breach"
    assert "critical" in result["detail"]
    assert "token_created" in result["detail"]


def test_trail_reconcile_real_chain_tamper_detected(tmp_path: Path) -> None:
    """A record edited after the fact breaks verify_chain -> critical breach."""
    intent_chain, chain = _real_chain(tmp_path)
    for i in range(2):
        intent_chain.append_intent(
            chain,
            actor_class="agent-claude",
            intent_type="merge_pr",
            target={"repo": REPO, "ref": "main"},
            now=lambda i=i: f"2026-06-11T11:4{i}:00+00:00",
        )
    lines = chain.read_text().splitlines()
    doctored = json.loads(lines[0])
    doctored["target"] = {"repo": "attacker/elsewhere"}
    chain.write_text("\n".join([json.dumps(doctored), *lines[1:]]) + "\n")
    result = sentinel.check_trail_reconcile(
        witness_events=lambda: [_witness_event("issue_comment")],
        chain_path=chain,
        now=T_NOW,
    )
    assert result["status"] == "breach"
    assert "tampered" in result["detail"]
    assert "seq 0" in result["detail"]


# ---------------------------------------------------------------------------
# outbox_drain_progress (circuit-breaker — §Conductor)
# ---------------------------------------------------------------------------


def _outbox_fingerprint(path: Path) -> str:
    return sentinel._outbox_fingerprint(sorted(path.glob("*.json")))


def _ledger_with_depths(path: Path, depths: list[int], *, fingerprint: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for d in depths:
        check = {"check": "outbox_depth", "status": "ok", "detail": f"{d} item(s) queued"}
        if fingerprint is not None:
            check["fingerprint"] = fingerprint
        lines.append(json.dumps({"checks": [check]}))
    path.write_text("\n".join(lines) + "\n")
    return path


def _ledger_with_checks(path: Path, checks_by_cycle: list[list[dict[str, Any]]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"checks": checks}) for checks in checks_by_cycle]
    path.write_text("\n".join(lines) + "\n")
    return path


def _outbox_with(path: Path, count: int) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (path / f"item-{i}.json").write_text("{}")
    return path


def test_outbox_drain_progress_stalled_breaches(tmp_path: Path) -> None:
    # Depth non-decreasing at/above the floor across the window, still congested now.
    outbox = _outbox_with(tmp_path / "outbox", 55)
    ledger = _ledger_with_depths(
        tmp_path / "ledger.jsonl", [50, 52, 55], fingerprint=_outbox_fingerprint(outbox)
    )
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "breach"
    assert "not draining" in r["detail"] and "dead-letter" in r["detail"]


def test_outbox_drain_progress_draining_is_ok(tmp_path: Path) -> None:
    # Depth fell over the window -> the loop is making external progress.
    ledger = _ledger_with_depths(tmp_path / "ledger.jsonl", [60, 55, 52])
    outbox = _outbox_with(tmp_path / "outbox", 50)
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "ok"


def test_outbox_drain_progress_live_drop_is_ok(tmp_path: Path) -> None:
    # Rising prior history alone is not a stall when the live depth has dropped.
    ledger = _ledger_with_depths(tmp_path / "ledger.jsonl", [50, 55, 60])
    outbox = _outbox_with(tmp_path / "outbox", 51)
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "ok"
    assert "draining or fluctuating" in r["detail"]


def test_outbox_drain_progress_refilled_after_small_drop_breaches(tmp_path: Path) -> None:
    # A temporary one-cycle dip does not prove progress if live depth refills.
    outbox = _outbox_with(tmp_path / "outbox", 55)
    ledger = _ledger_with_depths(
        tmp_path / "ledger.jsonl", [55, 54, 55], fingerprint=_outbox_fingerprint(outbox)
    )
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "breach"
    assert "net backlog progress" in r["detail"]


def test_outbox_drain_progress_uses_structured_depth(tmp_path: Path) -> None:
    outbox = _outbox_with(tmp_path / "outbox", 55)
    fingerprint = _outbox_fingerprint(outbox)
    ledger = _ledger_with_checks(
        tmp_path / "ledger.jsonl",
        [
            [
                {
                    "check": "outbox_depth",
                    "status": "ok",
                    "depth": 50,
                    "fingerprint": fingerprint,
                    "detail": "fifty queued",
                }
            ],
            [
                {
                    "check": "outbox_depth",
                    "status": "ok",
                    "depth": 52,
                    "fingerprint": fingerprint,
                    "detail": "fifty-two queued",
                }
            ],
            [
                {
                    "check": "outbox_depth",
                    "status": "ok",
                    "depth": 55,
                    "fingerprint": fingerprint,
                    "detail": "fifty-five queued",
                }
            ],
        ],
    )
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "breach"


def test_outbox_drain_progress_saturated_throughput_is_ok(tmp_path: Path) -> None:
    ledger = _ledger_with_checks(
        tmp_path / "ledger.jsonl",
        [
            [{"check": "outbox_depth", "status": "ok", "depth": 50, "fingerprint": "fp-a"}],
            [{"check": "outbox_depth", "status": "ok", "depth": 51, "fingerprint": "fp-b"}],
            [{"check": "outbox_depth", "status": "ok", "depth": 50, "fingerprint": "fp-c"}],
        ],
    )
    outbox = _outbox_with(tmp_path / "outbox", 50)
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "ok"
    assert "throughput" in r["detail"]


def test_outbox_drain_progress_stable_depth_without_fingerprint_is_unknown(tmp_path: Path) -> None:
    ledger = _ledger_with_depths(tmp_path / "ledger.jsonl", [50, 50, 50])
    outbox = _outbox_with(tmp_path / "outbox", 50)
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "unknown"
    assert "fingerprints" in r["detail"]


def test_outbox_drain_progress_unusable_history_is_unknown(tmp_path: Path) -> None:
    ledger = _ledger_with_checks(
        tmp_path / "ledger.jsonl",
        [
            [{"check": "outbox_depth", "status": "ok", "detail": "queued but not numeric"}],
            [{"check": "other_check", "status": "ok", "detail": "not depth"}],
            [{"check": "outbox_depth", "status": "ok", "detail": "still not numeric"}],
        ],
    )
    outbox = _outbox_with(tmp_path / "outbox", 55)
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "unknown"
    assert "usable outbox_depth" in r["detail"]


def test_outbox_drain_progress_missing_recent_cycle_is_unknown(tmp_path: Path) -> None:
    outbox = _outbox_with(tmp_path / "outbox", 55)
    fingerprint = _outbox_fingerprint(outbox)
    ledger = _ledger_with_checks(
        tmp_path / "ledger.jsonl",
        [
            [{"check": "outbox_depth", "status": "ok", "depth": 40, "fingerprint": "old"}],
            [{"check": "other_check", "status": "ok", "detail": "not depth"}],
            [{"check": "outbox_depth", "status": "ok", "depth": 55, "fingerprint": fingerprint}],
            [{"check": "outbox_depth", "status": "ok", "depth": 55, "fingerprint": fingerprint}],
        ],
    )
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "unknown"
    assert "last 3 ledger cycle" in r["detail"]


def test_outbox_drain_progress_invalid_stall_cycles_is_unknown(tmp_path: Path) -> None:
    ledger = _ledger_with_depths(tmp_path / "ledger.jsonl", [50, 52, 55])
    outbox = _outbox_with(tmp_path / "outbox", 55)
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=0, min_floor=50)
    assert r["status"] == "unknown"
    assert "must be >= 1" in r["detail"]


def test_outbox_drain_progress_flat_stuck_breaches(tmp_path: Path) -> None:
    # Flat at the floor across the window, current equals the most recent reading -> breach.
    outbox = _outbox_with(tmp_path / "outbox", 55)
    ledger = _ledger_with_depths(
        tmp_path / "ledger.jsonl", [55, 55, 55], fingerprint=_outbox_fingerprint(outbox)
    )
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "breach"
    assert "not draining" in r["detail"] and "dead-letter" in r["detail"]


def test_outbox_drain_progress_recovering_is_ok(tmp_path: Path) -> None:
    # Window stayed at/above the floor, but current depth fell below the most recent
    # reading -> the loop is improving, no breach.
    ledger = _ledger_with_depths(tmp_path / "ledger.jsonl", [50, 52, 55])
    outbox = _outbox_with(tmp_path / "outbox", 54)  # 54 < window[-1] (55) -> improving
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "ok"


def test_outbox_drain_progress_slow_drain_is_ok(tmp_path: Path) -> None:
    # Depth fell steadily over the window and is still falling -> external progress.
    ledger = _ledger_with_depths(tmp_path / "ledger.jsonl", [60, 58, 56])
    outbox = _outbox_with(tmp_path / "outbox", 54)  # 54 < window[-1] (56) -> draining
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "ok"


def test_outbox_drain_progress_slow_drain_with_brief_pause_is_ok(tmp_path: Path) -> None:
    # The full window shows external progress; a single flat current reading is
    # not enough to declare the drain loop stuck.
    ledger = _ledger_with_depths(tmp_path / "ledger.jsonl", [60, 58, 56])
    outbox = _outbox_with(tmp_path / "outbox", 56)
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "ok"


def test_outbox_drain_progress_below_floor_is_ok(tmp_path: Path) -> None:
    ledger = _ledger_with_depths(tmp_path / "ledger.jsonl", [50, 52, 55])
    outbox = _outbox_with(tmp_path / "outbox", 10)  # below floor -> not congested
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "ok"
    assert "below floor" in r["detail"]


def test_outbox_drain_progress_insufficient_history_is_ok(tmp_path: Path) -> None:
    ledger = _ledger_with_depths(tmp_path / "ledger.jsonl", [50])  # only one prior cycle
    outbox = _outbox_with(tmp_path / "outbox", 55)
    r = sentinel.check_outbox_drain_progress(ledger, outbox, stall_cycles=3, min_floor=50)
    assert r["status"] == "ok"


def test_outbox_drain_progress_no_ledger_is_ok(tmp_path: Path) -> None:
    outbox = _outbox_with(tmp_path / "outbox", 55)
    r = sentinel.check_outbox_drain_progress(
        tmp_path / "absent.jsonl", outbox, stall_cycles=3, min_floor=50
    )
    assert r["status"] == "ok"
