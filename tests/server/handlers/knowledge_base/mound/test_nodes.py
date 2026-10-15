"""Tests for NodeOperationsMixin."""

from __future__ import annotations

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


import io
import json
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from aragora.server.handlers.knowledge_base.mound.nodes import (
    NodeOperationsMixin,
)


def parse_response(result):
    """Parse HandlerResult body to dict."""
    return json.loads(result.body.decode("utf-8"))


# =============================================================================
# Mock Objects
# =============================================================================


@dataclass
class MockUser:
    """Mock user for testing."""

    id: str = "user-123"
    user_id: str = "user-123"


@dataclass
class MockNode:
    """Mock knowledge node."""

    id: str
    content: str
    node_type: str = "fact"
    confidence: float = 0.5
    workspace_id: str = "default"
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "node_type": self.node_type,
            "confidence": self.confidence,
            "workspace_id": self.workspace_id,
            "topics": self.topics,
            "metadata": self.metadata,
        }


@dataclass
class MockQueryResult:
    """Mock query result."""

    query: str
    nodes: list[MockNode]
    total_count: int
    processing_time_ms: int = 50


@dataclass
class MockKnowledgeMound:
    """Mock KnowledgeMound for testing."""

    query_semantic: AsyncMock = field(default_factory=AsyncMock)
    add_node: AsyncMock = field(default_factory=AsyncMock)
    get_node: AsyncMock = field(default_factory=AsyncMock)
    query_nodes: AsyncMock = field(default_factory=AsyncMock)
    get_stats: AsyncMock = field(default_factory=AsyncMock)


class MockHandler:
    """Mock HTTP handler for testing."""

    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None):
        self.headers = headers or {}
        self._body = body
        self.rfile = io.BytesIO(body)

        if body and "Content-Length" not in self.headers:
            self.headers["Content-Length"] = str(len(body))


class NodeHandler(NodeOperationsMixin):
    """Handler implementation for testing NodeOperationsMixin."""

    def __init__(self, mound: MockKnowledgeMound | None = None, user: MockUser | None = None):
        self._mound = mound
        self._user = user or MockUser()
        self.ctx = {}

    def _get_mound(self):
        return self._mound

    def require_auth_or_error(self, handler):
        return self._user, None


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_mound():
    """Create a mock KnowledgeMound."""
    return MockKnowledgeMound()


@pytest.fixture
def mock_user():
    """Create a mock user."""
    return MockUser()


@pytest.fixture
def handler(mock_mound, mock_user):
    """Create a test handler with mock mound."""
    return NodeHandler(mound=mock_mound, user=mock_user)


@pytest.fixture
def handler_no_mound(mock_user):
    """Create a test handler without mound."""
    return NodeHandler(mound=None, user=mock_user)


@pytest.fixture(autouse=True)
def clear_module_state():
    """Clear any module-level state between tests."""
    yield


# =============================================================================
# Test mound_query
# =============================================================================


class TestMoundQuery:
    """Tests for semantic query endpoint."""

    def test_query_success(self, handler, mock_mound):
        """Test successful semantic query."""
        nodes = [
            MockNode(id="node-1", content="Result 1"),
            MockNode(id="node-2", content="Result 2"),
        ]
        result_obj = MockQueryResult(query="test query", nodes=nodes, total_count=2)
        mock_mound.query_semantic.return_value = result_obj

        body = json.dumps({"query": "test query"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["query"] == "test query"
        assert data["total_count"] == 2
        assert len(data["nodes"]) == 2

    def test_query_with_filters(self, handler, mock_mound):
        """Test query with filters."""
        result_obj = MockQueryResult(query="test", nodes=[], total_count=0)
        mock_mound.query_semantic.return_value = result_obj

        body = json.dumps(
            {
                "query": "test",
                "workspace_id": "ws-123",
                "limit": 5,
                "node_types": ["fact", "claim"],
                "min_confidence": 0.7,
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 200

    def test_query_missing_query(self, handler):
        """Test query without query parameter."""
        body = json.dumps({}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 400
        assert "required" in parse_response(result)["error"]

    def test_query_no_mound(self, handler_no_mound):
        """Test query when mound not available."""
        body = json.dumps({"query": "test"}).encode()
        http_handler = MockHandler(body=body)

        result = handler_no_mound._handle_mound_query(http_handler)

        assert result.status_code == 503


# =============================================================================
# Test create_node
# =============================================================================


class TestCreateNode:
    """Tests for create node endpoint."""

    def test_create_node_success(self, handler, mock_mound):
        """Test successful node creation."""
        mock_mound.add_node.return_value = "node-123"
        saved_node = MockNode(id="node-123", content="Test content")
        mock_mound.get_node.return_value = saved_node

        body = json.dumps(
            {
                "content": "Test content",
                "node_type": "fact",
                "confidence": 0.8,
                "topics": ["test"],
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_node(http_handler)

        assert result.status_code == 201
        data = parse_response(result)
        assert data["id"] == "node-123"

    def test_create_node_with_source(self, handler, mock_mound):
        """Test node creation with source provenance."""
        mock_mound.add_node.return_value = "node-456"
        saved_node = MockNode(id="node-456", content="Content with source")
        mock_mound.get_node.return_value = saved_node

        body = json.dumps(
            {
                "content": "Content with source",
                "source": {
                    "type": "user",
                    "id": "source-123",
                    "user_id": "user-456",
                },
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_node(http_handler)

        assert result.status_code == 201

    def test_create_node_missing_content(self, handler):
        """Test node creation without content."""
        body = json.dumps({"node_type": "fact"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_node(http_handler)

        assert result.status_code == 400
        assert "required" in parse_response(result)["error"]

    def test_create_node_invalid_type(self, handler):
        """Test node creation with invalid type."""
        body = json.dumps(
            {
                "content": "Test",
                "node_type": "invalid",
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_node(http_handler)

        assert result.status_code == 400
        assert "Invalid node_type" in parse_response(result)["error"]

    def test_create_node_no_mound(self, handler_no_mound):
        """Test node creation when mound not available."""
        body = json.dumps({"content": "Test"}).encode()
        http_handler = MockHandler(body=body)

        result = handler_no_mound._handle_create_node(http_handler)

        assert result.status_code == 503


# =============================================================================
# Test get_node
# =============================================================================


class TestGetNode:
    """Tests for get node endpoint."""

    def test_get_node_success(self, handler, mock_mound):
        """Test successful node retrieval."""
        node = MockNode(id="node-123", content="Test content")
        mock_mound.get_node.return_value = node

        result = handler._handle_get_node("node-123")

        assert result.status_code == 200
        data = parse_response(result)
        assert data["id"] == "node-123"
        assert data["content"] == "Test content"

    def test_get_node_not_found(self, handler, mock_mound):
        """Test get node when not found."""
        mock_mound.get_node.return_value = None

        result = handler._handle_get_node("nonexistent")

        assert result.status_code == 404

    def test_get_node_no_mound(self, handler_no_mound):
        """Test get node when mound not available."""
        result = handler_no_mound._handle_get_node("node-123")

        assert result.status_code == 503


# =============================================================================
# Test list_nodes
# =============================================================================


class TestListNodes:
    """Tests for list nodes endpoint."""

    def test_list_nodes_success(self, handler, mock_mound):
        """Test successful node listing."""
        nodes = [
            MockNode(id="node-1", content="Node 1"),
            MockNode(id="node-2", content="Node 2"),
        ]
        mock_mound.query_nodes.return_value = nodes

        result = handler._handle_list_nodes({})

        assert result.status_code == 200
        data = parse_response(result)
        assert data["count"] == 2
        assert len(data["nodes"]) == 2

    def test_list_nodes_with_filters(self, handler, mock_mound):
        """Test node listing with filters."""
        mock_mound.query_nodes.return_value = []

        result = handler._handle_list_nodes(
            {
                "workspace_id": ["ws-123"],
                "node_types": ["fact,claim"],
                "min_confidence": ["0.5"],
                "tier": ["slow"],
                "limit": ["10"],
                "offset": ["5"],
            }
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["limit"] == 10
        assert data["offset"] == 5

    def test_list_nodes_no_mound(self, handler_no_mound):
        """Test node listing when mound not available."""
        result = handler_no_mound._handle_list_nodes({})

        assert result.status_code == 503


# =============================================================================
# Test mound_stats
# =============================================================================


class TestMoundStats:
    """Tests for mound stats endpoint."""

    def test_get_stats_success(self, handler, mock_mound):
        """Test successful stats retrieval."""
        stats = {
            "total_nodes": 1000,
            "by_type": {"fact": 500, "claim": 300, "memory": 200},
            "by_tier": {"fast": 100, "medium": 300, "slow": 500, "glacial": 100},
        }
        mock_mound.get_stats.return_value = stats

        result = handler._handle_mound_stats({})

        assert result.status_code == 200
        data = parse_response(result)
        assert data["total_nodes"] == 1000

    def test_get_stats_no_mound(self, handler_no_mound):
        """Test stats when mound not available."""
        result = handler_no_mound._handle_mound_stats({})

        assert result.status_code == 503

    def test_get_stats_error(self, handler, mock_mound):
        """Test stats error handling."""
        mock_mound.get_stats.side_effect = ValueError("Stats error")

        result = handler._handle_mound_stats({})

        assert result.status_code == 500
