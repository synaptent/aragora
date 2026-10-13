"""Tests for the boss-loop drain driver (injected I/O; safe-by-construction)."""

from __future__ import annotations

from aragora.swarm.boss_drain import (
    DrainContext,
    build_candidates,
    classify_candidate,
    make_repair_order,
    make_repair_prompt,
    run_boss_drain,
    touches_merge_authority,
)
from aragora.swarm.drain_pass import DrainPassPolicy
from aragora.swarm.drain_policy import DrainAction


def test_repair_prompt_is_scope_locked() -> None:
    pr = make_repair_prompt(8460, "codex/red")
    # must pin the branch, forbid scope-broadening, forbid touching gate logic, bound effort
    assert "codex/red" in pr and "#8460" in pr
    assert "ONLY" in pr and "branch" in pr
    assert "review_queue" in pr and "quorum" in pr  # gate logic explicitly off-limits
    assert "STOP" in pr  # bounded — must not thrash


def test_make_repair_order_defaults_to_codex() -> None:
    o = make_repair_order(8460, "codex/red")
    assert o.pr == 8460 and o.branch == "codex/red" and o.agent == "codex"
    assert o.to_dict()["prompt"] == o.prompt


def test_merge_authority_files_force_off_limits() -> None:
    # A green, mergeable, low-tier PR that touches the EVIDENCE PARSER (gate logic)
    # must be LEFT — the drain may never auto-merge merge-authority surfaces (#8467 class).
    view = {
        "number": 8467,
        "headRefName": "codex/evidence-fix",
        "changedFiles": 2,
        "files": [
            {"path": "aragora/cli/commands/review_queue_comment_verdicts.py"},
            {"path": "tests/cli/commands/test_review_queue.py"},
        ],
    }
    c = classify_candidate(view, DrainContext(), merge_authorized=True, tier=0)
    assert c.off_limits is True  # gate logic — never auto-merged


def test_touches_merge_authority_patterns() -> None:
    assert touches_merge_authority(["aragora/swarm/quorum_evidence.py"]) is True
    assert touches_merge_authority(["scripts/settle_one_pr.py"]) is True
    assert touches_merge_authority([".github/workflows/aragora-merge-quorum.yml"]) is True
    assert touches_merge_authority(["aragora/debate/orchestrator.py"]) is False


def test_merge_authority_patterns_are_anchored_no_overshoot() -> None:
    # Genuine gate surfaces stay fenced.
    assert touches_merge_authority(["scripts/settle_one_pr.py"]) is True
    assert touches_merge_authority(["scripts/settle_tier4.py"]) is True
    assert touches_merge_authority(["aragora/review/settlement_outcome.py"]) is True
    assert touches_merge_authority(["aragora/cli/commands/review_queue_parsers.py"]) is True
    # Unrelated "settlement"/"settle" files must NOT be fenced — a bare substring
    # match overshot (e.g. it would have stranded any of these in LEAVE).
    assert touches_merge_authority(["aragora/debate/settlement.py"]) is False
    assert touches_merge_authority(["aragora/markets/credit_settlement.py"]) is False
    assert touches_merge_authority(["aragora/reputation/settlement.py"]) is False
    assert touches_merge_authority(["aragora/blockchain/receipt_settlement.py"]) is False


def test_classify_off_limits_branch_prefix() -> None:
    c = classify_candidate(
        {"number": 1, "headRefName": "structex/p2-docs", "changedFiles": 3},
        DrainContext(),
        merge_authorized=True,
        tier=0,
    )
    assert c.off_limits is True  # Factory branch — must never be touched


def test_classify_off_limits_pinned_number() -> None:
    c = classify_candidate(
        {"number": 99, "headRefName": "codex/foo", "changedFiles": 3},
        DrainContext(off_limits_prs=frozenset({99})),
        merge_authorized=True,
        tier=0,
    )
    assert c.off_limits is True


def test_classify_empty_has_no_changes() -> None:
    c = classify_candidate(
        {"number": 2, "headRefName": "codex/x", "changedFiles": 0},
        DrainContext(),
        merge_authorized=False,
        tier=4,
    )
    assert c.has_changes is False  # -> CLOSE_SUPERSEDED downstream


def test_classify_authorized_sets_mergeable_bundle() -> None:
    c = classify_candidate(
        {"number": 3, "headRefName": "codex/x", "changedFiles": 5},
        DrainContext(),
        merge_authorized=True,
        tier=1,
    )
    assert c.required_checks_green and c.quorum_satisfied and c.mergeable and c.tier == 1


def _views() -> list[dict]:
    return [
        {"number": 10, "headRefName": "codex/green", "changedFiles": 4},  # -> authority probe
        {"number": 11, "headRefName": "codex/empty", "changedFiles": 0},  # -> CLOSE (no probe)
        {
            "number": 12,
            "headRefName": "structex/x",
            "changedFiles": 9,
        },  # -> off-limits LEAVE (no probe)
        {"number": 13, "headRefName": "codex/red", "changedFiles": 7},  # -> REPAIR
    ]


def test_build_candidates_only_probes_promising_prs() -> None:
    probed: list[int] = []
    viewed: list[int] = []

    def auth(n: int) -> tuple[bool, int]:
        probed.append(n)
        return (n == 10, 0)  # only #10 authorized

    def view(n: int) -> dict:
        viewed.append(n)
        return next(v for v in _views() if v["number"] == n)

    cands = build_candidates(
        DrainContext(),
        list_open_prs_fn=_views,
        view_pr_fn=view,
        merge_authorized_fn=auth,
        max_classify=60,
    )
    # off-limits (#12) and empty (#11) must NOT be authority-probed
    assert probed == [10, 13]
    # off-limits-by-prefix (#12) classifies on the cheap list signal alone — it must
    # NOT incur a per-PR detail fetch either (avoids +N gh calls at --list-limit 300).
    assert 12 not in viewed
    # empty (#11) still needs a detail fetch (the list query carries no changedFiles)
    # but is never authority-probed.
    assert 11 in viewed and 11 not in probed
    by_pr = {c.pr: c for c in cands}
    assert by_pr[10].mergeable is True
    assert by_pr[11].has_changes is False
    assert by_pr[12].off_limits is True
    assert by_pr[13].mergeable is False


def test_build_candidates_cheap_signals_skip_detail_fetch() -> None:
    # off-limits-by-prefix, owned, and explicitly-superseded all classify from the
    # list view alone — none of them may pay for a `gh pr view` (P2 #2 regression).
    viewed: list[int] = []
    probed: list[int] = []
    views = [
        {"number": 20, "headRefName": "codex/green", "changedFiles": 4},  # -> view + probe
        {"number": 21, "headRefName": "structex/x", "changedFiles": 9},  # off-limits prefix
        {"number": 22, "headRefName": "codex/owned", "changedFiles": 3},  # owned
        {"number": 23, "headRefName": "codex/dup", "changedFiles": 3},  # superseded
        {"number": 24, "headRefName": "codex/pinned", "changedFiles": 2},  # off-limits id
    ]

    def view(n: int) -> dict:
        viewed.append(n)
        return next(v for v in views if v["number"] == n)

    def auth(n: int) -> tuple[bool, int]:
        probed.append(n)
        return (n == 20, 0)

    ctx = DrainContext(
        off_limits_prs=frozenset({24}),
        owned_prs=frozenset({22}),
        superseded_prs=frozenset({23}),
    )
    cands = build_candidates(
        ctx,
        list_open_prs_fn=lambda: views,
        view_pr_fn=view,
        merge_authorized_fn=auth,
        max_classify=60,
    )
    # cheap-signal PRs are neither view-fetched nor authority-probed
    assert viewed == [20]
    assert probed == [20]
    by_pr = {c.pr: c for c in cands}
    assert by_pr[21].off_limits is True
    assert by_pr[22].owned_by_other_agent is True
    assert by_pr[23].superseded is True
    assert by_pr[24].off_limits is True


def test_build_candidates_respects_max_classify() -> None:
    many = [{"number": 100 + i, "headRefName": "codex/x", "changedFiles": 2} for i in range(50)]
    seen: list[int] = []
    build_candidates(
        DrainContext(),
        list_open_prs_fn=lambda: many,
        view_pr_fn=lambda n: {"number": n, "headRefName": "codex/x", "changedFiles": 2},
        merge_authorized_fn=lambda n: (seen.append(n) or (False, 4)),
        max_classify=5,
    )
    assert len(seen) == 5  # only first 5 classified/probed


def test_run_boss_drain_routes_and_executes_safely() -> None:
    executed: dict[int, DrainAction] = {}

    def auth(n: int) -> tuple[bool, int]:
        return (n == 10, 0)

    res = run_boss_drain(
        DrainContext(),
        DrainPassPolicy(max_repairs_per_pass=5),
        list_open_prs_fn=_views,
        view_pr_fn=lambda n: next(v for v in _views() if v["number"] == n),
        merge_authorized_fn=auth,
        execute_fn=lambda pr, a: executed.__setitem__(pr, a) or True,
        max_classify=60,
    )
    assert executed.get(10) is DrainAction.MERGE
    assert executed.get(11) is DrainAction.CLOSE_SUPERSEDED
    assert 12 not in executed  # off-limits LEFT, never executed
    assert executed.get(13) is DrainAction.REPAIR
    assert {c.pr for c in res.left} == {12}


def test_unauthorized_pr_never_merges() -> None:
    # Authority says NO for everything -> no MERGE, only REPAIR/CLOSE/LEAVE.
    res = run_boss_drain(
        DrainContext(),
        DrainPassPolicy(),
        list_open_prs_fn=lambda: [{"number": 5, "headRefName": "codex/x", "changedFiles": 3}],
        view_pr_fn=lambda n: {"number": 5, "headRefName": "codex/x", "changedFiles": 3},
        merge_authorized_fn=lambda n: (False, 0),
        execute_fn=lambda pr, a: True,
        max_classify=60,
    )
    actions = {p.action for p in res.planned}
    assert DrainAction.MERGE not in actions


# --- Shared required-check lineage (P3 #6) -----------------------------------


def test_required_check_names_are_single_sourced() -> None:
    # The 5 required-check names must not drift between the repair prompt
    # (boss_drain) and the proxy authority gate (boss_drain_pass).
    from aragora.swarm.boss_drain import REQUIRED_CHECK_NAMES
    from scripts.boss_drain_pass import _REQUIRED

    assert set(_REQUIRED) == set(REQUIRED_CHECK_NAMES)
    # the prompt prose is built from the same constant, so it can't drift either
    prompt = make_repair_prompt(1, "b")
    for name in REQUIRED_CHECK_NAMES:
        assert name in prompt


# --- _proxy_authorized any-SUCCESS semantics (P3 #4) -------------------------


def _rollup_all_green() -> list[dict]:
    from aragora.swarm.boss_drain import REQUIRED_CHECK_NAMES

    names = [*REQUIRED_CHECK_NAMES, "aragora-merge-quorum"]
    return [{"name": n, "conclusion": "SUCCESS"} for n in names]


def test_proxy_authorized_uses_any_success_for_duplicate_names() -> None:
    from scripts.boss_drain_pass import _proxy_authorized

    rollup = _rollup_all_green()
    # A stale re-run row for an already-green check, ordered AFTER the success.
    # Last-write-wins would wrongly flip authority to False; any-SUCCESS keeps it True.
    rollup.append({"name": "lint", "status": "IN_PROGRESS"})
    ok, _tier = _proxy_authorized({"mergeable": "MERGEABLE", "statusCheckRollup": rollup})
    assert ok is True


def test_proxy_authorized_requires_a_success_for_every_required_name() -> None:
    from scripts.boss_drain_pass import _proxy_authorized

    rollup = _rollup_all_green()
    # Replace lint's only row with a FAILURE -> no SUCCESS exists for lint.
    rollup = [c for c in rollup if c["name"] != "lint"]
    rollup.append({"name": "lint", "conclusion": "FAILURE"})
    ok, _tier = _proxy_authorized({"mergeable": "MERGEABLE", "statusCheckRollup": rollup})
    assert ok is False


def test_proxy_authorized_false_when_not_mergeable() -> None:
    from scripts.boss_drain_pass import _proxy_authorized

    ok, _tier = _proxy_authorized(
        {"mergeable": "CONFLICTING", "statusCheckRollup": _rollup_all_green()}
    )
    assert ok is False


# --- exact-head settlement provenance ---------------------------------------


_EXACT_HEAD = "0123456789abcdef0123456789abcdef01234567"


def test_settle_authorized_returns_exact_snapshot_head(monkeypatch) -> None:  # noqa: ANN001
    import json

    import scripts.boss_drain_pass as bdp

    report = {
        "status": "packet_authorized_dry_run",
        "blockers": [],
        "head_sha": _EXACT_HEAD,
    }
    monkeypatch.setattr(
        bdp.subprocess,
        "run",
        lambda *a, **k: _FakeProc(0, stdout=json.dumps(report)),
    )

    assert bdp._settle_authorized("synaptent/aragora", 9677) == _EXACT_HEAD


def test_settle_authorized_rejects_missing_or_malformed_head(monkeypatch) -> None:  # noqa: ANN001
    import json

    import scripts.boss_drain_pass as bdp

    for head in (None, "", "abc123", _EXACT_HEAD.upper()):
        report = {
            "status": "packet_authorized_dry_run",
            "blockers": [],
        }
        if head is not None:
            report["head_sha"] = head
        monkeypatch.setattr(
            bdp.subprocess,
            "run",
            lambda *a, report=report, **k: _FakeProc(0, stdout=json.dumps(report)),
        )
        assert bdp._settle_authorized("synaptent/aragora", 9677) is None


def test_settle_authorized_rejects_failed_settlement_command(monkeypatch) -> None:  # noqa: ANN001
    import json

    import scripts.boss_drain_pass as bdp

    report = {
        "status": "packet_authorized_dry_run",
        "blockers": [],
        "head_sha": _EXACT_HEAD,
    }
    monkeypatch.setattr(
        bdp.subprocess,
        "run",
        lambda *a, **k: _FakeProc(1, stdout=json.dumps(report)),
    )

    assert bdp._settle_authorized("synaptent/aragora", 9677) is None


def test_merge_uses_settlement_head_without_second_lookup(monkeypatch) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    commands: list[list[str]] = []
    monkeypatch.setattr(bdp, "_settle_authorized", lambda repo, pr: _EXACT_HEAD)
    monkeypatch.setattr(
        bdp,
        "view_pr",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected second head lookup")),
    )
    monkeypatch.setattr(
        bdp.subprocess,
        "run",
        lambda cmd, **kwargs: commands.append(cmd) or _FakeProc(0),
    )

    execute = bdp.make_execute_fn("synaptent/aragora", dry_run=False)
    assert execute(9677, DrainAction.MERGE) is True
    assert commands == [
        [
            "gh",
            "pr",
            "merge",
            "9677",
            "--repo",
            "synaptent/aragora",
            "--squash",
            "--match-head-commit",
            _EXACT_HEAD,
        ]
    ]


def test_merge_missing_snapshot_head_fails_before_merge_subprocess(monkeypatch) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    commands: list[list[str]] = []
    monkeypatch.setattr(bdp, "_settle_authorized", lambda repo, pr: None)
    monkeypatch.setattr(
        bdp.subprocess,
        "run",
        lambda cmd, **kwargs: commands.append(cmd) or _FakeProc(0),
    )

    execute = bdp.make_execute_fn("synaptent/aragora", dry_run=False)
    assert execute(9677, DrainAction.MERGE) is False
    assert commands == []


# --- dispatch_repair apply-path verification (P2 #1, P3 #3) ------------------


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_git_run(
    *,
    before: str = "AAA",
    head: str = "BBB",
    agent_rc: int = 0,
    push_rc: int = 0,
    after: str | None = None,
    add_rc: int = 0,
):
    """Build a fake subprocess.run modelling a git/agent repair sequence."""
    state = {"pushed": False}
    tip_after = head if after is None else after

    def run(cmd, **kwargs):  # noqa: ANN001, ANN003 - test stub
        if cmd[:3] == ["git", "worktree", "add"]:
            return _FakeProc(add_rc)
        if cmd[:3] == ["git", "worktree", "remove"]:
            return _FakeProc(0)
        if cmd[0] == "git" and "rev-parse" in cmd:
            ref = cmd[-1]
            if ref == "HEAD":
                return _FakeProc(0, stdout=head + "\n")
            return _FakeProc(0, stdout=(tip_after if state["pushed"] else before) + "\n")
        if cmd[0] == "git" and "push" in cmd:
            if push_rc == 0:
                state["pushed"] = True
            return _FakeProc(push_rc)
        if cmd[0] in ("codex", "claude"):
            return _FakeProc(agent_rc)
        return _FakeProc(0)

    return run


def _patch_view(monkeypatch) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    monkeypatch.setattr(bdp, "view_pr", lambda repo, pr: {"headRefName": "codex/red"})


def test_dispatch_repair_true_only_when_new_commit_is_pushed(monkeypatch) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    _patch_view(monkeypatch)
    monkeypatch.setattr(bdp.subprocess, "run", _fake_git_run(before="AAA", head="BBB"))
    assert bdp.dispatch_repair("r", 8460, dry_run=False, enable_repair=True, agent="codex") is True


def test_dispatch_repair_false_when_agent_committed_nothing(monkeypatch) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    _patch_view(monkeypatch)
    # HEAD == remote tip -> no new commit; must not report a successful repair.
    monkeypatch.setattr(bdp.subprocess, "run", _fake_git_run(before="AAA", head="AAA"))
    assert bdp.dispatch_repair("r", 8460, dry_run=False, enable_repair=True, agent="codex") is False


def test_dispatch_repair_false_when_push_fails(monkeypatch) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    _patch_view(monkeypatch)
    monkeypatch.setattr(bdp.subprocess, "run", _fake_git_run(before="AAA", head="BBB", push_rc=1))
    assert bdp.dispatch_repair("r", 8460, dry_run=False, enable_repair=True, agent="codex") is False


def test_dispatch_repair_false_when_remote_tip_did_not_move(monkeypatch) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    _patch_view(monkeypatch)
    # push "succeeds" but the remote tip is unchanged (no-op / lost race).
    monkeypatch.setattr(
        bdp.subprocess, "run", _fake_git_run(before="AAA", head="BBB", push_rc=0, after="AAA")
    )
    assert bdp.dispatch_repair("r", 8460, dry_run=False, enable_repair=True, agent="codex") is False


def test_dispatch_repair_false_when_agent_run_fails(monkeypatch) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    _patch_view(monkeypatch)
    monkeypatch.setattr(bdp.subprocess, "run", _fake_git_run(before="AAA", head="BBB", agent_rc=1))
    assert bdp.dispatch_repair("r", 8460, dry_run=False, enable_repair=True, agent="codex") is False


def test_dispatch_repair_dry_run_spawns_nothing(monkeypatch) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    _patch_view(monkeypatch)
    calls: list = []
    monkeypatch.setattr(bdp.subprocess, "run", lambda *a, **k: calls.append(a) or _FakeProc(0))
    assert bdp.dispatch_repair("r", 8460, dry_run=True, enable_repair=False, agent="codex") is True
    assert calls == []  # plan-only: no git/agent subprocess at all


def test_dispatch_repair_cleans_tempdir_when_worktree_add_fails(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    import scripts.boss_drain_pass as bdp

    _patch_view(monkeypatch)
    base = str(tmp_path / "drain-base")
    monkeypatch.setattr(bdp.tempfile, "mkdtemp", lambda **k: base)
    rmtree_calls: list[str] = []
    monkeypatch.setattr(bdp.shutil, "rmtree", lambda p, **k: rmtree_calls.append(p))
    monkeypatch.setattr(bdp.subprocess, "run", _fake_git_run(add_rc=1))
    ok = bdp.dispatch_repair("r", 8460, dry_run=False, enable_repair=True, agent="codex")
    assert ok is False
    # the mkdtemp base is backstop-cleaned even though `git worktree add` never registered it
    assert base in rmtree_calls
