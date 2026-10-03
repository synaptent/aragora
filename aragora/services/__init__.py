"""
Aragora Services Package.

Provides centralized service management via the ServiceRegistry pattern.
This replaces scattered global singletons with a unified, testable registry.

Usage:
    from aragora.services import ServiceRegistry, get_service, register_service

    # Register a service
    register_service(TierManager, my_tier_manager)

    # Get a service
    tier_manager = get_service(TierManager)

    # Get registry stats
    stats = ServiceRegistry.get().stats()

    # Graceful shutdown
    ServiceRegistry.get().shutdown()

    # For testing - reset all services
    ServiceRegistry.reset()
"""

from typing import Any

from aragora.utils.cache import register_cache_registration_hook

from .registry import (
    RegistryStats,
    ServiceDescriptor,
    ServiceNotFoundError,
    ServiceRegistry,
    ServiceScope,
    get_service,
    has_service,
    register_service,
)

# =============================================================================
# Marker Types for Cache Services
# =============================================================================
# These marker types allow registering different cache instances with the
# ServiceRegistry while maintaining type safety.


class MethodCacheService:
    """Marker type for the global method cache (utils/cache.py)."""

    pass


class QueryCacheService:
    """Marker type for the global query cache (utils/cache.py)."""

    pass


class EmbeddingCacheService:
    """Marker type for the embedding cache (memory/embeddings.py)."""

    pass


class HandlerCacheService:
    """Marker type for the HTTP handler cache (server/handlers/base.py)."""

    pass


class EmbeddingProviderService:
    """Marker type for the embedding provider reference (memory/streams.py)."""

    pass


def _register_foundation_caches(method_cache: Any, query_cache: Any) -> None:
    """Register foundation cache instances without making utils import services."""
    registry = ServiceRegistry.get()
    if not registry.has(MethodCacheService):
        registry.register(MethodCacheService, method_cache)
    if not registry.has(QueryCacheService):
        registry.register(QueryCacheService, query_cache)


register_cache_registration_hook(_register_foundation_caches)


__all__ = [
    # Registry
    "ServiceRegistry",
    "ServiceNotFoundError",
    "ServiceScope",
    "ServiceDescriptor",
    "RegistryStats",
    "get_service",
    "register_service",
    "has_service",
    # Cache markers
    "MethodCacheService",
    "QueryCacheService",
    "EmbeddingCacheService",
    "HandlerCacheService",
    "EmbeddingProviderService",
    # Email Prioritization
    "EmailPrioritizer",
    "EmailPriorityResult",
    "EmailPriority",
    "EmailPrioritizationConfig",
    "prioritize_inbox",
    # Cross-Channel Context
    "CrossChannelContextService",
    "ChannelContext",
    "EmailContextBoost",
    "SlackActivitySignal",
    "create_context_service",
    # Sender History
    "SenderHistoryService",
    "SenderStats",
    "SenderReputation",
    "create_sender_history_service",
    # Cost Optimization
    "CostOptimizedPrioritizer",
    "CostConfig",
    "UsageStats",
    "create_cost_optimized_prioritizer",
    # Multi-Inbox Manager
    "MultiInboxManager",
    "InboxAccount",
    "UnifiedEmail",
    "CrossAccountSenderProfile",
    "AccountType",
    "create_multi_inbox_manager",
    # Threat Intelligence
    "ThreatIntelligenceService",
    "ThreatIntelConfig",
    "ThreatResult",
    "ThreatType",
    "ThreatSeverity",
    "ThreatSource",
    "IPReputationResult",
    "FileHashResult",
    "check_threat",
    # Spam Classification
    "SpamClassifier",
    "SpamClassifierConfig",
    "SpamClassificationResult",
    "SpamCategory",
    "classify_email_spam",
]

# Email Prioritization Service
from .email_prioritization import (
    EmailPrioritizer,
    EmailPriorityResult,
    EmailPriority,
    EmailPrioritizationConfig,
    prioritize_inbox,
)

# Cross-Channel Context Service
from .cross_channel_context import (
    CrossChannelContextService,
    ChannelContext,
    EmailContextBoost,
    SlackActivitySignal,
    create_context_service,
)

# Sender History Service
from .sender_history import (
    SenderHistoryService,
    SenderStats,
    SenderReputation,
    create_sender_history_service,
)

# Cost Optimization Service
from .email_cost_optimizer import (
    CostOptimizedPrioritizer,
    CostConfig,
    UsageStats,
    create_cost_optimized_prioritizer,
)

# Multi-Inbox Manager
from .multi_inbox_manager import (
    MultiInboxManager,
    InboxAccount,
    UnifiedEmail,
    CrossAccountSenderProfile,
    AccountType,
    create_multi_inbox_manager,
)

# Threat Intelligence Service
from .threat_intelligence import (
    ThreatIntelligenceService,
    ThreatIntelConfig,
    ThreatResult,
    ThreatType,
    ThreatSeverity,
    ThreatSource,
    IPReputationResult,
    FileHashResult,
    check_threat,
)

# Spam Classification Service
from .spam_classifier import (
    SpamClassifier,
    SpamClassifierConfig,
    SpamClassificationResult,
    SpamCategory,
    classify_email_spam,
)
