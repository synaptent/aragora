"""
Unified error module for Aragora.

This module provides a single import point for all Aragora exceptions,
re-exporting errors from both the base exception hierarchy (aragora.exceptions)
and the foundation API error hierarchy (aragora.api_errors).

The hierarchy is unified: all API errors inherit from AragoraError.

Usage:
    from aragora.errors import (
        # Base errors
        AragoraError,
        DebateError,
        ValidationError,
        AuthenticationError,

        # API-specific errors
        AragoraAPIError,
        NotFoundError,
        RateLimitError,
        format_error_response,
    )

    # Catch all Aragora errors
    try:
        ...
    except AragoraError as e:
        handle_error(e)

    # Catch only API errors
    try:
        ...
    except AragoraAPIError as e:
        return format_error_response(e)
"""

from __future__ import annotations

# =============================================================================
# Base Exception Hierarchy (from aragora.exceptions)
# =============================================================================
from aragora.exceptions import (
    # Root
    AragoraError,
    # Debate errors
    ConsensusError,
    ConsensusTimeoutError,
    DebateBatchError,
    DebateConfigurationError,
    DebateError,
    DebateExecutionError,
    DebateNotFoundError,
    DebateStartError,
    EarlyStopError,
    PhaseExecutionError,
    RoundLimitExceededError,
    VoteProcessingError,
    VoteValidationError,
    # Agent configuration errors
    AgentConfigurationError,
    AgentNotFoundError,
    APIKeyError,
    ConfigurationError,
    # Validation errors
    InputValidationError,
    JSONParseError,
    SchemaValidationError,
)
from aragora.exceptions import ValidationError as BaseValidationError
from aragora.exceptions import (
    # Storage errors
    DatabaseConnectionError,
)
from aragora.exceptions import DatabaseError as BaseDatabaseError
from aragora.exceptions import (
    RecordNotFoundError,
    StorageError,
    # Memory errors
    EmbeddingError,
)
from aragora.exceptions import MemoryError as BaseMemoryError
from aragora.exceptions import (
    MemoryOperationError,
    MemoryRetrievalError,
    MemoryStorageError,
    TierTransitionError,
    # Mode errors
    ModeConfigurationError,
    ModeError,
    ModeNotFoundError,
    # Plugin errors
    PluginError,
    PluginExecutionError,
    PluginNotFoundError,
    # Auth errors
    AuthError,
)
from aragora.exceptions import AuthenticationError as BaseAuthenticationError
from aragora.exceptions import (
    AuthorizationError,
    OAuthStateError,
    RateLimitExceededError,
    TokenExpiredError,
    # Infrastructure errors
    CircuitBreakerError,
)
from aragora.exceptions import ExternalServiceError as BaseExternalServiceError
from aragora.exceptions import (
    InfrastructureError,
    RedisUnavailableError,
    # Nomic errors
    NomicAgentError,
    NomicAnalyticsError,
    NomicCycleError,
    NomicError,
    NomicInitError,
    NomicIntegrationError,
    NomicMemoryError,
    NomicPhaseError,
    NomicStateError,
    NomicTimeoutError,
    NomicVerificationError,
    # Checkpoint errors
    CheckpointCorruptedError,
    CheckpointError,
    CheckpointNotFoundError,
    CheckpointSaveError,
    # Convergence errors
    ConvergenceBackendError,
    ConvergenceError,
    ConvergenceThresholdError,
    # Cache errors
    CacheCapacityError,
    CacheError,
    CacheKeyError,
    # Streaming errors
    StreamConnectionError,
    StreamingError,
    StreamTimeoutError,
    WebSocketError,
    # Evidence errors
    EvidenceError,
    EvidenceNotFoundError,
    EvidenceParseError,
)

# Verification errors
from aragora.exceptions import VerificationError as BaseVerificationError
from aragora.exceptions import (
    VerificationTimeoutError,
    Z3NotAvailableError,
)

# =============================================================================
# API Error Hierarchy (from aragora.api_errors)
# =============================================================================
from aragora.api_errors import (
    # Error codes
    ErrorCode,
    # Context
    ErrorContext,
    # Base API class (inherits from AragoraError)
    AragoraAPIError,
    # Client errors (4xx)
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    MethodNotAllowedError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
    # Server errors (5xx)
    DatabaseError,
    ExternalServiceError,
    GatewayTimeoutError,
    InternalError,
    ServiceUnavailableError,
)

# Domain errors - import with API prefix to avoid confusion
from aragora.api_errors import DebateError as APIDebateError
from aragora.api_errors import MemoryError as APIMemoryError
from aragora.api_errors import VerificationError as APIVerificationError
from aragora.api_errors import (
    # Utilities
    EXCEPTION_MAP,
    ERROR_SUGGESTIONS,
    ErrorFormatter,
    format_cli_error,
    format_error_response,
    get_error_suggestion,
    get_status_code,
    log_error,
    safe_error_message,
    wrap_exception,
)

__all__ = [
    # =========================================================================
    # Base hierarchy (aragora.exceptions)
    # =========================================================================
    "AragoraError",
    # Debate
    "DebateError",
    "DebateNotFoundError",
    "DebateConfigurationError",
    "ConsensusError",
    "ConsensusTimeoutError",
    "VoteValidationError",
    "PhaseExecutionError",
    "RoundLimitExceededError",
    "EarlyStopError",
    "DebateStartError",
    "DebateBatchError",
    "DebateExecutionError",
    "VoteProcessingError",
    # Agent config
    "AgentNotFoundError",
    "AgentConfigurationError",
    "ConfigurationError",
    "APIKeyError",
    # Validation (base)
    "BaseValidationError",
    "InputValidationError",
    "SchemaValidationError",
    "JSONParseError",
    # Storage
    "StorageError",
    "BaseDatabaseError",
    "DatabaseConnectionError",
    "RecordNotFoundError",
    # Memory (base)
    "BaseMemoryError",
    "MemoryRetrievalError",
    "MemoryStorageError",
    "TierTransitionError",
    "EmbeddingError",
    "MemoryOperationError",
    # Mode
    "ModeError",
    "ModeNotFoundError",
    "ModeConfigurationError",
    # Plugin
    "PluginError",
    "PluginNotFoundError",
    "PluginExecutionError",
    # Auth (base)
    "AuthError",
    "BaseAuthenticationError",
    "AuthorizationError",
    "TokenExpiredError",
    "RateLimitExceededError",
    "OAuthStateError",
    # Infrastructure
    "InfrastructureError",
    "RedisUnavailableError",
    "BaseExternalServiceError",
    "CircuitBreakerError",
    # Nomic
    "NomicError",
    "NomicCycleError",
    "NomicStateError",
    "NomicInitError",
    "NomicMemoryError",
    "NomicAgentError",
    "NomicPhaseError",
    "NomicIntegrationError",
    "NomicAnalyticsError",
    "NomicVerificationError",
    "NomicTimeoutError",
    # Checkpoint
    "CheckpointError",
    "CheckpointNotFoundError",
    "CheckpointCorruptedError",
    "CheckpointSaveError",
    # Convergence
    "ConvergenceError",
    "ConvergenceBackendError",
    "ConvergenceThresholdError",
    # Cache
    "CacheError",
    "CacheKeyError",
    "CacheCapacityError",
    # Streaming
    "StreamingError",
    "WebSocketError",
    "StreamConnectionError",
    "StreamTimeoutError",
    # Evidence
    "EvidenceError",
    "EvidenceParseError",
    "EvidenceNotFoundError",
    # Verification (base)
    "BaseVerificationError",
    "Z3NotAvailableError",
    "VerificationTimeoutError",
    # =========================================================================
    # API hierarchy (aragora.api_errors)
    # =========================================================================
    "ErrorCode",
    "ErrorContext",
    "AragoraAPIError",
    # Client errors
    "BadRequestError",
    "ValidationError",
    "AuthenticationError",
    "ForbiddenError",
    "NotFoundError",
    "MethodNotAllowedError",
    "ConflictError",
    "RateLimitError",
    "PayloadTooLargeError",
    # Server errors
    "InternalError",
    "ServiceUnavailableError",
    "GatewayTimeoutError",
    "DatabaseError",
    "ExternalServiceError",
    # Domain errors (API variants)
    "APIDebateError",
    "APIVerificationError",
    "APIMemoryError",
    # Utilities
    "format_error_response",
    "get_status_code",
    "wrap_exception",
    "log_error",
    "EXCEPTION_MAP",
    "safe_error_message",
    "ERROR_SUGGESTIONS",
    "get_error_suggestion",
    "format_cli_error",
    "ErrorFormatter",
]
