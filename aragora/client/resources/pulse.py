"""
Pulse API for the Aragora Python SDK.

Provides access to trending topics and debate suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.client.client import AragoraClient


@dataclass
class TrendingTopic:
    """A trending topic for debates."""

    title: str
    source: str
    score: float
    category: str = "general"
    url: str | None = None
    summary: str | None = None
    suggested_agents: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.suggested_agents is None:
            self.suggested_agents = []

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrendingTopic:
        return cls(
            title=data.get("title", ""),
            source=data.get("source", "unknown"),
            score=data.get("score", 0.0),
            category=data.get("category", "general"),
            url=data.get("url"),
            summary=data.get("summary"),
            suggested_agents=data.get("suggested_agents", []),
        )


@dataclass
class DebateSuggestion:
    """A suggested debate topic."""

    topic: str
    rationale: str
    difficulty: str = "medium"
    estimated_rounds: int = 3
    suggested_agents: list[str] = field(default_factory=list)
    related_topics: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.suggested_agents is None:
            self.suggested_agents = []
        if self.related_topics is None:
            self.related_topics = []

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DebateSuggestion:
        return cls(
            topic=data.get("topic", ""),
            rationale=data.get("rationale", ""),
            difficulty=data.get("difficulty", "medium"),
            estimated_rounds=data.get("estimated_rounds", 3),
            suggested_agents=data.get("suggested_agents", []),
            related_topics=data.get("related_topics", []),
        )


@dataclass
class PulseAnalytics:
    """Analytics about trending topics."""

    total_topics: int
    by_source: dict[str, int]
    by_category: dict[str, int]
    top_categories: list[str]
    freshness_hours: float = 24.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PulseAnalytics:
        return cls(
            total_topics=data.get("total_topics", 0),
            by_source=data.get("by_source", {}),
            by_category=data.get("by_category", {}),
            top_categories=data.get("top_categories", []),
            freshness_hours=data.get("freshness_hours", 24.0),
        )


class PulseAPI:
    """
    API interface for trending topics and debate suggestions.

    Provides access to trending topics from various sources
    and AI-generated debate suggestions.

    Example:
        # Get trending topics
        trending = client.pulse.trending(category="technology")
        for topic in trending:
            print(f"{topic.title} (score: {topic.score})")

        # Get debate suggestions
        suggestions = client.pulse.suggest(domain="security")
        for s in suggestions:
            print(f"Suggested: {s.topic}")
            print(f"  Rationale: {s.rationale}")

        # Start a debate on a trending topic
        topic = trending[0]
        debate = client.debates.create(task=topic.title)
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    def trending(
        self,
        category: str | None = None,
        source: str | None = None,
        limit: int = 20,
    ) -> list[TrendingTopic]:
        """
        Get trending topics.

        Args:
            category: Filter by category (technology, science, business, etc.)
            source: Filter by source (hackernews, arxiv, reddit, etc.)
            limit: Maximum results to return

        Returns:
            List of TrendingTopic objects sorted by score
        """
        params: dict[str, Any] = {"limit": limit}
        if category:
            params["category"] = category
        if source:
            params["source"] = source

        response = self._client._get("/api/pulse/trending", params=params)
        topics = response.get("topics", [])
        return [TrendingTopic.from_dict(t) for t in topics]

    async def trending_async(
        self,
        category: str | None = None,
        source: str | None = None,
        limit: int = 20,
    ) -> list[TrendingTopic]:
        """Async version of trending."""
        params: dict[str, Any] = {"limit": limit}
        if category:
            params["category"] = category
        if source:
            params["source"] = source

        response = await self._client._get_async("/api/pulse/trending", params=params)
        topics = response.get("topics", [])
        return [TrendingTopic.from_dict(t) for t in topics]

    def suggest(
        self,
        domain: str | None = None,
        difficulty: str | None = None,
        count: int = 5,
    ) -> list[DebateSuggestion]:
        """
        Get debate topic suggestions.

        Args:
            domain: Domain for suggestions (security, architecture, etc.)
            difficulty: Difficulty level (easy, medium, hard)
            count: Number of suggestions to return

        Returns:
            List of DebateSuggestion objects
        """
        params: dict[str, Any] = {"count": count}
        if domain:
            params["domain"] = domain
        if difficulty:
            params["difficulty"] = difficulty

        response = self._client._get("/api/pulse/suggest", params=params)
        suggestions = response.get("suggestions", [])
        return [DebateSuggestion.from_dict(s) for s in suggestions]

    async def suggest_async(
        self,
        domain: str | None = None,
        difficulty: str | None = None,
        count: int = 5,
    ) -> list[DebateSuggestion]:
        """Async version of suggest."""
        params: dict[str, Any] = {"count": count}
        if domain:
            params["domain"] = domain
        if difficulty:
            params["difficulty"] = difficulty

        response = await self._client._get_async("/api/pulse/suggest", params=params)
        suggestions = response.get("suggestions", [])
        return [DebateSuggestion.from_dict(s) for s in suggestions]

    def get_analytics(self) -> PulseAnalytics:
        """
        Get pulse analytics.

        Returns:
            PulseAnalytics with aggregate statistics
        """
        response = self._client._get("/api/pulse/analytics")
        return PulseAnalytics.from_dict(response)

    async def get_analytics_async(self) -> PulseAnalytics:
        """Async version of get_analytics."""
        response = await self._client._get_async("/api/pulse/analytics")
        return PulseAnalytics.from_dict(response)

    def refresh(self, sources: list[str] | None = None) -> bool:
        """
        Refresh trending topics from sources.

        Args:
            sources: Optional list of sources to refresh

        Returns:
            True if refresh was triggered
        """
        data = {}
        if sources:
            data["sources"] = sources

        response = self._client._post("/api/pulse/refresh", data)
        return response.get("refreshed", False)

    async def refresh_async(self, sources: list[str] | None = None) -> bool:
        """Async version of refresh."""
        data = {}
        if sources:
            data["sources"] = sources

        response = await self._client._post_async("/api/pulse/refresh", data)
        return response.get("refreshed", False)
