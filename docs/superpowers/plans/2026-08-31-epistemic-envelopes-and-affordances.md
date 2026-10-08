# Epistemic Tags, Action Affordances, and Situation Envelopes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Aragora's agent-facing read models three primitives from the doodlestein/GPT-Pro agent-system design (X posts 2094376160884871438 / 2094377433784783330, 2026-08-31): (1) three-axis epistemic tags replacing the lone confidence scalar, (2) `ActionAffordance` records with hard-gate-then-Pareto-frontier ranking replacing opaque scores, and (3) an evidence–possibility–control `SituationFrame` whose truncation can never silently drop high-severity dissent.

**Architecture:** Three additive, standalone modules with zero changes to existing files: `aragora/reasoning/epistemics.py` (axis enums + tag + authority reconciliation), `aragora/work/affordances.py` (affordance model + hard gates + nondominated frontier + `WorkRecommendation` adapter), `aragora/reasoning/situation_frame.py` (three envelopes + `ReceiptDissent` adapter + protected truncation). Each module is one PR-sized batch. The in-flight Agent Operating Tower run (`agent-operating-tower-20260831`, PR #9932) later adopts these from its `aragora orient` layer; nothing here imports from or blocks that branch.

**Tech Stack:** Python 3.11+ stdlib only (dataclasses, enum, json). No new dependencies. pytest for tests.

**Spec:** This document's "Source material and Aragora mapping" section below (the X-post screenshots are transcribed there); companion context in the Agent Operating Tower spec carried by PR #9932 (`docs/architecture/agent-operating-loop.md` on that branch — NOT on main yet; do not import from it).

## Global Constraints

- Python 3.11+, stdlib only; no new third-party dependencies.
- Do NOT modify `aragora/__init__.py` (protected file), `CLAUDE.md`, `.env`, or `scripts/nomic_loop.py`.
- Do NOT modify any existing module. All three tasks create new files only (plus empty `tests/work/__init__.py`).
- Each task is one PR ≤800 changed lines, Tier 0–2 (additive types, no authority-semantics change to any live decision path), normal draft→ready CI flow: `lint`, `typecheck`, `sdk-parity`, `Generate & Validate`, `TypeScript SDK Type Check`, plus `aragora-merge-quorum` when ready.
- Run `make ci-required` locally before pushing each task.
- **Sequencing:** Merging to main forces the in-flight tower run (PR #9932) to restack under its exact-ref drift gate. Do not push/merge these batches until that run terminates (≤24h from 2026-08-31 morning) or its operator releases the lane. Implementation and local validation can proceed in an isolated worktree immediately.
- Timestamps are epoch-seconds floats passed in by callers (`now: float`); modules never call `time.time()` inside pure functions so tests stay deterministic.

## Source material and Aragora mapping (the spec)

Transcribed from the two X-post screenshots, with the Aragora adaptation decisions locked in:

**1. "Epistemology is no longer a confidence scalar" — three orthogonal axes.**
- Knowledge state: `known, estimated, unknown, conflicted, stale, not_observable, redacted, indeterminate, not_applicable`. All nine have real Aragora producers: `redacted` ← SecurityBarrier/tenancy, `not_observable` ← source-health failures, `indeterminate` ← quorum UNSTABLE / transport ambiguity, `stale` ← TTL expiry, `conflicted` ← recommendation-vs-live contradictions (the measured "ready while BLOCKED" failure).
- Provenance: `observed, derived, predicted, remembered, operator_asserted, vendor_claimed, policy`. This is an **authority-class** axis, distinct from the existing `aragora.reasoning.provenance.SourceType` (which records the *channel*: web_search, document, database…). Both coexist; do not merge them. Mapping: `observed` = exact git/API/lease/halt facts, `operator_asserted` = human settlement/steering, `policy` = operating contract/config, `remembered` = KM/Continuum/Supermemory, `vendor_claimed` = third-party self-reports (Pulse ingestors, provider claims), `derived` = computed joins and model analysis, `predicted` = forecasts.
- Hypothesis disposition: `live, supported, disfavored` (+ `refuted, superseded` completing the lifecycle; the screenshot cut off after "disfavored"). Distinct from `BeliefStatus` (a propagation lifecycle: prior/updated/converged/contested) — disposition is about where a competing *interpretation* stands, not how a belief node got its value.

**2. "Affordances replace hidden recommendation logic."** Every next move is an `ActionAffordance` with target/operation, reason-available-now, expected gain, cost vector, latency, privacy exposure, risk, reversibility, required capabilities/approvals, preconditions, invalidators, supported/unsafe worlds, alternatives, expected terminal proof. Hard authority/safety/freshness constraints apply **before** ranking; the agent receives a **nondominated frontier**, not one opaque score. `wait/watch` is itself an affordance with wake predicates, deadline, expected evidence, opportunity cost, fallback, owner, cancellation semantics. Aragora fit: `WorkRecommendation` (aragora/work/models.py:92) today exposes `rank` + `WorkScore.total` — an opaque universal score; `blockers` exist but don't gate ranking. Prior art for frontiers: `aragora/routing/decision_stakes_router.py` already records an unconstrained Pareto frontier separately from constrained selection — same philosophy, model-routing domain.

**3. "The evidence–possibility–control model."** A `SituationFrame` distinguishes an evidence envelope (established facts, certified absences, assumptions), a possibility envelope (material alternative worlds and *protected adversarial residuals* consistent with evidence), and a control envelope (actions classified robust / conditional / information-gathering / wait-watch / blocked / unavailable). Invariant: **"A high-loss residual cannot disappear because it has a low rank, low posterior, inconvenient token cost, or because a model reranker prefers a benign interpretation."** This is Aragora's dissent-preservation thesis restated at the orientation layer: `ReceiptDissent` (aragora/export/decision_receipt.py:56) and severity-gated dissent (#8574) already refuse to drop dissent at decision time; this task extends the guarantee through *summarization/truncation* of agent-facing views — directly relevant to the tower spec's 16KB envelope budget and truthful `truncation.emitted_bytes`.

**Deliberately NOT imported** (complexity accounting): the drone-domain world-model machinery (pose graphs, sensor fusion, physical possible-worlds enumeration), the full 11-layer cognitive-center tower (PR #9932's four-layer null hypothesis owns that decision), `privacy_exposure` and `latency` as first-class affordance fields (folded into `CostVector.seconds` and the `required_approvals` gate until a consumer needs them separately).

---

### Task 1: Three-axis epistemic tags (`aragora/reasoning/epistemics.py`)

**Files:**
- Create: `aragora/reasoning/epistemics.py`
- Test: `tests/reasoning/test_epistemics.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces (used by Tasks 2 and 3):
  - `class KnowledgeState(str, Enum)` — values `KNOWN, ESTIMATED, UNKNOWN, CONFLICTED, STALE, NOT_OBSERVABLE, REDACTED, INDETERMINATE, NOT_APPLICABLE`
  - `class ProvenanceClass(str, Enum)` — values `OBSERVED, OPERATOR_ASSERTED, POLICY, REMEMBERED, VENDOR_CLAIMED, DERIVED, PREDICTED`
  - `class HypothesisDisposition(str, Enum)` — values `LIVE, SUPPORTED, DISFAVORED, REFUTED, SUPERSEDED`
  - `AUTHORITY_RANK: dict[ProvenanceClass, int]` — lower is more authoritative
  - `@dataclass(slots=True) class EpistemicTag(state: KnowledgeState, provenance: ProvenanceClass, disposition: HypothesisDisposition | None = None, observed_at: float | None = None, ttl_seconds: float | None = None, basis: list[str] = [])` with methods `authority_rank() -> int`, `effective_state(now: float) -> KnowledgeState`, `to_dict() -> dict[str, Any]`
  - `reconcile(claimed_value: object, claimed: EpistemicTag, live_value: object, live: EpistemicTag) -> tuple[object, EpistemicTag]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/reasoning/test_epistemics.py
"""Tests for three-axis epistemic tags."""

from aragora.reasoning.epistemics import (
    AUTHORITY_RANK,
    EpistemicTag,
    KnowledgeState,
    ProvenanceClass,
    reconcile,
)


def _tag(state=KnowledgeState.KNOWN, prov=ProvenanceClass.OBSERVED, **kw) -> EpistemicTag:
    return EpistemicTag(state=state, provenance=prov, **kw)


class TestAuthorityRank:
    def test_observed_outranks_everything(self):
        observed = AUTHORITY_RANK[ProvenanceClass.OBSERVED]
        for prov in ProvenanceClass:
            assert observed <= AUTHORITY_RANK[prov]

    def test_derived_and_predicted_are_weakest(self):
        assert AUTHORITY_RANK[ProvenanceClass.DERIVED] > AUTHORITY_RANK[ProvenanceClass.REMEMBERED]
        assert AUTHORITY_RANK[ProvenanceClass.PREDICTED] > AUTHORITY_RANK[ProvenanceClass.DERIVED]

    def test_every_provenance_class_has_a_rank(self):
        assert set(AUTHORITY_RANK) == set(ProvenanceClass)


class TestEffectiveState:
    def test_known_within_ttl_stays_known(self):
        tag = _tag(observed_at=1000.0, ttl_seconds=60.0)
        assert tag.effective_state(now=1030.0) is KnowledgeState.KNOWN

    def test_known_past_ttl_degrades_to_stale(self):
        tag = _tag(observed_at=1000.0, ttl_seconds=60.0)
        assert tag.effective_state(now=1061.0) is KnowledgeState.STALE

    def test_estimated_past_ttl_degrades_to_stale(self):
        tag = _tag(state=KnowledgeState.ESTIMATED, observed_at=1000.0, ttl_seconds=60.0)
        assert tag.effective_state(now=1061.0) is KnowledgeState.STALE

    def test_conflicted_never_silently_improves(self):
        tag = _tag(state=KnowledgeState.CONFLICTED, observed_at=1000.0, ttl_seconds=60.0)
        assert tag.effective_state(now=1061.0) is KnowledgeState.CONFLICTED

    def test_no_ttl_means_no_decay(self):
        tag = _tag(observed_at=1000.0)
        assert tag.effective_state(now=10_000_000.0) is KnowledgeState.KNOWN


class TestReconcile:
    def test_ready_claim_vs_blocked_live_fact_is_conflicted(self):
        """The measured failure: a derived recommendation says 'ready' while
        the observed settlement state says 'blocked'. The observed value wins
        and the result is marked CONFLICTED so no consumer treats it as settled."""
        claimed = _tag(state=KnowledgeState.ESTIMATED, prov=ProvenanceClass.DERIVED, basis=["work:rec:42"])
        live = _tag(prov=ProvenanceClass.OBSERVED, basis=["gh:pr:9932:mergeStateStatus"])
        value, tag = reconcile("ready", claimed, "blocked", live)
        assert value == "blocked"
        assert tag.state is KnowledgeState.CONFLICTED
        assert tag.provenance is ProvenanceClass.OBSERVED
        assert "work:rec:42" in tag.basis and "gh:pr:9932:mergeStateStatus" in tag.basis

    def test_agreement_keeps_higher_authority_tag_unmarked(self):
        claimed = _tag(state=KnowledgeState.ESTIMATED, prov=ProvenanceClass.DERIVED)
        live = _tag(prov=ProvenanceClass.OBSERVED)
        value, tag = reconcile("green", claimed, "green", live)
        assert value == "green"
        assert tag.state is KnowledgeState.KNOWN
        assert tag.provenance is ProvenanceClass.OBSERVED

    def test_higher_authority_claim_beats_lower_authority_live(self):
        claimed = _tag(prov=ProvenanceClass.OPERATOR_ASSERTED)
        live = _tag(state=KnowledgeState.ESTIMATED, prov=ProvenanceClass.PREDICTED)
        value, tag = reconcile("halt", claimed, "proceed", live)
        assert value == "halt"
        assert tag.state is KnowledgeState.CONFLICTED


class TestSerialization:
    def test_to_dict_round_trips_enum_values_as_strings(self):
        tag = _tag(observed_at=5.0, ttl_seconds=10.0, basis=["a"])
        d = tag.to_dict()
        assert d["state"] == "known"
        assert d["provenance"] == "observed"
        assert d["disposition"] is None
        assert d["observed_at"] == 5.0
        assert d["basis"] == ["a"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/reasoning/test_epistemics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aragora.reasoning.epistemics'`

- [ ] **Step 3: Write the implementation**

```python
# aragora/reasoning/epistemics.py
"""Three-axis epistemic tags: knowledge state x provenance authority x disposition.

A single confidence scalar hides the difference between "we checked and it is
false", "we have not checked", "two authorities disagree", and "we are not
allowed to see it". Agent-facing read models (orientation envelopes, work
recommendations, situation frames) tag every derived record on three
orthogonal axes instead.

``ProvenanceClass`` is an *authority class* used for precedence decisions.
It is deliberately distinct from ``aragora.reasoning.provenance.SourceType``,
which records the channel a piece of evidence arrived through (web search,
document, database, ...). A fact can be ``SourceType.EXTERNAL_API`` and
``ProvenanceClass.OBSERVED`` at the same time.

Tagging convention: a deterministic computation that is exactly reproducible
from its anchored inputs (e.g. repo cleanliness computed from ``git status``)
may keep ``OBSERVED``; anything involving model inference, heuristics, or
sampling must be ``DERIVED`` or ``PREDICTED``. Summaries never gain authority:
``reconcile`` always resolves value disputes toward the lower rank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "AUTHORITY_RANK",
    "EpistemicTag",
    "HypothesisDisposition",
    "KnowledgeState",
    "ProvenanceClass",
    "reconcile",
]


class KnowledgeState(str, Enum):
    """What the system can currently say about a fact."""

    KNOWN = "known"  # positively established from an authoritative source
    ESTIMATED = "estimated"  # best-effort value with quantified uncertainty
    UNKNOWN = "unknown"  # not yet queried
    CONFLICTED = "conflicted"  # authorities disagree; must not be treated as settled
    STALE = "stale"  # was known/estimated, validity window has lapsed
    NOT_OBSERVABLE = "not_observable"  # source unavailable or unhealthy
    REDACTED = "redacted"  # withheld by security/tenancy policy
    INDETERMINATE = "indeterminate"  # queried, but the source could not decide
    NOT_APPLICABLE = "not_applicable"  # the question does not apply here


class ProvenanceClass(str, Enum):
    """Authority class of the producer, ordered by ``AUTHORITY_RANK``."""

    OBSERVED = "observed"  # exact git/API/lease/halt facts
    OPERATOR_ASSERTED = "operator_asserted"  # human settlement or steering
    POLICY = "policy"  # operating contract / configuration
    REMEMBERED = "remembered"  # KM / continuum / supermemory recall
    VENDOR_CLAIMED = "vendor_claimed"  # third-party self-reports
    DERIVED = "derived"  # computed joins, model analysis
    PREDICTED = "predicted"  # forecasts


AUTHORITY_RANK: dict[ProvenanceClass, int] = {
    ProvenanceClass.OBSERVED: 0,
    ProvenanceClass.OPERATOR_ASSERTED: 1,
    ProvenanceClass.POLICY: 1,
    ProvenanceClass.REMEMBERED: 2,
    ProvenanceClass.VENDOR_CLAIMED: 3,
    ProvenanceClass.DERIVED: 4,
    ProvenanceClass.PREDICTED: 5,
}


class HypothesisDisposition(str, Enum):
    """Where a competing interpretation currently stands."""

    LIVE = "live"  # still on the table, undecided
    SUPPORTED = "supported"  # evidence favors it
    DISFAVORED = "disfavored"  # evidence weighs against it, not eliminated
    REFUTED = "refuted"  # positively eliminated by evidence
    SUPERSEDED = "superseded"  # replaced by a sharper hypothesis

_DECAYABLE = frozenset({KnowledgeState.KNOWN, KnowledgeState.ESTIMATED})


@dataclass(slots=True)
class EpistemicTag:
    """Per-record tag carrying all three axes plus freshness and basis."""

    state: KnowledgeState
    provenance: ProvenanceClass
    disposition: HypothesisDisposition | None = None
    observed_at: float | None = None  # epoch seconds
    ttl_seconds: float | None = None
    basis: list[str] = field(default_factory=list)  # evidence refs / fingerprints

    def authority_rank(self) -> int:
        return AUTHORITY_RANK[self.provenance]

    def effective_state(self, now: float) -> KnowledgeState:
        """State after applying freshness decay.

        Only positive states decay to STALE; CONFLICTED, REDACTED and friends
        never silently improve or change through the passage of time.
        """
        if (
            self.state in _DECAYABLE
            and self.observed_at is not None
            and self.ttl_seconds is not None
            and now > self.observed_at + self.ttl_seconds
        ):
            return KnowledgeState.STALE
        return self.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "provenance": self.provenance.value,
            "disposition": self.disposition.value if self.disposition else None,
            "observed_at": self.observed_at,
            "ttl_seconds": self.ttl_seconds,
            "basis": list(self.basis),
        }


def reconcile(
    claimed_value: object,
    claimed: EpistemicTag,
    live_value: object,
    live: EpistemicTag,
) -> tuple[object, EpistemicTag]:
    """Resolve a claimed value against a live fact.

    The higher-authority side supplies the value. When the values disagree the
    resulting tag is CONFLICTED (carrying both bases) so no consumer can treat
    the claim as settled: a lower-authority recommendation can never override
    a higher-authority blocker, and the contradiction stays visible. At equal
    authority rank the live side wins the tie and supplies the value. The
    CONFLICTED tag intentionally resets ``observed_at``, ``ttl_seconds``, and
    ``disposition`` to their defaults — the conflict itself is a fresh finding,
    not an aging of either input fact.
    """
    if live.authority_rank() <= claimed.authority_rank():
        winner_value, winner, loser = live_value, live, claimed
    else:
        winner_value, winner, loser = claimed_value, claimed, live

    if claimed_value == live_value:
        return winner_value, winner
    return winner_value, EpistemicTag(
        state=KnowledgeState.CONFLICTED,
        provenance=winner.provenance,
        basis=[*winner.basis, *loser.basis],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/reasoning/test_epistemics.py -v`
Expected: all PASS

- [ ] **Step 5: Lint, typecheck, commit**

Run: `ruff check aragora/reasoning/epistemics.py tests/reasoning/test_epistemics.py && make ci-required`
Expected: clean

```bash
git add aragora/reasoning/epistemics.py tests/reasoning/test_epistemics.py
git commit -m "feat(reasoning): add three-axis epistemic tags (knowledge state, provenance authority, disposition)"
```

---

### Task 2: Action affordances with hard gates and a nondominated frontier (`aragora/work/affordances.py`)

**Files:**
- Create: `aragora/work/affordances.py`
- Create: `tests/work/__init__.py` (empty file; the suite uses package-style test dirs)
- Test: `tests/work/test_affordances.py`

**Interfaces:**
- Consumes: `EpistemicTag`, `KnowledgeState`, `ProvenanceClass` from Task 1 (`aragora.reasoning.epistemics`); `WorkRecommendation` from `aragora.work.models` (existing, read-only).
- Produces (used by Task 3):
  - `class AffordanceDisposition(str, Enum)` — values `ROBUST, CONDITIONAL, INFORMATION_GATHERING, WAIT_WATCH, BLOCKED, UNAVAILABLE`
  - `@dataclass(slots=True) class CostVector(tokens: int = 0, seconds: float = 0.0, money_usd: float = 0.0, human_attention: int = 0)`
  - `@dataclass(slots=True) class WaitSpec(wake_predicates: list[str], deadline_epoch: float | None, expected_evidence: list[str], fallback_affordance_id: str | None, owner: str, cancellation: str)`
  - `@dataclass(slots=True) class ActionAffordance(...)` — full field list in the implementation below; key methods `to_dict() -> dict[str, Any]`
  - `apply_hard_gates(candidates: Sequence[ActionAffordance], *, halted: bool = False, capabilities_held: frozenset[str] = frozenset(), approvals_granted: frozenset[str] = frozenset(), live_blockers: Mapping[str, Sequence[str]] | None = None) -> list[ActionAffordance]` — live prohibitions (blockers/halt) dominate → BLOCKED (truncation-safe); pure capability/approval lack → UNAVAILABLE; idempotent; halt is terminal on already-non-actionable candidates; gates only ever downgrade
  - `pareto_frontier(candidates: Sequence[ActionAffordance]) -> list[ActionAffordance]`
  - `from_work_recommendation(rec: WorkRecommendation, *, live_blockers: Sequence[str] = ()) -> ActionAffordance`

- [ ] **Step 1: Write the failing tests**

```python
# tests/work/test_affordances.py
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
        gated = {g.affordance_id: g for g in apply_hard_gates(acts, live_blockers={"a": ["lease conflict"]})}
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
        gated_live = apply_hard_gates(
            [aff], live_blockers={aff.affordance_id: ["lease conflict"]}
        )
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
        needs_approval = _aff(
            "approval", value=1.0, cost=CostVector(tokens=100, human_attention=2)
        )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/work/test_affordances.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aragora.work.affordances'`

- [ ] **Step 3: Write the implementation**

```python
# aragora/work/affordances.py
"""Action affordances: explicit next-move records with gates before ranking.

Replaces opaque universal scores in agent-facing views. Every candidate next
move carries its own cost vector, risk tier, preconditions, invalidators, and
expected terminal proof. Hard authority/safety gates (halt, capabilities,
live blockers) are applied BEFORE ranking, and ranking returns a nondominated
Pareto frontier rather than a single winner, so tradeoffs stay visible.

``wait/watch`` is itself an affordance (with wake predicates, deadline,
fallback, and cancellation semantics) so "the right move is to wait" competes
explicitly with acting.

Prior art: ``aragora.routing.decision_stakes_router`` records an unconstrained
Pareto frontier for model routing; this module applies the same philosophy to
work selection. Additive: does not modify ``aragora.work.models``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from aragora.reasoning.epistemics import (
    EpistemicTag,
    KnowledgeState,
    ProvenanceClass,
    reconcile,
)
from aragora.work.models import WorkRecommendation

__all__ = [
    "ActionAffordance",
    "AffordanceDisposition",
    "CostVector",
    "WaitSpec",
    "apply_hard_gates",
    "from_work_recommendation",
    "pareto_frontier",
]


class AffordanceDisposition(str, Enum):
    """Control-envelope classification of a candidate action."""

    ROBUST = "robust"  # safe under every live interpretation
    CONDITIONAL = "conditional"  # safe only in named worlds / predicates
    INFORMATION_GATHERING = "information_gathering"  # read-only probe
    WAIT_WATCH = "wait_watch"  # deliberate wait with wake conditions
    BLOCKED = "blocked"  # a live authority forbids it right now
    UNAVAILABLE = "unavailable"  # missing capability or approval

_ACTIONABLE = frozenset(
    {
        AffordanceDisposition.ROBUST,
        AffordanceDisposition.CONDITIONAL,
        AffordanceDisposition.INFORMATION_GATHERING,
        AffordanceDisposition.WAIT_WATCH,
    }
)

# Dispositions exempt from the halt gate: they observe, never mutate.
_HALT_EXEMPT = frozenset(
    {AffordanceDisposition.WAIT_WATCH, AffordanceDisposition.INFORMATION_GATHERING}
)

# Already-downgraded dispositions: terminal for the halt gate (re-gating
# gated output must not re-fire halt against a lost intrinsic disposition).
_NON_ACTIONABLE = frozenset(
    {AffordanceDisposition.BLOCKED, AffordanceDisposition.UNAVAILABLE}
)


@dataclass(slots=True)
class CostVector:
    """Multi-axis cost; axes are minimized independently by the frontier."""

    tokens: int = 0
    seconds: float = 0.0
    money_usd: float = 0.0
    human_attention: int = 0  # 0 none, 1 notify, 2 approval required

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "seconds": self.seconds,
            "money_usd": self.money_usd,
            "human_attention": self.human_attention,
        }


@dataclass(slots=True)
class WaitSpec:
    """Semantics that make waiting a first-class, cancellable action."""

    wake_predicates: list[str]
    deadline_epoch: float | None
    expected_evidence: list[str]
    fallback_affordance_id: str | None
    owner: str
    cancellation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "wake_predicates": list(self.wake_predicates),
            "deadline_epoch": self.deadline_epoch,
            "expected_evidence": list(self.expected_evidence),
            "fallback_affordance_id": self.fallback_affordance_id,
            "owner": self.owner,
            "cancellation": self.cancellation,
        }


@dataclass(slots=True)
class ActionAffordance:
    """One candidate next move with everything needed to judge it."""

    affordance_id: str
    target: str
    operation: str
    reason_available: str
    disposition: AffordanceDisposition
    expected_gain: str
    expected_value: float
    cost: CostVector
    risk_tier: int  # 0-4 per the operating contract
    reversibility: str  # "reversible" | "compensable" | "irreversible"
    required_capabilities: list[str]
    required_approvals: list[str]
    preconditions: list[str]
    invalidators: list[str]
    alternatives: list[str]
    expected_terminal_proof: str
    epistemics: EpistemicTag | None = None
    wait: WaitSpec | None = None
    blocked_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "affordance_id": self.affordance_id,
            "target": self.target,
            "operation": self.operation,
            "reason_available": self.reason_available,
            "disposition": self.disposition.value,
            "expected_gain": self.expected_gain,
            "expected_value": self.expected_value,
            "cost": self.cost.to_dict(),
            "risk_tier": self.risk_tier,
            "reversibility": self.reversibility,
            "required_capabilities": list(self.required_capabilities),
            "required_approvals": list(self.required_approvals),
            "preconditions": list(self.preconditions),
            "invalidators": list(self.invalidators),
            "alternatives": list(self.alternatives),
            "expected_terminal_proof": self.expected_terminal_proof,
            "epistemics": self.epistemics.to_dict() if self.epistemics else None,
            "wait": self.wait.to_dict() if self.wait else None,
            "blocked_by": list(self.blocked_by),
        }


def _merged_reasons(cand: ActionAffordance, new_reasons: Iterable[str]) -> list[str]:
    """Pre-existing ``blocked_by`` first, then new gate reasons, deduplicated.

    Order-preserving dedup makes gating idempotent: re-gating already-gated
    output never duplicates a reason.
    """
    return list(dict.fromkeys([*cand.blocked_by, *new_reasons]))


def apply_hard_gates(
    candidates: Sequence[ActionAffordance],
    *,
    halted: bool = False,
    capabilities_held: frozenset[str] = frozenset(),
    approvals_granted: frozenset[str] = frozenset(),
    live_blockers: Mapping[str, Sequence[str]] | None = None,
) -> list[ActionAffordance]:
    """Downgrade dispositions per live authority BEFORE any ranking happens.

    Never removes items: a blocked action stays visible as blocked, which is
    the point — the agent sees what it cannot do and why. Inputs are not
    mutated; downgraded copies are returned, with pre-existing ``blocked_by``
    entries preserved first and all reasons order-preserving-deduplicated, so
    gating is idempotent: re-gating already-gated output changes nothing.

    Precedence: a live-authority prohibition (a live blocker, or halt on an
    actionable non-exempt candidate) downgrades to BLOCKED and dominates a
    capability/approval lack — BLOCKED survives situation-frame truncation,
    so a live blocker can never be silently dropped under budget pressure —
    while a pure lack of required capabilities or approvals downgrades to
    UNAVAILABLE (approvals are a hard gate, not advice). Already-non-
    actionable candidates are terminal for the halt gate and pass through
    unchanged unless a live blocker names them, which (re)classifies them
    BLOCKED. A live blocker downgrades a still-actionable candidate even when
    its reason string is already recorded in ``blocked_by`` — a recorded
    reason is not the same as an applied downgrade. Gates only ever
    downgrade: re-gating with a relaxed gate (e.g. after a halt lifts) never
    recovers a candidate — recompute affordances from their original source
    to recover. Diagnostics are consequently path-dependent: gates applied
    across successive passes may record fewer ``blocked_by`` reasons than one
    combined pass (a terminal candidate skips later halt marking), though the
    non-actionable classification itself is identical either way.
    """
    blockers_by_id = dict(live_blockers or {})
    gated: list[ActionAffordance] = []
    for cand in candidates:
        live_reasons: list[str] = list(blockers_by_id.get(cand.affordance_id, ()))
        missing = [c for c in cand.required_capabilities if c not in capabilities_held]
        unapproved = [a for a in cand.required_approvals if a not in approvals_granted]
        non_actionable = cand.disposition in _NON_ACTIONABLE
        halt_applies = halted and not non_actionable and cand.disposition not in _HALT_EXEMPT
        prohibitions = [*live_reasons, *(["halt"] if halt_applies else [])]
        lacks = [
            *(f"missing capability: {c}" for c in missing),
            *(f"missing approval: {a}" for a in unapproved),
        ]
        if prohibitions:
            gated.append(
                replace(
                    cand,
                    disposition=AffordanceDisposition.BLOCKED,
                    blocked_by=_merged_reasons(cand, [*prohibitions, *lacks]),
                )
            )
        elif non_actionable:
            gated.append(cand)
        elif lacks:
            gated.append(
                replace(
                    cand,
                    disposition=AffordanceDisposition.UNAVAILABLE,
                    blocked_by=_merged_reasons(cand, lacks),
                )
            )
        else:
            gated.append(cand)
    return gated


def _frontier_key(a: ActionAffordance) -> tuple[float, float, float, float, float, float]:
    """All-minimized objective tuple (value negated so higher value is better)."""
    return (
        -a.expected_value,
        float(a.cost.tokens),
        a.cost.seconds,
        a.cost.money_usd,
        float(a.risk_tier),
        float(a.cost.human_attention),
    )


def _dominates(a: ActionAffordance, b: ActionAffordance) -> bool:
    ka, kb = _frontier_key(a), _frontier_key(b)
    return all(x <= y for x, y in zip(ka, kb)) and ka != kb


def pareto_frontier(candidates: Sequence[ActionAffordance]) -> list[ActionAffordance]:
    """Nondominated actionable candidates; blocked/unavailable never rank."""
    actionable = [c for c in candidates if c.disposition in _ACTIONABLE]
    return [c for c in actionable if not any(_dominates(o, c) for o in actionable)]


def from_work_recommendation(
    rec: WorkRecommendation,
    *,
    live_blockers: Sequence[str] = (),
) -> ActionAffordance:
    """Adapt an existing WorkRecommendation into an explicit affordance.

    The recommendation's own view of actionability (DERIVED authority) is
    reconciled against live blockers (OBSERVED authority): a clean rec that a
    live authority contradicts becomes CONFLICTED, never silently 'ready'.

    WorkRecommendation carries no cost or risk data, so adapter-produced
    affordances default to a zero CostVector and risk_tier 0; among such
    candidates alone the frontier degenerates to highest ``score.total``.
    Callers with real cost/risk estimates should set them on the result for
    the frontier's tradeoff axes to bite.
    """
    claimed_tag = EpistemicTag(
        state=KnowledgeState.ESTIMATED,
        provenance=ProvenanceClass.DERIVED,
        basis=[f"work:rec:{rec.item_id}"],
    )
    rec_actionable = not rec.blockers
    if live_blockers:
        live_tag = EpistemicTag(
            state=KnowledgeState.KNOWN,
            provenance=ProvenanceClass.OBSERVED,
            basis=[f"live:{b}" for b in live_blockers],
        )
        _, tag = reconcile(rec_actionable, claimed_tag, False, live_tag)
    else:
        tag = claimed_tag

    blocked = list(dict.fromkeys([*rec.blockers, *live_blockers]))
    return ActionAffordance(
        affordance_id=f"work:{rec.item_id}",
        target=rec.item_id,
        operation=rec.action,
        reason_available="; ".join(rec.rationale) or "recommended by work broker",
        disposition=AffordanceDisposition.BLOCKED if blocked else AffordanceDisposition.CONDITIONAL,
        expected_gain=f"{rec.classification} ({rec.priority})",
        expected_value=rec.score.total,
        cost=CostVector(),
        risk_tier=0,
        reversibility="reversible",
        required_capabilities=[],
        required_approvals=[],
        preconditions=[],
        invalidators=list(live_blockers),
        alternatives=[],
        expected_terminal_proof="work item transitions per its acceptance criteria",
        epistemics=tag,
        blocked_by=blocked,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/work/test_affordances.py tests/reasoning/test_epistemics.py -v`
Expected: all PASS (Task 1 tests must still pass — this task imports its module)

- [ ] **Step 5: Lint, typecheck, commit**

Run: `ruff check aragora/work/affordances.py tests/work/ && make ci-required`
Expected: clean

```bash
git add aragora/work/affordances.py tests/work/__init__.py tests/work/test_affordances.py
git commit -m "feat(work): add ActionAffordance model with hard gates and Pareto frontier ranking"
```

---

### Task 3: Situation envelopes with protected truncation (`aragora/reasoning/situation_frame.py`)

**Files:**
- Create: `aragora/reasoning/situation_frame.py`
- Test: `tests/reasoning/test_situation_frame.py`

**Interfaces:**
- Consumes: `EpistemicTag` from Task 1; `ActionAffordance`, `AffordanceDisposition` from Task 2; `ReceiptDissent` from `aragora.export.decision_receipt` (existing, read-only).
- Produces (consumed later by the tower's `aragora orient` layer, PR #9932 follow-on):
  - `@dataclass(slots=True) class EvidenceFact(fact_id: str, statement: str, tag: EpistemicTag, evidence_refs: list[str])`
  - `@dataclass(slots=True) class PossibilityResidual(residual_id: str, description: str, loss_severity: float, source: str = "", consistent_with_evidence: bool = True)`
  - `@dataclass(slots=True) class EvidenceEnvelope(facts, certified_absences: list[str], assumptions: list[str])`
  - `@dataclass(slots=True) class PossibilityEnvelope(residuals, protected_floor: float = 0.5)` with `protected() -> list[PossibilityResidual]`
  - `@dataclass(slots=True) class ControlEnvelope(affordances: list[ActionAffordance])`
  - `@dataclass(slots=True) class SituationFrame(anchor: dict[str, str], evidence, possibility, control, generated_at: float)` with `to_dict()`
  - `@dataclass(slots=True) class TruncationReport(emitted_bytes: int, budget_bytes: int, dropped_residuals: int, dropped_affordances: int, over_budget: bool, protected_retained: int)`
  - `from_receipt_dissents(dissents: Iterable[ReceiptDissent]) -> list[PossibilityResidual]`
  - `truncate_frame(frame: SituationFrame, budget_bytes: int) -> tuple[SituationFrame, TruncationReport]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/reasoning/test_situation_frame.py
"""Tests for evidence/possibility/control envelopes and protected truncation."""

import json

from aragora.export.decision_receipt import ReceiptDissent
from aragora.reasoning.epistemics import EpistemicTag, KnowledgeState, ProvenanceClass
from aragora.reasoning.situation_frame import (
    ControlEnvelope,
    EvidenceEnvelope,
    EvidenceFact,
    PossibilityEnvelope,
    PossibilityResidual,
    SituationFrame,
    from_receipt_dissents,
    truncate_frame,
)
from aragora.work.affordances import ActionAffordance, AffordanceDisposition, CostVector


def _fact(fid: str) -> EvidenceFact:
    return EvidenceFact(
        fact_id=fid,
        statement=f"fact {fid}",
        tag=EpistemicTag(state=KnowledgeState.KNOWN, provenance=ProvenanceClass.OBSERVED),
        evidence_refs=[f"ref:{fid}"],
    )


def _residual(rid: str, severity: float) -> PossibilityResidual:
    return PossibilityResidual(
        residual_id=rid,
        description=f"alternative world {rid} " + "x" * 40,
        loss_severity=severity,
        source="agent-red",
    )


def _aff(aid: str, disposition: AffordanceDisposition) -> ActionAffordance:
    return ActionAffordance(
        affordance_id=aid,
        target="t",
        operation="op",
        reason_available="r",
        disposition=disposition,
        expected_gain="g",
        expected_value=1.0,
        cost=CostVector(),
        risk_tier=0,
        reversibility="reversible",
        required_capabilities=[],
        required_approvals=[],
        preconditions=[],
        invalidators=[],
        alternatives=[],
        expected_terminal_proof="p",
    )


def _frame(residuals, affordances=()) -> SituationFrame:
    return SituationFrame(
        anchor={"repo": "aragora", "commit": "1aa62825", "branch": "main", "clean": "true"},
        evidence=EvidenceEnvelope(facts=[_fact("f1")], certified_absences=[], assumptions=[]),
        possibility=PossibilityEnvelope(residuals=list(residuals)),
        control=ControlEnvelope(affordances=list(affordances)),
        generated_at=1000.0,
    )


class TestFromReceiptDissents:
    def test_maps_fields_and_preserves_severity(self):
        dissent = ReceiptDissent(
            agent="claude",
            type="safety",
            severity=0.9,
            reasons=["rollback path unproven"],
            alternative="stage behind a flag",
        )
        (residual,) = from_receipt_dissents([dissent])
        assert residual.loss_severity == 0.9
        assert residual.source == "claude"
        assert "rollback path unproven" in residual.description
        assert "stage behind a flag" in residual.description


class TestProtectedTruncation:
    def test_within_budget_drops_nothing_and_reports_truthful_bytes(self):
        frame = _frame([_residual("r1", 0.9)])
        out, report = truncate_frame(frame, budget_bytes=1_000_000)
        assert report.dropped_residuals == 0
        assert not report.over_budget
        assert report.emitted_bytes == len(
            json.dumps(out.to_dict(), separators=(",", ":")).encode("utf-8")
        )

    def test_low_severity_residuals_drop_first_high_severity_survive(self):
        low = [_residual(f"low{i}", 0.1) for i in range(30)]
        high = _residual("high", 0.95)
        frame = _frame([*low, high])
        tight = len(json.dumps(_frame([high]).to_dict(), separators=(",", ":")).encode()) + 200
        out, report = truncate_frame(frame, budget_bytes=tight)
        kept = {r.residual_id for r in out.possibility.residuals}
        assert "high" in kept  # the invariant: high-loss residuals cannot disappear
        assert report.dropped_residuals > 0
        assert report.protected_retained == 1

    def test_protected_overflow_is_reported_never_silently_dropped(self):
        """If protected content alone exceeds the budget, keep it and say so."""
        protected = [_residual(f"p{i}", 0.9) for i in range(50)]
        frame = _frame(protected)
        out, report = truncate_frame(frame, budget_bytes=300)
        assert len(out.possibility.residuals) == 50
        assert report.over_budget
        assert report.emitted_bytes > 300

    def test_blocked_affordances_survive_unavailable_drop(self):
        blocked = _aff("blocked", AffordanceDisposition.BLOCKED)
        unavailable = [_aff(f"u{i}", AffordanceDisposition.UNAVAILABLE) for i in range(30)]
        frame = _frame([], affordances=[blocked, *unavailable])
        tight = len(json.dumps(_frame([], [blocked]).to_dict(), separators=(",", ":")).encode()) + 200
        out, report = truncate_frame(frame, budget_bytes=tight)
        kept = {a.affordance_id for a in out.control.affordances}
        assert "blocked" in kept
        assert report.dropped_affordances > 0

    def test_truncation_preserves_input_order_of_survivors(self):
        hi1 = _residual("hi1", 0.9)
        lo = _residual("lo", 0.1)
        hi2 = _residual("hi2", 0.8)
        frame = _frame([hi1, lo, hi2])
        tight = (
            len(json.dumps(_frame([hi1, hi2]).to_dict(), separators=(",", ":")).encode()) + 100
        )
        out, report = truncate_frame(frame, budget_bytes=tight)
        assert report.dropped_residuals == 1
        assert [r.residual_id for r in out.possibility.residuals] == ["hi1", "hi2"]

    def test_duplicate_residual_ids_do_not_resurrect_dropped(self):
        """The order-restore step must key on object identity: a dropped
        low-severity residual sharing a residual_id with a protected one
        must stay dropped, with truthful accounting."""
        protected = _residual("dup", 0.9)
        droppable = _residual("dup", 0.1)
        pad = [_residual(f"lo{i}", 0.1) for i in range(10)]
        frame = _frame([protected, droppable, *pad])
        tight = len(json.dumps(_frame([protected]).to_dict(), separators=(",", ":")).encode()) + 100
        out, report = truncate_frame(frame, budget_bytes=tight)
        kept = [(r.residual_id, r.loss_severity) for r in out.possibility.residuals]
        assert ("dup", 0.9) in kept
        assert ("dup", 0.1) not in kept
        assert report.dropped_residuals == 11
        assert len(out.possibility.residuals) == 1

    def test_evidence_facts_are_never_dropped(self):
        frame = _frame([_residual(f"r{i}", 0.1) for i in range(20)])
        out, _ = truncate_frame(frame, budget_bytes=100)
        assert [f.fact_id for f in out.evidence.facts] == ["f1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/reasoning/test_situation_frame.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aragora.reasoning.situation_frame'`

- [ ] **Step 3: Write the implementation**

```python
# aragora/reasoning/situation_frame.py
"""Evidence-possibility-control envelopes for agent-facing situation views.

A situation frame separates what is established (evidence envelope) from what
remains materially possible (possibility envelope) from what can be done about
it (control envelope). The load-bearing invariant lives in ``truncate_frame``:

    A high-loss residual cannot disappear because it has a low rank, a low
    posterior, an inconvenient token cost, or because a reranker prefers a
    benign interpretation.

This extends Aragora's dissent-preservation guarantee (ReceiptDissent,
severity-gated dissent) through summarization: budget pressure may drop
low-severity residuals and unavailable affordances, but protected residuals,
blocked affordances, and evidence facts always survive — and when they alone
exceed the budget, the frame is emitted over budget with a truthful
``TruncationReport`` rather than silently thinned.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from aragora.export.decision_receipt import ReceiptDissent
from aragora.reasoning.epistemics import EpistemicTag
from aragora.work.affordances import ActionAffordance, AffordanceDisposition

__all__ = [
    "ControlEnvelope",
    "EvidenceEnvelope",
    "EvidenceFact",
    "PossibilityEnvelope",
    "PossibilityResidual",
    "SituationFrame",
    "TruncationReport",
    "from_receipt_dissents",
    "truncate_frame",
]


@dataclass(slots=True)
class EvidenceFact:
    """A positively established fact with its epistemic tag and references."""

    fact_id: str
    statement: str
    tag: EpistemicTag
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "statement": self.statement,
            "tag": self.tag.to_dict(),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(slots=True)
class PossibilityResidual:
    """An alternative interpretation still consistent with the evidence."""

    residual_id: str
    description: str
    loss_severity: float  # 0.0-1.0: how bad it is if this world is real and ignored
    source: str = ""
    consistent_with_evidence: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "residual_id": self.residual_id,
            "description": self.description,
            "loss_severity": self.loss_severity,
            "source": self.source,
            "consistent_with_evidence": self.consistent_with_evidence,
        }


@dataclass(slots=True)
class EvidenceEnvelope:
    facts: list[EvidenceFact] = field(default_factory=list)
    certified_absences: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": [f.to_dict() for f in self.facts],
            "certified_absences": list(self.certified_absences),
            "assumptions": list(self.assumptions),
        }


@dataclass(slots=True)
class PossibilityEnvelope:
    residuals: list[PossibilityResidual] = field(default_factory=list)
    protected_floor: float = 0.5  # residuals at/above this severity are protected

    def protected(self) -> list[PossibilityResidual]:
        return [r for r in self.residuals if r.loss_severity >= self.protected_floor]

    def to_dict(self) -> dict[str, Any]:
        return {
            "residuals": [r.to_dict() for r in self.residuals],
            "protected_floor": self.protected_floor,
        }


@dataclass(slots=True)
class ControlEnvelope:
    affordances: list[ActionAffordance] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"affordances": [a.to_dict() for a in self.affordances]}


@dataclass(slots=True)
class SituationFrame:
    anchor: dict[str, str]  # repo / commit / branch / cleanliness identity
    evidence: EvidenceEnvelope
    possibility: PossibilityEnvelope
    control: ControlEnvelope
    generated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor": dict(self.anchor),
            "evidence": self.evidence.to_dict(),
            "possibility": self.possibility.to_dict(),
            "control": self.control.to_dict(),
            "generated_at": self.generated_at,
        }


@dataclass(slots=True)
class TruncationReport:
    """Truthful account of what a budget cut actually did."""

    emitted_bytes: int
    budget_bytes: int
    dropped_residuals: int
    dropped_affordances: int
    over_budget: bool
    protected_retained: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "emitted_bytes": self.emitted_bytes,
            "budget_bytes": self.budget_bytes,
            "dropped_residuals": self.dropped_residuals,
            "dropped_affordances": self.dropped_affordances,
            "over_budget": self.over_budget,
            "protected_retained": self.protected_retained,
        }


def from_receipt_dissents(dissents: Iterable[ReceiptDissent]) -> list[PossibilityResidual]:
    """Adapt receipt dissent records into possibility residuals."""
    residuals: list[PossibilityResidual] = []
    for i, d in enumerate(dissents):
        parts = ["; ".join(d.reasons)] if d.reasons else []
        if d.alternative:
            parts.append(f"alternative: {d.alternative}")
        residuals.append(
            PossibilityResidual(
                residual_id=f"dissent:{d.agent}:{i}",
                description=f"[{d.type}] " + " | ".join(parts),
                loss_severity=d.severity,
                source=d.agent,
            )
        )
    return residuals


def _frame_bytes(frame: SituationFrame) -> int:
    return len(json.dumps(frame.to_dict(), separators=(",", ":")).encode("utf-8"))


def truncate_frame(
    frame: SituationFrame, budget_bytes: int
) -> tuple[SituationFrame, TruncationReport]:
    """Cut the frame down toward ``budget_bytes`` without losing protection.

    Drop order: unprotected residuals (lowest severity first), then
    UNAVAILABLE affordances. Protected residuals, all other affordances
    (notably BLOCKED ones), evidence facts, and the anchor are never dropped.
    If the protected core alone exceeds the budget the frame is returned
    over budget with a truthful report — never silently thinned.
    """
    dropped_residuals = 0
    dropped_affordances = 0

    current = frame
    if _frame_bytes(current) > budget_bytes:
        floor = current.possibility.protected_floor
        original_order = list(current.possibility.residuals)
        keep = sorted(original_order, key=lambda r: r.loss_severity)
        while keep and _frame_bytes(current) > budget_bytes and keep[0].loss_severity < floor:
            keep.pop(0)
            dropped_residuals += 1
            current = replace(
                current,
                possibility=replace(current.possibility, residuals=list(keep)),
            )
        if dropped_residuals:
            # Survivors keep the caller's ordering; drop order was only a
            # severity policy, not a presentation change. Same elements mean
            # the same serialized byte count, so mid-loop measurements hold.
            # Keyed on object identity, not residual_id: duplicate ids must
            # not resurrect a dropped residual.
            kept = {id(r) for r in keep}
            current = replace(
                current,
                possibility=replace(
                    current.possibility,
                    residuals=[r for r in original_order if id(r) in kept],
                ),
            )

    if _frame_bytes(current) > budget_bytes:
        affs = list(current.control.affordances)
        removable = [a for a in affs if a.disposition is AffordanceDisposition.UNAVAILABLE]
        while removable and _frame_bytes(current) > budget_bytes:
            victim = removable.pop()
            affs.remove(victim)
            dropped_affordances += 1
            current = replace(current, control=ControlEnvelope(affordances=list(affs)))

    emitted = _frame_bytes(current)
    return current, TruncationReport(
        emitted_bytes=emitted,
        budget_bytes=budget_bytes,
        dropped_residuals=dropped_residuals,
        dropped_affordances=dropped_affordances,
        over_budget=emitted > budget_bytes,
        protected_retained=len(current.possibility.protected()),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/reasoning/test_situation_frame.py tests/work/test_affordances.py tests/reasoning/test_epistemics.py -v`
Expected: all PASS

- [ ] **Step 5: Lint, typecheck, commit**

Run: `ruff check aragora/reasoning/situation_frame.py tests/reasoning/test_situation_frame.py && make ci-required`
Expected: clean

```bash
git add aragora/reasoning/situation_frame.py tests/reasoning/test_situation_frame.py
git commit -m "feat(reasoning): add situation envelopes with dissent-protected truncation"
```

---

## Parked follow-on work (explicitly NOT in this plan)

- **Adoption into `aragora orient`** — owned by the Agent Operating Tower run (PR #9932). Once its orientation envelope merges, wire `SituationFrame` in as the envelope's typed body and `truncate_frame` as its 16KB budget enforcer. Coordinate with that lane's owner; do not pre-empt.
- **`WorkRecommendation` emitting affordances natively** — changes an existing public surface; propose as its own batch after the adapter has real consumers.
- **Receipt schema changes** (tagging `ReceiptVerification` with `EpistemicTag`) — receipt schemas are governance-adjacent; Tier 3–4, park for human settlement.
- **Wake-predicate execution** for `WaitSpec` (actual watchers/schedulers) — the control-plane scheduler owns execution; this plan only defines the declarative record.

## Verification checklist per batch (repo governance)

1. `pytest <task test files> -v` green.
2. `ruff check` on new files; `make ci-required` locally.
3. Draft PR → 5 required checks green → ready → full suite + `aragora-merge-quorum`.
4. PR body includes a "Reviewed design tradeoffs" section (nitpick-treadmill cure) noting: the two-enum coexistence with `SourceType`, the deliberate non-import of drone-domain machinery, and the over-budget-rather-than-drop-protected truncation choice.
5. Tier 0–2: normal merge-on-green. Nothing in this plan touches settlement, authority semantics of live gates, or protected files.
