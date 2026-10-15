"""
PerformanceAdapter - Unified adapter for agent performance metrics.

This module re-exports all public APIs from the
``aragora.knowledge.mound.adapters.performance`` subpackage for
backwards compatibility.  The implementation has been split into
focused submodules:

- ``performance/models.py``        -- Data classes
- ``performance/elo_storage.py``   -- ELO rating/match/calibration storage & retrieval
- ``performance/expertise.py``     -- Domain expertise tracking with caching
- ``performance/reverse_flow.py``  -- KM-to-ELO pattern analysis & adjustments
- ``performance/km_persistence.py``-- Knowledge Mound sync/load
- ``performance/search.py``        -- Search, fusion, semantic search implementations
- ``performance/adapter.py``       -- Main PerformanceAdapter class

Usage (unchanged):
    from aragora.knowledge.mound.adapters import PerformanceAdapter

    adapter = PerformanceAdapter()

    # Store performance data
    adapter.store_rating(rating, debate_id="d-123")
    adapter.store_agent_expertise("claude", "security", 1650, delta=50)

    # Query expertise
    experts = adapter.get_domain_experts("security", limit=5)

    # Analyze KM patterns
    patterns = await adapter.analyze_km_patterns_for_agent("claude", km_items)
"""

from __future__ import annotations

# Re-export everything from the performance subpackage
from aragora.knowledge.mound.adapters.performance.models import (
    AgentExpertise,
    EloAdjustmentRecommendation,
    EloSyncResult,
    ExpertiseSearchResult,
    KMEloPattern,
    RatingSearchResult,
)
from aragora.knowledge.mound.adapters.performance.adapter import (
    EloAdapter,
    EventCallback,
    PerformanceAdapter,
    RankingAdapter,
)

__all__ = [
    # Main adapter
    "PerformanceAdapter",
    # Backwards compatibility
    "EloAdapter",
    "RankingAdapter",
    # Type alias
    "EventCallback",
    # Dataclasses from EloAdapter
    "KMEloPattern",
    "EloAdjustmentRecommendation",
    "EloSyncResult",
    "RatingSearchResult",
    # Dataclasses from RankingAdapter
    "AgentExpertise",
    "ExpertiseSearchResult",
]
