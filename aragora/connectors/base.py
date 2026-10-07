"""
Base Connector - Abstract interface for evidence sources.

All connectors inherit from BaseConnector and implement:
- search(): Find relevant evidence for a query
- fetch(): Retrieve specific evidence by ID
- record(): Store evidence in provenance chain
"""

from __future__ import annotations

__all__ = [
    "BaseConnector",
    "Connector",
    "Evidence",
    "ConnectorHealth",
    "ConnectorCapabilities",
    "ConnectorProtocol",
    # Re-export exceptions for backward compatibility
    "ConnectorError",
    "ConnectorAuthError",
    "ConnectorRateLimitError",
    "ConnectorAPIError",
    "ConnectorTimeoutError",
    "ConnectorCircuitOpenError",
]

import asyncio
import hashlib
import logging
import random
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aragora.resilience import CircuitBreaker

from aragora.reasoning.provenance import (
    ProvenanceManager,
    ProvenanceRecord,
    SourceType,
)

logger = logging.getLogger(__name__)

# Re-export exceptions from dedicated module
from aragora.connectors.exceptions import (
    ConnectorError,
    ConnectorAuthError,
    ConnectorRateLimitError,
    ConnectorAPIError,
    ConnectorTimeoutError,
    ConnectorCircuitOpenError,
)


@dataclass
class Evidence:
    """
    A piece of evidence from an external source.

    Contains the content and metadata needed for
    provenance tracking and reliability scoring.
    """

    id: str
    source_type: SourceType
    source_id: str  # URL, file path, issue number, etc.
    content: str
    title: str = ""

    # Metadata
    created_at: str | None = None
    author: str | None = None
    url: str | None = None

    # Reliability indicators
    confidence: float = 0.5  # Base confidence in source
    freshness: float = 1.0  # How recent (1.0 = current, decays over time)
    authority: float = 0.5  # Source authority (0-1)

    # Additional context
    metadata: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Compute content hash."""
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]

    @property
    def reliability_score(self) -> float:
        """Combined reliability score."""
        # Weighted combination of factors
        return 0.4 * self.confidence + 0.3 * self.freshness + 0.3 * self.authority

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "content": self.content,
            "title": self.title,
            "created_at": self.created_at,
            "author": self.author,
            "url": self.url,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "authority": self.authority,
            "reliability_score": self.reliability_score,
            "content_hash": self.content_hash,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Evidence:
        """Reconstruct Evidence from dictionary (for cache deserialization)."""
        from aragora.reasoning.provenance import SourceType

        # Handle source_type as either string or SourceType enum
        source_type = data.get("source_type", "web_search")
        if isinstance(source_type, str):
            try:
                source_type = SourceType(source_type)
            except ValueError:
                source_type = SourceType.WEB_SEARCH

        return cls(
            id=data["id"],
            source_type=source_type,
            source_id=data["source_id"],
            content=data["content"],
            title=data.get("title", ""),
            created_at=data.get("created_at"),
            author=data.get("author"),
            url=data.get("url"),
            confidence=data.get("confidence", 0.5),
            freshness=data.get("freshness", 1.0),
            authority=data.get("authority", 0.5),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ConnectorHealth:
    """
    Health status of a connector.

    Used for monitoring connector availability and configuration state.
    """

    name: str
    is_available: bool  # Whether required dependencies are installed
    is_configured: bool  # Whether required credentials are configured
    is_healthy: bool  # Whether the connector is operational
    latency_ms: float | None = None  # Response latency if checked
    error: str | None = None  # Error message if unhealthy
    last_check: datetime | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_available": self.is_available,
            "is_configured": self.is_configured,
            "is_healthy": self.is_healthy,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "metadata": self.metadata,
        }

    def __getitem__(self, key: str) -> Any:
        data = self.to_dict()
        if key in data:
            return data[key]
        # Common aliases used by tests/callers.
        if key == "healthy":
            return self.is_healthy
        if key == "available":
            return self.is_available
        if key == "configured":
            return self.is_configured
        # Allow direct access to metadata entries.
        if key in self.metadata:
            return self.metadata[key]
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        try:
            _ = self[key]
            return True
        except KeyError:
            return False


@dataclass
class ConnectorCapabilities:
    """
    Describes the capabilities of a connector.

    Used for capability negotiation and feature discovery. Connectors
    can report what operations they support so the platform can route
    requests appropriately.
    """

    # Core capabilities
    can_send: bool = False  # Can send outbound messages/data
    can_receive: bool = False  # Can receive inbound messages/data
    can_search: bool = False  # Can search for data/evidence
    can_sync: bool = False  # Supports incremental sync
    can_stream: bool = False  # Supports real-time streaming
    can_batch: bool = False  # Supports batch operations

    # Connection model
    is_stateful: bool = False  # Maintains persistent connection
    requires_auth: bool = True  # Requires authentication
    supports_oauth: bool = False  # Supports OAuth flow
    supports_webhooks: bool = False  # Can receive webhooks

    # Data capabilities
    supports_files: bool = False  # Can handle file attachments
    supports_rich_text: bool = False  # Supports formatted messages
    supports_reactions: bool = False  # Supports emoji reactions
    supports_threads: bool = False  # Supports threaded conversations
    supports_voice: bool = False  # Supports voice messages/calls

    # Reliability
    supports_delivery_receipts: bool = False  # Confirms message delivery
    supports_retry: bool = True  # Has built-in retry logic
    has_circuit_breaker: bool = True  # Has circuit breaker protection

    # Rate limiting
    max_requests_per_second: float | None = None  # Rate limit if known
    max_message_size_bytes: int | None = None  # Max payload size

    # Platform-specific features
    platform_features: list[str] = field(default_factory=list)  # Custom features

    def to_dict(self) -> dict:
        """Serialize capabilities to dictionary."""
        return {
            "can_send": self.can_send,
            "can_receive": self.can_receive,
            "can_search": self.can_search,
            "can_sync": self.can_sync,
            "can_stream": self.can_stream,
            "can_batch": self.can_batch,
            "is_stateful": self.is_stateful,
            "requires_auth": self.requires_auth,
            "supports_oauth": self.supports_oauth,
            "supports_webhooks": self.supports_webhooks,
            "supports_files": self.supports_files,
            "supports_rich_text": self.supports_rich_text,
            "supports_reactions": self.supports_reactions,
            "supports_threads": self.supports_threads,
            "supports_voice": self.supports_voice,
            "supports_delivery_receipts": self.supports_delivery_receipts,
            "supports_retry": self.supports_retry,
            "has_circuit_breaker": self.has_circuit_breaker,
            "max_requests_per_second": self.max_requests_per_second,
            "max_message_size_bytes": self.max_message_size_bytes,
            "platform_features": self.platform_features,
        }


@runtime_checkable
class ConnectorProtocol(Protocol):
    """
    Standard interface for all Aragora connectors.

    This Protocol defines the minimal interface that all connectors must
    implement for interoperability. It enables:
    - Plugin marketplace and third-party connector development
    - Unified connector management and monitoring
    - Capability-based routing and feature discovery

    Connectors that implement this protocol can be discovered and used
    by the platform for various operations including chat, evidence
    collection, enterprise sync, device notifications, and more.

    Concrete connector types (BaseConnector, ChatPlatformConnector,
    EnterpriseConnector, DeviceConnector) may provide additional
    specialized methods beyond this interface.

    Usage:
        def process_connector(conn: ConnectorProtocol) -> None:
            caps = conn.capabilities()
            if caps.can_send:
                await conn.send({"message": "hello"})
    """

    @property
    def name(self) -> str:
        """Human-readable name for this connector."""
        ...

    @property
    def is_connected(self) -> bool:
        """Whether the connector has an active connection."""
        ...

    async def connect(self) -> bool:
        """
        Establish connection to the external service.

        Returns:
            True if connection successful, False otherwise
        """
        ...

    async def disconnect(self) -> None:
        """
        Close connection to the external service.

        Should be safe to call multiple times.
        """
        ...

    async def send(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Send data to the external service.

        Args:
            data: Connector-specific payload to send

        Returns:
            Response from the service

        Raises:
            ConnectorError: On send failure
        """
        ...

    async def receive(self) -> dict[str, Any] | None:
        """
        Receive data from the external service.

        For pull-based connectors, this actively polls for data.
        For push-based connectors, this may return None if using webhooks.

        Returns:
            Received data or None if no data available
        """
        ...

    async def health_check(self, timeout: float = 5.0) -> ConnectorHealth:
        """
        Perform a health check on the connector.

        Args:
            timeout: Maximum time to wait for health check

        Returns:
            ConnectorHealth with status details
        """
        ...

    def capabilities(self) -> ConnectorCapabilities:
        """
        Report the capabilities of this connector.

        Returns:
            ConnectorCapabilities describing what this connector supports
        """
        ...


class BaseConnector(ABC):
    """
    Abstract base class for evidence connectors.

    Provides common functionality for searching, fetching,
    and recording evidence with provenance tracking.
    """

    # Default retry configuration
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_BASE_DELAY = 1.0  # seconds
    DEFAULT_MAX_DELAY = 30.0  # seconds
    DEFAULT_JITTER_FACTOR = 0.3  # ±30%

    # Connector identification (defined as abstract properties below)
    # Subclasses must implement name and source_type properties

    @property
    def is_available(self) -> bool:
        """
        Check if required dependencies are installed.

        Subclasses should override to check for optional dependencies.
        """
        return True

    @property
    def is_configured(self) -> bool:
        """
        Check if required credentials/configuration are set.

        Subclasses should override to check for API keys, tokens, etc.
        """
        return True

    async def health_check(self, timeout: float = 5.0) -> ConnectorHealth:
        """
        Perform a health check on the connector.

        This makes a lightweight API call (if applicable) to verify
        the connector is operational.

        Args:
            timeout: Maximum time to wait for health check

        Returns:
            ConnectorHealth with status details
        """
        start_time = time.time()
        error_msg = None

        try:
            if not self.is_available:
                return ConnectorHealth(
                    name=self.name,
                    is_available=False,
                    is_configured=False,
                    is_healthy=False,
                    error="Required dependencies not installed",
                    last_check=datetime.now(),
                )

            if not self.is_configured:
                return ConnectorHealth(
                    name=self.name,
                    is_available=True,
                    is_configured=False,
                    is_healthy=False,
                    error="Connector not configured (missing credentials)",
                    last_check=datetime.now(),
                )

            # Try a lightweight operation to verify connectivity
            is_healthy = await self._perform_health_check(timeout)
            latency_ms = (time.time() - start_time) * 1000

            return ConnectorHealth(
                name=self.name,
                is_available=True,
                is_configured=True,
                is_healthy=is_healthy,
                latency_ms=latency_ms,
                last_check=datetime.now(),
            )

        except asyncio.TimeoutError:
            error_msg = f"Health check timed out after {timeout}s"
        except (OSError, ConnectionError, RuntimeError) as e:
            logger.warning("Health check failed: %s", e)
            error_msg = "Health check failed"

        latency_ms = (time.time() - start_time) * 1000
        return ConnectorHealth(
            name=self.name,
            is_available=self.is_available,
            is_configured=self.is_configured,
            is_healthy=False,
            latency_ms=latency_ms,
            error=error_msg,
            last_check=datetime.now(),
        )

    async def _perform_health_check(self, timeout: float) -> bool:
        """
        Perform the actual health check operation.

        Subclasses can override to make a lightweight API call.
        Default implementation just returns True if configured.
        """
        return True

    def __init__(
        self,
        provenance: ProvenanceManager | None = None,
        default_confidence: float = 0.5,
        max_cache_entries: int = 500,
        cache_ttl_seconds: float = 3600.0,  # 1 hour default TTL
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        enable_circuit_breaker: bool = True,
    ):
        self.provenance = provenance
        self.default_confidence = default_confidence
        # Cache stores (timestamp, evidence) tuples for TTL support
        self._cache: OrderedDict[str, tuple[float, Evidence]] = OrderedDict()
        self._max_cache_entries = max_cache_entries
        self._cache_ttl = cache_ttl_seconds
        # Retry configuration
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        # Circuit breaker for failure protection
        self._circuit_breaker: CircuitBreaker | None = None
        self._enable_circuit_breaker = enable_circuit_breaker

    def _get_circuit_breaker(self):
        """Lazy-initialize circuit breaker on first use."""
        if self._circuit_breaker is None and self._enable_circuit_breaker:
            try:
                from aragora.resilience import get_circuit_breaker

                # Use connector name for unique circuit breaker per connector type
                connector_name = getattr(self, "name", self.__class__.__name__)
                self._circuit_breaker = get_circuit_breaker(f"connector_{connector_name}")
            except ImportError:
                logger.debug("resilience module not available, circuit breaker disabled")
                self._enable_circuit_breaker = False
        return self._circuit_breaker

    def check_circuit_breaker(self) -> bool:
        """
        Check if requests are allowed by the circuit breaker.

        Convenience method for connectors that don't use _request_with_retry
        (e.g., connectors using subprocess calls or custom HTTP logic).

        Returns:
            True if requests are allowed, False if circuit is open.
        """
        cb = self._get_circuit_breaker()
        if cb is None:
            return True
        can = cb.can_proceed()
        if not can:
            remaining = cb.cooldown_remaining()
            logger.warning(
                f"[{getattr(self, 'name', self.__class__.__name__)}] "
                f"Circuit breaker open, cooldown remaining: {remaining:.1f}s"
            )
        return can

    def record_circuit_breaker_success(self) -> None:
        """Record a successful external call for the circuit breaker."""
        cb = self._get_circuit_breaker()
        if cb is not None:
            cb.record_success()

    def record_circuit_breaker_failure(self) -> None:
        """Record a failed external call for the circuit breaker."""
        cb = self._get_circuit_breaker()
        if cb is not None:
            cb.record_failure()

    def get_circuit_breaker_status(self) -> dict:
        """Get current circuit breaker status.

        Returns:
            Dict with 'enabled', 'status', 'failures', etc.
        """
        cb = self._get_circuit_breaker()
        if cb is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "status": cb.get_status(),
            "failures": cb.failures,
            "failure_threshold": cb.failure_threshold,
            "cooldown_seconds": cb.cooldown_seconds,
        }

    def _cache_get(self, evidence_id: str) -> Evidence | None:
        """Get from cache if not expired."""
        # Lazy import metrics
        try:
            from aragora.connectors.metrics import record_cache_hit, record_cache_miss

            metrics_available = True
        except ImportError:
            metrics_available = False

        connector_type = getattr(self, "name", "unknown").lower().replace(" ", "_")

        if evidence_id not in self._cache:
            if metrics_available:
                record_cache_miss(connector_type)
            return None

        cached_time, evidence = self._cache[evidence_id]
        now = time.time()

        # Check TTL
        if now - cached_time > self._cache_ttl:
            # Expired - remove and return None
            del self._cache[evidence_id]
            if metrics_available:
                record_cache_miss(connector_type)
            return None

        # Move to end (LRU)
        self._cache.move_to_end(evidence_id)
        if metrics_available:
            record_cache_hit(connector_type)
        return evidence

    def _cache_put(self, evidence_id: str, evidence: Evidence) -> None:
        """Add to cache with LRU eviction and TTL."""
        now = time.time()

        if evidence_id in self._cache:
            self._cache.move_to_end(evidence_id)
        self._cache[evidence_id] = (now, evidence)

        # LRU eviction if over limit
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)

    def _cache_clear_expired(self) -> int:
        """Clear expired entries from cache. Returns count cleared."""
        now = time.time()
        expired_keys = [
            key
            for key, (cached_time, _) in self._cache.items()
            if now - cached_time > self._cache_ttl
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    def _cache_stats(self) -> dict:
        """Get cache statistics."""
        now = time.time()
        total = len(self._cache)
        expired = sum(
            1 for cached_time, _ in self._cache.values() if now - cached_time > self._cache_ttl
        )
        return {
            "total_entries": total,
            "active_entries": total - expired,
            "expired_entries": expired,
            "max_entries": self._max_cache_entries,
            "ttl_seconds": self._cache_ttl,
        }

    def _calculate_retry_delay(self, attempt: int) -> float:
        """
        Calculate retry delay with exponential backoff and jitter.

        Jitter prevents thundering herd when multiple clients recover
        simultaneously after a provider outage.

        Args:
            attempt: Current retry attempt (0-indexed)

        Returns:
            Delay in seconds with jitter applied
        """
        # Calculate base exponential delay: 1s → 2s → 4s → 8s...
        delay = min(self._base_delay * (2**attempt), self._max_delay)

        # Apply random jitter: delay ± (jitter_factor * delay)
        jitter = delay * self.DEFAULT_JITTER_FACTOR * random.uniform(-1, 1)  # noqa: S311 -- retry jitter

        # Ensure minimum delay of 0.1s
        return max(0.1, delay + jitter)

    async def _request_with_retry(
        self,
        request_func: Any,
        operation: str = "request",
    ) -> Any:
        """
        Execute a request function with exponential backoff retry.

        Retries on:
        - Connection errors (network issues)
        - Timeout errors
        - 429 (Rate limit) - uses Retry-After header if present
        - 5xx (Server errors)

        Does NOT retry on:
        - 4xx errors (except 429)
        - Parse errors
        - Auth errors
        - Circuit breaker open (fast-fail)

        Args:
            request_func: Async callable that performs the HTTP request.
                         Should return the response or raise httpx exceptions.
            operation: Description for logging (e.g., "search", "fetch")

        Returns:
            Response from the request function

        Raises:
            ConnectorError subclass on failure after all retries exhausted
            ConnectorCircuitOpenError if circuit breaker is open

        Example:
            async def do_request():
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    return response.json()

            data = await self._request_with_retry(do_request, "search")
        """
        from aragora.connectors.exceptions import (
            ConnectorAPIError,
            ConnectorCircuitOpenError,
            ConnectorNetworkError,
            ConnectorParseError,
            ConnectorRateLimitError,
            ConnectorTimeoutError,
        )

        # Check circuit breaker before attempting request
        circuit_breaker = self._get_circuit_breaker()
        if circuit_breaker is not None and not circuit_breaker.can_proceed():
            cooldown = circuit_breaker.cooldown_remaining()
            logger.warning(
                f"[{self.name}] Circuit breaker open for {operation}, "
                f"cooldown remaining: {cooldown:.1f}s"
            )
            raise ConnectorCircuitOpenError(
                f"{operation} blocked by circuit breaker",
                connector_name=self.name,
                cooldown_remaining=cooldown,
            )

        # Lazy import httpx (optional dependency)
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not available for retry wrapper")
            return await request_func()

        # Lazy import metrics
        try:
            from aragora.connectors.metrics import (
                record_sync_error,
                record_rate_limit,
            )

            metrics_available = True
        except ImportError:
            metrics_available = False

        last_error: Exception | None = None
        connector_type = self.name.lower().replace(" ", "_")

        for attempt in range(self._max_retries + 1):
            try:
                result = await request_func()
                # Record success with circuit breaker
                if circuit_breaker is not None:
                    circuit_breaker.record_success()
                return result

            except httpx.TimeoutException:
                last_error = ConnectorTimeoutError(
                    f"{operation} timed out",
                    connector_name=self.name,
                )
                logger.warning(
                    "[%s] %s timeout (attempt %s/%s)",
                    self.name,
                    operation,
                    attempt + 1,
                    self._max_retries + 1,
                )
                if metrics_available:
                    record_sync_error(connector_type, "timeout")

            except (httpx.ConnectError, httpx.NetworkError) as e:
                last_error = ConnectorNetworkError(
                    f"{operation} connection failed: {e}",
                    connector_name=self.name,
                )
                logger.warning(
                    "[%s] %s network error (attempt %s/%s): %s",
                    self.name,
                    operation,
                    attempt + 1,
                    self._max_retries + 1,
                    e,
                )
                if metrics_available:
                    record_sync_error(connector_type, "network")

            except httpx.HTTPStatusError as e:
                status = e.response.status_code

                if status == 429:
                    # Rate limit - check for Retry-After header
                    retry_after = None
                    if "Retry-After" in e.response.headers:
                        try:
                            retry_after = float(e.response.headers["Retry-After"])
                        except (ValueError, TypeError) as parse_err:
                            logger.warning(
                                "[%s] Failed to parse Retry-After header '%s': %s",
                                self.name,
                                e.response.headers["Retry-After"],
                                parse_err,
                            )
                            # Continue with retry_after=None, will use exponential backoff

                    last_error = ConnectorRateLimitError(
                        f"{operation} rate limited (HTTP 429)",
                        connector_name=self.name,
                        retry_after=retry_after,
                    )
                    logger.warning(
                        "[%s] %s rate limited (attempt %s/%s)",
                        self.name,
                        operation,
                        attempt + 1,
                        self._max_retries + 1,
                    )
                    if metrics_available:
                        record_rate_limit(connector_type)

                    # Use Retry-After delay if provided, otherwise use exponential backoff
                    if retry_after is not None and attempt < self._max_retries:
                        delay = min(retry_after, self._max_delay)
                        # Add small jitter to Retry-After
                        delay += delay * 0.1 * random.uniform(0, 1)  # noqa: S311 -- retry jitter
                        logger.info(f"[{self.name}] Waiting {delay:.1f}s (Retry-After)")
                        await asyncio.sleep(delay)
                        continue

                elif status >= 500:
                    # Server error - retryable
                    last_error = ConnectorAPIError(
                        f"{operation} server error (HTTP {status})",
                        connector_name=self.name,
                        status_code=status,
                    )
                    logger.warning(
                        "[%s] %s server error %s (attempt %s/%s)",
                        self.name,
                        operation,
                        status,
                        attempt + 1,
                        self._max_retries + 1,
                    )
                    if metrics_available:
                        record_sync_error(connector_type, f"http_{status}")

                else:
                    # 4xx errors (except 429) - not retryable
                    if metrics_available:
                        record_sync_error(connector_type, f"http_{status}")
                    raise ConnectorAPIError(
                        f"{operation} failed (HTTP {status})",
                        connector_name=self.name,
                        status_code=status,
                    ) from e

            except (ValueError, TypeError, KeyError, AttributeError) as e:
                # Unexpected error - log and don't retry
                error_desc = str(e).lower()
                if "json" in error_desc or "decode" in error_desc:
                    if metrics_available:
                        record_sync_error(connector_type, "parse")
                    logger.warning("[%s] %s parse error: %s", self.name, operation, e)
                    raise ConnectorParseError(
                        f"{operation} parse error",
                        connector_name=self.name,
                    ) from e

                logger.error("[%s] %s unexpected error: %s", self.name, operation, e)
                if metrics_available:
                    record_sync_error(connector_type, "unexpected")
                raise ConnectorAPIError(
                    f"{operation} failed unexpectedly",
                    connector_name=self.name,
                ) from e

            except (UnicodeDecodeError, RuntimeError) as e:
                # Remaining non-HTTP errors: decode failures or runtime issues
                error_desc = str(e).lower()
                if "json" in error_desc or "decode" in error_desc:
                    if metrics_available:
                        record_sync_error(connector_type, "parse")
                    logger.warning("[%s] %s parse error: %s", self.name, operation, e)
                    raise ConnectorParseError(
                        f"{operation} parse error",
                        connector_name=self.name,
                    ) from e

                logger.error("[%s] %s unexpected error: %s", self.name, operation, e)
                if metrics_available:
                    record_sync_error(connector_type, "unexpected")
                raise ConnectorAPIError(
                    f"{operation} failed unexpectedly",
                    connector_name=self.name,
                ) from e

            # Retry with exponential backoff
            if attempt < self._max_retries:
                delay = self._calculate_retry_delay(attempt)
                logger.info(
                    f"[{self.name}] Retrying {operation} in {delay:.1f}s "
                    f"(attempt {attempt + 2}/{self._max_retries + 1})"
                )
                await asyncio.sleep(delay)

        # All retries exhausted - record failure with circuit breaker
        if circuit_breaker is not None:
            circuit_breaker.record_failure()

        if last_error is not None:
            raise last_error

        # Should never reach here, but just in case
        raise ConnectorAPIError(
            f"{operation} failed after {self._max_retries + 1} attempts",
            connector_name=self.name,
        )

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """The source type for this connector."""
        raise NotImplementedError("Subclasses must implement source_type property")

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this connector."""
        raise NotImplementedError("Subclasses must implement name property")

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> list[Evidence]:
        """
        Search for evidence matching a query.

        Args:
            query: Search query string
            limit: Maximum results to return
            **kwargs: Connector-specific options

        Returns:
            List of Evidence objects

        Error handling is not uniform across implementations: some connectors
        raise when the request fails, others log the error and return an empty
        list. A caller that must tell a failure from "no results" has to check
        the specific connector.
        """
        raise NotImplementedError("Subclasses must implement search method")

    @abstractmethod
    async def fetch(self, evidence_id: str) -> Evidence | None:
        """
        Fetch a specific piece of evidence by ID.

        Args:
            evidence_id: Unique identifier for the evidence

        Returns:
            Evidence object or None if not found

        Error handling is not uniform across implementations: some connectors
        raise when the request fails, others log the error and return None, so
        None does not always mean "not found". A caller that must tell the two
        apart has to check the specific connector.
        """
        raise NotImplementedError("Subclasses must implement fetch method")

    def record_evidence(
        self,
        evidence: Evidence,
        claim_id: str | None = None,
        support_type: str = "supports",
    ) -> ProvenanceRecord | None:
        """
        Record evidence in the provenance chain.

        Args:
            evidence: The evidence to record
            claim_id: Optional claim to link as citation
            support_type: How evidence relates to claim

        Returns:
            ProvenanceRecord or None if no provenance manager
        """
        if not self.provenance:
            return None

        # Record in chain
        record = self.provenance.record_evidence(
            content=evidence.content,
            source_type=evidence.source_type,
            source_id=evidence.source_id,
            confidence=evidence.reliability_score,
            metadata={
                "title": evidence.title,
                "author": evidence.author,
                "url": evidence.url,
                "content_hash": evidence.content_hash,
            },
        )

        # Create citation if claim_id provided
        if claim_id:
            self.provenance.cite_evidence(
                claim_id=claim_id,
                evidence_id=record.id,
                relevance=evidence.reliability_score,
                support_type=support_type,
                citation_text=evidence.content[:200],
            )

        return record

    async def search_and_record(
        self,
        query: str,
        claim_id: str | None = None,
        limit: int = 5,
        **kwargs,
    ) -> list[tuple[Evidence, ProvenanceRecord | None]]:
        """
        Search for evidence and record all results.

        Returns:
            List of (Evidence, ProvenanceRecord) tuples
        """
        results = await self.search(query, limit=limit, **kwargs)

        recorded = []
        for evidence in results:
            record = self.record_evidence(evidence, claim_id)
            recorded.append((evidence, record))

        return recorded

    def calculate_freshness(self, created_at: str) -> float:
        """
        Calculate freshness score based on age.

        Recent content (< 7 days) = 1.0
        Decays exponentially to 0.1 for old content (> 1 year)
        """
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_days = (datetime.now(created.tzinfo) - created).days

            if age_days < 7:
                return 1.0
            elif age_days < 30:
                return 0.9
            elif age_days < 90:
                return 0.7
            elif age_days < 365:
                return 0.5
            else:
                return 0.3
        except (ValueError, TypeError, AttributeError):
            return 0.5  # Unknown age

    # =========================================================================
    # ConnectorProtocol Implementation
    # =========================================================================
    # These methods provide the standard interface for all connectors.
    # Subclasses should override as needed for their specific use case.

    @property
    def is_connected(self) -> bool:
        """
        Whether the connector has an active connection.

        For evidence connectors, this is generally True if configured.
        Stateful connectors should track actual connection state.
        """
        return self.is_configured

    async def connect(self) -> bool:
        """
        Establish connection to the external service.

        For stateless connectors (like most evidence connectors),
        this is a no-op that returns True if properly configured.

        Returns:
            True if connection successful
        """
        return self.is_configured

    async def disconnect(self) -> None:
        """
        Close connection to the external service.

        For stateless connectors, this is a no-op.
        Stateful connectors should properly close connections.
        """
        pass

    async def send(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Send data to the external service.

        BaseConnector (evidence connectors) does not support sending.
        Subclasses like ChatPlatformConnector override this.

        Args:
            data: Connector-specific payload

        Returns:
            Response from service

        Raises:
            NotImplementedError: BaseConnector doesn't support send
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support send(). "
            "Use search() and fetch() for evidence connectors."
        )

    async def receive(self) -> dict[str, Any] | None:
        """
        Receive data from the external service.

        BaseConnector (evidence connectors) does not support receive.
        Use search() and fetch() instead. Subclasses may override.

        Returns:
            None - evidence connectors use search()/fetch()
        """
        return None

    def capabilities(self) -> ConnectorCapabilities:
        """
        Report the capabilities of this connector.

        Returns capabilities appropriate for evidence connectors.
        Subclasses should override to report their specific capabilities.

        Returns:
            ConnectorCapabilities for this connector
        """
        return ConnectorCapabilities(
            can_send=False,
            can_receive=False,
            can_search=True,
            can_sync=False,
            can_stream=False,
            can_batch=False,
            is_stateful=False,
            requires_auth=True,
            supports_oauth=False,
            supports_webhooks=False,
            supports_files=False,
            supports_rich_text=False,
            supports_reactions=False,
            supports_threads=False,
            supports_voice=False,
            supports_delivery_receipts=False,
            supports_retry=True,
            has_circuit_breaker=self._enable_circuit_breaker,
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source={self.source_type.value})"


# Alias for backward compatibility
Connector = BaseConnector
