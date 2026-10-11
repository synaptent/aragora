"""
Trending Pulse Ingestor.

Fetches real-time trending topics from social media platforms
for dynamic debate topic generation.

Production features:
- Exponential backoff with configurable retries
- Circuit breaker for failing APIs
- Proper logging (no print statements)
- Input validation
- Multiple platform support (Twitter, HackerNews, Reddit)
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable, Coroutine

import defusedxml.ElementTree as ET
import httpx

from aragora.exceptions import ExternalServiceError
from aragora.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


@dataclass
class TrendingTopic:
    """A trending topic from social media."""

    platform: str  # "twitter", "reddit", etc.
    topic: str
    volume: int = 0  # engagement metric
    category: str = ""  # "tech", "politics", etc.
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_debate_prompt(self) -> str:
        """Convert to a debate-ready prompt."""
        return f"Debate the implications of trending topic: '{self.topic}' ({self.platform}, {self.volume} engagement)"


@dataclass
class TrendingTopicOutcome:
    """Records the outcome of a debate on a trending topic.

    This enables analytics on which trending topics lead to productive debates.
    """

    topic: str
    platform: str
    debate_id: str
    consensus_reached: bool
    confidence: float
    rounds_used: int = 0
    timestamp: float = field(default_factory=time.time)
    category: str = ""
    volume: int = 0  # Original volume at debate time


class PulseIngestor(ABC):
    """Abstract base class for social media ingestors."""

    def __init__(
        self,
        api_key: str | None = None,
        rate_limit_delay: float = 1.0,
        max_retries: int = 3,
        base_retry_delay: float = 1.0,
    ):
        self.api_key = api_key
        self.rate_limit_delay = rate_limit_delay
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        self.last_request_time: float = 0.0
        self.cache: dict[str, list[TrendingTopic]] = {}
        self.cache_ttl = 300  # 5 minutes
        self.circuit_breaker = CircuitBreaker()

    async def _rate_limit(self) -> None:
        """Enforce rate limiting."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = now

    async def _retry_with_backoff(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
        fallback_fn: Callable[[], Any] | None = None,
    ) -> Any:
        """Execute a coroutine with exponential backoff retry.

        Args:
            coro_factory: Callable that returns a new coroutine on each call
            fallback_fn: Optional fallback function if all retries fail

        Returns:
            Result from successful coroutine or fallback
        """
        if not self.circuit_breaker.can_proceed():
            logger.debug("Circuit breaker open, using fallback")
            return fallback_fn() if fallback_fn else []

        last_error = None
        for attempt in range(self.max_retries):
            try:
                await self._rate_limit()
                result = await coro_factory()
                self.circuit_breaker.record_success()
                return result
            except (OSError, ValueError, TypeError, RuntimeError, TimeoutError) as e:
                last_error = e
                delay = self.base_retry_delay * (2**attempt)
                logger.warning(
                    "Attempt %s/%s failed: %s. Retrying in %.1fs",
                    attempt + 1,
                    self.max_retries,
                    e,
                    delay,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(delay)

        # All retries failed
        self.circuit_breaker.record_failure()
        logger.error("All %s retries failed: %s", self.max_retries, last_error)

        if fallback_fn:
            return fallback_fn()
        return []

    @abstractmethod
    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch trending topics from the platform."""
        raise NotImplementedError("Subclasses must implement fetch_trending method")

    def _filter_content(
        self, topics: list[TrendingTopic], filters: dict[str, Any]
    ) -> list[TrendingTopic]:
        """Apply content filters to remove harmful/inappropriate content."""
        filtered = []

        for topic in topics:
            # Skip if sentiment analysis indicates high toxicity (placeholder)
            if filters.get("skip_toxic", True) and self._is_toxic(topic.topic):
                continue

            # Category filtering
            if filters.get("categories") and topic.category not in filters["categories"]:
                continue

            # Volume threshold
            if filters.get("min_volume", 0) > 0 and topic.volume < filters["min_volume"]:
                continue

            filtered.append(topic)

        return filtered

    def _is_toxic(self, text: str) -> bool:
        """Enhanced toxicity check with categorized patterns.

        Uses weighted keyword matching across categories:
        - High severity: explicit hate speech, violence threats
        - Medium severity: harassment, discrimination
        - Low severity: profanity, adult content markers
        """
        text_lower = text.lower()

        # High severity - immediate reject
        high_severity = [
            "kill",
            "murder",
            "attack",
            "bomb",
            "terrorist",
            "hate crime",
            "genocide",
            "ethnic cleansing",
        ]
        if any(term in text_lower for term in high_severity):
            return True

        # Medium severity - context-dependent
        medium_severity = [
            "hate",
            "violence",
            "racist",
            "sexist",
            "homophobic",
            "slur",
            "harass",
            "threat",
            "abuse",
            "bully",
        ]
        medium_count = sum(1 for term in medium_severity if term in text_lower)
        if medium_count >= 2:
            return True

        # Low severity - adult content markers
        low_severity = ["nsfw", "explicit", "18+", "adult only", "xxx"]
        if any(term in text_lower for term in low_severity):
            return True

        return False


class TwitterIngestor(PulseIngestor):
    """Twitter/X trending topics ingestor using Twitter API v2."""

    def __init__(self, bearer_token: str | None = None, **kwargs):
        super().__init__(api_key=bearer_token, **kwargs)
        self.base_url = "https://api.twitter.com/2"

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch trending topics from Twitter.

        Note: Twitter/X API requires paid subscription ($100+/month).
        Without API key, returns empty list (use free alternatives like Google Trends).
        """
        # Validate limit
        limit = max(1, min(limit, 50))

        if not self.api_key:
            logger.info("[twitter] No API key configured (X API requires paid subscription)")
            return []  # Return empty, not mock data

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Get trending topics for a location (WOEID 1 = worldwide)
                url = f"{self.base_url}/trends/place.json"
                params = {"id": 1}  # Worldwide
                headers = {"Authorization": f"Bearer {self.api_key}"}

                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()

                data = response.json()

                # Validate response structure
                if not isinstance(data, list) or len(data) == 0:
                    raise ValueError("Invalid Twitter API response format")
                if "trends" not in data[0]:
                    raise ValueError("Missing 'trends' key in response")

                topics = []
                for trend in data[0]["trends"][:limit]:
                    topic = TrendingTopic(
                        platform="twitter",
                        topic=trend["name"],
                        volume=trend.get("tweet_volume") or 0,
                        category=self._categorize_topic(trend["name"]),
                        raw_data=trend,
                    )
                    topics.append(topic)

                return topics

        return await self._retry_with_backoff(
            _fetch, fallback_fn=lambda: self._mock_trending_data(limit)
        )

    def _categorize_topic(self, topic: str) -> str:
        """Simple categorization based on keywords."""
        topic_lower = topic.lower()
        if any(word in topic_lower for word in ["ai", "tech", "code", "software"]):
            return "tech"
        elif any(word in topic_lower for word in ["politics", "election", "government"]):
            return "politics"
        elif any(word in topic_lower for word in ["climate", "environment", "green"]):
            return "environment"
        else:
            return "general"

    def _mock_trending_data(self, limit: int) -> list[TrendingTopic]:
        """Mock trending data for development/testing."""
        mock_topics = [
            TrendingTopic("twitter", "#AIAgents2026", 125000, "tech"),
            TrendingTopic("twitter", "#ClimateAction", 98000, "environment"),
            TrendingTopic("twitter", "#AGISafety", 200000, "tech"),
            TrendingTopic("twitter", "#QuantumSupremacy", 45000, "tech"),
            TrendingTopic("twitter", "#SustainableAI", 78000, "environment"),
        ]
        return mock_topics[:limit]


class HackerNewsIngestor(PulseIngestor):
    """Hacker News trending stories ingestor using Algolia API (free, no auth)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = "https://hn.algolia.com/api/v1"

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch top stories from Hacker News."""
        limit = max(1, min(limit, 50))

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Get front page stories sorted by popularity
                url = f"{self.base_url}/search"
                params: dict[str, str | int] = {
                    "tags": "front_page",
                    "hitsPerPage": limit,
                }

                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json()

                # Validate response
                if "hits" not in data:
                    raise ValueError("Invalid HN API response format")

                topics = []
                for story in data["hits"][:limit]:
                    topic = TrendingTopic(
                        platform="hackernews",
                        topic=story.get("title", "Untitled"),
                        volume=story.get("points", 0),
                        category=self._categorize_topic(story.get("title", "")),
                        raw_data={
                            "url": story.get("url"),
                            "author": story.get("author"),
                            "num_comments": story.get("num_comments", 0),
                            "objectID": story.get("objectID"),
                        },
                    )
                    topics.append(topic)

                return topics

        return await self._retry_with_backoff(
            _fetch,
            fallback_fn=lambda: [],  # No mock data - return empty on failure
        )

    def _categorize_topic(self, title: str) -> str:
        """Categorize HN story based on title keywords."""
        title_lower = title.lower()
        if any(word in title_lower for word in ["ai", "gpt", "llm", "machine learning", "neural"]):
            return "ai"
        elif any(word in title_lower for word in ["startup", "funding", "vc", "acquisition"]):
            return "business"
        elif any(word in title_lower for word in ["rust", "python", "javascript", "go ", "code"]):
            return "programming"
        elif any(word in title_lower for word in ["security", "hack", "vulnerability", "breach"]):
            return "security"
        return "tech"

    def _mock_trending_data(self, limit: int) -> list[TrendingTopic]:
        """Mock HN data for development/testing."""
        mock_topics = [
            TrendingTopic("hackernews", "Show HN: I built an AI debate platform", 342, "ai"),
            TrendingTopic(
                "hackernews", "Why Rust is the future of systems programming", 256, "programming"
            ),
            TrendingTopic("hackernews", "The hidden costs of technical debt", 189, "tech"),
            TrendingTopic("hackernews", "OpenAI announces GPT-5 preview", 521, "ai"),
            TrendingTopic(
                "hackernews", "Startup raises $50M for quantum computing", 134, "business"
            ),
        ]
        return mock_topics[:limit]


class RedditIngestor(PulseIngestor):
    """Reddit trending posts ingestor using public JSON API (no auth required)."""

    DEFAULT_SUBREDDITS = ["technology", "programming", "science", "worldnews"]

    def __init__(self, subreddits: list[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.subreddits = subreddits or self.DEFAULT_SUBREDDITS
        self.base_url = "https://www.reddit.com"

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch hot posts from configured subreddits."""
        limit = max(1, min(limit, 50))
        per_sub_limit = max(1, limit // len(self.subreddits))

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                client.headers["User-Agent"] = "Aragora/1.0 (debate-platform)"

                all_topics = []
                for subreddit in self.subreddits:
                    try:
                        url = f"{self.base_url}/r/{subreddit}/hot.json"
                        params = {"limit": per_sub_limit}

                        response = await client.get(url, params=params)
                        response.raise_for_status()

                        data = response.json()

                        # Validate response
                        if "data" not in data or "children" not in data["data"]:
                            logger.warning("Invalid Reddit response for r/%s", subreddit)
                            continue

                        for post in data["data"]["children"][:per_sub_limit]:
                            post_data = post["data"]
                            topic = TrendingTopic(
                                platform="reddit",
                                topic=post_data.get("title", "Untitled"),
                                volume=post_data.get("score", 0),
                                category=self._categorize_subreddit(subreddit),
                                raw_data={
                                    "subreddit": subreddit,
                                    "url": post_data.get("url"),
                                    "author": post_data.get("author"),
                                    "num_comments": post_data.get("num_comments", 0),
                                    "permalink": post_data.get("permalink"),
                                },
                            )
                            all_topics.append(topic)
                    except (OSError, ValueError, TypeError, RuntimeError, httpx.HTTPError) as e:
                        logger.warning("Error fetching r/%s: %s", subreddit, e)
                        continue

                return all_topics[:limit]

        return await self._retry_with_backoff(
            _fetch,
            fallback_fn=lambda: [],  # No mock data - return empty on failure
        )

    def _categorize_subreddit(self, subreddit: str) -> str:
        """Map subreddit to category."""
        mapping = {
            "technology": "tech",
            "programming": "programming",
            "science": "science",
            "worldnews": "news",
            "politics": "politics",
            "askscience": "science",
            "machinelearning": "ai",
            "artificial": "ai",
        }
        return mapping.get(subreddit.lower(), "general")

    def _mock_trending_data(self, limit: int) -> list[TrendingTopic]:
        """Mock Reddit data for development/testing."""
        mock_topics = [
            TrendingTopic(
                "reddit", "Scientists discover high-temperature superconductor", 15420, "science"
            ),
            TrendingTopic("reddit", "New programming language gains traction", 8934, "programming"),
            TrendingTopic("reddit", "EU passes sweeping AI regulation", 12567, "news"),
            TrendingTopic("reddit", "Major tech company announces layoffs", 9823, "tech"),
            TrendingTopic("reddit", "Breakthrough in fusion energy announced", 18234, "science"),
        ]
        return mock_topics[:limit]


class GitHubTrendingIngestor(PulseIngestor):
    """GitHub Trending repositories ingestor using GitHub Search API.

    Uses the GitHub Search API to find recently created repositories
    with high star counts, simulating "trending" repositories.
    No authentication required for basic usage (60 requests/hour limit).
    """

    def __init__(self, access_token: str | None = None, **kwargs):
        """Initialize GitHub trending ingestor.

        Args:
            access_token: Optional GitHub personal access token for higher rate limits
                          (5000 requests/hour authenticated vs 60 unauthenticated)
        """
        super().__init__(api_key=access_token, **kwargs)
        self.base_url = "https://api.github.com"
        # Set lower rate limit delay for unauthenticated requests
        if not access_token:
            self.rate_limit_delay = 2.0  # Be more conservative without auth

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch trending repositories from GitHub.

        Queries recently created repositories sorted by stars to simulate
        trending repositories. Uses the Search API which doesn't require auth.
        """
        limit = max(1, min(limit, 30))  # GitHub API returns max 30 per page

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Build headers
                headers = {
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Aragora/1.0 (debate-platform)",
                }
                if self.api_key:
                    headers["Authorization"] = f"token {self.api_key}"

                # Search for repositories created in the last 7 days, sorted by stars
                from datetime import datetime, timedelta

                week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

                url = f"{self.base_url}/search/repositories"
                params: dict[str, str | int] = {
                    "q": f"created:>{week_ago}",
                    "sort": "stars",
                    "order": "desc",
                    "per_page": limit,
                }

                response = await client.get(url, headers=headers, params=params)

                # Check for rate limiting
                if response.status_code == 403:
                    remaining = response.headers.get("X-RateLimit-Remaining", "0")
                    if remaining == "0":
                        reset_time = response.headers.get("X-RateLimit-Reset", "")
                        logger.warning("GitHub rate limit exceeded. Reset at: %s", reset_time)
                        raise ExternalServiceError(
                            service="GitHub API",
                            reason=f"Rate limit exceeded. Reset at: {reset_time}",
                            status_code=403,
                        )

                response.raise_for_status()
                data = response.json()

                # Validate response
                if "items" not in data:
                    raise ValueError("Invalid GitHub API response format")

                topics = []
                for repo in data["items"][:limit]:
                    description = (repo.get("description") or "No description")[:100]
                    topic = TrendingTopic(
                        platform="github",
                        topic=f"{repo['full_name']}: {description}",
                        volume=repo.get("stargazers_count", 0),
                        category=self._categorize_repo(repo),
                        raw_data={
                            "full_name": repo["full_name"],
                            "url": repo["html_url"],
                            "stars": repo.get("stargazers_count", 0),
                            "forks": repo.get("forks_count", 0),
                            "language": repo.get("language"),
                            "description": repo.get("description"),
                            "created_at": repo.get("created_at"),
                            "topics": repo.get("topics", []),
                        },
                    )
                    topics.append(topic)

                logger.info("[github] Fetched %s real trending repositories", len(topics))
                return topics

        return await self._retry_with_backoff(
            _fetch,
            fallback_fn=lambda: [],  # No mock data - return empty on failure
        )

    def _categorize_repo(self, repo: dict[str, Any]) -> str:
        """Categorize repository based on language and topics."""
        language = (repo.get("language") or "").lower()
        topics = [t.lower() for t in repo.get("topics", [])]
        description = (repo.get("description") or "").lower()

        # Check topics first (most specific)
        ai_keywords = ["machine-learning", "deep-learning", "ai", "llm", "gpt", "neural-network"]
        if any(t in topics for t in ai_keywords) or any(
            k in description for k in ["ai", "llm", "machine learning"]
        ):
            return "ai"

        web_keywords = ["react", "vue", "angular", "frontend", "web", "nextjs"]
        if any(t in topics for t in web_keywords):
            return "web"

        devops_keywords = ["docker", "kubernetes", "devops", "ci-cd", "infrastructure"]
        if any(t in topics for t in devops_keywords):
            return "devops"

        security_keywords = ["security", "pentesting", "vulnerability", "ctf"]
        if any(t in topics for t in security_keywords):
            return "security"

        # Fall back to language
        lang_categories = {
            "rust": "systems",
            "go": "systems",
            "c": "systems",
            "c++": "systems",
            "python": "programming",
            "javascript": "web",
            "typescript": "web",
        }
        if language in lang_categories:
            return lang_categories[language]

        return "programming"

    def _mock_trending_data(self, limit: int) -> list[TrendingTopic]:
        """Mock GitHub trending data for development/testing."""
        mock_topics = [
            TrendingTopic(
                "github",
                "anthropics/claude-code: Official Anthropic CLI for Claude",
                8500,
                "ai",
                raw_data={"full_name": "anthropics/claude-code", "language": "TypeScript"},
            ),
            TrendingTopic(
                "github",
                "rust-lang/cargo: The Rust package manager",
                5200,
                "systems",
                raw_data={"full_name": "rust-lang/cargo", "language": "Rust"},
            ),
            TrendingTopic(
                "github",
                "vercel/ai: Build AI-powered applications with React",
                4100,
                "ai",
                raw_data={"full_name": "vercel/ai", "language": "TypeScript"},
            ),
            TrendingTopic(
                "github",
                "kubernetes/kubernetes: Production-Grade Container Scheduling",
                3800,
                "devops",
                raw_data={"full_name": "kubernetes/kubernetes", "language": "Go"},
            ),
            TrendingTopic(
                "github",
                "fastapi/fastapi: FastAPI framework for building APIs with Python",
                3200,
                "web",
                raw_data={"full_name": "fastapi/fastapi", "language": "Python"},
            ),
        ]
        return mock_topics[:limit]


class GoogleTrendsIngestor(PulseIngestor):
    """Google Trends ingestor using the public RSS feed (free, no auth required).

    Fetches real-time trending searches from Google Trends daily RSS feed.
    No authentication or API key required.
    """

    def __init__(self, geo: str = "US", **kwargs):
        """Initialize Google Trends ingestor.

        Args:
            geo: Geographic region code (US, GB, etc.). Default: US
        """
        super().__init__(**kwargs)
        self.geo = geo
        # Google Trends RSS feed URLs to try (Google changes these periodically)
        self.urls_to_try = [
            f"https://trends.google.com/trending/rss?geo={geo}",
            f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}",
            "https://trends.google.com/trends/trendingsearches/daily/rss",
        ]

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch trending searches from Google Trends RSS feed."""
        limit = max(1, min(limit, 20))

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                last_error: Exception | None = None
                for url in self.urls_to_try:
                    try:
                        params = {"geo": self.geo} if "?" not in url else {}
                        response = await client.get(url, params=params)
                        response.raise_for_status()
                        return await self._parse_rss(response.text, limit)
                    except httpx.HTTPStatusError as e:
                        last_error = e
                        logger.debug("[google_trends] URL %s failed: %s", url, e)
                        continue
                    except (OSError, ValueError, TypeError, RuntimeError) as e:
                        last_error = e
                        logger.debug("[google_trends] URL %s error: %s", url, e)
                        continue

                # All URLs failed - Google may have changed their API again
                logger.warning(
                    "[google_trends] All Google Trends RSS URLs failed. Google may have changed their API. Last error: %s",
                    last_error,
                )
                raise last_error or Exception("All Google Trends URLs failed")

        return await self._retry_with_backoff(_fetch, fallback_fn=lambda: [])

    async def _parse_rss(self, rss_text: str, limit: int) -> list[TrendingTopic]:
        """Parse Google Trends RSS XML response."""
        root = ET.fromstring(rss_text)

        topics = []
        # Find all items in the RSS feed
        for item in root.findall(".//item")[:limit]:
            title = item.find("title")
            # Try both old and new namespace formats
            traffic = item.find(
                "{https://trends.google.com/trends/trendingsearches/daily}approx_traffic"
            )
            if traffic is None:
                traffic = item.find("ht:approx_traffic")

            if title is not None:
                # Parse traffic number (e.g., "200K+" -> 200000)
                volume = 0
                if traffic is not None and traffic.text:
                    traffic_str = traffic.text.replace("+", "").replace(",", "")
                    if "K" in traffic_str:
                        volume = int(float(traffic_str.replace("K", "")) * 1000)
                    elif "M" in traffic_str:
                        volume = int(float(traffic_str.replace("M", "")) * 1000000)
                    else:
                        try:
                            volume = int(traffic_str)
                        except ValueError:
                            volume = 0

                topic = TrendingTopic(
                    platform="google",
                    topic=title.text or "Unknown",
                    volume=volume,
                    category=self._categorize_topic(title.text or ""),
                    raw_data={"geo": self.geo},
                )
                topics.append(topic)

        logger.info("[google_trends] Fetched %s real trending searches from Google", len(topics))
        return topics

    def _categorize_topic(self, topic: str) -> str:
        """Categorize Google Trends topic based on keywords."""
        topic_lower = topic.lower()
        if any(
            word in topic_lower
            for word in ["ai", "tech", "software", "app", "google", "apple", "microsoft"]
        ):
            return "tech"
        elif any(
            word in topic_lower
            for word in ["election", "president", "congress", "vote", "political"]
        ):
            return "politics"
        elif any(word in topic_lower for word in ["climate", "environment", "weather", "storm"]):
            return "environment"
        elif any(
            word in topic_lower for word in ["game", "sport", "nfl", "nba", "soccer", "football"]
        ):
            return "sports"
        elif any(word in topic_lower for word in ["movie", "show", "celebrity", "music", "album"]):
            return "entertainment"
        return "general"


class ArxivIngestor(PulseIngestor):
    """ArXiv new papers ingestor using the ArXiv API (free, no auth required).

    Fetches recent papers from ArXiv, sorted by submission date.
    Useful for academic and research-focused debate topics.
    """

    def __init__(self, categories: list[str] | None = None, **kwargs):
        """Initialize ArXiv ingestor.

        Args:
            categories: ArXiv categories to search (e.g., ["cs.AI", "cs.LG"]).
                        Default: AI/ML related categories.
        """
        super().__init__(**kwargs)
        self.categories = categories or ["cs.AI", "cs.LG", "cs.CL", "stat.ML"]
        self.base_url = "http://export.arxiv.org/api/query"

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch recent papers from ArXiv."""
        limit = max(1, min(limit, 50))

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Build category query (OR across categories)
                cat_query = " OR ".join(f"cat:{cat}" for cat in self.categories)
                params: dict[str, str | int] = {
                    "search_query": cat_query,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                    "max_results": limit,
                }

                response = await client.get(self.base_url, params=params)
                response.raise_for_status()

                # Parse Atom XML feed
                root = ET.fromstring(response.text)
                ns = {
                    "atom": "http://www.w3.org/2005/Atom",
                    "arxiv": "http://arxiv.org/schemas/atom",
                }

                topics = []
                for entry in root.findall("atom:entry", ns)[:limit]:
                    title = entry.find("atom:title", ns)
                    summary = entry.find("atom:summary", ns)
                    published = entry.find("atom:published", ns)
                    arxiv_id = entry.find("atom:id", ns)

                    # Get primary category
                    primary_cat = entry.find("arxiv:primary_category", ns)
                    category = (
                        primary_cat.get("term", "cs.AI") if primary_cat is not None else "cs.AI"
                    )

                    if title is not None:
                        topic = TrendingTopic(
                            platform="arxiv",
                            topic=(
                                title.text.strip().replace("\n", " ") if title.text else "Untitled"
                            ),
                            volume=0,  # ArXiv doesn't provide engagement metrics
                            category=self._categorize_arxiv(category),
                            raw_data={
                                "arxiv_id": arxiv_id.text if arxiv_id is not None else None,
                                "summary": (
                                    summary.text[:500]
                                    if summary is not None and summary.text
                                    else None
                                ),
                                "published": published.text if published is not None else None,
                                "arxiv_category": category,
                            },
                        )
                        topics.append(topic)

                logger.info("[arxiv] Fetched %s recent papers", len(topics))
                return topics

        return await self._retry_with_backoff(_fetch, fallback_fn=lambda: [])

    def _categorize_arxiv(self, arxiv_category: str) -> str:
        """Map ArXiv category to topic category."""
        mapping = {
            "cs.AI": "ai",
            "cs.LG": "ai",
            "cs.CL": "nlp",
            "cs.CV": "ai",
            "cs.NE": "ai",
            "stat.ML": "ai",
            "cs.CR": "security",
            "cs.SE": "programming",
            "cs.PL": "programming",
            "cs.DC": "systems",
            "cs.DB": "systems",
            "physics": "science",
            "math": "science",
            "q-bio": "science",
        }
        for prefix, cat in mapping.items():
            if arxiv_category.startswith(prefix):
                return cat
        return "research"


class LobstersIngestor(PulseIngestor):
    """Lobste.rs trending stories ingestor (free, no auth required).

    Fetches hottest stories from Lobste.rs, a technology-focused link aggregator.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = "https://lobste.rs"

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch hottest stories from Lobste.rs."""
        limit = max(1, min(limit, 25))

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.base_url}/hottest.json"
                response = await client.get(url)
                response.raise_for_status()

                stories = response.json()

                topics = []
                for story in stories[:limit]:
                    topic = TrendingTopic(
                        platform="lobsters",
                        topic=story.get("title", "Untitled"),
                        volume=story.get("score", 0),
                        category=self._categorize_tags(story.get("tags", [])),
                        raw_data={
                            "url": story.get("url"),
                            "short_id": story.get("short_id"),
                            "submitter": story.get("submitter_user", {}).get("username"),
                            "comment_count": story.get("comment_count", 0),
                            "tags": story.get("tags", []),
                        },
                    )
                    topics.append(topic)

                logger.info("[lobsters] Fetched %s hottest stories", len(topics))
                return topics

        return await self._retry_with_backoff(_fetch, fallback_fn=lambda: [])

    def _categorize_tags(self, tags: list[str]) -> str:
        """Map Lobste.rs tags to category."""
        tag_set = set(t.lower() for t in tags)
        if tag_set & {"ai", "ml", "machine-learning"}:
            return "ai"
        if tag_set & {"security", "privacy"}:
            return "security"
        if tag_set & {"rust", "go", "python", "javascript", "programming"}:
            return "programming"
        if tag_set & {"linux", "unix", "devops", "distributed"}:
            return "systems"
        if tag_set & {"web", "browsers", "css", "javascript"}:
            return "web"
        return "tech"


class DevToIngestor(PulseIngestor):
    """Dev.to trending articles ingestor (free, no auth required).

    Fetches top articles from Dev.to developer community.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = "https://dev.to/api"

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch top articles from Dev.to."""
        limit = max(1, min(limit, 30))

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{self.base_url}/articles"
                params = {"per_page": limit, "top": 7}  # Top from last 7 days
                response = await client.get(url, params=params)
                response.raise_for_status()

                articles = response.json()

                topics = []
                for article in articles[:limit]:
                    topic = TrendingTopic(
                        platform="devto",
                        topic=article.get("title", "Untitled"),
                        volume=article.get("public_reactions_count", 0),
                        category=self._categorize_tags(article.get("tag_list", [])),
                        raw_data={
                            "url": article.get("url"),
                            "id": article.get("id"),
                            "user": article.get("user", {}).get("username"),
                            "comments_count": article.get("comments_count", 0),
                            "reading_time": article.get("reading_time_minutes"),
                            "tags": article.get("tag_list", []),
                        },
                    )
                    topics.append(topic)

                logger.info("[devto] Fetched %s top articles", len(topics))
                return topics

        return await self._retry_with_backoff(_fetch, fallback_fn=lambda: [])

    def _categorize_tags(self, tags: list[str]) -> str:
        """Map Dev.to tags to category."""
        tag_set = set(t.lower() for t in tags)
        if tag_set & {"ai", "machinelearning", "deeplearning", "llm", "gpt"}:
            return "ai"
        if tag_set & {"security", "cybersecurity", "infosec"}:
            return "security"
        if tag_set & {"webdev", "frontend", "react", "vue", "javascript", "css"}:
            return "web"
        if tag_set & {"devops", "docker", "kubernetes", "cloud", "aws"}:
            return "devops"
        if tag_set & {"career", "beginners", "tutorial"}:
            return "learning"
        return "programming"


class ProductHuntIngestor(PulseIngestor):
    """Product Hunt trending products ingestor.

    Fetches trending products from Product Hunt.
    Note: Product Hunt API requires OAuth for full access.
    Uses public RSS feed for basic access.
    """

    def __init__(self, access_token: str | None = None, **kwargs):
        """Initialize Product Hunt ingestor.

        Args:
            access_token: Optional Product Hunt API access token for full API access.
                          Without token, uses public RSS feed (limited data).
        """
        super().__init__(api_key=access_token, **kwargs)
        self.api_url = "https://api.producthunt.com/v2/api/graphql"
        self.rss_url = "https://www.producthunt.com/feed"

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch trending products from Product Hunt."""
        limit = max(1, min(limit, 20))

        if self.api_key:
            return await self._fetch_via_api(limit)
        return await self._fetch_via_rss(limit)

    async def _fetch_via_rss(self, limit: int) -> list[TrendingTopic]:
        """Fetch via public RSS feed (no auth required)."""

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.rss_url)
                response.raise_for_status()

                root = ET.fromstring(response.text)

                topics = []
                for item in root.findall(".//item")[:limit]:
                    title = item.find("title")
                    link = item.find("link")
                    description = item.find("description")

                    if title is not None:
                        topic = TrendingTopic(
                            platform="producthunt",
                            topic=title.text or "Untitled",
                            volume=0,  # RSS doesn't include vote count
                            category="product",
                            raw_data={
                                "url": link.text if link is not None else None,
                                "description": (
                                    description.text[:200]
                                    if description is not None and description.text
                                    else None
                                ),
                            },
                        )
                        topics.append(topic)

                logger.info("[producthunt] Fetched %s products via RSS", len(topics))
                return topics

        return await self._retry_with_backoff(_fetch, fallback_fn=lambda: [])

    async def _fetch_via_api(self, limit: int) -> list[TrendingTopic]:
        """Fetch via GraphQL API (requires auth)."""

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                query = (
                    """
                query {
                    posts(first: %d, order: VOTES) {
                        edges {
                            node {
                                id
                                name
                                tagline
                                url
                                votesCount
                                topics {
                                    edges {
                                        node {
                                            name
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                """
                    % limit
                )

                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }

                response = await client.post(
                    self.api_url,
                    json={"query": query},
                    headers=headers,
                )
                response.raise_for_status()

                data = response.json()
                posts = data.get("data", {}).get("posts", {}).get("edges", [])

                topics = []
                for edge in posts[:limit]:
                    post = edge.get("node", {})
                    post_topics = [
                        t["node"]["name"] for t in post.get("topics", {}).get("edges", [])
                    ]

                    topic = TrendingTopic(
                        platform="producthunt",
                        topic=f"{post.get('name', 'Untitled')}: {post.get('tagline', '')}",
                        volume=post.get("votesCount", 0),
                        category=self._categorize_topics(post_topics),
                        raw_data={
                            "id": post.get("id"),
                            "url": post.get("url"),
                            "topics": post_topics,
                        },
                    )
                    topics.append(topic)

                logger.info("[producthunt] Fetched %s products via API", len(topics))
                return topics

        return await self._retry_with_backoff(_fetch, fallback_fn=lambda: [])

    def _categorize_topics(self, topics: list[str]) -> str:
        """Map Product Hunt topics to category."""
        topic_lower = [t.lower() for t in topics]
        if any("ai" in t or "machine learning" in t for t in topic_lower):
            return "ai"
        if any("developer" in t or "api" in t for t in topic_lower):
            return "developer-tools"
        if any("productivity" in t for t in topic_lower):
            return "productivity"
        if any("design" in t for t in topic_lower):
            return "design"
        return "product"


class SubstackIngestor(PulseIngestor):
    """Substack trending newsletters ingestor.

    Fetches from curated Substack feeds and popular tech newsletters.
    Uses RSS feeds (no auth required).
    """

    # Popular tech/AI Substack newsletters with RSS feeds
    DEFAULT_FEEDS = [
        ("https://stratechery.com/feed/", "tech"),
        ("https://www.lennysnewsletter.com/feed", "product"),
        ("https://thegeneralist.substack.com/feed", "business"),
        ("https://www.oneusefulthing.org/feed", "ai"),
    ]

    def __init__(self, feeds: list[tuple] | None = None, **kwargs):
        """Initialize Substack ingestor.

        Args:
            feeds: List of (feed_url, category) tuples. Default: curated tech feeds.
        """
        super().__init__(**kwargs)
        self.feeds = feeds or self.DEFAULT_FEEDS

    async def fetch_trending(self, limit: int = 10) -> list[TrendingTopic]:
        """Fetch recent articles from Substack RSS feeds."""
        from aragora.security.safe_http import SSRFBlockedError, async_safe_get

        limit = max(1, min(limit, 20))
        per_feed = max(1, limit // len(self.feeds))

        async def _fetch() -> list[TrendingTopic]:
            async with httpx.AsyncClient(timeout=10.0) as client:
                all_topics = []

                for feed_url, category in self.feeds:
                    try:
                        response = await async_safe_get(feed_url, client=client, timeout=10.0)
                        response.raise_for_status()

                        root = ET.fromstring(response.text)

                        for item in root.findall(".//item")[:per_feed]:
                            title = item.find("title")
                            link = item.find("link")
                            pub_date = item.find("pubDate")

                            if title is not None:
                                topic = TrendingTopic(
                                    platform="substack",
                                    topic=title.text or "Untitled",
                                    volume=0,  # RSS doesn't include engagement
                                    category=category,
                                    raw_data={
                                        "url": link.text if link is not None else None,
                                        "feed": feed_url,
                                        "published": (
                                            pub_date.text if pub_date is not None else None
                                        ),
                                    },
                                )
                                all_topics.append(topic)
                    except SSRFBlockedError:
                        logger.warning("[substack] SSRF blocked feed URL: %s", feed_url)
                        continue
                    except (OSError, ValueError, TypeError, RuntimeError) as e:
                        logger.warning("Error fetching Substack feed %s: %s", feed_url, e)
                        continue

                logger.info("[substack] Fetched %s articles from feeds", len(all_topics))
                return all_topics[:limit]

        return await self._retry_with_backoff(_fetch, fallback_fn=lambda: [])


class PulseManager:
    def __init__(self) -> None:
        self.ingestors: dict[str, PulseIngestor] = {}
        # Store debate outcomes for analytics
        self._outcomes: list[TrendingTopicOutcome] = []
        self._max_outcomes: int = 1000  # Rolling window

    def add_ingestor(self, name: str, ingestor: PulseIngestor) -> None:
        """Add an ingestor."""
        self.ingestors[name] = ingestor

    async def get_trending_topics(
        self,
        platforms: list[str] | None = None,
        limit_per_platform: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[TrendingTopic]:
        """Get trending topics from specified platforms."""
        if platforms is None:
            platforms = list(self.ingestors.keys())

        all_topics: list[TrendingTopic] = []

        # Fetch concurrently from all platforms
        tasks: list[Any] = []
        for platform in platforms:
            if platform in self.ingestors:
                tasks.append(self.ingestors[platform].fetch_trending(limit_per_platform))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, BaseException):
                    logger.warning("Ingestor error: %s", result)
                else:
                    all_topics.extend(result)

        # Apply global filters
        if filters and platforms:
            all_topics = self.ingestors.get(platforms[0], TwitterIngestor())._filter_content(
                all_topics, filters
            )

        # Sort by volume and return top topics
        all_topics.sort(key=lambda t: t.volume, reverse=True)
        max_results = limit_per_platform * len(platforms) if platforms else limit_per_platform
        return all_topics[:max_results]

    def select_topic_for_debate(self, topics: list[TrendingTopic]) -> TrendingTopic | None:
        """Select the most suitable topic for debate."""
        if not topics:
            return None

        # Prioritize diverse categories, high volume topics
        categories_seen = set()
        for topic in topics:
            if topic.category not in categories_seen:
                categories_seen.add(topic.category)
                return topic

        # Fallback to highest volume
        return max(topics, key=lambda t: t.volume)

    def record_debate_outcome(
        self,
        topic: str,
        platform: str,
        debate_id: str,
        consensus_reached: bool,
        confidence: float,
        rounds_used: int = 0,
        category: str = "",
        volume: int = 0,
    ) -> TrendingTopicOutcome:
        """Record the outcome of a debate on a trending topic.

        This enables analytics on which trending topics lead to productive debates.

        Args:
            topic: The trending topic text
            platform: Source platform (twitter, hackernews, reddit)
            debate_id: Unique debate identifier
            consensus_reached: Whether the debate reached consensus
            confidence: Final confidence score (0-1)
            rounds_used: Number of debate rounds
            category: Topic category (tech, politics, etc.)
            volume: Original engagement volume

        Returns:
            The created TrendingTopicOutcome record
        """
        outcome = TrendingTopicOutcome(
            topic=topic,
            platform=platform,
            debate_id=debate_id,
            consensus_reached=consensus_reached,
            confidence=confidence,
            rounds_used=rounds_used,
            category=category,
            volume=volume,
        )

        self._outcomes.append(outcome)

        # Trim to max size (rolling window)
        if len(self._outcomes) > self._max_outcomes:
            self._outcomes = self._outcomes[-self._max_outcomes :]

        logger.info(
            "[pulse] Recorded debate outcome: %s/%s... (consensus=%s, confidence=%.2f)",
            platform,
            topic[:50],
            consensus_reached,
            confidence,
        )

        return outcome

    def get_analytics(self) -> dict[str, Any]:
        """Get analytics on trending topic debate outcomes.

        Returns:
            Dictionary with analytics data including:
            - total_debates: Total debates with trending topics
            - consensus_rate: Percentage that reached consensus
            - avg_confidence: Average confidence score
            - by_platform: Breakdown by platform
            - by_category: Breakdown by category
            - recent_outcomes: Last 10 outcomes
        """
        if not self._outcomes:
            return {
                "total_debates": 0,
                "consensus_rate": 0.0,
                "avg_confidence": 0.0,
                "by_platform": {},
                "by_category": {},
                "recent_outcomes": [],
            }

        total = len(self._outcomes)
        consensus_count = sum(1 for o in self._outcomes if o.consensus_reached)
        avg_confidence = sum(o.confidence for o in self._outcomes) / total

        # Group by platform
        by_platform: dict[str, dict[str, Any]] = {}
        for outcome in self._outcomes:
            if outcome.platform not in by_platform:
                by_platform[outcome.platform] = {
                    "total": 0,
                    "consensus_count": 0,
                    "confidence_sum": 0.0,
                }
            by_platform[outcome.platform]["total"] += 1
            if outcome.consensus_reached:
                by_platform[outcome.platform]["consensus_count"] += 1
            by_platform[outcome.platform]["confidence_sum"] += outcome.confidence

        # Calculate platform stats
        for platform, stats in by_platform.items():
            stats["consensus_rate"] = (
                stats["consensus_count"] / stats["total"] if stats["total"] > 0 else 0.0
            )
            stats["avg_confidence"] = (
                stats["confidence_sum"] / stats["total"] if stats["total"] > 0 else 0.0
            )
            del stats["confidence_sum"]

        # Group by category
        by_category: dict[str, dict[str, Any]] = {}
        for outcome in self._outcomes:
            cat = outcome.category or "general"
            if cat not in by_category:
                by_category[cat] = {
                    "total": 0,
                    "consensus_count": 0,
                    "confidence_sum": 0.0,
                }
            by_category[cat]["total"] += 1
            if outcome.consensus_reached:
                by_category[cat]["consensus_count"] += 1
            by_category[cat]["confidence_sum"] += outcome.confidence

        # Calculate category stats
        for cat, stats in by_category.items():
            stats["consensus_rate"] = (
                stats["consensus_count"] / stats["total"] if stats["total"] > 0 else 0.0
            )
            stats["avg_confidence"] = (
                stats["confidence_sum"] / stats["total"] if stats["total"] > 0 else 0.0
            )
            del stats["confidence_sum"]

        # Recent outcomes (last 10)
        recent = [
            {
                "topic": o.topic[:100],
                "platform": o.platform,
                "consensus_reached": o.consensus_reached,
                "confidence": o.confidence,
                "timestamp": o.timestamp,
            }
            for o in self._outcomes[-10:]
        ]

        return {
            "total_debates": total,
            "consensus_rate": consensus_count / total,
            "avg_confidence": avg_confidence,
            "by_platform": by_platform,
            "by_category": by_category,
            "recent_outcomes": recent,
        }
