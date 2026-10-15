"""
Supermemory client - Cross-session memory persistence for Aragora.

Integrates with Supermemory (https://supermemory.ai) to provide:
- Persistent memory storage across sessions and projects
- Semantic search across historical debate outcomes
- Context injection for new debates
- Privacy-filtered external sync

Usage:
    from aragora.memory.supermemory import (
        SupermemoryClient,
        SupermemoryConfig,
        get_client,
    )

    # Initialize client
    client = get_client()  # Uses SUPERMEMORY_API_KEY env var

    # Store a memory
    result = await client.add_memory(
        content="Debate concluded with 85% confidence...",
        container_tag="debate_outcomes",
        metadata={"debate_id": "abc123"}
    )

    # Search memories
    results = await client.search("rate limiting strategies")
"""

from .config import SupermemoryConfig
from .client import SupermemoryClient, get_client, clear_client
from .privacy_filter import PrivacyFilter, PrivacyFilterConfig

__all__ = [
    # Config
    "SupermemoryConfig",
    # Client
    "SupermemoryClient",
    "get_client",
    "clear_client",
    # Privacy
    "PrivacyFilter",
    "PrivacyFilterConfig",
]
