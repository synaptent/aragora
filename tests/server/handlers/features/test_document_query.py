"""Tests for Document Query Handler."""

import sys
import types as _types_mod

# Pre-stub Slack modules to prevent import chain failures
_SLACK_ATTRS = [
    "SlackHandler",
    "get_slack_handler",
    "get_slack_integration",
    "get_workspace_store",
    "resolve_workspace",
    "create_tracked_task",
    "_validate_slack_url",
    "SLACK_SIGNING_SECRET",
    "SLACK_BOT_TOKEN",
    "SLACK_WEBHOOK_URL",
    "SLACK_ALLOWED_DOMAINS",
    "SignatureVerifierMixin",
    "CommandsMixin",
    "EventsMixin",
    "init_slack_handler",
]
for _mod_name in (
    "aragora.server.handlers.social.slack.handler",
    "aragora.server.handlers.social.slack",
    "aragora.server.handlers.social._slack_impl",
):
    if _mod_name not in sys.modules:
        _m = _types_mod.ModuleType(_mod_name)
        for _a in _SLACK_ATTRS:
            setattr(_m, _a, None)
        sys.modules[_mod_name] = _m

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.server.handlers.features.document_query import DocumentQueryHandler
from aragora.tenancy.record_scope import OrgScope

SCOPE = OrgScope(org_id="test-org-001", user_id="test-user-001", role="member")


@pytest.fixture
def handler():
    """Create handler instance."""
    return DocumentQueryHandler({})


@pytest.fixture
def owned_handler():
    """Handler whose document store holds the caller org's doc1."""
    store = MagicMock()
    store.get.side_effect = lambda doc_id: (
        MagicMock(id=doc_id, org_id=SCOPE.org_id, text="t", filename="f.md")
        if doc_id == "doc1"
        else None
    )
    return DocumentQueryHandler({"document_store": store})


class TestDocumentQueryHandler:
    """Tests for DocumentQueryHandler class."""

    def test_handler_creation(self, handler):
        """Test creating handler instance."""
        assert handler is not None

    def test_handler_routes(self):
        """Test that handler has route definitions."""
        assert hasattr(DocumentQueryHandler, "ROUTES")
        routes = DocumentQueryHandler.ROUTES
        assert "/api/v1/documents/query" in routes
        assert "/api/v1/documents/summarize" in routes
        assert "/api/v1/documents/compare" in routes
        assert "/api/v1/documents/extract" in routes

    def test_can_handle_document_routes(self, handler):
        """Test can_handle for document routes."""
        assert handler.can_handle("/api/v1/documents/query") is True
        assert handler.can_handle("/api/v1/documents/summarize") is True
        assert handler.can_handle("/api/v1/documents/compare") is True
        assert handler.can_handle("/api/v1/documents/extract") is True

    def test_can_handle_invalid_routes(self, handler):
        """Test can_handle rejects invalid routes."""
        assert handler.can_handle("/api/v1/files/query") is False
        assert handler.can_handle("/api/v1/invalid/route") is False


class TestDocumentQueryGET:
    """Tests for GET method handling."""

    def test_get_returns_method_not_allowed(self, handler):
        """Test GET requests return 405."""
        mock_handler = MagicMock()

        result = handler.handle("/api/v1/documents/query", {}, mock_handler)
        assert result.status_code == 405


class TestDocumentQuery:
    """Tests for document query endpoint."""

    def test_query_missing_body(self, handler):
        """Test query requires request body."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body", return_value=None),
        ):
            result = handler._query_documents(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_query_missing_question(self, handler):
        """Test query requires question field."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body", return_value={"document_ids": []}),
        ):
            result = handler._query_documents(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_query_empty_question(self, handler):
        """Test query rejects empty question."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body", return_value={"question": "  "}),
        ):
            result = handler._query_documents(mock_handler, SCOPE)
            assert result.status_code == 400


class TestDocumentSummarize:
    """Tests for document summarize endpoint."""

    def test_summarize_missing_body(self, handler):
        """Test summarize requires request body."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body", return_value=None),
        ):
            result = handler._summarize_documents(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_summarize_missing_document_ids(self, handler):
        """Test summarize requires document_ids."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body", return_value={"focus": "financial"}),
        ):
            result = handler._summarize_documents(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_summarize_empty_document_ids(self, handler):
        """Test summarize rejects empty document_ids."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body", return_value={"document_ids": []}),
        ):
            result = handler._summarize_documents(mock_handler, SCOPE)
            assert result.status_code == 400


class TestDocumentCompare:
    """Tests for document compare endpoint."""

    def test_compare_missing_body(self, handler):
        """Test compare requires request body."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body", return_value=None),
        ):
            result = handler._compare_documents(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_compare_requires_two_documents(self, owned_handler):
        """Test compare requires at least 2 documents."""
        mock_handler = MagicMock()

        with (
            patch.object(owned_handler, "read_json_body", return_value={"document_ids": ["doc1"]}),
        ):
            result = owned_handler._compare_documents(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_compare_checks_ownership_before_count(self, handler):
        """A single unknown id answers 404, not the count error."""
        with patch.object(handler, "read_json_body", return_value={"document_ids": ["doc1"]}):
            result = handler._compare_documents(MagicMock(), SCOPE)
        assert result.status_code == 404


class TestDocumentExtract:
    """Tests for document extract endpoint."""

    def test_extract_missing_body(self, handler):
        """Test extract requires request body."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body", return_value=None),
        ):
            result = handler._extract_information(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_extract_missing_document_ids(self, handler):
        """Test extract requires document_ids."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body", return_value={"fields": {"parties": "Who?"}}),
        ):
            result = handler._extract_information(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_extract_missing_fields(self, owned_handler):
        """Test extract requires fields."""
        mock_handler = MagicMock()

        with (
            patch.object(owned_handler, "read_json_body", return_value={"document_ids": ["doc1"]}),
        ):
            result = owned_handler._extract_information(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_extract_empty_fields(self, owned_handler):
        """Test extract rejects empty fields."""
        mock_handler = MagicMock()

        with (
            patch.object(
                owned_handler,
                "read_json_body",
                return_value={"document_ids": ["doc1"], "fields": {}},
            ),
        ):
            result = owned_handler._extract_information(mock_handler, SCOPE)
            assert result.status_code == 400


class TestDocumentQueryAsync:
    """Tests for async query execution."""

    @pytest.mark.asyncio
    async def test_run_query(self, handler):
        """Test async query execution."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"answer": "Test answer"}

        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            create=True,
        ) as MockEngine:
            mock_engine = MagicMock()
            mock_engine.query = AsyncMock(return_value=mock_result)
            MockEngine.create = AsyncMock(return_value=mock_engine)

            result = await handler._run_query(
                question="Test question?",
                document_ids=None,
                workspace_id=None,
                conversation_id=None,
                config_dict={},
            )
            assert result == {"answer": "Test answer"}

    @pytest.mark.asyncio
    async def test_run_summarize(self, handler):
        """Test async summarize execution."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"summary": "Test summary"}

        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            create=True,
        ) as MockEngine:
            mock_engine = MagicMock()
            mock_engine.summarize_documents = AsyncMock(return_value=mock_result)
            MockEngine.create = AsyncMock(return_value=mock_engine)

            result = await handler._run_summarize(
                document_ids=["doc1", "doc2"],
                focus="financial terms",
                config_dict={},
            )
            assert result == {"summary": "Test summary"}

    @pytest.mark.asyncio
    async def test_run_compare(self, handler):
        """Test async compare execution."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"comparison": "Test comparison"}

        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            create=True,
        ) as MockEngine:
            mock_engine = MagicMock()
            mock_engine.compare_documents = AsyncMock(return_value=mock_result)
            MockEngine.create = AsyncMock(return_value=mock_engine)

            result = await handler._run_compare(
                document_ids=["doc1", "doc2"],
                aspects=["pricing", "terms"],
                config_dict={},
            )
            assert result == {"comparison": "Test comparison"}

    @pytest.mark.asyncio
    async def test_run_extract(self, handler):
        """Test async extract execution."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"answer": "Party A and B"}

        with patch(
            "aragora.server.handlers.features.document_query.DocumentQueryEngine",
            create=True,
        ) as MockEngine:
            mock_engine = MagicMock()
            mock_engine.extract_information = AsyncMock(return_value={"parties": mock_result})
            MockEngine.create = AsyncMock(return_value=mock_engine)

            result = await handler._run_extract(
                document_ids=["doc1"],
                fields={"parties": "Who are the parties?"},
                config_dict={},
            )
            assert "extractions" in result
            assert "parties" in result["extractions"]
