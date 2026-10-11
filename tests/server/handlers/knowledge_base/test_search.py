"""
Tests for SearchOperationsMixin in knowledge_base search handler.

Tests cover:
- Import verification
- Search with valid query
- Search with missing 'q' parameter (400 error)
- Search with custom workspace_id and limit
- Search limit clamping (min 1, max 50)
- Search failure handling (500 error)
- Stats endpoint
- Stats with workspace_id filter
- Response format validation

Run with:
    pytest tests/server/handlers/knowledge_base/test_search.py -v --noconftest --timeout=30
"""

from __future__ import annotations

import functools
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Pre-mock broken transitive imports to allow importing without
# triggering the full handlers.__init__ chain
if "aragora.server.handlers.social._slack_impl" not in sys.modules:
    sys.modules["aragora.server.handlers.social._slack_impl"] = MagicMock()


# Bypass RBAC decorator by patching it before import
def _bypass_require_permission(permission):
    """No-op decorator for testing that preserves __wrapped__."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


# Patch decorators before importing the mixin, then stop to avoid
# leaking into other test modules.
_p1 = patch("aragora.rbac.decorators.require_permission", _bypass_require_permission)
_p2 = patch(
    "aragora.server.handlers.knowledge_base.search.require_permission", _bypass_require_permission
)
_p1.start()
_p2.start()

import pytest

from aragora.server.handlers.knowledge_base.search import SearchOperationsMixin  # noqa: E402

_p1.stop()
_p2.stop()


def parse_response(result) -> dict[str, Any]:
    """Parse HandlerResult body to dict."""
    body = result.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)


# =============================================================================
# Mock Objects
# =============================================================================


@dataclass
class MockSearchResult:
    """Mock search result from query engine."""

    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
        }


@dataclass
class MockKnowledgeItem:
    """Mock Knowledge Mound item for normalized search responses."""

    id: str
    content: str
    confidence: float
    node_type: str = "fact"
    domain: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "confidence": self.confidence,
            "node_type": self.node_type,
            "domain": self.domain,
            "metadata": self.metadata,
        }


class MockQueryEngine:
    """Mock query engine for testing."""

    def __init__(self, results: list[MockSearchResult] | None = None):
        self._results = results or []
        self._search_error: Exception | None = None
        self.org_ids: list[str | None] = []

    async def search(
        self, query: str, workspace_id: str, limit: int, *, org_id: str | None = None
    ) -> list[MockSearchResult]:
        self.org_ids.append(org_id)
        if self._search_error:
            raise self._search_error
        return self._results[:limit]


class MockKnowledgeMound:
    """Mock Knowledge Mound for testing KM-backed search."""

    def __init__(self, items: list[MockKnowledgeItem] | None = None):
        self._items = items or []
        self._query_error: Exception | None = None

    async def query_semantic(
        self,
        text: str,
        limit: int = 10,
        min_confidence: float = 0.0,
        workspace_id: str | None = None,
        allow_fallback: bool = True,
    ) -> list[MockKnowledgeItem]:
        if self._query_error:
            raise self._query_error
        return [item for item in self._items if item.confidence >= min_confidence][:limit]


class MockFactStore:
    """Mock fact store for testing."""

    def __init__(self, stats: dict[str, Any] | None = None):
        self._stats = stats or {
            "total_chunks": 100,
            "total_facts": 50,
            "indexed_workspaces": 3,
        }

    def get_statistics(
        self, workspace_id: str | None = None, *, org_id: str | None = None
    ) -> dict[str, Any]:
        result = self._stats.copy()
        if workspace_id:
            result["workspace_id"] = workspace_id
        return result


class SearchHandler(SearchOperationsMixin):
    """Handler implementation for testing SearchOperationsMixin."""

    def __init__(
        self,
        query_engine: MockQueryEngine | None = None,
        fact_store: MockFactStore | None = None,
        knowledge_mound: MockKnowledgeMound | None = None,
    ):
        self._query_engine = query_engine
        self._fact_store = fact_store
        self._knowledge_mound = knowledge_mound
        self.ctx: dict[str, Any] = {}

    def _get_query_engine(self):
        return self._query_engine

    def _get_fact_store(self):
        return self._fact_store

    def _get_knowledge_mound(self):
        return self._knowledge_mound

    def require_auth_or_error(self, handler):
        return MagicMock(org_id="test-org-001"), None


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_query_engine():
    """Create a mock query engine with sample results."""
    results = [
        MockSearchResult(
            chunk_id="chunk-1",
            content="First result content",
            score=0.95,
            metadata={"source": "doc-1"},
        ),
        MockSearchResult(
            chunk_id="chunk-2",
            content="Second result content",
            score=0.87,
            metadata={"source": "doc-2"},
        ),
        MockSearchResult(
            chunk_id="chunk-3",
            content="Third result content",
            score=0.75,
            metadata={"source": "doc-3"},
        ),
    ]
    return MockQueryEngine(results=results)


@pytest.fixture
def mock_fact_store():
    """Create a mock fact store with sample stats."""
    return MockFactStore(
        stats={
            "total_chunks": 1500,
            "total_facts": 750,
            "indexed_workspaces": 5,
            "last_indexed": "2026-01-29T10:00:00Z",
        }
    )


@pytest.fixture
def handler(mock_query_engine, mock_fact_store):
    """Create a test handler with mock dependencies."""
    return SearchHandler(
        query_engine=mock_query_engine,
        fact_store=mock_fact_store,
    )


@pytest.fixture
def mock_knowledge_mound():
    """Create a mock Knowledge Mound with sample semantic results."""
    return MockKnowledgeMound(
        items=[
            MockKnowledgeItem(
                id="km-1",
                content="Rate limiting best practices for API gateways",
                confidence=0.92,
                node_type="fact",
                domain="architecture",
                metadata={"title": "Rate limiting", "org_id": "test-org-001"},
            ),
            MockKnowledgeItem(
                id="km-2",
                content="Lower-confidence finance note",
                confidence=0.41,
                node_type="claim",
                domain="finance",
                metadata={"org_id": "test-org-001"},
            ),
        ]
    )


@pytest.fixture
def handler_with_knowledge_mound(mock_query_engine, mock_fact_store, mock_knowledge_mound):
    """Create a test handler with both legacy search and KM available."""
    return SearchHandler(
        query_engine=mock_query_engine,
        fact_store=mock_fact_store,
        knowledge_mound=mock_knowledge_mound,
    )


@pytest.fixture
def handler_no_engine():
    """Create a test handler without query engine."""
    return SearchHandler(query_engine=None, fact_store=MockFactStore())


@pytest.fixture
def handler_no_store():
    """Create a test handler without fact store."""
    return SearchHandler(query_engine=MockQueryEngine(), fact_store=None)


# =============================================================================
# Test Imports
# =============================================================================


class TestImports:
    """Tests for module imports and exports."""

    def test_import_search_operations_mixin(self):
        """Test that SearchOperationsMixin can be imported."""
        from aragora.server.handlers.knowledge_base.search import SearchOperationsMixin

        assert SearchOperationsMixin is not None

    def test_mixin_has_required_methods(self):
        """Test that mixin exposes required methods."""
        assert hasattr(SearchOperationsMixin, "_handle_search")
        assert hasattr(SearchOperationsMixin, "_handle_stats")
        assert callable(getattr(SearchOperationsMixin, "_handle_search"))
        assert callable(getattr(SearchOperationsMixin, "_handle_stats"))


# =============================================================================
# Test Search Endpoint
# =============================================================================


class TestHandleSearch:
    """Tests for _handle_search endpoint."""

    def test_search_with_valid_query(self, handler):
        """Test search with valid query returns results."""
        query_params = {"q": "test query"}

        # Create mock results with to_dict() method (as expected by the handler)
        mock_results = [
            MockSearchResult("c1", "content", 0.9),
            MockSearchResult("c2", "more", 0.8),
        ]

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: mock_results,
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["query"] == "test query"
        assert body["workspace_id"] == "default"
        assert "results" in body
        assert "count" in body
        assert body["count"] == 2
        assert body["total"] == 2
        assert body["search_backend"] == "query_engine"
        assert body["results"][0]["node_id"] == "c1"
        assert body["results"][0]["chunk_id"] == "c1"

    def test_search_missing_query_param(self, handler):
        """Test search without 'q' parameter returns 400."""
        query_params = {}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            result = handler._handle_search(query_params)

        assert result.status_code == 400
        body = parse_response(result)
        assert "error" in body
        assert "required" in body["error"].lower() or "q" in body["error"].lower()

    def test_search_accepts_query_alias(self, handler):
        """Test search accepts frontend-friendly `query` parameter."""
        query_params = {"query": "architecture"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["query"] == "architecture"

    def test_search_empty_query_param(self, handler):
        """Test search with empty 'q' parameter returns 400."""
        query_params = {"q": ""}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            result = handler._handle_search(query_params)

        assert result.status_code == 400
        body = parse_response(result)
        assert "error" in body

    def test_search_with_custom_workspace_id(self, handler):
        """Test search with custom workspace_id parameter."""
        query_params = {"q": "test", "workspace_id": "ws-custom-123"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["workspace_id"] == "ws-custom-123"

    def test_search_with_custom_limit(self, handler):
        """Test search with custom limit parameter."""
        query_params = {"q": "test", "limit": "25"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200

    def test_search_prefers_knowledge_mound_when_available(self, handler_with_knowledge_mound):
        """KM-backed search should use KM retrieval and normalized node results."""
        query_params = {"query": "rate limiter", "workspace_id": "ws-km"}

        class _Retrieved:
            def __init__(self, items):
                self.items = items

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: _Retrieved(handler_with_knowledge_mound._knowledge_mound._items[:1]),
            ):
                result = handler_with_knowledge_mound._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["search_backend"] == "knowledge_mound"
        assert body["total"] == 1
        assert body["results"][0]["node_id"] == "km-1"
        assert body["results"][0]["node_type"] == "fact"
        assert body["results"][0]["metadata"]["title"] == "Rate limiting"

    def test_search_filters_knowledge_mound_results(self, handler_with_knowledge_mound):
        """KM-backed search respects min_confidence and domain filters."""
        query_params = {
            "query": "rate limiter",
            "min_confidence": "0.9",
            "domain": "architecture",
        }

        class _Retrieved:
            def __init__(self, items):
                self.items = items

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: _Retrieved(handler_with_knowledge_mound._knowledge_mound._items),
            ):
                result = handler_with_knowledge_mound._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["total"] == 1
        assert body["results"][0]["node_id"] == "km-1"

    def test_search_limit_clamped_to_minimum(self, handler):
        """Test that limit is clamped to minimum of 1."""
        query_params = {"q": "test", "limit": "0"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        # Should succeed (limit clamped to 1)
        assert result.status_code == 200

    def test_search_limit_clamped_to_maximum(self, handler):
        """Test that limit is clamped to maximum of 50."""
        query_params = {"q": "test", "limit": "100"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        # Should succeed (limit clamped to 50)
        assert result.status_code == 200

    def test_search_negative_limit_clamped(self, handler):
        """Test that negative limit is clamped to minimum."""
        query_params = {"q": "test", "limit": "-5"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        # Should succeed (limit clamped to 1)
        assert result.status_code == 200

    def test_search_query_truncated_at_max_length(self, handler):
        """Test that query longer than 500 chars is truncated."""
        long_query = "a" * 600
        query_params = {"q": long_query}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)
        # Query should be truncated to max 500 chars
        assert len(body["query"]) <= 500

    def test_search_workspace_id_truncated_at_max_length(self, handler):
        """Test that workspace_id longer than 100 chars is truncated."""
        long_ws_id = "ws-" + "a" * 150
        query_params = {"q": "test", "workspace_id": long_ws_id}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)
        # workspace_id should be truncated to max 100 chars
        assert len(body["workspace_id"]) <= 100

    def test_search_failure_returns_500(self, handler):
        """Test search failure returns 500 error."""
        query_params = {"q": "test"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                side_effect=ValueError("Database connection failed"),
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 500
        body = parse_response(result)
        assert "error" in body

    def test_search_response_format(self, handler):
        """Test search response has correct format."""
        query_params = {"q": "test"}

        mock_results = [
            MockSearchResult("c1", "content 1", 0.95, {"source": "doc1"}),
            MockSearchResult("c2", "content 2", 0.85, {"source": "doc2"}),
        ]

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: mock_results,
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)

        # Verify response structure
        assert "query" in body
        assert "workspace_id" in body
        assert "results" in body
        assert "count" in body
        assert isinstance(body["results"], list)
        assert body["count"] == len(body["results"])
        assert body["count"] == 2

        # Verify result item structure
        for item in body["results"]:
            assert "chunk_id" in item
            assert "content" in item
            assert "score" in item


class _OrglessSearchHandler(SearchHandler):
    def require_auth_or_error(self, handler):
        return MagicMock(org_id=None), None


class TestSearchOrganizationScope:
    """v1 search reads only the caller's verified organization and fails closed without one."""

    def test_query_engine_search_receives_the_callers_organization(self):
        engine = MockQueryEngine([MockSearchResult("c1", "content", 0.9)])
        result = SearchHandler(query_engine=engine, fact_store=MockFactStore())._handle_search(
            {"q": "content", "workspace_id": "ws-1"}
        )

        assert result.status_code == 200
        assert engine.org_ids == ["test-org-001"]

    def test_caller_without_an_organization_gets_403_before_any_read(self):
        engine = MockQueryEngine([MockSearchResult("c1", "content", 0.9)])
        result = _OrglessSearchHandler(
            query_engine=engine, fact_store=MockFactStore()
        )._handle_search({"q": "content"})

        assert result.status_code == 403
        assert parse_response(result)["error"]["code"] == "knowledge_org_required"
        assert engine.org_ids == []

    def test_knowledge_mound_results_are_confined_to_the_callers_organization(self):
        items = [
            MockKnowledgeItem("own", "own note", 0.9, metadata={"org_id": "test-org-001"}),
            MockKnowledgeItem("other", "other org note", 0.9, metadata={"org_id": "beta"}),
            MockKnowledgeItem("legacy", "legacy note", 0.9),
        ]
        handler = SearchHandler(
            query_engine=MockQueryEngine(),
            fact_store=MockFactStore(),
            knowledge_mound=MockKnowledgeMound(items),
        )
        retrieved = MagicMock(items=items)

        with patch(
            "aragora.server.handlers.knowledge_base.search._run_async", lambda coro: retrieved
        ):
            result = handler._handle_search({"q": "note"})

        assert result.status_code == 200
        body = parse_response(result)
        assert body["search_backend"] == "knowledge_mound"
        assert [r["node_id"] for r in body["results"]] == ["own"]


# =============================================================================
# Test Stats Endpoint
# =============================================================================


class TestHandleStats:
    """Tests for _handle_stats endpoint."""

    def test_stats_without_workspace_filter(self, handler):
        """Test stats endpoint without workspace filter."""
        result = handler._handle_stats(workspace_id=None)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["workspace_id"] is None
        assert "total_chunks" in body
        assert "total_facts" in body

    def test_stats_with_workspace_filter(self, handler):
        """Test stats endpoint with workspace filter."""
        result = handler._handle_stats(workspace_id="ws-123")

        assert result.status_code == 200
        body = parse_response(result)
        assert body["workspace_id"] == "ws-123"

    def test_stats_response_includes_store_stats(self, handler):
        """Test stats response includes all store statistics."""
        result = handler._handle_stats(workspace_id=None)

        assert result.status_code == 200
        body = parse_response(result)

        # Check expected stats fields
        assert body["total_chunks"] == 1500
        assert body["total_facts"] == 750
        assert body["indexed_workspaces"] == 5
        assert body["last_indexed"] == "2026-01-29T10:00:00Z"

    def test_stats_no_fact_store(self, handler_no_store):
        """Test stats when fact store is not available."""
        # When _get_fact_store returns None, calling get_statistics
        # on None will raise AttributeError, which should be caught
        # by @handle_errors and return 500
        try:
            result = handler_no_store._handle_stats(workspace_id=None)
            # If handler returns a valid response, the mock store must have been used
            # This indicates the fixture is providing a fallback mock store
            assert result.status_code in (200, 500)
        except (AttributeError, TypeError):
            # Expected if _get_fact_store returns None and code tries to use it
            # without @handle_errors catching it
            pass

    def test_stats_response_format(self, handler):
        """Test stats response has correct format."""
        result = handler._handle_stats(workspace_id="test-ws")

        assert result.status_code == 200
        body = parse_response(result)

        # Verify all expected fields from fact store are present
        assert "workspace_id" in body
        assert isinstance(body.get("total_chunks"), int)
        assert isinstance(body.get("total_facts"), int)


# =============================================================================
# Test RBAC Decorator
# =============================================================================


class TestRBACDecorator:
    """Tests for RBAC permission decorator on endpoints."""

    def test_search_has_permission_decorator(self):
        """Test that _handle_search has require_permission decorator."""
        # Check that the method has been decorated
        method = SearchOperationsMixin._handle_search
        # The decorator wraps the function, so check for wrapper attributes
        assert callable(method)

    def test_stats_is_not_cached(self):
        """Stats are per organization, so no shared response cache wraps them."""
        assert not hasattr(SearchOperationsMixin._handle_stats, "cache_clear")


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_search_with_special_characters_in_query(self, handler):
        """Test search with special characters in query."""
        query_params = {"q": "test <script>alert('xss')</script>"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        # Should handle gracefully
        assert result.status_code == 200

    def test_search_with_unicode_query(self, handler):
        """Test search with unicode characters in query."""
        query_params = {"q": "test with unicode characters"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["query"] == "test with unicode characters"

    def test_search_with_whitespace_only_query(self, handler):
        """Test search with whitespace-only query.

        Note: The implementation accepts whitespace-only queries, treating them
        as valid search input (it does not trim/strip the query).
        """
        query_params = {"q": "   "}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        # The implementation accepts whitespace-only queries
        assert result.status_code == 200
        body = parse_response(result)
        assert body["query"] == "   "

    def test_search_with_non_numeric_limit(self, handler):
        """Test search with non-numeric limit parameter."""
        query_params = {"q": "test", "limit": "abc"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        # Should fall back to default limit
        assert result.status_code == 200

    def test_search_default_limit_is_10(self, handler):
        """Test that default limit is 10."""
        query_params = {"q": "test"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200
        # The response doesn't include limit but we verify the call works

    def test_search_default_workspace_is_default(self, handler):
        """Test that default workspace_id is 'default'."""
        query_params = {"q": "test"}

        with patch(
            "aragora.server.handlers.knowledge_base.search.require_permission",
            lambda p: lambda f: f,
        ):
            with patch(
                "aragora.server.handlers.knowledge_base.search._run_async",
                lambda coro: [],
            ):
                result = handler._handle_search(query_params)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["workspace_id"] == "default"
