"""
Configuration for Supermemory integration.

Environment variables:
    SUPERMEMORY_API_KEY: API key for authentication (required)
    SUPERMEMORY_BASE_URL: Base URL (default: SDK default)
    SUPERMEMORY_TIMEOUT: Request timeout in seconds (default: 30)
    SUPERMEMORY_SYNC_THRESHOLD: Min importance to sync externally (default: 0.7)
    SUPERMEMORY_PRIVACY_FILTER: Enable privacy filtering (default: true)
    SUPERMEMORY_CONTAINER_TAG: Default container tag (default: aragora)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class SupermemoryConfig:
    """Configuration for Supermemory client.

    Attributes:
        api_key: Supermemory API key (sm_... format)
        base_url: Optional base URL override
        timeout_seconds: Request timeout
        sync_threshold: Minimum importance score to sync externally (0.0-1.0)
        privacy_filter_enabled: Whether to filter sensitive data before sync
        container_tag: Default container tag for memories
        max_retries: Maximum retry attempts for failed requests
        retry_delay_seconds: Initial delay between retries
    """

    api_key: str
    base_url: str | None = None
    timeout_seconds: float = 30.0
    sync_threshold: float = 0.7
    privacy_filter_enabled: bool = True
    container_tag: str = "aragora"
    max_retries: int = 3
    retry_delay_seconds: float = 1.0

    # Per-feature container tags
    container_tags: dict[str, str] = field(
        default_factory=lambda: {
            "debate_outcomes": "aragora_debates",
            "consensus": "aragora_consensus",
            "agent_performance": "aragora_agents",
            "patterns": "aragora_patterns",
            "errors": "aragora_errors",
        }
    )

    @classmethod
    def from_env(cls) -> SupermemoryConfig | None:
        """Create config from environment variables.

        Returns:
            SupermemoryConfig if API key is set, None otherwise.
        """
        api_key = os.environ.get("SUPERMEMORY_API_KEY")
        if not api_key:
            return None

        return cls(
            api_key=api_key,
            base_url=os.environ.get("SUPERMEMORY_BASE_URL"),
            timeout_seconds=float(os.environ.get("SUPERMEMORY_TIMEOUT", "30")),
            sync_threshold=float(os.environ.get("SUPERMEMORY_SYNC_THRESHOLD", "0.7")),
            privacy_filter_enabled=os.environ.get("SUPERMEMORY_PRIVACY_FILTER", "true").lower()
            == "true",
            container_tag=os.environ.get("SUPERMEMORY_CONTAINER_TAG", "aragora"),
        )

    def get_container_tag(self, category: str) -> str:
        """Get container tag for a memory category.

        Args:
            category: Memory category (e.g., 'debate_outcomes', 'consensus')

        Returns:
            Container tag string
        """
        return self.container_tags.get(category, self.container_tag)

    def should_sync(self, importance: float) -> bool:
        """Check if a memory should be synced based on importance.

        Args:
            importance: Memory importance score (0.0-1.0)

        Returns:
            True if importance meets or exceeds sync threshold
        """
        return importance >= self.sync_threshold
