"""
Crux Detection for Debate Analysis.

Identifies debate-pivotal claims (cruxes) that, if resolved, would most
impact the debate outcome. A crux is a claim with:
1. High influence on other claims
2. High disagreement between agents
3. Significant uncertainty
4. High resolution impact

Also provides belief propagation analysis tools for:
- Identifying which claims need more evidence
- Estimating consensus probability
- What-if counterfactual analysis
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.knowledge.mound.adapters.belief_adapter import BeliefAdapter
    from aragora.reasoning.belief import BeliefNetwork

logger = logging.getLogger(__name__)


@dataclass
class CruxClaim:
    """A claim identified as pivotal to the debate outcome."""

    claim_id: str
    statement: str
    author: str
    crux_score: float  # Combined score (0-1)
    influence_score: float  # How much this affects other claims
    disagreement_score: float  # How contested this claim is
    uncertainty_score: float  # Entropy of the belief
    centrality_score: float  # Graph centrality
    affected_claims: list[str]  # Claims that depend on this one
    contesting_agents: list[str]  # Agents who disagree about this claim
    resolution_impact: float  # How much resolving this would reduce uncertainty

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "author": self.author,
            "crux_score": round(self.crux_score, 4),
            "influence_score": round(self.influence_score, 4),
            "disagreement_score": round(self.disagreement_score, 4),
            "uncertainty_score": round(self.uncertainty_score, 4),
            "centrality_score": round(self.centrality_score, 4),
            "affected_claims": self.affected_claims,
            "contesting_agents": self.contesting_agents,
            "resolution_impact": round(self.resolution_impact, 4),
        }


@dataclass
class CruxAnalysisResult:
    """Result of crux detection analysis."""

    cruxes: list[CruxClaim]
    total_claims: int
    total_disagreements: int
    average_uncertainty: float
    convergence_barrier: float  # How hard it is to reach consensus
    recommended_focus: list[str]  # Ordered list of claim IDs to focus on

    def to_dict(self) -> dict[str, Any]:
        return {
            "cruxes": [c.to_dict() for c in self.cruxes],
            "total_claims": self.total_claims,
            "total_disagreements": self.total_disagreements,
            "average_uncertainty": round(self.average_uncertainty, 4),
            "convergence_barrier": round(self.convergence_barrier, 4),
            "recommended_focus": self.recommended_focus,
        }


class CruxDetector:
    """
    Advanced crux detection for identifying debate-pivotal claims.

    A crux is a claim that:
    1. Has high influence on other claims (high influence_score)
    2. Is contested by multiple agents (high disagreement_score)
    3. Has significant uncertainty (high entropy)
    4. Would reduce overall uncertainty if resolved

    Resolving cruxes is the fastest path to consensus.
    """

    def __init__(
        self,
        network: BeliefNetwork,
        influence_weight: float = 0.3,
        disagreement_weight: float = 0.3,
        uncertainty_weight: float = 0.2,
        centrality_weight: float = 0.2,
        km_adapter: BeliefAdapter | None = None,
        km_min_crux_score: float = 0.3,
    ):
        """
        Initialize crux detector.

        Args:
            network: BeliefNetwork to analyze
            influence_weight: Weight for influence score in crux calculation
            disagreement_weight: Weight for disagreement score
            uncertainty_weight: Weight for uncertainty score
            centrality_weight: Weight for centrality score
            km_adapter: Optional Knowledge Mound adapter for syncing cruxes
            km_min_crux_score: Minimum crux score for KM ingestion
        """
        self.network = network
        self.weights = {
            "influence": influence_weight,
            "disagreement": disagreement_weight,
            "uncertainty": uncertainty_weight,
            "centrality": centrality_weight,
        }
        self._km_adapter = km_adapter
        self._km_min_crux_score = km_min_crux_score

    def set_km_adapter(self, adapter: BeliefAdapter) -> None:
        """Set the Knowledge Mound adapter for bidirectional sync."""
        self._km_adapter = adapter

    def compute_influence_scores(self) -> dict[str, float]:
        """
        Compute influence scores for all claims.

        Influence = how much changing this claim affects the network.
        Uses counterfactual analysis: set claim to true vs false and
        measure total change in other posteriors.
        """
        from aragora.reasoning.belief import BeliefDistribution

        influence_scores: dict[str, float] = {}

        for node_id, node in self.network.nodes.items():
            # Save current state
            original_posteriors = {
                nid: BeliefDistribution(
                    p_true=n.posterior.p_true,
                    p_false=n.posterior.p_false,
                )
                for nid, n in self.network.nodes.items()
            }

            # Set claim to definitely true
            node.posterior = BeliefDistribution(p_true=0.99, p_false=0.01)
            self.network.propagate()
            effects_if_true = {
                nid: self.network.nodes[nid].posterior.p_true
                for nid in self.network.nodes
                if nid != node_id
            }

            # Restore and set to definitely false
            for nid, post in original_posteriors.items():
                self.network.nodes[nid].posterior = post
            node.posterior = BeliefDistribution(p_true=0.01, p_false=0.99)
            self.network.propagate()
            effects_if_false = {
                nid: self.network.nodes[nid].posterior.p_true
                for nid in self.network.nodes
                if nid != node_id
            }

            # Influence = average absolute change
            total_change = 0.0
            for nid in effects_if_true:
                total_change += abs(effects_if_true[nid] - effects_if_false[nid])
            influence = total_change / max(1, len(effects_if_true))

            influence_scores[node_id] = influence

            # Restore original state
            for nid, post in original_posteriors.items():
                self.network.nodes[nid].posterior = post

        # Normalize to 0-1
        max_influence = max(influence_scores.values()) if influence_scores else 1.0
        if max_influence > 0:
            influence_scores = {k: v / max_influence for k, v in influence_scores.items()}

        return influence_scores

    def compute_disagreement_scores(self) -> dict[str, tuple[float, list[str]]]:
        """
        Compute disagreement scores for all claims.

        Attribution is read from the **direction and polarity of the edges**, not
        from variance across belief values (#9644). A ``CONTRADICTS`` factor from
        S to A is already the recorded fact "S's author contests A" — exact,
        directional, and impossible to invert. Deriving it from prior or
        posterior spread instead was wrong three separate ways:

        * posteriors are measured after ``propagate()`` has reconciled the very
          disagreement being measured, so a contested claim trended to zero;
        * a mean-and-threshold test over priors degenerates as contesters are
          added — with a uniform prior each contester sits ``0.6/(k+1)`` from the
          mean, which a strict ``> 0.2`` cut excludes for every ``k >= 2``, i.e.
          exactly the 3+ agent debates that are the normal configuration;
        * symmetric traversal ignored direction, so a critiqued proposer was
          reported as contesting the critiques of them.

        ``SUPPORTS`` edges never produce dissent, and an author never contests
        their own claim: this list becomes ``DecisionReceipt`` dissent
        attribution, where either would be a false statement about a person.

        Magnitude is the summed contest strength (``factor.strength``, carrying
        critique severity), capped at 1.0 and scaled by the contested share of
        the authors who took a *stance* on the claim. So a severity-9 objection
        outweighs a nitpick, two objections outweigh one, and a claim with three
        supporters and one contester scores below one contested by three.

        Only ``SUPPORTS``/``CONTRADICTS`` authors count toward that share.
        Non-stance relations (``REFINES``, ``QUALIFIES``, ``DEPENDS_ON``) are not
        treated as either agreement or dissent — silence about a claim is not
        support for it. Whether a qualification is *partial* dissent is a
        modelling question worth its own change.
        """
        from aragora.reasoning.claims import RelationType

        disagreement_scores: dict[str, tuple[float, list[str]]] = {}

        for node_id, node in self.network.nodes.items():
            contesters: dict[str, float] = {}
            supporters: set[str] = set()

            for factor_id in self.network.node_factors.get(node_id, []):
                factor = self.network.factors.get(factor_id)
                if not factor or factor.target_node_id != node_id:
                    # Only incoming edges say something about THIS claim; an
                    # outgoing one says something about the other claim.
                    continue
                source = self.network.nodes.get(factor.source_node_id)
                if not source or not source.author or source.author == node.author:
                    continue

                if factor.relation_type == RelationType.CONTRADICTS:
                    strength = float(getattr(factor, "strength", 1.0) or 0.0)
                    if strength <= 0:
                        # A zero-weight contradiction would name a contester on a
                        # claim scoring 0.0 — listed as contested by someone while
                        # the same result excludes it from `total_disagreements`.
                        # Keep the list and the count telling one story.
                        continue
                    contesters[source.author] = max(contesters.get(source.author, 0.0), strength)
                elif factor.relation_type == RelationType.SUPPORTS:
                    supporters.add(source.author)

            if not contesters:
                disagreement_scores[node_id] = (0.0, [])
                continue

            # Capped sum, not mean: averaging made a second, weaker contester
            # LOWER the score (0.7 alone -> 0.7; 0.7 plus a 0.1 nitpick -> 0.4),
            # so a more widely contested claim could rank as less contested.
            # This is monotonic in both the strength of objections and the
            # number of distinct agents raising them.
            contest_weight = min(1.0, sum(contesters.values()))
            stance_authors = len(contesters) + len(supporters - set(contesters))
            contested_share = len(contesters) / stance_authors if stance_authors else 1.0
            disagreement = min(1.0, max(0.0, contest_weight * contested_share))
            disagreement_scores[node_id] = (disagreement, sorted(contesters))

        return disagreement_scores

    def compute_resolution_impact(self, node_id: str) -> float:
        """
        Estimate how much resolving this claim would reduce total uncertainty.

        Impact = sum of entropy reduction in connected claims if this were resolved.
        """
        from aragora.reasoning.belief import BeliefDistribution

        # Save current state
        original_posteriors = {
            nid: BeliefDistribution(
                p_true=n.posterior.p_true,
                p_false=n.posterior.p_false,
            )
            for nid, n in self.network.nodes.items()
        }

        current_total_entropy = sum(n.posterior.entropy for n in self.network.nodes.values())

        # Resolve this claim (set to high confidence)
        self.network.nodes[node_id].posterior = BeliefDistribution(p_true=0.95, p_false=0.05)
        self.network.propagate()

        resolved_entropy = sum(n.posterior.entropy for n in self.network.nodes.values())
        impact_true = current_total_entropy - resolved_entropy

        # Restore and try false
        for nid, post in original_posteriors.items():
            self.network.nodes[nid].posterior = post
        self.network.nodes[node_id].posterior = BeliefDistribution(p_true=0.05, p_false=0.95)
        self.network.propagate()

        resolved_entropy = sum(n.posterior.entropy for n in self.network.nodes.values())
        impact_false = current_total_entropy - resolved_entropy

        # Restore original state
        for nid, post in original_posteriors.items():
            self.network.nodes[nid].posterior = post

        # Impact is the minimum of the two (worst-case guarantee)
        return float(max(0.0, min(impact_true, impact_false)))

    def detect_cruxes(self, top_k: int = 5, min_score: float = 0.1) -> CruxAnalysisResult:
        """
        Detect crux claims in the debate.

        Args:
            top_k: Maximum number of cruxes to return
            min_score: Minimum crux score threshold

        Returns:
            CruxAnalysisResult with ranked crux claims and analysis
        """
        if not self.network.nodes:
            return CruxAnalysisResult(
                cruxes=[],
                total_claims=0,
                total_disagreements=0,
                average_uncertainty=0.0,
                convergence_barrier=0.0,
                recommended_focus=[],
            )

        # Ensure propagation has run
        self.network.propagate()

        # Compute component scores
        influence_scores = self.compute_influence_scores()
        disagreement_data = self.compute_disagreement_scores()

        cruxes = []
        total_disagreements = 0

        for node_id, node in self.network.nodes.items():
            influence = influence_scores.get(node_id, 0.0)
            disagreement, contesting = disagreement_data.get(node_id, (0.0, []))
            uncertainty = node.posterior.entropy / math.log2(3)  # Normalize
            centrality = node.centrality

            if disagreement > 0:
                total_disagreements += 1

            # Compute resolution impact for promising candidates
            resolution_impact = 0.0
            preliminary_score = (
                self.weights["influence"] * influence
                + self.weights["disagreement"] * disagreement
                + self.weights["uncertainty"] * uncertainty
                + self.weights["centrality"] * centrality
            )

            if preliminary_score > min_score * 0.5:
                resolution_impact = self.compute_resolution_impact(node_id)
                # Normalize resolution impact
                max_possible = len(self.network.nodes) * math.log2(3)
                resolution_impact = resolution_impact / max_possible if max_possible > 0 else 0

            # Final crux score includes resolution impact
            crux_score = (
                self.weights["influence"] * influence
                + self.weights["disagreement"] * disagreement
                + self.weights["uncertainty"] * uncertainty
                + self.weights["centrality"] * centrality
                + 0.2 * resolution_impact  # Bonus for high resolution impact
            )

            # Get affected claims (children in the graph)
            affected = [
                self.network.nodes[child_id].claim_id
                for child_id in node.child_ids
                if child_id in self.network.nodes
            ]

            cruxes.append(
                CruxClaim(
                    claim_id=node.claim_id,
                    statement=node.claim_statement,
                    author=node.author,
                    crux_score=crux_score,
                    influence_score=influence,
                    disagreement_score=disagreement,
                    uncertainty_score=uncertainty,
                    centrality_score=centrality,
                    affected_claims=affected,
                    contesting_agents=contesting,
                    resolution_impact=resolution_impact,
                )
            )

        # Sort by crux score and filter
        cruxes = sorted(cruxes, key=lambda c: -c.crux_score)
        cruxes = [c for c in cruxes if c.crux_score >= min_score][:top_k]

        # Emit CRUX_DETECTED events for significant cruxes
        if cruxes:
            try:
                from aragora.events.dispatcher import dispatch_event

                for crux in cruxes:
                    dispatch_event(
                        "crux_detected",
                        {
                            "claim_id": crux.claim_id,
                            "statement": crux.statement[:200],
                            "crux_score": round(crux.crux_score, 4),
                            "influence_score": round(crux.influence_score, 4),
                            "disagreement_score": round(crux.disagreement_score, 4),
                            "contesting_agents": crux.contesting_agents,
                            "resolution_impact": round(crux.resolution_impact, 4),
                        },
                    )
            except Exception as e:  # noqa: BLE001
                logger.debug("Crux event emission unavailable: %s", e)

        # Compute summary statistics
        avg_uncertainty = sum(n.posterior.entropy for n in self.network.nodes.values()) / len(
            self.network.nodes
        )

        # Convergence barrier = combination of disagreement and uncertainty
        convergence_barrier = 0.4 * (total_disagreements / len(self.network.nodes)) + 0.6 * (
            avg_uncertainty / math.log2(3)
        )

        # Sync significant cruxes to Knowledge Mound
        if self._km_adapter:
            for crux in cruxes:
                if crux.crux_score >= self._km_min_crux_score:
                    try:
                        self._km_adapter.store_crux(crux)
                        logger.debug("Crux synced to Knowledge Mound: %s", crux.claim_id)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Failed to sync crux to KM: %s", e)

        return CruxAnalysisResult(
            cruxes=cruxes,
            total_claims=len(self.network.nodes),
            total_disagreements=total_disagreements,
            average_uncertainty=avg_uncertainty,
            convergence_barrier=convergence_barrier,
            recommended_focus=[c.claim_id for c in cruxes],
        )

    def suggest_resolution_strategy(self, crux: CruxClaim) -> dict[str, Any]:
        """
        Suggest how to resolve a crux claim.

        Returns actionable suggestions for facilitators and participants.
        """
        suggestions = []

        # Based on the type of crux
        if crux.disagreement_score > 0.5:
            suggestions.append(
                {
                    "type": "mediation",
                    "action": "Request agents to explicitly address opposing arguments",
                    "reason": f"High disagreement ({crux.disagreement_score:.0%}) between agents",
                }
            )

        if crux.uncertainty_score > 0.6:
            suggestions.append(
                {
                    "type": "evidence",
                    "action": "Request additional evidence or citations for this claim",
                    "reason": f"High uncertainty ({crux.uncertainty_score:.0%}) needs grounding",
                }
            )

        if crux.influence_score > 0.7:
            suggestions.append(
                {
                    "type": "decomposition",
                    "action": "Break this claim into smaller, independently verifiable sub-claims",
                    "reason": f"High influence ({crux.influence_score:.0%}) suggests compound claim",
                }
            )

        if len(crux.affected_claims) > 3:
            suggestions.append(
                {
                    "type": "priority",
                    "action": "Resolve this claim before dependent claims",
                    "reason": f"Affects {len(crux.affected_claims)} other claims in the debate",
                }
            )

        if crux.contesting_agents:
            suggestions.append(
                {
                    "type": "direct_dialogue",
                    "action": f"Facilitate direct exchange between: {', '.join(crux.contesting_agents)}",
                    "reason": "These agents have divergent views on this claim",
                }
            )

        return {
            "claim_id": crux.claim_id,
            "statement": crux.statement[:200],
            "crux_score": crux.crux_score,
            "suggestions": suggestions,
            "priority": "high" if crux.crux_score > 0.5 else "medium",
        }


class BeliefPropagationAnalyzer:
    """
    High-level analyzer for belief propagation in debates.

    Provides insights into:
    - Which claims need more evidence
    - Where the debate is stuck
    - What would move the needle on key claims
    """

    def __init__(self, network: BeliefNetwork):
        self.network = network

    def identify_debate_cruxes(self, top_k: int = 3) -> list[dict[str, Any]]:
        """
        Identify the key claims that, if resolved, would most
        impact the debate outcome.

        A "crux" is a claim with high centrality and high uncertainty.
        """
        cruxes: list[dict[str, Any]] = []

        for node in self.network.nodes.values():
            # Crux score = centrality * entropy
            score = node.centrality * node.posterior.entropy

            cruxes.append(
                {
                    "claim_id": node.claim_id,
                    "statement": node.claim_statement,
                    "author": node.author,
                    "crux_score": score,
                    "centrality": node.centrality,
                    "entropy": node.posterior.entropy,
                    "current_belief": node.posterior.to_dict(),
                }
            )

        return sorted(cruxes, key=lambda x: -float(x["crux_score"]))[:top_k]

    def suggest_evidence_targets(self) -> list[dict[str, Any]]:
        """
        Suggest which claims need more evidence to reduce uncertainty.
        """
        suggestions = []

        for node in self.network.nodes.values():
            # High entropy + high centrality = needs evidence
            if node.posterior.entropy > 0.8 and node.centrality > 0.05:
                suggestions.append(
                    {
                        "claim_id": node.claim_id,
                        "statement": node.claim_statement,
                        "author": node.author,
                        "current_uncertainty": node.posterior.entropy,
                        "importance": node.centrality,
                        "suggestion": f"Provide evidence to resolve: '{node.claim_statement[:100]}...'",
                    }
                )

        return sorted(suggestions, key=lambda x: -x["importance"])

    def compute_consensus_probability(self) -> dict[str, Any]:
        """
        Estimate probability of reaching consensus.

        Based on average certainty and agreement between claims.
        """
        if not self.network.nodes:
            return {"probability": 0.0, "explanation": "No claims in network"}

        # Average confidence across all claims
        avg_confidence = sum(n.posterior.confidence for n in self.network.nodes.values()) / len(
            self.network.nodes
        )

        # Count contested claims
        contested = len(self.network.get_contested_claims())
        contest_ratio = contested / len(self.network.nodes)

        # Consensus probability
        consensus_prob = avg_confidence * (1 - contest_ratio)

        return {
            "probability": consensus_prob,
            "average_confidence": avg_confidence,
            "contested_claims": contested,
            "contest_ratio": contest_ratio,
            "explanation": (
                f"Consensus probability {consensus_prob:.0%} based on "
                f"average confidence {avg_confidence:.0%} and "
                f"{contested} contested claims ({contest_ratio:.0%})"
            ),
        }

    def what_if_analysis(
        self,
        hypothetical: dict[str, bool],
    ) -> dict[str, Any]:
        """
        Analyze: "What if these claims were true/false?"

        Returns how the debate state would change.
        """
        from aragora.reasoning.belief import BeliefDistribution

        # Save current state
        original_posteriors = {
            nid: BeliefDistribution(
                p_true=n.posterior.p_true,
                p_false=n.posterior.p_false,
            )
            for nid, n in self.network.nodes.items()
        }

        # Apply hypothetical and propagate
        for claim_id, value in hypothetical.items():
            node = self.network.get_node_by_claim(claim_id)
            if node:
                if value:
                    node.posterior = BeliefDistribution(p_true=0.99, p_false=0.01)
                else:
                    node.posterior = BeliefDistribution(p_true=0.01, p_false=0.99)

        self.network.propagate()

        # Compute changes
        changes = []
        for nid, node in self.network.nodes.items():
            original = original_posteriors[nid]
            delta = node.posterior.p_true - original.p_true
            if abs(delta) > 0.05:
                changes.append(
                    {
                        "claim_id": node.claim_id,
                        "statement": node.claim_statement[:100],
                        "original_p_true": original.p_true,
                        "new_p_true": node.posterior.p_true,
                        "delta": delta,
                    }
                )

        # Restore original state
        for nid, posterior in original_posteriors.items():
            self.network.nodes[nid].posterior = posterior

        return {
            "hypothetical": hypothetical,
            "affected_claims": len(changes),
            "changes": sorted(changes, key=lambda x: -abs(x["delta"])),
        }


__all__ = [
    "CruxClaim",
    "CruxAnalysisResult",
    "CruxDetector",
    "BeliefPropagationAnalyzer",
]
