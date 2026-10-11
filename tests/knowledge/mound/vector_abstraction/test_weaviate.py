"""
Tests for Weaviate vector store adapter.

Covers connection management, CRUD operations, vector similarity search,
hybrid search, filter queries, error handling, and edge cases using mocked
weaviate-client.
"""

import uuid

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from aragora.knowledge.mound.vector_abstraction.base import (
    VectorBackend,
    VectorSearchResult,
    VectorStoreConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config():
    """Create test configuration for Weaviate."""
    return VectorStoreConfig(
        backend=VectorBackend.WEAVIATE,
        url="http://localhost:8080",
        collection_name="test_collection",
        embedding_dimensions=1536,
        distance_metric="cosine",
    )


@pytest.fixture
def config_with_api_key():
    """Create test configuration with API key."""
    return VectorStoreConfig(
        backend=VectorBackend.WEAVIATE,
        url="http://localhost:8080",
        api_key="test-api-key",
        collection_name="test_collection",
        embedding_dimensions=1536,
        extra={"grpc_port": 50051},
    )


@pytest.fixture
def mock_weaviate_env():
    """
    Patch Weaviate availability and client factory so WeaviateVectorStore
    can be instantiated without the real library.
    Yields mock_client for further customisation inside tests.
    """
    mock_client = MagicMock()

    # Mock collections interface
    mock_collections = MagicMock()
    mock_client.collections = mock_collections

    with (
        patch("aragora.knowledge.mound.vector_abstraction.weaviate.WEAVIATE_AVAILABLE", True),
        patch("aragora.knowledge.mound.vector_abstraction.weaviate.weaviate") as mock_weaviate_mod,
    ):
        mock_weaviate_mod.connect_to_local.return_value = mock_client
        mock_weaviate_mod.connect_to_custom.return_value = mock_client
        mock_weaviate_mod.auth.AuthApiKey.return_value = MagicMock()

        yield mock_client, mock_weaviate_mod


def _make_store(config, mock_client):
    """Helper: create a WeaviateVectorStore with pre-wired mock client."""
    from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

    store = WeaviateVectorStore(config)
    store._client = mock_client
    store._connected = True
    return store


def _make_batch_store(config, mock_client):
    """Helper: create a connected store whose collection yields a mock dynamic batch."""
    store = _make_store(config, mock_client)
    mock_collection = MagicMock()
    mock_batch = MagicMock()
    mock_collection.batch.dynamic.return_value.__enter__ = MagicMock(return_value=mock_batch)
    mock_collection.batch.dynamic.return_value.__exit__ = MagicMock(return_value=False)
    store._collections["test_collection"] = mock_collection
    return store, mock_batch


def _embedding(dim=1536, val=0.1):
    """Helper: create a dummy embedding vector."""
    return [val] * dim


def _mock_weaviate_object(uuid_val, properties, distance=None, score=None, vector=None):
    """Create a mock Weaviate query result object."""
    obj = MagicMock()
    obj.uuid = uuid_val
    obj.properties = properties

    obj.metadata = MagicMock()
    obj.metadata.distance = distance
    obj.metadata.score = score

    if vector is not None:
        obj.vector = {"default": vector}
    else:
        obj.vector = None

    return obj


# ---------------------------------------------------------------------------
# Connection Management
# ---------------------------------------------------------------------------


class TestWeaviateConnection:
    """Tests for Weaviate connection lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_local(self, config, mock_weaviate_env):
        """connect() should create a local client when no API key."""
        mock_client, mock_weaviate_mod = mock_weaviate_env

        # collection_exists returns True so it skips create_collection
        mock_client.collections.exists.return_value = True

        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        await store.connect()

        assert store.is_connected
        mock_weaviate_mod.connect_to_local.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_with_api_key(self, config_with_api_key, mock_weaviate_env):
        """connect() should use connect_to_custom when API key is set."""
        mock_client, mock_weaviate_mod = mock_weaviate_env
        mock_client.collections.exists.return_value = True

        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config_with_api_key)
        await store.connect()

        assert store.is_connected

    @pytest.mark.asyncio
    async def test_connect_already_connected_noop(self, config, mock_weaviate_env):
        """Calling connect() when already connected should not reconnect."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        await store.connect()
        # No assertions needed - just verifying no error

    @pytest.mark.asyncio
    async def test_connect_creates_collection_if_missing(self, config, mock_weaviate_env):
        """connect() should create the default collection when it does not exist."""
        mock_client, mock_weaviate_mod = mock_weaviate_env
        mock_client.collections.exists.return_value = False

        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        await store.connect()

        assert store.is_connected
        mock_client.collections.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure_raises_connection_error(self, config, mock_weaviate_env):
        """connect() should raise ConnectionError on failure."""
        _, mock_weaviate_mod = mock_weaviate_env
        mock_weaviate_mod.connect_to_local.side_effect = RuntimeError("refused")

        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError, match="Failed to connect to Weaviate"):
            await store.connect()

        assert not store.is_connected

    @pytest.mark.asyncio
    async def test_disconnect(self, config, mock_weaviate_env):
        """disconnect() should close client and reset state."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        await store.disconnect()

        mock_client.close.assert_called_once()
        assert not store.is_connected
        assert store._client is None
        assert store._collections == {}

    @pytest.mark.asyncio
    async def test_disconnect_handles_close_error(self, config, mock_weaviate_env):
        """disconnect() should handle errors during close gracefully."""
        mock_client, _ = mock_weaviate_env
        mock_client.close.side_effect = RuntimeError("close failed")
        store = _make_store(config, mock_client)

        await store.disconnect()

        assert not store.is_connected
        assert store._client is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, config, mock_weaviate_env):
        """disconnect() with no client should be a no-op."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        await store.disconnect()  # Should not raise

    @pytest.mark.asyncio
    async def test_context_manager(self, config, mock_weaviate_env):
        """Async context manager should connect and disconnect."""
        mock_client, mock_weaviate_mod = mock_weaviate_env
        mock_client.collections.exists.return_value = True

        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        async with WeaviateVectorStore(config) as store:
            assert store.is_connected

        mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Collection Management
# ---------------------------------------------------------------------------


class TestWeaviateCollections:
    """Tests for collection CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_collection(self, config, mock_weaviate_env):
        """create_collection() should create with properties."""
        mock_client, _ = mock_weaviate_env
        mock_client.collections.exists.return_value = False
        store = _make_store(config, mock_client)

        await store.create_collection("my_collection")

        mock_client.collections.create.assert_called_once()
        call_kwargs = mock_client.collections.create.call_args
        assert call_kwargs.kwargs["name"] == "my_collection"

    @pytest.mark.asyncio
    async def test_create_collection_with_schema(self, config, mock_weaviate_env):
        """create_collection() should add custom schema properties."""
        mock_client, _ = mock_weaviate_env
        mock_client.collections.exists.return_value = False
        store = _make_store(config, mock_client)

        await store.create_collection(
            "my_collection",
            schema={"topic": "string", "score": "float", "active": "bool"},
        )

        mock_client.collections.create.assert_called_once()
        call_kwargs = mock_client.collections.create.call_args
        # Should have content, namespace + 3 custom = 5 properties
        properties = call_kwargs.kwargs["properties"]
        assert len(properties) == 5

    @pytest.mark.asyncio
    async def test_create_collection_already_exists(self, config, mock_weaviate_env):
        """create_collection() should skip when collection exists."""
        mock_client, _ = mock_weaviate_env
        mock_client.collections.exists.return_value = True
        store = _make_store(config, mock_client)

        await store.create_collection("existing")

        mock_client.collections.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_collection_not_connected(self, config, mock_weaviate_env):
        """create_collection() should raise ConnectionError when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError, match="Not connected"):
            await store.create_collection("test")

    @pytest.mark.asyncio
    async def test_delete_collection_success(self, config, mock_weaviate_env):
        """delete_collection() should return True on success."""
        mock_client, _ = mock_weaviate_env
        mock_client.collections.exists.return_value = True
        store = _make_store(config, mock_client)

        result = await store.delete_collection("my_collection")

        assert result is True
        mock_client.collections.delete.assert_called_once_with("my_collection")

    @pytest.mark.asyncio
    async def test_delete_collection_not_exists(self, config, mock_weaviate_env):
        """delete_collection() should return False when not found."""
        mock_client, _ = mock_weaviate_env
        mock_client.collections.exists.return_value = False
        store = _make_store(config, mock_client)

        result = await store.delete_collection("missing")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_collection_clears_cache(self, config, mock_weaviate_env):
        """delete_collection() should remove from internal cache."""
        mock_client, _ = mock_weaviate_env
        mock_client.collections.exists.return_value = True
        store = _make_store(config, mock_client)
        store._collections["my_collection"] = MagicMock()

        await store.delete_collection("my_collection")

        assert "my_collection" not in store._collections

    @pytest.mark.asyncio
    async def test_collection_exists(self, config, mock_weaviate_env):
        """collection_exists() should delegate to weaviate client."""
        mock_client, _ = mock_weaviate_env
        mock_client.collections.exists.return_value = True
        store = _make_store(config, mock_client)

        assert await store.collection_exists("test_collection") is True
        mock_client.collections.exists.assert_called_with("test_collection")

    @pytest.mark.asyncio
    async def test_collection_exists_false(self, config, mock_weaviate_env):
        """collection_exists() should return False when absent."""
        mock_client, _ = mock_weaviate_env
        mock_client.collections.exists.return_value = False
        store = _make_store(config, mock_client)

        assert await store.collection_exists("nope") is False

    @pytest.mark.asyncio
    async def test_list_collections(self, config, mock_weaviate_env):
        """list_collections() should return collection names."""
        mock_client, _ = mock_weaviate_env
        c1 = MagicMock()
        c1.name = "col_a"
        c2 = MagicMock()
        c2.name = "col_b"
        mock_client.collections.list_all.return_value = [c1, c2]
        store = _make_store(config, mock_client)

        names = await store.list_collections()
        assert names == ["col_a", "col_b"]

    @pytest.mark.asyncio
    async def test_list_collections_not_connected(self, config, mock_weaviate_env):
        """list_collections() should raise when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError):
            await store.list_collections()


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------


class TestWeaviateUpsert:
    """Tests for insert/update operations."""

    @pytest.mark.asyncio
    async def test_upsert_insert_new(self, config, mock_weaviate_env):
        """upsert() should insert when object does not exist."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_collection.query.fetch_object_by_id.return_value = None
        store._collections["test_collection"] = mock_collection

        result = await store.upsert(
            id="vec-1",
            embedding=_embedding(),
            content="test content",
            metadata={"topic": "science"},
        )

        assert result == "vec-1"
        mock_collection.data.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_update_existing(self, config, mock_weaviate_env):
        """upsert() should update when object already exists."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_collection.query.fetch_object_by_id.return_value = MagicMock()  # exists
        store._collections["test_collection"] = mock_collection

        result = await store.upsert(
            id="vec-1",
            embedding=_embedding(),
            content="updated content",
        )

        assert result == "vec-1"
        mock_collection.data.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_fetch_fails_inserts(self, config, mock_weaviate_env):
        """upsert() should insert if fetch raises an error."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_collection.query.fetch_object_by_id.side_effect = KeyError("not found")
        store._collections["test_collection"] = mock_collection

        result = await store.upsert(
            id="vec-2",
            embedding=_embedding(),
            content="fallback insert",
        )

        assert result == "vec-2"
        mock_collection.data.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_with_namespace(self, config, mock_weaviate_env):
        """upsert() should include namespace in properties."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_collection.query.fetch_object_by_id.return_value = None
        store._collections["test_collection"] = mock_collection

        await store.upsert(
            id="vec-3",
            embedding=_embedding(),
            content="ns content",
            namespace="tenant-a",
        )

        call_kwargs = mock_collection.data.insert.call_args.kwargs
        assert call_kwargs["properties"]["namespace"] == "tenant-a"

    @pytest.mark.asyncio
    async def test_upsert_not_connected(self, config, mock_weaviate_env):
        """upsert() should raise ConnectionError when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError):
            await store.upsert(id="x", embedding=_embedding(), content="c")

    @pytest.mark.asyncio
    async def test_upsert_batch(self, config, mock_weaviate_env):
        """upsert_batch() should batch-insert multiple vectors."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_batch = MagicMock()
        mock_collection.batch.dynamic.return_value.__enter__ = MagicMock(return_value=mock_batch)
        mock_collection.batch.dynamic.return_value.__exit__ = MagicMock(return_value=False)
        store._collections["test_collection"] = mock_collection

        items = [
            {"id": "b1", "embedding": _embedding(), "content": "first"},
            {"id": "b2", "embedding": _embedding(), "content": "second", "metadata": {"k": "v"}},
        ]

        ids = await store.upsert_batch(items, namespace="ns1")

        assert ids == ["b1", "b2"]
        assert mock_batch.add_object.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "item",
        [
            {"embedding": [0.1], "content": "no id key"},
            {"id": None, "embedding": [0.1], "content": "explicit None id"},
        ],
        ids=["missing-key", "none-value"],
    )
    async def test_upsert_batch_generates_uuid_for_id_less_item(
        self, config, mock_weaviate_env, item
    ):
        """An item without an id gets a UUID4 that is both sent to Weaviate and returned."""
        mock_client, _ = mock_weaviate_env
        store, mock_batch = _make_batch_store(config, mock_client)

        ids = await store.upsert_batch([item])

        assert len(ids) == 1
        assert isinstance(ids[0], str)
        assert uuid.UUID(ids[0]).version == 4
        assert mock_batch.add_object.call_args.kwargs["uuid"] == ids[0]

    @pytest.mark.asyncio
    async def test_upsert_batch_mixed_ids_keep_explicit_ids(self, config, mock_weaviate_env):
        """Explicit ids pass through unchanged; each id-less item gets its own UUID."""
        mock_client, _ = mock_weaviate_env
        store, mock_batch = _make_batch_store(config, mock_client)

        items = [
            {"id": "keep-1", "embedding": [0.1], "content": "a"},
            {"embedding": [0.2], "content": "b"},
            {"id": "keep-3", "embedding": [0.3], "content": "c"},
            {"embedding": [0.4], "content": "d"},
        ]

        ids = await store.upsert_batch(items)

        sent = [call.kwargs["uuid"] for call in mock_batch.add_object.call_args_list]
        assert ids == sent
        assert ids[0] == "keep-1"
        assert ids[2] == "keep-3"
        assert uuid.UUID(ids[1]).version == 4
        assert uuid.UUID(ids[3]).version == 4
        assert ids[1] != ids[3]

    @pytest.mark.asyncio
    async def test_upsert_batch_not_connected(self, config, mock_weaviate_env):
        """upsert_batch() should raise when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError):
            await store.upsert_batch([{"id": "x", "embedding": [], "content": "c"}])


# ---------------------------------------------------------------------------
# Delete Operations
# ---------------------------------------------------------------------------


class TestWeaviateDelete:
    """Tests for delete operations."""

    @pytest.mark.asyncio
    async def test_delete_by_ids(self, config, mock_weaviate_env):
        """delete() should delete each id and return count."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        store._collections["test_collection"] = mock_collection

        count = await store.delete(ids=["id-1", "id-2", "id-3"])

        assert count == 3
        assert mock_collection.data.delete_by_id.call_count == 3

    @pytest.mark.asyncio
    async def test_delete_handles_individual_errors(self, config, mock_weaviate_env):
        """delete() should count only successful deletions."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_collection.data.delete_by_id.side_effect = [
            None,  # success
            KeyError("not found"),  # failure
            None,  # success
        ]
        store._collections["test_collection"] = mock_collection

        count = await store.delete(ids=["id-1", "id-2", "id-3"])

        assert count == 2

    @pytest.mark.asyncio
    async def test_delete_empty_ids(self, config, mock_weaviate_env):
        """delete() with empty list should return 0."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)
        mock_collection = MagicMock()
        store._collections["test_collection"] = mock_collection

        count = await store.delete(ids=[])

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_by_filter(self, config, mock_weaviate_env):
        """delete_by_filter() should delete matching vectors."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_agg_before = MagicMock()
        mock_agg_before.total_count = 10
        mock_agg_after = MagicMock()
        mock_agg_after.total_count = 7
        mock_collection.aggregate.over_all.side_effect = [mock_agg_before, mock_agg_after]
        store._collections["test_collection"] = mock_collection

        count = await store.delete_by_filter(
            filters={"topic": "obsolete"},
            namespace="tenant-a",
        )

        assert count == 3
        mock_collection.data.delete_many.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_not_connected(self, config, mock_weaviate_env):
        """delete() should raise when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError):
            await store.delete(ids=["x"])


# ---------------------------------------------------------------------------
# Search Operations
# ---------------------------------------------------------------------------


class TestWeaviateSearch:
    """Tests for vector similarity search."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, config, mock_weaviate_env):
        """search() should return VectorSearchResult list."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = [
            _mock_weaviate_object(
                "uuid-1",
                {"content": "first result", "namespace": "ns", "topic": "ai"},
                distance=0.1,
                vector=_embedding(dim=4),
            ),
            _mock_weaviate_object(
                "uuid-2",
                {"content": "second result", "namespace": "ns"},
                distance=0.3,
            ),
        ]
        mock_collection.query.near_vector.return_value = mock_response
        store._collections["test_collection"] = mock_collection

        results = await store.search(embedding=_embedding(), limit=10)

        assert len(results) == 2
        assert results[0].id == "uuid-1"
        assert results[0].score == pytest.approx(0.9)  # 1 - 0.1
        assert results[0].content == "first result"
        assert results[0].metadata == {"topic": "ai"}
        assert results[0].embedding == _embedding(dim=4)
        assert results[1].score == pytest.approx(0.7)  # 1 - 0.3

    @pytest.mark.asyncio
    async def test_search_with_min_score(self, config, mock_weaviate_env):
        """search() should filter results below min_score."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = [
            _mock_weaviate_object("uuid-1", {"content": "close", "namespace": ""}, distance=0.05),
            _mock_weaviate_object("uuid-2", {"content": "far", "namespace": ""}, distance=0.9),
        ]
        mock_collection.query.near_vector.return_value = mock_response
        store._collections["test_collection"] = mock_collection

        results = await store.search(embedding=_embedding(), min_score=0.5)

        assert len(results) == 1
        assert results[0].id == "uuid-1"

    @pytest.mark.asyncio
    async def test_search_with_filters_and_namespace(self, config, mock_weaviate_env):
        """search() should pass filters to Weaviate."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.near_vector.return_value = mock_response
        store._collections["test_collection"] = mock_collection

        await store.search(
            embedding=_embedding(),
            filters={"topic": "science"},
            namespace="tenant-b",
        )

        call_kwargs = mock_collection.query.near_vector.call_args.kwargs
        assert call_kwargs["filters"] is not None

    @pytest.mark.asyncio
    async def test_search_empty_results(self, config, mock_weaviate_env):
        """search() should return empty list when no matches."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.near_vector.return_value = mock_response
        store._collections["test_collection"] = mock_collection

        results = await store.search(embedding=_embedding())

        assert results == []

    @pytest.mark.asyncio
    async def test_search_null_distance(self, config, mock_weaviate_env):
        """search() should handle None distance gracefully."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        obj = _mock_weaviate_object("uuid-1", {"content": "text", "namespace": ""}, distance=None)
        mock_response = MagicMock()
        mock_response.objects = [obj]
        mock_collection.query.near_vector.return_value = mock_response
        store._collections["test_collection"] = mock_collection

        results = await store.search(embedding=_embedding())

        assert results[0].score == 1.0  # 1 - 0

    @pytest.mark.asyncio
    async def test_search_not_connected(self, config, mock_weaviate_env):
        """search() should raise ConnectionError when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError):
            await store.search(embedding=_embedding())


# ---------------------------------------------------------------------------
# Hybrid Search
# ---------------------------------------------------------------------------


class TestWeaviateHybridSearch:
    """Tests for hybrid vector + BM25 search."""

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_results(self, config, mock_weaviate_env):
        """hybrid_search() should return combined results."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = [
            _mock_weaviate_object(
                "uuid-1",
                {"content": "machine learning", "namespace": ""},
                score=0.92,
            ),
            _mock_weaviate_object(
                "uuid-2",
                {"content": "deep learning", "namespace": ""},
                score=0.85,
            ),
        ]
        mock_collection.query.hybrid.return_value = mock_response
        store._collections["test_collection"] = mock_collection

        results = await store.hybrid_search(
            query="machine learning",
            embedding=_embedding(),
            limit=10,
            alpha=0.5,
        )

        assert len(results) == 2
        assert results[0].id == "uuid-1"
        assert results[0].score == 0.92

    @pytest.mark.asyncio
    async def test_hybrid_search_passes_alpha(self, config, mock_weaviate_env):
        """hybrid_search() should pass alpha to Weaviate."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.hybrid.return_value = mock_response
        store._collections["test_collection"] = mock_collection

        await store.hybrid_search(query="test", embedding=_embedding(), alpha=0.7)

        call_kwargs = mock_collection.query.hybrid.call_args.kwargs
        assert call_kwargs["alpha"] == 0.7

    @pytest.mark.asyncio
    async def test_hybrid_search_with_filters(self, config, mock_weaviate_env):
        """hybrid_search() should apply filters."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.hybrid.return_value = mock_response
        store._collections["test_collection"] = mock_collection

        await store.hybrid_search(
            query="test",
            embedding=_embedding(),
            filters={"topic": "ai"},
            namespace="ns",
        )

        call_kwargs = mock_collection.query.hybrid.call_args.kwargs
        assert call_kwargs["filters"] is not None

    @pytest.mark.asyncio
    async def test_hybrid_search_null_score(self, config, mock_weaviate_env):
        """hybrid_search() should handle None score."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        obj = _mock_weaviate_object("uuid-1", {"content": "text", "namespace": ""}, score=None)
        mock_response = MagicMock()
        mock_response.objects = [obj]
        mock_collection.query.hybrid.return_value = mock_response
        store._collections["test_collection"] = mock_collection

        results = await store.hybrid_search(query="q", embedding=_embedding())
        assert results[0].score == 0

    @pytest.mark.asyncio
    async def test_hybrid_search_not_connected(self, config, mock_weaviate_env):
        """hybrid_search() should raise when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError):
            await store.hybrid_search(query="q", embedding=_embedding())


# ---------------------------------------------------------------------------
# Retrieval Operations
# ---------------------------------------------------------------------------


class TestWeaviateRetrieval:
    """Tests for get_by_id and get_by_ids."""

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, config, mock_weaviate_env):
        """get_by_id() should return result for existing ID."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_obj = _mock_weaviate_object(
            "uuid-1",
            {"content": "hello", "namespace": "ns", "topic": "greet"},
            vector=_embedding(dim=4),
        )
        mock_collection.query.fetch_object_by_id.return_value = mock_obj
        store._collections["test_collection"] = mock_collection

        result = await store.get_by_id("uuid-1")

        assert result is not None
        assert result.id == "uuid-1"
        assert result.content == "hello"
        assert result.score == 1.0
        assert result.metadata == {"topic": "greet"}
        assert result.embedding == _embedding(dim=4)

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, config, mock_weaviate_env):
        """get_by_id() should return None when not found."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_collection.query.fetch_object_by_id.return_value = None
        store._collections["test_collection"] = mock_collection

        result = await store.get_by_id("missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_id_handles_error(self, config, mock_weaviate_env):
        """get_by_id() should return None on error."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_collection.query.fetch_object_by_id.side_effect = RuntimeError("error")
        store._collections["test_collection"] = mock_collection

        result = await store.get_by_id("error-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_id_no_vector(self, config, mock_weaviate_env):
        """get_by_id() should handle object with no vector."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        obj = _mock_weaviate_object("uuid-1", {"content": "text", "namespace": ""})
        mock_collection.query.fetch_object_by_id.return_value = obj
        store._collections["test_collection"] = mock_collection

        result = await store.get_by_id("uuid-1")

        assert result is not None
        assert result.embedding is None

    @pytest.mark.asyncio
    async def test_get_by_ids(self, config, mock_weaviate_env):
        """get_by_ids() should return results for multiple IDs."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        obj1 = _mock_weaviate_object("u1", {"content": "first", "namespace": ""})
        obj2 = _mock_weaviate_object("u2", {"content": "second", "namespace": ""})
        mock_collection.query.fetch_object_by_id.side_effect = [obj1, obj2]
        store._collections["test_collection"] = mock_collection

        results = await store.get_by_ids(["u1", "u2"])

        assert len(results) == 2
        assert results[0].id == "u1"
        assert results[1].id == "u2"

    @pytest.mark.asyncio
    async def test_get_by_ids_skips_missing(self, config, mock_weaviate_env):
        """get_by_ids() should skip IDs that return None."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        obj1 = _mock_weaviate_object("u1", {"content": "first", "namespace": ""})
        mock_collection.query.fetch_object_by_id.side_effect = [obj1, None]
        store._collections["test_collection"] = mock_collection

        results = await store.get_by_ids(["u1", "u2"])

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_by_ids_not_connected(self, config, mock_weaviate_env):
        """get_by_ids() should raise when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError):
            await store.get_by_ids(["x"])


# ---------------------------------------------------------------------------
# Count
# ---------------------------------------------------------------------------


class TestWeaviateCount:
    """Tests for count operations."""

    @pytest.mark.asyncio
    async def test_count_all(self, config, mock_weaviate_env):
        """count() without filters should count all."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.total_count = 42
        mock_collection.aggregate.over_all.return_value = mock_result
        store._collections["test_collection"] = mock_collection

        count = await store.count()

        assert count == 42

    @pytest.mark.asyncio
    async def test_count_with_filters(self, config, mock_weaviate_env):
        """count() with filters should pass filter to aggregation."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.total_count = 7
        mock_collection.aggregate.over_all.return_value = mock_result
        store._collections["test_collection"] = mock_collection

        count = await store.count(filters={"topic": "ai"}, namespace="ns1")

        assert count == 7
        call_kwargs = mock_collection.aggregate.over_all.call_args.kwargs
        assert call_kwargs["filters"] is not None

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_none(self, config, mock_weaviate_env):
        """count() should return 0 if total_count is None."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_collection = MagicMock()
        mock_result = MagicMock()
        mock_result.total_count = None
        mock_collection.aggregate.over_all.return_value = mock_result
        store._collections["test_collection"] = mock_collection

        count = await store.count()

        assert count == 0

    @pytest.mark.asyncio
    async def test_count_not_connected(self, config, mock_weaviate_env):
        """count() should raise when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError):
            await store.count()


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------


class TestWeaviateHealth:
    """Tests for health and diagnostics."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, config, mock_weaviate_env):
        """health_check() should return healthy status."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_client.get_meta.return_value = {
            "version": "1.24.0",
            "modules": {"text2vec-openai": {}, "generative-openai": {}},
        }

        health = await store.health_check()

        assert health["status"] == "healthy"
        assert health["backend"] == "weaviate"
        assert health["version"] == "1.24.0"
        assert len(health["modules"]) == 2

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, config, mock_weaviate_env):
        """health_check() should return unhealthy on error."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)
        mock_client.get_meta.side_effect = ConnectionError("unreachable")

        health = await store.health_check()

        assert health["status"] == "unhealthy"
        assert health["backend"] == "weaviate"
        assert health["error"] == "Health check failed"

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, config, mock_weaviate_env):
        """health_check() should return disconnected when no client."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)

        health = await store.health_check()

        assert health["status"] == "disconnected"
        assert health["backend"] == "weaviate"

    @pytest.mark.asyncio
    async def test_ping_healthy(self, config, mock_weaviate_env):
        """ping() should return True when healthy."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)
        mock_client.get_meta.return_value = {"version": "1.24.0", "modules": {}}

        assert await store.ping() is True

    @pytest.mark.asyncio
    async def test_ping_unhealthy(self, config, mock_weaviate_env):
        """ping() should return False when unhealthy."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)
        mock_client.get_meta.side_effect = ConnectionError("down")

        assert await store.ping() is False


# ---------------------------------------------------------------------------
# Helper Methods
# ---------------------------------------------------------------------------


class TestWeaviateHelpers:
    """Tests for internal helper methods."""

    def test_get_collection_caches(self, config, mock_weaviate_env):
        """_get_collection() should cache collection references."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        mock_col = MagicMock()
        mock_client.collections.get.return_value = mock_col

        col1 = store._get_collection()
        col2 = store._get_collection()

        # Should only call get() once
        mock_client.collections.get.assert_called_once()
        assert col1 is col2

    def test_get_collection_not_connected(self, config, mock_weaviate_env):
        """_get_collection() should raise when not connected."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        with pytest.raises(ConnectionError):
            store._get_collection()

    def test_build_filter_none(self, config, mock_weaviate_env):
        """_build_filter() with no args should return None."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)
        assert store._build_filter(None, None) is None

    def test_build_filter_single_namespace(self, config, mock_weaviate_env):
        """_build_filter() with only namespace should return a filter."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        with patch("aragora.knowledge.mound.vector_abstraction.weaviate.Filter") as mock_filter:
            mock_prop = MagicMock()
            mock_filter.by_property.return_value = mock_prop
            mock_prop.equal.return_value = "ns_filter"

            result = store._build_filter(None, "tenant-a")
            assert result == "ns_filter"

    def test_build_filter_multiple_conditions(self, config, mock_weaviate_env):
        """_build_filter() should AND multiple conditions."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        with patch("aragora.knowledge.mound.vector_abstraction.weaviate.Filter") as mock_filter:
            mock_prop = MagicMock()
            mock_filter.by_property.return_value = mock_prop
            cond = MagicMock()
            mock_prop.equal.return_value = cond
            cond.__and__ = MagicMock(return_value=cond)

            result = store._build_filter({"topic": "ai", "lang": "en"}, "ns1")
            # Should have combined 3 conditions: namespace + topic + lang
            assert result is not None

    def test_map_data_type_string(self, config, mock_weaviate_env):
        """_map_data_type() should map string types correctly."""
        mock_client, _ = mock_weaviate_env
        store = _make_store(config, mock_client)

        with patch("aragora.knowledge.mound.vector_abstraction.weaviate.DataType") as mock_dt:
            mock_dt.TEXT = "TEXT"
            mock_dt.INT = "INT"
            mock_dt.NUMBER = "NUMBER"
            mock_dt.BOOL = "BOOL"
            mock_dt.DATE = "DATE"

            assert store._map_data_type("string") == "TEXT"
            assert store._map_data_type("text") == "TEXT"
            assert store._map_data_type("int") == "INT"
            assert store._map_data_type("integer") == "INT"
            assert store._map_data_type("float") == "NUMBER"
            assert store._map_data_type("number") == "NUMBER"
            assert store._map_data_type("bool") == "BOOL"
            assert store._map_data_type("boolean") == "BOOL"
            assert store._map_data_type("date") == "DATE"
            # Unknown type defaults to TEXT
            assert store._map_data_type("unknown") == "TEXT"


# ---------------------------------------------------------------------------
# Backend Registration
# ---------------------------------------------------------------------------


class TestWeaviateBackendRegistration:
    """Tests for backend enum and config."""

    def test_backend_enum_exists(self):
        """Should have WEAVIATE in VectorBackend enum."""
        assert hasattr(VectorBackend, "WEAVIATE")
        assert VectorBackend.WEAVIATE.value == "weaviate"

    def test_store_sets_backend(self, config, mock_weaviate_env):
        """WeaviateVectorStore should set config backend to WEAVIATE."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        assert store.backend == VectorBackend.WEAVIATE

    def test_import_check(self):
        """Module should expose WEAVIATE_AVAILABLE flag."""
        from aragora.knowledge.mound.vector_abstraction import weaviate as weaviate_mod

        assert hasattr(weaviate_mod, "WEAVIATE_AVAILABLE")

    def test_collection_name_property(self, config, mock_weaviate_env):
        """collection_name property should return config value."""
        from aragora.knowledge.mound.vector_abstraction.weaviate import WeaviateVectorStore

        store = WeaviateVectorStore(config)
        assert store.collection_name == "test_collection"
