"""Unified tests for the four SDK namespaces: moderation, audience, modes, spectate.

Covers all sync and async methods with mocked HTTP calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aragora_sdk", reason="aragora-sdk not installed")

from aragora_sdk.namespaces.audience import (  # noqa: E402
    AsyncAudienceAPI,
    AudienceAPI,
)
from aragora_sdk.namespaces.moderation import (  # noqa: E402
    AsyncModerationAPI,
    ModerationAPI,
)
from aragora_sdk.namespaces.modes import AsyncModesAPI, ModesAPI  # noqa: E402
from aragora_sdk.namespaces.spectate import (  # noqa: E402
    AsyncSpectateAPI,
    SpectateAPI,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sync_client() -> MagicMock:
    """Return a mock synchronous client."""
    client = MagicMock()
    client.request.return_value = {"status": "ok"}
    return client


@pytest.fixture
def async_client() -> MagicMock:
    """Return a mock asynchronous client."""
    client = MagicMock()
    client.request = AsyncMock(return_value={"status": "ok"})
    return client


# ===========================================================================
# Moderation
# ===========================================================================


class TestModerationSync:
    """Sync ModerationAPI -- 6 methods."""

    @pytest.fixture(autouse=True)
    def setup(self, sync_client: MagicMock) -> None:
        self.client = sync_client
        self.api = ModerationAPI(sync_client)

    def test_get_config(self) -> None:
        result = self.api.get_config()
        self.client.request.assert_called_once_with("GET", "/api/v1/moderation/config")
        assert result == {"status": "ok"}

    def test_update_config(self) -> None:
        config = {"spam_threshold": 0.9, "auto_reject": True}
        result = self.api.update_config(config)
        self.client.request.assert_called_once_with("PUT", "/api/v1/moderation/config", json=config)
        assert result == {"status": "ok"}

    def test_get_stats(self) -> None:
        result = self.api.get_stats()
        self.client.request.assert_called_once_with("GET", "/api/v1/moderation/stats")
        assert result == {"status": "ok"}

    def test_get_queue(self) -> None:
        result = self.api.get_queue()
        self.client.request.assert_called_once_with("GET", "/api/v1/moderation/queue")
        assert result == {"status": "ok"}

    def test_approve_item(self) -> None:
        result = self.api.approve_item("item-42")
        self.client.request.assert_called_once_with(
            "POST", "/api/v1/moderation/items/item-42/approve"
        )
        assert result == {"status": "ok"}

    def test_reject_item(self) -> None:
        result = self.api.reject_item("item-99")
        self.client.request.assert_called_once_with(
            "POST", "/api/v1/moderation/items/item-99/reject"
        )
        assert result == {"status": "ok"}


class TestModerationAsync:
    """Async ModerationAPI -- 6 methods."""

    @pytest.fixture(autouse=True)
    def setup(self, async_client: MagicMock) -> None:
        self.client = async_client
        self.api = AsyncModerationAPI(async_client)

    @pytest.mark.asyncio
    async def test_get_config(self) -> None:
        result = await self.api.get_config()
        self.client.request.assert_awaited_once_with("GET", "/api/v1/moderation/config")
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_update_config(self) -> None:
        config = {"spam_threshold": 0.5}
        result = await self.api.update_config(config)
        self.client.request.assert_awaited_once_with(
            "PUT", "/api/v1/moderation/config", json=config
        )
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_get_stats(self) -> None:
        result = await self.api.get_stats()
        self.client.request.assert_awaited_once_with("GET", "/api/v1/moderation/stats")
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_get_queue(self) -> None:
        result = await self.api.get_queue()
        self.client.request.assert_awaited_once_with("GET", "/api/v1/moderation/queue")
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_approve_item(self) -> None:
        result = await self.api.approve_item("item-async-1")
        self.client.request.assert_awaited_once_with(
            "POST", "/api/v1/moderation/items/item-async-1/approve"
        )
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_reject_item(self) -> None:
        result = await self.api.reject_item("item-async-2")
        self.client.request.assert_awaited_once_with(
            "POST", "/api/v1/moderation/items/item-async-2/reject"
        )
        assert result == {"status": "ok"}


# ===========================================================================
# Audience
# ===========================================================================


class TestAudienceSync:
    """Sync AudienceAPI -- get_suggestions, submit_suggestion."""

    @pytest.fixture(autouse=True)
    def setup(self, sync_client: MagicMock) -> None:
        self.client = sync_client
        self.api = AudienceAPI(sync_client)

    def test_get_suggestions(self) -> None:
        result = self.api.get_suggestions("debate-100")
        self.client.request.assert_called_once_with(
            "GET", "/api/v1/debates/debate-100/audience/suggestions"
        )
        assert result == {"status": "ok"}

    def test_submit_suggestion(self) -> None:
        suggestion = {"text": "Consider environmental impact", "author": "user-5"}
        result = self.api.submit_suggestion("debate-200", suggestion)
        self.client.request.assert_called_once_with(
            "POST",
            "/api/v1/debates/debate-200/audience/suggestions",
            json=suggestion,
        )
        assert result == {"status": "ok"}

    def test_get_suggestions_with_different_id(self) -> None:
        self.api.get_suggestions("abc-xyz")
        self.client.request.assert_called_once_with(
            "GET", "/api/v1/debates/abc-xyz/audience/suggestions"
        )

    def test_submit_empty_suggestion(self) -> None:
        self.api.submit_suggestion("debate-300", {})
        self.client.request.assert_called_once_with(
            "POST",
            "/api/v1/debates/debate-300/audience/suggestions",
            json={},
        )

    def test_list_suggestions(self) -> None:
        """Test the list_suggestions method with clustering parameters."""
        result = self.api.list_suggestions("debate-400", max_clusters=3, threshold=0.7)
        self.client.request.assert_called_once_with(
            "GET",
            "/api/v1/audience/suggestions",
            params={"debate_id": "debate-400", "max_clusters": 3, "threshold": 0.7},
        )
        assert result == {"status": "ok"}

    def test_create_suggestion(self) -> None:
        """Test the create_suggestion method."""
        suggestion = {"text": "New idea"}
        result = self.api.create_suggestion("debate-500", suggestion)
        self.client.request.assert_called_once_with(
            "POST",
            "/api/v1/audience/suggestions",
            json={"text": "New idea", "debate_id": "debate-500"},
        )
        assert result == {"status": "ok"}


class TestAudienceAsync:
    """Async AudienceAPI -- get_suggestions, submit_suggestion."""

    @pytest.fixture(autouse=True)
    def setup(self, async_client: MagicMock) -> None:
        self.client = async_client
        self.api = AsyncAudienceAPI(async_client)

    @pytest.mark.asyncio
    async def test_get_suggestions(self) -> None:
        result = await self.api.get_suggestions("debate-async-1")
        self.client.request.assert_awaited_once_with(
            "GET", "/api/v1/debates/debate-async-1/audience/suggestions"
        )
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_submit_suggestion(self) -> None:
        suggestion = {"text": "Async suggestion"}
        result = await self.api.submit_suggestion("debate-async-2", suggestion)
        self.client.request.assert_awaited_once_with(
            "POST",
            "/api/v1/debates/debate-async-2/audience/suggestions",
            json=suggestion,
        )
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_list_suggestions(self) -> None:
        result = await self.api.list_suggestions("debate-async-3")
        self.client.request.assert_awaited_once_with(
            "GET",
            "/api/v1/audience/suggestions",
            params={"debate_id": "debate-async-3", "max_clusters": 5, "threshold": 0.6},
        )
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_create_suggestion(self) -> None:
        suggestion = {"text": "Async new idea"}
        result = await self.api.create_suggestion("debate-async-4", suggestion)
        self.client.request.assert_awaited_once_with(
            "POST",
            "/api/v1/audience/suggestions",
            json={"text": "Async new idea", "debate_id": "debate-async-4"},
        )
        assert result == {"status": "ok"}


# ===========================================================================
# Modes
# ===========================================================================


class TestModesSync:
    """Sync ModesAPI -- list_modes."""

    @pytest.fixture(autouse=True)
    def setup(self, sync_client: MagicMock) -> None:
        self.client = sync_client
        self.api = ModesAPI(sync_client)

    def test_list_modes(self) -> None:
        result = self.api.list_modes()
        self.client.request.assert_called_once_with("GET", "/api/v1/modes")
        assert result == {"status": "ok"}


class TestModesAsync:
    """Async ModesAPI -- list_modes."""

    @pytest.fixture(autouse=True)
    def setup(self, async_client: MagicMock) -> None:
        self.client = async_client
        self.api = AsyncModesAPI(async_client)

    @pytest.mark.asyncio
    async def test_list_modes(self) -> None:
        result = await self.api.list_modes()
        self.client.request.assert_awaited_once_with("GET", "/api/v1/modes")
        assert result == {"status": "ok"}


# ===========================================================================
# Spectate
# ===========================================================================


class TestSpectateSync:
    """Sync SpectateAPI -- get_recent, get_status, get_stream."""

    @pytest.fixture(autouse=True)
    def setup(self, sync_client: MagicMock) -> None:
        self.client = sync_client
        self.api = SpectateAPI(sync_client)

    def test_get_recent_defaults(self) -> None:
        self.api.get_recent()
        self.client.request.assert_called_once_with(
            "GET", "/api/v1/spectate/recent", params={"count": 50}
        )

    def test_get_recent_with_params(self) -> None:
        self.api.get_recent(count=10, debate_id="d-123")
        self.client.request.assert_called_once_with(
            "GET",
            "/api/v1/spectate/recent",
            params={"count": 10, "debate_id": "d-123"},
        )

    def test_get_status(self) -> None:
        self.api.get_status()
        self.client.request.assert_called_once_with("GET", "/api/v1/spectate/status")

    def test_get_stream(self) -> None:
        self.api.get_stream(count=25)
        self.client.request.assert_called_once_with(
            "GET",
            "/api/v1/spectate/stream",
            params={"count": 25},
        )


class TestSpectateAsync:
    """Async SpectateAPI -- get_recent, get_status, get_stream."""

    @pytest.fixture(autouse=True)
    def setup(self, async_client: MagicMock) -> None:
        self.client = async_client
        self.api = AsyncSpectateAPI(async_client)

    @pytest.mark.asyncio
    async def test_get_recent(self) -> None:
        await self.api.get_recent(count=20, debate_id="d-456")
        self.client.request.assert_awaited_once_with(
            "GET",
            "/api/v1/spectate/recent",
            params={"count": 20, "debate_id": "d-456"},
        )

    @pytest.mark.asyncio
    async def test_get_status(self) -> None:
        await self.api.get_status()
        self.client.request.assert_awaited_once_with("GET", "/api/v1/spectate/status")

    @pytest.mark.asyncio
    async def test_get_stream(self) -> None:
        await self.api.get_stream()
        self.client.request.assert_awaited_once_with(
            "GET",
            "/api/v1/spectate/stream",
            params={"count": 50},
        )


# ===========================================================================
# Cross-namespace: verify __init__.py exports
# ===========================================================================


class TestNamespaceExports:
    """Verify all classes are importable from the namespaces package."""

    def test_moderation_exports(self) -> None:
        from aragora_sdk.namespaces import AsyncModerationAPI, ModerationAPI

        assert ModerationAPI is not None
        assert AsyncModerationAPI is not None

    def test_audience_exports(self) -> None:
        from aragora_sdk.namespaces import AsyncAudienceAPI, AudienceAPI

        assert AudienceAPI is not None
        assert AsyncAudienceAPI is not None

    def test_modes_exports(self) -> None:
        from aragora_sdk.namespaces import AsyncModesAPI, ModesAPI

        assert ModesAPI is not None
        assert AsyncModesAPI is not None

    def test_spectate_exports(self) -> None:
        from aragora_sdk.namespaces import AsyncSpectateAPI, SpectateAPI

        assert SpectateAPI is not None
        assert AsyncSpectateAPI is not None


# ===========================================================================
# Client integration: verify namespaces are accessible on the client
# ===========================================================================


class TestClientRegistration:
    """Verify namespaces are registered on AragoraClient and AragoraAsyncClient."""

    def test_sync_client_has_namespaces(self) -> None:
        from aragora_sdk.client import AragoraClient

        client = AragoraClient(base_url="http://localhost:8080", demo=True)
        assert hasattr(client, "moderation")
        assert hasattr(client, "audience")
        assert hasattr(client, "modes")
        assert hasattr(client, "spectate")
        assert isinstance(client.moderation, ModerationAPI)
        assert isinstance(client.audience, AudienceAPI)
        assert isinstance(client.modes, ModesAPI)
        assert isinstance(client.spectate, SpectateAPI)

    def test_async_client_has_namespaces(self) -> None:
        from aragora_sdk.client import AragoraAsyncClient

        client = AragoraAsyncClient(base_url="http://localhost:8080", demo=True)
        assert hasattr(client, "moderation")
        assert hasattr(client, "audience")
        assert hasattr(client, "modes")
        assert hasattr(client, "spectate")
        assert isinstance(client.moderation, AsyncModerationAPI)
        assert isinstance(client.audience, AsyncAudienceAPI)
        assert isinstance(client.modes, AsyncModesAPI)
        assert isinstance(client.spectate, AsyncSpectateAPI)
