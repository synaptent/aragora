"""
Backups namespace for disaster recovery operations.

Provides API access to backup management, restore operations,
and disaster recovery functionality.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

_List = list  # Preserve builtin list for type annotations


class BackupsAPI:
    """Synchronous backups API."""

    def __init__(self, client: AragoraClient) -> None:
        self._client = client

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        backup_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """
        List backups.

        Args:
            limit: Maximum number of backups to return
            offset: Number of backups to skip
            backup_type: Filter by type (full, incremental, snapshot)
            status: Filter by status (completed, in_progress, failed)

        Returns:
            Backup records
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if backup_type:
            params["backup_type"] = backup_type
        if status:
            params["status"] = status

        return self._client.request("GET", "/api/v1/backups", params=params)

    def get(self, backup_id: str) -> dict[str, Any]:
        """
        Get backup details.

        Args:
            backup_id: Backup identifier

        Returns:
            Backup details
        """
        return self._client.request("GET", f"/api/v1/backups/{backup_id}")

    def create(
        self,
        backup_type: str = "full",
        description: str | None = None,
        include_data: _List[str] | None = None,
        exclude_data: _List[str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new backup.

        Args:
            backup_type: Type of backup (full, incremental, snapshot)
            description: Optional description
            include_data: Data types to include
            exclude_data: Data types to exclude

        Returns:
            Created backup record
        """
        data: dict[str, Any] = {"backup_type": backup_type}
        if description:
            data["description"] = description
        if include_data:
            data["include_data"] = include_data
        if exclude_data:
            data["exclude_data"] = exclude_data

        return self._client.request("POST", "/api/v1/backups", json=data)

    def delete(self, backup_id: str) -> dict[str, Any]:
        """
        Delete a backup.

        Args:
            backup_id: Backup identifier

        Returns:
            Deletion confirmation
        """
        return self._client.request("DELETE", f"/api/v1/backups/{backup_id}")

    def verify(self, backup_id: str) -> dict[str, Any]:
        """
        Verify backup integrity.

        Args:
            backup_id: Backup identifier

        Returns:
            Verification result with integrity status
        """
        return self._client.request("POST", f"/api/v1/backups/{backup_id}/verify")

    def verify_comprehensive(self, backup_id: str) -> dict[str, Any]:
        """
        Run comprehensive backup verification.

        Args:
            backup_id: Backup identifier

        Returns:
            Detailed verification results including checksums and data validation
        """
        return self._client.request("POST", f"/api/v1/backups/{backup_id}/verify-comprehensive")

    def test_restore(
        self,
        backup_id: str,
        target_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Test restore without applying changes.

        Args:
            backup_id: Backup identifier
            target_path: Optional target path for test restore

        Returns:
            Test restore results
        """
        data: dict[str, Any] = {}
        if target_path:
            data["target_path"] = target_path
        return self._client.request(
            "POST",
            f"/api/v1/backups/{backup_id}/restore-test",
            json=data if data else None,
        )

    def cleanup(self, dry_run: bool = True) -> dict[str, Any]:
        """
        Clean up old or expired backups.

        Args:
            dry_run: If True, only report what would be cleaned up

        Returns:
            Cleanup results with affected backups
        """
        return self._client.request("POST", "/api/v1/backups/cleanup", json={"dry_run": dry_run})

    def get_stats(self) -> dict[str, Any]:
        """
        Get backup statistics.

        Returns:
            Backup statistics including counts, sizes, and health metrics
        """
        return self._client.request("GET", "/api/v1/backups/stats")


class AsyncBackupsAPI:
    """Asynchronous backups API."""

    def __init__(self, client: AragoraAsyncClient) -> None:
        self._client = client

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        backup_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List backups."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if backup_type:
            params["backup_type"] = backup_type
        if status:
            params["status"] = status

        return await self._client.request("GET", "/api/v1/backups", params=params)

    async def get(self, backup_id: str) -> dict[str, Any]:
        """Get backup details."""
        return await self._client.request("GET", f"/api/v1/backups/{backup_id}")

    async def create(
        self,
        backup_type: str = "full",
        description: str | None = None,
        include_data: _List[str] | None = None,
        exclude_data: _List[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new backup."""
        data: dict[str, Any] = {"backup_type": backup_type}
        if description:
            data["description"] = description
        if include_data:
            data["include_data"] = include_data
        if exclude_data:
            data["exclude_data"] = exclude_data

        return await self._client.request("POST", "/api/v1/backups", json=data)

    async def delete(self, backup_id: str) -> dict[str, Any]:
        """Delete a backup."""
        return await self._client.request("DELETE", f"/api/v1/backups/{backup_id}")

    async def verify(self, backup_id: str) -> dict[str, Any]:
        """Verify backup integrity."""
        return await self._client.request("POST", f"/api/v1/backups/{backup_id}/verify")

    async def verify_comprehensive(self, backup_id: str) -> dict[str, Any]:
        """Run comprehensive backup verification."""
        return await self._client.request(
            "POST", f"/api/v1/backups/{backup_id}/verify-comprehensive"
        )

    async def test_restore(
        self,
        backup_id: str,
        target_path: str | None = None,
    ) -> dict[str, Any]:
        """Test restore without applying changes."""
        data: dict[str, Any] = {}
        if target_path:
            data["target_path"] = target_path
        return await self._client.request(
            "POST",
            f"/api/v1/backups/{backup_id}/restore-test",
            json=data if data else None,
        )

    async def cleanup(self, dry_run: bool = True) -> dict[str, Any]:
        """Clean up old or expired backups."""
        return await self._client.request(
            "POST", "/api/v1/backups/cleanup", json={"dry_run": dry_run}
        )

    async def get_stats(self) -> dict[str, Any]:
        """Get backup statistics."""
        return await self._client.request("GET", "/api/v1/backups/stats")
