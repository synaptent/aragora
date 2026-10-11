"""
HTTP Resilience Mixin for Chat Platform Connectors.

Provides circuit breaker, retry logic, and HTTP request handling
with exponential backoff for fault-tolerant chat connector operations.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, TypeVar
from collections.abc import Awaitable, Callable

T = TypeVar("T")

logger = logging.getLogger(__name__)


class HTTPResilienceMixin:
    """
    Mixin providing HTTP resilience patterns for chat connectors.

    Includes:
    - Circuit breaker support for fault isolation
    - Exponential backoff retry logic
    - HTTP request wrapper with consistent error handling

    Usage:
        class MyConnector(HTTPResilienceMixin, ChatPlatformConnector):
            ...
    """

    # These attributes are expected to be set by the base class __init__
    _enable_circuit_breaker: bool
    _circuit_breaker_threshold: int
    _circuit_breaker_cooldown: float
    _request_timeout: float
    _circuit_breaker: Any | None
    _circuit_breaker_initialized: bool

    @property
    def platform_name(self) -> str:
        """Platform identifier - must be implemented by subclass."""
        raise NotImplementedError

    # ==========================================================================
    # Circuit Breaker Support
    # ==========================================================================

    def _get_circuit_breaker(self) -> Any | None:
        """Get or create circuit breaker (lazy initialization)."""
        if not self._enable_circuit_breaker:
            return None

        if not self._circuit_breaker_initialized:
            try:
                from aragora.resilience import get_circuit_breaker

                self._circuit_breaker = get_circuit_breaker(
                    name=f"chat_connector_{self.platform_name}",
                    failure_threshold=self._circuit_breaker_threshold,
                    cooldown_seconds=self._circuit_breaker_cooldown,
                )
                logger.debug("Circuit breaker initialized for %s", self.platform_name)
            except ImportError:
                logger.warning("Circuit breaker module not available")
            self._circuit_breaker_initialized = True

        return self._circuit_breaker

    def _check_circuit_breaker(self) -> tuple[bool, str | None]:
        """
        Check if circuit breaker allows the request.

        Returns:
            Tuple of (can_proceed, error_message)
        """
        cb = self._get_circuit_breaker()
        if cb is None:
            return True, None

        if not cb.can_proceed():
            remaining = cb.cooldown_remaining()
            error = f"Circuit breaker open for {self.platform_name}. Retry in {remaining:.1f}s"
            logger.warning(error)
            return False, error

        return True, None

    def _record_success(self) -> None:
        """Record a successful operation with the circuit breaker."""
        cb = self._get_circuit_breaker()
        if cb:
            cb.record_success()

    def _record_failure(self, error: Exception | None = None) -> None:
        """Record a failed operation with the circuit breaker."""
        cb = self._get_circuit_breaker()
        if cb:
            cb.record_failure()
            status = cb.get_status()
            if status == "open":
                logger.warning(
                    "Circuit breaker OPENED for %s after repeated failures", self.platform_name
                )

    # ==========================================================================
    # Retry Logic
    # ==========================================================================

    async def _with_retry(
        self,
        operation: str,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        retryable_exceptions: tuple[type[Exception], ...] = (
            TimeoutError,
            ConnectionError,
            OSError,
        ),
        **kwargs: Any,
    ) -> T:
        """
        Execute an async function with exponential backoff retry and circuit breaker.

        This provides a standardized retry pattern for all connector operations.

        Args:
            operation: Name of the operation (for logging)
            func: Async function to execute
            *args: Arguments to pass to the function
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay between retries in seconds
            max_delay: Maximum delay between retries
            retryable_exceptions: Tuple of exception types to retry on
            **kwargs: Keyword arguments to pass to the function

        Returns:
            Result of the function call

        Raises:
            Last exception if all retries fail
        """
        # Check circuit breaker first
        can_proceed, error_msg = self._check_circuit_breaker()
        if not can_proceed:
            raise ConnectionError(error_msg)

        last_exception = None
        for attempt in range(max_retries):
            try:
                result = await func(*args, **kwargs)
                self._record_success()
                return result
            except retryable_exceptions as e:
                last_exception = e
                self._record_failure(e)

                if attempt < max_retries - 1:
                    # Calculate delay with exponential backoff and jitter
                    delay = min(base_delay * (2**attempt), max_delay)
                    jitter = random.uniform(0, delay * 0.1)  # noqa: S311 -- retry jitter
                    total_delay = delay + jitter

                    logger.warning(
                        "%s %s failed (attempt %s/%s): %s. Retrying in %.1fs",
                        self.platform_name,
                        operation,
                        attempt + 1,
                        max_retries,
                        e,
                        total_delay,
                    )
                    await asyncio.sleep(total_delay)
                else:
                    logger.error(
                        "%s %s failed after %s attempts: %s",
                        self.platform_name,
                        operation,
                        max_retries,
                        e,
                    )

        if last_exception:
            raise last_exception
        raise RuntimeError(f"{operation} failed with no exception captured")

    def _is_retryable_status_code(self, status_code: int) -> bool:
        """
        Check if an HTTP status code indicates a retryable error.

        Args:
            status_code: HTTP status code

        Returns:
            True if the error is transient and should be retried
        """
        # 429 Too Many Requests - rate limited
        # 500 Internal Server Error - server error
        # 502 Bad Gateway - upstream error
        # 503 Service Unavailable - server overloaded
        # 504 Gateway Timeout - upstream timeout
        return status_code in {429, 500, 502, 503, 504}

    # ==========================================================================
    # HTTP Request Wrapper
    # ==========================================================================

    async def _http_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: Any | None = None,
        content: bytes | None = None,
        files: dict[str, Any] | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: float | None = None,
        return_raw: bool = False,
        operation: str = "http_request",
    ) -> tuple[bool, dict[str, Any] | bytes | None, str | None]:
        """
        Make an HTTP request with retry, timeout, and circuit breaker support.

        This is the recommended method for all HTTP operations in chat connectors.
        Provides consistent error handling, logging, and resilience patterns.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            url: Request URL
            headers: Optional request headers
            json: Optional JSON body
            data: Optional form data (dict for form-encoded, or bytes)
            content: Optional raw bytes body (for file uploads)
            files: Optional file uploads
            max_retries: Maximum retry attempts (default 3)
            base_delay: Initial retry delay in seconds (default 1.0)
            timeout: Custom timeout in seconds (defaults to self._request_timeout)
            return_raw: If True, return raw bytes instead of JSON
            operation: Operation name for logging

        Returns:
            Tuple of (success: bool, response_data: dict|bytes | None, error: str | None)
        """
        # Check circuit breaker first
        can_proceed, error_msg = self._check_circuit_breaker()
        if not can_proceed:
            return False, None, error_msg

        # Try to import httpx
        try:
            import httpx
        except ImportError:
            return False, None, "httpx not available"

        last_error: str | None = None
        request_timeout = timeout or self._request_timeout

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=request_timeout) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        json=json,
                        data=data,
                        content=content,
                        files=files,
                    )

                    # Check for retryable status codes
                    if self._is_retryable_status_code(response.status_code):
                        last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                        self._record_failure()

                        if attempt < max_retries - 1:
                            # Calculate delay with exponential backoff and jitter
                            delay = min(base_delay * (2**attempt), 30.0)
                            jitter = random.uniform(0, delay * 0.1)  # noqa: S311 -- retry jitter
                            total_delay = delay + jitter

                            logger.warning(
                                "%s %s got %s (attempt %s/%s). Retrying in %.1fs",
                                self.platform_name,
                                operation,
                                response.status_code,
                                attempt + 1,
                                max_retries,
                                total_delay,
                            )
                            await asyncio.sleep(total_delay)
                            continue
                        else:
                            logger.error(
                                "%s %s failed after %s attempts with status %s",
                                self.platform_name,
                                operation,
                                max_retries,
                                response.status_code,
                            )
                            return False, None, last_error

                    # Non-retryable error
                    if response.status_code >= 400:
                        self._record_failure()
                        error = f"HTTP {response.status_code}: {response.text[:200]}"
                        logger.warning("%s %s failed: %s", self.platform_name, operation, error)
                        return False, None, error

                    # Success
                    self._record_success()
                    if return_raw:
                        return True, response.content, None
                    try:
                        return True, response.json(), None
                    except ValueError:
                        # Response may not be JSON
                        return True, {"status": "ok", "text": response.text}, None

            except httpx.TimeoutException as e:
                last_error = f"Timeout after {self._request_timeout}s: {e}"
                self._record_failure()

                if attempt < max_retries - 1:
                    delay = min(base_delay * (2**attempt), 30.0)
                    logger.warning(
                        "%s %s timed out (attempt %s/%s). Retrying in %.1fs",
                        self.platform_name,
                        operation,
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "%s %s timed out after %s attempts",
                        self.platform_name,
                        operation,
                        max_retries,
                    )

            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
                self._record_failure()

                if attempt < max_retries - 1:
                    delay = min(base_delay * (2**attempt), 30.0)
                    logger.warning(
                        "%s %s connection failed (attempt %s/%s). Retrying in %.1fs",
                        self.platform_name,
                        operation,
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "%s %s connection failed after %s attempts",
                        self.platform_name,
                        operation,
                        max_retries,
                    )

            except (ValueError, TypeError, RuntimeError, OSError) as e:
                last_error = f"Unexpected error: {e}"
                self._record_failure()
                logger.error("%s %s unexpected error: %s", self.platform_name, operation, e)
                # Don't retry on unexpected errors
                break
            except httpx.HTTPError as e:
                last_error = f"Unexpected error: {e}"
                self._record_failure()
                logger.error(
                    "%s %s unhandled %s: %s", self.platform_name, operation, type(e).__name__, e
                )
                # Don't retry on other HTTP client exceptions.
                break

        return False, None, last_error


__all__ = ["HTTPResilienceMixin"]
