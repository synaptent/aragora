"""
Federation Registry - External agent framework registration and discovery.

Provides service discovery and lifecycle management for external AI agent
frameworks (OpenClaw, AutoGPT, CrewAI, LangGraph, etc.) that integrate with
Aragora's gateway.

Key features:
- Register external frameworks with capabilities and endpoints
- Health checking and liveness tracking for registered frameworks
- Capability-based routing support
- API version negotiation
- Automatic cleanup of dead frameworks

Usage:
    from aragora.gateway.federation import FederationRegistry

    registry = FederationRegistry()
    await registry.connect()

    # Register an external framework
    result = await registry.register(
        name="autogpt",
        version="0.5.0",
        capabilities=[
            FrameworkCapability(
                name="autonomous_task",
                description="Execute autonomous multi-step tasks",
                parameters={"task": "str", "max_steps": "int"},
                returns="TaskResult",
            ),
        ],
        endpoints={"base": "http://localhost:8090", "health": "/health"},
    )

    # Find frameworks by capability
    frameworks = await registry.find_by_capability("autonomous_task")

    # Health check
    status = await registry.health_check("autogpt")

    await registry.close()
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from collections.abc import Callable, Sequence

from aragora.resilience.health import HealthStatus

logger = logging.getLogger(__name__)


class FrameworkStatus(Enum):
    """Framework lifecycle status."""

    REGISTERING = "registering"
    ACTIVE = "active"
    DRAINING = "draining"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


@dataclass
class FrameworkCapability:
    """
    A capability provided by an external framework.

    Capabilities describe what operations a framework can perform,
    including parameter schemas and return types for routing decisions.

    Attributes:
        name: Unique capability identifier (e.g., "autonomous_task", "code_generation").
        description: Human-readable description of the capability.
        parameters: Dict mapping parameter names to type descriptions.
        returns: Description of the return type.
        version: Optional capability version for compatibility checking.
        metadata: Additional capability metadata.
    """

    name: str
    description: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    returns: str = "Any"
    version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize capability to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
            "version": self.version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FrameworkCapability:
        """Deserialize capability from dictionary."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
            returns=data.get("returns", "Any"),
            version=data.get("version", "1.0.0"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ExternalFramework:
    """
    Information about a registered external agent framework.

    Represents an external AI agent system (AutoGPT, CrewAI, LangGraph, etc.)
    that has registered with the Aragora federation gateway.

    Attributes:
        framework_id: Unique identifier assigned on registration.
        name: Framework name (e.g., "autogpt", "crewai", "langgraph").
        version: Framework version string.
        capabilities: Set of capabilities this framework provides.
        endpoints: Dict of endpoint URLs (base, health, invoke, etc.).
        health_status: Current health status from health checks.
        status: Lifecycle status (registering, active, draining, etc.).
        api_version: Negotiated API version for communication.
        supported_api_versions: List of API versions the framework supports.
        registered_at: Unix timestamp of registration.
        last_heartbeat: Unix timestamp of last successful heartbeat.
        last_health_check: Unix timestamp of last health check.
        consecutive_failures: Count of consecutive health check failures.
        metadata: Additional framework metadata (provider, description, etc.).
        tags: Optional tags for filtering and grouping.
        startup_hooks: Registered startup callback IDs.
        shutdown_hooks: Registered shutdown callback IDs.
    """

    framework_id: str = ""
    name: str = ""
    version: str = "0.0.0"
    capabilities: list[FrameworkCapability] = field(default_factory=list)
    endpoints: dict[str, str] = field(default_factory=dict)
    health_status: HealthStatus = HealthStatus.UNKNOWN
    status: FrameworkStatus = FrameworkStatus.REGISTERING
    api_version: str = "1.0.0"
    supported_api_versions: list[str] = field(default_factory=lambda: ["1.0.0"])
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    last_health_check: float = 0.0
    consecutive_failures: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: set[str] = field(default_factory=set)
    startup_hooks: list[str] = field(default_factory=list)
    shutdown_hooks: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Generate framework_id if not provided."""
        if not self.framework_id and self.name:
            unique_suffix = hashlib.sha256(
                f"{self.name}-{self.version}-{time.time()}".encode()
            ).hexdigest()[:12]
            self.framework_id = f"fw-{self.name}-{unique_suffix}"

    def is_healthy(self) -> bool:
        """Check if framework is in a healthy state."""
        return self.health_status == HealthStatus.HEALTHY

    def is_active(self) -> bool:
        """Check if framework is active and accepting requests."""
        return self.status == FrameworkStatus.ACTIVE and self.is_healthy()

    def is_alive(self, timeout_seconds: float = 60.0) -> bool:
        """Check if framework has sent a heartbeat within timeout."""
        return (time.time() - self.last_heartbeat) < timeout_seconds

    def has_capability(self, capability_name: str) -> bool:
        """Check if framework has a specific capability."""
        return any(cap.name == capability_name for cap in self.capabilities)

    def get_capability(self, capability_name: str) -> FrameworkCapability | None:
        """Get a capability by name."""
        for cap in self.capabilities:
            if cap.name == capability_name:
                return cap
        return None

    def has_all_capabilities(self, capability_names: Sequence[str]) -> bool:
        """Check if framework has all specified capabilities."""
        return all(self.has_capability(name) for name in capability_names)

    def supports_api_version(self, version: str) -> bool:
        """Check if framework supports a specific API version."""
        return version in self.supported_api_versions

    def get_endpoint(self, endpoint_type: str) -> str | None:
        """Get endpoint URL by type (base, health, invoke, etc.)."""
        return self.endpoints.get(endpoint_type)

    def record_health_check(self, healthy: bool) -> None:
        """Record result of a health check."""
        self.last_health_check = time.time()
        if healthy:
            self.consecutive_failures = 0
            self.health_status = HealthStatus.HEALTHY
        else:
            self.consecutive_failures += 1
            if self.consecutive_failures >= 3:
                self.health_status = HealthStatus.UNHEALTHY
            else:
                self.health_status = HealthStatus.DEGRADED

    def to_dict(self) -> dict[str, Any]:
        """Serialize framework to dictionary."""
        return {
            "framework_id": self.framework_id,
            "name": self.name,
            "version": self.version,
            "capabilities": [cap.to_dict() for cap in self.capabilities],
            "endpoints": self.endpoints,
            "health_status": self.health_status.value,
            "status": self.status.value,
            "api_version": self.api_version,
            "supported_api_versions": self.supported_api_versions,
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
            "last_health_check": self.last_health_check,
            "consecutive_failures": self.consecutive_failures,
            "metadata": self.metadata,
            "tags": list(self.tags),
            "startup_hooks": self.startup_hooks,
            "shutdown_hooks": self.shutdown_hooks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalFramework:
        """Deserialize framework from dictionary."""
        return cls(
            framework_id=data.get("framework_id", ""),
            name=data.get("name", ""),
            version=data.get("version", "0.0.0"),
            capabilities=[
                FrameworkCapability.from_dict(cap) for cap in data.get("capabilities", [])
            ],
            endpoints=data.get("endpoints", {}),
            health_status=HealthStatus(data.get("health_status", "unknown")),
            status=FrameworkStatus(data.get("status", "registering")),
            api_version=data.get("api_version", "1.0.0"),
            supported_api_versions=data.get("supported_api_versions", ["1.0.0"]),
            registered_at=data.get("registered_at", time.time()),
            last_heartbeat=data.get("last_heartbeat", time.time()),
            last_health_check=data.get("last_health_check", 0.0),
            consecutive_failures=data.get("consecutive_failures", 0),
            metadata=data.get("metadata", {}),
            tags=set(data.get("tags", [])),
            startup_hooks=data.get("startup_hooks", []),
            shutdown_hooks=data.get("shutdown_hooks", []),
        )


@dataclass
class RegistrationResult:
    """
    Result of registering an external framework.

    Attributes:
        success: Whether registration succeeded.
        framework_id: Assigned framework ID (if successful).
        negotiated_version: API version negotiated for communication.
        message: Human-readable status message.
        framework: The registered ExternalFramework object (if successful).
    """

    success: bool
    framework_id: str = ""
    negotiated_version: str = ""
    message: str = ""
    framework: ExternalFramework | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to dictionary."""
        return {
            "success": self.success,
            "framework_id": self.framework_id,
            "negotiated_version": self.negotiated_version,
            "message": self.message,
        }


# Type alias for lifecycle hooks
LifecycleHook = Callable[[ExternalFramework], Any]


class FederationRegistry:
    """
    Registry for external agent framework discovery and management.

    The FederationRegistry maintains a directory of external AI agent frameworks
    (OpenClaw, AutoGPT, CrewAI, LangGraph, etc.) that have registered with
    Aragora's gateway. It provides:

    - Framework registration with capability discovery
    - Health checking and liveness tracking
    - Capability-based framework selection
    - API version negotiation
    - Lifecycle management (startup/shutdown hooks)
    - Automatic cleanup of dead frameworks

    Features:
    - In-memory storage with optional Redis persistence
    - Configurable health check intervals and timeouts
    - Circuit breaker integration for resilience
    - Event callbacks for framework state changes

    Usage:
        registry = FederationRegistry()
        await registry.connect()

        # Register a framework
        result = await registry.register(
            name="autogpt",
            version="0.5.0",
            capabilities=[...],
            endpoints={"base": "http://localhost:8090"},
        )

        # Find by capability
        frameworks = await registry.find_by_capability("code_generation")

        # Select best framework
        fw = await registry.select_framework(["code_generation", "debugging"])

        await registry.close()
    """

    # Supported API versions for version negotiation
    SUPPORTED_API_VERSIONS = ["1.0.0", "1.1.0", "2.0.0"]

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "aragora:federation:frameworks:",
        heartbeat_timeout: float = 60.0,
        health_check_interval: float = 30.0,
        cleanup_interval: float = 120.0,
        max_consecutive_failures: int = 5,
    ) -> None:
        """
        Initialize the federation registry.

        Args:
            redis_url: Redis connection URL for persistence.
            key_prefix: Prefix for Redis keys.
            heartbeat_timeout: Seconds before framework is considered disconnected.
            health_check_interval: Seconds between health checks.
            cleanup_interval: Seconds between cleanup sweeps for dead frameworks.
            max_consecutive_failures: Failures before marking framework as failed.
        """
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._heartbeat_timeout = heartbeat_timeout
        self._health_check_interval = health_check_interval
        self._cleanup_interval = cleanup_interval
        self._max_consecutive_failures = max_consecutive_failures

        # Storage
        self._redis: Any | None = None
        self._local_cache: dict[str, ExternalFramework] = {}

        # Background tasks
        self._health_check_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None

        # Capability index for fast lookups
        self._capability_index: dict[str, set[str]] = {}  # capability -> framework_ids

        # Lifecycle hooks
        self._startup_hooks: dict[str, LifecycleHook] = {}
        self._shutdown_hooks: dict[str, LifecycleHook] = {}
        self._reconnect_hooks: dict[str, LifecycleHook] = {}

        # Event callback for state changes
        self._event_callback: Callable[[str, dict[str, Any]], None] | None = None

        # HTTP client for health checks
        self._http_client: Any | None = None

    async def connect(self) -> None:
        """Connect to Redis (if available) and start background tasks."""
        # Check for explicit in-memory mode
        if self._redis_url.startswith("memory://"):
            logger.info("FederationRegistry using in-memory mode")
            self._redis = None
        else:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await self._redis.ping()
                logger.info("FederationRegistry connected to Redis: %s", self._redis_url)
            except ImportError:
                logger.warning("redis package not installed, using in-memory fallback")
                self._redis = None
            except (OSError, ConnectionError, TimeoutError) as e:
                logger.warning("Redis not available, using in-memory fallback: %s", e)
                self._redis = None

        # Start background tasks
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def close(self) -> None:
        """Close connections and stop background tasks."""
        # Cancel background tasks
        for task in [self._health_check_task, self._cleanup_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close HTTP client session to prevent connection leaks
        if self._http_client:
            await self._http_client.close()
            self._http_client = None

        # Run shutdown hooks for all active frameworks
        for framework in list(self._local_cache.values()):
            await self._run_shutdown_hooks(framework)

        # Close HTTP client
        if self._http_client:
            await self._http_client.close()

        # Close Redis
        if self._redis:
            await self._redis.close()
            logger.info("FederationRegistry disconnected from Redis")

    def set_event_callback(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """Set callback for framework state change events."""
        self._event_callback = callback

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a state change event."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided event callback
                logger.warning("Failed to emit event %s: %s", event_type, e)

    async def register(
        self,
        name: str,
        version: str,
        capabilities: list[FrameworkCapability],
        endpoints: dict[str, str],
        supported_api_versions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> RegistrationResult:
        """
        Register an external agent framework.

        Registers a new framework or updates an existing registration.
        Performs API version negotiation and initial health check.

        Args:
            name: Framework name (e.g., "autogpt", "crewai").
            version: Framework version string.
            capabilities: List of capabilities the framework provides.
            endpoints: Dict of endpoint URLs (must include "base").
            supported_api_versions: API versions the framework supports.
            metadata: Additional framework metadata.
            tags: Optional tags for filtering.

        Returns:
            RegistrationResult with success status and framework ID.

        Raises:
            ValueError: If required endpoints are missing.
        """
        if "base" not in endpoints:
            return RegistrationResult(
                success=False,
                message="Missing required 'base' endpoint",
            )

        # Negotiate API version
        client_versions = supported_api_versions or ["1.0.0"]
        negotiated_version = self._negotiate_version(client_versions)
        if not negotiated_version:
            return RegistrationResult(
                success=False,
                message=f"No compatible API version. Client supports: {client_versions}, "
                f"server supports: {self.SUPPORTED_API_VERSIONS}",
            )

        # Check for existing registration by name
        existing = await self._find_by_name(name)
        framework_id = existing.framework_id if existing else ""

        # Create framework object
        now = time.time()
        framework = ExternalFramework(
            framework_id=framework_id,
            name=name,
            version=version,
            capabilities=capabilities,
            endpoints=endpoints,
            api_version=negotiated_version,
            supported_api_versions=client_versions,
            metadata=metadata or {},
            tags=set(tags or []),
            registered_at=existing.registered_at if existing else now,
            last_heartbeat=now,
            status=FrameworkStatus.ACTIVE,
            health_status=HealthStatus.UNKNOWN,
        )

        # Ensure framework_id is set
        if not framework.framework_id:
            framework.__post_init__()

        # Save and index
        await self._save_framework(framework)
        self._index_capabilities(framework)

        # Run startup hooks
        await self._run_startup_hooks(framework)

        # Emit registration event
        self._emit_event(
            "framework_registered",
            {
                "framework_id": framework.framework_id,
                "name": name,
                "version": version,
                "capabilities": [cap.name for cap in capabilities],
            },
        )

        logger.info(
            "Framework registered: %s (name=%s, version=%s, api=%s, capabilities=%s)",
            framework.framework_id,
            name,
            version,
            negotiated_version,
            [c.name for c in capabilities],
        )

        return RegistrationResult(
            success=True,
            framework_id=framework.framework_id,
            negotiated_version=negotiated_version,
            message="Registration successful",
            framework=framework,
        )

    async def unregister(self, framework_id: str) -> bool:
        """
        Unregister a framework from the registry.

        Runs shutdown hooks before removing the framework.

        Args:
            framework_id: ID of the framework to unregister.

        Returns:
            True if framework was unregistered, False if not found.
        """
        framework = await self.get(framework_id)
        if not framework:
            return False

        # Run shutdown hooks
        await self._run_shutdown_hooks(framework)

        # Remove from capability index
        self._unindex_capabilities(framework)

        # Remove from storage
        key = f"{self._key_prefix}{framework_id}"
        if self._redis:
            await self._redis.delete(key)
        self._local_cache.pop(framework_id, None)

        # Emit event
        self._emit_event(
            "framework_unregistered",
            {"framework_id": framework_id, "name": framework.name},
        )

        logger.info("Framework unregistered: %s", framework_id)
        return True

    async def get(self, framework_id: str) -> ExternalFramework | None:
        """
        Get framework by ID.

        Args:
            framework_id: Framework to look up.

        Returns:
            ExternalFramework if found, None otherwise.
        """
        # Check local cache first
        if framework_id in self._local_cache:
            return self._local_cache[framework_id]

        # Try Redis
        if self._redis:
            key = f"{self._key_prefix}{framework_id}"
            data = await self._redis.get(key)
            if data:
                framework = ExternalFramework.from_dict(json.loads(data))
                self._local_cache[framework_id] = framework
                return framework

        return None

    async def _find_by_name(self, name: str) -> ExternalFramework | None:
        """Find a framework by name."""
        for framework in await self.list_all():
            if framework.name == name:
                return framework
        return None

    async def list_all(self, include_inactive: bool = False) -> list[ExternalFramework]:
        """
        List all registered frameworks.

        Args:
            include_inactive: Whether to include disconnected/failed frameworks.

        Returns:
            List of ExternalFramework objects.
        """
        frameworks = []

        if self._redis:
            pattern = f"{self._key_prefix}*"
            async for key in self._redis.scan_iter(match=pattern):
                data = await self._redis.get(key)
                if data:
                    framework = ExternalFramework.from_dict(json.loads(data))
                    if include_inactive or framework.is_active():
                        frameworks.append(framework)
                    # Update local cache
                    self._local_cache[framework.framework_id] = framework
        else:
            for framework in self._local_cache.values():
                if include_inactive or framework.is_active():
                    frameworks.append(framework)

        return frameworks

    async def heartbeat(
        self,
        framework_id: str,
        status: FrameworkStatus | None = None,
    ) -> bool:
        """
        Update framework heartbeat timestamp.

        Args:
            framework_id: Framework sending heartbeat.
            status: Optional status update.

        Returns:
            True if heartbeat recorded, False if framework not found.
        """
        framework = await self.get(framework_id)
        if not framework:
            return False

        framework.last_heartbeat = time.time()
        if status:
            old_status = framework.status
            framework.status = status
            if old_status != status:
                self._emit_event(
                    "framework_status_changed",
                    {
                        "framework_id": framework_id,
                        "old_status": old_status.value,
                        "new_status": status.value,
                    },
                )

        await self._save_framework(framework)
        return True

    async def health_check(self, framework_id: str) -> HealthStatus:
        """
        Perform health check on a framework.

        Calls the framework's health endpoint and updates status.

        Args:
            framework_id: Framework to health check.

        Returns:
            Current health status after check.
        """
        framework = await self.get(framework_id)
        if not framework:
            return HealthStatus.UNKNOWN

        health_endpoint = framework.get_endpoint("health")
        if not health_endpoint:
            # Construct from base if not provided
            base = framework.get_endpoint("base")
            if base:
                health_endpoint = f"{base.rstrip('/')}/health"
            else:
                framework.record_health_check(False)
                await self._save_framework(framework)
                return framework.health_status

        # Perform HTTP health check
        try:
            healthy = await self._check_health_endpoint(health_endpoint)
            framework.record_health_check(healthy)
        except (OSError, ConnectionError, TimeoutError) as e:
            logger.warning("Health check failed for %s: %s", framework_id, e)
            framework.record_health_check(False)

        await self._save_framework(framework)

        # Check if we should mark as failed
        if framework.consecutive_failures >= self._max_consecutive_failures:
            framework.status = FrameworkStatus.FAILED
            await self._save_framework(framework)
            self._emit_event(
                "framework_failed",
                {"framework_id": framework_id, "failures": framework.consecutive_failures},
            )

        return framework.health_status

    async def _check_health_endpoint(self, url: str) -> bool:
        """Check if a health endpoint is responding."""
        try:
            import aiohttp

            if not self._http_client:
                self._http_client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

            async with self._http_client.get(url) as response:
                return response.status == 200
        except ImportError:
            # aiohttp not available, assume healthy
            logger.debug("aiohttp not available, skipping HTTP health check")
            return True
        except (OSError, ConnectionError, TimeoutError) as e:
            logger.debug("Health check request failed: %s", e)
            return False

    async def find_by_capability(
        self,
        capability_name: str,
        only_active: bool = True,
    ) -> list[ExternalFramework]:
        """
        Find frameworks with a specific capability.

        Args:
            capability_name: Required capability name.
            only_active: Only return active, healthy frameworks.

        Returns:
            List of matching frameworks.
        """
        # Use capability index for fast lookup
        framework_ids = self._capability_index.get(capability_name, set())

        frameworks = []
        for framework_id in framework_ids:
            framework = await self.get(framework_id)
            if framework and (not only_active or framework.is_active()):
                frameworks.append(framework)

        return frameworks

    async def find_by_capabilities(
        self,
        capability_names: Sequence[str],
        only_active: bool = True,
    ) -> list[ExternalFramework]:
        """
        Find frameworks with all specified capabilities.

        Args:
            capability_names: Required capability names.
            only_active: Only return active, healthy frameworks.

        Returns:
            List of matching frameworks.
        """
        if not capability_names:
            return await self.list_all(include_inactive=not only_active)

        # Start with frameworks having the first capability
        framework_ids = self._capability_index.get(capability_names[0], set()).copy()

        # Intersect with frameworks having remaining capabilities
        for cap_name in capability_names[1:]:
            framework_ids &= self._capability_index.get(cap_name, set())

        frameworks = []
        for framework_id in framework_ids:
            framework = await self.get(framework_id)
            if framework and (not only_active or framework.is_active()):
                # Double-check all capabilities (in case index is stale)
                if framework.has_all_capabilities(capability_names):
                    frameworks.append(framework)

        return frameworks

    async def select_framework(
        self,
        capability_names: Sequence[str],
        strategy: str = "healthiest",
        exclude: list[str] | None = None,
        prefer_version: str | None = None,
    ) -> ExternalFramework | None:
        """
        Select the best framework for given capabilities.

        Selection strategies:
        - "healthiest": Prefer frameworks with fewest recent failures
        - "newest": Prefer frameworks with highest version number
        - "random": Random selection among candidates

        Args:
            capability_names: Required capabilities.
            strategy: Selection strategy.
            exclude: Framework IDs to exclude.
            prefer_version: Prefer frameworks matching this version prefix.

        Returns:
            Selected framework or None if no suitable framework found.
        """
        candidates = await self.find_by_capabilities(capability_names)

        if exclude:
            candidates = [f for f in candidates if f.framework_id not in exclude]

        if not candidates:
            return None

        # Apply version preference filter
        if prefer_version:
            version_matches = [f for f in candidates if f.version.startswith(prefer_version)]
            if version_matches:
                candidates = version_matches

        if strategy == "healthiest":
            # Sort by consecutive failures (ascending), then by last health check (descending)
            return min(
                candidates,
                key=lambda f: (f.consecutive_failures, -f.last_health_check),
            )
        elif strategy == "newest":
            # Sort by version (descending) - simple string comparison
            return max(candidates, key=lambda f: f.version)
        elif strategy == "random":
            import random

            return random.choice(candidates)
        else:
            return candidates[0]

    async def query_capabilities(
        self,
        framework_id: str,
    ) -> list[FrameworkCapability]:
        """
        Query capabilities from a framework.

        Returns cached capabilities from registration. For live capability
        discovery, use refresh_capabilities().

        Args:
            framework_id: Framework to query.

        Returns:
            List of framework capabilities.
        """
        framework = await self.get(framework_id)
        if not framework:
            return []
        return framework.capabilities

    async def refresh_capabilities(
        self,
        framework_id: str,
    ) -> list[FrameworkCapability]:
        """
        Refresh capabilities by querying the framework directly.

        Calls the framework's capabilities endpoint to get updated
        capability information.

        Args:
            framework_id: Framework to refresh.

        Returns:
            Updated list of capabilities.
        """
        framework = await self.get(framework_id)
        if not framework:
            return []

        capabilities_endpoint = framework.get_endpoint("capabilities")
        if not capabilities_endpoint:
            base = framework.get_endpoint("base")
            if base:
                capabilities_endpoint = f"{base.rstrip('/')}/capabilities"
            else:
                return framework.capabilities

        try:
            import aiohttp

            if not self._http_client:
                self._http_client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

            async with self._http_client.get(capabilities_endpoint) as response:
                if response.status == 200:
                    data = await response.json()
                    capabilities = [
                        FrameworkCapability.from_dict(cap) for cap in data.get("capabilities", [])
                    ]

                    # Update framework
                    old_caps = {cap.name for cap in framework.capabilities}
                    new_caps = {cap.name for cap in capabilities}

                    framework.capabilities = capabilities
                    self._unindex_capabilities(framework)
                    self._index_capabilities(framework)
                    await self._save_framework(framework)

                    # Emit event if capabilities changed
                    if old_caps != new_caps:
                        self._emit_event(
                            "capabilities_updated",
                            {
                                "framework_id": framework_id,
                                "added": list(new_caps - old_caps),
                                "removed": list(old_caps - new_caps),
                            },
                        )

                    return capabilities
        except ImportError:
            logger.debug("aiohttp not available, using cached capabilities")
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            logger.warning("Failed to refresh capabilities for %s: %s", framework_id, e)

        return framework.capabilities

    def register_startup_hook(
        self,
        hook_id: str,
        callback: LifecycleHook,
    ) -> None:
        """
        Register a startup hook for new framework registrations.

        Startup hooks are called when a framework successfully registers.

        Args:
            hook_id: Unique identifier for the hook.
            callback: Callback function receiving the ExternalFramework.
        """
        self._startup_hooks[hook_id] = callback

    def register_shutdown_hook(
        self,
        hook_id: str,
        callback: LifecycleHook,
    ) -> None:
        """
        Register a shutdown hook for framework disconnections.

        Shutdown hooks are called when a framework is unregistered or
        marked as failed.

        Args:
            hook_id: Unique identifier for the hook.
            callback: Callback function receiving the ExternalFramework.
        """
        self._shutdown_hooks[hook_id] = callback

    def register_reconnect_hook(
        self,
        hook_id: str,
        callback: LifecycleHook,
    ) -> None:
        """
        Register a reconnect hook for framework re-registrations.

        Reconnect hooks are called when a previously registered framework
        registers again (e.g., after a restart).

        Args:
            hook_id: Unique identifier for the hook.
            callback: Callback function receiving the ExternalFramework.
        """
        self._reconnect_hooks[hook_id] = callback

    def unregister_hook(self, hook_id: str) -> bool:
        """
        Unregister a lifecycle hook by ID.

        Args:
            hook_id: Hook ID to unregister.

        Returns:
            True if hook was found and removed.
        """
        removed = False
        for hooks in [self._startup_hooks, self._shutdown_hooks, self._reconnect_hooks]:
            if hook_id in hooks:
                del hooks[hook_id]
                removed = True
        return removed

    async def _run_startup_hooks(self, framework: ExternalFramework) -> None:
        """Run all registered startup hooks."""
        for hook_id, callback in self._startup_hooks.items():
            try:
                result = callback(framework)
                if asyncio.iscoroutine(result):
                    await result
                framework.startup_hooks.append(hook_id)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided lifecycle hook callback
                logger.error("Startup hook %s failed: %s", hook_id, e)

    async def _run_shutdown_hooks(self, framework: ExternalFramework) -> None:
        """Run all registered shutdown hooks."""
        for hook_id, callback in self._shutdown_hooks.items():
            try:
                result = callback(framework)
                if asyncio.iscoroutine(result):
                    await result
                framework.shutdown_hooks.append(hook_id)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided lifecycle hook callback
                logger.error("Shutdown hook %s failed: %s", hook_id, e)

    def _negotiate_version(self, client_versions: list[str]) -> str | None:
        """
        Negotiate API version between client and server.

        Returns the highest version supported by both, or None if
        no compatible version exists.
        """
        # Find intersection of supported versions
        common = set(client_versions) & set(self.SUPPORTED_API_VERSIONS)
        if not common:
            return None

        # Return highest common version
        return max(common, key=lambda v: [int(x) for x in v.split(".")])

    def _index_capabilities(self, framework: ExternalFramework) -> None:
        """Add framework to capability index."""
        for cap in framework.capabilities:
            if cap.name not in self._capability_index:
                self._capability_index[cap.name] = set()
            self._capability_index[cap.name].add(framework.framework_id)

    def _unindex_capabilities(self, framework: ExternalFramework) -> None:
        """Remove framework from capability index."""
        for cap in framework.capabilities:
            if cap.name in self._capability_index:
                self._capability_index[cap.name].discard(framework.framework_id)
                if not self._capability_index[cap.name]:
                    del self._capability_index[cap.name]

    async def _save_framework(self, framework: ExternalFramework) -> None:
        """Save framework to storage."""
        key = f"{self._key_prefix}{framework.framework_id}"

        if self._redis:
            await self._redis.set(
                key,
                json.dumps(framework.to_dict()),
                ex=int(self._heartbeat_timeout * 3),
            )

        # Always update local cache
        self._local_cache[framework.framework_id] = framework

    async def _health_check_loop(self) -> None:
        """Background task for periodic health checks."""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                frameworks = await self.list_all(include_inactive=False)
                for framework in frameworks:
                    await self.health_check(framework.framework_id)
            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, RuntimeError) as e:
                logger.error("Error in health check loop: %s", e)

    async def _cleanup_loop(self) -> None:
        """Background task to clean up dead frameworks."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_dead_frameworks()
            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, RuntimeError) as e:
                logger.error("Error in cleanup loop: %s", e)

    async def _cleanup_dead_frameworks(self) -> int:
        """Mark frameworks as disconnected if heartbeat expired."""
        frameworks = await self.list_all(include_inactive=True)
        marked_disconnected = 0

        for framework in frameworks:
            if not framework.is_alive(self._heartbeat_timeout):
                if framework.status not in (
                    FrameworkStatus.DISCONNECTED,
                    FrameworkStatus.FAILED,
                ):
                    framework.status = FrameworkStatus.DISCONNECTED
                    await self._save_framework(framework)
                    marked_disconnected += 1

                    self._emit_event(
                        "framework_disconnected",
                        {"framework_id": framework.framework_id, "name": framework.name},
                    )

                    logger.warning("Framework marked disconnected: %s", framework.framework_id)

        if marked_disconnected > 0:
            logger.info("Marked %s frameworks as disconnected", marked_disconnected)

        return marked_disconnected

    async def get_stats(self) -> dict[str, Any]:
        """
        Get registry statistics.

        Returns:
            Dict with framework counts, capability distribution, etc.
        """
        frameworks = await self.list_all(include_inactive=True)

        status_counts: dict[str, int] = {}
        health_counts: dict[str, int] = {}
        capability_counts: dict[str, int] = {}

        for framework in frameworks:
            # Count by status
            status = framework.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

            # Count by health
            health = framework.health_status.value
            health_counts[health] = health_counts.get(health, 0) + 1

            # Count by capability
            for cap in framework.capabilities:
                capability_counts[cap.name] = capability_counts.get(cap.name, 0) + 1

        return {
            "total_frameworks": len(frameworks),
            "active_frameworks": len([f for f in frameworks if f.is_active()]),
            "by_status": status_counts,
            "by_health": health_counts,
            "by_capability": capability_counts,
            "heartbeat_timeout": self._heartbeat_timeout,
            "health_check_interval": self._health_check_interval,
            "supported_api_versions": self.SUPPORTED_API_VERSIONS,
        }

    async def clear(self) -> None:
        """Clear all registrations (for testing)."""
        # Clear Redis if available
        if self._redis:
            pattern = f"{self._key_prefix}*"
            async for key in self._redis.scan_iter(match=pattern):
                await self._redis.delete(key)

        # Clear local cache and indexes
        self._local_cache.clear()
        self._capability_index.clear()

        logger.info("FederationRegistry cleared")


__all__ = [
    "FederationRegistry",
    "ExternalFramework",
    "FrameworkCapability",
    "RegistrationResult",
    "HealthStatus",
    "FrameworkStatus",
    "LifecycleHook",
]
