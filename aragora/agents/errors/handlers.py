"""
Exception handler utilities for agent operations.

Provides reusable error handling patterns for async agent operations,
implementing the "Autonomic layer" that keeps debates alive by gracefully
handling agent failures.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast
from collections.abc import Callable

from aragora.agents.types import T

from .classifier import ErrorClassifier

logger = logging.getLogger(__name__)


async def handle_agent_operation(
    operation: Callable[[], Any],
    agent_name: str,
    operation_name: str = "operation",
    fallback_value: T | None = None,
    fallback_message: str | None = None,
) -> T:
    """Execute an async agent operation with autonomic error handling.

    Implements the "Autonomic layer" pattern - catches all exceptions to keep
    debates alive. Logs appropriately based on error type.

    Args:
        operation: Async callable to execute (e.g., lambda: agent.generate(prompt))
        agent_name: Name of the agent for logging
        operation_name: Name of the operation for logging (e.g., "generate", "critique")
        fallback_value: Value to return on error (default: None)
        fallback_message: If provided, return this string message on error
                         (overrides fallback_value for string operations)

    Returns:
        Result of operation, or fallback_value/fallback_message on error

    Example:
        # For generate (returns string message on error)
        result = await handle_agent_operation(
            lambda: agent.generate(prompt, context),
            agent.name,
            "generate",
            fallback_message=f"[System: Agent {agent.name} error - skipping]"
        )

        # For critique/vote (returns None on error)
        critique = await handle_agent_operation(
            lambda: agent.critique(proposal, task, context),
            agent.name,
            "critique",
            fallback_value=None
        )
    """
    try:
        return await operation()

    except asyncio.TimeoutError:
        logger.warning("[Autonomic] Agent %s %s timed out", agent_name, operation_name)
        return cast(T, fallback_message if fallback_message else fallback_value)

    except (ConnectionError, OSError) as e:
        logger.warning(
            "[Autonomic] Agent %s %s connection error: %s", agent_name, operation_name, e
        )
        return cast(T, fallback_message if fallback_message else fallback_value)

    except Exception as e:  # noqa: BLE001 - Intentional catch-all: autonomic error handler is the last-resort safety net keeping debates alive
        # Use ErrorClassifier for more detailed categorization
        _, category = ErrorClassifier.classify_error(e)
        logger.exception(
            "[Autonomic] Agent %s %s failed (%s): %s: %s",
            agent_name,
            operation_name,
            category,
            type(e).__name__,
            e,
        )
        return cast(T, fallback_message if fallback_message else fallback_value)


class AgentErrorHandler:
    """Context manager for agent error handling with automatic fallback.

    Provides a cleaner interface for wrapping agent operations.

    Example:
        async with AgentErrorHandler(agent.name, "generate") as handler:
            result = await agent.generate(prompt, context)
            handler.set_result(result)

        # If error occurred, handler.result is the fallback value
        output = handler.result or "[System: Error occurred]"
    """

    def __init__(
        self,
        agent_name: str,
        operation_name: str = "operation",
        fallback_value: Any = None,
    ):
        self.agent_name = agent_name
        self.operation_name = operation_name
        self.fallback_value = fallback_value
        self.result = fallback_value
        self.error: Exception | None = None

    def set_result(self, value: Any) -> None:
        """Set the successful result."""
        self.result = value

    async def __aenter__(self) -> AgentErrorHandler:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            return False

        self.error = exc_val

        if exc_type is asyncio.TimeoutError:
            logger.warning(
                "[Autonomic] Agent %s %s timed out", self.agent_name, self.operation_name
            )
            return True  # Suppress exception

        if issubclass(exc_type, (ConnectionError, OSError)):
            logger.warning(
                "[Autonomic] Agent %s %s connection error: %s",
                self.agent_name,
                self.operation_name,
                exc_val,
            )
            return True

        # General exception
        _, category = ErrorClassifier.classify_error(exc_val)
        logger.exception(
            "[Autonomic] Agent %s %s failed (%s): %s: %s",
            self.agent_name,
            self.operation_name,
            category,
            type(exc_val).__name__,
            exc_val,
        )
        return True  # Suppress exception and use fallback


def make_fallback_message(agent_name: str, operation: str = "turn") -> str:
    """Generate a standardized system fallback message.

    Args:
        agent_name: Name of the failing agent
        operation: What was being attempted

    Returns:
        Formatted system message for inclusion in debate context
    """
    return f"[System: Agent {agent_name} encountered an error - skipping this {operation}]"


def _build_error_action(e: Exception, context: str = "") -> tuple[str, str, bool]:
    """Build error action info for consistent logging.

    Classifies an exception and returns logging information.

    Args:
        e: The exception to classify
        context: Optional context string (e.g., "calibration", "memory")

    Returns:
        Tuple of (category, log_message, should_use_exc_info)
    """
    _, category = ErrorClassifier.classify_error(e)

    prefix = f"[{context}] " if context else ""
    type_name = type(e).__name__

    # Build message with category context
    log_message = f"{prefix}{type_name} ({category}): {e}"

    # Use exc_info for unexpected/unknown errors
    should_use_exc_info = category == "unknown"

    return category, log_message, should_use_exc_info


__all__ = [
    "handle_agent_operation",
    "AgentErrorHandler",
    "make_fallback_message",
    "_build_error_action",
]
