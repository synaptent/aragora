"""
Web Search Skill.

Provides web search capabilities using various search providers.
Integrates with debate context for evidence collection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..base import (
    Skill,
    SkillCapability,
    SkillContext,
    SkillManifest,
    SkillResult,
)

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    source: str = "web"
    relevance_score: float = 0.0
    published_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "relevance_score": self.relevance_score,
            "published_date": self.published_date,
        }


class WebSearchSkill(Skill):
    """
    Skill for searching the web.

    Supports multiple search providers:
    - DuckDuckGo (default, no API key required)
    - Google Custom Search (requires API key)
    - Bing Search (requires API key)
    - Tavily (requires API key, optimized for AI)
    """

    def __init__(
        self,
        default_provider: str = "duckduckgo",
        max_results: int = 10,
    ):
        """
        Initialize web search skill.

        Args:
            default_provider: Default search provider to use
            max_results: Default maximum results per search
        """
        self._default_provider = default_provider
        self._max_results = max_results

    @property
    def manifest(self) -> SkillManifest:
        return SkillManifest(
            name="web_search",
            version="1.0.0",
            description="Search the web for information",
            capabilities=[
                SkillCapability.WEB_SEARCH,
                SkillCapability.EXTERNAL_API,
            ],
            input_schema={
                "query": {
                    "type": "string",
                    "description": "Search query",
                    "required": True,
                },
                "max_results": {
                    "type": "number",
                    "description": "Maximum number of results",
                    "default": 10,
                },
                "provider": {
                    "type": "string",
                    "description": "Search provider (duckduckgo, google, bing, tavily)",
                    "default": "duckduckgo",
                },
                "region": {
                    "type": "string",
                    "description": "Search region (e.g., 'us-en')",
                },
                "time_range": {
                    "type": "string",
                    "description": "Time filter (day, week, month, year)",
                },
            },
            tags=["search", "web", "research"],
            debate_compatible=True,
            max_execution_time_seconds=30.0,
            rate_limit_per_minute=30,
        )

    async def execute(
        self,
        input_data: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        """Execute web search."""
        query = input_data.get("query", "")
        if not query:
            return SkillResult.create_failure(
                "Query is required",
                error_code="missing_query",
            )

        max_results = input_data.get("max_results", self._max_results)
        provider = input_data.get("provider", self._default_provider)
        region = input_data.get("region")
        time_range = input_data.get("time_range")

        try:
            if provider == "duckduckgo":
                results = await self._search_duckduckgo(query, max_results, region, time_range)
            elif provider == "tavily":
                results = await self._search_tavily(query, max_results)
            elif provider == "google":
                results = await self._search_google(query, max_results)
            else:
                # Fall back to DuckDuckGo
                results = await self._search_duckduckgo(query, max_results, region, time_range)

            return SkillResult.create_success(
                {
                    "query": query,
                    "provider": provider,
                    "results": [r.to_dict() for r in results],
                    "total_results": len(results),
                },
                provider=provider,
            )

        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            logger.exception("Web search failed: %s", e)
            return SkillResult.create_failure(f"Search failed: {e}")

    async def _search_duckduckgo(
        self,
        query: str,
        max_results: int,
        region: str | None = None,
        time_range: str | None = None,
    ) -> list[SearchResult]:
        """Search using DuckDuckGo."""
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.warning("duckduckgo-search not installed, returning empty results")
            return []

        results: list[SearchResult] = []
        try:
            with DDGS() as ddgs:
                timelimit = None
                if time_range:
                    timelimit_map = {
                        "day": "d",
                        "week": "w",
                        "month": "m",
                        "year": "y",
                    }
                    timelimit = timelimit_map.get(time_range)

                search_results = ddgs.text(
                    query,
                    region=region or "wt-wt",
                    timelimit=timelimit,
                    max_results=max_results,
                )

                for r in search_results:
                    results.append(
                        SearchResult(
                            title=r.get("title", ""),
                            url=r.get("href", ""),
                            snippet=r.get("body", ""),
                            source="duckduckgo",
                        )
                    )
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            logger.warning("DuckDuckGo search error: %s", e)

        return results

    async def _search_tavily(
        self,
        query: str,
        max_results: int,
    ) -> list[SearchResult]:
        """Search using Tavily (AI-optimized search)."""
        import os

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            logger.warning("TAVILY_API_KEY not set, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, max_results, None, None)

        try:
            from aragora.observability.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("tavily") as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": api_key,
                        "query": query,
                        "max_results": max_results,
                        "search_depth": "basic",
                    },
                    timeout=20.0,
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for r in data.get("results", []):
                    results.append(
                        SearchResult(
                            title=r.get("title", ""),
                            url=r.get("url", ""),
                            snippet=r.get("content", ""),
                            source="tavily",
                            relevance_score=r.get("score", 0.0),
                        )
                    )
                return results

        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            logger.warning("Tavily search error: %s", e)
            return await self._search_duckduckgo(query, max_results, None, None)

    async def _search_google(
        self,
        query: str,
        max_results: int,
    ) -> list[SearchResult]:
        """Search using Google Custom Search API."""
        import os

        api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
        cx = os.environ.get("GOOGLE_SEARCH_CX")

        if not api_key or not cx:
            logger.warning("Google Search API not configured, falling back to DuckDuckGo")
            return await self._search_duckduckgo(query, max_results, None, None)

        try:
            from aragora.observability.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("google") as client:
                response = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": api_key,
                        "cx": cx,
                        "q": query,
                        "num": min(max_results, 10),  # Google limits to 10
                    },
                    timeout=20.0,
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("items", []):
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            url=item.get("link", ""),
                            snippet=item.get("snippet", ""),
                            source="google",
                        )
                    )
                return results

        except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
            logger.warning("Google search error: %s", e)
            return await self._search_duckduckgo(query, max_results, None, None)


# Skill instance for registration
SKILLS = [WebSearchSkill()]
