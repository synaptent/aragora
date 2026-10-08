"""
Pulse Namespace API

Provides access to trending topics and real-time signals:
- Trending topics from HackerNews, Reddit, Twitter
- Debate topic suggestions based on signals
- Analytics on pulse data
- Scheduler management for automated pulse ingestion
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Literal


def _warn_deprecated(message: str) -> None:
    """Emit a runtime DeprecationWarning for a dead or drifted SDK method."""
    warnings.warn(message, DeprecationWarning, stacklevel=3)


if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class PulseAPI:
    """
    Synchronous Pulse API for trending topics and signals.

    Pulse monitors external sources (HackerNews, Reddit, Twitter) for
    trending topics and suggests debate topics based on real-time signals.

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> trending = client.pulse.get_trending(source="hackernews", limit=10)
        >>> topic = client.pulse.suggest_debate_topic()
        >>> scheduler = client.pulse.get_scheduler_status()
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    # =========================================================================
    # Trending & Suggestions
    # =========================================================================

    def get_trending(
        self,
        source: Literal["all", "hackernews", "reddit", "twitter"] | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Get trending topics from monitored sources.

        Args:
            source: Filter by source platform.
            category: Filter by category/domain.
            limit: Maximum number of topics to return.

        Returns:
            Dict with trending topics including scores, sources,
            and metadata.
        """
        params: dict[str, Any] = {"limit": limit}
        if source:
            params["source"] = source
        if category:
            params["category"] = category
        return self._client.request("GET", "/api/v1/pulse/trending", params=params)

    def suggest_debate_topic(
        self,
        source: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """
        Get a suggested debate topic from trending signals.

        Args:
            source: Prefer topics from this source.
            category: Prefer topics in this category.

        Returns:
            Dict with suggested topic, context, and reasoning.
        """
        params: dict[str, Any] = {}
        if source:
            params["source"] = source
        if category:
            params["category"] = category
        return self._client.request("GET", "/api/v1/pulse/suggest", params=params)

    def create_debate_topic(self, **kwargs: Any) -> dict[str, Any]:
        """
        Create a debate from a pulse topic.

        Args:
            **kwargs: Debate parameters including:
                - topic_id: Pulse topic to convert to debate
                - task: Override task description
                - agents: Specific agents to include

        Returns:
            Dict with created debate details.
        """
        return self._client.request("POST", "/api/v1/pulse/debate-topic", json=kwargs)

    # =========================================================================
    # Analytics
    # =========================================================================

    def get_analytics(self, **kwargs: Any) -> dict[str, Any]:
        """
        Get pulse analytics including topic distribution and trends.

        Returns:
            Dict with analytics data including topic counts by source,
            category distribution, and daily trends.
        """
        return self._client.request("GET", "/api/v1/pulse/analytics", params=kwargs)

    def get_scheduler_analytics(self) -> dict[str, Any]:
        """
        Get scheduler runtime metrics and store analytics.

        Returns combined scheduler metrics (polls, debates created/failed,
        uptime) and store analytics (by platform, by category, daily counts).

        Returns:
            Dict with scheduler metrics and store analytics.
        """
        return self._client.request("GET", "/api/v1/pulse/scheduler/analytics")

    # =========================================================================
    # Scheduler Management
    # =========================================================================

    def get_scheduler_status(self) -> dict[str, Any]:
        """
        Get pulse scheduler status.

        Returns:
            Dict with scheduler running state, next poll time,
            and configuration.
        """
        return self._client.request("GET", "/api/v1/pulse/scheduler/status")

    def get_scheduler_config(self) -> dict[str, Any]:
        """Get pulse scheduler configuration.

        .. deprecated::
            The server has no read endpoint for scheduler configuration
            (config is PATCH-only via /api/v1/pulse/scheduler/config); the
            previous implementation POSTed into the config-update branch.
            This shim performs a safe GET, which the server does not serve.
        """
        _warn_deprecated(
            "get_scheduler_config is deprecated: the server has no scheduler "
            "config read endpoint (config is PATCH-only)."
        )
        return self._client.request("GET", "/api/v1/pulse/scheduler/config")

    def get_scheduler_history(self) -> dict[str, Any]:
        """
        Get pulse scheduler execution history.

        Returns:
            Dict with recent scheduler runs, their results, and timing.
        """
        return self._client.request("GET", "/api/v1/pulse/scheduler/history")

    def start_scheduler(self) -> dict[str, Any]:
        """
        Start the pulse scheduler.

        Returns:
            Dict with scheduler start confirmation.
        """
        return self._client.request("POST", "/api/v1/pulse/scheduler/start")

    def stop_scheduler(self) -> dict[str, Any]:
        """
        Stop the pulse scheduler.

        Returns:
            Dict with scheduler stop confirmation.
        """
        return self._client.request("POST", "/api/v1/pulse/scheduler/stop")

    def pause_scheduler(self) -> dict[str, Any]:
        """
        Pause the pulse scheduler.

        Returns:
            Dict with scheduler pause confirmation.
        """
        return self._client.request("POST", "/api/v1/pulse/scheduler/pause")

    def resume_scheduler(self) -> dict[str, Any]:
        """
        Resume a paused pulse scheduler.

        Returns:
            Dict with scheduler resume confirmation.
        """
        return self._client.request("POST", "/api/v1/pulse/scheduler/resume")


class AsyncPulseAPI:
    """
    Asynchronous Pulse API for trending topics and signals.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     trending = await client.pulse.get_trending(source="hackernews")
        ...     topic = await client.pulse.suggest_debate_topic()
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    # =========================================================================
    # Trending & Suggestions
    # =========================================================================

    async def get_trending(
        self,
        source: Literal["all", "hackernews", "reddit", "twitter"] | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get trending topics from monitored sources."""
        params: dict[str, Any] = {"limit": limit}
        if source:
            params["source"] = source
        if category:
            params["category"] = category
        return await self._client.request("GET", "/api/v1/pulse/trending", params=params)

    async def suggest_debate_topic(
        self,
        source: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Get a suggested debate topic from trending signals."""
        params: dict[str, Any] = {}
        if source:
            params["source"] = source
        if category:
            params["category"] = category
        return await self._client.request("GET", "/api/v1/pulse/suggest", params=params)

    async def create_debate_topic(self, **kwargs: Any) -> dict[str, Any]:
        """Create a debate from a pulse topic."""
        return await self._client.request("POST", "/api/v1/pulse/debate-topic", json=kwargs)

    # =========================================================================
    # Analytics
    # =========================================================================

    async def get_analytics(self, **kwargs: Any) -> dict[str, Any]:
        """Get pulse analytics including topic distribution and trends."""
        return await self._client.request("GET", "/api/v1/pulse/analytics", params=kwargs)

    async def get_scheduler_analytics(self) -> dict[str, Any]:
        """Get scheduler runtime metrics and store analytics."""
        return await self._client.request("GET", "/api/v1/pulse/scheduler/analytics")

    # =========================================================================
    # Scheduler Management
    # =========================================================================

    async def get_scheduler_status(self) -> dict[str, Any]:
        """Get pulse scheduler status."""
        return await self._client.request("GET", "/api/v1/pulse/scheduler/status")

    async def get_scheduler_config(self) -> dict[str, Any]:
        """Deprecated: no scheduler-config read endpoint exists (PATCH-only)."""
        _warn_deprecated(
            "get_scheduler_config is deprecated: the server has no scheduler "
            "config read endpoint (config is PATCH-only)."
        )
        return await self._client.request("GET", "/api/v1/pulse/scheduler/config")

    async def get_scheduler_history(self) -> dict[str, Any]:
        """Get pulse scheduler execution history."""
        return await self._client.request("GET", "/api/v1/pulse/scheduler/history")

    async def start_scheduler(self) -> dict[str, Any]:
        """Start the pulse scheduler."""
        return await self._client.request("POST", "/api/v1/pulse/scheduler/start")

    async def stop_scheduler(self) -> dict[str, Any]:
        """Stop the pulse scheduler."""
        return await self._client.request("POST", "/api/v1/pulse/scheduler/stop")

    async def pause_scheduler(self) -> dict[str, Any]:
        """Pause the pulse scheduler."""
        return await self._client.request("POST", "/api/v1/pulse/scheduler/pause")

    async def resume_scheduler(self) -> dict[str, Any]:
        """Resume a paused pulse scheduler."""
        return await self._client.request("POST", "/api/v1/pulse/scheduler/resume")
