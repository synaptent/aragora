"""Crux cards on standard debates (#8227 / #9046 phase 1).

`enable_crux_cards` attaches the load-bearing disagreements of a *standard*
debate to its result metadata — without changing the debate goal (that is
`consensus="crux_finder"`, covered by test_crux_mode.py). Flag OFF (the
default) must leave results and receipts byte-identical to pre-flag behavior.
"""

from __future__ import annotations

from types import SimpleNamespace

from aragora.core_types import Critique, DebateResult, Message
from aragora.debate.crux_cards import (
    CRUX_CARDS_METADATA_KEY,
    _network_from_messages,
    build_crux_cards,
)
from aragora.debate.protocol import DebateProtocol
from aragora.reasoning.belief import BeliefNetwork
from aragora.reasoning.claims import RelationType


def _contested_network() -> BeliefNetwork:
    """A small network with one clearly load-bearing contested claim."""
    network = BeliefNetwork()
    network.add_claim("c1", "Load-bearing contested claim", "agent-alpha", 0.55)
    network.add_claim("c2", "Depends on c1", "agent-alpha", 0.7)
    network.add_claim("c3", "Also depends on c1", "agent-alpha", 0.4)
    network.add_claim("c4", "Counter-evidence against c1", "agent-beta", 0.6)
    network.add_claim("c5", "Supporting evidence for c1", "agent-gamma", 0.5)
    network.add_factor("c1", "c2", RelationType.SUPPORTS)
    network.add_factor("c1", "c3", RelationType.SUPPORTS)
    network.add_factor("c4", "c1", RelationType.CONTRADICTS)
    network.add_factor("c5", "c1", RelationType.SUPPORTS)
    return network


class TestProtocolFlag:
    def test_default_off(self) -> None:
        assert DebateProtocol().enable_crux_cards is False

    def test_opt_in(self) -> None:
        assert DebateProtocol(enable_crux_cards=True).enable_crux_cards is True


class TestBuildCruxCards:
    def test_from_belief_network(self) -> None:
        cards = build_crux_cards(belief_network=_contested_network(), top_k=5, min_score=0.05)
        assert cards is not None
        assert cards["items"], "contested network must yield at least one crux"
        first = cards["items"][0]
        # Per-crux dissent attribution (the work order's acceptance criterion).
        assert first["statement"]
        assert "contesting_agents" in first
        assert "author" in first
        assert "crux_score" in first
        assert "convergence_barrier" in cards
        assert cards["detector"] == "belief_network"

    def test_no_material_returns_none(self) -> None:
        assert build_crux_cards(belief_network=None, messages=[]) is None

    def test_messages_fallback_does_not_raise(self) -> None:
        messages = [
            Message(role="proposer", agent="agent-a", content="X is clearly true."),
            Message(role="critic", agent="agent-b", content="X is clearly false."),
            Message(role="synthesizer", agent="agent-c", content="ignored role"),
        ]
        cards = build_crux_cards(messages=messages, min_score=0.0)
        assert cards is None or cards["items"]

    def test_high_min_score_filters_to_none(self) -> None:
        cards = build_crux_cards(belief_network=_contested_network(), min_score=1.1)
        assert cards is None


class TestConsensusPhaseAttach:
    def _phase(self, protocol: DebateProtocol):
        from aragora.debate.phases.consensus_phase import ConsensusPhase

        return ConsensusPhase(protocol=protocol)

    def _ctx(self, network: BeliefNetwork | None) -> SimpleNamespace:
        result = DebateResult(
            debate_id="d-crux",
            task="Should we ship?",
            final_answer="Yes, with a canary rollout.",
            confidence=0.8,
            consensus_reached=True,
            rounds_used=2,
            participants=["agent-alpha", "agent-beta"],
        )
        return SimpleNamespace(result=result, belief_network=network)

    def test_attach_sets_metadata(self) -> None:
        phase = self._phase(DebateProtocol(enable_crux_cards=True, crux_finder_min_score=0.05))
        ctx = self._ctx(_contested_network())
        phase._attach_crux_cards(ctx)
        cards = ctx.result.metadata.get(CRUX_CARDS_METADATA_KEY)
        assert cards is not None
        assert cards["items"]
        assert cards["items"][0]["contesting_agents"] is not None

    def test_attach_without_material_leaves_metadata_untouched(self) -> None:
        phase = self._phase(DebateProtocol(enable_crux_cards=True, crux_finder_min_score=0.05))
        ctx = self._ctx(network=None)
        phase._attach_crux_cards(ctx)
        assert CRUX_CARDS_METADATA_KEY not in ctx.result.metadata

    def test_attach_never_raises(self) -> None:
        phase = self._phase(DebateProtocol(enable_crux_cards=True))
        broken_ctx = SimpleNamespace(result=None, belief_network=None)
        phase._attach_crux_cards(broken_ctx)  # must swallow, not raise


# --- #9581: cruxes were structurally unreachable in a real debate -------------
# The detector scores a claim by how much authors disagree about it, which it
# reads from the network's FACTOR EDGES. Both build paths added claims and no
# edges, so `total_disagreements` was always 0 and no crux cleared any
# threshold, at any min_score, with any agents.


AGENTS = ("claude", "codex", "gemini")


def _contested_debate() -> tuple[list[Message], list[Critique]]:
    """A real two-agent disagreement, as a debate actually records it."""
    messages = [
        Message(role="proposer", agent="claude", content="Declare the month failed."),
        Message(role="proposer", agent="codex", content="Ship local proofs and count them."),
        Message(role="critic", agent="codex", content="Failing discards real evidence."),
        Message(role="critic", agent="claude", content="Counting overstates what was proven."),
    ]
    critiques = [
        Critique(
            agent="codex",
            target_agent="claude",
            target_content="",
            issues=["discards evidence"],
            suggestions=[],
            severity=7.0,
            reasoning="Failing the month discards real evidence.",
        ),
        Critique(
            agent="claude",
            target_agent="codex",
            target_content="",
            issues=["overstates proof"],
            suggestions=[],
            severity=8.0,
            reasoning="Counting local proofs overstates what was proven.",
        ),
    ]
    return messages, critiques


def test_messages_without_critiques_still_yield_nothing():
    """The pre-fix behaviour, pinned: claims alone can never produce a crux."""
    messages, _ = _contested_debate()
    assert build_crux_cards(messages=messages) is None


def test_two_agent_debate_now_attributes_dissent():
    """#9644: a contested two-agent debate cards WITH named contesters.

    Previously impossible twice over: disagreement was measured after
    propagation had reconciled it, and the map held only neighbours so the
    author's own position was never counted. A two-agent debate therefore
    registered no disagreement at all and cards were suppressed.
    """
    messages, critiques = _contested_debate()
    cards = build_crux_cards(messages=messages, critiques=critiques)
    assert cards is not None
    assert cards["total_disagreements"] > 0
    contested = [item for item in cards["items"] if item["contesting_agents"]]
    assert contested, "a contested debate must name who contested what"
    # The claim's own author is never listed as contesting their own claim.
    for item in contested:
        assert item["author"] not in item["contesting_agents"]


def test_cards_suppressed_when_nothing_is_contested():
    """The suppression guard still holds when there is genuinely no dissent."""
    messages = [
        Message(role="proposer", agent="claude", content="A"),
        Message(role="proposer", agent="codex", content="B"),
    ]
    assert build_crux_cards(messages=messages, critiques=[]) is None


def test_critiques_make_a_contested_debate_produce_cruxes():
    """The #9581 regression: with critiques, a genuinely contested debate cards.

    Needs two distinct contesters of the same claim for the detector to register
    a disagreement at all, so this is the three-agent shape.
    """
    messages = [Message(role="proposer", agent=a, content=f"{a} proposal") for a in AGENTS]
    messages += [Message(role="critic", agent=a, content=f"{a} objection") for a in AGENTS]
    critiques = [
        Critique(
            agent=critic,
            target_agent="claude",
            target_content="claude proposal",
            issues=["x"],
            suggestions=[],
            severity=severity,
            reasoning=f"{critic} contests claude",
        )
        for critic, severity in (("codex", 7.0), ("gemini", 6.0))
    ]
    cards = build_crux_cards(messages=messages, critiques=critiques)
    assert cards is not None
    assert cards["items"], "a contested debate must surface at least one crux"
    assert cards["total_disagreements"] > 0


def test_same_debate_without_critiques_yields_nothing():
    """Pinned for contrast: claims alone can never produce a crux."""
    messages = [Message(role="proposer", agent=a, content=f"{a} proposal") for a in AGENTS]
    assert build_crux_cards(messages=messages) is None


def test_critique_severity_drives_edge_strength():
    """Severity sets the CONTRADICTS edge weight (0-10 scale -> 0.0-1.0).

    Deliberately asserts the edge weight rather than a crux-score direction:
    the score is a composite, and a *weakly* contested claim can legitimately
    score higher because it stays unresolved and therefore more load-bearing.
    """
    messages, critiques = _contested_debate()
    network = _network_from_messages(messages, critiques)
    assert sorted(f.strength for f in network.factors.values()) == [0.7, 0.8]


def test_zero_severity_placeholder_critiques_make_no_edges():
    """A timed-out critic must not manufacture a disagreement.

    `critique_generator` / `debate_rounds` emit placeholder Critiques with
    severity=0.0 when a critic errors or times out. Flooring those to a nonzero
    weight would emit crux cards for disagreements that never happened.
    """
    messages, _ = _contested_debate()
    placeholders = [
        Critique(
            agent="codex",
            target_agent="claude",
            target_content="",
            issues=["[Critique failed: timeout]"],
            suggestions=[],
            severity=0.0,
            reasoning="Critique generation failed due to timeout or agent error.",
        )
    ]
    assert build_crux_cards(messages=messages, critiques=placeholders) is None


def test_supplied_belief_network_is_not_mutated():
    """Crux building is optional enrichment and must stay read-only there.

    A KM-seeded ctx.belief_network uses KM-derived claim ids, so message-derived
    ids match nothing in it: linking would no-op every edge while leaving orphan
    claims behind in state that consensus_storage/crux_finder later read.
    """
    messages, critiques = _contested_debate()
    seeded = BeliefNetwork(max_iterations=3)
    seeded.add_claim(claim_id="km-derived-001", statement="seeded", author="claude")
    before_nodes, before_factors = len(seeded.nodes), len(seeded.factors)

    build_crux_cards(belief_network=seeded, messages=messages, critiques=critiques)

    assert (len(seeded.nodes), len(seeded.factors)) == (before_nodes, before_factors)


def test_successive_critiques_anchor_to_successive_messages():
    """A critic's Nth critique must not re-anchor to their first message.

    Otherwise every critique by one agent stacks duplicate parallel edges
    between the same claim pair and mis-attributes the source statement.
    """
    messages = [
        Message(role="proposer", agent="claude", content="P1"),
        Message(role="critic", agent="codex", content="first objection"),
        Message(role="critic", agent="codex", content="second objection"),
    ]
    critiques = [
        Critique(
            agent="codex",
            target_agent="claude",
            target_content="",
            issues=["a"],
            suggestions=[],
            severity=5.0,
            reasoning="r1",
        ),
        Critique(
            agent="codex",
            target_agent="claude",
            target_content="",
            issues=["b"],
            suggestions=[],
            severity=6.0,
            reasoning="r2",
        ),
    ]
    network = _network_from_messages(messages, critiques)
    sources = {network.nodes[f.source_node_id].claim_statement for f in network.factors.values()}
    assert sources == {"first objection", "second objection"}


def test_unmappable_critiques_are_skipped_not_raised():
    """Crux building is optional enrichment; bad input must not break a debate."""
    messages, _ = _contested_debate()
    junk = [
        Critique(
            agent="ghost",
            target_agent="nobody",  # no such proposer
            target_content="",
            issues=[],
            suggestions=[],
            severity=5.0,
            reasoning="unmappable",
        )
    ]
    # No proposal to attach to -> no edges -> no cruxes, and no exception.
    assert build_crux_cards(messages=messages, critiques=junk) is None


def test_self_critique_does_not_create_an_edge():
    """An agent critiquing itself is not a disagreement between authors."""
    messages, _ = _contested_debate()
    selfish = [
        Critique(
            agent="claude",
            target_agent="claude",
            target_content="",
            issues=["x"],
            suggestions=[],
            severity=9.0,
            reasoning="self",
        )
    ]
    assert build_crux_cards(messages=messages, critiques=selfish) is None


def test_critique_anchors_to_the_revision_it_addressed():
    """A round-2 critique of a revision must not attribute to the round-1 text.

    Revisions are recorded with role="proposer" too, so the target agent has one
    proposer message per round. `Critique.target_content` records exactly which
    one was critiqued.
    """
    messages = [
        Message(role="proposer", agent="claude", content="round 1 proposal"),
        Message(role="critic", agent="codex", content="objection to r1"),
        Message(role="proposer", agent="claude", content="round 2 revision"),
        Message(role="critic", agent="codex", content="objection to r2"),
    ]
    critiques = [
        Critique(
            agent="codex",
            target_agent="claude",
            target_content="round 1 proposal",
            issues=["a"],
            suggestions=[],
            severity=5.0,
            reasoning="r1",
        ),
        Critique(
            agent="codex",
            target_agent="claude",
            target_content="round 2 revision",
            issues=["b"],
            suggestions=[],
            severity=6.0,
            reasoning="r2",
        ),
    ]
    network = _network_from_messages(messages, critiques)
    targets = {network.nodes[f.target_node_id].claim_statement for f in network.factors.values()}
    # Both rounds attributed to their own proposal, so the revision accrues an
    # edge instead of every critique piling onto round 1.
    assert targets == {"round 1 proposal", "round 2 revision"}


def test_critique_without_target_content_uses_the_latest_proposal():
    """Absent an exact match, the target's current position is the better default."""
    messages = [
        Message(role="proposer", agent="claude", content="round 1 proposal"),
        Message(role="proposer", agent="claude", content="round 2 revision"),
        Message(role="critic", agent="codex", content="objection"),
    ]
    critiques = [
        Critique(
            agent="codex",
            target_agent="claude",
            target_content="",
            issues=["a"],
            suggestions=[],
            severity=5.0,
            reasoning="r",
        )
    ]
    network = _network_from_messages(messages, critiques)
    targets = [network.nodes[f.target_node_id].claim_statement for f in network.factors.values()]
    assert targets == ["round 2 revision"]


def test_truncated_target_content_still_matches_its_proposal():
    """Several agents record only `proposal[:200]`, so match by prefix.

    Exact comparison would miss every proposal longer than the excerpt and fall
    through to the latest revision, misattributing the disagreement.
    """
    long_proposal = "round 1 proposal " + ("x" * 500)
    messages = [
        Message(role="proposer", agent="claude", content=long_proposal),
        Message(role="proposer", agent="claude", content="round 2 revision"),
        Message(role="critic", agent="codex", content="objection"),
    ]
    critiques = [
        Critique(
            agent="codex",
            target_agent="claude",
            target_content=long_proposal[:200],  # what codebase_agent/code_reviewer record
            issues=["a"],
            suggestions=[],
            severity=5.0,
            reasoning="r",
        )
    ]
    network = _network_from_messages(messages, critiques)
    targets = [network.nodes[f.target_node_id].claim_statement for f in network.factors.values()]
    # Claim statements are stored truncated to 500 chars, so compare by prefix.
    assert len(targets) == 1
    assert long_proposal.startswith(targets[0])
    assert targets[0] != "round 2 revision"


def test_nan_severity_is_skipped_not_maximised():
    """NaN passes `<= 0` (all NaN comparisons are False) and min(1.0, nan/10)=1.0.

    Without an explicit check an unusable severity became a maximum-strength
    edge — the strongest possible disagreement from a value that means nothing.
    """
    messages = [
        Message(role="proposer", agent="claude", content="P"),
        Message(role="critic", agent="codex", content="C"),
    ]
    critiques = [
        Critique(
            agent="codex",
            target_agent="claude",
            target_content="P",
            issues=["x"],
            suggestions=[],
            severity=float("nan"),
            reasoning="r",
        )
    ]
    network = _network_from_messages(messages, critiques)
    assert not network.factors


def test_revision_sharing_a_prefix_anchors_to_the_revision():
    """Scanning newest-first keeps a shared opening from re-attributing to round 1.

    A revision commonly keeps the earlier proposal's header, so a prefix
    comparison can match both rounds; biasing to the newest matches the
    no-match fallback and avoids the stale-text attribution.
    """
    shared = "# Proposal\nWe should ship it."
    messages = [
        Message(role="proposer", agent="claude", content=shared),
        Message(role="proposer", agent="claude", content=shared + "\nRevised: with a caveat."),
        Message(role="critic", agent="codex", content="objection"),
    ]
    critiques = [
        Critique(
            agent="codex",
            target_agent="claude",
            target_content=shared,  # matches BOTH rounds by prefix
            issues=["x"],
            suggestions=[],
            severity=5.0,
            reasoning="r",
        )
    ]
    network = _network_from_messages(messages, critiques)
    targets = [network.nodes[f.target_node_id].claim_statement for f in network.factors.values()]
    assert targets == [shared + "\nRevised: with a caveat."]
