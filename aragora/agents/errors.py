"""
Standardized error handling for agent operations.

This module re-exports from aragora.agents.errors package for backward compatibility.

For new code, prefer importing directly from the package:
    from aragora.agents.errors import AgentError, handle_agent_errors
    from aragora.agents.errors.exceptions import AgentTimeoutError
    from aragora.agents.errors.classifier import ErrorClassifier
    from aragora.agents.errors.decorators import with_error_handling
"""

# Explicit re-exports from the concrete submodules for backward compatibility.
# Importing from aragora.agents.errors here would recurse back into this shim.
from aragora.agents.types import T
from aragora.utils.error_sanitizer import (
    SENSITIVE_PATTERNS as _SENSITIVE_PATTERNS,
)
from aragora.utils.error_sanitizer import (
    sanitize_error,
)

from aragora.agents.errors.classifier import (
    ALL_FALLBACK_PATTERNS,
    AUTH_ERROR_PATTERNS,
    CLI_ERROR_PATTERNS,
    CONTENT_POLICY_PATTERNS,
    MODEL_ERROR_PATTERNS,
    NETWORK_ERROR_PATTERNS,
    RATE_LIMIT_PATTERNS,
    VALIDATION_ERROR_PATTERNS,
    ClassifiedError,
    ErrorAction,
    ErrorCategory,
    ErrorClassifier,
    ErrorContext,
    ErrorSeverity,
    RecoveryAction,
    classify_cli_error,
)
from aragora.agents.errors.decorators import (
    _calculate_retry_delay_with_jitter,
    _handle_agent_error,
    _handle_connection_error,
    _handle_json_error,
    _handle_payload_error,
    _handle_response_error,
    _handle_timeout_error,
    _handle_unexpected_error,
    calculate_retry_delay_with_jitter,
    handle_agent_errors,
    handle_stream_errors,
    with_error_handling,
)
from aragora.agents.errors.exceptions import (
    AgentAPIError,
    AgentCircuitOpenError,
    AgentConnectionError,
    AgentError,
    AgentRateLimitError,
    AgentResponseError,
    AgentStreamError,
    AgentTimeoutError,
    CLIAgentError,
    CLINotFoundError,
    CLIParseError,
    CLISubprocessError,
    CLITimeoutError,
)
from aragora.agents.errors.handlers import (
    AgentErrorHandler,
    _build_error_action,
    handle_agent_operation,
    make_fallback_message,
)

__all__ = [
    "_SENSITIVE_PATTERNS",
    "ALL_FALLBACK_PATTERNS",
    "AUTH_ERROR_PATTERNS",
    "CLI_ERROR_PATTERNS",
    "CONTENT_POLICY_PATTERNS",
    "MODEL_ERROR_PATTERNS",
    "NETWORK_ERROR_PATTERNS",
    "RATE_LIMIT_PATTERNS",
    "VALIDATION_ERROR_PATTERNS",
    "AgentAPIError",
    "AgentCircuitOpenError",
    "AgentConnectionError",
    "AgentError",
    "AgentErrorHandler",
    "AgentRateLimitError",
    "AgentResponseError",
    "AgentStreamError",
    "AgentTimeoutError",
    "CLIAgentError",
    "CLINotFoundError",
    "CLIParseError",
    "CLISubprocessError",
    "CLITimeoutError",
    "ClassifiedError",
    "ErrorAction",
    "ErrorCategory",
    "ErrorClassifier",
    "ErrorContext",
    "ErrorSeverity",
    "RecoveryAction",
    "T",
    "_build_error_action",
    "_calculate_retry_delay_with_jitter",
    "_handle_agent_error",
    "_handle_connection_error",
    "_handle_json_error",
    "_handle_payload_error",
    "_handle_response_error",
    "_handle_timeout_error",
    "_handle_unexpected_error",
    "calculate_retry_delay_with_jitter",
    "classify_cli_error",
    "handle_agent_errors",
    "handle_agent_operation",
    "handle_stream_errors",
    "make_fallback_message",
    "sanitize_error",
    "with_error_handling",
]
