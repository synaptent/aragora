"""Tests for typing indicator functionality across chat connectors."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestTelegramTypingIndicator:
    """Tests for Telegram typing indicator."""

    @pytest.fixture
    def connector(self):
        """Create Telegram connector."""
        with patch("aragora.connectors.chat.telegram.HTTPX_AVAILABLE", True):
            from aragora.connectors.chat.telegram import TelegramConnector

            return TelegramConnector(bot_token="test_token")

    @pytest.mark.asyncio
    async def test_sends_typing_action(self, connector):
        """Test that typing indicator sends sendChatAction."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}

        with patch("aragora.connectors.chat.telegram.httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await connector.send_typing_indicator("123456789")

            assert result is True
            mock_client_instance.post.assert_called_once()
            call_args = mock_client_instance.post.call_args
            assert "sendChatAction" in call_args[0][0]
            assert call_args[1]["json"]["action"] == "typing"
            assert call_args[1]["json"]["chat_id"] == "123456789"

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self, connector):
        """Test that typing indicator returns False on API failure."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": False, "description": "Bad Request"}

        with patch("aragora.connectors.chat.telegram.httpx.AsyncClient") as mock_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await connector.send_typing_indicator("123456789")

            assert result is False


class TestTeamsTypingIndicator:
    """Tests for Teams typing indicator."""

    @pytest.fixture
    def connector(self):
        """Create Teams connector."""
        with patch("aragora.connectors.chat.teams._constants.HTTPX_AVAILABLE", True):
            from aragora.connectors.chat.teams import TeamsConnector

            return TeamsConnector(
                bot_id="bot_123",
                bot_name="TestBot",
                app_id="app_123",
                app_password="password",
            )

    @pytest.mark.asyncio
    async def test_sends_typing_activity(self, connector):
        """Test that typing indicator sends typing activity via _http_request."""
        with patch.object(connector, "_get_access_token", new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "test_token"

            with patch.object(connector, "_http_request", new_callable=AsyncMock) as mock_http:
                mock_http.return_value = (True, {"status": "ok"}, None)

                result = await connector.send_typing_indicator("conv_123")

                assert result is True
                mock_http.assert_called_once()
                call_kwargs = mock_http.call_args[1]
                assert call_kwargs["method"] == "POST"
                assert "activities" in call_kwargs["url"]
                assert call_kwargs["json"]["type"] == "typing"

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self, connector):
        """Test that typing indicator returns False on API failure."""
        with patch.object(connector, "_get_access_token", new_callable=AsyncMock) as mock_token:
            mock_token.return_value = "test_token"

            with patch.object(connector, "_http_request", new_callable=AsyncMock) as mock_http:
                mock_http.return_value = (False, None, "HTTP 500")

                result = await connector.send_typing_indicator("conv_123")

                assert result is False


class TestDiscordTypingIndicator:
    """Tests for Discord typing indicator."""

    @pytest.fixture
    def connector(self):
        """Create Discord connector."""
        with patch("aragora.connectors.chat.discord.HTTPX_AVAILABLE", True):
            from aragora.connectors.chat.discord import DiscordConnector

            return DiscordConnector(bot_token="test_token")

    @pytest.mark.asyncio
    async def test_sends_typing_request(self, connector):
        """Test that typing indicator sends POST to typing endpoint."""
        with patch.object(
            connector, "_http_request", return_value=(True, None, None)
        ) as mock_request:
            result = await connector.send_typing_indicator("channel_123")

            assert result is True
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert "typing" in call_args[1]["url"]
            assert call_args[1]["method"] == "POST"

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self, connector):
        """Test that typing indicator returns False on API failure."""
        with patch.object(connector, "_http_request", return_value=(False, None, "Error")):
            result = await connector.send_typing_indicator("channel_123")

            assert result is False


class TestBaseConnectorTypingIndicator:
    """Tests for base connector default typing indicator behavior."""

    def test_default_returns_false(self):
        """Test that base connector returns False for unsupported platforms."""
        from aragora.connectors.chat.base import ChatPlatformConnector

        # Create a concrete implementation for testing
        class TestConnector(ChatPlatformConnector):
            @property
            def platform_name(self):
                return "test"

            @property
            def platform_display_name(self):
                return "Test Platform"

            async def send_message(self, *args, **kwargs):
                pass

            async def update_message(self, *args, **kwargs):
                pass

            async def delete_message(self, *args, **kwargs):
                pass

            async def respond_to_command(self, *args, **kwargs):
                pass

            async def respond_to_interaction(self, *args, **kwargs):
                pass

            async def upload_file(self, *args, **kwargs):
                pass

            async def download_file(self, *args, **kwargs):
                pass

            def format_blocks(self, *args, **kwargs):
                pass

            def format_button(self, *args, **kwargs):
                pass

            def verify_webhook(self, *args, **kwargs):
                pass

            def parse_webhook_event(self, *args, **kwargs):
                pass

        connector = TestConnector()

        @pytest.mark.asyncio
        async def check():
            result = await connector.send_typing_indicator("channel_123")
            assert result is False

        import asyncio

        asyncio.run(check())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
