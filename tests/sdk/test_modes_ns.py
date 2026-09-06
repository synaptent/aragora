"""Tests for the Modes SDK namespace."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aragora_sdk.namespaces.modes import AsyncModesAPI, ModesAPI


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.request.return_value = {"modes": []}
    return client


@pytest.fixture
def api(mock_client):
    return ModesAPI(mock_client)


class TestModesAPI:
    def test_list_modes(self, api, mock_client):
        result = api.list_modes()
        mock_client.request.assert_called_once_with("GET", "/api/v1/modes")
        assert result == {"modes": []}

    def test_async_class_exists(self):
        """Verify AsyncModesAPI can be instantiated."""
        mock_client = MagicMock()
        async_api = AsyncModesAPI(mock_client)
        assert async_api is not None
