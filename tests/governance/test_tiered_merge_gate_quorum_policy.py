"""Governance tests for the tiered merge-gate quorum policy (Tier 4 pre-approval).

These tests are the pre-approval regression target for the design in
``docs/specs/TIERED_MERGE_GATE_QUORUM_POLICY.md``, per
``docs/REVIEW_AUTHORITY_PRINCIPLES.md::Family-additive change governance`` (a
change to *which family counts at which Tier* is a Tier 4 merge-authority
self-modification).

They pin the implementation that inverts the former gaps:

* **G1** — Tier 3-4 are Western-only counted (claude+deepseek no longer settles a
  Tier 4 merge; claude+grok — both Western — does).
* **G2** — Tier 2 requires at least one Western family.
* **G3** — a single ``QuorumPolicy`` source of truth drives all three quorum
  surfaces (the live merge gate, the auto-settle path, and the reconcile
  diagnostic), which agree per Tier.
* The Western-frontier set (Tier 1-2 single-signal authority) is a strict subset
  of the Western set (Tier 3-4 counting eligibility).
"""

from __future__ import annotations

import pytest

from aragora.swarm.quorum_evidence import (
    ADVISORY_ONLY_FAMILIES,
    CHINESE_ROUTED_FAMILIES,
    FAMILY_PROVIDERS,
    TIER_3_4_COUNTED_FAMILIES,
    WESTERN_FAMILIES,
    WESTERN_FRONTIER_FAMILIES,
    tier_quorum_rule,
)


# --- Family jurisdiction sets ------------------------------------------------


def test_western_families_match_spec():
    # docs/REVIEW_AUTHORITY_PRINCIPLES.md: Anthropic, OpenAI, xAI, Mistral,
    # Nous Hermes (by canonical family id). Google (gemini) was demoted to
    # advisory-only by the 2026-07-16 founder roster directive (see
    # docs/governance/records/20260716T2200Z-gemini-reviewer-reliability-record.md);
    # its reviews still post and remain readable but do not count.
    assert WESTERN_FAMILIES == frozenset({"claude", "openai", "grok", "mistral", "hermes"})
    assert "gemini" not in WESTERN_FAMILIES


def test_family_classification_is_total_and_disjoint():
    # Every recognized family is classified exactly once across the three
    # jurisdiction/authority classes; no family is left unclassified (which
    # would silently default it to full Tier 0-1 counting).
    assert not WESTERN_FAMILIES & CHINESE_ROUTED_FAMILIES
    assert not WESTERN_FAMILIES & ADVISORY_ONLY_FAMILIES
    assert not CHINESE_ROUTED_FAMILIES & ADVISORY_ONLY_FAMILIES
    assert WESTERN_FAMILIES | CHINESE_ROUTED_FAMILIES | ADVISORY_ONLY_FAMILIES == set(
        FAMILY_PROVIDERS
    )


@pytest.mark.parametrize("tier", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("gate", [False, True])
def test_advisory_only_families_never_count_at_any_tier(tier, gate):
    # Roster record mandate (docs/governance/records/
    # 20260716T2200Z-gemini-reviewer-reliability-record.md): an advisory-only
    # family never counts FOR a quorum at ANY tier, under either gate regime —
    # not just at the Western-keyed Tier 2-4 conditions.
    rule = tier_quorum_rule(tier, tiered_gate=gate)
    for family in ADVISORY_ONLY_FAMILIES:
        assert family not in rule.counted_families({family, "claude", "deepseek"})
        assert rule.is_satisfied_by({family}) is False
        # Presence of an advisory-only signal never changes the outcome.
        for others in ({"claude"}, {"claude", "openai"}, {"deepseek", "qwen"}):
            assert rule.is_satisfied_by(others | {family}) == rule.is_satisfied_by(others)


def test_advisory_only_dissent_is_not_blocking():
    # The against-side of the mandate ("gemini dissent is NOT to be counted
    # anywhere"): a [P1]-backed CHANGES-REQUESTED from an advisory-only family
    # never promotes blocking dissent, while the same review from a counting
    # family still does.
    from aragora.swarm.quorum_evidence import EvidenceItem

    body = "Verdict: CHANGES-REQUESTED\n- [P1] blocking finding"
    assert EvidenceItem("gemini", body, True, ["gemini"], [], "changes_requested").dissenting is (
        False
    )
    assert EvidenceItem("claude", body, True, ["claude"], [], "changes_requested").dissenting is (
        True
    )


def test_western_frontier_is_strict_subset_of_western():
    # "Frontier" (who may solo-settle Tier 1-2) is a strict subset of "Western"
    # (who counts at Tier 3-4). They are distinct concepts and must not be conflated.
    assert WESTERN_FRONTIER_FAMILIES < WESTERN_FAMILIES
    assert WESTERN_FRONTIER_FAMILIES == frozenset({"claude", "openai"})


@pytest.mark.parametrize("family", ["glm", "minimax", "tencent", "bytedance"])
def test_chinese_reviewer_families_never_count_at_tier3_4(family):
    assert family not in WESTERN_FAMILIES
    assert family not in WESTERN_FRONTIER_FAMILIES
    for tier in (3, 4):
        rule = tier_quorum_rule(tier, tiered_gate=False)
        assert rule.is_satisfied_by({"claude", family}) is False


@pytest.mark.parametrize("family", ["glm", "minimax", "tencent", "bytedance"])
def test_chinese_reviewer_families_require_western_peer_at_tier2(family):
    rule = tier_quorum_rule(2, tiered_gate=False)
    assert rule.is_satisfied_by({"claude", family}) is True
    assert rule.is_satisfied_by({"deepseek", family}) is False


# --- G1: Tier 3-4 Western-only counted quorum --------------------------------


@pytest.mark.parametrize("tier", [3, 4])
def test_tier3_4_are_western_only_counted(tier):
    rule = tier_quorum_rule(tier, tiered_gate=False)
    assert rule.western_only_counted is True
    assert rule.required_signals == 2
    # Two Western families settle; a Western + Chinese-routed pair does NOT (the
    # Chinese family is advisory-only and excluded from the counted set).
    assert rule.is_satisfied_by({"claude", "grok"}) is True
    assert rule.is_satisfied_by({"claude", "openai"}) is True
    assert rule.is_satisfied_by({"claude", "deepseek"}) is False
    assert rule.is_satisfied_by({"deepseek", "qwen"}) is False
    # mistral and hermes are Western but advisory-only at Tier 3-4 (operator
    # decision 2026-07-11): they do not count toward the two-signal bar.
    assert rule.is_satisfied_by({"mistral", "hermes"}) is False
    assert rule.is_satisfied_by({"claude", "mistral"}) is False  # only claude counts
    assert rule.is_satisfied_by({"claude", "hermes"}) is False
    # grok counts at Tier 3-4. gemini does NOT: the 2026-07-11 decision that put
    # it in the counted set was superseded by the 2026-07-16 founder roster
    # directive demoting it to advisory-only everywhere.
    assert rule.is_satisfied_by({"claude", "grok"}) is True
    assert rule.is_satisfied_by({"gemini", "grok"}) is False
    assert rule.is_satisfied_by({"claude", "gemini"}) is False
    # The flag never relaxes Tier 3-4.
    assert tier_quorum_rule(tier, tiered_gate=True).western_only_counted is True


def test_tier3_4_counted_families_excludes_mistral_hermes_and_gemini():
    """TIER_3_4_COUNTED_FAMILIES is the frontier-grade Western subset."""
    assert TIER_3_4_COUNTED_FAMILIES == {"claude", "openai", "grok"}
    # Strict subset of the broader Western set (which mistral/hermes remain in
    # for the Tier 2 "at least one Western" bar).
    assert TIER_3_4_COUNTED_FAMILIES < WESTERN_FAMILIES
    assert {"mistral", "hermes"} & TIER_3_4_COUNTED_FAMILIES == set()
    assert {"mistral", "hermes"} <= WESTERN_FAMILIES


def test_tier3_4_counted_families_disjoint_from_advisory_only():
    """The two directives must not contradict: an advisory-only family can
    never appear in the Tier 3-4 counted set (gemini regression guard)."""
    assert TIER_3_4_COUNTED_FAMILIES & ADVISORY_ONLY_FAMILIES == frozenset()
    assert "gemini" in ADVISORY_ONLY_FAMILIES
    assert "gemini" not in TIER_3_4_COUNTED_FAMILIES


def test_unknown_tier_fails_safe_to_western_only():
    rule = tier_quorum_rule(None, tiered_gate=True)
    assert rule.western_only_counted is True
    assert rule.is_satisfied_by({"claude", "deepseek"}) is False
    assert rule.is_satisfied_by({"claude", "grok"}) is True


# --- G2: Tier 2 requires at least one Western family --------------------------


def test_tier2_requires_at_least_one_western():
    rule = tier_quorum_rule(2, tiered_gate=False)
    assert rule.requires_at_least_one_western is True
    assert rule.western_only_counted is False  # Chinese still COUNT, just not alone
    assert rule.is_satisfied_by({"claude", "deepseek"}) is True  # >=1 Western
    assert rule.is_satisfied_by({"deepseek", "qwen"}) is False  # no Western
    assert rule.is_satisfied_by({"claude"}) is False  # only one signal


def test_tier1_counts_any_two_distinct_families():
    # Tier 1 (default OFF) is the routine tier: Chinese-routed families count freely.
    rule = tier_quorum_rule(1, tiered_gate=False)
    assert rule.requires_at_least_one_western is False
    assert rule.western_only_counted is False
    assert rule.is_satisfied_by({"deepseek", "qwen"}) is True


# --- Tier 1-2 single-western-frontier relaxation (#8507's feature) ------------


@pytest.mark.parametrize("tier", [1, 2])
def test_tiered_gate_relaxation_requires_western_frontier(tier):
    # Flag ON (ARAGORA_ENABLE_TIERED_MERGE_GATE=1): a Tier 1-2 PR settles on a
    # single western-frontier signal (claude/openai).
    rule = tier_quorum_rule(tier, tiered_gate=True)
    assert rule.required_signals == 1
    assert rule.requires_western_frontier is True
    assert rule.is_satisfied_by({"claude"}) is True  # frontier solo-settles
    assert rule.is_satisfied_by({"grok"}) is False  # Western but not frontier
    assert rule.is_satisfied_by({"deepseek"}) is False  # cheap cannot solo-settle

    # Flag OFF (contrast): without the gate, Tier 1-2 require two distinct
    # families, so a lone western-frontier signal no longer satisfies the quorum.
    off = tier_quorum_rule(tier, tiered_gate=False)
    assert off.required_signals == 2
    assert off.requires_western_frontier is False
    assert off.is_satisfied_by({"claude"}) is False  # one signal is insufficient


# --- G3: single source of truth across all three surfaces --------------------


@pytest.mark.parametrize("tier", [0, 1, 2, 3, 4])
def test_single_source_all_three_paths_agree(tier, monkeypatch):
    # Compare the live merge gate (_tier_requirement) against the canonical policy
    # under the default-OFF regime; they must encode the same per-Tier requirement.
    monkeypatch.delenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", raising=False)
    from aragora.cli.commands.review_queue import _tier_requirement

    rule = tier_quorum_rule(tier, tiered_gate=False)
    req = _tier_requirement(tier)
    assert req["required_model_signals"] == rule.required_signals
    assert req["requires_western_frontier_signal"] == rule.requires_western_frontier
    assert req["western_only_counted"] == rule.western_only_counted
    assert req["requires_at_least_one_western"] == rule.requires_at_least_one_western


def test_reconcile_diagnostic_matches_policy():
    # The merge_quorum_reconcile diagnostic table is a literal (a runtime derivation
    # would be a circular import); pin it to the canonical policy so it cannot drift.
    from aragora.swarm.merge_quorum_reconcile import TIER_REQUIREMENTS

    for tier, (required_signals, requires_dogfood, requires_human) in TIER_REQUIREMENTS.items():
        rule = tier_quorum_rule(tier, tiered_gate=False)
        assert required_signals == rule.required_signals
        assert requires_dogfood == (tier > 0)
        assert requires_human == (tier >= 3)


@pytest.mark.parametrize("tier", [1, 2])
def test_reconcile_diagnostic_is_flag_aware_under_tiered_gate(tier, monkeypatch):
    # The reconcile diagnostic must read the SAME tiered-gate flag the live gate reads
    # (tiered_merge_gate_enabled), not hardcode the strict default-OFF regime. Under the
    # flag a Tier 1-2 PR settles on one western-frontier signal, so a lone claude signal
    # (+ dogfood) must NOT be reported as short of quorum; with the flag OFF the same lone
    # signal IS one short of the strict two-family bar.
    from aragora.swarm.merge_quorum_reconcile import EvidenceComment, summarize_settlement

    lone_frontier = [
        EvidenceComment(
            created_at="2026-06-26T00:00:00Z",
            would_count=True,
            reviewer_id="claude",
            is_dogfood=True,
        )
    ]

    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "1")
    on = summarize_settlement(
        pr_number=1,
        head_sha="deadbeef",
        tier=tier,
        comments=lone_frontier,
        human_settlement_present=False,
        quorum_conclusion="FAILURE",
    )
    # Mirrors the live gate, which accepts a lone western-frontier signal under the flag.
    assert tier_quorum_rule(tier, tiered_gate=True).is_satisfied_by(["claude"]) is True
    assert "more distinct model signal" not in on.next_action
    assert "western-frontier" not in on.next_action  # claude already satisfies the frontier

    monkeypatch.delenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", raising=False)
    off = summarize_settlement(
        pr_number=1,
        head_sha="deadbeef",
        tier=tier,
        comments=lone_frontier,
        human_settlement_present=False,
        quorum_conclusion="FAILURE",
    )
    # Strict (flag OFF) bar: the same lone signal is one short of the two-family quorum.
    assert tier_quorum_rule(tier, tiered_gate=False).is_satisfied_by(["claude"]) is False
    assert "collect 1 more distinct model signal" in off.next_action


@pytest.mark.parametrize("tier", [1, 2])
def test_reconcile_diagnostic_never_green_lights_non_frontier_under_tiered_gate(tier, monkeypatch):
    # NEVER falsely green-light: grok is Western but NOT western-frontier, so under the flag
    # a lone grok signal does not settle a Tier 1-2 PR. The diagnostic must surface the
    # missing western-frontier signal (mirroring the gate's western_frontier check) instead
    # of reporting the lone non-frontier signal as sufficient.
    from aragora.swarm.merge_quorum_reconcile import EvidenceComment, summarize_settlement

    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "1")
    lone_grok = [
        EvidenceComment(
            created_at="2026-06-26T00:00:00Z",
            would_count=True,
            reviewer_id="grok",
            is_dogfood=True,
        )
    ]
    status = summarize_settlement(
        pr_number=1,
        head_sha="deadbeef",
        tier=tier,
        comments=lone_grok,
        human_settlement_present=False,
        quorum_conclusion="FAILURE",
    )
    assert tier_quorum_rule(tier, tiered_gate=True).is_satisfied_by(["grok"]) is False
    assert "western-frontier" in status.next_action


def test_review_queue_reexports_canonical_jurisdiction_sets():
    # The gate references the *same* frozenset objects as the policy (no duplicate
    # allowlist to drift).
    from aragora.cli.commands import review_queue as rq

    assert rq.WESTERN_FAMILIES is WESTERN_FAMILIES
    assert rq.WESTERN_FRONTIER_FAMILIES is WESTERN_FRONTIER_FAMILIES


# --- VAL-P4A-024: signal-only western-frontier advice in the read-only diagnostic


def test_diagnostic_dogfood_only_identity_does_not_advance_frontier_advice(monkeypatch):
    # VAL-P4A-024: a dogfood-only record attributed to a western-frontier family
    # (claude/openai) may satisfy the separate dogfood requirement, but it
    # carries NO genuine model-review signal, so the read-only settlement
    # diagnostic must keep asking for a western-frontier review signal instead
    # of reporting the frontier requirement as met. Mirrors the live gate's
    # signal-only derivation (review_queue._build_model_review_quorum computes
    # has_western_frontier_signal from reviewer signals with an EMPTY dogfood
    # list: "The WF requirement must be met by a model-review signal, not by
    # dogfood-only metadata").
    from aragora.swarm.merge_quorum_reconcile import EvidenceComment, summarize_settlement

    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "1")
    for tier in (1, 2):
        for family in ("claude", "openai"):
            dogfood_only = [
                EvidenceComment(
                    created_at="2026-07-15T00:00:00Z",
                    would_count=True,
                    # Counted identity attributed via dogfood evidence only.
                    reviewer_id=family,
                    is_dogfood=True,
                    # Provenance: affirmatively NO genuine reviewer signal.
                    reviewer_signals=(),
                )
            ]
            status = summarize_settlement(
                pr_number=1,
                head_sha="deadbeef",
                tier=tier,
                comments=dogfood_only,
                human_settlement_present=False,
                quorum_conclusion="FAILURE",
            )
            # The dogfood leg is satisfied by the dogfood-only record...
            assert status.has_dogfood is True
            # ...but the western-frontier review-signal requirement is NOT:
            # the diagnostic must still ask for a western-frontier signal.
            assert "western-frontier" in status.next_action


def test_diagnostic_genuine_reviewer_signal_advances_frontier_advice(monkeypatch):
    # VAL-P4A-024 companion: adding ONE genuine current-head claude/openai
    # reviewer signal (on top of the same dogfood-only record) satisfies the
    # western-frontier requirement, so the advice advances past it to the next
    # step (here the stale-quorum re-run hint) instead of asking for a signal.
    from aragora.swarm.merge_quorum_reconcile import EvidenceComment, summarize_settlement

    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "1")
    for tier in (1, 2):
        comments = [
            # The dogfood-only record from the companion test...
            EvidenceComment(
                created_at="2026-07-15T00:00:00Z",
                would_count=True,
                reviewer_id="claude",
                is_dogfood=True,
                reviewer_signals=(),
            ),
            # ...plus one genuine current-head claude reviewer signal.
            EvidenceComment(
                created_at="2026-07-15T00:05:00Z",
                would_count=True,
                reviewer_id="claude",
                is_dogfood=False,
                reviewer_signals=("claude",),
            ),
        ]
        status = summarize_settlement(
            pr_number=1,
            head_sha="deadbeef",
            tier=tier,
            comments=comments,
            human_settlement_present=False,
            quorum_conclusion="FAILURE",
        )
        assert tier_quorum_rule(tier, tiered_gate=True).is_satisfied_by(["claude"]) is True
        assert status.has_dogfood is True
        assert "western-frontier" not in status.next_action
        # Advice advanced past every quorum leg to the stale-check recovery hint.
        assert "re-run aragora-merge-quorum" in status.next_action
