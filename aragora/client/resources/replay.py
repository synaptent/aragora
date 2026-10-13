"""Replay API resource for debate replays."""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.client.client import AragoraClient

from aragora.client.models import Replay, ReplaySummary


class ReplayAPI:
    """API interface for debate replays."""

    def __init__(self, client: AragoraClient):
        self._client = client

    def list(
        self,
        limit: int = 20,
        debate_id: str | None = None,
    ) -> builtins.list[ReplaySummary]:
        """
        List available debate replays.

        Args:
            limit: Maximum number of replays to return.
            debate_id: Optional filter by debate ID.

        Returns:
            List of ReplaySummary objects.
        """
        params: dict[str, Any] = {"limit": limit}
        if debate_id:
            params["debate_id"] = debate_id

        response = self._client._get("/api/replays", params=params)
        replays = response.get("replays", response) if isinstance(response, dict) else response
        return [ReplaySummary(**r) for r in replays]

    async def list_async(
        self,
        limit: int = 20,
        debate_id: str | None = None,
    ) -> builtins.list[ReplaySummary]:
        """Async version of list()."""
        params: dict[str, Any] = {"limit": limit}
        if debate_id:
            params["debate_id"] = debate_id

        response = await self._client._get_async("/api/replays", params=params)
        replays = response.get("replays", response) if isinstance(response, dict) else response
        return [ReplaySummary(**r) for r in replays]

    def get(self, replay_id: str) -> Replay:
        """
        Get full replay by ID.

        Args:
            replay_id: The replay ID.

        Returns:
            Replay with full event timeline.
        """
        response = self._client._get(f"/api/replays/{replay_id}")
        return Replay(**response)

    async def get_async(self, replay_id: str) -> Replay:
        """Async version of get()."""
        response = await self._client._get_async(f"/api/replays/{replay_id}")
        return Replay(**response)

    def delete(self, replay_id: str) -> bool:
        """
        Delete a replay.

        Args:
            replay_id: The replay ID to delete.

        Returns:
            True if deleted successfully.
        """
        self._client._delete(f"/api/replays/{replay_id}")
        return True

    async def delete_async(self, replay_id: str) -> bool:
        """Async version of delete()."""
        await self._client._delete_async(f"/api/replays/{replay_id}")
        return True


__all__ = ["ReplayAPI"]
