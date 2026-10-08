"""
Supabase JWT Authentication Middleware - Core Implementation.

Provides comprehensive user authentication via Supabase Auth JWTs.
Supports both session tokens (browser) and API keys (programmatic).

This is the primary authentication implementation. The companion auth.py
module provides simplified decorator wrappers (@require_auth, @optional_auth)
for basic token validation. Both modules are exported through __init__.py.

Module Structure:
- user_auth.py (this file): Full implementation (User, Workspace, JWT, Supabase)
- auth.py: Simple decorators for basic auth flows

Key exports:
- User, Workspace, APIKey: Data classes for authenticated entities
- require_user, require_admin: Decorators requiring user authentication
- authenticate_request: Function to authenticate a request
- get_current_user: Get the authenticated user from context

Usage:
    from aragora.server.middleware import require_user, get_current_user, User

    @require_user
    async def protected_endpoint(request, user: User):
        return {"user_id": user.id}
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import warnings
from dataclasses import dataclass, field
from functools import wraps
from typing import TYPE_CHECKING, Any, Protocol, cast
from collections.abc import Callable

from aragora.utils.request_ip import extract_client_ip as _extract_client_ip

if TYPE_CHECKING:
    pass


# Stub exception classes for when PyJWT is not installed
# Defined unconditionally so type checker sees them
class _ExpiredSignatureError(Exception):
    """Stub for jwt.exceptions.ExpiredSignatureError."""

    pass


class _InvalidSignatureError(Exception):
    """Stub for jwt.exceptions.InvalidSignatureError."""

    pass


class _DecodeError(Exception):
    """Stub for jwt.exceptions.DecodeError."""

    pass


class _InvalidTokenError(Exception):
    """Stub for jwt.exceptions.InvalidTokenError."""

    pass


class _InvalidAudienceError(Exception):
    """Stub for jwt.exceptions.InvalidAudienceError."""

    pass


class _JWTModuleProtocol(Protocol):
    """Protocol for the jwt module to satisfy type checker."""

    def decode(
        self,
        jwt: str,
        key: str,
        algorithms: list[str] | None = None,
        audience: str | None = None,
        issuer: str | None = None,
    ) -> dict[str, Any]: ...


# JWT validation (PyJWT optional; auth fails closed if unavailable)
try:
    import jwt as _jwt  # type: ignore[import-not-found]

    _jwt_module: _JWTModuleProtocol | None = cast(_JWTModuleProtocol, _jwt)
    HAS_JWT = True

    # Use real exception classes from jwt
    from jwt.exceptions import DecodeError as _RealDecodeError
    from jwt.exceptions import ExpiredSignatureError as _RealExpiredSignatureError
    from jwt.exceptions import InvalidAudienceError as _RealInvalidAudienceError
    from jwt.exceptions import InvalidSignatureError as _RealInvalidSignatureError
    from jwt.exceptions import InvalidTokenError as _RealInvalidTokenError

    ExpiredSignatureError: type[Exception] = _RealExpiredSignatureError
    InvalidSignatureError: type[Exception] = _RealInvalidSignatureError
    DecodeError: type[Exception] = _RealDecodeError
    InvalidTokenError: type[Exception] = _RealInvalidTokenError
    InvalidAudienceError: type[Exception] = _RealInvalidAudienceError
except ImportError:
    _jwt_module = None
    HAS_JWT = False
    ExpiredSignatureError = _ExpiredSignatureError
    InvalidSignatureError = _InvalidSignatureError
    DecodeError = _DecodeError
    InvalidTokenError = _InvalidTokenError
    InvalidAudienceError = _InvalidAudienceError

logger = logging.getLogger(__name__)

# =============================================================================
# Data Models
# =============================================================================


@dataclass
class User:
    """Authenticated user from Supabase."""

    id: str
    email: str
    role: str = "user"  # user, admin, service
    metadata: dict[str, Any] = field(default_factory=dict)

    # Subscription info
    plan: str = "free"  # free, pro, team, enterprise
    workspace_id: str | None = None

    # Timestamps
    created_at: str | None = None
    last_sign_in: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_pro(self) -> bool:
        return self.plan in ("pro", "team", "enterprise")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "role": self.role,
            "plan": self.plan,
            "workspace_id": self.workspace_id,
            "is_admin": self.is_admin,
            "is_pro": self.is_pro,
        }


@dataclass
class Workspace:
    """Multi-tenant workspace."""

    id: str
    name: str
    owner_id: str
    plan: str = "free"

    # Limits based on plan
    max_debates: int = 50
    max_agents: int = 2
    max_members: int = 1

    # Members
    member_ids: list[str] = field(default_factory=list)

    # Settings
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "owner_id": self.owner_id,
            "plan": self.plan,
            "max_debates": self.max_debates,
            "max_agents": self.max_agents,
            "max_members": self.max_members,
            "member_count": len(self.member_ids) + 1,  # +1 for owner
        }


@dataclass
class APIKey:
    """API key for programmatic access."""

    id: str
    user_id: str
    workspace_id: str
    name: str
    key_hash: str  # Store hash, not the key itself
    prefix: str  # First 8 chars for identification (e.g., "ara_xxxx")

    # Permissions
    scopes: list[str] = field(default_factory=lambda: ["read", "write"])

    # Metadata
    created_at: str | None = None
    last_used_at: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "prefix": self.prefix,
            "scopes": self.scopes,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }


# =============================================================================
# Supabase JWT Validator
# =============================================================================


class SupabaseAuthValidator:
    """
    Validates Supabase Auth JWTs.

    Supports:
    - JWT signature verification (HS256)
    - Token expiration checking
    - Role/claims extraction
    """

    #: Minimum JWT secret length required in production to prevent brute-force attacks.
    _MIN_JWT_SECRET_LENGTH: int = 32

    def __init__(self, jwt_secret: str | None = None, supabase_url: str | None = None):
        self.jwt_secret = jwt_secret or os.getenv("SUPABASE_JWT_SECRET")
        self.supabase_url = supabase_url or os.getenv("SUPABASE_URL")

        # SECURITY: Enforce minimum JWT secret length in production.
        # Short secrets are vulnerable to brute-force / dictionary attacks.
        env = os.getenv("ARAGORA_ENV", "development").lower()
        is_production = env in ("production", "staging")
        if is_production and self.jwt_secret and len(self.jwt_secret) < self._MIN_JWT_SECRET_LENGTH:
            raise RuntimeError(
                f"SUPABASE_JWT_SECRET is too short ({len(self.jwt_secret)} chars). "
                f"Production requires at least {self._MIN_JWT_SECRET_LENGTH} characters. "
                'Generate a strong secret with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )

        # Cache for validated tokens (short TTL)
        # Stores: (user, cached_at, token_exp) keyed by SHA-256 hash of token.
        # SECURITY: Raw tokens are NOT stored as dictionary keys to prevent
        # extraction from memory dumps. Only the hash is used as the key.
        self._cache: dict[str, tuple[User, float, float]] = {}
        self._cache_ttl = 30  # 30 seconds (reduced from 60s for revocation safety)
        self._cache_max_size = 10_000  # Prevent unbounded growth

    @staticmethod
    def _hash_token(token: str) -> str:
        """Hash a token for use as a cache key.

        SECURITY: We never store raw tokens as dict keys. Using SHA-256
        means a memory dump will not reveal the original token values.
        """
        return hashlib.sha256(token.encode()).hexdigest()

    def validate_jwt(self, token: str) -> User | None:
        """
        Validate a Supabase JWT and return user info.

        Args:
            token: JWT from Supabase Auth

        Returns:
            User object if valid, None otherwise
        """
        if not token:
            return None

        # Check cache first (using hashed token as key)
        cache_key = self._hash_token(token)
        if cache_key in self._cache:
            user, cached_at, token_exp = self._cache[cache_key]
            now = time.time()
            # Must pass BOTH cache freshness AND token expiration
            if now - cached_at < self._cache_ttl and now < token_exp:
                return user
            else:
                # Cache stale or token expired - remove it
                del self._cache[cache_key]
                if now >= token_exp:
                    logger.debug("Cached token expired, re-validating")
                    return None  # Don't re-validate expired tokens

        try:
            if HAS_JWT and self.jwt_secret and _jwt_module is not None:
                # Use PyJWT for proper validation
                # Build decode options with audience; add issuer if URL is configured
                issuer: str | None = None
                if self.supabase_url:
                    # Supabase issuer format: {SUPABASE_URL}/auth/v1
                    issuer = f"{self.supabase_url.rstrip('/')}/auth/v1"
                payload = _jwt_module.decode(
                    token,
                    self.jwt_secret,
                    algorithms=["HS256"],
                    audience="authenticated",
                    issuer=issuer,
                )
            else:
                # SECURITY: Require proper JWT validation in all environments
                # Unsafe fallback is ONLY allowed when explicitly opted-in via env var
                env = os.getenv("ARAGORA_ENVIRONMENT", "").lower()
                # Check multiple production indicators
                is_production = env in ("production", "prod", "staging", "live") or not env
                # Explicit opt-in required for insecure mode (dev/local testing only)
                allow_insecure = os.getenv("ARAGORA_ALLOW_INSECURE_JWT", "").lower() in (
                    "1",
                    "true",
                    "yes",
                )

                if is_production or not allow_insecure:
                    if not HAS_JWT:
                        logger.error("JWT validation unavailable. Install PyJWT: pip install pyjwt")
                    if not self.jwt_secret:
                        logger.error(
                            "SUPABASE_JWT_SECRET not set. JWT validation requires this secret."
                        )
                    if not is_production and not allow_insecure:
                        logger.warning(
                            "JWT validation disabled. To enable insecure development mode, "
                            "set ARAGORA_ALLOW_INSECURE_JWT=1 (NOT for production!)"
                        )
                    return None

                # Fallback: decode without verification (ONLY with explicit opt-in!)
                logger.warning(
                    "INSECURE: Decoding JWT without signature verification. "
                    "This should NEVER be used in production! "
                    "Install PyJWT and set SUPABASE_JWT_SECRET."
                )
                unsafe_payload = self._decode_jwt_unsafe(token)
                if not unsafe_payload:
                    return None
                payload = unsafe_payload
                # Audit log the insecure decode event
                try:
                    from aragora.audit.unified import audit_security

                    audit_security(
                        event_type="insecure_jwt_decode",
                        actor_id=payload.get("sub", "unknown"),
                        reason="jwt_secret_or_pyjwt_unavailable",
                        details={"sub": payload.get("sub"), "env": env},
                    )
                except ImportError:
                    logger.error(
                        "SECURITY AUDIT: insecure JWT decode for sub=%s (audit module unavailable)",
                        payload.get("sub"),
                    )

            # Extract user info
            user = self._payload_to_user(payload)

            # Cache the result with token expiration time (keyed by hash, not raw token)
            # Default to cache_ttl from now if no exp claim (shouldn't happen with valid JWTs)
            token_exp = payload.get("exp", time.time() + self._cache_ttl)

            # Evict stale entries when cache is at capacity
            if len(self._cache) >= self._cache_max_size:
                self._evict_stale_cache_entries()

            self._cache[cache_key] = (user, time.time(), token_exp)

            return user

        except ExpiredSignatureError:
            # Token has expired - this is expected for old sessions
            logger.debug("JWT token expired")
            return None
        except InvalidAudienceError:
            # Token was issued for a different audience
            logger.warning("JWT has invalid audience claim")
            return None
        except (InvalidSignatureError, DecodeError) as e:
            # Token signature invalid or malformed - potential tampering
            logger.warning("JWT signature/decode error: %s", e)
            return None
        except InvalidTokenError as e:
            # Catch-all for other JWT validation errors
            logger.warning("JWT validation error: %s", e)
            return None
        except (KeyError, ValueError, TypeError) as e:
            # Malformed token structure or payload
            logger.warning("JWT structure error: %s", e)
            return None
        except (RuntimeError, OSError, AttributeError) as e:
            # Unexpected system error - always fail closed.
            # Never silently bypass auth, even in dev mode.
            logger.error("JWT validation system error (failing closed): %s", e)
            raise  # Re-raise to trigger 500 error, don't silently allow

    def _evict_stale_cache_entries(self) -> None:
        """Remove expired and oldest entries when cache is at capacity."""
        now = time.time()
        # First pass: remove expired entries
        expired = [
            tok
            for tok, (_, cached_at, token_exp) in self._cache.items()
            if now - cached_at >= self._cache_ttl or now >= token_exp
        ]
        for tok in expired:
            del self._cache[tok]

        # If still over capacity, remove oldest 25%
        if len(self._cache) >= self._cache_max_size:
            sorted_tokens = sorted(
                self._cache.keys(),
                key=lambda t: self._cache[t][1],  # sort by cached_at
            )
            evict_count = len(sorted_tokens) // 4
            for tok in sorted_tokens[:evict_count]:
                del self._cache[tok]
            logger.debug("Evicted %d stale JWT cache entries", evict_count + len(expired))

    def _decode_jwt_unsafe(self, token: str) -> dict[str, Any] | None:
        """
        Decode JWT without signature verification.
        WARNING: Only use in development!
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            # Decode payload (second part)
            payload_b64 = parts[1]
            # Add padding if needed
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding

            payload_json = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_json)

            # Require expiration claim
            if "exp" not in payload:
                logger.warning("JWT missing required exp claim - rejecting")
                return None
            if payload["exp"] < time.time():
                logger.debug("JWT expired")
                return None

            # Require subject claim to prevent empty/anonymous user creation
            if "sub" not in payload or not payload["sub"]:
                logger.warning("JWT missing required sub claim - rejecting")
                return None

            return payload

        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as e:
            logger.warning("JWT decode failed: %s", e)
            return None

    def _payload_to_user(self, payload: dict[str, Any]) -> User:
        """Convert JWT payload to User object."""
        # Supabase JWT structure
        user_meta = payload.get("user_metadata", {})
        app_meta = payload.get("app_metadata", {})

        return User(
            id=payload.get("sub", ""),
            email=payload.get("email", ""),
            role=payload.get("role", "user"),
            metadata=user_meta,
            plan=app_meta.get("plan", "free"),
            workspace_id=app_meta.get("workspace_id"),
            last_sign_in=payload.get("iat"),
        )

    def clear_cache(self):
        """Clear the token cache."""
        self._cache.clear()


# =============================================================================
# API Key Validator
# =============================================================================


class APIKeyValidator:
    """
    Validates API keys for programmatic access.

    API keys are stored as hashes in the database.
    Format: ara_<random>
    """

    def __init__(self, storage: Any | None = None):
        self._storage = storage
        # SECURITY: Cache keyed by SHA-256 hash of API key, not the raw key.
        self._cache: dict[str, tuple[User, float]] = {}
        self._cache_ttl = 300  # 5 minutes

    @staticmethod
    def _hash_key(key: str) -> str:
        """Hash an API key for use as a cache key."""
        return hashlib.sha256(key.encode()).hexdigest()

    async def validate_key(self, key: str) -> User | None:
        """
        Validate an API key and return associated user.

        Args:
            key: API key (format: ara_xxxx...)

        Returns:
            User object if valid, None otherwise
        """
        if not key or not key.startswith("ara_"):
            return None

        # Check cache (using hashed key, not raw API key)
        cache_key = self._hash_key(key)
        if cache_key in self._cache:
            user, cached_at = self._cache[cache_key]
            if time.time() - cached_at < self._cache_ttl:
                return user
            else:
                del self._cache[cache_key]

        # Look up key in storage
        try:
            key_hash = hashlib.sha256(key.encode()).hexdigest()

            # Query storage for key
            if self._storage:
                api_key_record = await self._storage.get_api_key_by_hash(key_hash)
                if api_key_record:
                    user = await self._storage.get_user(api_key_record["user_id"])
                    if user:
                        # Update last_used
                        await self._storage.update_api_key_usage(api_key_record["id"])
                        self._cache[cache_key] = (user, time.time())
                        return user

        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            logger.warning("API key validation failed: %s", e)

        return None


# =============================================================================
# Global Instances
# =============================================================================

# Singleton validators
_jwt_validator: SupabaseAuthValidator | None = None
_api_key_validator: APIKeyValidator | None = None


def get_jwt_validator() -> SupabaseAuthValidator:
    """Get the global JWT validator."""
    global _jwt_validator
    if _jwt_validator is None:
        _jwt_validator = SupabaseAuthValidator()
    return _jwt_validator


def get_api_key_validator() -> APIKeyValidator:
    """Get the global API key validator."""
    global _api_key_validator
    if _api_key_validator is None:
        _api_key_validator = APIKeyValidator()
    return _api_key_validator


# =============================================================================
# Authentication Functions
# =============================================================================


def extract_auth_token(handler: Any) -> str | None:
    """Extract Bearer token or API key from request."""
    if handler is None:
        return None

    auth_header = None
    if hasattr(handler, "headers"):
        auth_header = handler.headers.get("Authorization", "")

    if not auth_header:
        return None

    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    elif auth_header.startswith("ApiKey "):
        return auth_header[7:]

    return auth_header


def extract_token(handler: Any) -> str | None:
    """
    Extract Bearer token from request handler.

    Only extracts Bearer tokens. For broader token extraction
    (including ApiKey), use extract_auth_token.

    Args:
        handler: HTTP request handler with headers attribute.

    Returns:
        Token string or None if not present or not Bearer type.
    """
    if handler is None:
        return None

    auth_header = None
    if hasattr(handler, "headers"):
        auth_header = handler.headers.get("Authorization", "")

    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]

    return None


def extract_client_ip(handler: Any) -> str | None:
    """Compatibility wrapper for the foundation request-IP utility."""
    warnings.warn(
        "aragora.server.middleware.user_auth.extract_client_ip is deprecated; "
        "import aragora.utils.request_ip.extract_client_ip instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _extract_client_ip(handler)


async def authenticate_request(handler: Any) -> User | None:
    """
    Authenticate a request and return user.

    Tries JWT first, then API key.
    Optionally records auth events for anomaly detection when the
    anomaly detection service is enabled (``ARAGORA_ANOMALY_DETECTION=1``).

    Args:
        handler: HTTP request handler

    Returns:
        User if authenticated, None otherwise
    """
    token = extract_auth_token(handler)
    if not token:
        return None

    client_ip = _extract_client_ip(handler)
    user_agent: str | None = None
    if hasattr(handler, "headers"):
        user_agent = handler.headers.get("User-Agent")

    # Try JWT first
    jwt_validator = get_jwt_validator()
    user = jwt_validator.validate_jwt(token)
    if user:
        # Record successful auth for baseline learning
        await _record_auth_anomaly(
            user_id=user.id,
            success=True,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        return user

    # Try API key
    if token.startswith("ara_"):
        api_validator = get_api_key_validator()
        user = await api_validator.validate_key(token)
        if user:
            await _record_auth_anomaly(
                user_id=user.id,
                success=True,
                ip_address=client_ip,
                user_agent=user_agent,
            )
            return user

    # Auth failed -- record for brute-force / credential-stuffing detection.
    # We don't know the user_id, so use the IP for tracking.
    await _record_auth_anomaly(
        user_id=f"unknown:{client_ip or 'no-ip'}",
        success=False,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    return None


async def _record_auth_anomaly(
    user_id: str,
    success: bool,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Fire-and-forget anomaly detection check for an auth event.

    This is intentionally non-blocking: anomaly detection must never
    break the authentication flow.  The function is a no-op unless
    ``ARAGORA_ANOMALY_DETECTION`` is set to ``1`` in the environment.
    """
    try:
        if not os.getenv("ARAGORA_ANOMALY_DETECTION"):
            return

        from aragora.security.anomaly_detection import get_anomaly_detector

        detector = get_anomaly_detector()
        result = await detector.check_auth_event(
            user_id=user_id,
            success=success,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        if result.is_anomalous:
            logger.warning(
                "Auth anomaly detected: type=%s severity=%s ip=%s user=%s desc=%s",
                result.anomaly_type.value if result.anomaly_type else "unknown",
                result.severity.value,
                ip_address,
                user_id,
                result.description,
            )
    except (ImportError, RuntimeError, OSError, TypeError, ValueError) as exc:
        # Anomaly detection is optional -- never let it break auth
        logger.debug("Anomaly detection unavailable during auth: %s", exc)


def get_current_user(handler: Any) -> User | None:
    """
    Get the current authenticated user (sync version).

    For async handlers, use authenticate_request instead.
    """
    token = extract_auth_token(handler)
    if not token:
        return None

    jwt_validator = get_jwt_validator()
    return jwt_validator.validate_jwt(token)


# =============================================================================
# Decorators
# =============================================================================


def require_user(func: Callable) -> Callable:
    """
    Decorator that requires authenticated user.

    Injects 'user' keyword argument to the handler.

    Usage:
        @require_user
        def endpoint(self, handler, user: User):
            return {"user_id": user.id}
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        from aragora.server.handlers.base import error_response

        # Extract handler
        handler = kwargs.get("handler")
        if handler is None:
            for arg in args:
                if hasattr(arg, "headers"):
                    handler = arg
                    break

        if handler is None:
            return error_response("No request handler", 500)

        # Authenticate
        user = get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        # Inject user
        kwargs["user"] = user
        return func(*args, **kwargs)

    return wrapper


def require_admin(func: Callable) -> Callable:
    """
    Decorator that requires admin user.

    Usage:
        @require_admin
        def admin_endpoint(self, handler, user: User):
            ...
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        from aragora.server.handlers.base import error_response

        # Extract handler
        handler = kwargs.get("handler")
        if handler is None:
            for arg in args:
                if hasattr(arg, "headers"):
                    handler = arg
                    break

        if handler is None:
            return error_response("No request handler", 500)

        # Authenticate
        user = get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        if not user.is_admin:
            return error_response("Admin access required", 403)

        kwargs["user"] = user
        return func(*args, **kwargs)

    return wrapper


def require_plan(min_plan: str) -> Callable:
    """
    Decorator that requires a minimum subscription plan.

    Args:
        min_plan: Minimum plan required (free, pro, team, enterprise)

    Usage:
        @require_plan("pro")
        def pro_endpoint(self, handler, user: User):
            ...
    """
    plan_levels = {"free": 0, "pro": 1, "team": 2, "enterprise": 3}
    min_level = plan_levels.get(min_plan, 0)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            from aragora.server.handlers.base import error_response

            handler = kwargs.get("handler")
            if handler is None:
                for arg in args:
                    if hasattr(arg, "headers"):
                        handler = arg
                        break

            user = get_current_user(handler)
            if not user:
                return error_response("Authentication required", 401)

            user_level = plan_levels.get(user.plan, 0)
            if user_level < min_level:
                return error_response(
                    f"This feature requires {min_plan} plan or higher",
                    403,
                )

            kwargs["user"] = user
            return func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    # Models
    "User",
    "Workspace",
    "APIKey",
    # Validators
    "SupabaseAuthValidator",
    "APIKeyValidator",
    "get_jwt_validator",
    "get_api_key_validator",
    # Functions
    "authenticate_request",
    "get_current_user",
    "extract_auth_token",
    "extract_token",  # Alias for backward compatibility
    "extract_client_ip",
    # Decorators
    "require_user",
    "require_admin",
    "require_plan",
]
