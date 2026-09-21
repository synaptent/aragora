"""
Arena lifecycle management.

Extracted from Arena to reduce orchestrator size. Handles:
- Async context manager protocol (__aenter__/__aexit__)
- Cleanup operations (tasks, checkpoint manager, caches)
- Circuit breaker metrics tracking
- Phase failure logging
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import TYPE_CHECKING

from aragora.observability.server_metrics import track_circuit_breaker_state

if TYPE_CHECKING:
    from typing import Any

    from aragora.debate.protocol import CircuitBreaker
    from aragora.debate.state_cache import DebateStateCache

logger = logging.getLogger(__name__)


class LifecycleManager:
    """Manages Arena lifecycle operations including cleanup.

    Extracted from Arena to centralize lifecycle-related operations:
    - Context manager enter/exit
    - Task cancellation
    - Checkpoint manager cleanup
    - Cache clearing
    - Circuit breaker metrics

    Usage:
        manager = LifecycleManager(
            cache=cache,
            circuit_breaker=breaker,
            checkpoint_manager=checkpoint_mgr,
        )
        await manager.cleanup()
    """

    def __init__(
        self,
        cache: DebateStateCache | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        checkpoint_manager: Any = None,
    ) -> None:
        """Initialize lifecycle manager.

        Args:
            cache: Optional state cache to clear on cleanup
            circuit_breaker: Optional circuit breaker for metrics
            checkpoint_manager: Optional checkpoint manager to close
        """
        self._cache = cache
        self.circuit_breaker = circuit_breaker
        self.checkpoint_manager = checkpoint_manager

    def is_arena_task(self, task: asyncio.Task) -> bool:
        """Check if an asyncio task is arena-related and should be cancelled."""
        task_name = task.get_name() if hasattr(task, "get_name") else ""
        return bool(task_name and task_name.startswith(("arena_", "debate_")))

    async def cancel_task(self, task: asyncio.Task) -> None:
        """Cancel and await a single arena-related task with timeout."""
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except (asyncio.CancelledError, asyncio.TimeoutError) as e:
            logger.debug("Task cancellation completed: %s", e)

    async def cancel_arena_tasks(self) -> None:
        """Cancel all pending arena-related asyncio tasks."""
        try:
            for task in asyncio.all_tasks():
                if self.is_arena_task(task):
                    await self.cancel_task(task)
        except (RuntimeError, OSError) as e:
            logger.debug("Error cancelling tasks during cleanup: %s", e)

    async def close_checkpoint_manager(self) -> None:
        """Close the checkpoint manager if it exists and has a close method."""
        if not self.checkpoint_manager or not hasattr(self.checkpoint_manager, "close"):
            return
        try:
            close_result = self.checkpoint_manager.close()
            if asyncio.iscoroutine(close_result):
                await close_result
        except (RuntimeError, OSError, AttributeError) as e:
            logger.debug("Error closing checkpoint manager: %s", e)

    def count_open_circuit_breakers(self) -> int:
        """Count the number of open circuit breakers across all agents."""
        if not self.circuit_breaker:
            return 0
        agent_states = getattr(self.circuit_breaker, "_agent_states", {})
        return sum(1 for state in agent_states.values() if getattr(state, "is_open", False))

    def track_circuit_breaker_metrics(self) -> None:
        """Track circuit breaker state in metrics if circuit breaker is enabled."""
        if self.circuit_breaker:
            track_circuit_breaker_state(self.count_open_circuit_breakers())

    def log_phase_failures(self, execution_result: Any) -> None:
        """Log any failed phases from the execution result."""
        if execution_result.success:
            return
        error_phases = [p.phase_name for p in execution_result.phases if p.status.value == "failed"]
        if error_phases:
            logger.warning("Phase failures: %s", error_phases)

    def clear_cache(self) -> None:
        """Clear the state cache if it exists."""
        if self._cache:
            self._cache.clear()

    async def cleanup(self) -> None:
        """Perform full cleanup of arena resources.

        Cancels tasks, clears caches, and closes checkpoint manager.
        """
        await self.cancel_arena_tasks()
        self.clear_cache()
        await self.close_checkpoint_manager()


class ArenaContextManager:
    """Async context manager mixin for Arena.

    Provides __aenter__ and __aexit__ implementation that delegates
    to LifecycleManager for the actual cleanup work.

    Usage:
        class Arena(ArenaContextManager):
            def __init__(self):
                self._lifecycle = LifecycleManager(...)

            async def _cleanup(self):
                await self._lifecycle.cleanup()
    """

    async def _cleanup(self) -> None:
        """Cleanup resources. Subclasses should override this."""

    async def __aenter__(self) -> ArenaContextManager:
        """Enter async context - prepare for debate.

        Enables usage pattern:
            async with Arena(env, agents, protocol) as arena:
                result = await arena.run()
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context - cleanup resources.

        Cancels any pending arena-related tasks and clears caches.
        This ensures clean teardown even when tests timeout or fail.
        """
        await self._cleanup()


__all__ = ["LifecycleManager", "ArenaContextManager"]
