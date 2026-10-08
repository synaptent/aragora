"""
Twitter/X posting connector for publishing debate content.

Supports posting single tweets, threads, and media attachments
using Twitter API v2 with OAuth 1.0a authentication.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aragora.connectors.exceptions import (
    ConnectorAPIError,
    ConnectorAuthError,
    ConnectorError,
    ConnectorRateLimitError,
)
from aragora.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


class TwitterError(ConnectorError):
    """Base exception for Twitter connector errors."""

    def __init__(self, message: str = "Twitter API operation failed", **kwargs):
        super().__init__(message, connector_name="twitter", **kwargs)


class TwitterAuthError(TwitterError, ConnectorAuthError):
    """Authentication/authorization failed."""

    def __init__(self, message: str = "Twitter authentication failed. Check API credentials."):
        super().__init__(message)


class TwitterRateLimitError(TwitterError, ConnectorRateLimitError):
    """Rate limit exceeded."""

    def __init__(self, message: str = "Twitter rate limit exceeded", retry_after: int = 900):
        super().__init__(f"{message}. Retry after {retry_after}s", retry_after=float(retry_after))


class TwitterAPIError(TwitterError, ConnectorAPIError):
    """General API error."""

    def __init__(self, message: str = "Twitter API request failed", status_code: int | None = None):
        full_message = f"{message} (HTTP {status_code})" if status_code else message
        is_retryable = status_code is not None and 500 <= status_code < 600
        super().__init__(full_message, is_retryable=is_retryable)
        self.status_code = status_code


class TwitterMediaError(TwitterError):
    """Media upload failed."""

    def __init__(self, message: str = "Twitter media upload failed"):
        super().__init__(message, is_retryable=True)


# Twitter API limits
MAX_TWEET_LENGTH = 280
MAX_THREAD_LENGTH = 25  # Maximum tweets in a thread
MAX_MEDIA_SIZE_MB = 5  # For images


@dataclass
class TweetResult:
    """Result of posting a tweet."""

    tweet_id: str
    text: str
    created_at: str
    url: str
    success: bool = True
    error: str | None = None


@dataclass
class ThreadResult:
    """Result of posting a thread."""

    thread_id: str  # ID of first tweet
    tweets: list[TweetResult] = field(default_factory=list)
    success: bool = True
    error: str | None = None

    @property
    def url(self) -> str:
        """URL to the first tweet in the thread."""
        if self.tweets:
            return self.tweets[0].url
        return ""


class TwitterRateLimiter:
    """Simple rate limiter for Twitter API."""

    def __init__(self, calls_per_window: int = 50, window_seconds: int = 900):
        self.calls_per_window = calls_per_window
        self.window_seconds = window_seconds
        self.call_times: list[float] = []

    async def acquire(self) -> None:
        """Wait if necessary before making a call."""
        now = time.time()
        # Remove calls outside the window
        self.call_times = [t for t in self.call_times if now - t < self.window_seconds]

        if len(self.call_times) >= self.calls_per_window and self.call_times:
            # Wait until oldest call falls out of window
            wait_time = self.window_seconds - (now - self.call_times[0]) + 1
            if wait_time > 0:
                logger.info("Rate limit: waiting %.1fs", wait_time)
                await asyncio.sleep(wait_time)

        self.call_times.append(time.time())


class TwitterPosterConnector:
    """
    Post debate content to Twitter/X.

    Supports:
    - Single tweets (with optional media)
    - Threads (multiple connected tweets)
    - Media uploads (images, audio previews)

    Authentication uses OAuth 1.0a (required for posting).

    Environment variables:
    - TWITTER_API_KEY: API key (consumer key)
    - TWITTER_API_SECRET: API secret (consumer secret)
    - TWITTER_ACCESS_TOKEN: User access token
    - TWITTER_ACCESS_SECRET: User access token secret
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        access_token: str | None = None,
        access_secret: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("TWITTER_API_KEY", "")
        self.api_secret = api_secret or os.environ.get("TWITTER_API_SECRET", "")
        self.access_token = access_token or os.environ.get("TWITTER_ACCESS_TOKEN", "")
        self.access_secret = access_secret or os.environ.get("TWITTER_ACCESS_SECRET", "")

        self.base_url = "https://api.twitter.com/2"
        self.upload_url = "https://upload.twitter.com/1.1"

        self.rate_limiter = TwitterRateLimiter()
        # Use 1 minute cooldown with higher threshold for Twitter API (matches original)
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=60.0)

        # Log warning if credentials incomplete
        if not all([self.api_key, self.api_secret, self.access_token, self.access_secret]):
            missing = []
            if not self.api_key:
                missing.append("TWITTER_API_KEY")
            if not self.api_secret:
                missing.append("TWITTER_API_SECRET")
            if not self.access_token:
                missing.append("TWITTER_ACCESS_TOKEN")
            if not self.access_secret:
                missing.append("TWITTER_ACCESS_SECRET")
            logger.warning(
                "Twitter credentials incomplete. Missing: %s. Posts will fail.", ", ".join(missing)
            )

    @property
    def is_configured(self) -> bool:
        """Check if Twitter credentials are configured."""
        return all([self.api_key, self.api_secret, self.access_token, self.access_secret])

    def _generate_oauth_signature(
        self,
        method: str,
        url: str,
        params: dict,
        oauth_params: dict,
    ) -> str:
        """Generate OAuth 1.0a signature."""
        # Combine all parameters
        all_params = {**params, **oauth_params}

        # Sort and encode
        sorted_params = sorted(all_params.items())
        param_string = "&".join(
            f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted_params
        )

        # Create signature base string
        base_string = "&".join(
            [
                method.upper(),
                urllib.parse.quote(url, safe=""),
                urllib.parse.quote(param_string, safe=""),
            ]
        )

        # Create signing key
        signing_key = f"{urllib.parse.quote(self.api_secret, safe='')}&{urllib.parse.quote(self.access_secret, safe='')}"

        # Generate HMAC-SHA1 signature
        signature = hmac.new(
            signing_key.encode(),
            base_string.encode(),
            hashlib.sha1,
        ).digest()

        return base64.b64encode(signature).decode()

    def _generate_oauth_header(
        self,
        method: str,
        url: str,
        params: dict | None = None,
    ) -> str:
        """Generate OAuth 1.0a Authorization header."""
        params = params or {}

        oauth_params = {
            "oauth_consumer_key": self.api_key,
            "oauth_token": self.access_token,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_nonce": hashlib.sha256(os.urandom(32)).hexdigest()[:32],
            "oauth_version": "1.0",
        }

        signature = self._generate_oauth_signature(method, url, params, oauth_params)
        oauth_params["oauth_signature"] = signature

        # Build header
        header_parts = [
            f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
            for k, v in sorted(oauth_params.items())
        ]

        return "OAuth " + ", ".join(header_parts)

    async def post_tweet(
        self,
        text: str,
        reply_to: str | None = None,
        media_ids: list[str] | None = None,
    ) -> TweetResult:
        """
        Post a single tweet.

        Args:
            text: Tweet text (max 280 chars)
            reply_to: Tweet ID to reply to (for threads)
            media_ids: List of uploaded media IDs

        Returns:
            TweetResult with tweet details or error
        """
        if not self.is_configured:
            return TweetResult(
                tweet_id="",
                text=text,
                created_at=datetime.now().isoformat(),
                url="",
                success=False,
                error="Twitter API credentials not configured",
            )

        if not self.circuit_breaker.can_proceed():
            return TweetResult(
                tweet_id="",
                text=text,
                created_at=datetime.now().isoformat(),
                url="",
                success=False,
                error="Circuit breaker open - too many recent failures",
            )

        # Truncate text if needed
        if len(text) > MAX_TWEET_LENGTH:
            text = text[: MAX_TWEET_LENGTH - 3] + "..."

        await self.rate_limiter.acquire()

        try:
            import httpx

            url = f"{self.base_url}/tweets"

            payload: dict = {"text": text}
            if reply_to:
                payload["reply"] = {"in_reply_to_tweet_id": reply_to}
            if media_ids:
                payload["media"] = {"media_ids": media_ids}

            headers = {
                "Authorization": self._generate_oauth_header("POST", url),
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 201:
                    data = response.json()
                    tweet_id = data["data"]["id"]
                    self.circuit_breaker.record_success()

                    # Note: v2 doesn't return username, would need separate lookup
                    tweet_url = f"https://twitter.com/i/status/{tweet_id}"

                    logger.info("Posted tweet: %s", tweet_id)
                    return TweetResult(
                        tweet_id=tweet_id,
                        text=text,
                        created_at=datetime.now().isoformat(),
                        url=tweet_url,
                        success=True,
                    )
                else:
                    error = response.text
                    logger.error("Twitter API error: %s - %s", response.status_code, error)
                    self.circuit_breaker.record_failure()
                    return TweetResult(
                        tweet_id="",
                        text=text,
                        created_at=datetime.now().isoformat(),
                        url="",
                        success=False,
                        error=f"Twitter API error: {response.status_code}",
                    )

        except httpx.TimeoutException as e:
            logger.error("Timeout posting tweet: %s", e)
            self.circuit_breaker.record_failure()
            return TweetResult(
                tweet_id="",
                text=text,
                created_at=datetime.now().isoformat(),
                url="",
                success=False,
                error=f"Request timeout: {e}",
            )
        except httpx.RequestError as e:
            logger.error("Network error posting tweet: %s", e)
            self.circuit_breaker.record_failure()
            return TweetResult(
                tweet_id="",
                text=text,
                created_at=datetime.now().isoformat(),
                url="",
                success=False,
                error=f"Network error: {e}",
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse Twitter response: %s", e)
            self.circuit_breaker.record_failure()
            return TweetResult(
                tweet_id="",
                text=text,
                created_at=datetime.now().isoformat(),
                url="",
                success=False,
                error=f"Response parse error: {e}",
            )

    async def post_thread(self, tweets: list[str]) -> ThreadResult:
        """
        Post a thread (multiple connected tweets).

        Args:
            tweets: List of tweet texts (max 25)

        Returns:
            ThreadResult with all tweet details or error
        """
        if not tweets:
            return ThreadResult(
                thread_id="",
                success=False,
                error="No tweets provided",
            )

        if len(tweets) > MAX_THREAD_LENGTH:
            tweets = tweets[:MAX_THREAD_LENGTH]

        results: list[TweetResult] = []
        reply_to: str | None = None

        for i, text in enumerate(tweets):
            result = await self.post_tweet(text, reply_to=reply_to)
            results.append(result)

            if not result.success:
                return ThreadResult(
                    thread_id=results[0].tweet_id if results else "",
                    tweets=results,
                    success=False,
                    error=f"Failed at tweet {i + 1}: {result.error}",
                )

            reply_to = result.tweet_id

            # Small delay between tweets to avoid rate limiting
            if i < len(tweets) - 1:
                await asyncio.sleep(0.5)

        return ThreadResult(
            thread_id=results[0].tweet_id,
            tweets=results,
            success=True,
        )

    async def upload_media(self, file_path: Path) -> str:
        """
        Upload media file to Twitter.

        Args:
            file_path: Path to image file

        Returns:
            Media ID string

        Raises:
            TwitterAuthError: If credentials not configured
            TwitterMediaError: If file not found, too large, or upload fails
            TwitterAPIError: If API request fails
        """
        if not self.is_configured:
            raise TwitterAuthError("Twitter API credentials not configured")

        if not file_path.exists():
            raise TwitterMediaError(f"Media file not found: {file_path}")

        # Check file size
        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_MEDIA_SIZE_MB:
            raise TwitterMediaError(
                f"Media file too large: {size_mb:.1f}MB (max {MAX_MEDIA_SIZE_MB}MB)"
            )

        await self.rate_limiter.acquire()

        try:
            import httpx

            url = f"{self.upload_url}/media/upload.json"

            # Read file and encode
            media_data = base64.b64encode(file_path.read_bytes()).decode()

            params = {
                "media_data": media_data,
                "media_category": "tweet_image",
            }

            headers = {
                "Authorization": self._generate_oauth_header("POST", url, params),
                "Content-Type": "application/x-www-form-urlencoded",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, data=params, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    media_id = data.get("media_id_string")
                    if not media_id:
                        raise TwitterMediaError("No media_id in response")
                    logger.info("Uploaded media: %s", media_id)
                    return media_id
                elif response.status_code == 429:
                    raise TwitterRateLimitError("Rate limit exceeded for media upload")
                else:
                    raise TwitterAPIError("Media upload failed", status_code=response.status_code)

        except (TwitterAuthError, TwitterMediaError, TwitterAPIError, TwitterRateLimitError):
            raise
        except (OSError, ValueError, RuntimeError, TypeError) as e:
            logger.error("Failed to upload media: %s", e)
            raise TwitterMediaError(f"Failed to upload media: {e}") from e


class DebateContentFormatter:
    """
    Format debate content for Twitter posting.

    Creates single tweets, threads, and announcements
    from debate traces and results.
    """

    MAX_LENGTH = MAX_TWEET_LENGTH
    THREAD_MAX = MAX_THREAD_LENGTH

    def format_announcement(
        self,
        task: str,
        agents: list[str],
        debate_url: str | None = None,
    ) -> str:
        """
        Format a debate announcement tweet.

        Args:
            task: Debate topic
            agents: Participating agents
            debate_url: Optional URL to debate

        Returns:
            Tweet text
        """
        # Format agents
        agent_str = ", ".join(agents[:3])
        if len(agents) > 3:
            agent_str += f" +{len(agents) - 3} more"

        # Build tweet
        parts = [
            f"New AI Debate: {task}",
            f"Participants: {agent_str}",
        ]

        if debate_url:
            parts.append(debate_url)

        tweet = "\n\n".join(parts)

        # Truncate if needed
        if len(tweet) > self.MAX_LENGTH:
            # Shorten task
            available = self.MAX_LENGTH - len(agent_str) - 50
            if available > 20:
                task_short = task[:available] + "..."
                parts[0] = f"New AI Debate: {task_short}"
                tweet = "\n\n".join(parts)

        return tweet[: self.MAX_LENGTH]

    def format_result(
        self,
        task: str,
        agents: list[str],
        consensus_reached: bool,
        winner: str | None = None,
        debate_url: str | None = None,
        audio_url: str | None = None,
    ) -> str:
        """
        Format a debate result tweet.

        Args:
            task: Debate topic
            agents: Participating agents
            consensus_reached: Whether consensus was reached
            winner: Optional winning agent
            debate_url: URL to debate results
            audio_url: URL to podcast audio

        Returns:
            Tweet text
        """
        if consensus_reached:
            result_emoji = "Consensus reached!"
        elif winner:
            result_emoji = f"Winner: {winner}"
        else:
            result_emoji = "No consensus"

        parts = [
            f"Debate Complete: {task[:80]}{'...' if len(task) > 80 else ''}",
            result_emoji,
        ]

        if audio_url:
            parts.append(f"Listen: {audio_url}")
        elif debate_url:
            parts.append(debate_url)

        tweet = "\n\n".join(parts)
        return tweet[: self.MAX_LENGTH]

    def format_thread(
        self,
        task: str,
        agents: list[str],
        highlights: list[str],
        consensus_reached: bool,
        debate_url: str | None = None,
    ) -> list[str]:
        """
        Format a debate as a thread of tweets.

        Args:
            task: Debate topic
            agents: Participating agents
            highlights: Key moments/quotes from debate
            consensus_reached: Whether consensus was reached
            debate_url: URL to full debate

        Returns:
            List of tweet texts
        """
        tweets = []

        # First tweet: Introduction
        intro = self.format_announcement(task, agents)
        tweets.append(intro)

        # Middle tweets: Highlights
        for i, highlight in enumerate(highlights[: self.THREAD_MAX - 2]):
            # Truncate highlight if needed
            if len(highlight) > self.MAX_LENGTH - 10:
                highlight = highlight[: self.MAX_LENGTH - 13] + "..."
            tweets.append(f"{i + 1}. {highlight}")

        # Final tweet: Result
        result_text = (
            "Consensus reached!" if consensus_reached else "No consensus - debate continues..."
        )
        if debate_url:
            result_text += f"\n\nFull debate: {debate_url}"
        tweets.append(result_text)

        return tweets[: self.THREAD_MAX]


def create_debate_summary(
    task: str,
    agents: list[str],
    consensus_reached: bool = False,
    max_length: int = 280,
) -> str:
    """
    Create a short summary suitable for Twitter.

    Args:
        task: Debate topic
        agents: Participating agents
        consensus_reached: Whether consensus was reached
        max_length: Maximum character length

    Returns:
        Summary string within max_length
    """
    formatter = DebateContentFormatter()
    return formatter.format_result(
        task=task,
        agents=agents,
        consensus_reached=consensus_reached,
    )[:max_length]
