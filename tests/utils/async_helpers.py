"""Async test utilities with timeout support.

Provides helpers for running async code in tests with proper
timeout handling and clear error messages.
"""

import asyncio
import inspect
from typing import Any, Optional, TypeVar
from collections.abc import Callable, Coroutine

T = TypeVar("T")

# Default timeout for async operations in tests
DEFAULT_TIMEOUT = 30.0


async def run_with_timeout(
    coro: Coroutine[Any, Any, T],
    timeout: float = DEFAULT_TIMEOUT,
    *,
    operation_name: str | None = None,
) -> T:
    """Run a coroutine with a timeout and clear error message.

    This is a wrapper around asyncio.wait_for that provides:
    - Descriptive error messages
    - Configurable default timeout
    - Optional operation naming for debugging

    Args:
        coro: The coroutine to run
        timeout: Timeout in seconds (default: 30.0)
        operation_name: Optional name for the operation (used in error messages)

    Returns:
        The result of the coroutine

    Raises:
        TimeoutError: If the operation times out, with a descriptive message

    Usage:
        async def test_slow_operation():
            result = await run_with_timeout(
                slow_function(),
                timeout=10.0,
                operation_name="database query"
            )
            assert result is not None
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        op_desc = f" ({operation_name})" if operation_name else ""
        raise TimeoutError(f"Async operation{op_desc} timed out after {timeout}s") from None


async def run_with_cancellation(
    coro: Coroutine[Any, Any, T],
    timeout: float = DEFAULT_TIMEOUT,
) -> T | None:
    """Run a coroutine, returning None on timeout instead of raising.

    Useful for operations that are expected to possibly timeout
    and where None is an acceptable result.

    Args:
        coro: The coroutine to run
        timeout: Timeout in seconds

    Returns:
        The result of the coroutine, or None if it timed out
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def gather_with_timeout(
    *coros: Coroutine[Any, Any, Any],
    timeout: float = DEFAULT_TIMEOUT,
    return_exceptions: bool = False,
) -> list[Any]:
    """Gather multiple coroutines with a shared timeout.

    Args:
        *coros: Coroutines to run concurrently
        timeout: Total timeout for all operations
        return_exceptions: If True, exceptions are returned as results

    Returns:
        List of results from all coroutines

    Raises:
        TimeoutError: If the total operation times out
    """
    try:
        return await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=return_exceptions),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(f"Gathered async operations timed out after {timeout}s") from None


class AsyncTestContext:
    """Context manager for async test setup/teardown with timeout.

    Provides a structured way to handle async resources in tests
    with guaranteed cleanup.

    Usage:
        async def test_with_context():
            async with AsyncTestContext(setup_resource, cleanup_resource) as resource:
                result = await resource.do_something()
                assert result is not None
    """

    def __init__(
        self,
        setup_coro: Coroutine[Any, Any, T],
        cleanup_fn: Any | None = None,
        setup_timeout: float = DEFAULT_TIMEOUT,
        cleanup_timeout: float = 5.0,
    ):
        self.setup_coro = setup_coro
        self.cleanup_fn = cleanup_fn
        self.setup_timeout = setup_timeout
        self.cleanup_timeout = cleanup_timeout
        self._resource: T | None = None

    async def __aenter__(self) -> T:
        self._resource = await run_with_timeout(
            self.setup_coro,
            timeout=self.setup_timeout,
            operation_name="test setup",
        )
        return self._resource

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.cleanup_fn is not None and self._resource is not None:
            try:
                cleanup_result = self.cleanup_fn(self._resource)
                if hasattr(cleanup_result, "__await__"):
                    await asyncio.wait_for(
                        cleanup_result,
                        timeout=self.cleanup_timeout,
                    )
            except asyncio.TimeoutError:
                pass  # Cleanup timeout is not fatal
            except Exception:
                pass  # Cleanup errors are not fatal


def close_coroutine_then(
    result: Any = None,
    *,
    raise_: BaseException | None = None,
) -> Callable[..., Any]:
    """Build a ``side_effect`` for mocks that stand in for a coroutine *runner*.

    ``asyncio.run``, ``asyncio.create_task`` and
    ``aragora.utils.async_utils.run_async`` all receive an already-created
    coroutine object.  Patching them with a plain ``return_value`` (or a bare
    ``side_effect`` exception) leaves that coroutine unconsumed, and Python then
    emits ``RuntimeWarning: coroutine '...' was never awaited`` at garbage
    collection, attributed to whichever test happens to be running.  This side
    effect closes the coroutine first, then returns ``result`` or raises
    ``raise_``.

    Usage::

        with patch("asyncio.run", side_effect=close_coroutine_then(raise_=RuntimeError("x"))):
            main()

        with patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock())):
            handler.enqueue(...)
    """

    def _side_effect(coro: Any, *args: Any, **kwargs: Any) -> Any:
        if inspect.iscoroutine(coro):
            coro.close()
        if raise_ is not None:
            raise raise_
        return result

    return _side_effect


__all__ = [
    "DEFAULT_TIMEOUT",
    "run_with_timeout",
    "run_with_cancellation",
    "gather_with_timeout",
    "AsyncTestContext",
    "close_coroutine_then",
]
