"""Tests for the Spectate SDK namespace."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aragora_sdk.namespaces.spectate import AsyncSpectateAPI, SpectateAPI


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.request.return_value = {"stream_url": "https://api.aragora.ai/sse/debate-1"}
    return client


@pytest.fixture
def api(mock_client):
    return SpectateAPI(mock_client)


class TestSpectateAPI:
    def test_async_class_exists(self):
        """Verify AsyncSpectateAPI can be instantiated."""
        mock_client = MagicMock()
        async_api = AsyncSpectateAPI(mock_client)
        assert async_api is not None

    def test_sync_api_init(self):
        """Verify SpectateAPI stores client reference."""
        mock_client = MagicMock()
        api = SpectateAPI(mock_client)
        assert api._client is mock_client
