"""Tests for ``scripts/auto_evidence_cycle.py`` (bounded auto-evidence cycle).

All boundaries (PR listing, merge-packet probe, collect-evidence runner,
reconciler runner, clock) are injected; no test touches the network or spawns
a subprocess.
"""

from __future__ import annotations

import importlib.util
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


cycle = _load_module("auto_evidence_cycle.py")


def _quorum_check(conclusion: str = "FAILURE") -> dict[str, Any]:
    return {
        "workflowName": "aragora-merge-quorum",
        "name": "merge-quorum",
        "conclusion": conclusion,
        "completedAt": "2026-06-10T10:00:00Z",
    }


def _pr(
    number: int,
    *,
    draft: bool = False,
    checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "number": number,
        "isDraft": draft,
        "statusCheckRollup": checks if checks is not None else [_quorum_check()],
    }


def _entry(
    pr: int,
    *,
    status: str = "needs_model_review_quorum",
    tier: int | None = 1,
    families: list[str] | None = None,
    human: bool = False,
    dissent: bool = False,
) -> dict[str, Any]:
    return {
        "pr_number": pr,
        "status": status,
        "tier": tier,
        "counted_model_families": families or [],
        "requires_human_risk_settlement": human,
        "unresolved_dissent": dissent,
    }


class CollectRecorder:
    """Injected collect-evidence runner that records calls."""

    def __init__(self, results: dict[int, dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[int, bool]] = []
        self.results = results or {}

    def __call__(self, pr: int, apply: bool) -> dict[str, Any]:
        self.calls.append((pr, apply))
        return self.results.get(
            pr,
            {
                "ok": True,
                "counting_families": ["claude", "grok"],
                "posted_families": ["claude", "grok"],
                "error": "",
            },
        )


class ReconcilerRecorder:
    def __init__(self, returncode: int = 0) -> None:
        self.calls = 0
        self.returncode = returncode

    def __call__(self) -> int:
        self.calls += 1
        return self.returncode


def _run(
    prs: list[dict[str, Any]],
    packets: dict[int, dict[str, Any]],
    *,
    apply: bool = False,
    allow_legacy_apply: bool = True,
    max_prs: int = 3,
    max_scan: int = 30,
    budget_seconds: float = 1200.0,
    collect: CollectRecorder | None = None,
    reconciler: ReconcilerRecorder | None = None,
    clock: Any = None,
    breaker_threshold: int = 3,
    write_routing_record: Any = None,
    families: tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], CollectRecorder, ReconcilerRecorder]:
    collect = collect or CollectRecorder()
    reconciler = reconciler or ReconcilerRecorder()
    packet_calls: list[int] = []

    def fetch_packet(pr: int) -> dict[str, Any]:
        packet_calls.append(pr)
        return packets.get(pr, {})

    ticks = iter(range(100000)) if clock is None else clock
    summary = cycle.run_cycle(
        list_prs=lambda: prs,
        fetch_packet=fetch_packet,
        run_collect=collect,
        run_reconciler=reconciler,
        apply=apply,
        max_prs=max_prs,
        max_scan=max_scan,
        budget_seconds=budget_seconds,
        breaker_threshold=breaker_threshold,
        write_routing_record=write_routing_record,
        allow_legacy_apply=allow_legacy_apply,
        clock=(lambda: next(ticks) * 0.001) if clock is None else clock,
        **({} if families is None else {"families": families}),
    )
    summary["_packet_calls"] = packet_calls
    return summary, collect, reconciler


# --- Stage-1 selection -------------------------------------------------------


def test_drafts_are_never_candidates() -> None:
    summary, collect, _ = _run(
        [_pr(1, draft=True), _pr(2)],
        {2: _entry(2)},
    )
    assert [item["pr"] for item in summary["plan"]] == [2]
    assert 1 not in summary["_packet_calls"]
    assert collect.calls == []  # dry-run


def test_quorum_success_heads_are_skipped_without_packet_probe() -> None:
    summary, _, _ = _run(
        [_pr(1, checks=[_quorum_check("SUCCESS")]), _pr(2)],
        {2: _entry(2)},
    )
    assert summary["_packet_calls"] == [2]
    assert [item["pr"] for item in summary["plan"]] == [2]


def test_pr_without_quorum_check_is_still_probed() -> None:
    summary, _, _ = _run([_pr(3, checks=[])], {3: _entry(3)})
    assert summary["_packet_calls"] == [3]
    assert [item["pr"] for item in summary["plan"]] == [3]


def test_candidates_scanned_newest_first() -> None:
    # #8316: probe newest-first so a low-numbered tail of permanently ineligible
    # PRs can never starve fresh ready PRs at the high end.
    summary, _, _ = _run(
        [_pr(9), _pr(4), _pr(7)],
        {4: _entry(4), 7: _entry(7), 9: _entry(9)},
    )
    assert summary["_packet_calls"] == [9, 7, 4]


# --- Stage-2 selection (canonical merge-packet probe) -------------------------


def test_satisfied_packets_are_not_selected() -> None:
    summary, _, _ = _run(
        [_pr(1), _pr(2)],
        {1: _entry(1, status="satisfied", families=["claude", "grok"]), 2: _entry(2)},
    )
    assert [item["pr"] for item in summary["plan"]] == [2]


def test_tier3_and_unknown_tier_are_never_selected() -> None:
    summary, _, _ = _run(
        [_pr(1), _pr(2), _pr(3)],
        {1: _entry(1, tier=3), 2: _entry(2, tier=None), 3: _entry(3, tier=2)},
    )
    assert [item["pr"] for item in summary["plan"]] == [3]


def test_human_settlement_and_dissent_are_never_selected() -> None:
    summary, _, _ = _run(
        [_pr(1), _pr(2), _pr(3)],
        {1: _entry(1, human=True), 2: _entry(2, dissent=True), 3: _entry(3)},
    )
    assert [item["pr"] for item in summary["plan"]] == [3]


def test_packet_with_two_counted_families_is_not_selected() -> None:
    summary, _, _ = _run(
        [_pr(1)],
        {1: _entry(1, families=["claude", "grok"])},
    )
    assert summary["plan"] == []


def test_empty_packet_probe_is_skipped_failsafe() -> None:
    summary, _, _ = _run([_pr(1)], {1: {}})
    assert summary["plan"] == []


# --- Caps ---------------------------------------------------------------------


def test_max_prs_caps_the_plan() -> None:
    prs = [_pr(n) for n in (1, 2, 3, 4, 5)]
    packets = {n: _entry(n) for n in (1, 2, 3, 4, 5)}
    summary, _, _ = _run(prs, packets, max_prs=2)
    # Newest-first (#8316): the two freshest PRs are planned, not the oldest.
    assert [item["pr"] for item in summary["plan"]] == [5, 4]
    # Probing stops once the plan is full.
    assert summary["_packet_calls"] == [5, 4]


def test_max_scan_budget_is_eligible_or_indeterminate_not_raw_probes() -> None:
    # #8316: cleanly-ineligible candidates (here: already-satisfied) no longer
    # consume the --max-scan budget. A queue of 10 ineligible PRs is probed in
    # full (none burns budget), the plan stays empty, and the rejections are
    # surfaced by reason — distinguishable from an exhausted scan window.
    prs = [_pr(n) for n in range(1, 11)]
    packets = {n: _entry(n, status="satisfied", families=["claude", "grok"]) for n in range(1, 11)}
    summary, _, _ = _run(prs, packets, max_scan=4)
    assert len(summary["_packet_calls"]) == 10
    assert summary["plan"] == []
    assert summary["rejected_by_reason"]["wrong_status"] == 10
    assert summary["unprobed_candidates"] == 0


def test_max_scan_caps_eligible_examinations() -> None:
    # The eligible-or-indeterminate budget still bounds work: with 10 eligible
    # PRs and max_scan=4 (but max_prs high), only 4 are examined; the rest are
    # surfaced as unprobed so an empty/short plan is distinguishable from an
    # exhausted window.
    prs = [_pr(n) for n in range(1, 11)]
    packets = {n: _entry(n) for n in range(1, 11)}
    summary, _, _ = _run(prs, packets, max_scan=4, max_prs=10)
    assert len(summary["_packet_calls"]) == 4
    assert len(summary["plan"]) == 4
    assert summary["scanned"] == 4
    assert summary["unprobed_candidates"] == 6


def test_budget_exhaustion_stops_scanning() -> None:
    ticks = iter([0.0, 0.0, 10_000.0, 10_000.0, 10_000.0, 10_000.0, 10_000.0])
    summary, collect, _ = _run(
        [_pr(1), _pr(2)],
        {1: _entry(1), 2: _entry(2)},
        budget_seconds=60.0,
        clock=lambda: next(ticks),
    )
    assert summary["budget_exhausted"] is True
    assert collect.calls == []


# --- Dry-run purity ------------------------------------------------------------


def test_dry_run_never_collects_or_reconciles_and_exits_zero() -> None:
    summary, collect, reconciler = _run([_pr(1)], {1: _entry(1)}, apply=False)
    assert collect.calls == []
    assert reconciler.calls == 0
    assert summary["exit_code"] == 0
    assert summary["mode"] == "dry-run"
    assert [item["pr"] for item in summary["plan"]] == [1]


# --- Apply path ----------------------------------------------------------------


def test_apply_runs_collect_with_apply_then_reconciler_once() -> None:
    summary, collect, reconciler = _run(
        [_pr(1), _pr(2)],
        {1: _entry(1), 2: _entry(2)},
        apply=True,
    )
    # Newest-first scan order (#8316): PR 2 is planned/collected before PR 1.
    assert collect.calls == [(2, True), (1, True)]
    assert reconciler.calls == 1
    assert summary["exit_code"] == 0
    assert sorted(summary["posted_prs"]) == [1, 2]


def test_lint_fail_counts_as_failure_and_skips_reconciler() -> None:
    # collect-evidence returns ok=False when <2 families produce counting
    # evidence; the wrapper must treat that as failure and never reconcile.
    collect = CollectRecorder(
        results={
            1: {
                "ok": False,
                "counting_families": ["claude"],
                "posted_families": [],
                "error": "only 1 counting family",
            },
        }
    )
    summary, _, reconciler = _run([_pr(1)], {1: _entry(1)}, apply=True, collect=collect)
    assert reconciler.calls == 0
    assert summary["posted_prs"] == []
    assert summary["exit_code"] == 1
    assert summary["failed_prs"] == [1]


def test_reconciler_failure_fails_closed() -> None:
    reconciler = ReconcilerRecorder(returncode=1)
    summary, _, rec = _run([_pr(1)], {1: _entry(1)}, apply=True, reconciler=reconciler)
    assert rec.calls == 1
    assert summary["exit_code"] == 1


def test_identical_error_breaker_trips_after_threshold() -> None:
    err = {
        "ok": False,
        "counting_families": [],
        "posted_families": [],
        "error": "claude CLI not found on PATH",
    }
    collect = CollectRecorder(results={1: err, 2: err, 3: err, 4: err})
    summary, rec_collect, reconciler = _run(
        [_pr(n) for n in (1, 2, 3, 4)],
        {n: _entry(n) for n in (1, 2, 3, 4)},
        apply=True,
        max_prs=4,
        collect=collect,
        breaker_threshold=3,
    )
    assert len(rec_collect.calls) == 3  # stopped at the breaker, PR 4 untouched
    assert summary["breaker_tripped"] is True
    assert summary["exit_code"] == 2
    assert reconciler.calls == 0


def test_distinct_errors_do_not_trip_breaker() -> None:
    collect = CollectRecorder(
        results={
            1: {"ok": False, "counting_families": [], "posted_families": [], "error": "error A"},
            2: {"ok": False, "counting_families": [], "posted_families": [], "error": "error B"},
            3: {"ok": False, "counting_families": [], "posted_families": [], "error": "error A"},
        }
    )
    summary, rec_collect, _ = _run(
        [_pr(n) for n in (1, 2, 3)],
        {n: _entry(n) for n in (1, 2, 3)},
        apply=True,
        collect=collect,
    )
    assert len(rec_collect.calls) == 3
    assert summary["breaker_tripped"] is False
    assert summary["exit_code"] == 1


def test_success_resets_breaker_counter() -> None:
    err = {"ok": False, "counting_families": [], "posted_families": [], "error": "same"}
    collect = CollectRecorder(results={1: err, 2: err})  # 3 succeeds by default
    summary, rec_collect, _ = _run(
        [_pr(n) for n in (1, 2, 3, 4)],
        {n: _entry(n) for n in (1, 2, 3, 4)},
        apply=True,
        max_prs=4,
        collect=collect,
        breaker_threshold=3,
    )
    assert len(rec_collect.calls) == 4
    assert summary["breaker_tripped"] is False


def test_partial_post_is_a_failure() -> None:
    # One posted family is not quorum evidence; do not treat it as success.
    collect = CollectRecorder(
        results={
            1: {
                "ok": True,
                "counting_families": ["claude", "grok"],
                "posted_families": ["claude"],
                "error": "",
            },
        }
    )
    summary, _, reconciler = _run([_pr(1)], {1: _entry(1)}, apply=True, collect=collect)
    assert summary["posted_prs"] == []
    assert summary["failed_prs"] == [1]
    assert summary["exit_code"] == 1
    assert reconciler.calls == 0


def test_run_cycle_apply_refuses_without_legacy_override_flag() -> None:
    collect = CollectRecorder()
    summary, rec_collect, reconciler = _run(
        [_pr(1)],
        {1: _entry(1)},
        apply=True,
        allow_legacy_apply=False,
        collect=collect,
    )

    assert summary["legacy_apply_refused"] is True
    assert summary["exit_code"] == cycle.EXIT_FAILURES
    assert rec_collect.calls == []
    assert reconciler.calls == 0


# --- Secrets guard --------------------------------------------------------------


def test_sanitized_env_forces_secrets_off(monkeypatch: Any) -> None:
    # Lane V (run-20260609): collect-evidence API reviewers crash under
    # ARAGORA_SECRETS_STRICT=true with MFA-gated AWS (interactive prompt EOF).
    monkeypatch.setenv("ARAGORA_SECRETS_STRICT", "true")
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "true")
    env = cycle._sanitized_env()
    assert env["ARAGORA_SECRETS_STRICT"] == "false"
    assert env["ARAGORA_USE_SECRETS_MANAGER"] == "false"


def test_main_apply_refuses_without_legacy_override(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.delenv(cycle.LEGACY_AUTO_EVIDENCE_APPLY_OVERRIDE_ENV, raising=False)

    rc = cycle.main(["--apply"])

    assert rc == cycle.EXIT_FAILURES
    err = capsys.readouterr().err
    assert "legacy direct auto-evidence apply is disabled" in err
    assert cycle.LEGACY_AUTO_EVIDENCE_APPLY_OVERRIDE_ENV in err


def test_main_apply_with_legacy_override_can_reach_cycle(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setenv(cycle.LEGACY_AUTO_EVIDENCE_APPLY_OVERRIDE_ENV, "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cycle, "default_list_prs", lambda repo: [])

    rc = cycle.main(["--apply", "--repo", "owner/repo", "--no-routing-records"])

    assert rc == cycle.EXIT_OK
    assert '"plan": "empty"' in capsys.readouterr().out


# --- Result parsing --------------------------------------------------------------


def test_parse_collect_output_success() -> None:
    payload = {
        "mode": "collect_evidence",
        "counting_families": ["claude", "grok"],
        "posted_families": ["claude", "grok"],
        "post_errors": [],
    }
    result = cycle.parse_collect_output(0, __import__("json").dumps(payload), "")
    assert result["ok"] is True
    assert result["posted_families"] == ["claude", "grok"]


def test_parse_collect_output_failure_uses_error_field() -> None:
    payload = {"mode": "collect_evidence", "error": "could not resolve head SHA"}
    result = cycle.parse_collect_output(1, __import__("json").dumps(payload), "")
    assert result["ok"] is False
    assert "could not resolve head SHA" in result["error"]


def test_parse_collect_output_garbage_is_failure() -> None:
    result = cycle.parse_collect_output(0, "not json", "boom")
    assert result["ok"] is False
    assert result["error"]


# --- Singleton lock (double-post guard) --------------------------------------------


def test_cycle_lock_blocks_second_acquirer(tmp_path: Any) -> None:
    lock = str(tmp_path / "cycle.lock")
    release = cycle.acquire_cycle_lock(lock)
    try:
        try:
            cycle.acquire_cycle_lock(lock)
        except cycle.CycleLockHeld:
            pass
        else:
            raise AssertionError("expected CycleLockHeld")
    finally:
        release()
    # After release the lock is acquirable again.
    cycle.acquire_cycle_lock(lock)()


def test_cycle_lock_reclaims_stale_lock(tmp_path: Any) -> None:
    lock = str(tmp_path / "cycle.lock")
    cycle.acquire_cycle_lock(lock)  # crashed invocation: never released
    fake_now = __import__("os").path.getmtime(lock) + 7201.0
    release = cycle.acquire_cycle_lock(lock, now=lambda: fake_now)
    release()


def test_cycle_lock_fresh_lock_is_not_reclaimed(tmp_path: Any) -> None:
    lock = str(tmp_path / "cycle.lock")
    cycle.acquire_cycle_lock(lock)
    fake_now = __import__("os").path.getmtime(lock) + 60.0
    try:
        cycle.acquire_cycle_lock(lock, now=lambda: fake_now)
    except cycle.CycleLockHeld:
        pass
    else:
        raise AssertionError("expected CycleLockHeld")


# --- Listing degradation ----------------------------------------------------------


def test_list_prs_falls_back_to_light_listing(monkeypatch: Any) -> None:
    # statusCheckRollup over many PRs 504s GitHub GraphQL (observed live);
    # the lister must degrade to a light listing instead of crashing.
    calls: list[tuple[str, int]] = []

    def fake_gh_pr_list(repo: str, fields: str, limit: int) -> list[dict[str, Any]] | None:
        calls.append((fields, limit))
        if "statusCheckRollup" in fields:
            return None  # heavy query 504s at every page size
        return [{"number": 5, "isDraft": False}]

    monkeypatch.setattr(cycle, "_gh_pr_list", fake_gh_pr_list)
    rows = cycle.default_list_prs("owner/repo")
    assert rows == [{"number": 5, "isDraft": False}]
    assert calls[-1] == ("number,isDraft", 200)
    assert [limit for fields, limit in calls if "statusCheckRollup" in fields] == [100, 50, 30]


def test_list_prs_fails_closed_when_all_listings_fail(monkeypatch: Any) -> None:
    monkeypatch.setattr(cycle, "_gh_pr_list", lambda repo, fields, limit: None)
    try:
        cycle.default_list_prs("owner/repo")
    except RuntimeError as exc:
        assert "gh pr list failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_list_prs_prefers_first_successful_heavy_page(monkeypatch: Any) -> None:
    def fake_gh_pr_list(repo: str, fields: str, limit: int) -> list[dict[str, Any]] | None:
        if "statusCheckRollup" in fields and limit == 30:
            return [{"number": 7, "isDraft": False, "statusCheckRollup": []}]
        if "statusCheckRollup" in fields:
            return None
        raise AssertionError("light listing should not be reached")

    monkeypatch.setattr(cycle, "_gh_pr_list", fake_gh_pr_list)
    rows = cycle.default_list_prs("owner/repo")
    assert rows[0]["number"] == 7


# --- Quorum-check rollup helper ---------------------------------------------------


def test_latest_quorum_conclusion_uses_latest_row() -> None:
    checks = [
        {**_quorum_check("FAILURE"), "completedAt": "2026-06-10T10:00:00Z"},
        {**_quorum_check("SUCCESS"), "completedAt": "2026-06-10T11:00:00Z"},
    ]
    assert cycle.latest_quorum_conclusion({"statusCheckRollup": checks}) == "SUCCESS"


def test_latest_quorum_conclusion_missing() -> None:
    assert cycle.latest_quorum_conclusion({"statusCheckRollup": []}) == ""
    assert cycle.latest_quorum_conclusion({}) == ""


# --- Dogfood pass (#8219) ----------------------------------------------------


def _dogfood_entry(
    pr: int,
    *,
    tier: int = 1,
    requires_dogfood: bool = True,
    dogfood_evidence: list[dict[str, Any]] | None = None,
    human: bool = False,
    dissent: bool = False,
) -> dict[str, Any]:
    # A Tier-1+ code PR whose quorum is complete but dogfood is missing.
    return {
        "pr_number": pr,
        "status": "needs_model_review_quorum",
        "tier": tier,
        "counted_model_families": ["claude", "grok"],
        "requires_adversarial_dogfood": requires_dogfood,
        "dogfood_evidence": dogfood_evidence or [],
        "requires_human_risk_settlement": human,
        "unresolved_dissent": dissent,
    }


class DogfoodRecorder:
    def __init__(self, results: dict[int, dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[int, bool]] = []
        self.results = results or {}

    def __call__(self, pr: int, apply: bool) -> dict[str, Any]:
        self.calls.append((pr, apply))
        return self.results.get(pr, {"status": "posted", "posted": True, "reason": "ok"})


def _run_with_dogfood(
    prs: list[dict[str, Any]],
    packets: dict[int, dict[str, Any]],
    *,
    apply: bool = True,
    dogfood: DogfoodRecorder | None = None,
    reconciler: ReconcilerRecorder | None = None,
    max_dogfood: int = 3,
) -> tuple[dict[str, Any], DogfoodRecorder, ReconcilerRecorder]:
    dogfood = dogfood or DogfoodRecorder()
    reconciler = reconciler or ReconcilerRecorder()

    # Collect runner that posts nothing (these PRs have full quorum already).
    def collect(pr: int, apply_: bool) -> dict[str, Any]:
        return {"ok": False, "counting_families": [], "posted_families": [], "error": "n/a"}

    ticks = iter(range(100000))
    summary = cycle.run_cycle(
        list_prs=lambda: prs,
        fetch_packet=lambda pr: packets.get(pr, {}),
        run_collect=collect,
        run_reconciler=reconciler,
        run_dogfood=dogfood,
        max_dogfood=max_dogfood,
        apply=apply,
        max_prs=3,
        max_scan=30,
        budget_seconds=1200.0,
        breaker_threshold=3,
        allow_legacy_apply=True,
        clock=lambda: next(ticks) * 0.001,
    )
    return summary, dogfood, reconciler


def test_dogfood_selected_for_tier1_code_pr_missing_dogfood() -> None:
    summary, dogfood, recon = _run_with_dogfood([_pr(5)], {5: _dogfood_entry(5)})
    assert [item["pr"] for item in summary["dogfood_plan"]] == [5]
    assert dogfood.calls == [(5, True)]
    assert summary["dogfood_posted_prs"] == [5]
    # A posted dogfood triggers the reconciler so the quorum check reruns.
    assert recon.calls == 1
    assert summary["exit_code"] == cycle.EXIT_OK


def test_dogfood_not_selected_when_evidence_present() -> None:
    summary, dogfood, _ = _run_with_dogfood(
        [_pr(5)], {5: _dogfood_entry(5, dogfood_evidence=[{"reviewer_id": "claude"}])}
    )
    assert summary["dogfood_plan"] == []
    assert dogfood.calls == []


def test_dogfood_not_selected_for_docs_pr() -> None:
    # Tier 0 docs PR: requires_adversarial_dogfood is False.
    summary, dogfood, _ = _run_with_dogfood(
        [_pr(5)], {5: _dogfood_entry(5, tier=0, requires_dogfood=False)}
    )
    assert summary["dogfood_plan"] == []
    assert dogfood.calls == []


def test_dogfood_failure_posts_nothing_and_is_not_a_cycle_failure() -> None:
    # A failing dogfood (PR genuinely not ready) is a real signal, not a fault.
    summary, dogfood, recon = _run_with_dogfood(
        [_pr(5)],
        {5: _dogfood_entry(5)},
        dogfood=DogfoodRecorder({5: {"status": "failed", "posted": False, "reason": "tests red"}}),
    )
    assert summary["dogfood_failed_prs"] == [5]
    assert summary["dogfood_posted_prs"] == []
    assert recon.calls == 0  # nothing posted, no rerun
    assert summary["exit_code"] == cycle.EXIT_OK  # not a cycle failure


def test_dogfood_skipped_untrusted_recorded() -> None:
    summary, _dogfood, recon = _run_with_dogfood(
        [_pr(5)],
        {5: _dogfood_entry(5)},
        dogfood=DogfoodRecorder({5: {"status": "skipped", "posted": False, "reason": "untrusted"}}),
    )
    assert summary["dogfood_skipped_prs"] == [5]
    assert recon.calls == 0
    assert summary["exit_code"] == cycle.EXIT_OK


def test_dogfood_human_risk_pr_not_selected() -> None:
    summary, dogfood, _ = _run_with_dogfood([_pr(5)], {5: _dogfood_entry(5, tier=3, human=True)})
    assert summary["dogfood_plan"] == []
    assert dogfood.calls == []


def test_dogfood_max_cap_honored() -> None:
    prs = [_pr(n) for n in (5, 6, 7, 8)]
    packets = {n: _dogfood_entry(n) for n in (5, 6, 7, 8)}
    summary, dogfood, _ = _run_with_dogfood(prs, packets, max_dogfood=2)
    assert len(summary["dogfood_plan"]) == 2
    assert len(dogfood.calls) == 2


def test_dogfood_dry_run_plans_but_does_not_execute() -> None:
    summary, dogfood, recon = _run_with_dogfood([_pr(5)], {5: _dogfood_entry(5)}, apply=False)
    assert [item["pr"] for item in summary["dogfood_plan"]] == [5]
    assert dogfood.calls == []  # no execution in dry-run
    assert recon.calls == 0


def test_no_dogfood_runner_means_no_dogfood_plan() -> None:
    # Backward compat: without run_dogfood the cycle ignores dogfood entirely.
    summary, _collect, _recon = _run([_pr(5)], {5: _dogfood_entry(5)})
    assert summary["dogfood_plan"] == []


# --- Routing-rationale records (#8233 phase 1) --------------------------------


class RecordRecorder:
    """Injected routing-record writer that records (or rejects) writes."""

    def __init__(self, fail: bool = False) -> None:
        self.records: list[dict[str, Any]] = []
        self.fail = fail

    def __call__(self, record: dict[str, Any]) -> str:
        if self.fail:
            raise OSError("disk full")
        self.records.append(record)
        return f"/tmp/routing_pr{record['pr']}.json"


def test_apply_writes_one_routing_record_per_collected_pr() -> None:
    writer = RecordRecorder()
    summary, _, _ = _run(
        [_pr(1), _pr(2)],
        {1: _entry(1), 2: _entry(2)},
        apply=True,
        write_routing_record=writer,
    )
    # Newest-first scan order (#8316): records are written PR 2 then PR 1.
    assert [r["pr"] for r in writer.records] == [2, 1]
    assert len(summary["routing_records"]) == 2
    assert summary["routing_record_errors"] == []
    assert summary["exit_code"] == 0


def test_routing_record_fields_are_honest() -> None:
    writer = RecordRecorder()
    collect = CollectRecorder(
        results={
            1: {
                "ok": True,
                "counting_families": ["claude", "grok"],
                "posted_families": ["claude", "grok"],
                "head_sha": "a" * 40,
                "tier": 1,
                "error": "",
            }
        }
    )
    _run(
        [_pr(1)],
        {1: _entry(1, tier=1)},
        apply=True,
        collect=collect,
        write_routing_record=writer,
        families=("claude", "grok"),
    )
    (record,) = writer.records
    assert record["record_type"] == "routing_rationale"
    assert record["schema"] == cycle.ROUTING_RECORD_SCHEMA
    assert record["decision_tier"] == 1
    assert record["head_sha"] == "a" * 40
    # families_requested comes from the cycle's configuration, never from the
    # packet scan (regression guard: a scan-loop local must not shadow it).
    assert record["models"]["families_requested"] == ["claude", "grok"]
    assert record["models"]["families_counted"] == ["claude", "grok"]
    assert record["models"]["families_posted"] == ["claude", "grok"]
    # Honest-fields contract: cost is absent (never estimated), and the Pareto
    # optimizer is disclosed as NOT consulted (phase 2 / #8234 territory).
    assert record["cost"]["recorded"] is False
    assert record["cost"]["total_usd"] is None
    assert record["cost"]["absent_reason"]
    assert record["selection_rationale"]["inputs"]["pareto_optimizer_consulted"] is False


def test_routing_record_written_even_for_failed_collect() -> None:
    # A failed collect run is still a routing event worth auditing.
    writer = RecordRecorder()
    collect = CollectRecorder(
        results={
            1: {
                "ok": False,
                "counting_families": [],
                "posted_families": [],
                "error": "reviewer died",
            }
        }
    )
    summary, _, _ = _run(
        [_pr(1)], {1: _entry(1)}, apply=True, collect=collect, write_routing_record=writer
    )
    (record,) = writer.records
    assert record["outcome"]["ok"] is False
    assert "reviewer died" in record["outcome"]["error"]
    assert summary["failed_prs"] == [1]


def test_routing_record_write_failure_never_fails_the_cycle() -> None:
    writer = RecordRecorder(fail=True)
    summary, _, reconciler = _run([_pr(1)], {1: _entry(1)}, apply=True, write_routing_record=writer)
    assert summary["exit_code"] == 0
    assert summary["posted_prs"] == [1]
    assert reconciler.calls == 1
    assert len(summary["routing_record_errors"]) == 1
    assert "disk full" in summary["routing_record_errors"][0]


def test_dry_run_writes_no_routing_records() -> None:
    writer = RecordRecorder()
    summary, _, _ = _run([_pr(1)], {1: _entry(1)}, apply=False, write_routing_record=writer)
    assert writer.records == []
    assert summary["routing_records"] == []


def test_no_writer_means_no_records_backward_compat() -> None:
    summary, _, _ = _run([_pr(1)], {1: _entry(1)}, apply=True)
    assert summary["routing_records"] == []
    assert summary["routing_record_errors"] == []


def test_default_write_routing_record_round_trips(tmp_path: Any) -> None:
    import json as _json

    record = cycle.build_routing_record(
        repo="synaptent/aragora",
        pr=42,
        tier=2,
        families_requested=("claude", "grok"),
        collect_result={
            "ok": True,
            "counting_families": ["claude", "grok"],
            "posted_families": ["claude"],
            "head_sha": "b" * 40,
            "tier": 2,
            "error": "",
        },
        generated_at="2026-06-12T00:00:00Z",
    )
    path = cycle.default_write_routing_record(record, str(tmp_path / "routing"))
    on_disk = _json.loads(Path(path).read_text())
    assert on_disk == record
    assert "pr42" in Path(path).name


def test_build_routing_record_tier_falls_back_to_collect_result() -> None:
    record = cycle.build_routing_record(
        repo="synaptent/aragora",
        pr=7,
        tier=None,
        families_requested=("claude", "grok"),
        collect_result={"ok": True, "tier": 0, "head_sha": "", "error": ""},
    )
    assert record["decision_tier"] == 0


def test_parse_collect_output_carries_head_and_tier() -> None:
    import json as _json

    payload = {
        "mode": "collect_evidence",
        "counting_families": ["claude", "grok"],
        "posted_families": ["claude", "grok"],
        "head_sha": "c" * 40,
        "tier": 2,
    }
    result = cycle.parse_collect_output(0, _json.dumps(payload), "")
    assert result["head_sha"] == "c" * 40
    assert result["tier"] == 2


def test_parse_collect_output_missing_head_and_tier_are_absent_not_invented() -> None:
    import json as _json

    payload = {"mode": "collect_evidence", "counting_families": [], "posted_families": []}
    result = cycle.parse_collect_output(1, _json.dumps(payload), "")
    assert result["head_sha"] == ""
    assert result["tier"] is None


# --- #8316 DEFECT 1: transport/structural conflation -------------------------


def _transport_packet(pr: int, *, error: str = "GraphQL 502") -> dict[str, Any]:
    # Mirrors aragora/cli/commands/review_queue_transport.py: a probe that could
    # not see the PR carries status=transport_blocked / transport_blocked=True.
    return {
        "pr_number": pr,
        "status": "transport_blocked",
        "transport_blocked": True,
        "error": error,
    }


def test_transport_blocked_packet_is_indeterminate_not_silently_empty() -> None:
    # A transport hiccup must NOT look like a clean empty queue: count it in
    # transport_blocked_prs, leave the plan empty, and exit 3 (not 0).
    summary, collect, recon = _run([_pr(1)], {1: _transport_packet(1)})
    assert summary["transport_blocked_prs"] == [1]
    assert summary["plan"] == []
    assert summary["exit_code"] == cycle.EXIT_INDETERMINATE
    assert collect.calls == []  # dry-run posts nothing


def test_transport_blocked_via_status_only_is_detected() -> None:
    # An envelope that carries status=transport_blocked but no boolean flag.
    pkt = {"pr_number": 1, "status": "transport_blocked", "error": "504"}
    summary, _, _ = _run([_pr(1)], {1: pkt})
    assert summary["transport_blocked_prs"] == [1]
    assert summary["exit_code"] == cycle.EXIT_INDETERMINATE


def test_genuinely_empty_packet_still_exits_zero() -> None:
    # A structural empty (PR seen, nothing selectable) is NOT transport-blocked:
    # the queue is genuinely clear, so exit 0 with an empty plan.
    summary, _, _ = _run([_pr(1)], {1: {}})
    assert summary["transport_blocked_prs"] == []
    assert summary["plan"] == []
    assert summary["exit_code"] == cycle.EXIT_OK


def test_transport_drop_with_a_real_post_does_not_force_exit_three() -> None:
    # If something was actually posted, a transport drop elsewhere is not the
    # whole story: the run did real work, so it is not INDETERMINATE.
    summary, _, recon = _run(
        [_pr(2), _pr(1)],
        {2: _entry(2), 1: _transport_packet(1)},
        apply=True,
    )
    assert summary["posted_prs"] == [2]
    assert summary["transport_blocked_prs"] == [1]
    assert summary["exit_code"] == cycle.EXIT_OK


def test_default_fetch_packet_synthesizes_transport_on_failure(monkeypatch: Any) -> None:
    # A non-zero merge-packet exit must surface as a transport-blocked packet,
    # never as {} (which would be indistinguishable from a clean empty queue).
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "gh: API rate limit exceeded"

    monkeypatch.setattr(cycle.subprocess, "run", lambda *a, **k: _Proc())
    entry = cycle.default_fetch_packet("owner/repo", 42)
    assert cycle.is_transport_blocked(entry) is True
    assert entry["pr_number"] == 42


def test_default_fetch_packet_timeout_is_transport_blocked(monkeypatch: Any) -> None:
    def _boom(*a: Any, **k: Any) -> Any:
        raise cycle.subprocess.TimeoutExpired(cmd="merge-packet", timeout=1)

    monkeypatch.setattr(cycle.subprocess, "run", _boom)
    entry = cycle.default_fetch_packet("owner/repo", 7)
    assert cycle.is_transport_blocked(entry) is True


def test_default_fetch_packet_transport_envelope_is_propagated(monkeypatch: Any) -> None:
    import json as _json

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = _json.dumps(
            {
                "version": "merge_authorization_packet.v1",
                "status": "transport_blocked",
                "entries": [],
            }
        )

    monkeypatch.setattr(cycle.subprocess, "run", lambda *a, **k: _Proc())
    entry = cycle.default_fetch_packet("owner/repo", 99)
    assert cycle.is_transport_blocked(entry) is True


def test_consecutive_transport_blocks_trip_the_breaker() -> None:
    # A run of transport failures is a systemic fault: it feeds the same breaker
    # the apply loop uses and aborts the cycle (exit 2).
    prs = [_pr(n) for n in (5, 4, 3, 2, 1)]
    packets = {n: _transport_packet(n) for n in (5, 4, 3, 2, 1)}
    summary, _, _ = _run(prs, packets, breaker_threshold=3)
    assert summary["breaker_tripped"] is True
    assert summary["exit_code"] == cycle.EXIT_BREAKER
    # Stopped at the breaker: only the first 3 were probed.
    assert summary["transport_blocked_prs"] == [5, 4, 3]


# The apply-loop identical-error breaker (3 identical real collect failures →
# exit 2) is unchanged; its regression coverage lives in
# ``test_identical_error_breaker_trips_after_threshold`` above.


# --- #8316 DEFECT 2: scan-window starvation ----------------------------------


def test_ineligible_tail_does_not_starve_a_fresh_eligible_pr() -> None:
    # A tail of permanently-ineligible Tier-3 PRs (oldest, lowest numbers) plus
    # one fresh eligible Tier-1 PR (highest number). With the OLD oldest-first +
    # raw-probe-budget behavior the ineligible tail consumed --max-scan and the
    # fresh PR was never reached; now it is probed and selected.
    prs = [_pr(n) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20)]
    packets = {n: _entry(n, tier=3) for n in range(1, 11)}
    packets[20] = _entry(20, tier=1)  # the fresh eligible PR beyond --max-scan
    summary, _, _ = _run(prs, packets, max_scan=3)
    assert [item["pr"] for item in summary["plan"]] == [20]
    # The ineligible PRs were probed but did not consume the eligible budget.
    assert summary["rejected_by_reason"]["wrong_tier"] == 10
    assert 20 in summary["_packet_calls"]


def test_rejection_reasons_are_surfaced_with_counts() -> None:
    prs = [_pr(n) for n in (1, 2, 3, 4)]
    packets = {
        1: _entry(1, tier=3),  # wrong_tier
        2: _entry(2, human=True),  # human_settlement_required
        3: _entry(3, dissent=True),  # unresolved_dissent
        4: _entry(4, families=["claude", "grok"]),  # quorum_satisfied
    }
    summary, _, _ = _run(prs, packets)
    assert summary["plan"] == []
    assert summary["rejected_by_reason"] == {
        "wrong_tier": 1,
        "human_settlement_required": 1,
        "unresolved_dissent": 1,
        "quorum_satisfied": 1,
    }
    assert summary["scanned"] == 4
    assert summary["unprobed_candidates"] == 0
    # Genuinely clear queue (no transport drops): exit 0.
    assert summary["exit_code"] == cycle.EXIT_OK


def test_rejection_reason_classifier() -> None:
    assert cycle.rejection_reason({}) == "empty_packet"
    assert cycle.rejection_reason({"status": "satisfied", "tier": 1}) == "wrong_status"
    assert (
        cycle.rejection_reason({"status": "needs_model_review_quorum", "tier": 9}) == "wrong_tier"
    )
    assert (
        cycle.rejection_reason({"status": "needs_model_review_quorum", "tier": "x"})
        == "unknown_tier"
    )
    assert (
        cycle.rejection_reason(
            {
                "status": "needs_model_review_quorum",
                "tier": 1,
                "requires_human_risk_settlement": True,
            }
        )
        == "human_settlement_required"
    )
    assert (
        cycle.rejection_reason(
            {
                "status": "needs_model_review_quorum",
                "tier": 1,
                "counted_model_families": ["claude", "grok"],
            }
        )
        == "quorum_satisfied"
    )
    # Selectable entry returns None.
    assert (
        cycle.rejection_reason(
            {"status": "needs_model_review_quorum", "tier": 1, "counted_model_families": ["claude"]}
        )
        is None
    )
