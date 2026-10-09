"""
Social Media endpoint handlers for Twitter and YouTube.

Endpoints:
- GET /api/youtube/auth - Get YouTube OAuth authorization URL
- GET /api/youtube/callback - Handle YouTube OAuth callback
- GET /api/youtube/status - Get YouTube connector status
- POST /api/debates/{id}/publish/twitter - Publish debate to Twitter/X
- POST /api/debates/{id}/publish/youtube - Publish debate to YouTube
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Any, Protocol, cast
from collections.abc import Awaitable
from pathlib import Path

from aragora.config.secrets import get_secret
from aragora.rbac.decorators import require_permission
from aragora.api_errors import safe_error_message as _safe_error_message
from aragora.server.http_utils import run_async

from ..base import (
    SAFE_SLUG_PATTERN,
    BaseHandler,
    HandlerResult,
    error_response,
    get_host_header,
    json_response,
    handle_errors,
)

if TYPE_CHECKING:
    from aragora.connectors.youtube_uploader import YouTubeVideoMetadata

# =============================================================================
# Protocol Types for External Dependencies
# =============================================================================


class YouTubeRateLimiterProtocol(Protocol):
    """Protocol for YouTube rate limiter interface."""

    @property
    def remaining_quota(self) -> int:
        """Get remaining quota units."""
        ...

    def can_upload(self) -> bool:
        """Check if we have quota for an upload."""
        ...


class CircuitBreakerProtocol(Protocol):
    """Protocol for circuit breaker interface."""

    @property
    def is_open(self) -> bool:
        """Check if the circuit breaker is open."""
        ...

    def can_proceed(self) -> bool:
        """Check if operation can proceed."""
        ...


class YouTubeConnectorProtocol(Protocol):
    """Protocol for YouTube connector interface used by social media handler."""

    client_id: str
    client_secret: str
    refresh_token: str
    rate_limiter: YouTubeRateLimiterProtocol
    circuit_breaker: CircuitBreakerProtocol

    @property
    def is_configured(self) -> bool:
        """Check if YouTube credentials are configured."""
        ...

    def get_auth_url(self, redirect_uri: str, state: str = "") -> str:
        """Get OAuth authorization URL for user consent."""
        ...

    def exchange_code(self, code: str, redirect_uri: str) -> Awaitable[dict[str, Any]]:
        """Exchange authorization code for tokens."""
        ...

    def upload(self, video_path: Path, metadata: YouTubeVideoMetadata) -> Awaitable[dict[str, Any]]:
        """Upload a video to YouTube."""
        ...


class TwitterConnectorProtocol(Protocol):
    """Protocol for Twitter connector interface used by social media handler."""

    @property
    def is_configured(self) -> bool:
        """Check if Twitter credentials are configured."""
        ...

    def post_tweet(self, text: str) -> Awaitable[dict[str, Any]]:
        """Post a single tweet."""
        ...

    def post_thread(self, tweets: list[str]) -> Awaitable[dict[str, Any]]:
        """Post a thread (multiple connected tweets)."""
        ...


class AudioStoreProtocol(Protocol):
    """Protocol for audio store interface used by social media handler."""

    def exists(self, debate_id: str) -> bool:
        """Check if audio exists for a debate."""
        ...

    def get_path(self, debate_id: str) -> Path | None:
        """Get the path to an audio file."""
        ...


class VideoGeneratorProtocol(Protocol):
    """Protocol for video generator interface used by social media handler."""

    def generate_waveform_video(
        self, audio_path: Path, output_path: Path | None = None
    ) -> Awaitable[Path | None]:
        """Generate video with animated audio waveform."""
        ...

    def generate_static_video(
        self,
        audio_path: Path,
        title: str,
        agents: list[str],
        output_path: Path | None = None,
    ) -> Awaitable[Path | None]:
        """Generate video with static thumbnail and audio track."""
        ...


class DebateContentFormatterProtocol(Protocol):
    """Protocol for debate content formatter interface used by social media handler."""

    def format_as_thread(
        self,
        task: str,
        agents: list[str],
        verdict: str | None,
        debate_url: str,
    ) -> list[str]:
        """Format debate as a thread of tweets."""
        ...

    def format_single_tweet(
        self,
        task: str,
        agents: list[str],
        verdict: str | None,
        audio_url: str | None,
        debate_url: str | None,
    ) -> str:
        """Format debate as a single tweet."""
        ...


logger = logging.getLogger(__name__)


def _is_production_mode() -> bool:
    env = get_secret("ARAGORA_ENV", os.environ.get("ARAGORA_ENV", ""), strict=False) or ""
    return env.lower() == "production"


def _load_allowed_oauth_hosts() -> frozenset[str]:
    hosts = get_secret(
        "ARAGORA_ALLOWED_OAUTH_HOSTS",
        os.getenv("ARAGORA_ALLOWED_OAUTH_HOSTS"),
        strict=False,
    )
    if hosts:
        return frozenset(h.strip() for h in hosts.split(",") if h.strip())
    if _is_production_mode():
        logger.warning(
            "[Social] ARAGORA_ALLOWED_OAUTH_HOSTS not set in production! "
            "OAuth redirects may fail. Set this to your domain(s)."
        )
        return frozenset()
    logger.debug("[Social] Using localhost for OAuth hosts (dev mode)")
    return frozenset(["localhost:8080", "127.0.0.1:8080"])


_IS_PRODUCTION = _is_production_mode()

# OAuth state storage for CSRF protection (with TTL cleanup)
_oauth_states: dict[str, float] = {}  # state -> expiry_time
_oauth_states_lock = threading.Lock()
_OAUTH_STATE_TTL = 600  # 10 minutes
MAX_OAUTH_STATES = 5000  # Prevent memory exhaustion from rapid state generation

ALLOWED_OAUTH_HOSTS = _load_allowed_oauth_hosts()


def _store_oauth_state(state: str) -> None:
    """Store OAuth state for later validation."""
    with _oauth_states_lock:
        # Cleanup expired states
        now = time.time()
        expired = [s for s, exp in _oauth_states.items() if exp < now]
        for s in expired:
            del _oauth_states[s]

        # Enforce max size - remove oldest entries if at capacity
        if len(_oauth_states) >= MAX_OAUTH_STATES:
            sorted_states = sorted(_oauth_states.items(), key=lambda x: x[1])
            remove_count = max(1, len(sorted_states) // 10)
            for s, _ in sorted_states[:remove_count]:
                del _oauth_states[s]

        # Store new state
        _oauth_states[state] = now + _OAUTH_STATE_TTL


def _validate_oauth_state(state: str) -> bool:
    """Validate and consume OAuth state (one-time use)."""
    with _oauth_states_lock:
        if state in _oauth_states:
            expiry = _oauth_states.pop(state)
            return time.time() < expiry
        return False


def _run_async(coro: Any) -> Any:
    """Run async coroutine in sync context."""
    return run_async(coro)


class SocialMediaHandler(BaseHandler):
    """Handler for social media publishing (Twitter, YouTube) endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/youtube/auth",
        "/api/v1/youtube/callback",
        "/api/v1/youtube/status",
        "/api/v1/debates/*/publish/twitter",
        "/api/v1/debates/*/publish/youtube",
    ]

    # === Typed Accessor Methods ===

    def _get_youtube_connector(self) -> YouTubeConnectorProtocol | None:
        """Get the YouTube connector with proper typing."""
        connector = self.ctx.get("youtube_connector")
        if connector is None:
            return None
        return cast(YouTubeConnectorProtocol, connector)

    def _get_twitter_connector(self) -> TwitterConnectorProtocol | None:
        """Get the Twitter connector with proper typing."""
        connector = self.ctx.get("twitter_connector")
        if connector is None:
            return None
        return cast(TwitterConnectorProtocol, connector)

    def _get_audio_store(self) -> AudioStoreProtocol | None:
        """Get the audio store with proper typing."""
        store = self.ctx.get("audio_store")
        if store is None:
            return None
        return cast(AudioStoreProtocol, store)

    def _get_video_generator(self) -> VideoGeneratorProtocol | None:
        """Get the video generator with proper typing."""
        generator = self.ctx.get("video_generator")
        if generator is None:
            return None
        return cast(VideoGeneratorProtocol, generator)

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the request."""
        if path.startswith("/api/v1/youtube/"):
            return True
        if path.startswith("/api/v1/debates/") and "/publish/" in path:
            return True
        return False

    @require_permission("social:read")
    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any = None,
        method: str = "GET",
    ) -> HandlerResult | None:
        """Handle GET requests."""
        if hasattr(handler, "command"):
            method = handler.command

        if method != "GET":
            return None

        # YouTube OAuth endpoints
        if path == "/api/v1/youtube/auth":
            return self._get_youtube_auth_url(handler)
        if path == "/api/v1/youtube/callback":
            code = query_params.get("code")
            state = query_params.get("state")
            return self._handle_youtube_callback(code, state, handler)
        if path == "/api/v1/youtube/status":
            return self._get_youtube_status()

        return None

    @handle_errors("social media creation")
    @require_permission("social:create")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        # Twitter publishing
        if path.startswith("/api/v1/debates/") and path.endswith("/publish/twitter"):
            debate_id, err = self.extract_path_param(path, 4, "debate_id", SAFE_SLUG_PATTERN)
            if err or debate_id is None:
                return err
            return self._publish_to_twitter(debate_id, handler)

        # YouTube publishing
        if path.startswith("/api/v1/debates/") and path.endswith("/publish/youtube"):
            debate_id, err = self.extract_path_param(path, 4, "debate_id", SAFE_SLUG_PATTERN)
            if err or debate_id is None:
                return err
            return self._publish_to_youtube(debate_id, handler)

        return None

    # === YouTube OAuth Endpoints ===

    def _get_youtube_auth_url(self, handler: Any) -> HandlerResult:
        """Get YouTube OAuth authorization URL."""
        youtube = self._get_youtube_connector()
        if not youtube:
            return error_response("YouTube connector not initialized", status=500)

        if not youtube.client_id:
            return json_response(
                {
                    "error": "YouTube client ID not configured",
                    "hint": "Set YOUTUBE_CLIENT_ID environment variable",
                },
                status=400,
            )

        # Validate Host header against whitelist (prevent open redirect)
        host = get_host_header(handler)
        if host not in ALLOWED_OAUTH_HOSTS:
            logger.warning("OAuth auth request with untrusted host: %s", host)
            return error_response("Untrusted host for OAuth redirect", status=400)

        scheme = (
            "https" if handler and handler.headers.get("X-Forwarded-Proto") == "https" else "http"
        )
        redirect_uri = f"{scheme}://{host}/api/youtube/callback"

        import secrets

        state = secrets.token_urlsafe(32)

        # Store state for CSRF validation in callback
        _store_oauth_state(state)

        auth_url = youtube.get_auth_url(redirect_uri, state)
        return json_response(
            {
                "auth_url": auth_url,
                "state": state,
            }
        )

    def _handle_youtube_callback(
        self, code: str | None, state: str | None, handler: Any
    ) -> HandlerResult:
        """Handle YouTube OAuth callback."""
        if not code:
            return error_response("Missing authorization code", status=400)
        if not state:
            return error_response("Missing state parameter", status=400)

        # Validate state parameter (CSRF protection)
        if not _validate_oauth_state(state):
            logger.warning("OAuth callback with invalid/expired state")
            return error_response("Invalid or expired state parameter", status=400)

        youtube = self._get_youtube_connector()
        if not youtube:
            return error_response("YouTube connector not initialized", status=500)

        # Validate Host header against whitelist (prevent open redirect)
        host = get_host_header(handler)
        if host not in ALLOWED_OAUTH_HOSTS:
            logger.warning("OAuth callback with untrusted host: %s", host)
            return error_response("Untrusted host for OAuth redirect", status=400)

        scheme = (
            "https" if handler and handler.headers.get("X-Forwarded-Proto") == "https" else "http"
        )
        redirect_uri = f"{scheme}://{host}/api/youtube/callback"

        try:
            result = _run_async(youtube.exchange_code(code, redirect_uri))

            if result.get("success"):
                return json_response(
                    {
                        "success": True,
                        "message": "YouTube authentication successful",
                    }
                )
            else:
                return json_response(
                    {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                    status=400,
                )

        except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError, KeyError) as e:
            logger.error("YouTube OAuth callback failed: %s", e)
            return error_response(_safe_error_message(e, "youtube_callback"), status=500)

    def _get_youtube_status(self) -> HandlerResult:
        """Get YouTube connector status."""
        youtube = self._get_youtube_connector()
        if not youtube:
            return json_response(
                {
                    "configured": False,
                    "error": "YouTube connector not initialized",
                }
            )

        return json_response(
            {
                "configured": youtube.is_configured,
                "has_client_id": bool(youtube.client_id),
                "has_client_secret": bool(youtube.client_secret),
                "has_refresh_token": bool(youtube.refresh_token),
                "quota_remaining": youtube.rate_limiter.remaining_quota,
                "circuit_breaker_open": youtube.circuit_breaker.is_open,
            }
        )

    # === Social Publishing Endpoints ===

    def _publish_to_twitter(self, debate_id: str, handler: Any) -> HandlerResult:
        """Publish debate to Twitter/X."""
        twitter = self._get_twitter_connector()
        if not twitter:
            return error_response("Twitter connector not initialized", status=500)

        if not twitter.is_configured:
            return json_response(
                {
                    "error": "Twitter API credentials not configured",
                    "hint": "Set TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET",
                },
                status=400,
            )

        storage = self.get_storage()
        if not storage:
            return error_response("Storage not available", status=503)

        debate = storage.get_debate(debate_id)
        if not debate:
            debate = storage.get_debate_by_slug(debate_id)
        if not debate:
            return error_response("Debate not found", status=404)

        # Read POST body for options
        body = self.read_json_body(handler) if handler else {}
        if body is None:
            return error_response("Invalid JSON body", status=400)

        options = body or {}
        include_audio = options.get("include_audio_link", True)
        thread_mode = options.get("thread_mode", False)

        host = get_host_header(handler)
        scheme = (
            "https" if handler and handler.headers.get("X-Forwarded-Proto") == "https" else "http"
        )
        debate_url = f"{scheme}://{host}/debates/{debate_id}"

        audio_store = self._get_audio_store()
        audio_url = None
        if include_audio and audio_store and audio_store.exists(debate_id):
            audio_url = f"{scheme}://{host}/audio/{debate_id}.mp3"

        try:
            from aragora.connectors.twitter_poster import DebateContentFormatter

            formatter = cast(DebateContentFormatterProtocol, DebateContentFormatter())

            if thread_mode:
                tweets = formatter.format_as_thread(
                    task=debate.get("task", ""),
                    agents=debate.get("agents", []),
                    verdict=debate.get("verdict"),
                    debate_url=audio_url or debate_url,
                )
                result = _run_async(twitter.post_thread(tweets))
            else:
                tweet_text = formatter.format_single_tweet(
                    task=debate.get("task", ""),
                    agents=debate.get("agents", []),
                    verdict=debate.get("verdict"),
                    audio_url=audio_url,
                    debate_url=debate_url if not audio_url else None,
                )
                result = _run_async(twitter.post_tweet(tweet_text))

            if result.get("success"):
                return json_response(
                    {
                        "success": True,
                        "debate_id": debate_id,
                        "tweet_id": result.get("tweet_id"),
                        "thread_ids": result.get("thread_ids"),
                        "url": result.get("url"),
                    }
                )
            else:
                return json_response(
                    {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                    status=500,
                )

        except (
            ImportError,
            OSError,
            ConnectionError,
            TimeoutError,
            ValueError,
            RuntimeError,
            KeyError,
        ) as e:
            logger.error("Failed to publish to Twitter: %s", e)
            return error_response(_safe_error_message(e, "twitter_publish"), status=500)

    def _publish_to_youtube(self, debate_id: str, handler: Any) -> HandlerResult:
        """Publish debate to YouTube."""
        youtube = self._get_youtube_connector()
        if not youtube:
            return error_response("YouTube connector not initialized", status=500)

        if not youtube.is_configured:
            return json_response(
                {
                    "error": "YouTube API credentials not configured",
                    "hint": "Set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN",
                },
                status=400,
            )

        storage = self.get_storage()
        if not storage:
            return error_response("Storage not available", status=503)

        debate = storage.get_debate(debate_id)
        if not debate:
            debate = storage.get_debate_by_slug(debate_id)
        if not debate:
            return error_response("Debate not found", status=404)

        # Check quota
        if not youtube.rate_limiter.can_upload():
            return json_response(
                {
                    "error": "YouTube daily quota exceeded",
                    "quota_remaining": youtube.rate_limiter.remaining_quota,
                },
                status=429,
            )

        audio_store = self._get_audio_store()
        if not audio_store or not audio_store.exists(debate_id):
            return json_response(
                {
                    "error": "No audio found for this debate",
                    "hint": "Generate audio first using POST /api/debates/{id}/broadcast",
                },
                status=400,
            )

        # Read POST body for options
        body = self.read_json_body(handler) if handler else {}
        if body is None:
            return error_response("Invalid JSON body", status=400)

        options = body or {}
        custom_title = options.get("title")
        custom_description = options.get("description")
        tags = options.get("tags", [])
        privacy = options.get("privacy", "public")

        task = debate.get("task", "AI Debate")
        agents = debate.get("agents", [])

        audio_path = audio_store.get_path(debate_id)
        if not audio_path:
            return error_response("Audio file not found", status=404)

        try:
            video_generator = self._get_video_generator()
            if video_generator:
                try:
                    video_path = _run_async(video_generator.generate_waveform_video(audio_path))
                except Exception as e:  # noqa: BLE001 - graceful degradation, fall back to static video
                    logger.debug("Waveform video generation failed, using static fallback: %s", e)
                    video_path = _run_async(
                        video_generator.generate_static_video(audio_path, task, agents)
                    )
            else:
                return error_response("Video generator not available", status=503)

            from aragora.connectors.youtube_uploader import YouTubeVideoMetadata

            metadata = YouTubeVideoMetadata(
                title=custom_title or f"AI Debate: {task[:80]}",
                description=custom_description
                or f"Multi-agent AI debate on: {task}\n\nAgents: {', '.join(agents)}",
                tags=tags or ["AI", "debate", "agents", "artificial intelligence"],
                privacy_status=privacy,
            )

            if video_path is None:
                return error_response("Video generation failed", status=500)

            logger.info("Uploading video to YouTube: %s", metadata.title)
            result = _run_async(youtube.upload(video_path, metadata))

            if result.get("success"):
                return json_response(
                    {
                        "success": True,
                        "debate_id": debate_id,
                        "video_id": result.get("video_id"),
                        "url": result.get("url"),
                        "quota_remaining": youtube.rate_limiter.remaining_quota,
                    }
                )
            else:
                return json_response(
                    {
                        "success": False,
                        "error": result.get("error", "Upload failed"),
                    },
                    status=500,
                )

        except (
            ImportError,
            OSError,
            ConnectionError,
            TimeoutError,
            ValueError,
            RuntimeError,
            KeyError,
        ) as e:
            logger.error("Failed to publish to YouTube: %s", e)
            return error_response(_safe_error_message(e, "youtube_publish"), status=500)
