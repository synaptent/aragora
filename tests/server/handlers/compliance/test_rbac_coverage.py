"""
Tests for the RBAC coverage endpoint on the compliance handler.

Tests cover:
- GET /api/v1/compliance/rbac-coverage returns 200 with correct shape
- Response wraps data in {"data": {...}} envelope
- Fields: covered_endpoints, total_endpoints, coverage_pct
- Safe fallback when coverage computation fails
- compute_endpoint_coverage() function contract
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from aragora.server.handlers.compliance.handler import ComplianceHandler
from aragora.server.handlers.base import HandlerResult


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def compliance_handler():
    """Create a compliance handler instance."""
    return ComplianceHandler(server_context={})


@pytest.fixture
def mock_handler_get():
    """Create a mock HTTP handler for GET requests."""
    handler = MagicMock()
    handler.command = "GET"
    handler.headers = {}
    return handler


# ============================================================================
# Unit tests for compute_endpoint_coverage()
# ============================================================================


class TestComputeEndpointCoverage:
    """Tests for the compute_endpoint_coverage helper in aragora.rbac.audit."""

    def test_returns_dict_with_required_keys(self):
        """compute_endpoint_coverage returns a dict with the expected keys."""
        from aragora.rbac.audit import compute_endpoint_coverage

        result = compute_endpoint_coverage()
        assert isinstance(result, dict)
        assert "covered_endpoints" in result
        assert "total_endpoints" in result
        assert "coverage_pct" in result

    def test_total_endpoints_is_non_negative(self):
        """total_endpoints is >= 0."""
        from aragora.rbac.audit import compute_endpoint_coverage

        result = compute_endpoint_coverage()
        assert result["total_endpoints"] >= 0

    def test_covered_endpoints_lte_total(self):
        """covered_endpoints <= total_endpoints."""
        from aragora.rbac.audit import compute_endpoint_coverage

        result = compute_endpoint_coverage()
        assert result["covered_endpoints"] <= result["total_endpoints"]

    def test_coverage_pct_in_valid_range(self):
        """coverage_pct is between 0.0 and 100.0."""
        from aragora.rbac.audit import compute_endpoint_coverage

        result = compute_endpoint_coverage()
        assert 0.0 <= result["coverage_pct"] <= 100.0

    def test_coverage_pct_matches_counts(self):
        """coverage_pct is consistent with covered/total ratio."""
        from aragora.rbac.audit import compute_endpoint_coverage

        result = compute_endpoint_coverage()
        total = result["total_endpoints"]
        covered = result["covered_endpoints"]
        pct = result["coverage_pct"]
        if total > 0:
            expected = round(covered / total * 100, 1)
            assert abs(pct - expected) < 0.2, f"pct {pct} != expected {expected}"
        else:
            # When total is 0, coverage is 0.0
            assert pct == 0.0


# ============================================================================
# Handler endpoint tests
# ============================================================================


class TestRBACCoverageEndpoint:
    """Tests for GET /api/v1/compliance/rbac-coverage via ComplianceHandler."""

    @pytest.mark.asyncio
    async def test_returns_200(self, compliance_handler, mock_handler_get):
        """RBAC coverage endpoint returns HTTP 200."""
        result = await compliance_handler.handle(
            path="/api/v1/compliance/rbac-coverage",
            query_params={},
            handler=mock_handler_get,
        )
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_data_envelope(self, compliance_handler, mock_handler_get):
        """Response is wrapped in a {'data': ...} envelope."""
        result = await compliance_handler.handle(
            path="/api/v1/compliance/rbac-coverage",
            query_params={},
            handler=mock_handler_get,
        )
        body = json.loads(result.body)
        assert "data" in body, f"Expected 'data' key in response, got: {list(body.keys())}"

    @pytest.mark.asyncio
    async def test_response_data_has_required_fields(self, compliance_handler, mock_handler_get):
        """Response data contains covered_endpoints, total_endpoints, coverage_pct."""
        result = await compliance_handler.handle(
            path="/api/v1/compliance/rbac-coverage",
            query_params={},
            handler=mock_handler_get,
        )
        body = json.loads(result.body)
        data = body["data"]
        assert "covered_endpoints" in data, f"Missing covered_endpoints. Keys: {list(data.keys())}"
        assert "total_endpoints" in data, f"Missing total_endpoints. Keys: {list(data.keys())}"
        assert "coverage_pct" in data, f"Missing coverage_pct. Keys: {list(data.keys())}"

    @pytest.mark.asyncio
    async def test_coverage_pct_is_float(self, compliance_handler, mock_handler_get):
        """coverage_pct is a numeric value."""
        result = await compliance_handler.handle(
            path="/api/v1/compliance/rbac-coverage",
            query_params={},
            handler=mock_handler_get,
        )
        body = json.loads(result.body)
        data = body["data"]
        assert isinstance(data["coverage_pct"], (int, float))

    @pytest.mark.asyncio
    async def test_coverage_pct_in_range(self, compliance_handler, mock_handler_get):
        """coverage_pct is between 0 and 100."""
        result = await compliance_handler.handle(
            path="/api/v1/compliance/rbac-coverage",
            query_params={},
            handler=mock_handler_get,
        )
        body = json.loads(result.body)
        pct = body["data"]["coverage_pct"]
        assert 0 <= pct <= 100

    @pytest.mark.asyncio
    async def test_fallback_when_compute_fails(self, compliance_handler, mock_handler_get):
        """Endpoint returns safe fallback data when coverage scan raises an exception."""
        with patch(
            "aragora.rbac.audit.compute_endpoint_coverage",
            side_effect=RuntimeError("scan failed"),
        ):
            result = await compliance_handler.handle(
                path="/api/v1/compliance/rbac-coverage",
                query_params={},
                handler=mock_handler_get,
            )
        # Should still return 200 with a data envelope containing zero-value fallback
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "data" in body
        data = body["data"]
        assert "covered_endpoints" in data
        assert "total_endpoints" in data
        assert "coverage_pct" in data
        assert data["covered_endpoints"] == 0
        assert data["total_endpoints"] == 0
        assert data["coverage_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_can_handle_v1_path(self, compliance_handler):
        """can_handle accepts GET /api/v1/compliance/rbac-coverage."""
        assert compliance_handler.can_handle("/api/v1/compliance/rbac-coverage", "GET")

    @pytest.mark.asyncio
    async def test_handler_result_is_handler_result_type(
        self, compliance_handler, mock_handler_get
    ):
        """handle() returns a HandlerResult."""
        result = await compliance_handler.handle(
            path="/api/v1/compliance/rbac-coverage",
            query_params={},
            handler=mock_handler_get,
        )
        assert isinstance(result, HandlerResult)
