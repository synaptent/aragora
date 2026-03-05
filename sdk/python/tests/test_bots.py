"""Tests for Bots namespace API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aragora_sdk.client import AragoraAsyncClient, AragoraClient


def test_slack_status_sync() -> None:
    """Get Slack bot status through bots namespace."""
    with patch.object(AragoraClient, "request") as mock_request:
        mock_request.return_value = {"connected": True}

        client = AragoraClient(base_url="https://api.aragora.ai")
        client.bots.slack_status()

        mock_request.assert_called_once_with("GET", "/api/v1/bots/slack/status")
        client.close()


@pytest.mark.asyncio
async def test_slack_status_async() -> None:
    """Get Slack bot status through async bots namespace."""
    with patch.object(AragoraAsyncClient, "request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = {"connected": True}

        async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
            await client.bots.slack_status()

        mock_request.assert_awaited_once_with("GET", "/api/v1/bots/slack/status")
