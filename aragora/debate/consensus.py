"""
Consensus Proofs with Dissent Tracking.

Generates auditable artifacts from debates with:
- Structured claims and supporting evidence
- Dissenting opinions with reasoning
- Confidence scores and unresolved tensions
- Traceable evidence chains
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class VoteType(Enum):
    """Types of consensus votes."""

    AGREE = "agree"
    DISAGREE = "disagree"
    ABSTAIN = "abstain"
    CONDITIONAL = "conditional"  # Agree with reservations


@dataclass
class Evidence:
    """A piece of evidence supporting or refuting a claim."""

    evidence_id: str
    source: str  # Agent name, tool output, or external reference
    content: str
    evidence_type: str  # "argument", "data", "citation", "tool_output"
    supports_claim: bool  # True if supports, False if refutes
    strength: float  # 0-1
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Claim:
    """A structured claim with evidence."""

    claim_id: str
    statement: str
    author: str
    confidence: float  # 0-1
    supporting_evidence: list[Evidence] = field(default_factory=list)
    refuting_evidence: list[Evidence] = field(default_factory=list)
    round_introduced: int = 0
    status: str = "active"  # "active", "revised", "withdrawn", "merged"
    parent_claim_id: str | None = None  # If this revises another claim

    @property
    def net_evidence_strength(self) -> float:
        """Calculate net evidence strength (support - refutation)."""
        support = sum(e.strength for e in self.supporting_evidence)
        refute = sum(e.strength for e in self.refuting_evidence)
        total = support + refute
        return (support - refute) / total if total > 0 else 0.0


@dataclass
class DissentRecord:
    """Record of an agent's dissent from consensus."""

    agent: str
    claim_id: str
    dissent_type: str  # "full", "partial", "procedural"
    reasons: list[str]
    alternative_view: str | None = None
    suggested_resolution: str | None = None
    severity: float = 0.5  # How strongly they dissent (0-1)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UnresolvedTension:
    """A tension or tradeoff that wasn't fully resolved."""

    tension_id: str
    description: str
    agents_involved: list[str]
    options: list[str]  # The competing approaches/values
    impact: str  # What depends on resolving this
    suggested_followup: str | None = None


@dataclass
class PartialConsensusItem:
    """Tracks consensus on a specific sub-question or topic.

    When full consensus isn't reached, debates may still achieve agreement
    on specific aspects. This allows plans to proceed with agreed portions
    while flagging disagreements for human review.
    """

    item_id: str
    topic: str  # The sub-question or aspect
    statement: str  # The agreed-upon position
    confidence: float  # Confidence on this specific item (0-1)
    agreed: bool  # Whether consensus was reached on this item
    supporting_agents: list[str] = field(default_factory=list)
    dissenting_agents: list[str] = field(default_factory=list)
    dissenting_views: list[str] = field(default_factory=list)
    source: str = "claim_analysis"  # Where this was extracted from
    actionable: bool = True  # Whether this can be acted upon

    @property
    def agreement_ratio(self) -> float:
        """Calculate ratio of agents agreeing on this item."""
        total = len(self.supporting_agents) + len(self.dissenting_agents)
        return len(self.supporting_agents) / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "item_id": self.item_id,
            "topic": self.topic,
            "statement": self.statement,
            "confidence": self.confidence,
            "agreed": self.agreed,
            "agreement_ratio": self.agreement_ratio,
            "supporting_agents": self.supporting_agents,
            "dissenting_agents": self.dissenting_agents,
            "dissenting_views": self.dissenting_views,
            "source": self.source,
            "actionable": self.actionable,
        }


@dataclass
class PartialConsensus:
    """Collection of partial consensus items from a debate.

    Allows tracking which sub-questions achieved consensus even when
    overall consensus was not reached. This enables:
    - Plans to proceed with agreed portions
    - Clear flagging of disagreements for human review
    - More nuanced decision-making from debates
    """

    debate_id: str
    items: list[PartialConsensusItem] = field(default_factory=list)
    overall_consensus: bool = False  # Did the full debate reach consensus?
    overall_confidence: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_item(self, item: PartialConsensusItem) -> None:
        """Add a partial consensus item."""
        self.items.append(item)

    @property
    def agreed_items(self) -> list[PartialConsensusItem]:
        """Get items where consensus was reached."""
        return [i for i in self.items if i.agreed]

    @property
    def disagreed_items(self) -> list[PartialConsensusItem]:
        """Get items where consensus was NOT reached."""
        return [i for i in self.items if not i.agreed]

    @property
    def actionable_items(self) -> list[PartialConsensusItem]:
        """Get items that are agreed AND actionable."""
        return [i for i in self.items if i.agreed and i.actionable]

    @property
    def consensus_ratio(self) -> float:
        """Ratio of items that reached consensus."""
        if not self.items:
            return 0.0
        return len(self.agreed_items) / len(self.items)

    @property
    def avg_confidence(self) -> float:
        """Average confidence across all items."""
        if not self.items:
            return 0.0
        return sum(i.confidence for i in self.items) / len(self.items)

    def summary(self) -> str:
        """Generate a summary of partial consensus status."""
        total = len(self.items)
        agreed = len(self.agreed_items)
        actionable = len(self.actionable_items)
        disagreed = len(self.disagreed_items)

        if total == 0:
            return "No sub-questions analyzed"

        lines = [
            f"Partial Consensus: {agreed}/{total} items agreed ({self.consensus_ratio:.0%})",
            f"  - Actionable items: {actionable}",
            f"  - Disagreed items: {disagreed}",
            f"  - Average confidence: {self.avg_confidence:.0%}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "debate_id": self.debate_id,
            "items": [i.to_dict() for i in self.items],
            "overall_consensus": self.overall_consensus,
            "overall_confidence": self.overall_confidence,
            "consensus_ratio": self.consensus_ratio,
            "avg_confidence": self.avg_confidence,
            "agreed_count": len(self.agreed_items),
            "disagreed_count": len(self.disagreed_items),
            "actionable_count": len(self.actionable_items),
            "created_at": self.created_at,
        }


@dataclass
class ConsensusVote:
    """An agent's vote on the consensus."""

    agent: str
    vote: VoteType
    confidence: float  # 0-1
    reasoning: str
    conditions: list[str] = field(default_factory=list)  # For conditional votes
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ConsensusProof:
    """
    Auditable proof of debate consensus with full provenance.

    This artifact provides:
    - The final claim and supporting reasoning
    - Which agents agreed/disagreed and why
    - Unresolved tensions and tradeoffs
    - Evidence chain for verification
    """

    proof_id: str
    debate_id: str
    task: str

    # Final consensus
    final_claim: str
    confidence: float
    consensus_reached: bool

    # Voting record
    votes: list[ConsensusVote]
    supporting_agents: list[str]
    dissenting_agents: list[str]

    # Detailed records
    claims: list[Claim]
    dissents: list[DissentRecord]
    unresolved_tensions: list[UnresolvedTension]

    # Provenance
    evidence_chain: list[Evidence]
    reasoning_summary: str

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    rounds_to_consensus: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    # Cached checksum (computed on first access, excluded from repr/compare)
    _cached_checksum: str | None = field(default=None, repr=False, compare=False)

    @property
    def checksum(self) -> str:
        """Generate checksum for proof integrity (cached after first computation)."""
        if self._cached_checksum is not None:
            return self._cached_checksum

        def enum_dict_factory(data: list[tuple[str, Any]]) -> dict[str, Any]:
            """Convert Enum values to their string values for JSON serialization."""
            return {k: v.value if isinstance(v, Enum) else v for k, v in data}

        content = json.dumps(
            {
                "final_claim": self.final_claim,
                "votes": [asdict(v, dict_factory=enum_dict_factory) for v in self.votes],
                "claims": [asdict(c, dict_factory=enum_dict_factory) for c in self.claims],
            },
            sort_keys=True,
        )
        # Cache the computed checksum
        object.__setattr__(
            self, "_cached_checksum", hashlib.sha256(content.encode()).hexdigest()[:16]
        )
        return self._cached_checksum

    @property
    def agreement_ratio(self) -> float:
        """Ratio of agreeing agents."""
        total = len(self.supporting_agents) + len(self.dissenting_agents)
        return len(self.supporting_agents) / total if total > 0 else 0.0

    @property
    def has_strong_consensus(self) -> bool:
        """Check if consensus is strong (>80% agreement, >0.7 confidence)."""
        return self.consensus_reached and self.agreement_ratio > 0.8 and self.confidence > 0.7

    def get_dissent_summary(self) -> str:
        """Generate summary of dissenting views."""
        if not self.dissents:
            return "No dissenting views recorded."

        lines = ["## Dissenting Views", ""]
        for dissent in self.dissents:
            lines.append(f"### {dissent.agent}")
            lines.append(f"**Type:** {dissent.dissent_type}")
            lines.append(f"**Severity:** {dissent.severity:.0%}")
            lines.append("")
            lines.append("**Reasons:**")
            for reason in dissent.reasons:
                lines.append(f"- {reason}")
            if dissent.alternative_view:
                lines.append("")
                lines.append(f"**Alternative:** {dissent.alternative_view}")
            lines.append("")

        return "\n".join(lines)

    def get_tension_summary(self) -> str:
        """Generate summary of unresolved tensions."""
        if not self.unresolved_tensions:
            return "No unresolved tensions."

        lines = ["## Unresolved Tensions", ""]
        for tension in self.unresolved_tensions:
            lines.append(f"### {tension.description}")
            lines.append(f"**Involves:** {', '.join(tension.agents_involved)}")
            lines.append("")
            lines.append("**Competing options:**")
            for opt in tension.options:
                lines.append(f"- {opt}")
            lines.append("")
            lines.append(f"**Impact:** {tension.impact}")
            if tension.suggested_followup:
                lines.append(f"**Suggested followup:** {tension.suggested_followup}")
            lines.append("")

        return "\n".join(lines)

    def get_confidence_breakdown(self) -> dict[str, float]:
        """Get per-agent confidence scores.

        Returns:
            Dict mapping agent names to their confidence scores.
        """
        breakdown = {}
        for vote in self.votes:
            breakdown[vote.agent] = vote.confidence
        return breakdown

    def get_blind_spots(self) -> list[str]:
        """Identify perspectives not covered in the debate.

        Returns:
            List of potential blind spots based on dissent patterns.
        """
        blind_spots = []

        # High-severity dissents indicate blind spots
        for dissent in self.dissents:
            if dissent.severity >= 0.7:
                if dissent.alternative_view:
                    blind_spots.append(
                        f"Alternative view from {dissent.agent}: {dissent.alternative_view}"
                    )
                else:
                    blind_spots.append(
                        f"Strong dissent from {dissent.agent}: {', '.join(dissent.reasons[:2])}"
                    )

        # Unresolved tensions are potential blind spots
        for tension in self.unresolved_tensions:
            blind_spots.append(
                f"Unresolved: {tension.description} ({', '.join(tension.options[:2])})"
            )

        # Low agreement ratio indicates blind spots
        if self.agreement_ratio < 0.6:
            blind_spots.append(
                f"Low consensus ({self.agreement_ratio:.0%}) suggests multiple valid perspectives"
            )

        return blind_spots

    def get_risk_correlation(self) -> dict[str, list[str]]:
        """Get risk areas grouped by agent agreement.

        Returns:
            Dict with keys "unanimous", "majority", "contested" mapping to risk descriptions.
        """
        correlation: dict[str, list[str]] = {
            "unanimous": [],  # All agents agree
            "majority": [],  # Most agents agree
            "contested": [],  # Significant disagreement
        }

        # Analyze claim support patterns
        for claim in self.claims:
            support_count = len(claim.supporting_evidence)
            refute_count = len(claim.refuting_evidence)
            total = support_count + refute_count

            if total == 0:
                continue

            support_ratio = support_count / total

            if support_ratio >= 0.9:
                correlation["unanimous"].append(claim.statement[:100])
            elif support_ratio >= 0.6:
                correlation["majority"].append(claim.statement[:100])
            else:
                correlation["contested"].append(claim.statement[:100])

        # Add tensions to contested
        for tension in self.unresolved_tensions:
            correlation["contested"].append(tension.description)

        return correlation

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""

        def enum_dict_factory(data: list[tuple[str, Any]]) -> dict[str, Any]:
            """Convert Enum values to their string values for JSON serialization."""
            return {k: v.value if isinstance(v, Enum) else v for k, v in data}

        return {
            "proof_id": self.proof_id,
            "debate_id": self.debate_id,
            "task": self.task,
            "final_claim": self.final_claim,
            "confidence": self.confidence,
            "consensus_reached": self.consensus_reached,
            "votes": [asdict(v, dict_factory=enum_dict_factory) for v in self.votes],
            "supporting_agents": self.supporting_agents,
            "dissenting_agents": self.dissenting_agents,
            "claims": [asdict(c, dict_factory=enum_dict_factory) for c in self.claims],
            "dissents": [asdict(d, dict_factory=enum_dict_factory) for d in self.dissents],
            "unresolved_tensions": [
                asdict(t, dict_factory=enum_dict_factory) for t in self.unresolved_tensions
            ],
            "evidence_chain": [
                asdict(e, dict_factory=enum_dict_factory) for e in self.evidence_chain
            ],
            "reasoning_summary": self.reasoning_summary,
            "created_at": self.created_at,
            "rounds_to_consensus": self.rounds_to_consensus,
            "checksum": self.checksum,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Generate readable Markdown report."""
        lines = [
            "# Consensus Proof",
            "",
            f"**Proof ID:** `{self.proof_id}`",
            f"**Debate ID:** `{self.debate_id}`",
            f"**Checksum:** `{self.checksum}`",
            "",
            "---",
            "",
            "## Task",
            "",
            self.task,
            "",
            "---",
            "",
            "## Consensus",
            "",
            f"**Status:** {'Reached' if self.consensus_reached else 'Not Reached'}",
            f"**Confidence:** {self.confidence:.0%}",
            f"**Agreement:** {self.agreement_ratio:.0%}",
            f"**Rounds:** {self.rounds_to_consensus}",
            "",
            "### Final Claim",
            "",
            f"> {self.final_claim}",
            "",
            "### Supporting Agents",
            "",
        ]

        for agent in self.supporting_agents:
            vote = next((v for v in self.votes if v.agent == agent), None)
            if vote:
                lines.append(f"- **{agent}** ({vote.confidence:.0%}): {vote.reasoning[:100]}...")
            else:
                lines.append(f"- **{agent}**")

        lines.append("")
        lines.append("### Dissenting Agents")
        lines.append("")

        if self.dissenting_agents:
            for agent in self.dissenting_agents:
                vote = next((v for v in self.votes if v.agent == agent), None)
                if vote:
                    lines.append(
                        f"- **{agent}** ({vote.confidence:.0%}): {vote.reasoning[:100]}..."
                    )
                else:
                    lines.append(f"- **{agent}**")
        else:
            lines.append("*None*")

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(self.get_dissent_summary())
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(self.get_tension_summary())
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Reasoning Summary")
        lines.append("")
        lines.append(self.reasoning_summary)
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Evidence Chain")
        lines.append("")

        for i, evidence in enumerate(self.evidence_chain, 1):
            support = "+" if evidence.supports_claim else "-"
            lines.append(f"{i}. [{support}] **{evidence.source}** ({evidence.evidence_type})")
            lines.append(f"   {evidence.content[:200]}...")
            lines.append("")

        return "\n".join(lines)


class ConsensusBuilder:
    """
    Builds ConsensusProof artifacts from debate results.

    Analyzes debate messages and critiques to extract:
    - Claims and evidence
    - Voting patterns
    - Dissenting views
    - Unresolved tensions
    """

    def __init__(self, debate_id: str, task: str):
        self.debate_id = debate_id
        self.task = task
        self.claims: list[Claim] = []
        self.evidence: list[Evidence] = []
        self.votes: list[ConsensusVote] = []
        self.dissents: list[DissentRecord] = []
        self.tensions: list[UnresolvedTension] = []
        self._claim_counter = 0
        self._evidence_counter = 0

    def add_claim(
        self,
        statement: str,
        author: str,
        confidence: float = 0.5,
        round_num: int = 0,
        parent_claim_id: str | None = None,
    ) -> Claim:
        """Add a claim from the debate."""
        self._claim_counter += 1
        claim = Claim(
            claim_id=f"{self.debate_id}-claim-{self._claim_counter}",
            statement=statement,
            author=author,
            confidence=confidence,
            round_introduced=round_num,
            parent_claim_id=parent_claim_id,
        )
        self.claims.append(claim)
        return claim

    def add_evidence(
        self,
        claim_id: str,
        source: str,
        content: str,
        evidence_type: str = "argument",
        supports: bool = True,
        strength: float = 0.5,
    ) -> Evidence:
        """Add evidence for or against a claim."""
        self._evidence_counter += 1
        evidence = Evidence(
            evidence_id=f"{self.debate_id}-ev-{self._evidence_counter}",
            source=source,
            content=content,
            evidence_type=evidence_type,
            supports_claim=supports,
            strength=strength,
        )

        # Attach to claim
        claim = next((c for c in self.claims if c.claim_id == claim_id), None)
        if claim:
            if supports:
                claim.supporting_evidence.append(evidence)
            else:
                claim.refuting_evidence.append(evidence)

        self.evidence.append(evidence)
        return evidence

    def record_vote(
        self,
        agent: str,
        vote: VoteType,
        confidence: float,
        reasoning: str,
        conditions: list[str] | None = None,
    ) -> ConsensusVote:
        """Record an agent's vote on consensus."""
        v = ConsensusVote(
            agent=agent,
            vote=vote,
            confidence=confidence,
            reasoning=reasoning,
            conditions=conditions or [],
        )
        self.votes.append(v)
        return v

    def record_dissent(
        self,
        agent: str,
        claim_id: str,
        reasons: list[str],
        dissent_type: str = "partial",
        alternative: str | None = None,
        severity: float = 0.5,
    ) -> DissentRecord:
        """Record a dissenting view."""
        dissent = DissentRecord(
            agent=agent,
            claim_id=claim_id,
            dissent_type=dissent_type,
            reasons=reasons,
            alternative_view=alternative,
            severity=severity,
        )
        self.dissents.append(dissent)
        return dissent

    def record_tension(
        self,
        description: str,
        agents: list[str],
        options: list[str],
        impact: str,
        followup: str | None = None,
    ) -> UnresolvedTension:
        """Record an unresolved tension."""
        tension = UnresolvedTension(
            tension_id=f"{self.debate_id}-tension-{len(self.tensions) + 1}",
            description=description,
            agents_involved=agents,
            options=options,
            impact=impact,
            suggested_followup=followup,
        )
        self.tensions.append(tension)
        return tension

    def build(
        self,
        final_claim: str,
        confidence: float,
        consensus_reached: bool,
        reasoning_summary: str,
        rounds: int = 0,
    ) -> ConsensusProof:
        """Build the final ConsensusProof."""
        # Categorize agents by vote
        supporting = [
            v.agent for v in self.votes if v.vote in (VoteType.AGREE, VoteType.CONDITIONAL)
        ]
        dissenting = [v.agent for v in self.votes if v.vote == VoteType.DISAGREE]

        return ConsensusProof(
            proof_id=f"proof-{self.debate_id}",
            debate_id=self.debate_id,
            task=self.task,
            final_claim=final_claim,
            confidence=confidence,
            consensus_reached=consensus_reached,
            votes=self.votes,
            supporting_agents=supporting,
            dissenting_agents=dissenting,
            claims=self.claims,
            dissents=self.dissents,
            unresolved_tensions=self.tensions,
            evidence_chain=self.evidence,
            reasoning_summary=reasoning_summary,
            rounds_to_consensus=rounds,
        )

    @classmethod
    def from_debate_result(cls, result: Any) -> ConsensusBuilder:
        """
        Create a ConsensusBuilder from a DebateResult.

        Extracts claims, evidence, and voting patterns from the debate.
        """
        builder = cls(result.id, result.task)

        # Extract claims from messages
        for msg in result.messages:
            if msg.role == "proposer":
                # Each proposal is a claim
                claim = builder.add_claim(
                    statement=msg.content[:500],  # Truncate for claim
                    author=msg.agent,
                    round_num=msg.round,
                )

                # Add the full content as evidence
                builder.add_evidence(
                    claim_id=claim.claim_id,
                    source=msg.agent,
                    content=msg.content,
                    evidence_type="argument",
                    supports=True,
                    strength=0.6,
                )

        # Build claims-by-author index for O(1) lookup (optimization)
        claims_by_author: dict[str, list[Any]] = {}
        for claim in builder.claims:
            if claim.author not in claims_by_author:
                claims_by_author[claim.author] = []
            claims_by_author[claim.author].append(claim)

        # Extract critiques as evidence
        for critique in result.critiques:
            # Find the claim being critiqued (O(1) lookup using index)
            target_claims = claims_by_author.get(critique.target_agent, [])
            if target_claims:
                target_claim = target_claims[-1]  # Most recent claim

                # Add critique as refuting evidence
                for issue in critique.issues:
                    builder.add_evidence(
                        claim_id=target_claim.claim_id,
                        source=critique.agent,
                        content=issue,
                        evidence_type="argument",
                        supports=False,
                        strength=critique.severity * 0.8,
                    )

                # If high severity, record as tension
                if critique.severity > 0.7:
                    builder.record_tension(
                        description=f"Disagreement between {critique.agent} and {critique.target_agent}",
                        agents=[critique.agent, critique.target_agent],
                        options=[
                            f"{critique.target_agent}'s approach",
                            (
                                ", ".join(critique.suggestions[:2])
                                if critique.suggestions
                                else "Alternative approach"
                            ),
                        ],
                        impact="May affect final solution quality",
                    )

        # Infer votes from final state
        all_agents = set(msg.agent for msg in result.messages)
        for agent in all_agents:
            # Agents with high-severity critiques in final round likely dissent
            agent_critiques = [c for c in result.critiques if c.agent == agent]
            final_severity = agent_critiques[-1].severity if agent_critiques else 0

            if final_severity > 0.6:
                builder.record_vote(
                    agent=agent,
                    vote=VoteType.DISAGREE,
                    confidence=1 - final_severity,
                    reasoning=f"Raised concerns: {agent_critiques[-1].issues[0] if agent_critiques and agent_critiques[-1].issues else 'Unknown'}",
                )
                builder.record_dissent(
                    agent=agent,
                    claim_id=builder.claims[-1].claim_id if builder.claims else "",
                    reasons=agent_critiques[-1].issues if agent_critiques else [],
                    severity=final_severity,
                )
            else:
                builder.record_vote(
                    agent=agent,
                    vote=VoteType.AGREE if result.consensus_reached else VoteType.CONDITIONAL,
                    confidence=result.confidence,
                    reasoning=(
                        "Supported final consensus"
                        if result.consensus_reached
                        else "Partial agreement"
                    ),
                )

        return builder


def build_partial_consensus(result: Any) -> PartialConsensus:
    """Build partial consensus from a DebateResult.

    Analyzes the debate result to identify which sub-questions or topics
    achieved consensus, even if overall consensus wasn't reached.

    This enables:
    - Plans to proceed with agreed portions
    - Clear flagging of disagreements for human review
    - More nuanced decision-making from debates

    Args:
        result: DebateResult (or compatible object)

    Returns:
        PartialConsensus with items for each identified sub-topic
    """
    debate_id = getattr(result, "debate_id", getattr(result, "id", "unknown"))
    partial = PartialConsensus(
        debate_id=debate_id,
        overall_consensus=getattr(result, "consensus_reached", False),
        overall_confidence=getattr(result, "confidence", 0.0),
    )

    participants = list(getattr(result, "participants", []))
    final_answer = getattr(result, "final_answer", "")
    critiques = getattr(result, "critiques", [])
    dissenting_views = getattr(result, "dissenting_views", [])
    debate_cruxes = getattr(result, "debate_cruxes", [])

    # Extract sub-topics from final answer (numbered items or bullet points)
    item_num = 0
    if final_answer:
        for line in final_answer.split("\n"):
            line = line.strip()
            if not line or len(line) < 20:
                continue

            # Match numbered items or bullet points
            is_structured = (
                (line[0].isdigit() and "." in line[:3])
                or line.startswith("-")
                or line.startswith("*")
                or line.startswith("•")
            )

            if is_structured:
                item_num += 1
                clean = line.lstrip("0123456789.-*•) ").strip()

                # Check if any critique specifically mentions this topic
                critique_mentions = []
                disagreeing_agents: list[str] = []
                for critique in critiques:
                    for issue in getattr(critique, "issues", []):
                        # Check if critique relates to this topic
                        if _topics_overlap(clean, issue):
                            critique_mentions.append(issue)
                            agent = getattr(critique, "agent", "")
                            if agent and agent not in disagreeing_agents:
                                disagreeing_agents.append(agent)

                # Calculate confidence for this item
                # Higher if no critiques mention it, lower if they do
                critique_impact = min(len(critique_mentions) * 0.15, 0.5)
                item_confidence = max(0.2, result.confidence - critique_impact)

                # Determine if agreed
                agreed = len(disagreeing_agents) < len(participants) / 2

                # Supporting agents = participants minus dissenters
                supporting = [p for p in participants if p not in disagreeing_agents]

                partial.add_item(
                    PartialConsensusItem(
                        item_id=f"item-{debate_id[:8]}-{item_num}",
                        topic=_extract_topic(clean),
                        statement=clean[:500],
                        confidence=item_confidence,
                        agreed=agreed,
                        supporting_agents=supporting,
                        dissenting_agents=disagreeing_agents,
                        dissenting_views=critique_mentions[:3],
                        source="final_answer",
                        actionable=_is_actionable(clean),
                    )
                )

    # Add items from debate cruxes (key disagreement drivers)
    for i, crux in enumerate(debate_cruxes[:5]):
        claim = crux.get("claim", crux.get("text", ""))
        if not claim:
            continue

        item_num += 1
        agents_involved = crux.get("agents", [])

        partial.add_item(
            PartialConsensusItem(
                item_id=f"crux-{debate_id[:8]}-{i}",
                topic=f"Crux: {_extract_topic(str(claim))}",
                statement=str(claim)[:500],
                confidence=0.4,  # Cruxes are inherently contested
                agreed=False,  # Cruxes represent disagreements
                supporting_agents=[],
                dissenting_agents=agents_involved if agents_involved else participants,
                dissenting_views=[str(claim)],
                source="belief_network",
                actionable=False,  # Cruxes need resolution before action
            )
        )

    # Add items from explicit dissenting views
    for i, view in enumerate(dissenting_views[:3]):
        item_num += 1
        partial.add_item(
            PartialConsensusItem(
                item_id=f"dissent-{debate_id[:8]}-{i}",
                topic=f"Dissent: {_extract_topic(view)}",
                statement=view[:500],
                confidence=0.3,
                agreed=False,
                supporting_agents=[],
                dissenting_agents=["unknown"],  # We don't always know who dissented
                dissenting_views=[view],
                source="dissent_analysis",
                actionable=False,
            )
        )

    return partial


def _topics_overlap(topic1: str, topic2: str) -> bool:
    """Check if two topics share significant keywords."""
    # Simple keyword overlap check
    words1 = set(w.lower() for w in topic1.split() if len(w) > 4)
    words2 = set(w.lower() for w in topic2.split() if len(w) > 4)

    if not words1 or not words2:
        return False

    overlap = words1 & words2
    return len(overlap) >= 2 or len(overlap) / min(len(words1), len(words2)) > 0.3


def _extract_topic(text: str) -> str:
    """Extract a short topic descriptor from text."""
    # Take first meaningful phrase
    text = text.strip()
    if len(text) <= 50:
        return text

    # Try to find a natural break
    for punct in [":", ".", ",", " - "]:
        if punct in text[:60]:
            return text[: text.index(punct)].strip()

    # Fallback: first 50 chars
    return text[:50].strip() + "..."


def _is_actionable(text: str) -> bool:
    """Check if a statement is actionable (implementation-oriented)."""
    action_keywords = [
        "implement",
        "create",
        "add",
        "build",
        "design",
        "use",
        "ensure",
        "should",
        "must",
        "will",
        "configure",
        "deploy",
        "integrate",
        "update",
        "modify",
        "set up",
        "install",
    ]
    lower = text.lower()
    return any(kw in lower for kw in action_keywords)
