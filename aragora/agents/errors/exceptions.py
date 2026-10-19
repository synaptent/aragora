"""
Custom exception hierarchy for agent operations.

Provides a structured exception hierarchy for agent errors with support for:
- Recoverable vs non-recoverable errors
- Agent identification
- Cause chaining
- CLI-specific error types
"""

from typing import Any

from aragora.exceptions import AragoraError

# =============================================================================
# API Agent Exceptions
# =============================================================================


class AgentError(AragoraError):
    """Base exception for all agent errors.

    Inherits from AragoraError to provide unified exception hierarchy
    while adding agent-specific attributes for retry/circuit-breaker logic.

    Attributes:
        agent_name: Name of the agent that raised the error
        cause: Original exception that caused this error
        recoverable: Whether the operation can be retried
    """

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        cause: Exception | None = None,
        recoverable: bool = True,
    ) -> None:
        # Build details dict for AragoraError
        details: dict[str, Any] = {}
        if agent_name:
            details["agent_name"] = agent_name
        if cause:
            details["cause_type"] = type(cause).__name__
        details["recoverable"] = recoverable

        super().__init__(message, details)
        self.agent_name = agent_name
        self.cause = cause
        self.recoverable = recoverable

    def __str__(self) -> str:
        parts = [self.message]
        if self.agent_name:
            parts.insert(0, f"[{self.agent_name}]")
        if self.cause:
            parts.append(f"(caused by: {type(self.cause).__name__}: {self.cause})")
        return " ".join(parts)


class AgentConnectionError(AgentError):
    """Network connection or HTTP errors."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        status_code: int | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, agent_name, cause, recoverable=True)
        self.status_code = status_code


class AgentTimeoutError(AgentError):
    """Timeout during agent operation."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        timeout_seconds: float | None = None,
        cause: Exception | None = None,
        partial_content: str | None = None,
    ) -> None:
        super().__init__(message, agent_name, cause, recoverable=True)
        self.timeout_seconds = timeout_seconds
        self.partial_content = partial_content


class AgentRateLimitError(AgentError):
    """Rate limit or quota exceeded."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        retry_after: float | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, agent_name, cause, recoverable=True)
        self.retry_after = retry_after


class AgentAPIError(AgentError):
    """API-specific error (invalid request, auth failure, etc.)."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        status_code: int | None = None,
        error_type: str | None = None,
        cause: Exception | None = None,
        reason: str | None = None,
        category: str | None = None,
        recoverable: bool | None = None,
    ) -> None:
        # 4xx errors are generally not recoverable (bad request, auth).
        # An explicit ``recoverable`` overrides that inference for a
        # provider-declared failure that carries no HTTP status yet is
        # definitively terminal (e.g. stop_reason == "refusal", which retrying
        # can only reproduce).
        if recoverable is None:
            recoverable = status_code is None or status_code >= 500
        super().__init__(message, agent_name, cause, recoverable=recoverable)
        self.status_code = status_code
        self.error_type = error_type
        # Structured cause for provider-declared non-HTTP failures, e.g. an
        # Anthropic 200 response with stop_reason == "refusal": reason is the
        # coarse kind ("refusal"), category is the provider's finer-grained
        # stop_details.category (e.g. "cyber") when it supplies one.
        self.reason = reason
        self.category = category


class AgentResponseError(AgentError):
    """Error parsing or validating agent response."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        response_data: Any = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, agent_name, cause, recoverable=False)
        self.response_data = response_data


class AgentStreamError(AgentError):
    """Error during streaming response."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        partial_content: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, agent_name, cause, recoverable=True)
        self.partial_content = partial_content


class AgentCircuitOpenError(AgentError):
    """Circuit breaker is open, blocking requests to agent.

    This error is raised when too many consecutive failures have occurred
    and the circuit breaker has opened to protect the system from cascading
    failures. The request should be retried after the cooldown period.
    """

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        cooldown_seconds: float | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, agent_name, cause, recoverable=True)
        self.cooldown_seconds = cooldown_seconds


# =============================================================================
# CLI Agent Exceptions
# =============================================================================


class CLIAgentError(AgentError):
    """Base class for CLI agent errors."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        returncode: int | None = None,
        stderr: str | None = None,
        cause: Exception | None = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message, agent_name, cause, recoverable)
        self.returncode = returncode
        self.stderr = stderr


class CLIParseError(CLIAgentError):
    """Error parsing CLI agent output (invalid JSON, etc.)."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        returncode: int | None = None,
        stderr: str | None = None,
        raw_output: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, agent_name, returncode, stderr, cause, recoverable=False)
        self.raw_output = raw_output


class CLITimeoutError(CLIAgentError):
    """CLI agent subprocess timed out."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        timeout_seconds: float | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, agent_name, returncode=-9, cause=cause, recoverable=True)
        self.timeout_seconds = timeout_seconds


class CLISubprocessError(CLIAgentError):
    """CLI subprocess failed with non-zero exit code."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        returncode: int | None = None,
        stderr: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        # Non-zero exit codes are generally recoverable (transient failures)
        super().__init__(message, agent_name, returncode, stderr, cause, recoverable=True)


class CLINotFoundError(CLIAgentError):
    """CLI tool not found or not installed."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        cli_name: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message, agent_name, returncode=127, cause=cause, recoverable=False)
        self.cli_name = cli_name


__all__ = [
    # Base
    "AgentError",
    # API errors
    "AgentConnectionError",
    "AgentTimeoutError",
    "AgentRateLimitError",
    "AgentAPIError",
    "AgentResponseError",
    "AgentStreamError",
    "AgentCircuitOpenError",
    # CLI errors
    "CLIAgentError",
    "CLIParseError",
    "CLITimeoutError",
    "CLISubprocessError",
    "CLINotFoundError",
]
