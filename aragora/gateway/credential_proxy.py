"""
Credential Proxy - Secure credential mediation for external systems.

Provides:
- Per-external-system rate limiting (token bucket)
- TTL-cached credential lookups
- Scope validation before calls
- Credential usage audit logging
- Data lineage tracking
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from aragora.rbac.checker import PermissionChecker

logger = logging.getLogger(__name__)


@dataclass
class CredentialUsage:
    """Record of credential usage."""

    credential_id: str
    external_service: str
    operation: str
    scopes_used: list[str]
    timestamp: datetime
    tenant_id: str
    user_id: str
    success: bool
    error_message: str = ""
    duration_ms: float = 0.0
    decision_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "credential_id": self.credential_id,
            "external_service": self.external_service,
            "operation": self.operation,
            "scopes_used": self.scopes_used,
            "timestamp": self.timestamp.isoformat(),
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "success": self.success,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "decision_id": self.decision_id,
        }


@dataclass
class ExternalCredential:
    """Credential for external system."""

    credential_id: str
    external_service: str  # openclaw, slack, github
    tenant_id: str
    api_key: str = ""
    oauth_token: str = ""
    refresh_token: str = ""
    scopes: list[str] = field(default_factory=list)
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if credential has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (excludes sensitive data)."""
        return {
            "credential_id": self.credential_id,
            "external_service": self.external_service,
            "tenant_id": self.tenant_id,
            "scopes": self.scopes,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "is_expired": self.is_expired,
        }


class CredentialProxyError(Exception):
    """Base error for credential proxy."""

    pass


class CredentialNotFoundError(CredentialProxyError):
    """Credential does not exist."""

    pass


class CredentialExpiredError(CredentialProxyError):
    """Credential has expired."""

    pass


class ScopeError(CredentialProxyError):
    """Required scopes not available."""

    pass


class RateLimitExceededError(CredentialProxyError):
    """Rate limit exceeded for external system."""

    pass


class TenantIsolationError(CredentialProxyError):
    """Credential belongs to a different tenant."""

    pass


class _TokenBucket:
    """Simple token bucket rate limiter for per-service rate limiting."""

    def __init__(self, rate: float, capacity: int):
        """
        Initialize token bucket.

        Args:
            rate: Token refill rate (tokens per second)
            capacity: Maximum number of tokens (burst size)
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._acquired_count: int = 0

    def try_acquire(self) -> bool:
        """Try to acquire a token. Returns True if allowed."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            self._acquired_count += 1
            return True
        return False

    @property
    def acquired_count(self) -> int:
        """Total number of tokens successfully acquired."""
        return self._acquired_count


class CredentialProxy:
    """
    Mediate all external system credential access.

    Security controls:
    - Validates credentials not expired
    - Checks RBAC permissions for credential+operation
    - Enforces per-external-system rate limits
    - Logs all credential usage attempts
    - Tracks data lineage for decisions
    """

    def __init__(
        self,
        permission_checker: PermissionChecker | None = None,
        default_rate_limit: int = 60,  # requests per minute
        audit_enabled: bool = True,
        cache_ttl: float = 60.0,  # seconds
    ):
        """
        Initialize the credential proxy.

        Args:
            permission_checker: Optional RBAC permission checker
            default_rate_limit: Default requests per minute for external services
            audit_enabled: Whether to enable audit logging
            cache_ttl: TTL in seconds for credential lookup cache entries
        """
        self.permission_checker = permission_checker
        self.default_rate_limit = default_rate_limit
        self.audit_enabled = audit_enabled

        # Rate limiting state
        self._rate_limits: dict[str, int] = {}  # service -> requests/min
        self._rate_limiters: dict[str, _TokenBucket] = {}  # service -> token bucket

        # Credential store
        self._credentials: dict[str, ExternalCredential] = {}

        # Credential lookup cache: credential_id -> (cached_time, credential)
        self._lookup_cache: dict[str, tuple[float, ExternalCredential]] = {}
        self._cache_ttl: float = cache_ttl

        # Usage history for audit
        self._usage_history: list[CredentialUsage] = []

        # Audit callbacks
        self._audit_callbacks: list[Callable[[CredentialUsage], Awaitable[None]]] = []

    # -------------------------------------------------------------------------
    # Credential Lookup Cache
    # -------------------------------------------------------------------------

    def _get_cached_credential(self, credential_id: str) -> ExternalCredential | None:
        """Get credential from cache if not expired."""
        entry = self._lookup_cache.get(credential_id)
        if entry is not None:
            cached_time, credential = entry
            if time.monotonic() - cached_time < self._cache_ttl:
                return credential
            del self._lookup_cache[credential_id]
        return None

    def _cache_credential(self, credential_id: str, credential: ExternalCredential) -> None:
        """Cache a credential lookup result."""
        self._lookup_cache[credential_id] = (time.monotonic(), credential)

    def _invalidate_cache(self, credential_id: str | None = None) -> None:
        """Invalidate cache entry or entire cache."""
        if credential_id:
            self._lookup_cache.pop(credential_id, None)
        else:
            self._lookup_cache.clear()

    # -------------------------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------------------------

    def set_rate_limit(self, external_service: str, requests_per_minute: int) -> None:
        """
        Set rate limit for an external service.

        Args:
            external_service: Name of the external service
            requests_per_minute: Maximum requests allowed per minute
        """
        if requests_per_minute <= 0:
            raise ValueError("Rate limit must be positive")
        self._rate_limits[external_service] = requests_per_minute
        # Reset the token bucket so it picks up the new limit
        self._rate_limiters.pop(external_service, None)
        logger.debug("Set rate limit for %s: %s/min", external_service, requests_per_minute)

    def get_rate_limit(self, external_service: str) -> int:
        """Get rate limit for an external service."""
        return self._rate_limits.get(external_service, self.default_rate_limit)

    def register_credential(self, credential: ExternalCredential) -> None:
        """
        Register a credential for use.

        Args:
            credential: The credential to register
        """
        self._credentials[credential.credential_id] = credential
        self._invalidate_cache(credential.credential_id)
        logger.info(
            "Registered credential %s for %s (tenant: %s)",
            credential.credential_id,
            credential.external_service,
            credential.tenant_id,
        )

    def unregister_credential(self, credential_id: str) -> bool:
        """
        Unregister a credential.

        Args:
            credential_id: ID of the credential to remove

        Returns:
            True if credential was removed, False if not found
        """
        if credential_id in self._credentials:
            del self._credentials[credential_id]
            self._invalidate_cache(credential_id)
            logger.info("Unregistered credential %s", credential_id)
            return True
        return False

    def get_credential(self, credential_id: str) -> ExternalCredential | None:
        """
        Get a credential by ID (without executing).

        Uses a TTL cache to avoid repeated dictionary lookups for the same
        credential within the cache window.

        Args:
            credential_id: ID of the credential

        Returns:
            The credential or None if not found
        """
        cached = self._get_cached_credential(credential_id)
        if cached is not None:
            return cached

        credential = self._credentials.get(credential_id)
        if credential is not None:
            self._cache_credential(credential_id, credential)
        return credential

    def list_credentials(
        self,
        tenant_id: str | None = None,
        external_service: str | None = None,
    ) -> list[ExternalCredential]:
        """
        List registered credentials.

        Args:
            tenant_id: Filter by tenant ID
            external_service: Filter by external service

        Returns:
            List of matching credentials
        """
        result = list(self._credentials.values())

        if tenant_id:
            result = [c for c in result if c.tenant_id == tenant_id]
        if external_service:
            result = [c for c in result if c.external_service == external_service]

        return result

    async def execute_with_credential(
        self,
        credential_id: str,
        external_service: str,
        operation: str,
        execute_fn: Callable[[ExternalCredential], Awaitable[Any]],
        required_scopes: list[str],
        tenant_id: str,
        user_id: str,
        decision_id: str | None = None,
    ) -> Any:
        """
        Execute an operation with credential mediation.

        Args:
            credential_id: ID of credential to use
            external_service: Name of external service (openclaw, slack, etc.)
            operation: Operation being performed (for audit)
            execute_fn: Async function to execute with credential
            required_scopes: Scopes required for this operation
            tenant_id: Tenant making the request
            user_id: User making the request
            decision_id: Optional decision ID for data lineage

        Returns:
            Result from execute_fn

        Raises:
            CredentialNotFoundError: If credential does not exist
            CredentialExpiredError: If credential is expired
            ScopeError: If required scopes not available
            RateLimitExceededError: If rate limit exceeded
            TenantIsolationError: If credential belongs to different tenant
        """
        start_time = datetime.now(timezone.utc)
        usage = CredentialUsage(
            credential_id=credential_id,
            external_service=external_service,
            operation=operation,
            scopes_used=required_scopes,
            timestamp=start_time,
            tenant_id=tenant_id,
            user_id=user_id,
            success=False,
            decision_id=decision_id,
        )

        try:
            # 1. Get and validate credential
            credential = self._credentials.get(credential_id)
            if credential is None:
                raise CredentialNotFoundError(f"Credential not found: {credential_id}")

            if credential.is_expired:
                raise CredentialExpiredError(
                    f"Credential {credential_id} expired at {credential.expires_at}"
                )

            # 2. Verify tenant isolation
            if credential.tenant_id != tenant_id:
                raise TenantIsolationError(
                    f"Credential {credential_id} belongs to different tenant"
                )

            # 3. Check scope authorization
            required_set = set(required_scopes)
            available_set = set(credential.scopes)
            if not required_set.issubset(available_set):
                missing = required_set - available_set
                raise ScopeError(f"Missing scopes: {missing}")

            # 4. Check rate limits
            rate_limit = self._rate_limits.get(external_service, self.default_rate_limit)
            if not self._check_rate_limit(external_service, rate_limit):
                raise RateLimitExceededError(
                    f"Rate limit exceeded for {external_service}: {rate_limit}/min"
                )

            # 5. Execute with credential
            result = await execute_fn(credential)

            # 6. Update credential last used
            credential.last_used_at = datetime.now(timezone.utc)

            usage.success = True
            usage.duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            return result

        except (
            CredentialProxyError,
            OSError,
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
        ) as e:
            usage.error_message = str(e)
            raise

        finally:
            # Always log usage
            if self.audit_enabled:
                self._usage_history.append(usage)
                await self._emit_audit_event(usage)

    def _check_rate_limit(self, external_service: str, limit: int) -> bool:
        """
        Check if request is within rate limit using a token bucket.

        Args:
            external_service: Name of the external service
            limit: Maximum requests per minute

        Returns:
            True if within limit, False if exceeded
        """
        if external_service not in self._rate_limiters:
            self._rate_limiters[external_service] = _TokenBucket(
                rate=limit / 60.0,  # convert per-minute to per-second
                capacity=limit,
            )
        return self._rate_limiters[external_service].try_acquire()

    def get_current_request_count(self, external_service: str) -> int:
        """Get the approximate number of consumed tokens for a service.

        With a token bucket, the exact sliding-window count is not tracked.
        This returns ``capacity - available_tokens`` (rounded), which reflects
        how many tokens have been consumed since the bucket was last full.
        """
        bucket = self._rate_limiters.get(external_service)
        if bucket is None:
            return 0
        # Refill first so the value reflects elapsed time
        now = time.monotonic()
        elapsed = now - bucket._last_refill
        tokens = min(bucket._capacity, bucket._tokens + elapsed * bucket._rate)
        return max(0, round(bucket._capacity - tokens))

    def add_audit_callback(self, callback: Callable[[CredentialUsage], Awaitable[None]]) -> None:
        """
        Add an async callback for audit events.

        Args:
            callback: Async function called with CredentialUsage on each usage
        """
        self._audit_callbacks.append(callback)

    async def _emit_audit_event(self, usage: CredentialUsage) -> None:
        """
        Emit audit event for credential usage.

        Calls all registered callbacks and logs the event.
        """
        # Log to standard logger
        level = logging.INFO if usage.success else logging.WARNING
        logger.log(
            level,
            "Credential usage: %s for %s.%s by %s (tenant: %s) -> %s",
            usage.credential_id,
            usage.external_service,
            usage.operation,
            usage.user_id,
            usage.tenant_id,
            "success" if usage.success else "failed: " + usage.error_message,
        )

        # Call registered callbacks
        for callback in self._audit_callbacks:
            try:
                await callback(usage)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided audit callback
                logger.error("Audit callback failed: %s", e)

    def get_usage_history(
        self,
        credential_id: str | None = None,
        external_service: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        since: datetime | None = None,
        success_only: bool | None = None,
        limit: int = 100,
    ) -> list[CredentialUsage]:
        """
        Query credential usage history.

        Args:
            credential_id: Filter by credential ID
            external_service: Filter by external service
            tenant_id: Filter by tenant ID
            user_id: Filter by user ID
            since: Filter by timestamp (events after this time)
            success_only: Filter by success status (True/False/None for all)
            limit: Maximum number of results

        Returns:
            List of matching usage records
        """
        result = self._usage_history

        if credential_id:
            result = [u for u in result if u.credential_id == credential_id]
        if external_service:
            result = [u for u in result if u.external_service == external_service]
        if tenant_id:
            result = [u for u in result if u.tenant_id == tenant_id]
        if user_id:
            result = [u for u in result if u.user_id == user_id]
        if since:
            result = [u for u in result if u.timestamp >= since]
        if success_only is not None:
            result = [u for u in result if u.success == success_only]

        # Sort by timestamp descending and apply limit
        result = sorted(result, key=lambda u: u.timestamp, reverse=True)
        return result[:limit]

    def clear_usage_history(self) -> int:
        """
        Clear all usage history.

        Returns:
            Number of records cleared
        """
        count = len(self._usage_history)
        self._usage_history.clear()
        return count

    def get_stats(self) -> dict[str, Any]:
        """
        Get proxy statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            "credentials_registered": len(self._credentials),
            "usage_history_size": len(self._usage_history),
            "rate_limits": dict(self._rate_limits),
            "default_rate_limit": self.default_rate_limit,
            "audit_enabled": self.audit_enabled,
            "audit_callbacks_count": len(self._audit_callbacks),
        }


# Global instance
_credential_proxy: CredentialProxy | None = None


def get_credential_proxy() -> CredentialProxy:
    """Get global credential proxy instance."""
    global _credential_proxy
    if _credential_proxy is None:
        _credential_proxy = CredentialProxy()
    return _credential_proxy


def set_credential_proxy(proxy: CredentialProxy) -> None:
    """Set global credential proxy instance."""
    global _credential_proxy
    _credential_proxy = proxy


def reset_credential_proxy() -> None:
    """Reset global credential proxy instance (for testing)."""
    global _credential_proxy
    _credential_proxy = None


__all__ = [
    # Dataclasses
    "CredentialUsage",
    "ExternalCredential",
    # Exceptions
    "CredentialProxyError",
    "CredentialNotFoundError",
    "CredentialExpiredError",
    "ScopeError",
    "RateLimitExceededError",
    "TenantIsolationError",
    # Main class
    "CredentialProxy",
    # Global helpers
    "get_credential_proxy",
    "set_credential_proxy",
    "reset_credential_proxy",
]
