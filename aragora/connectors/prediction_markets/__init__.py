"""External prediction-market venue adapters.

Exposes AGT-03 venue adapters: Manifold Markets (read + gated write path) and
Metaculus (Phase 1, read-only). See
``docs/plans/2026-04-17-prediction-market-validation.md`` for the
venue stack rationale and graduation gates.
"""

from __future__ import annotations

from aragora.connectors.prediction_markets.manifold import (
    MANIFOLD_API_BASE,
    MANIFOLD_WRITE_FLAG,
    ManifoldAdapter,
    ManifoldBetAdapter,
    ManifoldBetResult,
    ManifoldError,
    ManifoldMarket,
    ManifoldResolution,
    manifold_to_market_resolution,
    manifold_write_enabled,
)
from aragora.connectors.prediction_markets.metaculus import (
    METACULUS_API_BASE,
    MetaculusAdapter,
    MetaculusError,
    MetaculusQuestion,
    MetaculusResolution,
    metaculus_to_market_resolution,
)
from aragora.connectors.prediction_markets.stake_caps import (
    CAP_GRADUATION_FLAG,
    StabilityRecord,
    StakeCapSchedule,
)
from aragora.connectors.prediction_markets.synthetic_github import (
    DEFAULT_POSITION_CAP,
    SYNTHETIC_MARKETS_FLAG,
    SyntheticGitHubAdapter,
    SyntheticGitHubError,
    open_adapter,
    synthetic_markets_enabled,
)

__all__ = [
    "CAP_GRADUATION_FLAG",
    "DEFAULT_POSITION_CAP",
    "MANIFOLD_API_BASE",
    "MANIFOLD_WRITE_FLAG",
    "ManifoldAdapter",
    "ManifoldBetAdapter",
    "ManifoldBetResult",
    "ManifoldError",
    "ManifoldMarket",
    "ManifoldResolution",
    "METACULUS_API_BASE",
    "MetaculusAdapter",
    "MetaculusError",
    "MetaculusQuestion",
    "MetaculusResolution",
    "SYNTHETIC_MARKETS_FLAG",
    "StabilityRecord",
    "StakeCapSchedule",
    "SyntheticGitHubAdapter",
    "SyntheticGitHubError",
    "manifold_to_market_resolution",
    "manifold_write_enabled",
    "metaculus_to_market_resolution",
    "open_adapter",
    "synthetic_markets_enabled",
]
