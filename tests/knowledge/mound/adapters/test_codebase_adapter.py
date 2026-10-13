"""Tests for CodebaseAdapter - bridges codebase structure to Knowledge Mound."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.knowledge.mound.adapters.codebase_adapter import (
    CodebaseAdapter,
    CodebaseAdapterError,
    CodebaseSyncResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mound():
    mound = AsyncMock()
    mound.store = AsyncMock(return_value=MagicMock(id="stored_123"))
    mound.query = AsyncMock(return_value=MagicMock(items=[]))
    return mound


@pytest.fixture
def adapter(mock_mound):
    return CodebaseAdapter(mound=mock_mound)


@pytest.fixture
def adapter_no_mound():
    return CodebaseAdapter(mound=None)


def _make_symbol(name="MyClass", kind="class", line=10, docstring="A test class"):
    sym = MagicMock()
    sym.name = name
    sym.kind = kind
    sym.line = line
    sym.docstring = docstring
    return sym


def _make_crawled_file(relative_path="aragora/debate/arena.py", symbols=None, line_count=100):
    f = MagicMock()
    f.relative_path = relative_path
    f.path = relative_path
    f.symbols = symbols or []
    f.line_count = line_count
    return f


def _make_crawl_result(
    files=None,
    dependency_graph=None,
    file_type_counts=None,
    repository_name="aragora",
):
    cr = MagicMock()
    cr.repository_name = repository_name
    cr.files = files or []
    cr.dependency_graph = dependency_graph or {}
    cr.file_type_counts = file_type_counts or {}
    cr.total_files = len(files or [])
    cr.total_lines = sum(getattr(f, "line_count", 0) for f in (files or []))
    cr.symbol_counts = {}
    return cr


# ---------------------------------------------------------------------------
# Sync to KM
# ---------------------------------------------------------------------------


class TestSyncToKM:
    @pytest.mark.asyncio
    async def test_sync_empty_crawl_result(self, adapter):
        result = await adapter.sync_to_km(_make_crawl_result())
        assert result == 0

    @pytest.mark.asyncio
    async def test_sync_with_symbols(self, adapter, mock_mound):
        sym = _make_symbol("Arena", "class", 50, "Main debate arena")
        files = [_make_crawled_file(symbols=[sym])]
        crawl = _make_crawl_result(files=files)

        count = await adapter.sync_to_km(crawl)
        assert count >= 1
        mock_mound.store.assert_called()

    @pytest.mark.asyncio
    async def test_sync_with_dependencies(self, adapter, mock_mound):
        dep_graph = {"aragora/debate/arena.py": ["aragora/debate/protocol.py", "aragora/core.py"]}
        crawl = _make_crawl_result(dependency_graph=dep_graph)

        count = await adapter.sync_to_km(crawl)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_sync_with_file_types(self, adapter, mock_mound):
        crawl = _make_crawl_result(file_type_counts={".py": 500, ".ts": 100, ".md": 50})

        count = await adapter.sync_to_km(crawl)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_sync_all_types(self, adapter, mock_mound):
        sym = _make_symbol()
        files = [_make_crawled_file(symbols=[sym])]
        dep_graph = {"a.py": ["b.py"]}
        file_types = {".py": 10}
        crawl = _make_crawl_result(
            files=files, dependency_graph=dep_graph, file_type_counts=file_types
        )

        count = await adapter.sync_to_km(crawl)
        # At least 3: 1 symbol + 1 dep + 1 file type pattern
        assert count >= 3

    @pytest.mark.asyncio
    async def test_sync_without_mound_returns_zero(self, adapter_no_mound):
        crawl = _make_crawl_result(files=[_make_crawled_file(symbols=[_make_symbol()])])
        count = await adapter_no_mound.sync_to_km(crawl)
        assert count == 0

    @pytest.mark.asyncio
    async def test_sync_stores_result(self, adapter):
        sym = _make_symbol()
        files = [_make_crawled_file(symbols=[sym])]
        crawl = _make_crawl_result(files=files, repository_name="test-repo")

        await adapter.sync_to_km(crawl)
        result = adapter.get_sync_result("test-repo")
        assert result is not None
        assert result.definitions_ingested >= 1

    @pytest.mark.asyncio
    async def test_sync_with_workspace_id(self, adapter, mock_mound):
        sym = _make_symbol()
        files = [_make_crawled_file(symbols=[sym])]
        crawl = _make_crawl_result(files=files)

        await adapter.sync_to_km(crawl, workspace_id="ws-123")
        call_args = mock_mound.store.call_args
        item = call_args[0][0]
        assert item.metadata["workspace_id"] == "ws-123"

    @pytest.mark.asyncio
    async def test_sync_with_custom_tags(self, adapter, mock_mound):
        sym = _make_symbol()
        files = [_make_crawled_file(symbols=[sym])]
        crawl = _make_crawl_result(files=files)

        await adapter.sync_to_km(crawl, tags=["custom_tag"])
        call_args = mock_mound.store.call_args
        item = call_args[0][0]
        assert "custom_tag" in item.metadata["tags"]

    @pytest.mark.asyncio
    async def test_sync_handles_store_error(self, adapter, mock_mound):
        mock_mound.store.side_effect = RuntimeError("store failed")
        sym = _make_symbol()
        files = [_make_crawled_file(symbols=[sym])]
        crawl = _make_crawl_result(files=files)

        count = await adapter.sync_to_km(crawl)
        assert count == 0
        result = adapter.get_sync_result("aragora")
        # _store_item catches errors internally, so errors list is empty
        # but success is False since total_ingested == 0
        assert result.success is False

    @pytest.mark.asyncio
    async def test_sync_emits_event(self, adapter):
        callback = MagicMock()
        adapter._event_callback = callback
        sym = _make_symbol()
        files = [_make_crawled_file(symbols=[sym])]
        crawl = _make_crawl_result(files=files)

        await adapter.sync_to_km(crawl)
        callback.assert_called()
        event_type = callback.call_args[0][0]
        assert event_type == "codebase_synced"


# ---------------------------------------------------------------------------
# Sync from KM
# ---------------------------------------------------------------------------


class TestSyncFromKM:
    @pytest.mark.asyncio
    async def test_query_code_items(self, adapter, mock_mound):
        items = await adapter.sync_from_km("database connection")
        assert isinstance(items, list)
        mock_mound.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_without_mound(self, adapter_no_mound):
        items = await adapter_no_mound.sync_from_km("anything")
        assert items == []

    @pytest.mark.asyncio
    async def test_query_with_workspace(self, adapter, mock_mound):
        await adapter.sync_from_km("query", workspace_id="ws-1", limit=5)
        call_args = mock_mound.query.call_args
        assert call_args.kwargs["workspace_id"] == "ws-1"
        assert call_args.kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_query_handles_error(self, adapter, mock_mound):
        mock_mound.query.side_effect = RuntimeError("query failed")
        items = await adapter.sync_from_km("query")
        assert items == []


# ---------------------------------------------------------------------------
# Crawl and sync
# ---------------------------------------------------------------------------


class TestCrawlAndSync:
    @pytest.mark.asyncio
    async def test_crawl_and_sync_import_guard(self, adapter, mock_mound):
        """Verify crawl_and_sync returns 0 when RepositoryCrawler is unavailable."""
        with patch.dict("sys.modules", {"aragora.analysis.codebase.repository_crawler": None}):
            count = await adapter.crawl_and_sync("/some/path")
            assert count == 0

    @pytest.mark.asyncio
    async def test_crawl_and_sync_import_error(self, adapter):
        with patch.dict("sys.modules", {"aragora.analysis.codebase.repository_crawler": None}):
            count = await adapter.crawl_and_sync("/some/path")
            assert count == 0


# ---------------------------------------------------------------------------
# Stats and helpers
# ---------------------------------------------------------------------------


class TestStats:
    def test_get_stats_empty(self, adapter):
        stats = adapter.get_stats()
        assert stats["repos_synced"] == 0
        assert stats["mound_connected"] is True

    def test_get_stats_no_mound(self, adapter_no_mound):
        stats = adapter_no_mound.get_stats()
        assert stats["mound_connected"] is False

    @pytest.mark.asyncio
    async def test_stats_after_sync(self, adapter):
        sym = _make_symbol()
        files = [_make_crawled_file(symbols=[sym])]
        crawl = _make_crawl_result(files=files, file_type_counts={".py": 10})

        await adapter.sync_to_km(crawl)
        stats = adapter.get_stats()
        assert stats["repos_synced"] == 1
        assert stats["total_definitions"] >= 1

    def test_set_mound(self, adapter_no_mound):
        new_mound = MagicMock()
        adapter_no_mound.set_mound(new_mound)
        assert adapter_no_mound._mound is new_mound


# ---------------------------------------------------------------------------
# CodebaseSyncResult
# ---------------------------------------------------------------------------


class TestCodebaseSyncResult:
    def test_success_property(self):
        result = CodebaseSyncResult(
            definitions_ingested=5,
            patterns_ingested=1,
            imports_ingested=3,
            knowledge_item_ids=["a", "b"],
            errors=[],
        )
        assert result.success is True
        assert result.total_ingested == 9

    def test_failure_property(self):
        result = CodebaseSyncResult(
            definitions_ingested=0,
            patterns_ingested=0,
            imports_ingested=0,
            knowledge_item_ids=[],
            errors=["something failed"],
        )
        assert result.success is False

    def test_to_dict(self):
        result = CodebaseSyncResult(
            definitions_ingested=2,
            patterns_ingested=1,
            imports_ingested=0,
            knowledge_item_ids=["x"],
            errors=[],
        )
        d = result.to_dict()
        assert d["total_ingested"] == 3
        assert d["success"] is True


# ---------------------------------------------------------------------------
# Factory registration
# ---------------------------------------------------------------------------


class TestFactoryRegistration:
    def test_codebase_adapter_registered(self):
        from aragora.knowledge.mound.adapters.factory import ADAPTER_SPECS

        assert "codebase" in ADAPTER_SPECS
        spec = ADAPTER_SPECS["codebase"]
        assert spec.priority == 63
        assert spec.enabled_by_default is False
        assert spec.forward_method == "sync_to_km"
        assert spec.reverse_method == "sync_from_km"
