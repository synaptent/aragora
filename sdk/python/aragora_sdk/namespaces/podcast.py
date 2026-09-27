"""
Podcast Namespace API.

Provides endpoints for generating podcast feeds from debates,
including RSS feed generation and episode management.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

AudioFormat = Literal["mp3", "aac", "m4a"]


def _warn_deprecated(message: str) -> None:
    """Emit a runtime DeprecationWarning for a dead or drifted SDK method."""
    warnings.warn(message, DeprecationWarning, stacklevel=3)


class PodcastAPI:
    """
    Synchronous Podcast API.

    Provides methods for audio content generation:
    - List and manage podcast episodes
    - Generate episodes from debates
    - Get RSS feed for subscription

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> episodes = client.podcast.list_episodes()
        >>> feed_url = client.podcast.get_feed_url()
    """

    def __init__(self, client: AragoraClient) -> None:
        self._client = client

    def list_episodes(
        self,
        limit: int | None = None,
        offset: int | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        """
        List all podcast episodes.

        Args:
            limit: Maximum episodes to return.
            offset: Pagination offset.
            since: Only episodes after this date (ISO format).

        Returns:
            List of episodes.
        """
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if since is not None:
            params["since"] = since

        return self._client._request("GET", "/api/v1/podcast/episodes", params=params)

    def get_episode(self, episode_id: str) -> dict[str, Any]:
        """
        Get a specific episode by ID.

        Args:
            episode_id: The episode ID.

        Returns:
            Episode details with audio URL and metadata.
        """
        return self._client._request("GET", f"/api/v1/podcast/episodes/{episode_id}")

    def get_feed(self) -> dict[str, Any]:
        """
        Get the full podcast feed metadata.

        Returns:
            Feed with title, description, and episodes.
        """
        return self._client._request("GET", "/api/v1/podcast/feed")

    def get_feed_url(self) -> str:
        """
        Get the RSS feed URL for podcast subscription.

        This URL can be used in podcast apps like Apple Podcasts, Spotify, etc.

        Returns:
            RSS feed URL.
        """
        base_url = getattr(self._client, "_base_url", "https://api.aragora.ai")
        return f"{base_url}/api/v1/podcast/feed.xml"

    def generate_episode(
        self,
        debate_id: str,
        title: str | None = None,
        description: str | None = None,
        voice: str | None = None,
        format: AudioFormat | None = None,
        include_intro: bool | None = None,
        include_outro: bool | None = None,
        background_music: bool | None = None,
    ) -> dict[str, Any]:
        """
        Generate a podcast episode from a debate.

        DEPRECATED: POST /api/v1/debates/{id}/podcast is not dispatched by
        any server handler; the request falls into the debate slug lookup
        and returns 404. Use debates.broadcast() (POST
        /api/v1/debates/{id}/broadcast) to generate audio from a debate,
        and list_episodes() to retrieve the results.

        Args:
            debate_id: The debate to convert to audio.
            title: Custom episode title.
            description: Custom episode description.
            voice: Voice to use for TTS.
            format: Audio format (mp3, aac, m4a).
            include_intro: Add intro segment.
            include_outro: Add outro segment.
            background_music: Add background music.
        """
        _warn_deprecated(
            "podcast.generate_episode() targets an unserved route (404 via "
            "slug fallback); use debates.broadcast() and list_episodes()."
        )
        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description
        if voice is not None:
            data["voice"] = voice
        if format is not None:
            data["format"] = format
        if include_intro is not None:
            data["include_intro"] = include_intro
        if include_outro is not None:
            data["include_outro"] = include_outro
        if background_music is not None:
            data["background_music"] = background_music

        return self._client._request("POST", f"/api/v1/debates/{debate_id}/podcast", json=data)

    def delete_episode(self, episode_id: str) -> dict[str, Any]:
        """
        Delete a podcast episode.

        Args:
            episode_id: The episode to delete.

        Returns:
            Deletion confirmation.
        """
        return self._client._request("DELETE", f"/api/v1/podcast/episodes/{episode_id}")

    def update_episode(
        self,
        episode_id: str,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """
        Update episode metadata.

        Args:
            episode_id: The episode to update.
            title: New title.
            description: New description.

        Returns:
            Updated episode.
        """
        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description

        return self._client._request("PATCH", f"/api/v1/podcast/episodes/{episode_id}", json=data)


class AsyncPodcastAPI:
    """Asynchronous Podcast API."""

    def __init__(self, client: AragoraAsyncClient) -> None:
        self._client = client

    async def list_episodes(
        self,
        limit: int | None = None,
        offset: int | None = None,
        since: str | None = None,
    ) -> dict[str, Any]:
        """List all podcast episodes."""
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if since is not None:
            params["since"] = since

        return await self._client._request("GET", "/api/v1/podcast/episodes", params=params)

    async def get_episode(self, episode_id: str) -> dict[str, Any]:
        """Get a specific episode by ID."""
        return await self._client._request("GET", f"/api/v1/podcast/episodes/{episode_id}")

    async def get_feed(self) -> dict[str, Any]:
        """Get the full podcast feed metadata."""
        return await self._client._request("GET", "/api/v1/podcast/feed")

    def get_feed_url(self) -> str:
        """Get the RSS feed URL for podcast subscription."""
        base_url = getattr(self._client, "_base_url", "https://api.aragora.ai")
        return f"{base_url}/api/v1/podcast/feed.xml"

    async def generate_episode(
        self,
        debate_id: str,
        title: str | None = None,
        description: str | None = None,
        voice: str | None = None,
        format: AudioFormat | None = None,
        include_intro: bool | None = None,
        include_outro: bool | None = None,
        background_music: bool | None = None,
    ) -> dict[str, Any]:
        """Generate a podcast episode from a debate.

        DEPRECATED: POST /api/v1/debates/{id}/podcast is not dispatched by
        any server handler; the request falls into the debate slug lookup
        and returns 404. Use debates.broadcast() and list_episodes().
        """
        _warn_deprecated(
            "podcast.generate_episode() targets an unserved route (404 via "
            "slug fallback); use debates.broadcast() and list_episodes()."
        )
        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description
        if voice is not None:
            data["voice"] = voice
        if format is not None:
            data["format"] = format
        if include_intro is not None:
            data["include_intro"] = include_intro
        if include_outro is not None:
            data["include_outro"] = include_outro
        if background_music is not None:
            data["background_music"] = background_music

        return await self._client._request(
            "POST", f"/api/v1/debates/{debate_id}/podcast", json=data
        )

    async def delete_episode(self, episode_id: str) -> dict[str, Any]:
        """Delete a podcast episode."""
        return await self._client._request("DELETE", f"/api/v1/podcast/episodes/{episode_id}")

    async def update_episode(
        self,
        episode_id: str,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Update episode metadata."""
        data: dict[str, Any] = {}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description

        return await self._client._request(
            "PATCH", f"/api/v1/podcast/episodes/{episode_id}", json=data
        )
