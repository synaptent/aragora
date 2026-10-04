"""Tests for SyncOperationsMixin."""

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

from aragora.server.handlers.knowledge_base.mound.sync import (
    SyncOperationsMixin,
)


def parse_response(result):
    """Parse HandlerResult body to dict."""
    return json.loads(result.body.decode("utf-8"))


# =============================================================================
# Mock Objects
# =============================================================================


@dataclass
class MockSyncResult:
    """Mock sync result."""

    nodes_synced: int = 0
    errors: int = 0


@dataclass
class MockKnowledgeMound:
    """Mock KnowledgeMound for testing."""

    sync_continuum_incremental: AsyncMock = field(default_factory=AsyncMock)
    sync_consensus_incremental: AsyncMock = field(default_factory=AsyncMock)
    sync_facts_incremental: AsyncMock = field(default_factory=AsyncMock)
    connect_memory_stores: AsyncMock = field(default_factory=AsyncMock)


class MockHandler:
    """Mock HTTP handler for testing."""

    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None):
        self.headers = headers or {}
        self._body = body
        self.rfile = io.BytesIO(body)

        if body and "Content-Length" not in self.headers:
            self.headers["Content-Length"] = str(len(body))


class SyncHandler(SyncOperationsMixin):
    """Handler implementation for testing SyncOperationsMixin."""

    def __init__(self, mound: MockKnowledgeMound | None = None):
        self._mound = mound
        self.ctx = {}

    def _get_mound(self):
        return self._mound


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_mound():
    """Create a mock KnowledgeMound."""
    return MockKnowledgeMound()


@pytest.fixture
def handler(mock_mound):
    """Create a test handler with mock mound."""
    return SyncHandler(mound=mock_mound)


@pytest.fixture
def handler_no_mound():
    """Create a test handler without mound."""
    return SyncHandler(mound=None)


@pytest.fixture(autouse=True)
def clear_module_state():
    """Clear any module-level state between tests."""
    yield


# =============================================================================
# Test sync_continuum
# =============================================================================


class TestSyncContinuum:
    """Tests for sync continuum endpoint."""

    def test_sync_continuum_success(self, handler, mock_mound):
        """Test successful continuum sync."""
        mock_mound.sync_continuum_incremental.return_value = MockSyncResult(nodes_synced=25)

        body = json.dumps(
            {
                "workspace_id": "ws-123",
                "limit": 50,
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_sync_continuum(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 25
        assert data["workspace_id"] == "ws-123"

    def test_sync_continuum_default_params(self, handler, mock_mound):
        """Test continuum sync with default parameters."""
        mock_mound.sync_continuum_incremental.return_value = MockSyncResult(nodes_synced=10)

        http_handler = MockHandler(body=b"")

        result = handler._handle_sync_continuum(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["workspace_id"] == "default"

    def test_sync_continuum_with_since(self, handler, mock_mound):
        """Test continuum sync with since timestamp."""
        mock_mound.sync_continuum_incremental.return_value = MockSyncResult(nodes_synced=5)

        body = json.dumps(
            {
                "since": "2026-01-01T00:00:00Z",
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_sync_continuum(http_handler)

        assert result.status_code == 200

    def test_sync_continuum_no_mound(self, handler_no_mound):
        """Test continuum sync when mound not available."""
        http_handler = MockHandler(body=b"")

        result = handler_no_mound._handle_sync_continuum(http_handler)

        assert result.status_code == 503

    def test_sync_continuum_not_available(self, handler, mock_mound):
        """Test continuum sync when continuum not connected."""
        mock_mound.sync_continuum_incremental.side_effect = AttributeError("No continuum")

        http_handler = MockHandler(body=b"")

        result = handler._handle_sync_continuum(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 0


# =============================================================================
# Test sync_consensus
# =============================================================================


class TestSyncConsensus:
    """Tests for sync consensus endpoint."""

    def test_sync_consensus_success(self, handler, mock_mound):
        """Test successful consensus sync."""
        mock_mound.sync_consensus_incremental.return_value = MockSyncResult(nodes_synced=15)

        body = json.dumps(
            {
                "workspace_id": "ws-456",
                "limit": 100,
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_sync_consensus(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 15
        assert data["workspace_id"] == "ws-456"

    def test_sync_consensus_default_params(self, handler, mock_mound):
        """Test consensus sync with default parameters."""
        mock_mound.sync_consensus_incremental.return_value = MockSyncResult(nodes_synced=8)

        http_handler = MockHandler(body=b"")

        result = handler._handle_sync_consensus(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["workspace_id"] == "default"

    def test_sync_consensus_no_mound(self, handler_no_mound):
        """Test consensus sync when mound not available."""
        http_handler = MockHandler(body=b"")

        result = handler_no_mound._handle_sync_consensus(http_handler)

        assert result.status_code == 503

    def test_sync_consensus_not_available(self, handler, mock_mound):
        """Test consensus sync when consensus not connected."""
        mock_mound.sync_consensus_incremental.side_effect = AttributeError("No consensus")

        http_handler = MockHandler(body=b"")

        result = handler._handle_sync_consensus(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 0


# =============================================================================
# Test sync_facts
# =============================================================================


@pytest.mark.xfail(strict=True, reason="fact sync closed until mound is org-scoped")
class TestSyncFacts:
    """Tests for sync facts endpoint."""

    def test_sync_facts_success(self, handler, mock_mound):
        """Test successful facts sync."""
        mock_mound.sync_facts_incremental.return_value = MockSyncResult(nodes_synced=30)

        body = json.dumps(
            {
                "workspace_id": "ws-789",
                "limit": 200,
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_sync_facts(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 30
        assert data["workspace_id"] == "ws-789"

    def test_sync_facts_default_params(self, handler, mock_mound):
        """Test facts sync with default parameters."""
        mock_mound.sync_facts_incremental.return_value = MockSyncResult(nodes_synced=12)

        http_handler = MockHandler(body=b"")

        result = handler._handle_sync_facts(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["workspace_id"] == "default"

    def test_sync_facts_with_since(self, handler, mock_mound):
        """Test facts sync with since timestamp."""
        mock_mound.sync_facts_incremental.return_value = MockSyncResult(nodes_synced=7)

        body = json.dumps(
            {
                "since": "2025-12-01T00:00:00Z",
                "limit": 50,
            }
        ).encode()
        http_handler = MockHandler(body=body)

        result = handler._handle_sync_facts(http_handler)

        assert result.status_code == 200

    def test_sync_facts_no_mound(self, handler_no_mound):
        """Test facts sync when mound not available."""
        http_handler = MockHandler(body=b"")

        result = handler_no_mound._handle_sync_facts(http_handler)

        assert result.status_code == 503

    def test_sync_facts_not_available(self, handler, mock_mound):
        """Test facts sync when fact store not connected."""
        mock_mound.sync_facts_incremental.side_effect = AttributeError("No facts")

        http_handler = MockHandler(body=b"")

        result = handler._handle_sync_facts(http_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["synced"] == 0

    def test_sync_facts_invalid_json(self, handler):
        """Test facts sync with invalid JSON."""
        http_handler = MockHandler(body=b"not json")

        result = handler._handle_sync_facts(http_handler)

        assert result.status_code == 400
        assert "invalid" in parse_response(result)["error"].lower()
