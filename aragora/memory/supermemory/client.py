"""
Supermemory client for Aragora integration.

Wraps the Supermemory SDK with:
- Privacy filtering
- Circuit breaker pattern
- Retry logic
- Async operation support
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Any, TypeVar
from collections.abc import Callable

from .config import SupermemoryConfig
from .privacy_filter import PrivacyFilter

logger = logging.getLogger(__name__)

# Global client instance for singleton pattern
_client: SupermemoryClient | None = None

T = TypeVar("T")


@dataclass
class MemoryAddResult:
    """Result from adding a memory."""

    memory_id: str
    container_tag: str
    success: bool = True
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SearchResult:
    """A single search result from Supermemory."""

    content: str
    similarity: float
    memory_id: str | None = None
    container_tag: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass
class SearchResponse:
    """Response from a search query."""

    results: list[SearchResult]
    query: str
    total_found: int = 0
    search_time_ms: int = 0


class SupermemoryError(Exception):
    """Base exception for Supermemory errors."""

    def __init__(self, message: str, recoverable: bool = True):
        super().__init__(message)
        self.recoverable = recoverable


class SupermemoryConnectionError(SupermemoryError):
    """Connection to Supermemory failed."""

    pass


class SupermemoryRateLimitError(SupermemoryError):
    """Rate limit exceeded."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message, recoverable=True)
        self.retry_after = retry_after


def with_retry(
    max_retries: int = 3, delay: float = 1.0
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for retry logic with exponential backoff."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: SupermemoryError | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except SupermemoryRateLimitError as e:
                    wait_time = e.retry_after or (delay * (2**attempt))
                    logger.warning(
                        "Rate limited, waiting %ss (attempt %s/%s)",
                        wait_time,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(wait_time)
                    last_error = e
                except SupermemoryConnectionError as e:
                    wait_time = delay * (2**attempt)
                    logger.warning(
                        "Connection error, retrying in %ss (attempt %s/%s): %s",
                        wait_time,
                        attempt + 1,
                        max_retries,
                        e,
                    )
                    await asyncio.sleep(wait_time)
                    last_error = e
                except (SupermemoryRateLimitError, SupermemoryConnectionError):
                    raise
                except SupermemoryError:
                    # Non-recoverable Supermemory errors don't retry
                    raise
            raise last_error or SupermemoryError("Max retries exceeded")

        return wrapper

    return decorator


class SupermemoryClient:
    """Client for interacting with Supermemory API.

    Provides async wrappers around the Supermemory SDK with:
    - Automatic privacy filtering
    - Retry logic with exponential backoff
    - Error handling and recovery

    Usage:
        config = SupermemoryConfig.from_env()
        client = SupermemoryClient(config)

        # Add a memory
        result = await client.add_memory(
            content="Debate concluded...",
            container_tag="debates",
            metadata={"debate_id": "123"}
        )

        # Search memories
        response = await client.search("rate limiting")
        for result in response.results:
            print(result.content)
    """

    def __init__(self, config: SupermemoryConfig):
        """Initialize the client.

        Args:
            config: Supermemory configuration
        """
        self.config = config
        self._privacy_filter = PrivacyFilter() if config.privacy_filter_enabled else None
        self._sdk_client: Any = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazily initialize the SDK client."""
        if self._initialized:
            return

        try:
            from supermemory import Supermemory

            self._sdk_client = Supermemory(api_key=self.config.api_key)
            self._initialized = True
            logger.info("Supermemory client initialized")
        except ImportError:
            raise SupermemoryError(
                "supermemory package not installed. Run: pip install supermemory",
                recoverable=False,
            )
        except (OSError, ConnectionError, TimeoutError, ValueError) as e:
            logger.warning("Failed to initialize Supermemory: %s", e)
            raise SupermemoryConnectionError("Failed to initialize Supermemory") from e

    def _filter_content(self, content: str) -> str:
        """Apply privacy filter to content if enabled."""
        if self._privacy_filter:
            return self._privacy_filter.filter(content)
        return content

    def _filter_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        """Apply privacy filter to metadata if enabled."""
        if not metadata:
            return {}
        if self._privacy_filter:
            return self._privacy_filter.filter_metadata(metadata)
        return metadata

    @with_retry(max_retries=3, delay=1.0)
    async def add_memory(
        self,
        content: str,
        container_tag: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryAddResult:
        """Add a memory to Supermemory.

        Args:
            content: The memory content to store
            container_tag: Optional container tag (uses config default if not provided)
            metadata: Optional metadata dictionary

        Returns:
            MemoryAddResult with memory_id and status
        """
        self._ensure_initialized()

        # Apply privacy filtering
        filtered_content = self._filter_content(content)
        filtered_metadata = self._filter_metadata(metadata)

        tag = container_tag or self.config.container_tag

        try:
            # Run SDK call in executor to avoid blocking
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._sdk_client.memories.add(
                    content=filtered_content,
                    container_tag=tag,
                    metadata=filtered_metadata,
                ),
            )

            # Extract memory ID from response
            memory_id = getattr(response, "id", None) or str(response)

            logger.debug("Added memory to Supermemory: %s...", memory_id[:20])
            return MemoryAddResult(
                memory_id=memory_id,
                container_tag=tag,
                success=True,
            )
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Supermemory connection error: %s", e)
            raise SupermemoryConnectionError("Connection failed") from e
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "429" in error_msg:
                raise SupermemoryRateLimitError("Rate limit exceeded") from e
            elif "unauthorized" in error_msg or "401" in error_msg:
                raise SupermemoryError("Invalid API key", recoverable=False)
            else:
                logger.error("Failed to add memory: %s", e)
                return MemoryAddResult(
                    memory_id="",
                    container_tag=tag,
                    success=False,
                    error="Memory add failed",
                )

    @with_retry(max_retries=3, delay=1.0)
    async def search(
        self,
        query: str,
        limit: int = 10,
        container_tag: str | None = None,
    ) -> SearchResponse:
        """Search for memories.

        Args:
            query: The search query
            limit: Maximum number of results
            container_tag: Optional container tag to filter by

        Returns:
            SearchResponse with results
        """
        self._ensure_initialized()

        start_time = time.time()

        try:
            loop = asyncio.get_running_loop()

            # Build search kwargs
            search_kwargs: dict[str, Any] = {"q": query}
            if limit:
                search_kwargs["limit"] = limit
            if container_tag:
                search_kwargs["container_tag"] = container_tag

            response = await loop.run_in_executor(
                None,
                lambda: self._sdk_client.search.execute(**search_kwargs),
            )

            # Parse results
            results: list[SearchResult] = []
            raw_results = getattr(response, "results", []) or []

            for item in raw_results[:limit]:
                results.append(
                    SearchResult(
                        content=getattr(item, "content", str(item)),
                        similarity=getattr(item, "similarity", 1.0),
                        memory_id=getattr(item, "id", None),
                        container_tag=getattr(item, "container_tag", None),
                        metadata=getattr(item, "metadata", {}),
                    )
                )

            search_time_ms = int((time.time() - start_time) * 1000)

            logger.debug("Search returned %s results in %sms", len(results), search_time_ms)
            return SearchResponse(
                results=results,
                query=query,
                total_found=len(results),
                search_time_ms=search_time_ms,
            )
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Supermemory search connection error: %s", e)
            raise SupermemoryConnectionError("Connection failed") from e
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "429" in error_msg:
                raise SupermemoryRateLimitError("Rate limit exceeded") from e
            else:
                logger.error("Search failed: %s", e)
                return SearchResponse(
                    results=[],
                    query=query,
                    total_found=0,
                    search_time_ms=int((time.time() - start_time) * 1000),
                )

    async def get_context(
        self,
        container_tag: str | None = None,
        limit: int = 50,
    ) -> list[SearchResult]:
        """Get recent context memories.

        Args:
            container_tag: Optional container to filter by
            limit: Maximum memories to retrieve

        Returns:
            List of recent memories
        """
        # Use a generic query to get recent memories
        response = await self.search(
            query="*",  # Wildcard to get recent
            limit=limit,
            container_tag=container_tag,
        )
        return response.results

    async def health_check(self) -> dict[str, Any]:
        """Check connection health.

        Returns:
            Health status dictionary
        """
        start_time = time.time()

        try:
            self._ensure_initialized()

            # Simple search to test connection
            await self.search("health_check_ping", limit=1)

            latency_ms = int((time.time() - start_time) * 1000)
            return {
                "healthy": True,
                "latency_ms": latency_ms,
                "service": "supermemory",
            }
        except SupermemoryError as e:
            logger.warning("Supermemory health check failed: %s", e)
            return {
                "healthy": False,
                "error": "Health check failed",
                "recoverable": e.recoverable,
                "service": "supermemory",
            }
        except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
            logger.warning("Supermemory health check error: %s", e)
            return {
                "healthy": False,
                "error": "Health check failed",
                "service": "supermemory",
            }

    async def close(self) -> None:
        """Close the client and release resources."""
        self._sdk_client = None
        self._initialized = False


def get_client(config: SupermemoryConfig | None = None) -> SupermemoryClient | None:
    """Get or create the global Supermemory client.

    Args:
        config: Optional config. Uses env vars if not provided.

    Returns:
        SupermemoryClient if configured, None otherwise.
    """
    global _client

    if _client is not None:
        return _client

    # Try to get config from env if not provided
    if config is None:
        config = SupermemoryConfig.from_env()

    if config is None:
        logger.debug("Supermemory not configured (no API key)")
        return None

    _client = SupermemoryClient(config)
    return _client


def clear_client() -> None:
    """Clear the global client instance."""
    global _client
    _client = None
