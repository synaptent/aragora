"""
Checkpoints Namespace API.

Provides debate checkpoint management for pause, resume, and intervention.

Features:
- Debate checkpoint creation and management
- Pause and resume debate functionality
- Human intervention support
- Knowledge Mound checkpoint management
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

CheckpointStatus = Literal["active", "resumed", "expired"]


def _warn_deprecated(message: str) -> None:
    """Emit a runtime DeprecationWarning for a dead or drifted SDK method."""
    warnings.warn(message, DeprecationWarning, stacklevel=3)


class CheckpointsAPI:
    """
    Synchronous Checkpoints API.

    Provides methods for checkpoint management:
    - List and manage debate checkpoints
    - Pause and resume debates
    - Perform human interventions
    - Knowledge Mound checkpoint operations

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> # List active checkpoints
        >>> checkpoints = client.checkpoints.list()
        >>> # Pause a running debate
        >>> checkpoint = client.checkpoints.pause_debate("debate_123")
        >>> # Resume later
        >>> result = client.checkpoints.resume(checkpoint['id'])
    """

    def __init__(self, client: AragoraClient) -> None:
        self._client = client

    # =========================================================================
    # Debate Checkpoints
    # =========================================================================

    def list(
        self,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """
        List all checkpoints.

        Args:
            limit: Maximum number of checkpoints to return.
            offset: Pagination offset.

        Returns:
            Dict with list of checkpoints and total count.
        """
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        return self._client._request(
            "GET",
            "/api/v1/checkpoints",
            params=params if params else None,
        )

    def list_resumable(self) -> dict[str, Any]:
        """
        Get resumable debates with active checkpoints.

        Returns:
            Dict with list of resumable debates, each containing
            debate_id, checkpoint_id, task, round, and paused_at.
        """
        return self._client._request("GET", "/api/v1/checkpoints/resumable")

    def get(self, checkpoint_id: str) -> dict[str, Any]:
        """
        Get a specific checkpoint.

        Args:
            checkpoint_id: The checkpoint identifier.

        Returns:
            Checkpoint details including id, debate_id, status, round,
            created_at, expires_at, and metadata.
        """
        return self._client._request("GET", f"/api/v1/checkpoints/{checkpoint_id}")

    def resume(self, checkpoint_id: str) -> dict[str, Any]:
        """
        Resume a debate from a checkpoint.

        Args:
            checkpoint_id: The checkpoint identifier.

        Returns:
            Dict with debate_id and resumed status.
        """
        return self._client._request("POST", f"/api/v1/checkpoints/{checkpoint_id}/resume")

    def delete(self, checkpoint_id: str) -> dict[str, Any]:
        """
        Delete a checkpoint.

        Args:
            checkpoint_id: The checkpoint identifier.

        Returns:
            Dict confirming deletion.
        """
        return self._client._request("DELETE", f"/api/v1/checkpoints/{checkpoint_id}")

    def intervene(
        self,
        checkpoint_id: str,
        action: str,
        message: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Perform an intervention on a checkpointed debate.

        Allows human operators to modify debate parameters or inject
        information before resuming.

        Args:
            checkpoint_id: The checkpoint identifier.
            action: The intervention action (e.g., 'inject_context', 'modify_agents').
            message: Optional message to inject.
            config: Optional configuration changes.

        Returns:
            Dict with success status and optional message.
        """
        data: dict[str, Any] = {"action": action}
        if message is not None:
            data["message"] = message
        if config is not None:
            data["config"] = config

        return self._client._request(
            "POST",
            f"/api/v1/checkpoints/{checkpoint_id}/intervention",
            json=data,
        )

    # =========================================================================
    # Debate-Specific Checkpoint Operations
    # =========================================================================

    def list_for_debate(self, debate_id: str) -> dict[str, Any]:
        """
        List checkpoints for a specific debate.

        DEPRECATED: GET /api/v1/debates/{id}/checkpoints is not dispatched
        by any server handler (the checkpoint handler that implements it is
        shadowed by DebatesHandler in the route index); the request falls
        into the debate slug lookup and returns 404. Use list() -- the
        documented GET /api/v1/checkpoints contract -- and filter by
        debate_id.

        Args:
            debate_id: The debate identifier.
        """
        _warn_deprecated(
            "checkpoints.list_for_debate() targets a shadowed, unserved "
            "route (404 via slug fallback); use list() and filter by "
            "debate_id."
        )
        return self._client._request("GET", f"/api/v1/debates/{debate_id}/checkpoints")

    def create_for_debate(self, debate_id: str) -> dict[str, Any]:
        """
        Create a checkpoint for a running debate.

        DEPRECATED: POST /api/v1/debates/{id}/checkpoint is not dispatched
        by any server handler; the request falls into the debate slug
        lookup and returns 404. Checkpoints are created server-side when a
        debate is paused -- use pause_debate() instead.

        Args:
            debate_id: The debate identifier.
        """
        _warn_deprecated(
            "checkpoints.create_for_debate() targets an unserved route "
            "(404 via slug fallback); use pause_debate()."
        )
        return self._client._request("POST", f"/api/v1/debates/{debate_id}/checkpoint")

    def pause_debate(self, debate_id: str) -> dict[str, Any]:
        """
        Pause a debate and create a checkpoint.

        Args:
            debate_id: The debate identifier.

        Returns:
            The created checkpoint with pause state.
        """
        return self._client._request("POST", f"/api/v1/debates/{debate_id}/pause")

    # =========================================================================
    # Knowledge Mound Checkpoints
    # =========================================================================

    def list_km(self, limit: int | None = None) -> dict[str, Any]:
        """
        List Knowledge Mound checkpoints.

        Args:
            limit: Maximum number of checkpoints to return.

        Returns:
            Dict with list of KM checkpoints.
        """
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit

        return self._client._request(
            "GET",
            "/api/v1/km/checkpoints",
            params=params if params else None,
        )

    def create_km(
        self,
        name: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a Knowledge Mound checkpoint.

        Args:
            name: Name for the checkpoint.
            workspace_id: Optional workspace ID.

        Returns:
            The created KM checkpoint with name, created_at, size_bytes, etc.
        """
        data: dict[str, Any] = {"name": name}
        if workspace_id is not None:
            data["workspace_id"] = workspace_id

        return self._client._request("POST", "/api/v1/km/checkpoints", json=data)

    def get_km(self, name: str) -> dict[str, Any]:
        """
        Get a Knowledge Mound checkpoint.

        Args:
            name: The checkpoint name.

        Returns:
            KM checkpoint details including name, workspace_id, created_at,
            size_bytes, node_count, and metadata.
        """
        return self._client._request("GET", f"/api/v1/km/checkpoints/{name}")

    def compare_km(self, name: str, compare_to: str) -> dict[str, Any]:
        """
        Compare two Knowledge Mound checkpoints.

        Args:
            name: The first checkpoint name.
            compare_to: The second checkpoint name to compare against.

        Returns:
            Dict with checkpoint_a, checkpoint_b, additions, deletions,
            modifications, and details.
        """
        return self._client._request(
            "GET",
            f"/api/v1/km/checkpoints/{name}/compare",
            params={"compare_to": compare_to},
        )

    def compare_km_checkpoints(self, checkpoint_a: str, checkpoint_b: str) -> dict[str, Any]:
        """
        Compare two named Knowledge Mound checkpoints directly.

        Uses the documented POST /api/v1/km/checkpoints/compare contract
        (body: checkpoint_a, checkpoint_b).

        Args:
            checkpoint_a: First checkpoint name.
            checkpoint_b: Second checkpoint name.

        Returns:
            Dict with checkpoint_a, checkpoint_b, additions, deletions,
            modifications, and details.
        """
        return self._client._request(
            "POST",
            "/api/v1/km/checkpoints/compare",
            json={"checkpoint_a": checkpoint_a, "checkpoint_b": checkpoint_b},
        )

    def restore_km(self, name: str) -> dict[str, Any]:
        """
        Restore a Knowledge Mound checkpoint.

        Args:
            name: The checkpoint name to restore.

        Returns:
            Dict with restored status.
        """
        return self._client._request("POST", f"/api/v1/km/checkpoints/{name}/restore")

    def delete_km(self, name: str) -> dict[str, Any]:
        """
        Delete a Knowledge Mound checkpoint.

        Args:
            name: The checkpoint name to delete.

        Returns:
            Dict confirming deletion.
        """
        return self._client._request("DELETE", f"/api/v1/km/checkpoints/{name}")


class AsyncCheckpointsAPI:
    """
    Asynchronous Checkpoints API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     # Pause a debate
        ...     checkpoint = await client.checkpoints.pause_debate("debate_123")
        ...     # Resume later
        ...     result = await client.checkpoints.resume(checkpoint['id'])
    """

    def __init__(self, client: AragoraAsyncClient) -> None:
        self._client = client

    # =========================================================================
    # Debate Checkpoints
    # =========================================================================

    async def list(
        self,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """List all checkpoints."""
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        return await self._client._request(
            "GET",
            "/api/v1/checkpoints",
            params=params if params else None,
        )

    async def list_resumable(self) -> dict[str, Any]:
        """Get resumable debates with active checkpoints."""
        return await self._client._request("GET", "/api/v1/checkpoints/resumable")

    async def get(self, checkpoint_id: str) -> dict[str, Any]:
        """Get a specific checkpoint."""
        return await self._client._request("GET", f"/api/v1/checkpoints/{checkpoint_id}")

    async def resume(self, checkpoint_id: str) -> dict[str, Any]:
        """Resume a debate from a checkpoint."""
        return await self._client._request("POST", f"/api/v1/checkpoints/{checkpoint_id}/resume")

    async def delete(self, checkpoint_id: str) -> dict[str, Any]:
        """Delete a checkpoint."""
        return await self._client._request("DELETE", f"/api/v1/checkpoints/{checkpoint_id}")

    async def intervene(
        self,
        checkpoint_id: str,
        action: str,
        message: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform an intervention on a checkpointed debate."""
        data: dict[str, Any] = {"action": action}
        if message is not None:
            data["message"] = message
        if config is not None:
            data["config"] = config

        return await self._client._request(
            "POST",
            f"/api/v1/checkpoints/{checkpoint_id}/intervention",
            json=data,
        )

    # =========================================================================
    # Debate-Specific Checkpoint Operations
    # =========================================================================

    async def list_for_debate(self, debate_id: str) -> dict[str, Any]:
        """List checkpoints for a specific debate.

        DEPRECATED: GET /api/v1/debates/{id}/checkpoints is not dispatched
        by any server handler (the checkpoint handler that implements it is
        shadowed by DebatesHandler in the route index); the request falls
        into the debate slug lookup and returns 404. Use list() and filter
        by debate_id.
        """
        _warn_deprecated(
            "checkpoints.list_for_debate() targets a shadowed, unserved "
            "route (404 via slug fallback); use list() and filter by "
            "debate_id."
        )
        return await self._client._request("GET", f"/api/v1/debates/{debate_id}/checkpoints")

    async def create_for_debate(self, debate_id: str) -> dict[str, Any]:
        """Create a checkpoint for a running debate.

        DEPRECATED: POST /api/v1/debates/{id}/checkpoint is not dispatched
        by any server handler; the request falls into the debate slug
        lookup and returns 404. Checkpoints are created server-side when a
        debate is paused -- use pause_debate() instead.
        """
        _warn_deprecated(
            "checkpoints.create_for_debate() targets an unserved route "
            "(404 via slug fallback); use pause_debate()."
        )
        return await self._client._request("POST", f"/api/v1/debates/{debate_id}/checkpoint")

    async def pause_debate(self, debate_id: str) -> dict[str, Any]:
        """Pause a debate and create a checkpoint."""
        return await self._client._request("POST", f"/api/v1/debates/{debate_id}/pause")

    # =========================================================================
    # Knowledge Mound Checkpoints
    # =========================================================================

    async def list_km(self, limit: int | None = None) -> dict[str, Any]:
        """List Knowledge Mound checkpoints."""
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit

        return await self._client._request(
            "GET",
            "/api/v1/km/checkpoints",
            params=params if params else None,
        )

    async def create_km(
        self,
        name: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a Knowledge Mound checkpoint."""
        data: dict[str, Any] = {"name": name}
        if workspace_id is not None:
            data["workspace_id"] = workspace_id

        return await self._client._request("POST", "/api/v1/km/checkpoints", json=data)

    async def get_km(self, name: str) -> dict[str, Any]:
        """Get a Knowledge Mound checkpoint."""
        return await self._client._request("GET", f"/api/v1/km/checkpoints/{name}")

    async def compare_km(self, name: str, compare_to: str) -> dict[str, Any]:
        """Compare two Knowledge Mound checkpoints."""
        return await self._client._request(
            "GET",
            f"/api/v1/km/checkpoints/{name}/compare",
            params={"compare_to": compare_to},
        )

    async def compare_km_checkpoints(self, checkpoint_a: str, checkpoint_b: str) -> dict[str, Any]:
        """Compare two named Knowledge Mound checkpoints directly.

        Uses the documented POST /api/v1/km/checkpoints/compare contract
        (body: checkpoint_a, checkpoint_b).
        """
        return await self._client._request(
            "POST",
            "/api/v1/km/checkpoints/compare",
            json={"checkpoint_a": checkpoint_a, "checkpoint_b": checkpoint_b},
        )

    async def restore_km(self, name: str) -> dict[str, Any]:
        """Restore a Knowledge Mound checkpoint."""
        return await self._client._request("POST", f"/api/v1/km/checkpoints/{name}/restore")

    async def delete_km(self, name: str) -> dict[str, Any]:
        """Delete a Knowledge Mound checkpoint."""
        return await self._client._request("DELETE", f"/api/v1/km/checkpoints/{name}")
