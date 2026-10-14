"""Tests for FactsOperationsMixin (aragora/server/handlers/knowledge_base/facts.py).

Covers all routes and behavior of the facts mixin:
- GET  /api/v1/knowledge/facts           - List facts with filtering
- GET  /api/v1/knowledge/facts/:id       - Get specific fact
- POST /api/v1/knowledge/facts           - Create a new fact
- PUT  /api/v1/knowledge/facts/:id       - Update a fact
- DELETE /api/v1/knowledge/facts/:id     - Delete a fact
- POST /api/v1/knowledge/facts/:id/verify       - Verify fact with agents
- GET  /api/v1/knowledge/facts/:id/contradictions - Get contradicting facts
- GET  /api/v1/knowledge/facts/:id/relations      - Get fact relations
- POST /api/v1/knowledge/facts/:id/relations      - Add relation from fact
- POST /api/v1/knowledge/facts/relations           - Bulk add relation
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.knowledge.types import (
    Fact,
    FactFilters,
    FactRelation,
    FactRelationType,
    ValidationStatus,
    VerificationResult,
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
    superseded_by: str | None = None,
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
        superseded_by=superseded_by,
    )


def _make_relation(
    relation_id: str = "rel-001",
    source_fact_id: str = "fact-001",
    target_fact_id: str = "fact-002",
    relation_type: FactRelationType = FactRelationType.SUPPORTS,
    confidence: float = 0.8,
) -> FactRelation:
    """Create a FactRelation instance for testing."""
    return FactRelation(
        id=relation_id,
        source_fact_id=source_fact_id,
        target_fact_id=target_fact_id,
        relation_type=relation_type,
        confidence=confidence,
        created_by="test-user",
        metadata={},
        created_at=datetime(2025, 1, 1, 12, 0, 0),
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
    store.add_relation.return_value = _make_relation()
    store.get_stats.return_value = {"total_facts": 2, "workspaces": 1}

    return store


@pytest.fixture
def mock_query_engine():
    """Create a mock query engine."""
    engine = MagicMock()
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


@pytest.fixture
def put_handler_factory():
    """Factory for creating PUT HTTP handlers with body."""

    def _create(body: dict) -> MockHTTPHandler:
        return MockHTTPHandler(body=body, method="PUT")

    return _create


@pytest.fixture
def delete_handler():
    """Create a mock DELETE HTTP handler."""
    return MockHTTPHandler(method="DELETE")


# ============================================================================
# Tests: GET /api/v1/knowledge/facts (list facts)
# ============================================================================


class TestListFacts:
    """Test GET /api/v1/knowledge/facts."""

    def test_list_facts_returns_200(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        assert _status(result) == 200

    def test_list_facts_returns_facts_array(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        body = _body(result)
        assert "facts" in body
        assert isinstance(body["facts"], list)
        assert len(body["facts"]) == 2

    def test_list_facts_returns_total_count(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        body = _body(result)
        assert body["total"] == 2

    def test_list_facts_returns_pagination_fields(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        body = _body(result)
        assert "limit" in body
        assert "offset" in body

    def test_list_facts_default_limit_50(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        body = _body(result)
        assert body["limit"] == 50

    def test_list_facts_default_offset_0(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        body = _body(result)
        assert body["offset"] == 0

    def test_list_facts_with_workspace_filter(self, handler, get_handler, mock_fact_store):
        params = {"workspace_id": ["my-workspace"]}
        handler.handle("/api/v1/knowledge/facts", params, get_handler)
        filters = mock_fact_store.list_facts.call_args[0][0]
        assert filters.workspace_id == "my-workspace"

    def test_list_facts_with_topic_filter(self, handler, get_handler, mock_fact_store):
        params = {"topic": ["physics"]}
        handler.handle("/api/v1/knowledge/facts", params, get_handler)
        filters = mock_fact_store.list_facts.call_args[0][0]
        assert filters.topics == ["physics"]

    def test_list_facts_with_min_confidence_filter(self, handler, get_handler, mock_fact_store):
        params = {"min_confidence": ["0.7"]}
        handler.handle("/api/v1/knowledge/facts", params, get_handler)
        filters = mock_fact_store.list_facts.call_args[0][0]
        assert filters.min_confidence == 0.7

    def test_list_facts_with_status_filter(self, handler, get_handler, mock_fact_store):
        params = {"status": ["contested"]}
        handler.handle("/api/v1/knowledge/facts", params, get_handler)
        filters = mock_fact_store.list_facts.call_args[0][0]
        assert filters.validation_status == ValidationStatus.CONTESTED

    def test_list_facts_with_include_superseded(self, handler, get_handler, mock_fact_store):
        params = {"include_superseded": ["true"]}
        handler.handle("/api/v1/knowledge/facts", params, get_handler)
        filters = mock_fact_store.list_facts.call_args[0][0]
        assert filters.include_superseded is True

    def test_list_facts_with_custom_limit(self, handler, get_handler):
        params = {"limit": ["10"]}
        result = handler.handle("/api/v1/knowledge/facts", params, get_handler)
        body = _body(result)
        assert body["limit"] == 10

    def test_list_facts_with_custom_offset(self, handler, get_handler):
        params = {"offset": ["20"]}
        result = handler.handle("/api/v1/knowledge/facts", params, get_handler)
        body = _body(result)
        assert body["offset"] == 20

    def test_list_facts_limit_clamped_to_max_200(self, handler, get_handler):
        params = {"limit": ["500"]}
        result = handler.handle("/api/v1/knowledge/facts", params, get_handler)
        body = _body(result)
        assert body["limit"] <= 200

    def test_list_facts_limit_clamped_to_min_1(self, handler, get_handler):
        params = {"limit": ["0"]}
        result = handler.handle("/api/v1/knowledge/facts", params, get_handler)
        body = _body(result)
        assert body["limit"] >= 1

    def test_list_facts_empty_result(self, handler, get_handler, mock_fact_store):
        mock_fact_store.list_facts.return_value = []
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        body = _body(result)
        assert body["facts"] == []
        assert body["total"] == 0

    def test_list_facts_calls_store_once(self, handler, get_handler, mock_fact_store):
        handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        mock_fact_store.list_facts.assert_called_once()

    def test_list_facts_fact_serialization(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        body = _body(result)
        fact = body["facts"][0]
        assert "id" in fact
        assert "statement" in fact
        assert "confidence" in fact

    def test_list_facts_via_sdk_alias(self, handler, get_handler):
        """The SDK uses /api/v1/facts without the /knowledge/ prefix."""
        result = handler.handle("/api/v1/facts", {}, get_handler)
        assert _status(result) == 200
        body = _body(result)
        assert "facts" in body


# ============================================================================
# Tests: GET /api/v1/knowledge/facts/:id (get fact)
# ============================================================================


class TestGetFact:
    """Test GET /api/v1/knowledge/facts/:id."""

    def test_get_fact_returns_200(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, get_handler)
        assert _status(result) == 200

    def test_get_fact_returns_fact_data(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, get_handler)
        body = _body(result)
        assert body["id"] == "fact-001"
        assert body["statement"] == "The sky is blue"

    def test_get_fact_not_found_returns_404(self, handler, get_handler, mock_fact_store):
        mock_fact_store.get_fact.return_value = None
        result = handler.handle("/api/v1/knowledge/facts/nonexistent", {}, get_handler)
        assert _status(result) == 404

    def test_get_fact_not_found_error_message(self, handler, get_handler, mock_fact_store):
        mock_fact_store.get_fact.return_value = None
        result = handler.handle("/api/v1/knowledge/facts/bad-id", {}, get_handler)
        body = _body(result)
        assert "error" in body or "message" in body

    def test_get_fact_calls_store_with_id(self, handler, get_handler, mock_fact_store):
        handler.handle("/api/v1/knowledge/facts/fact-xyz", {}, get_handler)
        mock_fact_store.get_fact.assert_called_with("fact-xyz", org_id="test-org-001")

    def test_get_fact_includes_all_fields(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, get_handler)
        body = _body(result)
        expected_keys = {
            "id",
            "statement",
            "confidence",
            "workspace_id",
            "validation_status",
            "topics",
        }
        assert expected_keys.issubset(set(body.keys()))

    def test_get_fact_via_sdk_alias(self, handler, get_handler):
        """SDK alias: /api/v1/facts/:id"""
        result = handler.handle("/api/v1/facts/fact-001", {}, get_handler)
        assert _status(result) == 200


# ============================================================================
# Tests: POST /api/v1/knowledge/facts (create fact)
# ============================================================================


class TestCreateFact:
    """Test POST /api/v1/knowledge/facts."""

    def test_create_fact_returns_201(self, handler, post_handler_factory):
        http = post_handler_factory({"statement": "New fact"})
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 201

    def test_create_fact_returns_fact_data(self, handler, post_handler_factory):
        http = post_handler_factory({"statement": "New fact"})
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        body = _body(result)
        assert "id" in body

    def test_create_fact_calls_store_add_fact(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory({"statement": "Testing"})
        handler.handle("/api/v1/knowledge/facts", {}, http)
        mock_fact_store.add_fact.assert_called_once()

    def test_create_fact_passes_statement(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory({"statement": "Earth is round"})
        handler.handle("/api/v1/knowledge/facts", {}, http)
        call_kwargs = mock_fact_store.add_fact.call_args
        assert (
            call_kwargs.kwargs.get("statement")
            or call_kwargs[1].get("statement") == "Earth is round"
        )

    def test_create_fact_passes_workspace_id(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory({"statement": "Test", "workspace_id": "ws-1"})
        handler.handle("/api/v1/knowledge/facts", {}, http)
        call_kwargs = mock_fact_store.add_fact.call_args
        assert (
            call_kwargs.kwargs.get("workspace_id") or call_kwargs[1].get("workspace_id") == "ws-1"
        )

    def test_create_fact_default_workspace(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory({"statement": "Test"})
        handler.handle("/api/v1/knowledge/facts", {}, http)
        call_kwargs = mock_fact_store.add_fact.call_args[1]
        assert call_kwargs.get("workspace_id") == "default"

    def test_create_fact_passes_evidence_ids(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory({"statement": "Test", "evidence_ids": ["e1", "e2"]})
        handler.handle("/api/v1/knowledge/facts", {}, http)
        call_kwargs = mock_fact_store.add_fact.call_args[1]
        assert call_kwargs.get("evidence_ids") == ["e1", "e2"]

    def test_create_fact_passes_confidence(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory({"statement": "Test", "confidence": 0.95})
        handler.handle("/api/v1/knowledge/facts", {}, http)
        call_kwargs = mock_fact_store.add_fact.call_args[1]
        assert call_kwargs.get("confidence") == 0.95

    def test_create_fact_passes_topics(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory({"statement": "Test", "topics": ["ai", "ml"]})
        handler.handle("/api/v1/knowledge/facts", {}, http)
        call_kwargs = mock_fact_store.add_fact.call_args[1]
        assert call_kwargs.get("topics") == ["ai", "ml"]

    def test_create_fact_passes_metadata(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory({"statement": "Test", "metadata": {"key": "val"}})
        handler.handle("/api/v1/knowledge/facts", {}, http)
        call_kwargs = mock_fact_store.add_fact.call_args[1]
        assert call_kwargs.get("metadata") == {"key": "val"}

    def test_create_fact_missing_statement_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory({})
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 400

    def test_create_fact_empty_statement_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory({"statement": ""})
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 400

    def test_create_fact_whitespace_statement_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory({"statement": "   "})
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 400

    def test_create_fact_no_body_returns_400(self, handler):
        http = MockHTTPHandler(method="POST")  # No body at all
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 400

    def test_create_fact_invalid_json_returns_400(self, handler):
        http = MockHTTPHandler(method="POST")
        http.rfile = io.BytesIO(b"not json")
        http.headers["Content-Length"] = "8"
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 400


# ============================================================================
# Tests: PUT /api/v1/knowledge/facts/:id (update fact)
# ============================================================================


class TestUpdateFact:
    """Test PUT /api/v1/knowledge/facts/:id."""

    def test_update_fact_returns_200(self, handler, put_handler_factory):
        http = put_handler_factory({"confidence": 0.95})
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        assert _status(result) == 200

    def test_update_fact_returns_updated_fact(self, handler, put_handler_factory):
        http = put_handler_factory({"confidence": 0.95})
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        body = _body(result)
        assert "id" in body

    def test_update_fact_calls_store(self, handler, put_handler_factory, mock_fact_store):
        http = put_handler_factory({"confidence": 0.95})
        handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        mock_fact_store.update_fact.assert_called_once()

    def test_update_fact_passes_confidence(self, handler, put_handler_factory, mock_fact_store):
        http = put_handler_factory({"confidence": 0.99})
        handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        call_args = mock_fact_store.update_fact.call_args
        assert call_args[1].get("confidence") == 0.99

    def test_update_fact_passes_validation_status(
        self, handler, put_handler_factory, mock_fact_store
    ):
        http = put_handler_factory({"validation_status": "contested"})
        handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        call_args = mock_fact_store.update_fact.call_args
        assert call_args[1].get("validation_status") == ValidationStatus.CONTESTED

    def test_update_fact_passes_evidence_ids(self, handler, put_handler_factory, mock_fact_store):
        http = put_handler_factory({"evidence_ids": ["ev-1", "ev-2"]})
        handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        call_args = mock_fact_store.update_fact.call_args
        assert call_args[1].get("evidence_ids") == ["ev-1", "ev-2"]

    def test_update_fact_passes_topics(self, handler, put_handler_factory, mock_fact_store):
        http = put_handler_factory({"topics": ["new-topic"]})
        handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        call_args = mock_fact_store.update_fact.call_args
        assert call_args[1].get("topics") == ["new-topic"]

    def test_update_fact_passes_metadata(self, handler, put_handler_factory, mock_fact_store):
        http = put_handler_factory({"metadata": {"source": "experiment"}})
        handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        call_args = mock_fact_store.update_fact.call_args
        assert call_args[1].get("metadata") == {"source": "experiment"}

    def test_update_fact_passes_superseded_by(self, handler, put_handler_factory, mock_fact_store):
        http = put_handler_factory({"superseded_by": "fact-099"})
        handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        call_args = mock_fact_store.update_fact.call_args
        assert call_args[1].get("superseded_by") == "fact-099"

    def test_update_fact_not_found_returns_404(self, handler, put_handler_factory, mock_fact_store):
        mock_fact_store.update_fact.return_value = None
        http = put_handler_factory({"confidence": 0.5})
        result = handler.handle("/api/v1/knowledge/facts/nonexistent", {}, http)
        assert _status(result) == 404

    def test_update_fact_no_body_returns_400(self, handler):
        http = MockHTTPHandler(method="PUT")
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        assert _status(result) == 400

    def test_update_fact_invalid_json_returns_400(self, handler):
        http = MockHTTPHandler(method="PUT")
        http.rfile = io.BytesIO(b"bad json!")
        http.headers["Content-Length"] = "9"
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        assert _status(result) == 400

    def test_update_fact_only_sends_provided_fields(
        self, handler, put_handler_factory, mock_fact_store
    ):
        """Only fields present in the body should be passed to update_fact."""
        http = put_handler_factory({"confidence": 0.5})
        handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        call_kwargs = mock_fact_store.update_fact.call_args[1]
        assert "confidence" in call_kwargs
        assert "topics" not in call_kwargs
        assert "metadata" not in call_kwargs


# ============================================================================
# Tests: DELETE /api/v1/knowledge/facts/:id (delete fact)
# ============================================================================


class TestDeleteFact:
    """Test DELETE /api/v1/knowledge/facts/:id."""

    def test_delete_fact_returns_200(self, handler, delete_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, delete_handler)
        assert _status(result) == 200

    def test_delete_fact_returns_deleted_true(self, handler, delete_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, delete_handler)
        body = _body(result)
        assert body["deleted"] is True

    def test_delete_fact_returns_fact_id(self, handler, delete_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, delete_handler)
        body = _body(result)
        assert body["fact_id"] == "fact-001"

    def test_delete_fact_not_found_returns_404(self, handler, delete_handler, mock_fact_store):
        mock_fact_store.delete_fact.return_value = False
        result = handler.handle("/api/v1/knowledge/facts/nonexistent", {}, delete_handler)
        assert _status(result) == 404

    def test_delete_fact_calls_store(self, handler, delete_handler, mock_fact_store):
        handler.handle("/api/v1/knowledge/facts/fact-001", {}, delete_handler)
        mock_fact_store.delete_fact.assert_called_once_with("fact-001", org_id="test-org-001")


# ============================================================================
# Tests: POST /api/v1/knowledge/facts/:id/verify (verify fact)
# ============================================================================


class TestVerifyFact:
    """Test POST /api/v1/knowledge/facts/:id/verify."""

    def test_verify_fact_not_found_returns_404(self, handler, mock_fact_store):
        mock_fact_store.get_fact.return_value = None
        http = MockHTTPHandler(method="POST", body={})
        result = handler.handle("/api/v1/knowledge/facts/bad-id/verify", {}, http)
        assert _status(result) == 404

    def test_verify_fact_queued_when_no_dataset_engine(
        self, handler, mock_fact_store, mock_query_engine
    ):
        """When query engine is not DatasetQueryEngine, fact is queued."""
        http = MockHTTPHandler(method="POST", body={})
        result = handler.handle("/api/v1/knowledge/facts/fact-001/verify", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "queued"
        assert body["fact_id"] == "fact-001"
        assert body["verified"] is None

    def test_verify_fact_queued_updates_metadata(self, handler, mock_fact_store, mock_query_engine):
        """When queued, the fact metadata should be updated with pending verification."""
        http = MockHTTPHandler(method="POST", body={})
        handler.handle("/api/v1/knowledge/facts/fact-001/verify", {}, http)
        # update_fact should be called with pending verification metadata
        mock_fact_store.update_fact.assert_called()
        call_kwargs = mock_fact_store.update_fact.call_args[1]
        assert call_kwargs["metadata"]["_pending_verification"] is True

    def test_verify_fact_with_dataset_engine_success(self, handler, mock_fact_store):
        """When a DatasetQueryEngine is available, verification proceeds."""
        from aragora.knowledge import DatasetQueryEngine

        mock_engine = MagicMock(spec=DatasetQueryEngine)
        verification_result = MagicMock()
        verification_result.to_dict.return_value = {
            "fact_id": "fact-001",
            "success": True,
            "new_status": "majority_agreed",
        }
        mock_engine.verify_fact = MagicMock(return_value=verification_result)

        handler._query_engine = mock_engine

        http = MockHTTPHandler(method="POST", body={})
        with patch(
            "aragora.server.http_utils.run_async",
            return_value=verification_result,
        ):
            result = handler.handle("/api/v1/knowledge/facts/fact-001/verify", {}, http)

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True

    def test_verify_fact_engine_error_returns_500(self, handler, mock_fact_store):
        """When verification raises an exception, return 500."""
        from aragora.knowledge import DatasetQueryEngine

        mock_engine = MagicMock(spec=DatasetQueryEngine)
        handler._query_engine = mock_engine

        http = MockHTTPHandler(method="POST", body={})
        with patch(
            "aragora.server.http_utils.run_async",
            side_effect=RuntimeError("Verification engine down"),
        ):
            result = handler.handle("/api/v1/knowledge/facts/fact-001/verify", {}, http)

        assert _status(result) == 500

    def test_verify_fact_engine_value_error_returns_500(self, handler, mock_fact_store):
        from aragora.knowledge import DatasetQueryEngine

        mock_engine = MagicMock(spec=DatasetQueryEngine)
        handler._query_engine = mock_engine

        http = MockHTTPHandler(method="POST", body={})
        with patch(
            "aragora.server.http_utils.run_async",
            side_effect=ValueError("Bad value"),
        ):
            result = handler.handle("/api/v1/knowledge/facts/fact-001/verify", {}, http)

        assert _status(result) == 500

    def test_verify_fact_engine_key_error_returns_500(self, handler, mock_fact_store):
        from aragora.knowledge import DatasetQueryEngine

        mock_engine = MagicMock(spec=DatasetQueryEngine)
        handler._query_engine = mock_engine

        http = MockHTTPHandler(method="POST", body={})
        with patch(
            "aragora.server.http_utils.run_async",
            side_effect=KeyError("missing"),
        ):
            result = handler.handle("/api/v1/knowledge/facts/fact-001/verify", {}, http)

        assert _status(result) == 500


# ============================================================================
# Tests: GET /api/v1/knowledge/facts/:id/contradictions
# ============================================================================


class TestGetContradictions:
    """Test GET /api/v1/knowledge/facts/:id/contradictions."""

    def test_contradictions_returns_200(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001/contradictions", {}, get_handler)
        assert _status(result) == 200

    def test_contradictions_returns_fact_id(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001/contradictions", {}, get_handler)
        body = _body(result)
        assert body["fact_id"] == "fact-001"

    def test_contradictions_returns_empty_list(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001/contradictions", {}, get_handler)
        body = _body(result)
        assert body["contradictions"] == []
        assert body["count"] == 0

    def test_contradictions_with_results(self, handler, get_handler, mock_fact_store):
        contra = _make_fact("fact-099", "The sky is green")
        mock_fact_store.get_contradictions.return_value = [contra]
        result = handler.handle("/api/v1/knowledge/facts/fact-001/contradictions", {}, get_handler)
        body = _body(result)
        assert body["count"] == 1
        assert body["contradictions"][0]["id"] == "fact-099"

    def test_contradictions_not_found_returns_404(self, handler, get_handler, mock_fact_store):
        mock_fact_store.get_fact.return_value = None
        result = handler.handle("/api/v1/knowledge/facts/bad-id/contradictions", {}, get_handler)
        assert _status(result) == 404

    def test_contradictions_calls_store_with_fact_id(self, handler, get_handler, mock_fact_store):
        handler.handle("/api/v1/knowledge/facts/fact-001/contradictions", {}, get_handler)
        mock_fact_store.get_contradictions.assert_called_once_with(
            "fact-001", org_id="test-org-001"
        )


# ============================================================================
# Tests: GET /api/v1/knowledge/facts/:id/relations
# ============================================================================


class TestGetRelations:
    """Test GET /api/v1/knowledge/facts/:id/relations."""

    def test_get_relations_returns_200(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, get_handler)
        assert _status(result) == 200

    def test_get_relations_returns_fact_id(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, get_handler)
        body = _body(result)
        assert body["fact_id"] == "fact-001"

    def test_get_relations_returns_empty_list(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, get_handler)
        body = _body(result)
        assert body["relations"] == []
        assert body["count"] == 0

    def test_get_relations_with_results(self, handler, get_handler, mock_fact_store):
        rel = _make_relation()
        mock_fact_store.get_relations.return_value = [rel]
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, get_handler)
        body = _body(result)
        assert body["count"] == 1
        assert body["relations"][0]["source_fact_id"] == "fact-001"

    def test_get_relations_not_found_returns_404(self, handler, get_handler, mock_fact_store):
        mock_fact_store.get_fact.return_value = None
        result = handler.handle("/api/v1/knowledge/facts/bad-id/relations", {}, get_handler)
        assert _status(result) == 404

    def test_get_relations_with_type_filter(self, handler, get_handler, mock_fact_store):
        params = {"type": ["supports"]}
        handler.handle("/api/v1/knowledge/facts/fact-001/relations", params, get_handler)
        call_kwargs = mock_fact_store.get_relations.call_args[1]
        assert call_kwargs["relation_type"] == FactRelationType.SUPPORTS

    def test_get_relations_with_as_source_false(self, handler, get_handler, mock_fact_store):
        params = {"as_source": ["false"]}
        handler.handle("/api/v1/knowledge/facts/fact-001/relations", params, get_handler)
        call_kwargs = mock_fact_store.get_relations.call_args[1]
        assert call_kwargs["as_source"] is False

    def test_get_relations_with_as_target_false(self, handler, get_handler, mock_fact_store):
        params = {"as_target": ["false"]}
        handler.handle("/api/v1/knowledge/facts/fact-001/relations", params, get_handler)
        call_kwargs = mock_fact_store.get_relations.call_args[1]
        assert call_kwargs["as_target"] is False

    def test_get_relations_defaults_as_source_true(self, handler, get_handler, mock_fact_store):
        handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, get_handler)
        call_kwargs = mock_fact_store.get_relations.call_args[1]
        assert call_kwargs["as_source"] is True

    def test_get_relations_defaults_as_target_true(self, handler, get_handler, mock_fact_store):
        handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, get_handler)
        call_kwargs = mock_fact_store.get_relations.call_args[1]
        assert call_kwargs["as_target"] is True


# ============================================================================
# Tests: POST /api/v1/knowledge/facts/:id/relations (add relation from fact)
# ============================================================================


class TestAddRelation:
    """Test POST /api/v1/knowledge/facts/:id/relations."""

    def test_add_relation_returns_201(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        assert _status(result) == 201

    def test_add_relation_returns_relation_data(
        self, handler, post_handler_factory, mock_fact_store
    ):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        body = _body(result)
        assert "source_fact_id" in body
        assert "target_fact_id" in body

    def test_add_relation_missing_target_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory({"relation_type": "supports"})
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        assert _status(result) == 400

    def test_add_relation_missing_relation_type_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory({"target_fact_id": "fact-002"})
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        assert _status(result) == 400

    def test_add_relation_invalid_relation_type_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "invalid_type",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        assert _status(result) == 400

    def test_add_relation_source_not_found_returns_404(
        self, handler, post_handler_factory, mock_fact_store
    ):
        mock_fact_store.get_fact.return_value = None
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/bad-source/relations", {}, http)
        assert _status(result) == 404

    def test_add_relation_target_not_found_returns_404(
        self, handler, post_handler_factory, mock_fact_store
    ):
        # Source exists, target does not
        source_fact = _make_fact("fact-001")
        mock_fact_store.get_fact.side_effect = (
            lambda fid, **_kw: source_fact if fid == "fact-001" else None
        )
        http = post_handler_factory(
            {
                "target_fact_id": "nonexistent",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        assert _status(result) == 404

    def test_add_relation_no_body_returns_400(self, handler):
        http = MockHTTPHandler(method="POST")
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        assert _status(result) == 400

    def test_add_relation_invalid_json_returns_400(self, handler):
        http = MockHTTPHandler(method="POST")
        http.rfile = io.BytesIO(b"{broken")
        http.headers["Content-Length"] = "7"
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        assert _status(result) == 400

    def test_add_relation_with_confidence(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
                "confidence": 0.9,
            }
        )
        handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        call_kwargs = mock_fact_store.add_relation.call_args[1]
        assert call_kwargs["confidence"] == 0.9

    def test_add_relation_with_created_by(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
                "created_by": "agent-claude",
            }
        )
        handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        call_kwargs = mock_fact_store.add_relation.call_args[1]
        assert call_kwargs["created_by"] == "agent-claude"

    def test_add_relation_with_metadata(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
                "metadata": {"reason": "test"},
            }
        )
        handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        call_kwargs = mock_fact_store.add_relation.call_args[1]
        assert call_kwargs["metadata"] == {"reason": "test"}

    def test_add_relation_all_valid_types(self, handler, post_handler_factory, mock_fact_store):
        """All FactRelationType values should be accepted."""
        for rt in FactRelationType:
            http = post_handler_factory(
                {
                    "target_fact_id": "fact-002",
                    "relation_type": rt.value,
                }
            )
            # Reset get_fact to return a fact
            mock_fact_store.get_fact.return_value = _make_fact()
            result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
            assert _status(result) == 201, f"Failed for relation type: {rt.value}"


# ============================================================================
# Tests: POST /api/v1/knowledge/facts/relations (bulk add relation)
# ============================================================================


class TestAddRelationBulk:
    """Test POST /api/v1/knowledge/facts/relations."""

    def test_bulk_add_relation_returns_201(self, handler, post_handler_factory):
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert _status(result) == 201

    def test_bulk_add_relation_returns_relation_data(self, handler, post_handler_factory):
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        body = _body(result)
        assert "source_fact_id" in body
        assert "target_fact_id" in body
        assert "relation_type" in body

    def test_bulk_add_relation_missing_source_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert _status(result) == 400

    def test_bulk_add_relation_missing_target_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert _status(result) == 400

    def test_bulk_add_relation_missing_relation_type_returns_400(
        self, handler, post_handler_factory
    ):
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert _status(result) == 400

    def test_bulk_add_relation_invalid_type_returns_400(self, handler, post_handler_factory):
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "bogus",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert _status(result) == 400

    def test_bulk_add_relation_no_body_returns_400(self, handler):
        http = MockHTTPHandler(method="POST")
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert _status(result) == 400

    def test_bulk_add_relation_invalid_json_returns_400(self, handler):
        http = MockHTTPHandler(method="POST")
        http.rfile = io.BytesIO(b"not-json")
        http.headers["Content-Length"] = "8"
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert _status(result) == 400

    def test_bulk_add_relation_with_confidence(
        self, handler, post_handler_factory, mock_fact_store
    ):
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "implies",
                "confidence": 0.75,
            }
        )
        handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        call_kwargs = mock_fact_store.add_relation.call_args[1]
        assert call_kwargs["confidence"] == 0.75

    def test_bulk_add_relation_with_created_by(
        self, handler, post_handler_factory, mock_fact_store
    ):
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "contradicts",
                "created_by": "user-123",
            }
        )
        handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        call_kwargs = mock_fact_store.add_relation.call_args[1]
        assert call_kwargs["created_by"] == "user-123"

    def test_bulk_add_relation_calls_store(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        mock_fact_store.add_relation.assert_called_once()
        call_kwargs = mock_fact_store.add_relation.call_args[1]
        assert call_kwargs["source_fact_id"] == "fact-001"
        assert call_kwargs["target_fact_id"] == "fact-002"
        assert call_kwargs["relation_type"] == FactRelationType.SUPPORTS


# ============================================================================
# Tests: Routing edge cases
# ============================================================================


class TestFactRouting:
    """Test routing through KnowledgeHandler to facts mixin methods."""

    def test_unknown_sub_route_returns_404(self, handler, get_handler):
        """Unknown sub-routes under facts should return 404."""
        result = handler.handle("/api/v1/knowledge/facts/fact-001/unknown", {}, get_handler)
        assert _status(result) == 404

    def test_post_to_facts_creates_fact(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory({"statement": "Test"})
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 201

    def test_get_to_facts_lists_facts(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        assert _status(result) == 200
        body = _body(result)
        assert "facts" in body

    def test_put_to_facts_id_updates(self, handler, put_handler_factory):
        http = put_handler_factory({"confidence": 0.5})
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        assert _status(result) == 200

    def test_delete_to_facts_id_deletes(self, handler, delete_handler, mock_fact_store):
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, delete_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True

    def test_get_contradictions_route_parsed(self, handler, get_handler, mock_fact_store):
        result = handler.handle("/api/v1/knowledge/facts/fact-001/contradictions", {}, get_handler)
        assert _status(result) == 200
        mock_fact_store.get_contradictions.assert_called_once()

    def test_get_relations_route_parsed(self, handler, get_handler, mock_fact_store):
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, get_handler)
        assert _status(result) == 200
        mock_fact_store.get_relations.assert_called_once()

    def test_post_relations_route_parsed(self, handler, post_handler_factory, mock_fact_store):
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        assert _status(result) == 201

    def test_post_verify_route_parsed(self, handler, mock_fact_store):
        http = MockHTTPHandler(method="POST", body={})
        result = handler.handle("/api/v1/knowledge/facts/fact-001/verify", {}, http)
        # Should return 200 (queued) since we use a simple query engine mock
        assert _status(result) == 200

    def test_sdk_facts_alias_normalization(self, handler, get_handler, mock_fact_store):
        """Test that /api/v1/facts/ is normalized to /api/v1/knowledge/facts/."""
        result = handler.handle("/api/v1/facts/fact-001", {}, get_handler)
        assert _status(result) == 200
        mock_fact_store.get_fact.assert_called_with("fact-001", org_id="test-org-001")


# ============================================================================
# Tests: Store error handling
# ============================================================================


class TestStoreErrorHandling:
    """Test that store errors are handled gracefully."""

    def test_list_facts_store_raises(self, handler, get_handler, mock_fact_store):
        mock_fact_store.list_facts.side_effect = RuntimeError("DB down")
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        assert _status(result) == 500

    def test_get_fact_store_raises(self, handler, get_handler, mock_fact_store):
        mock_fact_store.get_fact.side_effect = RuntimeError("DB down")
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, get_handler)
        assert _status(result) == 500

    def test_create_fact_store_raises(self, handler, post_handler_factory, mock_fact_store):
        mock_fact_store.add_fact.side_effect = RuntimeError("DB down")
        http = post_handler_factory({"statement": "Test"})
        result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert _status(result) == 500

    def test_update_fact_store_raises(self, handler, put_handler_factory, mock_fact_store):
        mock_fact_store.update_fact.side_effect = RuntimeError("DB down")
        http = put_handler_factory({"confidence": 0.5})
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, http)
        assert _status(result) == 500

    def test_delete_fact_store_raises(self, handler, delete_handler, mock_fact_store):
        mock_fact_store.delete_fact.side_effect = RuntimeError("DB down")
        result = handler.handle("/api/v1/knowledge/facts/fact-001", {}, delete_handler)
        assert _status(result) == 500

    def test_contradictions_store_raises(self, handler, get_handler, mock_fact_store):
        mock_fact_store.get_contradictions.side_effect = RuntimeError("DB down")
        result = handler.handle("/api/v1/knowledge/facts/fact-001/contradictions", {}, get_handler)
        assert _status(result) == 500

    def test_relations_store_raises(self, handler, get_handler, mock_fact_store):
        mock_fact_store.get_relations.side_effect = RuntimeError("DB down")
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, get_handler)
        assert _status(result) == 500

    def test_add_relation_store_raises(self, handler, post_handler_factory, mock_fact_store):
        mock_fact_store.add_relation.side_effect = RuntimeError("DB down")
        http = post_handler_factory(
            {
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/fact-001/relations", {}, http)
        assert _status(result) == 500

    def test_bulk_add_relation_store_raises(self, handler, post_handler_factory, mock_fact_store):
        mock_fact_store.add_relation.side_effect = RuntimeError("DB down")
        http = post_handler_factory(
            {
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert _status(result) == 500
