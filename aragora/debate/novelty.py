"""
Novelty tracking for multi-agent debate proposals.

Tracks semantic distance from prior proposals to prevent convergence to mediocrity.
When agents propose ideas too similar to what's already been said, novelty scores
drop and can trigger trickster interventions.

Uses the same similarity backends as convergence detection:
1. SentenceTransformer (best accuracy)
2. TF-IDF (good accuracy)
3. Jaccard (fallback)

Novelty score = 1 - max(similarity to any prior proposal)
- High novelty (>0.7): Fresh, divergent ideas
- Medium novelty (0.3-0.7): Building on prior ideas
- Low novelty (<0.15): Too similar, may need intervention
"""

from __future__ import annotations

__all__ = [
    "NoveltyScore",
    "NoveltyResult",
    "NoveltyTracker",
    "CodebaseNoveltyChecker",
    "CodebaseNoveltyResult",
]

import logging
from dataclasses import dataclass, field

from .convergence import SimilarityBackend, get_similarity_backend

logger = logging.getLogger(__name__)


@dataclass
class NoveltyScore:
    """Novelty measurement for a single proposal."""

    agent: str
    round_num: int
    novelty: float  # 1 - max_similarity to prior proposals (0-1, higher = more novel)
    max_similarity: float  # Highest similarity to any prior proposal
    most_similar_to: str | None = None  # Agent whose proposal was most similar
    prior_proposals_count: int = 0

    def is_low_novelty(self, threshold: float = 0.15) -> bool:
        """Check if novelty is below threshold."""
        return self.novelty < threshold


@dataclass
class NoveltyResult:
    """Result of novelty computation for a round."""

    round_num: int
    per_agent_novelty: dict[str, float] = field(default_factory=dict)
    avg_novelty: float = 0.0
    min_novelty: float = 1.0
    max_novelty: float = 0.0
    low_novelty_agents: list[str] = field(default_factory=list)
    details: dict[str, NoveltyScore] = field(default_factory=dict)

    def has_low_novelty(self) -> bool:
        """Check if any agent has low novelty."""
        return len(self.low_novelty_agents) > 0


class NoveltyTracker:
    """
    Tracks semantic novelty of proposals across debate rounds.

    Novelty = 1 - max(similarity to any prior proposal)

    A proposal is novel if it differs significantly from ALL prior proposals.
    If any prior proposal is highly similar, novelty is low.

    Usage:
        tracker = NoveltyTracker()

        # Round 1 - first proposals are maximally novel
        result1 = tracker.compute_novelty(proposals_round1, round_num=1)
        tracker.add_to_history(proposals_round1)

        # Round 2 - compared against round 1
        result2 = tracker.compute_novelty(proposals_round2, round_num=2)
        if result2.has_low_novelty():
            # Trigger intervention
            ...
        tracker.add_to_history(proposals_round2)
    """

    def __init__(
        self,
        backend: SimilarityBackend | None = None,
        low_novelty_threshold: float = 0.15,
    ):
        """
        Initialize novelty tracker.

        Args:
            backend: Similarity backend to use (default: auto-select best available)
            low_novelty_threshold: Below this triggers low novelty alert (default 0.15)
        """
        self.backend = backend or get_similarity_backend("auto")
        self.low_novelty_threshold = low_novelty_threshold

        # History of proposals by round
        # Each entry is {agent_name: proposal_text}
        self.history: list[dict[str, str]] = []

        # Scores computed for each round
        self.scores: list[NoveltyResult] = []

        logger.info(
            "NoveltyTracker initialized with %s, threshold=%s",
            self.backend.__class__.__name__,
            low_novelty_threshold,
        )

    def compute_novelty(
        self,
        current_proposals: dict[str, str],
        round_num: int,
    ) -> NoveltyResult:
        """
        Compute novelty scores for current round proposals.

        Novelty for each proposal = 1 - max(similarity to any prior proposal).
        First round proposals have novelty 1.0 (maximally novel).

        Args:
            current_proposals: Agent name -> proposal text mapping
            round_num: Current round number (1-indexed)

        Returns:
            NoveltyResult with per-agent scores and aggregate metrics
        """
        # Debug logging for novelty computation
        logger.debug(
            "compute_novelty round=%s history_rounds=%s current_agents=%s",
            round_num,
            len(self.history),
            list(current_proposals.keys()),
        )

        # Flatten history into list of (agent, proposal) tuples
        prior_proposals: list[tuple[str, str]] = []
        for round_history in self.history:
            for agent, text in round_history.items():
                prior_proposals.append((agent, text))

        logger.debug(
            "novelty_history_check round=%s prior_proposal_count=%s should_be_novel=%s",
            round_num,
            len(prior_proposals),
            len(prior_proposals) == 0,
        )

        # Compute novelty for each current proposal
        details: dict[str, NoveltyScore] = {}
        per_agent_novelty: dict[str, float] = {}

        for agent, proposal in current_proposals.items():
            if not prior_proposals:
                # First round - maximally novel
                score = NoveltyScore(
                    agent=agent,
                    round_num=round_num,
                    novelty=1.0,
                    max_similarity=0.0,
                    most_similar_to=None,
                    prior_proposals_count=0,
                )
            else:
                # Compare against all prior proposals
                max_similarity = 0.0
                most_similar_to: str | None = None

                for prior_agent, prior_text in prior_proposals:
                    similarity = self.backend.compute_similarity(proposal, prior_text)
                    if similarity > max_similarity:
                        max_similarity = similarity
                        most_similar_to = prior_agent

                novelty = 1.0 - max_similarity

                # Debug: log high-similarity comparisons
                if max_similarity > 0.8:
                    logger.debug(
                        "novelty_high_similarity agent=%s "
                        "max_sim=%.3f "
                        "similar_to=%s "
                        "proposal_len=%s "
                        "prior_len=%s",
                        agent,
                        max_similarity,
                        most_similar_to,
                        len(proposal),
                        len(prior_text) if prior_text else 0,
                    )

                score = NoveltyScore(
                    agent=agent,
                    round_num=round_num,
                    novelty=novelty,
                    max_similarity=max_similarity,
                    most_similar_to=most_similar_to,
                    prior_proposals_count=len(prior_proposals),
                )

            details[agent] = score
            per_agent_novelty[agent] = score.novelty

        # Compute aggregate metrics
        novelty_values = list(per_agent_novelty.values())
        avg_novelty = sum(novelty_values) / len(novelty_values) if novelty_values else 1.0
        min_novelty = min(novelty_values) if novelty_values else 1.0
        max_novelty = max(novelty_values) if novelty_values else 1.0

        # Find agents below threshold
        low_novelty_agents = [
            agent
            for agent, novelty in per_agent_novelty.items()
            if novelty < self.low_novelty_threshold
        ]

        result = NoveltyResult(
            round_num=round_num,
            per_agent_novelty=per_agent_novelty,
            avg_novelty=avg_novelty,
            min_novelty=min_novelty,
            max_novelty=max_novelty,
            low_novelty_agents=low_novelty_agents,
            details=details,
        )

        # Store result
        self.scores.append(result)

        if low_novelty_agents:
            logger.warning(
                "Round %s: Low novelty detected for %s. Min novelty: %.2f",
                round_num,
                low_novelty_agents,
                min_novelty,
            )
        else:
            logger.debug(
                "Round %s: Novelty OK. Avg=%.2f, Min=%.2f", round_num, avg_novelty, min_novelty
            )

        return result

    def add_to_history(self, proposals: dict[str, str]) -> None:
        """
        Add proposals to history for future comparisons.

        Call this after compute_novelty() if you want these proposals
        included in future novelty calculations.

        Args:
            proposals: Agent name -> proposal text mapping
        """
        # Store a copy to prevent mutation issues
        self.history.append(dict(proposals))
        logger.debug("Added round %s to history (%s proposals)", len(self.history), len(proposals))

    def get_agent_novelty_trajectory(self, agent: str) -> list[float]:
        """
        Get novelty scores across rounds for a specific agent.

        Args:
            agent: Agent name

        Returns:
            List of novelty scores by round
        """
        return [result.per_agent_novelty.get(agent, 0.0) for result in self.scores]

    def get_debate_novelty_summary(self) -> dict:
        """
        Get summary statistics for the entire debate.

        Returns:
            Dict with overall_avg, overall_min, rounds_with_low_novelty, etc.
        """
        if not self.scores:
            return {
                "overall_avg": 1.0,
                "overall_min": 1.0,
                "rounds_with_low_novelty": 0,
                "total_rounds": 0,
            }

        all_novelties = [n for result in self.scores for n in result.per_agent_novelty.values()]

        return {
            "overall_avg": sum(all_novelties) / len(all_novelties) if all_novelties else 1.0,
            "overall_min": min(all_novelties) if all_novelties else 1.0,
            "rounds_with_low_novelty": sum(1 for r in self.scores if r.has_low_novelty()),
            "total_rounds": len(self.scores),
            "low_novelty_agents_by_round": {
                r.round_num: r.low_novelty_agents for r in self.scores if r.low_novelty_agents
            },
        }

    def reset(self) -> None:
        """Reset tracker state for a new debate."""
        self.history.clear()
        self.scores.clear()
        logger.debug("NoveltyTracker reset")


@dataclass
class CodebaseNoveltyResult:
    """Result of checking proposal novelty against codebase features."""

    proposal: str
    agent: str
    is_novel: bool
    max_similarity: float
    most_similar_feature: str | None = None
    feature_module: str | None = None
    warning: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "agent": self.agent,
            "is_novel": self.is_novel,
            "max_similarity": self.max_similarity,
            "most_similar_feature": self.most_similar_feature,
            "feature_module": self.feature_module,
            "warning": self.warning,
        }


class CodebaseNoveltyChecker:
    """
    Checks proposal novelty against existing codebase features.

    Unlike NoveltyTracker which compares proposals against each other,
    this compares proposals against the feature inventory from the context phase.
    This catches cases where agents propose features that already exist in the codebase.

    Usage:
        checker = CodebaseNoveltyChecker(codebase_context)
        result = checker.check_proposal("Add WebSocket streaming", "agent-1")
        if not result.is_novel:
            print(f"Warning: {result.warning}")
    """

    # Common synonyms/variants that should trigger similarity checks
    FEATURE_SYNONYMS = {
        "streaming": ["websocket", "real-time", "live", "push", "sse", "server-sent"],
        "spectator": ["viewer", "read-only", "observer", "watcher", "monitor"],
        "dashboard": ["panel", "control center", "admin", "monitor", "overview"],
        "memory": ["cache", "store", "persistence", "storage", "recall"],
        "learning": ["training", "adaptation", "feedback", "improvement"],
        "consensus": ["agreement", "voting", "majority", "convergence"],
        "novelty": ["diversity", "uniqueness", "originality", "freshness"],
    }

    def __init__(
        self,
        codebase_context: str,
        backend: SimilarityBackend | None = None,
        novelty_threshold: float = 0.65,
    ):
        """
        Initialize codebase novelty checker.

        Args:
            codebase_context: The feature inventory from context phase
            backend: Similarity backend (default: auto-select best available)
            novelty_threshold: Similarity above this triggers warning (default 0.65)
        """
        self.codebase_context = codebase_context
        self.backend = backend or get_similarity_backend("auto")
        self.novelty_threshold = novelty_threshold

        # Extract feature entries from the context
        self.features = self._extract_features(codebase_context)

        logger.info(
            "CodebaseNoveltyChecker initialized with %s features, threshold=%s",
            len(self.features),
            novelty_threshold,
        )

    def _extract_features(self, context: str) -> list[dict]:
        """
        Extract feature entries from the codebase context.

        Looks for table-formatted features and free-form feature mentions.
        """
        features = []

        # Split into lines for processing
        lines = context.split("\n")

        current_section = ""
        for line in lines:
            # Track section headers
            if line.startswith("##"):
                current_section = line.strip("# ").lower()
                continue

            # Look for table rows (| feature | module | status |)
            if "|" in line and "---" not in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2:
                    feature_name = parts[0]
                    module = parts[1] if len(parts) > 1 else ""
                    # Skip header rows
                    if feature_name.lower() not in ["feature", "module", "status"]:
                        features.append(
                            {
                                "name": feature_name,
                                "module": module,
                                "section": current_section,
                                "text": f"{feature_name}: {module}",
                            }
                        )

            # Look for bullet-point features (- Feature: description)
            elif line.strip().startswith("- "):
                feature_text = line.strip("- ").strip()
                if ":" in feature_text:
                    name, desc = feature_text.split(":", 1)
                    features.append(
                        {
                            "name": name.strip(),
                            "module": "",
                            "section": current_section,
                            "text": feature_text,
                        }
                    )

        # Also extract key terms from the full context for broad matching
        key_terms = self._extract_key_terms(context)
        for term in key_terms:
            if not any(f["name"].lower() == term.lower() for f in features):
                features.append(
                    {
                        "name": term,
                        "module": "unknown",
                        "section": "extracted",
                        "text": term,
                    }
                )

        return features

    def _extract_key_terms(self, context: str) -> list[str]:
        """Extract key feature terms from context using simple heuristics."""
        terms = []
        # Look for capitalized phrases that might be feature names
        import re

        # Match patterns like "WebSocket Streaming", "ELO Rankings", etc.
        patterns = [
            r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b",  # Multi-word capitalized
            r"\b[A-Z]{2,}[a-z]*\b",  # Acronyms like "ELO", "RLM"
        ]

        for pattern in patterns:
            matches = re.findall(pattern, context)
            for match in matches:
                if len(match) > 3 and match not in terms:
                    terms.append(match)

        return terms[:50]  # Limit to avoid noise

    def check_proposal(self, proposal: str, agent: str) -> CodebaseNoveltyResult:
        """
        Check if a proposal is novel against the codebase features.

        Args:
            proposal: The proposal text
            agent: Agent name making the proposal

        Returns:
            CodebaseNoveltyResult with novelty assessment
        """
        if not self.features:
            logger.warning("No features extracted from codebase context")
            return CodebaseNoveltyResult(
                proposal=proposal,
                agent=agent,
                is_novel=True,
                max_similarity=0.0,
                warning="No codebase features available for comparison",
            )

        max_similarity = 0.0
        most_similar: dict | None = None

        # Check against each feature
        for feature in self.features:
            feature_text = feature["text"]

            # Compute direct similarity
            similarity = self.backend.compute_similarity(proposal, feature_text)

            # Boost similarity if proposal contains feature name directly
            feature_name_lower = feature["name"].lower()
            proposal_lower = proposal.lower()
            if feature_name_lower in proposal_lower:
                similarity = max(similarity, 0.7)  # At least 70% if name matches

            # Check for synonym matches
            for key, synonyms in self.FEATURE_SYNONYMS.items():
                if key in feature_name_lower:
                    for synonym in synonyms:
                        if synonym in proposal_lower:
                            similarity = max(similarity, 0.6)  # Boost for synonym match

            if similarity > max_similarity:
                max_similarity = similarity
                most_similar = feature

        is_novel = max_similarity < self.novelty_threshold

        warning = None
        if not is_novel and most_similar:
            warning = (
                f"Proposal may duplicate existing feature: '{most_similar['name']}' "
                f"(module: {most_similar['module']}, similarity: {max_similarity:.2f})"
            )
            logger.warning("[%s] %s", agent, warning)

        return CodebaseNoveltyResult(
            proposal=proposal,
            agent=agent,
            is_novel=is_novel,
            max_similarity=max_similarity,
            most_similar_feature=most_similar["name"] if most_similar else None,
            feature_module=most_similar["module"] if most_similar else None,
            warning=warning,
        )

    def check_proposals(
        self,
        proposals: dict[str, str],
    ) -> dict[str, CodebaseNoveltyResult]:
        """
        Check multiple proposals for novelty.

        Args:
            proposals: Agent name -> proposal text mapping

        Returns:
            Dict of agent name -> CodebaseNoveltyResult
        """
        results = {}
        for agent, proposal in proposals.items():
            results[agent] = self.check_proposal(proposal, agent)
        return results

    def get_non_novel_proposals(
        self,
        proposals: dict[str, str],
    ) -> list[CodebaseNoveltyResult]:
        """
        Get list of proposals that may duplicate existing features.

        Args:
            proposals: Agent name -> proposal text mapping

        Returns:
            List of non-novel results with warnings
        """
        results = self.check_proposals(proposals)
        return [r for r in results.values() if not r.is_novel]
