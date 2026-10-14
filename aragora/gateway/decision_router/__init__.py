"""
Intelligent Decision Router (deprecated compatibility path).

The router lives in :mod:`aragora.routing.gateway_decision_router`; this module
re-exports the same objects.
"""

from __future__ import annotations

import warnings

from aragora.routing.gateway_decision_router import (
    DEFAULT_CATEGORY_CONFIGS,
    ActionCategory,
    AlertHandlerProtocol,
    AnomalyDetectorProtocol,
    CategoryDefaults,
    DecisionRouter,
    RiskLevel,
    RouteDecision,
    RouteDestination,
    RoutingAuditEntry,
    RoutingCriteria,
    RoutingEventType,
    RoutingMetrics,
    RoutingRule,
    SimpleAnomalyDetector,
    TenantRoutingConfig,
)

warnings.warn(
    "aragora.gateway.decision_router is deprecated. Use aragora.core.decision_router instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "RouteDestination",
    "RiskLevel",
    "ActionCategory",
    "RoutingEventType",
    "RoutingCriteria",
    "RouteDecision",
    "RoutingRule",
    "TenantRoutingConfig",
    "CategoryDefaults",
    "RoutingMetrics",
    "RoutingAuditEntry",
    "AnomalyDetectorProtocol",
    "AlertHandlerProtocol",
    "DecisionRouter",
    "SimpleAnomalyDetector",
    "DEFAULT_CATEGORY_CONFIGS",
]
