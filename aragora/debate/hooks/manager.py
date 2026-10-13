"""
Extended Hooks System for Debate and Audit Lifecycle.

Adapted from claude-flow (MIT License)
Pattern: Extensible automation at phase boundaries
Original: https://github.com/ruvnet/claude-flow

Aragora adaptations:
- Integration with DebateContext for state access
- Audit-specific hooks (on_finding, on_contradiction)
- Async and sync callback support
- Hook priority ordering
- Typed hook signatures with Protocol

Usage:
    manager = HookManager()

    # Register hooks
    manager.register("on_round_end", lambda ctx, round: save_checkpoint(ctx, round))
    manager.register("on_finding", lambda finding: notify_dashboard(finding))

    # Trigger hooks
    await manager.trigger("on_round_end", ctx=context, round=3)
"""

from __future__ import annotations

__all__ = [
    "HookManager",
    "HookPriority",
    "HookType",
    "HookCallback",
    "DebateHooks",
    "AuditHooks",
    "PropulsionHooks",
    "create_hook_manager",
]

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
)
from collections.abc import Callable, Coroutine

if TYPE_CHECKING:
    from aragora.audit.types import AuditFinding
    from aragora.core import Agent, Critique, DebateResult, Vote
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)


class HookPriority(IntEnum):
    """Hook execution priority (lower values run first)."""

    CRITICAL = 0  # Safety/validation hooks
    HIGH = 10  # Core functionality
    NORMAL = 50  # Default priority
    LOW = 90  # Logging/telemetry
    CLEANUP = 100  # Cleanup handlers


class HookType(str, Enum):
    """Standard hook types for debate and audit lifecycle."""

    # Debate lifecycle hooks
    PRE_DEBATE = "pre_debate"
    POST_DEBATE = "post_debate"
    PRE_ROUND = "pre_round"
    POST_ROUND = "post_round"
    PRE_PHASE = "pre_phase"
    POST_PHASE = "post_phase"

    # Agent hooks
    PRE_GENERATE = "pre_generate"
    POST_GENERATE = "post_generate"
    PRE_CRITIQUE = "pre_critique"
    POST_CRITIQUE = "post_critique"
    PRE_VOTE = "pre_vote"
    POST_VOTE = "post_vote"

    # Consensus hooks
    PRE_CONSENSUS = "pre_consensus"
    POST_CONSENSUS = "post_consensus"
    ON_CONVERGENCE = "on_convergence"

    # Audit hooks
    ON_FINDING = "on_finding"
    ON_CONTRADICTION = "on_contradiction"
    ON_INCONSISTENCY = "on_inconsistency"
    ON_EVIDENCE = "on_evidence"
    ON_PROGRESS = "on_progress"

    # Error hooks
    ON_ERROR = "on_error"
    ON_TIMEOUT = "on_timeout"
    ON_CANCELLATION = "on_cancellation"

    # Session hooks
    ON_PAUSE = "on_pause"
    ON_RESUME = "on_resume"
    ON_CHECKPOINT = "on_checkpoint"

    # Propulsion hooks (Gastown pattern - push-based work assignment)
    ON_READY = "on_ready"  # Agent signals readiness for work
    ON_PROPEL = "on_propel"  # Push work to next stage
    ON_ESCALATE = "on_escalate"  # Escalation trigger (severity threshold crossed)
    ON_MOLECULE_COMPLETE = "on_molecule_complete"  # Multi-step workflow completed


# Type alias for hook callbacks
HookCallback = Callable[..., Any] | Callable[..., Coroutine[Any, Any, Any]]


@dataclass
class RegisteredHook:
    """A registered hook with metadata."""

    callback: HookCallback
    priority: HookPriority
    name: str
    once: bool = False  # If True, unregister after first call


class DebateHooks(Protocol):
    """Protocol for debate lifecycle hooks."""

    def on_pre_debate(
        self, ctx: DebateContext, agents: list[Agent]
    ) -> Coroutine[Any, Any, None] | None: ...

    def on_post_debate(
        self, ctx: DebateContext, result: DebateResult
    ) -> Coroutine[Any, Any, None] | None: ...

    def on_pre_round(
        self, ctx: DebateContext, round_num: int
    ) -> Coroutine[Any, Any, None] | None: ...

    def on_post_round(
        self, ctx: DebateContext, round_num: int, proposals: dict[str, str]
    ) -> Coroutine[Any, Any, None] | None: ...

    def on_pre_critique(
        self, ctx: DebateContext, agent: Agent, target: str
    ) -> Coroutine[Any, Any, None] | None: ...

    def on_post_critique(
        self, ctx: DebateContext, critique: Critique
    ) -> Coroutine[Any, Any, None] | None: ...

    def on_post_vote(self, ctx: DebateContext, vote: Vote) -> Coroutine[Any, Any, None] | None: ...


class AuditHooks(Protocol):
    """Protocol for audit-specific hooks."""

    def on_finding(self, finding: AuditFinding) -> Coroutine[Any, Any, None] | None: ...

    def on_contradiction(
        self, agent_a: str, agent_b: str, claim: str, round_num: int
    ) -> Coroutine[Any, Any, None] | None: ...

    def on_inconsistency(
        self, agent: str, round_a: int, round_b: int, claims: tuple[str, str]
    ) -> Coroutine[Any, Any, None] | None: ...

    def on_evidence(
        self, source: str, claim: str, strength: float
    ) -> Coroutine[Any, Any, None] | None: ...

    def on_progress(
        self, phase: str, completed: int, total: int
    ) -> Coroutine[Any, Any, None] | None: ...


class PropulsionHooks(Protocol):
    """Protocol for propulsion hooks (Gastown pattern - push-based work assignment)."""

    def on_ready(self, agent: str, capabilities: list[str]) -> Coroutine[Any, Any, None] | None:
        """Called when an agent signals readiness for work."""
        ...

    def on_propel(
        self, source_stage: str, target_stage: str, payload: dict[str, Any]
    ) -> Coroutine[Any, Any, None] | None:
        """Called to push work to the next stage in a pipeline."""
        ...

    def on_escalate(
        self, severity: str, source: str, reason: str, context: dict[str, Any]
    ) -> Coroutine[Any, Any, None] | None:
        """Called when an escalation is triggered (severity threshold crossed)."""
        ...

    def on_molecule_complete(
        self, molecule_id: str, steps_completed: int, result: dict[str, Any]
    ) -> Coroutine[Any, Any, None] | None:
        """Called when a multi-step workflow (molecule) completes."""
        ...


@dataclass
class HookManager:
    """
    Manager for registering and triggering lifecycle hooks.

    Supports:
    - Multiple callbacks per hook type
    - Priority ordering
    - Async and sync callbacks
    - One-time hooks (auto-unregister after first call)
    - Error isolation (one failed hook doesn't stop others)
    """

    _hooks: dict[str, list[RegisteredHook]] = field(default_factory=lambda: defaultdict(list))
    _enabled: bool = True
    _error_handler: Callable[[str, Exception], None] | None = None

    def register(
        self,
        hook_type: str | HookType,
        callback: HookCallback,
        *,
        priority: HookPriority = HookPriority.NORMAL,
        name: str | None = None,
        once: bool = False,
    ) -> Callable[[], None]:
        """
        Register a callback for a hook type.

        Args:
            hook_type: The hook type (string or HookType enum)
            callback: Function to call when hook is triggered
            priority: Execution priority (lower = earlier)
            name: Optional name for the hook (for debugging)
            once: If True, unregister after first call

        Returns:
            Unregister function to remove the callback
        """
        hook_key = hook_type.value if isinstance(hook_type, HookType) else hook_type
        hook_name = name or f"{hook_key}_{len(self._hooks[hook_key])}"

        registered = RegisteredHook(
            callback=callback,
            priority=priority,
            name=hook_name,
            once=once,
        )

        self._hooks[hook_key].append(registered)
        # Sort by priority
        self._hooks[hook_key].sort(key=lambda h: h.priority)

        logger.debug("Registered hook: %s for %s (priority=%s)", hook_name, hook_key, priority)

        def unregister() -> None:
            if registered in self._hooks[hook_key]:
                self._hooks[hook_key].remove(registered)
                logger.debug("Unregistered hook: %s", hook_name)

        return unregister

    def unregister(self, hook_type: str | HookType, name: str) -> bool:
        """
        Unregister a hook by name.

        Args:
            hook_type: The hook type
            name: Name of the hook to remove

        Returns:
            True if hook was found and removed
        """
        hook_key = hook_type.value if isinstance(hook_type, HookType) else hook_type

        for hook in self._hooks[hook_key]:
            if hook.name == name:
                self._hooks[hook_key].remove(hook)
                logger.debug("Unregistered hook: %s", name)
                return True
        return False

    def clear(self, hook_type: str | HookType | None = None) -> None:
        """
        Clear all hooks of a type, or all hooks if type is None.

        Args:
            hook_type: Optional hook type to clear (clears all if None)
        """
        if hook_type is None:
            self._hooks.clear()
            logger.debug("Cleared all hooks")
        else:
            hook_key = hook_type.value if isinstance(hook_type, HookType) else hook_type
            self._hooks[hook_key].clear()
            logger.debug("Cleared hooks for %s", hook_key)

    async def trigger(
        self,
        hook_type: str | HookType,
        **kwargs: Any,
    ) -> list[Any]:
        """
        Trigger all callbacks for a hook type.

        Args:
            hook_type: The hook type to trigger
            **kwargs: Arguments to pass to callbacks

        Returns:
            List of results from callbacks (None for failed/void callbacks)
        """
        if not self._enabled:
            return []

        hook_key = hook_type.value if isinstance(hook_type, HookType) else hook_type
        hooks = self._hooks.get(hook_key, [])

        if not hooks:
            return []

        results: list[Any] = []
        to_remove: list[RegisteredHook] = []

        for hook in hooks:
            try:
                result = hook.callback(**kwargs)

                # Await if coroutine
                if asyncio.iscoroutine(result):
                    result = await result

                results.append(result)

                if hook.once:
                    to_remove.append(hook)

            except (TypeError, ValueError, AttributeError) as e:
                # Expected errors from hook callback signature mismatches or invalid data
                logger.warning("Hook %s failed with expected error: %s", hook.name, e)
                results.append(None)

                if self._error_handler:
                    try:
                        self._error_handler(hook.name, e)
                    except Exception as handler_error:  # noqa: BLE001 - error handler isolation: prevent handler failures from cascading
                        # Don't let error handler failures cascade
                        logger.debug(
                            "Error handler failed for hook %s: %s", hook.name, handler_error
                        )
            except Exception as e:  # noqa: BLE001 - hook isolation boundary: user-provided callbacks can raise any exception
                # Unexpected errors from hook callback
                logger.exception("Hook %s failed with unexpected error: %s", hook.name, e)
                results.append(None)

                if self._error_handler:
                    try:
                        self._error_handler(hook.name, e)
                    except Exception as handler_error:  # noqa: BLE001 - error handler isolation: prevent handler failures from cascading
                        # Don't let error handler failures cascade
                        logger.debug(
                            "Error handler failed for hook %s: %s", hook.name, handler_error
                        )

        # Remove one-time hooks
        for hook in to_remove:
            if hook in self._hooks[hook_key]:
                self._hooks[hook_key].remove(hook)

        return results

    def trigger_sync(
        self,
        hook_type: str | HookType,
        **kwargs: Any,
    ) -> list[Any]:
        """
        Trigger hooks synchronously (for sync callbacks only).

        Args:
            hook_type: The hook type to trigger
            **kwargs: Arguments to pass to callbacks

        Returns:
            List of results from callbacks
        """
        if not self._enabled:
            return []

        hook_key = hook_type.value if isinstance(hook_type, HookType) else hook_type
        hooks = self._hooks.get(hook_key, [])

        if not hooks:
            return []

        results: list[Any] = []
        to_remove: list[RegisteredHook] = []

        for hook in hooks:
            try:
                result = hook.callback(**kwargs)

                if asyncio.iscoroutine(result):
                    logger.warning(
                        "Hook %s returned coroutine in sync trigger - skipping", hook.name
                    )
                    results.append(None)
                    continue

                results.append(result)

                if hook.once:
                    to_remove.append(hook)

            except (TypeError, ValueError, AttributeError) as e:
                # Expected errors from hook callback signature mismatches or invalid data
                logger.warning("Hook %s failed with expected error: %s", hook.name, e)
                results.append(None)

                if self._error_handler:
                    try:
                        self._error_handler(hook.name, e)
                    except Exception as handler_error:  # noqa: BLE001 - error handler isolation: prevent handler failures from cascading
                        # Don't let error handler failures cascade
                        logger.debug(
                            "Error handler failed for hook %s: %s", hook.name, handler_error
                        )
            except Exception as e:  # noqa: BLE001 - hook isolation boundary: user-provided callbacks can raise any exception
                # Unexpected errors from hook callback
                logger.exception("Hook %s failed with unexpected error: %s", hook.name, e)
                results.append(None)

                if self._error_handler:
                    try:
                        self._error_handler(hook.name, e)
                    except Exception as handler_error:  # noqa: BLE001 - error handler isolation: prevent handler failures from cascading
                        # Don't let error handler failures cascade
                        logger.debug(
                            "Error handler failed for hook %s: %s", hook.name, handler_error
                        )

        # Remove one-time hooks
        for hook in to_remove:
            if hook in self._hooks[hook_key]:
                self._hooks[hook_key].remove(hook)

        return results

    def enable(self) -> None:
        """Enable hook triggering."""
        self._enabled = True

    def disable(self) -> None:
        """Disable hook triggering (hooks are still registered)."""
        self._enabled = False

    def set_error_handler(self, handler: Callable[[str, Exception], None] | None) -> None:
        """Set a custom error handler for hook failures."""
        self._error_handler = handler

    def get_hooks(self, hook_type: str | HookType) -> list[str]:
        """Get names of all registered hooks for a type."""
        hook_key = hook_type.value if isinstance(hook_type, HookType) else hook_type
        return [h.name for h in self._hooks.get(hook_key, [])]

    def has_hooks(self, hook_type: str | HookType) -> bool:
        """Check if any hooks are registered for a type."""
        hook_key = hook_type.value if isinstance(hook_type, HookType) else hook_type
        return bool(self._hooks.get(hook_key))

    @property
    def stats(self) -> dict[str, int]:
        """Get count of hooks per type."""
        return {k: len(v) for k, v in self._hooks.items() if v}


def create_hook_manager(
    *,
    error_handler: Callable[[str, Exception], None] | None = None,
) -> HookManager:
    """
    Create a new HookManager with optional configuration.

    Args:
        error_handler: Optional handler for hook errors

    Returns:
        Configured HookManager instance
    """
    manager = HookManager()
    if error_handler:
        manager.set_error_handler(error_handler)
    return manager


# Default hooks for common patterns


def create_logging_hooks(
    manager: HookManager,
    log_level: int = logging.DEBUG,
) -> None:
    """
    Register logging hooks for all standard hook types.

    Args:
        manager: HookManager to register with
        log_level: Logging level to use
    """
    hook_logger = logging.getLogger("aragora.hooks")

    for hook_type in HookType:

        def make_logger(ht: HookType):
            def log_hook(**kwargs: Any) -> None:
                hook_logger.log(
                    log_level,
                    "Hook triggered: %s",
                    ht.value,
                    extra={"hook_type": ht.value, "kwargs": list(kwargs.keys())},
                )

            return log_hook

        manager.register(
            hook_type,
            make_logger(hook_type),
            priority=HookPriority.LOW,
            name=f"logging_{hook_type.value}",
        )


def create_checkpoint_hooks(
    manager: HookManager,
    checkpoint_fn: Callable[[DebateContext, int], None],
) -> None:
    """
    Register checkpoint hooks for debate persistence.

    Args:
        manager: HookManager to register with
        checkpoint_fn: Function to call with (context, round_num)
    """

    def on_round_end(ctx: DebateContext, round_num: int, **kwargs: Any) -> None:
        checkpoint_fn(ctx, round_num)

    manager.register(
        HookType.POST_ROUND,
        on_round_end,
        priority=HookPriority.HIGH,
        name="checkpoint_post_round",
    )


def create_finding_hooks(
    manager: HookManager,
    on_finding: Callable[[AuditFinding], None],
    severity_threshold: float = 0.0,
) -> None:
    """
    Register hooks for audit findings above a severity threshold.

    Args:
        manager: HookManager to register with
        on_finding: Function to call with finding
        severity_threshold: Minimum severity to trigger (0-10)
    """

    def check_and_notify(finding: AuditFinding) -> None:
        if hasattr(finding, "severity") and finding.severity >= severity_threshold:
            on_finding(finding)

    manager.register(
        HookType.ON_FINDING,
        check_and_notify,
        priority=HookPriority.NORMAL,
        name=f"finding_threshold_{severity_threshold}",
    )
