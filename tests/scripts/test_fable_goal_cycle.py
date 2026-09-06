"""Focused tests for the bounded Fable goal-cycle helper."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aragora.agents.transports.vibeproxy import TransportMode
from scripts import consult_claude


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fable_goal_cycle.py"
SPEC = importlib.util.spec_from_file_location("fable_goal_cycle_under_test", SCRIPT)
assert SPEC and SPEC.loader
fable_goal_cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fable_goal_cycle)


@pytest.fixture(autouse=True)
def _default_direct_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "direct")


def test_consult_budget_constants_follow_canonical_transport_definitions() -> None:
    assert fable_goal_cycle.CONSULT_FALLBACK_MODEL == consult_claude.FALLBACK_MODEL
    assert fable_goal_cycle.MODEL_TRANSPORT_MODES == frozenset(mode.value for mode in TransportMode)


def test_extract_next_prompt_uses_final_section_heading() -> None:
    response = """\
## ASSESSMENT
The words ## NEXT PROMPT appear in prose and should not be selected.

```text
wrong fenced example
```

## NEXT PLAN
Continue.

## NEXT PROMPT
```text
correct prompt
```
"""

    assert fable_goal_cycle.extract_next_prompt(response) == "correct prompt"


def test_extract_next_prompt_unfenced_stops_at_next_section() -> None:
    response = """\
## NEXT PROMPT
Run only this line.

## TRAILING
Do not include this.
"""

    assert fable_goal_cycle.extract_next_prompt(response) == "Run only this line."


def test_extract_next_prompt_keeps_headings_inside_fenced_prompt() -> None:
    response = """\
## NEXT PROMPT
```text
Start from live truth.

## Files
- scripts/fable_goal_cycle.py

## Acceptance
Report exact validation.
```

## TRAILING
Do not include this.
"""

    assert fable_goal_cycle.extract_next_prompt(response) == (
        "Start from live truth.\n\n"
        "## Files\n"
        "- scripts/fable_goal_cycle.py\n\n"
        "## Acceptance\n"
        "Report exact validation."
    )


def test_cycle_dir_avoids_same_second_collisions(tmp_path: Path) -> None:
    first = fable_goal_cycle._cycle_dir(tmp_path, "20260704T040000Z")
    second = fable_goal_cycle._cycle_dir(tmp_path, "20260704T040000Z")

    assert first.name == "20260704T040000Z"
    assert second.name == "20260704T040000Z-1"
    assert first.is_dir()
    assert second.is_dir()


def test_build_packet_truncates_large_context_file(tmp_path: Path) -> None:
    context_dir = tmp_path / fable_goal_cycle.SAFE_CONTEXT_SUBDIR
    context_dir.mkdir(parents=True)
    context_file = context_dir / "cycle_report.md"
    context_file.write_bytes(b"a" * (fable_goal_cycle.MAX_CONTEXT_FILE_BYTES + 50))

    packet = fable_goal_cycle.build_packet(
        {"sections": {}, "gaps": []},
        "standing mission",
        [context_file],
        since_hours=24,
        root=tmp_path,
    )

    assert "context file truncated" in packet
    assert "a" * fable_goal_cycle.MAX_CONTEXT_FILE_BYTES in packet
    assert "a" * (fable_goal_cycle.MAX_CONTEXT_FILE_BYTES + 1) not in packet


def test_build_packet_accepts_conductor_cycles_context_file(tmp_path: Path) -> None:
    context_dir = tmp_path / ".aragora" / "conductor_cycles"
    context_dir.mkdir(parents=True)
    context_file = context_dir / "cycle_report.md"
    context_file.write_text("cycle 157: transport_blocked", encoding="utf-8")

    packet = fable_goal_cycle.build_packet(
        {"sections": {}, "gaps": []},
        "standing mission",
        [context_file],
        since_hours=24,
        root=tmp_path,
    )

    assert "cycle 157: transport_blocked" in packet
    assert "OPERATOR CONTEXT MISSING" not in packet


def test_build_packet_accepts_operator_context_file(tmp_path: Path) -> None:
    context_dir = tmp_path / ".aragora" / "operator-context"
    context_dir.mkdir(parents=True)
    context_file = context_dir / "cycle_report.md"
    context_file.write_text("cycle 177: C13 RETIRE-PRESERVE", encoding="utf-8")

    packet = fable_goal_cycle.build_packet(
        {"sections": {}, "gaps": []},
        "standing mission",
        [context_file],
        since_hours=24,
        root=tmp_path,
    )

    assert "cycle 177: C13 RETIRE-PRESERVE" in packet
    assert "OPERATOR CONTEXT MISSING" not in packet


def test_build_packet_truncates_large_conductor_cycles_context_file(tmp_path: Path) -> None:
    context_dir = tmp_path / ".aragora" / "conductor_cycles"
    context_dir.mkdir(parents=True)
    context_file = context_dir / "cycle_report.md"
    context_file.write_bytes(b"a" * (fable_goal_cycle.MAX_CONTEXT_FILE_BYTES + 50))

    packet = fable_goal_cycle.build_packet(
        {"sections": {}, "gaps": []},
        "standing mission",
        [context_file],
        since_hours=24,
        root=tmp_path,
    )

    assert "context file truncated" in packet
    assert "a" * fable_goal_cycle.MAX_CONTEXT_FILE_BYTES in packet
    assert "a" * (fable_goal_cycle.MAX_CONTEXT_FILE_BYTES + 1) not in packet


def test_build_packet_respects_aggregate_prompt_budget() -> None:
    oversized_body = "x" * (fable_goal_cycle.MAX_PACKET_SECTION_BYTES * 8)

    packet = fable_goal_cycle.build_packet(
        {
            "sections": {
                "large one": oversized_body,
                "large two": oversized_body,
                "large three": oversized_body,
                "large four": oversized_body,
                "large five": oversized_body,
            },
            "gaps": [oversized_body],
        },
        "standing mission",
        [],
        since_hours=24,
    )

    assert len(packet.encode("utf-8")) <= fable_goal_cycle.MAX_PACKET_BYTES
    assert "[truncated " in packet
    assert "## Required response format" in packet
    assert "## NEXT PROMPT" in packet


def test_build_packet_aggregate_truncation_preserves_closed_fences() -> None:
    oversized_body = "x" * fable_goal_cycle.MAX_PACKET_SECTION_BYTES

    packet = fable_goal_cycle.build_packet(
        {
            "sections": {f"large {index}": oversized_body for index in range(10)},
            "gaps": [],
        },
        None,
        [],
        since_hours=24,
    )

    assert "[truncated packet before remaining sections]" in packet
    assert packet.count("```text\n") == packet.count("\n```\n")


def test_build_packet_refuses_sensitive_context_path(tmp_path: Path) -> None:
    context_file = tmp_path / "cycle_report.md"
    context_file.write_text("TOKEN=secret", encoding="utf-8")
    allowed_roots = " or ".join(str(subdir) for subdir in fable_goal_cycle.SAFE_CONTEXT_SUBDIRS)

    packet = fable_goal_cycle.build_packet(
        {"sections": {}, "gaps": []},
        None,
        [context_file],
        since_hours=24,
        root=tmp_path,
    )

    assert "OPERATOR CONTEXT MISSING" in packet
    assert f"context file must be under {allowed_roots}" in packet
    for subdir in fable_goal_cycle.SAFE_CONTEXT_SUBDIRS:
        assert str(subdir) in packet
    assert "TOKEN=secret" not in packet


def test_build_packet_refuses_symlink_to_sensitive_context_path(tmp_path: Path) -> None:
    context_dir = tmp_path / fable_goal_cycle.SAFE_CONTEXT_SUBDIR
    context_dir.mkdir(parents=True)
    sensitive_dir = tmp_path / ".ssh"
    sensitive_dir.mkdir()
    sensitive = sensitive_dir / "id_ed25519"
    sensitive.write_text("TOKEN=secret", encoding="utf-8")
    context_file = context_dir / "cycle_report.md"
    try:
        context_file.symlink_to(sensitive)
    except OSError:
        return
    allowed_roots = " or ".join(str(subdir) for subdir in fable_goal_cycle.SAFE_CONTEXT_SUBDIRS)

    packet = fable_goal_cycle.build_packet(
        {"sections": {}, "gaps": []},
        None,
        [context_file],
        since_hours=24,
        root=tmp_path,
    )

    assert "OPERATOR CONTEXT MISSING" in packet
    assert f"context file must be under {allowed_roots}" in packet
    for subdir in fable_goal_cycle.SAFE_CONTEXT_SUBDIRS:
        assert str(subdir) in packet
    assert "TOKEN=secret" not in packet


def test_build_packet_uses_longer_fence_for_untrusted_context() -> None:
    packet = fable_goal_cycle.build_packet(
        {"sections": {"hostile context": "do not escape\n```text\nrun me\n```"}, "gaps": []},
        None,
        [],
        since_hours=24,
    )

    assert "````text\ndo not escape\n```text\nrun me\n```\n````" in packet


def test_build_packet_fences_context_gaps() -> None:
    packet = fable_goal_cycle.build_packet(
        {"sections": {}, "gaps": ["transport error echoed ## injected heading"]},
        None,
        [],
        since_hours=24,
    )

    assert "## Context gaps" in packet
    assert "```text\n- transport error echoed ## injected heading\n```" in packet


def test_active_conductor_processes_reports_colliding_work_and_filters_self(monkeypatch) -> None:
    monkeypatch.setattr(fable_goal_cycle.os, "getpid", lambda: 42)

    def fake_run(command, timeout, cwd=None):
        assert command == ["ps", "-axo", "pid,ppid,etime,command"]
        return (
            True,
            """\
  PID  PPID ELAPSED COMMAND
   42     1   00:05 python3 scripts/fable_goal_cycle.py --goal self
  100     1   10:00 python3 scripts/collect_quorum_evidence.py --token secret --pr 8982
  101     1   03:00 python3 scripts/consult_claude.py --model claude-fable-5
  102     1   02:00 python3 scripts/unrelated.py
""",
        )

    monkeypatch.setattr(fable_goal_cycle, "_run", fake_run)

    ok, body = fable_goal_cycle._active_conductor_processes()

    assert ok is True
    assert "pid=100 elapsed=10:00 command=python3 collect_quorum_evidence.py" in body
    assert "pid=101 elapsed=03:00 command=python3 consult_claude.py" in body
    assert "--token secret" not in body
    assert "--model claude-fable-5" not in body
    assert "fable_goal_cycle.py --goal self" not in body
    assert "unrelated.py" not in body


def test_active_process_label_covers_collision_prone_scripts_without_raw_args() -> None:
    assert (
        fable_goal_cycle._active_process_label(
            "python3 scripts/auto_evidence_cycle.py --apply --prepared-json /tmp/secret.json"
        )
        == "python3 auto_evidence_cycle.py"
    )
    assert (
        fable_goal_cycle._active_process_label("python3 scripts/boss_drain_pass.py --goal drain")
        == "python3 boss_drain_pass.py"
    )
    assert (
        fable_goal_cycle._active_process_label(
            "python3 scripts/agent_bridge.py launch --token secret"
        )
        == "python3 agent_bridge.py"
    )
    assert (
        fable_goal_cycle._active_process_label("aragora review-queue collect-evidence --pr 1")
        == "aragora review-queue collect-evidence"
    )
    assert fable_goal_cycle._active_process_label("rg fable_goal_cycle.py") is None
    assert fable_goal_cycle._active_process_label("vim scripts/fable_goal_cycle.py") is None


def test_active_conductor_processes_falls_back_to_portable_ps(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, timeout, cwd=None):
        calls.append(command)
        if command == ["ps", "-axo", "pid,ppid,etime,command"]:
            return False, "unsupported ps"
        assert command == ["ps", "-eo", "pid,ppid,etime,command"]
        return (
            True,
            """\
  PID  PPID ELAPSED COMMAND
  200     1   01:00 python3 scripts/settle_pr.py --pr 8988
""",
        )

    monkeypatch.setattr(fable_goal_cycle, "_run", fake_run)

    ok, body = fable_goal_cycle._active_conductor_processes()

    assert ok is True
    assert calls == [
        ["ps", "-axo", "pid,ppid,etime,command"],
        ["ps", "-eo", "pid,ppid,etime,command"],
    ]
    assert "pid=200 elapsed=01:00 command=python3 settle_pr.py" in body


def test_fresh_active_lanes_reports_object_identity(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 4, 15, tzinfo=timezone.utc)
    lanes_path = tmp_path / ".aragora" / "agent-bridge" / "lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text(
        json.dumps(
            [
                {
                    "status": "active",
                    "lane_id": "lane-pr-9083",
                    "owner_session": "session-1",
                    "pr_number": 9083,
                    "branch": "codex/main-red-slice",
                    "worktree": "/private/tmp/aragora-main-red-slice",
                    "last_heartbeat_at": (now - timedelta(minutes=4)).isoformat(),
                    "next_action": "measure current main",
                }
            ]
        ),
        encoding="utf-8",
    )

    body, gaps = fable_goal_cycle._fresh_active_lanes(tmp_path, now=now, home=tmp_path / "home")

    assert gaps == []
    assert body is not None
    assert '"lane_id": "lane-pr-9083"' in body
    assert '"pr_number": 9083' in body
    assert '"branch": "codex/main-red-slice"' in body
    assert '"heartbeat_at": "2026-07-10T04:11:00+00:00"' in body
    assert '"next_action": "measure current main"' in body


def test_fresh_active_lanes_excludes_stale_and_terminal_lanes(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 4, 15, tzinfo=timezone.utc)
    lanes_path = tmp_path / ".aragora" / "agent-bridge" / "lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text(
        json.dumps(
            [
                {
                    "status": "working",
                    "lane_id": "stale-working",
                    "updated_at": (now - timedelta(minutes=16)).isoformat(),
                },
                {
                    "status": "released",
                    "lane_id": "fresh-released",
                    "updated_at": (now - timedelta(minutes=1)).isoformat(),
                },
                {
                    "status": "completed",
                    "lane_id": "fresh-completed",
                    "updated_at": (now - timedelta(minutes=1)).isoformat(),
                },
            ]
        ),
        encoding="utf-8",
    )

    body, gaps = fable_goal_cycle._fresh_active_lanes(tmp_path, now=now, home=tmp_path / "home")

    assert body == "none observed"
    assert gaps == []


def test_fresh_active_lanes_surfaces_bad_entries_as_gap(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 4, 15, tzinfo=timezone.utc)
    lanes_path = tmp_path / ".aragora" / "agent-bridge" / "lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text(
        json.dumps([42, {"status": "active", "lane_id": "bad-time", "updated_at": "nope"}]),
        encoding="utf-8",
    )

    body, gaps = fable_goal_cycle._fresh_active_lanes(tmp_path, now=now, home=tmp_path / "home")

    assert body == "none observed"
    assert len(gaps) == 1
    assert "skipped 2 malformed lane entries" in gaps[0]


def test_fresh_active_lanes_surfaces_missing_and_malformed_registry(tmp_path: Path) -> None:
    body, gaps = fable_goal_cycle._fresh_active_lanes(tmp_path, home=tmp_path / "home")

    assert body is None
    assert len(gaps) == 1
    assert "lane registries missing" in gaps[0]

    lanes_path = tmp_path / ".aragora" / "agent-bridge" / "lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text("{not-json", encoding="utf-8")

    body, gaps = fable_goal_cycle._fresh_active_lanes(tmp_path, home=tmp_path / "home")

    assert body is None
    assert len(gaps) == 1
    assert "lanes registry malformed" in gaps[0]


def test_gather_context_includes_fresh_active_lane_section(monkeypatch, tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    lanes_path = tmp_path / ".aragora" / "agent-bridge" / "lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text(
        json.dumps(
            [
                {
                    "status": "active",
                    "lane_id": "lane-owned-branch",
                    "branch": "codex/owned-branch",
                    "updated_at": now.isoformat(),
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fable_goal_cycle, "_run", lambda *args, **kwargs: (False, "offline"))
    monkeypatch.setattr(
        fable_goal_cycle, "_active_conductor_processes", lambda: (True, "none observed")
    )
    monkeypatch.setattr(fable_goal_cycle.shutil, "which", lambda _name: None)

    context = fable_goal_cycle.gather_context(
        tmp_path, since_hours=24, max_prs=30, skip_digest=True
    )

    body = context["sections"]["fresh active lanes (object ownership)"]
    assert '"lane_id": "lane-owned-branch"' in body
    assert '"branch": "codex/owned-branch"' in body


def test_fresh_active_lanes_merges_canonical_registries_and_statuses(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 4, 15, tzinfo=timezone.utc)
    home = tmp_path / "home"
    home_path = home / ".aragora" / "agent-bridge" / "lanes.json"
    repo_path = tmp_path / ".aragora" / "agent-bridge" / "lanes.json"
    home_path.parent.mkdir(parents=True)
    repo_path.parent.mkdir(parents=True)
    home_path.write_text(
        json.dumps(
            [
                {
                    "status": "running",
                    "lane_id": "shared-lane",
                    "owner_session": "home-owner",
                    "branch": "codex/from-home",
                    "updated_at": (now - timedelta(minutes=5)).isoformat(),
                },
                {
                    "status": "queued",
                    "lane_id": "home-only",
                    "updated_at": (now - timedelta(minutes=3)).isoformat(),
                },
            ]
        ),
        encoding="utf-8",
    )
    repo_path.write_text(
        json.dumps(
            [
                {
                    "status": "blocked",
                    "lane_id": "shared-lane",
                    "owner_session": "repo-owner",
                    "updated_at": (now - timedelta(minutes=1)).isoformat(),
                }
            ]
        ),
        encoding="utf-8",
    )

    body, gaps = fable_goal_cycle._fresh_active_lanes(tmp_path, now=now, home=home)

    assert gaps == []
    assert body is not None
    assert body.count('"lane_id": "shared-lane"') == 1
    assert '"owner_session": "repo-owner"' in body
    assert '"branch": "codex/from-home"' in body
    assert '"lane_id": "home-only"' in body


def test_fresh_active_lanes_surfaces_partial_utf8_degradation(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 4, 15, tzinfo=timezone.utc)
    home = tmp_path / "home"
    home_path = home / ".aragora" / "agent-bridge" / "lanes.json"
    repo_path = tmp_path / ".aragora" / "agent-bridge" / "lanes.json"
    home_path.parent.mkdir(parents=True)
    repo_path.parent.mkdir(parents=True)
    home_path.write_bytes(b"\xff\xfe")
    repo_path.write_text(
        json.dumps(
            [
                {
                    "status": "claimed",
                    "lane_id": "repo-lane",
                    "updated_at": (now - timedelta(minutes=1)).isoformat(),
                }
            ]
        ),
        encoding="utf-8",
    )

    body, gaps = fable_goal_cycle._fresh_active_lanes(tmp_path, now=now, home=home)

    assert body is not None
    assert '"lane_id": "repo-lane"' in body
    assert len(gaps) == 1
    assert "lanes registry unreadable" in gaps[0]
    assert str(home_path) in gaps[0]


def test_fresh_active_lanes_falls_back_from_bad_heartbeat_to_updated_at(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 10, 4, 15, tzinfo=timezone.utc)
    lanes_path = tmp_path / ".aragora" / "agent-bridge" / "lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text(
        json.dumps(
            [
                {
                    "status": "acknowledged",
                    "lane_id": "fallback-lane",
                    "last_heartbeat_at": "not-a-time",
                    "updated_at": (now - timedelta(minutes=2)).isoformat(),
                }
            ]
        ),
        encoding="utf-8",
    )

    body, gaps = fable_goal_cycle._fresh_active_lanes(tmp_path, now=now, home=tmp_path / "home")

    assert gaps == []
    assert body is not None
    assert '"lane_id": "fallback-lane"' in body
    assert '"heartbeat_at": "2026-07-10T04:13:00+00:00"' in body


def test_response_instructions_make_fresh_lane_ownership_per_object() -> None:
    instructions = fable_goal_cycle.RESPONSE_FORMAT_INSTRUCTIONS

    assert "fresh active lane" in instructions
    assert "PR, branch, or worktree" in instructions
    assert "per-object" in instructions
    assert "not a global lock" in instructions


def test_run_consult_sets_overall_timeout_and_bounded_outer_timeout(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, timeout, cwd=None):
        captured["command"] = command
        captured["timeout"] = timeout
        captured["cwd"] = cwd
        return True, json.dumps({"ok": True, "text": "advice"})

    monkeypatch.setattr(fable_goal_cycle, "_run", fake_run)

    result = fable_goal_cycle.run_consult(
        tmp_path / "consult_claude.py",
        tmp_path / "packet.md",
        "claude-fable-5",
        timeout=12.5,
    )

    command = captured["command"]
    assert result["ok"] is True
    assert command[command.index("--timeout") + 1] == "12.5"
    assert command[command.index("--overall-timeout") + 1] == "25.0"
    assert captured["timeout"] == 85.0


def test_run_consult_rejects_success_without_text(monkeypatch, tmp_path: Path) -> None:
    def fake_run(command, timeout, cwd=None):
        return True, json.dumps({"ok": True, "model": "claude-fable-5"})

    monkeypatch.setattr(fable_goal_cycle, "_run", fake_run)

    result = fable_goal_cycle.run_consult(
        tmp_path / "consult_claude.py",
        tmp_path / "packet.md",
        "claude-fable-5",
        timeout=12.5,
    )

    assert result["ok"] is False
    assert "without text" in result["error"]


def test_run_consult_direct_mode_does_not_budget_proxy_attempts(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, timeout, cwd=None):
        captured["command"] = command
        captured["timeout"] = timeout
        return True, json.dumps({"ok": True, "text": "advice"})

    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "direct")
    monkeypatch.setattr(fable_goal_cycle, "_run", fake_run)

    result = fable_goal_cycle.run_consult(
        tmp_path / "consult_claude.py",
        tmp_path / "packet.md",
        "claude-fable-5",
        timeout=12.5,
    )

    command = captured["command"]
    assert result["ok"] is True
    assert command[command.index("--overall-timeout") + 1] == "25.0"
    assert captured["timeout"] == 85.0


def test_run_consult_prefer_mode_budgets_unique_proxy_models(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, timeout, cwd=None):
        captured["command"] = command
        captured["timeout"] = timeout
        return True, json.dumps({"ok": True, "text": "advice"})

    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-prefer")
    monkeypatch.setattr(fable_goal_cycle, "_run", fake_run)

    result = fable_goal_cycle.run_consult(
        tmp_path / "consult_claude.py",
        tmp_path / "packet.md",
        fable_goal_cycle.CONSULT_FALLBACK_MODEL,
        timeout=12.5,
    )

    command = captured["command"]
    assert result["ok"] is True
    assert command[command.index("--overall-timeout") + 1] == "25.0"
    assert captured["timeout"] == 85.0


def test_run_consult_required_mode_excludes_unreachable_fallbacks(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, timeout, cwd=None):
        captured["command"] = command
        captured["timeout"] = timeout
        return True, json.dumps({"ok": False, "error": "proxy unavailable"})

    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-required")
    monkeypatch.setattr(fable_goal_cycle, "_run", fake_run)

    result = fable_goal_cycle.run_consult(
        tmp_path / "consult_claude.py",
        tmp_path / "packet.md",
        "claude-fable-5",
        timeout=12.5,
        openrouter_fallback=True,
    )

    command = captured["command"]
    assert result["ok"] is False
    assert command[command.index("--overall-timeout") + 1] == "25.0"
    assert captured["timeout"] == 85.0


def test_run_consult_empty_transport_uses_direct_default(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, timeout, cwd=None):
        captured["command"] = command
        captured["timeout"] = timeout
        return True, json.dumps({"ok": True, "text": "advice"})

    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "")
    monkeypatch.setattr(fable_goal_cycle, "_run", fake_run)

    result = fable_goal_cycle.run_consult(
        tmp_path / "consult_claude.py",
        tmp_path / "packet.md",
        "claude-fable-5",
        timeout=12.5,
    )

    command = captured["command"]
    assert result["ok"] is True
    assert command[command.index("--overall-timeout") + 1] == "25.0"
    assert captured["timeout"] == 85.0


def test_run_consult_rejects_invalid_transport_without_running(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-require")
    monkeypatch.setattr(
        fable_goal_cycle,
        "_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    result = fable_goal_cycle.run_consult(
        tmp_path / "consult_claude.py",
        tmp_path / "packet.md",
        "claude-fable-5",
        timeout=12.5,
    )

    assert result == {
        "ok": False,
        "error": "invalid ARAGORA_MODEL_TRANSPORT: vibeproxy-require",
    }


def test_run_consult_can_enable_openrouter_fallback(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, timeout, cwd=None):
        captured["command"] = command
        captured["timeout"] = timeout
        captured["cwd"] = cwd
        return True, json.dumps({"ok": True, "text": "advice"})

    monkeypatch.setattr(fable_goal_cycle, "_run", fake_run)

    result = fable_goal_cycle.run_consult(
        tmp_path / "consult_claude.py",
        tmp_path / "packet.md",
        "claude-fable-5",
        timeout=12.5,
        openrouter_fallback=True,
        openrouter_model="anthropic/claude-test",
    )

    command = captured["command"]
    assert result["ok"] is True
    assert "--openrouter-fallback" in command
    assert command[command.index("--openrouter-model") + 1] == "anthropic/claude-test"
    assert command[command.index("--overall-timeout") + 1] == "37.5"
    assert captured["timeout"] == 97.5
