"""
OAuth handler - main entry point.

Re-exports OAuthHandler from the implementation module for backward compatibility.
The modular structure is in place for future incremental migration of methods.
"""

# Re-export OAuthHandler from the implementation module
from ._oauth_impl import (
    OAuthHandler,
    OAuthUserInfo,
    validate_oauth_config,
    _oauth_limiter,
    _validate_redirect_url,
    _validate_state,
    _cleanup_expired_states,
    _generate_state,
    # Google
    _get_google_client_id,
    _get_google_client_secret,
    _get_google_redirect_uri,
    # GitHub
    _get_github_client_id,
    _get_github_client_secret,
    _get_github_redirect_uri,
    # Microsoft
    _get_microsoft_client_id,
    _get_microsoft_client_secret,
    _get_microsoft_tenant,
    _get_microsoft_redirect_uri,
    # Apple
    _get_apple_client_id,
    _get_apple_team_id,
    _get_apple_key_id,
    _get_apple_private_key,
    _get_apple_redirect_uri,
    # OIDC
    _get_oidc_issuer,
    _get_oidc_client_id,
    _get_oidc_client_secret,
    _get_oidc_redirect_uri,
    # Common
    _get_oauth_success_url,
    _get_oauth_error_url,
    _get_allowed_redirect_hosts,
    _IS_PRODUCTION,
    GOOGLE_CLIENT_ID,
    GITHUB_CLIENT_ID,
    ALLOWED_OAUTH_REDIRECT_HOSTS,
    OAUTH_SUCCESS_URL,
    OAUTH_ERROR_URL,
)

__all__ = [
    "OAuthHandler",
    "OAuthUserInfo",
    "validate_oauth_config",
    "_oauth_limiter",
    "_validate_redirect_url",
    "_validate_state",
    "_cleanup_expired_states",
    "_generate_state",
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
]
