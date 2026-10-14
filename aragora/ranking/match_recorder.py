"""
Match Recording Engine for ELO system.

Extracted from EloSystem to separate match recording concerns from
rating query operations. Handles match result processing and persistence.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from aragora.config import ELO_K_FACTOR

if TYPE_CHECKING:
    from aragora.ranking.database import EloDatabase

logger = logging.getLogger(__name__)

K_FACTOR = ELO_K_FACTOR


def build_match_scores(winner: str, loser: str, is_draw: bool) -> dict[str, float]:
    """Build score dict for a two-player match.

    Args:
        winner: Name of winning agent
        loser: Name of losing agent
        is_draw: Whether the match was a draw

    Returns:
        Dict mapping agent names to scores (1.0=win, 0.5=draw, 0.0=loss)
    """
    if is_draw:
        return {winner: 0.5, loser: 0.5}
    return {winner: 1.0, loser: 0.0}


def generate_match_id(
    participants: list[str], task: str | None = None, domain: str | None = None
) -> str:
    """Generate a unique match ID.

    Args:
        participants: List of participant names
        task: Optional task label
        domain: Optional domain label

    Returns:
        Unique match identifier string
    """
    label = "-vs-".join(participants) if participants else "match"
    scope = task or domain or "debate"
    return f"{scope}-{label}-{uuid.uuid4().hex[:8]}"


def normalize_match_params(
    debate_id: str | None,
    participants: list[str] | str | None,
    scores: dict[str, float] | None,
    winner: str | None,
    loser: str | None,
    draw: bool | None,
    task: str | None,
    domain: str | None,
) -> tuple[str, list[str] | None, dict[str, float] | None]:
    """Normalize legacy and modern match signatures.

    Handles backwards compatibility with older API signatures where
    participants could be a string (loser name) and debate_id was
    used as winner name.

    Args:
        debate_id: Debate ID or legacy winner name
        participants: List of participants or legacy loser name
        scores: Score dict or None
        winner: Explicit winner name
        loser: Explicit loser name
        draw: Whether match was a draw
        task: Task label for ID generation
        domain: Domain label for ID generation

    Returns:
        Tuple of (normalized_debate_id, participants_list, scores_dict)
    """
    participants_list: list[str] | None = None

    # Legacy signature: participants is a string (loser name)
    if isinstance(participants, str):
        winner_name = winner or (debate_id or "")
        loser_name = loser or participants
        if not winner_name or not loser_name:
            raise ValueError("winner and loser must be provided for legacy record_match calls")
        if scores is None or isinstance(scores, bool):
            draw_flag = (
                draw if draw is not None else bool(scores) if isinstance(scores, bool) else False
            )
            scores = build_match_scores(winner_name, loser_name, draw_flag)
        participants_list = [winner_name, loser_name]
        debate_id = generate_match_id(participants_list, task, domain)
    else:
        # Modern signature
        participants_list = participants if isinstance(participants, list) else None
        if scores is None and winner and loser:
            scores = build_match_scores(winner, loser, bool(draw))
            participants_list = [winner, loser]
        if scores is None and draw and participants_list:
            scores = dict.fromkeys(participants_list, 0.5)
        if participants_list is None and scores is not None:
            participants_list = list(scores.keys())
        if debate_id is None:
            debate_id = generate_match_id(participants_list or [], task, domain)

    return debate_id or "", participants_list, scores


def compute_calibration_k_multipliers(
    participants: list[str],
    calibration_tracker: Any | None = None,
) -> dict[str, float]:
    """Compute per-agent K-factor multipliers based on calibration quality.

    Combines ECE (historical calibration error) with fresh Brier scores
    to produce K-factor multipliers. Poorly calibrated agents get higher
    multipliers so their ELO changes more dramatically, creating stronger
    incentives to improve calibration.

    The multiplier blends two signals:
    - ECE (long-term calibration drift): 40% weight
    - Brier score (recent prediction accuracy): 60% weight

    Args:
        participants: List of agent names
        calibration_tracker: Optional CalibrationTracker instance

    Returns:
        Dict of agent_name -> K-factor multiplier (1.0 to 1.4)
    """
    if calibration_tracker is None:
        return {}

    multipliers = {}
    for agent in participants:
        try:
            # ECE: long-term calibration error (0-1, lower is better)
            ece = None
            try:
                val = calibration_tracker.get_expected_calibration_error(agent)
                if isinstance(val, (int, float)):
                    ece = float(val)
            except (KeyError, AttributeError, TypeError):
                logger.debug(
                    "Skipping calibration ECE lookup for agent=%s",
                    agent,
                    exc_info=True,
                )

            # Brier score: recent prediction accuracy (0-1, lower is better)
            brier = None
            try:
                val = calibration_tracker.get_brier_score(agent)
                if isinstance(val, (int, float)):
                    brier = float(val)
            except (KeyError, AttributeError, TypeError):
                logger.debug(
                    "Skipping calibration Brier score lookup for agent=%s",
                    agent,
                    exc_info=True,
                )

            # Blend available signals into composite calibration error
            if ece is not None and brier is not None:
                composite = 0.4 * ece + 0.6 * brier
            elif ece is not None:
                composite = ece
            elif brier is not None:
                composite = brier
            else:
                multipliers[agent] = 1.0
                continue

            # Map composite error to K-factor multiplier (1.0 to 1.4)
            if composite < 0.1:
                multipliers[agent] = 1.0
            elif composite < 0.2:
                multipliers[agent] = 1.1
            elif composite < 0.3:
                multipliers[agent] = 1.25
            else:
                multipliers[agent] = 1.4
        except (KeyError, AttributeError):
            logger.debug(
                "Using default calibration multiplier for agent=%s",
                agent,
                exc_info=True,
            )
            multipliers[agent] = 1.0

    return multipliers


def save_match(
    db: EloDatabase,
    debate_id: str,
    winner: str | None,
    participants: list[str],
    domain: str | None,
    scores: dict[str, float],
    elo_changes: dict[str, float],
) -> None:
    """Save match to history.

    Args:
        db: EloDatabase instance
        debate_id: Unique debate identifier
        winner: Winner name or None for draw
        participants: List of participant names
        domain: Optional domain
        scores: Dict of agent -> score
        elo_changes: Dict of agent -> ELO change
    """
    with db.connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO matches (debate_id, winner, participants, domain, scores, elo_changes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                debate_id,
                winner,
                json.dumps(participants),
                domain,
                json.dumps(scores),
                json.dumps(elo_changes),
            ),
        )
        conn.commit()


def check_duplicate_match(db: EloDatabase, debate_id: str) -> dict[str, float] | None:
    """Check if a match has already been recorded.

    Args:
        db: EloDatabase instance
        debate_id: Debate ID to check

    Returns:
        Cached ELO changes if match exists, None otherwise
    """
    from aragora.utils.json_helpers import safe_json_loads

    with db.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT elo_changes FROM matches WHERE debate_id = ?",
            (debate_id,),
        )
        existing = cursor.fetchone()
        if existing:
            logger.debug("Skipping duplicate record_match for debate_id=%s", debate_id)
            return safe_json_loads(existing[0], {})
    return None


def determine_winner(scores: dict[str, float]) -> str | None:
    """Determine winner from scores.

    Args:
        scores: Dict of agent -> score

    Returns:
        Winner name or None for draw
    """
    sorted_agents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_agents) < 2:
        return sorted_agents[0][0] if sorted_agents else None
    return sorted_agents[0][0] if sorted_agents[0][1] > sorted_agents[1][1] else None


__all__ = [
    "build_match_scores",
    "generate_match_id",
    "normalize_match_params",
    "compute_calibration_k_multipliers",
    "save_match",
    "check_duplicate_match",
    "determine_winner",
]
