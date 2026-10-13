"""Keep every automated merge path behind the main-red halt (#9216).

``.aragora/merge_executor.halt`` is armed when main is red. Before this guard
only ``scripts/merge_executor.py`` read it, so PRs #9115 and #9111 merged on
2026-07-11 while it was armed. Three kinds of test keep that from recurring:

* guard behaviour: the guard fails closed on every ambiguous input and admits
  only an exact-head, unexpired, single-PR waiver;
* structure: every module under ``aragora/`` and ``scripts/`` that invokes a
  merge is in ``GUARDED_MERGE_PATHS``, and the named function calls the guard. A
  new merge path fails the inventory test until it is wired and listed;
* obedience: each listed path is driven with an armed halt and a spy runner, and
  must refuse without running a merge. A call whose result is ignored passes the
  structural test, so only these tests prove the halt is obeyed.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aragora.swarm.merge_halt as guard  # noqa: E402

PR = 9115
HEAD = "f4a650dcd532596dcf93ceeed69e70b4bce90420"
OTHER_HEAD = "0" * 40
REPO = "synaptent/aragora"
NOW = dt.datetime(2026, 7, 11, 6, 0, tzinfo=dt.timezone.utc)


def _write_waiver(path: Path, **overrides: Any) -> Path:
    payload: dict[str, Any] = {
        "pr": PR,
        "head_sha": HEAD,
        "actor": "operator",
        "scope": "single-pr",
        "reason": "incident waiver",
        "expires_at": "2026-07-11T12:00:00+00:00",
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def halt(tmp_path: Path) -> Path:
    path = tmp_path / "merge_executor.halt"
    path.write_text(json.dumps({"reason": "main_red"}) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def waiver_path(tmp_path: Path) -> Path:
    return tmp_path / "merge_executor.waiver"


def _evaluate(halt_file: Path, waiver_file: Path, *, pr: int = PR, head: str = HEAD):
    return guard.evaluate_merge_halt(
        pr, head, halt_file=halt_file, waiver_file=waiver_file, now=NOW
    )


# ---------------------------------------------------------------------------
# Guard behaviour
# ---------------------------------------------------------------------------


def test_no_halt_marker_allows_merge(tmp_path: Path, waiver_path: Path) -> None:
    decision = _evaluate(tmp_path / "absent.halt", waiver_path)
    assert decision.allowed, decision.reason


def test_armed_halt_blocks_merge(halt: Path, waiver_path: Path) -> None:
    """The #9115 / #9111 case: armed halt, no waiver."""
    decision = _evaluate(halt, waiver_path)
    assert not decision.allowed
    assert decision.halt_reason == "main_red"


def test_exact_head_waiver_allows_merge(halt: Path, waiver_path: Path) -> None:
    _write_waiver(waiver_path)
    decision = _evaluate(halt, waiver_path)
    assert decision.allowed, decision.reason
    assert decision.waiver_actor == "operator"


def test_waiver_without_halt_is_irrelevant(tmp_path: Path, waiver_path: Path) -> None:
    _write_waiver(waiver_path, pr=1)
    assert _evaluate(tmp_path / "absent.halt", waiver_path).allowed


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"pr": 9111}, "not #9115"),
        ({"pr": "9115"}, "must be an integer"),
        ({"pr": True}, "must be an integer"),
        ({"head_sha": OTHER_HEAD}, "!= merge head"),
        ({"head_sha": HEAD[:12]}, "not a full 40-char SHA"),
        ({"scope": "all"}, "single-pr"),
        ({"actor": ""}, "empty actor"),
        ({"actor": None}, "actor must be a string"),
        ({"reason": ""}, "empty reason"),
        ({"reason": None}, "reason must be a string"),
        ({"expires_at": "2026-07-11T12:00:00"}, "timezone"),
        ({"expires_at": "tomorrow"}, "not ISO-8601"),
        ({"expires_at": "2026-07-11T05:59:00+00:00"}, "expired"),
    ],
)
def test_non_matching_waiver_keeps_the_halt(
    halt: Path, waiver_path: Path, overrides: dict[str, Any], expected: str
) -> None:
    _write_waiver(waiver_path, **overrides)
    decision = _evaluate(halt, waiver_path)
    assert not decision.allowed
    assert expected in decision.reason


def test_waiver_missing_a_field_keeps_the_halt(halt: Path, waiver_path: Path) -> None:
    payload = {"pr": PR, "head_sha": HEAD, "actor": "operator", "scope": "single-pr"}
    waiver_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not _evaluate(halt, waiver_path).allowed


def test_matching_abbreviations_on_both_sides_do_not_apply(halt: Path, waiver_path: Path) -> None:
    """Equal abbreviations would let one waiver cover every commit with that prefix."""
    _write_waiver(waiver_path, head_sha=HEAD[:12])
    assert not _evaluate(halt, waiver_path, head=HEAD[:12]).allowed


@pytest.mark.parametrize("content", ["{not json", "", "[1, 2]", "\xff\xfe"])
def test_unparseable_halt_marker_fails_closed(
    tmp_path: Path, waiver_path: Path, content: str
) -> None:
    """A marker that exists but does not parse, including an empty ``touch``, is armed."""
    marker = tmp_path / "merge_executor.halt"
    marker.write_bytes(content.encode("latin-1"))
    decision = _evaluate(marker, waiver_path)
    assert not decision.allowed
    assert "failing closed" in decision.reason


def test_corrupt_waiver_keeps_the_halt(halt: Path, waiver_path: Path) -> None:
    waiver_path.write_text("{not json", encoding="utf-8")
    assert not _evaluate(halt, waiver_path).allowed


def test_uninspectable_halt_marker_is_not_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, waiver_path: Path
) -> None:
    """``Path.exists()`` returns False on any OSError; the guard must not.

    A stat failure other than "not found" (for example an unsearchable parent
    directory) must fail closed rather than read as "no halt marker present".
    """
    marker = tmp_path / "locked" / "merge_executor.halt"
    real_stat = os.stat

    def stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if Path(path) == marker:
            raise PermissionError(13, "Permission denied", str(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(guard.os, "stat", stat)
    decision = _evaluate(marker, waiver_path)
    assert not decision.allowed
    assert "could not be inspected" in decision.reason


def test_unresolved_shared_checkout_fails_closed_for_the_default_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(guard, "SHARED_ROOT_ERROR", "bad gitdir")
    monkeypatch.setattr(guard, "DEFAULT_HALT_FILE", tmp_path / "absent.halt")
    decision = guard.evaluate_merge_halt(PR, HEAD)
    assert not decision.allowed
    assert "bad gitdir" in decision.reason


def test_assert_merge_allowed_raises_when_halted(halt: Path, waiver_path: Path) -> None:
    with pytest.raises(guard.MergeHalted, match=str(PR)):
        guard.assert_merge_allowed(PR, HEAD, halt_file=halt, waiver_file=waiver_path, now=NOW)


def test_linked_worktree_uses_primary_checkout_markers(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    common = primary / ".git"
    git_dir = common / "worktrees" / "worker"
    (common / "objects").mkdir(parents=True)
    git_dir.mkdir(parents=True)
    (git_dir / "commondir").write_text("../..\n", encoding="utf-8")
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")

    assert guard._shared_checkout_root(worker) == primary
    assert guard._shared_checkout_root(primary) == primary


def test_malformed_linked_worktree_metadata_raises(tmp_path: Path) -> None:
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / ".git").write_text("not-a-gitdir\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="could not resolve shared git state"):
        guard._shared_checkout_root(worker)


def test_halt_writer_and_executor_default_to_the_guard_marker() -> None:
    """The arming lane, merge_executor and the guard must default to one marker.

    Checked in the source because the autouse isolation fixture patches the
    guard's constant, so a runtime comparison depends on import order.
    """
    for path in ("scripts/merge_executor.py", "scripts/pristine_main_health.py"):
        tree = ast.parse((PROJECT_ROOT / path).read_text(encoding="utf-8"))
        imported = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "aragora.swarm.merge_halt"
            and any(a.name == "DEFAULT_HALT_FILE" and not a.asname for a in node.names)
            for node in tree.body
        )
        assigned = any(
            isinstance(node, ast.Assign)
            and any(getattr(target, "id", None) == "DEFAULT_HALT_FILE" for target in node.targets)
            for node in tree.body
        )
        assert imported and not assigned, f"{path} must take DEFAULT_HALT_FILE from the guard"


def test_disarm_file_resolves_beside_the_shared_halt() -> None:
    """A disarm placed beside the halt must stop an executor in a linked worktree."""
    import scripts.merge_executor as merge_executor

    shared_halt = guard.SHARED_REPO_ROOT / ".aragora" / "merge_executor.halt"
    assert merge_executor.DEFAULT_DISARM_FILE.parent == shared_halt.parent


# ---------------------------------------------------------------------------
# Structure: the inventory of merge paths
# ---------------------------------------------------------------------------

# A merge that is invoked, not merely named. Prose, worktree ``--strategy merge``
# and gh-subcommand allowlists do not match. The last pattern also catches a
# wrapper that supplies ``gh`` itself (``_run_gh(["pr", "merge", ...])``).
_MERGE_INVOCATIONS = (
    re.compile(r'\[[^\]]*"gh"\s*,\s*"pr"\s*,\s*"merge"', re.S),
    re.compile(r'"pr"\s*,\s*"merge"\s*,\s*str\(', re.S),
    re.compile(r'f?"gh pr merge [^"]*\{'),
    re.compile(r'\+=\s*\[\s*"merge"'),
    re.compile(r'\.append\(\s*"merge"\s*\)'),
    re.compile(r'"pr"\s*,\s*"merge"', re.S),
)
# The forms that hand an argv to a runner, used to re-check the exclusions.
_EXECUTION_SHAPED = _MERGE_INVOCATIONS[:2]

# Module -> the function that executes its merge. That function must call the
# guard for the head it merges.
GUARDED_MERGE_PATHS = {
    "aragora/missions/live_gate.py": "LiveBossLoopGate.merge_head_bound",
    "aragora/ralph/github_control.py": "GitHubControl.merge_pr",
    "aragora/swarm/merge_arbiter.py": "_merge_pr",
    "scripts/auto_merge_bucket_a.py": "gh_pr_merge_squash",
    "scripts/auto_merge_quorum_green.py": "_make_merge_fn.merge_fn",
    "scripts/boss_drain_pass.py": "make_execute_fn.execute",
    "scripts/drain_codex_automation_value.py": "_run_merge_phase",
    "scripts/merge_codex_automation_prs.py": "_merge_pr",
    "scripts/settle_tier4_pr.py": "_apply_merge",
}

# Modules the scan matches that never execute a merge, with the source text that
# makes each claim true. The test re-checks the evidence instead of trusting it.
NON_MERGE_MENTIONS = {
    # ACTIVE_PROCESS_COMMAND_PATTERNS matches running processes; it runs nothing.
    "scripts/fable_goal_cycle.py": "ACTIVE_PROCESS_COMMAND_PATTERNS",
    # The merge command is appended to a report for the operator, never run.
    "scripts/settle_one_pr.py": 'suggested_commands"].append',
}

_GUARD_MODULE = "aragora.swarm.merge_halt"
_GUARD_FUNCTIONS = {"evaluate_merge_halt", "assert_merge_allowed"}
_DOCSTRING_RE = re.compile(r'"""(?:.|\n)*?"""')


def _discovered_merge_modules() -> set[str]:
    found: set[str] = set()
    for pattern in ("aragora/**/*.py", "scripts/**/*.py"):
        for path in sorted(PROJECT_ROOT.glob(pattern)):
            text = _DOCSTRING_RE.sub("", path.read_text(encoding="utf-8", errors="replace"))
            if any(rx.search(text) for rx in _MERGE_INVOCATIONS):
                found.add(path.relative_to(PROJECT_ROOT).as_posix())
    return found


def test_merge_path_inventory_is_current() -> None:
    discovered = _discovered_merge_modules()
    declared = set(GUARDED_MERGE_PATHS) | set(NON_MERGE_MENTIONS)
    unlisted = sorted(discovered - declared)
    assert not unlisted, (
        f"{unlisted} invoke a merge but are not in GUARDED_MERGE_PATHS. Call "
        "aragora.swarm.merge_halt for the merged head and list the path, or record "
        "in NON_MERGE_MENTIONS why it does not merge (#9216)."
    )
    stale = sorted(declared - discovered)
    assert not stale, f"{stale} no longer invoke a merge; remove them from the inventory."


def _find_function(tree: ast.Module, qualname: str) -> ast.FunctionDef | None:
    scope: list[ast.stmt] = list(tree.body)
    node: ast.AST | None = None
    for part in qualname.split("."):
        node = next(
            (
                item
                for item in scope
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and item.name == part
            ),
            None,
        )
        if node is None:
            return None
        scope = list(node.body)
    return node if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) else None


def _guard_bindings(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Names bound to the guard's functions, and names bound to the guard module."""
    functions: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == _GUARD_MODULE:
            functions |= {a.asname or a.name for a in node.names if a.name in _GUARD_FUNCTIONS}
        elif isinstance(node, ast.ImportFrom) and node.module == "aragora.swarm":
            modules |= {a.asname or a.name for a in node.names if a.name == "merge_halt"}
        elif isinstance(node, ast.Import):
            modules |= {a.asname for a in node.names if a.name == _GUARD_MODULE and a.asname}
    return functions, modules


def _calls_guard(function: ast.FunctionDef, functions: set[str], modules: set[str]) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in functions:
            return True
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _GUARD_FUNCTIONS
            and isinstance(func.value, ast.Name)
            and func.value.id in modules
        ):
            return True
    return False


@pytest.mark.parametrize(("path", "qualname"), sorted(GUARDED_MERGE_PATHS.items()))
def test_every_merge_path_calls_the_guard(path: str, qualname: str) -> None:
    tree = ast.parse((PROJECT_ROOT / path).read_text(encoding="utf-8"))
    function = _find_function(tree, qualname)
    assert function is not None, f"{path} no longer defines {qualname}; update the inventory"
    functions, modules = _guard_bindings(tree)
    assert _calls_guard(function, functions, modules), (
        f"{path}:{qualname} merges but never calls {_GUARD_MODULE}. This is how PRs "
        "#9115 and #9111 merged while the halt was armed (#9216). An import alone is "
        "not coverage."
    )


def test_non_merge_mentions_really_do_not_merge() -> None:
    for path, evidence in sorted(NON_MERGE_MENTIONS.items()):
        text = (PROJECT_ROOT / path).read_text(encoding="utf-8")
        assert evidence in text, (
            f"{path} is excluded because of {evidence!r}, which is gone. "
            "Re-check whether it now merges."
        )
        stripped = _DOCSTRING_RE.sub("", text)
        assert not any(rx.search(stripped) for rx in _EXECUTION_SHAPED), (
            f"{path} is excluded as non-merging but now builds an executable merge argv."
        )


def test_merge_executor_merges_only_through_the_guarded_merge_fn() -> None:
    """merge_executor keeps its own halt check and borrows the guarded merge_fn."""
    text = (PROJECT_ROOT / "scripts/merge_executor.py").read_text(encoding="utf-8")
    assert "scripts/merge_executor.py" not in _discovered_merge_modules()
    assert "return _amqg._make_merge_fn(repo)" in text
    assert "halt_file.exists()" in text


# ---------------------------------------------------------------------------
# Obedience: each path refuses to merge while the halt is armed
# ---------------------------------------------------------------------------


@pytest.fixture
def armed(monkeypatch: pytest.MonkeyPatch, halt: Path, waiver_path: Path) -> Path:
    """Arm the default halt the merge paths read, with no waiver present."""
    monkeypatch.setattr(guard, "DEFAULT_HALT_FILE", halt)
    monkeypatch.setattr(guard, "DEFAULT_WAIVER_FILE", waiver_path)
    monkeypatch.setattr(guard, "SHARED_ROOT_ERROR", None)
    return waiver_path


def _future_waiver(path: Path, **overrides: Any) -> Path:
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    return _write_waiver(path, expires_at=expires.isoformat(), **overrides)


class _Spy:
    """Record every command; succeed for everything."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def record(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append([str(arg) for arg in args])
        return subprocess.CompletedProcess(list(args), 0, stdout="{}", stderr="")

    def merges(self) -> list[list[str]]:
        return [
            call
            for call in self.calls
            if any(call[i : i + 2] == ["pr", "merge"] for i in range(len(call) - 1))
        ]


def _merge_ralph(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, spy: _Spy) -> Any:
    from aragora.ralph.github_control import GitHubControl

    monkeypatch.setattr(
        "aragora.ralph.github_control.subprocess.run", lambda args, **_: spy.record(args)
    )
    return GitHubControl(repo_root=tmp_path).merge_pr(
        f"https://github.com/{REPO}/pull/{PR}",
        required_checks_green=True,
        allow_admin=True,
        head_sha=HEAD,
    )


def test_ralph_refuses_while_halted(armed, monkeypatch, tmp_path) -> None:
    spy = _Spy()
    result = _merge_ralph(monkeypatch, tmp_path, spy)
    assert (result.merged, result.action) == (False, "blocked")
    assert "halt armed" in result.detail
    assert spy.merges() == []


def test_ralph_merges_a_waived_head_pinned_to_that_head(armed, monkeypatch, tmp_path) -> None:
    _future_waiver(armed)
    spy = _Spy()
    result = _merge_ralph(monkeypatch, tmp_path, spy)
    assert result.merged is True
    assert [call[-2:] for call in spy.merges()] == [["--match-head-commit", HEAD]]


def test_ralph_waiver_for_another_head_does_not_apply(armed, monkeypatch, tmp_path) -> None:
    _future_waiver(armed, head_sha=OTHER_HEAD)
    spy = _Spy()
    assert _merge_ralph(monkeypatch, tmp_path, spy).merged is False
    assert spy.merges() == []


def test_live_gate_refuses_while_halted(armed, monkeypatch, tmp_path) -> None:
    from aragora.missions.dispatch import GateVerdict
    from aragora.missions.live_gate import LiveBossLoopGate

    spy = _Spy()
    gate = LiveBossLoopGate(repo_root=tmp_path, runner=lambda cmd, _cwd: spy.record(cmd).stdout)
    gate._metadata_by_branch["mission/f1"] = {"pr": PR}
    monkeypatch.setattr(
        gate, "collect_evidence", lambda _branch, _head: GateVerdict(satisfied=True, tier=1)
    )
    assert gate.merge_head_bound("mission/f1", HEAD) is False
    assert spy.merges() == []


def test_merge_arbiter_refuses_while_halted(armed, monkeypatch) -> None:
    from aragora.swarm import merge_arbiter

    spy = _Spy()
    monkeypatch.setattr(merge_arbiter, "_run_gh", lambda args, **_: spy.record(args))
    ok, reason = merge_arbiter._merge_pr(PR, REPO, HEAD)
    assert ok is False
    assert "halt armed" in reason
    assert spy.merges() == []


def test_bucket_a_refuses_while_halted(armed) -> None:
    import scripts.auto_merge_bucket_a as bucket_a

    spy = _Spy()
    with pytest.raises(guard.MergeHalted):
        bucket_a.gh_pr_merge_squash(PR, HEAD, runner=spy.record)
    assert spy.merges() == []


def test_bucket_a_merges_a_waived_head(armed) -> None:
    import scripts.auto_merge_bucket_a as bucket_a

    _future_waiver(armed)
    spy = _Spy()
    bucket_a.gh_pr_merge_squash(PR, HEAD, runner=spy.record)
    assert len(spy.merges()) == 1
    assert HEAD in spy.merges()[0]


def test_bucket_a_merges_when_not_halted(tmp_path, monkeypatch) -> None:
    """The guard must not block the normal path, or it is only an outage."""
    import scripts.auto_merge_bucket_a as bucket_a

    monkeypatch.setattr(guard, "DEFAULT_HALT_FILE", tmp_path / "absent.halt")
    monkeypatch.setattr(guard, "SHARED_ROOT_ERROR", None)
    spy = _Spy()
    bucket_a.gh_pr_merge_squash(PR, HEAD, runner=spy.record)
    assert len(spy.merges()) == 1


def test_quorum_green_merge_fn_refuses_while_halted(armed, monkeypatch) -> None:
    """merge_executor merges through auto_merge_quorum_green's merge_fn."""
    import scripts.auto_merge_quorum_green as quorum_green
    import scripts.merge_executor as merge_executor

    spy = _Spy()
    monkeypatch.setattr(subprocess, "run", lambda args, **_: spy.record(args))
    for make in (quorum_green._make_merge_fn, merge_executor.make_merge_fn):
        ok, reason = make(REPO)(PR, HEAD)
        assert ok is False
        assert "halt armed" in reason
    assert spy.merges() == []


def test_boss_drain_refuses_while_halted(armed, monkeypatch) -> None:
    import scripts.boss_drain_pass as boss_drain_pass
    from aragora.swarm.drain_policy import DrainAction

    spy = _Spy()
    monkeypatch.setattr(boss_drain_pass, "_settle_authorized", lambda _repo, _pr: HEAD)
    monkeypatch.setattr(boss_drain_pass.subprocess, "run", lambda args, **_: spy.record(args))
    execute = boss_drain_pass.make_execute_fn(REPO, dry_run=False)
    assert execute(PR, DrainAction.MERGE) is False
    assert spy.merges() == []


def test_codex_value_drain_refuses_while_halted(armed, monkeypatch, tmp_path) -> None:
    import scripts.drain_codex_automation_value as drain

    evaluation = drain.MergeEvaluation(
        pr_number=PR,
        title="t",
        url="u",
        head_sha=HEAD,
        eligible=True,
        reason="eligible",
        blockers=[],
        command=drain.protected_squash_merge_command(PR, HEAD),
    )
    monkeypatch.setattr(drain, "_open_codex_prs", lambda *_: ([{"number": PR}], {}))
    monkeypatch.setattr(drain, "_inspect_merge_candidate", lambda *_: (evaluation, []))
    config = drain.DrainConfig(
        repo_root=tmp_path,
        github_repo=REPO,
        state_root=tmp_path,
        outbox_dir=tmp_path,
        receipt_dir=tmp_path,
        cache_output=None,
        base="origin/main",
        branch_limit=0,
        issue_limit=0,
        merge_limit=1,
        max_open_prs=0,
        max_open_issues=0,
        branch_scan_limit=0,
        apply=True,
    )
    spy = _Spy()
    phase = drain._run_merge_phase(config, lambda args, _cwd: spy.record(args))
    assert phase["ok"] is False
    assert phase["merged"] == []
    assert phase["skipped"][-1]["reason"] == "merge halt armed"
    assert spy.merges() == []


def test_codex_automation_merger_refuses_while_halted(armed, monkeypatch, tmp_path) -> None:
    import scripts.merge_codex_automation_prs as merger

    spy = _Spy()
    monkeypatch.setattr(merger, "_run", lambda args, **_: spy.record(args))
    with pytest.raises(guard.MergeHalted):
        merger._merge_pr(tmp_path, REPO, PR, HEAD)
    assert spy.merges() == []


def test_settle_tier4_refuses_while_halted(armed, monkeypatch, tmp_path) -> None:
    import scripts.settle_tier4_pr as settle_tier4_pr

    spy = _Spy()
    monkeypatch.setattr(settle_tier4_pr, "_run_command", lambda args, **_: spy.record(args))
    with pytest.raises(settle_tier4_pr.Tier4ApplyError) as excinfo:
        settle_tier4_pr._apply_merge(pr=PR, head=HEAD, repo=REPO, cwd=tmp_path)
    assert excinfo.value.phase == "merge_halt"
    assert excinfo.value.mutation_occurred is False
    assert spy.calls == []
