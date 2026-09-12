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
import sys
from pathlib import Path
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


# --------------------------------------------------------------------------
# authority rule: a failed probe is never a reassuring default
# --------------------------------------------------------------------------


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
    monkeypatch.setattr(situation, "sh", lambda *a, **k: called.append(a) or (0, "{}"))

    situation.add_pr_beliefs(cap, 9924)

    assert not called, "must not shell out with an unusable slug"
    assert cap.degraded


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
            exit_code=1,
            out_tokens=0,
            err_tokens=500,
            out_bytes=0,
            wall_ms=1,
        )
    )
    assert r.total_tokens == 500
    assert measure.score(r)["verdict"] == "FAIL"


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
