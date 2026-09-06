"""Tests for the GitHub-event resolution adapter (AGT-04 sub-deliverable 2)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from aragora.prediction.github_event_resolver import (
    GitHubEventPayload,
    GitHubEventResolver,
    ResolutionResult,
)
from aragora.prediction.stakeable_claim import (
    InMemoryStakeableClaimStore,
    QuestionType,
    ResolutionStatus,
    StakeableClaim,
)

_FLAG = "ARAGORA_PREDICTION_MARKETS_ENABLED"
_NOW = datetime.now(tz=UTC)
_EVENT_TIME = _NOW.isoformat()
_FUTURE = (_NOW + timedelta(days=30)).isoformat()
_PAST = (_NOW - timedelta(days=1)).isoformat()
_BEFORE_PAST = (_NOW - timedelta(days=2)).isoformat()
_AFTER_EXPIRY = (_NOW + timedelta(days=31)).isoformat()


@pytest.fixture(autouse=True)
def enable_flag(monkeypatch):
    monkeypatch.setenv(_FLAG, "1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _open_claim(
    claim_id: str = "c1",
    question_type: QuestionType = QuestionType.PR_MERGE,
    target_ref: str = "owner/repo#42",
) -> StakeableClaim:
    return StakeableClaim(
        claim_id=claim_id,
        question=f"Will {target_ref} happen?",
        question_type=question_type,
        target_ref=target_ref,
        expiry=_FUTURE,
    )


# ---------------------------------------------------------------------------
# can_resolve
# ---------------------------------------------------------------------------


class TestCanResolve:
    def test_pr_merge_event_matches(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE, target_ref="a/b#1")
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#1",
            occurred_at=_EVENT_TIME,
            merged=True,
        )
        assert r.can_resolve(claim, event)

    def test_can_resolve_without_event_matches_legacy_adapter_surface(self):
        r = GitHubEventResolver()
        assert r.can_resolve(_open_claim(question_type=QuestionType.PR_MERGE))
        assert r.can_resolve(_open_claim(question_type=QuestionType.ISSUE_CLOSE))
        assert r.can_resolve(_open_claim(question_type=QuestionType.CI_PASS))
        assert not r.can_resolve(_open_claim(question_type=QuestionType.DEPENDENCY_RELEASE))

    def test_target_ref_mismatch_returns_false(self):
        r = GitHubEventResolver()
        claim = _open_claim(target_ref="a/b#1")
        event = GitHubEventPayload(event_type="pull_request", action="closed", target_ref="a/b#99")
        assert not r.can_resolve(claim, event)

    def test_wrong_event_type_returns_false(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE)
        event = GitHubEventPayload(
            event_type="issues", action="closed", target_ref=claim.target_ref
        )
        assert not r.can_resolve(claim, event)

    def test_issue_close_event_matches(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.ISSUE_CLOSE, target_ref="a/b#7")
        event = GitHubEventPayload(event_type="issues", action="closed", target_ref="a/b#7")
        assert r.can_resolve(claim, event)

    def test_ci_pass_check_run_matches(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="a/b#5")
        event = GitHubEventPayload(
            event_type="check_run",
            action="completed",
            target_ref="a/b#5",
            occurred_at=_EVENT_TIME,
            conclusion="success",
        )
        assert r.can_resolve(claim, event)

    def test_workflow_run_matches_ci_pass(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="a/b#5")
        event = GitHubEventPayload(
            event_type="workflow_run",
            action="completed",
            target_ref="a/b#5",
            occurred_at=_EVENT_TIME,
            conclusion="success",
        )
        assert r.can_resolve(claim, event)

    def test_can_resolve_is_case_insensitive(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE, target_ref="Owner/Repo#42")
        event = GitHubEventPayload(
            event_type="pull_request", action="closed", target_ref="owner/repo#42"
        )
        assert r.can_resolve(claim, event)

    def test_can_resolve_strips_whitespace(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE, target_ref="owner/repo#42")
        event = GitHubEventPayload(
            event_type="pull_request", action="closed", target_ref="  owner/repo#42  "
        )
        assert r.can_resolve(claim, event)

    def test_mixed_case_owner_repo_with_branch_ref_resolves(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="Owner/Repo@main")
        event = GitHubEventPayload(
            event_type="check_run", action="completed", target_ref="owner/repo@main"
        )
        assert r.can_resolve(claim, event)

    def test_format_variant_same_target_resolves(self):
        # Same target, different formatting: casing + whitespace around
        # the separator normalize to the canonical owner/repo#N form.
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE, target_ref="Owner/Repo #42")
        event = GitHubEventPayload(
            event_type="pull_request", action="closed", target_ref=" owner/repo# 42"
        )
        assert r.can_resolve(claim, event)

    def test_branch_ref_case_is_preserved(self):
        # git refs are case-sensitive: only owner/repo is case-folded,
        # so branch names differing in case are genuinely different targets.
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="owner/repo@Feature")
        event = GitHubEventPayload(
            event_type="check_run", action="completed", target_ref="owner/repo@feature"
        )
        assert not r.can_resolve(claim, event)

    def test_genuinely_different_targets_do_not_resolve(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE, target_ref="owner/repo#42")
        event = GitHubEventPayload(
            event_type="pull_request", action="closed", target_ref="owner/repo#43"
        )
        assert not r.can_resolve(claim, event)

    def test_unsupported_question_type_returns_false(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.DEPENDENCY_RELEASE)
        event = GitHubEventPayload(
            event_type="release", action="published", target_ref=claim.target_ref
        )
        assert not r.can_resolve(claim, event)


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_resolve_raises_when_flag_off(self, monkeypatch):
        monkeypatch.delenv(_FLAG, raising=False)
        r = GitHubEventResolver()
        claim = _open_claim()
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref=claim.target_ref,
            occurred_at=_EVENT_TIME,
            merged=True,
        )
        with pytest.raises(RuntimeError, match="Prediction markets are disabled"):
            r.resolve_from_event(claim, event)

    def test_can_resolve_does_not_require_flag(self, monkeypatch):
        monkeypatch.delenv(_FLAG, raising=False)
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE, target_ref="a/b#1")
        event = GitHubEventPayload(event_type="pull_request", action="closed", target_ref="a/b#1")
        # can_resolve is pure logic — must not raise
        assert r.can_resolve(claim, event)


# ---------------------------------------------------------------------------
# PR merge resolution
# ---------------------------------------------------------------------------


class TestPRMergeResolution:
    def test_merged_pr_resolves_yes(self):
        r = GitHubEventResolver()
        claim = _open_claim(target_ref="a/b#10")
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#10",
            occurred_at=_EVENT_TIME,
            merged=True,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True
        assert result.resolution_value is True
        assert "merged" in result.evidence

    def test_closed_without_merge_before_expiry_waits(self):
        r = GitHubEventResolver()
        claim = _open_claim(target_ref="a/b#11")
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#11",
            occurred_at=_EVENT_TIME,
            merged=False,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert result.resolution_value is False
        # Wording updated in 332c8130 (names expiry as the expected outcome).
        assert "reopened before expiry" in result.evidence

    def test_opened_action_not_terminal(self):
        r = GitHubEventResolver()
        claim = _open_claim(target_ref="a/b#12")
        event = GitHubEventPayload(
            event_type="pull_request",
            action="opened",
            target_ref="a/b#12",
            occurred_at=_EVENT_TIME,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False

    def test_already_resolved_claim_skipped(self):
        r = GitHubEventResolver()
        claim = StakeableClaim(
            claim_id="x1",
            question="?",
            question_type=QuestionType.PR_MERGE,
            target_ref="a/b#1",
            expiry=_FUTURE,
            resolution_status=ResolutionStatus.RESOLVED_YES,
            resolution_value=True,
        )
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#1",
            occurred_at=_EVENT_TIME,
            merged=True,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert "already" in result.evidence

    def test_target_ref_mismatch_not_resolved(self):
        r = GitHubEventResolver()
        claim = _open_claim(target_ref="a/b#1")
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#999",
            occurred_at=_EVENT_TIME,
            merged=True,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False

    def test_event_after_expiry_does_not_resolve(self):
        r = GitHubEventResolver()
        claim = StakeableClaim(
            claim_id="expired-pr",
            question="Will a/b#13 merge?",
            question_type=QuestionType.PR_MERGE,
            target_ref="a/b#13",
            expiry=_FUTURE,
        )
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#13",
            occurred_at=_AFTER_EXPIRY,
            merged=True,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert "after claim expiry" in result.evidence

    def test_historical_in_window_event_resolves_open_claim(self):
        # CONTRACT CHANGE (adjudicated, PR #8519 — operator-requested design
        # adjudication comment): expiry is gated on EVENT time, not wall-clock
        # processing time.  "Truth is determined by event-time; finality is
        # determined by processing-time."  This test previously characterized
        # the claims-made model (test_already_expired_claim_does_not_resolve_
        # from_historical_event) and asserted that an event occurring BEFORE
        # the (now-past) expiry left the claim unresolved.  Under the
        # adjudicated occurrence model, an in-window event resolves a claim
        # that is still OPEN, even when processed after wall-clock expiry
        # (webhook lag/redelivery).  Processing-time finality is enforced by
        # the store sweeper's grace window (expire_stale), not the resolver.
        r = GitHubEventResolver()
        claim = StakeableClaim(
            claim_id="stale-pr",
            question="Will a/b#15 merge?",
            question_type=QuestionType.PR_MERGE,
            target_ref="a/b#15",
            expiry=_PAST,
        )
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#15",
            occurred_at=_BEFORE_PAST,
            merged=True,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True
        assert result.resolution_value is True
        assert "merged" in result.evidence

    def test_missing_event_timestamp_does_not_resolve(self):
        r = GitHubEventResolver()
        claim = _open_claim(target_ref="a/b#14")
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#14",
            merged=True,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert "timestamp is missing" in result.evidence


# ---------------------------------------------------------------------------
# Issue close resolution
# ---------------------------------------------------------------------------


class TestIssueCloseResolution:
    def test_issue_closed_resolves_yes(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.ISSUE_CLOSE, target_ref="x/y#3")
        event = GitHubEventPayload(
            event_type="issues",
            action="closed",
            target_ref="x/y#3",
            occurred_at=_EVENT_TIME,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True
        assert result.resolution_value is True
        assert "closed" in result.evidence

    def test_issue_reopened_not_terminal(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.ISSUE_CLOSE, target_ref="x/y#4")
        event = GitHubEventPayload(
            event_type="issues",
            action="reopened",
            target_ref="x/y#4",
            occurred_at=_EVENT_TIME,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False

    def test_issue_labeled_not_terminal(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.ISSUE_CLOSE, target_ref="x/y#5")
        event = GitHubEventPayload(
            event_type="issues",
            action="labeled",
            target_ref="x/y#5",
            occurred_at=_EVENT_TIME,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False

    def test_issue_closed_not_planned_does_not_resolve_yes(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.ISSUE_CLOSE, target_ref="x/y#6")
        event = GitHubEventPayload(
            event_type="issues",
            action="closed",
            target_ref="x/y#6",
            occurred_at=_EVENT_TIME,
            raw={"state_reason": "not_planned"},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert result.resolution_value is False
        assert "not_planned" in result.evidence

    def test_issue_closed_not_planned_nested_payload_does_not_resolve_yes(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.ISSUE_CLOSE, target_ref="x/y#7")
        event = GitHubEventPayload(
            event_type="issues",
            action="closed",
            target_ref="x/y#7",
            occurred_at=_EVENT_TIME,
            raw={"issue": {"state_reason": "not_planned"}},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert result.resolution_value is False
        assert "not_planned" in result.evidence


# ---------------------------------------------------------------------------
# CI pass resolution
# ---------------------------------------------------------------------------


class TestCIPassResolution:
    def test_check_run_success_resolves_yes(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="p/q#5")
        event = GitHubEventPayload(
            event_type="check_run",
            action="completed",
            target_ref="p/q#5",
            occurred_at=_EVENT_TIME,
            conclusion="success",
            raw={"aggregate": True, "run_attempt": 1},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True
        assert result.resolution_value is True
        assert "pass" in result.evidence

    def test_check_run_failure_resolves_no(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="p/q#6")
        event = GitHubEventPayload(
            event_type="check_run",
            action="completed",
            target_ref="p/q#6",
            occurred_at=_EVENT_TIME,
            conclusion="failure",
            raw={"aggregate": True, "run_attempt": 1},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True
        assert result.resolution_value is False
        assert "fail" in result.evidence

    def test_workflow_run_success_resolves_yes(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="p/q#7")
        event = GitHubEventPayload(
            event_type="workflow_run",
            action="completed",
            target_ref="p/q#7",
            occurred_at=_EVENT_TIME,
            conclusion="success",
            raw={"aggregate": True, "run_attempt": 1},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True
        assert result.resolution_value is True

    def test_check_run_queued_not_terminal(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="p/q#8")
        event = GitHubEventPayload(
            event_type="check_run",
            action="queued",
            target_ref="p/q#8",
            occurred_at=_EVENT_TIME,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False

    def test_check_run_cancelled_resolves_no(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="p/q#9")
        event = GitHubEventPayload(
            event_type="check_run",
            action="completed",
            target_ref="p/q#9",
            occurred_at=_EVENT_TIME,
            conclusion="cancelled",
            raw={"aggregate": True, "run_attempt": 1},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True
        assert result.resolution_value is False

    def test_single_check_run_without_aggregate_marker_waits(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="p/q#10")
        event = GitHubEventPayload(
            event_type="check_run",
            action="completed",
            target_ref="p/q#10",
            occurred_at=_EVENT_TIME,
            conclusion="success",
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert "aggregate=True" in result.evidence

    def test_truthy_aggregate_marker_does_not_resolve_ci_claim(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="p/q#13")
        event = GitHubEventPayload(
            event_type="check_run",
            action="completed",
            target_ref="p/q#13",
            occurred_at=_EVENT_TIME,
            conclusion="success",
            raw={"aggregate": "true", "run_attempt": 1},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert result.resolution_value is False
        assert "aggregate=True" in result.evidence

    def test_rerun_ci_event_does_not_resolve_first_run_claim(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="p/q#11")
        event = GitHubEventPayload(
            event_type="workflow_run",
            action="completed",
            target_ref="p/q#11",
            occurred_at=_EVENT_TIME,
            conclusion="success",
            raw={"aggregate": True, "run_attempt": 2},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert "run_attempt=2" in result.evidence

    def test_ci_event_after_expiry_does_not_resolve(self):
        r = GitHubEventResolver()
        claim = StakeableClaim(
            claim_id="expired-ci",
            question="Will p/q#12 pass?",
            question_type=QuestionType.CI_PASS,
            target_ref="p/q#12",
            expiry=_FUTURE,
        )
        event = GitHubEventPayload(
            event_type="workflow_run",
            action="completed",
            target_ref="p/q#12",
            occurred_at=_AFTER_EXPIRY,
            conclusion="success",
            raw={"aggregate": True, "run_attempt": 1},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert "after claim expiry" in result.evidence


# ---------------------------------------------------------------------------
# End-to-end: resolver + store
# ---------------------------------------------------------------------------


class TestResolverWithStore:
    def test_full_roundtrip_merge(self):
        r = GitHubEventResolver()
        store = InMemoryStakeableClaimStore()
        claim = _open_claim(claim_id="e2e-1", target_ref="a/b#99")
        store.add(claim)

        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#99",
            occurred_at=_EVENT_TIME,
            merged=True,
        )
        result = r.resolve_from_event(store.get("e2e-1"), event)
        assert result.resolved
        store.resolve("e2e-1", result.resolution_value, result.evidence)
        resolved = store.get("e2e-1")
        assert resolved.resolution_status == ResolutionStatus.RESOLVED_YES
        assert resolved.resolution_value is True

    def test_full_roundtrip_ci_fail(self):
        r = GitHubEventResolver()
        store = InMemoryStakeableClaimStore()
        claim = _open_claim(
            claim_id="e2e-2",
            question_type=QuestionType.CI_PASS,
            target_ref="a/b#100",
        )
        store.add(claim)

        event = GitHubEventPayload(
            event_type="check_run",
            action="completed",
            target_ref="a/b#100",
            occurred_at=_EVENT_TIME,
            conclusion="failure",
            raw={"aggregate": True, "run_attempt": 1},
        )
        result = r.resolve_from_event(store.get("e2e-2"), event)
        assert result.resolved
        store.resolve("e2e-2", result.resolution_value, result.evidence)
        resolved = store.get("e2e-2")
        assert resolved.resolution_status == ResolutionStatus.RESOLVED_NO
        assert resolved.resolution_value is False


# ---------------------------------------------------------------------------
# Event-time resolution with finality guards (adjudicated design, PR #8519)
# ---------------------------------------------------------------------------


class TestEventTimeResolution:
    """Truth by event-time; finality by processing-time (PR #8519 adjudication)."""

    def test_in_window_event_processed_late_resolves(self):
        # Webhook lag/redelivery: the merge occurred inside the claim window,
        # but delivery is processed hours after wall-clock expiry — resolves.
        r = GitHubEventResolver()
        claim = StakeableClaim(
            claim_id="late-delivery",
            question="Will a/b#20 merge?",
            question_type=QuestionType.PR_MERGE,
            target_ref="a/b#20",
            expiry=(_NOW - timedelta(hours=2)).isoformat(),
        )
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#20",
            occurred_at=(_NOW - timedelta(hours=3)).isoformat(),
            merged=True,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True
        assert result.resolution_value is True

    def test_out_of_window_event_does_not_resolve_past_expiry_claim(self):
        # Event occurred AFTER the (already past) expiry — non-qualifying.
        r = GitHubEventResolver()
        claim = StakeableClaim(
            claim_id="out-of-window",
            question="Will a/b#21 merge?",
            question_type=QuestionType.PR_MERGE,
            target_ref="a/b#21",
            expiry=(_NOW - timedelta(hours=3)).isoformat(),
        )
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#21",
            occurred_at=(_NOW - timedelta(hours=1)).isoformat(),
            merged=True,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert "after claim expiry" in result.evidence

    def test_late_evidence_for_expired_claim_logs_side_output(self, caplog):
        # Late evidence for an already-voided claim is an auditable
        # side-output: structured warning, no raise, no resurrection.
        r = GitHubEventResolver()
        claim = StakeableClaim(
            claim_id="voided-1",
            question="Will a/b#22 merge?",
            question_type=QuestionType.PR_MERGE,
            target_ref="a/b#22",
            expiry=_PAST,
            resolution_status=ResolutionStatus.EXPIRED,
        )
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#22",
            occurred_at=_BEFORE_PAST,
            merged=True,
        )
        with caplog.at_level(logging.WARNING, logger="aragora.prediction.github_event_resolver"):
            result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert claim.resolution_status == ResolutionStatus.EXPIRED
        assert any(
            "prediction.late_event" in rec.message and "voided-1" in rec.getMessage()
            for rec in caplog.records
        )


class TestSweeperGraceWindow:
    """expire_stale voids only past expiry + grace (default 24h)."""

    def test_sweeper_honors_default_grace(self):
        store = InMemoryStakeableClaimStore()
        recently = _open_claim(claim_id="recently-expired")
        recently.expiry = (_NOW - timedelta(hours=1)).isoformat()
        long_past = _open_claim(claim_id="long-expired")
        long_past.expiry = (_NOW - timedelta(hours=25)).isoformat()
        store.add(recently)
        store.add(long_past)

        expired = store.expire_stale()
        # Within grace: still OPEN so a late-delivered in-window event can resolve.
        assert "recently-expired" not in expired
        assert store.get("recently-expired").resolution_status == ResolutionStatus.OPEN
        # Past expiry + grace: voided.
        assert "long-expired" in expired
        assert store.get("long-expired").resolution_status == ResolutionStatus.EXPIRED

    def test_sweeper_grace_accepts_seconds(self):
        store = InMemoryStakeableClaimStore()
        claim = _open_claim(claim_id="secs-grace")
        claim.expiry = (_NOW - timedelta(hours=1)).isoformat()
        store.add(claim)
        assert store.expire_stale(grace=7200) == []  # 2h grace: still open
        assert store.expire_stale(grace=0) == ["secs-grace"]  # no grace: voided


class TestSettlementRaces:
    """Resolver settles only OPEN; sweeper voids only OPEN — loser no-ops."""

    def test_resolve_then_sweep_noops_sweeper(self):
        store = InMemoryStakeableClaimStore()
        claim = _open_claim(claim_id="race-1", target_ref="a/b#30")
        claim.expiry = (_NOW - timedelta(hours=1)).isoformat()
        store.add(claim)

        r = GitHubEventResolver()
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#30",
            occurred_at=(_NOW - timedelta(hours=2)).isoformat(),
            merged=True,
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved
        store.resolve("race-1", result.resolution_value, result.evidence)

        # Sweeper runs after settlement: must no-op, never overwrite.
        assert store.expire_stale(grace=0) == []
        assert store.get("race-1").resolution_status == ResolutionStatus.RESOLVED_YES
        assert store.get("race-1").resolution_value is True

    def test_sweep_then_resolve_noops_resolver(self):
        store = InMemoryStakeableClaimStore()
        claim = _open_claim(claim_id="race-2", target_ref="a/b#31")
        claim.expiry = (_NOW - timedelta(hours=25)).isoformat()
        store.add(claim)

        assert store.expire_stale() == ["race-2"]
        assert store.get("race-2").resolution_status == ResolutionStatus.EXPIRED

        # Resolver sees the settled claim: side-output only, no resurrection.
        r = GitHubEventResolver()
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#31",
            occurred_at=(_NOW - timedelta(hours=26)).isoformat(),
            merged=True,
        )
        result = r.resolve_from_event(store.get("race-2"), event)
        assert result.resolved is False
        assert "already expired" in result.evidence
        # Store-level CAS guard: attempting to settle raises, state intact.
        with pytest.raises(ValueError, match="already"):
            store.resolve("race-2", True, "late")
        assert store.get("race-2").resolution_status == ResolutionStatus.EXPIRED
        assert store.get("race-2").resolution_value is None


class TestTerminalTimestampAllowlist:
    """#8777: only terminal-action timestamps may stand in for occurred_at."""

    def test_created_at_cannot_backdate_terminal_event(self):
        # created_at predates the terminal action (it is the open time); a
        # payload carrying only created_at must fail closed, not resolve.
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE, target_ref="a/b#41")
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#41",
            merged=True,
            raw={"created_at": _NOW.isoformat()},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert "timestamp is missing or invalid" in result.evidence

    def test_updated_at_cannot_backdate_terminal_event(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE, target_ref="a/b#42")
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#42",
            merged=True,
            raw={"updated_at": _NOW.isoformat()},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False

    def test_merged_at_is_accepted_terminal_timestamp(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.PR_MERGE, target_ref="a/b#43")
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#43",
            merged=True,
            raw={"merged_at": _NOW.isoformat()},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True
        assert result.resolution_value is True

    def test_terminal_timestamp_overrides_backdated_occurred_at(self):
        r = GitHubEventResolver()
        claim = StakeableClaim(
            claim_id="terminal-wins",
            question="Will a/b#44 merge?",
            question_type=QuestionType.PR_MERGE,
            target_ref="a/b#44",
            expiry=_NOW.isoformat(),
        )
        event = GitHubEventPayload(
            event_type="pull_request",
            action="closed",
            target_ref="a/b#44",
            occurred_at=(_NOW - timedelta(hours=1)).isoformat(),
            merged=True,
            raw={"merged_at": (_NOW + timedelta(hours=1)).isoformat()},
        )

        result = r.resolve_from_event(claim, event)

        assert result.resolved is False
        assert "after claim expiry" in result.evidence

    def test_completed_at_accepted_for_ci(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="a/b@main")
        event = GitHubEventPayload(
            event_type="workflow_run",
            action="completed",
            target_ref="a/b@main",
            conclusion="success",
            raw={"completed_at": _NOW.isoformat(), "aggregate": True, "run_attempt": 1},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is True


class TestRunAttemptFailClosed:
    """#8777: missing run_attempt metadata must never be assumed first-run."""

    def test_missing_run_attempt_fails_closed(self):
        r = GitHubEventResolver()
        claim = _open_claim(question_type=QuestionType.CI_PASS, target_ref="a/b@main")
        event = GitHubEventPayload(
            event_type="workflow_run",
            action="completed",
            target_ref="a/b@main",
            occurred_at=_NOW.isoformat(),
            conclusion="success",
            raw={"aggregate": True},
        )
        result = r.resolve_from_event(claim, event)
        assert result.resolved is False
        assert "lacks run_attempt" in result.evidence


class TestAdapterCompatibility:
    def test_resolve_method_exists_and_fails_closed_without_event(self):
        r = GitHubEventResolver()
        with pytest.raises(NotImplementedError, match="resolve_from_event"):
            r.resolve(_open_claim())
