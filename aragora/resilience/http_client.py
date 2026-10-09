"""
Resilient HTTP Client Utilities.

Provides shared patterns for making HTTP requests with circuit breaker
protection and retry logic. This consolidates duplicated code found across:

- aragora/connectors/accounting/xero.py
- aragora/connectors/accounting/gusto.py
- aragora/connectors/accounting/qbo.py
- aragora/connectors/chat/*.py

Usage:
    from aragora.resilience.http_client import (
        CircuitBreakerMixin,
        make_resilient_request,
        classify_http_error,
    )

    # Using the mixin
    class MyConnector(CircuitBreakerMixin):
        def __init__(self):
            self.init_circuit_breaker(
                name="my-connector",
                failure_threshold=3,
                cooldown_seconds=60.0,
            )

        async def call_api(self):
            return await make_resilient_request(
                circuit_breaker=self._circuit_breaker,
                request_func=self._do_request,
                connector_name="my-connector",
            )

    # Using the helper directly
    result = await make_resilient_request(
        circuit_breaker=my_circuit_breaker,
        request_func=lambda: client.get(url),
        connector_name="api",
        transient_statuses={429, 500, 502, 503, 504},
    )
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TypeVar
from collections.abc import Awaitable, Callable

from aragora.resilience.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

T = TypeVar("T")


# Default HTTP status codes considered transient (eligible for retry)
TRANSIENT_HTTP_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


@dataclass
class HttpErrorInfo:
    """Classification of an HTTP error.

    Attributes:
        is_transient: Whether this is a transient error (retry-eligible)
        is_rate_limit: Whether this is a rate limit error
        is_auth_error: Whether this is an authentication error
        retry_after: Optional retry-after value in seconds
        status_code: HTTP status code
        message: Error message
    """

    is_transient: bool
    is_rate_limit: bool
    is_auth_error: bool
    retry_after: float | None
    status_code: int
    message: str


def classify_http_error(
    status_code: int,
    headers: dict[str, str] | None = None,
    body: str | dict | None = None,
    transient_statuses: frozenset[int] = TRANSIENT_HTTP_STATUSES,
) -> HttpErrorInfo:
    """Classify an HTTP error for proper handling.

    This function provides consistent error classification across all
    HTTP connectors, ensuring uniform circuit breaker behavior.

    Args:
        status_code: HTTP response status code
        headers: Response headers (optional, used for Retry-After)
        body: Response body (optional, used for error message)
        transient_statuses: Status codes considered transient

    Returns:
        HttpErrorInfo with classification details

    Example:
        error_info = classify_http_error(429, {"Retry-After": "60"})
        if error_info.is_rate_limit:
            await asyncio.sleep(error_info.retry_after or 60)
    """
    headers = headers or {}

    # Extract retry-after if present
    retry_after: float | None = None
    if "Retry-After" in headers or "retry-after" in headers:
        retry_header = headers.get("Retry-After") or headers.get("retry-after")
        if retry_header:
            try:
                retry_after = float(retry_header)
            except (ValueError, TypeError) as e:
                logger.debug("Failed to parse numeric value: %s", e)

    # Build error message
    if isinstance(body, dict):
        message = body.get("error") or body.get("message") or body.get("Message") or str(body)
    elif isinstance(body, str):
        message = body[:200] if body else f"HTTP {status_code}"
    else:
        message = f"HTTP {status_code}"

    return HttpErrorInfo(
        is_transient=status_code in transient_statuses,
        is_rate_limit=status_code == 429,
        is_auth_error=status_code in (401, 403),
        retry_after=retry_after,
        status_code=status_code,
        message=message,
    )


class CircuitBreakerMixin:
    """Mixin providing standardized circuit breaker setup for HTTP connectors.

    This mixin extracts the common circuit breaker initialization pattern
    used across accounting connectors (Xero, Gusto, QBO) and chat connectors.

    Usage:
        class MyConnector(CircuitBreakerMixin):
            def __init__(
                self,
                circuit_breaker: CircuitBreaker | None = None,
                enable_circuit_breaker: bool = True,
            ):
                self.init_circuit_breaker(
                    name="my-connector",
                    circuit_breaker=circuit_breaker,
                    enable=enable_circuit_breaker,
                    failure_threshold=3,
                    cooldown_seconds=60.0,
                )

            async def _request(self, method: str, url: str):
                # Use self._circuit_breaker directly or via helpers
                if not self.check_circuit_breaker():
                    raise ServiceUnavailableError("Circuit breaker open")
                try:
                    result = await self._do_request(method, url)
                    self.record_circuit_success()
                    return result
                except TransientError:
                    self.record_circuit_failure()
                    raise
    """

    _circuit_breaker: CircuitBreaker | None = None

    def init_circuit_breaker(
        self,
        name: str,
        circuit_breaker: CircuitBreaker | None = None,
        enable: bool = True,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        """Initialize circuit breaker for this connector.

        Args:
            name: Circuit breaker name for metrics/logging
            circuit_breaker: Pre-configured circuit breaker (takes precedence)
            enable: Whether to enable circuit breaker (ignored if circuit_breaker provided)
            failure_threshold: Failures before opening circuit
            cooldown_seconds: Seconds before attempting recovery
        """
        if circuit_breaker is not None:
            self._circuit_breaker = circuit_breaker
        elif enable:
            self._circuit_breaker = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
            )
        else:
            self._circuit_breaker = None

    def check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows proceeding.

        Returns:
            True if request can proceed, False if circuit is open
        """
        if self._circuit_breaker is None:
            return True
        return self._circuit_breaker.can_proceed()

    def get_circuit_cooldown(self) -> float:
        """Get remaining cooldown time if circuit is open.

        Returns:
            Remaining cooldown in seconds, or 0 if circuit is closed
        """
        if self._circuit_breaker is None:
            return 0.0
        return self._circuit_breaker.cooldown_remaining()

    def record_circuit_success(self) -> None:
        """Record a successful request for the circuit breaker."""
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()

    def record_circuit_failure(self) -> None:
        """Record a failed request for the circuit breaker."""
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_failure()


@dataclass
class ResilientRequestConfig:
    """Configuration for resilient HTTP requests.

    Attributes:
        max_retries: Maximum retry attempts
        base_delay: Base delay in seconds for exponential backoff
        transient_statuses: HTTP status codes to retry on
        record_client_errors: Whether to record 4xx errors as circuit failures
    """

    max_retries: int = 3
    base_delay: float = 0.5
    transient_statuses: frozenset[int] = TRANSIENT_HTTP_STATUSES
    record_client_errors: bool = False  # Usually 4xx are not transient


async def make_resilient_request(
    request_func: Callable[[], Awaitable[T]],
    circuit_breaker: CircuitBreaker | None = None,
    connector_name: str = "api",
    config: ResilientRequestConfig | None = None,
    on_transient_error: Callable[[int, float], Awaitable[None]] | None = None,
) -> T:
    """Make an HTTP request with circuit breaker and retry protection.

    This function consolidates the common pattern of:
    1. Checking circuit breaker before request
    2. Making the request
    3. Handling transient errors with retry
    4. Recording success/failure for circuit breaker

    Args:
        request_func: Async function that makes the HTTP request and returns result
        circuit_breaker: Optional circuit breaker for protection
        connector_name: Name for logging
        config: Configuration for retry behavior
        on_transient_error: Optional callback for transient errors (status_code, delay)

    Returns:
        Result from request_func

    Raises:
        CircuitBreakerOpenError: If circuit breaker is open
        Exception: Any exception from request_func after retries exhausted

    Example:
        async def do_request():
            async with client.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()

        result = await make_resilient_request(
            request_func=do_request,
            circuit_breaker=my_breaker,
            connector_name="my-api",
        )
    """
    config = config or ResilientRequestConfig()

    # Check circuit breaker before attempting request
    if circuit_breaker is not None and not circuit_breaker.can_proceed():
        cooldown = circuit_breaker.cooldown_remaining()
        from aragora.resilience.circuit_breaker import CircuitOpenError

        raise CircuitOpenError(connector_name, cooldown)

    last_exception: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            result = await request_func()

            # Success - record it
            if circuit_breaker is not None:
                circuit_breaker.record_success()

            return result

        except Exception as e:  # noqa: BLE001 - HTTP retry must catch all to classify errors
            last_exception = e

            # Determine if this is a retryable error
            is_transient = _is_transient_exception(e, config.transient_statuses)

            if is_transient:
                # Record failure for transient errors
                if circuit_breaker is not None:
                    circuit_breaker.record_failure()

                if attempt < config.max_retries:
                    delay = config.base_delay * (2**attempt)

                    # Check for Retry-After in the exception
                    retry_after = _extract_retry_after(e)
                    if retry_after is not None:
                        delay = retry_after

                    logger.warning(
                        "[%s] Transient error (attempt %s/%s): %s. Retrying in %.1fs",
                        connector_name,
                        attempt + 1,
                        config.max_retries,
                        e,
                        delay,
                    )

                    if on_transient_error is not None:
                        status_code = _extract_status_code(e) or 0
                        await on_transient_error(status_code, delay)

                    await asyncio.sleep(delay)
                    continue
            else:
                # Non-transient error - record if configured
                if config.record_client_errors and circuit_breaker is not None:
                    circuit_breaker.record_failure()

            # Either non-transient or retries exhausted
            raise

    # Should not reach here, but handle edge case
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("Unexpected: no result after retries")


def _is_transient_exception(e: Exception, transient_statuses: frozenset[int]) -> bool:
    """Check if an exception represents a transient error."""
    # Check for timeout errors
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return True

    # Check for connection errors
    if isinstance(e, (ConnectionError, OSError)):
        return True

    # Try to extract HTTP status code
    status_code = _extract_status_code(e)
    if status_code is not None:
        return status_code in transient_statuses

    # Check exception attributes or message patterns
    err_str = str(e).lower()
    if any(term in err_str for term in ("timeout", "connection", "rate limit", "503", "502")):
        return True

    return False


def _extract_status_code(e: Exception) -> int | None:
    """Extract HTTP status code from exception if available."""
    # Check common httpx/aiohttp patterns
    if hasattr(e, "status_code"):
        return getattr(e, "status_code")
    if hasattr(e, "status"):
        return getattr(e, "status")
    if hasattr(e, "response"):
        resp = getattr(e, "response")
        if hasattr(resp, "status_code"):
            return getattr(resp, "status_code")
        if hasattr(resp, "status"):
            return getattr(resp, "status")
    return None


def _extract_retry_after(e: Exception) -> float | None:
    """Extract Retry-After value from exception if available."""
    if hasattr(e, "retry_after"):
        retry_after = getattr(e, "retry_after")
        if retry_after is not None:
            try:
                return float(retry_after)
            except (ValueError, TypeError) as parse_err:
                logger.debug("Failed to parse numeric value: %s", parse_err)

    if hasattr(e, "response"):
        resp = getattr(e, "response")
        if hasattr(resp, "headers"):
            headers = getattr(resp, "headers")
            if isinstance(headers, dict):
                retry_header = headers.get("Retry-After") or headers.get("retry-after")
                if retry_header:
                    try:
                        return float(retry_header)
                    except (ValueError, TypeError) as parse_err:
                        logger.debug("Failed to parse numeric value: %s", parse_err)

    return None


__all__ = [
    "TRANSIENT_HTTP_STATUSES",
    "HttpErrorInfo",
    "classify_http_error",
    "CircuitBreakerMixin",
    "ResilientRequestConfig",
    "make_resilient_request",
]
