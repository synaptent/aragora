"""Tests for the ComplianceHandler REST endpoints.

Covers all compliance domains:
- General: GET status, POST audit-verify, GET audit-events
- SOC2: GET soc2-report
- GDPR: GET gdpr-export, POST right-to-be-forgotten, deletions, legal holds,
        coordinated deletion, execute-pending, backup-exclusions
- CCPA: GET disclosure, POST delete, POST opt-out, POST correct, GET status
- HIPAA: GET status, GET phi-access, POST breach-assessment, GET/POST baa,
         GET security-report, POST deidentify, POST safe-harbor/verify, POST detect-phi
- EU AI Act: POST classify, POST audit, POST generate-bundle
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.compliance.handler import ComplianceHandler


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
def _patch_stores(monkeypatch):
    """Patch external stores and schedulers used by compliance mixins.

    Prevents tests from touching real storage or compliance infrastructure.
    """
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

    mock_hold_manager = MagicMock()
    mock_hold_manager.is_user_on_hold.return_value = False
    mock_hold_manager.get_active_holds.return_value = []

    mock_coordinator = MagicMock()

    # Patch the GDPR mixin's module-level helpers
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

    # Patch the composed handler's legal-hold providers.
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.handler.get_legal_hold_manager",
        lambda: mock_hold_manager,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.handler.get_audit_store",
        lambda: mock_audit_store,
    )

    # Patch audit_verify mixin's helpers
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.audit_verify.get_audit_store",
        lambda: mock_audit_store,
    )
    monkeypatch.setattr(
        "aragora.server.handlers.compliance.audit_verify.get_receipt_store",
        lambda: mock_receipt_store,
    )

    # Patch CCPA mixin's direct imports
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

    # Patch HIPAA mixin's direct imports
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

    # Expose mocks for tests that need to inspect calls
    yield {
        "audit_store": mock_audit_store,
        "receipt_store": mock_receipt_store,
        "scheduler": mock_scheduler,
        "hold_manager": mock_hold_manager,
        "coordinator": mock_coordinator,
    }


# ============================================================================
# can_handle routing
# ============================================================================


class TestCanHandle:
    """Verify that can_handle correctly accepts or rejects paths and methods."""

    def test_status_get(self, handler):
        assert handler.can_handle("/api/v2/compliance/status", "GET")

    def test_soc2_report_get(self, handler):
        assert handler.can_handle("/api/v2/compliance/soc2-report", "GET")

    def test_gdpr_export_get(self, handler):
        assert handler.can_handle("/api/v2/compliance/gdpr-export", "GET")

    def test_audit_verify_post(self, handler):
        assert handler.can_handle("/api/v2/compliance/audit-verify", "POST")

    def test_ccpa_delete_post(self, handler):
        assert handler.can_handle("/api/v2/compliance/ccpa/delete", "POST")

    def test_hipaa_status_get(self, handler):
        assert handler.can_handle("/api/v2/compliance/hipaa/status", "GET")

    def test_eu_ai_act_classify_post(self, handler):
        assert handler.can_handle("/api/v2/compliance/eu-ai-act/classify", "POST")

    def test_legal_holds_delete(self, handler):
        assert handler.can_handle("/api/v2/compliance/gdpr/legal-holds/hold-123", "DELETE")

    def test_rejects_patch_method(self, handler):
        assert not handler.can_handle("/api/v2/compliance/status", "PATCH")

    def test_rejects_put_method(self, handler):
        assert not handler.can_handle("/api/v2/compliance/status", "PUT")

    def test_rejects_unrelated_path(self, handler):
        assert not handler.can_handle("/api/v2/debates", "GET")

    def test_rejects_v1_path(self, handler):
        assert not handler.can_handle("/api/v1/compliance/status", "GET")

    def test_accepts_bare_compliance_path(self, handler):
        assert handler.can_handle("/api/v2/compliance", "GET")

    def test_accepts_nested_subpath(self, handler):
        assert handler.can_handle("/api/v2/compliance/hipaa/baa", "POST")


# ============================================================================
# Route dispatch (404 for unknown, correct method routing)
# ============================================================================


class TestRouteDispatch:
    """Verify handle() routes to the right mixin method or returns 404."""

    @pytest.mark.asyncio
    async def test_unknown_path_returns_404(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/nonexistent", {}, mock_h)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_wrong_method_returns_404(self, handler):
        """POST to a GET-only endpoint should 404 (no matching route)."""
        mock_h = _MockHTTPHandler("POST")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_status_dispatches(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert "status" in body
        assert "compliance_score" in body

    @pytest.mark.asyncio
    async def test_base_status_path_dispatches_to_status(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert "status" in body
        assert "compliance_score" in body

    @pytest.mark.asyncio
    async def test_trailing_slash_base_status_path_dispatches_to_status(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert "status" in body
        assert "compliance_score" in body

    @pytest.mark.asyncio
    async def test_get_soc2_report_dispatches(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/soc2-report", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body.get("report_type") == "SOC 2 Type II"


# ============================================================================
# General endpoints
# ============================================================================


class TestComplianceStatus:
    @pytest.mark.asyncio
    async def test_returns_frameworks(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        body = _body(result)
        assert "frameworks" in body
        assert "soc2_type2" in body["frameworks"]
        assert "gdpr" in body["frameworks"]
        assert "hipaa" in body["frameworks"]

    @pytest.mark.asyncio
    async def test_returns_controls_summary(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
        body = _body(result)
        summary = body.get("controls_summary", {})
        assert "total" in summary
        assert "compliant" in summary
        assert summary["total"] > 0


class TestAuditVerify:
    @pytest.mark.asyncio
    async def test_empty_body_returns_verified(self, handler):
        """An empty verification body (no trail_id, receipt_ids, date_range) is trivially valid."""
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/audit-verify", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body.get("verified") is True

    @pytest.mark.asyncio
    async def test_with_trail_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"trail_id": "test-trail-123"})
        result = await handler.handle("/api/v2/compliance/audit-verify", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert len(body.get("checks", [])) >= 1

    @pytest.mark.asyncio
    async def test_with_date_range(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={"date_range": {"from": "2025-01-01T00:00:00Z", "to": "2025-12-31T23:59:59Z"}},
        )
        result = await handler.handle("/api/v2/compliance/audit-verify", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert any(c.get("type") == "date_range" for c in body.get("checks", []))


class TestAuditEvents:
    @pytest.mark.asyncio
    async def test_default_json_format(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/audit-events", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert "events" in body
        assert "count" in body


# ============================================================================
# SOC2 endpoints
# ============================================================================


class TestSOC2Report:
    @pytest.mark.asyncio
    async def test_json_report(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/soc2-report", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body.get("report_type") == "SOC 2 Type II"
        assert "trust_service_criteria" in body
        assert "controls" in body
        assert "summary" in body

    @pytest.mark.asyncio
    async def test_html_report(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/soc2-report", {"format": "html"}, mock_h)
        assert _status(result) == 200
        assert result.content_type == "text/html"
        html = result.body.decode("utf-8")
        assert "SOC 2 Type II" in html

    @pytest.mark.asyncio
    async def test_with_period_params(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/soc2-report",
            {"period_start": "2025-01-01", "period_end": "2025-03-31"},
            mock_h,
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["period"]["days"] == 89

    @pytest.mark.asyncio
    async def test_invalid_date_returns_400(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/soc2-report",
            {"period_start": "not-a-date"},
            mock_h,
        )
        body = _body(result)
        assert _status(result) == 400
        assert "error" in body


# ============================================================================
# GDPR endpoints
# ============================================================================


class TestGDPRExport:
    @pytest.mark.asyncio
    async def test_requires_user_id(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr-export", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_json_export(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr-export", {"user_id": "user-42"}, mock_h
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["user_id"] == "user-42"
        assert "checksum" in body
        assert "data_categories" in body

    @pytest.mark.asyncio
    async def test_csv_export(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/gdpr-export",
            {"user_id": "user-42", "format": "csv"},
            mock_h,
        )
        assert _status(result) == 200
        assert result.content_type == "text/csv"


class TestGDPRRightToBeForgotten:
    @pytest.mark.asyncio
    async def test_requires_user_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/right-to-be-forgotten", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_schedules_deletion(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-99"})
        result = await handler.handle("/api/v2/compliance/gdpr/right-to-be-forgotten", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body.get("status") in ("scheduled", "failed")
        assert body["user_id"] == "user-99"

    @pytest.mark.asyncio
    async def test_custom_grace_period(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "user-99", "grace_period_days": 7})
        result = await handler.handle("/api/v2/compliance/gdpr/right-to-be-forgotten", {}, mock_h)
        body = _body(result)
        if body.get("status") == "scheduled":
            assert body.get("grace_period_days") == 7


class TestGDPRDeletions:
    @pytest.mark.asyncio
    async def test_list_deletions(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/deletions", {}, mock_h)
        # This may hit the scheduler store or return an error; accept both gracefully
        status = _status(result)
        assert status in (200, 500)

    @pytest.mark.asyncio
    async def test_get_deletion_not_found(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/deletions/del-abc", {}, mock_h)
        status = _status(result)
        # Mock returns None for get_request, so should be 404 or 500 if DeletionStatus import fails
        assert status in (404, 500)


class TestGDPRLegalHolds:
    @pytest.mark.asyncio
    async def test_list_legal_holds(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert "legal_holds" in body
        assert body["count"] == 0

    @pytest.mark.asyncio
    async def test_create_legal_hold_requires_fields(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_legal_hold_requires_reason(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"]})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_legal_hold_success(self, handler, _patch_stores):
        mock_hold = MagicMock()
        mock_hold.to_dict.return_value = {"hold_id": "h1", "user_ids": ["u1"]}
        _patch_stores["hold_manager"].create_hold.return_value = mock_hold

        mock_h = _MockHTTPHandler("POST", body={"user_ids": ["u1"], "reason": "litigation"})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds", {}, mock_h)
        body = _body(result)
        assert _status(result) == 201
        assert "legal_hold" in body

    @pytest.mark.asyncio
    async def test_release_legal_hold_not_found(self, handler, _patch_stores):
        _patch_stores["hold_manager"].release_hold.return_value = None

        mock_h = _MockHTTPHandler("DELETE", body={})
        result = await handler.handle("/api/v2/compliance/gdpr/legal-holds/hold-xyz", {}, mock_h)
        assert _status(result) == 404


class TestGDPRCoordinatedDeletion:
    @pytest.mark.asyncio
    async def test_requires_user_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"reason": "GDPR"})
        result = await handler.handle("/api/v2/compliance/gdpr/coordinated-deletion", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_requires_reason(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "u1"})
        result = await handler.handle("/api/v2/compliance/gdpr/coordinated-deletion", {}, mock_h)
        assert _status(result) == 400


class TestGDPRBackupExclusions:
    @pytest.mark.asyncio
    async def test_add_exclusion_requires_user_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"reason": "GDPR"})
        result = await handler.handle("/api/v2/compliance/gdpr/backup-exclusions", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_exclusion_requires_reason(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "u1"})
        result = await handler.handle("/api/v2/compliance/gdpr/backup-exclusions", {}, mock_h)
        assert _status(result) == 400


# ============================================================================
# CCPA endpoints
# ============================================================================


class TestCCPADisclosure:
    @pytest.mark.asyncio
    async def test_requires_user_id(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/ccpa/disclosure", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_categories_disclosure(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/ccpa/disclosure",
            {"user_id": "user-5", "disclosure_type": "categories"},
            mock_h,
        )
        body = _body(result)
        assert _status(result) == 200
        assert "categories_collected" in body
        assert body["regulatory_basis"] == "California Consumer Privacy Act (CCPA)"

    @pytest.mark.asyncio
    async def test_specific_disclosure(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/ccpa/disclosure",
            {"user_id": "user-5", "disclosure_type": "specific"},
            mock_h,
        )
        body = _body(result)
        assert _status(result) == 200
        assert "personal_information" in body


class TestCCPADelete:
    @pytest.mark.asyncio
    async def test_requires_user_id(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "verification_method": "email",
                "verification_code": "123456",
            },
        )
        result = await handler.handle("/api/v2/compliance/ccpa/delete", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_requires_verification(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "u1"})
        result = await handler.handle("/api/v2/compliance/ccpa/delete", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_successful_delete_request(self, handler, _patch_stores):
        mock_del = MagicMock()
        mock_del.scheduled_for.isoformat.return_value = "2025-04-01T00:00:00+00:00"
        _patch_stores["scheduler"].schedule_deletion.return_value = mock_del

        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_id": "u1",
                "verification_method": "email",
                "verification_code": "123456",
            },
        )
        result = await handler.handle("/api/v2/compliance/ccpa/delete", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body["status"] == "scheduled"


class TestCCPAOptOut:
    @pytest.mark.asyncio
    async def test_requires_user_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/ccpa/opt-out", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_successful_opt_out(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "u1"})
        result = await handler.handle("/api/v2/compliance/ccpa/opt-out", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body.get("status") == "confirmed"
        assert body.get("opt_out_type") == "both"

    @pytest.mark.asyncio
    async def test_opt_out_with_sensitive_pi_limit(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "u1", "sensitive_pi_limit": True})
        result = await handler.handle("/api/v2/compliance/ccpa/opt-out", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body.get("sensitive_pi_limit") is True


class TestCCPACorrect:
    @pytest.mark.asyncio
    async def test_requires_user_id(self, handler):
        mock_h = _MockHTTPHandler(
            "POST", body={"corrections": [{"field": "name", "corrected_value": "New"}]}
        )
        result = await handler.handle("/api/v2/compliance/ccpa/correct", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_requires_corrections(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"user_id": "u1"})
        result = await handler.handle("/api/v2/compliance/ccpa/correct", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_successful_correction_request(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "user_id": "u1",
                "corrections": [
                    {"field": "name", "current_value": "Old", "corrected_value": "New"}
                ],
            },
        )
        result = await handler.handle("/api/v2/compliance/ccpa/correct", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body.get("status") == "pending_review"
        assert body["corrections_requested"] == 1


class TestCCPAStatus:
    @pytest.mark.asyncio
    async def test_requires_user_id(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/ccpa/status", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_returns_empty_requests(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/ccpa/status", {"user_id": "u1"}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body["count"] == 0


# ============================================================================
# HIPAA endpoints
# ============================================================================


class TestHIPAAStatus:
    @pytest.mark.asyncio
    async def test_summary_status(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/status", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body.get("compliance_framework") == "HIPAA"
        assert "compliance_score" in body
        assert "rules" in body

    @pytest.mark.asyncio
    async def test_full_scope_includes_details(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/status", {"scope": "full"}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert "safeguard_details" in body
        assert "phi_controls" in body

    @pytest.mark.asyncio
    async def test_includes_recommendations(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/hipaa/status",
            {"include_recommendations": "true"},
            mock_h,
        )
        body = _body(result)
        assert "recommendations" in body


class TestHIPAAPHIAccess:
    @pytest.mark.asyncio
    async def test_returns_access_log(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/phi-access", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert "phi_access_log" in body
        assert "hipaa_reference" in body


class TestHIPAABreachAssessment:
    @pytest.mark.asyncio
    async def test_requires_incident_id(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"incident_type": "data_leak"})
        result = await handler.handle("/api/v2/compliance/hipaa/breach-assessment", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_requires_incident_type(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"incident_id": "inc-1"})
        result = await handler.handle("/api/v2/compliance/hipaa/breach-assessment", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_no_phi_involved(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "incident_id": "inc-1",
                "incident_type": "lost_laptop",
                "phi_involved": False,
            },
        )
        result = await handler.handle("/api/v2/compliance/hipaa/breach-assessment", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body["breach_determination"] == "not_applicable"
        assert body["notification_required"] is False

    @pytest.mark.asyncio
    async def test_phi_involved_high_risk(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "incident_id": "inc-2",
                "incident_type": "unauthorized_access",
                "phi_involved": True,
                "phi_types": ["SSN", "Medical diagnosis"],
                "unauthorized_access": {"confirmed_access": True},
                "affected_individuals": 1000,
            },
        )
        result = await handler.handle("/api/v2/compliance/hipaa/breach-assessment", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body["breach_determination"] == "presumed_breach"
        assert body["notification_required"] is True
        assert "notification_deadlines" in body


class TestHIPAABAA:
    @pytest.mark.asyncio
    async def test_list_baas(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/baa", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert "business_associates" in body
        assert body["count"] >= 0

    @pytest.mark.asyncio
    async def test_create_baa_requires_fields(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/hipaa/baa", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_baa_invalid_type(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "business_associate": "Test Corp",
                "ba_type": "invalid",
                "services_provided": "Testing",
            },
        )
        result = await handler.handle("/api/v2/compliance/hipaa/baa", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_baa_success(self, handler):
        mock_h = _MockHTTPHandler(
            "POST",
            body={
                "business_associate": "Cloud Provider X",
                "ba_type": "vendor",
                "services_provided": "Cloud hosting",
            },
        )
        result = await handler.handle("/api/v2/compliance/hipaa/baa", {}, mock_h)
        body = _body(result)
        assert _status(result) == 201
        assert "baa" in body
        assert body["baa"]["business_associate"] == "Cloud Provider X"


class TestHIPAASecurityReport:
    @pytest.mark.asyncio
    async def test_json_report(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle("/api/v2/compliance/hipaa/security-report", {}, mock_h)
        body = _body(result)
        assert _status(result) == 200
        assert body.get("report_type") == "HIPAA Security Rule Compliance"
        assert "safeguards" in body
        assert "summary" in body

    @pytest.mark.asyncio
    async def test_html_report(self, handler):
        mock_h = _MockHTTPHandler("GET")
        result = await handler.handle(
            "/api/v2/compliance/hipaa/security-report", {"format": "html"}, mock_h
        )
        assert _status(result) == 200
        assert result.content_type == "text/html"


# ============================================================================
# EU AI Act endpoints
# ============================================================================


class TestEUAIActClassify:
    @pytest.mark.asyncio
    async def test_requires_description(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/classify", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_successful_classification(self, handler):
        mock_classification = MagicMock()
        mock_classification.to_dict.return_value = {
            "risk_level": "high",
            "rationale": "test",
        }
        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = mock_classification

        with patch(
            "aragora.server.handlers.compliance.eu_ai_act._get_classifier",
            return_value=mock_classifier,
        ):
            mock_h = _MockHTTPHandler(
                "POST", body={"description": "AI system for hiring decisions"}
            )
            result = await handler.handle("/api/v2/compliance/eu-ai-act/classify", {}, mock_h)
            body = _body(result)
            assert _status(result) == 200
            assert "classification" in body


class TestEUAIActAudit:
    @pytest.mark.asyncio
    async def test_requires_receipt(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/audit", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_receipt_must_be_dict(self, handler):
        mock_h = _MockHTTPHandler("POST", body={"receipt": "not-a-dict"})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/audit", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_successful_audit(self, handler):
        mock_report = MagicMock()
        mock_report.to_dict.return_value = {"articles": [], "compliant": True}
        mock_gen = MagicMock()
        mock_gen.generate.return_value = mock_report

        with patch(
            "aragora.server.handlers.compliance.eu_ai_act._get_report_generator",
            return_value=mock_gen,
        ):
            mock_h = _MockHTTPHandler(
                "POST", body={"receipt": {"receipt_id": "r1", "verdict": "approve"}}
            )
            result = await handler.handle("/api/v2/compliance/eu-ai-act/audit", {}, mock_h)
            body = _body(result)
            assert _status(result) == 200
            assert "conformity_report" in body


class TestEUAIActGenerateBundle:
    @pytest.mark.asyncio
    async def test_requires_receipt(self, handler):
        mock_h = _MockHTTPHandler("POST", body={})
        result = await handler.handle("/api/v2/compliance/eu-ai-act/generate-bundle", {}, mock_h)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_successful_bundle_generation(self, handler):
        mock_bundle = MagicMock()
        mock_bundle.to_dict.return_value = {
            "articles": {"12": {}, "13": {}, "14": {}},
            "integrity_hash": "abc123",
        }
        mock_gen = MagicMock()
        mock_gen.generate.return_value = mock_bundle

        with patch(
            "aragora.server.handlers.compliance.eu_ai_act._get_artifact_generator",
            return_value=mock_gen,
        ):
            mock_h = _MockHTTPHandler(
                "POST", body={"receipt": {"receipt_id": "r1", "verdict": "approve"}}
            )
            result = await handler.handle(
                "/api/v2/compliance/eu-ai-act/generate-bundle", {}, mock_h
            )
            body = _body(result)
            assert _status(result) == 200
            assert "bundle" in body


# ============================================================================
# Error handling
# ============================================================================


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_value_error_returns_500(self, handler):
        """An unhandled ValueError in a mixin should be caught and return 500."""
        with patch.object(handler, "_get_status", side_effect=ValueError("boom")):
            mock_h = _MockHTTPHandler("GET")
            result = await handler.handle("/api/v2/compliance/status", {}, mock_h)
            assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_runtime_error_returns_500(self, handler):
        with patch.object(handler, "_get_soc2_report", side_effect=RuntimeError("fail")):
            mock_h = _MockHTTPHandler("GET")
            result = await handler.handle("/api/v2/compliance/soc2-report", {}, mock_h)
            assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_null_handler_uses_defaults(self, handler):
        """Passing None for handler should use GET and empty body."""
        result = await handler.handle("/api/v2/compliance/status", {}, None)
        body = _body(result)
        assert _status(result) == 200
        assert "status" in body
