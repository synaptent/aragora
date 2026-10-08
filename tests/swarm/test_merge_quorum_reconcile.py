"""Unit tests for ``aragora.swarm.merge_quorum_reconcile`` (pure logic).

Covers:

- ``parse_iso8601`` (Z form, naive, empty, invalid).
- ``counted_reviewer_ids`` aggregation (distinct, ignores non-counting).
- ``counted_reviewer_signal_families`` provenance (signal-only, ``None`` fallback).
- ``_signal_families_from_lint`` (lint ``reviewer_signals`` -> provenance tuple).
- ``plan_rerun`` — every safety guard and the happy path.
- ``summarize_settlement`` — every ``next_action`` branch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aragora.swarm.merge_quorum_io import (
    _SIGNAL_IDENTITY_BLOCKERS,
    _could_count,
    _evidence_lint_args,
    _looks_like_shadow,
    _signal_families_from_lint,
)
from aragora.swarm.merge_quorum_reconcile import (
    EvidenceComment,
    PacketClassification,
    QuorumRun,
    counted_reviewer_ids,
    counted_reviewer_signal_families,
    guard_rerun_classification_divergence,
    parse_ci_packet_classification,
    parse_iso8601,
    plan_rerun,
    summarize_settlement,
)

NOW = datetime(2026, 6, 4, 3, 0, 0, tzinfo=timezone.utc)


def _ts(offset_minutes: int) -> str:
    return (NOW + timedelta(minutes=offset_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(
    conclusion: str = "FAILURE", *, created_offset: int = -30, head: str = "abc123"
) -> QuorumRun:
    return QuorumRun(
        run_id=999, created_at=_ts(created_offset), conclusion=conclusion, head_sha=head
    )


def _counting_comment(
    reviewer: str = "claude", *, offset: int = -10, dogfood: bool = True
) -> EvidenceComment:
    return EvidenceComment(
        created_at=_ts(offset), would_count=True, reviewer_id=reviewer, is_dogfood=dogfood
    )


class TestParseIso8601:
    def test_z_form(self) -> None:
        dt = parse_iso8601("2026-06-04T03:00:00Z")
        assert dt == NOW

    def test_naive_assumed_utc(self) -> None:
        dt = parse_iso8601("2026-06-04T03:00:00")
        assert dt == NOW

    def test_empty_and_invalid(self) -> None:
        assert parse_iso8601("") is None
        assert parse_iso8601(None) is None
        assert parse_iso8601("not-a-date") is None


class TestCountedReviewerIds:
    def test_distinct_and_sorted(self) -> None:
        comments = [
            _counting_comment("claude"),
            _counting_comment("openai"),
            _counting_comment("claude"),
            EvidenceComment(created_at=_ts(-5), would_count=False, reviewer_id="grok"),
        ]
        assert counted_reviewer_ids(comments) == ["claude", "openai"]

    def test_empty(self) -> None:
        assert counted_reviewer_ids([]) == []


class TestCountedReviewerSignalFamilies:
    def test_signal_backed_families_counted(self) -> None:
        comments = [
            EvidenceComment(
                created_at=_ts(-10),
                would_count=True,
                reviewer_id="claude",
                reviewer_signals=("claude",),
            ),
            EvidenceComment(
                created_at=_ts(-5),
                would_count=True,
                reviewer_id="openai",
                reviewer_signals=("openai",),
            ),
        ]
        assert counted_reviewer_signal_families(comments) == {"claude", "openai"}

    def test_dogfood_only_comment_contributes_no_signal_family(self) -> None:
        # Explicit empty tuple = affirmatively no genuine reviewer signal:
        # the counted identity must not leak into the signal-only set.
        dogfood_only = EvidenceComment(
            created_at=_ts(-10),
            would_count=True,
            reviewer_id="claude",
            is_dogfood=True,
            reviewer_signals=(),
        )
        assert counted_reviewer_signal_families([dogfood_only]) == set()

    def test_legacy_none_falls_back_to_reviewer_id(self) -> None:
        # Provenance-unaware records (hand-built/legacy) keep prior behavior.
        legacy = EvidenceComment(created_at=_ts(-10), would_count=True, reviewer_id="claude")
        assert legacy.reviewer_signals is None
        assert counted_reviewer_signal_families([legacy]) == {"claude"}

    def test_non_counting_comment_never_contributes(self) -> None:
        rejected = EvidenceComment(
            created_at=_ts(-10),
            would_count=False,
            reviewer_id="claude",
            reviewer_signals=("claude",),
        )
        assert counted_reviewer_signal_families([rejected]) == set()


class TestSignalFamiliesFromLint:
    def test_blockers_pin_review_queue_identity_count_blockers(self) -> None:
        # The swarm layer cannot import the CLI module (upward edge + circular
        # import via quorum_evidence), so the blocker set is duplicated; this
        # pins the copy against the canonical CLI set so they cannot drift.
        from aragora.cli.commands.review_queue import IDENTITY_COUNT_BLOCKERS

        assert _SIGNAL_IDENTITY_BLOCKERS == IDENTITY_COUNT_BLOCKERS

    def test_signal_families_subset_of_counted(self) -> None:
        lint = {
            "counted_reviewer_ids": ["claude"],
            "reviewer_signals": [
                {"model_family": "claude", "identity_problems": []},
                # Not in counted ids -> excluded (e.g. advisory-only family).
                {"model_family": "gemini", "identity_problems": []},
            ],
        }
        assert _signal_families_from_lint(lint) == ("claude",)

    def test_dogfood_evidence_never_contributes(self) -> None:
        # A dogfood-only lint result has a counted id but NO reviewer_signals
        # item: provenance is affirmatively empty, not the counted id.
        lint = {
            "counted_reviewer_ids": ["claude"],
            "reviewer_signals": [],
            "dogfood_evidence": [{"model_family": "claude", "identity_problems": []}],
        }
        assert _signal_families_from_lint(lint) == ()

    def test_identity_blockers_exclude_item(self) -> None:
        lint = {
            "counted_reviewer_ids": ["claude"],
            "reviewer_signals": [
                {
                    "model_family": "claude",
                    "identity_problems": ["heading_model_family_conflict"],
                }
            ],
        }
        assert _signal_families_from_lint(lint) == ()


class TestPlanRerun:
    def _call(self, **overrides):
        kwargs = dict(
            pr_number=7720,
            run=_run(),
            comments=[_counting_comment(offset=-10)],
            current_head_sha="abc123",
            now=NOW,
            last_rerun_at=None,
            reruns_this_head=0,
            cooldown_seconds=600,
            max_reruns_per_head=3,
            has_real_required_failure=False,
        )
        kwargs.update(overrides)
        return plan_rerun(**kwargs)

    def test_happy_path(self) -> None:
        decision = self._call()
        assert decision.should_rerun is True
        assert decision.run_id == 999

    def test_no_run(self) -> None:
        decision = self._call(run=None)
        assert decision.should_rerun is False
        assert "no aragora-merge-quorum run" in decision.reason

    def test_already_success(self) -> None:
        decision = self._call(run=_run(conclusion="SUCCESS"))
        assert decision.should_rerun is False
        assert "already SUCCESS" in decision.reason

    def test_stale_head(self) -> None:
        decision = self._call(run=_run(head="oldsha"))
        assert decision.should_rerun is False
        assert "stale head" in decision.reason

    def test_real_required_failure(self) -> None:
        decision = self._call(has_real_required_failure=True)
        assert decision.should_rerun is False
        assert "real required-check failure" in decision.reason

    def test_no_countable_evidence(self) -> None:
        non_counting = [EvidenceComment(created_at=_ts(-5), would_count=False)]
        decision = self._call(comments=non_counting)
        assert decision.should_rerun is False
        assert "no countable evidence" in decision.reason

    def test_run_postdates_evidence(self) -> None:
        # Run created after the newest countable comment.
        decision = self._call(run=_run(created_offset=-5), comments=[_counting_comment(offset=-10)])
        assert decision.should_rerun is False
        assert "postdates" in decision.reason

    def test_max_reruns(self) -> None:
        decision = self._call(reruns_this_head=3, max_reruns_per_head=3)
        assert decision.should_rerun is False
        assert "max reruns" in decision.reason

    def test_pr_budget_disabled_by_default(self) -> None:
        # pr_round_budget defaults to 0 (disabled); a high consumed count is ignored.
        decision = self._call(pr_rounds_consumed=99)
        assert decision.should_rerun is True

    def test_pr_budget_under_limit_allows(self) -> None:
        decision = self._call(pr_rounds_consumed=2, pr_round_budget=6)
        assert decision.should_rerun is True

    def test_pr_budget_exhausted_demands_adjudication(self) -> None:
        decision = self._call(pr_rounds_consumed=6, pr_round_budget=6)
        assert decision.should_rerun is False
        assert "round budget exhausted" in decision.reason
        assert "net-value adjudication" in decision.reason
        assert decision.needs_adjudication is True

    def test_needs_adjudication_false_on_all_other_paths(self) -> None:
        assert self._call(pr_rounds_consumed=2, pr_round_budget=6).needs_adjudication is False
        assert self._call(reruns_this_head=5).needs_adjudication is False

    def test_pr_budget_bites_even_when_per_head_cap_is_fresh(self) -> None:
        # THE fix: a repair push creates a new head, so the per-head cap resets
        # (reruns_this_head=0). The per-PR budget must still bite across that drift.
        decision = self._call(
            reruns_this_head=0, max_reruns_per_head=3, pr_rounds_consumed=6, pr_round_budget=6
        )
        assert decision.should_rerun is False
        assert "round budget exhausted" in decision.reason

    def test_within_cooldown(self) -> None:
        decision = self._call(last_rerun_at=NOW - timedelta(seconds=120), cooldown_seconds=600)
        assert decision.should_rerun is False
        assert "cooldown" in decision.reason

    def test_cooldown_elapsed_allows(self) -> None:
        decision = self._call(last_rerun_at=NOW - timedelta(seconds=900), cooldown_seconds=600)
        assert decision.should_rerun is True

    def test_unparseable_run_timestamp(self) -> None:
        decision = self._call(
            run=QuorumRun(run_id=1, created_at="bad", conclusion="FAILURE", head_sha="abc123")
        )
        assert decision.should_rerun is False
        assert "unparseable" in decision.reason

    def test_classification_divergence_blocks_wasted_rerun(self) -> None:
        decision = self._call()
        ci_packet = PacketClassification(
            source="ci",
            pr_number=7754,
            head_sha="abc123",
            tier=4,
            status="human_preapproval_required",
            verdict="tier_4_human_preapproval_required",
            requires_human_risk_settlement=True,
        )
        local_packet = PacketClassification(
            source="local",
            pr_number=7754,
            head_sha="abc123",
            tier=2,
            status="repair_or_wait",
            verdict="not_ready_for_settlement",
            requires_human_risk_settlement=False,
        )

        guarded = guard_rerun_classification_divergence(
            decision,
            ci_packet=ci_packet,
            local_packet=local_packet,
            head_sha="abc123",
        )

        assert guarded.should_rerun is False
        assert "classification_divergence" in guarded.reason
        assert "CI packet: ci: head=abc123 tier=4" in guarded.next_prompt
        assert "Local packet: local: head=abc123 tier=2" in guarded.next_prompt

    def test_status_only_packet_difference_keeps_rerun_allowed(self) -> None:
        decision = self._call()
        ci_packet = PacketClassification(
            source="ci",
            pr_number=7754,
            head_sha="abc123",
            tier=2,
            status="needs_model_review_quorum",
            verdict="collect_model_quorum_before_merge",
            requires_human_risk_settlement=False,
        )
        local_packet = PacketClassification(
            source="local",
            pr_number=7754,
            head_sha="abc123",
            tier=2,
            status="repair_or_wait",
            verdict="not_ready_for_settlement",
            requires_human_risk_settlement=False,
        )

        guarded = guard_rerun_classification_divergence(
            decision,
            ci_packet=ci_packet,
            local_packet=local_packet,
            head_sha="abc123",
        )

        assert guarded.should_rerun is True
        assert guarded.reason == decision.reason


def test_parse_ci_packet_classification_from_quorum_log() -> None:
    packet = parse_ci_packet_classification(
        "\n".join(
            [
                "noise",
                "aragora-merge-quorum\tEvaluate merge quorum\tPR #7754 | Tier 4 | status=human_preapproval_required | verdict=tier_4_human_preapproval_required",
            ]
        ),
        pr_number=7754,
        head_sha="abc123",
    )

    assert packet is not None
    assert packet.pr_number == 7754
    assert packet.tier == 4
    assert packet.requires_human_risk_settlement is True


class TestSummarizeSettlement:
    def _call(self, **overrides):
        kwargs = dict(
            pr_number=7720,
            head_sha="abc123def456",
            tier=2,
            comments=[_counting_comment("claude"), _counting_comment("openai")],
            human_settlement_present=False,
            quorum_conclusion="FAILURE",
        )
        kwargs.update(overrides)
        return summarize_settlement(**kwargs)

    def test_signal_count_property(self) -> None:
        status = self._call()
        assert status.signal_count == 2
        assert status.counted_reviewer_ids == ["claude", "openai"]

    def test_green_quorum_ready_to_merge(self) -> None:
        status = self._call(quorum_conclusion="SUCCESS")
        assert "ready to merge" in status.next_action

    def test_needs_more_signals(self) -> None:
        status = self._call(comments=[_counting_comment("claude")])
        assert "1 more distinct model signal" in status.next_action

    def test_needs_dogfood(self) -> None:
        status = self._call(
            comments=[
                _counting_comment("claude", dogfood=False),
                _counting_comment("openai", dogfood=False),
            ]
        )
        assert "adversarial-dogfood" in status.next_action
        assert status.has_dogfood is False

    def test_tier4_needs_human_settlement(self) -> None:
        status = self._call(tier=4, human_settlement_present=False)
        assert "human settlement" in status.next_action

    def test_stale_quorum_rerun_hint(self) -> None:
        # Tier 2: signals + dogfood present, no human needed, but check still failing.
        status = self._call(tier=2, quorum_conclusion="FAILURE")
        assert "re-run aragora-merge-quorum" in status.next_action

    def test_no_run_yet_waits(self) -> None:
        # Everything satisfied but the check has not produced a conclusion yet.
        status = self._call(tier=2, quorum_conclusion="")
        assert "wait for the aragora-merge-quorum check" in status.next_action

    def test_non_final_state_waits(self) -> None:
        # A non-terminal state (via the check-run state fallback) is not a stale run.
        status = self._call(tier=2, quorum_conclusion="IN_PROGRESS")
        assert "wait for the aragora-merge-quorum check" in status.next_action

    def test_unknown_tier_defaults_strict(self) -> None:
        status = self._call(tier=None, human_settlement_present=False)
        # Strict default requires human settlement.
        assert "human settlement" in status.next_action

    # --- Jurisdiction consistency with the live gate (grok #8507 P2) -----------
    # The diagnostic must apply the same Western-only / at-least-one-Western rules
    # the gate enforces, so it can never tell an operator "settle-ready" for a
    # pair the gate would block.

    def test_tier3_chinese_routed_family_does_not_count_toward_settle_ready(self) -> None:
        # Tier 3 claude+deepseek: the gate drops deepseek (advisory-only), so the
        # diagnostic must report the quorum as incomplete, not settle-ready.
        status = self._call(
            tier=3,
            comments=[_counting_comment("claude"), _counting_comment("deepseek")],
        )
        # Western-only counted quorum: only claude counts → needs one more Western.
        assert "1 more distinct Western model signal" in status.next_action
        assert "advisory-only" in status.next_action

    def test_tier3_two_western_families_advance_past_signal_count(self) -> None:
        # claude+grok are both Western: the signal count is met, so the hint moves
        # on to the next requirement (human settlement) rather than "collect more".
        status = self._call(
            tier=3,
            comments=[_counting_comment("claude"), _counting_comment("grok")],
            human_settlement_present=False,
        )
        assert "Western model signal" not in status.next_action
        assert "human settlement" in status.next_action

    def test_tier2_no_western_family_is_not_settle_ready(self) -> None:
        # Tier 2 deepseek+qwen: two distinct families but no Western → the gate
        # blocks on the at-least-one-Western rule, so the diagnostic must too.
        status = self._call(
            tier=2,
            comments=[_counting_comment("deepseek"), _counting_comment("qwen")],
        )
        assert "Western model signal" in status.next_action


class TestLooksLikeShadow:
    def test_trailing_marker_is_shadow(self) -> None:
        assert _looks_like_shadow("Mac TypeScript SDK Shadow") is True
        assert _looks_like_shadow("Hetzner Offline Golden Path Shadow") is True
        assert _looks_like_shadow("deploy advisory") is True

    def test_hyphenated_required_not_misclassified(self) -> None:
        # Marker appears mid-name but the last token is "required".
        assert _looks_like_shadow("aragora-shadow-deploy-required") is False

    def test_plain_required_check(self) -> None:
        assert _looks_like_shadow("aragora-merge-quorum") is False
        assert _looks_like_shadow("") is False


class TestEvidenceLintArgs:
    def test_never_passes_repo(self) -> None:
        # evidence-lint rejects --repo; building it would break every lint call.
        args = _evidence_lint_args(7735, "abc1234", "2026-06-04T13:18:35Z", "someone", "/tmp/b.md")
        assert "--repo" not in args

    def test_includes_required_flags(self) -> None:
        args = _evidence_lint_args(7735, "abc1234", "", "someone", "/tmp/b.md")
        assert "evidence-lint" in args
        assert args[args.index("--pr") + 1] == "7735"
        assert args[args.index("--head-sha") + 1] == "abc1234"
        assert args[args.index("--body-file") + 1] == "/tmp/b.md"
        assert args[args.index("--author") + 1] == "someone"
        assert "--json" in args
        # No committed-at supplied -> flag omitted.
        assert "--head-committed-at" not in args

    def test_includes_committed_at_when_present(self) -> None:
        args = _evidence_lint_args(7735, "abc1234", "2026-06-04T13:18:35Z", "someone", "/tmp/b.md")
        assert args[args.index("--head-committed-at") + 1] == "2026-06-04T13:18:35Z"


class TestCouldCount:
    def test_github_actions_author_rejected(self) -> None:
        assert _could_count("github-actions[bot]", "x" * 80) is False

    def test_short_body_rejected(self) -> None:
        assert _could_count("someone", "too short") is False

    def test_plausible_comment_passes(self) -> None:
        body = "Claude review of head abc1234: VERDICT passed, dogfood adversarial check."
        assert _could_count("someone", body) is True
