"""Crux cards for standard debates (#8227 / #9046 phase 1).

Attaches the load-bearing disagreements of a *standard* debate to its
result — without changing the debate goal. (Making crux-finding the goal
itself is ``consensus="crux_finder"``; see ``crux_mode.py``.)

Gated by ``DebateProtocol.enable_crux_cards`` (default OFF). When on, the
consensus phase stores a crux-cards block on
``DebateResult.metadata["crux_cards"]``; ``DecisionReceipt.from_debate_result``
carries it additively into ``DecisionReceipt.cruxes``, from which the ODR
export's ``cruxes`` block is populated (previously always the absent marker
for standard debates).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

CRUX_CARDS_METADATA_KEY = "crux_cards"

# An agent that states a claim in a debate is asserting it, so it is not recorded
# at ``add_claim``'s 0.5 default — maximum entropy, i.e. "no opinion" about its
# own claim. Dissent attribution no longer reads belief values at all (#9644
# derives it from edge polarity), so this now feeds only the uncertainty/entropy
# component of ``crux_score`` and propagation dynamics. Deliberately short of
# certainty: an asserted debate claim is a position, not a proof.
_ASSERTED_CONFIDENCE = 0.8


def build_crux_cards(
    *,
    belief_network: Any = None,
    messages: list[Any] | None = None,
    critiques: list[Any] | None = None,
    top_k: int = 5,
    min_score: float = 0.3,
) -> dict[str, Any] | None:
    """Detect cruxes and package them as a crux-cards block.

    Prefers a populated belief network (from the belief-analysis phase);
    falls back to building one from proposer/critic messages. Returns ``None``
    when no crux clears ``min_score`` or there is no material to analyze —
    callers must then leave the result untouched so flag-off behavior stays
    byte-identical.

    ``critiques`` are what make detection possible at all.
    :class:`~aragora.reasoning.crux_detector.CruxDetector` scores a claim by how
    much *authors disagree about it*, which it reads from the network's factor
    edges. A network of claims with no edges therefore always reports zero
    disagreements and zero cruxes, however contested the debate actually was
    (#9581). Each :class:`~aragora.core_types.Critique` already records which
    agent contested whose proposal and how hard (``severity``), so those become
    the ``CONTRADICTS`` edges.
    """
    from aragora.reasoning.crux_detector import CruxDetector

    network = belief_network
    if network is None:
        network = _network_from_messages(messages or [], critiques or [])
    # NOT linked into a supplied ``belief_network``. That network is KM-seeded at
    # debate setup (only when ``enable_km_belief_sync``) and its claim ids are
    # KM-derived, so the message-derived ids here match nothing in it: every
    # ``add_factor`` would no-op while ``add_claim`` left orphan nodes behind in
    # state that ``consensus_storage.get_cruxes`` and crux_finder later read.
    # This function therefore adds no claims and no edges to a supplied network.
    # It is not a full read-only guarantee: `detect_cruxes` below still runs
    # `propagate()`/`compute_resolution_impact()`, which update posteriors on
    # whatever network it is given — pre-existing behaviour, not introduced here.
    # #9581 remains open for KM-belief-sync debates (see #9644).
    if network is None or not getattr(network, "nodes", None):
        return None

    detector = CruxDetector(network=network)
    analysis = detector.detect_cruxes(top_k=top_k, min_score=min_score)
    if not analysis.cruxes:
        return None
    if not analysis.total_disagreements:
        # `crux_score` is a composite, so a claim can clear `min_score` on
        # uncertainty and centrality alone. Emitting those as "crux cards" would
        # publish load-bearing-disagreement claims into a DecisionReceipt with no
        # disagreement actually detected behind them — an overclaim in exactly
        # the surface auditors read. Absent is honest; mislabelled is not.
        #
        # Reached when nothing was contested at all: since #9644 a single
        # CONTRADICTS edge registers a disagreement and names its contester, so
        # any real critique clears this guard.
        logger.info("crux_cards_suppressed_no_disagreement claims=%d", analysis.total_claims)
        return None

    return {
        # CruxClaim.to_dict() carries per-crux dissent attribution:
        # author, contesting_agents, affected_claims, component scores.
        "items": [crux.to_dict() for crux in analysis.cruxes],
        "total_claims": analysis.total_claims,
        "total_disagreements": analysis.total_disagreements,
        "convergence_barrier": round(float(analysis.convergence_barrier), 4),
        "detector": "belief_network",
    }


def _network_from_messages(messages: list[Any], critiques: list[Any] | None = None) -> Any | None:
    try:
        from aragora.reasoning.belief import BeliefNetwork
    except ImportError:
        return None

    network = BeliefNetwork(max_iterations=3)
    added = 0
    for i, msg in enumerate(messages):
        if getattr(msg, "role", "") in ("proposer", "critic"):
            network.add_claim(
                claim_id=f"msg_{i}_{getattr(msg, 'agent', 'unknown')}",
                statement=str(getattr(msg, "content", ""))[:500],
                author=str(getattr(msg, "agent", "unknown")),
                initial_confidence=_ASSERTED_CONFIDENCE,
            )
            added += 1
    if not added:
        return None
    _link_critiques(network, messages, critiques or [])
    return network


def _claim_ids_for_agent(messages: list[Any], agent: str, role: str) -> list[str]:
    """Claim ids of every ``role`` message by ``agent``, in order.

    A list rather than the first match: a critic writes one message per round
    per target, so anchoring every one of their critiques to their *first*
    message would mis-attribute the source statement and stack duplicate
    parallel edges between the same claim pair in a multi-round debate.
    """
    return [
        f"msg_{i}_{agent}"
        for i, msg in enumerate(messages)
        if getattr(msg, "role", "") == role and str(getattr(msg, "agent", "")) == agent
    ]


def _target_claim_for_critique(messages: list[Any], target: str, critique: Any) -> str | None:
    """The claim id of the proposal this critique actually addressed.

    Revisions are recorded with ``role="proposer"`` too, so a target agent has
    one proposer message per round. Always taking the first would attribute a
    round-N critique of a *revised* proposal to the round-1 text — showing stale
    text on the crux card — and would leave revision claims unable to accrue any
    disagreement edge at all.

    ``Critique.target_content`` records the proposal text that was critiqued, so
    it is matched against the proposals rather than guessed.

    Matched by **prefix**, not equality: several agents record only an excerpt
    (``proposal[:200]`` in ``codebase_agent``, ``code_reviewer``,
    ``test_generator``), so an exact comparison would miss every proposal longer
    than the excerpt and silently fall through to the wrong revision. Comparing
    in whichever direction is shorter handles a truncated record and a truncated
    message equally.

    When ``target_content`` is absent or matches nothing, the most recent
    proposal is the better default: it is the target's current position.
    """
    candidates = [
        (i, msg)
        for i, msg in enumerate(messages)
        if getattr(msg, "role", "") == "proposer" and str(getattr(msg, "agent", "")) == target
    ]
    if not candidates:
        return None

    wanted = str(getattr(critique, "target_content", "") or "").strip()
    if wanted:
        # Newest first: a revision commonly keeps the earlier proposal's header
        # or opening paragraph, so a prefix comparison can match round 1 as well
        # as round N. Scanning backwards biases toward the current position —
        # the same bias as the no-match fallback below — instead of silently
        # re-introducing the stale-text attribution this function exists to
        # avoid. A degenerate short early proposal ("Agreed.") would otherwise
        # absorb every critique whose excerpt starts with it.
        for i, msg in reversed(candidates):
            content = str(getattr(msg, "content", "") or "").strip()
            if not content:
                continue
            shorter, longer = sorted((content, wanted), key=len)
            if longer.startswith(shorter):
                return f"msg_{i}_{target}"

    index = candidates[-1][0]
    return f"msg_{index}_{target}"


def _link_critiques(network: Any, messages: list[Any], critiques: list[Any]) -> int:
    """Add a ``CONTRADICTS`` edge per critique; return how many were added.

    A critique is a *recorded, agent-attributed disagreement*: agent X contested
    agent Y's proposal with a model-assessed ``severity``. That is exactly the
    relation :class:`CruxDetector` needs, so edges are derived from the debate's
    own structured records rather than inferred from prose.

    Edge strength is ``severity / 10`` (the documented 0-10 scale), so a critical
    objection weighs more than a moderate one.

    ``severity <= 0`` is skipped entirely. The debate emits placeholder critiques
    with ``severity=0.0`` when a critic times out or errors
    (``critique_generator``/``debate_rounds``), and flooring those to a nonzero
    weight would manufacture crux cards for disagreements that never happened.
    A genuine 0-severity finding is "trivial/cosmetic" by the documented scale
    and so is not load-bearing either — which is precisely what a crux is.

    Best-effort: an unmappable critique is skipped rather than raising, since
    the caller treats crux-building as optional enrichment.
    """
    try:
        from aragora.reasoning.claims import RelationType
    except ImportError:
        return 0

    linked = 0
    used_source: dict[str, int] = {}
    for critique in critiques:
        critic = str(getattr(critique, "agent", "") or "")
        target = str(getattr(critique, "target_agent", "") or getattr(critique, "target", "") or "")
        if not critic or not target or critic == target:
            continue

        try:
            severity = float(getattr(critique, "severity", 0.0) or 0.0)
        except (TypeError, ValueError):
            severity = 0.0
        # `severity != severity` catches NaN: every NaN comparison is False, so a
        # NaN would pass `<= 0` and then `min(1.0, nan/10.0)` returns 1.0 —
        # a maximum-strength edge from an unusable value.
        if severity != severity or severity <= 0:  # noqa: PLR0124 - NaN check
            continue

        target_claim = _target_claim_for_critique(messages, target, critique)
        if target_claim is None:
            continue

        # Consume this critic's critic-role messages in order, so successive
        # critiques anchor to successive messages instead of all to the first.
        # This relies on `result.critiques` and the critic-role entries in
        # `result.messages` being appended 1:1 in the same order — true today in
        # both `critique_generator` and `debate_rounds`, but not asserted
        # anywhere. A producer that records critiques without mirroring messages
        # degrades to mis-anchored source prose or a skipped edge, never an
        # error: the edge's agents and severity stay correct either way.
        source_claims = _claim_ids_for_agent(messages, critic, "critic")
        index = used_source.get(critic, 0)
        if index >= len(source_claims):
            continue
        used_source[critic] = index + 1
        source_claim = source_claims[index]

        strength = min(1.0, severity / 10.0)

        if network.add_factor(source_claim, target_claim, RelationType.CONTRADICTS, strength):
            linked += 1
    return linked


__all__ = [
    "CRUX_CARDS_METADATA_KEY",
    "build_crux_cards",
]
