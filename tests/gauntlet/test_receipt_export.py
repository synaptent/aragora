"""
Tests for receipt export (HTML and PDF formats).

Covers:
- receipt_to_html rendering
- receipt_to_pdf generation
- ReceiptExportHandler GET /api/v1/receipts/:id/export
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.gauntlet.export import receipt_to_html, receipt_to_pdf


# ============================================================================
# Mock Receipt
# ============================================================================


@dataclass
class MockProvenanceRecord:
    timestamp: str = "2026-01-15T10:00:00Z"
    event_type: str = "attack"
    agent: str | None = "claude"
    description: str = "Tested input validation"
    evidence_hash: str = "abc123"


@dataclass
class MockConsensusProof:
    reached: bool = True
    confidence: float = 0.92
    supporting_agents: list[str] = field(default_factory=lambda: ["claude", "gemini"])
    dissenting_agents: list[str] = field(default_factory=list)
    method: str = "majority"
    evidence_hash: str = "consensus_hash"


@dataclass
class MockReceipt:
    receipt_id: str = "REC-001"
    gauntlet_id: str = "G-001"
    timestamp: str = "2026-01-15T10:00:00Z"
    input_summary: str = "Test input"
    input_hash: str = "input_hash_123"
    risk_summary: dict = field(
        default_factory=lambda: {
            "critical": 1,
            "high": 2,
            "medium": 3,
            "low": 5,
        }
    )
    attacks_attempted: int = 10
    attacks_successful: int = 2
    probes_run: int = 15
    vulnerabilities_found: int = 11
    verdict: str = "CONDITIONAL"
    confidence: float = 0.85
    robustness_score: float = 0.78
    vulnerability_details: list[dict] = field(
        default_factory=lambda: [
            {
                "severity": "critical",
                "title": "SQL Injection",
                "description": "Found SQL injection in input parsing",
            },
            {"severity": "high", "title": "XSS", "description": "Cross-site scripting possible"},
        ]
    )
    verdict_reasoning: str = "Some vulnerabilities detected but mitigations available"
    dissenting_views: list[str] = field(default_factory=lambda: ["Agent X disagrees"])
    consensus_proof: MockConsensusProof | None = field(default_factory=MockConsensusProof)
    provenance_chain: list[MockProvenanceRecord] = field(
        default_factory=lambda: [MockProvenanceRecord()]
    )
    schema_version: str = "1.0"
    artifact_hash: str = "artifact_abc123"
    signature: str | None = None
    org_id: str | None = "org-gauntlet"

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "gauntlet_id": self.gauntlet_id,
            "verdict": self.verdict,
            "confidence": self.confidence,
        }


@pytest.fixture
def receipt():
    return MockReceipt()


# ============================================================================
# HTML Export Tests
# ============================================================================


class TestReceiptToHTML:
    def test_basic_html_structure(self, receipt):
        html = receipt_to_html(receipt)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_contains_receipt_id(self, receipt):
        html = receipt_to_html(receipt)
        assert "REC-001" in html

    def test_contains_verdict(self, receipt):
        html = receipt_to_html(receipt)
        assert "CONDITIONAL" in html
        assert "verdict-conditional" in html

    def test_pass_verdict_class(self):
        r = MockReceipt(verdict="PASS")
        html = receipt_to_html(r)
        assert "verdict-pass" in html

    def test_fail_verdict_class(self):
        r = MockReceipt(verdict="FAIL")
        html = receipt_to_html(r)
        assert "verdict-fail" in html

    def test_contains_risk_summary(self, receipt):
        html = receipt_to_html(receipt)
        assert "Critical" in html
        assert "High" in html

    def test_contains_findings(self, receipt):
        html = receipt_to_html(receipt)
        assert "SQL Injection" in html
        assert "XSS" in html

    def test_contains_provenance(self, receipt):
        html = receipt_to_html(receipt)
        assert "Provenance" in html

    def test_no_findings_section_when_empty(self):
        r = MockReceipt(vulnerability_details=[])
        html = receipt_to_html(r)
        assert "Findings" not in html

    def test_no_provenance_when_empty(self):
        r = MockReceipt(provenance_chain=[])
        html = receipt_to_html(r)
        assert "Provenance" not in html

    def test_html_escapes_special_chars(self):
        r = MockReceipt(verdict_reasoning="<script>alert('xss')</script>")
        html = receipt_to_html(r)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ============================================================================
# PDF Export Tests
# ============================================================================


class TestReceiptToPDF:
    def test_produces_valid_pdf_bytes(self, receipt):
        pdf = receipt_to_pdf(receipt)
        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF-1.4")
        assert pdf.endswith(b"%%EOF\n")

    def test_contains_receipt_id_in_pdf(self, receipt):
        pdf = receipt_to_pdf(receipt)
        assert b"REC-001" in pdf

    def test_contains_verdict_in_pdf(self, receipt):
        pdf = receipt_to_pdf(receipt)
        assert b"CONDITIONAL" in pdf

    def test_contains_confidence(self, receipt):
        pdf = receipt_to_pdf(receipt)
        assert b"85.0%" in pdf

    def test_empty_findings(self):
        r = MockReceipt(vulnerability_details=[])
        pdf = receipt_to_pdf(r)
        assert isinstance(pdf, bytes)
        assert b"Findings" not in pdf


# ============================================================================
# Handler Tests
# ============================================================================


def _make_mock_handler(method="GET"):
    mock = MagicMock()
    mock.command = method
    mock.rfile = MagicMock()
    mock.rfile.read = MagicMock(return_value=b"{}")
    mock.headers = {"Content-Length": "2"}
    return mock


def _parse(result) -> dict[str, Any]:
    if result is None:
        return {}
    body = result.body
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {}


class TestReceiptExportHandler:
    @pytest.fixture(autouse=True)
    def org_member(self, monkeypatch):
        """Requests come from an authenticated member of the receipt's org."""
        from aragora.billing.auth.context import UserAuthContext

        user = UserAuthContext(
            authenticated=True,
            user_id="user-gauntlet",
            email="member@example.com",
            org_id="org-gauntlet",
            role="member",
            token_type="access",
        )
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: user,
        )
        return user

    @pytest.fixture
    def handler(self):
        from aragora.server.handlers.receipt_export import ReceiptExportHandler

        mock_receipt = MockReceipt()
        mock_store = MagicMock()
        mock_store.get.return_value = mock_receipt
        return ReceiptExportHandler(ctx={"receipt_store": mock_store})

    @pytest.fixture
    def handler_no_store(self):
        from aragora.server.handlers.receipt_export import ReceiptExportHandler

        return ReceiptExportHandler(ctx={})

    def test_can_handle_export_path(self, handler):
        assert handler.can_handle("/api/v1/receipts/REC-001/export") is True

    def test_cannot_handle_other_paths(self, handler):
        assert handler.can_handle("/api/v1/receipts/REC-001") is False
        assert handler.can_handle("/api/v1/other") is False

    @patch("aragora.server.handlers.receipt_export._get_receipt_store")
    def test_json_export(self, mock_store_fn, handler):
        mock_store_fn.return_value = None  # Fall back to ctx
        http = _make_mock_handler()
        result = handler.handle("/api/v1/receipts/REC-001/export", {"format": "json"}, http)
        assert result.status_code == 200
        body = _parse(result)
        assert body["receipt_id"] == "REC-001"

    @patch("aragora.server.handlers.receipt_export._get_receipt_store")
    def test_html_export(self, mock_store_fn, handler):
        mock_store_fn.return_value = None
        http = _make_mock_handler()
        result = handler.handle("/api/v1/receipts/REC-001/export", {"format": "html"}, http)
        assert result.status_code == 200
        assert "text/html" in result.content_type
        body = result.body if isinstance(result.body, bytes) else result.body.encode()
        assert b"<!DOCTYPE html>" in body

    @patch("aragora.server.handlers.receipt_export._get_receipt_store")
    def test_pdf_export(self, mock_store_fn, handler):
        mock_store_fn.return_value = None
        http = _make_mock_handler()
        result = handler.handle("/api/v1/receipts/REC-001/export", {"format": "pdf"}, http)
        assert result.status_code == 200
        assert "application/pdf" in result.content_type
        assert result.body.startswith(b"%PDF")

    @patch("aragora.server.handlers.receipt_export._get_receipt_store")
    def test_invalid_format(self, mock_store_fn, handler):
        mock_store_fn.return_value = None
        http = _make_mock_handler()
        result = handler.handle("/api/v1/receipts/REC-001/export", {"format": "xml"}, http)
        assert result.status_code == 400

    @patch("aragora.server.handlers.receipt_export._get_receipt_store")
    def test_receipt_not_found(self, mock_store_fn, handler_no_store):
        mock_store_fn.return_value = None
        http = _make_mock_handler()
        result = handler_no_store.handle(
            "/api/v1/receipts/MISSING/export", {"format": "json"}, http
        )
        assert result.status_code == 404

    @patch("aragora.server.handlers.receipt_export._get_receipt_store")
    def test_other_org_receipt_is_not_found(self, mock_store_fn):
        from aragora.server.handlers.receipt_export import ReceiptExportHandler

        mock_store_fn.return_value = None
        foreign = ReceiptExportHandler(
            ctx={"receipt_store": {"REC-001": MockReceipt(org_id="org-other")}}
        )
        result = foreign.handle(
            "/api/v1/receipts/REC-001/export", {"format": "json"}, _make_mock_handler()
        )
        assert result.status_code == 404
        assert "REC-001" not in result.body.decode()
