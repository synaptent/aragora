"""Tests for Media namespace API."""

from __future__ import annotations

import pytest

from aragora_sdk.client import AragoraAsyncClient, AragoraClient


class TestMediaAudio:
    """Tests for audio file operations."""

    def test_get_audio_url(self, client: AragoraClient) -> None:
        """Get direct audio URL."""
        url = client.media.get_audio_url("audio_123")

        assert url == "https://api.aragora.ai/audio/audio_123.mp3"

    def test_list_audio_default(self, client: AragoraClient, mock_request) -> None:
        """List audio files with default parameters."""
        mock_request.return_value = {
            "audio": [{"id": "audio_1", "format": "mp3"}],
            "total": 1,
        }

        result = client.media.list_audio()

        mock_request.assert_called_once_with(
            "GET", "/api/v1/media/audio", params=None, json=None, headers=None
        )
        assert len(result["audio"]) == 1

    def test_list_audio_filtered(self, client: AragoraClient, mock_request) -> None:
        """List audio files filtered by debate."""
        mock_request.return_value = {"audio": [], "total": 0}

        client.media.list_audio(limit=10, offset=5, debate_id="debate_123")

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["limit"] == 10
        assert call_kwargs["params"]["offset"] == 5
        assert call_kwargs["params"]["debate_id"] == "debate_123"

    def test_upload_audio(self, client: AragoraClient, mock_request) -> None:
        """Upload an audio file."""
        mock_request.return_value = {"id": "audio_new", "status": "processing"}

        result = client.media.upload_audio(
            file_path="/path/to/audio.mp3",
            debate_id="debate_123",
            format="mp3",
            metadata={"title": "Test Audio"},
        )

        call_kwargs = mock_request.call_args[1]
        call_json = call_kwargs["json"]
        assert call_json["file_path"] == "/path/to/audio.mp3"
        assert call_json["debate_id"] == "debate_123"
        assert call_json["format"] == "mp3"
        assert result["status"] == "processing"


class TestMediaPodcast:
    """Tests for podcast episode operations."""

    def test_list_podcast_episodes(self, client: AragoraClient, mock_request) -> None:
        """List podcast episodes."""
        mock_request.return_value = {
            "episodes": [
                {"id": "ep_1", "title": "Episode 1"},
                {"id": "ep_2", "title": "Episode 2"},
            ],
            "total": 2,
        }

        result = client.media.list_podcast_episodes()

        mock_request.assert_called_once_with(
            "GET", "/api/v1/podcast/episodes", params=None, json=None, headers=None
        )
        assert len(result["episodes"]) == 2

    def test_list_podcast_episodes_paginated(self, client: AragoraClient, mock_request) -> None:
        """List podcast episodes with pagination."""
        mock_request.return_value = {"episodes": [], "total": 0}

        client.media.list_podcast_episodes(limit=5, offset=10)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["limit"] == 5
        assert call_kwargs["params"]["offset"] == 10

    def test_get_podcast_episode(self, client: AragoraClient, mock_request) -> None:
        """Get a specific podcast episode."""
        mock_request.return_value = {
            "id": "ep_123",
            "title": "Test Episode",
            "description": "Test description",
            "audio_url": "https://example.com/audio.mp3",
            "duration_seconds": 1800,
        }

        result = client.media.get_podcast_episode("ep_123")

        mock_request.assert_called_once_with(
            "GET",
            "/api/v1/podcast/episodes/ep_123",
            params=None,
            json=None,
            headers=None,
        )
        assert result["title"] == "Test Episode"
        assert result["duration_seconds"] == 1800

    def test_get_feed_url(self, client: AragoraClient) -> None:
        """Get podcast RSS feed URL."""
        url = client.media.get_feed_url()

        assert url == "https://api.aragora.ai/api/v1/podcast/feed.xml"

    def test_get_feed(self, client: AragoraClient, mock_request) -> None:
        """Get podcast feed metadata."""
        mock_request.return_value = {
            "title": "Aragora Debates",
            "description": "AI debate podcasts",
            "episodes": [],
        }

        result = client.media.get_feed()

        mock_request.assert_called_once_with(
            "GET", "/api/v1/podcast/feed", params=None, json=None, headers=None
        )
        assert result["title"] == "Aragora Debates"


class TestMediaConversions:
    """Tests for media conversion operations."""

    def test_convert_audio(self, client: AragoraClient, mock_request) -> None:
        """Reject conversion calls because no public route backs them."""
        with pytest.raises(NotImplementedError, match="media/audio/.*/convert"):
            client.media.convert_audio(
                audio_id="audio_123",
                target_format="aac",
                bitrate=128,
            )

        mock_request.assert_not_called()

    def test_get_transcription(self, client: AragoraClient, mock_request) -> None:
        """Reject transcription calls because no public route backs them."""
        with pytest.raises(NotImplementedError, match="media/audio/.*/transcription"):
            client.media.get_transcription("audio_123")

        mock_request.assert_not_called()


class TestAsyncMedia:
    """Tests for async media API."""

    @pytest.mark.asyncio
    async def test_async_get_audio_url(self) -> None:
        """Get audio URL asynchronously."""
        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            url = client.media.get_audio_url("audio_123")

            assert url == "https://api.aragora.ai/audio/audio_123.mp3"

    @pytest.mark.asyncio
    async def test_async_list_podcast_episodes(self, mock_async_request) -> None:
        """List podcast episodes asynchronously."""
        mock_async_request.return_value = {"episodes": [{"id": "ep_1"}], "total": 1}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.media.list_podcast_episodes()

            assert len(result["episodes"]) == 1

    @pytest.mark.asyncio
    async def test_async_get_feed_url(self) -> None:
        """Get feed URL asynchronously."""
        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            url = client.media.get_feed_url()

            assert "feed.xml" in url

    @pytest.mark.asyncio
    async def test_async_convert_audio(self, mock_async_request) -> None:
        """Reject async conversion calls because no public route backs them."""
        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            with pytest.raises(NotImplementedError, match="media/audio/.*/convert"):
                await client.media.convert_audio(
                    audio_id="audio_123",
                    target_format="wav",
                )

            mock_async_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_get_transcription(self, mock_async_request) -> None:
        """Reject async transcription calls because no public route backs them."""
        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            with pytest.raises(NotImplementedError, match="media/audio/.*/transcription"):
                await client.media.get_transcription("audio_123")

            mock_async_request.assert_not_called()
