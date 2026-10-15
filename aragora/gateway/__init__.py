"""
Local Gateway - OpenClaw parity extension for consumer/device interface.

Provides a device-local routing and auth service that aggregates messages
from multiple channels into a unified inbox, routes them to appropriate
agents, and manages device registrations.

This module implements the OpenClaw consumer interface model on top of
the existing Aragora connector infrastructure.

Key concepts:
- LocalGateway: Device-local HTTP service for message routing and auth.
- InboxAggregator: Unified inbox across all connected channels.
- DeviceRegistry: Registry of device capabilities and permissions.
- AgentRouter: Per-channel/account agent assignment rules.

Usage:
    from aragora.gateway import LocalGateway

    gw = LocalGateway()
    await gw.start(host="127.0.0.1", port=8090)
"""

from aragora.gateway.server import LocalGateway, GatewayConfig
from aragora.gateway.inbox import InboxAggregator, InboxMessage, InboxThread
from aragora.gateway.device_registry import DeviceNode, DeviceRegistry, DeviceStatus
from aragora.gateway.device_node import DeviceNodeRuntime, DeviceNodeRuntimeConfig
from aragora.gateway.device_security import (
    PairingStatus,
    PairingRequest,
    SecureDeviceRegistry,
)
from aragora.gateway.router import AgentRouter, RoutingRule
from aragora.gateway.capability_router import CapabilityRouter, CapabilityRule, RoutingResult
from aragora.gateway.protocol import (
    GatewayProtocolAdapter,
    GatewaySession,
    GatewayWebSocketProtocol,
)
from aragora.gateway.persistence import (
    GatewayStore,
    InMemoryGatewayStore,
    FileGatewayStore,
    RedisGatewayStore,
    get_gateway_store,
)
from aragora.gateway.credential_proxy import (
    CredentialProxy,
    CredentialUsage,
    ExternalCredential,
    CredentialProxyError,
    CredentialNotFoundError,
    CredentialExpiredError,
    ScopeError,
    RateLimitExceededError,
    TenantIsolationError,
    get_credential_proxy,
    set_credential_proxy,
    reset_credential_proxy,
)

from aragora.routing.gateway_decision_router import (
    DecisionRouter,
    RoutingCriteria,
    RouteDecision,
    RoutingRule as DecisionRoutingRule,
    TenantRoutingConfig as DecisionTenantConfig,
    RouteDestination,
    RiskLevel,
    ActionCategory,
    RoutingEventType as DecisionRoutingEventType,
    RoutingMetrics,
    SimpleAnomalyDetector,
)
from aragora.gateway.metrics import (
    init_gateway_metrics,
    record_gateway_request,
    record_gateway_action,
    record_policy_decision,
    record_audit_event,
    set_circuit_breaker_state,
    set_credentials_stored,
    set_active_sessions,
    inc_active_sessions,
    dec_active_sessions,
    track_gateway_request,
    track_gateway_action,
)
from aragora.gateway.health import (
    GatewayHealthChecker,
    GatewayHealthStatus,
    ComponentHealth,
    HealthStatus as GatewayHealthStatus_Enum,
)

__all__ = [
    # Server
    "LocalGateway",
    "GatewayConfig",
    # Inbox
    "InboxAggregator",
    "InboxMessage",
    "InboxThread",
    # Device
    "DeviceNode",
    "DeviceRegistry",
    "DeviceStatus",
    "DeviceNodeRuntime",
    "DeviceNodeRuntimeConfig",
    # Device Security
    "PairingStatus",
    "PairingRequest",
    "SecureDeviceRegistry",
    # Protocol
    "GatewayProtocolAdapter",
    "GatewaySession",
    "GatewayWebSocketProtocol",
    # Router
    "AgentRouter",
    "RoutingRule",
    "CapabilityRouter",
    "CapabilityRule",
    "RoutingResult",
    # Persistence
    "GatewayStore",
    "InMemoryGatewayStore",
    "FileGatewayStore",
    "RedisGatewayStore",
    "get_gateway_store",
    # Credential Proxy
    "CredentialProxy",
    "CredentialUsage",
    "ExternalCredential",
    "CredentialProxyError",
    "CredentialNotFoundError",
    "CredentialExpiredError",
    "ScopeError",
    "RateLimitExceededError",
    "TenantIsolationError",
    "get_credential_proxy",
    "set_credential_proxy",
    "reset_credential_proxy",
    # Decision Router
    "DecisionRouter",
    "RoutingCriteria",
    "RouteDecision",
    "DecisionRoutingRule",
    "DecisionTenantConfig",
    "RouteDestination",
    "RiskLevel",
    "ActionCategory",
    "DecisionRoutingEventType",
    "RoutingMetrics",
    "SimpleAnomalyDetector",
    # Metrics
    "init_gateway_metrics",
    "record_gateway_request",
    "record_gateway_action",
    "record_policy_decision",
    "record_audit_event",
    "set_circuit_breaker_state",
    "set_credentials_stored",
    "set_active_sessions",
    "inc_active_sessions",
    "dec_active_sessions",
    "track_gateway_request",
    "track_gateway_action",
    # Health
    "GatewayHealthChecker",
    "GatewayHealthStatus",
    "ComponentHealth",
    "GatewayHealthStatus_Enum",
]
