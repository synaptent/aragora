"""
Tests for SlackMessagesMixin - Slack message operations module.

Tests cover:
- Message send, update, delete operations
- Ephemeral message sending
- Slash command and interaction responses
- Response URL delivery
- File upload and download
- Channel and user info retrieval
- Block Kit formatting (blocks, buttons, sections, actions, fields)
- User and channel mention formatting
- Reaction add/remove
- Modal open/update
- Pin/unpin messages and pinned message listing
- Channel and user discovery (list_channels, list_users)
- Channel history and evidence collection
- Message search
- Timestamp formatting
- Error handling and edge cases
- Unicode and special character handling
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def connector():
    """Create a SlackConnector with circuit breaker disabled for unit tests."""
    from aragora.connectors.chat.slack import SlackConnector

    return SlackConnector(bot_token="xoxb-test-token", use_circuit_breaker=False)


@pytest.fixture
def mock_success_response():
    """Factory for successful Slack API responses."""

    def _make(extra: dict[str, Any] | None = None):
        data = {"ok": True}
        if extra:
            data.update(extra)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = data
        return resp

    return _make


@pytest.fixture
def mock_error_response():
    """Factory for error Slack API responses."""

    def _make(error: str = "channel_not_found", status_code: int = 200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = {"ok": False, "error": error}
        return resp

    return _make


@pytest.fixture
def sample_message_button():
    """Create a sample MessageButton for testing."""
    from aragora.connectors.chat.models import MessageButton

    return MessageButton(
        text="Click Me",
        action_id="btn_click",
        value="click_value",
        style="primary",
    )


@pytest.fixture
def sample_message_button_danger():
    """Create a danger-styled MessageButton."""
    from aragora.connectors.chat.models import MessageButton

    return MessageButton(
        text="Delete",
        action_id="btn_delete",
        value="delete_value",
        style="danger",
    )


@pytest.fixture
def sample_message_button_default():
    """Create a default-styled MessageButton."""
    from aragora.connectors.chat.models import MessageButton

    return MessageButton(
        text="Info",
        action_id="btn_info",
        value="info_value",
        style="default",
    )


@pytest.fixture
def sample_message_button_url():
    """Create a URL MessageButton."""
    from aragora.connectors.chat.models import MessageButton

    return MessageButton(
        text="Open Link",
        action_id="btn_link",
        url="https://example.com",
    )


@pytest.fixture
def sample_bot_command():
    """Create a mock bot command object."""
    from aragora.connectors.chat.models import ChatChannel, ChatUser

    cmd = MagicMock()
    cmd.response_url = "https://hooks.slack.com/response/test"
    cmd.channel = ChatChannel(id="C12345", platform="slack")
    cmd.user = ChatUser(id="U12345", platform="slack")
    return cmd


@pytest.fixture
def sample_interaction():
    """Create a mock interaction object."""
    from aragora.connectors.chat.models import ChatChannel

    interaction = MagicMock()
    interaction.response_url = "https://hooks.slack.com/response/test"
    interaction.channel = ChatChannel(id="C12345", platform="slack")
    interaction.message_id = "1234567890.123456"
    return interaction


# ---------------------------------------------------------------------------
# Send Message Tests
# ---------------------------------------------------------------------------


class TestSendMessage:
    """Tests for the send_message method."""

    @pytest.mark.asyncio
    async def test_send_simple_message(self, connector, mock_success_response):
        """Should send a simple text message and return success."""
        resp = mock_success_response({"ts": "123.456", "channel": "C123"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=resp)
            result = await connector.send_message("C123", "Hello world")

        assert result.success is True
        assert result.message_id == "123.456"
        assert result.channel_id == "C123"
        assert result.timestamp == "123.456"

    @pytest.mark.asyncio
    async def test_send_message_with_blocks(self, connector, mock_success_response):
        """Should include blocks in the payload when provided."""
        resp = mock_success_response({"ts": "1", "channel": "C1"})
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "*Bold*"}}]
        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            await connector.send_message("C1", "fallback", blocks=blocks)
            payload = instance.post.call_args[1]["json"]
            assert payload["blocks"] == blocks

    @pytest.mark.asyncio
    async def test_send_threaded_message(self, connector, mock_success_response):
        """Should include thread_ts when sending a threaded reply."""
        resp = mock_success_response({"ts": "2", "channel": "C1"})
        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            await connector.send_message("C1", "reply", thread_id="1.0")
            payload = instance.post.call_args[1]["json"]
            assert payload["thread_ts"] == "1.0"

    @pytest.mark.asyncio
    async def test_send_message_with_unfurl_options(self, connector, mock_success_response):
        """Should pass unfurl_links and unfurl_media kwargs."""
        resp = mock_success_response({"ts": "3", "channel": "C1"})
        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            await connector.send_message("C1", "link text", unfurl_links=False, unfurl_media=True)
            payload = instance.post.call_args[1]["json"]
            assert payload["unfurl_links"] is False
            assert payload["unfurl_media"] is True

    @pytest.mark.asyncio
    async def test_send_message_without_thread_omits_thread_ts(
        self, connector, mock_success_response
    ):
        """Should not include thread_ts when no thread_id is provided."""
        resp = mock_success_response({"ts": "4", "channel": "C1"})
        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            await connector.send_message("C1", "text")
            payload = instance.post.call_args[1]["json"]
            assert "thread_ts" not in payload

    @pytest.mark.asyncio
    async def test_send_message_failure(self, connector):
        """Should return failure response on API error."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "channel_not_found"))
        result = await connector.send_message("C_INVALID", "text")
        assert result.success is False
        assert result.error == "channel_not_found"

    @pytest.mark.asyncio
    async def test_send_message_empty_text(self, connector, mock_success_response):
        """Should send message even with empty text."""
        resp = mock_success_response({"ts": "5", "channel": "C1"})
        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            result = await connector.send_message("C1", "")
            assert result.success is True

    @pytest.mark.asyncio
    async def test_send_message_unicode_text(self, connector, mock_success_response):
        """Should handle unicode characters in message text."""
        resp = mock_success_response({"ts": "6", "channel": "C1"})
        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            result = await connector.send_message(
                "C1", "Hello \u2603 \u00e9\u00e0\u00fc \u4f60\u597d"
            )
            assert result.success is True


# ---------------------------------------------------------------------------
# Update Message Tests
# ---------------------------------------------------------------------------


class TestUpdateMessage:
    """Tests for the update_message method."""

    @pytest.mark.asyncio
    async def test_update_message_success(self, connector):
        """Should update a message and return success."""
        connector._slack_api_request = AsyncMock(
            return_value=(True, {"ts": "1.0", "channel": "C1"}, None)
        )
        result = await connector.update_message("C1", "1.0", "Updated text")
        assert result.success is True
        assert result.message_id == "1.0"
        assert result.channel_id == "C1"

    @pytest.mark.asyncio
    async def test_update_message_with_blocks(self, connector):
        """Should include blocks in update payload."""
        connector._slack_api_request = AsyncMock(
            return_value=(True, {"ts": "1.0", "channel": "C1"}, None)
        )
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "new"}}]
        result = await connector.update_message("C1", "1.0", "text", blocks=blocks)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_update_message_failure(self, connector):
        """Should return error on update failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "message_not_found"))
        result = await connector.update_message("C1", "bad_ts", "text")
        assert result.success is False
        assert result.error == "message_not_found"


# ---------------------------------------------------------------------------
# Delete Message Tests
# ---------------------------------------------------------------------------


class TestDeleteMessage:
    """Tests for the delete_message method."""

    @pytest.mark.asyncio
    async def test_delete_message_success(self, connector):
        """Should return True on successful deletion."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"ok": True}, None))
        result = await connector.delete_message("C1", "1.0")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_message_failure(self, connector):
        """Should return False on deletion failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "message_not_found"))
        result = await connector.delete_message("C1", "bad_ts")
        assert result is False


# ---------------------------------------------------------------------------
# Ephemeral Message Tests
# ---------------------------------------------------------------------------


class TestSendEphemeral:
    """Tests for the send_ephemeral method."""

    @pytest.mark.asyncio
    async def test_send_ephemeral_success(self, connector):
        """Should send ephemeral message visible only to one user."""
        resp = MagicMock()
        resp.json.return_value = {"ok": True}

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            result = await connector.send_ephemeral("C1", "U1", "Secret msg")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_ephemeral_with_blocks(self, connector):
        """Should include blocks in ephemeral payload."""
        resp = MagicMock()
        resp.json.return_value = {"ok": True}
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hidden"}}]

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            result = await connector.send_ephemeral("C1", "U1", "text", blocks=blocks)
            payload = instance.post.call_args[1]["json"]
            assert payload["blocks"] == blocks

        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_ephemeral_api_error(self, connector):
        """Should handle Slack API error for ephemeral message."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"ok": False, "error": "user_not_found"}

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)

            with patch(
                "aragora.connectors.chat.slack.messages._is_retryable_error",
                return_value=False,
            ):
                result = await connector.send_ephemeral("C1", "U_BAD", "text")

        assert result.success is False
        assert result.error == "user_not_found"

    @pytest.mark.asyncio
    async def test_send_ephemeral_httpx_not_available(self, connector):
        """Should return error when httpx is not available."""
        with patch("aragora.connectors.chat.slack.messages.HTTPX_AVAILABLE", False):
            result = await connector.send_ephemeral("C1", "U1", "text")
        assert result.success is False
        assert "httpx" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_ephemeral_circuit_breaker_open(self, connector):
        """Should return error when circuit breaker is open."""
        cb = MagicMock()
        cb.can_proceed.return_value = False
        connector._circuit_breaker = cb
        result = await connector.send_ephemeral("C1", "U1", "text")
        assert result.success is False
        assert "circuit breaker" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_ephemeral_timeout_retries(self, connector):
        """Should retry on timeout and eventually fail."""
        import httpx

        connector._max_retries = 2

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

            with patch(
                "aragora.connectors.chat.slack.messages._exponential_backoff",
                new_callable=AsyncMock,
            ):
                result = await connector.send_ephemeral("C1", "U1", "text")

        assert result.success is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_ephemeral_connect_error_retries(self, connector):
        """Should retry on connection error and eventually fail."""
        import httpx

        connector._max_retries = 2

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

            with patch(
                "aragora.connectors.chat.slack.messages._exponential_backoff",
                new_callable=AsyncMock,
            ):
                result = await connector.send_ephemeral("C1", "U1", "text")

        assert result.success is False
        assert "connection" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_ephemeral_unexpected_error(self, connector):
        """Should not retry on unexpected errors."""
        connector._max_retries = 3

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=RuntimeError("unexpected"))

            result = await connector.send_ephemeral("C1", "U1", "text")

        assert result.success is False
        assert "unexpected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_ephemeral_records_circuit_breaker_failure(self, connector):
        """Should record circuit breaker failure on exhausted retries."""
        cb = MagicMock()
        cb.can_proceed.return_value = True
        connector._circuit_breaker = cb
        connector._max_retries = 1

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"ok": False, "error": "some_error"}

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)

            with patch(
                "aragora.connectors.chat.slack.messages._is_retryable_error",
                return_value=False,
            ):
                await connector.send_ephemeral("C1", "U1", "text")

        cb.record_failure.assert_called()

    @pytest.mark.asyncio
    async def test_send_ephemeral_records_circuit_breaker_success(self, connector):
        """Should record circuit breaker success on OK response."""
        cb = MagicMock()
        cb.can_proceed.return_value = True
        connector._circuit_breaker = cb

        resp = MagicMock()
        resp.json.return_value = {"ok": True}

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            await connector.send_ephemeral("C1", "U1", "text")

        cb.record_success.assert_called_once()


# ---------------------------------------------------------------------------
# Command and Interaction Response Tests
# ---------------------------------------------------------------------------


class TestRespondToCommand:
    """Tests for the respond_to_command method."""

    @pytest.mark.asyncio
    async def test_respond_via_response_url(self, connector, sample_bot_command):
        """Should use response_url when available."""
        connector._send_to_response_url = AsyncMock(return_value=MagicMock(success=True))
        result = await connector.respond_to_command(sample_bot_command, "response text")
        assert result.success is True
        connector._send_to_response_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_respond_ephemeral_fallback(self, connector, sample_bot_command):
        """Should fall back to ephemeral message when no response_url."""
        sample_bot_command.response_url = None
        connector.send_ephemeral = AsyncMock(return_value=MagicMock(success=True))
        result = await connector.respond_to_command(sample_bot_command, "text", ephemeral=True)
        assert result.success is True
        connector.send_ephemeral.assert_called_once()

    @pytest.mark.asyncio
    async def test_respond_in_channel_fallback(self, connector, sample_bot_command):
        """Should fall back to in-channel message when not ephemeral."""
        sample_bot_command.response_url = None
        connector.send_message = AsyncMock(return_value=MagicMock(success=True))
        result = await connector.respond_to_command(sample_bot_command, "text", ephemeral=False)
        assert result.success is True
        connector.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_respond_no_target(self, connector):
        """Should return failure when no response target is available."""
        cmd = MagicMock()
        cmd.response_url = None
        cmd.channel = None
        cmd.user = None
        result = await connector.respond_to_command(cmd, "text")
        assert result.success is False
        assert "no response target" in result.error.lower()

    @pytest.mark.asyncio
    async def test_respond_ephemeral_via_response_url_type(self, connector, sample_bot_command):
        """Should set response_type to ephemeral when ephemeral=True."""
        connector._send_to_response_url = AsyncMock(return_value=MagicMock(success=True))
        await connector.respond_to_command(sample_bot_command, "text", ephemeral=True)
        call_kwargs = connector._send_to_response_url.call_args
        assert call_kwargs[1].get(
            "response_type", call_kwargs[0][3] if len(call_kwargs[0]) > 3 else None
        ) == "ephemeral" or "ephemeral" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_respond_in_channel_via_response_url_type(self, connector, sample_bot_command):
        """Should set response_type to in_channel when ephemeral=False."""
        connector._send_to_response_url = AsyncMock(return_value=MagicMock(success=True))
        await connector.respond_to_command(sample_bot_command, "text", ephemeral=False)
        call_args = connector._send_to_response_url.call_args
        assert "in_channel" in str(call_args)


class TestRespondToInteraction:
    """Tests for the respond_to_interaction method."""

    @pytest.mark.asyncio
    async def test_respond_via_response_url(self, connector, sample_interaction):
        """Should use response_url when available."""
        connector._send_to_response_url = AsyncMock(return_value=MagicMock(success=True))
        result = await connector.respond_to_interaction(sample_interaction, "text")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_respond_replace_original(self, connector, sample_interaction):
        """Should update original message when replace_original is set."""
        sample_interaction.response_url = None
        connector.update_message = AsyncMock(return_value=MagicMock(success=True))
        result = await connector.respond_to_interaction(
            sample_interaction, "updated", replace_original=True
        )
        assert result.success is True
        connector.update_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_respond_send_new_message(self, connector, sample_interaction):
        """Should send new message when not replacing original."""
        sample_interaction.response_url = None
        sample_interaction.message_id = None
        connector.send_message = AsyncMock(return_value=MagicMock(success=True))
        result = await connector.respond_to_interaction(sample_interaction, "new msg")
        assert result.success is True
        connector.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_respond_no_target(self, connector):
        """Should return failure when no response target available."""
        interaction = MagicMock()
        interaction.response_url = None
        interaction.channel = None
        interaction.message_id = None
        result = await connector.respond_to_interaction(interaction, "text")
        assert result.success is False
        assert "no response target" in result.error.lower()


# ---------------------------------------------------------------------------
# Response URL Delivery Tests
# ---------------------------------------------------------------------------


class TestSendToResponseUrl:
    """Tests for the _send_to_response_url private method."""

    @pytest.mark.asyncio
    async def test_success(self, connector):
        """Should send payload to response URL and return success."""
        resp = MagicMock()
        resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            result = await connector._send_to_response_url("https://hooks.slack.com/test", "text")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_with_blocks(self, connector):
        """Should include blocks in response URL payload."""
        resp = MagicMock()
        resp.status_code = 200
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "ok"}}]

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            result = await connector._send_to_response_url(
                "https://hooks.slack.com/test", "text", blocks=blocks
            )
            payload = instance.post.call_args[1]["json"]
            assert payload["blocks"] == blocks

        assert result.success is True

    @pytest.mark.asyncio
    async def test_replace_original_flag(self, connector):
        """Should include replace_original in payload when set."""
        resp = MagicMock()
        resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            await connector._send_to_response_url(
                "https://hooks.slack.com/test",
                "text",
                replace_original=True,
            )
            payload = instance.post.call_args[1]["json"]
            assert payload["replace_original"] is True

    @pytest.mark.asyncio
    async def test_server_error_retries(self, connector):
        """Should retry on 5xx errors."""
        error_resp = MagicMock()
        error_resp.status_code = 500

        success_resp = MagicMock()
        success_resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=[error_resp, success_resp])

            with patch(
                "aragora.connectors.chat.slack.messages._exponential_backoff",
                new_callable=AsyncMock,
            ):
                result = await connector._send_to_response_url(
                    "https://hooks.slack.com/test", "text"
                )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_client_error_no_retry(self, connector):
        """Should not retry on 4xx client errors."""
        resp = MagicMock()
        resp.status_code = 400

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            result = await connector._send_to_response_url("https://hooks.slack.com/test", "text")

        assert result.success is False
        assert "400" in result.error

    @pytest.mark.asyncio
    async def test_timeout_retries(self, connector):
        """Should retry on timeout and return error after both attempts fail."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

            with patch(
                "aragora.connectors.chat.slack.messages._exponential_backoff",
                new_callable=AsyncMock,
            ):
                result = await connector._send_to_response_url(
                    "https://hooks.slack.com/test", "text"
                )

        assert result.success is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_connect_error_retries(self, connector):
        """Should retry on connection error."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=httpx.ConnectError("conn refused"))

            with patch(
                "aragora.connectors.chat.slack.messages._exponential_backoff",
                new_callable=AsyncMock,
            ):
                result = await connector._send_to_response_url(
                    "https://hooks.slack.com/test", "text"
                )

        assert result.success is False
        assert "connection" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unexpected_error_no_retry(self, connector):
        """Should not retry on unexpected exceptions."""
        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=ValueError("bad value"))

            result = await connector._send_to_response_url("https://hooks.slack.com/test", "text")

        assert result.success is False
        assert "error" in result.error.lower() or "unexpected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_httpx_not_available(self, connector):
        """Should return error when httpx is not available."""
        with patch("aragora.connectors.chat.slack.messages.HTTPX_AVAILABLE", False):
            result = await connector._send_to_response_url("https://hooks.slack.com/test", "text")
        assert result.success is False
        assert "httpx" in result.error.lower()

    @pytest.mark.asyncio
    async def test_response_type_passed(self, connector):
        """Should include the specified response_type in payload."""
        resp = MagicMock()
        resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=resp)
            await connector._send_to_response_url(
                "https://hooks.slack.com/test",
                "text",
                response_type="in_channel",
            )
            payload = instance.post.call_args[1]["json"]
            assert payload["response_type"] == "in_channel"


# ---------------------------------------------------------------------------
# File Operations Tests
# ---------------------------------------------------------------------------


class TestUploadFile:
    """Tests for the upload_file method."""

    @pytest.mark.asyncio
    async def test_upload_file_success(self, connector):
        """Should upload file and return FileAttachment with metadata."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "file": {
                        "id": "F123",
                        "name": "report.pdf",
                        "mimetype": "application/pdf",
                        "size": 1024,
                        "url_private": "https://files.slack.com/report.pdf",
                    }
                },
                None,
            )
        )
        result = await connector.upload_file(
            "C1", b"file content", "report.pdf", "application/pdf", title="Report"
        )
        assert result.id == "F123"
        assert result.filename == "report.pdf"
        assert result.content_type == "application/pdf"
        assert result.size == 1024
        assert result.url == "https://files.slack.com/report.pdf"

    @pytest.mark.asyncio
    async def test_upload_file_with_thread(self, connector):
        """Should include thread_ts when uploading to a thread."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {"file": {"id": "F1", "name": "f.txt", "mimetype": "text/plain", "size": 5}},
                None,
            )
        )
        await connector.upload_file("C1", b"hello", "f.txt", thread_id="1.0")
        call_kwargs = connector._slack_api_request.call_args[1]
        assert call_kwargs["form_data"]["thread_ts"] == "1.0"

    @pytest.mark.asyncio
    async def test_upload_file_failure(self, connector):
        """Should return empty FileAttachment on failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "upload_error"))
        result = await connector.upload_file("C1", b"data", "file.bin")
        assert result.id == ""
        assert result.filename == "file.bin"
        assert result.url is None

    @pytest.mark.asyncio
    async def test_upload_file_defaults(self, connector):
        """Should use default content type when not specified."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "error"))
        result = await connector.upload_file("C1", b"x", "unknown.bin")
        assert result.content_type == "application/octet-stream"


class TestDownloadFile:
    """Tests for the download_file method."""

    @pytest.mark.asyncio
    async def test_download_file_success(self, connector):
        """Should download file content and return FileAttachment."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "file": {
                        "id": "F1",
                        "name": "doc.txt",
                        "mimetype": "text/plain",
                        "size": 100,
                        "url_private_download": "https://files.slack.com/dl/doc.txt",
                    }
                },
                None,
            )
        )
        connector._http_request = AsyncMock(return_value=(True, b"file content here", None))
        result = await connector.download_file("F1")
        assert result.id == "F1"
        assert result.filename == "doc.txt"
        assert result.content == b"file content here"
        assert result.size == len(b"file content here")

    @pytest.mark.asyncio
    async def test_download_file_uses_resilient_http_request(self, connector):
        """The mixin's type-only declaration must not shadow HTTPResilienceMixin._http_request."""
        from aragora.connectors.chat.http_resilience import HTTPResilienceMixin

        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "file": {
                        "id": "F9",
                        "name": "real.txt",
                        "mimetype": "text/plain",
                        "size": 4,
                        "url_private_download": "https://files.slack.com/dl/real.txt",
                    }
                },
                None,
            )
        )
        http_request = AsyncMock(return_value=(True, b"real", None))
        with patch.object(HTTPResilienceMixin, "_http_request", http_request):
            result = await connector.download_file("F9")
        http_request.assert_awaited_once()
        assert result.content == b"real"

    @pytest.mark.asyncio
    async def test_download_file_no_url(self, connector):
        """Should return FileAttachment without content when no URL available."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {"file": {"id": "F2", "name": "nourl.txt", "mimetype": "text/plain", "size": 50}},
                None,
            )
        )
        result = await connector.download_file("F2")
        assert result.id == "F2"
        assert result.content is None

    @pytest.mark.asyncio
    async def test_download_file_info_failure(self, connector):
        """Should return empty FileAttachment when file info API fails."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "file_not_found"))
        result = await connector.download_file("F_BAD")
        assert result.id == "F_BAD"
        assert result.filename == ""
        assert result.size == 0

    @pytest.mark.asyncio
    async def test_download_file_content_failure(self, connector):
        """Should return FileAttachment without content when download fails."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "file": {
                        "id": "F3",
                        "name": "fail.bin",
                        "mimetype": "application/octet-stream",
                        "size": 200,
                        "url_private": "https://files.slack.com/fail.bin",
                    }
                },
                None,
            )
        )
        connector._http_request = AsyncMock(return_value=(False, None, "download error"))
        result = await connector.download_file("F3")
        assert result.id == "F3"
        assert result.content is None
        assert result.size == 200

    @pytest.mark.asyncio
    async def test_download_file_uses_url_private_fallback(self, connector):
        """Should fall back to url_private when url_private_download is absent."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "file": {
                        "id": "F4",
                        "name": "fb.txt",
                        "mimetype": "text/plain",
                        "size": 10,
                        "url_private": "https://files.slack.com/fb.txt",
                    }
                },
                None,
            )
        )
        connector._http_request = AsyncMock(return_value=(True, b"fallback", None))
        result = await connector.download_file("F4")
        assert result.content == b"fallback"


# ---------------------------------------------------------------------------
# Channel and User Info Tests
# ---------------------------------------------------------------------------


class TestGetChannelInfo:
    """Tests for the get_channel_info method."""

    @pytest.mark.asyncio
    async def test_get_channel_info_success(self, connector):
        """Should return ChatChannel with metadata on success."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "channel": {
                        "name": "general",
                        "context_team_id": "T123",
                        "is_private": False,
                        "topic": {"value": "General discussion"},
                        "purpose": {"value": "A place for general talk"},
                        "num_members": 42,
                    }
                },
                None,
            )
        )
        result = await connector.get_channel_info("C123")
        assert result is not None
        assert result.id == "C123"
        assert result.name == "general"
        assert result.team_id == "T123"
        assert result.is_private is False
        assert result.metadata["topic"] == "General discussion"
        assert result.metadata["num_members"] == 42

    @pytest.mark.asyncio
    async def test_get_channel_info_failure(self, connector):
        """Should return None on failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "channel_not_found"))
        result = await connector.get_channel_info("C_BAD")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_channel_info_platform_name(self, connector):
        """Should set platform to slack."""
        connector._slack_api_request = AsyncMock(
            return_value=(True, {"channel": {"name": "ch"}}, None)
        )
        result = await connector.get_channel_info("C1")
        assert result.platform == "slack"


class TestGetUserInfo:
    """Tests for the get_user_info method."""

    @pytest.mark.asyncio
    async def test_get_user_info_success(self, connector):
        """Should return ChatUser with profile data on success."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "user": {
                        "name": "johndoe",
                        "is_bot": False,
                        "team_id": "T123",
                        "tz": "America/New_York",
                        "profile": {
                            "display_name": "John Doe",
                            "real_name": "John D.",
                            "email": "john@example.com",
                            "title": "Engineer",
                        },
                    }
                },
                None,
            )
        )
        result = await connector.get_user_info("U123")
        assert result is not None
        assert result.id == "U123"
        assert result.username == "johndoe"
        assert result.display_name == "John Doe"
        assert result.email == "john@example.com"
        assert result.is_bot is False
        assert result.metadata["title"] == "Engineer"
        assert result.metadata["tz"] == "America/New_York"

    @pytest.mark.asyncio
    async def test_get_user_info_display_name_fallback(self, connector):
        """Should fall back to real_name when display_name is empty."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "user": {
                        "name": "jane",
                        "profile": {
                            "display_name": "",
                            "real_name": "Jane Smith",
                        },
                    }
                },
                None,
            )
        )
        result = await connector.get_user_info("U456")
        assert result.display_name == "Jane Smith"

    @pytest.mark.asyncio
    async def test_get_user_info_failure(self, connector):
        """Should return None on failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "user_not_found"))
        result = await connector.get_user_info("U_BAD")
        assert result is None


# ---------------------------------------------------------------------------
# Block Kit Formatting Tests
# ---------------------------------------------------------------------------


class TestFormatBlocks:
    """Tests for the format_blocks method - Block Kit construction."""

    def test_empty_blocks(self, connector):
        """Should return empty list when no content provided."""
        blocks = connector.format_blocks()
        assert blocks == []

    def test_title_only(self, connector):
        """Should create header block for title."""
        blocks = connector.format_blocks(title="My Title")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "header"
        assert blocks[0]["text"]["type"] == "plain_text"
        assert blocks[0]["text"]["text"] == "My Title"
        assert blocks[0]["text"]["emoji"] is True

    def test_body_only(self, connector):
        """Should create section block for body."""
        blocks = connector.format_blocks(body="Some *markdown* text")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"
        assert blocks[0]["text"]["type"] == "mrkdwn"
        assert blocks[0]["text"]["text"] == "Some *markdown* text"

    def test_fields_only(self, connector):
        """Should create section block with fields."""
        fields = [("Label1", "Value1"), ("Label2", "Value2")]
        blocks = connector.format_blocks(fields=fields)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"
        assert len(blocks[0]["fields"]) == 2
        assert blocks[0]["fields"][0]["type"] == "mrkdwn"
        assert blocks[0]["fields"][0]["text"] == "*Label1*\nValue1"
        assert blocks[0]["fields"][1]["text"] == "*Label2*\nValue2"

    def test_actions_only(self, connector, sample_message_button):
        """Should create actions block with buttons."""
        blocks = connector.format_blocks(actions=[sample_message_button])
        assert len(blocks) == 1
        assert blocks[0]["type"] == "actions"
        assert len(blocks[0]["elements"]) == 1

    def test_all_components(self, connector, sample_message_button):
        """Should create all blocks in order: header, section, fields, actions."""
        fields = [("F1", "V1")]
        blocks = connector.format_blocks(
            title="Title",
            body="Body text",
            fields=fields,
            actions=[sample_message_button],
        )
        assert len(blocks) == 4
        assert blocks[0]["type"] == "header"
        assert blocks[1]["type"] == "section"
        assert blocks[2]["type"] == "section"
        assert "fields" in blocks[2]
        assert blocks[3]["type"] == "actions"

    def test_title_with_unicode(self, connector):
        """Should handle unicode in title."""
        blocks = connector.format_blocks(title="Hello \u2603 World \u00e9")
        assert blocks[0]["text"]["text"] == "Hello \u2603 World \u00e9"

    def test_body_with_special_characters(self, connector):
        """Should handle special Slack mrkdwn characters in body."""
        blocks = connector.format_blocks(body="<@U123> & <#C456> `code` ~strike~")
        assert blocks[0]["text"]["text"] == "<@U123> & <#C456> `code` ~strike~"

    def test_multiple_actions(self, connector, sample_message_button, sample_message_button_danger):
        """Should include multiple buttons in actions block."""
        blocks = connector.format_blocks(
            actions=[sample_message_button, sample_message_button_danger]
        )
        assert len(blocks[0]["elements"]) == 2

    def test_empty_fields_list(self, connector):
        """Should not create fields block when fields list is empty."""
        blocks = connector.format_blocks(fields=[])
        assert blocks == []

    def test_none_blocks_parameter(self, connector):
        """Should handle None blocks parameter gracefully."""
        blocks = connector.format_blocks(title=None, body=None, fields=None, actions=None)
        assert blocks == []


# ---------------------------------------------------------------------------
# Button Formatting Tests
# ---------------------------------------------------------------------------


class TestFormatButton:
    """Tests for the format_button method."""

    def test_default_style_button(self, connector):
        """Should create button without style property for default."""
        btn = connector.format_button("Click", "action_1", "val_1")
        assert btn["type"] == "button"
        assert btn["text"]["type"] == "plain_text"
        assert btn["text"]["text"] == "Click"
        assert btn["action_id"] == "action_1"
        assert btn["value"] == "val_1"
        assert "style" not in btn

    def test_primary_style_button(self, connector):
        """Should include style=primary for primary buttons."""
        btn = connector.format_button("OK", "act", "v", style="primary")
        assert btn["style"] == "primary"

    def test_danger_style_button(self, connector):
        """Should include style=danger for danger buttons."""
        btn = connector.format_button("Delete", "del", "d", style="danger")
        assert btn["style"] == "danger"

    def test_url_button(self, connector):
        """Should create link button with URL, omitting action_id and value."""
        btn = connector.format_button("Visit", "action", "val", url="https://example.com")
        assert btn["type"] == "button"
        assert btn["url"] == "https://example.com"
        assert "action_id" not in btn
        assert "value" not in btn

    def test_value_defaults_to_action_id(self, connector):
        """Should use action_id as value when value is None."""
        btn = connector.format_button("Btn", "my_action")
        assert btn["value"] == "my_action"

    def test_emoji_enabled(self, connector):
        """Should enable emoji in button text."""
        btn = connector.format_button("OK", "act", "v")
        assert btn["text"]["emoji"] is True

    def test_button_with_unicode_text(self, connector):
        """Should handle unicode in button text."""
        btn = connector.format_button("\u2705 Approve", "approve", "yes")
        assert btn["text"]["text"] == "\u2705 Approve"

    def test_unknown_style_treated_as_default(self, connector):
        """Should not add style for unrecognized style values."""
        btn = connector.format_button("Btn", "act", "v", style="outline")
        assert "style" not in btn


# ---------------------------------------------------------------------------
# Reaction Tests
# ---------------------------------------------------------------------------


class TestReactions:
    """Tests for add_reaction and remove_reaction methods."""

    @pytest.mark.asyncio
    async def test_add_reaction_success(self, connector):
        """Should return True on successful reaction add."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"ok": True}, None))
        result = await connector.add_reaction("C1", "1.0", "thumbsup")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_reaction_strips_colons(self, connector):
        """Should strip colons from emoji name."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"ok": True}, None))
        await connector.add_reaction("C1", "1.0", ":thumbsup:")
        call_kwargs = connector._slack_api_request.call_args[1]
        assert call_kwargs["json_data"]["name"] == "thumbsup"

    @pytest.mark.asyncio
    async def test_add_reaction_already_reacted(self, connector):
        """Should return True for already_reacted error (idempotent)."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "already_reacted"))
        result = await connector.add_reaction("C1", "1.0", "thumbsup")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_reaction_failure(self, connector):
        """Should return False on actual error."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "channel_not_found"))
        result = await connector.add_reaction("C1", "1.0", "thumbsup")
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_reaction_success(self, connector):
        """Should return True on successful reaction removal."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"ok": True}, None))
        result = await connector.remove_reaction("C1", "1.0", "thumbsup")
        assert result is True

    @pytest.mark.asyncio
    async def test_remove_reaction_no_reaction(self, connector):
        """Should return True for no_reaction error (idempotent)."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "no_reaction"))
        result = await connector.remove_reaction("C1", "1.0", "thumbsup")
        assert result is True

    @pytest.mark.asyncio
    async def test_remove_reaction_strips_colons(self, connector):
        """Should strip colons from emoji name on remove."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"ok": True}, None))
        await connector.remove_reaction("C1", "1.0", ":fire:")
        call_kwargs = connector._slack_api_request.call_args[1]
        assert call_kwargs["json_data"]["name"] == "fire"

    @pytest.mark.asyncio
    async def test_remove_reaction_failure(self, connector):
        """Should return False on actual error."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "some_error"))
        result = await connector.remove_reaction("C1", "1.0", "thumbsup")
        assert result is False


# ---------------------------------------------------------------------------
# Mention Formatting Tests
# ---------------------------------------------------------------------------


class TestMentionFormatting:
    """Tests for format_user_mention and format_channel_mention static methods."""

    def test_format_user_mention(self):
        """Should format user ID as Slack mention."""
        from aragora.connectors.chat.slack.messages import SlackMessagesMixin

        result = SlackMessagesMixin.format_user_mention("U123ABC")
        assert result == "<@U123ABC>"

    def test_format_channel_mention(self):
        """Should format channel ID as Slack mention."""
        from aragora.connectors.chat.slack.messages import SlackMessagesMixin

        result = SlackMessagesMixin.format_channel_mention("C123ABC")
        assert result == "<#C123ABC>"

    def test_format_user_mention_empty_id(self):
        """Should handle empty user ID."""
        from aragora.connectors.chat.slack.messages import SlackMessagesMixin

        result = SlackMessagesMixin.format_user_mention("")
        assert result == "<@>"

    def test_format_channel_mention_empty_id(self):
        """Should handle empty channel ID."""
        from aragora.connectors.chat.slack.messages import SlackMessagesMixin

        result = SlackMessagesMixin.format_channel_mention("")
        assert result == "<#>"

    def test_format_user_mention_special_chars(self):
        """Should include special characters as-is in mention."""
        from aragora.connectors.chat.slack.messages import SlackMessagesMixin

        result = SlackMessagesMixin.format_user_mention("U_SPECIAL-123")
        assert result == "<@U_SPECIAL-123>"


# ---------------------------------------------------------------------------
# Modal Tests
# ---------------------------------------------------------------------------


class TestModals:
    """Tests for open_modal and update_modal methods."""

    @pytest.mark.asyncio
    async def test_open_modal_success(self, connector):
        """Should return view ID on successful modal open."""
        connector._slack_api_request = AsyncMock(
            return_value=(True, {"view": {"id": "V123"}}, None)
        )
        result = await connector.open_modal("trigger_123", {"type": "modal"})
        assert result == "V123"

    @pytest.mark.asyncio
    async def test_open_modal_failure(self, connector):
        """Should return None on failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "expired_trigger_id"))
        result = await connector.open_modal("trigger_expired", {"type": "modal"})
        assert result is None

    @pytest.mark.asyncio
    async def test_open_modal_no_view_id(self, connector):
        """Should return None when view ID is missing from response."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"view": {}}, None))
        result = await connector.open_modal("trigger_123", {"type": "modal"})
        assert result is None

    @pytest.mark.asyncio
    async def test_update_modal_success(self, connector):
        """Should return True on successful modal update."""
        connector._slack_api_request = AsyncMock(
            return_value=(True, {"view": {"id": "V123"}}, None)
        )
        result = await connector.update_modal("V123", {"type": "modal"})
        assert result is True

    @pytest.mark.asyncio
    async def test_update_modal_failure(self, connector):
        """Should return False on failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "view_not_found"))
        result = await connector.update_modal("V_BAD", {"type": "modal"})
        assert result is False

    @pytest.mark.asyncio
    async def test_update_modal_with_hash(self, connector):
        """Should include view_hash for optimistic locking."""
        connector._slack_api_request = AsyncMock(return_value=(True, {}, None))
        await connector.update_modal("V1", {"type": "modal"}, view_hash="abc123")
        call_kwargs = connector._slack_api_request.call_args[1]
        assert call_kwargs["json_data"]["hash"] == "abc123"


# ---------------------------------------------------------------------------
# Pinned Message Tests
# ---------------------------------------------------------------------------


class TestPinnedMessages:
    """Tests for pin_message, unpin_message, and get_pinned_messages."""

    @pytest.mark.asyncio
    async def test_pin_message_success(self, connector):
        """Should return True on successful pin."""
        connector._slack_api_request = AsyncMock(return_value=(True, {}, None))
        result = await connector.pin_message("C1", "1.0")
        assert result is True

    @pytest.mark.asyncio
    async def test_pin_message_already_pinned(self, connector):
        """Should return True for already_pinned (idempotent)."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "already_pinned"))
        result = await connector.pin_message("C1", "1.0")
        assert result is True

    @pytest.mark.asyncio
    async def test_pin_message_failure(self, connector):
        """Should return False on actual error."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "not_pinnable"))
        result = await connector.pin_message("C1", "1.0")
        assert result is False

    @pytest.mark.asyncio
    async def test_unpin_message_success(self, connector):
        """Should return True on successful unpin."""
        connector._slack_api_request = AsyncMock(return_value=(True, {}, None))
        result = await connector.unpin_message("C1", "1.0")
        assert result is True

    @pytest.mark.asyncio
    async def test_unpin_message_no_pin(self, connector):
        """Should return True for no_pin error (idempotent)."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "no_pin"))
        result = await connector.unpin_message("C1", "1.0")
        assert result is True

    @pytest.mark.asyncio
    async def test_unpin_message_failure(self, connector):
        """Should return False on actual error."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "permission_denied"))
        result = await connector.unpin_message("C1", "1.0")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_pinned_messages_success(self, connector):
        """Should return list of ChatMessage for pinned messages."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "items": [
                        {
                            "type": "message",
                            "message": {
                                "ts": "1609459200.000000",
                                "user": "U123",
                                "text": "Pinned content",
                            },
                        }
                    ]
                },
                None,
            )
        )
        result = await connector.get_pinned_messages("C1")
        assert len(result) == 1
        assert result[0].content == "Pinned content"
        assert result[0].metadata["pinned"] is True

    @pytest.mark.asyncio
    async def test_get_pinned_messages_empty(self, connector):
        """Should return empty list when no pinned messages."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"items": []}, None))
        result = await connector.get_pinned_messages("C1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_pinned_messages_skips_non_message_items(self, connector):
        """Should skip non-message items like pinned files."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "items": [
                        {"type": "file", "file": {"id": "F1"}},
                        {
                            "type": "message",
                            "message": {"ts": "1609459200.000000", "user": "U1", "text": "msg"},
                        },
                    ]
                },
                None,
            )
        )
        result = await connector.get_pinned_messages("C1")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_pinned_messages_failure(self, connector):
        """Should return empty list on API failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "channel_not_found"))
        result = await connector.get_pinned_messages("C_BAD")
        assert result == []


# ---------------------------------------------------------------------------
# Channel and User Discovery Tests
# ---------------------------------------------------------------------------


class TestListChannels:
    """Tests for the list_channels method."""

    @pytest.mark.asyncio
    async def test_list_channels_success(self, connector):
        """Should return list of ChatChannel objects."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "channels": [
                        {
                            "id": "C1",
                            "name": "general",
                            "is_private": False,
                            "is_archived": False,
                            "is_member": True,
                            "num_members": 100,
                            "topic": {"value": "General chat"},
                            "purpose": {"value": "General discussion"},
                        },
                        {
                            "id": "C2",
                            "name": "secret",
                            "is_private": True,
                            "is_archived": False,
                            "is_member": False,
                            "num_members": 5,
                            "topic": {"value": ""},
                            "purpose": {"value": ""},
                        },
                    ]
                },
                None,
            )
        )
        result = await connector.list_channels()
        assert len(result) == 2
        assert result[0].id == "C1"
        assert result[0].name == "general"
        assert result[0].metadata["is_private"] is False
        assert result[1].metadata["is_private"] is True

    @pytest.mark.asyncio
    async def test_list_channels_empty(self, connector):
        """Should return empty list when no channels."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"channels": []}, None))
        result = await connector.list_channels()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_channels_failure(self, connector):
        """Should return empty list on API failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "not_authed"))
        result = await connector.list_channels()
        assert result == []


class TestListUsers:
    """Tests for the list_users method."""

    @pytest.mark.asyncio
    async def test_list_users_success(self, connector):
        """Should return list of ChatUser objects."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "members": [
                        {
                            "id": "U1",
                            "name": "alice",
                            "is_bot": False,
                            "deleted": False,
                            "is_admin": True,
                            "is_owner": False,
                            "tz": "US/Pacific",
                            "profile": {
                                "display_name": "Alice",
                                "real_name": "Alice W.",
                                "image_72": "https://img.slack.com/alice.png",
                                "email": "alice@example.com",
                                "title": "Lead",
                            },
                        }
                    ]
                },
                None,
            )
        )
        result = await connector.list_users()
        assert len(result) == 1
        assert result[0].id == "U1"
        assert result[0].username == "alice"
        assert result[0].display_name == "Alice"
        assert result[0].avatar_url == "https://img.slack.com/alice.png"
        assert result[0].metadata["email"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_list_users_excludes_bots_by_default(self, connector):
        """Should exclude bot users when include_bots is False."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "members": [
                        {
                            "id": "U1",
                            "name": "human",
                            "is_bot": False,
                            "deleted": False,
                            "profile": {},
                        },
                        {
                            "id": "B1",
                            "name": "bot",
                            "is_bot": True,
                            "deleted": False,
                            "profile": {},
                        },
                    ]
                },
                None,
            )
        )
        result = await connector.list_users(include_bots=False)
        assert len(result) == 1
        assert result[0].id == "U1"

    @pytest.mark.asyncio
    async def test_list_users_includes_bots(self, connector):
        """Should include bot users when include_bots is True."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "members": [
                        {
                            "id": "U1",
                            "name": "human",
                            "is_bot": False,
                            "deleted": False,
                            "profile": {},
                        },
                        {
                            "id": "B1",
                            "name": "bot",
                            "is_bot": True,
                            "deleted": False,
                            "profile": {},
                        },
                    ]
                },
                None,
            )
        )
        result = await connector.list_users(include_bots=True)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_users_excludes_deleted(self, connector):
        """Should exclude deleted users."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "members": [
                        {
                            "id": "U1",
                            "name": "active",
                            "is_bot": False,
                            "deleted": False,
                            "profile": {},
                        },
                        {
                            "id": "U2",
                            "name": "gone",
                            "is_bot": False,
                            "deleted": True,
                            "profile": {},
                        },
                    ]
                },
                None,
            )
        )
        result = await connector.list_users()
        assert len(result) == 1
        assert result[0].id == "U1"

    @pytest.mark.asyncio
    async def test_list_users_failure(self, connector):
        """Should return empty list on API failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "not_authed"))
        result = await connector.list_users()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_users_display_name_fallback(self, connector):
        """Should fall back to real_name when display_name is empty."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "members": [
                        {
                            "id": "U1",
                            "name": "user",
                            "is_bot": False,
                            "deleted": False,
                            "profile": {
                                "display_name": "",
                                "real_name": "Real Name",
                            },
                        }
                    ]
                },
                None,
            )
        )
        result = await connector.list_users()
        assert result[0].display_name == "Real Name"


# ---------------------------------------------------------------------------
# Channel History Tests
# ---------------------------------------------------------------------------


class TestGetChannelHistory:
    """Tests for the get_channel_history method."""

    @pytest.mark.asyncio
    async def test_get_history_success(self, connector):
        """Should return list of ChatMessage objects from channel history."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "messages": [
                        {
                            "ts": "1609459200.000000",
                            "user": "U123",
                            "text": "Hello world",
                            "reply_count": 2,
                            "reactions": [{"name": "thumbsup", "count": 1}],
                        }
                    ]
                },
                None,
            )
        )
        connector.get_channel_info = AsyncMock(return_value=None)
        result = await connector.get_channel_history("C1", limit=10)
        assert len(result) == 1
        assert result[0].content == "Hello world"
        assert result[0].metadata["reply_count"] == 2

    @pytest.mark.asyncio
    async def test_get_history_limits_to_1000(self, connector):
        """Should cap limit at 1000 per Slack API constraint."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"messages": []}, None))
        connector.get_channel_info = AsyncMock(return_value=None)
        await connector.get_channel_history("C1", limit=5000)
        call_kwargs = connector._slack_api_request.call_args[1]
        assert call_kwargs["params"]["limit"] == 1000

    @pytest.mark.asyncio
    async def test_get_history_with_oldest_and_latest(self, connector):
        """Should pass oldest and latest timestamps to API."""
        connector._slack_api_request = AsyncMock(return_value=(True, {"messages": []}, None))
        connector.get_channel_info = AsyncMock(return_value=None)
        await connector.get_channel_history("C1", oldest="100.0", latest="200.0")
        call_kwargs = connector._slack_api_request.call_args[1]
        assert call_kwargs["params"]["oldest"] == "100.0"
        assert call_kwargs["params"]["latest"] == "200.0"

    @pytest.mark.asyncio
    async def test_get_history_skips_bot_messages(self, connector):
        """Should skip bot messages when skip_bots is True (default)."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "messages": [
                        {"ts": "1.0", "user": "U1", "text": "human"},
                        {"ts": "2.0", "bot_id": "B1", "text": "bot"},
                    ]
                },
                None,
            )
        )
        connector.get_channel_info = AsyncMock(return_value=None)
        result = await connector.get_channel_history("C1")
        assert len(result) == 1
        assert result[0].content == "human"

    @pytest.mark.asyncio
    async def test_get_history_includes_bots_when_requested(self, connector):
        """Should include bot messages when skip_bots is False."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "messages": [
                        {"ts": "1.0", "user": "U1", "text": "human"},
                        {"ts": "2.0", "bot_id": "B1", "text": "bot"},
                    ]
                },
                None,
            )
        )
        connector.get_channel_info = AsyncMock(return_value=None)
        result = await connector.get_channel_history("C1", skip_bots=False)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_history_failure(self, connector):
        """Should return empty list on API failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "channel_not_found"))
        result = await connector.get_channel_history("C_BAD")
        assert result == []


# ---------------------------------------------------------------------------
# Evidence Collection Tests
# ---------------------------------------------------------------------------


class TestCollectEvidence:
    """Tests for the collect_evidence method."""

    @pytest.mark.asyncio
    async def test_collect_evidence_basic(self, connector):
        """Should collect and convert messages to ChatEvidence objects."""
        from aragora.connectors.chat.models import ChatChannel, ChatMessage, ChatUser

        msg = ChatMessage(
            id="1.0",
            platform="slack",
            channel=ChatChannel(id="C1", platform="slack"),
            author=ChatUser(id="U1", platform="slack"),
            content="Important finding",
            timestamp=datetime(2024, 1, 1),
        )
        connector.get_channel_history = AsyncMock(return_value=[msg])
        connector._enrich_with_threads = AsyncMock()

        result = await connector.collect_evidence("C1")
        assert len(result) == 1
        assert result[0].content == "Important finding"

    @pytest.mark.asyncio
    async def test_collect_evidence_empty_channel(self, connector):
        """Should return empty list when no messages found."""
        connector.get_channel_history = AsyncMock(return_value=[])
        result = await connector.collect_evidence("C1")
        assert result == []

    @pytest.mark.asyncio
    async def test_collect_evidence_filters_by_relevance(self, connector):
        """Should filter out messages below min_relevance threshold."""
        from aragora.connectors.chat.models import ChatChannel, ChatMessage, ChatUser

        channel = ChatChannel(id="C1", platform="slack")
        user = ChatUser(id="U1", platform="slack")
        msgs = [
            ChatMessage(
                id="1.0", platform="slack", channel=channel, author=user, content="python tutorial"
            ),
            ChatMessage(
                id="2.0",
                platform="slack",
                channel=channel,
                author=user,
                content="unrelated lunch topic",
            ),
        ]
        connector.get_channel_history = AsyncMock(return_value=msgs)
        connector._enrich_with_threads = AsyncMock()

        result = await connector.collect_evidence("C1", query="python", min_relevance=0.5)
        # Only the message containing "python" should pass the relevance filter
        assert all("python" in e.content.lower() for e in result)

    @pytest.mark.asyncio
    async def test_collect_evidence_sorted_by_relevance(self, connector):
        """Should sort evidence by relevance score descending."""
        from aragora.connectors.chat.models import ChatChannel, ChatMessage, ChatUser

        channel = ChatChannel(id="C1", platform="slack")
        user = ChatUser(id="U1", platform="slack")
        msgs = [
            ChatMessage(
                id="1.0", platform="slack", channel=channel, author=user, content="other topic"
            ),
            ChatMessage(
                id="2.0", platform="slack", channel=channel, author=user, content="python python"
            ),
        ]
        connector.get_channel_history = AsyncMock(return_value=msgs)
        connector._enrich_with_threads = AsyncMock()

        result = await connector.collect_evidence("C1", query="python")
        if len(result) >= 2:
            assert result[0].relevance_score >= result[1].relevance_score


# ---------------------------------------------------------------------------
# Search Messages Tests
# ---------------------------------------------------------------------------


class TestSearchMessages:
    """Tests for the search_messages method."""

    @pytest.mark.asyncio
    async def test_search_messages_success(self, connector):
        """Should return ChatEvidence list from search results."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "messages": {
                        "matches": [
                            {
                                "ts": "1609459200.000000",
                                "text": "Found this",
                                "user": "U1",
                                "username": "alice",
                                "score": 85,
                                "permalink": "https://slack.com/archives/C1/p1",
                                "channel": {"id": "C1", "name": "general"},
                            }
                        ]
                    }
                },
                None,
            )
        )
        result = await connector.search_messages("query text")
        assert len(result) == 1
        assert result[0].content == "Found this"
        assert result[0].metadata["permalink"] == "https://slack.com/archives/C1/p1"

    @pytest.mark.asyncio
    async def test_search_with_channel_filter(self, connector):
        """Should prepend channel filter to search query."""
        connector._slack_api_request = AsyncMock(
            return_value=(True, {"messages": {"matches": []}}, None)
        )
        await connector.search_messages("query", channel_id="C123")
        call_kwargs = connector._slack_api_request.call_args[1]
        assert "in:<#C123>" in call_kwargs["params"]["query"]

    @pytest.mark.asyncio
    async def test_search_messages_empty(self, connector):
        """Should return empty list when no matches."""
        connector._slack_api_request = AsyncMock(
            return_value=(True, {"messages": {"matches": []}}, None)
        )
        result = await connector.search_messages("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_messages_failure(self, connector):
        """Should return empty list on API failure."""
        connector._slack_api_request = AsyncMock(return_value=(False, None, "not_authed"))
        result = await connector.search_messages("query")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_normalizes_score(self, connector):
        """Should normalize Slack score from 0-100 to 0-1 range."""
        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "messages": {
                        "matches": [
                            {
                                "ts": "1.0",
                                "text": "match",
                                "user": "U1",
                                "score": 50,
                                "channel": {"id": "C1"},
                            }
                        ]
                    }
                },
                None,
            )
        )
        result = await connector.search_messages("query")
        assert result[0].relevance_score == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Timestamp Formatting Tests
# ---------------------------------------------------------------------------


class TestTimestampFormatting:
    """Tests for the _format_timestamp_for_api method."""

    def test_format_datetime(self, connector):
        """Should convert datetime to Unix timestamp string."""
        dt = datetime(2024, 1, 1, 0, 0, 0)
        result = connector._format_timestamp_for_api(dt)
        assert result == str(dt.timestamp())

    def test_format_string(self, connector):
        """Should pass through string timestamps."""
        result = connector._format_timestamp_for_api("1609459200.000000")
        assert result == "1609459200.000000"

    def test_format_none(self, connector):
        """Should return None for None input."""
        result = connector._format_timestamp_for_api(None)
        assert result is None

    def test_format_numeric(self, connector):
        """Should convert numeric timestamp to string."""
        result = connector._format_timestamp_for_api(1609459200)
        assert result == "1609459200"

    def test_format_float(self, connector):
        """Should convert float timestamp to string."""
        result = connector._format_timestamp_for_api(1609459200.123)
        assert result == "1609459200.123"


# ---------------------------------------------------------------------------
# Thread Enrichment Tests
# ---------------------------------------------------------------------------


class TestEnrichWithThreads:
    """Tests for the _enrich_with_threads method."""

    @pytest.mark.asyncio
    async def test_enrich_fetches_thread_replies(self, connector):
        """Should enrich evidence with thread reply data."""
        from aragora.connectors.chat.models import ChatEvidence

        evidence = ChatEvidence(
            id="ev1",
            source_id="1.0",
            platform="slack",
            channel_id="C1",
            content="root message",
            is_thread_root=True,
            metadata={"reply_count": 3},
        )

        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "messages": [
                        {"ts": "1.0", "text": "root", "user": "U1"},
                        {"ts": "1.1", "text": "Reply 1", "user": "U2"},
                        {"ts": "1.2", "text": "Reply 2", "user": "U3"},
                    ]
                },
                None,
            )
        )

        await connector._enrich_with_threads([evidence])
        assert evidence.reply_count == 2
        assert len(evidence.metadata["thread_replies"]) == 2
        assert evidence.metadata["thread_replies"][0]["text"] == "Reply 1"

    @pytest.mark.asyncio
    async def test_enrich_skips_non_thread_roots(self, connector):
        """Should skip evidence that is not a thread root."""
        from aragora.connectors.chat.models import ChatEvidence

        evidence = ChatEvidence(
            id="ev2",
            source_id="2.0",
            platform="slack",
            channel_id="C1",
            content="not a root",
            is_thread_root=False,
            metadata={"reply_count": 0},
        )

        connector._slack_api_request = AsyncMock()
        await connector._enrich_with_threads([evidence])
        connector._slack_api_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_enrich_skips_zero_reply_threads(self, connector):
        """Should skip thread roots with zero replies."""
        from aragora.connectors.chat.models import ChatEvidence

        evidence = ChatEvidence(
            id="ev3",
            source_id="3.0",
            platform="slack",
            channel_id="C1",
            content="no replies",
            is_thread_root=True,
            metadata={"reply_count": 0},
        )

        connector._slack_api_request = AsyncMock()
        await connector._enrich_with_threads([evidence])
        connector._slack_api_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_enrich_respects_limit(self, connector):
        """Should only enrich up to the specified limit of evidence items."""
        from aragora.connectors.chat.models import ChatEvidence

        evidences = [
            ChatEvidence(
                id=f"ev{i}",
                source_id=f"{i}.0",
                platform="slack",
                channel_id="C1",
                content=f"msg {i}",
                is_thread_root=True,
                metadata={"reply_count": 1},
            )
            for i in range(10)
        ]

        connector._slack_api_request = AsyncMock(
            return_value=(
                True,
                {
                    "messages": [
                        {"ts": "1.0", "text": "root"},
                        {"ts": "1.1", "text": "reply", "user": "U1"},
                    ]
                },
                None,
            )
        )

        await connector._enrich_with_threads(evidences, limit=3)
        assert connector._slack_api_request.call_count == 3
