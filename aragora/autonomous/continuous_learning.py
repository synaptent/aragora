"""
Continuous Learning (Phase 5.2).

Provides:
- Real-time ELO updates
- Agent calibration refinement
- Cross-debate pattern extraction
- Knowledge decay management
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


class LearningEventType(Enum):
    """Types of learning events."""

    DEBATE_COMPLETED = "debate_completed"
    CONSENSUS_REACHED = "consensus_reached"
    AGENT_OUTPERFORMED = "agent_outperformed"
    PATTERN_DISCOVERED = "pattern_discovered"
    CALIBRATION_UPDATED = "calibration_updated"
    KNOWLEDGE_DECAYED = "knowledge_decayed"
    USER_FEEDBACK = "user_feedback"


@dataclass
class LearningEvent:
    """A learning event that updates the system's knowledge."""

    id: str
    event_type: LearningEventType
    timestamp: datetime
    source: str  # What generated this event (debate_id, agent_name, etc.)
    data: dict[str, Any]
    applied: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCalibration:
    """Calibration data for an agent."""

    agent_id: str
    elo_rating: float = 1500.0
    confidence_accuracy: float = 0.5  # How accurate are confidence predictions
    topic_strengths: dict[str, float] = field(default_factory=dict)
    topic_weaknesses: dict[str, float] = field(default_factory=dict)
    last_updated: datetime | None = None
    total_debates: int = 0
    win_rate: float = 0.5


@dataclass
class ExtractedPattern:
    """A pattern extracted from cross-debate analysis."""

    id: str
    pattern_type: str  # e.g., "consensus_strategy", "topic_expertise", "failure_mode"
    description: str
    confidence: float
    evidence_count: int
    first_seen: datetime
    last_seen: datetime
    agents_involved: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class EloUpdater:
    """
    Real-time ELO rating updates for agents.

    Updates ELO ratings based on:
    - Debate outcomes (win/loss/draw)
    - Vote counts
    - Consensus contributions
    - User feedback
    """

    def __init__(
        self,
        k_factor: float = 32.0,
        min_rating: float = 100.0,
        max_rating: float = 3000.0,
        decay_per_day: float = 0.0,  # Optional rating decay for inactive agents
    ):
        """
        Initialize ELO updater.

        Args:
            k_factor: ELO K-factor (sensitivity)
            min_rating: Minimum rating
            max_rating: Maximum rating
            decay_per_day: Rating decay per day of inactivity
        """
        self.k_factor = k_factor
        self.min_rating = min_rating
        self.max_rating = max_rating
        self.decay_per_day = decay_per_day
        self._ratings: dict[str, float] = {}
        self._last_active: dict[str, datetime] = {}

    def get_rating(self, agent_id: str) -> float:
        """Get current rating for an agent."""
        return self._ratings.get(agent_id, 1500.0)

    def set_rating(self, agent_id: str, rating: float) -> None:
        """Set rating for an agent."""
        self._ratings[agent_id] = max(self.min_rating, min(self.max_rating, rating))
        self._last_active[agent_id] = datetime.now()

    def update_from_debate(
        self,
        winner_id: str,
        loser_id: str,
        margin: float = 1.0,
    ) -> tuple[float, float]:
        """
        Update ratings based on debate outcome.

        Args:
            winner_id: ID of winning agent
            loser_id: ID of losing agent
            margin: Victory margin (0-1), affects update magnitude

        Returns:
            Tuple of (new_winner_rating, new_loser_rating)
        """
        winner_rating = self.get_rating(winner_id)
        loser_rating = self.get_rating(loser_id)

        # Expected scores
        exp_winner = 1.0 / (1.0 + math.pow(10, (loser_rating - winner_rating) / 400))
        exp_loser = 1.0 - exp_winner

        # Actual scores (winner=1, loser=0, modified by margin)
        actual_winner = 0.5 + (0.5 * margin)
        actual_loser = 0.5 - (0.5 * margin)

        # Update ratings
        new_winner = winner_rating + self.k_factor * (actual_winner - exp_winner)
        new_loser = loser_rating + self.k_factor * (actual_loser - exp_loser)

        self.set_rating(winner_id, new_winner)
        self.set_rating(loser_id, new_loser)

        logger.debug(
            "ELO update: %s %.0f->%.0f, %s %.0f->%.0f",
            winner_id,
            winner_rating,
            new_winner,
            loser_id,
            loser_rating,
            new_loser,
        )

        return new_winner, new_loser

    def update_from_votes(
        self,
        agent_votes: dict[str, int],
        total_votes: int,
    ) -> dict[str, float]:
        """
        Update ratings based on vote distribution.

        Args:
            agent_votes: Votes received by each agent
            total_votes: Total votes cast

        Returns:
            Dict of new ratings
        """
        if total_votes == 0:
            return {}

        new_ratings = {}

        for agent_id, votes in agent_votes.items():
            vote_share = votes / total_votes
            current_rating = self.get_rating(agent_id)

            # Adjust based on vote share vs expected (0.5 for 2 agents)
            expected_share = 1.0 / len(agent_votes)
            adjustment = self.k_factor * 0.5 * (vote_share - expected_share)

            new_rating = current_rating + adjustment
            self.set_rating(agent_id, new_rating)
            new_ratings[agent_id] = new_rating

        return new_ratings

    def apply_decay(self) -> dict[str, float]:
        """Apply decay to inactive agents."""
        if self.decay_per_day == 0:
            return {}

        now = datetime.now()
        decayed = {}

        for agent_id, last_active in list(self._last_active.items()):
            days_inactive = (now - last_active).days
            if days_inactive > 0:
                current = self.get_rating(agent_id)
                decay = self.decay_per_day * days_inactive
                new_rating = max(self.min_rating, current - decay)
                if new_rating != current:
                    self._ratings[agent_id] = new_rating
                    decayed[agent_id] = new_rating

        return decayed

    def get_all_ratings(self) -> dict[str, float]:
        """Get all agent ratings."""
        return self._ratings.copy()


class PatternExtractor:
    """
    Extracts patterns from cross-debate analysis.

    Identifies:
    - Consensus strategies that work
    - Topic expertise patterns
    - Common failure modes
    - Agent collaboration patterns
    """

    def __init__(
        self,
        min_evidence_count: int = 3,
        min_confidence: float = 0.6,
        storage_path: Path | None = None,
    ):
        """
        Initialize pattern extractor.

        Args:
            min_evidence_count: Minimum evidence count to report pattern
            min_confidence: Minimum confidence to report pattern
            storage_path: Path to store extracted patterns
        """
        self.min_evidence_count = min_evidence_count
        self.min_confidence = min_confidence
        self.storage_path = storage_path
        self._patterns: dict[str, ExtractedPattern] = {}
        self._observations: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def observe(
        self,
        observation_type: str,
        data: dict[str, Any],
        agents: list[str],
        topics: list[str] | None = None,
    ) -> None:
        """
        Record an observation for pattern extraction.

        Args:
            observation_type: Type of observation
            data: Observation data
            agents: Agents involved
            topics: Topics involved
        """
        self._observations[observation_type].append(
            {
                "data": data,
                "agents": agents,
                "topics": topics or [],
                "timestamp": datetime.now(),
            }
        )

    def extract_patterns(self) -> list[ExtractedPattern]:
        """
        Extract patterns from observations.

        Returns:
            List of newly extracted patterns
        """
        new_patterns = []

        # Extract consensus strategy patterns
        new_patterns.extend(self._extract_consensus_patterns())

        # Extract topic expertise patterns
        new_patterns.extend(self._extract_expertise_patterns())

        # Extract failure mode patterns
        new_patterns.extend(self._extract_failure_patterns())

        # Store patterns
        for pattern in new_patterns:
            self._patterns[pattern.id] = pattern

        if self.storage_path:
            self._save_patterns()

        return new_patterns

    def _extract_consensus_patterns(self) -> list[ExtractedPattern]:
        """Extract patterns from consensus observations."""
        patterns: list[ExtractedPattern] = []
        consensus_obs = self._observations.get("consensus_reached", [])

        if len(consensus_obs) < self.min_evidence_count:
            return patterns

        # Group by strategy
        strategies: dict[str, list[dict]] = defaultdict(list)
        for obs in consensus_obs:
            strategy = obs["data"].get("strategy", "unknown")
            strategies[strategy].append(obs)

        for strategy, obs_list in strategies.items():
            if len(obs_list) >= self.min_evidence_count:
                # Calculate success rate as confidence
                success_rate = sum(1 for o in obs_list if o["data"].get("success", False)) / len(
                    obs_list
                )

                if success_rate >= self.min_confidence:
                    pattern = ExtractedPattern(
                        id=f"consensus_{strategy}_{len(patterns)}",
                        pattern_type="consensus_strategy",
                        description=f"Consensus strategy '{strategy}' succeeds {success_rate:.0%} of the time",
                        confidence=success_rate,
                        evidence_count=len(obs_list),
                        first_seen=min(o["timestamp"] for o in obs_list),
                        last_seen=max(o["timestamp"] for o in obs_list),
                        agents_involved=list(set(a for o in obs_list for a in o["agents"])),
                        topics=list(set(t for o in obs_list for t in o["topics"])),
                    )
                    patterns.append(pattern)

        return patterns

    def _extract_expertise_patterns(self) -> list[ExtractedPattern]:
        """Extract topic expertise patterns."""
        patterns: list[ExtractedPattern] = []
        performance_obs = self._observations.get("agent_performance", [])

        if len(performance_obs) < self.min_evidence_count:
            return patterns

        # Group by agent and topic
        agent_topic_perf: dict[tuple[str, str], list[float]] = defaultdict(list)

        for obs in performance_obs:
            agent = obs["data"].get("agent")
            topic = obs["data"].get("topic")
            score = obs["data"].get("score", 0.5)

            if agent and topic:
                agent_topic_perf[(agent, topic)].append(score)

        for (agent, topic), scores in agent_topic_perf.items():
            if len(scores) >= self.min_evidence_count:
                avg_score = sum(scores) / len(scores)

                if avg_score >= 0.7:  # High performer
                    pattern = ExtractedPattern(
                        id=f"expertise_{agent}_{topic}",
                        pattern_type="topic_expertise",
                        description=f"{agent} excels at {topic} topics (avg score: {avg_score:.2f})",
                        confidence=avg_score,
                        evidence_count=len(scores),
                        first_seen=datetime.now() - timedelta(days=30),
                        last_seen=datetime.now(),
                        agents_involved=[agent],
                        topics=[topic],
                    )
                    patterns.append(pattern)

        return patterns

    def _extract_failure_patterns(self) -> list[ExtractedPattern]:
        """Extract failure mode patterns."""
        patterns: list[ExtractedPattern] = []
        failure_obs = self._observations.get("debate_failed", [])

        if len(failure_obs) < self.min_evidence_count:
            return patterns

        # Group by failure reason
        reasons: dict[str, list[dict]] = defaultdict(list)
        for obs in failure_obs:
            reason = obs["data"].get("reason", "unknown")
            reasons[reason].append(obs)

        for reason, obs_list in reasons.items():
            if len(obs_list) >= self.min_evidence_count:
                pattern = ExtractedPattern(
                    id=f"failure_{reason}_{len(patterns)}",
                    pattern_type="failure_mode",
                    description=f"Common failure: {reason} ({len(obs_list)} occurrences)",
                    confidence=len(obs_list) / len(failure_obs),
                    evidence_count=len(obs_list),
                    first_seen=min(o["timestamp"] for o in obs_list),
                    last_seen=max(o["timestamp"] for o in obs_list),
                    agents_involved=list(set(a for o in obs_list for a in o["agents"])),
                    topics=list(set(t for o in obs_list for t in o["topics"])),
                )
                patterns.append(pattern)

        return patterns

    def get_patterns(self, pattern_type: str | None = None) -> list[ExtractedPattern]:
        """Get extracted patterns, optionally filtered by type."""
        if pattern_type:
            return [p for p in self._patterns.values() if p.pattern_type == pattern_type]
        return list(self._patterns.values())

    def _save_patterns(self) -> None:
        """Save patterns to storage."""
        if not self.storage_path:
            return

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            pid: {
                "id": p.id,
                "pattern_type": p.pattern_type,
                "description": p.description,
                "confidence": p.confidence,
                "evidence_count": p.evidence_count,
                "first_seen": p.first_seen.isoformat(),
                "last_seen": p.last_seen.isoformat(),
                "agents_involved": p.agents_involved,
                "topics": p.topics,
                "metadata": p.metadata,
            }
            for pid, p in self._patterns.items()
        }
        self.storage_path.write_text(json.dumps(data, indent=2))


class KnowledgeDecayManager:
    """
    Manages knowledge decay over time.

    Features:
    - Configurable decay rates by knowledge type
    - Periodic refresh triggers
    - Importance-based decay resistance
    """

    def __init__(
        self,
        default_half_life_days: float = 30.0,
        min_confidence: float = 0.1,
        decay_check_interval_hours: float = 24.0,
    ):
        """
        Initialize decay manager.

        Args:
            default_half_life_days: Default half-life for knowledge
            min_confidence: Minimum confidence floor
            decay_check_interval_hours: How often to check for decay
        """
        self.default_half_life_days = default_half_life_days
        self.min_confidence = min_confidence
        self.decay_check_interval_hours = decay_check_interval_hours
        self._knowledge_items: dict[str, dict[str, Any]] = {}
        self._last_decay_check: datetime | None = None

    def register_knowledge(
        self,
        knowledge_id: str,
        initial_confidence: float,
        importance: float = 0.5,
        half_life_days: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Register a knowledge item for decay tracking.

        Args:
            knowledge_id: Unique identifier
            initial_confidence: Starting confidence
            importance: Importance factor (0-1), higher = slower decay
            half_life_days: Custom half-life
            metadata: Additional metadata
        """
        self._knowledge_items[knowledge_id] = {
            "confidence": initial_confidence,
            "importance": importance,
            "half_life_days": half_life_days or self.default_half_life_days,
            "created_at": datetime.now(),
            "last_refreshed": datetime.now(),
            "refresh_count": 0,
            "metadata": metadata or {},
        }

    def refresh_knowledge(self, knowledge_id: str, boost: float = 0.1) -> float | None:
        """
        Refresh knowledge item (reset decay, optional boost).

        Args:
            knowledge_id: ID of knowledge to refresh
            boost: Confidence boost (capped at 1.0)

        Returns:
            New confidence, or None if not found
        """
        if knowledge_id not in self._knowledge_items:
            return None

        item = self._knowledge_items[knowledge_id]
        item["last_refreshed"] = datetime.now()
        item["refresh_count"] += 1
        item["confidence"] = min(1.0, item["confidence"] + boost)

        return float(item["confidence"])

    def apply_decay(self) -> dict[str, float]:
        """
        Apply decay to all knowledge items.

        Returns:
            Dict of knowledge_id -> new_confidence for items that changed
        """
        now = datetime.now()
        changed = {}

        for kid, item in self._knowledge_items.items():
            last_refresh = item["last_refreshed"]
            days_since_refresh = (now - last_refresh).total_seconds() / 86400

            if days_since_refresh <= 0:
                continue

            # Calculate decay with importance-based resistance
            half_life = item["half_life_days"] * (1 + item["importance"])
            decay_factor = math.pow(0.5, days_since_refresh / half_life)

            old_confidence = item["confidence"]
            new_confidence = max(self.min_confidence, old_confidence * decay_factor)

            if abs(new_confidence - old_confidence) > 0.001:
                item["confidence"] = new_confidence
                changed[kid] = new_confidence

        self._last_decay_check = now
        return changed

    def get_confidence(self, knowledge_id: str) -> float | None:
        """Get current confidence for knowledge item."""
        item = self._knowledge_items.get(knowledge_id)
        return item["confidence"] if item else None

    def get_stale_knowledge(self, max_age_days: float = 30.0) -> list[str]:
        """Get knowledge items that haven't been refreshed recently."""
        now = datetime.now()
        threshold = timedelta(days=max_age_days)

        stale = []
        for kid, item in self._knowledge_items.items():
            age = now - item["last_refreshed"]
            if age > threshold:
                stale.append(kid)

        return stale


class ContinuousLearner:
    """
    Orchestrates continuous learning across all components.

    Coordinates:
    - ELO updates from debate outcomes
    - Pattern extraction from observations
    - Knowledge decay management
    - Calibration refinement
    """

    def __init__(
        self,
        elo_updater: EloUpdater | None = None,
        pattern_extractor: PatternExtractor | None = None,
        decay_manager: KnowledgeDecayManager | None = None,
        event_callback: Callable[[LearningEvent], None] | None = None,
    ):
        """
        Initialize continuous learner.

        Args:
            elo_updater: ELO rating updater
            pattern_extractor: Pattern extraction system
            decay_manager: Knowledge decay manager
            event_callback: Called when learning events occur
        """
        self.elo_updater = elo_updater or EloUpdater()
        self.pattern_extractor = pattern_extractor or PatternExtractor()
        self.decay_manager = decay_manager or KnowledgeDecayManager()
        self.event_callback = event_callback
        self._calibrations: dict[str, AgentCalibration] = {}
        self._event_history: list[LearningEvent] = []

    async def on_debate_completed(
        self,
        debate_id: str,
        agents: list[str],
        winner: str | None,
        votes: dict[str, int],
        consensus_reached: bool,
        topics: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> LearningEvent:
        """
        Process a completed debate for learning.

        Args:
            debate_id: ID of the completed debate
            agents: Agents that participated
            winner: Winning agent (if any)
            votes: Vote counts per agent
            consensus_reached: Whether consensus was reached
            topics: Topics discussed
            metadata: Additional metadata

        Returns:
            LearningEvent that was created
        """
        event = LearningEvent(
            id=f"debate_{debate_id}",
            event_type=LearningEventType.DEBATE_COMPLETED,
            timestamp=datetime.now(),
            source=debate_id,
            data={
                "agents": agents,
                "winner": winner,
                "votes": votes,
                "consensus_reached": consensus_reached,
                "topics": topics,
            },
            metadata=metadata or {},
        )

        # Update ELO ratings
        if winner and len(agents) >= 2:
            total_votes = sum(votes.values())
            if total_votes > 0:
                winner_votes = votes.get(winner, 0)
                margin = (winner_votes / total_votes) - 0.5  # Normalize to 0-0.5

                for agent in agents:
                    if agent != winner:
                        self.elo_updater.update_from_debate(
                            winner_id=winner,
                            loser_id=agent,
                            margin=margin * 2,  # Scale to 0-1
                        )
        else:
            # No winner - update from votes
            self.elo_updater.update_from_votes(votes, sum(votes.values()))

        # Record observation for pattern extraction
        self.pattern_extractor.observe(
            "debate_completed",
            data={
                "winner": winner,
                "votes": votes,
                "consensus": consensus_reached,
            },
            agents=agents,
            topics=topics,
        )

        if consensus_reached:
            self.pattern_extractor.observe(
                "consensus_reached",
                data={
                    "strategy": metadata.get("consensus_strategy") if metadata else None,
                    "success": True,
                },
                agents=agents,
                topics=topics,
            )

        # Update calibrations
        for agent in agents:
            await self._update_calibration(agent, event)

        event.applied = True
        self._event_history.append(event)

        if self.event_callback:
            self.event_callback(event)

        return event

    async def on_user_feedback(
        self,
        debate_id: str,
        agent_id: str,
        feedback_type: str,  # "helpful", "unhelpful", "accurate", "inaccurate"
        score: float,
        metadata: dict[str, Any] | None = None,
    ) -> LearningEvent:
        """
        Process user feedback for learning.

        Args:
            debate_id: Related debate ID
            agent_id: Agent receiving feedback
            feedback_type: Type of feedback
            score: Feedback score (-1 to 1)
            metadata: Additional metadata

        Returns:
            LearningEvent that was created
        """
        event = LearningEvent(
            id=f"feedback_{debate_id}_{agent_id}",
            event_type=LearningEventType.USER_FEEDBACK,
            timestamp=datetime.now(),
            source=debate_id,
            data={
                "agent_id": agent_id,
                "feedback_type": feedback_type,
                "score": score,
            },
            metadata=metadata or {},
        )

        # Update ELO based on feedback
        current_rating = self.elo_updater.get_rating(agent_id)
        adjustment = score * 10  # Small adjustment based on feedback
        self.elo_updater.set_rating(agent_id, current_rating + adjustment)

        # Update calibration
        if agent_id in self._calibrations:
            cal = self._calibrations[agent_id]
            # Adjust confidence accuracy based on feedback
            if feedback_type in ["accurate", "inaccurate"]:
                accuracy_delta = 0.01 if feedback_type == "accurate" else -0.01
                cal.confidence_accuracy = max(0, min(1, cal.confidence_accuracy + accuracy_delta))

        event.applied = True
        self._event_history.append(event)

        if self.event_callback:
            self.event_callback(event)

        return event

    async def run_periodic_learning(self) -> dict[str, Any]:
        """
        Run periodic learning tasks.

        Returns:
            Summary of actions taken
        """
        summary = {
            "patterns_extracted": 0,
            "knowledge_decayed": 0,
            "ratings_decayed": 0,
        }

        # Extract patterns
        new_patterns = self.pattern_extractor.extract_patterns()
        summary["patterns_extracted"] = len(new_patterns)

        for pattern in new_patterns:
            event = LearningEvent(
                id=f"pattern_{pattern.id}",
                event_type=LearningEventType.PATTERN_DISCOVERED,
                timestamp=datetime.now(),
                source="pattern_extractor",
                data={
                    "pattern_type": pattern.pattern_type,
                    "description": pattern.description,
                    "confidence": pattern.confidence,
                },
            )
            event.applied = True
            self._event_history.append(event)

        # Apply knowledge decay
        decayed = self.decay_manager.apply_decay()
        summary["knowledge_decayed"] = len(decayed)

        for kid, new_confidence in decayed.items():
            event = LearningEvent(
                id=f"decay_{kid}",
                event_type=LearningEventType.KNOWLEDGE_DECAYED,
                timestamp=datetime.now(),
                source="decay_manager",
                data={
                    "knowledge_id": kid,
                    "new_confidence": new_confidence,
                },
            )
            event.applied = True
            self._event_history.append(event)

        # Apply ELO decay
        rating_decay = self.elo_updater.apply_decay()
        summary["ratings_decayed"] = len(rating_decay)

        logger.info(
            "Periodic learning: %s patterns, %s decayed, %s rating adjustments",
            summary["patterns_extracted"],
            summary["knowledge_decayed"],
            summary["ratings_decayed"],
        )

        return summary

    async def _update_calibration(
        self,
        agent_id: str,
        event: LearningEvent,
    ) -> None:
        """Update agent calibration based on event."""
        if agent_id not in self._calibrations:
            self._calibrations[agent_id] = AgentCalibration(agent_id=agent_id)

        cal = self._calibrations[agent_id]
        cal.elo_rating = self.elo_updater.get_rating(agent_id)
        cal.last_updated = datetime.now()
        cal.total_debates += 1

        # Update win rate
        if event.data.get("winner") == agent_id:
            cal.win_rate = (cal.win_rate * (cal.total_debates - 1) + 1) / cal.total_debates
        else:
            cal.win_rate = (cal.win_rate * (cal.total_debates - 1)) / cal.total_debates

    def get_calibration(self, agent_id: str) -> AgentCalibration | None:
        """Get calibration for an agent."""
        return self._calibrations.get(agent_id)

    def get_all_calibrations(self) -> dict[str, AgentCalibration]:
        """Get all agent calibrations."""
        return self._calibrations.copy()


__all__ = [
    "LearningEventType",
    "LearningEvent",
    "AgentCalibration",
    "ExtractedPattern",
    "EloUpdater",
    "PatternExtractor",
    "KnowledgeDecayManager",
    "ContinuousLearner",
]
