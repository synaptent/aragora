"""
Analytics Core Module - Consolidated Analytics Handlers.

This module consolidates analytics handlers for a unified domain structure.
The original handler implementations are in _analytics_impl.py and
_analytics_metrics_impl.py, while this module provides a unified import point.

Handlers consolidated:
- AnalyticsHandler (from _analytics_impl.py): Core analytics endpoints
- AnalyticsMetricsHandler (from _analytics_metrics_impl.py): Debate/agent metrics

Note: AnalyticsDashboardHandler remains in analytics_dashboard.py as a separate
large module per the consolidation plan.

Migrated as part of handler consolidation Tier 1.
"""

from __future__ import annotations

# Re-export from renamed implementation files
from ._analytics_impl import (
    ANALYTICS_PERMISSION,
    AnalyticsHandler,
    _analytics_limiter,
)

from ._analytics_metrics_impl import (
    ANALYTICS_METRICS_PERMISSION,
    AnalyticsMetricsHandler,
    VALID_GRANULARITIES,
    VALID_TIME_RANGES,
    _analytics_metrics_limiter,
    _group_by_time,
    _parse_time_range,
)

# Keep the public re-export surface stable for imports and tests.
__all__ = (
    # Core analytics handler
    "AnalyticsHandler",
    "ANALYTICS_PERMISSION",
    "_analytics_limiter",
    # Analytics metrics handler
    "AnalyticsMetricsHandler",
    "ANALYTICS_METRICS_PERMISSION",
    "_analytics_metrics_limiter",
    # Utility functions
    "_parse_time_range",
    "_group_by_time",
    # Constants
    "VALID_GRANULARITIES",
    "VALID_TIME_RANGES",
)

# Guard the re-export contract against accidental duplicate additions.
if len(__all__) != len(set(__all__)):
    raise ImportError("analytics.core __all__ must stay duplicate-free")
