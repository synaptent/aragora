"""
Modes Namespace API

Provides methods for operational modes:
- List available modes (Architect, Coder, Reviewer, etc.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class ModesAPI:
    """
    Synchronous Modes API.

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> modes = client.modes.list_modes()
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    def list_modes(self) -> dict[str, Any]:
        """List available operational modes."""
        return self._client.request("GET", "/api/v1/modes")


class AsyncModesAPI:
    """
    Asynchronous Modes API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     modes = await client.modes.list_modes()
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    async def list_modes(self) -> dict[str, Any]:
        """List available operational modes."""
        return await self._client.request("GET", "/api/v1/modes")
