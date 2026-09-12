"""
Spectate Namespace API

Provides methods for real-time debate observation:
- Read recent, status, and stream snapshots
- Inject events into the spectate bridge
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class SpectateAPI:
    """
    Synchronous Spectate API.

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> stream = client.spectate.get_stream(debate_id="debate-123")
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    def get_recent(self, *, count: int = 50, debate_id: str | None = None) -> dict[str, Any]:
        """Get recent buffered spectate events."""
        params: dict[str, Any] = {"count": count}
        if debate_id:
            params["debate_id"] = debate_id
        return self._client.request("GET", "/api/v1/spectate/recent", params=params)

    def get_status(self) -> dict[str, Any]:
        """Get spectate bridge status (active sessions, subscribers, buffer size)."""
        return self._client.request("GET", "/api/v1/spectate/status")

    def get_stream(self, *, count: int = 50, debate_id: str | None = None) -> dict[str, Any]:
        """Get spectate event stream snapshot."""
        params: dict[str, Any] = {"count": count}
        if debate_id:
            params["debate_id"] = debate_id
        return self._client.request("GET", "/api/v1/spectate/stream", params=params)

    def emit(self, **kwargs: Any) -> dict[str, Any]:
        """Inject one or more events into the spectate bridge."""
        return self._client.request("POST", "/api/v1/spectate/emit", json=kwargs)


class AsyncSpectateAPI:
    """
    Asynchronous Spectate API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     stream = await client.spectate.get_stream(debate_id="debate-123")
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    async def get_recent(self, *, count: int = 50, debate_id: str | None = None) -> dict[str, Any]:
        """Get recent buffered spectate events."""
        params: dict[str, Any] = {"count": count}
        if debate_id:
            params["debate_id"] = debate_id
        return await self._client.request("GET", "/api/v1/spectate/recent", params=params)

    async def get_status(self) -> dict[str, Any]:
        """Get spectate bridge status (active sessions, subscribers, buffer size)."""
        return await self._client.request("GET", "/api/v1/spectate/status")

    async def get_stream(self, *, count: int = 50, debate_id: str | None = None) -> dict[str, Any]:
        """Get spectate event stream snapshot."""
        params: dict[str, Any] = {"count": count}
        if debate_id:
            params["debate_id"] = debate_id
        return await self._client.request("GET", "/api/v1/spectate/stream", params=params)

    async def emit(self, **kwargs: Any) -> dict[str, Any]:
        """Inject one or more events into the spectate bridge."""
        return await self._client.request("POST", "/api/v1/spectate/emit", json=kwargs)
