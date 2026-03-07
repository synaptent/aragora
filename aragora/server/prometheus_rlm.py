"""
RLM (Recursive Language Models) metrics for Aragora server.

Extracted from prometheus.py for maintainability.
Provides metrics for RLM compression, queries, caching, and refinement.
"""

import logging
import time
from functools import wraps
from typing import ParamSpec, TypeVar
from collections.abc import Callable
from collections.abc import Awaitable

logger = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")

from aragora.server.prometheus import (
    PROMETHEUS_AVAILABLE,
    _simple_metrics,
)

# Import metric definitions when prometheus is available
if PROMETHEUS_AVAILABLE:
    from aragora.server.prometheus import (
        RLM_CACHE_HITS,
        RLM_CACHE_MISSES,
        RLM_COMPRESSION_DURATION,
        RLM_COMPRESSION_RATIO,
        RLM_COMPRESSIONS,
        RLM_CONTEXT_LEVELS,
        RLM_MEMORY_USAGE,
        RLM_QUERIES,
        RLM_QUERY_DURATION,
        RLM_READY_FALSE_RATE,
        RLM_REFINEMENT_DURATION,
        RLM_REFINEMENT_ITERATIONS,
        RLM_REFINEMENT_SUCCESS,
        RLM_TOKENS_SAVED,
    )


def record_rlm_compression(
    source_type: str,
    original_tokens: int,
    compressed_tokens: int,
    levels: int = 1,
    duration_seconds: float = 0.0,
    success: bool = True,
) -> None:
    """Record an RLM compression operation.

    Args:
        source_type: Type of content compressed (debate, document, knowledge)
        original_tokens: Token count before compression
        compressed_tokens: Token count after compression
        levels: Number of abstraction levels created
        duration_seconds: Time taken for compression
        success: Whether compression succeeded
    """
    status = "success" if success else "failure"

    if PROMETHEUS_AVAILABLE:
        RLM_COMPRESSIONS.labels(source_type=source_type, status=status).inc()

        if success and original_tokens > 0:
            ratio = compressed_tokens / original_tokens
            RLM_COMPRESSION_RATIO.labels(source_type=source_type).observe(ratio)

            tokens_saved = original_tokens - compressed_tokens
            if tokens_saved > 0:
                RLM_TOKENS_SAVED.labels(source_type=source_type).inc(tokens_saved)

            RLM_CONTEXT_LEVELS.labels(source_type=source_type).observe(levels)

        if duration_seconds > 0:
            RLM_COMPRESSION_DURATION.labels(
                source_type=source_type,
                levels=str(levels),
            ).observe(duration_seconds)
    else:
        _simple_metrics.inc_counter(
            "aragora_rlm_compressions_total",
            {"source_type": source_type, "status": status},
        )
        if success and original_tokens > 0:
            ratio = compressed_tokens / original_tokens
            _simple_metrics.observe_histogram(
                "aragora_rlm_compression_ratio",
                ratio,
                {"source_type": source_type},
            )
            tokens_saved = original_tokens - compressed_tokens
            if tokens_saved > 0:
                _simple_metrics.inc_counter(
                    "aragora_rlm_tokens_saved_total",
                    {"source_type": source_type},
                    tokens_saved,
                )
        if duration_seconds > 0:
            _simple_metrics.observe_histogram(
                "aragora_rlm_compression_duration_seconds",
                duration_seconds,
                {"source_type": source_type, "levels": str(levels)},
            )


def record_rlm_query(
    query_type: str,
    level: str = "SUMMARY",
    duration_seconds: float = 0.0,
) -> None:
    """Record an RLM context query.

    Args:
        query_type: Type of query (drill_down, roll_up, search, etc.)
        level: Abstraction level queried (ABSTRACT, SUMMARY, DETAILED, FULL)
        duration_seconds: Time taken for query
    """
    if PROMETHEUS_AVAILABLE:
        RLM_QUERIES.labels(query_type=query_type, level=level).inc()
        if duration_seconds > 0:
            RLM_QUERY_DURATION.labels(query_type=query_type).observe(duration_seconds)
    else:
        _simple_metrics.inc_counter(
            "aragora_rlm_queries_total",
            {"query_type": query_type, "level": level},
        )
        if duration_seconds > 0:
            _simple_metrics.observe_histogram(
                "aragora_rlm_query_duration_seconds",
                duration_seconds,
                {"query_type": query_type},
            )


def record_rlm_cache_hit() -> None:
    """Record an RLM compression cache hit."""
    if PROMETHEUS_AVAILABLE:
        RLM_CACHE_HITS.inc()
    else:
        _simple_metrics.inc_counter("aragora_rlm_cache_hits_total")


def record_rlm_cache_miss() -> None:
    """Record an RLM compression cache miss."""
    if PROMETHEUS_AVAILABLE:
        RLM_CACHE_MISSES.inc()
    else:
        _simple_metrics.inc_counter("aragora_rlm_cache_misses_total")


def set_rlm_memory_usage(bytes_used: int) -> None:
    """Set current memory usage for RLM context cache.

    Args:
        bytes_used: Memory usage in bytes
    """
    if PROMETHEUS_AVAILABLE:
        RLM_MEMORY_USAGE.set(bytes_used)
    else:
        _simple_metrics.set_gauge("aragora_rlm_memory_bytes", bytes_used)


def record_rlm_refinement(
    strategy: str,
    iterations: int,
    success: bool,
    duration_seconds: float = 0.0,
) -> None:
    """Record an RLM iterative refinement operation.

    Args:
        strategy: Decomposition strategy used (auto, grep, partition_map, etc.)
        iterations: Number of iterations until ready=True (or max iterations)
        success: Whether ready=True was achieved before max iterations
        duration_seconds: Total time for refinement loop
    """
    if PROMETHEUS_AVAILABLE:
        RLM_REFINEMENT_ITERATIONS.labels(strategy=strategy).observe(iterations)
        if success:
            RLM_REFINEMENT_SUCCESS.labels(strategy=strategy).inc()
        if duration_seconds > 0:
            RLM_REFINEMENT_DURATION.labels(strategy=strategy).observe(duration_seconds)
    else:
        _simple_metrics.observe_histogram(
            "aragora_rlm_refinement_iterations",
            iterations,
            {"strategy": strategy},
        )
        if success:
            _simple_metrics.inc_counter(
                "aragora_rlm_refinement_success_total",
                {"strategy": strategy},
            )
        if duration_seconds > 0:
            _simple_metrics.observe_histogram(
                "aragora_rlm_refinement_duration_seconds",
                duration_seconds,
                {"strategy": strategy},
            )


def record_rlm_ready_false(iteration: int) -> None:
    """Record when LLM signals ready=False (needs refinement).

    Args:
        iteration: Current iteration number (0-indexed)
    """
    if PROMETHEUS_AVAILABLE:
        RLM_READY_FALSE_RATE.labels(iteration=str(iteration)).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_rlm_ready_false_total",
            {"iteration": str(iteration)},
        )


def timed_rlm_compression(
    source_type: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Async decorator to time RLM compression operations.

    Args:
        source_type: Type of content being compressed (debate, document, knowledge)

    Returns:
        Async decorator that wraps compression with timing.

    Usage:
        @timed_rlm_compression("debate")
        async def compress_debate(self, debate: DebateResult) -> RLMContext:
            ...
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            success = True
            original_tokens = 0
            compressed_tokens = 0
            levels = 1
            try:
                result = await func(*args, **kwargs)
                # Try to extract metrics from result
                if hasattr(result, "original_tokens"):
                    original_tokens = result.original_tokens
                if hasattr(result, "compressed_tokens"):
                    compressed_tokens = result.compressed_tokens
                if hasattr(result, "levels"):
                    levels = (
                        len(result.levels) if hasattr(result.levels, "__len__") else result.levels
                    )
                return result
            except (ValueError, TypeError, KeyError, RuntimeError, MemoryError) as e:
                logger.warning("RLM compression for %s failed: %s", source_type, e)
                success = False
                raise
            finally:
                duration = time.perf_counter() - start
                record_rlm_compression(
                    source_type=source_type,
                    original_tokens=original_tokens,
                    compressed_tokens=compressed_tokens,
                    levels=levels,
                    duration_seconds=duration,
                    success=success,
                )

        return wrapper

    return decorator


def timed_rlm_refinement(
    strategy: str = "auto",
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Async decorator to time RLM refinement operations.

    Args:
        strategy: Decomposition strategy being used

    Returns:
        Async decorator that wraps refinement with timing.

    Usage:
        @timed_rlm_refinement("grep")
        async def query_with_refinement(self, query: str) -> RLMResult:
            ...
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            iterations = 1
            success = False
            try:
                result = await func(*args, **kwargs)
                # Try to extract metrics from result
                if hasattr(result, "iteration"):
                    iterations = result.iteration + 1
                if hasattr(result, "ready"):
                    success = result.ready
                return result
            finally:
                duration = time.perf_counter() - start
                record_rlm_refinement(
                    strategy=strategy,
                    iterations=iterations,
                    success=success,
                    duration_seconds=duration,
                )

        return wrapper

    return decorator


__all__ = [
    "record_rlm_compression",
    "record_rlm_query",
    "record_rlm_cache_hit",
    "record_rlm_cache_miss",
    "set_rlm_memory_usage",
    "record_rlm_refinement",
    "record_rlm_ready_false",
    "timed_rlm_compression",
    "timed_rlm_refinement",
]
