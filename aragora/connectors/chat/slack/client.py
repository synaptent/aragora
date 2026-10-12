"""
Slack API client, token management, and resilience utilities.

Contains the low-level API request infrastructure, circuit breaker integration,
rate limiting, token refresh, and webhook verification logic.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import random
import time as _time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aragora.connectors.exceptions import (
    ConnectorAPIError,
    ConnectorAuthError,
    ConnectorNetworkError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None


try:
    from aragora.observability.tracing import build_trace_headers
except ImportError:

    def build_trace_headers() -> dict[str, str]:
        return {}


# Environment configuration
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# Slack API
SLACK_API_BASE = "https://slack.com/api"

# Resilience configuration
DEFAULT_TIMEOUT = 30.0  # seconds
DEFAULT_RETRIES = 3
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_COOLDOWN = 60.0  # seconds


def _is_retryable_error(status_code: int, error: str | None = None) -> bool:
    """Check if an error is retryable (transient)."""
    # Rate limited
    if status_code == 429:
        return True
    # Server errors
    if 500 <= status_code < 600:
        return True
    # Slack-specific retryable errors
    retryable_errors = {"service_unavailable", "timeout", "internal_error", "fatal_error"}
    if error and error.lower() in retryable_errors:
        return True
    return False


def _classify_slack_error(
    error: str,
    status_code: int | None = None,
    retry_after: float | None = None,
) -> Exception:
    """Classify Slack API errors into connector exception types."""
    error_lower = (error or "").lower()

    if status_code == 429 or "rate" in error_lower or "ratelimited" in error_lower:
        return ConnectorRateLimitError(
            error or "rate_limited",
            connector_name="slack",
            retry_after=retry_after,
        )

    auth_errors = {
        "invalid_auth",
        "token_expired",
        "token_revoked",
        "not_authed",
        "account_inactive",
    }
    if error_lower in auth_errors:
        return ConnectorAuthError(error or "auth_error", connector_name="slack")

    if "timeout" in error_lower:
        return ConnectorTimeoutError(error or "timeout", connector_name="slack")

    if "connection" in error_lower or "network" in error_lower:
        return ConnectorNetworkError(error or "network_error", connector_name="slack")

    if status_code is not None:
        return ConnectorAPIError(
            error or "api_error", connector_name="slack", status_code=status_code
        )

    return ConnectorAPIError(error or "api_error", connector_name="slack")


async def _exponential_backoff(attempt: int, base: float = 1.0, max_delay: float = 30.0) -> None:
    """Sleep with exponential backoff and jitter."""
    # Jitter scales with base to keep early attempts short.
    delay = min(base * (2**attempt) + random.uniform(0, base), max_delay)
    await asyncio.sleep(delay)


async def _wait_for_rate_limit(
    response: Any, attempt: int, base: float = 1.0, max_delay: float = 60.0
) -> None:
    """Wait according to Slack's rate limit guidance.

    Respects the Retry-After header if present, otherwise falls back to exponential backoff.

    Args:
        response: The HTTP response from Slack
        attempt: Current retry attempt number
        base: Base delay for exponential backoff
        max_delay: Maximum delay in seconds
    """
    retry_after = response.headers.get("Retry-After")

    if retry_after:
        try:
            # Slack sends Retry-After in seconds
            delay = min(int(retry_after), max_delay)
            logger.info("Rate limited by Slack, waiting %ss (Retry-After header)", delay)
            await asyncio.sleep(delay)
            return
        except (ValueError, TypeError):
            pass  # Fall through to exponential backoff

    # Fallback to exponential backoff
    await _exponential_backoff(attempt, base, max_delay)


@dataclass
class WorkspaceRateLimit:
    """
    Per-workspace rate limit tracking for Slack API.

    Tracks the rate limit status for a specific workspace to enable
    intelligent request scheduling and quota pooling.
    """

    workspace_id: str
    limit: int = 50  # Default Slack rate limit
    remaining: int = 50
    reset_at: float = 0.0  # Unix timestamp
    last_updated: float = field(default_factory=_time.time)

    def update_from_headers(self, headers: dict) -> None:
        """Update rate limit state from Slack API response headers."""
        if "X-Rate-Limit-Limit" in headers:
            self.limit = int(headers["X-Rate-Limit-Limit"])
        if "X-Rate-Limit-Remaining" in headers:
            self.remaining = int(headers["X-Rate-Limit-Remaining"])
        if "X-Rate-Limit-Reset" in headers:
            self.reset_at = float(headers["X-Rate-Limit-Reset"])
        self.last_updated = _time.time()

    @property
    def is_rate_limited(self) -> bool:
        """Check if we're currently rate limited."""
        if self.remaining <= 0 and _time.time() < self.reset_at:
            return True
        return False

    @property
    def seconds_until_reset(self) -> float:
        """Get seconds until rate limit resets."""
        if self.reset_at <= 0:
            return 0.0
        return max(0.0, self.reset_at - _time.time())

    def to_dict(self) -> dict:
        """Convert to dictionary for monitoring/logging."""
        return {
            "workspace_id": self.workspace_id,
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
            "is_rate_limited": self.is_rate_limited,
            "seconds_until_reset": self.seconds_until_reset,
        }


class WorkspaceRateLimitRegistry:
    """
    Registry for tracking rate limits across multiple workspaces.

    Enables intelligent request distribution and quota pooling
    in multi-workspace deployments.
    """

    def __init__(self) -> None:
        self._limits: dict[str, WorkspaceRateLimit] = {}

    def get(self, workspace_id: str) -> WorkspaceRateLimit:
        """Get or create rate limit tracker for a workspace."""
        if workspace_id not in self._limits:
            self._limits[workspace_id] = WorkspaceRateLimit(workspace_id=workspace_id)
        return self._limits[workspace_id]

    def update(self, workspace_id: str, headers: dict) -> WorkspaceRateLimit:
        """Update rate limit from API response headers."""
        limit = self.get(workspace_id)
        limit.update_from_headers(headers)
        return limit

    def get_best_workspace(self, workspace_ids: list[str]) -> str | None:
        """
        Select the workspace with most remaining quota.

        Useful for load balancing across multiple workspaces.
        """
        if not workspace_ids:
            return None

        best_id = None
        best_remaining = -1

        for wid in workspace_ids:
            limit = self.get(wid)
            if not limit.is_rate_limited and limit.remaining > best_remaining:
                best_id = wid
                best_remaining = limit.remaining

        return best_id

    def get_all_stats(self) -> dict[str, dict]:
        """Get rate limit stats for all tracked workspaces."""
        return {wid: limit.to_dict() for wid, limit in self._limits.items()}


# Global registry for rate limit tracking
_rate_limit_registry = WorkspaceRateLimitRegistry()


def get_rate_limit_registry() -> WorkspaceRateLimitRegistry:
    """Get the global rate limit registry."""
    return _rate_limit_registry
