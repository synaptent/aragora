"""
Aragora Authentication Module.

Provides SSO/SAML/OIDC authentication for enterprise deployments,
and account lockout protection against brute-force attacks.

Usage:
    from aragora.auth import get_sso_provider, SSOProvider, SAMLProvider, OIDCProvider
    from aragora.auth.sso import SSOUser, SSOConfig

    # Get configured provider
    provider = get_sso_provider()
    if provider:
        auth_url = await provider.get_authorization_url(state="...")
        user = await provider.authenticate(code="...")

    # Lockout tracking
    from aragora.auth import get_lockout_tracker

    tracker = get_lockout_tracker()
    if tracker.is_locked(email=email, ip=client_ip):
        remaining = tracker.get_remaining_time(email=email, ip=client_ip)
        return error(f"Locked for {remaining} seconds")
"""

from typing import Any

# Pre-declare SCIM names for optional import fallback
SCIMConfig: Any
SCIMServer: Any
SCIMUser: Any
SCIMGroup: Any
SCIMError: Any

# Pre-declare SAML names for optional import fallback
SAMLConfig: Any
SAMLError: Any
SAMLProvider: Any

from .lockout import (
    LockoutEntry,
    LockoutTracker,
    get_lockout_tracker,
    reset_lockout_tracker,
)

# Pre-declare OIDC names for optional import fallback
OIDCConfig: Any
OIDCError: Any
OIDCProvider: Any

# OIDC requires PyJWT (import jwt) at module level
try:
    from .oidc import (
        OIDCConfig,
        OIDCError,
        OIDCProvider,
    )

    HAS_OIDC = True
except ImportError:
    # OIDC unavailable (PyJWT not installed) - pre-declared above
    OIDCConfig = None
    OIDCError = None
    OIDCProvider = None
    HAS_OIDC = False

# SCIM 2.0 provisioning
try:
    from .scim import (
        SCIMConfig,
        SCIMServer,
        SCIMUser,
        SCIMGroup,
        SCIMError,
    )

    HAS_SCIM = True
except ImportError:
    # SCIM unavailable - pre-declared above
    SCIMConfig = None
    SCIMServer = None
    SCIMUser = None
    SCIMGroup = None
    SCIMError = None
    HAS_SCIM = False

# SAML requires python3-saml optional dependency
try:
    from .saml import (
        SAMLConfig,
        SAMLError,
        SAMLProvider,
    )

    HAS_SAML = True
except ImportError:
    # SAML unavailable - pre-declared above
    SAMLConfig = None
    SAMLError = None
    SAMLProvider = None
    HAS_SAML = False

from .mfa_drift_monitor import (
    MFADriftAlert,
    MFADriftMonitor,
    MFADriftReport,
    get_mfa_drift_monitor,
    init_mfa_drift_monitor,
)

from .session_monitor import (
    SessionHealthMonitor,
    SessionHealthStatus,
    SessionMetrics,
    SessionState,
    TrackedSession,
    get_session_monitor,
    reset_session_monitor,
)

from .sso import (
    SSOAuthenticationError,
    SSOConfig,
    SSOConfigurationError,
    SSOError,
    SSOProvider,
    SSOProviderType,
    SSOUser,
    get_sso_provider,
    reset_sso_provider,
)

__all__ = [
    # Base SSO
    "SSOProvider",
    "SSOProviderType",
    "SSOUser",
    "SSOConfig",
    "SSOError",
    "SSOAuthenticationError",
    "SSOConfigurationError",
    "get_sso_provider",
    "reset_sso_provider",
    # Lockout
    "LockoutTracker",
    "LockoutEntry",
    "get_lockout_tracker",
    "reset_lockout_tracker",
    # Session monitoring
    "SessionHealthMonitor",
    "SessionHealthStatus",
    "SessionMetrics",
    "SessionState",
    "TrackedSession",
    "get_session_monitor",
    "reset_session_monitor",
    # MFA drift monitoring
    "MFADriftAlert",
    "MFADriftMonitor",
    "MFADriftReport",
    "get_mfa_drift_monitor",
    "init_mfa_drift_monitor",
    # Availability flags
    "HAS_OIDC",
    "HAS_SAML",
]

# Add OIDC exports only if available
if HAS_OIDC:
    __all__.extend(["OIDCProvider", "OIDCConfig", "OIDCError"])

# Add SAML exports only if available
if HAS_SAML:
    __all__.extend(["SAMLProvider", "SAMLConfig", "SAMLError"])

# Add SCIM exports only if available
if HAS_SCIM:
    __all__.extend(["SCIMConfig", "SCIMServer", "SCIMUser", "SCIMGroup", "SCIMError", "HAS_SCIM"])
