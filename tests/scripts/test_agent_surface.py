"""Tests for ``scripts/agent_surface/`` -- the capsule and its measurement harness.

These cover the invariants whose silent failure would void the design rather
than merely produce a wrong number:

- the cursor must be stable for identical state (an over-sensitive cursor makes
  every tick report "changed" and the cheap delta path never fires);
- the cursor must exclude wall-clock time for the same reason;
- a failed probe must become an UNKNOWN or a DEGRADED note, never a silent
  default -- absence of evidence must not render as evidence of absence;
- budget scoring must fail closed.

Everything here is offline. No test in this file touches the network or GitHub.
"""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _load_module(relative: str) -> Any:
    here = Path(__file__).resolve()
    script_path = here.parents[2] / "scripts" / "agent_surface" / relative
    name = f"agent_surface_{relative.replace('.py', '')}_under_test"
    spec = importlib.util.spec_from_file_location(name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


situation = _load_module("situation.py")
measure = _load_module("measure.py")


def _capsule(**overrides: Any) -> Any:
    cap = situation.Capsule()
    cap.anchor = {
        "repo": "synaptent/aragora",
        "branch": "main",
        "head": "abc123def456",
        "main": "abc123def456",
        "generated_at": "2026-08-31T07:00:00-0500",
    }
    cap.beliefs = [
        situation.Belief("prs_open", 80, "gh pr list", "live", "observed"),
    ]
    for key, value in overrides.items():
        setattr(cap, key, value)
    return cap


# --------------------------------------------------------------------------
# cursor: the property the whole delta path rests on
# --------------------------------------------------------------------------


def test_cursor_is_stable_for_identical_state() -> None:
    assert _capsule().cursor() == _capsule().cursor()


def test_cursor_ignores_generated_at() -> None:
    """Wall-clock must not enter the digest.

    If it did, every tick would report a change and the 31-token quiet path
    would never fire -- the design would be dead while still appearing to work.
    """
    a = _capsule()
    b = _capsule()
    b.anchor = dict(b.anchor, generated_at="2099-01-01T00:00:00-0500")
    assert a.cursor() == b.cursor()


def test_cursor_changes_when_a_belief_changes() -> None:
    a = _capsule()
    b = _capsule(beliefs=[situation.Belief("prs_open", 81, "gh pr list", "live", "observed")])
    assert a.cursor() != b.cursor()


def test_cursor_changes_when_the_anchor_moves() -> None:
    """A capsule anchored to a different head is a different capsule.

    Settlement replay across a moved head is a documented failure mode in this
    repo; the cursor must not paper over it.
    """
    a = _capsule()
    b = _capsule()
    b.anchor = dict(b.anchor, head="999fff888eee")
    assert a.cursor() != b.cursor()


def test_cursor_changes_when_obligations_change() -> None:
    a = _capsule()
    b = _capsule(obligations=[{"kind": "advisory_next_action", "detail": "x"}])
    assert a.cursor() != b.cursor()


@pytest.mark.parametrize("field", ["source", "freshness", "confidence", "note"])
def test_cursor_changes_when_belief_provenance_changes(field: str) -> None:
    a = _capsule()
    b = _capsule()
    setattr(b.beliefs[0], field, "new uncertainty")
    assert a.cursor() != b.cursor()


@pytest.mark.parametrize("field", ["repo", "branch"])
def test_cursor_changes_when_checkout_identity_changes(field: str) -> None:
    a = _capsule()
    b = _capsule()
    b.anchor[field] = "different"
    assert a.cursor() != b.cursor()


@pytest.mark.parametrize("field", ["objective", "unknowns", "frontier", "degraded"])
def test_cursor_tracks_all_meaningful_capsule_sections(field: str) -> None:
    a = _capsule()
    b = _capsule()
    values = {
        "objective": {"inferred": "different objective"},
        "unknowns": [situation.Unknown("Ownership?", "Unknown owner", "probe", 1)],
        "frontier": [situation.Action("Inspect", "git status", "cheap", "none", True)],
        "degraded": ["probe unavailable"],
    }
    setattr(b, field, values[field])
    assert a.cursor() != b.cursor()


def test_since_emits_changed_uncertainty_with_full_provenance(
    monkeypatch: Any, capsys: Any
) -> None:
    previous = _capsule()
    current = _capsule()
    current.beliefs[0].freshness = "stale:60"
    current.unknowns = [situation.Unknown("Ownership?", "Unknown owner", "probe", 1)]
    current.degraded = ["probe unavailable"]
    monkeypatch.setattr(situation, "build", lambda *a, **k: current)
    monkeypatch.setattr(sys, "argv", ["situation", "--since", previous.cursor()])
    assert situation.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is True
    assert payload["belief_details"][0]["freshness"] == "stale:60"
    assert payload["unknowns"][0]["question"] == "Ownership?"
    assert payload["degraded"] == ["probe unavailable"]


def test_since_unchanged_retains_compact_response(monkeypatch: Any, capsys: Any) -> None:
    current = _capsule()
    monkeypatch.setattr(situation, "build", lambda *a, **k: current)
    monkeypatch.setattr(sys, "argv", ["situation", "--since", current.cursor()])
    assert situation.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "changed": False,
        "cursor": current.cursor(),
        "anchor": current.anchor["head"],
        "covers": situation.CURSOR_SCOPE,
    }


# --------------------------------------------------------------------------
# authority rule: a failed probe is never a reassuring default
# --------------------------------------------------------------------------


def test_failed_working_tree_probe_preserves_uncertainty_and_inspection(monkeypatch: Any) -> None:
    cap = _capsule()
    monkeypatch.setattr(
        situation,
        "sh",
        lambda cmd, **kw: (1, "unreadable index") if cmd[1] == "status" else (0, "0"),
    )
    situation.add_local_beliefs(cap)
    situation.add_frontier(cap)
    assert not any(b.key == "working_tree" for b in cap.beliefs)
    assert any("working tree" in u.question.lower() for u in cap.unknowns)
    assert any("git status" in d for d in cap.degraded)
    assert any(a.command == "git status --porcelain" for a in cap.frontier)


@pytest.mark.parametrize("which", ["HEAD..origin/main", "origin/main..HEAD"])
@pytest.mark.parametrize("failure", [(1, "0"), (0, "not a count"), (124, "timeout")])
def test_failed_branch_position_probe_is_explicit(
    monkeypatch: Any, which: str, failure: tuple[int, str]
) -> None:
    cap = _capsule()

    def probe(cmd: list[str], **kw: Any) -> tuple[int, str]:
        if cmd[1] == "status":
            return 0, ""
        return failure if cmd[-1] == which else (0, "0")

    monkeypatch.setattr(situation, "sh", probe)
    situation.add_local_beliefs(cap)
    assert not any(b.key == "branch_position" for b in cap.beliefs)
    assert any("ahead" in u.question for u in cap.unknowns)
    assert any("git rev-list" in d for d in cap.degraded)


_SLUG_PROBE_ERROR = "error connecting to api.github.com/repos: dial tcp: no such host"


def _anchor_probe(slug_result: tuple[int, str]) -> Any:
    def probe(cmd: list[str], **kwargs: Any) -> tuple[int, str]:
        if cmd[:3] == ["gh", "repo", "view"]:
            return slug_result
        if "--abbrev-ref" in cmd:
            return 0, "main"
        return 0, "abc123def456"

    return probe


def test_failed_slug_probe_is_not_laundered_into_the_anchor(monkeypatch: Any) -> None:
    """A gh diagnostic must never be reported as the repo's identity.

    ANCHOR is the field every other field claims to be true of, so a probe
    failure rendered there is the worst available place to lose provenance.
    """
    monkeypatch.setattr(situation, "sh", _anchor_probe((1, _SLUG_PROBE_ERROR)))
    cap = situation.Capsule()

    assert situation.build_anchor(cap) is True

    assert cap.anchor["repo"] == "unknown"
    assert any("slug unresolved" in note for note in cap.degraded)


def test_unresolvable_slug_withholds_settlement_and_keeps_frontier_runnable(
    monkeypatch: Any,
) -> None:
    """Both slug consumers must take their documented withholding path."""
    monkeypatch.setattr(situation, "sh", _anchor_probe((1, _SLUG_PROBE_ERROR)))
    cap = situation.Capsule()
    situation.build_anchor(cap)

    shelled: list[list[str]] = []

    def record(cmd: list[str], **kwargs: Any) -> tuple[int, str]:
        shelled.append(cmd)
        return 0, "{}"

    monkeypatch.setattr(situation, "sh", record)
    situation.add_pr_beliefs(cap, 9924)
    situation.add_frontier(cap)

    assert not shelled, "must not invoke settle_status.py with an unusable slug"
    assert not any(b.key.startswith("pr9924_") for b in cap.beliefs)
    assert not any(_SLUG_PROBE_ERROR in action.command for action in cap.frontier)
    settlement = next(a for a in cap.frontier if "settlement" in a.label.lower())
    assert settlement.prerequisite, "an unrunnable command must say what is missing"


def test_well_formed_slug_is_retained(monkeypatch: Any) -> None:
    monkeypatch.setattr(situation, "sh", _anchor_probe((0, "synaptent/aragora")))
    cap = situation.Capsule()

    assert situation.build_anchor(cap) is True

    assert cap.anchor["repo"] == "synaptent/aragora"
    assert cap.degraded == []


@pytest.mark.parametrize(
    "status,expected", [("", "clean"), (" M file.py", "1 uncommitted path(s)")]
)
def test_successful_local_probes_retain_observed_values(
    monkeypatch: Any, status: str, expected: str
) -> None:
    cap = _capsule()
    monkeypatch.setattr(
        situation, "sh", lambda cmd, **kw: (0, status if cmd[1] == "status" else "0")
    )
    situation.add_local_beliefs(cap)
    assert {b.key: b.value for b in cap.beliefs}["working_tree"] == expected
    assert not cap.degraded and not cap.unknowns


_MALFORMED_FLEET_PAYLOADS = [
    None,
    [1, 2, 3],
    {"summary": None},
    {"summary": {"by_state": ["running"]}},
    {"summary": {"by_state": {"running": "many"}}},
    {"summary": {"by_state": {}}, "records": "not-a-list"},
]


def test_fleet_shape_drift_degrades_instead_of_killing_the_capsule(monkeypatch: Any) -> None:
    """A composed tool that changes shape must cost its own beliefs only."""
    for payload in _MALFORMED_FLEET_PAYLOADS:
        cap = _capsule(beliefs=[])
        monkeypatch.setattr(situation, "sh", lambda *a, _p=payload, **k: (0, json.dumps(_p)))

        situation.add_fleet_beliefs(cap)

        assert cap.degraded, f"expected a degraded note for {payload!r}"
        assert not any(b.key == "fleet_safe_to_continue" for b in cap.beliefs)


def test_an_unreadable_loop_shape_withholds_the_green_verdict(monkeypatch: Any) -> None:
    """Coercing bad counts to zero would publish an uncaveated green as a live belief."""
    payload = {
        "summary": {"fleet_safe_to_continue": True, "by_state": {"running": "many"}},
    }
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, json.dumps(payload)))
    cap = _capsule(beliefs=[])

    situation.add_fleet_beliefs(cap)

    assert not any(b.key == "fleet_safe_to_continue" for b in cap.beliefs)
    assert not any(b.key == "fleet_loops" for b in cap.beliefs)
    assert cap.unknowns, "an unreadable fleet must leave a stated unknown"


def _cursor_with_degraded(note: str) -> str:
    cap = _capsule(beliefs=[])
    cap.degraded = [note]
    return cap.cursor()


def test_volatile_probe_detail_does_not_churn_the_cursor() -> None:
    """A rate-limit message with a timestamp must not disable the delta path."""
    assert _cursor_with_degraded(
        "gh pr list failed: API rate limit exceeded at 15:04:01"
    ) == _cursor_with_degraded("gh pr list failed: API rate limit exceeded at 15:09:44")


def test_a_different_failure_class_still_changes_the_cursor() -> None:
    """Same probe, different remediation: the caller must not be told nothing changed."""
    rate_limited = _cursor_with_degraded("gh pr list failed: API rate limit exceeded")
    unauthenticated = _cursor_with_degraded("gh pr list failed: authentication failed")
    other_probe = _cursor_with_degraded("loop_control_status unavailable: boom")

    assert len({rate_limited, unauthenticated, other_probe}) == 3


def test_settlement_shape_drift_degrades_instead_of_killing_the_capsule(monkeypatch: Any) -> None:
    for payload in (None, [], "a string"):
        cap = _capsule(beliefs=[])
        monkeypatch.setattr(situation, "sh", lambda *a, _p=payload, **k: (0, json.dumps(_p)))

        situation.add_pr_beliefs(cap, 9948)

        assert any("expected an object" in d for d in cap.degraded), payload
        assert not any(b.key.startswith("pr9948_") for b in cap.beliefs)


def test_missing_settlement_fields_are_withheld_not_valued_none(monkeypatch: Any) -> None:
    """A field the tool did not report is unknown, not a value of None."""
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, json.dumps({"head_sha": "a" * 40})))
    cap = _capsule(beliefs=[])

    situation.add_pr_beliefs(cap, 9948)

    assert not any(b.value is None for b in cap.beliefs)
    for field in ("tier", "signal_count", "quorum_conclusion"):
        assert any(field in note for note in cap.degraded), field


def test_a_missing_working_directory_is_not_blamed_on_the_tool() -> None:
    code, out = situation.sh(["git", "status"], cwd=Path("/nonexistent-path-for-this-test"))

    assert code == 127
    assert "working directory does not exist" in out


def test_a_settlement_without_a_head_sha_says_so(monkeypatch: Any) -> None:
    payload = {"tier": 2, "quorum_conclusion": "FAILURE", "head_sha": None}
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, json.dumps(payload)))
    cap = _capsule(beliefs=[])

    situation.add_pr_beliefs(cap, 9948)

    quorum = next(b for b in cap.beliefs if b.key == "pr9948_quorum")
    assert "cannot be tied to a revision" in quorum.note


def _capsule_for_pr_set(monkeypatch: Any, prs: list[dict[str, Any]]) -> Any:
    cap = _capsule(beliefs=[])
    monkeypatch.setattr(situation.shutil, "which", lambda _: "/fixture/gh")
    monkeypatch.setattr(
        situation,
        "sh",
        lambda cmd, **k: (0, json.dumps(prs if cmd[1] == "pr" else [{"conclusion": "success"}])),
    )
    situation.add_github_beliefs(cap)
    return cap


def test_a_changed_pr_set_at_equal_counts_shares_a_cursor(monkeypatch: Any) -> None:
    """Characterises the cursor's deliberate blind spot so it stays deliberate.

    Digesting PR identities was measured and rejected: in a continuously
    turning queue it fires on most ticks and blows the delta budget. The
    contract is stated instead, and ``--pr N`` covers a specific PR.
    """
    before = _capsule_for_pr_set(
        monkeypatch, [{"number": 9948, "isDraft": False}, {"number": 9949, "isDraft": True}]
    )
    after = _capsule_for_pr_set(
        monkeypatch, [{"number": 9950, "isDraft": False}, {"number": 9949, "isDraft": True}]
    )

    assert {b.key: b.value for b in before.beliefs} == {b.key: b.value for b in after.beliefs}
    assert before.cursor() == after.cursor()
    assert "not PR identities" in situation.CURSOR_SCOPE


def test_the_quiet_answer_states_what_it_covers(monkeypatch: Any, capsys: Any) -> None:
    """ "changed: false" must not be readable as "nothing happened anywhere"."""
    current = _capsule()
    monkeypatch.setattr(situation, "build", lambda *a, **k: current)
    monkeypatch.setattr(sys, "argv", ["situation", "--since", current.cursor()])

    assert situation.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is False
    assert payload["covers"] == situation.CURSOR_SCOPE


def test_an_unresolvable_head_is_not_laundered_into_the_anchor(monkeypatch: Any) -> None:
    """ANCHOR is what every other field claims to be true of, so a failed
    rev-parse must not supply its own error text as the revision."""

    def probe(cmd: list[str], **kwargs: Any) -> tuple[int, str]:
        if "--abbrev-ref" in cmd:
            return 0, "main"
        if cmd[:2] == ["git", "rev-parse"]:
            return 128, "fatal: ambiguous argument 'HEAD': unknown revision"
        return 0, "synaptent/aragora"

    monkeypatch.setattr(situation, "sh", probe)
    cap = situation.Capsule()

    assert situation.build_anchor(cap) is True

    assert cap.anchor["head"] == "unresolved"
    assert any("HEAD unresolved" in d for d in cap.degraded)


def test_probe_success_with_empty_stdout_never_returns_stderr() -> None:
    """`git status --porcelain` answers "clean" with silence, so an empty
    stdout on exit 0 is an answer and must not fall through to stderr."""
    code, output = situation.sh(
        [sys.executable, "-c", "import sys; print('warning: advisory', file=sys.stderr)"]
    )
    assert (code, output) == (0, "")


def test_a_clean_tree_that_warns_is_not_reported_as_dirty(monkeypatch: Any) -> None:
    class Result:
        returncode = 0
        stdout = ""
        stderr = "warning: safe.directory advice: detected dubious ownership\n"

    monkeypatch.setattr(situation.subprocess, "run", lambda *a, **kw: Result())
    cap = _capsule(beliefs=[])
    situation.add_local_beliefs(cap)
    situation.add_frontier(cap)

    working_tree = next(b for b in cap.beliefs if b.key == "working_tree")
    assert working_tree.value == "clean"
    assert cap.frontier, "expected add_frontier to produce actions to assert against"
    assert not any("uncommitted" in a.label for a in cap.frontier)


def test_failure_like_run_conclusions_are_counted_and_named(monkeypatch: Any) -> None:
    cap = _capsule(beliefs=[])
    runs = [{"conclusion": c} for c in ["timed_out", "cancelled", "success", "skipped"]]
    monkeypatch.setattr(situation.shutil, "which", lambda _: "/fixture/gh")
    monkeypatch.setattr(
        situation, "sh", lambda cmd, **k: (0, json.dumps([] if cmd[1] == "pr" else runs))
    )
    situation.add_github_beliefs(cap)

    failures = next(b for b in cap.beliefs if b.key == "main_recent_failures")
    assert failures.value == 2
    assert "cancelled" in failures.note and "timed_out" in failures.note
    assert "skipped is correct self-gating" in failures.note


def test_a_missing_settlement_field_is_withheld_not_assumed(monkeypatch: Any) -> None:
    """settle_status.py output without the key must not become "absent"."""
    payload = {"head_sha": "a" * 40, "tier": 2, "quorum_conclusion": "FAILURE"}
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, json.dumps(payload)))
    cap = _capsule(beliefs=[])
    situation.add_pr_beliefs(cap, 9948)

    assert not any(b.key == "pr9948_human_settlement" for b in cap.beliefs)
    assert any("human_settlement_present" in d for d in cap.degraded)


def test_a_missing_fleet_verdict_is_withheld_not_valued_none(monkeypatch: Any) -> None:
    payload = {"summary": {"by_state": {"running": 1}, "any_blocked": False}}
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, json.dumps(payload)))
    cap = _capsule(beliefs=[])
    situation.add_fleet_beliefs(cap)

    assert not any(b.key == "fleet_safe_to_continue" for b in cap.beliefs)
    assert any("fleet_safe_to_continue" in d for d in cap.degraded)


def test_composed_tools_run_under_the_current_interpreter(monkeypatch: Any) -> None:
    """loop_control_status.py imports aragora packages that only the
    interpreter running this capsule is guaranteed to have."""
    seen: list[list[str]] = []

    def record(cmd: list[str], **kwargs: Any) -> tuple[int, str]:
        seen.append(cmd)
        return 1, "unavailable"

    monkeypatch.setattr(situation, "sh", record)
    cap = _capsule(beliefs=[])
    situation.add_fleet_beliefs(cap)
    situation.add_pr_beliefs(cap, 9948)

    assert seen, "expected the composed tools to be invoked"
    assert all(cmd[0] == sys.executable for cmd in seen)


def test_settlement_frontier_is_runnable_only_when_the_pr_is_known() -> None:
    known = _capsule()
    situation.add_frontier(known, pr=9948)
    concrete = next(a for a in known.frontier if "settlement" in a.label.lower())
    assert "--pr 9948" in concrete.command
    assert not concrete.prerequisite

    unknown = _capsule()
    situation.add_frontier(unknown)
    placeholder = next(a for a in unknown.frontier if "settlement" in a.label.lower())
    assert "--pr <N>" in placeholder.command
    assert placeholder.prerequisite


def test_shell_probe_uses_explicit_cwd(tmp_path: Path) -> None:
    code, output = situation.sh(
        [sys.executable, "-c", "from pathlib import Path; print(Path.cwd())"], cwd=tmp_path
    )
    assert code == 0 and Path(output) == tmp_path.resolve()


@pytest.mark.parametrize("outside_repo", [False, True])
def test_cli_repo_root_applies_to_every_probe(
    monkeypatch: Any, tmp_path: Path, capsys: Any, outside_repo: bool
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    caller = tmp_path / "caller"
    caller.mkdir()
    monkeypatch.chdir(caller if outside_repo else target)
    calls: list[tuple[list[str], Any]] = []

    def subprocess_probe(cmd: list[str], **kw: Any) -> Any:
        calls.append((cmd, kw.get("cwd")))
        if cmd[0] == "git":
            if "--abbrev-ref" in cmd:
                output = "target-branch"
            elif "rev-parse" in cmd:
                output = "abc123def456"
            elif "status" in cmd:
                output = " M target-only.py"
            elif "rev-list" in cmd:
                output = "0"
            else:
                output = "target commit"
        elif cmd[:3] == ["gh", "repo", "view"]:
            output = "synaptent/aragora"
        elif cmd[0] == "gh":
            output = "[]"
        elif "scripts/loop_control_status.py" in cmd:
            output = '{"summary": {"by_state": {"running": 1}}}'
        else:
            assert "scripts/settle_status.py" in cmd
            output = '{"tier": 2, "head_sha": "abc123def456", "signal_count": 0}'
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(situation.subprocess, "run", subprocess_probe)
    monkeypatch.setattr(situation.shutil, "which", lambda _: "/fixture/gh")
    monkeypatch.setattr(
        sys, "argv", ["situation", "--repo-root", str(target), "--pr", "9924", "--json"]
    )
    assert situation.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["anchor"]["branch"] == "target-branch"
    assert all(cwd == target.resolve() for _, cwd in calls)
    assert any("scripts/loop_control_status.py" in cmd for cmd, _ in calls)
    assert any("scripts/settle_status.py" in cmd for cmd, _ in calls)
    assert any(cmd[:3] == ["gh", "run", "list"] for cmd, _ in calls)
    assert any(b["value"] == "1 uncommitted path(s)" for b in payload["beliefs"])
    assert Path.cwd() == (caller if outside_repo else target)


def test_settlement_journey_passes_required_options_without_masking_errors() -> None:
    spec = json.loads((Path(situation.__file__).parent / "journeys.json").read_text())
    command = spec["journeys"]["high_risk_settle"]["calls"][0]["cmd"]
    assert shlex.split(command) == [
        "python3",
        "scripts/settle_status.py",
        "--repo",
        "synaptent/aragora",
        "--pr",
        "9924",
    ]


def test_failed_fleet_probe_becomes_an_unknown_not_a_green(monkeypatch: Any) -> None:
    cap = _capsule()
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (1, "boom"))

    situation.add_fleet_beliefs(cap)

    assert not any(b.key == "fleet_safe_to_continue" for b in cap.beliefs), (
        "a failed probe must not yield a fleet verdict of any kind"
    )
    assert any("safe to continue" in u.question.lower() for u in cap.unknowns)
    assert cap.degraded


def test_unparseable_fleet_json_is_degraded_not_silently_dropped(monkeypatch: Any) -> None:
    cap = _capsule()
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, "not json at all"))

    situation.add_fleet_beliefs(cap)

    assert cap.degraded, "unparseable output must be reported, not swallowed"
    assert not any(b.key == "fleet_safe_to_continue" for b in cap.beliefs)


def test_green_fleet_verdict_carries_a_caveat_when_loops_are_unknown(monkeypatch: Any) -> None:
    """The exact case observed live: safe_to_continue=true over 3/7 unknown loops."""
    payload = (
        '{"summary": {"fleet_safe_to_continue": true, '
        '"by_state": {"running": 2, "halted": 2, "unknown": 3}}, "records": []}'
    )
    cap = _capsule()
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, payload))

    situation.add_fleet_beliefs(cap)

    verdict = next(b for b in cap.beliefs if b.key == "fleet_safe_to_continue")
    assert verdict.value is True
    assert "unknown" in verdict.note, "a partial green must not be restated as a plain green"
    assert any("unknown" in u.question for u in cap.unknowns)


def test_complete_fleet_verdict_carries_no_caveat(monkeypatch: Any) -> None:
    payload = (
        '{"summary": {"fleet_safe_to_continue": true, "by_state": {"running": 7}}, "records": []}'
    )
    cap = _capsule()
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, payload))

    situation.add_fleet_beliefs(cap)

    verdict = next(b for b in cap.beliefs if b.key == "fleet_safe_to_continue")
    assert verdict.note == "", "a fully-observed verdict should not be hedged"


def test_pr_settlement_is_bound_to_its_head(monkeypatch: Any) -> None:
    payload = (
        '{"pr_number": 9924, "head_sha": "6cfae2030ea2", "tier": 1, '
        '"signal_count": 0, "quorum_conclusion": "FAILURE", '
        '"human_settlement_present": false, "next_action": "collect 2 more"}'
    )
    cap = _capsule()
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, payload))

    situation.add_pr_beliefs(cap, 9924)

    quorum = next(b for b in cap.beliefs if b.key == "pr9924_quorum")
    assert "6cfae2030ea2" in quorum.note, "quorum must name the head it is true of"


def test_pr_next_action_is_attributed_not_adopted(monkeypatch: Any) -> None:
    """Four instruments compute next_action and nothing arbitrates them.

    The capsule must not launder one into "the" answer.
    """
    payload = (
        '{"pr_number": 9924, "head_sha": "abc", "tier": 1, "signal_count": 0, '
        '"quorum_conclusion": "FAILURE", "human_settlement_present": false, '
        '"next_action": "collect 2 more"}'
    )
    cap = _capsule()
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, payload))

    situation.add_pr_beliefs(cap, 9924)

    advisory = next(o for o in cap.obligations if o["kind"] == "advisory_next_action")
    assert "settle_status.py says" in advisory["detail"]
    assert not any(b.key == "pr9924_next_action" for b in cap.beliefs)


def test_missing_repo_slug_withholds_settlement(monkeypatch: Any) -> None:
    cap = _capsule()
    cap.anchor = dict(cap.anchor, repo="unknown")
    called: list[Any] = []

    def record_call(*args: Any, **kwargs: Any) -> tuple[int, str]:
        called.append(args)
        return 0, "{}"

    monkeypatch.setattr(situation, "sh", record_call)

    situation.add_pr_beliefs(cap, 9924)

    assert not called, "must not shell out with an unusable slug"
    assert cap.degraded


@pytest.mark.parametrize("probe", ["pr", "run"])
@pytest.mark.parametrize(
    "body",
    ["not json", "null", "{}", "[null]", "[{}]", '[{"isDraft": 1, "conclusion": []}]'],
)
def test_invalid_github_probe_cannot_assert_observed_zero(
    monkeypatch: Any, probe: str, body: str
) -> None:
    cap = _capsule(beliefs=[])

    def response(cmd: list[str], **kwargs: Any) -> tuple[int, str]:
        return 0, body if cmd[1] == probe else "[]"

    monkeypatch.setattr(situation.shutil, "which", lambda _: "/fixture/gh")
    monkeypatch.setattr(situation, "sh", response)
    situation.add_github_beliefs(cap)
    keys = {b.key for b in cap.beliefs}
    if probe == "pr":
        assert keys.isdisjoint({"prs_open", "prs_ready", "prs_draft"})
        assert "main_recent_failures" in keys
    else:
        assert "main_recent_failures" not in keys
        assert "prs_open" in keys
    assert cap.degraded
    assert cap.unknowns


def test_valid_empty_github_probes_are_observed_zero(monkeypatch: Any) -> None:
    cap = _capsule(beliefs=[])
    monkeypatch.setattr(situation.shutil, "which", lambda _: "/fixture/gh")
    monkeypatch.setattr(situation, "sh", lambda *a, **k: (0, "[]"))
    situation.add_github_beliefs(cap)
    assert {b.key: b.value for b in cap.beliefs} == {
        "prs_open": 0,
        "prs_ready": 0,
        "prs_draft": 0,
        "main_recent_failures": 0,
    }
    assert not cap.degraded


def test_valid_nonempty_github_probes_keep_counts_and_cap_warning(monkeypatch: Any) -> None:
    cap = _capsule(beliefs=[])
    prs = [{"isDraft": i < 40} for i in range(100)]
    runs = [{"conclusion": value} for value in ["failure", "success", "skipped", None]]
    monkeypatch.setattr(situation.shutil, "which", lambda _: "/fixture/gh")
    monkeypatch.setattr(
        situation, "sh", lambda cmd, **k: (0, json.dumps(prs if cmd[1] == "pr" else runs))
    )
    situation.add_github_beliefs(cap)
    values = {b.key: b.value for b in cap.beliefs}
    assert values == {"prs_open": 100, "prs_ready": 60, "prs_draft": 40, "main_recent_failures": 1}
    assert any("capped" in u.question for u in cap.unknowns)
    assert not cap.degraded


# --------------------------------------------------------------------------
# budget scoring: must fail closed
# --------------------------------------------------------------------------


def _result(budget: str, calls: int, tokens: int) -> Any:
    r = measure.JourneyResult(journey="t", question="q", budget=budget)
    for i in range(calls):
        r.calls.append(
            measure.CallRecord(
                label=f"c{i}",
                cmd="true",
                exit_code=0,
                out_tokens=tokens if i == 0 else 0,
                err_tokens=0,
                out_bytes=0,
                wall_ms=1,
            )
        )
    return r


def test_budget_passes_within_limits() -> None:
    assert measure.score(_result("cold_orientation", 1, 552))["verdict"] == "PASS"


def test_budget_fails_on_tokens_alone() -> None:
    s = measure.score(_result("cold_orientation", 1, 24_272))
    assert s["verdict"] == "FAIL"
    assert s["overshoot_x"] == pytest.approx(6.1, abs=0.05)


def test_budget_fails_on_calls_alone() -> None:
    """Six cheap calls still fail a three-call budget: round trips are the cost."""
    s = measure.score(_result("full_situation", 6, 100))
    assert s["verdict"] == "FAIL"
    assert s["over_calls_by"] == 3


def test_budget_at_exact_limit_passes() -> None:
    assert measure.score(_result("quiet_recheck", 1, 200))["verdict"] == "PASS"


def test_one_token_over_fails() -> None:
    assert measure.score(_result("quiet_recheck", 1, 201))["verdict"] == "FAIL"


def test_unknown_budget_is_unscored_not_passing() -> None:
    """An unrecognised budget must never read as success."""
    assert measure.score(_result("no_such_budget", 9, 999_999))["verdict"] == "UNSCORED"


def test_stderr_counts_against_the_budget() -> None:
    """Errors land in the agent's context exactly like stdout does."""
    r = measure.JourneyResult(journey="t", question="q", budget="quiet_recheck")
    r.calls.append(
        measure.CallRecord(
            label="c",
            cmd="true",
            exit_code=0,
            out_tokens=0,
            err_tokens=500,
            out_bytes=0,
            wall_ms=1,
        )
    )
    assert r.total_tokens == 500
    assert measure.score(r)["verdict"] == "FAIL"


def _failing_result(budget: str) -> Any:
    r = measure.JourneyResult(journey="t", question="q", budget=budget)
    r.calls.append(
        measure.CallRecord(
            label="the capsule itself",
            cmd="situation.py",
            exit_code=7,
            out_tokens=0,
            err_tokens=0,
            out_bytes=0,
            wall_ms=1,
        )
    )
    return r


def test_a_failed_call_can_never_certify_a_budget() -> None:
    """Zero tokens from a command that did not run is not an efficient answer."""
    s = measure.score(_failing_result("cold_orientation"))
    assert s["verdict"] == "INVALID"
    assert s["failed_calls"] == ["the capsule itself"]


def test_failed_calls_are_named_even_when_the_budget_is_unscored() -> None:
    s = measure.score(_failing_result("no_such_budget"))
    assert s["verdict"] == "UNSCORED"
    assert s["failed_calls"] == ["the capsule itself"]


def test_a_mixed_exact_run_never_reports_itself_as_purely_exact(monkeypatch: Any) -> None:
    """A per-call API failure degrades that call to the proxy, so the record
    must not keep claiming the exact tokenizer produced every count."""

    class FakeClient:
        class messages:
            @staticmethod
            def count_tokens(**kwargs: Any) -> Any:
                raise RuntimeError("upstream unavailable")

    fake_sdk = SimpleNamespace(Anthropic=lambda *a, **k: FakeClient())
    monkeypatch.setitem(sys.modules, "anthropic", fake_sdk)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused-by-this-fake")

    counter = measure.TokenCounter(exact=True)
    assert counter.name == "anthropic/count_tokens (exact)"

    counter.count("some output an agent would have to read")

    assert "exact" in counter.name
    assert "proxy on 1 call(s)" in counter.name


def test_cli_reports_an_unmeasurable_journey_distinctly(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    spec = {
        "journeys": {
            "broken": {
                "question": "q",
                "budget": "cold_orientation",
                "calls": [{"label": "broken probe", "cmd": "exit 7"}],
            }
        }
    }
    path = tmp_path / "journeys.json"
    path.write_text(json.dumps(spec))
    monkeypatch.setattr(sys, "argv", ["measure", "broken", "--file", str(path)])

    assert measure.main() == 4

    out = capsys.readouterr().out
    assert "INVALID" in out
    assert "not measured" in out


def test_a_misspelled_budget_stops_the_run_instead_of_going_unscored(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    """Falling back to "none" would silently retire the budget it meant to name."""
    spec = {
        "journeys": {
            "typo": {
                "question": "q",
                "budget": "cold_orientaton",
                "calls": [{"label": "cheap", "cmd": "echo hi"}],
            }
        }
    }
    path = tmp_path / "journeys.json"
    path.write_text(json.dumps(spec))
    monkeypatch.setattr(sys, "argv", ["measure", "typo", "--file", str(path)])

    assert measure.main() == 1

    err = capsys.readouterr().err
    assert "unknown budget" in err and "cold_orientaton" in err


# --------------------------------------------------------------------------
# token counting
# --------------------------------------------------------------------------


def test_token_counter_is_deterministic_and_names_itself() -> None:
    c = measure.TokenCounter()
    assert c.count("hello world") == c.count("hello world")
    assert c.count("hello world") > 0
    assert c.name != "unavailable"


def test_empty_text_costs_nothing() -> None:
    assert measure.TokenCounter().count("") == 0
