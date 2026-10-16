"""Execution mode for the Aragora pipeline.

AUTONOMOUS: Pre-approved by config. Used by boss loop, swarm, nomic loop.
    Safety comes from scope limits, merge gates, and explicit launch config.
INTERACTIVE: Per-action approval required. Used by API handlers, attended CLI.
    Safety comes from capability gates and the backbone ledger.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol


class ExecutionMode(str, Enum):
    AUTONOMOUS = "autonomous"
    INTERACTIVE = "interactive"


class SupportsInteractiveAuthContext(Protocol):
    """Minimal auth context contract for safety-mode inference."""

    user_id: str | None
    is_authenticated: bool | None


def _has_interactive_auth_context(auth_context: object | None) -> bool:
    """Return True only for contexts that look like real interactive users."""
    if auth_context is None:
        return False

    is_authenticated = getattr(auth_context, "is_authenticated", None)
    if is_authenticated is not None:
        return bool(is_authenticated)

    user_id = getattr(auth_context, "user_id", None)
    return isinstance(user_id, str) and bool(user_id.strip())


def resolve_safety_mode(
    mode: ExecutionMode | str | None,
    *,
    auth_context: SupportsInteractiveAuthContext | object | None = None,
    default: ExecutionMode = ExecutionMode.AUTONOMOUS,
    prefer_interactive_for_authenticated_context: bool = True,
) -> ExecutionMode:
    """Resolve safety mode from an explicit value or execution context."""
    if isinstance(mode, ExecutionMode):
        return mode

    normalized = str(mode or "").strip().lower()
    if normalized == ExecutionMode.INTERACTIVE.value:
        return ExecutionMode.INTERACTIVE
    if normalized == ExecutionMode.AUTONOMOUS.value:
        return ExecutionMode.AUTONOMOUS

    if prefer_interactive_for_authenticated_context and _has_interactive_auth_context(auth_context):
        return ExecutionMode.INTERACTIVE
    return default
