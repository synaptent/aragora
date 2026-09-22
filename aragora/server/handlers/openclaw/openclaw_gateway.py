"""
HTTP Handlers for OpenClaw Gateway.

Stability: STABLE

This module has been refactored into the `openclaw` package.
This file provides backwards compatibility for existing imports.

For new code, prefer importing from the package directly:
    from aragora.server.handlers.openclaw import OpenClawGatewayHandler

See aragora/server/handlers/openclaw/ for the full implementation:
- gateway.py: Main OpenClawGatewayHandler class
- orchestrator.py: Session and action orchestration handlers
- credentials.py: Credential management handlers
- policies.py: Policy enforcement and admin handlers
- models.py: Data models (Session, Action, Credential, etc.)
- validation.py: Input validation functions
- store.py: In-memory data store
"""

# Re-export everything from the openclaw package for backwards compatibility
from aragora.server.handlers.openclaw import (
    CREDENTIAL_ROTATION_WINDOW_SECONDS,
    MAX_ACTION_INPUT_SIZE,
    MAX_ACTION_TYPE_LENGTH,
    MAX_CREDENTIAL_NAME_LENGTH,
    MAX_CREDENTIAL_ROTATIONS_PER_HOUR,
    MAX_CREDENTIAL_SECRET_LENGTH,
    MAX_SESSION_CONFIG_KEYS,
    MAX_SESSION_CONFIG_DEPTH,
    MAX_SESSION_CONFIG_SIZE,
    MIN_CREDENTIAL_SECRET_LENGTH,
    Action,
    ActionStatus,
    AuditEntry,
    Credential,
    CredentialRotationRateLimiter,
    CredentialType,
    OpenClawGatewayHandler,
    OpenClawGatewayStore,
    Session,
    SessionStatus,
    _get_credential_rotation_limiter,
    _get_store,
    get_openclaw_circuit_breaker,
    get_openclaw_circuit_breaker_status,
    get_openclaw_gateway_handler,
    sanitize_action_parameters,
    validate_action_input,
    validate_action_type,
    validate_credential_name,
    validate_credential_secret,
    validate_metadata,
    validate_session_config,
)
from aragora.server.handlers.utils.decorators import has_permission, require_permission
from aragora.server.handlers.utils.rate_limit import auth_rate_limit, rate_limit

__all__ = [
    "OpenClawGatewayHandler",
    "get_openclaw_gateway_handler",
    # Resilience
    "get_openclaw_circuit_breaker",
    "get_openclaw_circuit_breaker_status",
    # Data models
    "Session",
    "SessionStatus",
    "Action",
    "ActionStatus",
    "Credential",
    "CredentialType",
    "AuditEntry",
    # Store (for testing)
    "OpenClawGatewayStore",
    "_get_store",
    # Validation constants (for testing)
    "MAX_CREDENTIAL_NAME_LENGTH",
    "MAX_CREDENTIAL_SECRET_LENGTH",
    "MIN_CREDENTIAL_SECRET_LENGTH",
    "MAX_SESSION_CONFIG_KEYS",
    "MAX_SESSION_CONFIG_DEPTH",
    "MAX_SESSION_CONFIG_SIZE",
    "MAX_ACTION_TYPE_LENGTH",
    "MAX_ACTION_INPUT_SIZE",
    "MAX_CREDENTIAL_ROTATIONS_PER_HOUR",
    "CREDENTIAL_ROTATION_WINDOW_SECONDS",
    # Validation functions (for testing)
    "validate_credential_name",
    "validate_credential_secret",
    "validate_session_config",
    "validate_action_type",
    "validate_action_input",
    "validate_metadata",
    "sanitize_action_parameters",
    # Rate limiting (for testing)
    "CredentialRotationRateLimiter",
    "_get_credential_rotation_limiter",
    # RBAC decorator (for testing)
    "require_permission",
    "has_permission",
    # Rate limiting decorator (for testing)
    "auth_rate_limit",
    "rate_limit",
]
