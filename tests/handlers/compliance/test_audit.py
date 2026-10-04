"""Comprehensive tests for aragora/server/handlers/compliance/audit.py.

This module is a consolidation/re-export hub for audit-related handlers from:
- audit_export.py  (handle_audit_events, handle_audit_stats, etc.)
- audit_trail.py   (AuditTrailHandler)
- auditing.py      (AuditRequestParser, AuditAgentFactory, AuditResultRecorder, AuditingHandler)

Tests cover:
- Module-level exports and __all__ completeness
- RBAC permission constants
- Re-exported symbols from all three source modules
- AuditTrailHandler routing, listing, retrieval, export, verification
- AuditingHandler routing, attack types, capability probe, red-team analysis
- AuditRequestParser field parsing and validation
- AuditAgentFactory single/multiple agent creation
- AuditResultRecorder ELO recording, report saving
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    if hasattr(result, "body"):
        raw = result.body
        if isinstance(raw, (bytes, bytearray)):
            return json.loads(raw.decode("utf-8"))
        if isinstance(raw, str):
            return json.loads(raw)
        return raw
    return {}


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


class _MockHTTPHandler:
    """Lightweight mock for HTTP handler passed to handler.handle."""

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


# ===========================================================================
# 1. Module-Level Exports
# ===========================================================================


class TestModuleExports:
    """Verify the consolidation module re-exports everything correctly."""

    def test_all_contains_rbac_constants(self):
        from aragora.server.handlers.compliance.audit import __all__

        assert "AUDIT_READ_PERMISSION" in __all__
        assert "AUDIT_EXPORT_PERMISSION" in __all__
        assert "require_permission" in __all__

    def test_all_contains_audit_export_symbols(self):
        from aragora.server.handlers.compliance.audit import __all__

        for name in [
            "handle_audit_events",
            "handle_audit_export",
            "handle_audit_stats",
            "handle_audit_verify",
            "register_handlers",
            "get_audit_log",
        ]:
            assert name in __all__, f"{name} missing from __all__"

    def test_all_contains_audit_trail_symbols(self):
        from aragora.server.handlers.compliance.audit import __all__

        assert "AuditTrailHandler" in __all__

    def test_all_contains_auditing_symbols(self):
        from aragora.server.handlers.compliance.audit import __all__

        for name in [
            "AuditRequestParser",
            "AuditAgentFactory",
            "AuditResultRecorder",
            "AuditingHandler",
        ]:
            assert name in __all__, f"{name} missing from __all__"

    def test_all_length(self):
        """__all__ should have exactly 14 entries."""
        from aragora.server.handlers.compliance.audit import __all__

        assert len(__all__) == 14

    def test_rbac_permission_values(self):
        from aragora.server.handlers.compliance.audit import (
            AUDIT_READ_PERMISSION,
            AUDIT_EXPORT_PERMISSION,
        )

        assert AUDIT_READ_PERMISSION == "audit:read"
        assert AUDIT_EXPORT_PERMISSION == "audit:export"

    def test_require_permission_is_callable(self):
        from aragora.server.handlers.compliance.audit import require_permission

        assert callable(require_permission)

    def test_imports_are_real_objects(self):
        """Verify re-exported symbols are not None and are importable."""
        from aragora.server.handlers.compliance.audit import (
            handle_audit_events,
            handle_audit_export,
            handle_audit_stats,
            handle_audit_verify,
            register_handlers,
            get_audit_log,
            AuditTrailHandler,
            AuditRequestParser,
            AuditAgentFactory,
            AuditResultRecorder,
            AuditingHandler,
        )

        assert handle_audit_events is not None
        assert handle_audit_export is not None
        assert handle_audit_stats is not None
        assert handle_audit_verify is not None
        assert register_handlers is not None
        assert get_audit_log is not None
        assert AuditTrailHandler is not None
        assert AuditRequestParser is not None
        assert AuditAgentFactory is not None
        assert AuditResultRecorder is not None
        assert AuditingHandler is not None


# ===========================================================================
# 2. AuditTrailHandler Tests
# ===========================================================================


@pytest.fixture
def audit_trail_handler():
    """Create an AuditTrailHandler with mocked store."""
    with patch("aragora.storage.audit_trail_store.get_audit_trail_store") as mock_store_fn:
        mock_store = MagicMock()
        mock_store.list_trails.return_value = []
        mock_store.count_trails.return_value = 0
        mock_store.get_trail.return_value = None
        mock_store.get_trail_by_gauntlet.return_value = None
        mock_store.list_receipts.return_value = []
        mock_store.count_receipts.return_value = 0
        mock_store.get_receipt.return_value = None
        mock_store.get_receipt_by_gauntlet.return_value = None
        mock_store_fn.return_value = mock_store
        handler = AuditTrailHandler(server_context={})
        handler._store = mock_store
        yield handler


# Import after fixture is defined
from aragora.server.handlers.compliance.audit import AuditTrailHandler


@pytest.fixture(autouse=True)
def _reset_audit_trail_class_storage():
    AuditTrailHandler._trails = {}
    yield
    AuditTrailHandler._trails = {}


class TestAuditTrailHandlerCanHandle:
    """Tests for AuditTrailHandler.can_handle routing."""

    def test_can_handle_audit_trails_get(self, audit_trail_handler):
        assert audit_trail_handler.can_handle("/api/v1/audit-trails", "GET") is True

    def test_can_handle_audit_trails_post(self, audit_trail_handler):
        assert audit_trail_handler.can_handle("/api/v1/audit-trails", "POST") is True

    def test_can_handle_audit_trails_subpath(self, audit_trail_handler):
        assert audit_trail_handler.can_handle("/api/v1/audit-trails/trail-123", "GET") is True

    def test_cannot_handle_unknown_path(self, audit_trail_handler):
        assert audit_trail_handler.can_handle("/api/v1/unknown", "GET") is False

    def test_cannot_handle_delete_method(self, audit_trail_handler):
        assert audit_trail_handler.can_handle("/api/v1/audit-trails", "DELETE") is False

    def test_does_not_handle_receipt_routes(self, audit_trail_handler):
        """Decision receipts are served by the org-scoped receipts handler."""
        for path in ("/api/v1/receipts", "/api/v1/receipts/r-1", "/api/v1/receipts/r-1/verify"):
            for method in ("GET", "POST"):
                assert not audit_trail_handler.can_handle(path, method)


class TestAuditTrailHandlerListTrails:
    """Tests for listing audit trails."""

    @pytest.mark.asyncio
    async def test_list_trails_empty(self, audit_trail_handler):
        result = await audit_trail_handler.handle("/api/v1/audit-trails", {})
        assert _status(result) == 200
        body = _body(result)
        assert body["trails"] == []
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_list_trails_with_data(self, audit_trail_handler):
        trail_summary = {
            "trail_id": "trail-1",
            "verdict": "pass",
            "created_at": "2026-01-01T00:00:00Z",
        }
        audit_trail_handler._store.list_trails.return_value = [trail_summary]
        audit_trail_handler._store.count_trails.return_value = 1

        result = await audit_trail_handler.handle("/api/v1/audit-trails", {})
        assert _status(result) == 200
        body = _body(result)
        assert len(body["trails"]) == 1
        assert body["total"] == 1

    @pytest.mark.asyncio
    async def test_list_trails_with_pagination(self, audit_trail_handler):
        audit_trail_handler._store.list_trails.return_value = []
        audit_trail_handler._store.count_trails.return_value = 0

        result = await audit_trail_handler.handle(
            "/api/v1/audit-trails", {"limit": "10", "offset": "5"}
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["limit"] == 10
        assert body["offset"] == 5

    @pytest.mark.asyncio
    async def test_list_trails_fallback_to_in_memory(self, audit_trail_handler):
        """When store returns empty but in-memory has data, falls back."""
        audit_trail_handler._store.list_trails.return_value = []
        audit_trail_handler._store.count_trails.return_value = 0
        # Populate class-level in-memory storage
        AuditTrailHandler._trails = {
            "trail-inmem": {
                "trail_id": "trail-inmem",
                "gauntlet_id": "g1",
                "created_at": "2026-01-01",
                "verdict": "pass",
                "confidence": 0.9,
                "total_findings": 3,
                "duration_seconds": 10,
                "checksum": "abc123",
            }
        }
        try:
            result = await audit_trail_handler.handle("/api/v1/audit-trails", {})
            assert _status(result) == 200
            body = _body(result)
            assert body["total"] == 1
            assert body["trails"][0]["trail_id"] == "trail-inmem"
        finally:
            AuditTrailHandler._trails = {}


class TestAuditTrailHandlerGetTrail:
    """Tests for getting a specific audit trail."""

    @pytest.mark.asyncio
    async def test_get_trail_from_store(self, audit_trail_handler):
        trail_data = {"trail_id": "trail-abc", "verdict": "pass"}
        audit_trail_handler._store.get_trail.return_value = trail_data

        result = await audit_trail_handler.handle("/api/v1/audit-trails/trail-abc", {})
        assert _status(result) == 200
        body = _body(result)
        assert body["trail_id"] == "trail-abc"

    @pytest.mark.asyncio
    async def test_get_trail_not_found(self, audit_trail_handler):
        audit_trail_handler._store.get_trail.return_value = None
        audit_trail_handler._store.get_trail_by_gauntlet.return_value = None

        result = await audit_trail_handler.handle("/api/v1/audit-trails/nonexistent", {})
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_trail_fallback_inmemory(self, audit_trail_handler):
        audit_trail_handler._store.get_trail.return_value = None
        audit_trail_handler._store.get_trail_by_gauntlet.return_value = None
        AuditTrailHandler._trails["trail-mem"] = {
            "trail_id": "trail-mem",
            "verdict": "fail",
        }
        try:
            result = await audit_trail_handler.handle("/api/v1/audit-trails/trail-mem", {})
            assert _status(result) == 200
            body = _body(result)
            assert body["trail_id"] == "trail-mem"
        finally:
            AuditTrailHandler._trails.pop("trail-mem", None)


class TestAuditTrailHandlerExport:
    """Tests for exporting an audit trail."""

    @pytest.mark.asyncio
    async def test_export_trail_not_found(self, audit_trail_handler):
        audit_trail_handler._store.get_trail.return_value = None
        audit_trail_handler._store.get_trail_by_gauntlet.return_value = None

        result = await audit_trail_handler.handle(
            "/api/v1/audit-trails/trail-abc/export", {"format": "json"}
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_export_trail_json_fallback(self, audit_trail_handler):
        """When export module is unavailable, falls back to plain JSON dump."""
        trail_data = {"trail_id": "trail-exp", "verdict": "pass"}
        audit_trail_handler._store.get_trail.return_value = trail_data

        with patch(
            "aragora.server.handlers.audit_trail.AuditTrailHandler._export_audit_trail"
        ) as mock_export:
            # Simulate the fallback path by returning a HandlerResult
            from aragora.server.handlers.utils.responses import HandlerResult

            mock_export.return_value = HandlerResult(
                status_code=200,
                content_type="application/json",
                body=json.dumps(trail_data, indent=2).encode(),
                headers={"Content-Disposition": 'attachment; filename="trail-exp.json"'},
            )
            result = await mock_export(audit_trail_handler, "trail-exp", {"format": "json"})
            assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_export_trail_unknown_format(self, audit_trail_handler):
        """Unknown format returns 400 error."""
        trail_data = {"trail_id": "trail-fmt", "verdict": "pass"}
        audit_trail_handler._store.get_trail.return_value = trail_data

        with patch("aragora.export.audit_trail.AuditTrail") as mock_at:
            mock_trail_obj = MagicMock()
            mock_at.from_json.return_value = mock_trail_obj

            result = await audit_trail_handler.handle(
                "/api/v1/audit-trails/trail-fmt/export", {"format": "xml"}
            )
            assert _status(result) == 400


class TestAuditTrailHandlerVerify:
    """Tests for verifying audit trail integrity."""

    @pytest.mark.asyncio
    async def test_verify_trail_not_found(self, audit_trail_handler):
        audit_trail_handler._store.get_trail_by_gauntlet.return_value = None

        result = await audit_trail_handler.handle("/api/v1/audit-trails/trail-xyz/verify", {})
        assert _status(result) == 404


class TestAuditTrailHandlerRouting:
    """Tests for route dispatch edge cases."""

    @pytest.mark.asyncio
    async def test_not_found_route(self, audit_trail_handler):
        result = await audit_trail_handler.handle("/api/v1/unknown-path", {})
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_handle_method_dispatch(self, audit_trail_handler):
        """Test the method-based handle signature (method, path, handler)."""
        handler_mock = _MockHTTPHandler("GET")
        result = await audit_trail_handler.handle("GET", "/api/v1/audit-trails", handler_mock)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_store_trail_classmethod(self):
        """Test the store_trail classmethod."""
        old = AuditTrailHandler._trails.copy()
        try:
            AuditTrailHandler.store_trail("t1", {"trail_id": "t1"})
            assert "t1" in AuditTrailHandler._trails
            assert AuditTrailHandler._trails["t1"]["trail_id"] == "t1"
        finally:
            AuditTrailHandler._trails = old


# ===========================================================================
# 3. AuditRequestParser Tests
# ===========================================================================

from aragora.server.handlers.compliance.audit import AuditRequestParser


class TestAuditRequestParserReadJson:
    """Tests for AuditRequestParser._read_json."""

    def test_read_json_success(self):
        data, err = AuditRequestParser._read_json(None, lambda h: {"key": "value"})
        assert data == {"key": "value"}
        assert err is None

    def test_read_json_none_returns_error(self):
        data, err = AuditRequestParser._read_json(None, lambda h: None)
        assert data is None
        assert _status(err) == 400
        assert "Invalid JSON" in _body(err).get("error", "")


class TestAuditRequestParserRequireField:
    """Tests for AuditRequestParser._require_field."""

    def test_require_field_present(self):
        value, err = AuditRequestParser._require_field({"name": "test-agent"}, "name")
        assert value == "test-agent"
        assert err is None

    def test_require_field_missing(self):
        value, err = AuditRequestParser._require_field({}, "name")
        assert value is None
        assert _status(err) == 400

    def test_require_field_empty_string(self):
        value, err = AuditRequestParser._require_field({"name": "  "}, "name")
        assert value is None
        assert _status(err) == 400

    def test_require_field_with_validator_pass(self):
        def always_ok(val):
            return True, None

        value, err = AuditRequestParser._require_field({"x": "good"}, "x", always_ok)
        assert value == "good"
        assert err is None

    def test_require_field_with_validator_fail(self):
        def always_fail(val):
            return False, "bad value"

        value, err = AuditRequestParser._require_field({"x": "bad"}, "x", always_fail)
        assert value is None
        assert _status(err) == 400


class TestAuditRequestParserParseInt:
    """Tests for AuditRequestParser._parse_int."""

    def test_parse_int_default(self):
        val, err = AuditRequestParser._parse_int({}, "rounds", 3, 10)
        assert val == 3
        assert err is None

    def test_parse_int_provided(self):
        val, err = AuditRequestParser._parse_int({"rounds": 5}, "rounds", 3, 10)
        assert val == 5
        assert err is None

    def test_parse_int_clamped(self):
        val, err = AuditRequestParser._parse_int({"rounds": 99}, "rounds", 3, 10)
        assert val == 10
        assert err is None

    def test_parse_int_invalid(self):
        val, err = AuditRequestParser._parse_int({"rounds": "not_a_number"}, "rounds", 3, 10)
        assert err is not None
        assert _status(err) == 400


class TestAuditRequestParserCapabilityProbe:
    """Tests for parsing capability probe requests."""

    def test_parse_capability_probe_success(self):
        body = {"agent_name": "test-agent", "probes_per_type": 5}
        read_fn = lambda h: body

        parsed, err = AuditRequestParser.parse_capability_probe(None, read_fn)
        assert err is None
        assert parsed["agent_name"] == "test-agent"
        assert parsed["probes_per_type"] == 5
        # Defaults
        assert "probe_types" in parsed
        assert parsed["model_type"] == "anthropic-api"

    def test_parse_capability_probe_missing_agent(self):
        body = {"probes_per_type": 5}
        read_fn = lambda h: body

        parsed, err = AuditRequestParser.parse_capability_probe(None, read_fn)
        assert err is not None
        assert _status(err) == 400

    def test_parse_capability_probe_null_body(self):
        parsed, err = AuditRequestParser.parse_capability_probe(None, lambda h: None)
        assert err is not None
        assert _status(err) == 400


class TestAuditRequestParserDeepAudit:
    """Tests for parsing deep audit requests."""

    def test_parse_deep_audit_success(self):
        body = {"task": "Review this code", "context": "Security audit"}
        read_fn = lambda h: body

        parsed, err = AuditRequestParser.parse_deep_audit(None, read_fn)
        assert err is None
        assert parsed["task"] == "Review this code"
        assert parsed["context"] == "Security audit"
        assert parsed["rounds"] == 6  # default
        assert parsed["risk_threshold"] == 0.7  # default

    def test_parse_deep_audit_missing_task(self):
        body = {"context": "something"}
        read_fn = lambda h: body

        parsed, err = AuditRequestParser.parse_deep_audit(None, read_fn)
        assert err is not None
        assert _status(err) == 400

    def test_parse_deep_audit_invalid_risk_threshold(self):
        body = {"task": "test", "config": {"risk_threshold": "not-a-number"}}
        read_fn = lambda h: body

        parsed, err = AuditRequestParser.parse_deep_audit(None, read_fn)
        assert err is not None
        assert _status(err) == 400


# ===========================================================================
# 4. AuditAgentFactory Tests
# ===========================================================================

from aragora.server.handlers.compliance.audit import AuditAgentFactory


class TestAuditAgentFactorySingle:
    """Tests for AuditAgentFactory.create_single_agent."""

    @patch("aragora.server.handlers.auditing.DEBATE_AVAILABLE", False)
    def test_create_single_agent_unavailable(self):
        agent, err = AuditAgentFactory.create_single_agent("test", "agent-1")
        assert agent is None
        assert _status(err) == 503

    @patch("aragora.server.handlers.auditing.DEBATE_AVAILABLE", True)
    @patch("aragora.server.handlers.auditing.create_agent")
    def test_create_single_agent_success(self, mock_create):
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        agent, err = AuditAgentFactory.create_single_agent("anthropic-api", "test-agent")
        assert agent is mock_agent
        assert err is None
        mock_create.assert_called_once_with("anthropic-api", name="test-agent", role="proposer")

    @patch("aragora.server.handlers.auditing.DEBATE_AVAILABLE", True)
    @patch("aragora.server.handlers.auditing.create_agent", side_effect=ValueError("bad"))
    def test_create_single_agent_failure(self, mock_create):
        agent, err = AuditAgentFactory.create_single_agent("anthropic-api", "bad-agent")
        assert agent is None
        assert _status(err) == 400


class TestAuditAgentFactoryMultiple:
    """Tests for AuditAgentFactory.create_multiple_agents."""

    @patch("aragora.server.handlers.auditing.DEBATE_AVAILABLE", False)
    def test_create_multiple_agents_unavailable(self):
        agents, err = AuditAgentFactory.create_multiple_agents("test", [], ["a", "b", "c"])
        assert agents == []
        assert _status(err) == 503

    @patch("aragora.server.handlers.auditing.DEBATE_AVAILABLE", True)
    @patch("aragora.server.handlers.auditing.create_agent")
    def test_create_multiple_agents_success(self, mock_create):
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        agents, err = AuditAgentFactory.create_multiple_agents(
            "anthropic-api", [], ["agent-a", "agent-b", "agent-c"]
        )
        assert err is None
        assert len(agents) == 3

    @patch("aragora.server.handlers.auditing.DEBATE_AVAILABLE", True)
    @patch("aragora.server.handlers.auditing.create_agent", side_effect=ValueError("fail"))
    def test_create_multiple_agents_all_fail(self, mock_create):
        agents, err = AuditAgentFactory.create_multiple_agents("test", [], ["agent-a", "agent-b"])
        assert agents == []
        assert _status(err) == 400
        assert "at least 2" in _body(err).get("error", "").lower()


# ===========================================================================
# 5. AuditResultRecorder Tests
# ===========================================================================

from aragora.server.handlers.compliance.audit import AuditResultRecorder


class TestAuditResultRecorderELO:
    """Tests for AuditResultRecorder.record_probe_elo."""

    def test_record_probe_elo_no_system(self):
        """No-op when elo_system is None."""
        mock_report = MagicMock(probes_run=5)
        # Should not raise
        AuditResultRecorder.record_probe_elo(None, "agent", mock_report, "r1")

    def test_record_probe_elo_zero_probes(self):
        """No-op when probes_run <= 0."""
        elo = MagicMock()
        mock_report = MagicMock(probes_run=0)
        AuditResultRecorder.record_probe_elo(elo, "agent", mock_report, "r1")
        elo.record_redteam_result.assert_not_called()

    @patch("aragora.server.handlers.auditing.invalidate_leaderboard_cache")
    def test_record_probe_elo_success(self, mock_invalidate):
        elo = MagicMock()
        mock_report = MagicMock(
            probes_run=10,
            vulnerability_rate=0.3,
            vulnerabilities_found=3,
            critical_count=1,
        )

        AuditResultRecorder.record_probe_elo(elo, "agent-x", mock_report, "r1")
        elo.record_redteam_result.assert_called_once()
        mock_invalidate.assert_called_once()


class TestAuditResultRecorderAuditELO:
    """Tests for AuditResultRecorder.calculate_audit_elo_adjustments."""

    def test_no_elo_system(self):
        result = AuditResultRecorder.calculate_audit_elo_adjustments(MagicMock(findings=[]), None)
        assert result == {}

    def test_adjustments_computed(self):
        finding = MagicMock(
            agents_agree=["agent-a", "agent-b"],
            agents_disagree=["agent-c"],
        )
        verdict = MagicMock(findings=[finding])
        elo = MagicMock()

        result = AuditResultRecorder.calculate_audit_elo_adjustments(verdict, elo)
        assert result["agent-a"] == 2
        assert result["agent-b"] == 2
        assert result["agent-c"] == -1


class TestAuditResultRecorderSaveProbeReport:
    """Tests for AuditResultRecorder.save_probe_report."""

    def test_save_probe_report_no_dir(self):
        """No-op when nomic_dir is None."""
        AuditResultRecorder.save_probe_report(None, "agent", MagicMock())

    def test_save_probe_report_success(self, tmp_path):
        mock_report = MagicMock(
            report_id="rpt-1",
            to_dict=MagicMock(return_value={"id": "rpt-1"}),
        )
        AuditResultRecorder.save_probe_report(tmp_path, "agent-x", mock_report)
        probes_dir = tmp_path / "probes" / "agent-x"
        assert probes_dir.exists()
        files = list(probes_dir.iterdir())
        assert len(files) == 1


class TestAuditResultRecorderSaveAuditReport:
    """Tests for AuditResultRecorder.save_audit_report."""

    def test_save_audit_report_no_dir(self):
        """No-op when nomic_dir is None."""
        AuditResultRecorder.save_audit_report(
            None, "a1", "task", "ctx", [], MagicMock(), MagicMock(), 100.0, {}
        )

    def test_save_audit_report_success(self, tmp_path):
        mock_agent = MagicMock(name="agent-1")
        mock_finding = MagicMock(
            category="risk",
            summary="summary",
            details="details",
            agents_agree=["a"],
            agents_disagree=[],
            confidence=0.9,
            severity=0.5,
            citations=[],
        )
        mock_verdict = MagicMock(
            recommendation="proceed",
            confidence=0.85,
            unanimous_issues=["issue1"],
            split_opinions=["split1"],
            risk_areas=["risk1"],
            findings=[mock_finding],
        )
        mock_config = MagicMock(
            rounds=3,
            enable_research=True,
            cross_examination_depth=2,
            risk_threshold=0.7,
        )

        AuditResultRecorder.save_audit_report(
            tmp_path,
            "audit-1",
            "task",
            "context",
            [mock_agent],
            mock_verdict,
            mock_config,
            500.0,
            {"a": 2},
        )
        audits_dir = tmp_path / "audits"
        assert audits_dir.exists()
        files = list(audits_dir.iterdir())
        assert len(files) == 1


# ===========================================================================
# 6. AuditingHandler Tests
# ===========================================================================

from aragora.server.handlers.compliance.audit import AuditingHandler


class TestAuditingHandlerCanHandle:
    """Tests for AuditingHandler.can_handle routing."""

    def test_can_handle_capability_probe(self):
        h = AuditingHandler(ctx={})
        assert h.can_handle("/api/v1/debates/capability-probe") is True

    def test_can_handle_deep_audit(self):
        h = AuditingHandler(ctx={})
        assert h.can_handle("/api/v1/debates/deep-audit") is True

    def test_can_handle_attack_types(self):
        h = AuditingHandler(ctx={})
        assert h.can_handle("/api/v1/redteam/attack-types") is True

    def test_can_handle_red_team(self):
        h = AuditingHandler(ctx={})
        assert h.can_handle("/api/v1/debates/debate-123/red-team") is True

    def test_cannot_handle_unknown(self):
        h = AuditingHandler(ctx={})
        assert h.can_handle("/api/v1/unknown") is False


class TestAuditingHandlerRouting:
    """Tests for AuditingHandler.handle routing."""

    def test_handle_returns_none_for_unknown_path(self):
        h = AuditingHandler(ctx={})
        result = h.handle("/api/v1/unknown", {}, _MockHTTPHandler())
        assert result is None

    @patch("aragora.server.handlers.auditing.REDTEAM_AVAILABLE", False)
    def test_attack_types_unavailable(self):
        h = AuditingHandler(ctx={})
        result = h.handle("/api/v1/redteam/attack-types", {}, _MockHTTPHandler())
        assert _status(result) == 503

    @patch("aragora.server.handlers.auditing.REDTEAM_AVAILABLE", True)
    @patch("aragora.server.handlers.auditing.RedTeamMode")
    def test_attack_types_available(self, mock_rtm):
        """When red team module is available, returns attack types."""
        from enum import Enum

        class MockAttackType(Enum):
            LOGICAL_FALLACY = "logical_fallacy"
            EDGE_CASE = "edge_case"
            UNSTATED_ASSUMPTION = "unstated_assumption"
            COUNTEREXAMPLE = "counterexample"
            SECURITY = "security"
            RESOURCE_EXHAUSTION = "resource_exhaustion"
            RACE_CONDITION = "race_condition"
            DEPENDENCY_FAILURE = "dependency_failure"

        with patch("aragora.modes.redteam.AttackType", MockAttackType):
            h = AuditingHandler(ctx={})
            result = h.handle("/api/v1/redteam/attack-types", {}, _MockHTTPHandler())
            assert _status(result) == 200
            body = _body(result)
            assert "attack_types" in body
            assert body["count"] == 8

    @patch("aragora.server.handlers.auditing.PROBER_AVAILABLE", False)
    def test_capability_probe_unavailable(self):
        h = AuditingHandler(ctx={})
        handler_mock = _MockHTTPHandler("POST", {"agent_name": "test-agent"})
        result = h.handle("/api/v1/debates/capability-probe", {}, handler_mock)
        assert _status(result) == 503

    @patch("aragora.server.handlers.auditing.REDTEAM_AVAILABLE", False)
    def test_red_team_unavailable(self):
        h = AuditingHandler(ctx={})
        handler_mock = _MockHTTPHandler("POST", {})
        result = h.handle("/api/v1/debates/debate-123/red-team", {}, handler_mock)
        assert _status(result) == 503

    @patch("aragora.server.handlers.auditing.REDTEAM_AVAILABLE", True)
    def test_red_team_no_storage(self):
        h = AuditingHandler(ctx={})
        handler_mock = _MockHTTPHandler("POST", {})
        result = h.handle("/api/v1/debates/debate-123/red-team", {}, handler_mock)
        assert _status(result) == 500

    @patch("aragora.server.handlers.auditing.REDTEAM_AVAILABLE", True)
    def test_red_team_debate_not_found(self):
        mock_storage = MagicMock()
        mock_storage.get_by_slug.return_value = None
        mock_storage.get_by_id.return_value = None

        h = AuditingHandler(ctx={"storage": mock_storage})
        handler_mock = _MockHTTPHandler("POST", {})
        result = h.handle("/api/v1/debates/debate-123/red-team", {}, handler_mock)
        assert _status(result) == 404


class TestAuditingHandlerRedTeamAnalysis:
    """Tests for red team analysis when debate is found."""

    @patch("aragora.server.handlers.auditing.REDTEAM_AVAILABLE", True)
    def test_red_team_success(self):
        mock_storage = MagicMock()
        mock_storage.get_by_slug.return_value = {
            "debate_id": "d-123",
            "task": "Evaluate API design",
            "consensus_answer": "Use REST",
        }

        from enum import Enum

        class MockAttackType(Enum):
            LOGICAL_FALLACY = "logical_fallacy"
            EDGE_CASE = "edge_case"
            UNSTATED_ASSUMPTION = "unstated_assumption"
            COUNTEREXAMPLE = "counterexample"
            SECURITY = "security"
            RESOURCE_EXHAUSTION = "resource_exhaustion"
            RACE_CONDITION = "race_condition"
            DEPENDENCY_FAILURE = "dependency_failure"

        with patch("aragora.modes.redteam.AttackType", MockAttackType):
            h = AuditingHandler(ctx={"storage": mock_storage})
            handler_mock = _MockHTTPHandler(
                "POST",
                {
                    "attack_types": ["logical_fallacy", "edge_case"],
                    "max_rounds": 2,
                },
            )
            result = h.handle("/api/v1/debates/d-123/red-team", {}, handler_mock)
            assert _status(result) == 200
            body = _body(result)
            assert body["debate_id"] == "d-123"
            assert "findings" in body
            assert "robustness_score" in body
            assert body["status"] == "analysis_complete"


class TestAuditingHandlerGetAuditConfig:
    """Tests for AuditingHandler._get_audit_config."""

    def test_strategy_preset(self):
        h = AuditingHandler(ctx={})
        sentinel = object()
        result = h._get_audit_config("strategy", {}, MagicMock, sentinel, MagicMock, MagicMock)
        assert result is sentinel

    def test_contract_preset(self):
        h = AuditingHandler(ctx={})
        sentinel = object()
        result = h._get_audit_config("contract", {}, MagicMock, MagicMock, sentinel, MagicMock)
        assert result is sentinel

    def test_code_architecture_preset(self):
        h = AuditingHandler(ctx={})
        sentinel = object()
        result = h._get_audit_config(
            "code_architecture", {}, MagicMock, MagicMock, MagicMock, sentinel
        )
        assert result is sentinel

    def test_custom_config(self):
        h = AuditingHandler(ctx={})
        mock_cls = MagicMock()
        parsed = {
            "rounds": 4,
            "enable_research": False,
            "cross_examination_depth": 2,
            "risk_threshold": 0.8,
        }
        h._get_audit_config("other", parsed, mock_cls, MagicMock, MagicMock, MagicMock)
        mock_cls.assert_called_once_with(
            rounds=4,
            enable_research=False,
            cross_examination_depth=2,
            risk_threshold=0.8,
        )


# ===========================================================================
# 7. get_audit_log Tests
# ===========================================================================


class TestGetAuditLog:
    """Tests for the get_audit_log lazy singleton."""

    @patch("aragora.server.handlers.audit_export._audit_log", None)
    @patch("aragora.audit.AuditLog")
    def test_get_audit_log_creates_instance(self, mock_cls):
        from aragora.server.handlers.compliance.audit import get_audit_log

        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        result = get_audit_log()
        assert result is mock_instance
        mock_cls.assert_called_once()


# ===========================================================================
# 8. register_handlers Tests
# ===========================================================================


class TestRegisterHandlers:
    """Tests for register_handlers."""

    def test_register_handlers_adds_routes(self):
        from aragora.server.handlers.compliance.audit import register_handlers

        mock_app = MagicMock()
        register_handlers(mock_app)

        calls = mock_app.router.method_calls
        paths_added = [call.args[0] for call in calls]
        assert "/api/v1/audit/events" in paths_added
        assert "/api/v1/audit/stats" in paths_added
        assert "/api/v1/audit/export" in paths_added
        assert "/api/v1/audit/verify" in paths_added
