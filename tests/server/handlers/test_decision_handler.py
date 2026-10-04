"""
Tests for DecisionHandler - Unified Decision-Making HTTP endpoints.

Tests cover:
- Route matching (can_handle)
- RBAC permission enforcement
- Input validation
- Happy path operations
- Error handling
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import os

import pytest

from aragora.server.handlers.decision import DecisionHandler


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


class MockDecisionType(Enum):
    """Mock decision type enum."""

    DEBATE = "debate"
    WORKFLOW = "workflow"
    GAUNTLET = "gauntlet"
    QUICK = "quick"
    AUTO = "auto"


@dataclass
class MockDecisionResult:
    """Mock decision result for testing."""

    request_id: str = "dec_abc123def456"
    decision_type: MockDecisionType = field(default_factory=lambda: MockDecisionType.DEBATE)
    success: bool = True
    answer: str = "The recommended approach is..."
    confidence: float = 0.85
    consensus_reached: bool = True
    reasoning: str = "Based on multi-agent deliberation..."
    evidence_used: list[str] = field(default_factory=list)
    duration_seconds: float = 12.5
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "decision_type": self.decision_type.value,
            "success": self.success,
            "answer": self.answer,
            "confidence": self.confidence,
            "consensus_reached": self.consensus_reached,
            "reasoning": self.reasoning,
            "evidence_used": self.evidence_used,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


@dataclass
class MockDecisionContext:
    """Mock decision context."""

    user_id: str | None = None
    workspace_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class MockDecisionRequest:
    """Mock decision request for testing."""

    request_id: str = "dec_abc123def456"
    content: str = "What is the best approach?"
    decision_type: str = "auto"
    config: dict[str, Any] = field(default_factory=dict)
    context: MockDecisionContext = field(default_factory=MockDecisionContext)

    @classmethod
    def from_http(cls, body: dict[str, Any], headers: dict[str, str]) -> MockDecisionRequest:
        """Create from HTTP request body."""
        if not body.get("content"):
            raise ValueError("Missing required field: content")
        return cls(
            content=body.get("content", ""),
            decision_type=body.get("decision_type", "auto"),
            config=body.get("config", {}),
            context=MockDecisionContext(
                user_id=body.get("context", {}).get("user_id"),
                workspace_id=body.get("context", {}).get("workspace_id"),
            ),
        )


class MockDecisionRouter:
    """Mock decision router for testing."""

    def __init__(self, should_fail: bool = False, should_timeout: bool = False):
        self._should_fail = should_fail
        self._should_timeout = should_timeout

    async def route(self, request: MockDecisionRequest) -> MockDecisionResult:
        """Route a decision request."""
        if self._should_timeout:
            raise asyncio.TimeoutError("Decision timed out")
        if self._should_fail:
            raise RuntimeError("Decision routing failed")
        return MockDecisionResult(
            request_id=request.request_id,
            answer=f"Answer for: {request.content}",
        )


ORG = "test-org-001"
USER = "test-user-001"


class MockDecisionResultStore:
    """Mock decision result store for testing, with org ownership like the real store."""

    def __init__(self):
        self._results: dict[str, dict[str, Any]] = {}

    def save(
        self,
        request_id: str,
        data: dict[str, Any],
        *,
        org_id: str | None = None,
        created_by: str | None = None,
    ) -> None:
        previous = self._results.get(request_id) or {}
        owned = bool(previous.get("org_id"))
        self._results[request_id] = {
            **data,
            "org_id": previous["org_id"] if owned else (org_id or data.get("org_id")),
            "created_by": (
                previous.get("created_by") if owned else (created_by or data.get("created_by"))
            ),
        }

    def get(self, request_id: str) -> dict[str, Any] | None:
        return self._results.get(request_id)

    def get_for_org(self, request_id: str, org_id: str | None) -> dict[str, Any] | None:
        result = self._results.get(request_id)
        if result is None or not org_id or result.get("org_id") != org_id:
            return None
        return result

    def _owned(self, org_id: str) -> list[dict[str, Any]]:
        return [d for d in self._results.values() if org_id and d.get("org_id") == org_id]

    def list_recent_for_org(self, org_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "request_id": d["request_id"],
                "status": d.get("status"),
                "completed_at": d.get("completed_at"),
            }
            for d in self._owned(org_id)[-limit:]
        ]

    def count_for_org(self, org_id: str) -> int:
        return len(self._owned(org_id))


@dataclass
class MockAuthContext:
    """Mock authentication context."""

    authenticated: bool = True
    user_id: str = "user-001"
    org_id: str = "org-001"


def create_mock_handler(
    method: str = "GET",
    body: dict[str, Any] | None = None,
    path: str = "/api/v1/decisions",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock HTTP handler for testing."""
    mock = MagicMock()
    mock.command = method
    mock.path = path

    if body is not None:
        body_bytes = json.dumps(body).encode()
    else:
        body_bytes = b"{}"

    mock.rfile = MagicMock()
    mock.rfile.read = MagicMock(return_value=body_bytes)

    default_headers = {"Content-Length": str(len(body_bytes))}
    if headers:
        default_headers.update(headers)
    if body:
        default_headers.setdefault("Content-Type", "application/json")
    mock.headers = default_headers
    mock.client_address = ("127.0.0.1", 12345)
    mock.user_context = MagicMock()
    mock.user_context.user_id = "test_user"

    return mock


@pytest.fixture
def mock_server_context():
    """Create mock server context."""
    return MagicMock()


@pytest.fixture
def mock_result_store():
    """Create mock result store with sample data."""
    store = MockDecisionResultStore()
    store.save(
        "dec_other_org",
        {"request_id": "dec_other_org", "status": "failed", "content": "Theirs"},
        org_id="other-org-999",
        created_by="other-user",
    )
    store.save(
        "dec_existing123",
        {
            "request_id": "dec_existing123",
            "status": "completed",
            "result": {"answer": "Test answer"},
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
        org_id=ORG,
        created_by=USER,
    )
    store.save(
        "dec_pending456",
        {
            "request_id": "dec_pending456",
            "status": "pending",
        },
        org_id=ORG,
        created_by=USER,
    )
    store.save(
        "dec_failed789",
        {
            "request_id": "dec_failed789",
            "status": "failed",
            "error": "Something went wrong",
            "result": {"task": "Test task", "request": {"content": "Test content"}},
        },
        org_id=ORG,
        created_by=USER,
    )
    return store


@pytest.fixture
def handler(mock_server_context, mock_result_store):
    """Create handler with mocked dependencies."""
    h = DecisionHandler(mock_server_context)

    # Create patches that we'll apply
    with (
        patch(
            "aragora.server.handlers.decision._decision_result_store.get",
            return_value=mock_result_store,
        ),
        patch(
            "aragora.server.handlers.decision._get_result",
            side_effect=mock_result_store.get_for_org,
        ),
        patch("aragora.server.handlers.decision._save_result", side_effect=mock_result_store.save),
        patch(
            "aragora.server.handlers.decision._decision_results_fallback",
            mock_result_store._results,
        ),
    ):
        yield h


# ===========================================================================
# Route Matching Tests
# ===========================================================================


class TestDecisionHandlerRouting:
    """Test request routing."""

    def test_can_handle_decisions_list_path(self, mock_server_context):
        """Test that handler recognizes decisions list path."""
        h = DecisionHandler(mock_server_context)
        assert h.can_handle("/api/v1/decisions") is True

    def test_can_handle_decision_detail_path(self, mock_server_context):
        """Test that handler recognizes decision detail paths."""
        h = DecisionHandler(mock_server_context)
        assert h.can_handle("/api/v1/decisions/dec_abc123") is True

    def test_can_handle_decision_status_path(self, mock_server_context):
        """Test that handler recognizes decision status path."""
        h = DecisionHandler(mock_server_context)
        assert h.can_handle("/api/v1/decisions/dec_abc123/status") is True

    def test_can_handle_decision_cancel_path(self, mock_server_context):
        """Test that handler recognizes decision cancel path."""
        h = DecisionHandler(mock_server_context)
        assert h.can_handle("/api/v1/decisions/dec_abc123/cancel") is True

    def test_can_handle_decision_retry_path(self, mock_server_context):
        """Test that handler recognizes decision retry path."""
        h = DecisionHandler(mock_server_context)
        assert h.can_handle("/api/v1/decisions/dec_abc123/retry") is True

    def test_cannot_handle_other_paths(self, mock_server_context):
        """Test that handler rejects non-decision paths."""
        h = DecisionHandler(mock_server_context)
        assert h.can_handle("/api/v1/debates") is False
        assert h.can_handle("/api/v1/workflows") is False
        assert h.can_handle("/api/v2/decisions") is False
        assert h.can_handle("/api/decisions") is False


# ===========================================================================
# RBAC Permission Tests
# ===========================================================================


class TestDecisionHandlerRBAC:
    """Test RBAC permission enforcement."""

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_list_decisions_requires_decisions_read(self, mock_server_context):
        """Test that listing decisions requires decisions:read permission."""
        from aragora.rbac.decorators import PermissionDeniedError
        from aragora.server.auth import auth_config

        orig_enabled = auth_config.enabled
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        auth_config.enabled = True
        try:
            h = DecisionHandler(mock_server_context)
            mock_handler = create_mock_handler()

            # Without proper auth context, should raise PermissionDeniedError
            with pytest.raises(PermissionDeniedError):
                h.handle("/api/v1/decisions", {}, mock_handler)
        finally:
            auth_config.enabled = orig_enabled
            del os.environ["ARAGORA_TEST_REAL_AUTH"]

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_create_decision_requires_decisions_create(self, mock_server_context):
        """Test that creating a decision requires decisions:create permission."""
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        try:
            h = DecisionHandler(mock_server_context)
            mock_handler = create_mock_handler(
                method="POST",
                body={"content": "Test question"},
            )

            result = await h.handle_post("/api/v1/decisions", {}, mock_handler)
            assert result is not None
            assert result.status_code == 401
        finally:
            del os.environ["ARAGORA_TEST_REAL_AUTH"]

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_cancel_decision_requires_decisions_update(self, mock_server_context):
        """Test that cancelling a decision requires decisions:update permission."""
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        try:
            h = DecisionHandler(mock_server_context)
            mock_handler = create_mock_handler(method="POST")

            result = await h.handle_post(
                "/api/v1/decisions/dec_pending456/cancel", {}, mock_handler
            )
            assert result is not None
            assert result.status_code == 401
        finally:
            del os.environ["ARAGORA_TEST_REAL_AUTH"]


# ===========================================================================
# Input Validation Tests
# ===========================================================================


class TestDecisionHandlerValidation:
    """Test input validation."""

    @pytest.mark.asyncio
    async def test_create_decision_missing_content(self, mock_server_context):
        """Test creating decision without content returns 400."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(
            method="POST",
            body={"decision_type": "debate"},
        )

        with patch(
            "aragora.server.handlers.decision._get_decision_router",
            return_value=MockDecisionRouter(),
        ):
            result = await h.handle_post("/api/v1/decisions", {}, mock_handler)
            assert result.status_code == 400
            body = json.loads(result.body)
            assert "content" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_decision_invalid_json(self, mock_server_context):
        """Test creating decision with invalid JSON returns 400."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(method="POST")
        mock_handler.rfile.read.return_value = b"not valid json"
        mock_handler.headers["Content-Type"] = "application/json"

        result = await h.handle_post("/api/v1/decisions", {}, mock_handler)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_create_decision_empty_content(self, mock_server_context):
        """Test creating decision with empty content returns 400."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(
            method="POST",
            body={"content": ""},
        )

        with patch(
            "aragora.server.handlers.decision._get_decision_router",
            return_value=MockDecisionRouter(),
        ):
            result = await h.handle_post("/api/v1/decisions", {}, mock_handler)
            assert result.status_code == 400
            body = json.loads(result.body)
            assert "content" in body.get("error", "").lower()


# ===========================================================================
# Happy Path Tests - GET Endpoints
# ===========================================================================


class TestListDecisions:
    """Test list decisions endpoint."""

    def test_list_decisions_success(self, mock_server_context, mock_result_store):
        """Test listing decisions returns correct format."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler()

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get",
            return_value=mock_result_store,
        ):
            result = h.handle("/api/v1/decisions", {}, mock_handler)
            assert result.status_code == 200
            body = json.loads(result.body)
            assert "decisions" in body
            assert "total" in body
            assert isinstance(body["decisions"], list)
            assert body["total"] == 3
            assert "dec_other_org" not in {d["request_id"] for d in body["decisions"]}

    def test_list_decisions_with_limit(self, mock_server_context, mock_result_store):
        """Test listing decisions with limit parameter."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler()

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get",
            return_value=mock_result_store,
        ):
            result = h.handle("/api/v1/decisions", {"limit": "5"}, mock_handler)
            assert result.status_code == 200


class TestGetDecision:
    """Test get single decision endpoint."""

    def test_get_decision_success(self, mock_server_context, mock_result_store):
        """Test getting a specific decision."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler()

        with patch(
            "aragora.server.handlers.decision._get_result",
            side_effect=mock_result_store.get_for_org,
        ):
            result = h.handle("/api/v1/decisions/dec_existing123", {}, mock_handler)
            assert result.status_code == 200
            body = json.loads(result.body)
            assert body["request_id"] == "dec_existing123"

    def test_get_decision_not_found(self, mock_server_context, mock_result_store):
        """Test getting non-existent decision returns 404."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler()

        with patch(
            "aragora.server.handlers.decision._get_result",
            side_effect=mock_result_store.get_for_org,
        ):
            result = h.handle("/api/v1/decisions/nonexistent", {}, mock_handler)
            assert result.status_code == 404
            assert json.loads(result.body) == {"error": "Decision not found", "code": "not_found"}

    def test_get_other_org_decision_not_found(self, mock_server_context, mock_result_store):
        """Another org's decision is reported exactly like a missing one."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler()

        with patch(
            "aragora.server.handlers.decision._get_result",
            side_effect=mock_result_store.get_for_org,
        ):
            foreign = h.handle("/api/v1/decisions/dec_other_org", {}, mock_handler)
            missing = h.handle("/api/v1/decisions/nonexistent", {}, mock_handler)
            assert foreign.status_code == missing.status_code == 404
            assert json.loads(foreign.body) == json.loads(missing.body)


class TestGetDecisionStatus:
    """Test get decision status endpoint."""

    def test_get_decision_status_success(self, mock_server_context, mock_result_store):
        """Test getting decision status."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler()

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get",
            return_value=mock_result_store,
        ):
            result = h.handle("/api/v1/decisions/dec_existing123/status", {}, mock_handler)
            assert result.status_code == 200
            body = json.loads(result.body)
            assert body["request_id"] == "dec_existing123"
            assert "status" in body

    def test_get_decision_status_not_found(self, mock_server_context, mock_result_store):
        """Test getting status for non-existent decision."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler()

        with patch(
            "aragora.server.handlers.decision._decision_result_store.get",
            return_value=mock_result_store,
        ):
            result = h.handle("/api/v1/decisions/nonexistent/status", {}, mock_handler)
            assert result.status_code == 200
            body = json.loads(result.body)
            assert body["status"] == "not_found"


# ===========================================================================
# Happy Path Tests - POST Endpoints
# ===========================================================================


class TestCreateDecision:
    """Test create decision endpoint."""

    @pytest.mark.asyncio
    async def test_create_decision_success(self, mock_server_context, mock_result_store):
        """Test creating a new decision."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(
            method="POST",
            body={
                "content": "What is the best approach for implementing caching?",
                "decision_type": "debate",
                "config": {"rounds": 3},
            },
        )

        mock_router = AsyncMock()
        mock_router.route = AsyncMock(
            return_value=MockDecisionResult(
                success=True,
                answer="Implement Redis caching...",
                confidence=0.9,
            )
        )

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router", return_value=mock_router
            ),
            patch(
                "aragora.server.handlers.decision._save_result", side_effect=mock_result_store.save
            ),
            patch("aragora.core.decision.DecisionRequest", MockDecisionRequest),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MockAuthContext(),
            ),
        ):
            result = await h.handle_post("/api/v1/decisions", {}, mock_handler)
            assert result.status_code == 200
            body = json.loads(result.body)
            assert "request_id" in body
            assert body["status"] == "completed"
            assert "answer" in body

    @pytest.mark.asyncio
    async def test_create_decision_minimal_request(self, mock_server_context, mock_result_store):
        """Test creating decision with minimal required fields."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(
            method="POST",
            body={"content": "Simple question"},
        )

        mock_router = AsyncMock()
        mock_router.route = AsyncMock(return_value=MockDecisionResult())

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router", return_value=mock_router
            ),
            patch(
                "aragora.server.handlers.decision._save_result", side_effect=mock_result_store.save
            ),
            patch("aragora.core.decision.DecisionRequest", MockDecisionRequest),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MockAuthContext(),
            ),
        ):
            result = await h.handle_post("/api/v1/decisions", {}, mock_handler)
            assert result.status_code == 200


class TestCancelDecision:
    """Test cancel decision endpoint."""

    @pytest.mark.asyncio
    async def test_cancel_pending_decision(self, mock_server_context, mock_result_store):
        """Test cancelling a pending decision."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(
            method="POST",
            body={"reason": "No longer needed"},
        )

        with (
            patch(
                "aragora.server.handlers.decision._get_result",
                side_effect=mock_result_store.get_for_org,
            ),
            patch(
                "aragora.server.handlers.decision._save_result",
                side_effect=mock_result_store.save,
            ),
        ):
            result = await h.handle_post(
                "/api/v1/decisions/dec_pending456/cancel", {}, mock_handler
            )
            assert result.status_code == 200
            body = json.loads(result.body)
            assert body["status"] == "cancelled"
            assert body["reason"] == "No longer needed"

    @pytest.mark.asyncio
    async def test_cancel_completed_decision_fails(self, mock_server_context, mock_result_store):
        """Test that cancelling a completed decision returns 409."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(method="POST")

        with patch(
            "aragora.server.handlers.decision._get_result",
            side_effect=mock_result_store.get_for_org,
        ):
            result = await h.handle_post(
                "/api/v1/decisions/dec_existing123/cancel", {}, mock_handler
            )
            assert result.status_code == 409
            body = json.loads(result.body)
            assert "cannot cancel" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_decision(self, mock_server_context, mock_result_store):
        """Test cancelling non-existent decision returns 404."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(method="POST")

        with patch(
            "aragora.server.handlers.decision._get_result",
            side_effect=mock_result_store.get_for_org,
        ):
            result = await h.handle_post("/api/v1/decisions/nonexistent/cancel", {}, mock_handler)
            assert result.status_code == 404


class TestRetryDecision:
    """Test retry decision endpoint."""

    @pytest.mark.asyncio
    async def test_retry_failed_decision(self, mock_server_context, mock_result_store):
        """Test retrying a failed decision."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(method="POST")

        mock_router = AsyncMock()
        mock_router.route = AsyncMock(return_value=MockDecisionResult(success=True))

        with (
            patch(
                "aragora.server.handlers.decision._get_result",
                side_effect=mock_result_store.get_for_org,
            ),
            patch(
                "aragora.server.handlers.decision._get_decision_router", return_value=mock_router
            ),
            patch(
                "aragora.server.handlers.decision._save_result",
                side_effect=mock_result_store.save,
            ),
            patch("aragora.core.decision.DecisionRequest", MockDecisionRequest),
        ):
            result = await h.handle_post("/api/v1/decisions/dec_failed789/retry", {}, mock_handler)
            assert result.status_code == 200
            body = json.loads(result.body)
            assert "request_id" in body
            assert body["retried_from"] == "dec_failed789"

    @pytest.mark.asyncio
    async def test_retry_completed_decision_fails(self, mock_server_context, mock_result_store):
        """Test that retrying a completed decision returns 409."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(method="POST")

        with patch(
            "aragora.server.handlers.decision._get_result",
            side_effect=mock_result_store.get_for_org,
        ):
            result = await h.handle_post(
                "/api/v1/decisions/dec_existing123/retry", {}, mock_handler
            )
            assert result.status_code == 409
            body = json.loads(result.body)
            assert "cannot retry" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_retry_nonexistent_decision(self, mock_server_context, mock_result_store):
        """Test retrying non-existent decision returns 404."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(method="POST")

        with patch(
            "aragora.server.handlers.decision._get_result",
            side_effect=mock_result_store.get_for_org,
        ):
            result = await h.handle_post("/api/v1/decisions/nonexistent/retry", {}, mock_handler)
            assert result.status_code == 404


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestDecisionHandlerErrors:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_decision_router_unavailable(self, mock_server_context):
        """Test handling when decision router is unavailable."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(
            method="POST",
            body={"content": "Test question"},
        )

        with (
            patch("aragora.server.handlers.decision._get_decision_router", return_value=None),
            patch("aragora.core.decision.DecisionRequest", MockDecisionRequest),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MockAuthContext(),
            ),
        ):
            result = await h.handle_post("/api/v1/decisions", {}, mock_handler)
            assert result.status_code == 503
            body = json.loads(result.body)
            assert "not available" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_decision_timeout(self, mock_server_context, mock_result_store):
        """Test handling decision timeout."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(
            method="POST",
            body={"content": "Complex question"},
        )

        mock_router = AsyncMock()
        mock_router.route = AsyncMock(side_effect=asyncio.TimeoutError())

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router", return_value=mock_router
            ),
            patch(
                "aragora.server.handlers.decision._save_result", side_effect=mock_result_store.save
            ),
            patch("aragora.core.decision.DecisionRequest", MockDecisionRequest),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MockAuthContext(),
            ),
        ):
            result = await h.handle_post("/api/v1/decisions", {}, mock_handler)
            assert result.status_code == 408
            body = json.loads(result.body)
            assert "timed out" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_decision_routing_error(self, mock_server_context, mock_result_store):
        """Test handling decision routing errors."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(
            method="POST",
            body={"content": "Test question"},
        )

        mock_router = AsyncMock()
        mock_router.route = AsyncMock(side_effect=RuntimeError("Internal error"))

        with (
            patch(
                "aragora.server.handlers.decision._get_decision_router", return_value=mock_router
            ),
            patch(
                "aragora.server.handlers.decision._save_result", side_effect=mock_result_store.save
            ),
            patch("aragora.core.decision.DecisionRequest", MockDecisionRequest),
            patch(
                "aragora.billing.auth.extract_user_from_request",
                return_value=MockAuthContext(),
            ),
        ):
            result = await h.handle_post("/api/v1/decisions", {}, mock_handler)
            assert result.status_code == 500
            body = json.loads(result.body)
            assert "failed" in body.get("error", "").lower()

    def test_result_store_fallback(self, mock_server_context):
        """Test fallback to in-memory store when persistent store fails."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler()

        # When store returns None, should use fallback
        with (
            patch("aragora.server.handlers.decision._decision_result_store.get", return_value=None),
            patch(
                "aragora.server.handlers.decision._decision_results_fallback",
                {
                    "dec_inmem": {
                        "request_id": "dec_inmem",
                        "status": "completed",
                        "completed_at": "2026-01-15T10:00:00Z",
                    }
                },
            ),
        ):
            result = h.handle("/api/v1/decisions", {}, mock_handler)
            assert result.status_code == 200
            body = json.loads(result.body)
            assert "decisions" in body

    def test_error_response_format(self, mock_server_context, mock_result_store):
        """Test that error responses have correct format."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler()

        with patch(
            "aragora.server.handlers.decision._get_result",
            side_effect=mock_result_store.get_for_org,
        ):
            result = h.handle("/api/v1/decisions/nonexistent", {}, mock_handler)
            assert result.status_code == 404
            body = json.loads(result.body)
            assert "error" in body
            assert isinstance(body["error"], str)


# ===========================================================================
# Retry Timeout and Error Tests
# ===========================================================================


class TestRetryErrorHandling:
    """Test retry endpoint error handling."""

    @pytest.mark.asyncio
    async def test_retry_timeout(self, mock_server_context, mock_result_store):
        """Test handling retry timeout."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(method="POST")

        mock_router = AsyncMock()
        mock_router.route = AsyncMock(side_effect=asyncio.TimeoutError())

        with (
            patch(
                "aragora.server.handlers.decision._get_result",
                side_effect=mock_result_store.get_for_org,
            ),
            patch(
                "aragora.server.handlers.decision._get_decision_router", return_value=mock_router
            ),
            patch(
                "aragora.server.handlers.decision._save_result",
                side_effect=mock_result_store.save,
            ),
            patch("aragora.core.decision.DecisionRequest", MockDecisionRequest),
        ):
            result = await h.handle_post("/api/v1/decisions/dec_failed789/retry", {}, mock_handler)
            assert result.status_code == 408
            body = json.loads(result.body)
            assert "timed out" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_retry_routing_error(self, mock_server_context, mock_result_store):
        """Test handling retry routing errors."""
        h = DecisionHandler(mock_server_context)
        mock_handler = create_mock_handler(method="POST")

        mock_router = AsyncMock()
        mock_router.route = AsyncMock(side_effect=RuntimeError("Routing failed"))

        with (
            patch(
                "aragora.server.handlers.decision._get_result",
                side_effect=mock_result_store.get_for_org,
            ),
            patch(
                "aragora.server.handlers.decision._get_decision_router", return_value=mock_router
            ),
            patch(
                "aragora.server.handlers.decision._save_result",
                side_effect=mock_result_store.save,
            ),
            patch("aragora.core.decision.DecisionRequest", MockDecisionRequest),
        ):
            result = await h.handle_post("/api/v1/decisions/dec_failed789/retry", {}, mock_handler)
            assert result.status_code == 500
            body = json.loads(result.body)
            assert "failed" in body.get("error", "").lower()
