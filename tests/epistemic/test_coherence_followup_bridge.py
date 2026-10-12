"""Integration tests: DIC-26 coherence monitor → DIC-17 follow-up bridge.

Verifies:
- propose_followup_for_coherence_issue() only proposes for error severity
- Source kind is 'coherence_issue'; boss-ready label excluded
- Source key is stable and deterministic (dedup guarantee)
- scan_coherence(emit_followup_proposals=False) never populates proposals
- scan_coherence(emit_followup_proposals=True) populates proposals only
  when ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED is set
- Only error-severity issues produce proposals; warnings are skipped

Gating: both ARAGORA_COHERENCE_MONITOR_ENABLED and
ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED must be set for proposals to flow.
Default is OFF; live queue is unaffected.

Advances: #6220 (DIC-26 Belief Coherence Monitor)
"""

from __future__ import annotations

import pytest

from aragora.epistemic.coherence import (
    BeliefEntry,
    CoherenceIssue,
    IncoherenceKind,
    scan_coherence,
)
from aragora.epistemic.followup import (
    FollowupProposal,
    propose_followup_for_coherence_issue,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _error_contradiction() -> CoherenceIssue:
    return CoherenceIssue(
        kind=IncoherenceKind.CONTRADICTION,
        belief_ids=("b1", "b2"),
        detail="Subject 'rate-limiter': high [b1(0.95)] contradicts low [b2(0.05)].",
        severity="error",
    )


def _warning_conflict() -> CoherenceIssue:
    return CoherenceIssue(
        kind=IncoherenceKind.EVIDENCE_CONFLICT,
        belief_ids=("b3", "b4"),
        detail="Evidence 'docs/status/B0.md' cited by 2 beliefs with conflicting outcomes.",
        severity="warning",
    )


def _error_rot() -> CoherenceIssue:
    return CoherenceIssue(
        kind=IncoherenceKind.CONFIDENCE_ROT,
        belief_ids=("b5",),
        detail="Belief 'b5' confidence 0.05 below minimum 0.30.",
        severity="error",
    )


# ---------------------------------------------------------------------------
# propose_followup_for_coherence_issue unit tests
# ---------------------------------------------------------------------------


class TestProposeFollowupForCoherenceIssue:
    def test_error_severity_returns_proposal(self) -> None:
        proposal = propose_followup_for_coherence_issue(_error_contradiction())
        assert isinstance(proposal, FollowupProposal)

    def test_warning_severity_returns_none(self) -> None:
        assert propose_followup_for_coherence_issue(_warning_conflict()) is None

    def test_source_kind_is_coherence_issue(self) -> None:
        proposal = propose_followup_for_coherence_issue(_error_contradiction())
        assert proposal is not None
        assert proposal.source_kind == "coherence_issue"

    def test_no_boss_ready_label(self) -> None:
        """Queue-governance invariant: boss-ready must never appear."""
        proposal = propose_followup_for_coherence_issue(_error_contradiction())
        assert proposal is not None
        assert "boss-ready" not in proposal.labels

    def test_epistemic_and_coherence_labels_present(self) -> None:
        proposal = propose_followup_for_coherence_issue(_error_rot())
        assert proposal is not None
        assert "epistemic" in proposal.labels
        assert "coherence" in proposal.labels

    def test_source_key_is_stable_and_deterministic(self) -> None:
        issue = _error_contradiction()
        key1 = propose_followup_for_coherence_issue(issue)
        key2 = propose_followup_for_coherence_issue(issue)
        assert key1 is not None and key2 is not None
        assert key1.source_key == key2.source_key

    def test_source_key_differs_for_different_issues(self) -> None:
        p1 = propose_followup_for_coherence_issue(_error_contradiction())
        p2 = propose_followup_for_coherence_issue(_error_rot())
        assert p1 is not None and p2 is not None
        assert p1.source_key != p2.source_key

    def test_provenance_contains_kind_and_belief_ids(self) -> None:
        proposal = propose_followup_for_coherence_issue(_error_contradiction())
        assert proposal is not None
        assert proposal.provenance["kind"] == "contradiction"
        assert set(proposal.provenance["belief_ids"]) == {"b1", "b2"}

    def test_extra_labels_included_but_not_boss_ready(self) -> None:
        proposal = propose_followup_for_coherence_issue(
            _error_contradiction(), extra_labels=("vision-layer",)
        )
        assert proposal is not None
        assert "vision-layer" in proposal.labels
        assert "boss-ready" not in proposal.labels

    def test_title_truncated_to_140_chars(self) -> None:
        long_issue = CoherenceIssue(
            kind=IncoherenceKind.CONTRADICTION,
            belief_ids=tuple(f"belief_{i}" for i in range(20)),
            detail="Very long detail string.",
            severity="error",
        )
        proposal = propose_followup_for_coherence_issue(long_issue)
        assert proposal is not None
        assert len(proposal.title) <= 140


# ---------------------------------------------------------------------------
# scan_coherence integration tests
# ---------------------------------------------------------------------------


_CONTRADICTING_ENTRIES = [
    BeliefEntry("b1", "rate-limiter", 0.95, "pass"),
    BeliefEntry("b2", "rate-limiter", 0.04, "fail"),
]
_WARNING_ENTRIES = [
    BeliefEntry("b3", "auth-pass", 0.40, "pass", evidence_paths=("docs/auth.md",)),
    BeliefEntry("b4", "auth-fail", 0.60, "fail", evidence_paths=("docs/auth.md",)),
]


class TestScanCoherenceFollowupIntegration:
    def test_default_no_proposals_even_with_error_issues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """emit_followup_proposals defaults to False — proposals must be empty."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        report = scan_coherence(_CONTRADICTING_ENTRIES)
        assert report.proposals == []

    def test_emit_proposals_false_when_followup_flag_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with emit_followup_proposals=True, no proposals if followup flag off."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.delenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", raising=False)
        report = scan_coherence(_CONTRADICTING_ENTRIES, emit_followup_proposals=True)
        assert report.proposals == []

    def test_emit_proposals_when_both_flags_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With both flags + emit_followup_proposals=True, error issues generate proposals."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        report = scan_coherence(_CONTRADICTING_ENTRIES, emit_followup_proposals=True)
        assert len(report.proposals) >= 1
        for p in report.proposals:
            assert p.source_kind == "coherence_issue"
            assert "boss-ready" not in p.labels

    def test_warning_issues_produce_no_proposals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Warning-severity evidence conflicts must not generate proposals."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        # _WARNING_ENTRIES produce only evidence_conflict issues (severity=warning)
        report = scan_coherence(_WARNING_ENTRIES, emit_followup_proposals=True)
        assert report.proposals == []

    def test_proposals_absent_from_to_dict_when_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """to_dict() must not include 'proposals' key when proposals is empty."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.delenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", raising=False)
        report = scan_coherence(_CONTRADICTING_ENTRIES, emit_followup_proposals=True)
        assert "proposals" not in report.to_dict()

    def test_proposals_present_in_to_dict_when_non_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """to_dict() includes 'proposals' list when proposals were generated."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        report = scan_coherence(_CONTRADICTING_ENTRIES, emit_followup_proposals=True)
        if report.proposals:
            d = report.to_dict()
            assert "proposals" in d
            assert isinstance(d["proposals"], list)

    def test_to_dict_proposals_carry_every_proposal_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Serialized proposals keep title, body, labels and keys, not only provenance."""
        monkeypatch.setenv("ARAGORA_COHERENCE_MONITOR_ENABLED", "1")
        monkeypatch.setenv("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED", "1")
        report = scan_coherence(_CONTRADICTING_ENTRIES, emit_followup_proposals=True)
        assert report.proposals
        serialized = report.to_dict()["proposals"]
        assert len(serialized) == len(report.proposals)
        for entry, proposal in zip(serialized, report.proposals):
            assert entry == {
                "source_kind": proposal.source_kind,
                "source_key": proposal.source_key,
                "title": proposal.title,
                "body": proposal.body,
                "labels": list(proposal.labels),
                "rationale": proposal.rationale,
                "provenance": proposal.provenance,
            }
