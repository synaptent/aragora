"""
User Authentication Context.

Provides user authentication context extraction from HTTP requests,
including JWT and API key validation.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from aragora.utils.request_ip import extract_client_ip

logger = logging.getLogger(__name__)


@dataclass
class UserAuthContext:
    """
    User authentication context for handlers.

    Extended version of AuthContext with user-specific information.
    """

    authenticated: bool = False
    user_id: str | None = None
    email: str | None = None
    org_id: str | None = None
    role: str = "member"
    token_type: str = "none"  # noqa: S105 -- field default (none, access, api_key)
    client_ip: str | None = None
    error_reason: str | None = None  # Set when auth fails with a specific reason

    @property
    def is_authenticated(self) -> bool:
        """Alias for authenticated."""
        return self.authenticated

    @property
    def id(self) -> str | None:
        """Alias for user_id for compatibility."""
        return self.user_id

    @property
    def is_owner(self) -> bool:
        """Check if user is org owner."""
        return self.role == "owner"

    @property
    def is_admin(self) -> bool:
        """Check if user is admin or owner."""
        return self.role in ("owner", "admin")


def extract_user_from_request(handler: Any, user_store=None) -> UserAuthContext:
    """
    Extract user authentication from a request.

    Checks for:
    1. Bearer token (JWT)
    2. API key (ara_xxx)

    Args:
        handler: HTTP request handler
        user_store: Optional user store for API key validation against database.
                    API keys require a store unless ARAGORA_ALLOW_FORMAT_ONLY_API_KEYS=1.

    Returns:
        UserAuthContext with authentication info
    """
    from .tokens import validate_access_token

    context = UserAuthContext(
        authenticated=False,
        client_ip=extract_client_ip(handler),
    )

    if handler is None:
        logger.debug("extract_user_from_request: handler is None")
        return context

    # Get authorization header
    auth_header = ""
    if hasattr(handler, "headers"):
        auth_header = handler.headers.get("Authorization", "")

    # Ensure auth_header is a string (handles MagicMock in tests)
    if not isinstance(auth_header, str) or not auth_header:
        logger.debug("extract_user_from_request: no Authorization header")
        return context

    # Check for Bearer token (JWT)
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        token_fingerprint = hashlib.sha256(token.encode()).hexdigest()[:8]
        logger.debug(
            "extract_user_from_request: Bearer token found, length=%s, fingerprint=%s",
            len(token),
            token_fingerprint,
        )

        # Check if it's an API key
        if token.startswith("ara_"):
            logger.debug("token is API key")
            return _validate_api_key(token, context, user_store)

        # Validate as JWT
        logger.debug("validating as JWT")
        payload = validate_access_token(token)
        if payload:
            logger.debug(
                "JWT validated: user_id=%s, email=%s",
                payload.user_id,
                payload.email,
            )
            context.authenticated = True
            context.user_id = payload.user_id
            context.email = payload.email
            context.org_id = payload.org_id
            context.role = payload.role
            context.token_type = "access"  # noqa: S105 -- token category label
        else:
            logger.warning("JWT validation failed: validate_access_token returned None")
            context.error_reason = "JWT validation failed"

    return context


def _validate_api_key(api_key: str, context: UserAuthContext, user_store=None) -> UserAuthContext:
    """
    Validate an API key and populate context.

    Performs format validation and optional database lookup if user_store is provided.

    API key format: ara_<random_string> (minimum 15 chars total)

    Args:
        api_key: API key string (expected format: ara_xxxxx)
        context: Context to populate
        user_store: Optional user store for database validation

    Returns:
        Updated context with authentication status
    """
    # Format validation (basic security check)
    if not api_key.startswith("ara_") or len(api_key) < 15:
        logger.warning("api_key_invalid_format key_prefix=%s...", api_key[:8])
        context.authenticated = False
        return context

    # Database lookup if store available
    if user_store is not None:
        try:
            # Look up user by API key
            user = user_store.get_user_by_api_key(api_key)
            if user is None:
                logger.warning("api_key_not_found key_prefix=%s...", api_key[:8])
                context.authenticated = False
                return context

            # Check if user is active
            if not user.is_active:
                logger.warning("api_key_user_inactive user_id=%s", user.id)
                context.authenticated = False
                return context

            # Populate context with user info
            context.authenticated = True
            context.user_id = user.id
            context.email = user.email
            context.org_id = user.org_id
            context.role = user.role
            context.token_type = "api_key"  # noqa: S105 -- token category label
            logger.debug("api_key_validated user_id=%s", user.id)
            return context

        except (OSError, ConnectionError, TimeoutError, RuntimeError, KeyError, ValueError) as e:
            logger.error("api_key_validation_error: %s", e)
            context.authenticated = False
            return context

    # No user store available - API key auth requires database validation
    # This is an intentional security requirement - format-only validation was removed
    logger.error(
        "api_key_validation_failed: user_store is required for API key authentication. "
        "Ensure UserStore is initialized before processing API key auth requests."
    )
    context.authenticated = False
    context.error_reason = "API key authentication requires server configuration"
    return context


__all__ = [
    "UserAuthContext",
    "extract_user_from_request",
]
