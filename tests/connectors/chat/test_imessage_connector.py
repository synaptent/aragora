"""
Tests for iMessage Connector (via BlueBubbles).

Tests cover:
- Initialization and configuration
- Message sending
- Error handling
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from aragora.connectors.chat.imessage import IMessageConnector
from aragora.connectors.chat.models import SendMessageResponse


class TestIMessageConnectorInit:
    """Tests for IMessageConnector initialization."""

    def test_custom_initialization(self):
        """Test connector with custom settings."""
        connector = IMessageConnector(
            server_url="http://custom:5000",
            password="custom-password",
        )
        assert connector._server_url == "http://custom:5000"
        assert connector._password == "custom-password"
        assert connector.platform_name == "imessage"
        assert connector.platform_display_name == "iMessage"

    def test_is_configured(self):
        """Test is_configured check."""
        connector = IMessageConnector(
            server_url="http://localhost:1234",
            password="test",
        )
        assert connector.is_configured is True

    def test_not_configured_missing_password(self):
        """Test is_configured when password is missing."""
        connector = IMessageConnector(
            server_url="http://localhost:1234",
            password="",
        )
        assert connector.is_configured is False


class TestIMessageConnectorMessages:
    """Tests for message operations."""

    @pytest.fixture
    def connector(self):
        """Create a configured connector."""
        return IMessageConnector(
            server_url="http://localhost:1234",
            password="test-password",
        )

    @pytest.mark.asyncio
    async def test_send_message_success(self, connector):
        """Test successful message sending."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": 200, "data": {"guid": "msg-123"}}'
        mock_response.json.return_value = {"status": 200, "data": {"guid": "msg-123"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await connector.send_message(
                channel_id="+1234567890",
                text="Hello from iMessage!",
            )

            assert result.success is True

    @pytest.mark.asyncio
    async def test_send_message_to_chat(self, connector):
        """Test sending message to existing chat by GUID."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": 200, "data": {"guid": "msg-456"}}'
        mock_response.json.return_value = {"status": 200, "data": {"guid": "msg-456"}}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await connector.send_message(
                channel_id="chat-guid-abc123",
                text="Hello chat!",
            )

            assert result.success is True

    @pytest.mark.asyncio
    async def test_send_message_error(self, connector):
        """Test handling HTTP error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await connector.send_message(
                channel_id="+1234567890",
                text="Hello!",
            )

            assert result.success is False

    @pytest.mark.asyncio
    async def test_send_message_raises_contextual_runtime_error(self, connector):
        """Test send_message preserves cause while adding chat context."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.ConnectError("boom")
            )

            with pytest.raises(RuntimeError) as exc_info:
                await connector.send_message(
                    channel_id="+1234567890",
                    text="Hello!",
                )

            assert "+1234567890" in str(exc_info.value)
            assert isinstance(exc_info.value.__cause__, httpx.ConnectError)

    @pytest.mark.asyncio
    async def test_update_message_not_supported(self, connector):
        """Test that update_message returns failure (iMessage doesn't support it)."""
        result = await connector.update_message(
            channel_id="+1234567890",
            message_id="msg-123",
            text="Updated text",
        )

        assert result.success is False


class TestIMessageConnectorFiles:
    """Tests for file operations."""

    @pytest.fixture
    def connector(self):
        """Create a configured connector."""
        return IMessageConnector(
            server_url="http://localhost:1234",
            password="test-password",
        )

    @pytest.mark.asyncio
    async def test_download_file(self, connector):
        """Test file download."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"downloaded image data"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await connector.download_file("attachment-guid-123")

            assert result is not None


class TestIMessageConnectorCircuitBreaker:
    """Tests for circuit breaker behavior."""

    @pytest.fixture
    def connector(self):
        """Create a configured connector."""
        return IMessageConnector(
            server_url="http://localhost:1234",
            password="test-password",
        )

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self, connector):
        """Test that circuit breaker opens after consecutive failures."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "BlueBubbles server error"

        with patch("httpx.AsyncClient") as mock_client:
            post_mock = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = post_mock

            # HTTP 500 is reported as a failed send (never raised) and counted
            # against the breaker; once it opens, the remaining calls short-circuit.
            for _ in range(10):
                result = await connector.send_message("+1234567890", "test")
                assert result.success is False
            assert post_mock.await_count == connector._circuit_breaker_threshold

            # Circuit breaker is now open: the call fails fast without an HTTP request
            result = await connector.send_message("+1234567890", "test")
            assert result.success is False
            assert "Circuit breaker open for imessage" in result.error
            assert post_mock.await_count == connector._circuit_breaker_threshold
