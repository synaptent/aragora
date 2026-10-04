"""Tests for document NL query handler.

Tests the document query API endpoints including:
- POST /api/v1/documents/query - Ask questions about documents
- POST /api/v1/documents/summarize - Summarize documents
- POST /api/v1/documents/compare - Compare multiple documents
- POST /api/v1/documents/extract - Extract structured information
- GET /api/v1/documents/search - Keyword search over the caller org's documents
- GET (other routes) - Returns 405 Method Not Allowed

Also tests:
- Input validation (missing fields, empty bodies, type checking)
- Error handling (RuntimeError, ValueError, TypeError, OSError, KeyError)
- Config forwarding to QueryConfig
- Async engine invocation via _run_async
- Security (path traversal, injection, oversized inputs)
- can_handle route matching
"""

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.features.document_query import DocumentQueryHandler
from aragora.server.handlers.base import HandlerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status(result: HandlerResult) -> int:
    """Extract status code from HandlerResult."""
    return result.status_code


def _body(result: HandlerResult) -> dict[str, Any]:
    """Extract parsed JSON body from HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


@dataclass
class MockHTTPHandler:
    """Mock HTTP handler that mimics the real HTTP handler attributes."""

    body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None

    def __post_init__(self):
        if self.headers is None:
            self.headers = {"Content-Length": "0", "Content-Type": "application/json"}
        self.client_address = ("127.0.0.1", 12345)
        self.rfile = MagicMock()
        if self.body:
            body_bytes = json.dumps(self.body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.rfile.read.return_value = b""
            self.headers["Content-Length"] = "0"


class MockQueryResult:
    """Mock result object returned by DocumentQueryEngine methods."""

    def __init__(self, data: dict[str, Any] | None = None):
        self._data = data or {
            "query_id": "query_abc123",
            "question": "What are the payment terms?",
            "answer": "The payment terms are net-30.",
            "confidence": "high",
            "citations": [{"document_id": "doc1", "text": "Net-30 payment", "page": 2}],
            "processing_time_ms": 150,
        }

    def to_dict(self) -> dict[str, Any]:
        return self._data


class MockQueryEngine:
    """Mock DocumentQueryEngine for testing."""

    def __init__(self, config=None):
        self.config = config
        self._query_result = MockQueryResult()
        self._summarize_result = MockQueryResult(
            {
                "query_id": "sum_abc123",
                "answer": "Document summary here.",
                "confidence": "high",
                "citations": [],
            }
        )
        self._compare_result = MockQueryResult(
            {
                "query_id": "cmp_abc123",
                "answer": "Comparison result here.",
                "confidence": "medium",
                "citations": [],
            }
        )
        self._extract_results = {
            "parties": MockQueryResult(
                {
                    "answer": "Party A and Party B",
                    "confidence": "high",
                    "citations": [],
                }
            ),
        }

    @classmethod
    async def create(cls, config=None, searcher=None):
        return cls(config=config)

    async def query(self, question, workspace_id=None, document_ids=None, conversation_id=None):
        return self._query_result

    async def summarize_documents(self, document_ids=None, focus=None):
        return self._summarize_result

    async def compare_documents(self, document_ids=None, aspects=None):
        return self._compare_result

    async def extract_information(self, document_ids=None, extraction_template=None):
        return self._extract_results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


TEST_ORG = "test-org-001"


class _SameOrgDocumentStore:
    """Document store in which every requested id is a document of the caller's org."""

    def get(self, doc_id: str) -> Any:
        if "/" in doc_id or "\x00" in doc_id:
            return None  # the real store refuses ids that are not safe file names
        return SimpleNamespace(
            id=doc_id, filename=f"{doc_id}.txt", text=f"text of {doc_id}", org_id=TEST_ORG
        )

    def list_for_org(self, org_id: str) -> list[dict[str, Any]]:
        return [{"id": "doc1"}, {"id": "doc2"}] if org_id == TEST_ORG else []


@pytest.fixture
def handler():
    """Create a DocumentQueryHandler whose store holds the caller org's documents."""
    return DocumentQueryHandler(ctx={"document_store": _SameOrgDocumentStore()})


@pytest.fixture(autouse=True)
def _bypass_jwt_auth(monkeypatch):
    """Authenticate every request as test-user-001 of test-org-001."""
    from aragora.billing.auth.context import UserAuthContext

    user = UserAuthContext(
        authenticated=True,
        user_id="test-user-001",
        email="test@example.com",
        org_id=TEST_ORG,
        role="member",
        token_type="access",
    )
    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda handler, user_store=None: user,
    )


@pytest.fixture(autouse=True)
def _patch_run_async(monkeypatch):
    """Patch _run_async to just run the coroutine synchronously."""
    import asyncio

    def _sync_run(coro):
        """Run coroutine synchronously for testing."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr(
        "aragora.server.handlers.features.document_query._run_async",
        _sync_run,
    )


@pytest.fixture
def mock_engine():
    """Create a mock query engine."""
    return MockQueryEngine()


def _make_handler(body: dict[str, Any] | None = None) -> MockHTTPHandler:
    """Helper to create a MockHTTPHandler with optional body."""
    return MockHTTPHandler(body=body)


# =============================================================================
# Initialization Tests
# =============================================================================


class TestDocumentQueryHandlerInit:
    """Tests for handler initialization."""

    def test_init_with_no_args(self):
        h = DocumentQueryHandler()
        assert h.ctx == {}

    def test_init_with_ctx(self):
        ctx = {"key": "value"}
        h = DocumentQueryHandler(ctx=ctx)
        assert h.ctx == ctx

    def test_init_with_server_context(self):
        ctx = {"key": "old"}
        server_ctx = {"key": "new"}
        h = DocumentQueryHandler(ctx=ctx, server_context=server_ctx)
        assert h.ctx == server_ctx

    def test_init_server_context_takes_precedence(self):
        h = DocumentQueryHandler(ctx={"a": 1}, server_context={"b": 2})
        assert h.ctx == {"b": 2}

    def test_routes_defined(self, handler):
        assert hasattr(handler, "ROUTES")
        assert len(handler.ROUTES) == 5

    def test_expected_routes(self, handler):
        expected = {
            "/api/v1/documents/query",
            "/api/v1/documents/search",
            "/api/v1/documents/summarize",
            "/api/v1/documents/compare",
            "/api/v1/documents/extract",
        }
        assert set(handler.ROUTES) == expected


# =============================================================================
# can_handle Tests
# =============================================================================


class TestCanHandle:
    """Tests for route matching."""

    def test_can_handle_query(self, handler):
        assert handler.can_handle("/api/v1/documents/query")

    def test_can_handle_search(self, handler):
        assert handler.can_handle("/api/v1/documents/search")

    def test_can_handle_summarize(self, handler):
        assert handler.can_handle("/api/v1/documents/summarize")

    def test_can_handle_compare(self, handler):
        assert handler.can_handle("/api/v1/documents/compare")

    def test_can_handle_extract(self, handler):
        assert handler.can_handle("/api/v1/documents/extract")

    def test_cannot_handle_unknown(self, handler):
        assert not handler.can_handle("/api/v1/documents/unknown")

    def test_cannot_handle_partial(self, handler):
        assert not handler.can_handle("/api/v1/documents")

    def test_cannot_handle_different_prefix(self, handler):
        assert not handler.can_handle("/api/v1/debates/query")

    def test_cannot_handle_empty(self, handler):
        assert not handler.can_handle("")

    def test_cannot_handle_root(self, handler):
        assert not handler.can_handle("/")

    def test_case_sensitive(self, handler):
        assert not handler.can_handle("/api/v1/documents/QUERY")
        assert not handler.can_handle("/API/V1/DOCUMENTS/query")


# =============================================================================
# GET (handle) Tests - 405 Method Not Allowed
# =============================================================================


class TestHandleGet:
    """Tests for GET requests, which should all return 405."""

    def test_get_query_returns_405(self, handler):
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 405
        body = _body(result)
        error = body.get("error", {})
        # Structured error: {"error": {"code": ..., "message": ...}}
        if isinstance(error, dict):
            assert "POST" in error.get("message", "")
        else:
            assert "POST" in error

    def test_get_summarize_returns_405(self, handler):
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 405

    def test_get_compare_returns_405(self, handler):
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 405

    def test_get_extract_returns_405(self, handler):
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 405

    def test_get_search_returns_matching_org_documents(self, handler):
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/search", {"q": ["doc2"]}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert [hit["document_id"] for hit in body["results"]] == ["doc2"]
        assert body["total"] == 1
        assert body["results"][0]["filename"] == "doc2.txt"

    def test_get_search_accepts_query_param(self, handler):
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/search", {"query": ["text"]}, mock_http)
        assert _status(result) == 200
        assert _body(result)["total"] == 2

    def test_get_search_accepts_single_value_params(self, handler):
        """The live server passes each query parameter as one string."""
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/search", {"q": "doc2"}, mock_http)
        assert _status(result) == 200
        assert [hit["document_id"] for hit in _body(result)["results"]] == ["doc2"]

    def test_get_search_requires_a_query(self, handler):
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/search", {}, mock_http)
        assert _status(result) == 400

    def test_get_error_message_mentions_post(self, handler):
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/query", {}, mock_http)
        body = _body(result)
        error = body.get("error", {})
        if isinstance(error, dict):
            assert "POST" in error.get("message", "")
        else:
            assert "POST" in error

    def test_get_error_has_method_not_allowed_code(self, handler):
        mock_http = _make_handler()
        result = handler.handle("/api/v1/documents/query", {}, mock_http)
        body = _body(result)
        error = body.get("error", {})
        if isinstance(error, dict):
            assert error.get("code") == "METHOD_NOT_ALLOWED"
        else:
            assert body.get("code") == "METHOD_NOT_ALLOWED"


# =============================================================================
# POST /api/v1/documents/query Tests
# =============================================================================


class TestQueryDocuments:
    """Tests for POST /api/v1/documents/query endpoint."""

    def test_query_success(self, handler):
        mock_http = _make_handler({"question": "What are the payment terms?"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["query_id"] == "query_abc123"
        assert body["confidence"] == "high"
        assert "answer" in body

    def test_query_missing_body(self, handler):
        mock_http = _make_handler()
        result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 400
        assert "body" in _body(result).get("error", "").lower()

    def test_query_missing_question(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1"]})
        result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 400
        assert "question" in _body(result).get("error", "").lower()

    def test_query_empty_question(self, handler):
        mock_http = _make_handler({"question": ""})
        result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 400
        assert "question" in _body(result).get("error", "").lower()

    def test_query_whitespace_only_question(self, handler):
        mock_http = _make_handler({"question": "   "})
        result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 400
        assert "question" in _body(result).get("error", "").lower()

    def test_query_with_document_ids(self, handler):
        mock_http = _make_handler(
            {
                "question": "What are the terms?",
                "document_ids": ["doc1", "doc2"],
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        engine_instance.query.assert_called_once()
        call_kwargs = engine_instance.query.call_args[1]
        assert call_kwargs["document_ids"] == ["doc1", "doc2"]

    def test_query_with_workspace_id(self, handler):
        mock_http = _make_handler(
            {
                "question": "What is the scope?",
                "workspace_id": "ws_123",
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.query.call_args[1]
        assert call_kwargs["workspace_id"] == "ws_123"

    def test_query_with_conversation_id(self, handler):
        mock_http = _make_handler(
            {
                "question": "Follow-up question?",
                "conversation_id": "conv_456",
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.query.call_args[1]
        assert call_kwargs["conversation_id"] == "conv_456"

    def test_query_with_config(self, handler):
        mock_http = _make_handler(
            {
                "question": "What are the terms?",
                "config": {"max_chunks": 5, "include_quotes": False, "max_answer_length": 200},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        create_kwargs = MockEngine.create.call_args[1]
        config = create_kwargs["config"]
        assert config.max_chunks == 5
        assert config.include_quotes is False
        assert config.max_answer_length == 200

    def test_query_with_default_config(self, handler):
        mock_http = _make_handler({"question": "Simple question?"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        create_kwargs = MockEngine.create.call_args[1]
        config = create_kwargs["config"]
        assert config.max_chunks == 10
        assert config.include_quotes is True
        assert config.max_answer_length == 500

    def test_query_runtime_error(self, handler):
        mock_http = _make_handler({"question": "Will fail"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=RuntimeError("Engine init failed"))
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 500

    def test_query_value_error(self, handler):
        mock_http = _make_handler({"question": "Will fail"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=ValueError("Bad value"))
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 500

    def test_query_type_error(self, handler):
        mock_http = _make_handler({"question": "Will fail"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=TypeError("Type mismatch"))
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 500

    def test_query_os_error(self, handler):
        mock_http = _make_handler({"question": "Will fail"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=OSError("Disk error"))
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 500

    def test_query_key_error(self, handler):
        mock_http = _make_handler({"question": "Will fail"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=KeyError("missing_key"))
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 500

    def test_query_all_params(self, handler):
        mock_http = _make_handler(
            {
                "question": "Full query",
                "document_ids": ["d1", "d2"],
                "workspace_id": "ws_1",
                "conversation_id": "conv_1",
                "config": {"max_chunks": 20},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.query.call_args[1]
        assert call_kwargs["question"] == "Full query"
        assert call_kwargs["document_ids"] == ["d1", "d2"]
        assert call_kwargs["workspace_id"] == "ws_1"
        assert call_kwargs["conversation_id"] == "conv_1"

    def test_query_strips_whitespace(self, handler):
        mock_http = _make_handler({"question": "  What is this?  "})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.query.call_args[1]
        assert call_kwargs["question"] == "What is this?"


# =============================================================================
# POST /api/v1/documents/summarize Tests
# =============================================================================


class TestSummarizeDocuments:
    """Tests for POST /api/v1/documents/summarize endpoint."""

    def test_summarize_success(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1", "doc2"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert "answer" in body

    def test_summarize_missing_body(self, handler):
        mock_http = _make_handler()
        result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 400

    def test_summarize_missing_document_ids(self, handler):
        mock_http = _make_handler({"focus": "terms"})
        result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 400
        assert "document_ids" in _body(result).get("error", "").lower()

    def test_summarize_empty_document_ids(self, handler):
        mock_http = _make_handler({"document_ids": []})
        result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 400

    def test_summarize_with_focus(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "focus": "financial terms",
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.summarize_documents.return_value = MockQueryResult(
                {
                    "query_id": "sum_1",
                    "answer": "Summary.",
                    "confidence": "high",
                    "citations": [],
                }
            )
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.summarize_documents.call_args[1]
        assert call_kwargs["focus"] == "financial terms"
        assert call_kwargs["document_ids"] == ["doc1"]

    def test_summarize_no_focus(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.summarize_documents.return_value = MockQueryResult(
                {
                    "query_id": "sum_2",
                    "answer": "Summary.",
                    "confidence": "medium",
                    "citations": [],
                }
            )
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.summarize_documents.call_args[1]
        assert call_kwargs["focus"] is None

    def test_summarize_with_config(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "config": {"max_chunks": 5, "include_quotes": False},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.summarize_documents.return_value = MockQueryResult(
                {
                    "query_id": "sum_3",
                    "answer": "Summary.",
                    "confidence": "high",
                    "citations": [],
                }
            )
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 200
        create_kwargs = MockEngine.create.call_args[1]
        config = create_kwargs["config"]
        assert config.max_chunks == 5
        assert config.include_quotes is False

    def test_summarize_config_filters_unknown_keys(self, handler):
        """Config dict should only pass known QueryConfig fields."""
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "config": {"max_chunks": 3, "unknown_field": "ignored"},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.summarize_documents.return_value = MockQueryResult(
                {
                    "query_id": "sum_4",
                    "answer": "Summary.",
                    "confidence": "high",
                    "citations": [],
                }
            )
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 200
        create_kwargs = MockEngine.create.call_args[1]
        config = create_kwargs["config"]
        assert config.max_chunks == 3
        assert not hasattr(config, "unknown_field")

    def test_summarize_runtime_error(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=RuntimeError("Engine failed"))
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 500

    def test_summarize_value_error(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=ValueError("Bad input"))
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 500

    def test_summarize_os_error(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=OSError("File error"))
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 500

    def test_summarize_multiple_documents(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1", "doc2", "doc3"],
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.summarize_documents.return_value = MockQueryResult(
                {
                    "query_id": "sum_5",
                    "answer": "Multi-doc summary.",
                    "confidence": "high",
                    "citations": [],
                }
            )
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.summarize_documents.call_args[1]
        assert len(call_kwargs["document_ids"]) == 3


# =============================================================================
# POST /api/v1/documents/compare Tests
# =============================================================================


class TestCompareDocuments:
    """Tests for POST /api/v1/documents/compare endpoint."""

    def test_compare_success(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1", "doc2"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert "answer" in body

    def test_compare_missing_body(self, handler):
        mock_http = _make_handler()
        result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 400

    def test_compare_missing_document_ids(self, handler):
        mock_http = _make_handler({"aspects": ["pricing"]})
        result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 400
        assert (
            "2" in _body(result).get("error", "")
            or "document_ids" in _body(result).get("error", "").lower()
        )

    def test_compare_single_document_id(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1"]})
        result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 400
        assert "2" in _body(result).get("error", "")

    def test_compare_empty_document_ids(self, handler):
        mock_http = _make_handler({"document_ids": []})
        result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 400

    def test_compare_with_aspects(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1", "doc2"],
                "aspects": ["pricing", "terms", "coverage"],
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.compare_documents.return_value = MockQueryResult(
                {
                    "query_id": "cmp_1",
                    "answer": "Comparison.",
                    "confidence": "high",
                    "citations": [],
                }
            )
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.compare_documents.call_args[1]
        assert call_kwargs["aspects"] == ["pricing", "terms", "coverage"]

    def test_compare_no_aspects(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1", "doc2"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.compare_documents.return_value = MockQueryResult(
                {
                    "query_id": "cmp_2",
                    "answer": "Comparison.",
                    "confidence": "medium",
                    "citations": [],
                }
            )
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.compare_documents.call_args[1]
        assert call_kwargs["aspects"] is None

    def test_compare_with_config(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1", "doc2"],
                "config": {"max_chunks": 15},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.compare_documents.return_value = MockQueryResult(
                {
                    "query_id": "cmp_3",
                    "answer": "Comparison.",
                    "confidence": "high",
                    "citations": [],
                }
            )
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 200
        create_kwargs = MockEngine.create.call_args[1]
        assert create_kwargs["config"].max_chunks == 15

    def test_compare_exactly_two_documents(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1", "doc2"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 200

    def test_compare_many_documents(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1", "doc2", "doc3", "doc4", "doc5"],
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 200

    def test_compare_runtime_error(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1", "doc2"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=RuntimeError("Comparison failed"))
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 500

    def test_compare_key_error(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1", "doc2"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=KeyError("missing"))
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 500


# =============================================================================
# POST /api/v1/documents/extract Tests
# =============================================================================


class TestExtractInformation:
    """Tests for POST /api/v1/documents/extract endpoint."""

    def test_extract_success(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {
                    "parties": "Who are the parties?",
                },
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["document_ids"] == ["doc1"]
        assert "extractions" in body
        assert "parties" in body["extractions"]

    def test_extract_missing_body(self, handler):
        mock_http = _make_handler()
        result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 400

    def test_extract_missing_document_ids(self, handler):
        mock_http = _make_handler(
            {
                "fields": {"parties": "Who?"},
            }
        )
        result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 400
        assert "document_ids" in _body(result).get("error", "").lower()

    def test_extract_empty_document_ids(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": [],
                "fields": {"parties": "Who?"},
            }
        )
        result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 400

    def test_extract_missing_fields(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
            }
        )
        result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 400
        assert "fields" in _body(result).get("error", "").lower()

    def test_extract_empty_fields(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {},
            }
        )
        result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 400

    def test_extract_multiple_fields(self, handler):
        fields = {
            "parties": "Who are the parties?",
            "effective_date": "What is the effective date?",
            "term": "What is the term?",
            "payment_terms": "What are the payment terms?",
        }
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": fields,
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            extract_results = {
                f: MockQueryResult(
                    {"answer": f"Answer for {f}", "confidence": "high", "citations": []}
                )
                for f in fields
            }
            engine_instance.extract_information.return_value = extract_results
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert len(body["extractions"]) == 4
        for field_name in fields:
            assert field_name in body["extractions"]

    def test_extract_passes_fields_as_template(self, handler):
        fields = {"parties": "Who?", "date": "When?"}
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": fields,
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.extract_information.return_value = {
                "parties": MockQueryResult(
                    {"answer": "A and B", "confidence": "high", "citations": []}
                ),
                "date": MockQueryResult(
                    {"answer": "Jan 1", "confidence": "medium", "citations": []}
                ),
            }
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 200
        call_kwargs = engine_instance.extract_information.call_args[1]
        assert call_kwargs["extraction_template"] == fields
        assert call_kwargs["document_ids"] == ["doc1"]

    def test_extract_with_config(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {"parties": "Who?"},
                "config": {"max_chunks": 8},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.extract_information.return_value = {
                "parties": MockQueryResult({"answer": "A", "confidence": "high", "citations": []}),
            }
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 200
        create_kwargs = MockEngine.create.call_args[1]
        assert create_kwargs["config"].max_chunks == 8

    def test_extract_runtime_error(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {"parties": "Who?"},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=RuntimeError("Extract failed"))
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 500

    def test_extract_value_error(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {"parties": "Who?"},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=ValueError("Invalid"))
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 500

    def test_extract_type_error(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {"parties": "Who?"},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=TypeError("Type issue"))
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 500

    def test_extract_response_includes_document_ids(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1", "doc2"],
                "fields": {"parties": "Who?"},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.extract_information.return_value = {
                "parties": MockQueryResult({"answer": "A", "confidence": "high", "citations": []}),
            }
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["document_ids"] == ["doc1", "doc2"]


# =============================================================================
# POST Routing Tests
# =============================================================================


class TestHandlePostRouting:
    """Tests for POST request routing to correct handler methods."""

    def test_post_routes_to_query(self, handler):
        mock_http = _make_handler({"question": "What?"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200

    def test_post_routes_to_summarize(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 200

    def test_post_routes_to_compare(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1", "doc2"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 200

    def test_post_routes_to_extract(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {"parties": "Who?"},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 200

    def test_post_unknown_path_returns_none(self, handler):
        mock_http = _make_handler({"question": "What?"})
        result = handler.handle_post("/api/v1/documents/unknown", {}, mock_http)
        assert result is None

    def test_post_routes_to_search(self, handler):
        mock_http = _make_handler({"query": "doc1", "limit": 5})
        result = handler.handle_post("/api/v1/documents/search", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert [hit["document_id"] for hit in body["results"]] == ["doc1"]
        assert body["limit"] == 5

    def test_post_unknown_route_returns_none(self, handler):
        mock_http = _make_handler({"question": "What?"})
        assert handler.handle_post("/api/v1/documents/unknown", {}, mock_http) is None


# =============================================================================
# Security Tests
# =============================================================================


class TestSecurity:
    """Tests for security-related behaviors."""

    def test_path_traversal_in_document_ids(self, handler):
        """Path traversal in document_ids should not cause issues."""
        mock_http = _make_handler(
            {
                "question": "What?",
                "document_ids": ["../../../etc/passwd", "doc1"],
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        # An id that is not a stored document of the caller's org is not found
        assert _status(result) == 404
        MockEngine.create.assert_not_called()

    def test_script_injection_in_question(self, handler):
        """Script injection in question should be passed through safely."""
        mock_http = _make_handler(
            {
                "question": "<script>alert('xss')</script>",
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200

    def test_sql_injection_in_question(self, handler):
        """SQL injection attempt in question should not cause issues."""
        mock_http = _make_handler(
            {
                "question": "'; DROP TABLE documents; --",
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200

    def test_long_question(self, handler):
        """Very long question should be accepted (engine handles limits)."""
        long_question = "A" * 10000
        mock_http = _make_handler({"question": long_question})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200

    def test_unicode_question(self, handler):
        """Unicode in question should work."""
        mock_http = _make_handler(
            {
                "question": "What about the contract terms?",
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200

    def test_null_bytes_in_document_ids(self, handler):
        """Null bytes in document IDs should not crash."""
        mock_http = _make_handler(
            {
                "question": "What?",
                "document_ids": ["doc\x001", "doc2"],
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 404
        MockEngine.create.assert_not_called()

    def test_error_response_sanitized(self, handler):
        """Error responses should use safe_error_message, not expose internals."""
        mock_http = _make_handler({"question": "Will fail"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            MockEngine.create = AsyncMock(side_effect=RuntimeError("/var/secrets/api_key leaked"))
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 500
        body = _body(result)
        error_msg = body.get("error", "")
        # Should NOT contain the internal path
        assert "/var/secrets" not in error_msg

    def test_special_chars_in_field_names(self, handler):
        """Special characters in extraction field names should not crash."""
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {
                    "field<script>": "Question?",
                    "field; DROP TABLE": "Another question?",
                },
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.extract_information.return_value = {
                "field<script>": MockQueryResult(
                    {"answer": "A", "confidence": "high", "citations": []}
                ),
                "field; DROP TABLE": MockQueryResult(
                    {"answer": "B", "confidence": "high", "citations": []}
                ),
            }
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 200


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_query_with_none_document_ids(self, handler):
        """Explicitly passing None for optional fields."""
        mock_http = _make_handler(
            {
                "question": "What?",
                "document_ids": None,
                "workspace_id": None,
                "conversation_id": None,
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200

    def test_query_with_empty_config(self, handler):
        mock_http = _make_handler(
            {
                "question": "What?",
                "config": {},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        # Default config values should be used
        create_kwargs = MockEngine.create.call_args[1]
        config = create_kwargs["config"]
        assert config.max_chunks == 10

    def test_query_without_config_key(self, handler):
        """When 'config' key is absent, defaults should be used."""
        mock_http = _make_handler({"question": "What?"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200

    def test_summarize_single_document(self, handler):
        mock_http = _make_handler({"document_ids": ["doc1"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            MockQueryEngine,
        ):
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 200

    def test_compare_with_empty_aspects_list(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1", "doc2"],
                "aspects": [],
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.compare_documents.return_value = MockQueryResult(
                {
                    "query_id": "cmp_empty",
                    "answer": "Comparison.",
                    "confidence": "high",
                    "citations": [],
                }
            )
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 200

    def test_extract_single_field(self, handler):
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {"single": "One field only?"},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.extract_information.return_value = {
                "single": MockQueryResult({"answer": "One", "confidence": "high", "citations": []}),
            }
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert len(body["extractions"]) == 1

    def test_extract_many_fields(self, handler):
        """Extract with many fields."""
        fields = {f"field_{i}": f"Question {i}?" for i in range(20)}
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": fields,
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            extract_results = {
                f: MockQueryResult({"answer": f"Answer {f}", "confidence": "high", "citations": []})
                for f in fields
            }
            engine_instance.extract_information.return_value = extract_results
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert len(body["extractions"]) == 20

    def test_handler_preserves_context(self):
        """Handler should preserve the server context."""
        ctx = {"storage": MagicMock(), "user_store": MagicMock()}
        h = DocumentQueryHandler(server_context=ctx)
        assert h.ctx is ctx

    def test_query_error_during_engine_query(self, handler):
        """Error during engine.query (not engine.create)."""
        mock_http = _make_handler({"question": "Will fail mid-query"})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.side_effect = RuntimeError("Query processing failed")
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 500

    def test_summarize_error_during_summarize(self, handler):
        """Error during engine.summarize_documents."""
        mock_http = _make_handler({"document_ids": ["doc1"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.summarize_documents.side_effect = ValueError("Summarize failed")
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/summarize", {}, mock_http)
        assert _status(result) == 500

    def test_compare_error_during_compare(self, handler):
        """Error during engine.compare_documents."""
        mock_http = _make_handler({"document_ids": ["doc1", "doc2"]})
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.compare_documents.side_effect = KeyError("missing_field")
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/compare", {}, mock_http)
        assert _status(result) == 500

    def test_extract_error_during_extract(self, handler):
        """Error during engine.extract_information."""
        mock_http = _make_handler(
            {
                "document_ids": ["doc1"],
                "fields": {"parties": "Who?"},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.extract_information.side_effect = TypeError("Bad extract")
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/extract", {}, mock_http)
        assert _status(result) == 500

    def test_query_config_partial_override(self, handler):
        """Config with only some fields overridden uses defaults for the rest."""
        mock_http = _make_handler(
            {
                "question": "What?",
                "config": {"max_chunks": 3},
            }
        )
        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
        ) as MockEngine:
            engine_instance = AsyncMock()
            engine_instance.query.return_value = MockQueryResult()
            MockEngine.create = AsyncMock(return_value=engine_instance)
            result = handler.handle_post("/api/v1/documents/query", {}, mock_http)
        assert _status(result) == 200
        create_kwargs = MockEngine.create.call_args[1]
        config = create_kwargs["config"]
        assert config.max_chunks == 3
        assert config.include_quotes is True  # default
        assert config.max_answer_length == 500  # default
