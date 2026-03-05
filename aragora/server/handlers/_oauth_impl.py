"""
OAuth Authentication Handlers - backward compatibility shim.

This module previously contained the monolithic OAuthHandler class (~1,800 LOC).
It has been refactored into the `_oauth/` package with provider-specific mixins:

- _oauth/base.py: OAuthHandler (combines all mixins)
- _oauth/google.py: GoogleOAuthMixin
- _oauth/github.py: GitHubOAuthMixin
- _oauth/microsoft.py: MicrosoftOAuthMixin
- _oauth/apple.py: AppleOAuthMixin
- _oauth/oidc.py: OIDCOAuthMixin
- _oauth/account.py: AccountManagementMixin
- _oauth/utils.py: Shared utility functions

All public names are re-exported here for backward compatibility.
"""

from __future__ import annotations

# Re-export OAuthHandler from the new package
from ._oauth.base import OAuthHandler  # noqa: F401

# Re-export rate limiter from the new package
from ._oauth.utils import _oauth_limiter  # noqa: F401

# Re-export tracing (used by tests that patch at this module path)
from aragora.observability.tracing import create_span, add_span_attributes  # noqa: F401

# Re-export everything from oauth.config (tests patch these at _oauth_impl level)
from .oauth.config import (  # noqa: F401
    _get_secret,
    _is_production,
    _get_google_client_id,
    _get_google_client_secret,
    _get_github_client_id,
    _get_github_client_secret,
    _get_microsoft_client_id,
    _get_microsoft_client_secret,
    _get_microsoft_tenant,
    _get_apple_client_id,
    _get_apple_team_id,
    _get_apple_key_id,
    _get_apple_private_key,
    _get_oidc_issuer,
    _get_oidc_client_id,
    _get_oidc_client_secret,
    _get_google_redirect_uri,
    _get_github_redirect_uri,
    _get_microsoft_redirect_uri,
    _get_apple_redirect_uri,
    _get_oidc_redirect_uri,
    _get_oauth_success_url,
    _get_oauth_error_url,
    _get_allowed_redirect_hosts,
    _IS_PRODUCTION,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    GITHUB_REDIRECT_URI,
    OAUTH_SUCCESS_URL,
    OAUTH_ERROR_URL,
    ALLOWED_OAUTH_REDIRECT_HOSTS,
    validate_oauth_config,
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    GITHUB_AUTH_URL,
    GITHUB_TOKEN_URL,
    GITHUB_USERINFO_URL,
    GITHUB_EMAILS_URL,
    MICROSOFT_AUTH_URL_TEMPLATE,
    MICROSOFT_TOKEN_URL_TEMPLATE,
    MICROSOFT_USERINFO_URL,
    APPLE_AUTH_URL,
    APPLE_TOKEN_URL,
    APPLE_KEYS_URL,
)

# Re-export models
from .oauth.models import OAuthUserInfo, _get_param  # noqa: F401

# Re-export state management
from .oauth.state import (  # noqa: F401
    _OAuthStatesView,
    _OAUTH_STATES,
    _STATE_TTL_SECONDS,
    MAX_OAUTH_STATES,
    _cleanup_expired_states,
)

# Re-export state store functions (tests patch these at _oauth_impl level)
from aragora.server.oauth_state_store import (  # noqa: F401
    generate_oauth_state as _generate_state,
    validate_oauth_state as _validate_state_internal,
)

import logging as _logging
import sys as _sys
from urllib.parse import urlparse as _urlparse

_logger = _logging.getLogger(__name__)


def _validate_redirect_url(redirect_url: str) -> bool:
    """Validate that redirect URL is in the allowed hosts list.

    Collects allowed hosts from both the internal ``_oauth_impl`` module and
    the public ``oauth`` module so that tests patching either location have
    the patch visible.  Treats an empty allowlist as a security failure.
    """
    try:
        parsed = _urlparse(redirect_url)
        if parsed.scheme not in ("http", "https"):
            _logger.warning("oauth_redirect_blocked: scheme=%s not allowed", parsed.scheme)
            return False
        host = parsed.hostname
        if not host:
            return False
        host = host.lower()

        # Collect allowed hosts from multiple sources for test patchability
        allowed_hosts: set[str] = set()
        _self = _sys.modules[__name__]
        getters = [getattr(_self, "_get_allowed_redirect_hosts", None)]
        try:
            _oauth_pub = _sys.modules.get("aragora.server.handlers.oauth")
            if _oauth_pub is not None:
                pub_getter = getattr(_oauth_pub, "_get_allowed_redirect_hosts", None)
                if pub_getter is not None and pub_getter is not getters[0]:
                    getters.append(pub_getter)
        except (AttributeError, KeyError):
            pass

        for getter in getters:
            if getter is None:
                continue
            try:
                allowed_hosts.update(getter())
            except (TypeError, RuntimeError, OSError):
                continue

        if not allowed_hosts:
            _logger.warning("oauth_redirect_blocked: empty allowlist")
            return False

        if host in allowed_hosts:
            return True
        for allowed in allowed_hosts:
            if host.endswith(f".{allowed}"):
                return True
        _logger.warning("oauth_redirect_blocked: host=%s not in allowlist", host)
        return False
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        _logger.warning("oauth_redirect_validation_error: %s", e)
        return False


def _validate_state(state: str):
    """Validate an OAuth state token.

    Wraps ``_validate_state_internal`` so that tests can patch
    ``_oauth_impl._validate_state`` and have the patch visible to mixin code
    that calls ``_impl()._validate_state()``.
    """
    return _validate_state_internal(state)


__all__ = ["OAuthHandler", "validate_oauth_config"]
