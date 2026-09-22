"""
Streaming task context for event identification.

Provides a contextvars-based mechanism for tracking the current task_id
during streaming operations. This allows concurrent generate() calls
from the same agent to be distinguished in TOKEN_* events.

Extracted from aragora/server/stream/arena_hooks.py to break the
debate -> server coupling.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from collections.abc import Generator

# Context variable to track current task_id for streaming events
# This allows concurrent generate() calls from the same agent to be distinguished
_current_task_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_task_id", default=""
)


@contextmanager
def streaming_task_context(task_id: str) -> Generator[None, None, None]:
    """Context manager to set the current task_id for streaming events.

    Use this when calling agent methods that may stream, to ensure their
    TOKEN_* events include the task_id for proper grouping.

    Example:
        with streaming_task_context(f"{agent.name}:critique:{target}"):
            result = await agent.critique(proposal, task, context)
    """
    token = _current_task_id.set(task_id)
    try:
        yield
    finally:
        _current_task_id.reset(token)


def get_current_task_id() -> str:
    """Get the current task_id for streaming events."""
    return _current_task_id.get()


__all__ = ["streaming_task_context", "get_current_task_id"]
