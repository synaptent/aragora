"""Entry-level merge-packet output fields.

Covers the additive ``non_admin_merge_eligible`` field (the #9858 drafting-rule
triple: model-quorum satisfied + all effective REQUIRED contexts green + zero
unresolved dissent + tier settlement recorded where required, independent of
admin-squash-lane live-gate state) and the noop-placeholder labeling on the
``already_merged`` entry (tier 0 / empty counted families are placeholders, not
computed values). Existing fields must keep their exact shapes.
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora.cli.commands.review_queue import (
    ReviewPacket,
    _build_merge_authorization_packet,
    _explicit_merged_pr_merge_packet_entry,
)


def _quorum(**overrides: Any) -> dict[str, Any]:
    quorum: dict[str, Any] = {
        "tier": 2,
        "tier_name": "Tier 2",
        "status": "satisfied",
        "verdict": "admin_squash_allowed",
        "admin_squash_allowed": True,
        "requires_human_risk_settlement": False,
        "unresolved_dissent": False,
        "reviewer_signals": [],
        "dogfood_evidence": [],
        "counted_reviewer_ids": ["claude", "codex"],
        "reasons": ["model quorum satisfied"],
    }
    quorum.update(overrides)
    return quorum


def _packet_factory(
    *,
    quorum: dict[str, Any],
    labels: list[str] | None = None,
    merge_state_status: str = "CLEAN",
):
    def _build(ref: str, **_kwargs: Any) -> ReviewPacket:
        return ReviewPacket(
            pr_number=int(ref),
            title=f"PR {ref}",
            url=f"https://github.com/synaptent/aragora/pull/{ref}",
            head_sha="abc123",
            base_sha="def456",
            author="codex",
            is_draft=False,
            additions=1,
            deletions=1,
            changed_files=1,
            queue_bucket="ready_now",
            touched_subsystems=["scripts"],
            high_risk_paths_touched=[],
            validation=[],
            checks_summary="4/4 green",
            risk_flags=[],
            machine_recommendation="approve_candidate",
            machine_recommendation_reason="bounded test packet",
            packet_sha="sha256:test",
            generated_at="2026-08-30T00:00:00+00:00",
            labels=labels or [],
            merge_state_status=merge_state_status,
            model_review_quorum=quorum,
        )

    return _build


def _entry(
    monkeypatch: pytest.MonkeyPatch,
    *,
    quorum: dict[str, Any],
    labels: list[str] | None = None,
    merge_state_status: str = "CLEAN",
) -> dict[str, Any]:
    monkeypatch.setattr(
        "aragora.cli.commands.review_queue._build_packet",
        _packet_factory(quorum=quorum, labels=labels, merge_state_status=merge_state_status),
    )
    monkeypatch.setattr(
        "aragora.cli.commands.review_queue._explicit_merged_pr_merge_packet_entry",
        lambda ref, repo_override: None,
    )
    packet = _build_merge_authorization_packet(pr_refs=["9858"], limit=30, repo_override=None)
    return packet["entries"][0]


class TestNonAdminMergeEligible:
    def test_true_when_only_admin_lane_live_gate_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _entry(monkeypatch, quorum=_quorum(), merge_state_status="UNSTABLE")

        # Existing #8965 relabel shape stays byte-identical.
        assert entry["status"] == "blocked_by_live_gate"
        assert entry["verdict"] == "admin_squash_blocked_by_live_gate"
        assert entry["admin_squash_allowed"] is False
        assert entry["model_quorum_admin_squash_allowed"] is True
        assert entry["admin_squash_gate_blockers"]

        # The non-admin lane is unaffected by the admin-squash live gate.
        assert entry["non_admin_merge_eligible"] is True

    def test_true_when_fully_clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = _entry(monkeypatch, quorum=_quorum(), merge_state_status="CLEAN")

        assert entry["status"] == "satisfied"
        assert entry["admin_squash_allowed"] is True
        assert entry["non_admin_merge_eligible"] is True

    def test_true_under_operator_review_required_label_hold(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _entry(
            monkeypatch,
            quorum=_quorum(),
            labels=["operator-review-required"],
            merge_state_status="CLEAN",
        )

        # The operator hold blocks the admin-squash lane and stays visible in
        # the sibling keys; the model-level verdict is label-independent (it
        # must stay True while a compliant parked draft still carries the
        # label, or the field would be constant-false at packet time).
        assert entry["operator_review_required"] is True
        assert entry["admin_squash_allowed"] is False
        assert any(
            "operator-review-required" in blocker for blocker in entry["admin_squash_gate_blockers"]
        )
        assert entry["non_admin_merge_eligible"] is True

    def test_true_when_merge_state_status_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = _entry(monkeypatch, quorum=_quorum(), merge_state_status="")

        # Unavailable mergeStateStatus zeroes only the admin-squash lane; the
        # model-level verdict does not claim live mergeability.
        assert entry["admin_squash_allowed"] is False
        assert any("mergeStateStatus" in blocker for blocker in entry["admin_squash_gate_blockers"])
        assert entry["non_admin_merge_eligible"] is True
        assert entry["operator_review_required"] is False

    def test_false_when_model_quorum_not_satisfied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = _entry(
            monkeypatch,
            quorum=_quorum(
                status="needs_model_review_quorum",
                verdict="collect_model_quorum_before_merge",
                admin_squash_allowed=False,
                counted_reviewer_ids=[],
                reasons=["model quorum incomplete: 0/2 signal(s)"],
            ),
            merge_state_status="CLEAN",
        )

        assert entry["status"] == "needs_model_review_quorum"
        assert entry["non_admin_merge_eligible"] is False

    def test_false_when_unresolved_dissent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entry = _entry(
            monkeypatch,
            quorum=_quorum(
                status="unresolved_dissent",
                verdict="human_risk_settlement_required",
                admin_squash_allowed=False,
                requires_human_risk_settlement=True,
                unresolved_dissent=True,
                reasons=["unresolved model dissent is present"],
            ),
            merge_state_status="CLEAN",
        )

        assert entry["unresolved_dissent"] is True
        assert entry["non_admin_merge_eligible"] is False


class TestAlreadyMergedNoopEntry:
    def test_labels_noop_placeholder_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda _args: {
                "number": 9750,
                "title": "merged upstream",
                "url": "https://github.com/synaptent/aragora/pull/9750",
                "headRefOid": "057407297d7c057407297d7c057407297d7c0574",
                "state": "MERGED",
                "mergedAt": "2026-08-27T00:00:00Z",
                "mergeCommit": {"oid": "057407297d7c"},
            },
        )

        entry = _explicit_merged_pr_merge_packet_entry("9750", None)

        assert entry is not None
        assert entry["status"] == "already_merged"
        assert entry["tier"] == 0
        assert entry["counted_model_families"] == []

        # The zero values must be explicitly labeled as noop placeholders so
        # after-the-fact auditors do not read tier 0 / no families as computed
        # results (authoritative values live in the collector JSON artifact).
        assert set(entry["noop_placeholder_fields"]) == {
            "tier",
            "tier_name",
            "counted_reviewer_ids",
            "counted_model_families",
        }
        assert any("noop placeholders" in reason for reason in entry["reasons"])
        assert any("collector JSON artifact" in reason for reason in entry["reasons"])

        # An already-merged PR is not eligible for any merge lane.
        assert entry["non_admin_merge_eligible"] is False
