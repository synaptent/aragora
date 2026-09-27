"""
OAuth utility functions.

Provides the ``_impl()`` helper that all mixin modules use to resolve config
functions and utility names from the ``_oauth_impl`` backward-compatibility
shim at runtime.  This ensures that ``unittest.mock.patch`` calls targeting
``_oauth_impl.<name>`` are visible to the actual mixin code.

Also holds shared utilities:
- ``_oauth_limiter``: Rate limiter with exponential backoff
- ``TokenHealthStatus``: Enum for token expiration states
- ``TokenHealthChecker``: Unified token health checking
- ``OAuthStateDataExtractor``: Safe state data access
- ``OAuthPermissionHelper``: Consistent permission checking

These utilities consolidate ~920 lines of duplicate code across OAuth handlers.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol
import inspect

from aragora.server.middleware.rate_limit.oauth_limiter import (
    get_oauth_limiter,
)

if TYPE_CHECKING:
    from aragora.server.handlers.base import HandlerResult
    from aragora.server.handlers.oauth.models import OAuthUserInfo

logger = logging.getLogger(__name__)


async def _maybe_await(value: Any) -> Any:
    """Await coroutines when mixins are used without full OAuthHandler."""
    if inspect.isawaitable(value):
        return await value
    return value


class OAuthHandlerProtocol(Protocol):
    """Protocol defining methods that OAuth mixins expect from OAuthHandler.

    This protocol enables mypy to type-check mixin classes that reference
    methods defined on the main OAuthHandler or its parent classes.
    """

    def _get_user_store(self) -> Any:
        """Get user store from context."""
        ...

    def _redirect_with_error(self, error: str) -> HandlerResult:
        """Redirect to error page with error message."""
        ...

    def _redirect_with_tokens(self, redirect_url: str, tokens: Any) -> HandlerResult:
        """Redirect to frontend with tokens in URL query parameters."""
        ...

    def _check_permission(
        self, handler: Any, permission_key: str, resource_id: str | None = None
    ) -> HandlerResult | None:
        """Check RBAC permission. Returns error response if denied, None if allowed."""
        ...

    def _complete_oauth_flow(
        self, user_info: OAuthUserInfo, state_data: dict[str, Any]
    ) -> HandlerResult:
        """Complete OAuth flow - create/login user and redirect with tokens."""
        ...

    def _find_user_by_oauth(self, user_store: Any, user_info: OAuthUserInfo) -> Any:
        """Find user by OAuth provider ID."""
        ...

    def _link_oauth_to_user(self, user_store: Any, user_id: str, user_info: OAuthUserInfo) -> bool:
        """Link OAuth provider to existing user."""
        ...

    def _create_oauth_user(self, user_store: Any, user_info: OAuthUserInfo) -> Any:
        """Create a new user from OAuth info."""
        ...

    def _handle_account_linking(
        self,
        user_store: Any,
        user_id: str,
        user_info: OAuthUserInfo,
        state_data: dict[str, Any],
    ) -> HandlerResult:
        """Handle linking OAuth account to existing user."""
        ...

    def read_json_body(self, handler: Any, max_size: int | None = None) -> dict[str, Any] | None:
        """Read and parse JSON body from request handler."""
        ...

    # Provider-specific auth start methods (used by AccountManagementMixin)
    def _handle_google_auth_start(
        self, handler: Any, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Redirect user to Google OAuth consent screen."""
        ...

    def _handle_github_auth_start(
        self, handler: Any, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Redirect user to GitHub OAuth consent screen."""
        ...

    def _handle_microsoft_auth_start(
        self, handler: Any, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Redirect user to Microsoft OAuth consent screen."""
        ...

    def _handle_apple_auth_start(self, handler: Any, query_params: dict[str, Any]) -> HandlerResult:
        """Redirect user to Apple OAuth consent screen."""
        ...

    def _handle_oidc_auth_start(self, handler: Any, query_params: dict[str, Any]) -> HandlerResult:
        """Redirect user to OIDC OAuth consent screen."""
        ...

    # Provider-specific callback methods (used by AccountManagementMixin)
    def _handle_google_callback(self, handler: Any, query_params: dict[str, Any]) -> HandlerResult:
        """Handle Google OAuth callback."""
        ...

    def _handle_github_callback(self, handler: Any, query_params: dict[str, Any]) -> HandlerResult:
        """Handle GitHub OAuth callback."""
        ...

    def _handle_microsoft_callback(
        self, handler: Any, query_params: dict[str, Any]
    ) -> HandlerResult:
        """Handle Microsoft OAuth callback."""
        ...

    def _handle_apple_callback(self, handler: Any, query_params: dict[str, Any]) -> HandlerResult:
        """Handle Apple OAuth callback."""
        ...

    def _handle_oidc_callback(self, handler: Any, query_params: dict[str, Any]) -> HandlerResult:
        """Handle OIDC OAuth callback."""
        ...


class OAuthRateLimiterWrapper:
    """Wrapper around the new OAuthRateLimiter for backward compatibility.

    This wrapper provides the old `is_allowed(key)` interface expected by
    existing code while using the new OAuth rate limiting infrastructure
    with exponential backoff and stricter limits.

    The wrapper does NOT cache the limiter - it always gets the current global
    instance to support reset between tests.
    """

    def is_allowed(self, key: str, endpoint_type: str = "auth_start") -> bool:
        """Check if request is allowed.

        Args:
            key: Client IP address
            endpoint_type: Type of endpoint for limit selection

        Returns:
            True if request is allowed, False if rate limited
        """
        # Always get fresh limiter instance to support reset
        limiter = get_oauth_limiter()
        result = limiter.check(key, endpoint_type)
        return result.allowed

    @property
    def rpm(self) -> int:
        """Get approximate requests per minute (for logging compatibility)."""
        # Return auth_start limit as RPM equivalent (15 per 15 min = 1/min)
        limiter = get_oauth_limiter()
        return limiter.config.auth_start_limit


# Rate limiter for OAuth endpoints - now uses the new OAuthRateLimiter with
# exponential backoff and stricter limits:
# - Token endpoints: 5 requests per 15 minutes
# - Callback handlers: 10 requests per 15 minutes
# - Auth start (redirect): 15 requests per 15 minutes
_oauth_limiter = OAuthRateLimiterWrapper()

# Module path constant for the backward-compat shim that tests patch against.
_IMPL_MODULE = "aragora.server.handlers.oauth._oauth_impl"


def _impl() -> ModuleType:
    """Return the ``_oauth_impl`` module lazily to avoid circular imports.

    All mixin modules call ``_impl().<name>`` instead of importing config
    functions directly so that ``unittest.mock.patch`` applied to
    ``_oauth_impl.<name>`` is visible to the running code.

    Uses ``sys.modules`` first (so patches are visible), falling back to
    ``importlib.import_module`` when the shim has not been imported yet or
    was evicted from the module cache by another test.
    """
    try:
        return sys.modules[_IMPL_MODULE]
    except KeyError:
        import importlib

        return importlib.import_module(_IMPL_MODULE)


# =============================================================================
# Token Health Status (consolidates ~40 lines across slack_oauth, teams_oauth)
# =============================================================================


class TokenHealthStatus(str, Enum):
    """Token health/expiration status."""

    VALID = "valid"
    EXPIRING_SOON = "expiring_soon"  # Within 1 hour
    EXPIRING_TODAY = "expiring_today"  # Within 24 hours
    EXPIRED = "expired"
    UNKNOWN = "unknown"  # No expiration info


@dataclass
class TokenHealthResult:
    """Result of token health check."""

    status: TokenHealthStatus
    expires_at: float | None = None
    seconds_remaining: float | None = None
    needs_refresh: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "expires_at": self.expires_at,
            "seconds_remaining": self.seconds_remaining,
            "needs_refresh": self.needs_refresh,
            "message": self.message,
        }


class TokenHealthChecker:
    """Unified token health checking.

    Consolidates duplicate token expiration logic from:
    - slack_oauth.py:1202-1209
    - teams_oauth.py:725-730
    - teams_oauth.py:848-857

    Usage:
        checker = TokenHealthChecker()
        result = checker.check(token_expires_at)
        if result.needs_refresh:
            await refresh_token()
    """

    def __init__(
        self,
        expiring_soon_threshold: int = 3600,  # 1 hour
        expiring_today_threshold: int = 86400,  # 24 hours
    ):
        self.expiring_soon_threshold = expiring_soon_threshold
        self.expiring_today_threshold = expiring_today_threshold

    def check(
        self, expires_at: float | None, current_time: float | None = None
    ) -> TokenHealthResult:
        """Check token health status.

        Args:
            expires_at: Token expiration timestamp (Unix epoch)
            current_time: Optional current time for testing

        Returns:
            TokenHealthResult with status and metadata
        """
        if expires_at is None:
            return TokenHealthResult(
                status=TokenHealthStatus.UNKNOWN,
                message="No expiration information available",
            )

        now = current_time or time.time()
        seconds_remaining = expires_at - now

        if seconds_remaining <= 0:
            return TokenHealthResult(
                status=TokenHealthStatus.EXPIRED,
                expires_at=expires_at,
                seconds_remaining=0,
                needs_refresh=True,
                message="Token has expired",
            )

        if seconds_remaining <= self.expiring_soon_threshold:
            return TokenHealthResult(
                status=TokenHealthStatus.EXPIRING_SOON,
                expires_at=expires_at,
                seconds_remaining=seconds_remaining,
                needs_refresh=True,
                message=f"Token expires in {int(seconds_remaining / 60)} minutes",
            )

        if seconds_remaining <= self.expiring_today_threshold:
            return TokenHealthResult(
                status=TokenHealthStatus.EXPIRING_TODAY,
                expires_at=expires_at,
                seconds_remaining=seconds_remaining,
                needs_refresh=False,
                message=f"Token expires in {int(seconds_remaining / 3600)} hours",
            )

        return TokenHealthResult(
            status=TokenHealthStatus.VALID,
            expires_at=expires_at,
            seconds_remaining=seconds_remaining,
            needs_refresh=False,
            message="Token is valid",
        )


# Singleton for convenience
_token_health_checker: TokenHealthChecker | None = None


def get_token_health_checker() -> TokenHealthChecker:
    """Get or create the token health checker singleton."""
    global _token_health_checker
    if _token_health_checker is None:
        _token_health_checker = TokenHealthChecker()
    return _token_health_checker


# =============================================================================
# OAuth State Data Extractor (consolidates ~50 lines across handlers)
# =============================================================================


class OAuthStateDataExtractor:
    """Safe extraction of data from OAuth state objects.

    Handles both dict and object-based state representations consistently.

    Consolidates patterns from:
    - slack_oauth.py:826-830
    - teams_oauth.py:408
    - base.py:349

    Usage:
        extractor = OAuthStateDataExtractor(state_data)
        tenant_id = extractor.get("tenant_id")
        user_id = extractor.get_from_metadata("user_id")
    """

    def __init__(self, state_data: Any):
        """Initialize with state data (dict or object).

        Args:
            state_data: The OAuth state data (may be dict or object with attributes)
        """
        self._data = state_data
        self._is_dict = isinstance(state_data, dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from state data.

        Args:
            key: The key to look up
            default: Default value if not found

        Returns:
            The value or default
        """
        if self._data is None:
            return default

        if self._is_dict:
            return self._data.get(key, default)

        return getattr(self._data, key, default)

    def get_from_metadata(self, key: str, default: Any = None) -> Any:
        """Get a value from the metadata sub-object.

        Args:
            key: The key to look up in metadata
            default: Default value if not found

        Returns:
            The value or default
        """
        if self._data is None:
            return default

        metadata = None
        if self._is_dict:
            metadata = self._data.get("metadata")
        else:
            metadata = getattr(self._data, "metadata", None)

        if metadata is None:
            return default

        if isinstance(metadata, dict):
            return metadata.get(key, default)

        return getattr(metadata, key, default)

    def get_tenant_id(self) -> str | None:
        """Get tenant_id from state (common pattern)."""
        # Try direct access first
        tenant_id = self.get("tenant_id")
        if tenant_id:
            return tenant_id

        # Try metadata
        tenant_id = self.get_from_metadata("tenant_id")
        if tenant_id:
            return tenant_id

        # Try org_id as fallback
        return self.get("org_id") or self.get_from_metadata("org_id")

    def get_user_id(self) -> str | None:
        """Get user_id from state (common pattern)."""
        return self.get("user_id") or self.get_from_metadata("user_id")

    def get_redirect_url(self, default: str = "") -> str:
        """Get redirect_url from state."""
        return self.get("redirect_url", default) or default

    def get_workspace_id(self) -> str | None:
        """Get workspace_id from state."""
        return self.get("workspace_id") or self.get_from_metadata("workspace_id")

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary representation."""
        if self._data is None:
            return {}
        if self._is_dict:
            return dict(self._data)
        # Convert object to dict
        result = {}
        for attr in [
            "tenant_id",
            "user_id",
            "redirect_url",
            "workspace_id",
            "org_id",
            "metadata",
        ]:
            val = getattr(self._data, attr, None)
            if val is not None:
                result[attr] = val
        return result


# =============================================================================
# OAuth Permission Helper (consolidates ~40 lines per handler)
# =============================================================================


@dataclass
class PermissionCheckResult:
    """Result of permission check."""

    allowed: bool
    error_response: Any | None = None
    permission_used: str = ""
    fallback_used: bool = False


class OAuthPermissionHelper:
    """Unified OAuth permission checking.

    Consolidates permission check patterns from:
    - slack_oauth.py:203-249, 378-388, 409-420, 432-443
    - teams_oauth.py:126-156, 232-237, 248-249, 260-265
    - base.py:276-311

    Usage:
        helper = OAuthPermissionHelper()
        result = helper.check(
            handler=self,
            auth_context=auth_context,
            permission="slack.oauth.install",
            fallback="connectors.authorize",
        )
        if not result.allowed:
            return result.error_response
    """

    def check(
        self,
        handler: Any,
        auth_context: Any,
        permission: str,
        fallback_permission: str | None = None,
        resource_id: str | None = None,
    ) -> PermissionCheckResult:
        """Check if user has required permission.

        Args:
            handler: The HTTP handler instance
            auth_context: Authorization context with user info
            permission: Primary permission to check
            fallback_permission: Fallback permission if primary fails
            resource_id: Optional resource ID for resource-level permissions

        Returns:
            PermissionCheckResult with allowed status and error response if denied
        """
        # Try primary permission
        error = None
        try:
            error = self._check_single_permission(handler, auth_context, permission, resource_id)
            if error is None:
                return PermissionCheckResult(
                    allowed=True,
                    permission_used=permission,
                    fallback_used=False,
                )
        except (ValueError, AttributeError, TypeError, KeyError, ImportError) as e:
            logger.debug("Permission check failed for %s: %s", permission, e)

        # Try fallback if provided
        if fallback_permission and error is not None:
            try:
                fallback_error = self._check_single_permission(
                    handler, auth_context, fallback_permission, resource_id
                )
                if fallback_error is None:
                    return PermissionCheckResult(
                        allowed=True,
                        permission_used=fallback_permission,
                        fallback_used=True,
                    )
                error = fallback_error
            except (ValueError, AttributeError, TypeError, KeyError, ImportError) as e:
                logger.debug("Fallback permission check failed for %s: %s", fallback_permission, e)

        return PermissionCheckResult(
            allowed=False,
            error_response=error,
            permission_used=permission,
        )

    def _check_single_permission(
        self,
        handler: Any,
        auth_context: Any,
        permission: str,
        resource_id: str | None,
    ) -> Any | None:
        """Check a single permission.

        Returns:
            None if allowed, error response if denied
        """
        # Use handler's _check_permission if available
        if hasattr(handler, "_check_permission"):
            return handler._check_permission(auth_context, permission, resource_id)

        # Fallback to RBAC checker
        try:
            from aragora.rbac.checker import get_permission_checker

            checker = get_permission_checker()
            if checker.check_permission(auth_context, permission, resource_id).allowed:
                return None

            # Build error response
            from aragora.server.handlers.base import json_response

            return json_response(
                {"error": "forbidden", "message": "Permission denied"},
                status=403,
            )
        except ImportError:
            logger.debug("RBAC checker not available")
            return None  # Allow if no checker available


# Singleton for convenience
_oauth_permission_helper: OAuthPermissionHelper | None = None


def get_oauth_permission_helper() -> OAuthPermissionHelper:
    """Get or create the OAuth permission helper singleton."""
    global _oauth_permission_helper
    if _oauth_permission_helper is None:
        _oauth_permission_helper = OAuthPermissionHelper()
    return _oauth_permission_helper
