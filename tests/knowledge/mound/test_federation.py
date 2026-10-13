"""
Tests for Knowledge Federation Mixin.

Tests cover:
- register_federated_region
- unregister_federated_region
- sync_to_region
- pull_from_region
- sync_all_regions
- get_federation_status
- FederationMode enum
- SyncScope enum
"""

import pytest
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.knowledge.mound.ops.federation import (
    KnowledgeFederationMixin,
    FederationMode,
    SyncScope,
    FederatedRegion,
    SyncResult,
)
from aragora.knowledge.mound.types import KnowledgeSource
from aragora.storage.federation_registry_store import (
    InMemoryFederationRegistryStore,
    reset_federation_registry_store,
    set_federation_registry_store,
)


@pytest.fixture(autouse=True)
def isolated_federation_registry_store():
    """Keep federation tests isolated from the process-global registry backend."""
    KnowledgeFederationMixin._federated_regions.clear()
    set_federation_registry_store(InMemoryFederationRegistryStore())
    try:
        yield
    finally:
        KnowledgeFederationMixin._federated_regions.clear()
        reset_federation_registry_store()


# =============================================================================
# FederationMode Tests
# =============================================================================


class TestFederationMode:
    """Tests for FederationMode enum."""

    def test_federation_mode_values(self):
        """Should have correct mode values."""
        assert FederationMode.PUSH.value == "push"
        assert FederationMode.PULL.value == "pull"
        assert FederationMode.BIDIRECTIONAL.value == "bidirectional"
        assert FederationMode.NONE.value == "none"

    def test_federation_mode_from_string(self):
        """Should create from string."""
        assert FederationMode("push") == FederationMode.PUSH
        assert FederationMode("bidirectional") == FederationMode.BIDIRECTIONAL


# =============================================================================
# SyncScope Tests
# =============================================================================


class TestSyncScope:
    """Tests for SyncScope enum."""

    def test_sync_scope_values(self):
        """Should have correct scope values."""
        assert SyncScope.FULL.value == "full"
        assert SyncScope.METADATA.value == "metadata"
        assert SyncScope.SUMMARY.value == "summary"


# =============================================================================
# FederatedRegion Tests
# =============================================================================


class TestFederatedRegion:
    """Tests for FederatedRegion dataclass."""

    def test_create_basic_region(self):
        """Should create a basic region."""
        region = FederatedRegion(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io/api",
            api_key="secret_key",
        )
        assert region.region_id == "us-east"
        assert region.endpoint_url == "https://us-east.aragora.io/api"
        assert region.api_key == "secret_key"
        assert region.mode == FederationMode.BIDIRECTIONAL
        assert region.sync_scope == SyncScope.SUMMARY
        assert region.enabled is True

    def test_create_region_with_options(self):
        """Should create region with custom options."""
        region = FederatedRegion(
            region_id="eu-west",
            endpoint_url="https://eu-west.aragora.io/api",
            api_key="key",
            mode=FederationMode.PULL,
            sync_scope=SyncScope.FULL,
            enabled=False,
        )
        assert region.mode == FederationMode.PULL
        assert region.sync_scope == SyncScope.FULL
        assert region.enabled is False


# =============================================================================
# SyncResult Tests
# =============================================================================


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_create_success_result(self):
        """Should create a success result."""
        result = SyncResult(
            region_id="us-east",
            direction="push",
            nodes_synced=100,
            duration_ms=500.5,
        )
        assert result.success is True
        assert result.error is None
        assert result.nodes_synced == 100

    def test_create_error_result(self):
        """Should create an error result."""
        result = SyncResult(
            region_id="eu-west",
            direction="pull",
            success=False,
            error="Connection refused",
        )
        assert result.success is False
        assert result.error == "Connection refused"


# =============================================================================
# MockKnowledgeMound for Testing
# =============================================================================


class MockKnowledgeMound(KnowledgeFederationMixin):
    """Mock KnowledgeMound with KnowledgeFederationMixin."""

    def __init__(self):
        self.config = MagicMock()
        self.config.max_query_limit = 100
        self.workspace_id = "test_workspace"
        self._meta_store = MagicMock()
        self._cache = None
        self._initialized = True
        self._items = []
        # Reset class-level registry for each test (use clear() to modify in place)
        KnowledgeFederationMixin._federated_regions.clear()

    def _ensure_initialized(self):
        if not self._initialized:
            raise RuntimeError("Not initialized")

    async def store(self, request):
        """Mock store method."""
        result = MagicMock()
        result.node_id = f"kn_{len(self._items)}"
        self._items.append(request)
        return result

    async def query(self, query, sources=("all",), filters=None, limit=20, workspace_id=None):
        """Mock query method."""
        result = MagicMock()
        items = []
        for i, req in enumerate(self._items):
            if workspace_id and hasattr(req, "workspace_id") and req.workspace_id != workspace_id:
                continue
            item = MagicMock()
            item.id = f"kn_{i}"
            item.content = req.content if hasattr(req, "content") else "Content"
            item.importance = 0.8
            item.metadata = req.metadata if hasattr(req, "metadata") else {}
            items.append(item)
        result.items = items[:limit]
        return result


# =============================================================================
# register_federated_region Tests
# =============================================================================


class TestRegisterFederatedRegion:
    """Tests for register_federated_region method."""

    @pytest.mark.asyncio
    async def test_register_basic_region(self):
        """Should register a basic region."""
        mound = MockKnowledgeMound()

        region = await mound.register_federated_region(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io/api",
            api_key="secret",
        )

        assert region.region_id == "us-east"
        assert region.endpoint_url == "https://us-east.aragora.io/api"
        assert region.mode == FederationMode.BIDIRECTIONAL

    @pytest.mark.asyncio
    async def test_register_with_options(self):
        """Should register region with custom options."""
        mound = MockKnowledgeMound()

        region = await mound.register_federated_region(
            region_id="eu-west",
            endpoint_url="https://eu-west.aragora.io/api",
            api_key="key",
            mode=FederationMode.PUSH,
            sync_scope=SyncScope.METADATA,
        )

        assert region.mode == FederationMode.PUSH
        assert region.sync_scope == SyncScope.METADATA

    @pytest.mark.asyncio
    async def test_register_stores_in_registry(self):
        """Should store region in registry."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="asia-pacific",
            endpoint_url="https://apac.aragora.io/api",
            api_key="key",
        )

        assert "asia-pacific" in KnowledgeFederationMixin._federated_regions

    @pytest.mark.asyncio
    async def test_register_multiple_regions(self):
        """Should register multiple regions."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io",
            api_key="key1",
        )
        await mound.register_federated_region(
            region_id="eu-west",
            endpoint_url="https://eu-west.aragora.io",
            api_key="key2",
        )
        await mound.register_federated_region(
            region_id="asia-pacific",
            endpoint_url="https://apac.aragora.io",
            api_key="key3",
        )

        assert len(KnowledgeFederationMixin._federated_regions) == 3


# =============================================================================
# unregister_federated_region Tests
# =============================================================================


class TestUnregisterFederatedRegion:
    """Tests for unregister_federated_region method."""

    @pytest.mark.asyncio
    async def test_unregister_existing_region(self):
        """Should unregister existing region."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io",
            api_key="key",
        )

        result = await mound.unregister_federated_region("us-east")

        assert result is True
        assert "us-east" not in KnowledgeFederationMixin._federated_regions

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_region(self):
        """Should return False for nonexistent region."""
        mound = MockKnowledgeMound()

        result = await mound.unregister_federated_region("nonexistent")

        assert result is False


# =============================================================================
# sync_to_region Tests
# =============================================================================


class TestSyncToRegion:
    """Tests for sync_to_region method."""

    @pytest.mark.asyncio
    async def test_sync_to_unregistered_region(self):
        """Should fail for unregistered region."""
        mound = MockKnowledgeMound()

        result = await mound.sync_to_region("unregistered")

        assert result.success is False
        assert "not registered" in result.error

    @pytest.mark.asyncio
    async def test_sync_to_pull_only_region(self):
        """Should fail for pull-only region."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="pull-only",
            endpoint_url="https://pull.aragora.io",
            api_key="key",
            mode=FederationMode.PULL,
        )

        result = await mound.sync_to_region("pull-only")

        assert result.success is False
        assert "pull-only" in result.error

    @pytest.mark.asyncio
    async def test_sync_to_region_success(self):
        """Should sync successfully."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io",
            api_key="key",
            mode=FederationMode.PUSH,
        )

        # Add some items
        from aragora.knowledge.mound.types import IngestionRequest

        for i in range(5):
            req = IngestionRequest(
                content=f"Item {i}",
                workspace_id="test_workspace",
                source_type=KnowledgeSource.FACT,
                metadata={"visibility": "public"},
            )
            await mound.store(req)

        result = await mound.sync_to_region("us-east")

        assert result.success is True
        assert result.direction == "push"
        assert result.nodes_synced >= 0

    @pytest.mark.asyncio
    async def test_sync_updates_last_sync_time(self):
        """Should update last sync time on success."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io",
            api_key="key",
        )

        await mound.sync_to_region("us-east")

        region = KnowledgeFederationMixin._federated_regions["us-east"]
        assert region.last_sync_at is not None


# =============================================================================
# pull_from_region Tests
# =============================================================================


class TestPullFromRegion:
    """Tests for pull_from_region method."""

    @pytest.mark.asyncio
    async def test_pull_from_unregistered_region(self):
        """Should fail for unregistered region."""
        mound = MockKnowledgeMound()

        result = await mound.pull_from_region("unregistered")

        assert result.success is False
        assert "not registered" in result.error

    @pytest.mark.asyncio
    async def test_pull_from_push_only_region(self):
        """Should fail for push-only region."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="push-only",
            endpoint_url="https://push.aragora.io",
            api_key="key",
            mode=FederationMode.PUSH,
        )

        result = await mound.pull_from_region("push-only")

        assert result.success is False
        assert "push-only" in result.error

    @pytest.mark.asyncio
    async def test_pull_from_region_success(self):
        """Should pull successfully."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io",
            api_key="key",
            mode=FederationMode.PULL,
        )

        result = await mound.pull_from_region("us-east")

        assert result.success is True
        assert result.direction == "pull"


# =============================================================================
# sync_all_regions Tests
# =============================================================================


class TestSyncAllRegions:
    """Tests for sync_all_regions method."""

    @pytest.mark.asyncio
    async def test_sync_all_empty(self):
        """Should return empty when no regions."""
        mound = MockKnowledgeMound()

        # Mock the persistent store to avoid loading persisted data from previous runs
        with patch(
            "aragora.storage.federation_registry_store.get_federation_registry_store",
            side_effect=ImportError("Mocked for test"),
        ):
            results = await mound.sync_all_regions()

            assert results == []

    @pytest.mark.asyncio
    async def test_sync_all_multiple_regions(self):
        """Should sync all registered regions."""
        mound = MockKnowledgeMound()

        # Mock the persistent store to use only cache
        with patch(
            "aragora.storage.federation_registry_store.get_federation_registry_store",
            side_effect=ImportError("Mocked for test"),
        ):
            await mound.register_federated_region(
                region_id="us-east",
                endpoint_url="https://us-east.aragora.io",
                api_key="key1",
                mode=FederationMode.PUSH,
            )
            await mound.register_federated_region(
                region_id="eu-west",
                endpoint_url="https://eu-west.aragora.io",
                api_key="key2",
                mode=FederationMode.PULL,
            )

            results = await mound.sync_all_regions()

            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_sync_all_skips_disabled(self):
        """Should skip disabled regions."""
        mound = MockKnowledgeMound()

        # Mock the persistent store to use only cache
        with patch(
            "aragora.storage.federation_registry_store.get_federation_registry_store",
            side_effect=ImportError("Mocked for test"),
        ):
            await mound.register_federated_region(
                region_id="enabled",
                endpoint_url="https://enabled.aragora.io",
                api_key="key",
                mode=FederationMode.PUSH,
            )

            # Disable the region
            KnowledgeFederationMixin._federated_regions["enabled"].enabled = False

            results = await mound.sync_all_regions()

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_sync_all_bidirectional(self):
        """Should do both push and pull for bidirectional."""
        mound = MockKnowledgeMound()


class _CoordinatorFederationMode:
    ISOLATED = "isolated"
    READONLY = "readonly"
    BIDIRECTIONAL = "bidirectional"
    ORCHESTRATED = "orchestrated"


def _fake_cross_workspace_module(register_workspace_mock: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(
        CrossWorkspaceCoordinator=lambda: SimpleNamespace(
            register_workspace=register_workspace_mock
        ),
        FederatedWorkspace=lambda **kwargs: SimpleNamespace(**kwargs),
        FederationMode=_CoordinatorFederationMode,
    )


class TestCoordinatorRegistration:
    """Tests for coordinator federation-mode compatibility mapping."""

    @pytest.mark.asyncio
    async def test_register_with_coordinator_maps_pull_to_readonly(self):
        mound = MockKnowledgeMound()
        register_workspace = MagicMock()
        fake_module = _fake_cross_workspace_module(register_workspace)

        region = FederatedRegion(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io/api",
            api_key="secret",
            mode=FederationMode.PULL,
        )

        with patch.dict(sys.modules, {"aragora.tenancy.cross_workspace": fake_module}):
            await mound._register_with_coordinator(region)

        workspace = register_workspace.call_args.args[0]
        assert workspace.federation_mode == _CoordinatorFederationMode.READONLY

    @pytest.mark.asyncio
    async def test_register_with_coordinator_defaults_invalid_modes_to_isolated(self):
        mound = MockKnowledgeMound()
        register_workspace = MagicMock()
        fake_module = _fake_cross_workspace_module(register_workspace)

        region = FederatedRegion(
            region_id="eu-west",
            endpoint_url="https://eu-west.aragora.io/api",
            api_key="secret",
        )
        region.mode = "unsupported-mode"  # type: ignore[assignment]

        with (
            patch.dict(sys.modules, {"aragora.tenancy.cross_workspace": fake_module}),
            patch("aragora.knowledge.mound.ops.federation.logger.warning") as warning,
        ):
            await mound._register_with_coordinator(region)

        workspace = register_workspace.call_args.args[0]
        assert workspace.federation_mode == _CoordinatorFederationMode.ISOLATED
        warning.assert_called_once()

        # Mock the persistent store to use only cache
        with patch(
            "aragora.storage.federation_registry_store.get_federation_registry_store",
            side_effect=ImportError("Mocked for test"),
        ):
            await mound.register_federated_region(
                region_id="us-east",
                endpoint_url="https://us-east.aragora.io",
                api_key="key",
                mode=FederationMode.BIDIRECTIONAL,
            )

            results = await mound.sync_all_regions()

        # Should have both push and pull results
        assert len(results) == 2
        directions = {r.direction for r in results}
        assert "push" in directions
        assert "pull" in directions


# =============================================================================
# get_federation_status Tests
# =============================================================================


class TestGetFederationStatus:
    """Tests for get_federation_status method."""

    @pytest.mark.asyncio
    async def test_status_empty(self):
        """Should return empty dict when no regions."""
        mound = MockKnowledgeMound()

        # Mock the persistent store to use only cache
        with patch(
            "aragora.storage.federation_registry_store.get_federation_registry_store",
            side_effect=ImportError("Mocked for test"),
        ):
            status = await mound.get_federation_status()

        assert status == {}

    @pytest.mark.asyncio
    async def test_status_with_regions(self):
        """Should return status for all regions."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io",
            api_key="key",
            mode=FederationMode.PUSH,
        )

        status = await mound.get_federation_status()

        assert "us-east" in status
        assert status["us-east"]["mode"] == "push"
        assert status["us-east"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_status_includes_sync_info(self):
        """Should include last sync info."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io",
            api_key="key",
        )

        # Sync to update last_sync_at
        await mound.sync_to_region("us-east")

        status = await mound.get_federation_status()

        assert status["us-east"]["last_sync_at"] is not None


# =============================================================================
# _apply_sync_scope Tests
# =============================================================================


class TestApplySyncScope:
    """Tests for _apply_sync_scope helper."""

    def test_full_scope(self):
        """Should include all data for FULL scope."""
        mound = MockKnowledgeMound()

        item = MagicMock()
        item.id = "item_1"
        item.content = "Full content here"
        item.importance = 0.8
        item.metadata = {"key": "value"}

        result = mound._apply_sync_scope(item, SyncScope.FULL)

        assert result["id"] == "item_1"
        assert result["content"] == "Full content here"
        assert result["metadata"] == {"key": "value"}

    def test_summary_scope(self):
        """Should truncate content for SUMMARY scope."""
        mound = MockKnowledgeMound()

        item = MagicMock()
        item.id = "item_1"
        item.content = "A" * 1000  # Long content
        item.importance = 0.8
        item.metadata = {"topics": ["test"], "extra": "data"}

        result = mound._apply_sync_scope(item, SyncScope.SUMMARY)

        assert result["id"] == "item_1"
        assert len(result["content"]) <= 500
        assert "extra" not in result["metadata"]

    def test_metadata_scope(self):
        """Should only include metadata for METADATA scope."""
        mound = MockKnowledgeMound()

        item = MagicMock()
        item.id = "item_1"
        item.content = "Full content"
        item.metadata = {"content_hash": "abc123", "topics": ["test"]}

        result = mound._apply_sync_scope(item, SyncScope.METADATA)

        assert result["id"] == "item_1"
        assert "content" not in result or result.get("content_hash")
        assert result["metadata"] is not None


# =============================================================================
# Integration Tests
# =============================================================================


class TestFederationIntegration:
    """Integration tests for federation workflow."""

    @pytest.mark.asyncio
    async def test_full_federation_workflow(self):
        """Test complete federation workflow."""
        mound = MockKnowledgeMound()

        # Mock the persistent store to use only cache
        with patch(
            "aragora.storage.federation_registry_store.get_federation_registry_store",
            side_effect=ImportError("Mocked for test"),
        ):
            # Register regions
            await mound.register_federated_region(
                region_id="us-east",
                endpoint_url="https://us-east.aragora.io",
                api_key="key1",
                mode=FederationMode.BIDIRECTIONAL,
            )
            await mound.register_federated_region(
                region_id="eu-west",
                endpoint_url="https://eu-west.aragora.io",
                api_key="key2",
                mode=FederationMode.PUSH,
            )

            # Check status
            status = await mound.get_federation_status()
            assert len(status) == 2

            # Sync all
            results = await mound.sync_all_regions()
            assert len(results) == 3  # 2 for bidirectional + 1 for push-only

            # Unregister one
            await mound.unregister_federated_region("eu-west")

            # Verify
            status = await mound.get_federation_status()
            assert len(status) == 1
            assert "us-east" in status

    @pytest.mark.asyncio
    async def test_sync_with_since_filter(self):
        """Test sync with time filter."""
        mound = MockKnowledgeMound()

        await mound.register_federated_region(
            region_id="us-east",
            endpoint_url="https://us-east.aragora.io",
            api_key="key",
        )

        # Sync with since filter
        since = datetime.now() - timedelta(hours=1)
        result = await mound.sync_to_region("us-east", since=since)

        assert result.success is True
