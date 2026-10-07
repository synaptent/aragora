"""
Match Orchestration for ELO system.

Extracted from EloSystem to separate the high-level match recording
orchestration from core CRUD operations. Handles:
- End-to-end match recording workflow
- ELO change calculation and application
- Event emission and Knowledge Mound sync
- Cache invalidation after matches
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aragora.config import ELO_INITIAL_RATING, ELO_K_FACTOR
from aragora.ranking.elo_core import calculate_pairwise_elo_changes, apply_elo_changes
from aragora.ranking.match_recorder import (
    check_duplicate_match,
    compute_calibration_k_multipliers,
    determine_winner,
    save_match,
)
from aragora.ranking.snapshot import write_snapshot

if TYPE_CHECKING:
    from aragora.ranking.elo import AgentRating, EloSystem

logger = logging.getLogger(__name__)

DEFAULT_ELO = ELO_INITIAL_RATING
K_FACTOR = ELO_K_FACTOR


def record_match(
    elo_system: EloSystem,
    debate_id: str | None = None,
    participants: list[str] | str | None = None,
    scores: dict[str, float] | None = None,
    domain: str | None = None,
    confidence_weight: float = 1.0,
    calibration_tracker: object | None = None,
    *,
    winner: str | None = None,
    loser: str | None = None,
    draw: bool | None = None,
    task: str | None = None,
) -> dict[str, float]:
    """
    Record a match result and update ELO ratings.

    This is the main match orchestration function that coordinates:
    1. Parameter normalization (legacy + modern signatures)
    2. Duplicate detection
    3. ELO change calculation (pairwise, with calibration)
    4. Rating persistence (batch save)
    5. Match history recording
    6. Snapshot writing
    7. Cache invalidation
    8. Event emission
    9. Knowledge Mound sync

    Args:
        elo_system: EloSystem instance
        debate_id: Unique debate identifier (auto-generated if omitted)
        participants: List of agent names or legacy "loser" string
        scores: Dict of agent -> score (higher is better)
        domain: Optional domain for domain-specific ELO
        confidence_weight: Weight for ELO change (0-1)
        calibration_tracker: Optional CalibrationTracker instance
        winner: Legacy winner name (for compatibility)
        loser: Legacy loser name (for compatibility)
        draw: Legacy draw flag (for compatibility)
        task: Legacy task label (used in auto-generated debate_id)

    Returns:
        Dict of agent -> ELO change
    """
    # Normalize legacy and modern signatures
    debate_id, participants_list, scores = elo_system._normalize_match_params(
        debate_id, participants, scores, winner, loser, draw, task, domain
    )

    if not participants_list or scores is None:
        return {}

    # Clamp confidence_weight to valid range
    confidence_weight = max(0.1, min(1.0, confidence_weight))
    if len(participants_list) < 2:
        return {}

    # Check for duplicate match recording to prevent ELO accumulation bug
    cached_changes = check_duplicate_match(elo_system._db, debate_id)
    if cached_changes is not None:
        return cached_changes

    # Determine winner (highest score)
    winner = determine_winner(scores)

    # Get current ratings (batch query to avoid N+1)
    ratings = elo_system.get_ratings_batch(participants_list)

    # Compute calibration-based K-factor multipliers
    k_multipliers = compute_calibration_k_multipliers(participants_list, calibration_tracker)

    # Calculate pairwise ELO changes (with calibration adjustments if provided)
    elo_changes = calculate_pairwise_elo_changes(
        participants_list, scores, ratings, confidence_weight, K_FACTOR, k_multipliers
    )

    # Apply changes and collect for batch save
    ratings_to_save, history_entries = apply_elo_changes(
        elo_changes, ratings, winner, domain, debate_id, DEFAULT_ELO
    )

    # Batch save all ratings and history (single transaction each)
    elo_system._save_ratings_batch(ratings_to_save)
    elo_system._record_elo_history_batch(history_entries)

    # Save match
    save_match(elo_system._db, debate_id, winner, participants_list, domain, scores, elo_changes)

    # Write JSON snapshot for fast reads (avoids SQLite locking)
    _write_snapshot(elo_system)

    # Invalidate related caches so API returns fresh data
    _invalidate_handler_cache()

    # Emit ELO update events for each agent
    _emit_elo_events(elo_system, elo_changes, ratings, debate_id, domain)

    # Sync to Knowledge Mound if adapter configured
    _sync_to_km(elo_system, debate_id, participants_list, winner, domain, elo_changes, ratings)

    return elo_changes


def _write_snapshot(elo_system: EloSystem) -> None:
    """Write JSON snapshot for fast reads."""
    snapshot_path = elo_system.db_path.parent / "elo_snapshot.json"
    write_snapshot(snapshot_path, elo_system.get_leaderboard, elo_system.get_recent_matches)


def _invalidate_handler_cache() -> None:
    """Invalidate handler cache after match recording."""
    try:
        from aragora.server.handlers.base import invalidate_on_event

        invalidate_on_event("match_recorded")
    except ImportError:
        logger.debug("Handler cache invalidation skipped - handlers module not available")


def _emit_elo_events(
    elo_system: EloSystem,
    elo_changes: dict[str, float],
    ratings: dict[str, AgentRating],
    debate_id: str,
    domain: str | None,
) -> None:
    """Emit ELO update events for each agent."""
    if not elo_system.event_emitter or not elo_changes:
        return

    try:
        from aragora.events.types import StreamEvent, StreamEventType

        for agent_name, elo_change in elo_changes.items():
            agent_rating = ratings.get(agent_name)
            base_rating: float = agent_rating.elo if agent_rating else 1500.0
            new_rating = base_rating + elo_change
            elo_system.event_emitter.emit(
                StreamEvent(
                    type=StreamEventType.AGENT_ELO_UPDATED,
                    data={
                        "agent": agent_name,
                        "elo_change": elo_change,
                        "new_elo": new_rating,
                        "debate_id": debate_id,
                        "domain": domain,
                    },
                )
            )
    except (ImportError, AttributeError, TypeError):
        logger.debug("Stream event emission skipped - stream module not available")


def _sync_to_km(
    elo_system: EloSystem,
    debate_id: str,
    participants: list[str],
    winner: str | None,
    domain: str | None,
    elo_changes: dict[str, float],
    ratings: dict[str, AgentRating],
) -> None:
    """Sync match results and ratings to Knowledge Mound."""
    if not elo_system._km_adapter or not elo_changes:
        return

    try:
        from aragora.ranking.elo import MatchResult

        # Store match result for skill history tracking
        match_result = MatchResult(
            debate_id=debate_id,
            winner=winner,
            participants=participants,
            domain=domain,
            scores={name: elo_changes.get(name, 0.0) for name in participants},
        )
        elo_system._km_adapter.store_match(match_result)

        # Store updated ratings
        for agent_name, elo_change in elo_changes.items():
            agent_rating = ratings.get(agent_name)
            if agent_rating:
                updated_rating = AgentRating(
                    agent_name=agent_name,
                    elo=agent_rating.elo + elo_change,
                    domain_elos=agent_rating.domain_elos,
                    wins=agent_rating.wins,
                    losses=agent_rating.losses,
                    draws=agent_rating.draws,
                    debates_count=agent_rating.debates_count,
                    critiques_accepted=agent_rating.critiques_accepted,
                    critiques_total=agent_rating.critiques_total,
                    calibration_correct=agent_rating.calibration_correct,
                    calibration_total=agent_rating.calibration_total,
                    calibration_brier_sum=agent_rating.calibration_brier_sum,
                    updated_at=agent_rating.updated_at,
                )
                elo_system._km_adapter.store_rating(
                    updated_rating,
                    debate_id=debate_id,
                    reason="match_update",
                )
        logger.debug("ELO changes synced to Knowledge Mound: %s", debate_id)
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
        logger.warning("Failed to sync ELO to KM: %s", e)


__all__ = [
    "record_match",
]
