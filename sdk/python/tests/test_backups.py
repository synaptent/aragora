"""Tests for Backups namespace API."""

from __future__ import annotations

import pytest

from aragora_sdk.client import AragoraAsyncClient, AragoraClient


class TestBackupsList:
    """Tests for listing backups."""

    def test_list_backups_default(self, client: AragoraClient, mock_request) -> None:
        """List backups with default parameters."""
        mock_request.return_value = [{"backup_id": "bk_1", "status": "completed"}]

        result = client.backups.list()

        mock_request.assert_called_once_with(
            "GET",
            "/api/v1/backups",
            params={"limit": 50, "offset": 0},
        )
        assert result == [{"backup_id": "bk_1", "status": "completed"}]

    def test_list_backups_filtered(self, client: AragoraClient, mock_request) -> None:
        """List backups filtered by type and status."""
        mock_request.return_value = []

        client.backups.list(backup_type="incremental", status="completed", limit=10)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["backup_type"] == "incremental"
        assert call_kwargs["params"]["status"] == "completed"
        assert call_kwargs["params"]["limit"] == 10


class TestBackupsGet:
    """Tests for getting backup details."""

    def test_get_backup(self, client: AragoraClient, mock_request) -> None:
        """Get backup details."""
        mock_request.return_value = {
            "backup_id": "bk_123",
            "backup_type": "full",
            "status": "completed",
            "size_bytes": 1048576,
        }

        result = client.backups.get("bk_123")

        mock_request.assert_called_once_with("GET", "/api/v1/backups/bk_123")
        assert result["backup_type"] == "full"
        assert result["size_bytes"] == 1048576


class TestBackupsCreate:
    """Tests for backup creation."""

    def test_create_backup_default(self, client: AragoraClient, mock_request) -> None:
        """Create a backup with default type (full)."""
        mock_request.return_value = {"backup_id": "bk_new", "status": "in_progress"}

        result = client.backups.create()

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/backups",
            json={"backup_type": "full"},
        )
        assert result["status"] == "in_progress"

    def test_create_backup_incremental(self, client: AragoraClient, mock_request) -> None:
        """Create an incremental backup."""
        mock_request.return_value = {"backup_id": "bk_inc"}

        client.backups.create(backup_type="incremental")

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["json"]["backup_type"] == "incremental"

    def test_create_backup_full_options(self, client: AragoraClient, mock_request) -> None:
        """Create a backup with all options."""
        mock_request.return_value = {"backup_id": "bk_full"}

        client.backups.create(
            backup_type="snapshot",
            description="Weekly snapshot",
            include_data=["debates", "knowledge"],
            exclude_data=["logs"],
        )

        call_kwargs = mock_request.call_args[1]
        call_json = call_kwargs["json"]
        assert call_json["backup_type"] == "snapshot"
        assert call_json["description"] == "Weekly snapshot"
        assert call_json["include_data"] == ["debates", "knowledge"]
        assert call_json["exclude_data"] == ["logs"]


class TestBackupsDelete:
    """Tests for backup deletion."""

    def test_delete_backup(self, client: AragoraClient, mock_request) -> None:
        """Delete a backup."""
        mock_request.return_value = {"deleted": True}

        result = client.backups.delete("bk_123")

        mock_request.assert_called_once_with("DELETE", "/api/v1/backups/bk_123")
        assert result["deleted"] is True


class TestBackupsVerification:
    """Tests for backup verification methods."""

    def test_verify(self, client: AragoraClient, mock_request) -> None:
        """Verify backup integrity."""
        mock_request.return_value = {"valid": True, "checksum": "abc123"}
        result = client.backups.verify("bk_123")
        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/backups/bk_123/verify",
        )
        assert result["valid"] is True

    def test_verify_comprehensive(self, client: AragoraClient, mock_request) -> None:
        """Run comprehensive backup verification."""
        mock_request.return_value = {
            "valid": True,
            "checks": {"data": True, "schema": True},
        }
        result = client.backups.verify_comprehensive("bk_123")
        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/backups/bk_123/verify-comprehensive",
        )
        assert result["checks"]["data"] is True

    def test_test_restore(self, client: AragoraClient, mock_request) -> None:
        """Test restore without applying changes."""
        mock_request.return_value = {"success": True, "estimated_time": 120}
        result = client.backups.test_restore("bk_123")
        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/backups/bk_123/restore-test",
            json=None,
        )
        assert result["success"] is True

    def test_test_restore_with_path(self, client: AragoraClient, mock_request) -> None:
        """Test restore to a specific target path."""
        mock_request.return_value = {"success": True}
        client.backups.test_restore("bk_123", target_path="/tmp/restore-test")
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["json"]["target_path"] == "/tmp/restore-test"

    def test_cleanup_dry_run(self, client: AragoraClient, mock_request) -> None:
        """Clean up with dry run (default)."""
        mock_request.return_value = {"would_delete": 5, "freed_bytes": 1024000}
        result = client.backups.cleanup()
        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/backups/cleanup",
            json={"dry_run": True},
        )
        assert result["would_delete"] == 5

    def test_cleanup_execute(self, client: AragoraClient, mock_request) -> None:
        """Clean up with actual deletion."""
        mock_request.return_value = {"deleted": 5, "freed_bytes": 1024000}
        result = client.backups.cleanup(dry_run=False)
        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/backups/cleanup",
            json={"dry_run": False},
        )
        assert result["deleted"] == 5

    def test_get_stats(self, client: AragoraClient, mock_request) -> None:
        """Get backup statistics."""
        mock_request.return_value = {
            "total_backups": 42,
            "total_size_bytes": 5000000,
            "health": "healthy",
        }
        result = client.backups.get_stats()
        mock_request.assert_called_once_with("GET", "/api/v1/backups/stats")
        assert result["total_backups"] == 42
        assert result["health"] == "healthy"


class TestAsyncBackups:
    """Tests for async backups API."""

    @pytest.mark.asyncio
    async def test_async_list_backups(self, mock_async_request) -> None:
        """List backups asynchronously."""
        mock_async_request.return_value = [{"backup_id": "bk_1"}]

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.backups.list()

            assert result == [{"backup_id": "bk_1"}]

    @pytest.mark.asyncio
    async def test_async_create_backup(self, mock_async_request) -> None:
        """Create a backup asynchronously."""
        mock_async_request.return_value = {"backup_id": "bk_async"}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.backups.create(backup_type="snapshot")

            assert result["backup_id"] == "bk_async"

    @pytest.mark.asyncio
    async def test_async_verify(self, mock_async_request) -> None:
        """Verify a backup asynchronously."""
        mock_async_request.return_value = {"valid": True}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.backups.verify("bk_123")

            assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_async_verify_comprehensive(self, mock_async_request) -> None:
        """Run comprehensive verification asynchronously."""
        mock_async_request.return_value = {"valid": True, "checks": {"data": True}}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.backups.verify_comprehensive("bk_123")

            assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_async_test_restore(self, mock_async_request) -> None:
        """Test restore asynchronously."""
        mock_async_request.return_value = {"success": True}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.backups.test_restore("bk_123")

            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_async_cleanup(self, mock_async_request) -> None:
        """Clean up asynchronously."""
        mock_async_request.return_value = {"would_delete": 3}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.backups.cleanup()

            call_kwargs = mock_async_request.call_args[1]
            assert call_kwargs["json"]["dry_run"] is True
            assert result["would_delete"] == 3

    @pytest.mark.asyncio
    async def test_async_get_stats(self, mock_async_request) -> None:
        """Get backup stats asynchronously."""
        mock_async_request.return_value = {"total_backups": 10}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.backups.get_stats()

            assert result["total_backups"] == 10
