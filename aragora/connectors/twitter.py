"""
Twitter/X Connector - Social media evidence for aragora agents.

Provides access to Twitter/X via the API v2:
- Search recent tweets by query
- Fetch tweet details
- Get user timeline tweets

Requires TWITTER_BEARER_TOKEN environment variable for API access.
The free tier allows read-only access with limited rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import os

from aragora.connectors.base import BaseConnector, ConnectorError, Evidence
from aragora.reasoning.provenance import ProvenanceManager, SourceType

logger = logging.getLogger(__name__)

# Try to import optional dependencies
try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# Twitter API v2 endpoints
TWITTER_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
TWITTER_TWEET_URL = "https://api.twitter.com/2/tweets"
TWITTER_USER_TWEETS_URL = "https://api.twitter.com/2/users/{user_id}/tweets"
TWITTER_ME_URL = "https://api.twitter.com/2/users/me"
TWITTER_BOOKMARKS_URL = "https://api.twitter.com/2/users/{user_id}/bookmarks"
TWITTER_LIKED_URL = "https://api.twitter.com/2/users/{user_id}/liked_tweets"

# Tweet URL template
TWEET_URL_TEMPLATE = "https://twitter.com/i/status/{tweet_id}"


class TwitterConnector(BaseConnector):
    """
    Connector for Twitter/X via API v2.

    Enables agents to:
    - Search recent tweets (last 7 days)
    - Fetch tweet details with engagement metrics
    - Get tweets from specific users
    - Track public discourse on topics

    Requires TWITTER_BEARER_TOKEN environment variable.

    Example:
        connector = TwitterConnector()
        if connector.is_available and connector.is_configured:
            results = await connector.search("AI safety")
            for evidence in results:
                print(f"{evidence.title} ({evidence.metadata['retweet_count']} RTs)")
    """

    def __init__(
        self,
        bearer_token: str | None = None,
        provenance: ProvenanceManager | None = None,
        default_confidence: float = 0.5,  # Lower than Reddit due to less fact-checking
        timeout: int = 30,
        rate_limit_delay: float = 1.0,  # Twitter has strict rate limits
        max_cache_entries: int = 500,
        cache_ttl_seconds: float = 1800.0,  # 30 min cache (tweets change quickly)
    ):
        """
        Initialize TwitterConnector.

        Args:
            bearer_token: Twitter API v2 Bearer token. If not provided,
                         uses TWITTER_BEARER_TOKEN environment variable.
            provenance: Optional provenance manager for tracking
            default_confidence: Base confidence for Twitter sources
            timeout: HTTP request timeout in seconds
            rate_limit_delay: Delay between API requests
            max_cache_entries: Maximum cached entries
            cache_ttl_seconds: Cache TTL in seconds
        """
        super().__init__(
            provenance=provenance,
            default_confidence=default_confidence,
            max_cache_entries=max_cache_entries,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        self.bearer_token = bearer_token or os.environ.get("TWITTER_BEARER_TOKEN", "")
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time: float = 0.0

    @property
    def source_type(self) -> SourceType:
        """Twitter is external API data."""
        return SourceType.EXTERNAL_API

    @property
    def name(self) -> str:
        """Human-readable connector name."""
        return "Twitter"

    @property
    def is_available(self) -> bool:
        """Check if httpx is available for making requests."""
        return HTTPX_AVAILABLE

    @property
    def is_configured(self) -> bool:
        """Check if Twitter API credentials are configured."""
        return bool(self.bearer_token)

    async def _perform_health_check(self, timeout: float) -> bool:
        """
        Verify Twitter API connectivity with a lightweight request.

        Uses a simple search query to verify the API is responding.
        """
        if not HTTPX_AVAILABLE:
            return False

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # Use a simple search with minimal results
                response = await client.get(
                    TWITTER_SEARCH_URL,
                    headers=self._get_headers(),
                    params={"query": "hello", "max_results": 10},
                )
                # 200 = success, 429 = rate limited (still connected)
                return response.status_code in (200, 429)
        except httpx.TimeoutException:
            logger.debug("Twitter health check timed out")
            return False
        except httpx.RequestError as e:
            logger.debug("Twitter health check failed: %s", e)
            return False

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        import time

        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def _get_headers(self) -> dict:
        """Get headers for Twitter API requests."""
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json",
        }

    async def search(
        self,
        query: str,
        limit: int = 10,
        sort_order: str = "relevancy",
        **kwargs,
    ) -> list[Evidence]:
        """
        Search recent tweets matching query.

        Note: Free tier only searches tweets from the last 7 days.

        Args:
            query: Search query (supports Twitter search operators)
            limit: Maximum results to return (max 100)
            sort_order: "relevancy" (default) or "recency"
            **kwargs: Additional API parameters

        Returns:
            List of Evidence objects with tweet content

        Query operators:
            - "exact phrase" - Exact match
            - from:username - From specific user
            - -keyword - Exclude keyword
            - lang:en - Language filter
            - is:retweet / -is:retweet - Include/exclude retweets
            - has:links - Only tweets with links
        """
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available, cannot search Twitter")
            return []

        if not self.is_configured:
            logger.warning("Twitter Bearer token not configured, cannot search")
            return []

        # Clamp limit (API max is 100)
        limit = min(limit, 100)

        # Build params with expansions for full data
        params: dict[str, str | int] = {
            "query": query,
            "max_results": max(10, limit),  # API requires min 10
            "sort_order": sort_order,
            "tweet.fields": "created_at,author_id,public_metrics,lang,source",
            "expansions": "author_id",
            "user.fields": "username,name,verified,public_metrics",
        }

        # Rate limiting
        await self._rate_limit()

        headers = self._get_headers()

        async def do_request():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    TWITTER_SEARCH_URL,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()

        try:
            data = await self._request_with_retry(do_request, f"search '{query[:50]}'")
            results = self._parse_search_results(data)
            logger.info("Twitter search '%s...' returned %s results", query[:50], len(results))
            return results[:limit]

        except (
            httpx.HTTPError,
            ConnectorError,
            ConnectionError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
        ) as e:
            logger.debug("Twitter search failed: %s", e)
            return []

    async def fetch(self, evidence_id: str) -> Evidence | None:
        """
        Fetch a specific tweet by ID.

        Args:
            evidence_id: Tweet ID (e.g., "twitter:123456" or just "123456")

        Returns:
            Evidence object or None if not found
        """
        # Check cache first
        cached = self._cache_get(evidence_id)
        if cached:
            return cached

        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available, cannot fetch tweet")
            return None

        if not self.is_configured:
            logger.warning("Twitter Bearer token not configured, cannot fetch")
            return None

        # Extract tweet ID
        tweet_id = evidence_id.replace("twitter:", "").strip()

        await self._rate_limit()

        url = f"{TWITTER_TWEET_URL}/{tweet_id}"
        params = {
            "tweet.fields": "created_at,author_id,public_metrics,lang,source,conversation_id",
            "expansions": "author_id",
            "user.fields": "username,name,verified,public_metrics",
        }
        headers = self._get_headers()

        async def do_request():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()

        try:
            data = await self._request_with_retry(do_request, f"fetch {evidence_id}")
            evidence = self._parse_tweet(data.get("data", {}), data.get("includes", {}))
            if evidence:
                self._cache_put(evidence_id, evidence)
            return evidence

        except (
            httpx.HTTPError,
            ConnectorError,
            ConnectionError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
        ) as e:
            logger.debug("Twitter fetch failed for %s: %s", evidence_id, e)
            return None

    def _parse_search_results(self, data: dict) -> list[Evidence]:
        """Parse Twitter search API response into Evidence objects."""
        results = []
        tweets = data.get("data", [])
        includes = data.get("includes", {})

        # Build user lookup for author info
        users = {u["id"]: u for u in includes.get("users", [])}

        for tweet in tweets:
            try:
                evidence = self._parse_tweet(tweet, includes, users)
                if evidence:
                    results.append(evidence)
            except (ValueError, TypeError, KeyError, AttributeError) as e:
                logger.debug("Error parsing tweet: %s", e)
                continue

        return results

    def _parse_tweet(
        self,
        tweet: dict,
        includes: dict,
        users: dict | None = None,
    ) -> Evidence | None:
        """Parse a single tweet into Evidence."""
        tweet_id = tweet.get("id")
        if not tweet_id:
            return None

        # Get content
        text = tweet.get("text", "")
        if not text:
            return None

        # Get author info
        author_id = tweet.get("author_id")
        if users is None:
            users = {u["id"]: u for u in includes.get("users", [])}

        author_info = users.get(author_id, {})
        username = author_info.get("username", "unknown")
        author_name = author_info.get("name", username)
        is_verified = author_info.get("verified", False)

        # Author metrics
        author_metrics = author_info.get("public_metrics", {})
        followers_count = author_metrics.get("followers_count", 0)

        # Created time
        created_at = tweet.get("created_at")

        # Engagement metrics
        metrics = tweet.get("public_metrics", {})
        retweet_count = metrics.get("retweet_count", 0)
        reply_count = metrics.get("reply_count", 0)
        like_count = metrics.get("like_count", 0)
        quote_count = metrics.get("quote_count", 0)

        # Total engagement
        total_engagement = retweet_count + reply_count + like_count + quote_count

        # Calculate confidence based on engagement and author credibility
        engagement_score = min(1.0, total_engagement / 10000)  # Normalize
        follower_score = min(1.0, followers_count / 1_000_000)  # Normalize

        # Verified accounts get bonus
        verified_bonus = 0.1 if is_verified else 0

        confidence = (
            self.default_confidence
            + (engagement_score * 0.15)
            + (follower_score * 0.1)
            + verified_bonus
        )

        # Freshness (tweets decay quickly in relevance)
        freshness = self.calculate_freshness(created_at) if created_at else 0.5

        # Authority based on follower count and verification
        if is_verified and followers_count > 100_000:
            authority = 0.7
        elif followers_count > 100_000:
            authority = 0.6
        elif followers_count > 10_000:
            authority = 0.55
        else:
            authority = 0.45

        # Tweet URL
        tweet_url = TWEET_URL_TEMPLATE.format(tweet_id=tweet_id)

        # Build title
        title = f"@{username}: {text[:50]}{'...' if len(text) > 50 else ''}"

        return Evidence(
            id=f"twitter:{tweet_id}",
            source_type=self.source_type,
            source_id=tweet_id,
            content=text,
            title=title,
            created_at=created_at,
            author=f"@{username}",
            url=tweet_url,
            confidence=min(confidence, 0.80),  # Cap lower than Reddit
            freshness=freshness,
            authority=authority,
            metadata={
                "retweet_count": retweet_count,
                "reply_count": reply_count,
                "like_count": like_count,
                "quote_count": quote_count,
                "total_engagement": total_engagement,
                "author_id": author_id,
                "author_name": author_name,
                "username": username,
                "is_verified": is_verified,
                "followers_count": followers_count,
                "lang": tweet.get("lang"),
                "source": tweet.get("source"),
                "conversation_id": tweet.get("conversation_id"),
            },
        )

    async def get_user_tweets(
        self,
        user_id: str,
        limit: int = 10,
        exclude_replies: bool = True,
        exclude_retweets: bool = True,
    ) -> list[Evidence]:
        """
        Get recent tweets from a specific user.

        Args:
            user_id: Twitter user ID (numeric)
            limit: Maximum tweets to return
            exclude_replies: Exclude reply tweets
            exclude_retweets: Exclude retweets

        Returns:
            List of Evidence objects
        """
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available, cannot get user tweets")
            return []

        if not self.is_configured:
            logger.warning("Twitter Bearer token not configured")
            return []

        limit = min(limit, 100)

        url = TWITTER_USER_TWEETS_URL.format(user_id=user_id)
        params: dict[str, str | int] = {
            "max_results": max(5, limit),
            "tweet.fields": "created_at,author_id,public_metrics,lang,source",
        }

        exclude = []
        if exclude_replies:
            exclude.append("replies")
        if exclude_retweets:
            exclude.append("retweets")
        if exclude:
            params["exclude"] = ",".join(exclude)

        await self._rate_limit()

        headers = self._get_headers()

        async def do_request():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()

        try:
            data = await self._request_with_retry(do_request, f"get_user_tweets {user_id}")
            tweets = data.get("data", [])

            results = []
            for tweet in tweets[:limit]:
                evidence = self._parse_tweet(tweet, {})
                if evidence:
                    results.append(evidence)

            logger.info("Twitter user %s returned %s tweets", user_id, len(results))
            return results

        except (
            httpx.HTTPError,
            ConnectorError,
            ConnectionError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
        ) as e:
            logger.debug("Twitter get_user_tweets failed for %s: %s", user_id, e)
            return []

    async def search_hashtag(self, hashtag: str, limit: int = 10) -> list[Evidence]:
        """
        Search tweets with a specific hashtag.

        Args:
            hashtag: Hashtag without # (e.g., "ArtificialIntelligence")
            limit: Maximum results

        Returns:
            List of Evidence objects
        """
        # Ensure hashtag has # prefix for search
        if not hashtag.startswith("#"):
            hashtag = f"#{hashtag}"

        return await self.search(hashtag, limit=limit)

    # ------------------------------------------------------------------
    # OAuth2 user-context reads (bookmarks / likes)
    #
    # These use a *user* token (scopes bookmark.read / like.read) from
    # aragora.connectors.x_oauth, not the app-only bearer token. Entries are
    # returned in the same shape as the Twitter data-export files so the
    # ideacloud ingestors can reuse their export parsers verbatim.
    # ------------------------------------------------------------------

    async def _user_context_get(self, url: str, params: dict) -> dict | None:
        """GET with a user-context token, refreshing once on 401."""
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available, cannot call X user-context API")
            return None
        from aragora.connectors.x_oauth import XOAuthTokenStore

        store = XOAuthTokenStore()
        tokens = await store.get_valid()
        if tokens is None:
            logger.warning("No X OAuth2 user tokens configured (run scripts/x_oauth_setup.py)")
            return None

        await self._rate_limit()
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {tokens.access_token}"}
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params, headers=headers)
                if response.status_code == 401 and attempt == 0:
                    # refresh_rejected re-reads under the cross-process lock,
                    # so a concurrent refresher's rotated pair is reused
                    # instead of burning a second rotation.
                    tokens = await store.refresh_rejected(tokens)
                    if tokens is None:
                        return None
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                # ValueError covers json.JSONDecodeError on a non-JSON 200 —
                # must honor the (None, None) failure contract, not raise.
                logger.warning("X user-context request failed: %s", exc)
                return None
        return None

    async def get_authenticated_user_id(self) -> str | None:
        """Resolve the token owner's numeric user id via GET /2/users/me."""
        data = await self._user_context_get(TWITTER_ME_URL, {})
        if data:
            return (data.get("data") or {}).get("id")
        return None

    async def fetch_bookmarks_page(
        self,
        user_id: str,
        pagination_token: str | None = None,
        max_results: int = 100,
    ) -> tuple[list[dict] | None, str | None]:
        """Fetch one page of the user's bookmarks (newest-bookmarked first).

        Returns ``(None, None)`` on a failed request — callers must treat that
        differently from ``([], None)``, which means the feed is exhausted.
        """
        return await self._fetch_engagement_page(
            TWITTER_BOOKMARKS_URL.format(user_id=user_id), pagination_token, max_results
        )

    async def fetch_liked_page(
        self,
        user_id: str,
        pagination_token: str | None = None,
        max_results: int = 100,
    ) -> tuple[list[dict] | None, str | None]:
        """Fetch one page of the user's liked tweets (newest-liked first).

        Returns ``(None, None)`` on a failed request — callers must treat that
        differently from ``([], None)``, which means the feed is exhausted.
        """
        return await self._fetch_engagement_page(
            TWITTER_LIKED_URL.format(user_id=user_id), pagination_token, max_results
        )

    async def _fetch_engagement_page(
        self,
        url: str,
        pagination_token: str | None,
        max_results: int,
    ) -> tuple[list[dict] | None, str | None]:
        """Shared pager: (entries, next_token); (None, None) = request failed."""
        params: dict[str, str | int] = {
            "max_results": min(max(1, max_results), 100),
            "tweet.fields": "created_at,author_id,public_metrics,lang",
            "expansions": "author_id",
            "user.fields": "username,name",
        }
        if pagination_token:
            params["pagination_token"] = pagination_token

        data = await self._user_context_get(url, params)
        if data is None:
            # Failed request (network/429/5xx/auth) — NOT feed exhaustion
            return None, None

        users = {u["id"]: u for u in (data.get("includes") or {}).get("users", [])}
        entries: list[dict] = []
        for tweet in data.get("data", []) or []:
            author = users.get(tweet.get("author_id"), {})
            entries.append(
                {
                    "tweetId": tweet.get("id"),
                    "fullText": tweet.get("text", ""),
                    "screenName": author.get("username", ""),
                    "created_at": tweet.get("created_at"),
                    "public_metrics": tweet.get("public_metrics", {}),
                }
            )
        next_token = (data.get("meta") or {}).get("next_token")
        return entries, next_token

    async def search_from_user(
        self,
        username: str,
        query: str = "",
        limit: int = 10,
    ) -> list[Evidence]:
        """
        Search tweets from a specific user, optionally with query.

        Args:
            username: Twitter username (without @)
            query: Optional additional search query
            limit: Maximum results

        Returns:
            List of Evidence objects
        """
        search_query = f"from:{username}"
        if query:
            search_query = f"{query} {search_query}"

        return await self.search(search_query, limit=limit)


__all__ = ["TwitterConnector"]
