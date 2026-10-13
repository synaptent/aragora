"""
Supermemory client (compatibility path).

The client lives in :mod:`aragora.memory.supermemory.client`; this module
re-exports the same objects. The shared client returned by ``get_client`` lives
only in the new module; patch or reset it there.
"""

from __future__ import annotations

from aragora.memory.supermemory.client import (
    MemoryAddResult,
    PrivacyFilter,
    SearchResponse,
    SearchResult,
    SupermemoryClient,
    SupermemoryConfig,
    SupermemoryConnectionError,
    SupermemoryError,
    SupermemoryRateLimitError,
    clear_client,
    get_client,
    with_retry,
)

__all__ = [
    "MemoryAddResult",
    "PrivacyFilter",
    "SearchResponse",
    "SearchResult",
    "SupermemoryClient",
    "SupermemoryConfig",
    "SupermemoryConnectionError",
    "SupermemoryError",
    "SupermemoryRateLimitError",
    "clear_client",
    "get_client",
    "with_retry",
]
