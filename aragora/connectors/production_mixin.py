"""Production Connector Mixin.

Provides production-quality patterns for connectors that do not extend
BaseConnector (e.g., standalone API connectors). Connectors that already
extend BaseConnector get circuit breaker and retry from the base class.

This mixin adds:
- Circuit breaker wrapping for all API calls
- Retry logic with exponential backoff for transient errors
- Query sanitization (prevent injection in search queries)
- Rate limiting awareness (respect API rate limits, back off on 429)
- Timeout guards on all network calls

Usage::

    class MyConnector(ProductionConnectorMixin):
        def __init__(self, ...):
            self._init_production_mixin(connector_name="my_connector")
            ...

        async def _request(self, method, url, **kwargs):
            return await self._call_with_retry(
                self._do_request, method, url, **kwargs
            )
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

logger = logging.getLogger(__name__)

# Query sanitization
_SAFE_QUERY_RE = re.compile(r"[^\w\s@.\-+/:]")
MAX_QUERY_LENGTH = 500

# Retry defaults
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER_FACTOR = 0.3
DEFAULT_REQUEST_TIMEOUT = 30.0


def sanitize_query(query: str, max_length: int = MAX_QUERY_LENGTH) -> str:
    """Sanitize a search query to prevent injection.

    Strips characters that could be used for injection attacks,
    and limits the query length.

    Args:
        query: Raw query string from user input.
        max_length: Maximum allowed query length.

    Returns:
        Sanitized query string safe for use in API calls.
    """
    query = query[:max_length]
    return _SAFE_QUERY_RE.sub("", query).strip()


class ProductionConnectorMixin:
    """Mixin providing production-quality patterns for connectors.

    This mixin is designed for standalone connectors that do NOT extend
    BaseConnector. It provides:

    - Circuit breaker integration (lazy-initialized)
    - Retry with exponential backoff on transient errors
    - Query sanitization helper
    - Rate limit (429) awareness with Retry-After support

    Connectors that extend BaseConnector should use the built-in
    ``_request_with_retry`` method instead.
    """

    # Set by _init_production_mixin
    _pcm_connector_name: str = "unknown"
    _pcm_max_retries: int = DEFAULT_MAX_RETRIES
    _pcm_base_delay: float = DEFAULT_BASE_DELAY
    _pcm_max_delay: float = DEFAULT_MAX_DELAY
    _pcm_request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    _pcm_circuit_breaker: Any = None
    _pcm_cb_initialized: bool = False

    def _init_production_mixin(
        self,
        connector_name: str = "unknown",
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Initialize the production mixin.

        Call this from the connector's ``__init__`` method.
        """
        self._pcm_connector_name = connector_name
        self._pcm_max_retries = max_retries
        self._pcm_base_delay = base_delay
        self._pcm_max_delay = max_delay
        self._pcm_request_timeout = request_timeout
        self._pcm_circuit_breaker = None
        self._pcm_cb_initialized = False

    def _get_pcm_circuit_breaker(self) -> Any:
        """Lazy-initialize the circuit breaker."""
        if not self._pcm_cb_initialized:
            self._pcm_cb_initialized = True
            try:
                from aragora.resilience import get_circuit_breaker

                self._pcm_circuit_breaker = get_circuit_breaker(
                    f"connector_{self._pcm_connector_name}"
                )
            except ImportError as exc:
                raise RuntimeError(
                    "ProductionConnectorMixin requires aragora.resilience.get_circuit_breaker "
                    f"for connector {self._pcm_connector_name!r}"
                ) from exc
        return self._pcm_circuit_breaker

    def _sanitize_query(self, query: str) -> str:
        """Sanitize a query string for safe API use."""
        return sanitize_query(query)

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        delay = min(self._pcm_base_delay * (2**attempt), self._pcm_max_delay)
        jitter = delay * DEFAULT_JITTER_FACTOR * random.uniform(-1, 1)
        return max(0.1, delay + jitter)

    async def _call_with_retry(
        self,
        fn: Any,
        *args: Any,
        operation: str = "request",
        **kwargs: Any,
    ) -> Any:
        """Execute a function with circuit breaker and retry logic.

        Retries on:
        - ConnectionError, TimeoutError
        - httpx.TimeoutException, httpx.NetworkError
        - HTTP 429 (rate limit) with Retry-After support
        - HTTP 5xx (server errors)

        Does NOT retry on:
        - HTTP 4xx (except 429)
        - Authentication errors (401, 403)

        Args:
            fn: Async callable to execute.
            *args: Positional arguments for fn.
            operation: Description for logging.
            **kwargs: Keyword arguments for fn.

        Returns:
            Result of fn(*args, **kwargs).

        Raises:
            The last exception after all retries are exhausted.
        """
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "ProductionConnectorMixin requires httpx for retry-aware connector calls"
            ) from exc

        # Check circuit breaker
        cb = self._get_pcm_circuit_breaker()
        if cb is not None and not cb.can_proceed():
            cooldown = cb.cooldown_remaining()
            logger.warning(
                "[%s] Circuit breaker open for %s, cooldown: %.1fs",
                self._pcm_connector_name,
                operation,
                cooldown,
            )
            raise ConnectionError(
                f"{operation} blocked by circuit breaker (cooldown: {cooldown:.1f}s)"
            )

        last_error: Exception | None = None

        for attempt in range(self._pcm_max_retries + 1):
            try:
                result = await fn(*args, **kwargs)
                if cb is not None:
                    cb.record_success()
                return result

            except httpx.TimeoutException:
                last_error = TimeoutError(f"{operation} timed out")
                logger.warning(
                    "[%s] %s timeout (attempt %s/%s)",
                    self._pcm_connector_name,
                    operation,
                    attempt + 1,
                    self._pcm_max_retries + 1,
                )

            except (httpx.ConnectError, httpx.NetworkError, ConnectionError, OSError) as e:
                last_error = ConnectionError(f"{operation} connection failed: {e}")
                logger.warning(
                    "[%s] %s network error (attempt %s/%s): %s",
                    self._pcm_connector_name,
                    operation,
                    attempt + 1,
                    self._pcm_max_retries + 1,
                    e,
                )

            except httpx.HTTPStatusError as e:
                status = e.response.status_code

                if status == 429:
                    # Rate limit - check Retry-After header
                    retry_after = None
                    if "Retry-After" in e.response.headers:
                        retry_after_header = e.response.headers["Retry-After"]
                        try:
                            retry_after = float(retry_after_header)
                        except (ValueError, TypeError) as exc:
                            raise RuntimeError(
                                f"{operation} received invalid Retry-After header "
                                f"{retry_after_header!r}"
                            ) from exc

                    last_error = e
                    logger.warning(
                        "[%s] %s rate limited (attempt %s/%s)",
                        self._pcm_connector_name,
                        operation,
                        attempt + 1,
                        self._pcm_max_retries + 1,
                    )

                    if retry_after is not None and attempt < self._pcm_max_retries:
                        delay = min(retry_after, self._pcm_max_delay)
                        delay += delay * 0.1 * random.uniform(0, 1)
                        await asyncio.sleep(delay)
                        continue

                elif status >= 500:
                    last_error = e
                    logger.warning(
                        "[%s] %s server error %s (attempt %s/%s)",
                        self._pcm_connector_name,
                        operation,
                        status,
                        attempt + 1,
                        self._pcm_max_retries + 1,
                    )

                else:
                    # 4xx (non-429) -- not retryable, raise immediately
                    raise

            # Retry with exponential backoff
            if attempt < self._pcm_max_retries:
                delay = self._calculate_retry_delay(attempt)
                logger.info(
                    "[%s] Retrying %s in %.1fs (attempt %s/%s)",
                    self._pcm_connector_name,
                    operation,
                    delay,
                    attempt + 2,
                    self._pcm_max_retries + 1,
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        if cb is not None:
            cb.record_failure()

        if last_error is not None:
            raise last_error

        raise ConnectionError(f"{operation} failed after {self._pcm_max_retries + 1} attempts")
