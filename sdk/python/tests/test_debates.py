"""Tests for Debates namespace API."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aragora_sdk.client import AragoraAsyncClient, AragoraClient


class TestDebatesCreate:
    """Tests for debate creation."""

    def test_create_debate_with_task(self) -> None:
        """Create a debate with just a task."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {
                "debate_id": "deb_123",
                "task": "Should we adopt microservices?",
                "status": "pending",
            }

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.create(task="Should we adopt microservices?")

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/debates",
                json={"task": "Should we adopt microservices?"},
            )
            assert result["debate_id"] == "deb_123"
            client.close()

    def test_create_debate_with_agents(self) -> None:
        """Create a debate with specific agents."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debate_id": "deb_123"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.create(task="Debate topic", agents=["claude", "gpt-4", "gemini"])

            call_args = mock_request.call_args
            assert call_args[1]["json"]["agents"] == ["claude", "gpt-4", "gemini"]
            client.close()

    def test_create_debate_with_protocol(self) -> None:
        """Create a debate with protocol configuration."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debate_id": "deb_123"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            protocol = {"rounds": 5, "consensus": "unanimous"}
            client.debates.create(task="Debate topic", protocol=protocol)

            call_args = mock_request.call_args
            assert call_args[1]["json"]["protocol"] == protocol
            client.close()

    def test_create_debate_with_extra_kwargs(self) -> None:
        """Create a debate with additional keyword arguments."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debate_id": "deb_123"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.create(task="Debate topic", timeout=300, workspace_id="ws_123")

            call_args = mock_request.call_args
            assert call_args[1]["json"]["timeout"] == 300
            assert call_args[1]["json"]["workspace_id"] == "ws_123"
            client.close()


class TestDebatesList:
    """Tests for listing debates."""

    def test_list_debates_default_pagination(self) -> None:
        """List debates with default pagination."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {
                "debates": [],
                "total": 0,
                "limit": 20,
                "offset": 0,
            }

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.list()

            mock_request.assert_called_once_with(
                "GET", "/api/v1/debates", params={"limit": 20, "offset": 0}
            )
            client.close()

    def test_list_debates_custom_pagination(self) -> None:
        """List debates with custom pagination."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debates": [], "total": 100}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.list(limit=50, offset=25)

            mock_request.assert_called_once_with(
                "GET", "/api/v1/debates", params={"limit": 50, "offset": 25}
            )
            client.close()

    def test_list_debates_with_status_filter(self) -> None:
        """List debates filtered by status."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debates": []}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.list(status="completed")

            call_args = mock_request.call_args
            assert call_args[1]["params"]["status"] == "completed"
            client.close()

    def test_list_active_debates(self) -> None:
        """List currently active debates."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debates": [{"id": "deb_active", "status": "running"}]}

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.list_active()

            mock_request.assert_called_once_with("GET", "/api/v1/debates/active")
            assert result["debates"][0]["id"] == "deb_active"
            client.close()


class TestDebatesMessages:
    """Tests for debate message operations."""

    def test_get_messages(self) -> None:
        """Get messages from a debate."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {
                "messages": [
                    {"id": "msg_1", "content": "First message", "role": "agent"},
                ]
            }

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.get_messages("deb_123")

            mock_request.assert_called_once_with("GET", "/api/v1/debates/deb_123/messages")
            assert len(result["messages"]) == 1
            client.close()

    def test_add_message(self) -> None:
        """Add a message to a debate."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {
                "id": "msg_new",
                "content": "User input",
                "role": "user",
            }

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.add_message("deb_123", content="User input", role="user")

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/debates/deb_123/messages",
                json={"content": "User input", "role": "user"},
            )
            client.close()


class TestDebatesExport:
    """Tests for debate export."""

    def test_export_debate_json(self) -> None:
        """Export debate as JSON (format is a path segment)."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"data": "exported_content"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.get_export("deb_123", format="json")

            mock_request.assert_called_once_with(
                "GET", "/api/v1/debates/deb_123/export/json", params=None
            )
            client.close()

    def test_export_debate_csv_with_table(self) -> None:
        """Export debate as CSV with a table selector."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"data": "exported_content"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.get_export("deb_123", format="csv", table="messages")

            mock_request.assert_called_once_with(
                "GET", "/api/v1/debates/deb_123/export/csv", params={"table": "messages"}
            )
            client.close()


class TestDebatesCancel:
    """Tests for cancelling debates."""

    def test_cancel_debate(self) -> None:
        """Cancel a debate."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"cancelled": True}

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.cancel("deb_123")

            mock_request.assert_called_once_with("POST", "/api/v1/debates/deb_123/cancel")
            assert result["cancelled"] is True
            client.close()


class TestAsyncDebates:
    """Tests for async debates API."""

    @pytest.mark.asyncio
    async def test_async_create_debate(self) -> None:
        """Create a debate asynchronously."""
        with patch.object(AragoraAsyncClient, "request") as mock_request:
            mock_request.return_value = {"debate_id": "deb_123"}

            async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
                result = await client.debates.create(task="Async debate")

                mock_request.assert_called_once_with(
                    "POST", "/api/v1/debates", json={"task": "Async debate"}
                )
                assert result["debate_id"] == "deb_123"

    @pytest.mark.asyncio
    async def test_async_list_debates(self) -> None:
        """List debates asynchronously."""
        with patch.object(AragoraAsyncClient, "request") as mock_request:
            mock_request.return_value = {"debates": [], "total": 0}

            async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
                await client.debates.list(limit=10, offset=5)

                mock_request.assert_called_once_with(
                    "GET", "/api/v1/debates", params={"limit": 10, "offset": 5}
                )

    @pytest.mark.asyncio
    async def test_async_list_active_debates(self) -> None:
        """List active debates asynchronously."""
        with patch.object(AragoraAsyncClient, "request") as mock_request:
            mock_request.return_value = {"debates": [{"id": "deb_active", "status": "paused"}]}

            async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
                result = await client.debates.list_active()

                mock_request.assert_called_once_with("GET", "/api/v1/debates/active")
                assert result["debates"][0]["status"] == "paused"


class TestDebatesAdvancedFeatures:
    """Tests for advanced debate features."""

    def test_capability_probe(self) -> None:
        """Run a capability probe debate."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debate_id": "deb_probe"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.capability_probe(task="Test capability", agents=["claude"])

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/debates/capability-probe",
                json={"task": "Test capability", "agents": ["claude"]},
            )
            client.close()

    def test_deep_audit(self) -> None:
        """Run a deep audit debate."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debate_id": "deb_audit"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.deep_audit(task="Audit this decision")

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/debates/deep-audit",
                json={"task": "Audit this decision"},
            )
            client.close()

    def test_fork_debate(self) -> None:
        """Fork a debate with changes."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debate_id": "deb_forked"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.fork("deb_123", changes={"agents": ["gpt-4"]})

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/debates/deb_123/fork",
                json={"agents": ["gpt-4"]},
            )
            client.close()

    def test_broadcast_debate(self) -> None:
        """Broadcast debate to channels."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"broadcasted": True}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.debates.broadcast("deb_123", channels=["slack", "email"])

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/debates/deb_123/broadcast",
                json={"channels": ["slack", "email"]},
            )
            client.close()


class TestDebatesAnalysis:
    """Tests for debate analysis methods."""

    def test_get_summary(self) -> None:
        """Get a debate summary."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"verdict": "Adopt microservices", "confidence": 0.9}

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.get_summary("deb_123")

            mock_request.assert_called_once_with("GET", "/api/v1/debates/deb_123/summary")
            assert result["verdict"] == "Adopt microservices"
            client.close()


class TestDebatesRoundsAgentsVotes:
    """Tests for rounds, agents, and votes methods."""

    def test_add_evidence(self) -> None:
        """Add evidence to a debate."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"evidence_id": "ev_123", "success": True}

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.add_evidence(
                "deb_123", "Studies show...", source="research-paper"
            )

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/debates/deb_123/evidence",
                json={"evidence": "Studies show...", "source": "research-paper"},
            )
            assert result["evidence_id"] == "ev_123"
            client.close()


class TestDebatesBatchOperations:
    """Tests for batch operations."""

    def test_submit_batch(self) -> None:
        """Submit multiple debates for batch processing."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"batch_id": "batch_123", "total_jobs": 2}

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.submit_batch(
                [
                    {"task": "Debate 1"},
                    {"task": "Debate 2"},
                ]
            )

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/debates/batch",
                json={"requests": [{"task": "Debate 1"}, {"task": "Debate 2"}]},
            )
            assert result["total_jobs"] == 2
            client.close()

    def test_get_batch_status(self) -> None:
        """Get the status of a batch job."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"batch_id": "batch_123", "status": "running"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.get_batch_status("batch_123")

            mock_request.assert_called_once_with("GET", "/api/v1/debates/batch/batch_123/status")
            assert result["status"] == "running"
            client.close()

    def test_get_queue_status(self) -> None:
        """Get the current queue status."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"pending_count": 5, "running_count": 2}

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.get_queue_status()

            mock_request.assert_called_once_with("GET", "/api/v1/debates/queue/status")
            assert result["pending_count"] == 5
            client.close()


class TestDebatesSearch:
    """Tests for search functionality."""

    def test_search_debates(self) -> None:
        """Search across all debates."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"debates": [], "total": 0}

            client = AragoraClient(base_url="https://api.aragora.ai")
            result = client.debates.search("microservices", limit=10, status="completed")

            mock_request.assert_called_once_with(
                "GET",
                "/api/v1/search",
                params={
                    "query": "microservices",
                    "limit": 10,
                    "offset": 0,
                    "status": "completed",
                },
            )
            assert "debates" in result
            client.close()
