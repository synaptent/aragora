"""
Multi-Tenant Router for Enterprise Gateway.

Routes requests to tenant-specific external framework instances with
complete data isolation, quota enforcement, and context propagation.

Features:
- Tenant-isolated routing to external framework endpoints
- Per-tenant rate limiting and quota tracking
- Fallback routing rules for high availability
- Load balancing across tenant instances
- Tenant context injection into external requests
- Comprehensive audit logging for compliance

Usage:
    from aragora.gateway.enterprise.routing import (
        TenantRouter,
        TenantRoutingConfig,
        EndpointConfig,
    )

    # Configure tenant routing
    router = TenantRouter(
        configs=[
            TenantRoutingConfig(
                tenant_id="acme-corp",
                endpoints=[
                    EndpointConfig(
                        url="https://acme.framework.example.com/api",
                        weight=100,
                        priority=1,
                    )
                ],
                quotas=TenantQuotas(
                    requests_per_minute=100,
                    requests_per_day=10000,
                ),
            ),
        ]
    )

    # Route a request
    decision = await router.route(
        tenant_id="acme-corp",
        request=request_data,
    )

    # Check quota status
    status = await router.get_quota_status("acme-corp")
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.tenancy.context import (
    get_current_tenant_id,
    TenantNotSetError,
)
from aragora.tenancy.isolation import (
    TenantDataIsolation,
    TenantIsolationConfig,
    IsolationLevel,
)

from .quotas import QuotaTracker, TenantQuotas, QuotaStatus
from .isolation import (
    CrossTenantAccessError,
    TenantContextBuilder,
    TenantRoutingContextManager,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class TenantRoutingError(Exception):
    """Base exception for tenant routing errors."""

    def __init__(
        self,
        message: str,
        tenant_id: str | None = None,
        code: str = "ROUTING_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.tenant_id = tenant_id
        self.code = code
        self.details = details or {}


class TenantNotFoundError(TenantRoutingError):
    """Raised when tenant configuration is not found."""

    def __init__(self, tenant_id: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            f"Tenant configuration not found: {tenant_id}",
            tenant_id=tenant_id,
            code="TENANT_NOT_FOUND",
            details=details,
        )


class NoAvailableEndpointError(TenantRoutingError):
    """Raised when no healthy endpoints are available for routing."""

    def __init__(self, tenant_id: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            f"No available endpoints for tenant: {tenant_id}",
            tenant_id=tenant_id,
            code="NO_AVAILABLE_ENDPOINT",
            details=details,
        )


class QuotaExceededError(TenantRoutingError):
    """Raised when tenant quota is exceeded."""

    def __init__(
        self,
        tenant_id: str,
        quota_type: str,
        limit: int,
        current: int,
        retry_after: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            f"Quota exceeded for tenant {tenant_id}: {quota_type} ({current}/{limit})",
            tenant_id=tenant_id,
            code="QUOTA_EXCEEDED",
            details={
                "quota_type": quota_type,
                "limit": limit,
                "current": current,
                "retry_after": retry_after,
                **(details or {}),
            },
        )
        self.quota_type = quota_type
        self.limit = limit
        self.current = current
        self.retry_after = retry_after


# =============================================================================
# Enums
# =============================================================================


class LoadBalancingStrategy(str, Enum):
    """Load balancing strategies for multi-endpoint routing."""

    ROUND_ROBIN = "round_robin"
    WEIGHTED_RANDOM = "weighted_random"
    LEAST_CONNECTIONS = "least_connections"
    PRIORITY = "priority"
    LATENCY = "latency"


class EndpointStatus(str, Enum):
    """Health status of an endpoint."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class RoutingEventType(str, Enum):
    """Types of routing events for audit logging."""

    ROUTE_SUCCESS = "route_success"
    ROUTE_FALLBACK = "route_fallback"
    ROUTE_FAILED = "route_failed"
    QUOTA_WARNING = "quota_warning"
    QUOTA_EXCEEDED = "quota_exceeded"
    ENDPOINT_HEALTH_CHANGE = "endpoint_health_change"
    CROSS_TENANT_BLOCKED = "cross_tenant_blocked"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class EndpointConfig:
    """
    Configuration for a single external framework endpoint.

    Attributes:
        url: Base URL of the external framework endpoint.
        weight: Weight for weighted load balancing (higher = more traffic).
        priority: Priority for failover (lower = higher priority, tried first).
        timeout: Request timeout in seconds.
        max_retries: Maximum retry attempts for failed requests.
        health_check_path: Path for health check requests.
        headers: Additional headers to include in requests.
        metadata: Additional endpoint metadata.
    """

    url: str
    weight: int = 100
    priority: int = 1
    timeout: float = 30.0
    max_retries: int = 3
    health_check_path: str = "/health"
    headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EndpointHealth:
    """
    Health status of an endpoint.

    Attributes:
        endpoint_url: URL of the endpoint.
        status: Current health status.
        last_check: Timestamp of last health check.
        consecutive_failures: Number of consecutive health check failures.
        latency_ms: Average latency in milliseconds.
        active_connections: Current number of active connections.
        error_rate: Error rate over the last window.
    """

    endpoint_url: str
    status: EndpointStatus = EndpointStatus.UNKNOWN
    last_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consecutive_failures: int = 0
    latency_ms: float = 0.0
    active_connections: int = 0
    error_rate: float = 0.0


@dataclass
class TenantRoutingConfig:
    """
    Complete routing configuration for a tenant.

    Attributes:
        tenant_id: Unique tenant identifier.
        endpoints: List of endpoint configurations for this tenant.
        quotas: Quota limits for this tenant.
        load_balancing: Load balancing strategy to use.
        enable_fallback: Whether to use fallback endpoints on failure.
        fallback_endpoints: Fallback endpoints when primary endpoints fail.
        context_headers: Headers to inject with tenant context.
        isolation_level: Data isolation level for this tenant.
        allowed_operations: Set of allowed operation types.
        metadata: Additional tenant metadata.
    """

    tenant_id: str
    endpoints: list[EndpointConfig] = field(default_factory=list)
    quotas: TenantQuotas = field(default_factory=TenantQuotas)
    load_balancing: LoadBalancingStrategy = LoadBalancingStrategy.WEIGHTED_RANDOM
    enable_fallback: bool = True
    fallback_endpoints: list[EndpointConfig] = field(default_factory=list)
    context_headers: dict[str, str] = field(default_factory=dict)
    isolation_level: IsolationLevel = IsolationLevel.STRICT
    allowed_operations: set[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if not self.endpoints and not self.fallback_endpoints:
            raise ValueError("At least one endpoint or fallback endpoint is required")


@dataclass
class RoutingDecision:
    """
    Result of a routing decision.

    Attributes:
        target_endpoint: Selected endpoint URL for the request.
        tenant_context: Tenant context to propagate with the request.
        headers: Headers to include in the external request.
        used_fallback: Whether a fallback endpoint was selected.
        endpoint_config: Full configuration of the selected endpoint.
        routing_metadata: Additional routing metadata.
        decision_time_ms: Time taken to make the routing decision.
    """

    target_endpoint: str
    tenant_context: dict[str, str]
    headers: dict[str, str] = field(default_factory=dict)
    used_fallback: bool = False
    endpoint_config: EndpointConfig | None = None
    routing_metadata: dict[str, Any] = field(default_factory=dict)
    decision_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "target_endpoint": self.target_endpoint,
            "tenant_context": self.tenant_context,
            "headers": self.headers,
            "used_fallback": self.used_fallback,
            "routing_metadata": self.routing_metadata,
            "decision_time_ms": self.decision_time_ms,
        }


@dataclass
class RoutingAuditEntry:
    """
    Audit log entry for routing events.

    Attributes:
        timestamp: When the event occurred.
        tenant_id: Tenant involved in the event.
        event_type: Type of routing event.
        endpoint: Target endpoint (if applicable).
        duration_ms: Request duration in milliseconds.
        success: Whether the operation succeeded.
        error: Error message if operation failed.
        metadata: Additional event metadata.
    """

    timestamp: datetime
    tenant_id: str
    event_type: RoutingEventType
    endpoint: str | None = None
    duration_ms: float = 0.0
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Endpoint Health Tracker
# =============================================================================


class EndpointHealthTracker:
    """
    Tracks health status of endpoints with automatic recovery.
    """

    def __init__(
        self,
        unhealthy_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        """
        Initialize health tracker.

        Args:
            unhealthy_threshold: Consecutive failures before marking unhealthy.
            recovery_timeout: Seconds before unhealthy endpoint can be retried.
        """
        self._health: dict[str, EndpointHealth] = {}
        self._unhealthy_threshold = unhealthy_threshold
        self._recovery_timeout = recovery_timeout
        self._lock = asyncio.Lock()

    async def record_success(
        self,
        endpoint_url: str,
        latency_ms: float,
    ) -> None:
        """
        Record a successful request to an endpoint.

        Args:
            endpoint_url: URL of the endpoint.
            latency_ms: Request latency in milliseconds.
        """
        async with self._lock:
            health = self._health.get(endpoint_url)
            if health is None:
                health = EndpointHealth(endpoint_url=endpoint_url)
                self._health[endpoint_url] = health

            health.status = EndpointStatus.HEALTHY
            health.consecutive_failures = 0
            health.last_check = datetime.now(timezone.utc)
            # Exponential moving average for latency
            if health.latency_ms > 0:
                health.latency_ms = 0.7 * health.latency_ms + 0.3 * latency_ms
            else:
                health.latency_ms = latency_ms

    async def record_failure(self, endpoint_url: str, error: str = "") -> EndpointStatus:
        """
        Record a failed request to an endpoint.

        Args:
            endpoint_url: URL of the endpoint.
            error: Error message.

        Returns:
            New health status of the endpoint.
        """
        async with self._lock:
            health = self._health.get(endpoint_url)
            if health is None:
                health = EndpointHealth(endpoint_url=endpoint_url)
                self._health[endpoint_url] = health

            health.consecutive_failures += 1
            health.last_check = datetime.now(timezone.utc)

            if health.consecutive_failures >= self._unhealthy_threshold:
                health.status = EndpointStatus.UNHEALTHY
            elif health.consecutive_failures >= self._unhealthy_threshold // 2:
                health.status = EndpointStatus.DEGRADED
            else:
                health.status = EndpointStatus.HEALTHY

            logger.warning(
                "Endpoint %s failure #%s: %s", endpoint_url, health.consecutive_failures, error
            )

            return health.status

    async def is_available(self, endpoint_url: str) -> bool:
        """
        Check if an endpoint is available for routing.

        Args:
            endpoint_url: URL of the endpoint.

        Returns:
            True if endpoint is available, False otherwise.
        """
        async with self._lock:
            health = self._health.get(endpoint_url)
            if health is None:
                return True

            if health.status == EndpointStatus.UNHEALTHY:
                # Check if recovery timeout has passed
                elapsed = (datetime.now(timezone.utc) - health.last_check).total_seconds()
                if elapsed >= self._recovery_timeout:
                    # Allow retry
                    health.status = EndpointStatus.DEGRADED
                    return True
                return False

            return True

    async def get_health(self, endpoint_url: str) -> EndpointHealth:
        """
        Get health status of an endpoint.

        Args:
            endpoint_url: URL of the endpoint.

        Returns:
            EndpointHealth for the endpoint.
        """
        async with self._lock:
            health = self._health.get(endpoint_url)
            if health is None:
                return EndpointHealth(endpoint_url=endpoint_url)
            return health

    async def get_all_health(self) -> dict[str, EndpointHealth]:
        """
        Get health status of all tracked endpoints.

        Returns:
            Dictionary of endpoint URL to EndpointHealth.
        """
        async with self._lock:
            return dict(self._health)


# =============================================================================
# Tenant Router
# =============================================================================


class TenantRouter:
    """
    Multi-tenant router for enterprise gateway.

    Routes requests to tenant-specific external framework instances with
    complete data isolation, quota enforcement, and context propagation.

    Features:
    - Tenant-isolated routing with configurable endpoints
    - Per-tenant rate limiting and quota tracking
    - Load balancing across tenant instances
    - Fallback routing for high availability
    - Tenant context injection into external requests
    - Comprehensive audit logging for compliance

    Example:
        >>> router = TenantRouter(
        ...     configs=[
        ...         TenantRoutingConfig(
        ...             tenant_id="acme-corp",
        ...             endpoints=[
        ...                 EndpointConfig(url="https://acme.api.example.com"),
        ...             ],
        ...         ),
        ...     ]
        ... )
        >>> decision = await router.route("acme-corp", request_data)
        >>> print(decision.target_endpoint)
        "https://acme.api.example.com"
    """

    def __init__(
        self,
        configs: list[TenantRoutingConfig] | None = None,
        isolation_config: TenantIsolationConfig | None = None,
        enable_audit: bool = True,
        event_handlers: list[Callable[[RoutingAuditEntry], None]] | None = None,
    ) -> None:
        """
        Initialize the tenant router.

        Args:
            configs: List of tenant routing configurations.
            isolation_config: Configuration for tenant data isolation.
            enable_audit: Whether to enable audit logging.
            event_handlers: Event handlers for routing audit events.
        """
        self._configs: dict[str, TenantRoutingConfig] = {}
        self._isolation = TenantDataIsolation(isolation_config)
        self._enable_audit = enable_audit
        self._event_handlers = event_handlers or []

        # Initialize trackers
        self._quota_tracker = QuotaTracker()
        self._health_tracker = EndpointHealthTracker()
        self._context_builder = TenantContextBuilder()

        # Load balancing state
        self._round_robin_index: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

        # Audit log (bounded)
        self._audit_log: list[RoutingAuditEntry] = []
        self._max_audit_entries = 10000

        # Load initial configs
        if configs:
            for config in configs:
                self._configs[config.tenant_id] = config

        logger.info("TenantRouter initialized with %s tenant configs", len(self._configs))

    # =========================================================================
    # Configuration Management
    # =========================================================================

    async def add_tenant_config(self, config: TenantRoutingConfig) -> None:
        """
        Add or update a tenant configuration.

        Args:
            config: Tenant routing configuration.
        """
        async with self._lock:
            self._configs[config.tenant_id] = config
            logger.info("Added tenant config for %s", config.tenant_id)

    async def remove_tenant_config(self, tenant_id: str) -> bool:
        """
        Remove a tenant configuration.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            True if config was removed, False if not found.
        """
        async with self._lock:
            if tenant_id in self._configs:
                del self._configs[tenant_id]
                # Also reset quota tracking
                await self._quota_tracker.reset(tenant_id)
                logger.info("Removed tenant config for %s", tenant_id)
                return True
            return False

    async def get_tenant_config(self, tenant_id: str) -> TenantRoutingConfig | None:
        """
        Get configuration for a tenant.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            TenantRoutingConfig or None if not found.
        """
        return self._configs.get(tenant_id)

    async def list_tenant_configs(self) -> list[TenantRoutingConfig]:
        """
        List all tenant configurations.

        Returns:
            List of all tenant routing configurations.
        """
        return list(self._configs.values())

    # =========================================================================
    # Routing
    # =========================================================================

    async def route(
        self,
        tenant_id: str | None = None,
        request: dict[str, Any] | None = None,
        operation: str | None = None,
        bytes_size: int = 0,
    ) -> RoutingDecision:
        """
        Route a request to the appropriate tenant endpoint.

        Args:
            tenant_id: Tenant identifier (uses context if not provided).
            request: Request data for context.
            operation: Operation type for permission checking.
            bytes_size: Size of request in bytes for bandwidth limiting.

        Returns:
            RoutingDecision with target endpoint and context.

        Raises:
            TenantNotFoundError: If tenant configuration not found.
            NoAvailableEndpointError: If no healthy endpoints available.
            QuotaExceededError: If tenant quota is exceeded.
            CrossTenantAccessError: If cross-tenant access attempted.
        """
        start_time = time.time()

        # Resolve tenant ID
        resolved_tenant_id = tenant_id or get_current_tenant_id()
        if resolved_tenant_id is None:
            raise TenantNotSetError("No tenant context for routing")

        # Verify tenant isolation
        context_tenant = get_current_tenant_id()
        if context_tenant and context_tenant != resolved_tenant_id:
            await self._log_audit(
                RoutingAuditEntry(
                    timestamp=datetime.now(timezone.utc),
                    tenant_id=resolved_tenant_id,
                    event_type=RoutingEventType.CROSS_TENANT_BLOCKED,
                    success=False,
                    error=f"Cross-tenant access: {context_tenant} -> {resolved_tenant_id}",
                    metadata={"requesting_tenant": context_tenant},
                )
            )
            raise CrossTenantAccessError(context_tenant, resolved_tenant_id)

        # Get tenant config
        config = self._configs.get(resolved_tenant_id)
        if config is None:
            raise TenantNotFoundError(resolved_tenant_id)

        # Check allowed operations
        if operation and config.allowed_operations is not None:
            if operation not in config.allowed_operations:
                raise TenantRoutingError(
                    f"Operation '{operation}' not allowed for tenant {resolved_tenant_id}",
                    tenant_id=resolved_tenant_id,
                    code="OPERATION_NOT_ALLOWED",
                    details={"operation": operation},
                )

        # Check quotas
        allowed, exceeded_status = await self._quota_tracker.check_and_consume(
            resolved_tenant_id,
            config.quotas,
            bytes_size,
        )

        if not allowed and exceeded_status:
            await self._log_audit(
                RoutingAuditEntry(
                    timestamp=datetime.now(timezone.utc),
                    tenant_id=resolved_tenant_id,
                    event_type=RoutingEventType.QUOTA_EXCEEDED,
                    success=False,
                    error=f"Quota exceeded: {exceeded_status.quota_type}",
                    metadata=exceeded_status.to_dict(),
                )
            )
            retry_after = max(
                1, int((exceeded_status.reset_time - datetime.now(timezone.utc)).total_seconds())
            )
            raise QuotaExceededError(
                tenant_id=resolved_tenant_id,
                quota_type=exceeded_status.quota_type,
                limit=exceeded_status.limit,
                current=exceeded_status.used,
                retry_after=retry_after,
            )

        # Select endpoint
        try:
            endpoint, used_fallback = await self._select_endpoint(
                resolved_tenant_id,
                config,
            )
        except NoAvailableEndpointError:
            # Release the consumed quota slot on failure
            await self._quota_tracker.release_concurrent(resolved_tenant_id)
            raise

        # Build tenant context
        tenant_context = self._context_builder.build_context(
            resolved_tenant_id,
            config.isolation_level,
            config.context_headers,
            request,
        )

        # Build headers
        headers = self._context_builder.build_headers(
            resolved_tenant_id,
            config.context_headers,
            endpoint.headers,
        )

        decision_time_ms = (time.time() - start_time) * 1000

        decision = RoutingDecision(
            target_endpoint=endpoint.url,
            tenant_context=tenant_context,
            headers=headers,
            used_fallback=used_fallback,
            endpoint_config=endpoint,
            routing_metadata={
                "load_balancing": config.load_balancing.value,
                "isolation_level": config.isolation_level.value,
            },
            decision_time_ms=decision_time_ms,
        )

        # Log successful routing
        event_type = (
            RoutingEventType.ROUTE_FALLBACK if used_fallback else RoutingEventType.ROUTE_SUCCESS
        )
        await self._log_audit(
            RoutingAuditEntry(
                timestamp=datetime.now(timezone.utc),
                tenant_id=resolved_tenant_id,
                event_type=event_type,
                endpoint=endpoint.url,
                duration_ms=decision_time_ms,
                success=True,
                metadata={"used_fallback": used_fallback},
            )
        )

        logger.debug(
            "Routed tenant %s to %s (fallback=%s, time=%.2fms)",
            resolved_tenant_id,
            endpoint.url,
            used_fallback,
            decision_time_ms,
        )

        return decision

    async def complete_request(
        self,
        tenant_id: str,
        endpoint_url: str,
        success: bool,
        latency_ms: float,
        error: str | None = None,
    ) -> None:
        """
        Mark a request as complete and update tracking.

        Call this after the external request completes to update
        health tracking and release concurrent request slots.

        Args:
            tenant_id: Tenant identifier.
            endpoint_url: URL of the endpoint used.
            success: Whether the request succeeded.
            latency_ms: Request latency in milliseconds.
            error: Error message if request failed.
        """
        # Release concurrent slot
        await self._quota_tracker.release_concurrent(tenant_id)

        # Update health tracking
        if success:
            await self._health_tracker.record_success(endpoint_url, latency_ms)
        else:
            status = await self._health_tracker.record_failure(
                endpoint_url, error or "Unknown error"
            )
            if status == EndpointStatus.UNHEALTHY:
                await self._log_audit(
                    RoutingAuditEntry(
                        timestamp=datetime.now(timezone.utc),
                        tenant_id=tenant_id,
                        event_type=RoutingEventType.ENDPOINT_HEALTH_CHANGE,
                        endpoint=endpoint_url,
                        success=False,
                        error=f"Endpoint marked unhealthy: {error}",
                    )
                )

    async def _select_endpoint(
        self,
        tenant_id: str,
        config: TenantRoutingConfig,
    ) -> tuple[EndpointConfig, bool]:
        """
        Select an endpoint based on load balancing strategy.

        Args:
            tenant_id: Tenant identifier.
            config: Tenant routing configuration.

        Returns:
            Tuple of (selected endpoint, used_fallback).

        Raises:
            NoAvailableEndpointError: If no healthy endpoints available.
        """
        # Get available primary endpoints
        available_primary = []
        for endpoint in config.endpoints:
            if await self._health_tracker.is_available(endpoint.url):
                available_primary.append(endpoint)

        if available_primary:
            endpoint = await self._apply_load_balancing(
                tenant_id,
                available_primary,
                config.load_balancing,
            )
            return endpoint, False

        # Try fallback endpoints if enabled
        if config.enable_fallback:
            available_fallback = []
            for endpoint in config.fallback_endpoints:
                if await self._health_tracker.is_available(endpoint.url):
                    available_fallback.append(endpoint)

            if available_fallback:
                endpoint = await self._apply_load_balancing(
                    tenant_id,
                    available_fallback,
                    config.load_balancing,
                )
                logger.warning("Using fallback endpoint for tenant %s: %s", tenant_id, endpoint.url)
                return endpoint, True

        raise NoAvailableEndpointError(
            tenant_id,
            details={
                "primary_endpoints": len(config.endpoints),
                "fallback_endpoints": len(config.fallback_endpoints),
            },
        )

    async def _apply_load_balancing(
        self,
        tenant_id: str,
        endpoints: list[EndpointConfig],
        strategy: LoadBalancingStrategy,
    ) -> EndpointConfig:
        """
        Apply load balancing strategy to select an endpoint.

        Args:
            tenant_id: Tenant identifier.
            endpoints: Available endpoints.
            strategy: Load balancing strategy.

        Returns:
            Selected endpoint.
        """
        if len(endpoints) == 1:
            return endpoints[0]

        if strategy == LoadBalancingStrategy.ROUND_ROBIN:
            async with self._lock:
                index = self._round_robin_index[tenant_id]
                self._round_robin_index[tenant_id] = (index + 1) % len(endpoints)
            return endpoints[index % len(endpoints)]

        elif strategy == LoadBalancingStrategy.WEIGHTED_RANDOM:
            total_weight = sum(e.weight for e in endpoints)
            if total_weight == 0:
                return random.choice(endpoints)  # noqa: S311 -- load balancing
            r = random.randint(1, total_weight)  # noqa: S311 -- load balancing
            cumulative = 0
            for endpoint in endpoints:
                cumulative += endpoint.weight
                if r <= cumulative:
                    return endpoint
            return endpoints[-1]

        elif strategy == LoadBalancingStrategy.PRIORITY:
            sorted_endpoints = sorted(endpoints, key=lambda e: e.priority)
            return sorted_endpoints[0]

        elif strategy == LoadBalancingStrategy.LATENCY:
            best_endpoint = endpoints[0]
            best_latency = float("inf")
            for endpoint in endpoints:
                health = await self._health_tracker.get_health(endpoint.url)
                if health.latency_ms < best_latency:
                    best_latency = health.latency_ms
                    best_endpoint = endpoint
            return best_endpoint

        elif strategy == LoadBalancingStrategy.LEAST_CONNECTIONS:
            # For least connections, we'd need to track active connections per endpoint
            # For now, fall back to weighted random
            return await self._apply_load_balancing(
                tenant_id,
                endpoints,
                LoadBalancingStrategy.WEIGHTED_RANDOM,
            )

        return endpoints[0]

    # =========================================================================
    # Quota Management
    # =========================================================================

    async def get_quota_status(
        self,
        tenant_id: str | None = None,
    ) -> dict[str, QuotaStatus]:
        """
        Get current quota status for a tenant.

        Args:
            tenant_id: Tenant identifier (uses context if not provided).

        Returns:
            Dictionary of quota type to QuotaStatus.

        Raises:
            TenantNotFoundError: If tenant configuration not found.
        """
        resolved_tenant_id = tenant_id or get_current_tenant_id()
        if resolved_tenant_id is None:
            raise TenantNotSetError("No tenant context for quota status")

        config = self._configs.get(resolved_tenant_id)
        if config is None:
            raise TenantNotFoundError(resolved_tenant_id)

        return await self._quota_tracker.get_status(resolved_tenant_id, config.quotas)

    async def reset_quota(self, tenant_id: str) -> None:
        """
        Reset quota usage for a tenant.

        Args:
            tenant_id: Tenant identifier.
        """
        await self._quota_tracker.reset(tenant_id)
        logger.info("Reset quota for tenant %s", tenant_id)

    # =========================================================================
    # Health Monitoring
    # =========================================================================

    async def get_endpoint_health(self, endpoint_url: str) -> EndpointHealth:
        """
        Get health status of an endpoint.

        Args:
            endpoint_url: URL of the endpoint.

        Returns:
            EndpointHealth for the endpoint.
        """
        return await self._health_tracker.get_health(endpoint_url)

    async def get_all_endpoint_health(self) -> dict[str, EndpointHealth]:
        """
        Get health status of all tracked endpoints.

        Returns:
            Dictionary of endpoint URL to EndpointHealth.
        """
        return await self._health_tracker.get_all_health()

    async def get_tenant_health(self, tenant_id: str) -> dict[str, Any]:
        """
        Get overall health status for a tenant's endpoints.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Dictionary with health summary.

        Raises:
            TenantNotFoundError: If tenant configuration not found.
        """
        config = self._configs.get(tenant_id)
        if config is None:
            raise TenantNotFoundError(tenant_id)

        all_health = await self._health_tracker.get_all_health()

        primary_health = []
        for endpoint in config.endpoints:
            health = all_health.get(endpoint.url, EndpointHealth(endpoint_url=endpoint.url))
            primary_health.append(
                {
                    "url": endpoint.url,
                    "status": health.status.value,
                    "latency_ms": health.latency_ms,
                    "consecutive_failures": health.consecutive_failures,
                }
            )

        fallback_health = []
        for endpoint in config.fallback_endpoints:
            health = all_health.get(endpoint.url, EndpointHealth(endpoint_url=endpoint.url))
            fallback_health.append(
                {
                    "url": endpoint.url,
                    "status": health.status.value,
                    "latency_ms": health.latency_ms,
                    "consecutive_failures": health.consecutive_failures,
                }
            )

        healthy_count = sum(
            1
            for h in primary_health + fallback_health
            if h["status"] in (EndpointStatus.HEALTHY.value, EndpointStatus.UNKNOWN.value)
        )
        total_count = len(primary_health) + len(fallback_health)

        return {
            "tenant_id": tenant_id,
            "overall_status": "healthy" if healthy_count > 0 else "unhealthy",
            "healthy_endpoints": healthy_count,
            "total_endpoints": total_count,
            "primary_endpoints": primary_health,
            "fallback_endpoints": fallback_health,
        }

    # =========================================================================
    # Audit Logging
    # =========================================================================

    async def _log_audit(self, entry: RoutingAuditEntry) -> None:
        """
        Log a routing audit entry.

        Args:
            entry: Audit entry to log.
        """
        if not self._enable_audit:
            return

        self._audit_log.append(entry)

        # Keep audit log bounded
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries :]

        # Call event handlers
        for handler in self._event_handlers:
            try:
                handler(entry)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided event handler callback
                logger.error("Audit event handler failed: %s", e)

        # Log to standard logger
        log_msg = (
            f"[TenantRouter] {entry.event_type.value} tenant={entry.tenant_id} "
            f"endpoint={entry.endpoint} success={entry.success}"
        )
        if entry.error:
            log_msg += f" error={entry.error}"
        logger.debug(log_msg)

    async def get_audit_log(
        self,
        tenant_id: str | None = None,
        event_type: RoutingEventType | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get routing audit log entries.

        Args:
            tenant_id: Filter by tenant ID.
            event_type: Filter by event type.
            since: Filter entries after this timestamp.
            limit: Maximum entries to return.

        Returns:
            List of audit entries as dictionaries.
        """
        entries = self._audit_log

        if tenant_id:
            entries = [e for e in entries if e.tenant_id == tenant_id]
        if event_type:
            entries = [e for e in entries if e.event_type == event_type]
        if since:
            entries = [e for e in entries if e.timestamp >= since]

        # Return most recent entries
        entries = entries[-limit:]

        return [
            {
                "timestamp": e.timestamp.isoformat(),
                "tenant_id": e.tenant_id,
                "event_type": e.event_type.value,
                "endpoint": e.endpoint,
                "duration_ms": e.duration_ms,
                "success": e.success,
                "error": e.error,
                **e.metadata,
            }
            for e in entries
        ]

    def add_event_handler(
        self,
        handler: Callable[[RoutingAuditEntry], None],
    ) -> None:
        """
        Add an event handler for routing audit events.

        Args:
            handler: Callback function receiving RoutingAuditEntry.
        """
        self._event_handlers.append(handler)

    def remove_event_handler(
        self,
        handler: Callable[[RoutingAuditEntry], None],
    ) -> None:
        """
        Remove an event handler.

        Args:
            handler: Handler to remove.
        """
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> dict[str, Any]:
        """
        Get router statistics.

        Returns:
            Dictionary of router statistics.
        """
        all_health = await self._health_tracker.get_all_health()
        healthy_endpoints = sum(
            1
            for h in all_health.values()
            if h.status in (EndpointStatus.HEALTHY, EndpointStatus.UNKNOWN)
        )

        return {
            "tenant_count": len(self._configs),
            "total_endpoints": sum(
                len(c.endpoints) + len(c.fallback_endpoints) for c in self._configs.values()
            ),
            "healthy_endpoints": healthy_endpoints,
            "unhealthy_endpoints": len(all_health) - healthy_endpoints,
            "audit_entries": len(self._audit_log),
            "audit_enabled": self._enable_audit,
        }


# =============================================================================
# Alias for backwards compatibility
# =============================================================================

# TenantRoutingContext is an alias for TenantRoutingContextManager
TenantRoutingContext = TenantRoutingContextManager


__all__ = [
    # Exceptions
    "TenantRoutingError",
    "TenantNotFoundError",
    "NoAvailableEndpointError",
    "QuotaExceededError",
    # Enums
    "LoadBalancingStrategy",
    "EndpointStatus",
    "RoutingEventType",
    # Data classes
    "EndpointConfig",
    "EndpointHealth",
    "TenantRoutingConfig",
    "RoutingDecision",
    "RoutingAuditEntry",
    # Core classes
    "EndpointHealthTracker",
    "TenantRouter",
    "TenantRoutingContext",
]
