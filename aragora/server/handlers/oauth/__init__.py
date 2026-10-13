"""
OAuth handler package.

Provides OAuth2/OIDC authentication endpoints for various providers:
- Google OAuth 2.0
- GitHub OAuth
- Microsoft OAuth (Azure AD)
- Apple Sign-In
- Generic OIDC

The handler is split into logical modules for better maintainability:

- handler.py: Main OAuthHandler class (re-exported from _oauth_impl.py)
- config.py: OAuth configuration status

For backward compatibility, import OAuthHandler from this package:

    from aragora.server.handlers.oauth import OAuthHandler

Imports are deferred to avoid circular dependency:
  oauth/__init__ -> handler -> _oauth_impl -> _oauth/base -> oauth.models
  The models module is safe (no circular deps), but loading __init__ triggers
  the handler import chain before _oauth/base finishes loading.
"""

from __future__ import annotations

from typing import Any

from .config import get_oauth_config_status

__all__ = [
    "OAuthHandler",
    "OAuthUserInfo",
    "validate_oauth_config",
    "_oauth_limiter",
    "_validate_redirect_url",
    "_validate_state",
    "_cleanup_expired_states",
    "_generate_state",
    "_OAUTH_STATES",
    # Google
    "_get_google_client_id",
    "_get_google_client_secret",
    "_get_google_redirect_uri",
    # GitHub
    "_get_github_client_id",
    "_get_github_client_secret",
    "_get_github_redirect_uri",
    # Microsoft
    "_get_microsoft_client_id",
    "_get_microsoft_client_secret",
    "_get_microsoft_tenant",
    "_get_microsoft_redirect_uri",
    # Apple
    "_get_apple_client_id",
    "_get_apple_team_id",
    "_get_apple_key_id",
    "_get_apple_private_key",
    "_get_apple_redirect_uri",
    # OIDC
    "_get_oidc_issuer",
    "_get_oidc_client_id",
    "_get_oidc_client_secret",
    "_get_oidc_redirect_uri",
    # Common
    "_get_oauth_success_url",
    "_get_oauth_error_url",
    "_get_allowed_redirect_hosts",
    "_IS_PRODUCTION",
    "GOOGLE_CLIENT_ID",
    "GITHUB_CLIENT_ID",
    "ALLOWED_OAUTH_REDIRECT_HOSTS",
    "OAUTH_SUCCESS_URL",
    "OAUTH_ERROR_URL",
    "get_oauth_config_status",
]


def __getattr__(name: str) -> Any:
    """Lazy imports to break circular dependency with _oauth/base.py."""
    if name == "_OAUTH_STATES":
        from ._oauth_impl import _OAUTH_STATES

        return _OAUTH_STATES

    if name in __all__:
        from . import handler as _handler

        val = getattr(_handler, name, None)
        if val is not None:
            return val

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
