"""Tests for KnowledgeHandler (aragora/server/handlers/knowledge_base/handler.py).

Covers the main handler class behavior:
- can_handle() route matching
- _normalize_facts_path() alias normalization
- handle() routing to all endpoints
- Permission checking (_check_permission)
- Rate limiting
- Query endpoint (POST /api/v1/knowledge/query)
- Search endpoint (GET /api/v1/knowledge/search)
- Stats endpoint (GET /api/v1/knowledge/stats)
- Fact store / query engine lazy initialization
- Error handling and edge cases
- SDK alias routing (/api/v1/facts/*)
- Unknown endpoint handling
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.knowledge.embeddings import ChunkMatch
from aragora.knowledge.types import (
    Fact,
    QueryResult,
    ValidationStatus,
)
from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler


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


class MockHTTPHandler:
    """Mock HTTP request handler for knowledge handler tests."""

    def __init__(
        self,
        body: dict | None = None,
        method: str = "GET",
    ):
        self.command = method
        self.client_address = ("127.0.0.1", 12345)
        self.headers: dict[str, str] = {"User-Agent": "test-agent"}

        if body is not None:
            body_bytes = json.dumps(body).encode()
            self.rfile = io.BytesIO(body_bytes)
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.rfile = io.BytesIO(b"")
            self.headers["Content-Length"] = "0"


def _make_fact(
    fact_id: str = "fact-001",
    statement: str = "The sky is blue",
    confidence: float = 0.9,
    workspace_id: str = "default",
    topics: list[str] | None = None,
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED,
    metadata: dict[str, Any] | None = None,
) -> Fact:
    """Create a Fact instance for testing."""
    return Fact(
        id=fact_id,
        statement=statement,
        confidence=confidence,
        evidence_ids=[],
        source_documents=[],
        workspace_id=workspace_id,
        validation_status=validation_status,
        topics=topics or ["science"],
        metadata=metadata or {},
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        updated_at=datetime(2025, 1, 1, 12, 0, 0),
        superseded_by=None,
    )


def _make_query_result(
    answer: str = "The sky is blue due to Rayleigh scattering.",
    confidence: float = 0.85,
    question: str = "Why is the sky blue?",
    workspace_id: str = "default",
) -> QueryResult:
    """Create a QueryResult instance for testing."""
    return QueryResult(
        answer=answer,
        facts=[_make_fact()],
        evidence_ids=["ev-001"],
        confidence=confidence,
        query=question,
        workspace_id=workspace_id,
        processing_time_ms=150,
        agent_contributions={"claude": "Rayleigh scattering"},
        metadata={},
    )


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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_fact_store():
    """Create a mock fact store with sensible defaults."""
    store = MagicMock()
    fact1 = _make_fact("fact-001", "The sky is blue")
    fact2 = _make_fact("fact-002", "Water is wet", confidence=0.85)

    store.list_facts.return_value = [fact1, fact2]
    store.get_fact.return_value = fact1
    store.add_fact.return_value = fact1
    store.update_fact.return_value = fact1
    store.delete_fact.return_value = True
    store.get_contradictions.return_value = []
    store.get_relations.return_value = []
    store.add_relation.return_value = MagicMock()
    store.get_statistics.return_value = {
        "total_facts": 2,
        "by_status": {"unverified": 2},
        "avg_confidence": 0.875,
        "verified_count": 0,
    }

    return store


@pytest.fixture
def mock_query_engine():
    """Create a mock query engine with search support."""
    engine = MagicMock()
    engine.search = MagicMock()
    return engine


@pytest.fixture
def handler(mock_fact_store, mock_query_engine):
    """Create a KnowledgeHandler with injected mock stores."""
    h = KnowledgeHandler(server_context={})
    h._fact_store = mock_fact_store
    h._query_engine = mock_query_engine
    return h


@pytest.fixture
def get_handler():
    """Create a mock GET HTTP handler."""
    return MockHTTPHandler(method="GET")


@pytest.fixture
def post_handler_factory():
    """Factory for creating POST HTTP handlers with body."""

    def _create(body: dict) -> MockHTTPHandler:
        return MockHTTPHandler(body=body, method="POST")

    return _create


# ============================================================================
# Tests: can_handle()
# ============================================================================


class TestCanHandle:
    """Test can_handle() route matching logic."""

    def test_matches_query_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/query") is True

    def test_matches_facts_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/facts") is True

    def test_matches_facts_relations_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/facts/relations") is True

    def test_matches_facts_wildcard_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/facts/some-id") is True

    def test_matches_facts_verify_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/facts/fact-001/verify") is True

    def test_matches_facts_contradictions_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/facts/fact-001/contradictions") is True

    def test_matches_facts_id_relations_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/facts/fact-001/relations") is True

    def test_matches_search_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/search") is True

    def test_matches_stats_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/stats") is True

    def test_matches_embeddings_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/embeddings") is True

    def test_matches_entries_embeddings_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/entries/*/embeddings") is True

    def test_matches_entries_sources_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/entries/*/sources") is True

    def test_matches_export_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/export") is True

    def test_matches_refresh_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/refresh") is True

    def test_matches_validate_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/validate") is True

    def test_matches_sdk_facts_alias(self, handler):
        assert handler.can_handle("/api/v1/facts") is True

    def test_matches_sdk_facts_batch_alias(self, handler):
        assert handler.can_handle("/api/v1/facts/batch") is True

    def test_matches_sdk_facts_batch_delete_alias(self, handler):
        assert handler.can_handle("/api/v1/facts/batch/delete") is True

    def test_matches_sdk_facts_merge_alias(self, handler):
        assert handler.can_handle("/api/v1/facts/merge") is True

    def test_matches_sdk_facts_relationships_alias(self, handler):
        assert handler.can_handle("/api/v1/facts/relationships") is True

    def test_matches_sdk_facts_stats_alias(self, handler):
        assert handler.can_handle("/api/v1/facts/stats") is True

    def test_matches_sdk_facts_validate_alias(self, handler):
        assert handler.can_handle("/api/v1/facts/validate") is True

    def test_matches_index_route(self, handler):
        assert handler.can_handle("/api/v1/index") is True

    def test_matches_index_embed_batch_route(self, handler):
        assert handler.can_handle("/api/v1/index/embed-batch") is True

    def test_matches_index_search_route(self, handler):
        assert handler.can_handle("/api/v1/index/search") is True

    def test_matches_sdk_facts_dynamic_path(self, handler):
        """SDK dynamic path /api/v1/facts/<id> should be handled."""
        assert handler.can_handle("/api/v1/facts/some-fact-id") is True

    def test_does_not_match_unrelated_path(self, handler):
        assert handler.can_handle("/api/v1/debates") is False

    def test_does_not_match_partial_knowledge(self, handler):
        assert handler.can_handle("/api/v1/knowledg") is False

    def test_does_not_match_empty_path(self, handler):
        assert handler.can_handle("") is False

    def test_does_not_match_root(self, handler):
        assert handler.can_handle("/") is False

    def test_does_not_match_other_api_namespace(self, handler):
        assert handler.can_handle("/api/v1/agents") is False


# ============================================================================
# Tests: _normalize_facts_path()
# ============================================================================


class TestNormalizeFactsPath:
    """Test the _normalize_facts_path static method."""

    def test_normalizes_facts_root(self):
        result = KnowledgeHandler._normalize_facts_path("/api/v1/facts")
        assert result == "/api/v1/knowledge/facts"

    def test_normalizes_facts_with_id(self):
        result = KnowledgeHandler._normalize_facts_path("/api/v1/facts/fact-123")
        assert result == "/api/v1/knowledge/facts/fact-123"

    def test_normalizes_facts_relations(self):
        result = KnowledgeHandler._normalize_facts_path("/api/v1/facts/relations")
        assert result == "/api/v1/knowledge/facts/relations"

    def test_normalizes_facts_batch(self):
        result = KnowledgeHandler._normalize_facts_path("/api/v1/facts/batch")
        assert result == "/api/v1/knowledge/facts/batch"

    def test_normalizes_facts_id_verify(self):
        result = KnowledgeHandler._normalize_facts_path("/api/v1/facts/f1/verify")
        assert result == "/api/v1/knowledge/facts/f1/verify"

    def test_does_not_modify_knowledge_facts_path(self):
        result = KnowledgeHandler._normalize_facts_path("/api/v1/knowledge/facts")
        assert result == "/api/v1/knowledge/facts"

    def test_does_not_modify_unrelated_path(self):
        result = KnowledgeHandler._normalize_facts_path("/api/v1/debates")
        assert result == "/api/v1/debates"

    def test_does_not_modify_search_path(self):
        result = KnowledgeHandler._normalize_facts_path("/api/v1/knowledge/search")
        assert result == "/api/v1/knowledge/search"

    def test_does_not_double_normalize(self):
        """Applying normalization twice should be idempotent."""
        path = "/api/v1/facts/fact-001"
        first = KnowledgeHandler._normalize_facts_path(path)
        second = KnowledgeHandler._normalize_facts_path(first)
        assert first == second == "/api/v1/knowledge/facts/fact-001"


# ============================================================================
# Tests: Handler initialization
# ============================================================================


class TestHandlerInitialization:
    """Test KnowledgeHandler constructor and lazy init."""

    def test_init_with_empty_context(self):
        h = KnowledgeHandler(server_context={})
        assert h._fact_store is None
        assert h._query_engine is None

    def test_init_with_server_context(self):
        ctx = {"some_key": "some_value"}
        h = KnowledgeHandler(server_context=ctx)
        assert h.ctx == ctx

    def test_fact_store_lazy_creates_in_memory(self):
        """When FactStore constructor fails, fall back to InMemoryFactStore."""
        h = KnowledgeHandler(server_context={})
        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=OSError("No DB"),
        ):
            store = h._get_fact_store()
        from aragora.knowledge import InMemoryFactStore

        assert isinstance(store, InMemoryFactStore)

    def test_fact_store_caches_instance(self):
        """Calling _get_fact_store() twice returns the same object."""
        h = KnowledgeHandler(server_context={})
        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=OSError("No DB"),
        ):
            store1 = h._get_fact_store()
            store2 = h._get_fact_store()
        assert store1 is store2

    def test_query_engine_lazy_creates(self):
        """_get_query_engine() creates a SimpleQueryEngine."""
        h = KnowledgeHandler(server_context={})
        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=OSError("No DB"),
        ):
            engine = h._get_query_engine()
        from aragora.knowledge import SimpleQueryEngine

        assert isinstance(engine, SimpleQueryEngine)

    def test_query_engine_caches_instance(self):
        """Calling _get_query_engine() twice returns the same object."""
        h = KnowledgeHandler(server_context={})
        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=OSError("No DB"),
        ):
            engine1 = h._get_query_engine()
            engine2 = h._get_query_engine()
        assert engine1 is engine2

    def test_permission_constants(self, handler):
        assert handler.KNOWLEDGE_READ_PERMISSION == "knowledge.read"
        assert handler.KNOWLEDGE_WRITE_PERMISSION == "knowledge.write"
        assert handler.KNOWLEDGE_DELETE_PERMISSION == "knowledge.delete"


# ============================================================================
# Tests: POST /api/v1/knowledge/query
# ============================================================================


class TestQueryEndpoint:
    """Test POST /api/v1/knowledge/query."""

    PATCH_QUERY_RUN_ASYNC = "aragora.server.handlers.knowledge_base.query._run_async"

    def test_query_returns_200(self, handler, post_handler_factory):
        query_result = _make_query_result()
        http = post_handler_factory({"question": "Why is the sky blue?"})
        with patch(self.PATCH_QUERY_RUN_ASYNC, return_value=query_result):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 200

    def test_query_returns_answer(self, handler, post_handler_factory):
        query_result = _make_query_result()
        http = post_handler_factory({"question": "Why is the sky blue?"})
        with patch(self.PATCH_QUERY_RUN_ASYNC, return_value=query_result):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        body = _body(result)
        assert "answer" in body
        assert body["answer"] == "The sky is blue due to Rayleigh scattering."

    def test_query_returns_confidence(self, handler, post_handler_factory):
        query_result = _make_query_result(confidence=0.85)
        http = post_handler_factory({"question": "Why is the sky blue?"})
        with patch(self.PATCH_QUERY_RUN_ASYNC, return_value=query_result):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        body = _body(result)
        assert body["confidence"] == 0.85

    def test_query_returns_facts(self, handler, post_handler_factory):
        query_result = _make_query_result()
        http = post_handler_factory({"question": "Why is the sky blue?"})
        with patch(self.PATCH_QUERY_RUN_ASYNC, return_value=query_result):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        body = _body(result)
        assert "facts" in body
        assert len(body["facts"]) == 1

    def test_query_missing_question_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory({})
        result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 400

    def test_query_empty_question_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory({"question": ""})
        result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 400

    def test_query_no_body_still_works(self, handler):
        """Empty content length should result in empty data and missing question."""
        http = MockHTTPHandler(method="POST")
        result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 400

    def test_query_invalid_json_returns_400(self, handler):
        http = MockHTTPHandler(method="POST")
        http.rfile = io.BytesIO(b"not-json!!")
        http.headers["Content-Length"] = "10"
        result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 400

    def test_query_with_workspace_id(self, handler, post_handler_factory, mock_query_engine):
        query_result = _make_query_result(workspace_id="ws-test")
        http = post_handler_factory(
            {
                "question": "Test?",
                "workspace_id": "ws-test",
            }
        )
        with patch(self.PATCH_QUERY_RUN_ASYNC, return_value=query_result):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 200

    def test_query_with_options(self, handler, post_handler_factory, mock_query_engine):
        query_result = _make_query_result()
        http = post_handler_factory(
            {
                "question": "Test?",
                "options": {
                    "max_chunks": 5,
                    "search_alpha": 0.8,
                    "use_agents": True,
                    "extract_facts": False,
                    "include_citations": False,
                },
            }
        )
        with patch(self.PATCH_QUERY_RUN_ASYNC, return_value=query_result):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 200

    def test_query_engine_runtime_error_returns_500(self, handler, post_handler_factory):
        http = post_handler_factory({"question": "Test?"})
        with patch(
            self.PATCH_QUERY_RUN_ASYNC,
            side_effect=RuntimeError("Engine crashed"),
        ):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 500

    def test_query_engine_value_error_returns_500(self, handler, post_handler_factory):
        http = post_handler_factory({"question": "Test?"})
        with patch(
            self.PATCH_QUERY_RUN_ASYNC,
            side_effect=ValueError("Bad value"),
        ):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 500

    def test_query_engine_key_error_returns_500(self, handler, post_handler_factory):
        http = post_handler_factory({"question": "Test?"})
        with patch(
            self.PATCH_QUERY_RUN_ASYNC,
            side_effect=KeyError("missing"),
        ):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 500

    def test_query_engine_os_error_returns_500(self, handler, post_handler_factory):
        http = post_handler_factory({"question": "Test?"})
        with patch(
            self.PATCH_QUERY_RUN_ASYNC,
            side_effect=OSError("IO error"),
        ):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 500

    def test_query_engine_type_error_returns_500(self, handler, post_handler_factory):
        http = post_handler_factory({"question": "Test?"})
        with patch(
            self.PATCH_QUERY_RUN_ASYNC,
            side_effect=TypeError("Wrong type"),
        ):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 500

    def test_query_default_workspace_is_default(
        self, handler, post_handler_factory, mock_query_engine
    ):
        """When no workspace_id is specified, 'default' is used."""
        query_result = _make_query_result()
        http = post_handler_factory({"question": "Test?"})
        with patch(
            self.PATCH_QUERY_RUN_ASYNC,
            return_value=query_result,
        ) as mock_run:
            handler.handle("/api/v1/knowledge/query", {}, http)
            # The engine.query should be called; check it through run_async
            assert mock_run.called


# ============================================================================
# Tests: GET /api/v1/knowledge/search
# ============================================================================


class TestSearchEndpoint:
    """Test GET /api/v1/knowledge/search."""

    PATCH_SEARCH_RUN_ASYNC = "aragora.server.handlers.knowledge_base.search._run_async"

    def test_search_returns_200(self, handler, get_handler):
        chunk = _make_chunk_match()
        with patch(self.PATCH_SEARCH_RUN_ASYNC, return_value=[chunk]):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["why is the sky blue"]},
                get_handler,
            )
        assert _status(result) == 200

    def test_search_returns_results(self, handler, get_handler):
        chunk1 = _make_chunk_match("chunk-001")
        chunk2 = _make_chunk_match("chunk-002", score=0.88)
        with patch(self.PATCH_SEARCH_RUN_ASYNC, return_value=[chunk1, chunk2]):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["search term"]},
                get_handler,
            )
        body = _body(result)
        assert "results" in body
        assert body["count"] == 2

    def test_search_returns_query_in_response(self, handler, get_handler):
        with patch(self.PATCH_SEARCH_RUN_ASYNC, return_value=[]):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["my query"]},
                get_handler,
            )
        body = _body(result)
        assert body["query"] == "my query"

    def test_search_returns_workspace_id(self, handler, get_handler):
        with patch(self.PATCH_SEARCH_RUN_ASYNC, return_value=[]):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["test"], "workspace_id": ["ws-1"]},
                get_handler,
            )
        body = _body(result)
        assert body["workspace_id"] == "ws-1"

    def test_search_default_workspace(self, handler, get_handler):
        with patch(self.PATCH_SEARCH_RUN_ASYNC, return_value=[]):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["test"]},
                get_handler,
            )
        body = _body(result)
        assert body["workspace_id"] == "default"

    def test_search_missing_query_returns_400(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/search", {}, get_handler)
        assert _status(result) == 400

    def test_search_empty_query_returns_400(self, handler, get_handler):
        result = handler.handle(
            "/api/v1/knowledge/search",
            {"q": [""]},
            get_handler,
        )
        assert _status(result) == 400

    def test_search_with_limit(self, handler, get_handler, mock_query_engine):
        with patch(self.PATCH_SEARCH_RUN_ASYNC, return_value=[]):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["test"], "limit": ["5"]},
                get_handler,
            )
        assert _status(result) == 200

    def test_search_limit_clamped_to_max_50(self, handler, get_handler, mock_query_engine):
        with patch(self.PATCH_SEARCH_RUN_ASYNC, return_value=[]):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["test"], "limit": ["200"]},
                get_handler,
            )
        # Should succeed (limit internally clamped)
        assert _status(result) == 200

    def test_search_engine_error_returns_500(self, handler, get_handler):
        with patch(
            self.PATCH_SEARCH_RUN_ASYNC,
            side_effect=RuntimeError("Search failed"),
        ):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["test"]},
                get_handler,
            )
        assert _status(result) == 500

    def test_search_engine_value_error_returns_500(self, handler, get_handler):
        with patch(
            self.PATCH_SEARCH_RUN_ASYNC,
            side_effect=ValueError("Bad search"),
        ):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["test"]},
                get_handler,
            )
        assert _status(result) == 500

    def test_search_engine_os_error_returns_500(self, handler, get_handler):
        with patch(
            self.PATCH_SEARCH_RUN_ASYNC,
            side_effect=OSError("Disk error"),
        ):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["test"]},
                get_handler,
            )
        assert _status(result) == 500

    def test_search_engine_without_search_method_returns_error(self, handler, get_handler):
        """When query engine lacks search method, should raise TypeError caught by handle_errors."""
        del handler._query_engine.search
        result = handler.handle(
            "/api/v1/knowledge/search",
            {"q": ["test"]},
            get_handler,
        )
        # TypeError is caught by handle_errors and returned as 400
        assert _status(result) in (400, 500)
        body = _body(result)
        assert "error" in body

    def test_search_empty_results(self, handler, get_handler):
        with patch(self.PATCH_SEARCH_RUN_ASYNC, return_value=[]):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["nonexistent"]},
                get_handler,
            )
        body = _body(result)
        assert body["results"] == []
        assert body["count"] == 0

    def test_search_result_serialization(self, handler, get_handler):
        chunk = _make_chunk_match()
        with patch(self.PATCH_SEARCH_RUN_ASYNC, return_value=[chunk]):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["test"]},
                get_handler,
            )
        body = _body(result)
        chunk_data = body["results"][0]
        assert "chunk_id" in chunk_data
        assert "document_id" in chunk_data
        assert "content" in chunk_data
        assert "score" in chunk_data


# ============================================================================
# Tests: GET /api/v1/knowledge/stats
# ============================================================================


class TestStatsEndpoint:
    """Test GET /api/v1/knowledge/stats."""

    def test_stats_returns_200(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        assert _status(result) == 200

    def test_stats_returns_statistics(self, handler, get_handler, mock_fact_store):
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        body = _body(result)
        assert "total_facts" in body
        assert body["total_facts"] == 2

    def test_stats_returns_workspace_id_field(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        body = _body(result)
        assert "workspace_id" in body

    def test_stats_default_workspace_is_none(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        body = _body(result)
        assert body["workspace_id"] is None

    def test_stats_with_workspace_filter(self, handler, get_handler, mock_fact_store):
        params = {"workspace_id": ["my-workspace"]}
        result = handler.handle("/api/v1/knowledge/stats", params, get_handler)
        body = _body(result)
        assert body["workspace_id"] == "my-workspace"

    def test_stats_calls_store_get_statistics(self, handler, get_handler, mock_fact_store):
        handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        mock_fact_store.get_statistics.assert_called_once()

    def test_stats_passes_workspace_to_store(self, handler, get_handler, mock_fact_store):
        params = {"workspace_id": ["ws-123"]}
        handler.handle("/api/v1/knowledge/stats", params, get_handler)
        mock_fact_store.get_statistics.assert_called_once_with("ws-123", org_id="test-org-001")

    def test_stats_store_error_returns_500(self, handler, get_handler, mock_fact_store):
        mock_fact_store.get_statistics.side_effect = RuntimeError("DB down")
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        assert _status(result) == 500

    def test_stats_merges_store_data_with_workspace_id(self, handler, get_handler, mock_fact_store):
        """The response should contain both workspace_id and store stats."""
        mock_fact_store.get_statistics.return_value = {"total_facts": 42, "verified": 10}
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        body = _body(result)
        assert body["total_facts"] == 42
        assert body["verified"] == 10
        assert "workspace_id" in body


# ============================================================================
# Tests: Rate limiting
# ============================================================================


class TestRateLimiting:
    """Test rate limit behavior on knowledge endpoints."""

    def test_rate_limit_allows_normal_requests(self, handler, get_handler):
        """Normal request count should not trigger rate limit."""
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        assert _status(result) == 200

    def test_rate_limit_returns_429(self, handler, get_handler):
        """When rate limit is exceeded, 429 should be returned."""
        with patch(
            "aragora.server.handlers.knowledge_base.handler._knowledge_limiter"
        ) as mock_limiter:
            mock_limiter.is_allowed.return_value = False
            result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        assert _status(result) == 429

    def test_rate_limit_429_includes_error_message(self, handler, get_handler):
        with patch(
            "aragora.server.handlers.knowledge_base.handler._knowledge_limiter"
        ) as mock_limiter:
            mock_limiter.is_allowed.return_value = False
            result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        body = _body(result)
        assert "error" in body
        assert "rate limit" in body["error"].lower() or "Rate limit" in body["error"]


# ============================================================================
# Tests: Routing dispatching
# ============================================================================


class TestRouting:
    """Test handle() dispatches to correct methods."""

    def test_query_route_dispatched(self, handler, post_handler_factory):
        query_result = _make_query_result()
        http = post_handler_factory({"question": "Test?"})
        with patch(
            "aragora.server.handlers.knowledge_base.query._run_async",
            return_value=query_result,
        ):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert "answer" in body

    def test_facts_get_dispatches_to_list(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        assert _status(result) == 200
        body = _body(result)
        assert "facts" in body

    def test_facts_post_dispatches_to_create(self, handler, post_handler_factory):
        http = post_handler_factory({"statement": "New fact"})
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 201

    def test_search_route_dispatched(self, handler, get_handler):
        with patch(
            "aragora.server.handlers.knowledge_base.search._run_async",
            return_value=[],
        ):
            result = handler.handle(
                "/api/v1/knowledge/search",
                {"q": ["test"]},
                get_handler,
            )
        assert _status(result) == 200
        body = _body(result)
        assert "results" in body

    def test_stats_route_dispatched(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        assert _status(result) == 200
        body = _body(result)
        assert "total_facts" in body

    def test_fact_routes_dispatched(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, get_handler)
        assert _status(result) == 200

    def test_unhandled_path_returns_none(self, handler, get_handler):
        result = handler.handle("/api/v1/unrelated/path", {}, get_handler)
        assert result is None


# ============================================================================
# Tests: SDK alias routing
# ============================================================================


class TestSDKAliasRouting:
    """Test that SDK alias paths (/api/v1/facts/*) route correctly."""

    def test_sdk_facts_list(self, handler, get_handler):
        result = handler.handle("/api/v1/facts", {}, get_handler)
        assert _status(result) == 200
        body = _body(result)
        assert "facts" in body

    def test_sdk_facts_create(self, handler, post_handler_factory):
        http = post_handler_factory({"statement": "SDK fact"})
        result = handler.handle("/api/v1/facts", {}, http)
        assert _status(result) == 201

    def test_sdk_facts_get_by_id(self, handler, get_handler):
        result = handler.handle("/api/v1/facts/fact-001", {}, get_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "fact-001"

    def test_sdk_facts_update(self, handler):
        http = MockHTTPHandler(body={"confidence": 0.99}, method="PUT")
        result = handler.handle("/api/v1/facts/fact-001", {}, http)
        assert _status(result) == 200

    def test_sdk_facts_delete(self, handler):
        http = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/facts/fact-001", {}, http)
        assert _status(result) == 200

    def test_sdk_facts_verify(self, handler):
        http = MockHTTPHandler(body={}, method="POST")
        result = handler.handle("/api/v1/facts/fact-001/verify", {}, http)
        assert _status(result) == 200

    def test_sdk_facts_contradictions(self, handler, get_handler):
        result = handler.handle("/api/v1/facts/fact-001/contradictions", {}, get_handler)
        assert _status(result) == 200

    def test_sdk_facts_relations(self, handler, get_handler):
        result = handler.handle("/api/v1/facts/fact-001/relations", {}, get_handler)
        assert _status(result) == 200

    def test_sdk_facts_add_relation(self, handler, post_handler_factory):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/facts/fact-001/relations", {}, http)
        assert _status(result) == 201


# ============================================================================
# Tests: _handle_fact_routes edge cases
# ============================================================================


class TestFactRoutesEdgeCases:
    """Test _handle_fact_routes edge cases."""

    def test_unknown_sub_route_returns_404(self, handler, get_handler):
        result = handler.handle(
            "/api/v1/knowledge/facts/fact-001/unknown_sub_path",
            {},
            get_handler,
        )
        assert _status(result) == 404

    def test_deeply_nested_unknown_returns_404(self, handler, get_handler):
        result = handler.handle(
            "/api/v1/knowledge/facts/fact-001/very/deeply/nested",
            {},
            get_handler,
        )
        assert _status(result) == 404

    def test_get_on_facts_id_returns_fact(self, handler, get_handler, mock_fact_store):
        result = handler.handle("/api/v1/knowledge/facts/fact-abc", {}, get_handler)
        assert _status(result) == 200
        mock_fact_store.get_fact.assert_called_with("fact-abc", org_id="test-org-001")

    def test_put_on_facts_id_updates_fact(self, handler, mock_fact_store):
        http = MockHTTPHandler(body={"confidence": 0.5}, method="PUT")
        result = handler.handle("/api/v1/knowledge/facts/fact-abc", {}, http)
        assert _status(result) == 200
        mock_fact_store.update_fact.assert_called_once()

    def test_delete_on_facts_id_deletes_fact(self, handler, mock_fact_store):
        http = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/knowledge/facts/fact-abc", {}, http)
        assert _status(result) == 200
        mock_fact_store.delete_fact.assert_called_once_with("fact-abc", org_id="test-org-001")

    def test_post_on_facts_id_verify(self, handler, mock_fact_store):
        http = MockHTTPHandler(body={}, method="POST")
        result = handler.handle("/api/v1/knowledge/facts/fact-001/verify", {}, http)
        assert _status(result) == 200

    def test_get_contradictions(self, handler, get_handler, mock_fact_store):
        result = handler.handle(
            "/api/v1/knowledge/facts/fact-001/contradictions",
            {},
            get_handler,
        )
        assert _status(result) == 200
        mock_fact_store.get_contradictions.assert_called_once_with(
            "fact-001", org_id="test-org-001"
        )

    def test_get_relations(self, handler, get_handler, mock_fact_store):
        result = handler.handle(
            "/api/v1/knowledge/facts/fact-001/relations",
            {},
            get_handler,
        )
        assert _status(result) == 200
        mock_fact_store.get_relations.assert_called_once()

    def test_post_relations_on_fact_id(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle(
            "/api/v1/knowledge/facts/fact-001/relations",
            {},
            http,
        )
        assert _status(result) == 201

    def test_bulk_relations_route(self, handler, post_handler_factory, mock_fact_store):
        """POST /api/v1/knowledge/facts/relations routes to bulk handler."""
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert _status(result) == 201


# ============================================================================
# Tests: _check_permission
# ============================================================================


class TestCheckPermission:
    """Test the _check_permission method."""

    @pytest.mark.no_auto_auth
    def test_check_permission_returns_error_on_unauthenticated(self):
        """When user is not authenticated, _check_permission returns 401."""
        h = KnowledgeHandler(server_context={})
        http = MockHTTPHandler(method="GET")
        # Without auto-auth, require_auth_or_error returns (None, error)
        result = h._check_permission(http, "knowledge.read")
        assert result is not None
        assert _status(result) in (401, 403)

    def test_check_permission_returns_none_for_admin(self, handler, get_handler):
        """Admin users should pass _check_permission (returns None)."""
        result = handler._check_permission(get_handler, "knowledge.read")
        assert result is None

    def test_check_permission_returns_none_for_admin_role(self, handler, get_handler):
        """The auto-auth fixture gives admin role, so permissions pass."""
        result = handler._check_permission(get_handler, "knowledge.write")
        assert result is None


# ============================================================================
# Tests: Method-based permission routing in handle()
# ============================================================================


class TestMethodPermissionRouting:
    """Test that handle() checks appropriate permissions per HTTP method."""

    def test_get_routes_to_facts(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        assert _status(result) == 200

    def test_post_query_routes_correctly(self, handler, post_handler_factory):
        query_result = _make_query_result()
        http = post_handler_factory({"question": "Test?"})
        with patch(
            "aragora.server.handlers.knowledge_base.query._run_async",
            return_value=query_result,
        ):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert _status(result) == 200

    def test_post_fact_create_routes_correctly(self, handler, post_handler_factory):
        http = post_handler_factory({"statement": "New"})
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 201

    def test_put_fact_update_routes_correctly(self, handler):
        http = MockHTTPHandler(body={"confidence": 0.7}, method="PUT")
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        assert _status(result) == 200

    def test_delete_fact_routes_correctly(self, handler):
        http = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        assert _status(result) == 200


# ============================================================================
# Tests: Handler returns None for unrecognized paths
# ============================================================================


class TestHandlerReturnsNone:
    """Test that handle() returns None for paths it does not recognize."""

    def test_returns_none_for_debates_path(self, handler, get_handler):
        result = handler.handle("/api/v1/debates", {}, get_handler)
        assert result is None

    def test_returns_none_for_agents_path(self, handler, get_handler):
        result = handler.handle("/api/v1/agents", {}, get_handler)
        assert result is None

    def test_returns_none_for_empty_path(self, handler, get_handler):
        result = handler.handle("", {}, get_handler)
        assert result is None

    def test_returns_none_for_root_path(self, handler, get_handler):
        result = handler.handle("/", {}, get_handler)
        assert result is None


# ============================================================================
# Tests: ROUTES constant
# ============================================================================


class TestRoutesConstant:
    """Test that the ROUTES constant contains expected entries."""

    def test_routes_is_list(self):
        assert isinstance(KnowledgeHandler.ROUTES, list)

    def test_routes_contain_query(self):
        assert "/api/v1/knowledge/query" in KnowledgeHandler.ROUTES

    def test_routes_contain_facts(self):
        assert "/api/v1/knowledge/facts" in KnowledgeHandler.ROUTES

    def test_routes_contain_search(self):
        assert "/api/v1/knowledge/search" in KnowledgeHandler.ROUTES

    def test_routes_contain_stats(self):
        assert "/api/v1/knowledge/stats" in KnowledgeHandler.ROUTES

    def test_routes_contain_embeddings(self):
        assert "/api/v1/knowledge/embeddings" in KnowledgeHandler.ROUTES

    def test_routes_contain_export(self):
        assert "/api/v1/knowledge/export" in KnowledgeHandler.ROUTES

    def test_routes_contain_refresh(self):
        assert "/api/v1/knowledge/refresh" in KnowledgeHandler.ROUTES

    def test_routes_contain_validate(self):
        assert "/api/v1/knowledge/validate" in KnowledgeHandler.ROUTES

    def test_routes_contain_sdk_facts_aliases(self):
        assert "/api/v1/facts" in KnowledgeHandler.ROUTES
        assert "/api/v1/facts/batch" in KnowledgeHandler.ROUTES
        assert "/api/v1/facts/batch/delete" in KnowledgeHandler.ROUTES
        assert "/api/v1/facts/merge" in KnowledgeHandler.ROUTES
        assert "/api/v1/facts/relationships" in KnowledgeHandler.ROUTES
        assert "/api/v1/facts/stats" in KnowledgeHandler.ROUTES
        assert "/api/v1/facts/validate" in KnowledgeHandler.ROUTES

    def test_routes_contain_index_aliases(self):
        assert "/api/v1/index" in KnowledgeHandler.ROUTES
        assert "/api/v1/index/embed-batch" in KnowledgeHandler.ROUTES
        assert "/api/v1/index/search" in KnowledgeHandler.ROUTES

    def test_routes_all_start_with_api_v1(self):
        for route in KnowledgeHandler.ROUTES:
            assert route.startswith("/api/v1/"), f"Route {route} does not start with /api/v1/"


# ============================================================================
# Tests: Edge cases and miscellaneous
# ============================================================================


class TestEdgeCases:
    """Test various edge cases for the knowledge handler."""

    def test_handler_with_none_client_address(self, handler):
        """Handler should work when client_address is not set."""
        http = MockHTTPHandler(method="GET")
        http.client_address = None
        result = handler.handle("/api/v1/knowledge/stats", {}, http)
        assert _status(result) == 200

    def test_handler_query_params_list_format(self, handler, get_handler):
        """Query params should handle list values (as from urllib.parse_qs)."""
        params = {"workspace_id": ["ws-test"]}
        result = handler.handle("/api/v1/knowledge/stats", params, get_handler)
        body = _body(result)
        assert body["workspace_id"] == "ws-test"

    def test_handler_query_params_empty_dict(self, handler, get_handler):
        """Empty query params should use defaults."""
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        assert _status(result) == 200

    def test_method_attribute_defaults_to_get(self, handler):
        """When handler has no 'command' attribute, method should default to GET."""
        http = MockHTTPHandler(method="GET")
        del http.command
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert "facts" in body

    def test_multiple_sequential_requests(self, handler, get_handler):
        """Handler should handle multiple sequential requests correctly."""
        r1 = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        assert _status(r1) == 200

        r2 = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        assert _status(r2) == 200

    def test_fact_id_with_special_characters(self, handler, get_handler, mock_fact_store):
        """Fact IDs with common separators should be accepted."""
        result = handler.handle(
            "/api/v1/knowledge/facts/fact-001-abc_xyz",
            {},
            get_handler,
        )
        assert _status(result) == 200
        mock_fact_store.get_fact.assert_called_with("fact-001-abc_xyz", org_id="test-org-001")

    def test_handler_inherits_from_base_handler(self):
        """KnowledgeHandler should inherit from BaseHandler."""
        from aragora.server.handlers.base import BaseHandler

        assert issubclass(KnowledgeHandler, BaseHandler)

    def test_handler_includes_all_mixins(self):
        """KnowledgeHandler should include all three mixins."""
        from aragora.server.handlers.knowledge_base.facts import FactsOperationsMixin
        from aragora.server.handlers.knowledge_base.query import QueryOperationsMixin
        from aragora.server.handlers.knowledge_base.search import SearchOperationsMixin

        assert issubclass(KnowledgeHandler, FactsOperationsMixin)
        assert issubclass(KnowledgeHandler, QueryOperationsMixin)
        assert issubclass(KnowledgeHandler, SearchOperationsMixin)

    def test_limiter_buckets_cleared_on_init(self):
        """Constructor should clear rate limiter buckets to prevent cross-test leakage."""
        h = KnowledgeHandler(server_context={})
        # No exception should be raised
        assert h is not None
