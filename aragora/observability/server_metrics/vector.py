"""
Vector Store Metrics for Aragora.

Tracks vector store operations, latency, and search results.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from collections.abc import Generator

from .types import Counter, Histogram
from aragora.exceptions import REDIS_CONNECTION_ERRORS

logger = logging.getLogger(__name__)

# =============================================================================
# Vector Store Metrics
# =============================================================================

VECTOR_OPERATIONS = Counter(
    name="aragora_vector_operations_total",
    help="Total vector store operations",
    label_names=["operation", "store", "status"],  # operation: search/index/delete
)

VECTOR_LATENCY = Histogram(
    name="aragora_vector_latency_seconds",
    help="Vector operation latency",
    label_names=["operation", "store"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

VECTOR_RESULTS = Histogram(
    name="aragora_vector_results_count",
    help="Number of results returned by vector search",
    label_names=["store", "search_type"],  # search_type: semantic/keyword/relationship
    buckets=[0, 1, 5, 10, 25, 50, 100, 250, 500],
)

VECTOR_INDEX_BATCH_SIZE = Histogram(
    name="aragora_vector_index_batch_size",
    help="Batch size for vector indexing operations",
    label_names=["store"],
    buckets=[1, 10, 25, 50, 100, 250, 500, 1000],
)


# =============================================================================
# Helpers
# =============================================================================


@contextmanager
def track_vector_operation(operation: str, store: str = "weaviate") -> Generator[None, None, None]:
    """Context manager to track vector store operation latency.

    Args:
        operation: Operation type (search_semantic, search_keyword, index, delete)
        store: Store name (weaviate, qdrant, chroma)

    Usage:
        with track_vector_operation("search_semantic", "weaviate"):
            results = await store.search_semantic(embedding, limit=10)
    """
    start = time.perf_counter()
    status = "success"
    try:
        yield
    except (ValueError, TypeError, KeyError) as e:
        # Data validation and lookup errors
        status = "error"
        logger.warning("Vector %s error on %s: %s", operation, store, e)
        raise
    except REDIS_CONNECTION_ERRORS as e:
        # I/O and network-related errors (common with vector stores)
        status = "error"
        logger.warning("Vector %s I/O error on %s: %s", operation, store, e)
        raise
    except RuntimeError as e:
        # Runtime errors (async issues, store state errors)
        status = "error"
        logger.warning("Vector %s runtime error on %s: %s", operation, store, e)
        raise
    finally:
        duration = time.perf_counter() - start
        VECTOR_OPERATIONS.inc(operation=operation, store=store, status=status)
        VECTOR_LATENCY.observe(duration, operation=operation, store=store)
        # Log slow queries (>500ms)
        if duration > 0.5:
            logger.warning("Slow vector operation: %s on %s took %.3fs", operation, store, duration)


def track_vector_search_results(
    result_count: int, store: str = "weaviate", search_type: str = "semantic"
) -> None:
    """Track number of results returned by vector search.

    Args:
        result_count: Number of results returned
        store: Store name
        search_type: Type of search (semantic, keyword, relationship)
    """
    VECTOR_RESULTS.observe(result_count, store=store, search_type=search_type)


def track_vector_index_batch(batch_size: int, store: str = "weaviate") -> None:
    """Track batch size for vector indexing.

    Args:
        batch_size: Number of items indexed
        store: Store name
    """
    VECTOR_INDEX_BATCH_SIZE.observe(batch_size, store=store)


__all__ = [
    "VECTOR_OPERATIONS",
    "VECTOR_LATENCY",
    "VECTOR_RESULTS",
    "VECTOR_INDEX_BATCH_SIZE",
    "track_vector_operation",
    "track_vector_search_results",
    "track_vector_index_batch",
]
