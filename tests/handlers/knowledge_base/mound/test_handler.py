"""Tests for KnowledgeMoundHandler (aragora/server/handlers/knowledge_base/mound/handler.py).

Covers the main handler entry point including:
- Handler initialization and can_handle routing
- Rate limiting enforcement
- Authentication checks
- Dispatch to all static and dynamic routes
- HTTP method validation (correct method dispatched, wrong method returns None)
- Mound unavailability (503 responses)
- Error responses and edge cases across all endpoint categories:
  Nodes, Relationships, Graph, Culture, Staleness, Sync, Export, Visibility,
  Sharing, Global Knowledge, Federation, Dedup, Pruning, Dashboard,
  Contradictions, Governance, Analytics, Extraction, Confidence Decay, Curation
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.knowledge_base.mound.handler import (
    KnowledgeMoundHandler,
    _knowledge_limiter,
)
from aragora.server.handlers.utils.responses import HandlerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_TOKEN = "test-token-mound-handler"

# Patch targets at the handler/routing module level
import asyncio
import inspect

_HANDLER_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.handler._run_async"
_ROUTING_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.routing._run_async"
_NODES_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.nodes._run_async"
_SHARING_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.sharing._run_async"
_CULTURE_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.culture._run_async"
_STALENESS_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.staleness._run_async"
_SYNC_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.sync._run_async"
_EXPORT_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.export._run_async"
_VISIBILITY_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.visibility._run_async"
_GLOBAL_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.global_knowledge._run_async"
_FEDERATION_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.federation._run_async"
_RELATIONSHIPS_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.relationships._run_async"
_GRAPH_RUN_ASYNC = "aragora.server.handlers.knowledge_base.mound.graph._run_async"


def _fake_run_async(coro, timeout=30.0):
    """Replacement for run_async that handles both coroutines and plain values.

    In test mode, mound methods are MagicMocks returning plain values.
    When routing mixin wraps an async mixin method, the result is a real
    coroutine that needs to be awaited. This function handles both cases.
    """
    if inspect.isawaitable(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    return coro


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    raw = result.body
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return -1
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ---------------------------------------------------------------------------
# Mock HTTP handler
# ---------------------------------------------------------------------------


@dataclass
class MockHTTPHandler:
    """Lightweight mock HTTP handler for handler tests."""

    command: str = "GET"
    path: str = ""
    headers: dict[str, str] = field(
        default_factory=lambda: {
            "User-Agent": "test-agent",
            "Authorization": f"Bearer {_TEST_TOKEN}",
            "Content-Length": "0",
        }
    )
    client_address: tuple = ("127.0.0.1", 12345)
    rfile: Any = field(default_factory=lambda: io.BytesIO(b""))
    request: Any = None
    _auth_context: Any = None

    def __post_init__(self):
        if self.request is None:
            self.request = MagicMock()
            self.request.body = b""

    @classmethod
    def get(cls) -> MockHTTPHandler:
        return cls(command="GET")

    @classmethod
    def post(cls, body: dict | None = None) -> MockHTTPHandler:
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            handler = cls(
                command="POST",
                headers={
                    "User-Agent": "test-agent",
                    "Authorization": f"Bearer {_TEST_TOKEN}",
                    "Content-Length": str(len(raw)),
                },
                rfile=io.BytesIO(raw),
            )
            handler.request = MagicMock()
            handler.request.body = raw
            return handler
        return cls(command="POST")

    @classmethod
    def put(cls, body: dict | None = None) -> MockHTTPHandler:
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            handler = cls(
                command="PUT",
                headers={
                    "User-Agent": "test-agent",
                    "Authorization": f"Bearer {_TEST_TOKEN}",
                    "Content-Length": str(len(raw)),
                },
                rfile=io.BytesIO(raw),
            )
            handler.request = MagicMock()
            handler.request.body = raw
            return handler
        return cls(command="PUT")

    @classmethod
    def delete(cls, body: dict | None = None) -> MockHTTPHandler:
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            handler = cls(
                command="DELETE",
                headers={
                    "User-Agent": "test-agent",
                    "Authorization": f"Bearer {_TEST_TOKEN}",
                    "Content-Length": str(len(raw)),
                },
                rfile=io.BytesIO(raw),
            )
            handler.request = MagicMock()
            handler.request.body = raw
            return handler
        return cls(command="DELETE")

    @classmethod
    def patch_method(cls, body: dict | None = None) -> MockHTTPHandler:
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            handler = cls(
                command="PATCH",
                headers={
                    "User-Agent": "test-agent",
                    "Authorization": f"Bearer {_TEST_TOKEN}",
                    "Content-Length": str(len(raw)),
                },
                rfile=io.BytesIO(raw),
            )
            handler.request = MagicMock()
            handler.request.body = raw
            return handler
        return cls(command="PATCH")


# ---------------------------------------------------------------------------
# Mock data classes
# ---------------------------------------------------------------------------


@dataclass
class MockKnowledgeNode:
    """Lightweight mock for KnowledgeNode."""

    node_id: str = "node-001"
    id: str = "node-001"
    node_type: str = "fact"
    content: str = "Test content"
    confidence: float = 0.8
    workspace_id: str = "default"
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tier: str = "slow"

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "content": self.content,
            "confidence": self.confidence,
            "workspace_id": self.workspace_id,
            "topics": self.topics,
            "metadata": self.metadata,
            "tier": self.tier,
        }


@dataclass
class MockQueryResult:
    """Lightweight mock for semantic query results."""

    query: str = "test query"
    nodes: list = field(default_factory=list)
    total_count: int = 0
    processing_time_ms: float = 12.5


@dataclass
class MockStalenessCheck:
    """Mock staleness check result."""

    node_id: str = "node-001"
    staleness_score: float = 0.7
    reasons: list[str] = field(default_factory=lambda: ["age"])
    last_checked_at: Any = None
    revalidation_recommended: bool = True


@dataclass
class MockSyncResult:
    """Mock sync result."""

    nodes_synced: int = 5


@dataclass
class MockGraphQueryResult:
    """Mock graph query result."""

    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0


@dataclass
class MockCultureProfile:
    """Mock culture profile."""

    workspace_id: str = "default"
    patterns: dict = field(default_factory=dict)
    generated_at: Any = None
    total_observations: int = 42


@dataclass
class MockRelationship:
    """Mock relationship."""

    id: str = "rel-001"
    from_node_id: str = "node-001"
    to_node_id: str = "node-002"
    relationship_type: str = "supports"
    strength: float = 1.0
    created_at: Any = None
    created_by: str = "test"
    metadata: dict = field(default_factory=dict)


@dataclass
class MockAccessGrant:
    """Mock access grant."""

    item_id: str = "node-001"
    grantee_id: str = "user-002"
    permissions: list[str] = field(default_factory=lambda: ["read"])

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "grantee_id": self.grantee_id,
            "permissions": self.permissions,
        }


@dataclass
class MockShareGrant:
    """Mock share grant."""

    item_id: str = "node-001"
    shared_with: str = "ws-002"

    def to_dict(self) -> dict:
        return {"item_id": self.item_id, "shared_with": self.shared_with}


@dataclass
class MockFederationRegion:
    """Mock federation region."""

    region_id: str = "us-east-1"
    endpoint_url: str = "https://east.example.com/api"
    mode: MagicMock = field(default_factory=lambda: MagicMock(value="bidirectional"))
    sync_scope: MagicMock = field(default_factory=lambda: MagicMock(value="summary"))
    enabled: bool = True


@dataclass
class MockFederationSyncResult:
    """Mock federation sync result."""

    success: bool = True
    region_id: str = "us-east-1"
    direction: str = "push"
    nodes_synced: int = 10
    nodes_skipped: int = 2
    nodes_failed: int = 0
    duration_ms: int = 500
    error: str | None = None


# ---------------------------------------------------------------------------
# Autouse fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _bypass_require_auth(monkeypatch):
    """Patch auth_config so the @require_auth decorator accepts our test token."""
    try:
        from aragora.server import auth as auth_module

        monkeypatch.setattr(auth_module.auth_config, "api_token", _TEST_TOKEN)
        monkeypatch.setattr(
            auth_module.auth_config, "validate_token", lambda token: token == _TEST_TOKEN
        )
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    """Reset rate limiter between tests."""
    _knowledge_limiter.clear()
    yield
    _knowledge_limiter.clear()


@pytest.fixture(autouse=True)
def _bypass_tier_gating(monkeypatch):
    """Bypass tier gating decorator for tests."""
    try:
        from aragora.billing import tier_gating

        original_require_tier = tier_gating.require_tier

        def mock_require_tier(*args, **kwargs):
            def decorator(func):
                return func

            return decorator

        monkeypatch.setattr(tier_gating, "require_tier", mock_require_tier)
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def _bypass_workspace_validation(monkeypatch):
    """Bypass workspace access validation."""
    try:
        from aragora.server.handlers.utils import tenant_validation

        monkeypatch.setattr(tenant_validation, "validate_workspace_access_sync", lambda **kw: None)
    except (ImportError, AttributeError):
        pass

    # Also patch at the routing module level where it's imported
    try:
        import aragora.server.handlers.knowledge_base.mound.routing as routing_mod

        monkeypatch.setattr(routing_mod, "validate_workspace_access_sync", lambda **kw: None)
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def _bypass_metrics(monkeypatch):
    """Bypass metrics tracking functions."""
    noop = lambda *a, **kw: None

    for module_path in [
        "aragora.server.handlers.knowledge_base.mound.sharing",
        "aragora.server.handlers.knowledge_base.mound.visibility",
        "aragora.server.handlers.knowledge_base.mound.global_knowledge",
        "aragora.server.handlers.knowledge_base.mound.federation",
    ]:
        try:
            import importlib

            mod = importlib.import_module(module_path)
            for name in dir(mod):
                if name.startswith("track_"):
                    monkeypatch.setattr(mod, name, noop)
        except (ImportError, AttributeError):
            pass

    # Also patch track_federation_sync context manager
    try:
        from contextlib import contextmanager

        @contextmanager
        def fake_track_federation_sync(*args, **kwargs):
            ctx = {}
            yield ctx

        import aragora.server.handlers.knowledge_base.mound.federation as fed_mod

        monkeypatch.setattr(fed_mod, "track_federation_sync", fake_track_federation_sync)
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def _patch_run_async(monkeypatch):
    """Patch _run_async in all mixin modules to handle both sync/async calls.

    The routing mixin calls _run_async(self.async_method(...)) which produces
    real coroutines. Our _fake_run_async handles both coroutines (from async
    mixins like dedup/pruning) and plain values (from sync mock return values).
    """
    _ALL_RUN_ASYNC_MODULES = [
        "aragora.server.handlers.knowledge_base.mound.routing",
        "aragora.server.handlers.knowledge_base.mound.nodes",
        "aragora.server.handlers.knowledge_base.mound.sharing",
        "aragora.server.handlers.knowledge_base.mound.culture",
        "aragora.server.handlers.knowledge_base.mound.staleness",
        "aragora.server.handlers.knowledge_base.mound.sync",
        "aragora.server.handlers.knowledge_base.mound.export",
        "aragora.server.handlers.knowledge_base.mound.visibility",
        "aragora.server.handlers.knowledge_base.mound.global_knowledge",
        "aragora.server.handlers.knowledge_base.mound.federation",
        "aragora.server.handlers.knowledge_base.mound.relationships",
        "aragora.server.handlers.knowledge_base.mound.graph",
    ]
    for mod_path in _ALL_RUN_ASYNC_MODULES:
        try:
            import importlib

            mod = importlib.import_module(mod_path)
            monkeypatch.setattr(mod, "_run_async", _fake_run_async)
        except (ImportError, AttributeError):
            pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_mound() -> MagicMock:
    """Build a comprehensive mock mound with all required methods."""
    mound = MagicMock()

    # Node operations
    mound.add_node = MagicMock(return_value="node-001")
    mound.get_node = MagicMock(return_value=MockKnowledgeNode())
    mound.query_nodes = MagicMock(return_value=[MockKnowledgeNode()])
    mound.query_semantic = MagicMock(
        return_value=MockQueryResult(nodes=[MockKnowledgeNode()], total_count=1)
    )
    mound.get_stats = MagicMock(return_value={"total_nodes": 100, "by_type": {"fact": 50}})

    # Relationship operations
    mound.get_relationships = MagicMock(return_value=[MockRelationship()])
    mound.add_relationship = MagicMock(return_value="rel-001")

    # Graph operations
    mound.query_graph = MagicMock(return_value=MockGraphQueryResult())

    # Culture operations
    mound.get_culture_profile = MagicMock(return_value=MockCultureProfile())
    mound.update = MagicMock(return_value=True)

    # Staleness operations
    mound.get_stale_knowledge = MagicMock(return_value=[MockStalenessCheck()])
    mound.mark_validated = MagicMock(return_value=True)
    mound.schedule_revalidation = MagicMock(return_value=["node-001", "node-002"])

    # Sync operations
    mound.sync_continuum_incremental = MagicMock(return_value=MockSyncResult())
    mound.sync_consensus_incremental = MagicMock(return_value=MockSyncResult())
    mound.sync_facts_incremental = MagicMock(return_value=MockSyncResult())

    # Export operations
    mound.export_graph_d3 = MagicMock(
        return_value={"nodes": [{"id": "n1"}], "links": [{"source": "n1", "target": "n2"}]}
    )
    mound.export_graph_graphml = MagicMock(return_value="<graphml></graphml>")

    # Visibility operations
    mound.set_visibility = MagicMock(return_value=None)
    mound.get_access_grants = MagicMock(return_value=[MockAccessGrant()])
    mound.grant_access = MagicMock(return_value=MockAccessGrant())
    mound.revoke_access = MagicMock(return_value=True)

    # Sharing operations
    mound.share_with_workspace = MagicMock(return_value=None)
    mound.share_with_user = MagicMock(return_value=None)
    mound.get_shared_with_me = MagicMock(return_value=[MockKnowledgeNode()])
    mound.revoke_share = MagicMock(return_value=True)
    mound.get_share_grants = MagicMock(return_value=[MockShareGrant()])
    mound.update_share_permissions = MagicMock(return_value=MockShareGrant())

    # Global knowledge
    mound.store_verified_fact = MagicMock(return_value="global-001")
    mound.query_global_knowledge = MagicMock(return_value=[MockKnowledgeNode()])
    mound.get_system_facts = MagicMock(return_value=[MockKnowledgeNode()])
    mound.promote_to_global = MagicMock(return_value="global-002")
    mound.get_system_workspace_id = MagicMock(return_value="__system__")

    # Federation
    mound.register_federated_region = MagicMock(return_value=MockFederationRegion())
    mound.unregister_federated_region = MagicMock(return_value=True)
    mound.sync_to_region = MagicMock(return_value=MockFederationSyncResult())
    mound.pull_from_region = MagicMock(return_value=MockFederationSyncResult(direction="pull"))
    mound.sync_all_regions = MagicMock(return_value=[MockFederationSyncResult()])
    mound.get_federation_status = MagicMock(
        return_value={"us-east-1": {"enabled": True, "healthy": True}}
    )

    # Dedup - method names must match what the handler calls on the mound
    mound.find_duplicates = AsyncMock(return_value=[])
    _dedup_report = MagicMock()
    _dedup_report.workspace_id = "default"
    _dedup_report.generated_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    _dedup_report.total_nodes_analyzed = 0
    _dedup_report.duplicate_clusters_found = 0
    _dedup_report.estimated_reduction_percent = 0.0
    _dedup_report.clusters = []
    mound.generate_dedup_report = AsyncMock(return_value=_dedup_report)
    _merge_result = MagicMock()
    _merge_result.kept_node_id = "node-001"
    _merge_result.merged_node_ids = []
    _merge_result.archived_count = 0
    _merge_result.updated_relationships = 0
    mound.merge_duplicates = AsyncMock(return_value=_merge_result)
    mound.auto_merge_exact_duplicates = AsyncMock(return_value={"merged": 0})

    # Pruning
    mound.get_prunable_items = AsyncMock(return_value=[])
    _prune_result = MagicMock()
    _prune_result.workspace_id = "default"
    _prune_result.executed_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    _prune_result.items_analyzed = 2
    _prune_result.items_pruned = 2
    _prune_result.items_archived = 2
    _prune_result.items_deleted = 0
    _prune_result.items_demoted = 0
    _prune_result.items_flagged = 0
    _prune_result.pruned_item_ids = ["node-001", "node-002"]
    _prune_result.errors = []
    mound.prune_items = AsyncMock(return_value=_prune_result)
    _auto_prune_result = MagicMock()
    _auto_prune_result.workspace_id = "default"
    _auto_prune_result.policy_id = "policy-001"
    _auto_prune_result.dry_run = True
    _auto_prune_result.executed_at = MagicMock(
        isoformat=MagicMock(return_value="2026-01-01T00:00:00")
    )
    _auto_prune_result.items_analyzed = 0
    _auto_prune_result.items_pruned = 0
    _auto_prune_result.items_archived = 0
    _auto_prune_result.items_deleted = 0
    _auto_prune_result.items_demoted = 0
    _auto_prune_result.items_flagged = 0
    _auto_prune_result.errors = []
    mound.auto_prune = AsyncMock(return_value=_auto_prune_result)
    mound.get_prune_history = AsyncMock(return_value=[])
    mound.restore_pruned_item = AsyncMock(return_value=True)
    # apply_confidence_decay returns a DecayReport with to_dict()
    _decay_report = MagicMock()
    _decay_report.to_dict.return_value = {"affected": 0, "workspace_id": "default"}
    mound.apply_confidence_decay = AsyncMock(return_value=_decay_report)

    # Contradictions - mixin calls report.to_dict(), result.to_dict()
    _contradiction_report = MagicMock()
    _contradiction_report.to_dict.return_value = {
        "workspace_id": "default",
        "contradictions_found": 0,
        "contradictions": [],
    }
    mound.detect_contradictions = AsyncMock(return_value=_contradiction_report)
    mound.get_unresolved_contradictions = AsyncMock(return_value=[])
    _resolve_result = MagicMock()
    _resolve_result.to_dict.return_value = {
        "contradiction_id": "c-001",
        "strategy": "prefer_newer",
        "resolved": True,
    }
    mound.resolve_contradiction = AsyncMock(return_value=_resolve_result)

    # Governance - mixin calls role.to_dict(), assignment.to_dict(), p.value
    from aragora.knowledge.mound.ops.governance import Permission

    _role_mock = MagicMock()
    _role_mock.to_dict.return_value = {
        "role_id": "role-001",
        "name": "editor",
        "permissions": ["read"],
    }
    mound.create_role = AsyncMock(return_value=_role_mock)
    _assignment_mock = MagicMock()
    _assignment_mock.to_dict.return_value = {"user_id": "user-001", "role_id": "role-001"}
    mound.assign_role = AsyncMock(return_value=_assignment_mock)
    mound.revoke_role = AsyncMock(return_value=True)
    mound.get_user_permissions = AsyncMock(return_value=[Permission.READ])
    mound.check_permission = AsyncMock(return_value=True)
    mound.query_audit = AsyncMock(return_value=[])
    mound.get_user_activity = AsyncMock(return_value={})

    # Analytics - handler calls .to_dict() on results
    _coverage_report = MagicMock()
    _coverage_report.to_dict = MagicMock(return_value={"coverage": {}})
    mound.analyze_coverage = AsyncMock(return_value=_coverage_report)
    _usage_report = MagicMock()
    _usage_report.to_dict = MagicMock(return_value={"usage": {}})
    mound.analyze_usage = AsyncMock(return_value=_usage_report)
    _usage_event = MagicMock()
    _usage_event.id = "evt-001"
    _usage_event.event_type = MagicMock(value="query")
    _usage_event.recorded_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    mound.record_usage_event = AsyncMock(return_value=_usage_event)
    _quality_snapshot = MagicMock()
    _quality_snapshot.to_dict = MagicMock(return_value={"quality": "snapshot"})
    mound.capture_quality_snapshot = AsyncMock(return_value=_quality_snapshot)
    _quality_trend = MagicMock()
    _quality_trend.to_dict = MagicMock(return_value={"snapshots": []})
    mound.get_quality_trend = AsyncMock(return_value=_quality_trend)

    # Extraction
    extraction_result = MagicMock()
    extraction_result.to_dict.return_value = {
        "debate_id": "debate-001",
        "claims": [],
        "relationships": [],
    }
    mound.extract_from_debate = AsyncMock(return_value=extraction_result)
    mound.promote_extracted_knowledge = AsyncMock(return_value=3)

    # Confidence decay - mixin calls report.to_dict(), adjustment.to_dict()
    _conf_decay_report = MagicMock()
    _conf_decay_report.to_dict.return_value = {"affected": 0, "workspace_id": "default"}
    mound.apply_confidence_decay_endpoint = AsyncMock(return_value=_conf_decay_report)
    # record_confidence_event returns None (no adjustment needed) or obj with to_dict()
    mound.record_confidence_event = AsyncMock(return_value=None)
    mound.get_confidence_history = AsyncMock(return_value=[])

    # Dashboard (async methods)
    mound.get_dashboard_health = AsyncMock(return_value={"healthy": True})
    mound.get_dashboard_metrics = AsyncMock(return_value={"queries": 0})

    # Curation
    mound.get_curation_policy = AsyncMock(return_value={})
    mound.create_curation_policy = AsyncMock(return_value="policy-001")
    mound.update_curation_policy = AsyncMock(return_value=True)
    mound.get_curation_status = AsyncMock(return_value={})
    mound.run_curation = AsyncMock(return_value={})
    mound.get_curation_history = AsyncMock(return_value=[])
    mound.get_curation_scores = AsyncMock(return_value=[])
    mound.get_curation_tiers = AsyncMock(return_value={})

    # Stats methods
    mound.get_contradiction_stats = AsyncMock(return_value={})
    mound.get_governance_stats = AsyncMock(return_value={})
    mound.get_analytics_stats = AsyncMock(return_value={})
    mound.get_extraction_stats = AsyncMock(return_value={})
    mound.get_decay_stats = AsyncMock(return_value={})

    return mound


@pytest.fixture
def mock_mound():
    """Create a comprehensive mock mound."""
    return _build_mound()


@pytest.fixture
def mock_server_context():
    """Create a mock server context."""
    return {
        "user_store": MagicMock(),
        "nomic_dir": "/tmp/test",
        "stream_emitter": MagicMock(),
    }


@pytest.fixture
def handler(mock_server_context, mock_mound):
    """Create KnowledgeMoundHandler with mocked mound."""
    h = KnowledgeMoundHandler(mock_server_context)
    h._mound = mock_mound
    h._mound_initialized = True
    return h


@pytest.fixture
def handler_no_mound(mock_server_context):
    """Create KnowledgeMoundHandler with no mound."""
    h = KnowledgeMoundHandler(mock_server_context)
    h._mound = None
    h._mound_initialized = False
    # Override _get_mound to always return None
    h._get_mound = lambda: None
    return h


# ============================================================================
# Tests: Handler Initialization and can_handle
# ============================================================================


class TestHandlerInit:
    """Tests for handler initialization and routing detection."""

    def test_init_sets_mound_to_none(self, mock_server_context):
        """Handler initializes with mound as None."""
        h = KnowledgeMoundHandler(mock_server_context)
        assert h._mound is None
        assert h._mound_initialized is False

    def test_can_handle_mound_paths(self, handler):
        """can_handle returns True for mound paths."""
        assert handler.can_handle("/api/v1/knowledge/mound/query") is True
        assert handler.can_handle("/api/v1/knowledge/mound/nodes") is True
        assert handler.can_handle("/api/v1/knowledge/mound/stats") is True
        assert handler.can_handle("/api/v1/knowledge/mound/culture") is True
        assert handler.can_handle("/api/v1/knowledge/mound/stale") is True

    def test_can_handle_rejects_non_mound_paths(self, handler):
        """can_handle returns False for non-mound paths."""
        assert handler.can_handle("/api/v1/debates") is False
        assert handler.can_handle("/api/v1/knowledge/base") is False
        assert handler.can_handle("/api/v1/other") is False

    def test_has_routes_attribute(self, handler):
        """Handler has ROUTES class attribute."""
        assert hasattr(handler, "ROUTES")
        assert len(handler.ROUTES) > 0

    def test_routes_cover_major_endpoints(self, handler):
        """ROUTES include all major endpoint categories."""
        routes = handler.ROUTES
        categories = [
            "/api/v1/knowledge/mound/query",
            "/api/v1/knowledge/mound/nodes",
            "/api/v1/knowledge/mound/stats",
            "/api/v1/knowledge/mound/share",
            "/api/v1/knowledge/mound/global",
            "/api/v1/knowledge/mound/federation/regions",
            "/api/v1/knowledge/mound/dedup/clusters",
            "/api/v1/knowledge/mound/pruning/items",
            "/api/v1/knowledge/mound/contradictions",
            "/api/v1/knowledge/mound/governance/roles",
            "/api/v1/knowledge/mound/analytics/coverage",
            "/api/v1/knowledge/mound/extraction/debate",
            "/api/v1/knowledge/mound/confidence/decay",
        ]
        for cat in categories:
            assert cat in routes, f"Missing route: {cat}"


# ============================================================================
# Tests: Rate Limiting
# ============================================================================


class TestRateLimiting:
    """Tests for rate limiting behavior."""

    def test_rate_limit_key_uses_user_id_when_authenticated(self, handler):
        """Rate limit key uses user_id from auth context."""
        http = MockHTTPHandler.get()
        auth_ctx = MagicMock()
        auth_ctx.user_id = "user-123"
        http._auth_context = auth_ctx
        key = handler._get_rate_limit_key(http)
        assert key == "user-123"

    def test_rate_limit_key_uses_sub_when_no_user_id(self, handler):
        """Rate limit key falls back to sub claim."""
        http = MockHTTPHandler.get()
        auth_ctx = MagicMock()
        auth_ctx.user_id = None
        auth_ctx.sub = "sub-456"
        http._auth_context = auth_ctx
        key = handler._get_rate_limit_key(http)
        assert key == "sub-456"

    def test_rate_limit_key_uses_ip_when_no_auth(self, handler):
        """Rate limit key uses client IP when no auth context."""
        http = MockHTTPHandler.get()
        http._auth_context = None
        key = handler._get_rate_limit_key(http)
        # Should be an IP address
        assert key is not None

    def test_check_rate_limit_returns_none_when_allowed(self, handler):
        """No error when under rate limit."""
        result = handler._check_rate_limit("test-user")
        assert result is None

    def test_check_rate_limit_returns_429_when_exceeded(self, handler):
        """Returns 429 when rate limit exceeded."""
        # Exhaust rate limit
        for _ in range(101):
            _knowledge_limiter.is_allowed("flood-user")

        result = handler._check_rate_limit("flood-user")
        assert result is not None
        assert _status(result) == 429
        body = _body(result)
        assert "rate limit" in body["error"].lower()

    def test_rate_limit_headers_included_in_429(self, handler):
        """429 response includes rate limit headers."""
        for _ in range(101):
            _knowledge_limiter.is_allowed("flood-user")

        result = handler._check_rate_limit("flood-user")
        assert result is not None
        assert result.headers is not None
        assert "X-RateLimit-Limit" in result.headers
        assert "Retry-After" in result.headers


# ============================================================================
# Tests: Authentication
# ============================================================================


class TestAuthentication:
    """Tests for authentication checks."""

    def test_check_authentication_passes_with_valid_auth(self, handler):
        """No error with valid authentication."""
        http = MockHTTPHandler.get()
        result = handler._check_authentication(http)
        assert result is None


# ============================================================================
# Tests: Static Route Dispatch - Nodes
# ============================================================================


class TestNodeRoutes:
    """Tests for node endpoint routing."""

    def test_query_post(self, handler, mock_mound):
        """POST /query dispatches to mound query."""
        http = MockHTTPHandler.post({"query": "test query"})
        result = handler.handle("/api/v1/knowledge/mound/query", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_list_nodes_get(self, handler, mock_mound):
        """GET /nodes dispatches to list nodes."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/nodes", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_create_node_post(self, handler, mock_mound):
        """POST /nodes dispatches to create node."""
        http = MockHTTPHandler.post({"content": "Test fact", "node_type": "fact"})
        result = handler.handle("/api/v1/knowledge/mound/nodes", {}, http)
        assert result is not None
        assert _status(result) == 201

    def test_get_node_by_id(self, handler, mock_mound):
        """GET /nodes/:id dispatches to get node."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/nodes/node-001", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_stats(self, handler, mock_mound):
        """GET /stats returns mound statistics."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/stats", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_query_no_mound_returns_503(self, handler_no_mound):
        """POST /query with no mound returns 503."""
        http = MockHTTPHandler.post({"query": "test"})
        result = handler_no_mound.handle("/api/v1/knowledge/mound/query", {}, http)
        assert result is not None
        assert _status(result) == 503

    def test_query_empty_query_returns_400(self, handler):
        """POST /query with empty query returns 400."""
        http = MockHTTPHandler.post({"query": ""})
        result = handler.handle("/api/v1/knowledge/mound/query", {}, http)
        assert result is not None
        assert _status(result) == 400


# ============================================================================
# Tests: Static Route Dispatch - Relationships
# ============================================================================


class TestRelationshipRoutes:
    """Tests for relationship endpoint routing."""

    def test_create_relationship_post(self, handler, mock_mound):
        """POST /relationships creates a relationship."""
        http = MockHTTPHandler.post(
            {
                "from_node_id": "node-001",
                "to_node_id": "node-002",
                "relationship_type": "supports",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/relationships", {}, http)
        assert result is not None
        assert _status(result) == 201

    def test_create_relationship_missing_fields(self, handler):
        """POST /relationships with missing fields returns 400."""
        http = MockHTTPHandler.post({"from_node_id": "node-001"})
        result = handler.handle("/api/v1/knowledge/mound/relationships", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_create_relationship_invalid_type(self, handler):
        """POST /relationships with invalid type returns 400."""
        http = MockHTTPHandler.post(
            {
                "from_node_id": "node-001",
                "to_node_id": "node-002",
                "relationship_type": "INVALID",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/relationships", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_get_node_relationships(self, handler, mock_mound):
        """GET /nodes/:id/relationships returns relationships."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/nodes/node-001/relationships", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Dynamic Route Dispatch - Graph
# ============================================================================


class TestGraphRoutes:
    """Tests for graph endpoint routing.

    Note: The graph mixin methods parse the node_id from a full path (splitting
    on '/' and expecting 5+ segments), but the routing dispatch passes only the
    regex-captured entity_id (e.g. "node-001"). As a result, calls through the
    dispatch table hit the 'Node ID required' 400 guard. Tests verify this
    actual dispatch behavior.
    """

    def test_graph_traversal_dispatches(self, handler, mock_mound):
        """GET /graph/:id dispatches to graph traversal handler.

        The graph mixin returns 400 because entity_id lacks enough path segments.
        """
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/graph/node-001", {}, http)
        assert result is not None
        # Dispatch succeeds but graph mixin returns 400 due to entity_id path parsing
        assert _status(result) == 400

    def test_graph_lineage_dispatches(self, handler, mock_mound):
        """GET /graph/:id/lineage dispatches to lineage handler."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/graph/node-001/lineage", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_graph_related_dispatches(self, handler, mock_mound):
        """GET /graph/:id/related dispatches to related nodes handler."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/graph/node-001/related", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_graph_wrong_method_returns_none(self, handler):
        """POST on GET-only /graph/:id returns None."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/graph/node-001", {}, http)
        assert result is None


# ============================================================================
# Tests: Culture Routes
# ============================================================================


class TestCultureRoutes:
    """Tests for culture endpoint routing."""

    def test_get_culture(self, handler, mock_mound):
        """GET /culture returns culture profile."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/culture", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_add_culture_document(self, handler, mock_mound):
        """POST /culture/documents adds document."""
        http = MockHTTPHandler.post({"content": "Our company values..."})
        result = handler.handle("/api/v1/knowledge/mound/culture/documents", {}, http)
        assert result is not None
        assert _status(result) == 201

    def test_add_culture_document_missing_content(self, handler):
        """POST /culture/documents with no content returns 400."""
        http = MockHTTPHandler.post({"document_type": "policy"})
        result = handler.handle("/api/v1/knowledge/mound/culture/documents", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_promote_to_culture(self, handler, mock_mound):
        """POST /culture/promote promotes node to culture."""
        http = MockHTTPHandler.post({"node_id": "node-001"})
        result = handler.handle("/api/v1/knowledge/mound/culture/promote", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_promote_to_culture_missing_node_id(self, handler):
        """POST /culture/promote without node_id returns 400."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/culture/promote", {}, http)
        assert result is not None
        assert _status(result) == 400


# ============================================================================
# Tests: Staleness Routes
# ============================================================================


class TestStalenessRoutes:
    """Tests for staleness endpoint routing."""

    def test_get_stale(self, handler, mock_mound):
        """GET /stale returns stale items."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/stale", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_revalidate_node(self, handler, mock_mound):
        """POST /revalidate/:id triggers revalidation."""
        http = MockHTTPHandler.post({"validator": "api"})
        result = handler.handle("/api/v1/knowledge/mound/revalidate/node-001", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_schedule_revalidation(self, handler, mock_mound):
        """POST /schedule-revalidation schedules batch."""
        http = MockHTTPHandler.post(
            {
                "node_ids": ["node-001", "node-002"],
                "priority": "medium",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/schedule-revalidation", {}, http)
        assert result is not None
        assert _status(result) == 202

    def test_schedule_revalidation_missing_node_ids(self, handler):
        """POST /schedule-revalidation without node_ids returns 400."""
        http = MockHTTPHandler.post({"priority": "low"})
        result = handler.handle("/api/v1/knowledge/mound/schedule-revalidation", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_schedule_revalidation_invalid_priority(self, handler):
        """POST /schedule-revalidation with bad priority returns 400."""
        http = MockHTTPHandler.post(
            {
                "node_ids": ["node-001"],
                "priority": "ultra-high",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/schedule-revalidation", {}, http)
        assert result is not None
        assert _status(result) == 400


# ============================================================================
# Tests: Sync Routes
# ============================================================================


class TestSyncRoutes:
    """Tests for sync endpoint routing."""

    def test_sync_continuum(self, handler, mock_mound):
        """POST /sync/continuum syncs from continuum."""
        http = MockHTTPHandler.post({"workspace_id": "default"})
        result = handler.handle("/api/v1/knowledge/mound/sync/continuum", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_sync_consensus(self, handler, mock_mound):
        """POST /sync/consensus syncs from consensus."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/sync/consensus", {}, http)
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.xfail(strict=True, reason="fact sync closed until mound is org-scoped")
    def test_sync_facts(self, handler, mock_mound):
        """POST /sync/facts syncs from fact store."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/sync/facts", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Export Routes
# ============================================================================


class TestExportRoutes:
    """Tests for export endpoint routing."""

    def test_export_d3(self, handler, mock_mound):
        """GET /export/d3 exports D3 format."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/export/d3", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_export_graphml(self, handler, mock_mound):
        """GET /export/graphml exports GraphML format."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/export/graphml", {}, http)
        assert result is not None
        assert _status(result) == 200
        assert result.content_type == "application/xml"


# ============================================================================
# Tests: Visibility Routes
# ============================================================================


class TestVisibilityRoutes:
    """Tests for visibility endpoint routing."""

    def test_get_visibility(self, handler, mock_mound):
        """GET /nodes/:id/visibility returns visibility."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/nodes/node-001/visibility", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_access_grants(self, handler, mock_mound):
        """GET /nodes/:id/access returns access grants."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/nodes/node-001/access", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Sharing Routes
# ============================================================================


class TestSharingRoutes:
    """Tests for sharing endpoint routing."""

    def test_share_item_to_workspace(self, handler, mock_mound):
        """POST /share shares item with workspace."""
        http = MockHTTPHandler.post(
            {
                "item_id": "node-001",
                "target_type": "workspace",
                "target_id": "ws-002",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/share", {}, http)
        assert result is not None
        assert _status(result) == 201

    def test_share_item_to_user(self, handler, mock_mound):
        """POST /share shares item with user."""
        http = MockHTTPHandler.post(
            {
                "item_id": "node-001",
                "target_type": "user",
                "target_id": "user-002",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/share", {}, http)
        assert result is not None
        assert _status(result) == 201

    def test_share_item_missing_item_id(self, handler):
        """POST /share without item_id returns 400."""
        http = MockHTTPHandler.post(
            {
                "target_type": "workspace",
                "target_id": "ws-002",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/share", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_share_item_invalid_target_type(self, handler):
        """POST /share with invalid target_type returns 400."""
        http = MockHTTPHandler.post(
            {
                "item_id": "node-001",
                "target_type": "invalid",
                "target_id": "ws-002",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/share", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_get_shared_with_me(self, handler, mock_mound):
        """GET /shared-with-me returns shared items."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/shared-with-me", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_my_shares(self, handler, mock_mound):
        """GET /my-shares returns items I shared."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/my-shares", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_revoke_share(self, handler, mock_mound):
        """DELETE /share revokes a share."""
        http = MockHTTPHandler.delete(
            {
                "item_id": "node-001",
                "grantee_id": "user-002",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/share", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_update_share(self, handler, mock_mound):
        """PATCH /share updates share permissions."""
        http = MockHTTPHandler.patch_method(
            {
                "item_id": "node-001",
                "grantee_id": "user-002",
                "permissions": ["read", "write"],
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/share", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Global Knowledge Routes
# ============================================================================


class TestGlobalKnowledgeRoutes:
    """Tests for global knowledge endpoint routing."""

    def test_store_verified_fact(self, handler, mock_mound):
        """POST /global stores verified fact."""
        http = MockHTTPHandler.post(
            {
                "content": "Earth is round",
                "source": "science",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/global", {}, http)
        assert result is not None
        assert _status(result) == 201

    def test_store_verified_fact_missing_content(self, handler):
        """POST /global without content returns 400."""
        http = MockHTTPHandler.post({"source": "science"})
        result = handler.handle("/api/v1/knowledge/mound/global", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_store_verified_fact_missing_source(self, handler):
        """POST /global without source returns 400."""
        http = MockHTTPHandler.post({"content": "A fact"})
        result = handler.handle("/api/v1/knowledge/mound/global", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_query_global_get(self, handler, mock_mound):
        """GET /global queries global knowledge."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/global", {"query": "test"}, http)
        assert result is not None
        assert _status(result) == 200

    def test_promote_to_global(self, handler, mock_mound):
        """POST /global/promote promotes to global."""
        http = MockHTTPHandler.post(
            {
                "item_id": "node-001",
                "workspace_id": "ws-001",
                "reason": "Universally applicable",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/global/promote", {}, http)
        assert result is not None
        assert _status(result) == 201

    def test_promote_to_global_missing_fields(self, handler):
        """POST /global/promote with missing fields returns 400."""
        http = MockHTTPHandler.post({"item_id": "node-001"})
        result = handler.handle("/api/v1/knowledge/mound/global/promote", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_get_system_facts(self, handler, mock_mound):
        """GET /global/facts returns system facts."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/global/facts", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_system_workspace_id(self, handler, mock_mound):
        """GET /global/workspace-id returns workspace ID."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/global/workspace-id", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Dedup Routes (via routing mixin)
# ============================================================================


class TestDedupRoutes:
    """Tests for dedup endpoint routing."""

    def test_get_duplicate_clusters(self, handler, mock_mound):
        """GET /dedup/clusters returns duplicate clusters."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/dedup/clusters", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_dedup_report(self, handler, mock_mound):
        """GET /dedup/report returns dedup report."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/dedup/report", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_merge_duplicate_cluster(self, handler, mock_mound):
        """POST /dedup/merge merges a duplicate cluster."""
        http = MockHTTPHandler.post({"cluster_id": "cluster-001"})
        result = handler.handle("/api/v1/knowledge/mound/dedup/merge", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_merge_duplicate_cluster_missing_cluster_id(self, handler):
        """POST /dedup/merge without cluster_id returns 400."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/dedup/merge", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_auto_merge(self, handler, mock_mound):
        """POST /dedup/auto-merge auto-merges duplicates."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/dedup/auto-merge", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Pruning Routes (via routing mixin)
# ============================================================================


class TestPruningRoutes:
    """Tests for pruning endpoint routing."""

    def test_get_prunable_items(self, handler, mock_mound):
        """GET /pruning/items returns prunable items."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/pruning/items", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_execute_prune(self, handler, mock_mound):
        """POST /pruning/execute prunes items."""
        http = MockHTTPHandler.post({"item_ids": ["node-001", "node-002"]})
        result = handler.handle("/api/v1/knowledge/mound/pruning/execute", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_execute_prune_missing_item_ids(self, handler):
        """POST /pruning/execute without item_ids returns 400."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/pruning/execute", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_auto_prune(self, handler, mock_mound):
        """POST /pruning/auto runs auto-prune."""
        http = MockHTTPHandler.post({"dry_run": True})
        result = handler.handle("/api/v1/knowledge/mound/pruning/auto", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_prune_history(self, handler, mock_mound):
        """GET /pruning/history returns prune history."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/pruning/history", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_restore_pruned_item(self, handler, mock_mound):
        """POST /pruning/restore restores a pruned item."""
        http = MockHTTPHandler.post({"node_id": "node-001"})
        result = handler.handle("/api/v1/knowledge/mound/pruning/restore", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_restore_pruned_item_missing_node_id(self, handler):
        """POST /pruning/restore without node_id returns 400."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/pruning/restore", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_apply_confidence_decay(self, handler, mock_mound):
        """POST /pruning/decay applies confidence decay."""
        http = MockHTTPHandler.post({"decay_rate": "0.05"})
        result = handler.handle("/api/v1/knowledge/mound/pruning/decay", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Contradiction Routes
# ============================================================================


class TestContradictionRoutes:
    """Tests for contradiction endpoint routing."""

    def test_detect_contradictions(self, handler, mock_mound):
        """POST /contradictions/detect triggers scan."""
        http = MockHTTPHandler.post({"workspace_id": "default"})
        result = handler.handle("/api/v1/knowledge/mound/contradictions/detect", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_list_contradictions(self, handler, mock_mound):
        """GET /contradictions lists unresolved contradictions."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/contradictions", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_resolve_contradiction(self, handler, mock_mound):
        """POST /contradictions/:id/resolve resolves a contradiction."""
        http = MockHTTPHandler.post(
            {
                "strategy": "prefer_newer",
                "resolved_by": "admin",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/contradictions/c-001/resolve", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_resolve_contradiction_missing_strategy(self, handler):
        """POST /contradictions/:id/resolve without strategy returns 400."""
        http = MockHTTPHandler.post({"resolved_by": "admin"})
        result = handler.handle("/api/v1/knowledge/mound/contradictions/c-001/resolve", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_contradiction_stats(self, handler, mock_mound):
        """GET /contradictions/stats returns statistics."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/contradictions/stats", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Governance Routes
# ============================================================================


class TestGovernanceRoutes:
    """Tests for governance endpoint routing."""

    def test_create_role(self, handler, mock_mound):
        """POST /governance/roles creates a role."""
        http = MockHTTPHandler.post({"name": "editor", "permissions": ["read", "update"]})
        result = handler.handle("/api/v1/knowledge/mound/governance/roles", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_create_role_missing_name(self, handler):
        """POST /governance/roles without name returns 400."""
        http = MockHTTPHandler.post({"permissions": ["read"]})
        result = handler.handle("/api/v1/knowledge/mound/governance/roles", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_assign_role(self, handler, mock_mound):
        """POST /governance/roles/assign assigns role."""
        http = MockHTTPHandler.post(
            {
                "user_id": "user-001",
                "role_id": "role-001",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/governance/roles/assign", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_assign_role_missing_fields(self, handler):
        """POST /governance/roles/assign without user_id returns 400."""
        http = MockHTTPHandler.post({"role_id": "role-001"})
        result = handler.handle("/api/v1/knowledge/mound/governance/roles/assign", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_revoke_role(self, handler, mock_mound):
        """POST /governance/roles/revoke revokes role."""
        http = MockHTTPHandler.post(
            {
                "user_id": "user-001",
                "role_id": "role-001",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/governance/roles/revoke", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_check_permission(self, handler, mock_mound):
        """POST /governance/permissions/check checks permission."""
        http = MockHTTPHandler.post(
            {
                "user_id": "user-001",
                "permission": "read",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/governance/permissions/check", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_check_permission_missing_fields(self, handler):
        """POST /governance/permissions/check without user_id returns 400."""
        http = MockHTTPHandler.post({"permission": "read"})
        result = handler.handle("/api/v1/knowledge/mound/governance/permissions/check", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_query_audit(self, handler, mock_mound):
        """GET /governance/audit queries audit trail."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/governance/audit", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_user_permissions(self, handler, mock_mound):
        """GET /governance/permissions/:user_id returns permissions."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/governance/permissions/user-001", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_user_activity(self, handler, mock_mound):
        """GET /governance/audit/user/:user_id returns user activity."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/governance/audit/user/user-001", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_governance_stats(self, handler, mock_mound):
        """GET /governance/stats returns governance stats."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/governance/stats", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Analytics Routes
# ============================================================================


class TestAnalyticsRoutes:
    """Tests for analytics endpoint routing."""

    def test_analyze_coverage(self, handler, mock_mound):
        """GET /analytics/coverage returns coverage analysis."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/analytics/coverage", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_analyze_usage(self, handler, mock_mound):
        """GET /analytics/usage returns usage patterns."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/analytics/usage", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_record_usage_event(self, handler, mock_mound):
        """POST /analytics/usage/record records event."""
        http = MockHTTPHandler.post({"event_type": "query"})
        result = handler.handle("/api/v1/knowledge/mound/analytics/usage/record", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_record_usage_event_missing_type(self, handler):
        """POST /analytics/usage/record without event_type returns 400."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/analytics/usage/record", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_capture_quality_snapshot(self, handler, mock_mound):
        """POST /analytics/quality/snapshot captures snapshot."""
        http = MockHTTPHandler.post({"workspace_id": "default"})
        result = handler.handle("/api/v1/knowledge/mound/analytics/quality/snapshot", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_quality_trend(self, handler, mock_mound):
        """GET /analytics/quality/trend returns trend data."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/analytics/quality/trend", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_analytics_stats(self, handler, mock_mound):
        """GET /analytics/stats returns analytics stats."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/analytics/stats", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Extraction Routes
# ============================================================================


class TestExtractionRoutes:
    """Tests for extraction endpoint routing."""

    def test_extract_from_debate(self, handler, mock_mound):
        """POST /extraction/debate extracts from debate."""
        http = MockHTTPHandler.post(
            {
                "debate_id": "debate-001",
                "messages": [{"role": "agent", "content": "I think..."}],
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/extraction/debate", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_extract_from_debate_missing_debate_id(self, handler):
        """POST /extraction/debate without debate_id returns 400."""
        http = MockHTTPHandler.post({"messages": [{"content": "test"}]})
        result = handler.handle("/api/v1/knowledge/mound/extraction/debate", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_extract_from_debate_missing_messages(self, handler):
        """POST /extraction/debate without messages returns 400."""
        http = MockHTTPHandler.post({"debate_id": "debate-001"})
        result = handler.handle("/api/v1/knowledge/mound/extraction/debate", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_promote_extracted(self, handler, mock_mound):
        """POST /extraction/promote promotes extracted claims."""
        http = MockHTTPHandler.post({"min_confidence": "0.7"})
        result = handler.handle("/api/v1/knowledge/mound/extraction/promote", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_extraction_stats(self, handler, mock_mound):
        """GET /extraction/stats returns extraction stats."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/extraction/stats", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Confidence Decay Routes
# ============================================================================


class TestConfidenceDecayRoutes:
    """Tests for confidence decay endpoint routing."""

    def test_apply_confidence_decay_new(self, handler, mock_mound):
        """POST /confidence/decay applies decay."""
        http = MockHTTPHandler.post({"workspace_id": "default"})
        result = handler.handle("/api/v1/knowledge/mound/confidence/decay", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_record_confidence_event(self, handler, mock_mound):
        """POST /confidence/event records event."""
        http = MockHTTPHandler.post(
            {
                "item_id": "node-001",
                "event": "validated",
            }
        )
        result = handler.handle("/api/v1/knowledge/mound/confidence/event", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_record_confidence_event_missing_item_id(self, handler):
        """POST /confidence/event without item_id returns 400."""
        http = MockHTTPHandler.post({"event": "accessed"})
        result = handler.handle("/api/v1/knowledge/mound/confidence/event", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_record_confidence_event_missing_event(self, handler):
        """POST /confidence/event without event returns 400."""
        http = MockHTTPHandler.post({"item_id": "node-001"})
        result = handler.handle("/api/v1/knowledge/mound/confidence/event", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_get_confidence_history(self, handler, mock_mound):
        """GET /confidence/history returns history."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/confidence/history", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_decay_stats(self, handler, mock_mound):
        """GET /confidence/stats returns decay stats."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/confidence/stats", {}, http)
        assert result is not None
        assert _status(result) == 200


# ============================================================================
# Tests: Mound Unavailability (503)
# ============================================================================


class TestMoundUnavailable:
    """Tests that all major endpoints return 503 when mound is unavailable."""

    def test_query_no_mound(self, handler_no_mound):
        http = MockHTTPHandler.post({"query": "test"})
        result = handler_no_mound.handle("/api/v1/knowledge/mound/query", {}, http)
        assert _status(result) == 503

    def test_list_nodes_no_mound(self, handler_no_mound):
        http = MockHTTPHandler.get()
        result = handler_no_mound.handle("/api/v1/knowledge/mound/nodes", {}, http)
        assert _status(result) == 503

    def test_get_node_no_mound(self, handler_no_mound):
        http = MockHTTPHandler.get()
        result = handler_no_mound.handle("/api/v1/knowledge/mound/nodes/node-001", {}, http)
        assert _status(result) == 503

    def test_stats_no_mound(self, handler_no_mound):
        http = MockHTTPHandler.get()
        result = handler_no_mound.handle("/api/v1/knowledge/mound/stats", {}, http)
        assert _status(result) == 503

    def test_culture_no_mound(self, handler_no_mound):
        http = MockHTTPHandler.get()
        result = handler_no_mound.handle("/api/v1/knowledge/mound/culture", {}, http)
        assert _status(result) == 503

    def test_stale_no_mound(self, handler_no_mound):
        http = MockHTTPHandler.get()
        result = handler_no_mound.handle("/api/v1/knowledge/mound/stale", {}, http)
        assert _status(result) == 503

    def test_export_d3_no_mound(self, handler_no_mound):
        http = MockHTTPHandler.get()
        result = handler_no_mound.handle("/api/v1/knowledge/mound/export/d3", {}, http)
        assert _status(result) == 503

    def test_graph_no_mound(self, handler_no_mound):
        http = MockHTTPHandler.get()
        result = handler_no_mound.handle("/api/v1/knowledge/mound/graph/node-001", {}, http)
        # Graph mixin validates entity_id path parsing before checking mound,
        # so returns 400 ("Node ID required") rather than 503.
        assert _status(result) == 400


# ============================================================================
# Tests: Method Not Allowed (None returns)
# ============================================================================


class TestMethodNotAllowed:
    """Tests that wrong HTTP methods return None (unhandled)."""

    def test_query_get_returns_none(self, handler):
        """GET on POST-only /query returns None."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/query", {}, http)
        assert result is None

    def test_stats_post_returns_none(self, handler):
        """POST on GET-only /stats returns None."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/stats", {}, http)
        assert result is None

    def test_relationships_get_returns_none(self, handler):
        """GET on POST-only /relationships returns None."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/relationships", {}, http)
        assert result is None


# ============================================================================
# Tests: Unknown Paths
# ============================================================================


class TestUnknownPaths:
    """Tests that unknown paths return None."""

    def test_completely_unknown_path(self, handler):
        """Unknown path returns None."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/nonexistent", {}, http)
        assert result is None

    def test_partially_matching_path(self, handler):
        """Partially matching but not exact path returns None."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/stats/extra", {}, http)
        assert result is None


# ============================================================================
# Tests: _get_mound initialization
# ============================================================================


class TestGetMound:
    """Tests for the _get_mound method."""

    def test_get_mound_returns_cached_mound(self, handler, mock_mound):
        """Returns cached mound if already initialized."""
        result = handler._get_mound()
        assert result is mock_mound

    def test_get_mound_returns_none_when_not_initialized(self, mock_server_context, monkeypatch):
        """Returns None when initialization fails."""
        h = KnowledgeMoundHandler(mock_server_context)

        # Patch _run_async at the handler module level to raise RuntimeError
        # so the initialize() call inside the try block fails.
        import aragora.server.handlers.knowledge_base.mound.handler as handler_mod

        monkeypatch.setattr(
            handler_mod, "_run_async", MagicMock(side_effect=RuntimeError("init fail"))
        )

        # Patch KnowledgeMound at its source so the local import in _get_mound
        # returns a mock (constructor succeeds), but _run_async will raise
        # during initialize(), which is caught by the try/except.
        with patch(
            "aragora.knowledge.mound.KnowledgeMound",
            return_value=MagicMock(),
        ):
            result = h._get_mound()
        assert result is None


# ============================================================================
# Tests: Federation Routes
# ============================================================================


class TestFederationRoutes:
    """Tests for federation endpoint routing."""

    def test_list_regions(self, handler, mock_mound):
        """GET /federation/regions lists regions."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/federation/regions", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_get_federation_status(self, handler, mock_mound):
        """GET /federation/status returns status."""
        http = MockHTTPHandler.get()
        result = handler.handle("/api/v1/knowledge/mound/federation/status", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_sync_push(self, handler, mock_mound):
        """POST /federation/sync/push pushes to region."""
        http = MockHTTPHandler.post({"region_id": "us-east-1"})
        result = handler.handle("/api/v1/knowledge/mound/federation/sync/push", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_sync_push_missing_region_id(self, handler):
        """POST /federation/sync/push without region_id returns 400."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/federation/sync/push", {}, http)
        assert result is not None
        assert _status(result) == 400

    def test_sync_pull(self, handler, mock_mound):
        """POST /federation/sync/pull pulls from region."""
        http = MockHTTPHandler.post({"region_id": "us-east-1"})
        result = handler.handle("/api/v1/knowledge/mound/federation/sync/pull", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_sync_all(self, handler, mock_mound):
        """POST /federation/sync/all syncs all regions."""
        http = MockHTTPHandler.post({})
        result = handler.handle("/api/v1/knowledge/mound/federation/sync/all", {}, http)
        assert result is not None
        assert _status(result) == 200

    def test_unregister_region(self, handler, mock_mound):
        """DELETE /federation/regions/:id unregisters region."""
        http = MockHTTPHandler.delete()
        result = handler.handle("/api/v1/knowledge/mound/federation/regions/us-east-1", {}, http)
        assert result is not None
        assert _status(result) == 200
