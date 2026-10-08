"""Tests for Receipts namespace API."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from httpx import Client as HTTPXClient

from aragora_sdk.client import AragoraAsyncClient, AragoraClient


class TestReceiptsGauntlet:
    """Tests for gauntlet receipt operations."""

    def test_list_gauntlet(self) -> None:
        """List gauntlet results."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"results": [], "total": 0}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.receipts.list_gauntlet(verdict="PASS", limit=10)

            mock_request.assert_called_once_with(
                "GET",
                "/api/v1/gauntlet/results",
                params={"limit": 10, "offset": 0, "verdict": "PASS"},
            )
            client.close()

    def test_get_gauntlet(self) -> None:
        """Get a gauntlet receipt."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"receipt_id": "gnt_123"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.receipts.get_gauntlet("gnt_123")

            mock_request.assert_called_once_with("GET", "/api/v1/gauntlet/gnt_123/receipt")
            client.close()

    def test_verify_gauntlet(self) -> None:
        """Verify a gauntlet receipt."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"valid": True}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.receipts.verify_gauntlet("gnt_123")

            mock_request.assert_called_once_with("POST", "/api/v1/gauntlet/gnt_123/receipt/verify")
            client.close()

    def test_export_gauntlet_markdown(self) -> None:
        """Export gauntlet receipt as markdown."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"content": "# Receipt"}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.receipts.export_gauntlet("gnt_123", format="markdown")

            mock_request.assert_called_once_with(
                "GET",
                "/api/v1/gauntlet/gnt_123/receipt",
                params={"format": "md"},
            )
            client.close()


class TestReceiptsHelpers:
    """Tests for static helper methods."""

    def test_has_dissent_true(self) -> None:
        """Check receipt with dissenting views."""
        from aragora_sdk.namespaces.receipts import ReceiptsAPI

        receipt = {"dissenting_agents": ["agent_1", "agent_2"]}
        assert ReceiptsAPI.has_dissent(receipt) is True

    def test_has_dissent_false(self) -> None:
        """Check receipt without dissenting views."""
        from aragora_sdk.namespaces.receipts import ReceiptsAPI

        receipt = {"dissenting_agents": []}
        assert ReceiptsAPI.has_dissent(receipt) is False

    def test_get_consensus_status(self) -> None:
        """Get consensus status from receipt."""
        from aragora_sdk.namespaces.receipts import ReceiptsAPI

        receipt = {
            "consensus_reached": True,
            "confidence": 0.95,
            "participating_agents": ["a1", "a2", "a3"],
            "dissenting_agents": ["a3"],
        }

        status = ReceiptsAPI.get_consensus_status(receipt)
        assert status["reached"] is True
        assert status["confidence"] == 0.95
        assert status["participating_agents"] == 3
        assert status["dissenting_agents"] == 1


class TestReceiptsDeliveryBridge:
    """Tests for the v1 delivery bridge endpoint."""

    def test_deliver_v1_with_modern_fields(self) -> None:
        """Deliver a receipt using modern channel field names."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"delivered": True}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.receipts.deliver_v1(
                "r_123",
                channel_type="slack",
                channel_id="C123",
                workspace_id="T123",
                message="FYI",
            )

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/receipts/r_123/deliver",
                json={
                    "channel_type": "slack",
                    "channel_id": "C123",
                    "workspace_id": "T123",
                    "message": "FYI",
                },
            )
            client.close()

    @pytest.mark.asyncio
    async def test_async_deliver_v1_with_legacy_fields(self) -> None:
        """Deliver a receipt using legacy channel/destination fields."""
        with patch.object(AragoraAsyncClient, "request") as mock_request:
            mock_request.return_value = {"delivered": True}

            client = AragoraAsyncClient(base_url="https://api.aragora.ai")
            await client.receipts.deliver_v1(
                "r_456",
                channel="teams",
                destination="chat:19:abc",
            )

            mock_request.assert_called_once_with(
                "POST",
                "/api/v1/receipts/r_456/deliver",
                json={
                    "channel": "teams",
                    "destination": "chat:19:abc",
                },
            )
            await client.close()

    def test_list_deliveries_with_filters(self) -> None:
        """List receipt delivery history with filters."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"deliveries": [], "total": 0}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.receipts.list_deliveries(
                limit=20,
                offset=5,
                receipt_id="r_123",
                channel_type="slack",
                status="delivered",
            )

            mock_request.assert_called_once_with(
                "GET",
                "/api/v1/receipts/deliveries",
                params={
                    "limit": 20,
                    "offset": 5,
                    "receipt_id": "r_123",
                    "channel_type": "slack",
                    "status": "delivered",
                },
            )
            client.close()

    def test_list_recent_anchors(self) -> None:
        """List recently anchored receipts."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"anchors": [], "total": 0, "limit": 7}

            client = AragoraClient(base_url="https://api.aragora.ai")
            response = client.receipts.list_recent_anchors(limit=7)

            mock_request.assert_called_once_with(
                "GET",
                "/api/v1/receipts/recent-anchors",
                params={"limit": 7},
            )
            assert response == {"anchors": [], "total": 0, "limit": 7}
            client.close()

    def test_get_anchor_status_encodes_receipt_id(self) -> None:
        """Get receipt anchor status for IDs that contain path separators."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {"receipt_id": "r/123", "anchored": True}

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.receipts.get_anchor_status("r/123")

            mock_request.assert_called_once_with(
                "GET",
                "/api/v1/receipts/r%2F123/anchor-status",
            )
            client.close()

    @pytest.mark.asyncio
    async def test_async_get_anchor_status_encodes_receipt_id(self) -> None:
        """Get receipt anchor status for IDs that contain path separators."""
        with patch.object(AragoraAsyncClient, "request") as mock_request:
            mock_request.return_value = {"receipt_id": "r/123", "anchored": True}

            client = AragoraAsyncClient(base_url="https://api.aragora.ai")
            await client.receipts.get_anchor_status("r/123")

            mock_request.assert_called_once_with(
                "GET",
                "/api/v1/receipts/r%2F123/anchor-status",
            )
            await client.close()


class TestReceiptsSigningKey:
    """Tests for the ODR signing public key trust anchor."""

    def test_get_signing_key(self) -> None:
        """Fetch the JSON signing-key envelope."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = {
                "algorithm": "Ed25519",
                "key_id": "ed25519-abc",
                "public_key_pem": "-----BEGIN PUBLIC KEY-----\n...",
            }

            client = AragoraClient(base_url="https://api.aragora.ai")
            client.receipts.get_signing_key()

            mock_request.assert_called_once_with("GET", "/api/v2/receipts/signing-key")
            client.close()

    def test_get_signing_key_pem(self) -> None:
        """Fetch the raw PEM through the client's text response mode."""
        with patch.object(AragoraClient, "request") as mock_request:
            mock_request.return_value = "-----BEGIN PUBLIC KEY-----\n..."

            client = AragoraClient(base_url="https://api.aragora.ai")
            assert client.receipts.get_signing_key_pem() == "-----BEGIN PUBLIC KEY-----\n..."

            mock_request.assert_called_once_with(
                "GET",
                "/.well-known/aragora-odr-signing-key",
                headers={"Accept": "application/x-pem-file"},
                response_format="text",
            )
            client.close()

    def test_get_signing_key_pem_demo_mode_raises_not_found(self) -> None:
        """Demo mode mirrors the live 404: NotFoundError, not a hard crash."""
        from aragora_sdk.exceptions import NotFoundError

        client = AragoraClient(demo=True)
        with pytest.raises(NotFoundError):
            client.receipts.get_signing_key_pem()
        client.close()

    def test_get_signing_key_pem_with_real_text_transport(self) -> None:
        """Exercise the real client's non-JSON response path."""
        pem = "-----BEGIN PUBLIC KEY-----\nreal-key\n-----END PUBLIC KEY-----\n"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/.well-known/aragora-odr-signing-key"
            assert request.headers["accept"] == "application/x-pem-file"
            return httpx.Response(
                200,
                text=pem,
                headers={"content-type": "application/x-pem-file"},
            )

        client = AragoraClient(base_url="https://api.aragora.ai", max_retries=1)
        client._client.close()
        client._client = HTTPXClient(transport=httpx.MockTransport(handler))
        try:
            assert client.receipts.get_signing_key_pem() == pem
        finally:
            client.close()

    @pytest.mark.asyncio
    async def test_async_get_signing_key(self) -> None:
        """Fetch the JSON signing-key envelope (async)."""
        with patch.object(AragoraAsyncClient, "request") as mock_request:
            mock_request.return_value = {"algorithm": "Ed25519"}

            client = AragoraAsyncClient(base_url="https://api.aragora.ai")
            await client.receipts.get_signing_key()

            mock_request.assert_called_once_with("GET", "/api/v2/receipts/signing-key")
            await client.close()

    @pytest.mark.asyncio
    async def test_async_get_signing_key_pem(self) -> None:
        """Fetch the raw PEM through the async client's text response mode."""
        with patch.object(AragoraAsyncClient, "request") as mock_request:
            mock_request.return_value = "-----BEGIN PUBLIC KEY-----\n..."

            client = AragoraAsyncClient(base_url="https://api.aragora.ai")
            assert await client.receipts.get_signing_key_pem() == "-----BEGIN PUBLIC KEY-----\n..."

            mock_request.assert_called_once_with(
                "GET",
                "/.well-known/aragora-odr-signing-key",
                headers={"Accept": "application/x-pem-file"},
                response_format="text",
            )
            await client.close()
