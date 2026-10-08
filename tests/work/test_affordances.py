"""Tests for the affordance model: hard gates before ranking, frontier not score."""

from aragora.reasoning.epistemics import KnowledgeState
from aragora.work.affordances import (
    ActionAffordance,
    AffordanceDisposition,
    CostVector,
    WaitSpec,
    apply_hard_gates,
    from_work_recommendation,
    pareto_frontier,
)
from aragora.work.models import WorkRecommendation


def _aff(aid: str, value: float = 1.0, tokens: int = 100, risk: int = 0, **kw) -> ActionAffordance:
    defaults = dict(
        affordance_id=aid,
        target="repo",
        operation="probe",
        reason_available="lane is clear",
        disposition=AffordanceDisposition.CONDITIONAL,
        expected_gain="learn merge state",
        expected_value=value,
        cost=CostVector(tokens=tokens),
        risk_tier=risk,
        reversibility="reversible",
        required_capabilities=[],
        required_approvals=[],
        preconditions=[],
        invalidators=[],
        alternatives=[],
        expected_terminal_proof="observation recorded",
    )
    defaults.update(kw)
    return ActionAffordance(**defaults)


class TestHardGates:
    def test_halt_blocks_everything_except_wait_and_info_gathering(self):
        acts = [
            _aff("a"),
            _aff("w", disposition=AffordanceDisposition.WAIT_WATCH),
            _aff("i", disposition=AffordanceDisposition.INFORMATION_GATHERING),
        ]
        gated = {g.affordance_id: g for g in apply_hard_gates(acts, halted=True)}
        assert gated["a"].disposition is AffordanceDisposition.BLOCKED
        assert "halt" in gated["a"].blocked_by
        assert gated["w"].disposition is AffordanceDisposition.WAIT_WATCH
        assert gated["i"].disposition is AffordanceDisposition.INFORMATION_GATHERING

    def test_missing_capability_makes_unavailable(self):
        acts = [_aff("a", required_capabilities=["github:write"])]
        gated = apply_hard_gates(acts, capabilities_held=frozenset({"github:read"}))
        assert gated[0].disposition is AffordanceDisposition.UNAVAILABLE
        assert any("github:write" in b for b in gated[0].blocked_by)

    def test_live_blockers_block_by_id(self):
        acts = [_aff("a"), _aff("b")]
        gated = {
            g.affordance_id: g
            for g in apply_hard_gates(acts, live_blockers={"a": ["lease conflict"]})
        }
        assert gated["a"].disposition is AffordanceDisposition.BLOCKED
        assert gated["a"].blocked_by == ["lease conflict"]
        assert gated["b"].disposition is AffordanceDisposition.CONDITIONAL

    def test_gating_never_removes_items(self):
        acts = [_aff("a"), _aff("b", required_capabilities=["x"])]
        assert len(apply_hard_gates(acts, halted=True)) == 2

    def test_inputs_are_not_mutated(self):
        act = _aff("a")
        apply_hard_gates([act], halted=True)
        assert act.disposition is AffordanceDisposition.CONDITIONAL

    def test_pre_existing_blocked_by_survives_new_gate_reason(self):
        """A candidate that already carries blocked_by (e.g. from
        from_work_recommendation) must never lose those reasons. An
        already-BLOCKED candidate is terminal for the halt gate (it is
        already non-actionable) and passes through unchanged; a NEW live
        blocker still lands, with prior reasons preserved first."""
        aff = from_work_recommendation(
            WorkRecommendation(
                rank=1,
                item_id="bead-2",
                classification="feature",
                action="implement",
                priority="high",
                rationale=["ready"],
                blockers=["needs spec"],
            )
        )
        assert aff.blocked_by == ["needs spec"]

        # Halt is terminal on an already-BLOCKED candidate: unchanged.
        gated = apply_hard_gates([aff], halted=True)
        assert gated[0] is aff
        assert gated[0].blocked_by == ["needs spec"]

        # A NEW live blocker merges after the prior reasons.
        gated_live = apply_hard_gates([aff], live_blockers={aff.affordance_id: ["lease conflict"]})
        assert gated_live[0].blocked_by == ["needs spec", "lease conflict"]
        assert gated_live[0].disposition is AffordanceDisposition.BLOCKED
        # inputs not mutated
        assert aff.blocked_by == ["needs spec"]

        # No new gate reason applies: passes through unchanged.
        gated_no_gate = apply_hard_gates([aff])
        assert gated_no_gate[0] is aff
        assert gated_no_gate[0].blocked_by == ["needs spec"]

    def test_live_blocker_dominates_capability_lack(self):
        """A live-authority blocker must classify as BLOCKED even when a
        capability/approval lack also applies — BLOCKED survives situation-
        frame truncation, so the live blocker can never be silently dropped."""
        acts = [_aff("a", required_capabilities=["github:write"])]
        gated = apply_hard_gates(acts, live_blockers={"a": ["lease conflict"]})
        assert gated[0].disposition is AffordanceDisposition.BLOCKED
        assert "lease conflict" in gated[0].blocked_by
        assert "missing capability: github:write" in gated[0].blocked_by

    def test_live_blocker_downgrades_even_if_reason_already_recorded(self):
        """A recorded reason is not an applied downgrade: a still-actionable
        candidate whose blocked_by already contains the live blocker's string
        must still be classified BLOCKED."""
        acts = [_aff("a", blocked_by=["lease conflict"])]
        assert acts[0].disposition is AffordanceDisposition.CONDITIONAL
        gated = apply_hard_gates(acts, live_blockers={"a": ["lease conflict"]})
        assert gated[0].disposition is AffordanceDisposition.BLOCKED
        assert gated[0].blocked_by == ["lease conflict"]

    def test_missing_approval_makes_unavailable(self):
        acts = [_aff("a", required_approvals=["operator:tier3"])]
        gated = apply_hard_gates(acts)
        assert gated[0].disposition is AffordanceDisposition.UNAVAILABLE
        assert any("operator:tier3" in b for b in gated[0].blocked_by)

    def test_granted_approval_stays_actionable(self):
        acts = [_aff("a", required_approvals=["operator:tier3"])]
        gated = apply_hard_gates(acts, approvals_granted=frozenset({"operator:tier3"}))
        assert gated[0].disposition is AffordanceDisposition.CONDITIONAL
        assert gated[0].blocked_by == []

    def test_gating_is_idempotent(self):
        """Re-gating already-gated output must not duplicate blocked_by,
        change dispositions, or re-fire halt against a candidate whose
        intrinsic disposition (e.g. halt-exempt WAIT_WATCH) was downgraded
        on the first pass."""
        acts = [
            _aff("a"),
            _aff("u", required_capabilities=["github:write"]),
            _aff("p", required_approvals=["operator:tier3"]),
            _aff("w", disposition=AffordanceDisposition.WAIT_WATCH),
        ]
        kwargs = dict(
            halted=True,
            live_blockers={"a": ["lease conflict"], "w": ["lease conflict"]},
        )
        once = apply_hard_gates(acts, **kwargs)
        twice = apply_hard_gates(once, **kwargs)
        for first, second in zip(once, twice):
            assert first.blocked_by == second.blocked_by
            assert first.disposition is second.disposition


class TestParetoFrontier:
    def test_dominated_candidate_is_excluded(self):
        better = _aff("better", value=2.0, tokens=50)
        worse = _aff("worse", value=1.0, tokens=100)
        assert pareto_frontier([better, worse]) == [better]

    def test_tradeoff_candidates_both_survive(self):
        cheap = _aff("cheap", value=1.0, tokens=10)
        strong = _aff("strong", value=5.0, tokens=1000)
        frontier = pareto_frontier([cheap, strong])
        assert {a.affordance_id for a in frontier} == {"cheap", "strong"}

    def test_blocked_and_unavailable_never_ranked(self):
        blocked = _aff("x", value=99.0, tokens=1, disposition=AffordanceDisposition.BLOCKED)
        ok = _aff("ok")
        assert pareto_frontier([blocked, ok]) == [ok]

    def test_risk_tier_is_an_axis(self):
        safe = _aff("safe", value=1.0, tokens=100, risk=0)
        risky = _aff("risky", value=1.0, tokens=100, risk=4)
        assert pareto_frontier([safe, risky]) == [safe]

    def test_human_attention_is_an_axis(self):
        approval_free = _aff("free", value=1.0, cost=CostVector(tokens=100, human_attention=0))
        needs_approval = _aff("approval", value=1.0, cost=CostVector(tokens=100, human_attention=2))
        assert pareto_frontier([approval_free, needs_approval]) == [approval_free]

    def test_wait_watch_can_sit_on_the_frontier(self):
        wait = _aff(
            "wait",
            value=0.5,
            tokens=1,
            disposition=AffordanceDisposition.WAIT_WATCH,
            wait=WaitSpec(
                wake_predicates=["pr:9932:checks_complete"],
                deadline_epoch=2_000_000.0,
                expected_evidence=["check rollup"],
                fallback_affordance_id="probe",
                owner="session",
                cancellation="drop the watch; no side effects",
            ),
        )
        act = _aff("act", value=0.4, tokens=500)
        frontier = pareto_frontier([wait, act])
        assert {a.affordance_id for a in frontier} == {"wait"}


class TestFromWorkRecommendation:
    def _rec(self, blockers: list[str] | None = None) -> WorkRecommendation:
        return WorkRecommendation(
            rank=1,
            item_id="bead-1",
            classification="feature",
            action="implement",
            priority="high",
            rationale=["small and ready"],
            blockers=blockers or [],
        )

    def test_clean_recommendation_is_conditional(self):
        aff = from_work_recommendation(self._rec())
        assert aff.disposition is AffordanceDisposition.CONDITIONAL
        assert aff.target == "bead-1"
        assert aff.operation == "implement"
        assert aff.epistemics is not None
        assert aff.epistemics.state is KnowledgeState.ESTIMATED

    def test_live_blocker_contradicting_clean_rec_is_conflicted_and_blocked(self):
        """A rec with no blockers while live authority says blocked must surface
        the contradiction instead of staying 'ready'."""
        aff = from_work_recommendation(self._rec(), live_blockers=["settlement BLOCKED"])
        assert aff.disposition is AffordanceDisposition.BLOCKED
        assert "settlement BLOCKED" in aff.blocked_by
        assert aff.epistemics.state is KnowledgeState.CONFLICTED

    def test_rec_own_blockers_block_without_conflict(self):
        aff = from_work_recommendation(self._rec(blockers=["needs spec"]))
        assert aff.disposition is AffordanceDisposition.BLOCKED
        assert aff.epistemics.state is KnowledgeState.ESTIMATED
