"""
Tests for FactsOperationsMixin.

Tests fact CRUD operations, verification, contradictions, and relations API endpoints.

Run with:
    pytest tests/server/handlers/knowledge_base/test_facts.py -v --noconftest --timeout=30
"""

from __future__ import annotations

import functools
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from unittest.mock import MagicMock, patch


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
    "aragora.server.handlers.knowledge_base.facts.require_permission", _bypass_require_permission
)
_p1.start()
_p2.start()

import pytest

from aragora.server.handlers.knowledge_base.facts import FactsOperationsMixin  # noqa: E402

_p1.stop()
_p2.stop()


def parse_response(result):
    """Parse HandlerResult body to dict."""
    if result.body is None:
        return {}
    body = result.body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    return json.loads(body)


# =============================================================================
# Import Tests
# =============================================================================


class TestImports:
    """Verify imports work correctly."""

    def test_import_facts_mixin(self):
        """Should be able to import FactsOperationsMixin."""
        from aragora.server.handlers.knowledge_base.facts import FactsOperationsMixin

        assert FactsOperationsMixin is not None

    def test_import_types(self):
        """Should be able to import supporting types."""
        from aragora.knowledge import (
            FactFilters,
            FactRelationType,
            ValidationStatus,
        )

        assert FactFilters is not None
        assert FactRelationType is not None
        assert ValidationStatus is not None


# =============================================================================
# Mock Objects
# =============================================================================


class ValidationStatus(str, Enum):
    """Mock validation status enum."""

    UNVERIFIED = "unverified"
    CONTESTED = "contested"
    MAJORITY_AGREED = "majority_agreed"
    BYZANTINE_AGREED = "byzantine_agreed"
    FORMALLY_PROVEN = "formally_proven"


class FactRelationType(str, Enum):
    """Mock fact relation type enum."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    IMPLIES = "implies"
    RELATED_TO = "related_to"


@dataclass
class MockFact:
    """Mock Fact object."""

    id: str
    statement: str
    confidence: float = 0.5
    evidence_ids: list[str] = field(default_factory=list)
    consensus_proof_id: str | None = None
    source_documents: list[str] = field(default_factory=list)
    workspace_id: str = "default"
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "confidence": self.confidence,
            "evidence_ids": self.evidence_ids,
            "consensus_proof_id": self.consensus_proof_id,
            "source_documents": self.source_documents,
            "workspace_id": self.workspace_id,
            "validation_status": self.validation_status.value,
            "topics": self.topics,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "superseded_by": self.superseded_by,
        }


@dataclass
class MockFactRelation:
    """Mock FactRelation object."""

    id: str
    source_fact_id: str
    target_fact_id: str
    relation_type: FactRelationType
    confidence: float = 0.5
    created_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_fact_id": self.source_fact_id,
            "target_fact_id": self.target_fact_id,
            "relation_type": self.relation_type.value,
            "confidence": self.confidence,
            "created_by": self.created_by,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MockVerificationResult:
    """Mock verification result."""

    fact_id: str
    verified: bool
    confidence: float
    agents_agreed: list[str] = field(default_factory=list)
    agents_disagreed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "verified": self.verified,
            "confidence": self.confidence,
            "agents_agreed": self.agents_agreed,
            "agents_disagreed": self.agents_disagreed,
        }


@dataclass
class MockContradiction:
    """Mock contradiction object."""

    id: str
    fact_a_id: str
    fact_b_id: str
    severity: str = "medium"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "fact_a_id": self.fact_a_id,
            "fact_b_id": self.fact_b_id,
            "severity": self.severity,
            "reason": self.reason,
        }


@dataclass
class MockFactStore:
    """Mock FactStore for testing."""

    list_facts: MagicMock = field(default_factory=MagicMock)
    get_fact: MagicMock = field(default_factory=MagicMock)
    add_fact: MagicMock = field(default_factory=MagicMock)
    update_fact: MagicMock = field(default_factory=MagicMock)
    delete_fact: MagicMock = field(default_factory=MagicMock)
    get_contradictions: MagicMock = field(default_factory=MagicMock)
    get_relations: MagicMock = field(default_factory=MagicMock)
    add_relation: MagicMock = field(default_factory=MagicMock)


@dataclass
class MockQueryEngine:
    """Mock query engine for testing."""

    verify_fact: MagicMock = field(default_factory=MagicMock)


@dataclass
class MockUserContext:
    """Mock user auth context."""

    authenticated: bool = True
    user_id: str = "test-user-001"
    email: str = "test@example.com"
    org_id: str = "test-org-001"
    role: str = "admin"


class FactsHandler(FactsOperationsMixin):
    """Handler implementation for testing FactsOperationsMixin."""

    def __init__(
        self,
        fact_store: MockFactStore | None = None,
        query_engine: MockQueryEngine | None = None,
    ):
        self._store = fact_store
        self._engine = query_engine
        self.ctx = {}

    def _get_fact_store(self):
        return self._store

    def _get_query_engine(self):
        return self._engine

    def require_auth_or_error(self, handler):
        """Mock auth that returns authenticated user."""
        return MockUserContext(), None


class FactsHandlerNoAuth(FactsOperationsMixin):
    """Handler that returns auth error."""

    def __init__(self, fact_store: MockFactStore | None = None):
        self._store = fact_store
        self.ctx = {}

    def _get_fact_store(self):
        return self._store

    def _get_query_engine(self):
        return None

    def require_auth_or_error(self, handler):
        """Mock auth failure."""
        from aragora.server.handlers.base import error_response

        return None, error_response("Authentication required", 401)


def create_mock_http_handler(
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock HTTP handler."""
    mock = MagicMock()
    mock.command = method

    if body is not None:
        body_bytes = json.dumps(body).encode()
    else:
        body_bytes = b"{}"

    mock.rfile = MagicMock()
    mock.rfile.read = MagicMock(return_value=body_bytes)

    mock.headers = headers or {}
    mock.headers.setdefault("Content-Length", str(len(body_bytes)))

    return mock


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_store():
    """Create a mock FactStore."""
    return MockFactStore()


@pytest.fixture
def mock_engine():
    """Create a mock QueryEngine."""
    return MockQueryEngine()


@pytest.fixture
def handler(mock_store, mock_engine):
    """Create a test handler with mock store and engine."""
    return FactsHandler(fact_store=mock_store, query_engine=mock_engine)


@pytest.fixture
def handler_no_auth(mock_store):
    """Create a handler that returns auth error."""
    return FactsHandlerNoAuth(fact_store=mock_store)


@pytest.fixture
def sample_fact():
    """Create a sample mock fact."""
    return MockFact(
        id="fact-001",
        statement="The sky is blue",
        confidence=0.95,
        evidence_ids=["ev-001", "ev-002"],
        workspace_id="ws-123",
        validation_status=ValidationStatus.MAJORITY_AGREED,
        topics=["science", "nature"],
    )


@pytest.fixture
def sample_facts():
    """Create a list of sample facts."""
    return [
        MockFact(
            id="fact-001",
            statement="The sky is blue",
            confidence=0.95,
            workspace_id="ws-123",
            topics=["science"],
        ),
        MockFact(
            id="fact-002",
            statement="Water is wet",
            confidence=0.99,
            workspace_id="ws-123",
            topics=["science"],
        ),
        MockFact(
            id="fact-003",
            statement="Fire is hot",
            confidence=0.85,
            workspace_id="ws-456",
            topics=["physics"],
        ),
    ]


@pytest.fixture
def sample_relation():
    """Create a sample mock relation."""
    return MockFactRelation(
        id="rel-001",
        source_fact_id="fact-001",
        target_fact_id="fact-002",
        relation_type=FactRelationType.SUPPORTS,
        confidence=0.8,
        created_by="user-001",
    )


# =============================================================================
# Test list_facts
# =============================================================================


class TestListFacts:
    """Tests for _handle_list_facts endpoint."""

    def test_list_facts_success(self, handler, mock_store, sample_facts):
        """Should return list of facts with default parameters."""
        mock_store.list_facts.return_value = sample_facts

        result = handler._handle_list_facts({})

        assert result.status_code == 200
        body = parse_response(result)
        assert "facts" in body
        assert len(body["facts"]) == 3
        assert body["total"] == 3
        assert body["limit"] == 50  # Default
        assert body["offset"] == 0  # Default

    def test_list_facts_with_workspace_filter(self, handler, mock_store, sample_facts):
        """Should filter facts by workspace_id."""
        filtered = [f for f in sample_facts if f.workspace_id == "ws-123"]
        mock_store.list_facts.return_value = filtered

        result = handler._handle_list_facts({"workspace_id": "ws-123"})

        assert result.status_code == 200
        body = parse_response(result)
        assert len(body["facts"]) == 2

    def test_list_facts_with_topic_filter(self, handler, mock_store, sample_facts):
        """Should filter facts by topic."""
        filtered = [f for f in sample_facts if "science" in f.topics]
        mock_store.list_facts.return_value = filtered

        result = handler._handle_list_facts({"topic": "science"})

        assert result.status_code == 200
        body = parse_response(result)
        assert len(body["facts"]) == 2

    def test_list_facts_with_min_confidence(self, handler, mock_store, sample_facts):
        """Should filter facts by minimum confidence."""
        filtered = [f for f in sample_facts if f.confidence >= 0.9]
        mock_store.list_facts.return_value = filtered

        result = handler._handle_list_facts({"min_confidence": "0.9"})

        assert result.status_code == 200
        body = parse_response(result)
        assert len(body["facts"]) == 2

    def test_list_facts_with_status_filter(self, handler, mock_store, sample_fact):
        """Should filter facts by validation status."""
        mock_store.list_facts.return_value = [sample_fact]

        result = handler._handle_list_facts({"status": "majority_agreed"})

        assert result.status_code == 200
        body = parse_response(result)
        assert len(body["facts"]) == 1

    def test_list_facts_with_include_superseded(self, handler, mock_store, sample_facts):
        """Should include superseded facts when requested."""
        mock_store.list_facts.return_value = sample_facts

        result = handler._handle_list_facts({"include_superseded": "true"})

        assert result.status_code == 200
        body = parse_response(result)
        assert "facts" in body

    def test_list_facts_with_pagination(self, handler, mock_store, sample_facts):
        """Should handle limit and offset parameters."""
        mock_store.list_facts.return_value = sample_facts[1:2]

        result = handler._handle_list_facts({"limit": "1", "offset": "1"})

        assert result.status_code == 200
        body = parse_response(result)
        assert body["limit"] == 1
        assert body["offset"] == 1

    def test_list_facts_empty_result(self, handler, mock_store):
        """Should return empty list when no facts match."""
        mock_store.list_facts.return_value = []

        result = handler._handle_list_facts({"workspace_id": "nonexistent"})

        assert result.status_code == 200
        body = parse_response(result)
        assert body["facts"] == []
        assert body["total"] == 0


# =============================================================================
# Test get_fact
# =============================================================================


class TestGetFact:
    """Tests for _handle_get_fact endpoint."""

    def test_get_fact_success(self, handler, mock_store, sample_fact):
        """Should return fact when found."""
        mock_store.get_fact.return_value = sample_fact

        result = handler._handle_get_fact("fact-001")

        assert result.status_code == 200
        body = parse_response(result)
        assert body["id"] == "fact-001"
        assert body["statement"] == "The sky is blue"
        assert body["confidence"] == 0.95

    def test_get_fact_not_found(self, handler, mock_store):
        """Should return 404 when fact not found."""
        mock_store.get_fact.return_value = None

        result = handler._handle_get_fact("nonexistent")

        assert result.status_code == 404
        body = parse_response(result)
        assert "not found" in body["error"].lower()


# =============================================================================
# Test create_fact
# =============================================================================


class TestCreateFact:
    """Tests for _handle_create_fact endpoint."""

    def test_create_fact_success(self, handler, mock_store, sample_fact):
        """Should create fact and return 201."""
        mock_store.add_fact.return_value = sample_fact

        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "statement": "The sky is blue",
                "workspace_id": "ws-123",
                "confidence": 0.95,
                "topics": ["science"],
            },
        )

        result = handler._handle_create_fact(http_handler)

        assert result.status_code == 201
        body = parse_response(result)
        assert body["id"] == "fact-001"
        mock_store.add_fact.assert_called_once()

    def test_create_fact_missing_statement(self, handler, mock_store):
        """Should return 400 when statement is missing."""
        http_handler = create_mock_http_handler(
            method="POST",
            body={"workspace_id": "ws-123"},
        )

        result = handler._handle_create_fact(http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "statement" in body["error"].lower()

    def test_create_fact_empty_statement(self, handler, mock_store):
        """Should return 400 when statement is empty."""
        http_handler = create_mock_http_handler(
            method="POST",
            body={"statement": ""},
        )

        result = handler._handle_create_fact(http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "statement" in body["error"].lower()

    def test_create_fact_invalid_json(self, handler, mock_store):
        """Should return 400 for invalid JSON body."""
        http_handler = MagicMock()
        http_handler.headers = {"Content-Length": "11"}
        http_handler.rfile = MagicMock()
        http_handler.rfile.read.return_value = b"not valid json"

        result = handler._handle_create_fact(http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "invalid" in body["error"].lower()

    def test_create_fact_no_body(self, handler, mock_store):
        """Should return 400 when request body is empty."""
        http_handler = MagicMock()
        http_handler.headers = {"Content-Length": "0"}
        http_handler.rfile = MagicMock()
        http_handler.rfile.read.return_value = b""

        result = handler._handle_create_fact(http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "body" in body["error"].lower()

    def test_create_fact_default_workspace(self, handler, mock_store, sample_fact):
        """Should use default workspace_id when not provided."""
        mock_store.add_fact.return_value = sample_fact

        http_handler = create_mock_http_handler(
            method="POST",
            body={"statement": "Test statement"},
        )

        result = handler._handle_create_fact(http_handler)

        assert result.status_code == 201
        call_args = mock_store.add_fact.call_args
        assert call_args[1]["workspace_id"] == "default"

    def test_create_fact_requires_auth(self, handler_no_auth, mock_store):
        """Should return 401 when not authenticated."""
        http_handler = create_mock_http_handler(
            method="POST",
            body={"statement": "Test statement"},
        )

        result = handler_no_auth._handle_create_fact(http_handler)

        assert result.status_code == 401


# =============================================================================
# Test update_fact
# =============================================================================


class TestUpdateFact:
    """Tests for _handle_update_fact endpoint."""

    def test_update_fact_success(self, handler, mock_store, sample_fact):
        """Should update fact and return updated data."""
        updated_fact = MockFact(
            id="fact-001",
            statement="The sky is blue",
            confidence=0.99,
            workspace_id="ws-123",
        )
        mock_store.update_fact.return_value = updated_fact

        http_handler = create_mock_http_handler(
            method="PUT",
            body={"confidence": 0.99},
        )

        result = handler._handle_update_fact("fact-001", http_handler)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["confidence"] == 0.99

    def test_update_fact_not_found(self, handler, mock_store):
        """Should return 404 when fact not found."""
        mock_store.update_fact.return_value = None

        http_handler = create_mock_http_handler(
            method="PUT",
            body={"confidence": 0.99},
        )

        result = handler._handle_update_fact("nonexistent", http_handler)

        assert result.status_code == 404
        body = parse_response(result)
        assert "not found" in body["error"].lower()

    def test_update_fact_multiple_fields(self, handler, mock_store, sample_fact):
        """Should update multiple fields at once."""
        mock_store.update_fact.return_value = sample_fact

        http_handler = create_mock_http_handler(
            method="PUT",
            body={
                "confidence": 0.99,
                "validation_status": "byzantine_agreed",
                "topics": ["updated"],
            },
        )

        result = handler._handle_update_fact("fact-001", http_handler)

        assert result.status_code == 200
        call_kwargs = mock_store.update_fact.call_args[1]
        assert "confidence" in call_kwargs
        assert "validation_status" in call_kwargs
        assert "topics" in call_kwargs

    def test_update_fact_requires_auth(self, handler_no_auth, mock_store):
        """Should return 401 when not authenticated."""
        http_handler = create_mock_http_handler(
            method="PUT",
            body={"confidence": 0.99},
        )

        result = handler_no_auth._handle_update_fact("fact-001", http_handler)

        assert result.status_code == 401


# =============================================================================
# Test delete_fact
# =============================================================================


class TestDeleteFact:
    """Tests for _handle_delete_fact endpoint."""

    def test_delete_fact_success(self, handler, mock_store):
        """Should delete fact and return confirmation."""
        mock_store.delete_fact.return_value = True

        http_handler = create_mock_http_handler(method="DELETE")

        result = handler._handle_delete_fact("fact-001", http_handler)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["deleted"] is True
        assert body["fact_id"] == "fact-001"

    def test_delete_fact_not_found(self, handler, mock_store):
        """Should return 404 when fact not found."""
        mock_store.delete_fact.return_value = False

        http_handler = create_mock_http_handler(method="DELETE")

        result = handler._handle_delete_fact("nonexistent", http_handler)

        assert result.status_code == 404
        body = parse_response(result)
        assert "not found" in body["error"].lower()

    def test_delete_fact_requires_auth(self, handler_no_auth, mock_store):
        """Should return 401 when not authenticated."""
        http_handler = create_mock_http_handler(method="DELETE")

        result = handler_no_auth._handle_delete_fact("fact-001", http_handler)

        assert result.status_code == 401


# =============================================================================
# Test verify_fact
# =============================================================================


class TestVerifyFact:
    """Tests for _handle_verify_fact endpoint."""

    def test_verify_fact_not_found(self, handler, mock_store, mock_engine):
        """Should return 404 when fact not found."""
        mock_store.get_fact.return_value = None

        http_handler = create_mock_http_handler(method="POST")

        result = handler._handle_verify_fact("nonexistent", http_handler)

        assert result.status_code == 404
        body = parse_response(result)
        assert "not found" in body["error"].lower()

    def test_verify_fact_queued_simple_engine(self, handler, mock_store, sample_fact):
        """Should queue verification when using SimpleQueryEngine."""
        # Create handler with SimpleQueryEngine instead of DatasetQueryEngine
        simple_handler = FactsHandler(
            fact_store=mock_store,
            query_engine=MockQueryEngine(),  # Not a DatasetQueryEngine
        )
        mock_store.get_fact.return_value = sample_fact

        http_handler = create_mock_http_handler(method="POST")

        result = simple_handler._handle_verify_fact("fact-001", http_handler)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["status"] == "queued"
        assert body["verified"] is None

    def test_verify_fact_with_dataset_engine(self, handler, mock_store, sample_fact):
        """Should verify fact when DatasetQueryEngine is available."""
        # Import the real DatasetQueryEngine to create a proper mock subclass
        from aragora.knowledge import DatasetQueryEngine

        # Create a mock that IS an instance of DatasetQueryEngine
        mock_dataset_engine = MagicMock(spec=DatasetQueryEngine)

        verification_result = MockVerificationResult(
            fact_id="fact-001",
            verified=True,
            confidence=0.95,
            agents_agreed=["claude", "gpt4"],
            agents_disagreed=[],
        )

        mock_store.get_fact.return_value = sample_fact

        # Patch run_async to return our mock result
        with patch(
            "aragora.server.http_utils.run_async",
            return_value=verification_result,
        ):
            dataset_handler = FactsHandler(
                fact_store=mock_store,
                query_engine=mock_dataset_engine,
            )
            http_handler = create_mock_http_handler(method="POST")
            result = dataset_handler._handle_verify_fact("fact-001", http_handler)

        assert result.status_code == 200
        body = parse_response(result)
        assert body["fact_id"] == "fact-001"
        assert body["verified"] is True


# =============================================================================
# Test get_contradictions
# =============================================================================


class TestGetContradictions:
    """Tests for _handle_get_contradictions endpoint."""

    def test_get_contradictions_success(self, handler, mock_store, sample_fact):
        """Should return contradictions for fact."""
        mock_store.get_fact.return_value = sample_fact
        mock_contradictions = [
            MockContradiction(
                id="contr-001",
                fact_a_id="fact-001",
                fact_b_id="fact-002",
                severity="high",
                reason="Direct contradiction",
            ),
        ]
        mock_store.get_contradictions.return_value = mock_contradictions

        result = handler._handle_get_contradictions("fact-001")

        assert result.status_code == 200
        body = parse_response(result)
        assert body["fact_id"] == "fact-001"
        assert body["count"] == 1
        assert len(body["contradictions"]) == 1

    def test_get_contradictions_not_found(self, handler, mock_store):
        """Should return 404 when fact not found."""
        mock_store.get_fact.return_value = None

        result = handler._handle_get_contradictions("nonexistent")

        assert result.status_code == 404
        body = parse_response(result)
        assert "not found" in body["error"].lower()

    def test_get_contradictions_empty(self, handler, mock_store, sample_fact):
        """Should return empty list when no contradictions."""
        mock_store.get_fact.return_value = sample_fact
        mock_store.get_contradictions.return_value = []

        result = handler._handle_get_contradictions("fact-001")

        assert result.status_code == 200
        body = parse_response(result)
        assert body["contradictions"] == []
        assert body["count"] == 0


# =============================================================================
# Test get_relations
# =============================================================================


class TestGetRelations:
    """Tests for _handle_get_relations endpoint."""

    def test_get_relations_success(self, handler, mock_store, sample_fact, sample_relation):
        """Should return relations for fact."""
        mock_store.get_fact.return_value = sample_fact
        mock_store.get_relations.return_value = [sample_relation]

        result = handler._handle_get_relations("fact-001", {})

        assert result.status_code == 200
        body = parse_response(result)
        assert body["fact_id"] == "fact-001"
        assert body["count"] == 1
        assert len(body["relations"]) == 1

    def test_get_relations_not_found(self, handler, mock_store):
        """Should return 404 when fact not found."""
        mock_store.get_fact.return_value = None

        result = handler._handle_get_relations("nonexistent", {})

        assert result.status_code == 404
        body = parse_response(result)
        assert "not found" in body["error"].lower()

    def test_get_relations_with_type_filter(
        self, handler, mock_store, sample_fact, sample_relation
    ):
        """Should filter relations by type."""
        mock_store.get_fact.return_value = sample_fact
        mock_store.get_relations.return_value = [sample_relation]

        result = handler._handle_get_relations("fact-001", {"type": "supports"})

        assert result.status_code == 200
        mock_store.get_relations.assert_called_once()
        call_kwargs = mock_store.get_relations.call_args[1]
        assert call_kwargs["relation_type"].value == "supports"

    def test_get_relations_as_source_only(self, handler, mock_store, sample_fact, sample_relation):
        """Should get relations where fact is source only."""
        mock_store.get_fact.return_value = sample_fact
        mock_store.get_relations.return_value = [sample_relation]

        result = handler._handle_get_relations(
            "fact-001", {"as_source": "true", "as_target": "false"}
        )

        assert result.status_code == 200
        call_kwargs = mock_store.get_relations.call_args[1]
        assert call_kwargs["as_source"] is True
        assert call_kwargs["as_target"] is False

    def test_get_relations_as_target_only(self, handler, mock_store, sample_fact, sample_relation):
        """Should get relations where fact is target only."""
        mock_store.get_fact.return_value = sample_fact
        mock_store.get_relations.return_value = [sample_relation]

        result = handler._handle_get_relations(
            "fact-001", {"as_source": "false", "as_target": "true"}
        )

        assert result.status_code == 200
        call_kwargs = mock_store.get_relations.call_args[1]
        assert call_kwargs["as_source"] is False
        assert call_kwargs["as_target"] is True


# =============================================================================
# Test add_relation
# =============================================================================


class TestAddRelation:
    """Tests for _handle_add_relation endpoint."""

    def test_add_relation_success(self, handler, mock_store, sample_fact, sample_relation):
        """Should add relation and return 201."""
        mock_store.get_fact.return_value = sample_fact
        mock_store.add_relation.return_value = sample_relation

        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "target_fact_id": "fact-002",
                "relation_type": "supports",
                "confidence": 0.8,
            },
        )

        result = handler._handle_add_relation("fact-001", http_handler)

        assert result.status_code == 201
        body = parse_response(result)
        assert body["source_fact_id"] == "fact-001"
        assert body["target_fact_id"] == "fact-002"

    def test_add_relation_missing_target(self, handler, mock_store, sample_fact):
        """Should return 400 when target_fact_id missing."""
        mock_store.get_fact.return_value = sample_fact

        http_handler = create_mock_http_handler(
            method="POST",
            body={"relation_type": "supports"},
        )

        result = handler._handle_add_relation("fact-001", http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "target_fact_id" in body["error"]

    def test_add_relation_missing_type(self, handler, mock_store, sample_fact):
        """Should return 400 when relation_type missing."""
        mock_store.get_fact.return_value = sample_fact

        http_handler = create_mock_http_handler(
            method="POST",
            body={"target_fact_id": "fact-002"},
        )

        result = handler._handle_add_relation("fact-001", http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "relation_type" in body["error"]

    def test_add_relation_invalid_type(self, handler, mock_store, sample_fact):
        """Should return 400 for invalid relation_type."""
        mock_store.get_fact.return_value = sample_fact

        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "target_fact_id": "fact-002",
                "relation_type": "invalid_type",
            },
        )

        result = handler._handle_add_relation("fact-001", http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "invalid" in body["error"].lower()

    def test_add_relation_source_not_found(self, handler, mock_store):
        """Should return 404 when source fact not found."""
        mock_store.get_fact.return_value = None

        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            },
        )

        result = handler._handle_add_relation("nonexistent", http_handler)

        assert result.status_code == 404
        body = parse_response(result)
        assert "source" in body["error"].lower()

    def test_add_relation_target_not_found(self, handler, mock_store, sample_fact):
        """Should return 404 when target fact not found."""

        # Use a callable side_effect instead of a list to avoid the
        # 'list object is not an iterator' TypeError that occurs when the
        # MagicMock.side_effect property descriptor is corrupted by a
        # prior test (e.g. setting side_effect on a MagicMock CLASS rather
        # than an instance).  A callable side_effect bypasses the
        # list-to-iterator conversion entirely.
        def _get_fact_side_effect(fact_id, **_kwargs):
            if fact_id == "fact-001":
                return sample_fact
            return None

        mock_store.get_fact.side_effect = _get_fact_side_effect

        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "target_fact_id": "nonexistent",
                "relation_type": "supports",
            },
        )

        result = handler._handle_add_relation("fact-001", http_handler)

        assert result.status_code == 404
        body = parse_response(result)
        assert "target" in body["error"].lower()


# =============================================================================
# Test add_relation_bulk
# =============================================================================


class TestAddRelationBulk:
    """Tests for _handle_add_relation_bulk endpoint."""

    def test_add_relation_bulk_success(self, handler, mock_store, sample_relation):
        """Should add relation via bulk endpoint and return 201."""
        mock_store.add_relation.return_value = sample_relation

        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "supports",
                "confidence": 0.8,
            },
        )

        result = handler._handle_add_relation_bulk(http_handler)

        assert result.status_code == 201
        body = parse_response(result)
        assert body["source_fact_id"] == "fact-001"
        assert body["target_fact_id"] == "fact-002"

    def test_add_relation_bulk_missing_source(self, handler, mock_store):
        """Should return 400 when source_fact_id missing."""
        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "target_fact_id": "fact-002",
                "relation_type": "supports",
            },
        )

        result = handler._handle_add_relation_bulk(http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "source_fact_id" in body["error"]

    def test_add_relation_bulk_missing_target(self, handler, mock_store):
        """Should return 400 when target_fact_id missing."""
        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "source_fact_id": "fact-001",
                "relation_type": "supports",
            },
        )

        result = handler._handle_add_relation_bulk(http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "target_fact_id" in body["error"]

    def test_add_relation_bulk_missing_type(self, handler, mock_store):
        """Should return 400 when relation_type missing."""
        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
            },
        )

        result = handler._handle_add_relation_bulk(http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "relation_type" in body["error"]

    def test_add_relation_bulk_invalid_type(self, handler, mock_store):
        """Should return 400 for invalid relation_type."""
        http_handler = create_mock_http_handler(
            method="POST",
            body={
                "source_fact_id": "fact-001",
                "target_fact_id": "fact-002",
                "relation_type": "invalid",
            },
        )

        result = handler._handle_add_relation_bulk(http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "invalid" in body["error"].lower()

    def test_add_relation_bulk_no_body(self, handler, mock_store):
        """Should return 400 when request body is empty."""
        http_handler = MagicMock()
        http_handler.headers = {"Content-Length": "0"}
        http_handler.rfile = MagicMock()
        http_handler.rfile.read.return_value = b""

        result = handler._handle_add_relation_bulk(http_handler)

        assert result.status_code == 400
        body = parse_response(result)
        assert "body" in body["error"].lower()


# =============================================================================
# Test caching
# =============================================================================


class TestCaching:
    """list_facts is per organization, so no shared response cache wraps it."""

    def test_list_facts_hits_the_store_every_time(self, sample_facts):
        """Every call reads the store; there is no response cache."""
        # Create completely fresh mocks to avoid any state pollution
        fresh_store = MockFactStore()
        fresh_engine = MockQueryEngine()
        fresh_handler = FactsHandler(fact_store=fresh_store, query_engine=fresh_engine)
        fresh_store.list_facts.return_value = sample_facts

        # Call with different parameters
        fresh_handler._handle_list_facts({"workspace_id": "ws-123"})
        fresh_handler._handle_list_facts({"workspace_id": "ws-456"})

        assert fresh_store.list_facts.call_count == 2


# =============================================================================
# Test error handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling via @handle_errors decorator."""

    def test_list_facts_handles_store_error(self):
        """Should return 500 when store raises exception."""
        # Create completely fresh mocks to avoid any state pollution
        fresh_store = MockFactStore()
        fresh_engine = MockQueryEngine()
        fresh_handler = FactsHandler(fact_store=fresh_store, query_engine=fresh_engine)
        fresh_store.list_facts.side_effect = OSError("Database error")

        result = fresh_handler._handle_list_facts({})

        assert result.status_code == 500

    def test_get_fact_handles_store_error(self, handler, mock_store):
        """Should return 500 when store raises exception."""
        mock_store.get_fact.side_effect = OSError("Database error")

        result = handler._handle_get_fact("fact-001")

        assert result.status_code == 500

    def test_create_fact_handles_store_error(self, handler, mock_store):
        """Should return 500 when store raises exception."""
        mock_store.add_fact.side_effect = OSError("Database error")

        http_handler = create_mock_http_handler(
            method="POST",
            body={"statement": "Test statement"},
        )

        result = handler._handle_create_fact(http_handler)

        assert result.status_code == 500
