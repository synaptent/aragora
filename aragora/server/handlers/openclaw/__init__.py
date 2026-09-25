"""
OpenClaw Gateway HTTP Handlers Package.

Stability: STABLE

This package provides REST API endpoints for the OpenClaw gateway integration:
- Session management (create, get, list, close)
- Action execution (execute, status, cancel)
- Credential management (store, list, delete, rotate)
- Admin operations (health, metrics, audit)

Package Structure:
- gateway.py: Main OpenClawGatewayHandler class
- orchestrator.py: Session and action orchestration handlers
- credentials.py: Credential management handlers
- policies.py: Policy enforcement and admin handlers
- models.py: Data models (Session, Action, Credential, etc.)
- validation.py: Input validation functions
- store.py: In-memory data store

Additional modules (import directly, without expanding eager package exports):
openclaw_gateway.
"""

from aragora.server.handlers.openclaw.credentials import (
    CREDENTIAL_ROTATION_WINDOW_SECONDS,
    MAX_CREDENTIAL_ROTATIONS_PER_HOUR,
    CredentialRotationRateLimiter,
    _get_credential_rotation_limiter,
)
from aragora.server.handlers.openclaw.gateway import (
    OpenClawGatewayHandler,
    get_openclaw_circuit_breaker,
    get_openclaw_circuit_breaker_status,
    get_openclaw_gateway_handler,
)
from aragora.server.handlers.openclaw.models import (
    Action,
    ActionStatus,
    AuditEntry,
    Credential,
    CredentialType,
    Session,
    SessionStatus,
)
from aragora.server.handlers.openclaw.store import (
    OpenClawGatewayStore,
    _get_store,
)
from aragora.server.handlers.openclaw.validation import (
    MAX_ACTION_INPUT_SIZE,
    MAX_ACTION_TYPE_LENGTH,
    MAX_CREDENTIAL_NAME_LENGTH,
    MAX_CREDENTIAL_SECRET_LENGTH,
    MAX_SESSION_CONFIG_KEYS,
    MAX_SESSION_CONFIG_DEPTH,
    MAX_SESSION_CONFIG_SIZE,
    MIN_CREDENTIAL_SECRET_LENGTH,
    sanitize_action_parameters,
    validate_action_input,
    validate_action_type,
    validate_credential_name,
    validate_credential_secret,
    validate_metadata,
    validate_session_config,
)

__all__ = [
    # Main handler
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
]
