"""Comprehensive tests for the LegalHoldMixin handler (aragora/server/handlers/compliance/legal_hold.py).

Covers all legal hold endpoints routed through ComplianceHandler:
- GET    /api/v2/compliance/gdpr/legal-holds       - List legal holds
- POST   /api/v2/compliance/gdpr/legal-holds       - Create legal hold
- DELETE /api/v2/compliance/gdpr/legal-holds/:id    - Release legal hold

Also covers internal helpers:
- _extract_user_id_from_headers
- get_legal_hold_manager / get_audit_store indirection
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.compliance.handler import ComplianceHandler
from aragora.server.handlers.compliance.legal_hold import (
    LegalHoldMixin,
    _extract_user_id_from_headers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


class _MockHTTPHandler:
    """Lightweight mock for the HTTP handler passed to ComplianceHandler.handle."""

    def __init__(
        self,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.command = method
        self.headers = headers or {"Content-Length": "0"}
        self.rfile = MagicMock()

        if body is not None:
            raw = json.dumps(body).encode()
            self.rfile.read.return_value = raw
            self.headers["Content-Length"] = str(len(raw))
        else:
            self.rfile.read.return_value = b"{}"
            self.headers["Content-Length"] = "2"


# ---------------------------------------------------------------------------
# Mock data objects
# ---------------------------------------------------------------------------


class MockLegalHold:
    """Mock legal hold object returned by hold_manager."""

    def __init__(
        self,
        hold_id: str = "hold-001",
        user_ids: list[str] | None = None,
        reason: str = "Litigation matter",
        created_by: str = "compliance_api",
        case_reference: str | None = None,
        created_at: datetime | None = None,
        released_at: datetime | None = None,
    ):
        self.hold_id = hold_id
        self.user_ids = user_ids or ["user-42"]
        self.reason = reason
        self.created_by = created_by
        self.case_reference = case_reference
        self.created_at = created_at or datetime.now(timezone.utc)
        self.released_at = released_at

    def to_dict(self) -> dict[str, Any]:
        result = {
            "hold_id": self.hold_id,
            "user_ids": self.user_ids,
            "reason": self.reason,
            "created_by": self.created_by,
            "case_reference": self.case_reference,
            "created_at": self.created_at.isoformat(),
            "released_at": self.released_at.isoformat() if self.released_at else None,
        }
        return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a ComplianceHandler with minimal server context."""
    return ComplianceHandler({})


@pytest.fixture
def mock_hold_manager():
    """Create a mock legal hold manager."""
    mgr = MagicMock()
    mgr.get_active_holds.return_value = []
    mgr.is_user_on_hold.return_value = False
    mgr.create_hold.return_value = MockLegalHold()
    mgr.release_hold.return_value = None
    mgr._store = MagicMock()
    mgr._store._holds = {}
    return mgr


@pytest.fixture
def mock_audit_store():
    """Create a mock audit store."""
    store = MagicMock()
    store.log_event.return_value = None
    store.get_log.return_value = []
    store.get_recent_activity.return_value = []
    return store


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch, mock_hold_manager, mock_audit_store):
    """Patch external stores used by legal hold mixin and other compliance mixins."""
    # The composed handler supplies the legal-hold dependencies.
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.handler.get_legal_hold_manager",
        lambda: mock_hold_manager,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.handler.get_audit_store",
        lambda: mock_audit_store,
    )

    # GDPR mixin's helpers (needed because ComplianceHandler includes all mixins)
    mock_receipt_store = MagicMock()
    mock_receipt_store.list.return_value = []
    mock_receipt_store.get.return_value = None
    mock_receipt_store.get_by_gauntlet.return_value = None
    mock_receipt_store.verify_batch.return_value = ([], {"total": 0, "valid": 0})

    mock_scheduler = MagicMock()
    mock_scheduler.store = MagicMock()
    mock_scheduler.store.get_all_requests.return_value = []
    mock_scheduler.store.get_request.return_value = None
    mock_scheduler.cancel_deletion.return_value = None

    mock_coordinator = MagicMock()
    mock_coordinator.get_backup_exclusion_list.return_value = []

    monkeypatch.setattr(
        "aragora.server.handlers.compliance.gdpr.get_audit_store",
        lambda: mock_audit_store,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.gdpr.get_receipt_store",
        lambda: mock_receipt_store,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.gdpr.get_deletion_scheduler",
        lambda: mock_scheduler,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.gdpr.get_legal_hold_manager",
        lambda: mock_hold_manager,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.gdpr.get_deletion_coordinator",
        lambda: mock_coordinator,
    )

    # Audit verify mixin's helpers
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.audit_verify.get_audit_store",
        lambda: mock_audit_store,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.audit_verify.get_receipt_store",
        lambda: mock_receipt_store,
    )

    # CCPA mixin's helpers
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.ccpa.get_audit_store",
        lambda: mock_audit_store,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.ccpa.get_receipt_store",
        lambda: mock_receipt_store,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.ccpa.get_deletion_scheduler",
        lambda: mock_scheduler,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.ccpa.get_legal_hold_manager",
        lambda: mock_hold_manager,
    )

    # HIPAA mixin's helpers
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.hipaa.get_audit_store",
        lambda: mock_audit_store,
    )

    # Patch handler_events emit to avoid side effects
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.handler.emit_handler_event",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.gdpr.emit_handler_event",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.ccpa.emit_handler_event",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.hipaa.emit_handler_event",
        lambda *a, **kw: None,
    )

    yield {
        "hold_manager": mock_hold_manager,
        "audit_store": mock_audit_store,
        "receipt_store": mock_receipt_store,
        "scheduler": mock_scheduler,
        "coordinator": mock_coordinator,
    }


# ============================================================================
# _extract_user_id_from_headers - Unit Tests
# ============================================================================


class TestExtractUserIdFromHeaders:
    """Tests for the _extract_user_id_from_headers helper function."""

    def test_none_headers_returns_default(self):
        """None headers returns 'compliance_api' default."""
        assert _extract_user_id_from_headers(None) == "compliance_api"

    def test_empty_headers_returns_default(self):
        """Empty headers dict returns 'compliance_api' default."""
        assert _extract_user_id_from_headers({}) == "compliance_api"

    def test_no_authorization_header_returns_default(self):
        """Headers without Authorization returns default."""
        assert (
            _extract_user_id_from_headers({"Content-Type": "application/json"}) == "compliance_api"
        )

    def test_empty_authorization_returns_default(self):
        """Empty Authorization header returns default."""
        assert _extract_user_id_from_headers({"Authorization": ""}) == "compliance_api"

    def test_non_bearer_token_returns_default(self):
        """Non-Bearer authorization scheme returns default."""
        assert _extract_user_id_from_headers({"Authorization": "Basic abc123"}) == "compliance_api"

    def test_api_key_token(self):
        """API key token (ara_ prefix) returns truncated key identifier."""
        result = _extract_user_id_from_headers({"Authorization": "Bearer ara_1234567890abcdef"})
        assert result.startswith("api_key:")
        assert result.endswith("...")
        assert "ara_12345678" in result

    def test_api_key_token_short(self):
        """Short API key token returns proper truncation."""
        result = _extract_user_id_from_headers({"Authorization": "Bearer ara_short"})
        assert result == "api_key:ara_short..."

    def test_jwt_import_error_returns_default(self):
        """When validate_access_token import fails, returns default."""
        with patch(
            "aragora.server.handlers.compliance.legal_hold.validate_access_token",
            side_effect=ImportError("No module"),
            create=True,
        ):
            result = _extract_user_id_from_headers({"Authorization": "Bearer some.jwt.token"})
            assert result == "compliance_api"

    def test_jwt_validation_error_returns_default(self):
        """When JWT validation raises ValueError, returns default."""
        with patch(
            "aragora.billing.auth.tokens.validate_access_token",
            side_effect=ValueError("Invalid token"),
        ):
            result = _extract_user_id_from_headers({"Authorization": "Bearer invalid.jwt.token"})
            assert result == "compliance_api"

    def test_lowercase_authorization_header(self):
        """Lowercase 'authorization' header is also recognized."""
        result = _extract_user_id_from_headers({"authorization": "Bearer ara_test_key_123"})
        assert result.startswith("api_key:")

    def test_bearer_without_space_returns_default(self):
        """'Bearertoken' (without space) returns default."""
        assert _extract_user_id_from_headers({"Authorization": "Bearertoken"}) == "compliance_api"

    def test_jwt_with_valid_user_id(self):
        """When JWT validation succeeds and payload has user_id, returns it."""
        mock_payload = MagicMock()
        mock_payload.user_id = "user-from-jwt"

        with patch(
            "aragora.billing.auth.tokens.validate_access_token",
            return_value=mock_payload,
        ):
            result = _extract_user_id_from_headers({"Authorization": "Bearer valid.jwt.token"})
            assert result == "user-from-jwt"

    def test_jwt_with_none_payload_returns_default(self):
        """When JWT validation returns None payload, returns default."""
        with patch(
            "aragora.billing.auth.tokens.validate_access_token",
            return_value=None,
        ):
            result = _extract_user_id_from_headers({"Authorization": "Bearer some.jwt.token"})
            assert result == "compliance_api"

    def test_jwt_with_none_user_id_returns_default(self):
        """When JWT payload has None user_id, returns default."""
        mock_payload = MagicMock()
        mock_payload.user_id = None

        with patch(
            "aragora.billing.auth.tokens.validate_access_token",
            return_value=mock_payload,
        ):
            result = _extract_user_id_from_headers({"Authorization": "Bearer some.jwt.token"})
            assert result == "compliance_api"

    def test_jwt_with_attribute_error_returns_default(self):
        """When JWT payload access raises AttributeError, returns default."""
        with patch(
            "aragora.billing.auth.tokens.validate_access_token",
            side_effect=AttributeError("No user_id"),
        ):
            result = _extract_user_id_from_headers({"Authorization": "Bearer some.jwt.token"})
            assert result == "compliance_api"


# ============================================================================
# List Legal Holds Endpoint
# ============================================================================


class TestListLegalHolds:
    """Tests for GET /api/v2/compliance/gdpr/legal-holds."""

    @pytest.mark.asyncio
    async def test_list_empty_holds(self, handler, mock_hold_manager):
        """Empty active holds returns empty list with count 0."""
        mock_hold_manager.get_active_holds.return_value = []

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert body["legal_holds"] == []
        assert body["count"] == 0
        assert body["filters"]["active_only"] is True

    @pytest.mark.asyncio
    async def test_list_active_holds(self, handler, mock_hold_manager):
        """Active holds are returned with correct count."""
        holds = [
            MockLegalHold(hold_id="hold-1", user_ids=["u1"]),
            MockLegalHold(hold_id="hold-2", user_ids=["u2", "u3"]),
        ]
        mock_hold_manager.get_active_holds.return_value = holds

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 2
        assert len(body["legal_holds"]) == 2
        assert body["legal_holds"][0]["hold_id"] == "hold-1"
        assert body["legal_holds"][1]["hold_id"] == "hold-2"

    @pytest.mark.asyncio
    async def test_list_active_only_default_true(self, handler, mock_hold_manager):
        """Default query is active_only=true."""
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        body = _body(result)
        assert body["filters"]["active_only"] is True
        mock_hold_manager.get_active_holds.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_active_only_true_explicit(self, handler, mock_hold_manager):
        """Explicit active_only=true calls get_active_holds."""
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr/legal-holds", {"active_only": "true"}, mock_h
        )
        body = _body(result)
        assert body["filters"]["active_only"] is True
        mock_hold_manager.get_active_holds.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_active_only_True_uppercase(self, handler, mock_hold_manager):
        """active_only=True (uppercase) is treated as true."""
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr/legal-holds", {"active_only": "True"}, mock_h
        )
        body = _body(result)
        assert body["filters"]["active_only"] is True

    @pytest.mark.asyncio
    async def test_list_all_holds(self, handler, mock_hold_manager):
        """active_only=false returns all holds from store."""
        hold_active = MockLegalHold(hold_id="hold-a")
        hold_released = MockLegalHold(hold_id="hold-r", released_at=datetime.now(timezone.utc))
        mock_hold_manager._store._holds = {
            "hold-a": hold_active,
            "hold-r": hold_released,
        }

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr/legal-holds", {"active_only": "false"}, mock_h
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["filters"]["active_only"] is False
        assert body["count"] == 2

    @pytest.mark.asyncio
    async def test_list_holds_runtime_error(self, handler, mock_hold_manager):
        """RuntimeError from hold_manager returns 500."""
        mock_hold_manager.get_active_holds.side_effect = RuntimeError("DB down")

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_holds_attribute_error(self, handler, mock_hold_manager):
        """AttributeError from hold_manager returns 500."""
        mock_hold_manager.get_active_holds.side_effect = AttributeError("missing attr")

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_holds_key_error(self, handler, mock_hold_manager):
        """KeyError from hold_manager returns 500."""
        mock_hold_manager.get_active_holds.side_effect = KeyError("missing key")

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_holds_response_shape(self, handler, mock_hold_manager):
        """Response has exactly legal_holds, count, and filters keys."""
        mock_hold_manager.get_active_holds.return_value = []

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        body = _body(result)
        assert set(body.keys()) == {"legal_holds", "count", "filters"}

    @pytest.mark.asyncio
    async def test_list_holds_to_dict_called(self, handler, mock_hold_manager):
        """Each hold's to_dict method is called for serialization."""
        hold = MockLegalHold(hold_id="hold-x", reason="test reason")
        mock_hold_manager.get_active_holds.return_value = [hold]

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        body = _body(result)
        assert body["legal_holds"][0]["reason"] == "test reason"

    @pytest.mark.asyncio
    async def test_list_all_holds_empty_store(self, handler, mock_hold_manager):
        """active_only=false with empty store returns empty list."""
        mock_hold_manager._store._holds = {}

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr/legal-holds", {"active_only": "false"}, mock_h
        )
        body = _body(result)
        assert body["count"] == 0
        assert body["legal_holds"] == []


# ============================================================================
# Create Legal Hold Endpoint
# ============================================================================


class TestCreateLegalHold:
    """Tests for POST /api/v2/compliance/gdpr/legal-holds."""

    @pytest.mark.asyncio
    async def test_requires_user_ids(self, handler):
        """Missing user_ids returns 400."""
        mock_h = _MockHTTPHandler("POST", body={"reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400
        assert "user_ids" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_empty_user_ids_returns_400(self, handler):
        """Empty user_ids list returns 400."""
        mock_h = _MockHTTPHandler("POST", body={"user_ids": [], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400
        assert "user_ids" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_requires_reason(self, handler):
        """Missing reason returns 400."""
        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"]})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400
        assert "reason" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_empty_reason_returns_400(self, handler):
        """Empty string reason returns 400."""
        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": ""})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400
        assert "reason" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_missing_both_required_fields(self, handler):
        """Missing both user_ids and reason returns 400."""
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_successful_creation(self, handler, mock_hold_manager, mock_audit_store):
        """Successful creation returns 201 with hold data."""
        created_hold = MockLegalHold(
            hold_id="hold-new",
            user_ids=["u1", "u2"],
            reason="Patent dispute",
        )
        mock_hold_manager.create_hold.return_value = created_hold

        mock_h = _MockHTTPHandler(
            "POST", body={"user_ids": ["u1", "u2"], "reason": "Patent dispute"}
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        body = _body(result)
        assert "Legal hold created successfully" in body["message"]
        assert body["legal_hold"]["hold_id"] == "hold-new"
        assert body["legal_hold"]["user_ids"] == ["u1", "u2"]

    @pytest.mark.asyncio
    async def test_creation_calls_hold_manager(self, handler, mock_hold_manager):
        """create_hold is called with correct arguments."""
        created_hold = MockLegalHold(hold_id="hold-new")
        mock_hold_manager.create_hold.return_value = created_hold

        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_ids": ["u1"],
                "reason": "Investigation",
                "case_reference": "CASE-2026-001",
            },
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        mock_hold_manager.create_hold.assert_called_once()
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert call_kwargs["user_ids"] == ["u1"]
        assert call_kwargs["reason"] == "Investigation"
        assert call_kwargs["case_reference"] == "CASE-2026-001"
        assert call_kwargs["created_by"] == "compliance_api"

    @pytest.mark.asyncio
    async def test_creation_with_case_reference(self, handler, mock_hold_manager):
        """case_reference is forwarded to hold_manager."""
        mock_hold_manager.create_hold.return_value = MockLegalHold(case_reference="REF-99")

        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_ids": ["u1"],
                "reason": "Audit",
                "case_reference": "REF-99",
            },
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        body = _body(result)
        assert body["legal_hold"]["case_reference"] == "REF-99"

    @pytest.mark.asyncio
    async def test_creation_without_case_reference(self, handler, mock_hold_manager):
        """Missing case_reference passes None."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Audit"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert call_kwargs["case_reference"] is None

    @pytest.mark.asyncio
    async def test_creation_with_valid_expires_at(self, handler, mock_hold_manager):
        """Valid expires_at is parsed and forwarded."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()
        expires = "2026-12-31T23:59:59Z"

        mock_h = _MockHTTPHandler(
            "POST",
            body={"user_ids": ["u1"], "reason": "Audit", "expires_at": expires},
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert call_kwargs["expires_at"] is not None
        assert isinstance(call_kwargs["expires_at"], datetime)

    @pytest.mark.asyncio
    async def test_creation_with_iso_expires_at(self, handler, mock_hold_manager):
        """ISO 8601 expires_at with timezone offset is parsed correctly."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()
        expires = "2026-06-15T12:00:00+00:00"

        mock_h = _MockHTTPHandler(
            "POST",
            body={"user_ids": ["u1"], "reason": "Audit", "expires_at": expires},
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201

    @pytest.mark.asyncio
    async def test_creation_with_invalid_expires_at(self, handler):
        """Invalid expires_at format returns 400."""
        mock_h = _MockHTTPHandler(
            "POST",
            body={"user_ids": ["u1"], "reason": "Audit", "expires_at": "not-a-date"},
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400
        assert "expires_at" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_creation_without_expires_at(self, handler, mock_hold_manager):
        """Missing expires_at passes None to hold_manager."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Audit"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert call_kwargs["expires_at"] is None

    @pytest.mark.asyncio
    async def test_creation_logs_audit_event(self, handler, mock_hold_manager, mock_audit_store):
        """Legal hold creation logs an audit event."""
        created_hold = MockLegalHold(hold_id="hold-audit")
        mock_hold_manager.create_hold.return_value = created_hold

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        mock_audit_store.log_event.assert_called_once()
        call_kwargs = mock_audit_store.log_event.call_args[1]
        assert call_kwargs["action"] == "legal_hold_created"
        assert call_kwargs["resource_type"] == "legal_hold"
        assert call_kwargs["resource_id"] == "hold-audit"

    @pytest.mark.asyncio
    async def test_creation_audit_metadata(self, handler, mock_hold_manager, mock_audit_store):
        """Audit event metadata includes user_ids, reason, and case_reference."""
        mock_hold_manager.create_hold.return_value = MockLegalHold(hold_id="hold-m")

        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_ids": ["u1", "u2"],
                "reason": "Dispute",
                "case_reference": "CASE-1",
            },
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        metadata = mock_audit_store.log_event.call_args[1]["metadata"]
        assert metadata["user_ids"] == ["u1", "u2"]
        assert metadata["reason"] == "Dispute"
        assert metadata["case_reference"] == "CASE-1"

    @pytest.mark.asyncio
    async def test_creation_audit_log_failure_still_succeeds(
        self, handler, mock_hold_manager, mock_audit_store
    ):
        """Creation succeeds even if audit logging fails."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()
        mock_audit_store.log_event.side_effect = RuntimeError("Audit DB down")

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201

    @pytest.mark.asyncio
    async def test_creation_audit_log_os_error_still_succeeds(
        self, handler, mock_hold_manager, mock_audit_store
    ):
        """Creation succeeds even if audit logging raises OSError."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()
        mock_audit_store.log_event.side_effect = OSError("Disk full")

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201

    @pytest.mark.asyncio
    async def test_creation_audit_log_value_error_still_succeeds(
        self, handler, mock_hold_manager, mock_audit_store
    ):
        """Creation succeeds even if audit logging raises ValueError."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()
        mock_audit_store.log_event.side_effect = ValueError("Bad data")

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201

    @pytest.mark.asyncio
    async def test_creation_runtime_error_returns_500(self, handler, mock_hold_manager):
        """RuntimeError from create_hold returns 500."""
        mock_hold_manager.create_hold.side_effect = RuntimeError("DB failure")

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_creation_value_error_returns_500(self, handler, mock_hold_manager):
        """ValueError from create_hold returns 500."""
        mock_hold_manager.create_hold.side_effect = ValueError("Invalid")

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_creation_type_error_returns_500(self, handler, mock_hold_manager):
        """TypeError from create_hold returns 500."""
        mock_hold_manager.create_hold.side_effect = TypeError("Bad type")

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_creation_extracts_user_from_headers_no_auth(self, handler, mock_hold_manager):
        """Without auth header, created_by defaults to compliance_api."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert call_kwargs["created_by"] == "compliance_api"

    @pytest.mark.asyncio
    async def test_creation_extracts_user_from_api_key_header(self, handler, mock_hold_manager):
        """With Bearer ara_ API key, created_by uses key identifier."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()

        mock_h = _MockHTTPHandler(
            "POST",
            body={"user_ids": ["u1"], "reason": "Litigation"},
            headers={
                "Content-Length": "50",
                "Authorization": "Bearer ara_test_key_abcdef",
            },
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert call_kwargs["created_by"].startswith("api_key:")

    @pytest.mark.asyncio
    async def test_creation_with_multiple_user_ids(self, handler, mock_hold_manager):
        """Multiple user_ids are forwarded correctly."""
        mock_hold_manager.create_hold.return_value = MockLegalHold(user_ids=["u1", "u2", "u3"])

        mock_h = _MockHTTPHandler(
            "POST",
            body={"user_ids": ["u1", "u2", "u3"], "reason": "Class action"},
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert call_kwargs["user_ids"] == ["u1", "u2", "u3"]

    @pytest.mark.asyncio
    async def test_creation_response_contains_legal_hold_key(self, handler, mock_hold_manager):
        """Response body has 'message' and 'legal_hold' keys."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Test"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        body = _body(result)
        assert "message" in body
        assert "legal_hold" in body


# ============================================================================
# Release Legal Hold Endpoint
# ============================================================================


class TestReleaseLegalHold:
    """Tests for DELETE /api/v2/compliance/gdpr/legal-holds/:id."""

    @pytest.mark.asyncio
    async def test_release_not_found(self, handler, mock_hold_manager):
        """Non-existent hold returns 404."""
        mock_hold_manager.release_hold.return_value = None

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle(
            "/api/v2/compliance/gdpr/legal-holds/hold-nonexistent", {}, mock_h
        )
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_release_returns_false(self, handler, mock_hold_manager):
        """release_hold returning False returns 404."""
        mock_hold_manager.release_hold.return_value = False

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-nope", {}, mock_h)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_successful_release(self, handler, mock_hold_manager):
        """Successful release returns 200 with hold data."""
        released = MockLegalHold(
            hold_id="hold-001",
            released_at=datetime.now(timezone.utc),
        )
        mock_hold_manager.release_hold.return_value = released

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-001", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert "Legal hold released successfully" in body["message"]
        assert body["legal_hold"]["hold_id"] == "hold-001"

    @pytest.mark.asyncio
    async def test_release_calls_hold_manager(self, handler, mock_hold_manager):
        """release_hold is called with correct hold_id and released_by."""
        released = MockLegalHold(hold_id="hold-x", released_at=datetime.now(timezone.utc))
        mock_hold_manager.release_hold.return_value = released

        mock_h = _MockHTTPHandler("DELETE", body={"released_by": "admin@example.com"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-x", {}, mock_h)
        mock_hold_manager.release_hold.assert_called_once_with("hold-x", "admin@example.com")

    @pytest.mark.asyncio
    async def test_release_default_released_by(self, handler, mock_hold_manager):
        """Default released_by is 'compliance_api'."""
        released = MockLegalHold(hold_id="hold-d", released_at=datetime.now(timezone.utc))
        mock_hold_manager.release_hold.return_value = released

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-d", {}, mock_h)
        mock_hold_manager.release_hold.assert_called_once_with("hold-d", "compliance_api")

    @pytest.mark.asyncio
    async def test_release_logs_audit_event(self, handler, mock_hold_manager, mock_audit_store):
        """Release logs an audit event."""
        released = MockLegalHold(
            hold_id="hold-audit",
            user_ids=["u1", "u2"],
            released_at=datetime.now(timezone.utc),
        )
        mock_hold_manager.release_hold.return_value = released

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-audit", {}, mock_h)
        assert _status(result) == 200
        mock_audit_store.log_event.assert_called_once()
        call_kwargs = mock_audit_store.log_event.call_args[1]
        assert call_kwargs["action"] == "legal_hold_released"
        assert call_kwargs["resource_type"] == "legal_hold"
        assert call_kwargs["resource_id"] == "hold-audit"

    @pytest.mark.asyncio
    async def test_release_audit_metadata(self, handler, mock_hold_manager, mock_audit_store):
        """Audit event metadata includes released_by, released_at, and user_ids."""
        release_time = datetime.now(timezone.utc)
        released = MockLegalHold(
            hold_id="hold-m",
            user_ids=["u1"],
            released_at=release_time,
        )
        mock_hold_manager.release_hold.return_value = released

        mock_h = _MockHTTPHandler("DELETE", body={"released_by": "admin"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-m", {}, mock_h)
        metadata = mock_audit_store.log_event.call_args[1]["metadata"]
        assert metadata["released_by"] == "admin"
        assert metadata["released_at"] == release_time.isoformat()
        assert metadata["user_ids"] == ["u1"]

    @pytest.mark.asyncio
    async def test_release_audit_metadata_no_released_at(
        self, handler, mock_hold_manager, mock_audit_store
    ):
        """Audit metadata handles hold without released_at (None)."""
        released = MockLegalHold(hold_id="hold-none", released_at=None)
        mock_hold_manager.release_hold.return_value = released

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-none", {}, mock_h)
        assert _status(result) == 200
        metadata = mock_audit_store.log_event.call_args[1]["metadata"]
        assert metadata["released_at"] is None

    @pytest.mark.asyncio
    async def test_release_audit_log_failure_still_succeeds(
        self, handler, mock_hold_manager, mock_audit_store
    ):
        """Release succeeds even if audit logging fails."""
        released = MockLegalHold(hold_id="hold-a", released_at=datetime.now(timezone.utc))
        mock_hold_manager.release_hold.return_value = released
        mock_audit_store.log_event.side_effect = RuntimeError("Audit DB down")

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-a", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_release_audit_log_os_error_still_succeeds(
        self, handler, mock_hold_manager, mock_audit_store
    ):
        """Release succeeds even if audit logging raises OSError."""
        released = MockLegalHold(hold_id="hold-b", released_at=datetime.now(timezone.utc))
        mock_hold_manager.release_hold.return_value = released
        mock_audit_store.log_event.side_effect = OSError("Disk full")

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-b", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_release_audit_log_value_error_still_succeeds(
        self, handler, mock_hold_manager, mock_audit_store
    ):
        """Release succeeds even if audit logging raises ValueError."""
        released = MockLegalHold(hold_id="hold-c", released_at=datetime.now(timezone.utc))
        mock_hold_manager.release_hold.return_value = released
        mock_audit_store.log_event.side_effect = ValueError("Bad data")

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-c", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_release_runtime_error_returns_500(self, handler, mock_hold_manager):
        """RuntimeError from release_hold returns 500."""
        mock_hold_manager.release_hold.side_effect = RuntimeError("DB failure")

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-err", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_release_value_error_returns_500(self, handler, mock_hold_manager):
        """ValueError from release_hold returns 500."""
        mock_hold_manager.release_hold.side_effect = ValueError("Invalid")

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-err", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_release_key_error_returns_500(self, handler, mock_hold_manager):
        """KeyError from release_hold returns 500."""
        mock_hold_manager.release_hold.side_effect = KeyError("Not found")

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-err", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_release_extracts_hold_id_from_path(self, handler, mock_hold_manager):
        """hold_id is correctly extracted from the URL path."""
        mock_hold_manager.release_hold.return_value = None

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle(
            "/api/v2/compliance/gdpr/legal-holds/my-special-hold-id", {}, mock_h
        )
        mock_hold_manager.release_hold.assert_called_once_with(
            "my-special-hold-id", "compliance_api"
        )

    @pytest.mark.asyncio
    async def test_release_response_shape(self, handler, mock_hold_manager):
        """Successful release response has message and legal_hold keys."""
        released = MockLegalHold(hold_id="hold-s", released_at=datetime.now(timezone.utc))
        mock_hold_manager.release_hold.return_value = released

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-s", {}, mock_h)
        body = _body(result)
        assert set(body.keys()) == {"message", "legal_hold"}


# ============================================================================
# Route Dispatch Verification
# ============================================================================


class TestLegalHoldRouteDispatch:
    """Verify that legal hold routes dispatch correctly through ComplianceHandler."""

    @pytest.mark.asyncio
    async def test_get_legal_holds_route(self, handler, mock_hold_manager):
        """GET /api/v2/compliance/gdpr/legal-holds dispatches to _list_legal_holds."""
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_post_legal_holds_route(self, handler, mock_hold_manager):
        """POST /api/v2/compliance/gdpr/legal-holds dispatches to _create_legal_hold."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()
        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Test"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201

    @pytest.mark.asyncio
    async def test_delete_legal_hold_route(self, handler, mock_hold_manager):
        """DELETE /api/v2/compliance/gdpr/legal-holds/:id dispatches to _release_legal_hold."""
        mock_hold_manager.release_hold.return_value = None
        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-001", {}, mock_h)
        assert _status(result) == 404  # Not found since mock returns None

    @pytest.mark.asyncio
    async def test_wrong_method_get_on_delete_route_returns_404(self, handler):
        """GET on /legal-holds/:id returns 404 (no GET handler for individual holds)."""
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-001", {}, mock_h)
        # The path matches the startswith check but method doesn't match DELETE
        # So it falls through to the 404
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_post_on_delete_route_returns_404(self, handler):
        """POST on /legal-holds/:id returns 404 (only DELETE is valid)."""
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-001", {}, mock_h)
        # POST to legal-holds (exact) would create, but /legal-holds/hold-001 has no POST handler
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_delete_on_list_route_returns_404(self, handler):
        """DELETE on /legal-holds (without ID) returns 404."""
        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 404


# ============================================================================
# Edge Cases
# ============================================================================


class TestLegalHoldEdgeCases:
    """Edge cases and boundary conditions for legal hold endpoints."""

    @pytest.mark.asyncio
    async def test_create_with_single_user_id(self, handler, mock_hold_manager):
        """Single user_id in list is handled correctly."""
        mock_hold_manager.create_hold.return_value = MockLegalHold(user_ids=["u1"])

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "Investigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201

    @pytest.mark.asyncio
    async def test_create_with_many_user_ids(self, handler, mock_hold_manager):
        """Large list of user_ids is forwarded correctly."""
        user_ids = [f"user-{i}" for i in range(100)]
        mock_hold_manager.create_hold.return_value = MockLegalHold(user_ids=user_ids)

        mock_h = _MockHTTPHandler("POST", body={"user_ids": user_ids, "reason": "Mass hold"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert len(call_kwargs["user_ids"]) == 100

    @pytest.mark.asyncio
    async def test_release_hold_id_with_special_characters(self, handler, mock_hold_manager):
        """Hold ID with special path characters is extracted correctly."""
        mock_hold_manager.release_hold.return_value = None

        mock_h = _MockHTTPHandler("DELETE", body={})
        # UUID-style hold_id
        result = await handler.handle(
            "/api/v2/compliance/gdpr/legal-holds/550e8400-e29b-41d4-a716-446655440000",
            {},
            mock_h,
        )
        mock_hold_manager.release_hold.assert_called_once_with(
            "550e8400-e29b-41d4-a716-446655440000", "compliance_api"
        )

    @pytest.mark.asyncio
    async def test_list_holds_with_null_query_params(self, handler, mock_hold_manager):
        """None query_params are handled (coerced to empty dict by handler)."""
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", None, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_with_null_body_fields(self, handler, mock_hold_manager):
        """Null/None values for optional fields are handled."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()

        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_ids": ["u1"],
                "reason": "Test",
                "case_reference": None,
                "expires_at": None,
            },
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert call_kwargs["case_reference"] is None
        assert call_kwargs["expires_at"] is None

    @pytest.mark.asyncio
    async def test_can_handle_get(self, handler):
        """can_handle returns True for GET on compliance paths."""
        assert handler.can_handle("/api/v2/compliance/gdpr/legal-holds", "GET") is True

    @pytest.mark.asyncio
    async def test_can_handle_post(self, handler):
        """can_handle returns True for POST on compliance paths."""
        assert handler.can_handle("/api/v2/compliance/gdpr/legal-holds", "POST") is True

    @pytest.mark.asyncio
    async def test_can_handle_delete(self, handler):
        """can_handle returns True for DELETE on compliance paths."""
        assert handler.can_handle("/api/v2/compliance/gdpr/legal-holds/hold-1", "DELETE") is True

    @pytest.mark.asyncio
    async def test_can_handle_patch_returns_false(self, handler):
        """can_handle returns False for PATCH (unsupported method)."""
        assert handler.can_handle("/api/v2/compliance/gdpr/legal-holds", "PATCH") is False

    @pytest.mark.asyncio
    async def test_can_handle_non_compliance_path(self, handler):
        """can_handle returns False for non-compliance paths."""
        assert handler.can_handle("/api/v2/other/path", "GET") is False

    @pytest.mark.asyncio
    async def test_release_with_custom_released_by(self, handler, mock_hold_manager):
        """Custom released_by field is passed to release_hold."""
        released = MockLegalHold(hold_id="h1", released_at=datetime.now(timezone.utc))
        mock_hold_manager.release_hold.return_value = released

        mock_h = _MockHTTPHandler("DELETE", body={"released_by": "legal-team@corp.com"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/h1", {}, mock_h)
        assert _status(result) == 200
        mock_hold_manager.release_hold.assert_called_once_with("h1", "legal-team@corp.com")

    @pytest.mark.asyncio
    async def test_list_holds_active_only_various_false_values(self, handler, mock_hold_manager):
        """Various false-like values for active_only are treated as false."""
        mock_hold_manager._store._holds = {}

        for value in ["false", "False", "FALSE", "no", "0"]:
            mock_h = _MockHTTPHandler("GET")
            result = await handler.handle(
                "/api/v2/compliance/gdpr/legal-holds", {"active_only": value}, mock_h
            )
            body = _body(result)
            assert body["filters"]["active_only"] is False, f"Failed for value: {value}"

    @pytest.mark.asyncio
    async def test_expires_at_with_z_suffix(self, handler, mock_hold_manager):
        """expires_at with Z suffix (UTC) is parsed correctly."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()

        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_ids": ["u1"],
                "reason": "Test",
                "expires_at": "2026-12-31T23:59:59Z",
            },
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        call_kwargs = mock_hold_manager.create_hold.call_args[1]
        assert call_kwargs["expires_at"].year == 2026
        assert call_kwargs["expires_at"].month == 12

    @pytest.mark.asyncio
    async def test_expires_at_with_offset(self, handler, mock_hold_manager):
        """expires_at with timezone offset is parsed correctly."""
        mock_hold_manager.create_hold.return_value = MockLegalHold()

        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_ids": ["u1"],
                "reason": "Test",
                "expires_at": "2026-06-15T12:00:00+05:30",
            },
        )
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201


# ============================================================================
# Legal-hold dependency-provider tests
# ============================================================================


@pytest.mark.parametrize(
    ("getter", "hook"),
    [
        ("get_legal_hold_manager", "_get_legal_hold_manager"),
        ("get_audit_store", "_get_legal_hold_audit_store"),
    ],
)
class TestLegalHoldDependencyProviders:
    def test_standalone_mixin_does_not_depend_on_handler(self, monkeypatch, getter, hook):
        from aragora.server.handlers.compliance import handler as handler_module
        from aragora.server.handlers.compliance import legal_hold

        dependency = object()
        base_provider = MagicMock(return_value=dependency)
        monkeypatch.setattr(legal_hold, f"_base_{getter}", base_provider)
        handler_provider = MagicMock(side_effect=AssertionError("concrete handler used"))
        monkeypatch.setattr(handler_module, getter, handler_provider)

        assert getattr(LegalHoldMixin(), hook)() is dependency
        base_provider.assert_called_once_with()
        handler_provider.assert_not_called()

    def test_composed_handler_resolves_provider_at_call_time(self, monkeypatch, getter, hook):
        from aragora.server.handlers.compliance import handler as handler_module

        handler = ComplianceHandler({})
        for _ in range(2):
            dependency = object()
            provider = MagicMock(return_value=dependency)
            monkeypatch.setattr(handler_module, getter, provider)
            assert getattr(handler, hook)() is dependency
            provider.assert_called_once_with()

    @pytest.mark.parametrize("error_type", [ImportError, AttributeError])
    def test_unavailable_handler_provider_falls_back(self, monkeypatch, getter, hook, error_type):
        from aragora.server.handlers.compliance import handler as handler_module
        from aragora.server.handlers.compliance import legal_hold

        dependency = object()
        base_provider = MagicMock(return_value=dependency)
        monkeypatch.setattr(legal_hold, f"_base_{getter}", base_provider)
        provider = MagicMock(side_effect=error_type("provider unavailable"))
        monkeypatch.setattr(handler_module, getter, provider)

        assert getattr(ComplianceHandler({}), hook)() is dependency
        provider.assert_called_once_with()
        base_provider.assert_called_once_with()

    def test_runtime_failure_is_not_replaced_with_another_store(self, monkeypatch, getter, hook):
        from aragora.server.handlers.compliance import handler as handler_module
        from aragora.server.handlers.compliance import legal_hold

        base_provider = MagicMock()
        monkeypatch.setattr(legal_hold, f"_base_{getter}", base_provider)
        monkeypatch.setattr(handler_module, getter, MagicMock(side_effect=RuntimeError("offline")))

        with pytest.raises(RuntimeError, match="offline"):
            getattr(ComplianceHandler({}), hook)()
        base_provider.assert_not_called()
