"""Comprehensive tests for ComplianceHandler (aragora/server/handlers/compliance/handler.py).

Tests the main handler routing, can_handle, factory, and all endpoint dispatch paths:
- General: status, audit-verify, audit-events
- SOC 2: soc2-report
- GDPR: gdpr-export, right-to-be-forgotten, deletions, legal-holds, coordinated-deletion,
        execute-pending, backup-exclusions
- CCPA: disclosure, delete, opt-out, correct, status
- HIPAA: status, phi-access, breach-assessment, baa (list/create), security-report,
         deidentify, safe-harbor/verify, detect-phi
- EU AI Act: classify, audit, generate-bundle
- Error handling: unknown routes, wrong methods, exception paths
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.compliance.handler import (
    ComplianceHandler,
    create_compliance_handler,
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


def _raw_body(result) -> bytes:
    """Get raw body bytes from a HandlerResult."""
    if isinstance(result, dict):
        return json.dumps(result).encode()
    return result.body


def _content_type(result) -> str:
    """Get content type from a HandlerResult."""
    if isinstance(result, dict):
        return "application/json"
    return result.content_type


class _MockHTTPHandler:
    """Lightweight mock for the HTTP handler passed to ComplianceHandler.handle."""

    def __init__(self, method: str = "GET", body: dict[str, Any] | None = None):
        self.command = method
        self.headers = {"Content-Length": "0"}
        self.rfile = MagicMock()

        if body is not None:
            raw = json.dumps(body).encode()
            self.rfile.read.return_value = raw
            self.headers = {"Content-Length": str(len(raw))}
        else:
            self.rfile.read.return_value = b"{}"
            self.headers = {"Content-Length": "2"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a ComplianceHandler with minimal server context."""
    return ComplianceHandler({})


@pytest.fixture(autouse=True)
def _patch_external_deps(monkeypatch):
    """Patch external stores and schedulers that ComplianceHandler mixins import."""
    mock_audit_store = MagicMock()
    mock_audit_store.get_log.return_value = []
    mock_audit_store.get_recent_activity.return_value = []
    mock_audit_store.log_event.return_value = None

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
    mock_scheduler.schedule_deletion.return_value = MagicMock(
        request_id="del-001",
        scheduled_for=datetime(2026, 4, 1, tzinfo=timezone.utc),
        status=MagicMock(value="pending"),
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    mock_hold_manager = MagicMock()
    mock_hold_manager.is_user_on_hold.return_value = False
    mock_hold_manager.get_active_holds.return_value = []

    monkeypatch.setattr(
        "aragora.server.handlers.compliance.handler.get_legal_hold_manager",
        lambda: mock_hold_manager,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.handler.get_audit_store", lambda: mock_audit_store
    )

    mock_coordinator = MagicMock()
    mock_coordinator.get_backup_exclusion_list.return_value = []
    mock_coordinator.add_to_backup_exclusion_list.return_value = None

    # For coordinated deletion
    mock_deletion_report = MagicMock()
    mock_deletion_report.success = True
    mock_deletion_report.deleted_from = []
    mock_deletion_report.backup_purge_results = {}
    mock_deletion_report.to_dict.return_value = {"success": True}
    mock_coordinator.execute_coordinated_deletion = AsyncMock(return_value=mock_deletion_report)

    # For pending deletions
    mock_coordinator.process_pending_deletions = AsyncMock(return_value=[])

    # Patch all mixin module-level store getters
    for module in [
        "aragora.server.handlers.compliance.gdpr",
        "aragora.server.handlers.compliance.ccpa",
        "aragora.server.handlers.compliance.hipaa",
        "aragora.server.handlers.compliance.audit_verify",
        "aragora.server.handlers.compliance.legal_hold",
    ]:
        try:
            monkeypatch.setattr(f"{module}.get_audit_store", lambda: mock_audit_store)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr(f"{module}.get_receipt_store", lambda: mock_receipt_store)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr(f"{module}.get_deletion_scheduler", lambda: mock_scheduler)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr(f"{module}.get_legal_hold_manager", lambda: mock_hold_manager)
        except AttributeError:
            pass
        try:
            monkeypatch.setattr(f"{module}.get_deletion_coordinator", lambda: mock_coordinator)
        except AttributeError:
            pass

    # Patch handler_events emit
    for module in [
        "aragora.server.handlers.compliance.handler",
        "aragora.server.handlers.compliance.gdpr",
        "aragora.server.handlers.compliance.ccpa",
        "aragora.server.handlers.compliance.hipaa",
    ]:
        try:
            monkeypatch.setattr(f"{module}.emit_handler_event", lambda *a, **kw: None)
        except AttributeError:
            pass

    # Patch EU AI Act lazy-loaded singletons
    mock_classifier = MagicMock()
    mock_classification = MagicMock()
    mock_classification.to_dict.return_value = {
        "risk_level": "limited",
        "rationale": "Test rationale",
    }
    mock_classifier.classify.return_value = mock_classification

    mock_report_gen = MagicMock()
    mock_report = MagicMock()
    mock_report.to_dict.return_value = {"report_id": "EUAIA-test", "articles": []}
    mock_report_gen.generate.return_value = mock_report

    mock_bundle_gen = MagicMock()
    mock_bundle = MagicMock()
    mock_bundle.to_dict.return_value = {"bundle_id": "bundle-test", "articles": {}}
    mock_bundle_gen.generate.return_value = mock_bundle

    monkeypatch.setattr(
        "aragora.server.handlers.compliance.eu_ai_act._get_classifier",
        lambda: mock_classifier,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.eu_ai_act._get_report_generator",
        lambda: mock_report_gen,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.eu_ai_act._get_artifact_generator",
        lambda **kw: mock_bundle_gen,
    )

    # Patch consent manager for GDPR RTBF
    try:
        monkeypatch.setattr(
            "aragora.server.handlers.compliance.gdpr._get_compliance_module",
            lambda: MagicMock(
                get_receipt_store=lambda: mock_receipt_store,
                get_audit_store=lambda: mock_audit_store,
                get_deletion_scheduler=lambda: mock_scheduler,
                get_legal_hold_manager=lambda: mock_hold_manager,
                get_deletion_coordinator=lambda: mock_coordinator,
            ),
        )
    except AttributeError:
        pass


# ============================================================================
# Factory and can_handle
# ============================================================================


class TestFactory:
    """Tests for the create_compliance_handler factory function."""

    def test_factory_creates_handler(self):
        h = create_compliance_handler({})
        assert isinstance(h, ComplianceHandler)

    def test_factory_passes_context(self):
        ctx = {"key": "value"}
        h = create_compliance_handler(ctx)
        assert isinstance(h, ComplianceHandler)


class TestCanHandle:
    """Tests for ComplianceHandler.can_handle()."""

    def test_can_handle_compliance_get(self, handler):
        assert handler.can_handle("/api/v2/compliance/status", "GET") is True

    def test_can_handle_compliance_post(self, handler):
        assert handler.can_handle("/api/v2/compliance/audit-verify", "POST") is True

    def test_can_handle_compliance_delete(self, handler):
        assert handler.can_handle("/api/v2/compliance/gdpr/legal-holds/123", "DELETE") is True

    def test_cannot_handle_put(self, handler):
        assert handler.can_handle("/api/v2/compliance/status", "PUT") is False

    def test_cannot_handle_patch(self, handler):
        assert handler.can_handle("/api/v2/compliance/status", "PATCH") is False

    def test_cannot_handle_non_compliance_path(self, handler):
        assert handler.can_handle("/api/v2/debates", "GET") is False

    def test_can_handle_nested_compliance_path(self, handler):
        assert handler.can_handle("/api/v2/compliance/hipaa/baa", "GET") is True

    def test_can_handle_compliance_base(self, handler):
        assert handler.can_handle("/api/v2/compliance", "GET") is True


# ============================================================================
# Unknown routes / 404
# ============================================================================


class TestNotFound:
    """Tests for unknown routes returning 404."""

    @pytest.mark.asyncio
    async def test_unknown_path_returns_404(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/nonexistent", {}, mock_h)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_wrong_method_returns_404(self, handler):
        # GET on a POST-only endpoint
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/audit-verify", {}, mock_h)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_post_on_get_only_returns_404(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        assert _status(result) == 404


# ============================================================================
# GET /api/v2/compliance/status
# ============================================================================


class TestStatusEndpoint:
    """Tests for GET /api/v2/compliance/status."""

    @pytest.mark.asyncio
    async def test_status_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_status_contains_required_fields(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        body = _body(result)
        assert "status" in body
        assert "compliance_score" in body
        assert "frameworks" in body
        assert "controls_summary" in body
        assert "generated_at" in body

    @pytest.mark.asyncio
    async def test_status_score_is_100_by_default(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        body = _body(result)
        assert body["compliance_score"] == 100
        assert body["status"] == "compliant"


# ============================================================================
# GET /api/v2/compliance/soc2-report
# ============================================================================


class TestSoc2Report:
    """Tests for GET /api/v2/compliance/soc2-report."""

    @pytest.mark.asyncio
    async def test_soc2_report_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/soc2-report", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_soc2_report_contains_report_fields(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/soc2-report", {}, mock_h)
        body = _body(result)
        assert body["report_type"] == "SOC 2 Type II"
        assert "trust_service_criteria" in body
        assert "controls" in body
        assert "summary" in body

    @pytest.mark.asyncio
    async def test_soc2_report_with_period(self, handler):
        mock_h = _MockHTTPHandler("GET")
        params = {"period_start": "2025-01-01", "period_end": "2025-03-31"}
        result = await handler.handle("/api/v2/compliance/soc2-report", params, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert "period" in body

    @pytest.mark.asyncio
    async def test_soc2_report_invalid_date_returns_400(self, handler):
        mock_h = _MockHTTPHandler("GET")
        params = {"period_start": "not-a-date"}
        result = await handler.handle("/api/v2/compliance/soc2-report", params, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_soc2_report_html_format(self, handler):
        mock_h = _MockHTTPHandler("GET")
        params = {"format": "html"}
        result = await handler.handle("/api/v2/compliance/soc2-report", params, mock_h)
        assert _status(result) == 200
        assert _content_type(result) == "text/html"
        assert b"<!DOCTYPE html>" in _raw_body(result)

    @pytest.mark.asyncio
    async def test_soc2_report_trust_service_criteria(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/soc2-report", {}, mock_h)
        body = _body(result)
        criteria = body["trust_service_criteria"]
        assert "security" in criteria
        assert "availability" in criteria
        assert "processing_integrity" in criteria
        assert "confidentiality" in criteria
        assert "privacy" in criteria


# ============================================================================
# GET /api/v2/compliance/gdpr-export
# ============================================================================


class TestGdprExport:
    """Tests for GET /api/v2/compliance/gdpr-export."""

    @pytest.mark.asyncio
    async def test_gdpr_export_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr-export", {"user_id": "user-1"}, mock_h
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_gdpr_export_missing_user_id(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr-export", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_gdpr_export_contains_user_data(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr-export", {"user_id": "user-1"}, mock_h
        )
        body = _body(result)
        assert body["user_id"] == "user-1"
        assert "export_id" in body
        assert "checksum" in body

    @pytest.mark.asyncio
    async def test_gdpr_export_csv_format(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr-export",
            {"user_id": "user-1", "format": "csv"},
            mock_h,
        )
        assert _status(result) == 200
        assert _content_type(result) == "text/csv"

    @pytest.mark.asyncio
    async def test_gdpr_export_with_include_filter(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr-export",
            {"user_id": "user-1", "include": "decisions"},
            mock_h,
        )
        body = _body(result)
        assert "decisions" in body["data_categories"]

    @pytest.mark.asyncio
    async def test_gdpr_export_all_categories(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr-export",
            {"user_id": "user-1", "include": "all"},
            mock_h,
        )
        body = _body(result)
        assert "decisions" in body["data_categories"]
        assert "preferences" in body["data_categories"]
        assert "activity" in body["data_categories"]


# ============================================================================
# POST /api/v2/compliance/gdpr/right-to-be-forgotten
# ============================================================================


class TestGdprRTBF:
    """Tests for POST /api/v2/compliance/gdpr/right-to-be-forgotten."""

    @pytest.mark.asyncio
    async def test_rtbf_returns_200(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1"})
        result = await handler.handle("/api/v2/compliance/gdpr/right-to-be-forgotten", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_rtbf_missing_user_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/right-to-be-forgotten", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_rtbf_response_fields(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1"})
        result = await handler.handle("/api/v2/compliance/gdpr/right-to-be-forgotten", {}, mock_h)
        body = _body(result)
        assert body["user_id"] == "user-1"
        assert body["status"] == "scheduled"
        assert "operations" in body
        assert "deletion_scheduled" in body

    @pytest.mark.asyncio
    async def test_rtbf_custom_grace_period(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1", "grace_period_days": 60})
        result = await handler.handle("/api/v2/compliance/gdpr/right-to-be-forgotten", {}, mock_h)
        body = _body(result)
        assert body["grace_period_days"] == 60

    @pytest.mark.asyncio
    async def test_rtbf_no_export(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1", "include_export": False})
        result = await handler.handle("/api/v2/compliance/gdpr/right-to-be-forgotten", {}, mock_h)
        body = _body(result)
        assert "export_url" not in body


# ============================================================================
# GET /api/v2/compliance/gdpr/deletions
# ============================================================================


class TestGdprListDeletions:
    """Tests for GET /api/v2/compliance/gdpr/deletions."""

    @pytest.mark.asyncio
    async def test_list_deletions_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/deletions", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_deletions_response_structure(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/deletions", {}, mock_h)
        body = _body(result)
        assert "deletions" in body
        assert "count" in body
        assert "filters" in body


# ============================================================================
# GET /api/v2/compliance/gdpr/deletions/:id
# ============================================================================


class TestGdprGetDeletion:
    """Tests for GET /api/v2/compliance/gdpr/deletions/:id."""

    @pytest.mark.asyncio
    async def test_get_deletion_not_found(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/deletions/del-999", {}, mock_h)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_deletion_found(self, handler, monkeypatch):
        mock_req = MagicMock()
        mock_req.to_dict.return_value = {"request_id": "del-001", "status": "pending"}

        mock_scheduler = MagicMock()
        mock_scheduler.store.get_request.return_value = mock_req
        monkeypatch.setattr(
            "aragora.server.handlers.compliance.gdpr.get_deletion_scheduler",
            lambda: mock_scheduler,
        )

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/deletions/del-001", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert "deletion" in body


# ============================================================================
# POST /api/v2/compliance/gdpr/deletions/:id/cancel
# ============================================================================


class TestGdprCancelDeletion:
    """Tests for POST /api/v2/compliance/gdpr/deletions/:id/cancel."""

    @pytest.mark.asyncio
    async def test_cancel_deletion_not_found(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle(
            "/api/v2/compliance/gdpr/deletions/del-999/cancel", {}, mock_h
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_cancel_deletion_success(self, handler, monkeypatch):
        mock_cancelled = MagicMock()
        mock_cancelled.user_id = "user-1"
        mock_cancelled.cancelled_at = datetime(2026, 2, 23, tzinfo=timezone.utc)
        mock_cancelled.to_dict.return_value = {"request_id": "del-001", "status": "cancelled"}

        mock_scheduler = MagicMock()
        mock_scheduler.cancel_deletion.return_value = mock_cancelled

        mock_audit = MagicMock()
        mock_audit.log_event.return_value = None

        monkeypatch.setattr(
            "aragora.server.handlers.compliance.gdpr.get_deletion_scheduler",
            lambda: mock_scheduler,
        )
        monkeypatch.setattr(
            "aragora.server.handlers.compliance.gdpr.get_audit_store",
            lambda: mock_audit,
        )

        mock_h = _MockHTTPHandler("POST", body={"reason": "User request"})
        result = await handler.handle(
            "/api/v2/compliance/gdpr/deletions/del-001/cancel", {}, mock_h
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["message"] == "Deletion cancelled successfully"


# ============================================================================
# Legal Holds (list, create, release)
# ============================================================================


class TestLegalHolds:
    """Tests for GDPR legal hold endpoints."""

    @pytest.mark.asyncio
    async def test_list_legal_holds_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_legal_holds_structure(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        body = _body(result)
        assert "legal_holds" in body
        assert "count" in body

    @pytest.mark.asyncio
    async def test_create_legal_hold_missing_user_ids(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"reason": "test"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_legal_hold_missing_reason(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"]})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_legal_hold_success(self, handler, monkeypatch):
        mock_hold = MagicMock()
        mock_hold.hold_id = "hold-001"
        mock_hold.to_dict.return_value = {"hold_id": "hold-001"}

        mock_mgr = MagicMock()
        mock_mgr.create_hold.return_value = mock_hold

        mock_audit = MagicMock()
        mock_audit.log_event.return_value = None

        monkeypatch.setattr(
            "aragora.server.handlers.compliance.handler.get_legal_hold_manager",
            lambda: mock_mgr,
        )
        monkeypatch.setattr(
            "aragora.server.handlers.compliance.handler.get_audit_store",
            lambda: mock_audit,
        )

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1", "u2"], "reason": "Litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 201
        body = _body(result)
        assert body["message"] == "Legal hold created successfully"
        mock_mgr.create_hold.assert_called_once()
        mock_audit.log_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_legal_hold_not_found(self, handler, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.release_hold.return_value = None
        monkeypatch.setattr(
            "aragora.server.handlers.compliance.handler.get_legal_hold_manager",
            lambda: mock_mgr,
        )

        mock_h = _MockHTTPHandler("DELETE")
        mock_h.command = "DELETE"
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-999", {}, mock_h)
        assert _status(result) == 404
        mock_mgr.release_hold.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_legal_hold_success(self, handler, monkeypatch):
        mock_released = MagicMock()
        mock_released.released_at = datetime(2026, 2, 23, tzinfo=timezone.utc)
        mock_released.user_ids = ["u1"]
        mock_released.to_dict.return_value = {"hold_id": "hold-001", "status": "released"}

        mock_mgr = MagicMock()
        mock_mgr.release_hold.return_value = mock_released

        mock_audit = MagicMock()
        mock_audit.log_event.return_value = None

        monkeypatch.setattr(
            "aragora.server.handlers.compliance.handler.get_legal_hold_manager",
            lambda: mock_mgr,
        )
        monkeypatch.setattr(
            "aragora.server.handlers.compliance.handler.get_audit_store",
            lambda: mock_audit,
        )

        mock_h = _MockHTTPHandler("DELETE")
        mock_h.command = "DELETE"
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-001", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert body["message"] == "Legal hold released successfully"
        mock_mgr.release_hold.assert_called_once()
        mock_audit.log_event.assert_called_once()


# ============================================================================
# POST /api/v2/compliance/gdpr/coordinated-deletion
# ============================================================================


class TestCoordinatedDeletion:
    """Tests for POST /api/v2/compliance/gdpr/coordinated-deletion."""

    @pytest.mark.asyncio
    async def test_coordinated_deletion_missing_user_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"reason": "GDPR"})
        result = await handler.handle("/api/v2/compliance/gdpr/coordinated-deletion", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_coordinated_deletion_missing_reason(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1"})
        result = await handler.handle("/api/v2/compliance/gdpr/coordinated-deletion", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_coordinated_deletion_success(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1", "reason": "GDPR request"})
        result = await handler.handle("/api/v2/compliance/gdpr/coordinated-deletion", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert "report" in body

    @pytest.mark.asyncio
    async def test_coordinated_deletion_legal_hold_blocks(self, handler, monkeypatch):
        mock_mgr = MagicMock()
        mock_mgr.is_user_on_hold.return_value = True
        mock_hold = MagicMock()
        mock_hold.hold_id = "hold-001"
        mock_hold.user_ids = ["user-1"]
        mock_mgr.get_active_holds.return_value = [mock_hold]

        monkeypatch.setattr(
            "aragora.server.handlers.compliance.gdpr.get_legal_hold_manager",
            lambda: mock_mgr,
        )

        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1", "reason": "GDPR request"})
        result = await handler.handle("/api/v2/compliance/gdpr/coordinated-deletion", {}, mock_h)
        assert _status(result) == 409


# ============================================================================
# POST /api/v2/compliance/gdpr/execute-pending
# ============================================================================


class TestExecutePending:
    """Tests for POST /api/v2/compliance/gdpr/execute-pending."""

    @pytest.mark.asyncio
    async def test_execute_pending_returns_200(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/execute-pending", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_execute_pending_response_structure(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/execute-pending", {}, mock_h)
        body = _body(result)
        assert "summary" in body
        assert "results" in body


# ============================================================================
# Backup Exclusions
# ============================================================================


class TestBackupExclusions:
    """Tests for GDPR backup exclusion endpoints."""

    @pytest.mark.asyncio
    async def test_list_backup_exclusions_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/backup-exclusions", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_list_backup_exclusions_structure(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/backup-exclusions", {}, mock_h)
        body = _body(result)
        assert "exclusions" in body
        assert "count" in body

    @pytest.mark.asyncio
    async def test_add_backup_exclusion_missing_user_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"reason": "GDPR"})
        result = await handler.handle("/api/v2/compliance/gdpr/backup-exclusions", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_backup_exclusion_missing_reason(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1"})
        result = await handler.handle("/api/v2/compliance/gdpr/backup-exclusions", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_backup_exclusion_success(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1", "reason": "GDPR deletion"})
        result = await handler.handle("/api/v2/compliance/gdpr/backup-exclusions", {}, mock_h)
        assert _status(result) == 201
        body = _body(result)
        assert body["user_id"] == "user-1"


# ============================================================================
# POST /api/v2/compliance/audit-verify
# ============================================================================


class TestAuditVerify:
    """Tests for POST /api/v2/compliance/audit-verify."""

    @pytest.mark.asyncio
    async def test_audit_verify_empty_body(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/audit-verify", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert body["verified"] is True

    @pytest.mark.asyncio
    async def test_audit_verify_with_trail_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"trail_id": "trail-001"})
        result = await handler.handle("/api/v2/compliance/audit-verify", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert "checks" in body

    @pytest.mark.asyncio
    async def test_audit_verify_with_receipt_ids(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"receipt_ids": ["r1", "r2"]})
        result = await handler.handle("/api/v2/compliance/audit-verify", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_audit_verify_with_date_range(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={"date_range": {"from": "2025-01-01T00:00:00Z", "to": "2025-12-31T23:59:59Z"}},
        )
        result = await handler.handle("/api/v2/compliance/audit-verify", {}, mock_h)
        assert _status(result) == 200


# ============================================================================
# GET /api/v2/compliance/audit-events
# ============================================================================


class TestAuditEvents:
    """Tests for GET /api/v2/compliance/audit-events."""

    @pytest.mark.asyncio
    async def test_audit_events_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/audit-events", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_audit_events_json_format(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/audit-events", {"format": "json"}, mock_h)
        body = _body(result)
        assert "events" in body
        assert "count" in body

    @pytest.mark.asyncio
    async def test_audit_events_ndjson_format(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/audit-events", {"format": "ndjson"}, mock_h
        )
        assert _status(result) == 200
        assert _content_type(result) == "application/x-ndjson"

    @pytest.mark.asyncio
    async def test_audit_events_elasticsearch_format(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/audit-events", {"format": "elasticsearch"}, mock_h
        )
        assert _status(result) == 200
        assert _content_type(result) == "application/x-ndjson"

    @pytest.mark.asyncio
    async def test_audit_events_with_time_range(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/audit-events",
            {"from": "2025-01-01T00:00:00Z", "to": "2025-12-31T23:59:59Z"},
            mock_h,
        )
        assert _status(result) == 200


# ============================================================================
# CCPA Endpoints
# ============================================================================


class TestCCPADisclosure:
    """Tests for GET /api/v2/compliance/ccpa/disclosure."""

    @pytest.mark.asyncio
    async def test_disclosure_missing_user_id(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/ccpa/disclosure", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_disclosure_categories_type(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/ccpa/disclosure",
            {"user_id": "user-1", "disclosure_type": "categories"},
            mock_h,
        )
        assert _status(result) == 200
        body = _body(result)
        assert "categories_collected" in body

    @pytest.mark.asyncio
    async def test_disclosure_specific_type(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/ccpa/disclosure",
            {"user_id": "user-1", "disclosure_type": "specific"},
            mock_h,
        )
        assert _status(result) == 200
        body = _body(result)
        assert "personal_information" in body

    @pytest.mark.asyncio
    async def test_disclosure_has_verification_hash(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/ccpa/disclosure",
            {"user_id": "user-1"},
            mock_h,
        )
        body = _body(result)
        assert "verification_hash" in body


class TestCCPADelete:
    """Tests for POST /api/v2/compliance/ccpa/delete."""

    @pytest.mark.asyncio
    async def test_delete_missing_user_id(self, handler):
        mock_h = _MockHTTPHandler(
            "POST", body={"verification_method": "email", "verification_code": "123"}
        )
        result = await handler.handle("/api/v2/compliance/ccpa/delete", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_delete_missing_verification(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1"})
        result = await handler.handle("/api/v2/compliance/ccpa/delete", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_delete_success(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_id": "user-1",
                "verification_method": "email",
                "verification_code": "123456",
            },
        )
        result = await handler.handle("/api/v2/compliance/ccpa/delete", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "scheduled"

    @pytest.mark.asyncio
    async def test_delete_with_retention_exceptions(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_id": "user-1",
                "verification_method": "email",
                "verification_code": "123456",
                "retain_for_exceptions": ["legal_obligations"],
            },
        )
        result = await handler.handle("/api/v2/compliance/ccpa/delete", {}, mock_h)
        body = _body(result)
        assert body["retained_categories"] == ["legal_obligations"]


class TestCCPAOptOut:
    """Tests for POST /api/v2/compliance/ccpa/opt-out."""

    @pytest.mark.asyncio
    async def test_opt_out_missing_user_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/ccpa/opt-out", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_opt_out_success(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1"})
        result = await handler.handle("/api/v2/compliance/ccpa/opt-out", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_opt_out_both_type(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1", "opt_out_type": "both"})
        result = await handler.handle("/api/v2/compliance/ccpa/opt-out", {}, mock_h)
        body = _body(result)
        assert body["opt_out_type"] == "both"

    @pytest.mark.asyncio
    async def test_opt_out_with_sensitive_pi_limit(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1", "sensitive_pi_limit": True})
        result = await handler.handle("/api/v2/compliance/ccpa/opt-out", {}, mock_h)
        body = _body(result)
        assert body["sensitive_pi_limit"] is True
        assert "sensitive personal information" in body["message"]


class TestCCPACorrect:
    """Tests for POST /api/v2/compliance/ccpa/correct."""

    @pytest.mark.asyncio
    async def test_correct_missing_user_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"corrections": [{"field": "name"}]})
        result = await handler.handle("/api/v2/compliance/ccpa/correct", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_correct_missing_corrections(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-1"})
        result = await handler.handle("/api/v2/compliance/ccpa/correct", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_correct_success(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_id": "user-1",
                "corrections": [
                    {"field": "name", "current_value": "old", "corrected_value": "new"}
                ],
            },
        )
        result = await handler.handle("/api/v2/compliance/ccpa/correct", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "pending_review"
        assert body["corrections_requested"] == 1

    @pytest.mark.asyncio
    async def test_correct_redacts_current_value(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_id": "user-1",
                "corrections": [{"field": "ssn", "current_value": "123-45-6789"}],
            },
        )
        result = await handler.handle("/api/v2/compliance/ccpa/correct", {}, mock_h)
        body = _body(result)
        assert body["corrections"][0]["current_value"] == "[REDACTED]"


class TestCCPAStatus:
    """Tests for GET /api/v2/compliance/ccpa/status."""

    @pytest.mark.asyncio
    async def test_status_missing_user_id(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/ccpa/status", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_status_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/ccpa/status", {"user_id": "user-1"}, mock_h
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_status_response_structure(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/ccpa/status", {"user_id": "user-1"}, mock_h
        )
        body = _body(result)
        assert body["user_id"] == "user-1"
        assert "requests" in body
        assert "count" in body


# ============================================================================
# HIPAA Endpoints
# ============================================================================


class TestHIPAAStatus:
    """Tests for GET /api/v2/compliance/hipaa/status."""

    @pytest.mark.asyncio
    async def test_hipaa_status_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/status", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_hipaa_status_contains_framework(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/status", {}, mock_h)
        body = _body(result)
        assert body["compliance_framework"] == "HIPAA"
        assert "compliance_score" in body
        assert "rules" in body

    @pytest.mark.asyncio
    async def test_hipaa_status_full_scope(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/status", {"scope": "full"}, mock_h)
        body = _body(result)
        assert "safeguard_details" in body
        assert "phi_controls" in body

    @pytest.mark.asyncio
    async def test_hipaa_status_no_recommendations(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/hipaa/status",
            {"include_recommendations": "false"},
            mock_h,
        )
        body = _body(result)
        assert "recommendations" not in body


class TestHIPAAPhiAccess:
    """Tests for GET /api/v2/compliance/hipaa/phi-access."""

    @pytest.mark.asyncio
    async def test_phi_access_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/phi-access", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_phi_access_response_structure(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/phi-access", {}, mock_h)
        body = _body(result)
        assert "phi_access_log" in body
        assert "count" in body
        assert "hipaa_reference" in body


class TestHIPAABreachAssessment:
    """Tests for POST /api/v2/compliance/hipaa/breach-assessment."""

    @pytest.mark.asyncio
    async def test_breach_assessment_missing_incident_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"incident_type": "data_leak"})
        result = await handler.handle("/api/v2/compliance/hipaa/breach-assessment", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_breach_assessment_missing_incident_type(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"incident_id": "inc-001"})
        result = await handler.handle("/api/v2/compliance/hipaa/breach-assessment", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_breach_assessment_no_phi(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "incident_id": "inc-001",
                "incident_type": "data_leak",
                "phi_involved": False,
            },
        )
        result = await handler.handle("/api/v2/compliance/hipaa/breach-assessment", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert body["breach_determination"] == "not_applicable"
        assert body["notification_required"] is False

    @pytest.mark.asyncio
    async def test_breach_assessment_with_phi_high_risk(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "incident_id": "inc-002",
                "incident_type": "unauthorized_access",
                "phi_involved": True,
                "phi_types": ["SSN", "Medical diagnosis"],
                "unauthorized_access": {"confirmed_access": True},
                "affected_individuals": 600,
            },
        )
        result = await handler.handle("/api/v2/compliance/hipaa/breach-assessment", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert body["breach_determination"] == "presumed_breach"
        assert body["notification_required"] is True
        assert "notification_deadlines" in body

    @pytest.mark.asyncio
    async def test_breach_assessment_low_risk(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "incident_id": "inc-003",
                "incident_type": "minor_issue",
                "phi_involved": True,
                "phi_types": ["Name"],
                "unauthorized_access": {"known_recipient": True},
                "mitigation_actions": ["action1", "action2", "action3"],
            },
        )
        result = await handler.handle("/api/v2/compliance/hipaa/breach-assessment", {}, mock_h)
        body = _body(result)
        assert body["breach_determination"] == "low_probability"
        assert body["notification_required"] is False


class TestHIPAABaa:
    """Tests for HIPAA BAA endpoints."""

    @pytest.mark.asyncio
    async def test_list_baas_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/baa", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert "business_associates" in body

    @pytest.mark.asyncio
    async def test_create_baa_missing_name(self, handler):
        mock_h = _MockHTTPHandler(
            "POST", body={"ba_type": "vendor", "services_provided": "hosting"}
        )
        result = await handler.handle("/api/v2/compliance/hipaa/baa", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_baa_invalid_type(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "business_associate": "Acme",
                "ba_type": "invalid",
                "services_provided": "hosting",
            },
        )
        result = await handler.handle("/api/v2/compliance/hipaa/baa", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_baa_missing_services(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"business_associate": "Acme", "ba_type": "vendor"})
        result = await handler.handle("/api/v2/compliance/hipaa/baa", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_baa_success(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "business_associate": "Cloud Corp",
                "ba_type": "vendor",
                "services_provided": "Cloud hosting",
            },
        )
        result = await handler.handle("/api/v2/compliance/hipaa/baa", {}, mock_h)
        assert _status(result) == 201
        body = _body(result)
        assert body["message"] == "Business Associate Agreement registered"
        assert "baa" in body


class TestHIPAASecurityReport:
    """Tests for GET /api/v2/compliance/hipaa/security-report."""

    @pytest.mark.asyncio
    async def test_security_report_returns_200(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/security-report", {}, mock_h)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_security_report_structure(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/security-report", {}, mock_h)
        body = _body(result)
        assert body["report_type"] == "HIPAA Security Rule Compliance"
        assert "safeguards" in body
        assert "summary" in body

    @pytest.mark.asyncio
    async def test_security_report_html_format(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/hipaa/security-report", {"format": "html"}, mock_h
        )
        assert _status(result) == 200
        assert _content_type(result) == "text/html"

    @pytest.mark.asyncio
    async def test_security_report_with_evidence(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/hipaa/security-report",
            {"include_evidence": "true"},
            mock_h,
        )
        body = _body(result)
        assert "evidence_references" in body


class TestHIPAADeidentify:
    """Tests for POST /api/v2/compliance/hipaa/deidentify."""

    @pytest.mark.asyncio
    async def test_deidentify_missing_content(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/hipaa/deidentify", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_deidentify_empty_content_and_no_data(self, handler):
        """An empty string is falsy, so both content and data are falsy => 400."""
        mock_h = _MockHTTPHandler("POST", body={"content": ""})
        result = await handler.handle("/api/v2/compliance/hipaa/deidentify", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_deidentify_no_content_or_data_keys(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"method": "redact"})
        result = await handler.handle("/api/v2/compliance/hipaa/deidentify", {}, mock_h)
        assert _status(result) == 400


class TestHIPAASafeHarborVerify:
    """Tests for POST /api/v2/compliance/hipaa/safe-harbor/verify."""

    @pytest.mark.asyncio
    async def test_safe_harbor_missing_content(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/hipaa/safe-harbor/verify", {}, mock_h)
        assert _status(result) == 400


class TestHIPAADetectPhi:
    """Tests for POST /api/v2/compliance/hipaa/detect-phi."""

    @pytest.mark.asyncio
    async def test_detect_phi_missing_content(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/hipaa/detect-phi", {}, mock_h)
        assert _status(result) == 400


# ============================================================================
# EU AI Act Endpoints
# ============================================================================


class TestEUAIActClassify:
    """Tests for POST /api/v2/compliance/eu-ai-act/classify."""

    @pytest.mark.asyncio
    async def test_classify_missing_description(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/classify", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_classify_empty_description(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"description": "  "})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/classify", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_classify_success(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"description": "AI for customer service chatbot"})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/classify", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert "classification" in body


class TestEUAIActAudit:
    """Tests for POST /api/v2/compliance/eu-ai-act/audit."""

    @pytest.mark.asyncio
    async def test_audit_missing_receipt(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/audit", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_audit_receipt_not_dict(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"receipt": "not-a-dict"})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/audit", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_audit_success(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={"receipt": {"receipt_id": "rcpt-001", "verdict": "approve"}},
        )
        result = await handler.handle("/api/v2/compliance/eu-ai-act/audit", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert "conformity_report" in body


class TestEUAIActGenerateBundle:
    """Tests for POST /api/v2/compliance/eu-ai-act/generate-bundle."""

    @pytest.mark.asyncio
    async def test_generate_bundle_missing_receipt(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/generate-bundle", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_generate_bundle_receipt_not_dict(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"receipt": 42})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/generate-bundle", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_generate_bundle_success(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={"receipt": {"receipt_id": "rcpt-001", "verdict": "approve"}},
        )
        result = await handler.handle("/api/v2/compliance/eu-ai-act/generate-bundle", {}, mock_h)
        assert _status(result) == 200
        body = _body(result)
        assert "bundle" in body

    @pytest.mark.asyncio
    async def test_generate_bundle_with_provider_params(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "receipt": {"receipt_id": "rcpt-001"},
                "provider_name": "Custom Corp",
                "system_name": "My AI System",
            },
        )
        result = await handler.handle("/api/v2/compliance/eu-ai-act/generate-bundle", {}, mock_h)
        assert _status(result) == 200


# ============================================================================
# Error handling in main handler
# ============================================================================


class TestErrorHandling:
    """Tests for exception handling in the main handle() method."""

    @pytest.mark.asyncio
    async def test_value_error_returns_500(self, handler, monkeypatch):
        """A ValueError in a sub-handler should be caught and return 500."""

        async def _boom(*args, **kwargs):
            raise ValueError("test error")

        monkeypatch.setattr(handler, "_get_status", _boom)

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_key_error_returns_500(self, handler, monkeypatch):
        async def _boom(*args, **kwargs):
            raise KeyError("missing")

        monkeypatch.setattr(handler, "_get_status", _boom)

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_type_error_returns_500(self, handler, monkeypatch):
        async def _boom(*args, **kwargs):
            raise TypeError("bad type")

        monkeypatch.setattr(handler, "_get_status", _boom)

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_runtime_error_returns_500(self, handler, monkeypatch):
        async def _boom(*args, **kwargs):
            raise RuntimeError("runtime fail")

        monkeypatch.setattr(handler, "_get_status", _boom)

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_os_error_returns_500(self, handler, monkeypatch):
        async def _boom(*args, **kwargs):
            raise OSError("disk fail")

        monkeypatch.setattr(handler, "_get_status", _boom)

        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        assert _status(result) == 500


# ============================================================================
# Timestamp parser
# ============================================================================


class TestParseTimestamp:
    """Tests for the _parse_timestamp static method."""

    def test_parse_none(self, handler):
        assert handler._parse_timestamp(None) is None

    def test_parse_empty_string(self, handler):
        assert handler._parse_timestamp("") is None

    def test_parse_iso_format(self, handler):
        result = handler._parse_timestamp("2025-06-15T10:30:00Z")
        assert result is not None
        assert result.year == 2025
        assert result.month == 6

    def test_parse_unix_timestamp(self, handler):
        result = handler._parse_timestamp("1700000000")
        assert result is not None
        assert isinstance(result, datetime)

    def test_parse_invalid_returns_none(self, handler):
        result = handler._parse_timestamp("not-a-date-or-number")
        assert result is None


# ============================================================================
# handler with None body
# ============================================================================


class TestNullHandler:
    """Tests for handling when handler parameter is None."""

    @pytest.mark.asyncio
    async def test_handle_with_none_handler(self, handler):
        result = await handler.handle("/api/v2/compliance/status", {}, None)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_none_defaults_to_get(self, handler):
        # POST-only endpoint with None handler defaults to GET, so 404
        result = await handler.handle("/api/v2/compliance/audit-verify", {}, None)
        assert _status(result) == 404


# ============================================================================
# Routes attribute
# ============================================================================


class TestRoutes:
    """Tests for the ROUTES class attribute."""

    def test_routes_includes_compliance_base(self, handler):
        assert "/api/v2/compliance" in handler.ROUTES

    def test_routes_includes_wildcard(self, handler):
        assert "/api/v2/compliance/*" in handler.ROUTES
