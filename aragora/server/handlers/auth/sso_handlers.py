"""
HTTP API Handlers for SSO Authentication.

Provides REST APIs for SSO/OIDC authentication flow:
- Initiate SSO login
- Handle OAuth/OIDC callback
- Refresh tokens
- Logout

Endpoints:
- GET /api/v1/auth/sso/login - Get SSO authorization URL
- GET /api/v1/auth/sso/callback - Handle OAuth callback
- POST /api/v1/auth/sso/refresh - Refresh access token
- POST /api/v1/auth/sso/logout - Logout from SSO
- GET /api/v1/auth/sso/providers - List available providers
- GET /api/v1/auth/sso/config - Get provider configuration
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from aragora.config import resolve_db_path
from aragora.api_errors import safe_error_message
from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    success_response,
)
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.utils.lazy_stores import LazyStore
from aragora.server.handlers.utils.rate_limit import auth_rate_limit
from aragora.server.oauth_state_store import (
    OAUTH_STATE_TTL_SECONDS,
    get_oauth_state_store,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IdP Circuit Breaker — protects against cascading failures when an IdP
# (Okta, Azure AD, Google, etc.) becomes unavailable or slow.
# ---------------------------------------------------------------------------
_idp_circuit_breakers: dict[str, Any] = {}
_idp_cb_lock = threading.Lock()

# Retry configuration for IdP token exchange
_IDP_MAX_RETRIES = 2
_IDP_RETRY_DELAY_SECONDS = 0.5


def _get_idp_circuit_breaker(provider_type: str) -> Any:
    """Get or create a circuit breaker for the given IdP provider."""
    with _idp_cb_lock:
        if provider_type not in _idp_circuit_breakers:
            try:
                from aragora.resilience.circuit_breaker import CircuitBreaker

                _idp_circuit_breakers[provider_type] = CircuitBreaker(
                    name=f"idp-{provider_type}",
                    failure_threshold=3,
                    cooldown_seconds=60.0,
                    half_open_success_threshold=1,
                )
            except ImportError:
                logger.debug("Circuit breaker module unavailable, skipping IdP protection")
                return None
        return _idp_circuit_breakers[provider_type]


async def _authenticate_with_retry(
    provider: Any,
    code: str,
    state: str,
    provider_type: str,
) -> Any:
    """Authenticate with IdP, with retry and circuit breaker protection.

    Retries transient network failures (ConnectionError, TimeoutError)
    up to _IDP_MAX_RETRIES times with exponential backoff. Skips retry
    for authentication/validation errors.
    """
    import asyncio

    cb = _get_idp_circuit_breaker(provider_type)

    # Check circuit breaker state
    if cb is not None and not cb.can_proceed():
        logger.warning(
            "IdP circuit breaker OPEN for provider=%s, failing fast",
            provider_type,
        )
        raise ConnectionError(
            f"IdP provider '{provider_type}' is temporarily unavailable (circuit open)"
        )

    last_error: Exception | None = None
    for attempt in range(_IDP_MAX_RETRIES + 1):
        try:
            result = await provider.authenticate(code=code, state=state)
            # Record success with circuit breaker
            if cb is not None:
                cb.record_success()
            return result
        except (ConnectionError, TimeoutError, OSError) as e:
            last_error = e
            if cb is not None:
                cb.record_failure()
            if attempt < _IDP_MAX_RETRIES:
                delay = _IDP_RETRY_DELAY_SECONDS * (2**attempt)
                logger.warning(
                    "IdP auth attempt %d/%d failed for provider=%s: %s, retrying in %.1fs",
                    attempt + 1,
                    _IDP_MAX_RETRIES + 1,
                    provider_type,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "IdP auth failed after %d attempts for provider=%s: %s",
                    _IDP_MAX_RETRIES + 1,
                    provider_type,
                    e,
                )
        except (ValueError, KeyError):
            # Non-retryable authentication errors
            if cb is not None:
                cb.record_failure()
            raise

    # All retries exhausted
    if last_error:
        raise last_error
    raise ConnectionError(f"IdP authentication failed for provider '{provider_type}'")


# Thread-safe SSO provider instances
_sso_providers: dict[str, Any] = {}
_sso_providers_lock = threading.Lock()

# In-memory auth sessions (used alongside the state store for session tracking)
_auth_sessions: dict[str, dict[str, Any]] = {}

# OAuth state store singleton (supports Redis/SQLite/JWT for multi-instance deployments)
_sso_state_store = LazyStore(
    factory=lambda: get_oauth_state_store(
        sqlite_path=resolve_db_path("aragora_sso_state.db"),
        use_sqlite=True,
        use_jwt=True,
    ),
    store_name="sso_state_store",
    logger_context="SSO",
)

# Session TTL (use OAuth state store TTL for consistency)
AUTH_SESSION_TTL = OAUTH_STATE_TTL_SECONDS


def _cleanup_expired_sessions() -> None:
    """Remove expired sessions from the in-memory auth sessions dict."""
    now = time.time()
    expired = [
        key
        for key, session in _auth_sessions.items()
        if now - session.get("created_at", 0) > AUTH_SESSION_TTL
    ]
    for key in expired:
        del _auth_sessions[key]


def _get_sso_provider(provider_type: str = "oidc"):
    """Get or create SSO provider for type."""
    with _sso_providers_lock:
        if provider_type in _sso_providers:
            return _sso_providers[provider_type]

        try:
            if provider_type == "oidc":
                from aragora.auth.oidc import OIDCConfig, OIDCProvider
                from aragora.auth.sso import SSOProviderType

                # Get configuration from environment
                config = OIDCConfig(
                    provider_type=SSOProviderType.OIDC,
                    client_id=os.environ.get("OIDC_CLIENT_ID", ""),
                    client_secret=os.environ.get("OIDC_CLIENT_SECRET", ""),
                    issuer_url=os.environ.get("OIDC_ISSUER_URL", ""),
                    callback_url=os.environ.get(
                        "OIDC_CALLBACK_URL",
                        "http://localhost:8080/api/v1/auth/sso/callback",
                    ),
                    scopes=os.environ.get("OIDC_SCOPES", "openid,email,profile").split(","),
                )

                if config.client_id and config.issuer_url:
                    provider = OIDCProvider(config)
                    _sso_providers[provider_type] = provider
                    return provider

            elif provider_type == "google":
                from aragora.auth.oidc import OIDCConfig, OIDCProvider
                from aragora.auth.sso import SSOProviderType

                config = OIDCConfig(
                    provider_type=SSOProviderType.GOOGLE,
                    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
                    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
                    issuer_url="https://accounts.google.com",
                    callback_url=os.environ.get(
                        "GOOGLE_CALLBACK_URL",
                        "http://localhost:8080/api/v1/auth/sso/callback",
                    ),
                    scopes=["openid", "email", "profile"],
                )

                if config.client_id:
                    provider = OIDCProvider(config)
                    _sso_providers[provider_type] = provider
                    return provider

            elif provider_type == "github":
                from aragora.auth.oidc import OIDCConfig, OIDCProvider
                from aragora.auth.sso import SSOProviderType

                config = OIDCConfig(
                    client_id=os.environ.get("GITHUB_CLIENT_ID", ""),
                    client_secret=os.environ.get("GITHUB_CLIENT_SECRET", ""),
                    authorization_endpoint="https://github.com/login/oauth/authorize",
                    token_endpoint="https://github.com/login/oauth/access_token",  # noqa: S106 - OAuth config field name, not a secret
                    userinfo_endpoint="https://api.github.com/user",
                    callback_url=os.environ.get(
                        "GITHUB_CALLBACK_URL",
                        "http://localhost:8080/api/v1/auth/sso/callback",
                    ),
                    scopes=["user:email", "read:user"],
                    use_pkce=False,  # GitHub doesn't support PKCE
                    provider_type=SSOProviderType.GITHUB,
                )

                if config.client_id:
                    provider = OIDCProvider(config)
                    _sso_providers[provider_type] = provider
                    return provider

            return None

        except (ImportError, ConnectionError, ValueError, TypeError) as e:
            logger.warning("Failed to initialize SSO provider %s: %s", provider_type, e)
            return None


# =============================================================================
# SSO Login Flow
# =============================================================================


# NOTE: SSO login is a public endpoint - users must be able to initiate SSO
# authentication before they have a token. RBAC protection via middleware.
@auth_rate_limit(
    requests_per_minute=20,
    limiter_name="auth_sso_login",
    endpoint_name="SSO login initiation",
)
async def handle_sso_login(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Initiate SSO login flow.

    GET /api/v1/auth/sso/login
    Query params:
        provider: str (optional, default "oidc") - Provider type
        redirect_url: str (optional) - Where to redirect after auth
    """
    try:
        provider_type = data.get("provider", "oidc")
        redirect_url = data.get("redirect_url", "/")

        provider = _get_sso_provider(provider_type)
        if not provider:
            return error_response(
                f"SSO provider '{provider_type}' not configured",
                status=503,
            )

        # Generate state token using OAuth state store (supports Redis/SQLite/JWT)
        state_store = _sso_state_store.get()
        state = state_store.generate(
            redirect_url=redirect_url,
            metadata={"provider_type": provider_type},
        )

        # Store session in-memory for quick lookup (kept alongside state store)
        _cleanup_expired_sessions()
        _auth_sessions[state] = {
            "created_at": time.time(),
            "redirect_url": redirect_url,
            "provider_type": provider_type,
        }

        # Get authorization URL
        auth_url = await provider.get_authorization_url(state=state)

        return success_response(
            {
                "authorization_url": auth_url,
                "state": state,
                "provider": provider_type,
                "expires_in": AUTH_SESSION_TTL,
            }
        )

    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        logger.exception("SSO login initiation failed")
        return error_response(safe_error_message(e, "SSO login"), status=500)


# NOTE: SSO callback is a public endpoint - IdP redirects here before user
# has our token. RBAC protection via middleware.
@auth_rate_limit(
    requests_per_minute=20,
    limiter_name="auth_sso_callback",
    endpoint_name="SSO callback",
)
async def handle_sso_callback(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Handle SSO callback from IdP.

    GET /api/v1/auth/sso/callback
    Query params:
        code: str - Authorization code
        state: str - State parameter for CSRF
        error: str (optional) - Error from IdP
        error_description: str (optional)
    """
    try:
        # Check for IdP error
        if data.get("error"):
            error_msg = data.get("error_description", data["error"])
            logger.warning("SSO callback error from IdP: %s", error_msg)
            return error_response(f"SSO error: {error_msg}", status=401)

        code = data.get("code")
        state = data.get("state")

        if not code:
            return error_response("No authorization code provided", status=400)
        if not state:
            return error_response("No state parameter provided", status=400)

        # Validate state using OAuth state store (atomic get-and-delete)
        # NOTE: State validation is timing-safe:
        # - JWTOAuthStateStore uses hmac.compare_digest() for signature verification
        # - InMemoryOAuthStateStore uses dictionary lookup (hash-based, constant-time)
        # - SQLiteOAuthStateStore uses SQL index lookup (not timing-vulnerable)
        # - RedisOAuthStateStore uses Redis key lookup (not timing-vulnerable)
        state_store = _sso_state_store.get()
        oauth_state = state_store.validate_and_consume(state)
        if not oauth_state:
            _cleanup_expired_sessions()
            session = _auth_sessions.pop(state, None)
            if not session:
                return error_response("Invalid or expired state", status=401)
            provider_type = session.get("provider_type", "oidc")
            redirect_url = session.get("redirect_url", "/")
        else:
            # Extract session data from state
            provider_type = (oauth_state.metadata or {}).get("provider_type", "oidc")
            redirect_url = oauth_state.redirect_url or "/"

        provider = _get_sso_provider(provider_type)
        if not provider:
            return error_response("SSO provider not available", status=503)

        # Authenticate with the provider (with retry + circuit breaker)
        sso_user = await _authenticate_with_retry(
            provider,
            code=code,
            state=state,
            provider_type=provider_type,
        )

        # Create or update user in our system
        from aragora.billing.jwt_auth import create_token_pair
        from aragora.storage.user_store.singleton import get_user_store

        user_store = get_user_store()
        if not user_store:
            logger.error("User store unavailable during SSO callback")
            return error_response("User service unavailable", 503)

        # Check if user already exists by email
        existing_user = user_store.get_user_by_email(sso_user.email)
        is_new_user = False

        if existing_user:
            # Update name from SSO provider if available
            sso_name = sso_user.name or sso_user.email.split("@")[0]
            if hasattr(user_store, "update_user"):
                user_store.update_user(existing_user.id, name=sso_name)
            user = user_store.get_user_by_id(existing_user.id) or existing_user

            # Link SSO provider to existing account if not already linked
            if hasattr(user_store, "link_oauth_provider"):
                try:
                    user_store.link_oauth_provider(
                        user_id=user.id,
                        provider=provider_type,
                        provider_user_id=sso_user.id,
                        email=sso_user.email,
                    )
                except (ValueError, AttributeError, TypeError) as link_err:
                    # Non-fatal: provider may already be linked
                    logger.debug(
                        "SSO provider linking for user %s: %s",
                        user.id,
                        link_err,
                    )
        else:
            is_new_user = True
            # Create new user (SSO users have no local password)
            user = user_store.create_user(
                email=sso_user.email,
                password_hash="sso",  # noqa: S106 - SSO placeholder (no local password); field name is not a secret
                password_salt="",
                name=sso_user.name or sso_user.email.split("@")[0],
            )

            # Link SSO provider to the new account
            if user and hasattr(user_store, "link_oauth_provider"):
                try:
                    user_store.link_oauth_provider(
                        user_id=user.id,
                        provider=provider_type,
                        provider_user_id=sso_user.id,
                        email=sso_user.email,
                    )
                except (ValueError, AttributeError, TypeError) as link_err:
                    logger.debug(
                        "SSO provider linking for new user %s: %s",
                        user.id,
                        link_err,
                    )

            # Auto-create a default organization for new OAuth users
            # so they have a complete profile on first login
            if user and not user.org_id:
                try:
                    sso_name = sso_user.name or sso_user.email.split("@")[0]
                    org_name = f"{sso_name}'s Organization"
                    if hasattr(user_store, "create_organization"):
                        user_store.create_organization(
                            name=org_name,
                            owner_id=user.id,
                        )
                        # Refresh user to get updated org_id
                        user = user_store.get_user_by_id(user.id) or user
                except (ValueError, AttributeError, TypeError) as org_err:
                    # Non-fatal: user can set up org later
                    logger.warning(
                        "Auto-org creation failed for SSO user %s: %s",
                        user.id,
                        org_err,
                    )

        if not user:
            logger.error(
                "Failed to create or retrieve user for SSO email %s",
                sso_user.email,
            )
            return error_response("User account creation failed", status=500)

        # Update last login timestamp
        if hasattr(user_store, "update_user"):
            try:
                from datetime import datetime, timezone

                user_store.update_user(user.id, last_login_at=datetime.now(timezone.utc))
            except (ValueError, AttributeError, TypeError):
                pass  # Non-fatal

        # Generate JWT token pair using Aragora user ID (not SSO provider ID)
        # Use create_token_pair to provide both access and refresh tokens
        tokens = create_token_pair(
            user_id=user.id,
            email=user.email,
            org_id=getattr(user, "org_id", None),
            role=getattr(user, "role", "member"),
        )

        # Bind session for session management tracking
        try:
            import hashlib

            from aragora.billing.auth.sessions import get_session_manager

            session_manager = get_session_manager()
            token_jti = hashlib.sha256(tokens.access_token.encode()).hexdigest()[:32]
            session_manager.create_session(
                user_id=user.id,
                token_jti=token_jti,
            )
        except (ImportError, AttributeError, TypeError, ValueError) as session_err:
            # Non-fatal: session tracking is optional
            logger.debug("Session tracking unavailable: %s", session_err)

        # Track session in health monitor for reliability metrics
        try:
            from aragora.auth.session_monitor import get_session_monitor

            monitor = get_session_monitor()
            monitor.track_session(
                session_id=token_jti if "token_jti" in dir() else tokens.access_token[:32],
                user_id=user.id,
                ip_address=data.get("client_ip"),
            )
            monitor.record_auth_success()
        except (ImportError, AttributeError, TypeError, ValueError) as monitor_err:
            # Non-fatal: monitoring is best-effort
            logger.debug("Session monitor tracking unavailable: %s", monitor_err)

        # Build organization data for frontend
        org_data = None
        org_membership = []
        if getattr(user, "org_id", None) and hasattr(user_store, "get_organization_by_id"):
            org = user_store.get_organization_by_id(user.org_id)
            if org:
                org_data = org.to_dict()
                joined_at = getattr(user, "created_at", None)
                org_membership = [
                    {
                        "user_id": user.id,
                        "org_id": user.org_id,
                        "organization": org_data,
                        "role": getattr(user, "role", None) or "member",
                        "is_default": True,
                        "joined_at": joined_at.isoformat() if joined_at else None,
                    }
                ]

        return success_response(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": "bearer",
                "expires_in": tokens.expires_in,
                "is_new_user": is_new_user,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "name": getattr(user, "name", sso_user.name),
                    "role": getattr(user, "role", "member"),
                    "org_id": getattr(user, "org_id", None),
                },
                "organization": org_data,
                "organizations": org_membership,
                "redirect_url": redirect_url,
                "sso_access_token": sso_user.access_token,  # For API calls to IdP
                "expires_at": sso_user.token_expires_at,
            }
        )

    except (
        ConnectionError,
        TimeoutError,
        ValueError,
        OSError,
        KeyError,
        ImportError,
        AttributeError,
    ) as e:
        logger.exception("SSO callback failed")
        # Track auth failure for reliability metrics
        try:
            from aragora.auth.session_monitor import get_session_monitor

            get_session_monitor().record_auth_failure()
        except (ImportError, AttributeError, TypeError):
            pass  # Non-fatal: monitoring is best-effort
        return error_response(safe_error_message(e, "SSO authentication"), status=401)


@require_permission("auth:manage_sso")
@auth_rate_limit(
    requests_per_minute=20,
    limiter_name="auth_sso_refresh",
    endpoint_name="SSO token refresh",
)
async def handle_sso_refresh(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Refresh SSO access token.

    POST /api/v1/auth/sso/refresh
    Body: {
        provider: str,
        refresh_token: str
    }
    """
    try:
        provider_type = data.get("provider", "oidc")
        refresh_token = data.get("refresh_token")

        if not refresh_token:
            return error_response("refresh_token is required", status=400)

        provider = _get_sso_provider(provider_type)
        if not provider:
            return error_response("SSO provider not available", status=503)

        # Create minimal user for refresh
        from aragora.auth.sso import SSOUser

        temp_user = SSOUser(
            id=user_id,
            email="",
            refresh_token=refresh_token,
        )

        refreshed_user = await provider.refresh_token(temp_user)

        if not refreshed_user:
            return error_response("Token refresh failed", status=401)

        return success_response(
            {
                "access_token": refreshed_user.access_token,
                "refresh_token": refreshed_user.refresh_token,
                "expires_at": refreshed_user.token_expires_at,
            }
        )

    except (ConnectionError, TimeoutError, ValueError, OSError, ImportError, AttributeError) as e:
        logger.exception("SSO refresh failed")
        return error_response(safe_error_message(e, "token refresh"), status=401)


@require_permission("auth:manage_sso")
@auth_rate_limit(
    requests_per_minute=20,
    limiter_name="auth_sso_logout",
    endpoint_name="SSO logout",
)
async def handle_sso_logout(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Logout from SSO.

    POST /api/v1/auth/sso/logout
    Body: {
        provider: str,
        id_token: str (optional) - For IdP logout
    }
    """
    try:
        provider_type = data.get("provider", "oidc")
        id_token = data.get("id_token")

        provider = _get_sso_provider(provider_type)

        logout_url = None
        if provider and id_token:
            from aragora.auth.sso import SSOUser

            temp_user = SSOUser(
                id=user_id,
                email="",
                id_token=id_token,
            )
            logout_url = await provider.logout(temp_user)

        return success_response(
            {
                "logged_out": True,
                "logout_url": logout_url,  # If provided, redirect user here for IdP logout
            }
        )

    except (ConnectionError, TimeoutError, ValueError, OSError, ImportError, AttributeError) as e:
        logger.exception("SSO logout failed")
        return error_response(safe_error_message(e, "logout"), status=500)


# =============================================================================
# Provider Configuration
# =============================================================================


# NOTE: List providers is a public endpoint - allows UI to show SSO buttons
# to unauthenticated users. RBAC protection via middleware.
@auth_rate_limit(
    requests_per_minute=30,
    limiter_name="auth_sso_list_providers",
    endpoint_name="SSO list providers",
)
async def handle_list_providers(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    List available SSO providers.

    GET /api/v1/auth/sso/providers
    """
    try:
        providers = []

        # Check which providers are configured
        provider_configs = [
            {
                "type": "oidc",
                "name": "OIDC/OAuth 2.0",
                "env_vars": ["OIDC_CLIENT_ID", "OIDC_ISSUER_URL"],
            },
            {
                "type": "google",
                "name": "Google",
                "env_vars": ["GOOGLE_CLIENT_ID"],
            },
            {
                "type": "github",
                "name": "GitHub",
                "env_vars": ["GITHUB_CLIENT_ID"],
            },
            {
                "type": "azure_ad",
                "name": "Azure AD",
                "env_vars": ["AZURE_AD_CLIENT_ID", "AZURE_AD_TENANT_ID"],
            },
        ]

        for config in provider_configs:
            is_configured = all(os.environ.get(var) for var in config["env_vars"])
            providers.append(
                {
                    "type": config["type"],
                    "name": config["name"],
                    "enabled": is_configured,
                }
            )

        return success_response(
            {
                "providers": providers,
                "sso_enabled": any(p["enabled"] for p in providers),
            }
        )

    except (ValueError, KeyError, TypeError) as e:
        logger.exception("Failed to list providers")
        return error_response(safe_error_message(e, "list SSO providers"), status=500)


@require_permission("auth:manage_sso")
@auth_rate_limit(
    requests_per_minute=20,
    limiter_name="auth_sso_config",
    endpoint_name="SSO config",
)
async def handle_get_sso_config(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get SSO configuration for a provider.

    GET /api/v1/auth/sso/config
    Query params:
        provider: str
    """
    try:
        provider_type = data.get("provider", "oidc")

        # Return public configuration (no secrets)
        config: dict[str, Any] = {
            "provider": provider_type,
            "enabled": False,
        }

        if provider_type == "oidc":
            client_id = os.environ.get("OIDC_CLIENT_ID")
            issuer_url = os.environ.get("OIDC_ISSUER_URL")

            if client_id and issuer_url:
                config.update(
                    {
                        "enabled": True,
                        "issuer_url": issuer_url,
                        "scopes": os.environ.get("OIDC_SCOPES", "openid,email,profile").split(","),
                    }
                )

        elif provider_type == "google":
            client_id = os.environ.get("GOOGLE_CLIENT_ID")
            if client_id:
                config.update(
                    {
                        "enabled": True,
                        "issuer_url": "https://accounts.google.com",
                        "scopes": ["openid", "email", "profile"],
                    }
                )

        elif provider_type == "github":
            client_id = os.environ.get("GITHUB_CLIENT_ID")
            if client_id:
                config.update(
                    {
                        "enabled": True,
                        "authorization_endpoint": "https://github.com/login/oauth/authorize",
                        "scopes": ["user:email", "read:user"],
                    }
                )

        return success_response(config)

    except (ValueError, KeyError, TypeError) as e:
        logger.exception("Failed to get SSO config")
        return error_response(safe_error_message(e, "get SSO config"), status=500)


# =============================================================================
# Handler Registration
# =============================================================================


def get_sso_handlers() -> dict[str, Any]:
    """Get all SSO handlers for registration."""
    return {
        "sso_login": handle_sso_login,
        "sso_callback": handle_sso_callback,
        "sso_refresh": handle_sso_refresh,
        "sso_logout": handle_sso_logout,
        "sso_list_providers": handle_list_providers,
        "sso_get_config": handle_get_sso_config,
    }


__all__ = [
    "handle_sso_login",
    "handle_sso_callback",
    "handle_sso_refresh",
    "handle_sso_logout",
    "handle_list_providers",
    "handle_get_sso_config",
    "get_sso_handlers",
    # Internal but exported for testing
    "_sso_providers",
    "_sso_providers_lock",
    "AUTH_SESSION_TTL",
    "_get_sso_provider",
]
