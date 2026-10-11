"""
Comprehensive tests for KnowledgeMoundHandler.

Tests cover:
1. Mound CRUD Operations - create, read, update, delete nodes
2. Mound Search Operations - semantic search, keyword search, filtered queries
3. Mound Sync Operations - sync triggers, revalidation flows, error handling
4. Integration with Adapters - adapter selection, multi-adapter queries
5. Graph Operations - traversal, lineage, related nodes
6. Deduplication Operations - duplicate detection and merging
7. Pruning Operations - staleness detection, pruning, restoration
8. Relationship Operations - create and query relationships
"""

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
from datetime import datetime
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
    email: str = "user@example.com"
    roles: list[str] = field(default_factory=lambda: ["admin"])
    permissions: list[str] = field(default_factory=list)


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
    tier: str = "slow"
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "node_type": self.node_type,
            "confidence": self.confidence,
            "workspace_id": self.workspace_id,
            "topics": self.topics,
            "metadata": self.metadata,
            "tier": self.tier,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MockRelationship:
    """Mock relationship between nodes."""

    id: str
    from_node_id: str
    to_node_id: str
    relationship_type: str
    strength: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "relationship_type": self.relationship_type,
            "strength": self.strength,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
        }


@dataclass
class MockEdge:
    """Mock graph edge."""

    from_id: str
    to_id: str
    relationship_type: str
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "relationship_type": self.relationship_type,
            "weight": self.weight,
        }


@dataclass
class MockQueryResult:
    """Mock query result."""

    query: str
    nodes: list[MockNode]
    total_count: int
    processing_time_ms: int = 50


@dataclass
class MockGraphQueryResult:
    """Mock graph query result."""

    nodes: list[MockNode]
    edges: list[MockEdge] = field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0

    def __post_init__(self):
        if self.total_nodes == 0:
            self.total_nodes = len(self.nodes)
        if self.total_edges == 0:
            self.total_edges = len(self.edges)


@dataclass
class MockSyncResult:
    """Mock sync result."""

    nodes_synced: int = 0
    errors: int = 0


@dataclass
class MockStalenessCheck:
    """Mock staleness check result."""

    node_id: str
    staleness_score: float
    reasons: list[str] = field(default_factory=list)
    last_checked_at: datetime | None = None
    revalidation_recommended: bool = False


@dataclass
class MockDuplicateItem:
    """Mock duplicate item in a cluster."""

    node_id: str
    similarity: float
    content_preview: str
    tier: str = "slow"
    confidence: float = 0.5


@dataclass
class MockDuplicateCluster:
    """Mock duplicate cluster."""

    cluster_id: str
    primary_node_id: str
    duplicates: list[MockDuplicateItem]
    avg_similarity: float = 0.95
    recommended_action: str = "merge"


@dataclass
class MockDedupReport:
    """Mock deduplication report."""

    workspace_id: str
    generated_at: datetime
    total_nodes_analyzed: int
    duplicate_clusters_found: int
    estimated_reduction_percent: float
    clusters: list[MockDuplicateCluster]


@dataclass
class MockMergeResult:
    """Mock merge result."""

    kept_node_id: str
    merged_node_ids: list[str]
    archived_count: int
    updated_relationships: int


@dataclass
class MockPrunableItem:
    """Mock prunable item."""

    node_id: str
    content_preview: str
    staleness_score: float
    confidence: float
    retrieval_count: int = 0
    last_retrieved_at: datetime | None = None
    tier: str = "slow"
    created_at: datetime = field(default_factory=datetime.now)
    prune_reason: str = "stale"
    recommended_action: MagicMock = field(default_factory=lambda: MagicMock(value="archive"))


@dataclass
class MockPruneResult:
    """Mock prune result."""

    workspace_id: str
    executed_at: datetime
    items_analyzed: int
    items_pruned: int
    items_archived: int = 0
    items_deleted: int = 0
    items_demoted: int = 0
    items_flagged: int = 0
    pruned_item_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class MockPruneHistory:
    """Mock prune history entry."""

    history_id: str
    executed_at: datetime
    policy_id: str
    action: MagicMock
    items_pruned: int
    pruned_item_ids: list[str]
    reason: str
    executed_by: str


@dataclass
class MockKnowledgeMound:
    """Mock KnowledgeMound for testing."""

    # Node operations
    query_semantic: AsyncMock = field(default_factory=AsyncMock)
    add_node: AsyncMock = field(default_factory=AsyncMock)
    get_node: AsyncMock = field(default_factory=AsyncMock)
    query_nodes: AsyncMock = field(default_factory=AsyncMock)
    get_stats: AsyncMock = field(default_factory=AsyncMock)
    update_node: AsyncMock = field(default_factory=AsyncMock)
    delete_node: AsyncMock = field(default_factory=AsyncMock)

    # Relationship operations
    get_relationships: AsyncMock = field(default_factory=AsyncMock)
    add_relationship: AsyncMock = field(default_factory=AsyncMock)

    # Graph operations
    query_graph: AsyncMock = field(default_factory=AsyncMock)

    # Sync operations
    sync_continuum_incremental: AsyncMock = field(default_factory=AsyncMock)
    sync_consensus_incremental: AsyncMock = field(default_factory=AsyncMock)
    sync_facts_incremental: AsyncMock = field(default_factory=AsyncMock)
    connect_memory_stores: AsyncMock = field(default_factory=AsyncMock)

    # Staleness operations
    get_stale_knowledge: AsyncMock = field(default_factory=AsyncMock)
    mark_validated: AsyncMock = field(default_factory=AsyncMock)
    schedule_revalidation: AsyncMock = field(default_factory=AsyncMock)

    # Deduplication operations
    find_duplicates: AsyncMock = field(default_factory=AsyncMock)
    generate_dedup_report: AsyncMock = field(default_factory=AsyncMock)
    merge_duplicates: AsyncMock = field(default_factory=AsyncMock)
    auto_merge_exact_duplicates: AsyncMock = field(default_factory=AsyncMock)

    # Pruning operations
    get_prunable_items: AsyncMock = field(default_factory=AsyncMock)
    prune_items: AsyncMock = field(default_factory=AsyncMock)
    auto_prune: AsyncMock = field(default_factory=AsyncMock)
    get_prune_history: AsyncMock = field(default_factory=AsyncMock)
    restore_pruned_item: AsyncMock = field(default_factory=AsyncMock)
    apply_confidence_decay: AsyncMock = field(default_factory=AsyncMock)


class MockHandler:
    """Mock HTTP handler for testing."""

    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None):
        self.headers = headers or {}
        self._body = body
        self.rfile = io.BytesIO(body)
        self.command = "GET"

        if body and "Content-Length" not in self.headers:
            self.headers["Content-Length"] = str(len(body))


class MockServerContext:
    """Mock server context."""

    def __init__(self):
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)


# =============================================================================
# Test Handler Classes
# =============================================================================


class TestMoundHandler:
    """Base test handler combining all mixins for comprehensive testing."""

    def __init__(self, mound: MockKnowledgeMound | None = None, user: MockUser | None = None):
        self._mound = mound
        self._user = user or MockUser()
        self.ctx = MockServerContext()

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
def test_handler(mock_mound, mock_user):
    """Create a test handler with mock mound."""
    return TestMoundHandler(mound=mock_mound, user=mock_user)


@pytest.fixture
def handler_no_mound(mock_user):
    """Create a test handler without mound."""
    return TestMoundHandler(mound=None, user=mock_user)


@pytest.fixture(autouse=True)
def clear_module_state():
    """Clear any module-level state between tests."""
    yield


# =============================================================================
# Test Node CRUD Operations
# =============================================================================


class TestNodeCRUDOperations:
    """Tests for node Create, Read, Update, Delete operations."""

    def test_create_node_with_all_fields(self, mock_mound, mock_user):
        """Test node creation with all optional fields populated."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        mock_mound.add_node.return_value = "node-full"
        saved_node = MockNode(
            id="node-full",
            content="Full content",
            node_type="claim",
            confidence=0.9,
            topics=["topic1", "topic2"],
            metadata={"key": "value"},
        )
        mock_mound.get_node.return_value = saved_node

        body = json.dumps(
            {
                "content": "Full content",
                "node_type": "claim",
                "confidence": 0.9,
                "workspace_id": "ws-custom",
                "topics": ["topic1", "topic2"],
                "metadata": {"key": "value"},
                "tier": "fast",
                "source": {
                    "type": "debate",
                    "id": "debate-123",
                    "debate_id": "debate-123",
                },
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_node(http_handler)

        assert result.status_code == 201
        data = parse_response(result)
        assert data["id"] == "node-full"
        assert data["content"] == "Full content"
        assert data["node_type"] == "claim"

    def test_create_node_minimal(self, mock_mound, mock_user):
        """Test node creation with minimal required fields."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        mock_mound.add_node.return_value = "node-minimal"
        saved_node = MockNode(id="node-minimal", content="Minimal content")
        mock_mound.get_node.return_value = saved_node

        body = json.dumps({"content": "Minimal content"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_node(http_handler)

        assert result.status_code == 201

    def test_create_node_all_valid_types(self, mock_mound, mock_user):
        """Test node creation for all valid node types."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)

        valid_types = ["fact", "claim", "memory", "evidence", "consensus", "entity"]

        for node_type in valid_types:
            mock_mound.add_node.return_value = f"node-{node_type}"
            saved_node = MockNode(id=f"node-{node_type}", content=f"Content for {node_type}")
            mock_mound.get_node.return_value = saved_node

            body = json.dumps(
                {"content": f"Content for {node_type}", "node_type": node_type}
            ).encode()
            http_handler = MockHandler(body=body)

            result = handler._handle_create_node(http_handler)

            assert result.status_code == 201, f"Failed for node_type: {node_type}"

    def test_create_node_invalid_type(self, mock_mound, mock_user):
        """Test node creation with invalid node type."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)

        body = json.dumps({"content": "Test", "node_type": "invalid_type"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_node(http_handler)

        assert result.status_code == 400
        assert "Invalid node_type" in parse_response(result)["error"]

    def test_create_node_empty_content(self, mock_mound, mock_user):
        """Test node creation with empty content."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)

        body = json.dumps({"content": ""}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_node(http_handler)

        assert result.status_code == 400
        assert "required" in parse_response(result)["error"].lower()

    def test_create_node_invalid_source_type(self, mock_mound, mock_user):
        """Test node creation with invalid source type in provenance."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)

        body = json.dumps(
            {
                "content": "Test content",
                "source": {"type": "invalid_source_type", "id": "source-123"},
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_node(http_handler)

        assert result.status_code == 400
        assert "source type" in parse_response(result)["error"].lower()

    def test_get_node_by_id(self, mock_mound, mock_user):
        """Test getting a specific node by ID."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        node = MockNode(
            id="node-abc",
            content="Test content",
            node_type="fact",
            confidence=0.8,
            topics=["test"],
        )
        mock_mound.get_node.return_value = node

        result = handler._handle_get_node("node-abc")

        assert result.status_code == 200
        data = parse_response(result)
        assert data["id"] == "node-abc"
        assert data["content"] == "Test content"
        assert data["confidence"] == 0.8
        assert data["topics"] == ["test"]

    def test_get_node_not_found(self, mock_mound, mock_user):
        """Test getting a non-existent node."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        mock_mound.get_node.return_value = None

        result = handler._handle_get_node("nonexistent-node")

        assert result.status_code == 404

    def test_list_nodes_with_pagination(self, mock_mound, mock_user):
        """Test listing nodes with pagination."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        nodes = [MockNode(id=f"node-{i}", content=f"Content {i}") for i in range(25)]
        mock_mound.query_nodes.return_value = nodes

        result = handler._handle_list_nodes({"limit": ["25"], "offset": ["50"]})

        assert result.status_code == 200
        data = parse_response(result)
        assert data["count"] == 25
        assert data["limit"] == 25
        assert data["offset"] == 50

    def test_list_nodes_with_filters(self, mock_mound, mock_user):
        """Test listing nodes with type and confidence filters."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        mock_mound.query_nodes.return_value = []

        result = handler._handle_list_nodes(
            {
                "workspace_id": ["ws-123"],
                "node_types": ["fact,claim"],
                "min_confidence": ["0.7"],
                "tier": ["fast"],
            }
        )

        assert result.status_code == 200
        # Verify the call was made with correct parameters
        mock_mound.query_nodes.assert_called_once()


# =============================================================================
# Test Semantic Query Operations
# =============================================================================


class TestSemanticQueryOperations:
    """Tests for semantic query/search operations."""

    def test_semantic_query_basic(self, mock_mound, mock_user):
        """Test basic semantic query."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        nodes = [
            MockNode(id="node-1", content="Machine learning basics"),
            MockNode(id="node-2", content="Deep learning fundamentals"),
        ]
        result_obj = MockQueryResult(query="learning", nodes=nodes, total_count=2)
        mock_mound.query_semantic.return_value = result_obj

        body = json.dumps({"query": "learning"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["query"] == "learning"
        assert data["total_count"] == 2
        assert len(data["nodes"]) == 2

    def test_semantic_query_with_filters(self, mock_mound, mock_user):
        """Test semantic query with filters applied."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        result_obj = MockQueryResult(query="test", nodes=[], total_count=0)
        mock_mound.query_semantic.return_value = result_obj

        body = json.dumps(
            {
                "query": "test query",
                "workspace_id": "ws-specific",
                "limit": 5,
                "node_types": ["fact", "evidence"],
                "min_confidence": 0.8,
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 200
        mock_mound.query_semantic.assert_called_once()
        call_kwargs = mock_mound.query_semantic.call_args[1]
        assert call_kwargs["workspace_id"] == "ws-specific"
        assert call_kwargs["limit"] == 5
        assert call_kwargs["node_types"] == ["fact", "evidence"]
        assert call_kwargs["min_confidence"] == 0.8

    def test_semantic_query_empty_results(self, mock_mound, mock_user):
        """Test semantic query with no results."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        result_obj = MockQueryResult(query="nonexistent", nodes=[], total_count=0)
        mock_mound.query_semantic.return_value = result_obj

        body = json.dumps({"query": "nonexistent topic"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["total_count"] == 0
        assert len(data["nodes"]) == 0

    def test_semantic_query_missing_query(self, mock_mound, mock_user):
        """Test semantic query without query parameter."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)

        body = json.dumps({}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 400
        assert "required" in parse_response(result)["error"].lower()

    def test_semantic_query_invalid_json(self, mock_mound, mock_user):
        """Test semantic query with invalid JSON body."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)

        http_handler = MockHandler(body=b"not valid json")

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 400
        assert "invalid" in parse_response(result)["error"].lower()


# =============================================================================
# Test Relationship Operations
# =============================================================================


class TestRelationshipOperations:
    """Tests for relationship management operations."""

    def test_create_relationship(self, mock_mound, mock_user):
        """Test creating a relationship between nodes."""
        from aragora.server.handlers.knowledge_base.mound.relationships import (
            RelationshipOperationsMixin,
        )

        class RelHandler(RelationshipOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = RelHandler(mock_mound, mock_user)
        mock_mound.add_relationship.return_value = "rel-123"

        body = json.dumps(
            {
                "from_node_id": "node-a",
                "to_node_id": "node-b",
                "relationship_type": "supports",
                "strength": 0.9,
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_relationship(http_handler)

        assert result.status_code == 201
        data = parse_response(result)
        assert data["id"] == "rel-123"
        assert data["from_node_id"] == "node-a"
        assert data["to_node_id"] == "node-b"
        assert data["relationship_type"] == "supports"

    def test_create_relationship_all_types(self, mock_mound, mock_user):
        """Test creating relationships of all valid types."""
        from aragora.server.handlers.knowledge_base.mound.relationships import (
            RelationshipOperationsMixin,
        )

        class RelHandler(RelationshipOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = RelHandler(mock_mound, mock_user)
        valid_types = ["supports", "contradicts", "derived_from", "related_to", "supersedes"]

        for rel_type in valid_types:
            mock_mound.add_relationship.return_value = f"rel-{rel_type}"

            body = json.dumps(
                {
                    "from_node_id": "node-a",
                    "to_node_id": "node-b",
                    "relationship_type": rel_type,
                }
            ).encode()
            http_handler = MockHandler(body=body)

            result = handler._handle_create_relationship(http_handler)

            assert result.status_code == 201, f"Failed for relationship_type: {rel_type}"

    def test_create_relationship_invalid_type(self, mock_mound, mock_user):
        """Test creating relationship with invalid type."""
        from aragora.server.handlers.knowledge_base.mound.relationships import (
            RelationshipOperationsMixin,
        )

        class RelHandler(RelationshipOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = RelHandler(mock_mound, mock_user)

        body = json.dumps(
            {
                "from_node_id": "node-a",
                "to_node_id": "node-b",
                "relationship_type": "invalid_type",
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_create_relationship(http_handler)

        assert result.status_code == 400
        assert "Invalid relationship_type" in parse_response(result)["error"]

    def test_create_relationship_missing_fields(self, mock_mound, mock_user):
        """Test creating relationship with missing required fields."""
        from aragora.server.handlers.knowledge_base.mound.relationships import (
            RelationshipOperationsMixin,
        )

        class RelHandler(RelationshipOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = RelHandler(mock_mound, mock_user)

        # Missing from_node_id
        body = json.dumps({"to_node_id": "node-b", "relationship_type": "supports"}).encode()
        http_handler = MockHandler(body=body)
        result = handler._handle_create_relationship(http_handler)
        assert result.status_code == 400
        assert "from_node_id" in parse_response(result)["error"]

        # Missing to_node_id
        body = json.dumps({"from_node_id": "node-a", "relationship_type": "supports"}).encode()
        http_handler = MockHandler(body=body)
        result = handler._handle_create_relationship(http_handler)
        assert result.status_code == 400
        assert "to_node_id" in parse_response(result)["error"]

        # Missing relationship_type
        body = json.dumps({"from_node_id": "node-a", "to_node_id": "node-b"}).encode()
        http_handler = MockHandler(body=body)
        result = handler._handle_create_relationship(http_handler)
        assert result.status_code == 400
        assert "relationship_type" in parse_response(result)["error"]

    def test_get_node_relationships(self, mock_mound, mock_user):
        """Test getting relationships for a node."""
        from aragora.server.handlers.knowledge_base.mound.relationships import (
            RelationshipOperationsMixin,
        )

        class RelHandler(RelationshipOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = RelHandler(mock_mound, mock_user)
        node = MockNode(id="node-123", content="Test")
        mock_mound.get_node.return_value = node

        relationships = [
            MockRelationship(
                id="rel-1",
                from_node_id="node-123",
                to_node_id="node-456",
                relationship_type="supports",
            ),
            MockRelationship(
                id="rel-2",
                from_node_id="node-789",
                to_node_id="node-123",
                relationship_type="derived_from",
            ),
        ]
        mock_mound.get_relationships.return_value = relationships

        result = handler._handle_get_node_relationships("node-123", {})

        assert result.status_code == 200
        data = parse_response(result)
        assert data["node_id"] == "node-123"
        assert data["count"] == 2
        assert len(data["relationships"]) == 2

    def test_get_node_relationships_with_direction(self, mock_mound, mock_user):
        """Test getting relationships filtered by direction."""
        from aragora.server.handlers.knowledge_base.mound.relationships import (
            RelationshipOperationsMixin,
        )

        class RelHandler(RelationshipOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = RelHandler(mock_mound, mock_user)
        node = MockNode(id="node-123", content="Test")
        mock_mound.get_node.return_value = node
        mock_mound.get_relationships.return_value = []

        result = handler._handle_get_node_relationships("node-123", {"direction": ["outgoing"]})

        assert result.status_code == 200
        data = parse_response(result)
        assert data["direction"] == "outgoing"


# =============================================================================
# Test Graph Operations
# =============================================================================


class TestGraphOperations:
    """Tests for graph traversal operations."""

    def test_graph_traversal(self, mock_mound, mock_user):
        """Test basic graph traversal from a node."""
        from aragora.server.handlers.knowledge_base.mound.graph import GraphOperationsMixin

        class GraphHandler(GraphOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = GraphHandler(mock_mound)
        nodes = [
            MockNode(id="node-1", content="Start node"),
            MockNode(id="node-2", content="Connected node 1"),
            MockNode(id="node-3", content="Connected node 2"),
        ]
        result_obj = MockGraphQueryResult(nodes=nodes)
        mock_mound.query_graph.return_value = result_obj

        # Note: The graph handler expects path format /api/knowledge/mound/graph/:id (no v1)
        # because it parses parts[4] as the node_id
        result = handler._handle_graph_traversal(
            "/api/knowledge/mound/graph/node-1", {"depth": ["2"], "max_nodes": ["50"]}
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["start_node_id"] == "node-1"
        assert data["count"] == 3
        assert data["depth"] == 2

    def test_graph_lineage(self, mock_mound, mock_user):
        """Test getting node lineage (derived_from chain)."""
        from aragora.server.handlers.knowledge_base.mound.graph import GraphOperationsMixin

        class GraphHandler(GraphOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = GraphHandler(mock_mound)
        nodes = [
            MockNode(id="node-1", content="Current"),
            MockNode(id="node-parent", content="Parent"),
            MockNode(id="node-grandparent", content="Grandparent"),
        ]
        edges = [
            MockEdge(from_id="node-1", to_id="node-parent", relationship_type="derived_from"),
            MockEdge(
                from_id="node-parent", to_id="node-grandparent", relationship_type="derived_from"
            ),
        ]
        result_obj = MockGraphQueryResult(nodes=nodes, edges=edges)
        mock_mound.query_graph.return_value = result_obj

        # Note: The graph handler expects path format /api/knowledge/mound/graph/:id/lineage (no v1)
        result = handler._handle_graph_lineage(
            "/api/knowledge/mound/graph/node-1/lineage", {"depth": ["5"]}
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["node_id"] == "node-1"
        assert "lineage" in data
        assert len(data["lineage"]["nodes"]) == 3
        assert len(data["lineage"]["edges"]) == 2

    def test_graph_related(self, mock_mound, mock_user):
        """Test getting related nodes."""
        from aragora.server.handlers.knowledge_base.mound.graph import GraphOperationsMixin

        class GraphHandler(GraphOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = GraphHandler(mock_mound)
        nodes = [
            MockNode(id="node-1", content="Center"),
            MockNode(id="node-2", content="Related 1"),
            MockNode(id="node-3", content="Related 2"),
        ]
        result_obj = MockGraphQueryResult(nodes=nodes)
        mock_mound.query_graph.return_value = result_obj

        # Note: The graph handler expects path format /api/knowledge/mound/graph/:id/related (no v1)
        result = handler._handle_graph_related(
            "/api/knowledge/mound/graph/node-1/related", {"limit": ["10"]}
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["node_id"] == "node-1"
        assert data["total"] == 2  # Excludes the center node

    def test_graph_traversal_no_mound(self, mock_user):
        """Test graph traversal when mound not available."""
        from aragora.server.handlers.knowledge_base.mound.graph import GraphOperationsMixin

        class GraphHandler(GraphOperationsMixin):
            def __init__(self):
                self.ctx = {}

            def _get_mound(self):
                return None

        handler = GraphHandler()

        result = handler._handle_graph_traversal("/api/knowledge/mound/graph/node-1", {})

        assert result.status_code == 503


# =============================================================================
# Test Staleness and Revalidation Operations
# =============================================================================


class TestStalenessOperations:
    """Tests for staleness detection and revalidation."""

    def test_get_stale_knowledge(self, mock_mound, mock_user):
        """Test getting stale knowledge items."""
        from aragora.server.handlers.knowledge_base.mound.staleness import (
            StalenessOperationsMixin,
        )

        class StalenessHandler(StalenessOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = StalenessHandler(mock_mound)
        stale_items = [
            MockStalenessCheck(
                node_id="node-1",
                staleness_score=0.8,
                reasons=["outdated", "low_confidence"],
                revalidation_recommended=True,
            ),
            MockStalenessCheck(
                node_id="node-2",
                staleness_score=0.6,
                reasons=["infrequent_access"],
                revalidation_recommended=False,
            ),
        ]
        mock_mound.get_stale_knowledge.return_value = stale_items

        result = handler._handle_get_stale(
            {"workspace_id": ["ws-123"], "threshold": ["0.5"], "limit": ["100"]}
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["total"] == 2
        assert len(data["stale_items"]) == 2
        assert data["stale_items"][0]["staleness_score"] == 0.8
        assert data["stale_items"][0]["revalidation_recommended"] is True

    def test_revalidate_node(self, mock_mound, mock_user):
        """Test revalidating a specific node."""
        from aragora.server.handlers.knowledge_base.mound.staleness import (
            StalenessOperationsMixin,
        )

        class StalenessHandler(StalenessOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = StalenessHandler(mock_mound)
        mock_mound.mark_validated.return_value = None

        body = json.dumps({"validator": "human_review", "confidence": 0.9}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_revalidate_node("node-123", http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["node_id"] == "node-123"
        assert data["validated"] is True
        assert data["validator"] == "human_review"
        assert data["new_confidence"] == 0.9

    def test_schedule_revalidation(self, mock_mound, mock_user):
        """Test scheduling batch revalidation."""
        from aragora.server.handlers.knowledge_base.mound.staleness import (
            StalenessOperationsMixin,
        )

        class StalenessHandler(StalenessOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = StalenessHandler(mock_mound)
        mock_mound.schedule_revalidation.return_value = ["node-1", "node-2", "node-3"]

        body = json.dumps({"node_ids": ["node-1", "node-2", "node-3"], "priority": "high"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_schedule_revalidation(http_handler)

        assert result.status_code == 202
        data = parse_response(result)
        assert data["count"] == 3
        assert data["priority"] == "high"

    def test_schedule_revalidation_invalid_priority(self, mock_mound, mock_user):
        """Test scheduling with invalid priority."""
        from aragora.server.handlers.knowledge_base.mound.staleness import (
            StalenessOperationsMixin,
        )

        class StalenessHandler(StalenessOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = StalenessHandler(mock_mound)

        body = json.dumps({"node_ids": ["node-1"], "priority": "invalid"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_schedule_revalidation(http_handler)

        assert result.status_code == 400
        assert "priority" in parse_response(result)["error"].lower()


# =============================================================================
# Test Sync Operations
# =============================================================================


class TestSyncOperations:
    """Tests for sync operations with memory systems."""

    def test_sync_continuum_success(self, mock_mound, mock_user):
        """Test successful sync from ContinuumMemory."""
        from aragora.server.handlers.knowledge_base.mound.sync import SyncOperationsMixin

        class SyncHandler(SyncOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = SyncHandler(mock_mound)
        mock_mound.sync_continuum_incremental.return_value = MockSyncResult(nodes_synced=50)

        body = json.dumps({"workspace_id": "ws-123", "limit": 100}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_sync_continuum(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 50
        assert data["workspace_id"] == "ws-123"

    def test_sync_consensus_success(self, mock_mound, mock_user):
        """Test successful sync from ConsensusMemory."""
        from aragora.server.handlers.knowledge_base.mound.sync import SyncOperationsMixin

        class SyncHandler(SyncOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = SyncHandler(mock_mound)
        mock_mound.sync_consensus_incremental.return_value = MockSyncResult(nodes_synced=30)

        body = json.dumps({"workspace_id": "ws-456"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_sync_consensus(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 30

    @pytest.mark.xfail(strict=True, reason="fact sync closed until mound is org-scoped")
    def test_sync_facts_success(self, mock_mound, mock_user):
        """Test successful sync from FactStore."""
        from aragora.server.handlers.knowledge_base.mound.sync import SyncOperationsMixin

        class SyncHandler(SyncOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = SyncHandler(mock_mound)
        mock_mound.sync_facts_incremental.return_value = MockSyncResult(nodes_synced=75)

        body = json.dumps({"since": "2026-01-01T00:00:00Z"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_sync_facts(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 75

    def test_sync_no_mound(self, mock_user):
        """Test sync when mound not available."""
        from aragora.server.handlers.knowledge_base.mound.sync import SyncOperationsMixin

        class SyncHandler(SyncOperationsMixin):
            def __init__(self):
                self.ctx = {}

            def _get_mound(self):
                return None

        handler = SyncHandler()
        http_handler = MockHandler(body=b"")

        result = handler._handle_sync_continuum(http_handler)

        assert result.status_code == 503

    def test_sync_error_handling(self, mock_mound, mock_user):
        """Test sync error handling with fallback."""
        from aragora.server.handlers.knowledge_base.mound.sync import SyncOperationsMixin

        class SyncHandler(SyncOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = SyncHandler(mock_mound)
        mock_mound.sync_continuum_incremental.side_effect = AttributeError("Not connected")

        http_handler = MockHandler(body=b"")

        result = handler._handle_sync_continuum(http_handler)

        # Should return success with 0 synced when continuum not available
        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 0


# =============================================================================
# Test Deduplication Operations
# =============================================================================


class TestDeduplicationOperations:
    """Tests for deduplication operations."""

    @pytest.mark.asyncio
    async def test_get_duplicate_clusters(self, mock_mound, mock_user):
        """Test finding duplicate clusters."""
        from aragora.server.handlers.knowledge_base.mound.dedup import DedupOperationsMixin

        class DedupHandler(DedupOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = DedupHandler(mock_mound)
        clusters = [
            MockDuplicateCluster(
                cluster_id="cluster-1",
                primary_node_id="node-1",
                duplicates=[
                    MockDuplicateItem(
                        node_id="node-2", similarity=0.95, content_preview="Duplicate 1"
                    ),
                    MockDuplicateItem(
                        node_id="node-3", similarity=0.92, content_preview="Duplicate 2"
                    ),
                ],
            ),
        ]
        mock_mound.find_duplicates.return_value = clusters

        result = await handler.get_duplicate_clusters(
            workspace_id="ws-123", similarity_threshold=0.9, limit=100
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["clusters_found"] == 1
        assert len(data["clusters"]) == 1
        assert data["clusters"][0]["duplicate_count"] == 2

    @pytest.mark.asyncio
    async def test_get_dedup_report(self, mock_mound, mock_user):
        """Test generating deduplication report."""
        from aragora.server.handlers.knowledge_base.mound.dedup import DedupOperationsMixin

        class DedupHandler(DedupOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = DedupHandler(mock_mound)
        report = MockDedupReport(
            workspace_id="ws-123",
            generated_at=datetime.now(),
            total_nodes_analyzed=1000,
            duplicate_clusters_found=15,
            estimated_reduction_percent=5.5,
            clusters=[],
        )
        mock_mound.generate_dedup_report.return_value = report

        result = await handler.get_dedup_report(workspace_id="ws-123")

        assert result.status_code == 200
        data = parse_response(result)
        assert data["total_nodes_analyzed"] == 1000
        assert data["duplicate_clusters_found"] == 15
        assert data["estimated_reduction_percent"] == 5.5

    @pytest.mark.asyncio
    async def test_merge_duplicate_cluster(self, mock_mound, mock_user):
        """Test merging a duplicate cluster."""
        from aragora.server.handlers.knowledge_base.mound.dedup import DedupOperationsMixin

        class DedupHandler(DedupOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = DedupHandler(mock_mound)
        merge_result = MockMergeResult(
            kept_node_id="node-1",
            merged_node_ids=["node-2", "node-3"],
            archived_count=2,
            updated_relationships=5,
        )
        mock_mound.merge_duplicates.return_value = merge_result

        result = await handler.merge_duplicate_cluster(
            workspace_id="ws-123",
            cluster_id="cluster-1",
            primary_node_id="node-1",
            archive=True,
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["success"] is True
        assert data["kept_node_id"] == "node-1"
        assert data["archived_count"] == 2

    @pytest.mark.asyncio
    async def test_auto_merge_exact_duplicates(self, mock_mound, mock_user):
        """Test auto-merging exact duplicates."""
        from aragora.server.handlers.knowledge_base.mound.dedup import DedupOperationsMixin

        class DedupHandler(DedupOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = DedupHandler(mock_mound)
        mock_mound.auto_merge_exact_duplicates.return_value = {
            "dry_run": False,
            "duplicates_found": 10,
            "merges_performed": 10,
            "details": [],
        }

        result = await handler.auto_merge_exact_duplicates(workspace_id="ws-123", dry_run=False)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["duplicates_found"] == 10
        assert data["merges_performed"] == 10


# =============================================================================
# Test Pruning Operations
# =============================================================================


class TestPruningOperations:
    """Tests for pruning operations."""

    @pytest.mark.asyncio
    async def test_get_prunable_items(self, mock_mound, mock_user):
        """Test getting prunable items."""
        from aragora.server.handlers.knowledge_base.mound.pruning import PruningOperationsMixin

        class PruningHandler(PruningOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = PruningHandler(mock_mound)
        items = [
            MockPrunableItem(
                node_id="node-1",
                content_preview="Old content",
                staleness_score=0.95,
                confidence=0.3,
                prune_reason="stale",
            ),
            MockPrunableItem(
                node_id="node-2",
                content_preview="Low confidence",
                staleness_score=0.88,
                confidence=0.1,
                prune_reason="low_confidence",
            ),
        ]
        mock_mound.get_prunable_items.return_value = items

        result = await handler.get_prunable_items(
            workspace_id="ws-123",
            staleness_threshold=0.8,
            min_age_days=30,
            limit=100,
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["items_found"] == 2
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_execute_prune(self, mock_mound, mock_user):
        """Test executing prune on items."""
        from aragora.server.handlers.knowledge_base.mound.pruning import PruningOperationsMixin

        class PruningHandler(PruningOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = PruningHandler(mock_mound)
        prune_result = MockPruneResult(
            workspace_id="ws-123",
            executed_at=datetime.now(),
            items_analyzed=3,
            items_pruned=3,
            items_archived=3,
            pruned_item_ids=["node-1", "node-2", "node-3"],
        )
        mock_mound.prune_items.return_value = prune_result

        result = await handler.execute_prune(
            workspace_id="ws-123",
            item_ids=["node-1", "node-2", "node-3"],
            action="archive",
            reason="manual_cleanup",
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["success"] is True
        assert data["items_pruned"] == 3
        assert data["items_archived"] == 3

    @pytest.mark.asyncio
    async def test_execute_prune_invalid_action(self, mock_mound, mock_user):
        """Test pruning with invalid action."""
        from aragora.server.handlers.knowledge_base.mound.pruning import PruningOperationsMixin

        class PruningHandler(PruningOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = PruningHandler(mock_mound)

        result = await handler.execute_prune(
            workspace_id="ws-123",
            item_ids=["node-1"],
            action="invalid_action",
            reason="test",
        )

        assert result.status_code == 400
        assert "Invalid action" in parse_response(result)["error"]

    @pytest.mark.asyncio
    async def test_auto_prune_dry_run(self, mock_mound, mock_user):
        """Test auto-prune in dry-run mode."""
        from aragora.server.handlers.knowledge_base.mound.pruning import PruningOperationsMixin

        class PruningHandler(PruningOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = PruningHandler(mock_mound)
        prune_result = MockPruneResult(
            workspace_id="ws-123",
            executed_at=datetime.now(),
            items_analyzed=100,
            items_pruned=15,
        )
        mock_mound.auto_prune.return_value = prune_result

        result = await handler.auto_prune(
            workspace_id="ws-123",
            staleness_threshold=0.9,
            min_age_days=60,
            action="archive",
            dry_run=True,
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["dry_run"] is True
        assert data["items_analyzed"] == 100

    @pytest.mark.asyncio
    async def test_restore_pruned_item(self, mock_mound, mock_user):
        """Test restoring a pruned item."""
        from aragora.server.handlers.knowledge_base.mound.pruning import PruningOperationsMixin

        class PruningHandler(PruningOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = PruningHandler(mock_mound)
        mock_mound.restore_pruned_item.return_value = True

        result = await handler.restore_pruned_item(workspace_id="ws-123", node_id="node-1")

        assert result.status_code == 200
        data = parse_response(result)
        assert data["success"] is True
        assert data["node_id"] == "node-1"

    @pytest.mark.asyncio
    async def test_restore_pruned_item_not_found(self, mock_mound, mock_user):
        """Test restoring non-existent pruned item."""
        from aragora.server.handlers.knowledge_base.mound.pruning import PruningOperationsMixin

        class PruningHandler(PruningOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = PruningHandler(mock_mound)
        mock_mound.restore_pruned_item.return_value = False

        result = await handler.restore_pruned_item(workspace_id="ws-123", node_id="nonexistent")

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_apply_confidence_decay(self, mock_mound, mock_user):
        """Test applying confidence decay."""
        from aragora.server.handlers.knowledge_base.mound.pruning import PruningOperationsMixin

        class PruningHandler(PruningOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = PruningHandler(mock_mound)
        mock_mound.apply_confidence_decay.return_value = 250

        result = await handler.apply_confidence_decay(
            workspace_id="ws-123", decay_rate=0.01, min_confidence=0.1
        )

        assert result.status_code == 200
        data = parse_response(result)
        assert data["success"] is True
        assert data["items_decayed"] == 250

    @pytest.mark.asyncio
    async def test_apply_confidence_decay_invalid_rate(self, mock_mound, mock_user):
        """Test applying confidence decay with invalid rate."""
        from aragora.server.handlers.knowledge_base.mound.pruning import PruningOperationsMixin

        class PruningHandler(PruningOperationsMixin):
            def __init__(self, mound):
                self._mound_instance = mound
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

        handler = PruningHandler(mock_mound)

        # Decay rate out of bounds
        result = await handler.apply_confidence_decay(
            workspace_id="ws-123", decay_rate=1.5, min_confidence=0.1
        )

        assert result.status_code == 400
        assert "decay_rate" in parse_response(result)["error"]


# =============================================================================
# Test Mound Statistics
# =============================================================================


class TestMoundStatistics:
    """Tests for mound statistics operations."""

    def test_get_mound_stats(self, mock_mound, mock_user):
        """Test getting mound statistics."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        stats = {
            "total_nodes": 5000,
            "by_type": {
                "fact": 2000,
                "claim": 1500,
                "memory": 1000,
                "evidence": 300,
                "consensus": 200,
            },
            "by_tier": {
                "fast": 500,
                "medium": 1500,
                "slow": 2500,
                "glacial": 500,
            },
            "total_relationships": 12000,
            "avg_confidence": 0.72,
        }
        mock_mound.get_stats.return_value = stats

        result = handler._handle_mound_stats({})

        assert result.status_code == 200
        data = parse_response(result)
        assert data["total_nodes"] == 5000
        assert data["by_type"]["fact"] == 2000
        assert data["total_relationships"] == 12000


# =============================================================================
# Test Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling across operations."""

    def test_mound_unavailable_error(self, mock_user):
        """Test handling when mound is unavailable."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, user):
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return None

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_user)

        body = json.dumps({"query": "test"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 503
        assert "not available" in parse_response(result)["error"].lower()

    def test_query_exception_handling(self, mock_mound, mock_user):
        """Test handling exceptions during query."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)
        mock_mound.query_semantic.side_effect = ValueError("Database connection failed")

        body = json.dumps({"query": "test"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 500

    def test_invalid_json_body(self, mock_mound, mock_user):
        """Test handling invalid JSON in request body."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)

        http_handler = MockHandler(body=b"{{invalid json")

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 400
        assert "invalid" in parse_response(result)["error"].lower()


# =============================================================================
# Test Adapter Integration
# =============================================================================


class TestAdapterIntegration:
    """Tests for adapter selection and multi-adapter queries."""

    def test_query_across_workspaces(self, mock_mound, mock_user):
        """Test querying across multiple workspaces via adapters."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)

        # Test with specific workspace
        nodes_ws1 = [MockNode(id="node-ws1", content="Workspace 1 content", workspace_id="ws-1")]
        result_obj = MockQueryResult(query="test", nodes=nodes_ws1, total_count=1)
        mock_mound.query_semantic.return_value = result_obj

        body = json.dumps({"query": "test", "workspace_id": "ws-1"}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 200
        mock_mound.query_semantic.assert_called_once()
        call_kwargs = mock_mound.query_semantic.call_args[1]
        assert call_kwargs["workspace_id"] == "ws-1"

    def test_multi_type_query(self, mock_mound, mock_user):
        """Test querying multiple node types."""
        from aragora.server.handlers.knowledge_base.mound.nodes import NodeOperationsMixin

        class NodeHandler(NodeOperationsMixin):
            def __init__(self, mound, user):
                self._mound_instance = mound
                self._user = user
                self.ctx = {}

            def _get_mound(self):
                return self._mound_instance

            def require_auth_or_error(self, handler):
                return self._user, None

        handler = NodeHandler(mock_mound, mock_user)

        nodes = [
            MockNode(id="fact-1", content="A fact", node_type="fact"),
            MockNode(id="claim-1", content="A claim", node_type="claim"),
            MockNode(id="evidence-1", content="Evidence", node_type="evidence"),
        ]
        result_obj = MockQueryResult(query="test", nodes=nodes, total_count=3)
        mock_mound.query_semantic.return_value = result_obj

        body = json.dumps({"query": "test", "node_types": ["fact", "claim", "evidence"]}).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_mound_query(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["total_count"] == 3

        # Verify node types in response
        node_types = [n["node_type"] for n in data["nodes"]]
        assert "fact" in node_types
        assert "claim" in node_types
        assert "evidence" in node_types
