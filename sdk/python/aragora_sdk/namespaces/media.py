"""
Media Namespace API.

Provides access to media assets including audio files and podcast episodes.

Features:
- Audio file metadata retrieval
- Direct audio URL generation
- Podcast episode management
- RSS feed access
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

AudioFormat = Literal["mp3", "aac", "m4a", "wav", "ogg"]


class MediaAPI:
    """
    Synchronous Media API.

    Provides methods for media asset access:
    - Build direct audio URLs
    - List and browse podcast episodes
    - Access RSS feed for subscription
    - Media format conversions

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> audio_url = client.media.get_audio_url("debate_123")
        >>> episodes = client.media.list_podcast_episodes()
        >>> feed_url = client.media.get_feed_url()
    """

    def __init__(self, client: AragoraClient) -> None:
        self._client = client

    # =========================================================================
    # Audio Files
    # =========================================================================

    def get_audio_url(self, audio_id: str) -> str:
        """
        Get the direct audio file URL for a debate or audio file.

        This URL can be used to stream or download the audio file directly.

        Args:
            audio_id: The audio file identifier.

        Returns:
            Direct URL to the audio file in MP3 format.
        """
        base_url = getattr(self._client, "_base_url", "https://api.aragora.ai")
        return f"{base_url}/audio/{audio_id}.mp3"

    def list_audio(
        self,
        limit: int | None = None,
        offset: int | None = None,
        debate_id: str | None = None,
    ) -> dict[str, Any]:
        """
        List audio files.

        Args:
            limit: Maximum number of files to return.
            offset: Pagination offset.
            debate_id: Filter by associated debate ID.

        Returns:
            Dict with list of audio files and total count.
        """
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if debate_id is not None:
            params["debate_id"] = debate_id

        return self._client._request(
            "GET",
            "/api/v1/media/audio",
            params=params if params else None,
        )

    def upload_audio(
        self,
        file_path: str,
        debate_id: str | None = None,
        format: AudioFormat | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Upload an audio file.

        Args:
            file_path: Path to the audio file.
            debate_id: Optional debate ID to associate with.
            format: Audio format (mp3, aac, m4a, wav, ogg).
            metadata: Optional metadata for the audio file.

        Returns:
            Dict with uploaded audio file details.
        """
        data: dict[str, Any] = {"file_path": file_path}
        if debate_id is not None:
            data["debate_id"] = debate_id
        if format is not None:
            data["format"] = format
        if metadata is not None:
            data["metadata"] = metadata

        return self._client._request("POST", "/api/v1/media/audio", json=data)

    # =========================================================================
    # Podcast Episodes
    # =========================================================================

    def list_podcast_episodes(
        self,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """
        List podcast episodes.

        Args:
            limit: Maximum number of episodes to return.
            offset: Pagination offset.

        Returns:
            Dict with list of episodes and total count.
        """
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        return self._client._request(
            "GET",
            "/api/v1/podcast/episodes",
            params=params if params else None,
        )

    def get_podcast_episode(self, episode_id: str) -> dict[str, Any]:
        """
        Get a specific podcast episode.

        Args:
            episode_id: The episode identifier.

        Returns:
            Episode details including title, description, audio URL, and duration.
        """
        return self._client._request("GET", f"/api/v1/podcast/episodes/{episode_id}")

    def get_feed_url(self) -> str:
        """
        Get the podcast RSS feed URL.

        This URL can be used in podcast apps like Apple Podcasts, Spotify, etc.

        Returns:
            RSS feed URL for podcast subscription.
        """
        base_url = getattr(self._client, "_base_url", "https://api.aragora.ai")
        return f"{base_url}/api/v1/podcast/feed.xml"

    def get_feed(self) -> dict[str, Any]:
        """
        Get the full podcast feed metadata.

        Returns:
            Feed metadata including title, description, and episodes.
        """
        return self._client._request("GET", "/api/v1/podcast/feed")

    # =========================================================================
    # Unsupported Media Operations
    # =========================================================================

    def convert_audio(
        self,
        audio_id: str,
        target_format: AudioFormat,
        bitrate: int | None = None,
    ) -> dict[str, Any]:
        """
        Guard unsupported conversion access until the API publishes this route.

        Args:
            audio_id: The source audio file identifier.
            target_format: Target format (mp3, aac, m4a, wav, ogg).
            bitrate: Optional target bitrate in kbps.

        Raises:
            NotImplementedError: The public API does not expose this route.
        """
        raise NotImplementedError(
            "POST /api/v1/media/audio/{audio_id}/convert is not part of the current "
            "Aragora API contract."
        )

    def get_transcription(self, audio_id: str) -> dict[str, Any]:
        """
        Guard unsupported transcription access until the API publishes this route.

        Args:
            audio_id: The audio file identifier.

        Raises:
            NotImplementedError: The public API does not expose this route.
        """
        raise NotImplementedError(
            "GET /api/v1/media/audio/{audio_id}/transcription is not part of the current "
            "Aragora API contract."
        )


class AsyncMediaAPI:
    """
    Asynchronous Media API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     episodes = await client.media.list_podcast_episodes()
        ...     print(f"Found {len(episodes['episodes'])} episodes")
    """

    def __init__(self, client: AragoraAsyncClient) -> None:
        self._client = client

    # =========================================================================
    # Audio Files
    # =========================================================================

    def get_audio_url(self, audio_id: str) -> str:
        """Get the direct audio file URL."""
        base_url = getattr(self._client, "_base_url", "https://api.aragora.ai")
        return f"{base_url}/audio/{audio_id}.mp3"

    async def list_audio(
        self,
        limit: int | None = None,
        offset: int | None = None,
        debate_id: str | None = None,
    ) -> dict[str, Any]:
        """List audio files."""
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if debate_id is not None:
            params["debate_id"] = debate_id

        return await self._client._request(
            "GET",
            "/api/v1/media/audio",
            params=params if params else None,
        )

    async def upload_audio(
        self,
        file_path: str,
        debate_id: str | None = None,
        format: AudioFormat | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Upload an audio file."""
        data: dict[str, Any] = {"file_path": file_path}
        if debate_id is not None:
            data["debate_id"] = debate_id
        if format is not None:
            data["format"] = format
        if metadata is not None:
            data["metadata"] = metadata

        return await self._client._request("POST", "/api/v1/media/audio", json=data)

    # =========================================================================
    # Podcast Episodes
    # =========================================================================

    async def list_podcast_episodes(
        self,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """List podcast episodes."""
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        return await self._client._request(
            "GET",
            "/api/v1/podcast/episodes",
            params=params if params else None,
        )

    async def get_podcast_episode(self, episode_id: str) -> dict[str, Any]:
        """Get a specific podcast episode."""
        return await self._client._request("GET", f"/api/v1/podcast/episodes/{episode_id}")

    def get_feed_url(self) -> str:
        """Get the podcast RSS feed URL."""
        base_url = getattr(self._client, "_base_url", "https://api.aragora.ai")
        return f"{base_url}/api/v1/podcast/feed.xml"

    async def get_feed(self) -> dict[str, Any]:
        """Get the full podcast feed metadata."""
        return await self._client._request("GET", "/api/v1/podcast/feed")

    # =========================================================================
    # Unsupported Media Operations
    # =========================================================================

    async def convert_audio(
        self,
        audio_id: str,
        target_format: AudioFormat,
        bitrate: int | None = None,
    ) -> dict[str, Any]:
        """Guard unsupported conversion access until the API publishes this route."""
        raise NotImplementedError(
            "POST /api/v1/media/audio/{audio_id}/convert is not part of the current "
            "Aragora API contract."
        )

    async def get_transcription(self, audio_id: str) -> dict[str, Any]:
        """Guard unsupported transcription access until the API publishes this route."""
        raise NotImplementedError(
            "GET /api/v1/media/audio/{audio_id}/transcription is not part of the current "
            "Aragora API contract."
        )
