"""
Slack messaging utilities.

Response helpers and async message posting for Slack Web API and response URLs.

Includes circuit breaker pattern for resilience when Slack APIs are degraded.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from aragora.rbac.decorators import require_permission

from .config import (
    HandlerResult,
    SLACK_BOT_TOKEN,
    _validate_slack_url,
    json_response,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Circuit Breaker for Slack API
# =============================================================================

from aragora.resilience.simple_circuit_breaker import SimpleCircuitBreaker as SlackCircuitBreaker

# Global circuit breaker instance for Slack API calls
_slack_circuit_breaker: SlackCircuitBreaker | None = None
_circuit_breaker_lock = threading.Lock()


def get_slack_circuit_breaker() -> SlackCircuitBreaker:
    """Get or create the Slack circuit breaker singleton."""
    global _slack_circuit_breaker
    with _circuit_breaker_lock:
        if _slack_circuit_breaker is None:
            _slack_circuit_breaker = SlackCircuitBreaker("slack", half_open_max_calls=2)
        return _slack_circuit_breaker


def reset_slack_circuit_breaker() -> None:
    """Reset the circuit breaker (for testing)."""
    global _slack_circuit_breaker
    with _circuit_breaker_lock:
        if _slack_circuit_breaker is not None:
            _slack_circuit_breaker.reset()


class MessagingMixin:
    """Mixin providing Slack message posting and response formatting."""

    def _slack_response(
        self,
        text: str,
        response_type: str = "ephemeral",
    ) -> HandlerResult:
        """Create a simple Slack response."""
        return json_response(
            {
                "response_type": response_type,
                "text": text,
            }
        )

    def _slack_blocks_response(
        self,
        blocks: list[dict[str, Any]],
        text: str,
        response_type: str = "ephemeral",
    ) -> HandlerResult:
        """Create a Slack response with blocks."""
        return json_response(
            {
                "response_type": response_type,
                "text": text,
                "blocks": blocks,
            }
        )

    # Auth context flows from the parent event/command handler that invokes this method.
    @require_permission("slack:write")
    async def _post_to_response_url(self, url: str, payload: dict[str, Any]) -> None:
        """POST a message to Slack's response_url.

        Includes:
        - SSRF protection by validating the URL is a Slack endpoint
        - Circuit breaker pattern for resilience
        """
        # Validate URL to prevent SSRF attacks
        if not _validate_slack_url(url):
            logger.warning("Invalid Slack response_url blocked (SSRF protection): %s", url[:50])
            return

        # Check circuit breaker before making the call
        circuit_breaker = get_slack_circuit_breaker()
        if not circuit_breaker.can_proceed():
            logger.warning("Slack circuit breaker OPEN - skipping response_url POST")
            return

        from aragora.server.http_client_pool import get_http_pool

        try:
            pool = get_http_pool()
            async with pool.get_session("slack") as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )
                if response.status_code != 200:
                    text = response.text
                    logger.warning(
                        "Slack response_url POST failed: %s - %s", response.status_code, text[:100]
                    )
                    # Record failure for non-2xx responses
                    if response.status_code >= 500:
                        circuit_breaker.record_failure()
                else:
                    circuit_breaker.record_success()
        except (ConnectionError, TimeoutError) as e:
            logger.warning("Connection error posting to Slack response_url: %s", e)
            circuit_breaker.record_failure()
        except (RuntimeError, ValueError, TypeError, OSError) as e:
            logger.exception("Unexpected error posting to Slack response_url: %s", e)
            circuit_breaker.record_failure()

    # Auth context flows from the parent event/command handler that invokes this method.
    @require_permission("slack:write")
    async def _post_message_async(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """Post a message to Slack using the Web API.

        Includes circuit breaker pattern for resilience when Slack APIs are degraded.

        Args:
            channel: Channel ID to post to
            text: Message text
            thread_ts: Optional thread timestamp to reply to
            blocks: Optional Block Kit blocks for rich formatting

        Returns:
            Message timestamp (ts) if successful, None otherwise
        """
        from aragora.server.http_client_pool import get_http_pool

        if not SLACK_BOT_TOKEN:
            logger.warning("Cannot post message: SLACK_BOT_TOKEN not configured")
            return None

        # Check circuit breaker before making the call
        circuit_breaker = get_slack_circuit_breaker()
        if not circuit_breaker.can_proceed():
            logger.warning("Slack circuit breaker OPEN - skipping Web API POST")
            return None

        try:
            payload: dict[str, Any] = {
                "channel": channel,
                "text": text,
            }
            if thread_ts:
                payload["thread_ts"] = thread_ts
            if blocks:
                payload["blocks"] = blocks

            pool = get_http_pool()
            async with pool.get_session("slack") as client:
                response = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    timeout=30,
                )
                result = response.json()
                if not result.get("ok"):
                    error = result.get("error", "unknown")
                    logger.warning("Slack API error: %s", error)
                    # Some errors indicate Slack issues (rate_limited, service_unavailable)
                    if error in ("rate_limited", "service_unavailable", "fatal_error"):
                        circuit_breaker.record_failure()
                    return None
                # Success - record for circuit breaker
                circuit_breaker.record_success()
                # Return message timestamp for thread tracking
                return result.get("ts")
        except (ConnectionError, TimeoutError) as e:
            logger.warning("Connection error posting Slack message: %s", e)
            circuit_breaker.record_failure()
            return None
        except (RuntimeError, ValueError, TypeError, OSError) as e:
            logger.exception("Unexpected error posting Slack message: %s", e)
            circuit_breaker.record_failure()
            return None

    def get_circuit_breaker_status(self) -> dict[str, Any]:
        """Get the Slack circuit breaker status for monitoring."""
        return get_slack_circuit_breaker().get_status()
