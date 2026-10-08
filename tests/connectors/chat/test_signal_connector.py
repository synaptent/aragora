"""
Tests for Signal Messenger Connector.

Tests cover:
- Initialization and configuration
- Message sending
- Error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from aragora.connectors.chat.signal import SignalConnector
from aragora.connectors.chat.models import SendMessageResponse


class TestSignalConnectorInit:
    """Tests for SignalConnector initialization."""

    def test_custom_initialization(self):
        """Test connector with custom settings."""
        connector = SignalConnector(
            api_url="http://custom:9000/",
            phone_number="+9876543210",
        )
        assert connector._api_url == "http://custom:9000"
        assert connector._phone_number == "+9876543210"
        assert connector.platform_name == "signal"
        assert connector.platform_display_name == "Signal"

    def test_is_configured(self):
        """Test is_configured check."""
        connector = SignalConnector(
            api_url="http://localhost:8080",
            phone_number="+1234567890",
        )
        assert connector.is_configured is True

    def test_not_configured_missing_phone(self):
        """Test is_configured when phone is missing."""
        connector = SignalConnector(
            api_url="http://localhost:8080",
            phone_number="",
        )
        assert connector.is_configured is False


class TestSignalConnectorMessages:
    """Tests for message operations."""

    @pytest.fixture
    def connector(self):
        """Create a configured connector."""
        return SignalConnector(
            api_url="http://localhost:8080",
            phone_number="+1234567890",
        )

    @pytest.mark.asyncio
    async def test_send_message_success(self, connector):
        """Test successful message sending."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"timestamp": 1234567890000}'
        mock_response.json.return_value = {"timestamp": 1234567890000}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await connector.send_message(
                channel_id="+9876543210",
                text="Hello, Signal!",
            )

            assert result.success is True
            assert result.channel_id == "+9876543210"
            assert result.message_id == "1234567890000"

    @pytest.mark.asyncio
    async def test_send_message_to_group(self, connector):
        """Test sending message to a group."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"timestamp": 1234567890000}'
        mock_response.json.return_value = {"timestamp": 1234567890000}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await connector.send_message(
                channel_id="group.abc123",
                text="Hello group!",
            )

            assert result.success is True

    @pytest.mark.asyncio
    async def test_send_message_rate_limited(self, connector):
        """Test handling rate limit (429)."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Too many requests"

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await connector.send_message(
                channel_id="+9876543210",
                text="Hello!",
            )

            assert result.success is False
            assert "rate limit" in result.error.lower()

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
                channel_id="+9876543210",
                text="Hello!",
            )

            assert result.success is False
            assert "500" in result.error

    @pytest.mark.asyncio
    async def test_update_message_not_supported(self, connector):
        """Test that update_message returns failure (Signal doesn't support it)."""
        result = await connector.update_message(
            channel_id="+9876543210",
            message_id="123",
            text="Updated text",
        )

        assert result.success is False


class TestSignalConnectorCircuitBreaker:
    """Tests for circuit breaker behavior."""

    @pytest.fixture
    def connector(self):
        """Create a configured connector."""
        return SignalConnector(
            api_url="http://localhost:8080",
            phone_number="+1234567890",
        )

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self, connector):
        """Test that circuit breaker opens after consecutive failures."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server error"

        with patch("httpx.AsyncClient") as mock_client:
            post_mock = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = post_mock

            # HTTP 500 is reported as a failed send (never raised) and counted
            # against the breaker; once it opens, the remaining calls short-circuit.
            for _ in range(10):
                result = await connector.send_message("+9876543210", "test")
                assert result.success is False
            assert post_mock.await_count == connector._circuit_breaker_threshold

            # Circuit breaker is now open: the call fails fast without an HTTP request
            result = await connector.send_message("+9876543210", "test")
            assert result.success is False
            assert "Circuit breaker open for signal" in result.error
            assert post_mock.await_count == connector._circuit_breaker_threshold
