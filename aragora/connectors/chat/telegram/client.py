"""
Telegram Bot Connector - Core Client.

Contains the TelegramConnector base class and API request handling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any

logger = logging.getLogger(__name__)

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from aragora.connectors.exceptions import (
    ConnectorError,
    classify_connector_error,
)

# Distributed tracing support
try:
    from aragora.observability.tracing import build_trace_headers

    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False

    def build_trace_headers() -> dict[str, str]:
        return {}


from ..base import ChatPlatformConnector

# Environment configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_URL = os.environ.get("TELEGRAM_WEBHOOK_URL", "")

# Telegram API
TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def _classify_telegram_error(
    error_str: str,
    error_code: int | None = None,
) -> ConnectorError:
    """Classify a Telegram API error into a typed ConnectorError."""
    return classify_connector_error(
        error_str,
        connector_name="telegram",
        status_code=error_code,
    )


class TelegramConnectorBase(ChatPlatformConnector):
    """
    Base Telegram connector with API request handling.

    Supports:
    - Sending messages with Markdown/HTML formatting
    - Inline keyboards (buttons)
    - File uploads (documents, photos, voice)
    - Reply messages (threads)
    - Callback queries (button interactions)
    - Webhook and long-polling

    All HTTP operations include circuit breaker protection for fault tolerance.
    """

    def __init__(
        self,
        bot_token: str | None = None,
        webhook_url: str | None = None,
        parse_mode: str = "MarkdownV2",
        **config: Any,
    ):
        """
        Initialize Telegram connector.

        Args:
            bot_token: Bot API token from @BotFather
            webhook_url: Webhook URL for receiving updates
            parse_mode: Default parse mode (Markdown, MarkdownV2, HTML)
            **config: Additional configuration
        """
        super().__init__(
            bot_token=bot_token or TELEGRAM_BOT_TOKEN,
            webhook_url=webhook_url or TELEGRAM_WEBHOOK_URL,
            **config,
        )
        self.parse_mode = parse_mode
        self._api_base = f"{TELEGRAM_API_BASE}{self.bot_token}"

    @property
    def platform_name(self) -> str:
        return "telegram"

    @property
    def platform_display_name(self) -> str:
        return "Telegram"

    async def _telegram_api_request(
        self,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        operation: str = "api_call",
        *,
        method: str = "POST",
        files: dict[str, Any] | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
    ) -> tuple[bool, dict[str, Any] | None, str | None]:
        """
        Make a Telegram API request with circuit breaker, retry, and timeout.

        Centralizes the resilience pattern for all Telegram API calls.

        Args:
            endpoint: API endpoint (e.g., "sendMessage", "getMe")
            payload: JSON payload to send
            operation: Operation name for logging
            method: HTTP method - "GET" or "POST" (default: "POST")
            files: File data for multipart uploads
            timeout: Optional timeout override
            max_retries: Maximum retry attempts

        Returns:
            Tuple of (success, response_data, error_message)
        """
        # Expose/patch this behavior via the package-level constant for tests.
        from aragora.connectors.chat.telegram import HTTPX_AVAILABLE as PKG_HTTPX_AVAILABLE

        if not PKG_HTTPX_AVAILABLE:
            return False, None, "httpx not available"

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            return False, None, cb_error

        last_error: str | None = None
        url = f"{self._api_base}/{endpoint}"
        request_timeout = timeout if timeout is not None else self._request_timeout

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=request_timeout) as client:
                    if files:
                        # Multipart form data for file uploads
                        response = await client.post(
                            url,
                            data=payload,
                            files=files,
                            headers=build_trace_headers(),
                        )
                    elif method.upper() == "GET":
                        response = await client.get(
                            url,
                            params=payload,
                            headers=build_trace_headers(),
                        )
                    else:
                        response = await client.post(
                            url,
                            json=payload,
                            headers=build_trace_headers(),
                        )

                    data = response.json()

                    # Check for rate limit (429)
                    if data.get("error_code") == 429:
                        retry_after = data.get("parameters", {}).get("retry_after", 60)
                        error_desc = data.get("description", "Rate limit exceeded")
                        last_error = error_desc

                        if attempt < max_retries - 1:
                            logger.warning(
                                "[telegram] %s rate limited, retry in %ss (attempt %s/%s)",
                                operation,
                                retry_after,
                                attempt + 1,
                                max_retries,
                            )
                            await asyncio.sleep(min(retry_after, 60))
                            continue

                        classified = classify_connector_error(
                            error_desc, "telegram", status_code=429, retry_after=retry_after
                        )
                        self._record_failure(classified)
                        return False, None, error_desc

                    if not data.get("ok"):
                        error_desc = data.get("description", "Unknown error")
                        error_code = data.get("error_code")
                        last_error = error_desc

                        # Check if retryable
                        if error_code in {500, 502, 503, 504} and attempt < max_retries - 1:
                            delay = min(1.0 * (2**attempt), 30.0)
                            jitter = random.uniform(0, delay * 0.1)
                            logger.warning(
                                "[telegram] %s server error %s (attempt %s/%s)",
                                operation,
                                error_code,
                                attempt + 1,
                                max_retries,
                            )
                            await asyncio.sleep(delay + jitter)
                            continue

                        classified = classify_connector_error(
                            error_desc, "telegram", status_code=error_code
                        )
                        logger.error(
                            "[telegram] %s failed [%s]: %s",
                            operation,
                            type(classified).__name__,
                            error_desc,
                        )
                        self._record_failure(classified)
                        return False, data, error_desc

                    self._record_success()
                    return True, data, None

            except httpx.TimeoutException:
                last_error = f"Request timeout after {request_timeout}s"
                if attempt < max_retries - 1:
                    logger.warning(
                        "[telegram] %s timeout (attempt %s/%s)", operation, attempt + 1, max_retries
                    )
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                logger.error("[telegram] %s timeout after %s attempts", operation, max_retries)

            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
                if attempt < max_retries - 1:
                    logger.warning(
                        "[telegram] %s network error (attempt %s/%s)",
                        operation,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                logger.error(
                    "[telegram] %s network error after %s attempts: %s", operation, max_retries, e
                )

            except (httpx.RequestError, OSError, ValueError, RuntimeError, TypeError) as e:
                # Unexpected error - don't retry
                last_error = f"Unexpected error: {e}"
                classified = classify_connector_error(last_error, "telegram")
                logger.exception(
                    "[telegram] %s unexpected error [%s]: %s",
                    operation,
                    type(classified).__name__,
                    e,
                )
                break

        classified = classify_connector_error(last_error or "Unknown error", "telegram")
        self._record_failure(classified)
        return False, None, last_error or "Unknown error"

    def _escape_markdown(self, text: str) -> str:
        """Escape special characters for MarkdownV2."""
        # Characters that need escaping in MarkdownV2
        special_chars = "_*[]()~`>#+-=|{}.!"
        for char in special_chars:
            text = text.replace(char, f"\\{char}")
        return text

    def _blocks_to_keyboard(self, blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Convert generic blocks to Telegram inline keyboard."""
        buttons = []

        for block in blocks:
            if block.get("type") == "button":
                buttons.append(
                    {
                        "text": block.get("text", ""),
                        "callback_data": block.get("action_id", block.get("value", "")),
                    }
                )
            elif block.get("type") == "url_button":
                buttons.append(
                    {
                        "text": block.get("text", ""),
                        "url": block.get("url", ""),
                    }
                )

        if not buttons:
            return None

        # Group buttons into rows (max 8 buttons per row)
        rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
        return {"inline_keyboard": rows}
