"""
Relationship endpoint handlers.

Endpoints:
- GET /api/relationships/summary - Global relationship overview
- GET /api/relationships/graph - Full relationship graph for visualizations
- GET /api/relationships/stats - Relationship system statistics
- GET /api/relationship/{agent_a}/{agent_b} - Detailed relationship between two agents
"""

from __future__ import annotations

import logging
from functools import wraps
from pathlib import Path
from typing import Any, TYPE_CHECKING, NamedTuple
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.agents.grounded import AgentRelationship as AgentRelationshipType
    from aragora.agents.grounded import RelationshipTracker as RelationshipTrackerType

from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.rbac.decorators import require_permission
from aragora.utils.optional_imports import try_import

from ..base import (
    SAFE_AGENT_PATTERN,
    BaseHandler,
    HandlerResult,
    error_response,
    get_db_connection,
    get_float_param,
    get_int_param,
    json_response,
    table_exists,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for relationship endpoints (60 requests per minute - read-heavy)
_relationship_limiter = RateLimiter(requests_per_minute=60)

# Lazy imports for optional dependencies using centralized utility
_relationship_imports, RELATIONSHIP_TRACKER_AVAILABLE = try_import(
    "aragora.agents.grounded", "RelationshipTracker", "AgentRelationship"
)
# These are class types when available, None otherwise
RelationshipTracker: type[RelationshipTrackerType] | None = _relationship_imports[
    "RelationshipTracker"
]
AgentRelationship: type[AgentRelationshipType] | None = _relationship_imports["AgentRelationship"]

from aragora.api_errors import safe_error_message as _safe_error_message

# =============================================================================
# Score Computation Utilities
# =============================================================================


def compute_rivalry_score(
    debate_count: int, agreement_count: int, a_wins: int, b_wins: int
) -> float:
    """Compute rivalry score between two agents.

    Rivalry is high when agents frequently disagree and have competitive win rates.

    Args:
        debate_count: Number of debates between the agents
        agreement_count: Number of debates where they agreed
        a_wins: Wins by agent A over agent B
        b_wins: Wins by agent B over agent A

    Returns:
        Rivalry score from 0.0 to 1.0
    """
    if debate_count < 3:
        return 0.0
    disagreement_rate = 1 - (agreement_count / debate_count)
    total_wins = a_wins + b_wins
    competitiveness = 1 - abs(a_wins - b_wins) / max(total_wins, 1)
    frequency_factor = min(1.0, debate_count / 20)
    return disagreement_rate * competitiveness * frequency_factor


def compute_alliance_score(debate_count: int, agreement_count: int) -> float:
    """Compute alliance score between two agents.

    Alliance is high when agents frequently agree.

    Note: Full alliance_score also uses critique acceptance rates, but those
    aren't always available. This simplified version uses just agreement rate.

    Args:
        debate_count: Number of debates between the agents
        agreement_count: Number of debates where they agreed

    Returns:
        Alliance score from 0.0 to 1.0
    """
    if debate_count < 3:
        return 0.0
    agreement_rate = agreement_count / debate_count
    # Simplified: alliance_score = agreement_rate * 0.6 + acceptance_rate * 0.4
    # Since we don't have critique data, use agreement_rate * 0.6 as baseline
    return agreement_rate * 0.6


def determine_relationship_type(
    rivalry_score: float, alliance_score: float, threshold: float = 0.3
) -> str:
    """Determine relationship type based on rivalry and alliance scores.

    Args:
        rivalry_score: Rivalry score (0.0 to 1.0)
        alliance_score: Alliance score (0.0 to 1.0)
        threshold: Minimum score to classify as rivalry/alliance (default: 0.3)

    Returns:
        Relationship type: "rivalry", "alliance", or "neutral"
    """
    if rivalry_score > alliance_score and rivalry_score > threshold:
        return "rivalry"
    elif alliance_score > rivalry_score and alliance_score > threshold:
        return "alliance"
    return "neutral"


class RelationshipScores(NamedTuple):
    """Computed relationship scores and classification."""

    rivalry_score: float
    alliance_score: float
    relationship_type: str


def compute_relationship_scores(
    debate_count: int, agreement_count: int, a_wins: int, b_wins: int
) -> RelationshipScores:
    """Compute all relationship scores and type in one call.

    Combines rivalry score, alliance score, and relationship type computation
    into a single function to avoid duplicate code patterns.

    Args:
        debate_count: Number of debates between the agents
        agreement_count: Number of debates where they agreed
        a_wins: Wins by agent A over agent B
        b_wins: Wins by agent B over agent A

    Returns:
        RelationshipScores with rivalry_score, alliance_score, and relationship_type
    """
    rivalry = compute_rivalry_score(debate_count, agreement_count, a_wins, b_wins)
    alliance = compute_alliance_score(debate_count, agreement_count)
    rel_type = determine_relationship_type(rivalry, alliance)
    return RelationshipScores(rivalry, alliance, rel_type)


# =============================================================================
# Handler Decorators
# =============================================================================


def require_tracker(func: Callable) -> Callable:
    """Decorator that handles tracker availability and initialization.

    Converts nomic_dir parameter to an initialized tracker. Methods decorated
    with this receive a guaranteed non-None RelationshipTracker.

    Usage:
        # Call site: self._get_summary(nomic_dir)
        @require_tracker
        def _get_summary(self, tracker: RelationshipTrackerType) -> HandlerResult:
            # tracker is guaranteed non-None
            ...
    """

    @wraps(func)
    def wrapper(self: Any, nomic_dir: Path | None, *args: Any, **kwargs: Any) -> HandlerResult:
        if not RELATIONSHIP_TRACKER_AVAILABLE:
            return error_response("Relationship tracker not available", 503)
        tracker = self._get_tracker(nomic_dir)
        if not tracker:
            return error_response("Failed to initialize relationship tracker", 503)
        return func(self, tracker, *args, **kwargs)

    return wrapper


class RelationshipHandler(BaseHandler):
    """Handler for relationship endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/relationships/summary",
        "/api/v1/relationships/graph",
        "/api/v1/relationships/stats",
        "/api/v1/relationship/{agent_a}/{agent_b}",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        # Handle dynamic route: /api/relationship/{agent_a}/{agent_b}
        if path.startswith("/api/v1/relationship/") and path.count("/") >= 4:
            return True
        return False

    @require_permission("relationships:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route relationship requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _relationship_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for relationship endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        logger.debug("Relationship request: %s params=%s", path, query_params)
        nomic_dir = self.ctx.get("nomic_dir")

        if path == "/api/v1/relationships/summary":
            return self._get_summary(nomic_dir)

        if path == "/api/v1/relationships/graph":
            min_debates = get_int_param(query_params, "min_debates", 3)
            min_score = get_float_param(query_params, "min_score", 0.0)
            return self._get_graph(nomic_dir, min_debates, min_score)

        if path == "/api/v1/relationships/stats":
            return self._get_stats(nomic_dir)

        # Handle /api/v1/relationship/{agent_a}/{agent_b}
        if path.startswith("/api/v1/relationship/"):
            params, err = self.extract_path_params(
                path,
                [
                    (4, "agent_a", SAFE_AGENT_PATTERN),
                    (5, "agent_b", SAFE_AGENT_PATTERN),
                ],
            )
            if err or params is None:
                return err
            return self._get_pair_detail(nomic_dir, params["agent_a"], params["agent_b"])

        return None

    def _get_tracker(self, nomic_dir: Path | None) -> RelationshipTrackerType | None:
        """Get or create a RelationshipTracker instance."""
        if not RELATIONSHIP_TRACKER_AVAILABLE or RelationshipTracker is None:
            return None
        try:
            # Use the positions DB if nomic_dir is set
            if nomic_dir:
                db_path = get_db_path(DatabaseType.POSITIONS, nomic_dir)
                if db_path.exists():
                    return RelationshipTracker(elo_db_path=str(db_path))
            # Fall back to default
            return RelationshipTracker()
        except (OSError, ValueError, TypeError, RuntimeError) as e:
            logger.warning("Failed to create RelationshipTracker: %s", e)
            return None

    def _fetch_relationships(
        self, tracker: RelationshipTrackerType, min_debates: int = 0
    ) -> list[tuple[str, str, int, int, int, int]]:
        """Fetch relationship rows from database.

        Returns list of (agent_a, agent_b, debate_count, agreement_count, a_wins, b_wins).
        Returns empty list if table doesn't exist.
        """
        with get_db_connection(str(tracker.db_path)) as conn:
            cursor = conn.cursor()
            if not table_exists(cursor, "agent_relationships"):
                return []
            cursor.execute(
                """
                SELECT agent_a, agent_b, debate_count, agreement_count,
                       a_wins_over_b, b_wins_over_a
                FROM agent_relationships
                WHERE debate_count >= ?
            """,
                (min_debates,),
            )
            return cursor.fetchall()

    @require_tracker
    def _get_summary(self, tracker: RelationshipTrackerType) -> HandlerResult:
        """Get global relationship overview."""
        try:
            # Collect all unique agents and their relationships
            all_agents: set[str] = set()
            agent_relationship_counts: dict[str, int] = {}

            # We need to query the DB directly to get all relationships
            # Use a helper to get all pairs from the database
            with get_db_connection(str(tracker.db_path)) as conn:
                cursor = conn.cursor()

                if not table_exists(cursor, "agent_relationships"):
                    return json_response(
                        {
                            "total_relationships": 0,
                            "strongest_rivalry": None,
                            "strongest_alliance": None,
                            "most_connected_agent": None,
                            "avg_rivalry_score": 0.0,
                            "avg_alliance_score": 0.0,
                        }
                    )

                # Safety limit to prevent memory explosion - cap at 10,000 relationships
                MAX_RELATIONSHIPS = 10000
                cursor.execute(
                    """
                    SELECT agent_a, agent_b, debate_count, agreement_count,
                           a_wins_over_b, b_wins_over_a
                    FROM agent_relationships
                    WHERE debate_count >= 3
                    ORDER BY debate_count DESC
                    LIMIT ?
                """,
                    (MAX_RELATIONSHIPS,),
                )
                rows = cursor.fetchall()

                if len(rows) == MAX_RELATIONSHIPS:
                    logger.warning(
                        "Relationship summary hit limit of %s - results may be incomplete",
                        MAX_RELATIONSHIPS,
                    )

            if not rows:
                return json_response(
                    {
                        "total_relationships": 0,
                        "strongest_rivalry": None,
                        "strongest_alliance": None,
                        "most_connected_agent": None,
                        "avg_rivalry_score": 0.0,
                        "avg_alliance_score": 0.0,
                    }
                )

            # Process relationships
            strongest_rivalry = None
            strongest_rivalry_score = 0.0
            strongest_alliance = None
            strongest_alliance_score = 0.0
            rivalry_scores = []
            alliance_scores = []

            for row in rows:
                agent_a, agent_b, debate_count, agreement_count, a_wins, b_wins = row
                all_agents.add(agent_a)
                all_agents.add(agent_b)

                # Count connections per agent
                agent_relationship_counts[agent_a] = agent_relationship_counts.get(agent_a, 0) + 1
                agent_relationship_counts[agent_b] = agent_relationship_counts.get(agent_b, 0) + 1

                # Compute scores inline (avoids N+1 query)
                scores = compute_relationship_scores(debate_count, agreement_count, a_wins, b_wins)

                if scores.rivalry_score > 0:
                    rivalry_scores.append(scores.rivalry_score)
                    if scores.rivalry_score > strongest_rivalry_score:
                        strongest_rivalry_score = scores.rivalry_score
                        strongest_rivalry = {
                            "agents": [agent_a, agent_b],
                            "score": scores.rivalry_score,
                        }

                if scores.alliance_score > 0:
                    alliance_scores.append(scores.alliance_score)
                    if scores.alliance_score > strongest_alliance_score:
                        strongest_alliance_score = scores.alliance_score
                        strongest_alliance = {
                            "agents": [agent_a, agent_b],
                            "score": scores.alliance_score,
                        }

            # Find most connected agent
            most_connected = None
            if agent_relationship_counts:
                most_connected_name = max(
                    agent_relationship_counts, key=agent_relationship_counts.__getitem__
                )
                most_connected = {
                    "name": most_connected_name,
                    "relationship_count": agent_relationship_counts[most_connected_name],
                }

            logger.info(
                "Relationship summary: %s relationships, %s rivalries, %s alliances",
                len(rows),
                len(rivalry_scores),
                len(alliance_scores),
            )
            return json_response(
                {
                    "total_relationships": len(rows),
                    "strongest_rivalry": strongest_rivalry,
                    "strongest_alliance": strongest_alliance,
                    "most_connected_agent": most_connected,
                    "avg_rivalry_score": (
                        sum(rivalry_scores) / len(rivalry_scores) if rivalry_scores else 0.0
                    ),
                    "avg_alliance_score": (
                        sum(alliance_scores) / len(alliance_scores) if alliance_scores else 0.0
                    ),
                }
            )

        except (OSError, KeyError, ValueError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "relationships_summary"), 500)

    @require_tracker
    def _get_graph(
        self, tracker: RelationshipTrackerType, min_debates: int, min_score: float
    ) -> HandlerResult:
        """Get full relationship graph for visualizations."""
        try:
            rows = self._fetch_relationships(tracker, min_debates)
            if not rows:
                return json_response(
                    {"nodes": [], "edges": [], "stats": {"node_count": 0, "edge_count": 0}}
                )

            # Build nodes and edges
            nodes_data = {}  # agent -> {debate_count, rivals, allies}
            edges = []

            for row in rows:
                agent_a, agent_b, debate_count, agreement_count, a_wins, b_wins = row

                # Initialize node data
                for agent in [agent_a, agent_b]:
                    if agent not in nodes_data:
                        nodes_data[agent] = {"debate_count": 0, "rivals": 0, "allies": 0}

                # Compute scores inline (avoids N+1 query)
                scores = compute_relationship_scores(debate_count, agreement_count, a_wins, b_wins)

                # Apply score filter
                max_score = max(scores.rivalry_score, scores.alliance_score)
                if max_score < min_score:
                    continue

                # Update node counters based on relationship type
                if scores.relationship_type == "rivalry":
                    nodes_data[agent_a]["rivals"] += 1
                    nodes_data[agent_b]["rivals"] += 1
                elif scores.relationship_type == "alliance":
                    nodes_data[agent_a]["allies"] += 1
                    nodes_data[agent_b]["allies"] += 1

                # Update debate counts
                nodes_data[agent_a]["debate_count"] += debate_count
                nodes_data[agent_b]["debate_count"] += debate_count

                edges.append(
                    {
                        "source": agent_a,
                        "target": agent_b,
                        "rivalry_score": round(scores.rivalry_score, 3),
                        "alliance_score": round(scores.alliance_score, 3),
                        "debate_count": debate_count,
                        "type": scores.relationship_type,
                    }
                )

            # Build nodes list
            nodes = [
                {
                    "id": agent,
                    "debate_count": data["debate_count"],
                    "rivals": data["rivals"],
                    "allies": data["allies"],
                }
                for agent, data in nodes_data.items()
            ]

            logger.info("Relationship graph: %s nodes, %s edges", len(nodes), len(edges))
            return json_response(
                {
                    "nodes": nodes,
                    "edges": edges,
                    "stats": {"node_count": len(nodes), "edge_count": len(edges)},
                }
            )

        except (OSError, KeyError, ValueError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "relationships_graph"), 500)

    @require_tracker
    def _get_pair_detail(
        self, tracker: RelationshipTrackerType, agent_a: str, agent_b: str
    ) -> HandlerResult:
        """Get detailed relationship between two specific agents."""
        try:
            rel = tracker.get_relationship(agent_a, agent_b)

            if rel.debate_count == 0:
                return json_response(
                    {
                        "agent_a": agent_a,
                        "agent_b": agent_b,
                        "relationship_exists": False,
                        "message": "No recorded interactions between these agents",
                    }
                )

            # Compute derived metrics
            agreement_rate = rel.agreement_count / rel.debate_count if rel.debate_count > 0 else 0
            rivalry_score = rel.rivalry_score
            alliance_score = rel.alliance_score
            rel_type = determine_relationship_type(rivalry_score, alliance_score)

            return json_response(
                {
                    "agent_a": rel.agent_a,
                    "agent_b": rel.agent_b,
                    "relationship_exists": True,
                    "debate_count": rel.debate_count,
                    "agreement_count": rel.agreement_count,
                    "agreement_rate": round(agreement_rate, 3),
                    "rivalry_score": round(rivalry_score, 3),
                    "alliance_score": round(alliance_score, 3),
                    "relationship_type": rel_type,
                    "head_to_head": {
                        f"{rel.agent_a}_wins": rel.a_wins_over_b,
                        f"{rel.agent_b}_wins": rel.b_wins_over_a,
                    },
                    "critique_balance": {
                        f"{rel.agent_a}_to_{rel.agent_b}": rel.critique_count_a_to_b,
                        f"{rel.agent_b}_to_{rel.agent_a}": rel.critique_count_b_to_a,
                    },
                    "influence": {
                        f"{rel.agent_a}_on_{rel.agent_b}": round(rel.influence_a_on_b, 3),
                        f"{rel.agent_b}_on_{rel.agent_a}": round(rel.influence_b_on_a, 3),
                    },
                }
            )

        except (OSError, KeyError, ValueError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "relationship_pair_detail"), 500)

    def _empty_stats_response(self) -> HandlerResult:
        """Return empty stats response when no data available."""
        return json_response(
            {
                "total_tracked_pairs": 0,
                "total_debates_tracked": 0,
                "rivalries": {"count": 0, "avg_score": 0.0},
                "alliances": {"count": 0, "avg_score": 0.0},
                "neutral": {"count": 0},
                "most_debated_pair": None,
                "highest_agreement_pair": None,
            }
        )

    @require_tracker
    def _get_stats(self, tracker: RelationshipTrackerType) -> HandlerResult:
        """Get relationship system statistics."""
        try:
            rows = self._fetch_relationships(tracker)
            if not rows:
                return self._empty_stats_response()

            # Process statistics
            total_debates = 0
            rivalries = []
            alliances = []
            neutral_count = 0
            most_debated = None
            most_debated_count = 0
            highest_agreement = None
            highest_agreement_rate = 0.0

            for row in rows:
                agent_a, agent_b, debate_count, agreement_count, a_wins, b_wins = row
                total_debates += debate_count

                # Track most debated pair
                if debate_count > most_debated_count:
                    most_debated_count = debate_count
                    most_debated = {"agents": [agent_a, agent_b], "debates": debate_count}

                # Track highest agreement (min 3 debates)
                if debate_count >= 3:
                    agreement_rate = agreement_count / debate_count
                    if agreement_rate > highest_agreement_rate:
                        highest_agreement_rate = agreement_rate
                        highest_agreement = {
                            "agents": [agent_a, agent_b],
                            "rate": round(agreement_rate, 3),
                        }

                    # Compute scores inline (avoids N+1 query)
                    scores = compute_relationship_scores(
                        debate_count, agreement_count, a_wins, b_wins
                    )

                    if scores.relationship_type == "rivalry":
                        rivalries.append(scores.rivalry_score)
                    elif scores.relationship_type == "alliance":
                        alliances.append(scores.alliance_score)
                    else:
                        neutral_count += 1

            return json_response(
                {
                    "total_tracked_pairs": len(rows),
                    "total_debates_tracked": total_debates,
                    "rivalries": {
                        "count": len(rivalries),
                        "avg_score": (
                            round(sum(rivalries) / len(rivalries), 3) if rivalries else 0.0
                        ),
                    },
                    "alliances": {
                        "count": len(alliances),
                        "avg_score": (
                            round(sum(alliances) / len(alliances), 3) if alliances else 0.0
                        ),
                    },
                    "neutral": {"count": neutral_count},
                    "most_debated_pair": most_debated,
                    "highest_agreement_pair": highest_agreement,
                }
            )

        except (OSError, KeyError, ValueError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "relationships_stats"), 500)
