"""Dependency-free async resilience for provider calls.

Use ``await with_timeout(1)(coroutine_or_callable)``, ``@retry(3, backoff=0.1)``,
and ``await breaker.call(callable)``. Sync callables run in a worker thread.
A timeout stops waiting, not the underlying thread: configure SDK transport
timeouts too when a call must stop consuming resources.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial, wraps
import inspect
import math
import os
import time
from typing import ParamSpec, Protocol, TypeVar, cast, overload

_P = ParamSpec("_P")
_T = TypeVar("_T")


def _positive_float(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Expected a finite positive number")
    return value


def _env_float(name: str, fallback: float) -> float:
    try:
        return _positive_float(float(os.environ.get(name, str(fallback))))
    except ValueError:
        return fallback


def _env_int(name: str, fallback: int) -> int:
    try:
        value = int(os.environ.get(name, str(fallback)))
        return value if value > 0 else fallback
    except ValueError:
        return fallback


async def _invoke(operation: Awaitable[_T] | Callable[[], _T | Awaitable[_T]]) -> _T:
    if not callable(operation):
        return await operation
    result = (
        operation()
        if inspect.iscoroutinefunction(operation)
        else await asyncio.to_thread(operation)
    )
    if inspect.isawaitable(result):
        return cast(_T, await result)
    return result


def with_timeout(
    seconds: float | None = None,
) -> Callable[[Awaitable[_T] | Callable[[], _T | Awaitable[_T]]], Awaitable[_T]]:
    """Bound one attempt, defaulting to ARAGORA_DEBATE_TIMEOUT_S or 30 seconds."""
    limit = (
        _env_float("ARAGORA_DEBATE_TIMEOUT_S", 30.0)
        if seconds is None
        else _positive_float(seconds)
    )

    async def run(operation: Awaitable[_T] | Callable[[], _T | Awaitable[_T]]) -> _T:
        try:
            return await asyncio.wait_for(_invoke(operation), timeout=limit)
        except asyncio.TimeoutError as exc:
            # Python 3.10's asyncio.TimeoutError is not the built-in TimeoutError.
            raise TimeoutError(f"Call exceeded {limit:g} seconds") from exc

    return run


class CircuitOpenError(RuntimeError):
    """The provider circuit is open; no SDK call was made."""


class _RetryDecorator(Protocol):
    @overload
    def __call__(self, operation: Callable[_P, Awaitable[_T]]) -> Callable[_P, Awaitable[_T]]: ...

    @overload
    def __call__(self, operation: Callable[_P, _T]) -> Callable[_P, Awaitable[_T]]: ...


def retry(
    max_attempts: int | None = None,
    backoff: float = 0.1,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> _RetryDecorator:
    """Retry matching failures with backoff * 2**attempt; never retry open circuits.

    Attempts include the initial call (default ARAGORA_DEBATE_RETRY_ATTEMPTS or 3).
    Cancellation and other BaseExceptions propagate immediately.
    """
    attempts = (
        _env_int("ARAGORA_DEBATE_RETRY_ATTEMPTS", 3) if max_attempts is None else max_attempts
    )
    if attempts < 1 or not math.isfinite(backoff) or backoff < 0:
        raise ValueError("Expected positive attempts and finite non-negative backoff")

    def decorate(
        operation: Callable[_P, _T | Awaitable[_T]],
    ) -> Callable[_P, Awaitable[_T]]:
        @wraps(operation)
        async def run(*args: _P.args, **kwargs: _P.kwargs) -> _T:
            for attempt in range(attempts):
                try:
                    return await _invoke(partial(operation, *args, **kwargs))
                except CircuitOpenError:
                    raise
                except exceptions:
                    if attempt == attempts - 1:
                        raise
                    await asyncio.sleep(backoff * 2**attempt)
            raise AssertionError("Unreachable: attempts is positive")

        return run

    return cast(_RetryDecorator, decorate)


class CircuitBreaker:
    """Consecutive-failure breaker, shared by an agent's operations.

    Confined to one event loop at a time. Half-open allows one probe; success
    closes, failure reopens, cancellation releases the probe without counting
    a provider failure. The injectable monotonic clock makes resets testable.
    """

    def __init__(
        self,
        fail_max: int | None = None,
        reset_timeout: float = 30.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.fail_max = (
            _env_int("ARAGORA_DEBATE_BREAKER_FAIL_MAX", 5) if fail_max is None else fail_max
        )
        if self.fail_max < 1:
            raise ValueError("Expected positive fail_max")
        self.reset_timeout = _positive_float(reset_timeout)
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_active = False
        self._generation = 0

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.reset_timeout:
            return "half-open"
        return "open"

    async def call(self, operation: Callable[[], _T | Awaitable[_T]]) -> _T:
        """Run a lazy operation unless open, counting each failed SDK attempt."""
        state = self.state
        if state == "open" or self._probe_active:
            raise CircuitOpenError("Provider circuit is open")
        self._probe_active = state == "half-open"
        generation = self._generation
        try:
            result = await _invoke(operation)
        except Exception:
            if generation == self._generation:
                self._failures += 1
                if self._probe_active or self._failures >= self.fail_max:
                    self._opened_at = self._clock()
                    self._generation += 1
                    self._probe_active = False
            raise
        else:
            if generation == self._generation:
                self._failures = 0
                self._opened_at = None
                if self._probe_active:
                    self._generation += 1
                    self._probe_active = False
            return result
        finally:
            if generation == self._generation:
                self._probe_active = False
