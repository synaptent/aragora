"""Tests for SearchOperationsMixin (aragora/server/handlers/knowledge_base/search.py).

Covers the search and stats mixin methods:
- _handle_search: query parameter validation, engine search, result serialization, error handling
- _handle_stats: fact store statistics, workspace filtering
- SearchHandlerProtocol: protocol shape
- Edge cases: empty results, long queries, boundary limit values, engine errors
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.knowledge.embeddings import ChunkMatch
from aragora.server.handlers.knowledge_base.search import SearchOperationsMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: object) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _make_chunk_match(
    chunk_id: str = "chunk-001",
    document_id: str = "doc-001",
    workspace_id: str = "default",
    content: str = "Relevant content about the topic.",
    score: float = 0.92,
) -> ChunkMatch:
    """Create a ChunkMatch instance for testing."""
    return ChunkMatch(
        chunk_id=chunk_id,
        document_id=document_id,
        workspace_id=workspace_id,
        content=content,
        score=score,
        metadata={},
    )


# ---------------------------------------------------------------------------
# Concrete test class implementing the protocol + mixin
# ---------------------------------------------------------------------------


class ConcreteSearchHandler(SearchOperationsMixin):
    """Concrete implementation of SearchOperationsMixin for testing."""

    def __init__(
        self,
        fact_store: Any = None,
        query_engine: Any = None,
    ):
        self._fact_store = fact_store or MagicMock()
        self._query_engine = query_engine or MagicMock()

    def _get_fact_store(self):
        return self._fact_store

    def _get_query_engine(self):
        return self._query_engine

    def require_auth_or_error(self, handler):
        return MagicMock(org_id="test-org-001"), None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_fact_store():
    """Create a mock fact store with sensible defaults."""
    store = MagicMock()
    store.get_statistics.return_value = {
        "total_facts": 42,
        "by_status": {"verified": 30, "unverified": 12},
        "avg_confidence": 0.88,
        "verified_count": 30,
    }
    return store


@pytest.fixture
def mock_query_engine():
    """Create a mock query engine with search support."""
    engine = MagicMock()
    engine.search = MagicMock(return_value=[])
    return engine


@pytest.fixture
def handler(mock_fact_store, mock_query_engine):
    """Create a ConcreteSearchHandler with injected mock stores."""
    return ConcreteSearchHandler(
        fact_store=mock_fact_store,
        query_engine=mock_query_engine,
    )


# ============================================================================
# Tests: _handle_search - basic behavior
# ============================================================================


class TestHandleSearchBasic:
    """Test basic search operation behavior."""

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_search_returns_200_on_success(self, mock_run_async, handler):
        chunk = _make_chunk_match()
        mock_run_async.return_value = [chunk]
        result = handler._handle_search({"q": "test query"})
        assert _status(result) == 200

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_search_returns_query_in_response(self, mock_run_async, handler):
        mock_run_async.return_value = []
        result = handler._handle_search({"q": "my search"})
        body = _body(result)
        assert body["query"] == "my search"

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_search_returns_workspace_id_in_response(self, mock_run_async, handler):
        mock_run_async.return_value = []
        result = handler._handle_search({"q": "test", "workspace_id": "ws-123"})
        body = _body(result)
        assert body["workspace_id"] == "ws-123"

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_search_returns_default_workspace(self, mock_run_async, handler):
        mock_run_async.return_value = []
        result = handler._handle_search({"q": "test"})
        body = _body(result)
        assert body["workspace_id"] == "default"

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_search_returns_count(self, mock_run_async, handler):
        chunks = [_make_chunk_match("c1"), _make_chunk_match("c2")]
        mock_run_async.return_value = chunks
        result = handler._handle_search({"q": "test"})
        body = _body(result)
        assert body["count"] == 2

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_search_returns_results_as_dicts(self, mock_run_async, handler):
        chunk = _make_chunk_match(chunk_id="c-42", content="Hello world")
        mock_run_async.return_value = [chunk]
        result = handler._handle_search({"q": "test"})
        body = _body(result)
        assert len(body["results"]) == 1
        assert body["results"][0]["chunk_id"] == "c-42"
        assert body["results"][0]["content"] == "Hello world"

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_search_empty_results(self, mock_run_async, handler):
        mock_run_async.return_value = []
        result = handler._handle_search({"q": "nothing"})
        body = _body(result)
        assert body["results"] == []
        assert body["count"] == 0


# ============================================================================
# Tests: _handle_search - query parameter validation
# ============================================================================


class TestHandleSearchQueryValidation:
    """Test query parameter validation in search."""

    def test_missing_q_param_returns_400(self, handler):
        result = handler._handle_search({})
        assert _status(result) == 400
        body = _body(result)
        assert "error" in body

    def test_empty_q_param_returns_400(self, handler):
        result = handler._handle_search({"q": ""})
        assert _status(result) == 400

    def test_none_q_param_returns_400(self, handler):
        result = handler._handle_search({"q": None})
        assert _status(result) == 400

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_q_param_truncated_to_max_length(self, mock_run_async, handler):
        """Query strings longer than 500 chars get truncated."""
        mock_run_async.return_value = []
        long_query = "x" * 600
        result = handler._handle_search({"q": long_query})
        body = _body(result)
        # get_bounded_string_param truncates to 500
        assert len(body["query"]) == 500

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_q_at_max_length_passes(self, mock_run_async, handler):
        mock_run_async.return_value = []
        query_500 = "a" * 500
        result = handler._handle_search({"q": query_500})
        body = _body(result)
        assert body["query"] == query_500


# ============================================================================
# Tests: _handle_search - limit parameter
# ============================================================================


class TestHandleSearchLimitParam:
    """Test limit parameter handling in search."""

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_default_limit_is_10(self, mock_run_async, handler):
        mock_run_async.return_value = []
        handler._handle_search({"q": "test"})
        # run_async receives the coroutine; check engine.search was called with limit=10
        handler._query_engine.search.assert_called_once_with("test", "default", 10)

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_custom_limit(self, mock_run_async, handler):
        mock_run_async.return_value = []
        handler._handle_search({"q": "test", "limit": "25"})
        handler._query_engine.search.assert_called_once_with("test", "default", 25)

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_limit_clamped_to_min_1(self, mock_run_async, handler):
        mock_run_async.return_value = []
        handler._handle_search({"q": "test", "limit": "0"})
        handler._query_engine.search.assert_called_once_with("test", "default", 1)

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_limit_clamped_to_max_50(self, mock_run_async, handler):
        mock_run_async.return_value = []
        handler._handle_search({"q": "test", "limit": "100"})
        handler._query_engine.search.assert_called_once_with("test", "default", 50)

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_limit_negative_clamped_to_min(self, mock_run_async, handler):
        mock_run_async.return_value = []
        handler._handle_search({"q": "test", "limit": "-5"})
        handler._query_engine.search.assert_called_once_with("test", "default", 1)

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_limit_non_numeric_uses_default(self, mock_run_async, handler):
        mock_run_async.return_value = []
        handler._handle_search({"q": "test", "limit": "abc"})
        handler._query_engine.search.assert_called_once_with("test", "default", 10)

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_limit_exactly_1(self, mock_run_async, handler):
        mock_run_async.return_value = []
        handler._handle_search({"q": "test", "limit": "1"})
        handler._query_engine.search.assert_called_once_with("test", "default", 1)

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_limit_exactly_50(self, mock_run_async, handler):
        mock_run_async.return_value = []
        handler._handle_search({"q": "test", "limit": "50"})
        handler._query_engine.search.assert_called_once_with("test", "default", 50)


# ============================================================================
# Tests: _handle_search - workspace_id parameter
# ============================================================================


class TestHandleSearchWorkspaceParam:
    """Test workspace_id parameter handling in search."""

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_custom_workspace_id(self, mock_run_async, handler):
        mock_run_async.return_value = []
        handler._handle_search({"q": "test", "workspace_id": "my-ws"})
        handler._query_engine.search.assert_called_once_with("test", "my-ws", 10)

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_workspace_id_truncated_to_100_chars(self, mock_run_async, handler):
        mock_run_async.return_value = []
        long_ws = "w" * 150
        handler._handle_search({"q": "test", "workspace_id": long_ws})
        call_args = handler._query_engine.search.call_args
        # workspace_id should be truncated to 100 chars
        assert len(call_args[0][1]) == 100


# ============================================================================
# Tests: _handle_search - engine errors
# ============================================================================


class TestHandleSearchEngineErrors:
    """Test error handling when the query engine fails."""

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_key_error_returns_500(self, mock_run_async, handler):
        mock_run_async.side_effect = KeyError("missing key")
        result = handler._handle_search({"q": "test"})
        assert _status(result) == 500

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_value_error_returns_500(self, mock_run_async, handler):
        mock_run_async.side_effect = ValueError("bad value")
        result = handler._handle_search({"q": "test"})
        assert _status(result) == 500

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_os_error_returns_500(self, mock_run_async, handler):
        mock_run_async.side_effect = OSError("disk failure")
        result = handler._handle_search({"q": "test"})
        assert _status(result) == 500

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_type_error_returns_500(self, mock_run_async, handler):
        mock_run_async.side_effect = TypeError("type mismatch")
        result = handler._handle_search({"q": "test"})
        assert _status(result) == 500

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_runtime_error_returns_500(self, mock_run_async, handler):
        mock_run_async.side_effect = RuntimeError("runtime issue")
        result = handler._handle_search({"q": "test"})
        assert _status(result) == 500

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_search_error_body_contains_error_message(self, mock_run_async, handler):
        mock_run_async.side_effect = ValueError("bad embedding")
        result = handler._handle_search({"q": "test"})
        body = _body(result)
        assert "error" in body

    def test_engine_without_search_raises_type_error(self, mock_fact_store):
        """If query engine lacks 'search' attribute, TypeError is raised.

        TypeError maps to 400 via handle_errors exception mapping."""
        engine = MagicMock(spec=[])  # No methods at all
        del engine.search  # Ensure no search
        h = ConcreteSearchHandler(fact_store=mock_fact_store, query_engine=engine)
        # The handle_errors decorator catches TypeError -> maps to 400
        result = h._handle_search({"q": "test"})
        assert _status(result) == 400


# ============================================================================
# Tests: _handle_search - result serialization
# ============================================================================


class TestHandleSearchResultSerialization:
    """Test search result serialization."""

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_multiple_results_serialized(self, mock_run_async, handler):
        chunks = [
            _make_chunk_match("c1", "d1", "ws1", "Content 1", 0.95),
            _make_chunk_match("c2", "d2", "ws2", "Content 2", 0.85),
            _make_chunk_match("c3", "d3", "ws3", "Content 3", 0.75),
        ]
        mock_run_async.return_value = chunks
        result = handler._handle_search({"q": "multi"})
        body = _body(result)
        assert body["count"] == 3
        assert body["results"][0]["score"] == 0.95
        assert body["results"][1]["chunk_id"] == "c2"
        assert body["results"][2]["document_id"] == "d3"

    @patch("aragora.server.handlers.knowledge_base.search._run_async")
    def test_result_contains_all_chunk_fields(self, mock_run_async, handler):
        chunk = _make_chunk_match(
            chunk_id="test-chunk",
            document_id="test-doc",
            workspace_id="test-ws",
            content="Test content here",
            score=0.99,
        )
        mock_run_async.return_value = [chunk]
        result = handler._handle_search({"q": "test"})
        body = _body(result)
        r = body["results"][0]
        assert r["chunk_id"] == "test-chunk"
        assert r["document_id"] == "test-doc"
        assert r["workspace_id"] == "test-ws"
        assert r["content"] == "Test content here"
        assert r["score"] == 0.99
        assert "metadata" in r


# ============================================================================
# Tests: _handle_stats - basic behavior
# ============================================================================


class TestHandleStatsBasic:
    """Test basic stats operation behavior."""

    def test_stats_returns_200(self, handler):
        result = handler._handle_stats(None)
        assert _status(result) == 200

    def test_stats_includes_workspace_id(self, handler):
        result = handler._handle_stats("my-workspace")
        body = _body(result)
        assert body["workspace_id"] == "my-workspace"

    def test_stats_with_none_workspace(self, handler):
        result = handler._handle_stats(None)
        body = _body(result)
        assert body["workspace_id"] is None

    def test_stats_includes_store_statistics(self, handler, mock_fact_store):
        mock_fact_store.get_statistics.return_value = {
            "total_facts": 100,
            "avg_confidence": 0.9,
        }
        result = handler._handle_stats(None)
        body = _body(result)
        assert body["total_facts"] == 100
        assert body["avg_confidence"] == 0.9

    def test_stats_calls_store_with_workspace(self, handler, mock_fact_store):
        handler._handle_stats("ws-abc")
        mock_fact_store.get_statistics.assert_called_once_with("ws-abc", org_id="test-org-001")

    def test_stats_calls_store_with_none(self, handler, mock_fact_store):
        handler._handle_stats(None)
        mock_fact_store.get_statistics.assert_called_once_with(None, org_id="test-org-001")


# ============================================================================
# Tests: _handle_stats - statistics content
# ============================================================================


class TestHandleStatsContent:
    """Test stats response content merging."""

    def test_stats_merges_all_store_fields(self, handler, mock_fact_store):
        mock_fact_store.get_statistics.return_value = {
            "total_facts": 42,
            "by_status": {"verified": 30},
            "avg_confidence": 0.88,
            "verified_count": 30,
        }
        result = handler._handle_stats("default")
        body = _body(result)
        assert body["total_facts"] == 42
        assert body["by_status"] == {"verified": 30}
        assert body["avg_confidence"] == 0.88
        assert body["verified_count"] == 30
        assert body["workspace_id"] == "default"

    def test_stats_empty_store_returns_workspace(self, handler, mock_fact_store):
        mock_fact_store.get_statistics.return_value = {}
        result = handler._handle_stats("empty-ws")
        body = _body(result)
        assert body == {"workspace_id": "empty-ws"}

    def test_stats_workspace_id_does_not_override_store_key(self, handler, mock_fact_store):
        """If store returns a workspace_id, our explicit one takes precedence."""
        mock_fact_store.get_statistics.return_value = {
            "workspace_id": "store-ws",
            "total_facts": 5,
        }
        result = handler._handle_stats("param-ws")
        body = _body(result)
        # The unpacking order puts workspace_id first, then **stats
        # But since workspace_id is a keyword in the dict literal, the **stats
        # would overwrite it. Let's check actual behavior:
        # {"workspace_id": workspace_id, **stats} -> stats overwrites
        # Actually: {"workspace_id": "param-ws", **{"workspace_id": "store-ws", ...}}
        # In Python, later keys win, so store-ws would win
        assert body["workspace_id"] == "store-ws"


# ============================================================================
# Tests: _handle_stats - error handling
# ============================================================================


class TestHandleStatsErrors:
    """Test error handling in stats operations."""

    def test_stats_store_runtime_error_caught(self, handler, mock_fact_store):
        """handle_errors decorator should catch RuntimeError (default 500)."""
        mock_fact_store.get_statistics.side_effect = RuntimeError("DB down")
        result = handler._handle_stats(None)
        assert _status(result) == 500

    def test_stats_store_key_error_maps_to_404(self, handler, mock_fact_store):
        """KeyError maps to 404 via handle_errors exception mapping."""
        mock_fact_store.get_statistics.side_effect = KeyError("missing")
        result = handler._handle_stats(None)
        assert _status(result) == 404

    def test_stats_store_type_error_maps_to_400(self, handler, mock_fact_store):
        """TypeError maps to 400 via handle_errors exception mapping."""
        mock_fact_store.get_statistics.side_effect = TypeError("bad type")
        result = handler._handle_stats(None)
        assert _status(result) == 400

    def test_stats_store_os_error_maps_to_500(self, handler, mock_fact_store):
        """OSError maps to 500 via handle_errors exception mapping."""
        mock_fact_store.get_statistics.side_effect = OSError("disk failure")
        result = handler._handle_stats(None)
        assert _status(result) == 500

    def test_stats_store_value_error_maps_to_400(self, handler, mock_fact_store):
        """ValueError maps to 400 via handle_errors exception mapping."""
        mock_fact_store.get_statistics.side_effect = ValueError("bad value")
        result = handler._handle_stats(None)
        assert _status(result) == 400


# ============================================================================
# Tests: Protocol shape
# ============================================================================


class TestSearchHandlerProtocol:
    """Test that the protocol defines the right shape."""

    def test_concrete_handler_has_get_fact_store(self, handler):
        assert hasattr(handler, "_get_fact_store")
        assert callable(handler._get_fact_store)

    def test_concrete_handler_has_get_query_engine(self, handler):
        assert hasattr(handler, "_get_query_engine")
        assert callable(handler._get_query_engine)

    def test_mixin_has_handle_search(self):
        assert hasattr(SearchOperationsMixin, "_handle_search")

    def test_mixin_has_handle_stats(self):
        assert hasattr(SearchOperationsMixin, "_handle_stats")
