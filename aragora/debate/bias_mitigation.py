"""
Bias Mitigation Utilities for Agent-as-a-Judge Improvements.

Implements bias mitigation techniques from research on LLM-as-a-Judge reliability
(arXiv:2508.02994 "When AIs Judge AIs: The Rise of Agent-as-a-Judge Evaluation").

Provides:
- Position shuffling for proposal presentation order
- Self-vote detection and down-weighting
- Verbosity normalization for response length bias
- Process-based evaluation with multi-criteria rubrics

All features are opt-in via DebateProtocol configuration flags.
"""

from __future__ import annotations

import ast
import logging
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.core import Vote
    from aragora.evidence.collector import EvidencePack

logger = logging.getLogger(__name__)

# =============================================================================
# Position Bias Mitigation
# =============================================================================


@dataclass
class PositionBiasConfig:
    """Configuration for position bias mitigation."""

    enabled: bool = False
    num_permutations: int = 3  # Number of random orderings to average
    seed: int | None = None  # For reproducibility in tests
    log_permutation_details: bool = False


def shuffle_proposals(
    proposals: dict[str, str],
    seed: int | None = None,
) -> dict[str, str]:
    """Shuffle proposal ordering to mitigate position bias.

    Research shows LLMs exhibit position bias - favoring proposals that appear
    first or in certain positions. Shuffling presentation order helps mitigate this.

    Args:
        proposals: Original proposals dict mapping agent_name -> proposal_text
        seed: Optional seed for reproducibility in tests

    Returns:
        New dict with shuffled key order
    """
    items = list(proposals.items())
    rng = random.Random(seed)  # noqa: S311 -- position shuffling for fairness
    rng.shuffle(items)
    return dict(items)


def generate_permutations(
    proposals: dict[str, str],
    num_permutations: int = 3,
    base_seed: int | None = None,
) -> list[dict[str, str]]:
    """Generate multiple proposal orderings for averaging across permutations.

    By collecting votes on multiple orderings and averaging, position bias
    effects are reduced since each proposal appears in different positions.

    Args:
        proposals: Original proposals dict
        num_permutations: Number of orderings to generate (default: 3)
        base_seed: Optional base seed for reproducibility

    Returns:
        List of proposal dicts with different orderings
    """
    if num_permutations <= 1:
        return [proposals]

    permutations = []
    for i in range(num_permutations):
        seed = None
        if base_seed is not None:
            # Create unique but deterministic seed for each permutation
            seed = base_seed + i * 1000
        permutations.append(shuffle_proposals(proposals, seed))

    return permutations


def average_permutation_votes(
    votes_by_agent: dict[str, list[Vote]],
    proposals: dict[str, str],
) -> list[Vote]:
    """Average votes across multiple permutations.

    Takes votes collected from multiple orderings and produces a single
    vote per agent by selecting the most frequently chosen option.

    Args:
        votes_by_agent: Dict mapping agent_name -> list of votes from each permutation
        proposals: Original proposals dict (for reference)

    Returns:
        List of averaged votes, one per agent
    """
    from aragora.core import Vote

    final_votes = []

    for agent_name, votes in votes_by_agent.items():
        if not votes:
            continue

        # Count choices across permutations
        choice_counts: Counter[str] = Counter()
        total_confidence = 0.0
        reasonings = []

        for vote in votes:
            choice_counts[vote.choice] += 1
            total_confidence += vote.confidence
            reasonings.append(vote.reasoning)

        # Most frequent choice wins
        if choice_counts:
            choice, count = choice_counts.most_common(1)[0]
            avg_confidence = total_confidence / len(votes)
            consistency = count / len(votes)

            # Combine reasonings with note about averaging
            combined_reasoning = (
                f"[Averaged across {len(votes)} orderings, {consistency:.0%} consistent] "
                + reasonings[0]
            )

            final_votes.append(
                Vote(
                    agent=agent_name,
                    choice=choice,
                    reasoning=combined_reasoning,
                    confidence=avg_confidence,
                    continue_debate=votes[0].continue_debate,
                )
            )

            logger.debug(
                "position_bias_averaged agent=%s choice=%s consistency=%.0f%% avg_confidence=%.2f",
                agent_name,
                choice,
                consistency * 100,
                avg_confidence,
            )

    return final_votes


# =============================================================================
# Self-Enhancement Bias Mitigation
# =============================================================================


@dataclass
class SelfVoteConfig:
    """Configuration for self-vote bias mitigation."""

    enabled: bool = False
    mode: str = "downweight"  # "exclude", "downweight", "log_only"
    downweight_factor: float = 0.5  # Applied when mode="downweight"
    log_self_votes: bool = True


def detect_self_vote(
    vote: Vote,
    proposals: dict[str, str],
) -> bool:
    """Detect if an agent voted for their own proposal.

    Self-enhancement bias causes LLMs to prefer their own outputs.
    This function detects when an agent's vote choice matches their own proposal.

    Args:
        vote: The vote to check
        proposals: Dict mapping agent names to their proposals

    Returns:
        True if the agent voted for their own proposal
    """
    voter = vote.agent.lower().strip()
    choice = vote.choice.lower().strip()

    # Direct name match
    if voter == choice:
        return True

    # Check various patterns that might indicate self-vote
    voter_patterns = [
        voter,
        voter.replace("_", " "),
        voter.replace("-", " "),
        voter.split("_")[0],  # Handle "claude_proposer" -> "claude"
    ]

    for pattern in voter_patterns:
        if pattern in choice:
            return True

    # Check if choice explicitly references voter's proposal
    if f"proposal from {voter}" in choice:
        return True
    if f"{voter}'s proposal" in choice:
        return True

    return False


def apply_self_vote_penalty(
    weights: dict[str, float],
    votes: list[Vote],
    proposals: dict[str, str],
    config: SelfVoteConfig,
) -> dict[str, float]:
    """Apply penalties to agents who voted for their own proposals.

    Args:
        weights: Original vote weights by agent name
        votes: List of votes
        proposals: Dict of proposals
        config: Self-vote configuration

    Returns:
        Adjusted weights dict
    """
    if not config.enabled:
        return weights

    adjusted = dict(weights)

    for vote in votes:
        if detect_self_vote(vote, proposals):
            agent = vote.agent
            original_weight = adjusted.get(agent, 1.0)

            if config.mode == "exclude":
                adjusted[agent] = 0.0
                if config.log_self_votes:
                    logger.info(
                        "self_vote_excluded agent=%s choice=%s original_weight=%.2f",
                        agent,
                        vote.choice,
                        original_weight,
                    )

            elif config.mode == "downweight":
                adjusted[agent] = original_weight * config.downweight_factor
                if config.log_self_votes:
                    logger.info(
                        "self_vote_downweighted agent=%s choice=%s weight=%.2f->%.2f",
                        agent,
                        vote.choice,
                        original_weight,
                        adjusted[agent],
                    )

            else:  # log_only
                if config.log_self_votes:
                    logger.info(
                        "self_vote_detected agent=%s choice=%s (no penalty applied)",
                        agent,
                        vote.choice,
                    )

    return adjusted


# =============================================================================
# Verbosity Bias Normalization
# =============================================================================


@dataclass
class VerbosityBiasConfig:
    """Configuration for verbosity bias mitigation."""

    enabled: bool = False
    target_length: int = 1000  # "ideal" proposal length in chars
    penalty_threshold: float = 3.0  # Penalize if > 3x target length
    max_penalty: float = 0.3  # Max 30% weight reduction
    log_adjustments: bool = False


def calculate_verbosity_factor(
    proposal_length: int,
    config: VerbosityBiasConfig,
) -> float:
    """Calculate weight factor based on proposal verbosity.

    Research shows LLMs exhibit verbosity bias - favoring longer responses
    regardless of quality. This function penalizes excessively long proposals.

    Args:
        proposal_length: Character count of proposal
        config: Verbosity configuration

    Returns:
        Weight factor between (1.0 - max_penalty) and 1.0
    """
    if not config.enabled:
        return 1.0

    if proposal_length <= 0:
        return 1.0

    ratio = proposal_length / config.target_length

    # No penalty below threshold
    if ratio <= config.penalty_threshold:
        return 1.0

    # Linear penalty above threshold
    excess = ratio - config.penalty_threshold
    penalty = min(config.max_penalty, excess * 0.1)

    factor = 1.0 - penalty

    if config.log_adjustments:
        logger.debug(
            "verbosity_factor length=%s ratio=%.1fx target factor=%.2f",
            proposal_length,
            ratio,
            factor,
        )

    return factor


def get_verbosity_weights(
    proposals: dict[str, str],
    config: VerbosityBiasConfig,
) -> dict[str, float]:
    """Calculate verbosity weight factors for all proposals.

    Args:
        proposals: Dict mapping agent names to proposals
        config: Verbosity configuration

    Returns:
        Dict mapping agent names to verbosity factors
    """
    return {
        agent: calculate_verbosity_factor(len(proposal), config)
        for agent, proposal in proposals.items()
    }


# =============================================================================
# Process-Based Evaluation (Multi-Criteria Rubrics)
# =============================================================================


@dataclass
class EvaluationCriterion:
    """Single evaluation criterion for rubric-based assessment."""

    name: str
    description: str
    weight: float = 1.0
    required: bool = False


@dataclass
class ProcessEvaluationConfig:
    """Configuration for process-based evaluation."""

    enabled: bool = False
    criteria: list[EvaluationCriterion] = field(
        default_factory=lambda: [
            EvaluationCriterion(
                name="reasoning_clarity",
                description="Is the reasoning chain clear and logical?",
                weight=1.0,
            ),
            EvaluationCriterion(
                name="evidence_usage",
                description="Are claims supported by evidence (EVID-xxx citations)?",
                weight=1.2,
            ),
            EvaluationCriterion(
                name="counterargument_consideration",
                description="Does the proposal address potential counterarguments?",
                weight=0.8,
            ),
            EvaluationCriterion(
                name="uncertainty_acknowledgment",
                description="Are limitations and uncertainties acknowledged?",
                weight=0.6,
            ),
            EvaluationCriterion(
                name="synthesis_quality",
                description="Does it synthesize insights from other proposals?",
                weight=1.0,
            ),
        ]
    )
    tool_verification_enabled: bool = False


@dataclass
class ProcessEvaluationResult:
    """Result of process-based evaluation."""

    agent: str
    proposal_preview: str
    criterion_scores: dict[str, float]  # criterion_name -> 0-1 score
    weighted_total: float
    evaluation_notes: list[str]
    tool_verification_results: dict[str, Any] | None = None


class ProcessEvaluator:
    """Evaluates proposals using multi-criteria rubrics.

    Goes beyond simple output comparison to evaluate reasoning quality,
    evidence usage, and other process indicators.
    """

    def __init__(
        self,
        config: ProcessEvaluationConfig | None = None,
        generate_fn: Callable[..., Any] | None = None,
    ):
        """Initialize process evaluator.

        Args:
            config: Evaluation configuration with criteria
            generate_fn: Optional LLM generation function for complex criteria
        """
        self.config = config or ProcessEvaluationConfig()
        self._generate_fn = generate_fn

    async def evaluate_proposal(
        self,
        agent_name: str,
        proposal: str,
        task: str,
        evidence_pack: EvidencePack | None = None,
    ) -> ProcessEvaluationResult:
        """Evaluate a proposal against the rubric.

        Args:
            agent_name: Name of the proposing agent
            proposal: The proposal text
            task: The debate task
            evidence_pack: Optional evidence for verification

        Returns:
            ProcessEvaluationResult with criterion scores
        """
        criterion_scores: dict[str, float] = {}
        notes: list[str] = []

        for criterion in self.config.criteria:
            score = await self._evaluate_criterion(proposal, criterion, task, evidence_pack)
            criterion_scores[criterion.name] = score

            if score < 0.5 and criterion.required:
                notes.append(f"REQUIRED criterion '{criterion.name}' scored low: {score:.2f}")

        # Calculate weighted total
        total_weight = sum(c.weight for c in self.config.criteria)
        weighted_total = (
            sum(criterion_scores[c.name] * c.weight for c in self.config.criteria) / total_weight
            if total_weight > 0
            else 0.0
        )

        # Tool verification if enabled
        tool_results = None
        if self.config.tool_verification_enabled:
            tool_results = await self._run_tool_verification(proposal, evidence_pack)

        logger.debug(
            "process_evaluation agent=%s weighted_total=%.2f criteria=%s",
            agent_name,
            weighted_total,
            criterion_scores,
        )

        return ProcessEvaluationResult(
            agent=agent_name,
            proposal_preview=proposal[:200],
            criterion_scores=criterion_scores,
            weighted_total=weighted_total,
            evaluation_notes=notes,
            tool_verification_results=tool_results,
        )

    async def _evaluate_criterion(
        self,
        proposal: str,
        criterion: EvaluationCriterion,
        task: str,
        evidence_pack: EvidencePack | None,
    ) -> float:
        """Evaluate a single criterion using pattern matching or LLM."""
        # Fast path: pattern-based evaluation for some criteria
        if criterion.name == "evidence_usage":
            return self._score_evidence_usage(proposal, evidence_pack)

        if criterion.name == "uncertainty_acknowledgment":
            return self._score_uncertainty(proposal)

        if criterion.name == "reasoning_clarity":
            return self._score_reasoning_clarity(proposal)

        if criterion.name == "counterargument_consideration":
            return self._score_counterarguments(proposal)

        if criterion.name == "synthesis_quality":
            return self._score_synthesis(proposal)

        # LLM-based evaluation for custom criteria
        if self._generate_fn:
            return await self._llm_evaluate_criterion(proposal, criterion, task)

        return 0.5  # Default neutral score

    def _score_evidence_usage(
        self,
        proposal: str,
        evidence_pack: EvidencePack | None,
    ) -> float:
        """Score evidence citation quality."""
        citations = re.findall(r"EVID-([a-zA-Z0-9]+)", proposal)

        if not citations:
            return 0.2  # No citations

        if evidence_pack:
            valid_ids = {s.id for s in evidence_pack.snippets}
            valid_citations = sum(1 for c in citations if c in valid_ids)
            return min(1.0, 0.3 + (valid_citations * 0.2))

        return min(1.0, 0.3 + (len(citations) * 0.15))

    def _score_uncertainty(self, proposal: str) -> float:
        """Score acknowledgment of uncertainty."""
        uncertainty_markers = [
            "uncertain",
            "unclear",
            "may",
            "might",
            "could",
            "limitation",
            "caveat",
            "however",
            "although",
            "depends on",
            "trade-off",
            "risk",
            "assumption",
            "if we assume",
            "not certain",
        ]

        proposal_lower = proposal.lower()
        matches = sum(1 for m in uncertainty_markers if m in proposal_lower)

        return min(1.0, 0.2 + (matches * 0.12))

    def _score_reasoning_clarity(self, proposal: str) -> float:
        """Score clarity of reasoning chain."""
        reasoning_markers = [
            "therefore",
            "thus",
            "hence",
            "because",
            "since",
            "as a result",
            "this means",
            "consequently",
            "it follows",
            "given that",
            "first",
            "second",
            "finally",
            "in conclusion",
        ]

        proposal_lower = proposal.lower()
        matches = sum(1 for m in reasoning_markers if m in proposal_lower)

        # Also check for structure (numbered lists, bullets)
        has_structure = bool(re.search(r"(\d+\.|[-*])\s+", proposal))
        structure_bonus = 0.15 if has_structure else 0

        return min(1.0, 0.3 + (matches * 0.1) + structure_bonus)

    def _score_counterarguments(self, proposal: str) -> float:
        """Score consideration of counterarguments."""
        counter_markers = [
            "on the other hand",
            "alternatively",
            "critics might argue",
            "one could argue",
            "counterpoint",
            "objection",
            "concern",
            "downside",
            "weakness",
            "challenge",
            "however",
            "but",
            "yet",
            "although",
            "despite",
        ]

        proposal_lower = proposal.lower()
        matches = sum(1 for m in counter_markers if m in proposal_lower)

        return min(1.0, 0.2 + (matches * 0.12))

    def _score_synthesis(self, proposal: str) -> float:
        """Score synthesis of other proposals."""
        synthesis_markers = [
            "building on",
            "as mentioned by",
            "combining",
            "integrating",
            "synthesizing",
            "agrees with",
            "extends",
            "similar to",
            "in line with",
            "complementary",
            "both approaches",
            "common ground",
        ]

        proposal_lower = proposal.lower()
        matches = sum(1 for m in synthesis_markers if m in proposal_lower)

        return min(1.0, 0.2 + (matches * 0.15))

    async def _llm_evaluate_criterion(
        self,
        proposal: str,
        criterion: EvaluationCriterion,
        task: str,
    ) -> float:
        """Use LLM to evaluate a custom criterion."""
        if not self._generate_fn:
            return 0.5

        prompt = f"""Evaluate this proposal on a scale of 0-10 for the following criterion:

Criterion: {criterion.name}
Description: {criterion.description}

Task: {task}

Proposal:
{proposal[:2000]}

Respond with ONLY a number from 0-10."""

        try:
            import asyncio

            response = await asyncio.wait_for(
                self._generate_fn(prompt),
                timeout=10.0,
            )

            # Parse score from response
            score_match = re.search(r"(\d+(?:\.\d+)?)", str(response))
            if score_match:
                score = float(score_match.group(1)) / 10.0
                return min(1.0, max(0.0, score))

        except asyncio.TimeoutError:
            logger.debug("LLM criterion evaluation timed out")
        except (ValueError, TypeError) as e:
            logger.debug("LLM criterion evaluation failed to parse response: %s", e)
        except (RuntimeError, OSError, ConnectionError, KeyError, AttributeError) as e:
            logger.warning("Unexpected error in LLM criterion evaluation: %s", e)

        return 0.5

    def _verify_code_block(self, language: str | None, code: str) -> dict[str, Any]:
        """Verify a code block for syntax validity.

        Args:
            language: The programming language tag (e.g., "python", "py")
            code: The code content to verify

        Returns:
            Dict with verification results including validity and any errors
        """
        result: dict[str, Any] = {
            "language": language or "unknown",
            "valid": False,
            "error": None,
        }

        # Only verify Python code (other languages would need external tools)
        if language in ("python", "py", None, ""):
            try:
                ast.parse(code)
                result["valid"] = True
            except SyntaxError as e:
                result["error"] = f"Line {e.lineno}: {e.msg}"

        return result

    def _verify_evidence_citations(
        self,
        proposal: str,
        evidence_pack: EvidencePack,
    ) -> dict[str, Any]:
        """Verify citations in proposal match available evidence.

        Args:
            proposal: The proposal text containing citations
            evidence_pack: The evidence pack with available snippets

        Returns:
            Dict with citation validation results
        """
        # Match citation patterns like [1], [2], etc.
        citation_pattern = r"\[(\d+)\]"
        found_citations = set(re.findall(citation_pattern, proposal))

        # Available citations are 1-indexed based on snippet count
        available_citations = {str(i + 1) for i in range(len(evidence_pack.snippets))}

        valid_citations = found_citations & available_citations
        invalid_citations = found_citations - available_citations

        return {
            "status": "valid" if not invalid_citations else "warnings",
            "valid_citations": sorted(valid_citations, key=int),
            "invalid_citations": sorted(invalid_citations, key=int),
            "total_found": len(found_citations),
            "total_available": len(available_citations),
        }

    async def _run_tool_verification(
        self,
        proposal: str,
        evidence_pack: EvidencePack | None,
    ) -> dict[str, Any]:
        """Run tool-based verification (code execution, evidence re-check)."""
        results: dict[str, Any] = {}

        # Check for code blocks that could be verified
        code_blocks = re.findall(r"```(\w+)?\n(.*?)```", proposal, re.DOTALL)
        if code_blocks:
            results["code_blocks_found"] = len(code_blocks)
            verification_results = [
                self._verify_code_block(lang, code) for lang, code in code_blocks
            ]
            results["code_verification"] = {
                "status": ("valid" if all(r["valid"] for r in verification_results) else "invalid"),
                "blocks": verification_results,
            }

        # Verify evidence citations match available evidence
        if evidence_pack:
            results["evidence_count"] = len(evidence_pack.snippets)
            results["evidence_verification"] = self._verify_evidence_citations(
                proposal, evidence_pack
            )

        return results


# =============================================================================
# Unified Bias Mitigation Context
# =============================================================================


@dataclass
class BiasMitigationConfig:
    """Unified configuration for all bias mitigation features."""

    # Position bias
    enable_position_shuffling: bool = False
    position_shuffling_permutations: int = 3
    position_shuffling_seed: int | None = None

    # Self-vote bias
    enable_self_vote_mitigation: bool = False
    self_vote_mode: str = "downweight"
    self_vote_downweight: float = 0.5

    # Verbosity bias
    enable_verbosity_normalization: bool = False
    verbosity_target_length: int = 1000
    verbosity_penalty_threshold: float = 3.0
    verbosity_max_penalty: float = 0.3

    # Process evaluation
    enable_process_evaluation: bool = False

    def get_position_config(self) -> PositionBiasConfig:
        """Get position bias configuration."""
        return PositionBiasConfig(
            enabled=self.enable_position_shuffling,
            num_permutations=self.position_shuffling_permutations,
            seed=self.position_shuffling_seed,
        )

    def get_self_vote_config(self) -> SelfVoteConfig:
        """Get self-vote configuration."""
        return SelfVoteConfig(
            enabled=self.enable_self_vote_mitigation,
            mode=self.self_vote_mode,
            downweight_factor=self.self_vote_downweight,
        )

    def get_verbosity_config(self) -> VerbosityBiasConfig:
        """Get verbosity configuration."""
        return VerbosityBiasConfig(
            enabled=self.enable_verbosity_normalization,
            target_length=self.verbosity_target_length,
            penalty_threshold=self.verbosity_penalty_threshold,
            max_penalty=self.verbosity_max_penalty,
        )

    def get_process_config(self) -> ProcessEvaluationConfig:
        """Get process evaluation configuration."""
        return ProcessEvaluationConfig(
            enabled=self.enable_process_evaluation,
        )

    def log_summary(self) -> None:
        """Log summary of enabled bias mitigation features."""
        logger.info(
            "bias_mitigation_config position_shuffling=%s self_vote=%s verbosity=%s process_eval=%s",
            self.enable_position_shuffling,
            self.enable_self_vote_mitigation,
            self.enable_verbosity_normalization,
            self.enable_process_evaluation,
        )
