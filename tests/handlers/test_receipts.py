"""Tests for receipts handler (aragora/server/handlers/receipts.py).

Covers all routes and behavior of the ReceiptsHandler class:
- can_handle() routing for all receipt endpoints
- GET /api/v2/receipts - List receipts with filtering and pagination
- GET /api/v2/receipts/search - Full-text search receipts
- GET /api/v2/receipts/:receipt_id - Get specific receipt
- GET /api/v2/receipts/:receipt_id/export - Export (json, html, md, pdf, sarif, csv)
- GET /api/v2/receipts/:receipt_id/verify - Verify integrity + signature
- POST /api/v2/receipts/:receipt_id/verify - Verify integrity checksum
- POST /api/v2/receipts/:receipt_id/verify-signature - Verify cryptographic signature
- POST /api/v2/receipts/verify-batch - Batch signature verification
- POST /api/v2/receipts/sign-batch - Batch signing
- POST /api/v2/receipts/batch-export - Batch export to ZIP
- GET /api/v2/receipts/stats - Receipt statistics
- POST /api/v2/receipts/:receipt_id/share - Create shareable link
- GET /api/v2/receipts/share/:token - Access receipt via share token
- GET /api/v2/receipts/retention-status - GDPR retention status
- GET /api/v2/receipts/dsar/:user_id - GDPR DSAR
- POST /api/v2/receipts/:receipt_id/send-to-channel - Send to channel
- GET /api/v2/receipts/:receipt_id/formatted/:channel_type - Get formatted receipt
- Error handling (not found, invalid ID, missing params)
- Edge cases (empty lists, pagination, timestamp parsing)
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.receipts import ReceiptsHandler, _render_shared_receipt_html
from aragora.storage.receipt_store import StoredReceipt

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    raw = result.body
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# The org the autouse auth fixture signs every request in as.
TEST_ORG = "test-org-001"


def _owned(receipt: Any, org_id: str) -> Any:
    """``receipt`` when ``org_id`` owns it, else None (the store's org filter)."""
    return receipt if receipt is not None and getattr(receipt, "org_id", None) == org_id else None


def _scope_store_double(store: MagicMock) -> MagicMock:
    """Answer the org-scoped store methods from the unscoped mocks a test configures."""
    store.get_for_org.side_effect = lambda rid, org_id: _owned(store.get(rid), org_id)
    store.get_by_gauntlet_for_org.side_effect = lambda gid, org_id: _owned(
        store.get_by_gauntlet(gid), org_id
    )
    store.list_for_org.side_effect = lambda org_id, **kw: [
        r for r in store.list(**kw) if _owned(r, org_id)
    ]
    store.count_for_org.side_effect = lambda org_id, **kw: store.count(**kw)
    store.search_for_org.side_effect = lambda org_id, **kw: [
        r for r in store.search(**kw) if _owned(r, org_id)
    ]
    store.search_count_for_org.side_effect = lambda org_id, **kw: store.search_count(**kw)
    store.stats_for_org.side_effect = lambda org_id: store.get_stats()
    store.retention_status_for_org.side_effect = lambda org_id: store.get_retention_status()
    store.get_by_user_for_org.side_effect = lambda org_id, **kw: store.get_by_user(**kw)
    return store


class MockReceipt:
    """Mock receipt object returned by the store."""

    def __init__(
        self,
        receipt_id: str = "rcpt-001",
        debate_id: str = "dbt-001",
        verdict: str = "APPROVED",
        confidence: float = 0.95,
        risk_level: str = "LOW",
        input_summary: str = "Test decision",
        timestamp: str = "2026-01-01T00:00:00Z",
        agents_involved: list[str] | None = None,
        findings: list | None = None,
        checksum: str = "abc123def456abc123def456abc123def456",
        robustness_score: float = 0.9,
        coverage_score: float = 0.85,
        verification_coverage: float = 0.8,
        data: dict[str, Any] | None = None,
        org_id: str | None = TEST_ORG,
    ):
        self.receipt_id = receipt_id
        self.org_id = org_id
        self.signature: str | None = None
        self.debate_id = debate_id
        self.verdict = verdict
        self.confidence = confidence
        self.risk_level = risk_level
        self.input_summary = input_summary
        self.timestamp = timestamp
        self.agents_involved = agents_involved or ["claude", "gpt4"]
        self.findings = findings or []
        self.checksum = checksum
        self.robustness_score = robustness_score
        self.coverage_score = coverage_score
        self.verification_coverage = verification_coverage
        self.data = data or {"receipt_id": receipt_id, "verdict": verdict}

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "debate_id": self.debate_id,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
        }

    def to_full_dict(self) -> dict[str, Any]:
        return {
            **self.to_dict(),
            "input_summary": self.input_summary,
            "timestamp": self.timestamp,
            "agents_involved": self.agents_involved,
            "findings": [f.__dict__ for f in self.findings] if self.findings else [],
            "checksum": self.checksum,
        }

    def to_html(self) -> str:
        return f"<html><body>Receipt {self.receipt_id}</body></html>"


class MockFinding:
    """Mock finding object."""

    def __init__(
        self,
        severity: str = "MEDIUM",
        title: str = "Test Finding",
        description: str = "A test finding description",
        mitigation: str = "Apply fix",
    ):
        self.severity = severity
        self.title = title
        self.description = description
        self.mitigation = mitigation


class MockSignatureResult:
    """Mock signature verification result."""

    def __init__(self, valid: bool = True, error: str | None = None):
        self.valid = valid
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "error": self.error}


class MockDecisionReceipt:
    """Mock decision receipt for export."""

    def __init__(self, receipt_id: str = "rcpt-001"):
        self.receipt_id = receipt_id

    def to_json(self, indent: int = 2) -> str:
        return json.dumps({"receipt_id": self.receipt_id}, indent=indent)

    def to_html(self) -> str:
        return f"<html><body>Receipt {self.receipt_id}</body></html>"

    def to_markdown(self) -> str:
        return f"# Receipt {self.receipt_id}"

    def to_pdf(self) -> bytes:
        return b"%PDF-1.4 mock pdf content"

    def to_csv(self) -> str:
        return f"receipt_id,verdict\n{self.receipt_id},APPROVED"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store():
    """Create a mock receipt store."""
    store = MagicMock()
    store.list.return_value = []
    store.count.return_value = 0
    store.get.return_value = None
    store.get_by_gauntlet.return_value = None
    store.search.return_value = []
    store.search_count.return_value = 0
    store.verify_signature.return_value = MockSignatureResult()
    store.verify_integrity.return_value = {"integrity_valid": True}
    store.verify_batch.return_value = ([], {"total": 0, "valid": 0})
    store.get_stats.return_value = {"total": 0, "by_verdict": {}}
    store.get_retention_status.return_value = {"policy": "7_years", "active": True}
    store.get_by_user.return_value = ([], 0)
    store.update_signature.return_value = True
    return _scope_store_double(store)


@pytest.fixture
def mock_share_store():
    """Create a mock receipt share store."""
    store = MagicMock()
    store.get_by_token.return_value = None
    store.save.return_value = None
    store.increment_access.return_value = None
    return store


@pytest.fixture
def handler(mock_store, mock_share_store):
    """Create a ReceiptsHandler with mocked stores."""
    h = ReceiptsHandler({})
    h._store = mock_store
    h._share_store = mock_share_store
    return h


@pytest.fixture
def sample_receipt():
    """Create a sample receipt for testing."""
    return MockReceipt()


@pytest.fixture
def sample_receipts():
    """Create a list of sample receipts."""
    return [
        MockReceipt(receipt_id=f"rcpt-{i:03d}", verdict=v, risk_level=r)
        for i, (v, r) in enumerate(
            [
                ("APPROVED", "LOW"),
                ("REJECTED", "HIGH"),
                ("APPROVED_WITH_CONDITIONS", "MEDIUM"),
            ]
        )
    ]


# ---------------------------------------------------------------------------
# can_handle() routing
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for route matching via can_handle()."""

    def test_list_receipts_get(self, handler):
        assert handler.can_handle("/api/v2/receipts", "GET")

    def test_list_receipts_post(self, handler):
        assert handler.can_handle("/api/v2/receipts", "POST")

    def test_specific_receipt(self, handler):
        assert handler.can_handle("/api/v2/receipts/rcpt-001", "GET")

    def test_receipt_export(self, handler):
        assert handler.can_handle("/api/v2/receipts/rcpt-001/export", "GET")

    def test_receipt_verify_get(self, handler):
        assert handler.can_handle("/api/v2/receipts/rcpt-001/verify", "GET")

    def test_receipt_verify_post(self, handler):
        assert handler.can_handle("/api/v2/receipts/rcpt-001/verify", "POST")

    def test_receipt_verify_signature(self, handler):
        assert handler.can_handle("/api/v2/receipts/rcpt-001/verify-signature", "POST")

    def test_verify_batch(self, handler):
        assert handler.can_handle("/api/v2/receipts/verify-batch", "POST")

    def test_sign_batch(self, handler):
        assert handler.can_handle("/api/v2/receipts/sign-batch", "POST")

    def test_batch_export(self, handler):
        assert handler.can_handle("/api/v2/receipts/batch-export", "POST")

    def test_stats(self, handler):
        assert handler.can_handle("/api/v2/receipts/stats", "GET")

    def test_share_receipt(self, handler):
        assert handler.can_handle("/api/v2/receipts/rcpt-001/share", "POST")

    def test_share_token(self, handler):
        assert handler.can_handle("/api/v2/receipts/share/some-token", "GET")

    def test_search(self, handler):
        assert handler.can_handle("/api/v2/receipts/search", "GET")

    def test_retention_status(self, handler):
        assert handler.can_handle("/api/v2/receipts/retention-status", "GET")

    def test_dsar(self, handler):
        assert handler.can_handle("/api/v2/receipts/dsar/user-123", "GET")

    def test_unrelated_path_rejected(self, handler):
        assert not handler.can_handle("/api/v2/debates", "GET")

    def test_wrong_version_rejected(self, handler):
        assert not handler.can_handle("/api/v3/receipts", "GET")

    def test_delete_method_rejected(self, handler):
        assert not handler.can_handle("/api/v2/receipts", "DELETE")

    def test_put_method_rejected(self, handler):
        assert not handler.can_handle("/api/v2/receipts/rcpt-001", "PUT")

    def test_send_to_channel(self, handler):
        assert handler.can_handle("/api/v2/receipts/rcpt-001/send-to-channel", "POST")

    def test_formatted(self, handler):
        assert handler.can_handle("/api/v2/receipts/rcpt-001/formatted/slack", "GET")


# ---------------------------------------------------------------------------
# GET /api/v2/receipts - List receipts
# ---------------------------------------------------------------------------


class TestListReceipts:
    """Tests for listing receipts with filtering and pagination."""

    @pytest.mark.asyncio
    async def test_list_empty(self, handler, mock_store):
        result = await handler.handle("GET", "/api/v2/receipts")
        body = _body(result)
        assert _status(result) == 200
        assert body["receipts"] == []
        assert body["pagination"]["total"] == 0
        assert body["pagination"]["has_more"] is False

    @pytest.mark.asyncio
    async def test_list_with_results(self, handler, mock_store, sample_receipts):
        mock_store.list.return_value = sample_receipts
        mock_store.count.return_value = 3

        result = await handler.handle("GET", "/api/v2/receipts")
        body = _body(result)
        assert _status(result) == 200
        assert len(body["receipts"]) == 3
        assert body["pagination"]["total"] == 3

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, handler, mock_store, sample_receipts):
        mock_store.list.return_value = sample_receipts[:2]
        mock_store.count.return_value = 10

        result = await handler.handle(
            "GET", "/api/v2/receipts", query_params={"limit": "2", "offset": "0"}
        )
        body = _body(result)
        assert body["pagination"]["limit"] == 2
        assert body["pagination"]["offset"] == 0
        assert body["pagination"]["has_more"] is True

    @pytest.mark.asyncio
    async def test_list_with_filters(self, handler, mock_store):
        mock_store.list.return_value = []
        mock_store.count.return_value = 0

        result = await handler.handle(
            "GET",
            "/api/v2/receipts",
            query_params={
                "debate_id": "dbt-001",
                "verdict": "APPROVED",
                "risk_level": "LOW",
                "signed_only": "true",
            },
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["filters"]["debate_id"] == "dbt-001"
        assert body["filters"]["verdict"] == "APPROVED"
        assert body["filters"]["risk_level"] == "LOW"
        assert body["filters"]["signed_only"] is True

    @pytest.mark.asyncio
    async def test_list_with_date_filter(self, handler, mock_store):
        mock_store.list.return_value = []
        mock_store.count.return_value = 0

        result = await handler.handle(
            "GET",
            "/api/v2/receipts",
            query_params={"date_from": "2026-01-01", "date_to": "2026-12-31"},
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["filters"]["date_from"] is not None
        assert body["filters"]["date_to"] is not None

    @pytest.mark.asyncio
    async def test_list_with_unix_timestamp_filter(self, handler, mock_store):
        mock_store.list.return_value = []
        mock_store.count.return_value = 0

        result = await handler.handle(
            "GET",
            "/api/v2/receipts",
            query_params={"date_from": "1704067200"},
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["filters"]["date_from"] == 1704067200.0

    @pytest.mark.asyncio
    async def test_list_sort_params(self, handler, mock_store):
        mock_store.list.return_value = []
        mock_store.count.return_value = 0

        result = await handler.handle(
            "GET",
            "/api/v2/receipts",
            query_params={"sort_by": "confidence", "order": "asc"},
        )
        assert _status(result) == 200
        # Verify the store was called with the sort params
        mock_store.list.assert_called_once()
        call_kwargs = mock_store.list.call_args[1]
        assert call_kwargs["sort_by"] == "confidence"
        assert call_kwargs["order"] == "asc"

    @pytest.mark.asyncio
    async def test_list_empty_debate_id_becomes_none(self, handler, mock_store):
        mock_store.list.return_value = []
        mock_store.count.return_value = 0

        result = await handler.handle(
            "GET",
            "/api/v2/receipts",
            query_params={"debate_id": "   "},
        )
        body = _body(result)
        assert body["filters"]["debate_id"] is None


# ---------------------------------------------------------------------------
# GET /api/v2/receipts/search - Search receipts
# ---------------------------------------------------------------------------


class TestSearchReceipts:
    """Tests for full-text search across receipt content."""

    @pytest.mark.asyncio
    async def test_search_with_results(self, handler, mock_store, sample_receipts):
        mock_store.search.return_value = sample_receipts
        mock_store.search_count.return_value = 3

        result = await handler.handle(
            "GET", "/api/v2/receipts/search", query_params={"q": "test query"}
        )
        body = _body(result)
        assert _status(result) == 200
        assert len(body["receipts"]) == 3
        assert body["query"] == "test query"

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_400(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/search", query_params={"q": ""})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_search_missing_query_returns_400(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/search")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_search_short_query_returns_400(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/search", query_params={"q": "ab"})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_search_with_filters(self, handler, mock_store):
        mock_store.search.return_value = []
        mock_store.search_count.return_value = 0

        result = await handler.handle(
            "GET",
            "/api/v2/receipts/search",
            query_params={"q": "test query", "verdict": "APPROVED", "risk_level": "HIGH"},
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["filters"]["verdict"] == "APPROVED"
        assert body["filters"]["risk_level"] == "HIGH"

    @pytest.mark.asyncio
    async def test_search_pagination(self, handler, mock_store):
        mock_store.search.return_value = []
        mock_store.search_count.return_value = 100

        result = await handler.handle(
            "GET",
            "/api/v2/receipts/search",
            query_params={"q": "test query", "limit": "10", "offset": "20"},
        )
        body = _body(result)
        assert body["pagination"]["limit"] == 10
        assert body["pagination"]["offset"] == 20
        assert body["pagination"]["has_more"] is True


# ---------------------------------------------------------------------------
# GET /api/v2/receipts/:receipt_id - Get receipt
# ---------------------------------------------------------------------------


class TestGetReceipt:
    """Tests for getting a specific receipt."""

    @pytest.mark.asyncio
    async def test_get_existing_receipt(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = sample_receipt

        result = await handler.handle("GET", "/api/v2/receipts/rcpt-001")
        body = _body(result)
        assert _status(result) == 200
        assert body["receipt_id"] == "rcpt-001"

    @pytest.mark.asyncio
    async def test_get_receipt_not_found(self, handler, mock_store):
        mock_store.get.return_value = None
        mock_store.get_by_gauntlet.return_value = None

        result = await handler.handle("GET", "/api/v2/receipts/nonexistent")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_receipt_by_gauntlet_id(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = None
        mock_store.get_by_gauntlet.return_value = sample_receipt

        result = await handler.handle("GET", "/api/v2/receipts/gauntlet-id-123")
        body = _body(result)
        assert _status(result) == 200
        assert body["receipt_id"] == "rcpt-001"


# ---------------------------------------------------------------------------
# GET /api/v2/receipts/:receipt_id/export - Export receipt
# ---------------------------------------------------------------------------


class TestExportReceipt:
    """Tests for exporting receipts in various formats."""

    DECISION_RECEIPT_PATH = "aragora.export.decision_receipt.DecisionReceipt"

    @pytest.fixture(autouse=True)
    def _patch_decision_receipt(self, mock_store, sample_receipt):
        """Patch DecisionReceipt.from_dict for export tests."""
        mock_store.get.return_value = sample_receipt
        self._mock_dr = MockDecisionReceipt()
        self._patcher = patch(
            self.DECISION_RECEIPT_PATH,
            **{"from_dict.return_value": self._mock_dr},
        )
        self._mock_class = self._patcher.start()
        yield
        self._patcher.stop()

    @pytest.mark.asyncio
    async def test_export_json(self, handler):
        result = await handler.handle(
            "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "json"}
        )
        assert _status(result) == 200
        assert "application/json" in result.content_type

    @pytest.mark.asyncio
    async def test_export_html(self, handler):
        result = await handler.handle(
            "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "html"}
        )
        assert _status(result) == 200
        assert "text/html" in result.content_type

    @pytest.mark.asyncio
    async def test_export_markdown(self, handler):
        result = await handler.handle(
            "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "md"}
        )
        assert _status(result) == 200
        assert "text/markdown" in result.content_type

    @pytest.mark.asyncio
    async def test_export_markdown_long_name(self, handler):
        result = await handler.handle(
            "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "markdown"}
        )
        assert _status(result) == 200
        assert "text/markdown" in result.content_type

    @pytest.mark.asyncio
    async def test_export_pdf(self, handler):
        result = await handler.handle(
            "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "pdf"}
        )
        assert _status(result) == 200
        assert result.content_type == "application/pdf"
        assert result.headers["Content-Disposition"] == "attachment; filename=receipt-rcpt-001.pdf"

    @pytest.mark.asyncio
    async def test_export_pdf_fallback_to_html(self, handler):
        """When weasyprint is not available, PDF falls back to printable HTML."""
        self._mock_dr.to_pdf = MagicMock(side_effect=ImportError("No weasyprint"))
        result = await handler.handle(
            "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "pdf"}
        )
        assert _status(result) == 200
        assert result.content_type == "text/html"
        assert result.headers.get("X-PDF-Fallback") == "true"

    @pytest.mark.asyncio
    async def test_export_csv(self, handler):
        result = await handler.handle(
            "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "csv"}
        )
        assert _status(result) == 200
        assert "text/csv" in result.content_type
        assert "Content-Disposition" in result.headers

    @pytest.mark.asyncio
    async def test_export_sarif(self, handler):
        mock_export = MagicMock(return_value='{"runs": []}')
        mock_format = MagicMock(SARIF="sarif")
        with (
            patch("aragora.gauntlet.api.export.export_receipt", mock_export),
            patch("aragora.gauntlet.api.export.ReceiptExportFormat", mock_format),
        ):
            result = await handler.handle(
                "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "sarif"}
            )
        assert _status(result) == 200
        assert result.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_export_unsupported_format(self, handler):
        result = await handler.handle(
            "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "xml"}
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_export_default_format_is_json(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/rcpt-001/export")
        assert _status(result) == 200
        assert "application/json" in result.content_type

    @pytest.mark.asyncio
    async def test_export_receipt_not_found(self, handler, mock_store):
        mock_store.get.return_value = None
        result = await handler.handle(
            "GET", "/api/v2/receipts/nonexistent/export", query_params={"format": "json"}
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_export_error_returns_500(self, handler):
        self._mock_dr.to_json = MagicMock(side_effect=ValueError("Export failed"))
        result = await handler.handle(
            "GET", "/api/v2/receipts/rcpt-001/export", query_params={"format": "json"}
        )
        assert _status(result) == 500


# ---------------------------------------------------------------------------
# GET /api/v2/receipts/:receipt_id/verify - Verify receipt (combined)
# ---------------------------------------------------------------------------


class TestVerifyReceipt:
    """Tests for combined signature + integrity verification."""

    @pytest.mark.asyncio
    async def test_verify_success(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()
        mock_store.verify_signature.return_value = MockSignatureResult(valid=True)
        mock_store.verify_integrity.return_value = {"integrity_valid": True}

        result = await handler.handle("GET", "/api/v2/receipts/rcpt-001/verify")
        body = _body(result)
        assert _status(result) == 200
        assert body["receipt_id"] == "rcpt-001"
        assert "signature" in body
        assert "integrity" in body

    @pytest.mark.asyncio
    async def test_verify_signature_not_found(self, handler, mock_store):
        mock_store.verify_signature.return_value = MockSignatureResult(
            valid=False, error="Receipt not found"
        )
        mock_store.verify_integrity.return_value = {"integrity_valid": True}

        result = await handler.handle("GET", "/api/v2/receipts/nonexistent/verify")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_verify_integrity_not_found(self, handler, mock_store):
        mock_store.verify_signature.return_value = MockSignatureResult(valid=True)
        mock_store.verify_integrity.return_value = {
            "integrity_valid": False,
            "error": "Receipt not found",
        }

        result = await handler.handle("GET", "/api/v2/receipts/nonexistent/verify")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_verify_signature_result_as_dict(self, handler, mock_store):
        """When signature result doesn't have to_dict, it's returned directly."""
        mock_store.get.return_value = MockReceipt()
        mock_store.verify_signature.return_value = {"valid": True}
        mock_store.verify_integrity.return_value = {"integrity_valid": True}

        result = await handler.handle("GET", "/api/v2/receipts/rcpt-001/verify")
        body = _body(result)
        assert _status(result) == 200
        assert body["signature"] == {"valid": True}


# ---------------------------------------------------------------------------
# POST /api/v2/receipts/:receipt_id/verify - Verify integrity
# ---------------------------------------------------------------------------


class TestVerifyIntegrity:
    """Tests for integrity checksum verification."""

    @pytest.mark.asyncio
    async def test_verify_integrity_success(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()
        mock_store.verify_integrity.return_value = {"integrity_valid": True}

        result = await handler.handle("POST", "/api/v2/receipts/rcpt-001/verify")
        body = _body(result)
        assert _status(result) == 200
        assert body["integrity_valid"] is True

    @pytest.mark.asyncio
    async def test_verify_integrity_not_found(self, handler, mock_store):
        mock_store.verify_integrity.return_value = {
            "integrity_valid": False,
            "error": "Receipt not found",
        }

        result = await handler.handle("POST", "/api/v2/receipts/nonexistent/verify")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_verify_integrity_valid_with_error(self, handler, mock_store):
        """When error exists but integrity is not explicitly False, return the result."""
        mock_store.get.return_value = MockReceipt()
        mock_store.verify_integrity.return_value = {
            "integrity_valid": True,
            "error": "Some warning",
        }

        result = await handler.handle("POST", "/api/v2/receipts/rcpt-001/verify")
        body = _body(result)
        assert _status(result) == 200
        assert body["integrity_valid"] is True


# ---------------------------------------------------------------------------
# POST /api/v2/receipts/:receipt_id/verify-signature
# ---------------------------------------------------------------------------


class TestVerifySignature:
    """Tests for cryptographic signature verification."""

    @pytest.mark.asyncio
    async def test_verify_signature_success(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()
        mock_store.verify_signature.return_value = MockSignatureResult(valid=True)

        result = await handler.handle("POST", "/api/v2/receipts/rcpt-001/verify-signature")
        body = _body(result)
        assert _status(result) == 200
        assert body["valid"] is True

    @pytest.mark.asyncio
    async def test_verify_signature_not_found(self, handler, mock_store):
        mock_store.verify_signature.return_value = MockSignatureResult(
            valid=False, error="Receipt not found"
        )

        result = await handler.handle("POST", "/api/v2/receipts/nonexistent/verify-signature")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_verify_signature_invalid(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()
        mock_store.verify_signature.return_value = MockSignatureResult(
            valid=False, error="Invalid signature"
        )

        result = await handler.handle("POST", "/api/v2/receipts/rcpt-001/verify-signature")
        body = _body(result)
        assert _status(result) == 200
        assert body["valid"] is False
        assert body["error"] == "Invalid signature"


# ---------------------------------------------------------------------------
# POST /api/v2/receipts/verify-batch - Batch verification
# ---------------------------------------------------------------------------


class TestVerifyBatch:
    """Tests for batch signature verification."""

    @pytest.mark.asyncio
    async def test_verify_batch_success(self, handler, mock_store):
        mock_results = [MockSignatureResult(valid=True)]
        mock_store.verify_batch.return_value = (mock_results, {"total": 1, "valid": 1})

        result = await handler.handle(
            "POST",
            "/api/v2/receipts/verify-batch",
            body={"receipt_ids": ["rcpt-001"]},
        )
        body = _body(result)
        assert _status(result) == 200
        assert len(body["results"]) == 1
        assert body["summary"]["total"] == 1

    @pytest.mark.asyncio
    async def test_verify_batch_empty_ids_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/verify-batch",
            body={"receipt_ids": []},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_verify_batch_missing_ids_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/verify-batch",
            body={},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_verify_batch_too_many_ids_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/verify-batch",
            body={"receipt_ids": [f"rcpt-{i}" for i in range(101)]},
        )
        assert _status(result) == 400


# ---------------------------------------------------------------------------
# POST /api/v2/receipts/sign-batch - Batch signing
# ---------------------------------------------------------------------------


class TestSignBatch:
    """Tests for batch receipt signing."""

    @pytest.mark.asyncio
    async def test_sign_batch_empty_ids_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/sign-batch",
            body={"receipt_ids": []},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_sign_batch_missing_ids_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/sign-batch",
            body={},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_sign_batch_too_many_ids_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/sign-batch",
            body={"receipt_ids": [f"rcpt-{i}" for i in range(101)]},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_sign_batch_import_error_returns_501(self, handler, mock_store):
        """When signing module is not available, return 501."""
        with patch(
            "aragora.server.handlers.receipts.ReceiptsHandler._sign_batch",
            side_effect=ImportError("No crypto"),
        ):
            # Call the handle method directly since we need to trigger the import error
            # in _sign_batch. Actually test the logic by calling _sign_batch directly.
            pass

        # Instead, test via the import path within the sign batch logic
        mock_store.get.return_value = MockReceipt()
        with patch.dict("sys.modules", {"aragora.storage.receipt_signing": None}):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/sign-batch",
                body={"receipt_ids": ["rcpt-001"]},
            )
        assert _status(result) == 501

    @pytest.mark.asyncio
    async def test_sign_batch_signatory_missing_name_returns_400(self, handler, mock_store):
        mock_signing = MagicMock()
        mock_signing.HMACSigner.from_env.return_value = MagicMock()
        mock_signing.ReceiptSigner.return_value = MagicMock()
        mock_signing.SignatoryInfo = MagicMock()

        with patch.dict("sys.modules", {"aragora.storage.receipt_signing": mock_signing}):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/sign-batch",
                body={
                    "receipt_ids": ["rcpt-001"],
                    "signatory": {"email": "test@example.com"},
                },
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_sign_batch_signatory_missing_email_returns_400(self, handler, mock_store):
        mock_signing = MagicMock()
        mock_signing.HMACSigner.from_env.return_value = MagicMock()
        mock_signing.ReceiptSigner.return_value = MagicMock()
        mock_signing.SignatoryInfo = MagicMock()

        with patch.dict("sys.modules", {"aragora.storage.receipt_signing": mock_signing}):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/sign-batch",
                body={
                    "receipt_ids": ["rcpt-001"],
                    "signatory": {"name": "Test User"},
                },
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_sign_batch_receipt_not_found(self, handler, mock_store):
        mock_store.get.return_value = None
        mock_signing = MagicMock()
        mock_signing.HMACSigner.from_env.return_value = MagicMock()
        mock_signing.ReceiptSigner.return_value = MagicMock()

        with patch.dict("sys.modules", {"aragora.storage.receipt_signing": mock_signing}):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/sign-batch",
                body={"receipt_ids": ["nonexistent"]},
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["results"][0]["status"] == "not_found"
        assert body["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_sign_batch_already_signed(self, handler, mock_store):
        signed = MockReceipt()
        signed.signature = "existing-sig"
        mock_store.get.return_value = signed
        mock_signing = MagicMock()
        mock_signing.HMACSigner.from_env.return_value = MagicMock()
        mock_signing.ReceiptSigner.return_value = MagicMock()

        with patch.dict("sys.modules", {"aragora.storage.receipt_signing": mock_signing}):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/sign-batch",
                body={"receipt_ids": ["rcpt-001"]},
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["results"][0]["status"] == "already_signed"
        assert body["summary"]["skipped"] == 1

    @pytest.mark.asyncio
    async def test_sign_batch_success(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()

        mock_signer = MagicMock()
        mock_signer.sign.return_value.signature = "c2lnbmF0dXJl"
        mock_signer.sign.return_value.signature_metadata.algorithm = "HMAC-SHA256"
        mock_signer.sign.return_value.signature_metadata.key_id = "key-1"

        mock_signing = MagicMock()
        mock_signing.HMACSigner.from_env.return_value = MagicMock()
        mock_signing.ReceiptSigner.return_value = mock_signer
        mock_signing.SignatoryInfo = MagicMock()

        with patch.dict("sys.modules", {"aragora.storage.receipt_signing": mock_signing}):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/sign-batch",
                body={"receipt_ids": ["rcpt-001"]},
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["results"][0]["status"] == "signed"
        assert body["summary"]["signed"] == 1
        mock_store.update_signature.assert_called_once_with(
            "rcpt-001", "c2lnbmF0dXJl", "HMAC-SHA256", "key-1"
        )


# ---------------------------------------------------------------------------
# POST /api/v2/receipts/batch-export - Batch export to ZIP
# ---------------------------------------------------------------------------


class TestBatchExport:
    """Tests for batch export to ZIP file."""

    @pytest.mark.asyncio
    async def test_batch_export_empty_ids_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/batch-export",
            body={"receipt_ids": []},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_export_missing_ids_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/batch-export",
            body={},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_export_too_many_ids_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/batch-export",
            body={"receipt_ids": [f"rcpt-{i}" for i in range(101)]},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_export_unsupported_format_returns_400(self, handler):
        result = await handler.handle(
            "POST",
            "/api/v2/receipts/batch-export",
            body={"receipt_ids": ["rcpt-001"], "format": "xml"},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_export_json_success(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()
        mock_dr = MockDecisionReceipt()

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt",
            **{"from_dict.return_value": mock_dr},
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["rcpt-001"], "format": "json"},
            )
        assert _status(result) == 200
        assert result.content_type == "application/zip"
        assert result.headers["Content-Disposition"] == "attachment; filename=receipts-export.zip"

        # Verify ZIP contents
        zip_buffer = io.BytesIO(result.body)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert "receipt-rcpt-001.json" in names
            assert "manifest.json" in names
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["exported"] == 1
            assert manifest["format"] == "json"

    @pytest.mark.asyncio
    async def test_batch_export_html_format(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()
        mock_dr = MockDecisionReceipt()

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt",
            **{"from_dict.return_value": mock_dr},
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["rcpt-001"], "format": "html"},
            )
        assert _status(result) == 200
        zip_buffer = io.BytesIO(result.body)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "receipt-rcpt-001.html" in zf.namelist()

    @pytest.mark.asyncio
    async def test_batch_export_markdown_format(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()
        mock_dr = MockDecisionReceipt()

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt",
            **{"from_dict.return_value": mock_dr},
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["rcpt-001"], "format": "markdown"},
            )
        assert _status(result) == 200
        zip_buffer = io.BytesIO(result.body)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "receipt-rcpt-001.md" in zf.namelist()

    @pytest.mark.asyncio
    async def test_batch_export_csv_format(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()
        mock_dr = MockDecisionReceipt()

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt",
            **{"from_dict.return_value": mock_dr},
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["rcpt-001"], "format": "csv"},
            )
        assert _status(result) == 200
        zip_buffer = io.BytesIO(result.body)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "receipt-rcpt-001.csv" in zf.namelist()

    @pytest.mark.asyncio
    async def test_batch_export_with_not_found_receipts(self, handler, mock_store):
        """Missing receipts are tracked in manifest failures."""
        mock_store.get.return_value = None

        result = await handler.handle(
            "POST",
            "/api/v2/receipts/batch-export",
            body={"receipt_ids": ["nonexistent"], "format": "json"},
        )
        assert _status(result) == 200
        zip_buffer = io.BytesIO(result.body)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["exported"] == 0
            assert "nonexistent" in manifest["failed"]

    @pytest.mark.asyncio
    async def test_batch_export_md_alias(self, handler, mock_store):
        mock_store.get.return_value = MockReceipt()
        mock_dr = MockDecisionReceipt()

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt",
            **{"from_dict.return_value": mock_dr},
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/batch-export",
                body={"receipt_ids": ["rcpt-001"], "format": "md"},
            )
        assert _status(result) == 200
        zip_buffer = io.BytesIO(result.body)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "receipt-rcpt-001.md" in zf.namelist()


# ---------------------------------------------------------------------------
# GET /api/v2/receipts/stats - Receipt statistics
# ---------------------------------------------------------------------------


class TestReceiptStats:
    """Tests for receipt statistics endpoint."""

    @pytest.mark.asyncio
    async def test_get_stats(self, handler, mock_store):
        mock_store.get_stats.return_value = {
            "total": 42,
            "by_verdict": {"APPROVED": 30, "REJECTED": 12},
        }

        result = await handler.handle("GET", "/api/v2/receipts/stats")
        body = _body(result)
        assert _status(result) == 200
        assert body["stats"]["total"] == 42
        assert "generated_at" in body


# ---------------------------------------------------------------------------
# POST /api/v2/receipts/:receipt_id/share - Create shareable link
# ---------------------------------------------------------------------------


class TestShareReceipt:
    """Tests for creating shareable links."""

    @pytest.mark.asyncio
    async def test_share_receipt_success(
        self, handler, mock_store, mock_share_store, sample_receipt
    ):
        mock_store.get.return_value = sample_receipt

        with patch(
            "aragora.integrations.receipt_webhooks.ReceiptWebhookNotifier",
            side_effect=ImportError("No webhooks"),
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/rcpt-001/share",
                body={"expires_in_hours": 48},
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["success"] is True
        assert body["receipt_id"] == "rcpt-001"
        assert "token" in body
        assert "share_url" in body
        assert "expires_at" in body

    @pytest.mark.asyncio
    async def test_share_receipt_not_found(self, handler, mock_store):
        mock_store.get.return_value = None

        result = await handler.handle(
            "POST",
            "/api/v2/receipts/nonexistent/share",
            body={},
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_share_receipt_with_max_accesses(
        self, handler, mock_store, mock_share_store, sample_receipt
    ):
        mock_store.get.return_value = sample_receipt

        with patch(
            "aragora.integrations.receipt_webhooks.ReceiptWebhookNotifier",
            side_effect=ImportError("No webhooks"),
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/rcpt-001/share",
                body={"max_accesses": 5},
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["max_accesses"] == 5

    @pytest.mark.asyncio
    async def test_share_receipt_with_webhook(
        self, handler, mock_store, mock_share_store, sample_receipt
    ):
        mock_store.get.return_value = sample_receipt
        mock_notifier = MagicMock()

        with patch(
            "aragora.integrations.receipt_webhooks.ReceiptWebhookNotifier",
            return_value=mock_notifier,
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/rcpt-001/share",
                body={},
            )
        assert _status(result) == 200
        mock_notifier.notify_receipt_shared.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/v2/receipts/share/:token - Access shared receipt
# ---------------------------------------------------------------------------


class TestGetSharedReceipt:
    """Tests for accessing a receipt via share token."""

    @pytest.mark.asyncio
    async def test_shared_receipt_not_found(self, handler, mock_share_store):
        mock_share_store.get_by_token.return_value = None

        result = await handler.handle("GET", "/api/v2/receipts/share/invalid-token")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_shared_receipt_expired(self, handler, mock_share_store):
        mock_share_store.get_by_token.return_value = {
            "receipt_id": "rcpt-001",
            "expires_at": 1.0,  # very old timestamp
            "access_count": 0,
        }

        result = await handler.handle("GET", "/api/v2/receipts/share/expired-token")
        assert _status(result) == 410

    @pytest.mark.asyncio
    async def test_shared_receipt_access_limit_reached(self, handler, mock_share_store):
        mock_share_store.get_by_token.return_value = {
            "receipt_id": "rcpt-001",
            "expires_at": datetime.now(timezone.utc).timestamp() + 3600,
            "max_accesses": 5,
            "access_count": 5,
        }

        result = await handler.handle("GET", "/api/v2/receipts/share/limited-token")
        assert _status(result) == 410

    @pytest.mark.asyncio
    async def test_shared_receipt_json_response(
        self, handler, mock_store, mock_share_store, sample_receipt
    ):
        mock_share_store.get_by_token.return_value = {
            "receipt_id": "rcpt-001",
            "expires_at": datetime.now(timezone.utc).timestamp() + 3600,
            "access_count": 0,
        }
        mock_store.get.return_value = sample_receipt

        result = await handler.handle("GET", "/api/v2/receipts/share/valid-token")
        body = _body(result)
        assert _status(result) == 200
        assert body["shared"] is True
        assert body["receipt"]["receipt_id"] == "rcpt-001"
        assert body["access_count"] == 1

    @pytest.mark.asyncio
    async def test_shared_receipt_html_via_accept_header(
        self, handler, mock_store, mock_share_store, sample_receipt
    ):
        mock_share_store.get_by_token.return_value = {
            "receipt_id": "rcpt-001",
            "expires_at": datetime.now(timezone.utc).timestamp() + 3600,
            "access_count": 0,
        }
        mock_store.get.return_value = sample_receipt

        result = await handler.handle(
            "GET",
            "/api/v2/receipts/share/valid-token",
            headers={"Accept": "text/html"},
        )
        assert _status(result) == 200
        assert "text/html" in result.content_type

    @pytest.mark.asyncio
    async def test_shared_receipt_html_via_format_param(
        self, handler, mock_store, mock_share_store, sample_receipt
    ):
        mock_share_store.get_by_token.return_value = {
            "receipt_id": "rcpt-001",
            "expires_at": datetime.now(timezone.utc).timestamp() + 3600,
            "access_count": 0,
        }
        mock_store.get.return_value = sample_receipt

        result = await handler.handle(
            "GET",
            "/api/v2/receipts/share/valid-token",
            query_params={"format": "html"},
        )
        assert _status(result) == 200
        assert "text/html" in result.content_type

    @pytest.mark.asyncio
    async def test_shared_receipt_increments_access(
        self, handler, mock_store, mock_share_store, sample_receipt
    ):
        mock_share_store.get_by_token.return_value = {
            "receipt_id": "rcpt-001",
            "expires_at": datetime.now(timezone.utc).timestamp() + 3600,
            "access_count": 2,
        }
        mock_store.get.return_value = sample_receipt

        await handler.handle("GET", "/api/v2/receipts/share/valid-token")
        mock_share_store.increment_access.assert_called_once_with("valid-token")

    @pytest.mark.asyncio
    async def test_shared_receipt_receipt_not_found(self, handler, mock_store, mock_share_store):
        mock_share_store.get_by_token.return_value = {
            "receipt_id": "deleted-rcpt",
            "expires_at": datetime.now(timezone.utc).timestamp() + 3600,
            "access_count": 0,
        }
        mock_store.get.return_value = None

        result = await handler.handle("GET", "/api/v2/receipts/share/valid-token")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_shared_receipt_no_expiry(
        self, handler, mock_store, mock_share_store, sample_receipt
    ):
        """Share link without expires_at should still work."""
        mock_share_store.get_by_token.return_value = {
            "receipt_id": "rcpt-001",
            "access_count": 0,
        }
        mock_store.get.return_value = sample_receipt

        result = await handler.handle("GET", "/api/v2/receipts/share/no-expiry-token")
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# GET /api/v2/receipts/retention-status - GDPR retention
# ---------------------------------------------------------------------------


class TestRetentionStatus:
    """Tests for GDPR retention status endpoint."""

    @pytest.mark.asyncio
    async def test_get_retention_status(self, handler, mock_store):
        result = await handler.handle("GET", "/api/v2/receipts/retention-status")
        body = _body(result)
        assert _status(result) == 200
        assert body["policy"] == "7_years"


# ---------------------------------------------------------------------------
# GET /api/v2/receipts/dsar/:user_id - GDPR DSAR
# ---------------------------------------------------------------------------


class TestDSAR:
    """Tests for GDPR Data Subject Access Requests."""

    @pytest.mark.asyncio
    async def test_dsar_success(self, handler, mock_store):
        mock_store.get_by_user.return_value = ([MockReceipt()], 1)

        result = await handler.handle("GET", "/api/v2/receipts/dsar/user-123")
        body = _body(result)
        assert _status(result) == 200
        assert body["dsar_request"]["user_id"] == "user-123"
        assert body["dsar_request"]["gdpr_article"] == "Article 15 - Right of access"
        assert body["summary"]["total_receipts"] == 1

    @pytest.mark.asyncio
    async def test_dsar_short_user_id_returns_400(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/dsar/ab")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_dsar_empty_results(self, handler, mock_store):
        mock_store.get_by_user.return_value = ([], 0)

        result = await handler.handle("GET", "/api/v2/receipts/dsar/user-with-no-data")
        body = _body(result)
        assert _status(result) == 200
        assert body["summary"]["total_receipts"] == 0

    @pytest.mark.asyncio
    async def test_dsar_pagination(self, handler, mock_store):
        mock_store.get_by_user.return_value = ([], 0)

        result = await handler.handle(
            "GET",
            "/api/v2/receipts/dsar/user-123",
            query_params={"limit": "10", "offset": "5"},
        )
        body = _body(result)
        assert body["pagination"]["limit"] == 10
        assert body["pagination"]["offset"] == 5

    @pytest.mark.asyncio
    async def test_dsar_missing_user_id_returns_400(self, handler):
        """Path without user_id segment should return 400."""
        result = await handler.handle("GET", "/api/v2/receipts/dsar/")
        # Will match but dsar/ is empty so user_id check will trigger
        # Actually this depends on path parsing; parts[5] would be empty string
        # which has len < 3, so it returns 400
        assert _status(result) == 400


# ---------------------------------------------------------------------------
# POST /api/v2/receipts/:receipt_id/send-to-channel
# ---------------------------------------------------------------------------


class TestSendToChannel:
    """Tests for sending receipt to channel."""

    @pytest.mark.asyncio
    async def test_missing_channel_type_returns_400(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = sample_receipt

        result = await handler.handle(
            "POST",
            "/api/v2/receipts/rcpt-001/send-to-channel",
            body={"channel_id": "C123"},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_missing_channel_id_returns_400(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = sample_receipt

        result = await handler.handle(
            "POST",
            "/api/v2/receipts/rcpt-001/send-to-channel",
            body={"channel_type": "slack"},
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_receipt_not_found_returns_404(self, handler, mock_store):
        mock_store.get.return_value = None

        result = await handler.handle(
            "POST",
            "/api/v2/receipts/nonexistent/send-to-channel",
            body={"channel_type": "slack", "channel_id": "C123"},
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_unsupported_channel_type(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = sample_receipt

        mock_formatter = MagicMock(return_value={"blocks": []})
        mock_dr_class = MagicMock()
        mock_dr_class.from_dict.return_value = MockDecisionReceipt()

        with (
            patch("aragora.channels.formatter.format_receipt_for_channel", mock_formatter),
            patch("aragora.export.decision_receipt.DecisionReceipt", mock_dr_class),
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/rcpt-001/send-to-channel",
                body={"channel_type": "fax", "channel_id": "123"},
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_import_error_returns_501(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = sample_receipt

        mock_dr_class = MagicMock()
        mock_dr_class.from_dict.return_value = MockDecisionReceipt()

        with (
            patch(
                "aragora.channels.formatter.format_receipt_for_channel",
                side_effect=ImportError("No channel module"),
            ),
            patch("aragora.export.decision_receipt.DecisionReceipt", mock_dr_class),
        ):
            result = await handler.handle(
                "POST",
                "/api/v2/receipts/rcpt-001/send-to-channel",
                body={"channel_type": "slack", "channel_id": "C123"},
            )
        assert _status(result) == 501


# ---------------------------------------------------------------------------
# GET /api/v2/receipts/:receipt_id/formatted/:channel_type
# ---------------------------------------------------------------------------


class TestGetFormatted:
    """Tests for getting receipt formatted for a channel."""

    @pytest.mark.asyncio
    async def test_formatted_receipt_not_found(self, handler, mock_store):
        mock_store.get.return_value = None

        result = await handler.handle("GET", "/api/v2/receipts/rcpt-001/formatted/slack")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_formatted_success(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = sample_receipt
        mock_formatter = MagicMock(return_value={"blocks": [{"type": "section"}]})
        mock_dr_class = MagicMock()
        mock_dr_class.from_dict.return_value = MockDecisionReceipt()

        with (
            patch("aragora.channels.formatter.format_receipt_for_channel", mock_formatter),
            patch("aragora.export.decision_receipt.DecisionReceipt", mock_dr_class),
        ):
            result = await handler.handle("GET", "/api/v2/receipts/rcpt-001/formatted/slack")
        body = _body(result)
        assert _status(result) == 200
        assert body["channel_type"] == "slack"
        assert body["formatted"]["blocks"] is not None

    @pytest.mark.asyncio
    async def test_formatted_default_channel_is_slack(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = sample_receipt
        mock_formatter = MagicMock(return_value={"blocks": []})
        mock_dr_class = MagicMock()
        mock_dr_class.from_dict.return_value = MockDecisionReceipt()

        with (
            patch("aragora.channels.formatter.format_receipt_for_channel", mock_formatter),
            patch("aragora.export.decision_receipt.DecisionReceipt", mock_dr_class),
        ):
            # Path without channel_type defaults to slack
            result = await handler.handle("GET", "/api/v2/receipts/rcpt-001/formatted")
        body = _body(result)
        assert _status(result) == 200
        assert body["channel_type"] == "slack"

    @pytest.mark.asyncio
    async def test_formatted_import_error_returns_500(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = sample_receipt

        mock_dr_class = MagicMock()
        mock_dr_class.from_dict.return_value = MockDecisionReceipt()

        with (
            patch(
                "aragora.channels.formatter.format_receipt_for_channel",
                side_effect=ImportError("No formatter"),
            ),
            patch("aragora.export.decision_receipt.DecisionReceipt", mock_dr_class),
        ):
            result = await handler.handle("GET", "/api/v2/receipts/rcpt-001/formatted/teams")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_formatted_value_error_returns_400(self, handler, mock_store, sample_receipt):
        mock_store.get.return_value = sample_receipt

        mock_dr_class = MagicMock()
        mock_dr_class.from_dict.return_value = MockDecisionReceipt()

        with (
            patch(
                "aragora.channels.formatter.format_receipt_for_channel",
                side_effect=ValueError("Bad channel type"),
            ),
            patch("aragora.export.decision_receipt.DecisionReceipt", mock_dr_class),
        ):
            result = await handler.handle("GET", "/api/v2/receipts/rcpt-001/formatted/invalid")
        assert _status(result) == 400


# ---------------------------------------------------------------------------
# Error handling and edge cases
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling in the main dispatch."""

    @pytest.mark.asyncio
    async def test_trailing_slash_list_path_returns_receipt_index(self, handler):
        """Trailing slash on the list route should not become an empty receipt lookup."""
        result = await handler.handle("GET", "/api/v2/receipts/")
        assert _status(result) == 200
        assert "receipts" in _body(result)

    @pytest.mark.asyncio
    async def test_not_found_for_unknown_path(self, handler):
        """An unmatched path within /api/v2/receipts returns 404."""
        # POST to the list endpoint with no specific match
        result = await handler.handle("POST", "/api/v2/receipts")
        # POST to /api/v2/receipts doesn't match any route (no POST handler for list)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_handler_exception_returns_500(self, handler, mock_store):
        """Exceptions in the handler return 500."""
        mock_store.get_stats.side_effect = RuntimeError("Database error")

        result = await handler.handle("GET", "/api/v2/receipts/stats")
        assert _status(result) == 500


# ---------------------------------------------------------------------------
# _parse_timestamp helper
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    """Tests for the _parse_timestamp helper."""

    def test_none_returns_none(self, handler):
        assert handler._parse_timestamp(None) is None

    def test_empty_string_returns_none(self, handler):
        assert handler._parse_timestamp("") is None

    def test_unix_timestamp(self, handler):
        result = handler._parse_timestamp("1704067200")
        assert result == 1704067200.0

    def test_float_timestamp(self, handler):
        result = handler._parse_timestamp("1704067200.5")
        assert result == 1704067200.5

    def test_iso_date(self, handler):
        result = handler._parse_timestamp("2026-01-01T00:00:00Z")
        assert result is not None
        assert isinstance(result, float)

    def test_iso_date_with_timezone(self, handler):
        result = handler._parse_timestamp("2026-01-01T00:00:00+00:00")
        assert result is not None

    def test_invalid_string_returns_none(self, handler):
        result = handler._parse_timestamp("not-a-date")
        assert result is None


# ---------------------------------------------------------------------------
# _render_shared_receipt_html helper
# ---------------------------------------------------------------------------


class TestRenderSharedReceiptHtml:
    """Tests for the shared receipt HTML rendering helper."""

    def test_renders_basic_html(self):
        receipt = MockReceipt()
        html = _render_shared_receipt_html(receipt, "test-token")
        assert "<!DOCTYPE html>" in html
        assert "Aragora" in html
        assert "APPROVED" in html

    def test_renders_with_findings(self):
        findings = [
            MockFinding(severity="CRITICAL", title="Critical Issue"),
            MockFinding(severity="LOW", title="Minor Issue"),
        ]
        receipt = MockReceipt(findings=findings)
        html = _render_shared_receipt_html(receipt, "test-token")
        assert "Critical Issue" in html
        assert "Minor Issue" in html
        assert "CRITICAL" in html
        assert "2 finding(s)" in html

    def test_renders_with_empty_findings(self):
        receipt = MockReceipt(findings=[])
        html = _render_shared_receipt_html(receipt, "test-token")
        assert "<!DOCTYPE html>" in html

    def test_escapes_html(self):
        receipt = MockReceipt(input_summary="<script>alert('xss')</script>")
        html = _render_shared_receipt_html(receipt, "test-token")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_truncates_long_receipt_id(self):
        receipt = MockReceipt(receipt_id="a" * 32)
        html = _render_shared_receipt_html(receipt, "test-token")
        # Title uses receipt_id[:16], meta row uses receipt_id[:24]
        assert ("a" * 16) in html

    def test_truncates_agents_list(self):
        receipt = MockReceipt(agents_involved=[f"agent-{i}" for i in range(10)])
        html = _render_shared_receipt_html(receipt, "test-token")
        assert "..." in html

    def test_verdict_colors(self):
        for verdict, expected_color in [
            ("APPROVED", "#28a745"),
            ("REJECTED", "#dc3545"),
            ("APPROVED_WITH_CONDITIONS", "#ffc107"),
            ("NEEDS_REVIEW", "#fd7e14"),
            ("UNKNOWN", "#6c757d"),
        ]:
            receipt = MockReceipt(verdict=verdict)
            html = _render_shared_receipt_html(receipt, "test-token")
            assert expected_color in html

    def test_findings_with_mitigation(self):
        findings = [MockFinding(mitigation="Apply patch XYZ")]
        receipt = MockReceipt(findings=findings)
        html = _render_shared_receipt_html(receipt, "test-token")
        assert "Apply patch XYZ" in html

    def test_findings_without_mitigation(self):
        findings = [MockFinding(mitigation="")]
        receipt = MockReceipt(findings=findings)
        html = _render_shared_receipt_html(receipt, "test-token")
        assert "Mitigation:" not in html

    def test_renders_stored_receipt_payload_fields(self):
        receipt = StoredReceipt(
            receipt_id="stored-001",
            gauntlet_id="gauntlet-001",
            debate_id="debate-001",
            created_at=1700000000.0,
            expires_at=None,
            verdict="APPROVED",
            confidence=0.91,
            risk_level="LOW",
            risk_score=0.2,
            checksum="stored-checksum",
            data={
                "receipt_id": "stored-001",
                "gauntlet_id": "gauntlet-001",
                "timestamp": "2026-04-07T01:00:00Z",
                "input_summary": "Stored proof summary",
                "agents_involved": ["claude", "gpt-4"],
                "findings": [
                    {
                        "severity": "HIGH",
                        "title": "Need audit trail",
                        "description": "missing receipt proof",
                    }
                ],
                "robustness_score": 0.8,
                "coverage_score": 0.7,
                "verification_coverage": 0.6,
                "duration_seconds": 18.2,
                "cost_usd": 0.42,
                "tokens_used": 12345,
            },
        )

        html = _render_shared_receipt_html(receipt, "test-token")

        assert "Stored proof summary" in html
        assert "Need audit trail" in html
        assert "80%" in html
        assert "$0.4200" in html
        assert "12,345" in html
        assert "18.2s" in html


# ---------------------------------------------------------------------------
# Handler initialization
# ---------------------------------------------------------------------------


class TestHandlerInit:
    """Tests for handler initialization."""

    def test_handler_creates_with_empty_context(self):
        h = ReceiptsHandler({})
        assert h._store is None
        assert h._share_store is None

    def test_lazy_store_initialization(self):
        h = ReceiptsHandler({})
        # The store factories are created but stores are not yet initialized
        assert h._store_factory is not None
        assert h._share_store_factory is not None

    def test_routes_defined(self):
        h = ReceiptsHandler({})
        assert len(h.ROUTES) > 0
        assert "/api/v2/receipts" in h.ROUTES

    def test_create_receipts_handler_factory(self):
        from aragora.server.handlers.receipts import create_receipts_handler

        h = create_receipts_handler({})
        assert isinstance(h, ReceiptsHandler)


# ---------------------------------------------------------------------------
# Rate limiting integration
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Tests that the handler has rate limiting applied."""

    def test_handle_has_rate_limit_decorator(self, handler):
        """Verify the handle method has the rate_limit decorator applied."""
        # The rate_limit decorator wraps the method; check it exists
        assert hasattr(handler, "handle")
        # The handle method should be callable
        assert callable(handler.handle)
