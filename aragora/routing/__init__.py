"""
Routing - Agent selection and decision routing.

Provides:
- Adaptive agent selection for optimal team composition
- Domain detection and auto-routing
- Unified decision routing (Gateway + Core integration)

The unified router chains Gateway (business logic) with Core (execution):
    Request → Gateway Router → Core Router → Result
           (business criteria)  (engine selection)

Usage:
    # Agent selection
    from aragora.routing import AgentSelector, TeamBuilder

    # Decision routing
    from aragora.routing import UnifiedDecisionRouter, route_decision_auto
"""

from aragora.routing.selection import (
    DEFAULT_AGENT_EXPERTISE,
    DOMAIN_KEYWORDS,
    PHASE_ROLES,
    AgentProfile,
    AgentSelector,
    DomainDetector,
    TaskRequirements,
    TeamBuilder,
    TeamComposition,
)
from aragora.routing.unified_router import (
    UnifiedDecisionRouter,
    UnifiedRoutingResult,
    get_unified_router,
    reset_unified_router,
    route_decision_auto,
)
from aragora.routing.config import GatewayRoutingConfig, load_gateway_routing_config
from aragora.routing.lara_router import (
    LaRARouter,
    LaRAConfig,
    QueryFeatures,
    RetrievalMode,
    RoutingDecision,
    create_lara_router,
    quick_route,
)
from aragora.routing.provider_metrics import ProviderMetrics, ProviderMetricsStore
from aragora.routing.cost_quality_optimizer import (
    CostQualityOptimizer,
    SelectionStrategy,
    pareto_frontier,
)
from aragora.routing.provider_config import (
    ProviderPricing,
    PROVIDER_PRICING as PROVIDER_ROUTING_PRICING,
    get_estimated_cost,
)
from aragora.routing.provider_router import ProviderRouter, get_provider_router

__all__ = [
    # Agent selection
    "AgentSelector",
    "AgentProfile",
    "TaskRequirements",
    "TeamComposition",
    "TeamBuilder",
    "DomainDetector",
    "DOMAIN_KEYWORDS",
    "PHASE_ROLES",
    "DEFAULT_AGENT_EXPERTISE",
    # Unified decision routing
    "UnifiedDecisionRouter",
    "UnifiedRoutingResult",
    "get_unified_router",
    "reset_unified_router",
    "route_decision_auto",
    "GatewayRoutingConfig",
    "load_gateway_routing_config",
    # LaRA retrieval routing
    "LaRARouter",
    "LaRAConfig",
    "QueryFeatures",
    "RetrievalMode",
    "RoutingDecision",
    "create_lara_router",
    "quick_route",
    # Provider routing (Phase 1)
    "ProviderMetrics",
    "ProviderMetricsStore",
    "CostQualityOptimizer",
    "SelectionStrategy",
    "pareto_frontier",
    "ProviderPricing",
    "PROVIDER_ROUTING_PRICING",
    "get_estimated_cost",
    "ProviderRouter",
    "get_provider_router",
]
