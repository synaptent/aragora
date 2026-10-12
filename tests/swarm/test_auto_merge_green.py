"""Tests for the unattended Tier 0-2 auto-merge decision core.

The decision core (:func:`aragora.swarm.auto_merge_green.decide_auto_merge`) is
pure: it takes an already-fetched PR context and returns whether the PR may be
merged unattended, plus the blockers that prevented it. It encodes the *same*
authorization the merge-quorum gate already grants for Tier 0-2 PRs whose
merge-packet reaches ``status=satisfied`` -- it never makes a new risk judgment,
it only decides whether to *execute* an already-authorized merge without a human.

Safety is the whole point, so every guard that keeps a not-fully-authorized PR
from auto-merging gets its own test asserting the specific blocker.
"""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from aragora.swarm.auto_merge_green import (
    MAX_AUTO_MERGE_TIER,
    REQUIRED_CHECKS,
    MergeDecision,
    PRMergeContext,
    apply_merges,
    context_from_gh,
    decide_auto_merge,
    first_error_line,
    required_check_surface_proves_optional_only_unstable,
)


def _green_checks() -> dict[str, str]:
    states = dict.fromkeys(REQUIRED_CHECKS, "SUCCESS")
    states["aragora-merge-quorum"] = "SUCCESS"
    return states


def _authorized_context(**overrides) -> PRMergeContext:
    """A fully-authorized Tier-2 PR: every guard passes unless overridden."""
    base = dict(
        number=8447,
        head_sha="a" * 40,
        packet_head_sha="a" * 40,
        packet_pr_number=8447,
        tier=2,
        packet_status="satisfied",
        packet_verdict="admin_squash_allowed",
        requires_human_risk_settlement=False,
        unresolved_dissent=False,
        admin_squash_allowed=True,
        is_draft=False,
        mergeable="MERGEABLE",
        merge_state_status="BLOCKED",
        check_states=_green_checks(),
        check_surfaces={},
    )
    base.update(overrides)
    return PRMergeContext(**base)


def test_fully_authorized_tier2_pr_is_merged():
    decision = decide_auto_merge(_authorized_context())
    assert decision.should_merge is True
    assert decision.blockers == ()
    assert decision.number == 8447
    assert decision.head_sha == "a" * 40


def test_packet_head_mismatch_is_blocked():
    # The merge-packet is fetched in a separate subprocess from the gh view; if
    # the head moved between them we'd be deciding on mismatched data.
    decision = decide_auto_merge(_authorized_context(packet_head_sha="f" * 40))
    assert decision.should_merge is False
    assert any("head" in b.lower() for b in decision.blockers)


def test_absent_packet_head_does_not_add_mismatch_blocker():
    # packet=None -> packet_head_sha="" -> tier=None already blocks; no spurious
    # head-mismatch blocker should pile on.
    decision = decide_auto_merge(_authorized_context(packet_head_sha="", tier=None))
    assert decision.should_merge is False
    assert not any("head" in b.lower() and "mismatch" in b.lower() for b in decision.blockers)


def test_packet_pr_number_mismatch_is_blocked():
    # Defense-in-depth: a packet entry bound to a different PR must not merge.
    decision = decide_auto_merge(_authorized_context(packet_pr_number=9999))
    assert decision.should_merge is False
    assert any("pr mismatch" in b.lower() for b in decision.blockers)


def test_absent_packet_pr_number_blocks():
    # A packet with no concrete PR identity cannot safely be bound to the gh
    # view. Fail closed instead of treating "undisclosed" as acceptable.
    decision = decide_auto_merge(_authorized_context(packet_pr_number=0))
    assert decision.should_merge is False
    assert any("packet pr number" in b.lower() for b in decision.blockers)


def test_negative_tier_is_blocked():
    decision = decide_auto_merge(_authorized_context(tier=-1))
    assert decision.should_merge is False
    assert any("tier" in b.lower() for b in decision.blockers)


def test_clean_merge_state_is_also_mergeable():
    # A Tier-0 docs PR can reach CLEAN (no branch-protection block); still merge.
    decision = decide_auto_merge(_authorized_context(tier=0, merge_state_status="CLEAN"))
    assert decision.should_merge is True
    assert decision.blockers == ()


def test_tier_three_is_blocked_for_human_settlement():
    decision = decide_auto_merge(_authorized_context(tier=3))
    assert decision.should_merge is False
    assert any("tier" in b.lower() for b in decision.blockers)


def test_tier_four_is_blocked():
    decision = decide_auto_merge(_authorized_context(tier=4))
    assert decision.should_merge is False
    assert any("tier" in b.lower() for b in decision.blockers)


def test_unknown_tier_is_blocked():
    decision = decide_auto_merge(_authorized_context(tier=None))
    assert decision.should_merge is False
    assert any("tier" in b.lower() for b in decision.blockers)


def test_requires_human_risk_settlement_is_blocked():
    decision = decide_auto_merge(_authorized_context(requires_human_risk_settlement=True))
    assert decision.should_merge is False
    assert any("human" in b.lower() for b in decision.blockers)


def test_packet_status_not_satisfied_is_blocked():
    decision = decide_auto_merge(_authorized_context(packet_status="needs_model_review_quorum"))
    assert decision.should_merge is False
    assert any("satisfied" in b.lower() for b in decision.blockers)


def test_packet_verdict_not_admin_squash_is_blocked():
    decision = decide_auto_merge(
        _authorized_context(packet_verdict="collect_model_quorum_before_merge")
    )
    assert decision.should_merge is False
    assert any("verdict" in b.lower() for b in decision.blockers)


def test_admin_squash_not_allowed_is_blocked():
    decision = decide_auto_merge(_authorized_context(admin_squash_allowed=False))
    assert decision.should_merge is False
    assert any("admin squash" in b.lower() for b in decision.blockers)


def test_unresolved_dissent_is_blocked():
    decision = decide_auto_merge(_authorized_context(unresolved_dissent=True))
    assert decision.should_merge is False
    assert any("dissent" in b.lower() for b in decision.blockers)


def test_draft_is_blocked():
    decision = decide_auto_merge(_authorized_context(is_draft=True))
    assert decision.should_merge is False
    assert any("draft" in b.lower() for b in decision.blockers)


def test_conflicting_is_blocked():
    decision = decide_auto_merge(_authorized_context(mergeable="CONFLICTING"))
    assert decision.should_merge is False
    assert any("mergeable" in b.lower() for b in decision.blockers)


def test_unknown_mergeability_is_blocked():
    decision = decide_auto_merge(_authorized_context(mergeable="UNKNOWN"))
    assert decision.should_merge is False
    assert any("mergeable" in b.lower() for b in decision.blockers)


def test_dirty_merge_state_is_blocked():
    decision = decide_auto_merge(_authorized_context(merge_state_status="DIRTY"))
    assert decision.should_merge is False
    assert any("merge state" in b.lower() for b in decision.blockers)


def test_unstable_merge_state_is_blocked():
    # UNSTABLE alone is not evidence that only optional checks are non-green.
    decision = decide_auto_merge(_authorized_context(merge_state_status="UNSTABLE"))
    assert decision.should_merge is False
    assert any("merge state" in b.lower() for b in decision.blockers)


def _optional_only_unstable_surface(**required_overrides) -> dict:
    required = {
        "available": True,
        "effective_total": 6,
        "gate_selected": True,
        "gate_blocked_reason": "",
        "failing_or_cancelled": [],
        "pending": [],
    }
    required.update(required_overrides)
    return {
        "effective_gate": {"source": "required_pr_checks", "summary": "6/6 required green"},
        "required_pr_checks": required,
        "pr_rollup": {
            "available": True,
            "non_green_count": 2,
            "non_required_non_green_count": 2,
            "non_required_non_green_sample": ["npm Security Scan", "Security Gate Summary"],
            "failing_or_cancelled_count": 2,
            "pending_count": 0,
            "unverified_cancelled_non_required_count": 0,
            "unverified_cancelled_non_required_sample": [],
        },
        "unstable_receipt_guard": {"modifies_guarded_paths": False},
    }


_PROOF_COUNT_KEYS = (
    "non_green_count",
    "non_required_non_green_count",
    "failing_or_cancelled_count",
    "pending_count",
    "unverified_cancelled_non_required_count",
)


def _executor_proof(surface: dict, **overrides) -> dict:
    """merge-packet's ``optional_only_unstable_executor_proof`` field for ``surface``."""
    proof = {
        "model_quorum_status": "satisfied",
        "model_quorum_verdict": "admin_squash_allowed",
        "model_quorum_admin_squash_allowed": True,
        "proof_counts": {key: surface["pr_rollup"].get(key) for key in _PROOF_COUNT_KEYS},
    }
    proof.update(overrides)
    return proof


def _unstable_proof_context(surface: dict | None = None, **overrides) -> PRMergeContext:
    """An optional-only UNSTABLE PR as merge-packet reports it.

    The packet's own live gate blocks UNSTABLE, so its status, verdict and
    admin_squash_allowed read as blocked; only the separate executor proof field
    carries the model-level verdict and the proof counts.
    """
    surface = _optional_only_unstable_surface() if surface is None else surface
    base = dict(
        merge_state_status="UNSTABLE",
        packet_status="blocked_by_live_gate",
        packet_verdict="admin_squash_blocked_by_live_gate",
        admin_squash_allowed=False,
        operator_review_required=False,
        check_surfaces=surface,
        optional_only_unstable_executor_proof=_executor_proof(surface),
    )
    base.update(overrides)
    return _authorized_context(**base)


def _unstable_view(extra_rows: list[dict]) -> dict:
    return {
        "number": 9453,
        "headRefOid": "a" * 40,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "UNSTABLE",
        "statusCheckRollup": [
            *[
                {"name": name, "conclusion": "SUCCESS"}
                for name in sorted(REQUIRED_CHECKS | {"aragora-merge-quorum"})
            ],
            *extra_rows,
        ],
    }


def _unstable_packet(check_surfaces: dict) -> dict:
    """A merge-packet entry for an optional-only UNSTABLE PR, as the producer builds it."""
    return {
        "pr_number": 9453,
        "head_sha": "a" * 40,
        "tier": 2,
        "status": "blocked_by_live_gate",
        "verdict": "admin_squash_blocked_by_live_gate",
        "admin_squash_allowed": False,
        "model_quorum_admin_squash_allowed": True,
        "admin_squash_gate_blockers": [
            "mergeStateStatus=UNSTABLE; admin squash requires CLEAN or BLOCKED"
        ],
        "operator_review_required": False,
        "requires_human_risk_settlement": False,
        "unresolved_dissent": False,
        "check_surfaces": check_surfaces,
        "optional_only_unstable_executor_proof": _executor_proof(check_surfaces),
    }


@pytest.mark.parametrize("count", ["absent", 1, -1, True, "0", None])
def test_unstable_proof_requires_zero_unverified_cancelled_optional_rows(count):
    # Non-quorum cancelled rows never reach the rollup's non-green counts, so the
    # proof needs the producer's separate count of them and fails closed without it.
    surface = _optional_only_unstable_surface()
    if count == "absent":
        del surface["pr_rollup"]["unverified_cancelled_non_required_count"]
    else:
        surface["pr_rollup"]["unverified_cancelled_non_required_count"] = count
    assert required_check_surface_proves_optional_only_unstable(surface) is False


def test_unstable_with_an_unverified_cancelled_optional_row_in_the_packet_is_blocked():
    # The live view no longer shows the cancelled row (it was rerun green), but
    # the packet that vouches for the merge counted it unverified.
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Security Gate Summary"] = "FAILURE"
    surface = _optional_only_unstable_surface()
    surface["pr_rollup"]["unverified_cancelled_non_required_count"] = 1
    surface["pr_rollup"]["unverified_cancelled_non_required_sample"] = [
        "Build Documentation (PR Check) / build"
    ]
    decision = decide_auto_merge(
        _unstable_proof_context(
            surface,
            check_states=states,
            failing_check_identities=frozenset({"npm Security Scan", "Security Gate Summary"}),
        )
    )
    assert decision.should_merge is False
    assert any("merge state" in blocker.lower() for blocker in decision.blockers)
    assert decision.waived_failing_checks == ()
    assert decision.optional_only_unstable_proof is None


@pytest.mark.parametrize(
    "guard",
    [
        "absent",
        None,
        {},
        {"modifies_guarded_paths": True},
        {"modifies_guarded_paths": None},
        {"modifies_guarded_paths": 0},
        {"modifies_guarded_paths": "false"},
    ],
)
def test_unstable_proof_refuses_prs_that_touch_or_cannot_clear_guarded_paths(guard):
    # A PR that edits the gate (or whose file list could not be read) cannot
    # present its own failures as optional-only.
    surface = _optional_only_unstable_surface()
    if guard == "absent":
        del surface["unstable_receipt_guard"]
    else:
        surface["unstable_receipt_guard"] = guard
    assert required_check_surface_proves_optional_only_unstable(surface) is False
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Security Gate Summary"] = "FAILURE"
    decision = decide_auto_merge(
        _unstable_proof_context(
            surface,
            check_states=states,
            failing_check_identities=frozenset({"npm Security Scan", "Security Gate Summary"}),
        )
    )
    assert decision.should_merge is False
    assert any("merge state" in blocker.lower() for blocker in decision.blockers)


def test_optional_only_waiver_is_recorded_in_the_decision():
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Security Gate Summary"] = "FAILURE"
    decision = decide_auto_merge(
        _unstable_proof_context(
            check_states=states,
            failing_check_identities=frozenset({"Security Gate Summary", "npm Security Scan"}),
        )
    )
    assert decision.should_merge is True
    assert decision.waived_failing_checks == ("Security Gate Summary", "npm Security Scan")
    assert decision.optional_only_unstable_proof == {
        "non_green_count": 2,
        "non_required_non_green_count": 2,
        "failing_or_cancelled_count": 2,
        "pending_count": 0,
        "unverified_cancelled_non_required_count": 0,
    }


def test_optional_only_proof_without_failing_rows_records_counts_and_no_waived_rows():
    # Optional rows that are only pending make GitHub report UNSTABLE too; the
    # proof lets the merge state through but there is no failing row to waive.
    surface = _optional_only_unstable_surface()
    surface["pr_rollup"].update(failing_or_cancelled_count=0, pending_count=2)
    decision = decide_auto_merge(
        _unstable_proof_context(surface, failing_check_identities=frozenset())
    )
    assert decision.should_merge is True
    assert decision.waived_failing_checks == ()
    assert decision.optional_only_unstable_proof == {
        "non_green_count": 2,
        "non_required_non_green_count": 2,
        "failing_or_cancelled_count": 0,
        "pending_count": 2,
        "unverified_cancelled_non_required_count": 0,
    }


def test_decisions_outside_the_optional_only_proof_record_no_waiver():
    merged = decide_auto_merge(_authorized_context())
    assert merged.should_merge is True
    assert merged.waived_failing_checks == ()
    assert merged.optional_only_unstable_proof is None
    assert merged.waiver_record() == {}

    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    blocked = decide_auto_merge(_authorized_context(check_states=states))
    assert blocked.should_merge is False
    assert blocked.waived_failing_checks == ()
    assert blocked.optional_only_unstable_proof is None


def _waiver_decision(number: int = 9453) -> MergeDecision:
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Security Gate Summary"] = "FAILURE"
    decision = decide_auto_merge(
        _unstable_proof_context(
            number=number,
            packet_pr_number=number,
            check_states=states,
            failing_check_identities=frozenset({"npm Security Scan", "Security Gate Summary"}),
        )
    )
    assert decision.should_merge is True
    return decision


_EXPECTED_WAIVER_RECORD = {
    "waived_failing_checks": ["Security Gate Summary", "npm Security Scan"],
    "optional_only_unstable_proof": {
        "non_green_count": 2,
        "non_required_non_green_count": 2,
        "failing_or_cancelled_count": 2,
        "pending_count": 0,
        "unverified_cancelled_non_required_count": 0,
    },
}


def test_apply_merges_records_waived_rows_for_would_merge_entries():
    plain = decide_auto_merge(_authorized_context(number=8447))
    results = apply_merges(
        [_waiver_decision(), plain],
        merge_fn=lambda *_args: pytest.fail("dry run must not merge"),
        dry_run=True,
    )
    assert results[0]["action"] == "would-merge"
    assert {key: results[0][key] for key in _EXPECTED_WAIVER_RECORD} == _EXPECTED_WAIVER_RECORD
    assert results[1]["action"] == "would-merge"
    assert "waived_failing_checks" not in results[1]
    assert "optional_only_unstable_proof" not in results[1]


@pytest.mark.parametrize(("merge_ok", "action"), [(True, "merged"), (False, "merge-failed")])
def test_apply_merges_records_waived_rows_for_merge_attempts(merge_ok, action):
    calls: list[tuple[int, str]] = []

    def merger(pr: int, head: str) -> tuple[bool, str]:
        calls.append((pr, head))
        return merge_ok, "detail"

    results = apply_merges([_waiver_decision()], merge_fn=merger, dry_run=False)
    assert calls == [(9453, "a" * 40)]
    assert results[0]["action"] == action
    assert {key: results[0][key] for key in _EXPECTED_WAIVER_RECORD} == _EXPECTED_WAIVER_RECORD


def test_apply_merges_skip_records_carry_no_waiver():
    blocked = decide_auto_merge(_authorized_context(merge_state_status="UNSTABLE"))
    results = apply_merges([blocked], merge_fn=lambda *_args: (True, "x"), dry_run=False)
    assert results[0]["action"] == "skip"
    assert "waived_failing_checks" not in results[0]
    assert "optional_only_unstable_proof" not in results[0]


def test_unstable_with_authoritative_required_green_surface_is_mergeable():
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Security Gate Summary"] = "FAILURE"
    decision = decide_auto_merge(
        _unstable_proof_context(
            check_states=states,
            failing_check_identities=frozenset({"npm Security Scan", "Security Gate Summary"}),
        )
    )
    assert decision.should_merge is True
    assert decision.blockers == ()


@pytest.mark.parametrize(
    "required_overrides",
    [
        {"available": False},
        {"failing_or_cancelled": ["lint"]},
        {"pending": ["typecheck"]},
        {"gate_blocked_reason": ["malformed"]},
    ],
)
def test_unstable_required_surface_failures_remain_blocked(required_overrides):
    surface = _optional_only_unstable_surface(**required_overrides)
    assert required_check_surface_proves_optional_only_unstable(surface) is False
    decision = decide_auto_merge(_unstable_proof_context(surface))
    assert decision.should_merge is False
    assert any("merge state" in blocker.lower() for blocker in decision.blockers)


def test_context_from_gh_reads_the_executor_proof_field():
    view = {
        "number": 9453,
        "headRefOid": "a" * 40,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "UNSTABLE",
        "statusCheckRollup": [
            *[
                {"name": name, "conclusion": "SUCCESS"}
                for name in sorted(REQUIRED_CHECKS | {"aragora-merge-quorum"})
            ],
            {"name": "npm Security Scan", "conclusion": "FAILURE"},
            {"name": "Security Gate Summary", "conclusion": "FAILURE"},
        ],
    }
    packet = _unstable_packet(_optional_only_unstable_surface())
    decision = decide_auto_merge(context_from_gh(view, packet))
    assert decision.should_merge is True
    assert decision.blockers == ()


def _optional_only_states() -> dict[str, str]:
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Security Gate Summary"] = "FAILURE"
    return states


_OPTIONAL_ONLY_IDENTITIES = frozenset({"npm Security Scan", "Security Gate Summary"})


def test_unstable_proof_applies_only_through_the_executor_proof_field():
    # A packet whose own verdict admitted the UNSTABLE PR (the packet-level
    # relaxation) still carries a valid check surface, but without the executor
    # proof field the merge state is not let through.
    decision = decide_auto_merge(
        _authorized_context(
            merge_state_status="UNSTABLE",
            check_states=_optional_only_states(),
            check_surfaces=_optional_only_unstable_surface(),
            failing_check_identities=_OPTIONAL_ONLY_IDENTITIES,
            operator_review_required=False,
        )
    )
    assert decision.should_merge is False
    assert "merge state not safe (mergeStateStatus=UNSTABLE)" in decision.blockers
    assert decision.waiver_record() == {}


def test_blocked_packet_without_the_executor_proof_field_stays_blocked():
    decision = decide_auto_merge(
        _unstable_proof_context(
            check_states=_optional_only_states(),
            failing_check_identities=_OPTIONAL_ONLY_IDENTITIES,
            optional_only_unstable_executor_proof=None,
        )
    )
    assert decision.should_merge is False
    assert "merge-packet status not satisfied (blocked_by_live_gate)" in decision.blockers
    assert "admin squash not allowed by merge-packet" in decision.blockers
    assert "merge state not safe (mergeStateStatus=UNSTABLE)" in decision.blockers


@pytest.mark.parametrize(
    "proof_overrides",
    [
        {"model_quorum_status": "needs_model_review_quorum"},
        {"model_quorum_verdict": "operator_advisory_settlement"},
        {"model_quorum_admin_squash_allowed": False},
        {"model_quorum_admin_squash_allowed": "true"},
    ],
)
def test_executor_proof_requires_the_model_level_admin_squash_verdict(proof_overrides):
    surface = _optional_only_unstable_surface()
    decision = decide_auto_merge(
        _unstable_proof_context(
            surface,
            check_states=_optional_only_states(),
            failing_check_identities=_OPTIONAL_ONLY_IDENTITIES,
            optional_only_unstable_executor_proof=_executor_proof(surface, **proof_overrides),
        )
    )
    assert decision.should_merge is False
    assert decision.waived_failing_checks == ()


def test_executor_proof_refuses_an_operator_review_hold():
    decision = decide_auto_merge(
        _unstable_proof_context(
            check_states=_optional_only_states(),
            failing_check_identities=_OPTIONAL_ONLY_IDENTITIES,
            operator_review_required=True,
        )
    )
    assert decision.should_merge is False
    assert "merge state not safe (mergeStateStatus=UNSTABLE)" in decision.blockers
    assert decision.optional_only_unstable_proof is None


@pytest.mark.parametrize(
    "proof",
    [
        "malformed",
        {"model_quorum_status": "satisfied"},
        "counts-disagree",
        "counts-missing-key",
    ],
)
def test_executor_proof_must_be_well_formed_and_match_the_packet_rollup(proof):
    surface = _optional_only_unstable_surface()
    if proof == "counts-disagree":
        proof = _executor_proof(surface)
        proof["proof_counts"] = dict(proof["proof_counts"], non_green_count=3)
    elif proof == "counts-missing-key":
        proof = _executor_proof(surface)
        del proof["proof_counts"]["pending_count"]
    decision = decide_auto_merge(
        _unstable_proof_context(
            surface,
            check_states=_optional_only_states(),
            failing_check_identities=_OPTIONAL_ONLY_IDENTITIES,
            optional_only_unstable_executor_proof=proof,
        )
    )
    assert decision.should_merge is False
    assert "merge state not safe (mergeStateStatus=UNSTABLE)" in decision.blockers


@pytest.mark.parametrize(
    ("packet_status", "packet_verdict"),
    [
        ("needs_model_review_quorum", "operator_advisory_settlement"),
        ("blocked_by_live_gate", "admin_squash_allowed"),
        ("satisfied", "admin_squash_blocked_by_live_gate"),
        ("", ""),
    ],
)
def test_executor_proof_must_sit_beside_the_model_or_live_gate_verdict(
    packet_status, packet_verdict
):
    # The field stands in only for a verdict the packet's live gate withheld; it
    # cannot override any other packet status.
    decision = decide_auto_merge(
        _unstable_proof_context(
            check_states=_optional_only_states(),
            failing_check_identities=_OPTIONAL_ONLY_IDENTITIES,
            packet_status=packet_status,
            packet_verdict=packet_verdict,
        )
    )
    assert decision.should_merge is False
    assert "merge state not safe (mergeStateStatus=UNSTABLE)" in decision.blockers
    assert decision.waiver_record() == {}


def test_executor_proof_is_ignored_outside_unstable():
    # The field only ever stands in for the packet's verdict on an UNSTABLE PR.
    decision = decide_auto_merge(_unstable_proof_context(merge_state_status="BLOCKED"))
    assert decision.should_merge is False
    assert "merge-packet status not satisfied (blocked_by_live_gate)" in decision.blockers


@pytest.mark.parametrize("flag", ["absent", None, "false", True])
def test_context_from_gh_fails_closed_on_the_operator_review_flag(flag):
    view = _unstable_view(
        [
            {"name": "npm Security Scan", "conclusion": "FAILURE"},
            {"name": "Security Gate Summary", "conclusion": "FAILURE"},
        ]
    )
    packet = _unstable_packet(_optional_only_unstable_surface())
    if flag == "absent":
        del packet["operator_review_required"]
    else:
        packet["operator_review_required"] = flag
    decision = decide_auto_merge(context_from_gh(view, packet))
    assert decision.should_merge is False
    assert "merge state not safe (mergeStateStatus=UNSTABLE)" in decision.blockers


def test_unstable_proof_does_not_waive_live_cancelled_optional_row():
    # The packet's rollup counts never include cancelled non-quorum rows, so a
    # live cancellation is outside what the optional-only proof covers.
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Security Gate Summary"] = "FAILURE"
    states["Docs Consistency"] = "CANCELLED"
    decision = decide_auto_merge(_unstable_proof_context(check_states=states))
    assert decision.should_merge is False
    assert any("failing checks" in blocker for blocker in decision.blockers)
    assert any("Docs Consistency" in blocker for blocker in decision.blockers)


def test_unstable_proof_never_waives_a_cancelled_row_even_when_counts_match():
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Docs Consistency"] = "CANCELLED"
    decision = decide_auto_merge(_unstable_proof_context(check_states=states))
    assert decision.should_merge is False
    assert any("failing checks" in blocker for blocker in decision.blockers)


def test_unstable_proof_does_not_waive_a_live_failure_the_packet_did_not_count():
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Security Gate Summary"] = "FAILURE"
    states["Newly Added Check"] = "FAILURE"
    decision = decide_auto_merge(_unstable_proof_context(check_states=states))
    assert decision.should_merge is False
    assert any("failing checks" in blocker for blocker in decision.blockers)


def test_context_from_gh_unstable_proof_keeps_live_cancelled_row_blocking():
    view = {
        "number": 9453,
        "headRefOid": "a" * 40,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "UNSTABLE",
        "statusCheckRollup": [
            *[
                {"name": name, "conclusion": "SUCCESS"}
                for name in sorted(REQUIRED_CHECKS | {"aragora-merge-quorum"})
            ],
            {"name": "npm Security Scan", "conclusion": "FAILURE"},
            {"name": "Security Gate Summary", "conclusion": "FAILURE"},
            {"name": "Integration Smoke", "conclusion": "CANCELLED"},
        ],
    }
    packet = _unstable_packet(_optional_only_unstable_surface())
    decision = decide_auto_merge(context_from_gh(view, packet))
    assert decision.should_merge is False
    assert any("Integration Smoke" in blocker for blocker in decision.blockers)


def test_unstable_proof_does_not_waive_a_different_row_failing_in_a_proven_rows_place():
    # The packet proved two optional failures. Live, one of them went green and
    # a row the packet never named failed instead: the count still matches, but
    # the proof does not cover the new row.
    view = _unstable_view(
        [
            {"name": "npm Security Scan", "conclusion": "SUCCESS"},
            {"name": "Security Gate Summary", "conclusion": "FAILURE"},
            {"name": "Release Readiness", "conclusion": "FAILURE"},
        ]
    )
    decision = decide_auto_merge(
        context_from_gh(view, _unstable_packet(_optional_only_unstable_surface()))
    )
    assert decision.should_merge is False
    assert any("Release Readiness" in blocker for blocker in decision.blockers)


def test_unstable_proof_binds_the_workflow_qualified_identity():
    # Two workflows share the bare job name "test". The packet proved only the
    # optional workflow's row; live, that row passed and the other one failed.
    surface = _optional_only_unstable_surface()
    surface["pr_rollup"].update(
        non_green_count=1,
        non_required_non_green_count=1,
        non_required_non_green_sample=["Optional Scans / test"],
        failing_or_cancelled_count=1,
    )
    view = _unstable_view(
        [
            {
                "name": "test",
                "workflowName": "Optional Scans",
                "conclusion": "SUCCESS",
                "startedAt": "2026-10-07T06:00:00Z",
                "completedAt": "2026-10-07T06:05:00Z",
            },
            {
                "name": "test",
                "workflowName": "Release Gate",
                "conclusion": "FAILURE",
                "startedAt": "2026-10-07T06:10:00Z",
                "completedAt": "2026-10-07T06:15:00Z",
            },
        ]
    )
    decision = decide_auto_merge(context_from_gh(view, _unstable_packet(surface)))
    assert decision.should_merge is False
    assert any("failing checks" in blocker for blocker in decision.blockers)


def test_unstable_proof_refuses_a_truncated_packet_sample():
    # The packet's name sample is capped; when it cannot name every proven row,
    # the live rows cannot be matched to the proof and the veto stands.
    names = [f"Optional Check {index:02d}" for index in range(13)]
    surface = _optional_only_unstable_surface()
    surface["pr_rollup"].update(
        non_green_count=13,
        non_required_non_green_count=13,
        non_required_non_green_sample=names[:12],
        failing_or_cancelled_count=13,
    )
    view = _unstable_view([{"name": name, "conclusion": "FAILURE"} for name in names])
    decision = decide_auto_merge(context_from_gh(view, _unstable_packet(surface)))
    assert decision.should_merge is False
    assert any("failing checks" in blocker for blocker in decision.blockers)


def test_unstable_proof_without_live_failing_identities_fails_closed():
    # A context built without the live failing identities cannot be matched to
    # the packet's named rows, so the optional-only waiver does not apply.
    states = _green_checks()
    states["npm Security Scan"] = "FAILURE"
    states["Security Gate Summary"] = "FAILURE"
    decision = decide_auto_merge(_unstable_proof_context(check_states=states))
    assert decision.should_merge is False
    assert any("failing checks" in blocker for blocker in decision.blockers)


def test_unstable_proof_accepts_identities_named_by_the_packet_producer():
    # Build the packet's rollup diagnostics with the real producer from the same
    # workflow-qualified rows the executor sees, so both sides name rows alike.
    from aragora.cli.commands.review_queue import _rollup_non_green_diagnostics

    optional_rows = [
        {
            "name": "npm Security Scan",
            "workflowName": "Security",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
            "startedAt": "2026-10-07T06:00:00Z",
            "completedAt": "2026-10-07T06:05:00Z",
        },
        {
            "name": "Security Gate Summary",
            "workflowName": "Security",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
            "startedAt": "2026-10-07T06:00:00Z",
            "completedAt": "2026-10-07T06:06:00Z",
        },
    ]
    view = _unstable_view(optional_rows)
    diagnostics = _rollup_non_green_diagnostics(
        view["statusCheckRollup"],
        required_checks=[{"name": name} for name in sorted(REQUIRED_CHECKS)],
    )
    surface = _optional_only_unstable_surface()
    surface["pr_rollup"] = {"available": True, **diagnostics}
    assert surface["pr_rollup"]["non_required_non_green_sample"] == [
        "Security / npm Security Scan",
        "Security / Security Gate Summary",
    ]

    decision = decide_auto_merge(context_from_gh(view, _unstable_packet(surface)))
    assert decision.should_merge is True
    assert decision.blockers == ()


def test_quorum_not_green_is_blocked():
    states = _green_checks()
    states["aragora-merge-quorum"] = "FAILURE"
    decision = decide_auto_merge(_authorized_context(check_states=states))
    assert decision.should_merge is False
    assert any("quorum" in b.lower() for b in decision.blockers)


def test_quorum_missing_is_blocked():
    states = _green_checks()
    del states["aragora-merge-quorum"]
    decision = decide_auto_merge(_authorized_context(check_states=states))
    assert decision.should_merge is False
    assert any("quorum" in b.lower() for b in decision.blockers)


def test_any_failing_required_check_is_blocked():
    states = _green_checks()
    states["lint"] = "FAILURE"
    decision = decide_auto_merge(_authorized_context(check_states=states))
    assert decision.should_merge is False
    assert any("lint" in b for b in decision.blockers)


def test_pending_required_check_is_blocked():
    states = _green_checks()
    states["typecheck"] = "PENDING"
    decision = decide_auto_merge(_authorized_context(check_states=states))
    assert decision.should_merge is False
    assert any("typecheck" in b for b in decision.blockers)


def test_missing_required_check_is_blocked():
    states = _green_checks()
    del states["sdk-parity"]
    decision = decide_auto_merge(_authorized_context(check_states=states))
    assert decision.should_merge is False
    assert any("sdk-parity" in b for b in decision.blockers)


def test_multiple_blockers_are_all_reported():
    decision = decide_auto_merge(
        _authorized_context(tier=4, is_draft=True, mergeable="CONFLICTING")
    )
    assert decision.should_merge is False
    # all three independent problems surface, not just the first
    assert len(decision.blockers) >= 3


def test_max_tier_is_two_by_default():
    assert MAX_AUTO_MERGE_TIER == 2


def test_context_is_immutable():
    ctx = _authorized_context()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.tier = 4  # type: ignore[misc]


def test_failing_non_required_check_blocks_even_when_blocked():
    # The target population is ~always mergeStateStatus=BLOCKED, so a failing
    # *non-required* check would otherwise pass every guard and get --admin
    # merged. Any failing check in the rollup must block.
    states = _green_checks()
    states["Baseline Determinism"] = "FAILURE"  # non-required, failing
    decision = decide_auto_merge(
        _authorized_context(check_states=states, merge_state_status="BLOCKED")
    )
    assert decision.should_merge is False
    assert any(
        "baseline determinism" in b.lower() or "failing" in b.lower() for b in decision.blockers
    )


def test_cancelled_check_blocks():
    states = _green_checks()
    states["some-check"] = "CANCELLED"
    decision = decide_auto_merge(_authorized_context(check_states=states))
    assert decision.should_merge is False


def test_first_error_line_whitespace_only_is_safe():
    # Regression: "\n".strip().splitlines()[0] used to raise IndexError mid-pass.
    assert first_error_line("\n", "") == "merge failed"
    assert first_error_line("", "") == "merge failed"
    assert first_error_line("   ", "  ") == "merge failed"


def test_first_error_line_returns_first_line():
    assert first_error_line("boom\nmore detail", "") == "boom"
    assert first_error_line("", "stdout only") == "stdout only"
    assert first_error_line("stderr wins", "stdout loses") == "stderr wins"


def _status_row(state: str) -> dict[str, object]:
    """A commit *status* row: `context`/`state` shape, carrying no timestamps."""
    return {"context": "aragora-merge-quorum", "state": state}


def _quorum_row(conclusion: str, completed_at: str | None) -> dict[str, object]:
    return {
        "__typename": "CheckRun",
        "name": "aragora-merge-quorum",
        "conclusion": conclusion,
        "startedAt": completed_at,
        "completedAt": completed_at,
    }


def test_stale_success_after_current_failure_does_not_read_green():
    """A superseded SUCCESS ordered after the current FAILURE must not win.

    Observed live on PR #9571: the rollup carried
    [FAILURE @21:39 (current), SUCCESS @18:43 (stale draft-phase run)] in that
    order, so last-write-wins reported the quorum check green while the
    current run had in fact failed.
    """
    view = {
        "number": 9571,
        "headRefOid": "a" * 40,
        "statusCheckRollup": [
            _quorum_row("FAILURE", "2026-07-24T21:39:21Z"),
            _quorum_row("SUCCESS", "2026-07-24T18:43:02Z"),
        ],
    }
    ctx = context_from_gh(view, {"tier": 2})
    assert ctx.check_states["aragora-merge-quorum"] == "FAILURE"


def test_rerun_success_after_earlier_failure_reads_green():
    """The legitimate rerun case must still resolve to SUCCESS.

    Guards against over-correcting into "any failure wins", which would block
    every PR whose check was rerun to green (common after cancelled runs).
    """
    view = {
        "number": 1,
        "headRefOid": "a" * 40,
        "statusCheckRollup": [
            _quorum_row("FAILURE", "2026-07-24T18:00:00Z"),
            _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
        ],
    }
    ctx = context_from_gh(view, {"tier": 2})
    assert ctx.check_states["aragora-merge-quorum"] == "SUCCESS"


def test_rollup_reduction_is_order_independent():
    """Same rows, either order, same verdict — order must not decide merges."""
    rows = [
        _quorum_row("FAILURE", "2026-07-24T21:39:21Z"),
        _quorum_row("SUCCESS", "2026-07-24T18:43:02Z"),
    ]
    forward = context_from_gh({"statusCheckRollup": rows}, {"tier": 2})
    reverse = context_from_gh({"statusCheckRollup": list(reversed(rows))}, {"tier": 2})
    assert forward.check_states == reverse.check_states


def test_untimestamped_rows_fail_closed():
    """Without timestamps a success cannot be proven current, so failure wins."""
    view = {
        "statusCheckRollup": [
            {"name": "aragora-merge-quorum", "conclusion": "SUCCESS"},
            _quorum_row("FAILURE", None),
        ]
    }
    assert context_from_gh(view, {"tier": 2}).check_states["aragora-merge-quorum"] == "FAILURE"
    # ...and the reverse order agrees.
    view["statusCheckRollup"].reverse()
    assert context_from_gh(view, {"tier": 2}).check_states["aragora-merge-quorum"] == "FAILURE"


def test_stale_success_blocks_the_actual_merge_decision():
    """End-to-end: the stale-success rollup must not authorise a merge."""
    states = _green_checks()
    ctx = _authorized_context(check_states=states)
    stale = context_from_gh(
        {
            "statusCheckRollup": [
                _quorum_row("FAILURE", "2026-07-24T21:39:21Z"),
                _quorum_row("SUCCESS", "2026-07-24T18:43:02Z"),
            ]
        },
        {"tier": 2},
    )
    merged_states = dict(states)
    merged_states["aragora-merge-quorum"] = stale.check_states["aragora-merge-quorum"]
    decision = decide_auto_merge(dataclasses.replace(ctx, check_states=merged_states))
    assert decision.should_merge is False


def test_in_flight_current_run_outranks_stale_completed_success():
    """A re-run still in flight must not lose to a stale completed SUCCESS.

    Regression on the first attempt at this fix: ranking on ``completedAt``
    first put an in-progress row (which has none) *below* an older finished
    row, so a stale SUCCESS won and the merge read as green while the current
    quorum run was still deciding.
    """
    view = {
        "statusCheckRollup": [
            {
                "name": "aragora-merge-quorum",
                "status": "IN_PROGRESS",
                "conclusion": None,
                "startedAt": "2026-07-24T22:00:00Z",
                "completedAt": None,
            },
            _quorum_row("SUCCESS", "2026-07-24T18:43:02Z"),
        ]
    }
    assert context_from_gh(view, {"tier": 2}).check_states["aragora-merge-quorum"] != "SUCCESS"


def test_completed_rerun_still_beats_older_in_flight_row():
    """Ordering by start time must not flip the legitimate rerun case."""
    view = {
        "statusCheckRollup": [
            {
                "name": "aragora-merge-quorum",
                "status": "IN_PROGRESS",
                "conclusion": None,
                "startedAt": "2026-07-24T18:00:00Z",
                "completedAt": None,
            },
            _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
        ]
    }
    assert context_from_gh(view, {"tier": 2}).check_states["aragora-merge-quorum"] == "SUCCESS"


@pytest.mark.parametrize("blocking", ["PENDING", "QUEUED", "IN_PROGRESS", ""])
def test_untimestamped_success_loses_to_any_non_success(blocking):
    """An unrankable SUCCESS must not beat *any* non-success row.

    Review finding: the first tie-break only preferred explicitly failing
    states, so PENDING/QUEUED/IN_PROGRESS/unknown could still lose to an
    untimestamped SUCCESS purely on input order.
    """
    rows = [
        {"name": "aragora-merge-quorum", "conclusion": "SUCCESS"},
        {"name": "aragora-merge-quorum", "status": blocking, "conclusion": None},
    ]
    assert (
        context_from_gh({"statusCheckRollup": rows}, {"tier": 2}).check_states[
            "aragora-merge-quorum"
        ]
        != "SUCCESS"
    )
    assert (
        context_from_gh({"statusCheckRollup": list(reversed(rows))}, {"tier": 2}).check_states[
            "aragora-merge-quorum"
        ]
        != "SUCCESS"
    )


def test_rollup_states_are_case_normalised():
    """Lower-cased states must not slip past the reduction or the decision."""
    rows = [
        {"name": "aragora-merge-quorum", "conclusion": "success"},
        {"name": "aragora-merge-quorum", "conclusion": "failure"},
    ]
    states = context_from_gh({"statusCheckRollup": rows}, {"tier": 2}).check_states
    assert states["aragora-merge-quorum"] == "FAILURE"


def test_untimestamped_failure_beats_timestamped_success():
    """An untimestamped row is unrankable, not merely "oldest".

    Residual gap after the first recency fix, flagged in review of #9571:
    commit *statuses* (the context/state shape) carry neither startedAt nor
    completedAt, so ("", "") compared as lowest and a timestamped stale SUCCESS
    outranked an untimestamped FAILURE.
    """
    rows = [
        _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
        _quorum_row("FAILURE", None),
    ]
    for ordering in (rows, list(reversed(rows))):
        states = context_from_gh({"statusCheckRollup": ordering}, {"tier": 2}).check_states
        assert states["aragora-merge-quorum"] == "FAILURE"


def test_commit_status_shape_without_timestamps_is_unrankable():
    """The real shape that triggers it: a `context`/`state` commit status."""
    rows = [
        _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
        _status_row("PENDING"),
    ]
    states = context_from_gh({"statusCheckRollup": rows}, {"tier": 2}).check_states
    assert states["aragora-merge-quorum"] != "SUCCESS"


def test_rankable_rerun_still_wins_after_unrankable_guard():
    """The guard must not regress the legitimate rerun-to-green case."""
    rows = [
        _quorum_row("FAILURE", "2026-07-24T18:00:00Z"),
        _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
    ]
    states = context_from_gh({"statusCheckRollup": rows}, {"tier": 2}).check_states
    assert states["aragora-merge-quorum"] == "SUCCESS"


def _reduced_over_all_orders(rows: list[dict[str, object]]) -> set[str]:
    """Reduce ``rows`` in EVERY input order; return the set of outcomes.

    Forward/reverse coverage is too weak: the dropped-veto P1 survived it because
    it needed a specific three-row interleave. A single-element result set is the
    order-independence property itself.
    """
    return {
        context_from_gh({"statusCheckRollup": list(order)}, {"tier": 2}).check_states[
            "aragora-merge-quorum"
        ]
        for order in itertools.permutations(rows)
    }


def test_unrankable_veto_survives_a_non_success_incumbent():
    """A still-deciding commit status must veto, whatever else is in the rollup.

    Review finding: an unrankable non-success landing on a *non-success*
    incumbent matched no branch and was silently dropped, after which a later
    rankable SUCCESS outranked the incumbent and the name read green while the
    commit status was still deciding.
    """
    rows = [
        _quorum_row("FAILURE", "2026-07-24T18:00:00Z"),
        _status_row("PENDING"),
        _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
    ]
    assert _reduced_over_all_orders(rows) == {"PENDING"}


def test_unrankable_veto_survives_a_success_incumbent():
    rows = [
        _quorum_row("SUCCESS", "2026-07-24T18:00:00Z"),
        _status_row("PENDING"),
        _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
    ]
    assert _reduced_over_all_orders(rows) == {"PENDING"}


def test_unrankable_success_never_blocks_a_rankable_verdict():
    """An unrankable SUCCESS may not outrank anything, nor suppress a real row.

    It previously sat in the single slot as an incumbent, keeping a rankable
    SUCCESS out and letting a stale FAILURE take the tie-break — so the same
    multiset reduced differently depending on order.
    """
    rows = [
        _quorum_row("SUCCESS", None),
        _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
        _quorum_row("FAILURE", "2026-07-24T18:00:00Z"),
    ]
    assert _reduced_over_all_orders(rows) == {"SUCCESS"}


def test_unrankable_and_rankable_non_success_agree_on_one_answer():
    """Two non-success rows must collapse to ONE answer, whatever the order.

    That answer is the terminal failure, not the transient veto: this test
    originally expected PENDING, which review showed masks the FAILURE from
    `decide_auto_merge`'s failing-check guard. Order-independence is the
    property under test; the precedence rule decides which state survives.
    """
    rows = [_status_row("PENDING"), _quorum_row("FAILURE", "2026-07-24T18:00:00Z")]
    assert _reduced_over_all_orders(rows) == {"FAILURE"}


def test_rerun_to_green_survives_the_veto_redesign():
    """The legitimate rerun case must stay green in every order."""
    rows = [
        _quorum_row("FAILURE", "2026-07-24T18:00:00Z"),
        _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
    ]
    assert _reduced_over_all_orders(rows) == {"SUCCESS"}


def test_equal_stamp_tie_then_a_genuinely_newer_success_is_green():
    rows = [
        _quorum_row("SUCCESS", "2026-07-24T18:00:00Z"),
        _quorum_row("FAILURE", "2026-07-24T18:00:00Z"),
        _quorum_row("SUCCESS", "2026-07-24T21:00:00Z"),
    ]
    assert _reduced_over_all_orders(rows) == {"SUCCESS"}


def test_transient_veto_never_masks_a_terminal_failure():
    """A PENDING must not replace a FAILURE — that disarms the failing-check guard.

    Review finding: `decide_auto_merge` blocks non-required checks on
    `_FAILING_CHECK_STATES`, which excludes PENDING/QUEUED. Collapsing a
    timestamped FAILURE CheckRun and an untimestamped PENDING commit status
    (the dual-transport shape) into PENDING therefore silently un-blocked a
    genuinely failing check.
    """
    rows = [_quorum_row("FAILURE", "2026-07-27T18:00:00Z"), _status_row("PENDING")]
    assert _reduced_over_all_orders(rows) == {"FAILURE"}


def test_veto_still_blocks_a_success_it_cannot_be_proven_staler_than():
    """Precedence must not weaken the veto itself."""
    rows = [_quorum_row("SUCCESS", "2026-07-27T21:00:00Z"), _status_row("PENDING")]
    assert _reduced_over_all_orders(rows) == {"PENDING"}


def test_completed_at_only_row_is_unrankable():
    """Ordering is startedAt-primary, so a completedAt-only row cannot be ranked.

    Otherwise it compares as ("", completedAt) and sorts below every
    startedAt-bearing row whatever the real times — re-admitting the original
    stale-outranks-current hazard for that shape.
    """
    rows = [
        {
            "name": "aragora-merge-quorum",
            "conclusion": "FAILURE",
            "completedAt": "2026-07-27T19:00:00Z",
        },
        _quorum_row("SUCCESS", "2026-07-27T21:00:00Z"),
    ]
    assert _reduced_over_all_orders(rows) == {"FAILURE"}


def test_equal_stamp_transient_and_terminal_resolve_to_the_terminal():
    """Neither is provably live, so keep the more decision-relevant one."""
    rows = [
        _quorum_row("PENDING", "2026-07-27T18:00:00Z"),
        _quorum_row("FAILURE", "2026-07-27T18:00:00Z"),
    ]
    assert _reduced_over_all_orders(rows) == {"FAILURE"}
