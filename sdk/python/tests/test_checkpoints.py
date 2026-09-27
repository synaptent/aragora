"""Tests for Checkpoints namespace API."""

from __future__ import annotations

import pytest

from aragora_sdk.client import AragoraAsyncClient, AragoraClient


class TestCheckpointsList:
    """Tests for listing checkpoints."""

    def test_list_checkpoints_default(self, client: AragoraClient, mock_request) -> None:
        """List checkpoints with default parameters."""
        mock_request.return_value = {
            "checkpoints": [
                {"id": "cp_1", "debate_id": "d_1", "status": "active"},
            ],
            "total": 1,
        }

        result = client.checkpoints.list()

        mock_request.assert_called_once_with(
            "GET", "/api/v1/checkpoints", params=None, json=None, headers=None
        )
        assert len(result["checkpoints"]) == 1

    def test_list_checkpoints_paginated(self, client: AragoraClient, mock_request) -> None:
        """List checkpoints with pagination."""
        mock_request.return_value = {"checkpoints": [], "total": 0}

        client.checkpoints.list(limit=10, offset=20)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["limit"] == 10
        assert call_kwargs["params"]["offset"] == 20

    def test_list_resumable(self, client: AragoraClient, mock_request) -> None:
        """List resumable debates."""
        mock_request.return_value = {
            "debates": [
                {
                    "debate_id": "d_1",
                    "checkpoint_id": "cp_1",
                    "task": "Test task",
                    "round": 2,
                    "paused_at": "2024-01-15T10:00:00Z",
                }
            ]
        }

        result = client.checkpoints.list_resumable()

        mock_request.assert_called_once_with(
            "GET", "/api/v1/checkpoints/resumable", params=None, json=None, headers=None
        )
        assert len(result["debates"]) == 1
        assert result["debates"][0]["round"] == 2


class TestCheckpointsOperations:
    """Tests for checkpoint CRUD operations."""

    def test_get_checkpoint(self, client: AragoraClient, mock_request) -> None:
        """Get a specific checkpoint."""
        mock_request.return_value = {
            "id": "cp_123",
            "debate_id": "d_456",
            "status": "active",
            "round": 3,
            "created_at": "2024-01-15T10:00:00Z",
        }

        result = client.checkpoints.get("cp_123")

        mock_request.assert_called_once_with(
            "GET", "/api/v1/checkpoints/cp_123", params=None, json=None, headers=None
        )
        assert result["status"] == "active"
        assert result["round"] == 3

    def test_resume_checkpoint(self, client: AragoraClient, mock_request) -> None:
        """Resume a debate from checkpoint."""
        mock_request.return_value = {"debate_id": "d_456", "resumed": True}

        result = client.checkpoints.resume("cp_123")

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/checkpoints/cp_123/resume",
            params=None,
            json=None,
            headers=None,
        )
        assert result["resumed"] is True

    def test_delete_checkpoint(self, client: AragoraClient, mock_request) -> None:
        """Delete a checkpoint."""
        mock_request.return_value = {"deleted": True}

        result = client.checkpoints.delete("cp_123")

        mock_request.assert_called_once_with(
            "DELETE", "/api/v1/checkpoints/cp_123", params=None, json=None, headers=None
        )
        assert result["deleted"] is True

    def test_intervene(self, client: AragoraClient, mock_request) -> None:
        """Perform intervention on checkpoint."""
        mock_request.return_value = {
            "success": True,
            "message": "Context injected successfully",
        }

        result = client.checkpoints.intervene(
            checkpoint_id="cp_123",
            action="inject_context",
            message="Additional context for the debate",
            config={"priority": "high"},
        )

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/checkpoints/cp_123/intervention",
            params=None,
            json={
                "action": "inject_context",
                "message": "Additional context for the debate",
                "config": {"priority": "high"},
            },
            headers=None,
        )
        assert result["success"] is True


class TestDebateCheckpoints:
    """Tests for debate-specific checkpoint operations."""

    def test_list_for_debate(self, client: AragoraClient, mock_request) -> None:
        """List checkpoints for a debate."""
        mock_request.return_value = {
            "checkpoints": [
                {"id": "cp_1", "round": 1},
                {"id": "cp_2", "round": 2},
            ]
        }

        result = client.checkpoints.list_for_debate("d_123")

        mock_request.assert_called_once_with(
            "GET",
            "/api/v1/debates/d_123/checkpoints",
            params=None,
            json=None,
            headers=None,
        )
        assert len(result["checkpoints"]) == 2

    def test_create_for_debate(self, client: AragoraClient, mock_request) -> None:
        """Create checkpoint for a debate."""
        mock_request.return_value = {
            "id": "cp_new",
            "debate_id": "d_123",
            "status": "active",
            "round": 2,
        }

        result = client.checkpoints.create_for_debate("d_123")

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/debates/d_123/checkpoint",
            params=None,
            json=None,
            headers=None,
        )
        assert result["status"] == "active"

    def test_pause_debate(self, client: AragoraClient, mock_request) -> None:
        """Pause a debate."""
        mock_request.return_value = {
            "id": "cp_paused",
            "debate_id": "d_123",
            "status": "active",
            "round": 3,
            "created_at": "2024-01-15T10:00:00Z",
        }

        result = client.checkpoints.pause_debate("d_123")

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/debates/d_123/pause",
            params=None,
            json=None,
            headers=None,
        )
        assert result["id"] == "cp_paused"


class TestKMCheckpoints:
    """Tests for Knowledge Mound checkpoint operations."""

    def test_list_km(self, client: AragoraClient, mock_request) -> None:
        """List KM checkpoints."""
        mock_request.return_value = {
            "checkpoints": [
                {"name": "backup_2024_01", "node_count": 1000},
            ]
        }

        result = client.checkpoints.list_km(limit=5)

        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["params"]["limit"] == 5
        assert len(result["checkpoints"]) == 1

    def test_create_km(self, client: AragoraClient, mock_request) -> None:
        """Create KM checkpoint."""
        mock_request.return_value = {
            "name": "backup_new",
            "created_at": "2024-01-15T10:00:00Z",
            "size_bytes": 10000000,
            "node_count": 5000,
        }

        result = client.checkpoints.create_km(
            name="backup_new",
            workspace_id="ws_123",
        )

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/km/checkpoints",
            params=None,
            json={"name": "backup_new", "workspace_id": "ws_123"},
            headers=None,
        )
        assert result["node_count"] == 5000

    def test_get_km(self, client: AragoraClient, mock_request) -> None:
        """Get KM checkpoint."""
        mock_request.return_value = {
            "name": "backup_2024_01",
            "workspace_id": "ws_123",
            "created_at": "2024-01-15T10:00:00Z",
            "size_bytes": 10000000,
            "node_count": 5000,
        }

        result = client.checkpoints.get_km("backup_2024_01")

        mock_request.assert_called_once_with(
            "GET",
            "/api/v1/km/checkpoints/backup_2024_01",
            params=None,
            json=None,
            headers=None,
        )
        assert result["name"] == "backup_2024_01"

    def test_compare_km(self, client: AragoraClient, mock_request) -> None:
        """Compare KM checkpoints."""
        mock_request.return_value = {
            "checkpoint_a": "backup_2024_01",
            "checkpoint_b": "backup_2024_02",
            "additions": 100,
            "deletions": 20,
            "modifications": 50,
        }

        result = client.checkpoints.compare_km("backup_2024_01", "backup_2024_02")

        mock_request.assert_called_once_with(
            "GET",
            "/api/v1/km/checkpoints/backup_2024_01/compare",
            params={"compare_to": "backup_2024_02"},
            json=None,
            headers=None,
        )
        assert result["additions"] == 100
        assert result["deletions"] == 20

    def test_compare_km_checkpoints(self, client: AragoraClient, mock_request) -> None:
        """Compare two named KM checkpoints via the POST body contract."""
        mock_request.return_value = {
            "checkpoint_a": "backup_2024_01",
            "checkpoint_b": "backup_2024_02",
            "additions": 5,
            "deletions": 2,
            "modifications": 3,
        }

        result = client.checkpoints.compare_km_checkpoints("backup_2024_01", "backup_2024_02")

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/km/checkpoints/compare",
            params=None,
            json={"checkpoint_a": "backup_2024_01", "checkpoint_b": "backup_2024_02"},
            headers=None,
        )
        assert result["additions"] == 5

    def test_restore_km(self, client: AragoraClient, mock_request) -> None:
        """Restore KM checkpoint."""
        mock_request.return_value = {"restored": True}

        result = client.checkpoints.restore_km("backup_2024_01")

        mock_request.assert_called_once_with(
            "POST",
            "/api/v1/km/checkpoints/backup_2024_01/restore",
            params=None,
            json=None,
            headers=None,
        )
        assert result["restored"] is True

    def test_delete_km(self, client: AragoraClient, mock_request) -> None:
        """Delete KM checkpoint."""
        mock_request.return_value = {"deleted": True}

        result = client.checkpoints.delete_km("old_backup")

        mock_request.assert_called_once_with(
            "DELETE",
            "/api/v1/km/checkpoints/old_backup",
            params=None,
            json=None,
            headers=None,
        )
        assert result["deleted"] is True


class TestAsyncCheckpoints:
    """Tests for async checkpoints API."""

    @pytest.mark.asyncio
    async def test_async_list(self, mock_async_request) -> None:
        """List checkpoints asynchronously."""
        mock_async_request.return_value = {"checkpoints": [{"id": "cp_1"}], "total": 1}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.checkpoints.list()

            assert len(result["checkpoints"]) == 1

    @pytest.mark.asyncio
    async def test_async_resume(self, mock_async_request) -> None:
        """Resume checkpoint asynchronously."""
        mock_async_request.return_value = {"debate_id": "d_1", "resumed": True}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.checkpoints.resume("cp_123")

            assert result["resumed"] is True

    @pytest.mark.asyncio
    async def test_async_pause_debate(self, mock_async_request) -> None:
        """Pause debate asynchronously."""
        mock_async_request.return_value = {"id": "cp_new", "status": "active"}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.checkpoints.pause_debate("d_123")

            assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_async_intervene(self, mock_async_request) -> None:
        """Intervene asynchronously."""
        mock_async_request.return_value = {"success": True}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.checkpoints.intervene(
                checkpoint_id="cp_123",
                action="inject_context",
            )

            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_async_create_km(self, mock_async_request) -> None:
        """Create KM checkpoint asynchronously."""
        mock_async_request.return_value = {"name": "async_backup"}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.checkpoints.create_km(name="async_backup")

            assert result["name"] == "async_backup"

    @pytest.mark.asyncio
    async def test_async_compare_km(self, mock_async_request) -> None:
        """Compare KM checkpoints asynchronously."""
        mock_async_request.return_value = {
            "additions": 50,
            "deletions": 10,
            "modifications": 25,
        }

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.checkpoints.compare_km("cp_a", "cp_b")

            assert result["additions"] == 50

    @pytest.mark.asyncio
    async def test_async_compare_km_checkpoints(self, mock_async_request) -> None:
        """Compare two named KM checkpoints asynchronously via POST body."""
        mock_async_request.return_value = {
            "additions": 7,
            "deletions": 1,
            "modifications": 2,
        }

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            result = await client.checkpoints.compare_km_checkpoints("cp_a", "cp_b")

            assert result["additions"] == 7
