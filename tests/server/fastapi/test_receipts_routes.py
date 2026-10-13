"""
Tests for FastAPI receipt route endpoints.

 Covers:
- List receipts with pagination
- Get receipt by ID
- Create receipt share links
- Access shared receipts
- Verify receipt integrity
- Export receipt in various formats
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi import create_app
from aragora.server.fastapi.dependencies.auth import require_authenticated
from aragora.server.handlers.utils.receipt_delivery_history import (
    DELIVERY_ORG_KEY,
    get_receipt_delivery_history_store,
)
from aragora.storage.receipt_store import StoredReceipt
from aragora.tenancy.record_scope import OrgScope, require_org_scope_fastapi

ORG_ID = "org-1"


def _org_of(receipt):
    if isinstance(receipt, dict):
        return receipt.get("org_id")
    return getattr(receipt, "org_id", None)


@pytest.fixture
def app():
    """Create a test FastAPI app whose callers belong to ``ORG_ID``."""
    app = create_app()
    app.dependency_overrides[require_org_scope_fastapi] = lambda: OrgScope(
        org_id=ORG_ID, user_id="user-1", role="member"
    )
    return app


@pytest.fixture
def mock_receipt_store():
    """Mock receipt store; ``get_for_org`` filters ``get`` by owner like the real store."""
    store = MagicMock()
    store.list_for_org = MagicMock(return_value=[])
    store.count_for_org = MagicMock(return_value=0)
    store.get = MagicMock(return_value=None)
    store.get_by_id = MagicMock(return_value=None)

    def _get_for_org(receipt_id, org_id):
        receipt = store.get(receipt_id)
        return receipt if receipt is not None and _org_of(receipt) == org_id else None

    store.get_for_org = MagicMock(side_effect=_get_for_org)
    return store


@pytest.fixture
def mock_receipt_share_store():
    """Create a mock receipt share store."""
    store = MagicMock()
    store.save = MagicMock()
    store.get_by_token = MagicMock(return_value=None)
    store.increment_access = MagicMock(return_value=True)
    return store


@pytest.fixture
def client(app, mock_receipt_store, mock_receipt_share_store):
    """Create a test client with mocked context."""
    app.state.context = {
        "storage": MagicMock(),
        "elo_system": MagicMock(),
        "user_store": None,
        "rbac_checker": MagicMock(),
        "decision_service": MagicMock(),
        "receipt_store": mock_receipt_store,
        "receipt_share_store": mock_receipt_share_store,
    }
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clear_receipt_delivery_history():
    """Keep shared receipt delivery history isolated per test."""
    history = get_receipt_delivery_history_store()
    history.clear()
    yield
    history.clear()


def _override_auth(
    client: TestClient,
    *,
    roles: set[str] | None = None,
    permissions: set[str] | None = None,
) -> None:
    """Override auth dependency with a minimal authenticated context."""
    auth_ctx = AuthorizationContext(
        user_id="user-1",
        org_id="org-1",
        workspace_id="ws-1",
        roles=roles if roles is not None else {"member"},
        permissions=permissions if permissions is not None else set(),
    )
    client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx


@pytest.fixture
def sample_receipt_dict():
    """Sample receipt data for testing."""
    return {
        "receipt_id": "rcpt_test123",
        "gauntlet_id": "gauntlet-20260211-abc123",
        "timestamp": "2026-02-11T12:00:00",
        "input_summary": "Test input content",
        "input_type": "spec",
        "schema_version": "1.0",
        "verdict": "APPROVED",
        "confidence": 0.85,
        "risk_level": "LOW",
        "risk_score": 0.15,
        "robustness_score": 0.85,
        "coverage_score": 0.9,
        "verification_coverage": 0.7,
        "findings": [
            {
                "id": "f-001",
                "severity": "MEDIUM",
                "category": "security",
                "title": "Input validation missing",
                "description": "The input lacks validation",
                "mitigation": "Add input validation",
                "source": "claude",
                "verified": False,
            }
        ],
        "critical_count": 0,
        "high_count": 0,
        "medium_count": 1,
        "low_count": 0,
        "mitigations": ["Add input validation"],
        "dissenting_views": [],
        "unresolved_tensions": [],
        "verified_claims": [],
        "unverified_claims": [],
        "agents_involved": ["claude", "codex"],
        "rounds_completed": 3,
        "duration_seconds": 45.2,
        "audit_trail_id": None,
        "checksum": "abc123",
        "org_id": ORG_ID,
    }


@pytest.fixture
def sample_stored_receipt(sample_receipt_dict):
    """StoredReceipt carrying the rich payload persisted by quickstart."""
    return StoredReceipt(
        receipt_id=sample_receipt_dict["receipt_id"],
        gauntlet_id=sample_receipt_dict["gauntlet_id"],
        debate_id="debate-123",
        created_at=1740000000.0,
        expires_at=None,
        verdict=sample_receipt_dict["verdict"],
        confidence=sample_receipt_dict["confidence"],
        risk_level=sample_receipt_dict["risk_level"],
        risk_score=sample_receipt_dict["risk_score"],
        checksum=sample_receipt_dict["checksum"],
        audit_trail_id=sample_receipt_dict["audit_trail_id"],
        data=sample_receipt_dict,
        org_id=ORG_ID,
    )


class TestListReceipts:
    """Tests for GET /api/v2/receipts."""

    def test_list_receipts_returns_200(self, client):
        """List receipts should return 200 with empty list."""
        response = client.get("/api/v2/receipts")
        assert response.status_code == 200
        data = response.json()
        assert "receipts" in data
        assert "total" in data
        assert data["receipts"] == []
        assert data["total"] == 0

    def test_list_receipts_with_pagination(self, client):
        """List receipts supports pagination params."""
        response = client.get("/api/v2/receipts?limit=10&offset=5")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 5

    def test_list_receipts_with_verdict_filter(self, client):
        """List receipts supports verdict filter."""
        response = client.get("/api/v2/receipts?verdict=APPROVED")
        assert response.status_code == 200

    def test_list_receipts_forwards_debate_id_filter(self, app, sample_stored_receipt):
        """List receipts forwards debate_id filtering to durable stores."""

        calls: dict[str, tuple[str, dict[str, object]]] = {}

        class StorageBackedStore:
            def list_for_org(self, org_id, **kwargs):
                calls["list"] = (org_id, kwargs)
                return [sample_stored_receipt]

            def count_for_org(self, org_id, **kwargs):
                calls["count"] = (org_id, kwargs)
                return 1

        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "receipt_store": StorageBackedStore(),
        }
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v2/receipts?debate_id=debate-123")
        assert response.status_code == 200
        assert calls["list"][0] == calls["count"][0] == ORG_ID
        assert calls["list"][1]["debate_id"] == "debate-123"
        assert calls["count"][1]["debate_id"] == "debate-123"

    def test_list_receipts_filters_list_all_fallback_by_debate_id(self, app):
        """List-all fallback should still respect debate_id filtering."""

        class ListAllStore:
            def list_all(self):
                return [
                    {
                        "receipt_id": "receipt-1",
                        "debate_id": "debate-123",
                        "verdict": "APPROVED",
                        "org_id": ORG_ID,
                    },
                    {
                        "receipt_id": "receipt-2",
                        "debate_id": "debate-999",
                        "verdict": "APPROVED",
                        "org_id": ORG_ID,
                    },
                ]

        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "receipt_store": ListAllStore(),
        }
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v2/receipts?debate_id=debate-123")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert [receipt["receipt_id"] for receipt in data["receipts"]] == ["receipt-1"]

    def test_list_receipts_with_data(self, client, mock_receipt_store, sample_receipt_dict):
        """List receipts returns receipt summaries."""
        mock_receipt_store.list_for_org.return_value = [sample_receipt_dict]
        mock_receipt_store.count_for_org.return_value = 1

        response = client.get("/api/v2/receipts")
        assert response.status_code == 200
        data = response.json()
        assert len(data["receipts"]) == 1
        assert data["receipts"][0]["receipt_id"] == "rcpt_test123"
        assert data["receipts"][0]["input_summary"] == "Test input content"
        assert data["receipts"][0]["verdict"] == "APPROVED"
        assert data["total"] == 1

    def test_list_receipts_with_storage_store_objects(self, app, sample_stored_receipt):
        """List receipts should support the durable store's org-scoped list API."""

        class StorageBackedStore:
            def list_for_org(self, org_id, **kwargs):
                return [sample_stored_receipt]

            def count_for_org(self, org_id, **kwargs):
                return 1

        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "receipt_store": StorageBackedStore(),
        }
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v2/receipts")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["receipts"][0]["receipt_id"] == "rcpt_test123"
        assert data["receipts"][0]["input_summary"] == "Test input content"
        assert data["receipts"][0]["findings_count"] == 1

    def test_list_receipts_validation_limit_bounds(self, client):
        """Pagination limit must be between 1 and 100."""
        response = client.get("/api/v2/receipts?limit=0")
        assert response.status_code == 422

        response = client.get("/api/v2/receipts?limit=101")
        assert response.status_code == 422


class TestGetReceipt:
    """Tests for GET /api/v2/receipts/{receipt_id}."""

    def test_get_receipt_not_found(self, client):
        """Get nonexistent receipt returns 404."""
        response = client.get("/api/v2/receipts/nonexistent-id")
        assert response.status_code == 404

    def test_get_receipt_found(self, client, mock_receipt_store, sample_receipt_dict):
        """Get existing receipt returns full details."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123")
        assert response.status_code == 200
        data = response.json()
        assert data["receipt_id"] == "rcpt_test123"
        assert data["gauntlet_id"] == "gauntlet-20260211-abc123"
        assert data["verdict"] == "APPROVED"
        assert data["confidence"] == 0.85
        assert len(data["findings"]) == 1
        assert data["agents_involved"] == ["claude", "codex"]

    def test_get_receipt_with_nested_data(self, client, mock_receipt_store, sample_receipt_dict):
        """Get receipt handles stored receipts with nested 'data' key."""
        mock_receipt_store.get.return_value = {"data": sample_receipt_dict, "org_id": ORG_ID}

        response = client.get("/api/v2/receipts/rcpt_test123")
        assert response.status_code == 200
        data = response.json()
        assert data["receipt_id"] == "rcpt_test123"

    def test_get_receipt_from_stored_receipt_uses_full_payload(
        self, client, mock_receipt_store, sample_stored_receipt
    ):
        """StoredReceipt objects should expose their rich data payload."""
        mock_receipt_store.get.return_value = sample_stored_receipt

        response = client.get("/api/v2/receipts/rcpt_test123")
        assert response.status_code == 200
        data = response.json()
        assert data["input_summary"] == "Test input content"
        assert data["timestamp"] == "2026-02-11T12:00:00"
        assert len(data["findings"]) == 1
        assert data["agents_involved"] == ["claude", "codex"]


class TestVerifyReceipt:
    """Tests for GET /api/v2/receipts/{receipt_id}/verify."""

    def test_verify_receipt_not_found(self, client):
        """Verify nonexistent receipt returns 404."""
        response = client.get("/api/v2/receipts/nonexistent-id/verify")
        assert response.status_code == 404

    def test_verify_receipt_returns_verification_result(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        """Verify receipt returns verification details."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/verify")
        assert response.status_code == 200
        data = response.json()
        assert data["receipt_id"] == "rcpt_test123"
        assert "verified" in data
        assert "integrity_valid" in data
        assert "checksum_match" in data
        assert "details" in data

    def test_verify_receipt_with_valid_integrity(self, client, mock_receipt_store):
        """Verify receipt with matching checksum succeeds."""
        from aragora.export.decision_receipt import DecisionReceipt

        receipt = DecisionReceipt(
            receipt_id="rcpt_integrity_test",
            gauntlet_id="gauntlet-test",
            verdict="APPROVED",
            confidence=0.9,
        )
        receipt_dict = {**receipt.to_dict(), "org_id": ORG_ID}
        mock_receipt_store.get.return_value = receipt_dict

        response = client.get("/api/v2/receipts/rcpt_integrity_test/verify")
        assert response.status_code == 200
        data = response.json()
        assert data["integrity_valid"] is True


class TestExportReceipt:
    """Tests for GET /api/v2/receipts/{receipt_id}/export."""

    def test_export_receipt_not_found(self, client):
        """Export nonexistent receipt returns 404."""
        response = client.get("/api/v2/receipts/nonexistent-id/export")
        assert response.status_code == 404

    def test_export_receipt_json_format(self, client, mock_receipt_store, sample_receipt_dict):
        """Export receipt in JSON format."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=json")
        assert response.status_code == 200
        data = response.json()
        assert data["receipt_id"] == "rcpt_test123"
        assert data["format"] == "json"
        assert "content" in data
        # Content should be valid JSON
        import json

        parsed = json.loads(data["content"])
        assert parsed["receipt_id"] == "rcpt_test123"

    def test_export_receipt_markdown_format(self, client, mock_receipt_store, sample_receipt_dict):
        """Export receipt in Markdown format."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=markdown")
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "markdown"
        assert "Decision Receipt" in data["content"]

    def test_export_receipt_markdown_raw_mode(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        """Raw mode returns markdown bytes for the live download surfaces."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=md&raw=true")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "Decision Receipt" in response.text

    def test_export_receipt_md_alias_format(self, client, mock_receipt_store, sample_receipt_dict):
        """Export receipt accepts the legacy md alias used by the live UI."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=md")
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "markdown"
        assert "Decision Receipt" in data["content"]

    def test_export_receipt_html_format(self, client, mock_receipt_store, sample_receipt_dict):
        """Export receipt supports HTML for onboarding and receipt download links."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=html")
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "html"
        assert "<!DOCTYPE html>" in data["content"]
        assert "Decision Receipt" in data["content"]

    def test_export_receipt_html_raw_mode(self, client, mock_receipt_store, sample_receipt_dict):
        """Raw HTML mode returns an inline document for onboarding receipt links."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=html&raw=true")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "<!DOCTYPE html>" in response.text
        assert "Decision Receipt" in response.text

    def test_export_receipt_sarif_format(self, client, mock_receipt_store, sample_receipt_dict):
        """Export receipt in SARIF format."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=sarif")
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "sarif"
        import json

        sarif = json.loads(data["content"])
        assert sarif["version"] == "2.1.0"

    def test_export_receipt_json_raw_mode(self, client, mock_receipt_store, sample_receipt_dict):
        """Raw JSON mode serves the receipt body directly for file downloads."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=json&raw=true")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["receipt_id"] == "rcpt_test123"

    def test_export_receipt_pdf_format_returns_pdf_bytes(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        """PDF export should return raw bytes for browser/download flows."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        mock_receipt = MagicMock()
        mock_receipt.to_pdf.return_value = b"%PDF-1.4..."

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_receipt
        ):
            response = client.get("/api/v2/receipts/rcpt_test123/export?format=pdf")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")
        assert response.content == b"%PDF-1.4..."

    def test_export_receipt_pdf_fallback_returns_printable_html(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        """When PDF generation is unavailable, export falls back to printable HTML."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        mock_receipt = MagicMock()
        mock_receipt.to_pdf.side_effect = ImportError("weasyprint not found")
        mock_receipt.to_html.return_value = "<div>Receipt Content</div>"

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_receipt
        ):
            response = client.get("/api/v2/receipts/rcpt_test123/export?format=pdf")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["x-pdf-fallback"] == "true"
        assert "PDF export is unavailable" in response.text
        assert "Receipt Content" in response.text

    def test_export_receipt_from_stored_receipt_uses_full_payload(
        self, client, mock_receipt_store, sample_stored_receipt
    ):
        """StoredReceipt exports should reconstruct from the full stored data."""
        mock_receipt_store.get.return_value = sample_stored_receipt

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=json")
        assert response.status_code == 200
        data = response.json()
        import json

        exported = json.loads(data["content"])
        assert exported["input_summary"] == "Test input content"
        assert exported["agents_involved"] == ["claude", "codex"]
        assert data["format"] == "json"

    def test_export_receipt_from_stored_receipt_preserves_cost_summary(
        self, client, mock_receipt_store, sample_stored_receipt
    ):
        """Stored rich receipt payloads export even when cost_summary is present."""
        sample_stored_receipt.data = dict(sample_stored_receipt.data)
        sample_stored_receipt.data["cost_summary"] = {
            "total_cost_usd": "0.0234",
            "total_tokens_in": 3000,
            "total_tokens_out": 1000,
            "total_calls": 6,
            "per_agent": {"claude": {"total_cost_usd": "0.015", "call_count": 3}},
        }
        mock_receipt_store.get.return_value = sample_stored_receipt

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=json")

        assert response.status_code == 200
        data = response.json()
        import json

        exported = json.loads(data["content"])
        assert exported["cost_summary"]["total_cost_usd"] == "0.0234"
        assert exported["cost_summary"]["per_agent"]["claude"]["call_count"] == 3

    def test_export_receipt_default_format_is_json(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        """Export without format param defaults to JSON."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export")
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "json"

    def test_export_receipt_invalid_format(self, client, mock_receipt_store, sample_receipt_dict):
        """Export with invalid format returns 422."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/rcpt_test123/export?format=pdf_invalid")
        assert response.status_code == 422


# =============================================================================
# GET /api/v2/receipts/search
# =============================================================================


class TestSearchReceipts:
    """Tests for GET /api/v2/receipts/search."""

    def test_search_returns_200_empty(self, client, mock_receipt_store):
        """Search with no results returns 200 with empty list."""
        mock_receipt_store.search_for_org = MagicMock(return_value=[])
        mock_receipt_store.search_count_for_org = MagicMock(return_value=0)

        response = client.get("/api/v2/receipts/search?q=test")
        assert response.status_code == 200
        data = response.json()
        assert data["receipts"] == []
        assert data["query"] == "test"
        assert data["total"] == 0

    def test_search_requires_query(self, client):
        """Search without query returns 422."""
        response = client.get("/api/v2/receipts/search")
        assert response.status_code == 422

    def test_search_returns_results(self, client, mock_receipt_store, sample_receipt_dict):
        """Search returns matching receipts."""
        mock_receipt_store.search_for_org = MagicMock(return_value=[sample_receipt_dict])
        mock_receipt_store.search_count_for_org = MagicMock(return_value=1)

        response = client.get("/api/v2/receipts/search?q=security")
        assert response.status_code == 200
        data = response.json()
        assert len(data["receipts"]) == 1
        assert data["receipts"][0]["receipt_id"] == "rcpt_test123"
        assert data["total"] == 1

    def test_search_with_filters(self, client, mock_receipt_store):
        """Search passes verdict and risk_level filters."""
        mock_receipt_store.search_for_org = MagicMock(return_value=[])
        mock_receipt_store.search_count_for_org = MagicMock(return_value=0)

        response = client.get("/api/v2/receipts/search?q=test&verdict=APPROVED&risk_level=LOW")
        assert response.status_code == 200
        mock_receipt_store.search_for_org.assert_called_once()
        call_kwargs = mock_receipt_store.search_for_org.call_args
        assert call_kwargs.args == (ORG_ID,)
        assert call_kwargs.kwargs.get("verdict") == "APPROVED"
        assert call_kwargs.kwargs.get("risk_level") == "LOW"

    def test_search_with_pagination(self, client, mock_receipt_store):
        """Search supports pagination."""
        mock_receipt_store.search_for_org = MagicMock(return_value=[])
        mock_receipt_store.search_count_for_org = MagicMock(return_value=0)

        response = client.get("/api/v2/receipts/search?q=test&limit=10&offset=5")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 5


# =============================================================================
# GET /api/v2/receipts/stats
# =============================================================================


class TestReceiptStats:
    """Tests for GET /api/v2/receipts/stats."""

    def test_stats_returns_200(self, client, mock_receipt_store):
        """Stats returns aggregate statistics."""
        mock_receipt_store.stats_for_org = MagicMock(
            return_value={
                "total": 100,
                "verified": 85,
                "by_verdict": {"APPROVED": 70, "REJECTED": 30},
                "by_risk_level": {"LOW": 50, "MEDIUM": 30, "HIGH": 20},
            }
        )

        response = client.get("/api/v2/receipts/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 100
        assert data["verified"] == 85
        assert data["by_verdict"]["APPROVED"] == 70
        assert data["by_risk_level"]["LOW"] == 50
        assert "generated_at" in data

    def test_stats_empty_store(self, client, mock_receipt_store):
        """Stats with empty store returns zeros."""
        mock_receipt_store.stats_for_org = MagicMock(return_value={})

        response = client.get("/api/v2/receipts/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0

    def test_stats_preserve_delivery_aggregates_from_store(self, client, mock_receipt_store):
        """Stats should keep delivery aggregates surfaced by the store."""
        mock_receipt_store.stats_for_org = MagicMock(
            return_value={
                "total": 12,
                "verified": 10,
                "delivered": 8,
                "pending": 3,
                "failed": 1,
                "delivery_rate": 0.8889,
            }
        )

        response = client.get("/api/v2/receipts/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["delivered"] == 8
        assert data["pending"] == 3
        assert data["failed"] == 1
        assert data["delivery_rate"] == pytest.approx(0.8889)

    def test_stats_derive_delivery_rate_from_store_counts(self, client, mock_receipt_store):
        """Stats should compute a missing delivery rate from the returned counts."""
        mock_receipt_store.stats_for_org = MagicMock(
            return_value={
                "total": 12,
                "verified": 10,
                "delivered": 8,
                "pending": 3,
                "failed": 1,
            }
        )
        get_receipt_delivery_history_store().extend(
            [
                {
                    "receiptId": "r-1",
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "delivered",
                    "deliveredAt": "2026-04-08T00:00:00Z",
                },
                {
                    "receiptId": "r-2",
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "failed",
                    "deliveredAt": "2026-04-08T00:01:00Z",
                },
            ]
        )

        response = client.get("/api/v2/receipts/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["delivered"] == 8
        assert data["pending"] == 3
        assert data["failed"] == 1
        assert data["delivery_rate"] == pytest.approx(8 / 9)

    def test_stats_backfill_delivery_aggregates_from_history(self, client, mock_receipt_store):
        """Stats should derive delivery aggregates when the store omits them."""
        mock_receipt_store.stats_for_org = MagicMock(return_value={"total": 5, "verified": 4})
        get_receipt_delivery_history_store().extend(
            [
                {
                    "receiptId": "r-1",
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "delivered",
                    "deliveredAt": "2026-04-08T00:00:00Z",
                },
                {
                    "receiptId": "r-2",
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "success",
                    "deliveredAt": "2026-04-08T00:01:00Z",
                },
                {
                    "receiptId": "r-3",
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "pending",
                    "deliveredAt": "2026-04-08T00:02:00Z",
                },
                {
                    "receiptId": "r-4",
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "failed",
                    "deliveredAt": "2026-04-08T00:03:00Z",
                },
            ]
        )

        response = client.get("/api/v2/receipts/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["delivered"] == 2
        assert data["pending"] == 1
        assert data["failed"] == 1
        assert data["delivery_rate"] == pytest.approx(2 / 3)

    def test_stats_ignore_test_and_orphan_delivery_history(self, client, mock_receipt_store):
        """Stats should ignore test sends and non-receipt history entries."""
        mock_receipt_store.stats_for_org = MagicMock(return_value={"total": 1, "verified": 1})
        get_receipt_delivery_history_store().extend(
            [
                {
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "success",
                    "is_test": True,
                    "receiptId": "test-1",
                },
                {
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "failed",
                    "is_test": True,
                    "receiptId": "test-2",
                },
                {
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "delivered",
                    "receiptId": "real-1",
                },
                {
                    DELIVERY_ORG_KEY: ORG_ID,
                    "status": "failed",
                    "channel_type": "slack",
                },
            ]
        )

        response = client.get("/api/v2/receipts/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["delivered"] == 1
        assert data["pending"] == 0
        assert data["failed"] == 0
        assert data["delivery_rate"] == pytest.approx(1.0)


class TestShareReceipt:
    """Tests for POST /api/v2/receipts/{receipt_id}/share."""

    def test_share_receipt_requires_auth(self, client):
        response = client.post("/api/v2/receipts/rcpt_test123/share", json={})
        assert response.status_code == 401

    def test_share_receipt_requires_permission(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        mock_receipt_store.get.return_value = sample_receipt_dict
        _override_auth(client, roles=set(), permissions=set())
        response = client.post("/api/v2/receipts/rcpt_test123/share", json={})
        client.app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_share_receipt_not_found(self, client):
        _override_auth(client, permissions={"receipts:share"})
        response = client.post("/api/v2/receipts/missing/share", json={})
        client.app.dependency_overrides.clear()
        assert response.status_code == 404

    def test_share_receipt_success(
        self, client, mock_receipt_store, mock_receipt_share_store, sample_receipt_dict
    ):
        from aragora.rbac.models import AuthorizationContext
        from aragora.server.fastapi.dependencies.auth import require_authenticated

        mock_receipt_store.get.return_value = sample_receipt_dict
        _override_auth(client, permissions={"receipts:share"})

        response = client.post(
            "/api/v2/receipts/rcpt_test123/share",
            json={"expires_in_hours": 12, "max_accesses": 3},
        )
        client.app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["receipt_id"] == "rcpt_test123"
        assert data["share_url"].startswith("/api/v2/receipts/share/")
        assert data["max_accesses"] == 3
        mock_receipt_share_store.save.assert_called_once()


class TestFormattedReceipt:
    """Tests for GET /api/v2/receipts/{receipt_id}/formatted/{channel_type}."""

    def test_get_formatted_receipt_not_found(self, client):
        response = client.get("/api/v2/receipts/missing/formatted/slack")
        assert response.status_code == 404

    def test_get_formatted_receipt_success(self, client, mock_receipt_store, sample_receipt_dict):
        mock_receipt_store.get.return_value = sample_receipt_dict

        with patch(
            "aragora.channels.formatter.format_receipt_for_channel",
            return_value={"blocks": [{"type": "section"}]},
        ) as format_receipt:
            response = client.get("/api/v2/receipts/rcpt_test123/formatted/slack?compact=true")

        assert response.status_code == 200
        data = response.json()
        assert data["receipt_id"] == "rcpt_test123"
        assert data["channel_type"] == "slack"
        assert data["formatted"]["blocks"][0]["type"] == "section"
        format_receipt.assert_called_once()

    def test_get_formatted_receipt_invalid_channel(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        mock_receipt_store.get.return_value = sample_receipt_dict

        with patch(
            "aragora.channels.formatter.format_receipt_for_channel",
            side_effect=ValueError("No formatter registered for channel: fax"),
        ):
            response = client.get("/api/v2/receipts/rcpt_test123/formatted/fax")

        assert response.status_code == 400
        assert response.json()["detail"] == "No formatter registered for channel: fax"


class TestVerifyReceiptSignature:
    """Tests for POST /api/v2/receipts/{receipt_id}/verify-signature."""

    def test_verify_signature_not_found(self, client, mock_receipt_store):
        result = MagicMock()
        result.error = "Receipt not found"
        result.to_dict.return_value = {
            "receipt_id": "missing",
            "signature_valid": False,
            "algorithm": None,
            "key_id": None,
            "signed_at": None,
            "verification_timestamp": "2026-02-11T12:00:00Z",
            "error": "Receipt not found",
        }
        mock_receipt_store.verify_signature = MagicMock(return_value=result)

        response = client.post("/api/v2/receipts/missing/verify-signature")
        assert response.status_code == 404

    def test_verify_signature_success(self, client, mock_receipt_store, sample_receipt_dict):
        mock_receipt_store.get.return_value = sample_receipt_dict
        result = MagicMock()
        result.error = None
        result.to_dict.return_value = {
            "receipt_id": "rcpt_test123",
            "signature_valid": True,
            "algorithm": "hmac-sha256",
            "key_id": "key-1",
            "signed_at": 1740000000.0,
            "verification_timestamp": "2026-02-11T12:00:00Z",
            "error": None,
        }
        mock_receipt_store.verify_signature = MagicMock(return_value=result)

        response = client.post("/api/v2/receipts/rcpt_test123/verify-signature")
        assert response.status_code == 200
        data = response.json()
        assert data["receipt_id"] == "rcpt_test123"
        assert data["signature_valid"] is True
        assert data["algorithm"] == "hmac-sha256"
        mock_receipt_store.verify_signature.assert_called_once_with("rcpt_test123", org_id=ORG_ID)


class TestSendToChannel:
    """Tests for POST /api/v2/receipts/{receipt_id}/send-to-channel."""

    def test_send_to_channel_requires_auth(self, client):
        response = client.post(
            "/api/v2/receipts/rcpt_test123/send-to-channel",
            json={"channel_type": "email", "channel_id": "user@example.com"},
        )
        assert response.status_code == 401

    def test_send_to_channel_requires_permission(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        mock_receipt_store.get.return_value = sample_receipt_dict
        _override_auth(client, roles=set(), permissions=set())
        response = client.post(
            "/api/v2/receipts/rcpt_test123/send-to-channel",
            json={"channel_type": "email", "channel_id": "user@example.com"},
        )
        client.app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_send_to_channel_not_found(self, client):
        _override_auth(client, permissions={"receipts:share"})
        response = client.post(
            "/api/v2/receipts/missing/send-to-channel",
            json={"channel_type": "email", "channel_id": "user@example.com"},
        )
        client.app.dependency_overrides.clear()
        assert response.status_code == 404

    def test_send_to_channel_success(self, client, mock_receipt_store, sample_receipt_dict):
        mock_receipt_store.get.return_value = sample_receipt_dict
        _override_auth(client, permissions={"receipts:share"})

        with patch(
            "aragora.channels.formatter.format_receipt_for_channel",
            return_value={"subject": "Decision Receipt", "html": "<p>ok</p>"},
        ):
            with patch(
                "aragora.server.handlers.receipts.ReceiptsHandler._send_to_email",
                new=AsyncMock(
                    return_value={"message_id": "msg-123", "email_sent_to": "user@example.com"}
                ),
            ):
                response = client.post(
                    "/api/v2/receipts/rcpt_test123/send-to-channel",
                    json={"channel_type": "email", "channel_id": "user@example.com"},
                )

        client.app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["sent"] is True
        assert data["receipt_id"] == "rcpt_test123"
        assert data["channel_type"] == "email"
        assert data["message_id"] == "msg-123"
        assert [entry[DELIVERY_ORG_KEY] for entry in get_receipt_delivery_history_store()] == [
            ORG_ID
        ]


class TestGetSharedReceipt:
    """Tests for GET /api/v2/receipts/share/{token}."""

    def test_get_shared_receipt_not_found(self, client):
        response = client.get("/api/v2/receipts/share/bad-token")
        assert response.status_code == 404

    def test_get_shared_receipt_success_json(
        self, client, mock_receipt_store, mock_receipt_share_store, sample_receipt_dict
    ):
        mock_receipt_share_store.get_by_token.return_value = {
            "token": "valid-token",
            "receipt_id": "rcpt_test123",
            "expires_at": None,
            "max_accesses": 5,
            "access_count": 1,
        }
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get("/api/v2/receipts/share/valid-token")
        assert response.status_code == 200
        data = response.json()
        assert data["shared"] is True
        assert data["access_count"] == 2
        assert data["receipt"]["receipt_id"] == "rcpt_test123"
        mock_receipt_share_store.increment_access.assert_called_once_with("valid-token")

    def test_get_shared_receipt_success_html(
        self, client, mock_receipt_store, mock_receipt_share_store, sample_receipt_dict
    ):
        mock_receipt_share_store.get_by_token.return_value = {
            "token": "html-token",
            "receipt_id": "rcpt_test123",
            "expires_at": None,
            "max_accesses": None,
            "access_count": 0,
        }
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.get(
            "/api/v2/receipts/share/html-token",
            headers={"Accept": "text/html"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Aragora Decision Receipt" in response.text
        assert (
            '<meta property="og:url" content="https://aragora.ai/api/v2/receipts/share/html-token" />'
            in response.text
        )
        assert (
            '<link rel="canonical" href="https://aragora.ai/api/v2/receipts/share/html-token" />'
            in response.text
        )

    def test_runtime_openapi_has_receipt_share_paths(self, app):
        spec = app.openapi()

        assert "/api/v2/receipts/share/{token}" in spec["paths"]
        assert "security" not in spec["paths"]["/api/v2/receipts/share/{token}"]["get"]

        assert "/api/v2/receipts/{receipt_id}/share" in spec["paths"]
        assert spec["paths"]["/api/v2/receipts/{receipt_id}/share"]["post"]["security"] == [
            {"bearerAuth": []}
        ]
        assert "/api/v2/receipts/{receipt_id}/formatted/{channel_type}" in spec["paths"]
        assert (
            "security"
            not in spec["paths"]["/api/v2/receipts/{receipt_id}/formatted/{channel_type}"]["get"]
        )
        assert "/api/v2/receipts/{receipt_id}/verify-signature" in spec["paths"]
        assert (
            "security"
            not in spec["paths"]["/api/v2/receipts/{receipt_id}/verify-signature"]["post"]
        )
        assert "/api/v2/receipts/{receipt_id}/send-to-channel" in spec["paths"]
        assert spec["paths"]["/api/v2/receipts/{receipt_id}/send-to-channel"]["post"][
            "security"
        ] == [{"bearerAuth": []}]


# =============================================================================
# POST /api/v2/receipts/batch-verify
# =============================================================================


class TestBatchVerify:
    """Tests for POST /api/v2/receipts/batch-verify."""

    def test_batch_verify_returns_200(self, client, mock_receipt_store, sample_receipt_dict):
        """Batch verify returns results for each receipt."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.post(
            "/api/v2/receipts/batch-verify",
            json={"receipt_ids": ["rcpt_test123"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["receipt_id"] == "rcpt_test123"
        assert "verified" in data["results"][0]

    def test_batch_verify_not_found(self, client, mock_receipt_store):
        """Batch verify handles missing receipts."""
        mock_receipt_store.get.return_value = None

        response = client.post(
            "/api/v2/receipts/batch-verify",
            json={"receipt_ids": ["nonexistent"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["verified"] is False
        assert data["results"][0]["error"] == "Receipt not found"
        assert data["failed_count"] == 1

    def test_batch_verify_empty_list(self, client):
        """Batch verify with empty list returns 422."""
        response = client.post(
            "/api/v2/receipts/batch-verify",
            json={"receipt_ids": []},
        )
        assert response.status_code == 422

    def test_batch_verify_multiple(self, client, mock_receipt_store, sample_receipt_dict):
        """Batch verify handles multiple receipts."""
        mock_receipt_store.get.side_effect = [sample_receipt_dict, None]

        response = client.post(
            "/api/v2/receipts/batch-verify",
            json={"receipt_ids": ["rcpt_1", "rcpt_missing"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2


# =============================================================================
# POST /api/v2/receipts/batch-export
# =============================================================================


class TestBatchExport:
    """Tests for POST /api/v2/receipts/batch-export."""

    def test_batch_export_json(self, client, mock_receipt_store, sample_receipt_dict):
        """Batch export returns exported items when JSON mode is requested explicitly."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["rcpt_test123"], "format": "json", "raw": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["exported_count"] == 1
        assert data["total_requested"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["format"] == "json"
        assert data["items"][0]["receipt_id"] == "rcpt_test123"

    def test_batch_export_missing_receipt(self, client, mock_receipt_store):
        """Batch export adds missing receipts to failed_ids."""
        mock_receipt_store.get.return_value = None

        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["missing"], "format": "json", "raw": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["exported_count"] == 0
        assert data["failed_ids"] == ["missing"]

    def test_batch_export_empty_list(self, client):
        """Batch export with empty list returns 422."""
        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": []},
        )
        assert response.status_code == 422

    def test_batch_export_markdown_format(self, client, mock_receipt_store, sample_receipt_dict):
        """Batch export in markdown format."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["rcpt_test123"], "format": "markdown", "raw": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"][0]["format"] == "markdown"

    def test_batch_export_html_format(self, client, mock_receipt_store, sample_receipt_dict):
        """Batch export supports HTML in the JSON item bundle."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["rcpt_test123"], "format": "html", "raw": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["items"][0]["format"] == "html"
        assert "<!DOCTYPE html>" in data["items"][0]["content"]

    def test_batch_export_pdf_defaults_to_zip_bundle(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        """PDF batch export should produce the default ZIP download bundle."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["rcpt_test123"], "format": "pdf"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/zip")
        archive = zipfile.ZipFile(BytesIO(response.content), "r")
        assert "receipt-rcpt_test123.pdf" in archive.namelist()
        assert archive.read("receipt-rcpt_test123.pdf").startswith(b"%PDF")
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "pdf"
        assert manifest["exported"] == 1
        assert manifest["failed"] == []

    def test_batch_export_pdf_json_mode_rejected(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        """PDF batch export rejects JSON item mode because PDFs are binary."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["rcpt_test123"], "format": "pdf", "raw": False},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "PDF batch export requires raw=true and returns a ZIP bundle of PDF files"
        )

    def test_batch_export_md_alias(self, client, mock_receipt_store, sample_receipt_dict):
        """Batch export normalizes the md alias to markdown content."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["rcpt_test123"], "format": "md", "raw": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["items"][0]["format"] == "markdown"

    def test_batch_export_defaults_to_zip_bundle(
        self, client, mock_receipt_store, sample_receipt_dict
    ):
        """Batch export defaults to the legacy ZIP bundle."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["rcpt_test123"], "format": "html"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/zip")
        assert response.headers["content-disposition"] == "attachment; filename=receipts-export.zip"

        archive = zipfile.ZipFile(BytesIO(response.content), "r")
        assert "receipt-rcpt_test123.html" in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "html"
        assert manifest["exported"] == 1
        assert manifest["failed"] == []

    def test_batch_export_raw_zip_bundle(self, client, mock_receipt_store, sample_receipt_dict):
        """Explicit raw mode still returns the legacy ZIP bundle with a manifest."""
        mock_receipt_store.get.return_value = sample_receipt_dict

        response = client.post(
            "/api/v2/receipts/batch-export",
            json={"receipt_ids": ["rcpt_test123"], "format": "html", "raw": True},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/zip")
        assert response.headers["content-disposition"] == "attachment; filename=receipts-export.zip"

        archive = zipfile.ZipFile(BytesIO(response.content), "r")
        assert "receipt-rcpt_test123.html" in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "html"
        assert manifest["exported"] == 1
        assert manifest["failed"] == []
