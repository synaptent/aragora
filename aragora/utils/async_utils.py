"""
Async utility functions for safe sync/async bridging.

Provides utilities for running async code from sync contexts, handling
the common case where code may be called from either sync or async contexts.

Also includes async subprocess utilities for non-blocking command execution.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, TypeVar
from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)

T = TypeVar("T")
PoolEventLoopProvider = Callable[[], asyncio.AbstractEventLoop | None]

_pool_event_loop_provider: PoolEventLoopProvider | None = None


def register_pool_event_loop_provider(provider: PoolEventLoopProvider | None) -> None:
    """Register the infrastructure callback that resolves the shared pool loop."""
    global _pool_event_loop_provider
    _pool_event_loop_provider = provider


def get_pool_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the shared pool event loop without importing storage infrastructure."""
    if _pool_event_loop_provider is None:
        return None
    return _pool_event_loop_provider()


def _run_async_in_worker_thread(coro: Coroutine[Any, Any, T], timeout: float) -> T:
    """Run a coroutine on a dedicated worker thread when the current loop cannot be re-entered."""

    result: dict[str, Any] = {"value": None, "error": None}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(asyncio.wait_for(coro, timeout=timeout))
        except BaseException as exc:  # noqa: BLE001 - preserve original exception
            result["error"] = exc

    thread = threading.Thread(target=_runner, name="run_async_worker", daemon=True)
    thread.start()
    thread.join(timeout + 1.0)

    if thread.is_alive():
        raise TimeoutError(f"run_async() worker thread timed out after {timeout:.1f}s")
    if result["error"] is not None:
        raise result["error"]
    return result["value"]


def run_async(coro: Coroutine[Any, Any, T], timeout: float = 30.0) -> T:
    """Run async coroutine from sync context, dispatching to the correct event loop.

    Handles five scenarios:
    1. Already on the main event loop (sync handler called from async handle()):
       Uses loop.run_until_complete() with nest_asyncio support.
    2. Already on a different async event loop while the shared pool loop is alive:
       Dispatches to the shared loop via run_coroutine_threadsafe().
    3. Already on an async event loop with no shared pool loop to re-enter:
       Runs the coroutine on a dedicated worker thread.
    4. In a different thread with no running loop (sync HTTP handler thread):
       Dispatches to the main event loop via run_coroutine_threadsafe().
    5. No shared pool (CLI/SQLite mode):
       Creates a temporary event loop via asyncio.run().

    Args:
        coro: Coroutine to execute
        timeout: Maximum time to wait (seconds), default 30

    Returns:
        Result from the coroutine

    Raises:
        RuntimeError: If called from an unrelated async context
        Exception: Any exception from the coroutine
        TimeoutError: If execution exceeds timeout
    """
    # Check if there's already a running event loop in this thread.
    running_loop: asyncio.AbstractEventLoop | None = None
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass  # No running loop - handled below

    if running_loop is not None:
        # We're on an event loop. Check if it's the main pool loop
        # (sync handler called from async handle() on the main loop).
        # nest_asyncio is applied to the main loop in pool_manager, so
        # loop.run_until_complete() works for nested calls.
        main_loop = get_pool_event_loop()

        if main_loop is not None and main_loop.is_running():
            if running_loop is main_loop:
                try:
                    return running_loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
                except RuntimeError as exc:
                    message = str(exc)
                    if "already running" in message or "Cannot enter into task" in message:
                        return _run_async_in_worker_thread(coro, timeout)
                    raise
            future = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(coro, timeout=timeout),
                main_loop,
            )
            return future.result(timeout=timeout)

        # Fallback: apply nest_asyncio to allow nested run_until_complete
        # (covers test environments and CLI where pool_manager is absent)
        try:
            import nest_asyncio

            nest_asyncio.apply(running_loop)
            return running_loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
        except ImportError:
            return _run_async_in_worker_thread(coro, timeout)
        except RuntimeError as exc:
            message = str(exc)
            if "already running" in message or "Cannot enter into task" in message:
                return _run_async_in_worker_thread(coro, timeout)

        # Running loop but NOT the main pool loop - caller bug
        coro.close()
        raise RuntimeError(
            "run_async() cannot be called from an async context. "
            "asyncpg connection pools are bound to specific event loops. "
            "Use 'await coro' directly instead of 'run_async(coro)'. "
            f"Current event loop: {running_loop}"
        )

    # No running loop in this thread - we're in a sync context.
    # Try to dispatch to the main event loop where the asyncpg pool lives.
    main_loop = get_pool_event_loop()
    if main_loop is not None and main_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(coro, timeout=timeout),
            main_loop,
        )
        return future.result(timeout=timeout)

    # Fallback: no shared pool / CLI mode - create temporary event loop
    return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


def sync_wrapper(async_method: Any) -> Any:
    """Decorator that creates a sync wrapper for an async method.

    Use this to eliminate boilerplate sync/async pairs in store classes.
    The generated sync method calls run_async() to bridge to the async impl.

    Usage::

        class MyStore:
            async def get_async(self, id: str) -> Item | None:
                ...

            # Instead of writing:
            #   def get(self, id): return run_async(self.get_async(id))
            # Just do:
            get = sync_wrapper(get_async)

    Or as a class decorator helper::

        class MyStore:
            async def save_async(self, data): ...
            async def delete_async(self, id): ...

            save = sync_wrapper(save_async)
            delete = sync_wrapper(delete_async)
    """
    import functools

    @functools.wraps(async_method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        return run_async(async_method(self, *args, **kwargs))

    # Mark as auto-generated for introspection
    wrapper._is_sync_wrapper = True  # type: ignore[attr-defined]
    wrapper._async_method = async_method  # type: ignore[attr-defined]
    return wrapper


# Semaphore to limit concurrent subprocess calls (prevent resource exhaustion)
_subprocess_semaphore = asyncio.Semaphore(10)


async def run_command(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: float = 60.0,
    input_data: bytes | None = None,
) -> tuple[int, bytes, bytes]:
    """Run command asynchronously without blocking event loop.

    Uses asyncio.create_subprocess_exec for non-blocking execution.
    Limits concurrent subprocess calls to prevent resource exhaustion.

    Args:
        cmd: Command and arguments as list
        cwd: Optional working directory
        timeout: Timeout in seconds (default 60)
        input_data: Optional stdin data

    Returns:
        Tuple of (return_code, stdout, stderr)

    Raises:
        asyncio.TimeoutError: If command exceeds timeout
        FileNotFoundError: If command not found
    """
    async with _subprocess_semaphore:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if input_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(input_data), timeout=timeout)
            return proc.returncode or 0, stdout, stderr
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise


async def run_git_command(args: list[str], cwd: Path, timeout: float = 30.0) -> tuple[bool, str]:
    """Run git command asynchronously.

    Convenience wrapper for common git operations.

    Args:
        args: Git subcommand and arguments (e.g., ["status", "-s"])
        cwd: Repository directory
        timeout: Timeout in seconds (default 30)

    Returns:
        Tuple of (success: bool, output_or_error: str)
    """
    try:
        returncode, stdout, stderr = await run_command(["git"] + args, cwd=cwd, timeout=timeout)
        if returncode == 0:
            return True, stdout.decode(errors="replace")
        return False, stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        return False, "Git command timed out"
    except FileNotFoundError:
        return False, "Git not found"
    except OSError as e:
        return False, str(e)


def get_event_loop_safe() -> asyncio.AbstractEventLoop:
    """Get event loop safely, avoiding the deprecated asyncio.get_event_loop().

    This function handles the Python 3.10+ deprecation of get_event_loop() which
    emits a DeprecationWarning when called outside an async context.

    Returns:
        The running event loop if available, otherwise creates a new one.

    Note:
        In async code, prefer asyncio.get_running_loop() directly.
        This function is mainly for sync code that needs to schedule work
        on an event loop.
    """
    try:
        # First try to get a running loop (we're in async context)
        return asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - we're in sync context
        # Create a new event loop for this thread (avoids deprecation warning)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def run_sync_in_async_context(func: Any, *args: Any, **kwargs: Any) -> asyncio.Future:
    """Run a synchronous function in the executor from an async context.

    This is the proper replacement for:
        asyncio.get_event_loop().run_in_executor(None, func, *args)

    Args:
        func: Synchronous callable to run
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func (will use functools.partial)

    Returns:
        Future that resolves to the function's return value

    Raises:
        RuntimeError: If not called from an async context
    """
    import functools

    loop = asyncio.get_running_loop()  # Raises if not in async context
    if kwargs:
        func = functools.partial(func, **kwargs)
    return loop.run_in_executor(None, func, *args)


def schedule_background_task(coro: Coroutine[Any, Any, T]) -> None:
    """Schedule a coroutine to run in the background (fire-and-forget).

    Works from both sync and async contexts. In async context, uses create_task.
    In sync context, schedules on the event loop.

    Args:
        coro: Coroutine to execute in background

    Note:
        The coroutine's result is ignored. Exceptions are logged but not raised.
    """
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        task.add_done_callback(_log_task_exception)
    except RuntimeError:
        # No running loop - need to handle differently
        loop = get_event_loop_safe()
        if loop.is_running():
            loop.call_soon_threadsafe(lambda: loop.create_task(coro))
        else:
            # Run the coroutine blocking if no loop is available
            try:
                asyncio.run(coro)
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("Background task failed: %s", e)


def _log_task_exception(task: asyncio.Task) -> None:
    """Callback to log exceptions from background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background task failed: %s", exc, exc_info=exc)


# =============================================================================
# Task Lifecycle Management
# =============================================================================


class TaskRegistry:
    """Registry for tracking and managing background tasks.

    Provides a central place to track all background tasks, enabling graceful
    shutdown by waiting for or cancelling pending tasks.

    Usage:
        registry = TaskRegistry()

        # Register a task
        task = asyncio.create_task(some_coro())
        registry.register(task, name="my-task")

        # Later, during shutdown
        await registry.cancel_all(timeout=5.0)
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._counter = 0

    def register(
        self,
        task: asyncio.Task,
        name: str | None = None,
        log_exceptions: bool = True,
    ) -> str:
        """Register a task for tracking.

        Args:
            task: The asyncio.Task to track
            name: Optional name for the task (auto-generated if not provided)
            log_exceptions: Whether to log exceptions (default True)

        Returns:
            The task name (for later reference)
        """
        if name is None:
            self._counter += 1
            name = f"task-{self._counter}"

        self._tasks[name] = task

        def on_done(t: asyncio.Task) -> None:
            self._tasks.pop(name, None)
            if log_exceptions and not t.cancelled():
                exc = t.exception()
                if exc is not None:
                    logger.error("Task %s failed: %s", name, exc, exc_info=exc)

        task.add_done_callback(on_done)
        return name

    def get(self, name: str) -> asyncio.Task | None:
        """Get a task by name."""
        return self._tasks.get(name)

    @property
    def active_tasks(self) -> list[str]:
        """Get names of all active (not done) tasks."""
        return [name for name, task in self._tasks.items() if not task.done()]

    @property
    def count(self) -> int:
        """Get count of active tasks."""
        return len([t for t in self._tasks.values() if not t.done()])

    async def cancel_all(self, timeout: float = 5.0) -> int:
        """Cancel all tracked tasks and wait for completion.

        Args:
            timeout: Maximum time to wait for tasks to finish (seconds)

        Returns:
            Number of tasks that were cancelled
        """
        cancelled = 0
        tasks = list(self._tasks.values())

        for task in tasks:
            if not task.done():
                task.cancel()
                cancelled += 1

        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for %s tasks to cancel", len(tasks))

        return cancelled

    async def wait_all(self, timeout: float | None = None) -> None:
        """Wait for all tracked tasks to complete.

        Args:
            timeout: Maximum time to wait (None for no timeout)
        """
        tasks = [t for t in self._tasks.values() if not t.done()]
        if not tasks:
            return

        if timeout:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        else:
            await asyncio.gather(*tasks, return_exceptions=True)


# Global task registry for background tasks
_global_registry = TaskRegistry()


def get_task_registry() -> TaskRegistry:
    """Get the global task registry."""
    return _global_registry


def create_tracked_task(
    coro: Coroutine[Any, Any, T],
    name: str | None = None,
) -> asyncio.Task:
    """Create an asyncio task and register it in the global registry.

    This is a convenience function that combines create_task with registration.

    Args:
        coro: Coroutine to run
        name: Optional name for the task

    Returns:
        The created task
    """
    task = asyncio.create_task(coro)
    _global_registry.register(task, name=name)
    return task


async def graceful_shutdown(
    timeout: float = 10.0,
    cancel_tasks: bool = True,
) -> None:
    """Gracefully shutdown async operations.

    Cancels all tracked tasks and waits for them to complete.
    Should be called during application shutdown.

    Args:
        timeout: Maximum time to wait for tasks
        cancel_tasks: Whether to cancel tasks (vs just waiting)
    """
    registry = get_task_registry()
    count = registry.count

    if count == 0:
        logger.debug("No active tasks to shutdown")
        return

    logger.info("Shutting down %s active tasks...", count)

    if cancel_tasks:
        cancelled = await registry.cancel_all(timeout=timeout)
        logger.info("Cancelled %s tasks", cancelled)
    else:
        await registry.wait_all(timeout=timeout)
        logger.info("All tasks completed")


__all__ = [
    # Sync/async bridging
    "get_event_loop_safe",
    "run_async",
    "run_sync_in_async_context",
    "schedule_background_task",
    # Command execution
    "run_command",
    "run_git_command",
    # Task lifecycle management
    "TaskRegistry",
    "create_tracked_task",
    "get_task_registry",
    "graceful_shutdown",
]
