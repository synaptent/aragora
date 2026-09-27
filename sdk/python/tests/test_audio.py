"""Tests for Audio namespace API."""

from __future__ import annotations

import pytest

from aragora_sdk.client import AragoraAsyncClient, AragoraClient


class TestAudioUrls:
    """Tests for audio URL generation."""

    def test_get_audio_url(self, client: AragoraClient) -> None:
        """Get direct URL for an audio file."""
        url = client.audio.get_audio_url("audio_123")

        assert url == "https://api.aragora.ai/audio/audio_123.mp3"

    def test_get_feed_url(self, client: AragoraClient) -> None:
        """Get podcast RSS feed URL."""
        url = client.audio.get_feed_url()

        assert url == "https://api.aragora.ai/api/v1/podcast/feed.xml"


class TestAudioInfo:
    """Tests for audio file metadata."""

    def test_get_audio_info(self, client: AragoraClient, mock_request) -> None:
        """Get audio file metadata."""
        mock_request.return_value = {
            "id": "audio_123",
            "format": "mp3",
            "duration_seconds": 300,
            "size_bytes": 5000000,
        }

        result = client.audio.get_audio_info("audio_123")

        mock_request.assert_called_once_with(
            "GET", "/api/v1/media/audio", params={"audio_id": "audio_123"}
        )
        assert result["format"] == "mp3"
        assert result["duration_seconds"] == 300


class TestAudioEpisodes:
    """Tests for podcast episode operations."""

    def test_list_episodes_default(self, client: AragoraClient, mock_request) -> None:
        """List episodes with default parameters."""
        mock_request.return_value = {
            "episodes": [{"id": "ep_1", "title": "Test Episode"}],
            "total": 1,
        }

        result = client.audio.list_episodes()

        mock_request.assert_called_once_with("GET", "/api/v1/podcast/episodes", params=None)
        assert len(result["episodes"]) == 1

    def test_list_episodes_with_pagination(self, client: AragoraClient, mock_request) -> None:
        """List episodes with pagination."""
        mock_request.return_value = {"episodes": [], "total": 0}

        client.audio.list_episodes(limit=10, offset=20)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["limit"] == 10
        assert call_kwargs["params"]["offset"] == 20

    def test_get_episode(self, client: AragoraClient, mock_request) -> None:
        """Get a specific episode."""
        mock_request.return_value = {
            "id": "ep_123",
            "title": "Test Episode",
            "audio_url": "https://example.com/audio.mp3",
            "duration_seconds": 600,
        }

        result = client.audio.get_episode("ep_123")

        mock_request.assert_called_once_with(
            "GET",
            "/api/v1/podcast/episodes/ep_123",
        )
        assert result["title"] == "Test Episode"


class TestAsyncAudio:
    """Tests for async audio API."""

    @pytest.mark.asyncio
    async def test_async_get_audio_url(self) -> None:
        """Get audio URL asynchronously."""
        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            url = client.audio.get_audio_url("audio_456")

            assert url == "https://api.aragora.ai/audio/audio_456.mp3"

    @pytest.mark.asyncio
    async def test_async_get_audio_info(self, mock_async_request) -> None:
        """Get audio info asynchronously."""
        mock_async_request.return_value = {"id": "audio_456", "format": "mp3"}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.audio.get_audio_info("audio_456")

            assert result["id"] == "audio_456"

    @pytest.mark.asyncio
    async def test_async_list_episodes(self, mock_async_request) -> None:
        """List episodes asynchronously."""
        mock_async_request.return_value = {
            "episodes": [{"id": "ep_1"}],
            "total": 1,
        }

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.audio.list_episodes()

            assert len(result["episodes"]) == 1

    @pytest.mark.asyncio
    async def test_async_get_episode(self, mock_async_request) -> None:
        """Get episode asynchronously."""
        mock_async_request.return_value = {"id": "ep_async", "title": "Async Episode"}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.audio.get_episode("ep_async")

            assert result["title"] == "Async Episode"

    @pytest.mark.asyncio
    async def test_async_get_feed_url(self) -> None:
        """Get feed URL asynchronously."""
        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            url = client.audio.get_feed_url()

            assert url == "https://api.aragora.ai/api/v1/podcast/feed.xml"
