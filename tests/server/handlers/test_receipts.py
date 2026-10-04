"""
Tests for aragora.server.handlers.receipts - Decision Receipt HTTP Handlers.

Tests cover:
- Route registration (can_handle for GET/POST on receipt paths)
- List receipts: happy path, pagination, filtering, sorting
- Search receipts: happy path, missing query, short query, filters
- Get single receipt: found, not found, fallback to gauntlet_id
- Export receipt: JSON, HTML, Markdown, CSV, SARIF, PDF, unsupported format, not found
- Verify integrity: valid, invalid, not found
- Verify signature: valid, not found
- Batch verify: happy path, empty list, limit exceeded
- Batch sign: happy path, empty list, limit exceeded, already signed, not found
- Batch export: happy path, unsupported format, empty list, limit exceeded
- Get stats: happy path
- Share receipt: create link, receipt not found
- Get shared receipt: valid token, expired, access limit reached, not found
- DSAR: happy path, short user_id
- Retention status: happy path
- Send to channel: missing fields, unsupported channel, receipt not found
- Get formatted: happy path, not found, unsupported channel
- Timestamp parsing
- Error handling: internal exception in handle()
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# The receipts handler imports several decorators that need special handling
# in test context. We patch the decorators to be pass-through before importing
# the module under test.
# ---------------------------------------------------------------------------

# Patch the RBAC require_permission decorator to be a no-op in tests
_original_require_permission = None


def _passthrough_decorator(*args, **kwargs):
    """A no-op decorator that passes through the function unchanged.

    Uses functools.wraps to preserve __wrapped__ attribute.
    """
    import functools

    if len(args) == 1 and callable(args[0]):

        @functools.wraps(args[0])
        def passthrough(*a, **kw):
            return args[0](*a, **kw)

        return passthrough

    def wrapper(func):
        @functools.wraps(func)
        def inner(*a, **kw):
            return func(*a, **kw)

        return inner

    return wrapper


# Patch decorators before importing the module
with patch("aragora.rbac.decorators.require_permission", _passthrough_decorator):
    pass

# Now import - the decorators are already applied at class definition time,
# so we need to patch them at the module level before the class is defined.
# Instead, we'll work with the handler directly and mock the stores.
from aragora.server.handlers.receipts import ReceiptsHandler, create_receipts_handler
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.tenancy.record_scope import OrgScope

TEST_ORG = "test-org-001"
SCOPE = OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


@dataclass
class MockReceipt:
    """Mock receipt object returned by the store."""

    id: str = "receipt-001"
    gauntlet_id: str = "gauntlet-001"
    debate_id: str = "debate-001"
    org_id: str | None = TEST_ORG
    signature: str | None = None
    data: dict = field(
        default_factory=lambda: {
            "decision_id": "d-001",
            "verdict": "APPROVED",
            "confidence": 0.92,
            "risk_level": "LOW",
            "timestamp": "2025-01-01T00:00:00Z",
            "question": "Should we deploy?",
            "summary": "All agents agree the deployment is safe.",
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gauntlet_id": self.gauntlet_id,
            "verdict": self.data.get("verdict", "APPROVED"),
            "confidence": self.data.get("confidence", 0.92),
        }

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gauntlet_id": self.gauntlet_id,
            "debate_id": self.debate_id,
            **self.data,
        }


class MockReceiptStore:
    """Mock receipt store with all methods used by ReceiptsHandler."""

    def __init__(self, receipts: list[MockReceipt] | None = None):
        self._receipts = {r.id: r for r in (receipts or [])}
        self._gauntlet_map = {r.gauntlet_id: r for r in (receipts or [])}

    def list(self, **kwargs) -> list[MockReceipt]:
        receipts = list(self._receipts.values())

        debate_id = kwargs.get("debate_id")
        if debate_id:
            receipts = [r for r in receipts if r.debate_id == debate_id]

        limit = int(kwargs.get("limit", len(receipts)))
        offset = int(kwargs.get("offset", 0))
        return receipts[offset : offset + limit]

    def count(self, **kwargs) -> int:
        debate_id = kwargs.get("debate_id")
        if debate_id:
            return sum(1 for r in self._receipts.values() if r.debate_id == debate_id)
        return len(self._receipts)

    def get(self, receipt_id: str) -> MockReceipt | None:
        return self._receipts.get(receipt_id)

    def get_by_gauntlet(self, gauntlet_id: str) -> MockReceipt | None:
        return self._gauntlet_map.get(gauntlet_id)

    def search(self, **kwargs) -> list[MockReceipt]:
        return list(self._receipts.values())

    def search_count(self, **kwargs) -> int:
        return len(self._receipts)

    def _visible(self, receipt_id: str, org_id: str | None) -> bool:
        receipt = self._receipts.get(receipt_id)
        return receipt is not None and (org_id is None or receipt.org_id == org_id)

    def get_for_org(self, receipt_id: str, org_id: str) -> MockReceipt | None:
        return self.get(receipt_id) if self._visible(receipt_id, org_id) else None

    def get_by_gauntlet_for_org(self, gauntlet_id: str, org_id: str) -> MockReceipt | None:
        receipt = self.get_by_gauntlet(gauntlet_id)
        return receipt if receipt is not None and receipt.org_id == org_id else None

    def list_for_org(self, org_id: str, **kwargs) -> list[MockReceipt]:
        return [r for r in self.list(**kwargs) if r.org_id == org_id]

    def count_for_org(self, org_id: str, **kwargs) -> int:
        debate_id = kwargs.get("debate_id")
        return sum(
            1
            for r in self._receipts.values()
            if r.org_id == org_id and (not debate_id or r.debate_id == debate_id)
        )

    def search_for_org(self, org_id: str, **kwargs) -> list[MockReceipt]:
        return [r for r in self.search(**kwargs) if r.org_id == org_id]

    def search_count_for_org(self, org_id: str, **kwargs) -> int:
        return len(self.search_for_org(org_id, **kwargs))

    def stats_for_org(self, org_id: str) -> dict[str, Any]:
        return self.get_stats()

    def retention_status_for_org(self, org_id: str) -> dict[str, Any]:
        return self.get_retention_status()

    def get_by_user_for_org(self, org_id: str, user_id: str, limit: int = 100, offset: int = 0):
        receipts = [r for r in self._receipts.values() if r.org_id == org_id]
        return receipts, len(receipts)

    def update_signature(self, receipt_id, signature, algorithm, key_id) -> bool:
        self._receipts[receipt_id].signature = signature
        return True

    def verify_integrity(self, receipt_id: str, *, org_id: str | None = None) -> dict[str, Any]:
        if not self._visible(receipt_id, org_id):
            return {"integrity_valid": False, "error": "Receipt not found"}
        return {"integrity_valid": True, "receipt_id": receipt_id}

    def verify_signature(self, receipt_id: str, *, org_id: str | None = None):
        result = MagicMock()
        if not self._visible(receipt_id, org_id):
            result.error = "Receipt not found"
        else:
            result.error = None
        result.to_dict.return_value = {
            "receipt_id": receipt_id,
            "signature_valid": receipt_id in self._receipts,
        }
        return result

    def verify_batch(self, receipt_ids: list[str], *, org_id: str | None = None):
        results = []
        valid = 0
        invalid = 0
        for rid in receipt_ids:
            r = MagicMock()
            if self._visible(rid, org_id):
                r.to_dict.return_value = {"receipt_id": rid, "valid": True}
                valid += 1
            else:
                r.to_dict.return_value = {"receipt_id": rid, "valid": False}
                invalid += 1
            results.append(r)
        summary = {"total": len(receipt_ids), "valid": valid, "invalid": invalid}
        return results, summary

    def get_stats(self) -> dict[str, Any]:
        return {
            "total": len(self._receipts),
            "by_verdict": {"APPROVED": len(self._receipts)},
            "by_risk": {"LOW": len(self._receipts)},
        }

    def get_retention_status(self) -> dict[str, Any]:
        return {"retention_policy": "7_years", "total_stored": len(self._receipts)}

    def get_by_user(self, user_id: str, limit: int = 100, offset: int = 0):
        receipts = list(self._receipts.values())
        return receipts, len(receipts)


class MockShareStore:
    """Mock share token store."""

    def __init__(self):
        self._tokens: dict[str, dict] = {}

    def save(self, token: str, receipt_id: str, expires_at: float, max_accesses: int | None = None):
        self._tokens[token] = {
            "token": token,
            "receipt_id": receipt_id,
            "expires_at": expires_at,
            "max_accesses": max_accesses,
            "access_count": 0,
        }

    def get_by_token(self, token: str) -> dict | None:
        return self._tokens.get(token)

    def increment_access(self, token: str):
        if token in self._tokens:
            self._tokens[token]["access_count"] += 1


def _make_receipts(count: int = 3) -> list[MockReceipt]:
    """Create a list of mock receipts."""
    return [
        MockReceipt(
            id=f"receipt-{i:03d}",
            gauntlet_id=f"gauntlet-{i:03d}",
            debate_id=f"debate-{i:03d}",
        )
        for i in range(1, count + 1)
    ]


@pytest.fixture
def mock_store():
    """Create a mock receipt store with sample receipts."""
    return MockReceiptStore(_make_receipts(3))


@pytest.fixture
def mock_share_store():
    """Create a mock share store."""
    return MockShareStore()


@pytest.fixture
def handler(mock_store, mock_share_store):
    """Create ReceiptsHandler with mocked stores."""
    ctx: dict[str, Any] = {}
    h = ReceiptsHandler(ctx)
    h._store = mock_store
    h._share_store = mock_share_store
    return h


def _parse_body(result: HandlerResult) -> dict[str, Any]:
    """Parse JSON body from HandlerResult."""
    return json.loads(result.body)


# ===========================================================================
# Test Routing (can_handle)
# ===========================================================================


class TestReceiptsRouting:
    """Tests for ReceiptsHandler.can_handle."""

    def test_can_handle_list_get(self, handler):
        assert handler.can_handle("/api/v2/receipts", "GET") is True

    def test_can_handle_receipt_get(self, handler):
        assert handler.can_handle("/api/v2/receipts/receipt-001", "GET") is True

    def test_can_handle_verify_post(self, handler):
        assert handler.can_handle("/api/v2/receipts/receipt-001/verify", "POST") is True

    def test_can_handle_search_get(self, handler):
        assert handler.can_handle("/api/v2/receipts/search", "GET") is True

    def test_cannot_handle_put(self, handler):
        assert handler.can_handle("/api/v2/receipts", "PUT") is False

    def test_cannot_handle_delete(self, handler):
        assert handler.can_handle("/api/v2/receipts/receipt-001", "DELETE") is False

    def test_cannot_handle_other_path(self, handler):
        assert handler.can_handle("/api/v2/debates", "GET") is False


# ===========================================================================
# Test List Receipts
# ===========================================================================


class TestListReceipts:
    """Tests for the list receipts endpoint."""

    @pytest.mark.asyncio
    async def test_list_receipts_success(self, handler):
        result = await handler._list_receipts({}, scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert "receipts" in data
        assert "pagination" in data
        assert data["pagination"]["total"] == 3

    @pytest.mark.asyncio
    async def test_list_receipts_with_pagination(self, handler):
        result = await handler._list_receipts({"limit": "10", "offset": "5"}, scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["pagination"]["limit"] == 10
        assert data["pagination"]["offset"] == 5

    @pytest.mark.asyncio
    async def test_list_receipts_with_filters(self, handler):
        result = await handler._list_receipts(
            {
                "verdict": "APPROVED",
                "risk_level": "LOW",
                "signed_only": "true",
                "sort_by": "confidence",
                "order": "asc",
            },
            scope=SCOPE,
        )
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["filters"]["verdict"] == "APPROVED"
        assert data["filters"]["risk_level"] == "LOW"
        assert data["filters"]["signed_only"] is True

    @pytest.mark.asyncio
    async def test_list_receipts_with_date_range(self, handler):
        result = await handler._list_receipts(
            {
                "date_from": "2025-01-01T00:00:00Z",
                "date_to": "2025-12-31T23:59:59Z",
            },
            scope=SCOPE,
        )
        assert result.status_code == 200
        data = _parse_body(result)
        # date_from/date_to are converted to floats via _parse_timestamp
        assert data["filters"]["date_from"] is not None
        assert data["filters"]["date_to"] is not None

    @pytest.mark.asyncio
    async def test_list_receipts_with_debate_id_filter(self, handler):
        result = await handler._list_receipts({"debate_id": "debate-001"}, scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["filters"]["debate_id"] == "debate-001"
        assert data["pagination"]["total"] == 1
        assert len(data["receipts"]) == 1

    @pytest.mark.asyncio
    async def test_list_receipts_with_nonexistent_debate_id(self, handler):
        result = await handler._list_receipts({"debate_id": "debate-nonexistent"}, scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["filters"]["debate_id"] == "debate-nonexistent"
        assert data["pagination"]["total"] == 0
        assert len(data["receipts"]) == 0
        assert data["pagination"]["has_more"] is False

    @pytest.mark.asyncio
    async def test_list_receipts_no_filter_returns_all(self, handler):
        """No debate_id filter returns all receipts (backwards compatible)."""
        result = await handler._list_receipts({}, scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["filters"]["debate_id"] is None
        assert data["pagination"]["total"] == 3
        assert len(data["receipts"]) == 3


# ===========================================================================
# Test Search Receipts
# ===========================================================================


class TestSearchReceipts:
    """Tests for the search receipts endpoint."""

    @pytest.mark.asyncio
    async def test_search_receipts_success(self, handler):
        result = await handler._search_receipts({"q": "deployment"}, scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert "receipts" in data
        assert data["query"] == "deployment"

    @pytest.mark.asyncio
    async def test_search_receipts_missing_query(self, handler):
        result = await handler._search_receipts({}, scope=SCOPE)
        assert result.status_code == 400
        data = _parse_body(result)
        assert "required" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_search_receipts_short_query(self, handler):
        result = await handler._search_receipts({"q": "ab"}, scope=SCOPE)
        assert result.status_code == 400
        data = _parse_body(result)
        assert "3 characters" in data["error"]

    @pytest.mark.asyncio
    async def test_search_with_filters(self, handler):
        result = await handler._search_receipts(
            {
                "q": "deploy",
                "verdict": "APPROVED",
                "risk_level": "HIGH",
            },
            scope=SCOPE,
        )
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["filters"]["verdict"] == "APPROVED"
        assert data["filters"]["risk_level"] == "HIGH"


# ===========================================================================
# Test Get Receipt
# ===========================================================================


class TestGetReceipt:
    """Tests for the get receipt endpoint."""

    @pytest.mark.asyncio
    async def test_get_receipt_by_id(self, handler):
        result = await handler._get_receipt("receipt-001", scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["id"] == "receipt-001"

    @pytest.mark.asyncio
    async def test_get_receipt_by_gauntlet_id(self, handler):
        result = await handler._get_receipt("gauntlet-002", scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["gauntlet_id"] == "gauntlet-002"

    @pytest.mark.asyncio
    async def test_get_receipt_not_found(self, handler):
        result = await handler._get_receipt("nonexistent", scope=SCOPE)
        assert result.status_code == 404


# ===========================================================================
# Test Verify Integrity
# ===========================================================================


class TestVerifyIntegrity:
    """Tests for receipt integrity verification."""

    @pytest.mark.asyncio
    async def test_verify_integrity_valid(self, handler):
        result = await handler._verify_integrity("receipt-001", scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["integrity_valid"] is True

    @pytest.mark.asyncio
    async def test_verify_integrity_not_found(self, handler):
        result = await handler._verify_integrity("nonexistent", scope=SCOPE)
        assert result.status_code == 404


# ===========================================================================
# Test Verify Signature
# ===========================================================================


class TestVerifySignature:
    """Tests for receipt signature verification."""

    @pytest.mark.asyncio
    async def test_verify_signature_valid(self, handler):
        result = await handler._verify_signature("receipt-001", scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["signature_valid"] is True

    @pytest.mark.asyncio
    async def test_verify_signature_not_found(self, handler):
        result = await handler._verify_signature("nonexistent", scope=SCOPE)
        assert result.status_code == 404


# ===========================================================================
# Test Batch Verify
# ===========================================================================


class TestBatchVerify:
    """Tests for batch signature verification."""

    @pytest.mark.asyncio
    async def test_batch_verify_success(self, handler):
        result = await handler._verify_batch(
            {"receipt_ids": ["receipt-001", "receipt-002"]}, scope=SCOPE
        )
        assert result.status_code == 200
        data = _parse_body(result)
        assert len(data["results"]) == 2
        assert data["summary"]["total"] == 2
        assert data["summary"]["valid"] == 2

    @pytest.mark.asyncio
    async def test_batch_verify_empty_list(self, handler):
        result = await handler._verify_batch({"receipt_ids": []}, scope=SCOPE)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_verify_exceeds_limit(self, handler):
        ids = [f"r-{i}" for i in range(101)]
        result = await handler._verify_batch({"receipt_ids": ids}, scope=SCOPE)
        assert result.status_code == 400
        data = _parse_body(result)
        assert "100" in data["error"]

    @pytest.mark.asyncio
    async def test_batch_verify_missing_receipt_ids(self, handler):
        result = await handler._verify_batch({}, scope=SCOPE)
        assert result.status_code == 400


# ===========================================================================
# Test Get Stats
# ===========================================================================


class TestGetStats:
    """Tests for receipt statistics endpoint."""

    @pytest.mark.asyncio
    async def test_get_stats_success(self, handler):
        result = await handler._get_stats(scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert "stats" in data
        assert "generated_at" in data
        assert data["stats"]["total"] == 3


# ===========================================================================
# Test Async Safety
# ===========================================================================


class TestAsyncSafety:
    """Sync-backed stores should not block the event loop in async endpoints."""

    @pytest.mark.asyncio
    async def test_list_receipts_offloads_sync_store_calls(self):
        class BlockingReceiptStore(MockReceiptStore):
            def list(self, **kwargs) -> list[MockReceipt]:
                time.sleep(0.15)
                return super().list(**kwargs)

            def count(self, **kwargs) -> int:
                time.sleep(0.15)
                return super().count(**kwargs)

        handler = ReceiptsHandler({})
        handler._store = BlockingReceiptStore(_make_receipts(3))

        list_task = asyncio.create_task(handler._list_receipts({}, scope=SCOPE))
        heartbeat_task = asyncio.create_task(asyncio.sleep(0.02, result=True))

        assert await asyncio.wait_for(heartbeat_task, timeout=0.05) is True

        result = await list_task
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_stats_offloads_sync_store_calls(self):
        class BlockingReceiptStore(MockReceiptStore):
            def get_stats(self) -> dict[str, Any]:
                time.sleep(0.15)
                return super().get_stats()

        handler = ReceiptsHandler({})
        handler._store = BlockingReceiptStore(_make_receipts(3))

        stats_task = asyncio.create_task(handler._get_stats(scope=SCOPE))
        heartbeat_task = asyncio.create_task(asyncio.sleep(0.02, result=True))

        assert await asyncio.wait_for(heartbeat_task, timeout=0.05) is True

        result = await stats_task
        assert result.status_code == 200


# ===========================================================================
# Test Export Receipt
# ===========================================================================


class TestExportReceipt:
    """Tests for receipt export in various formats."""

    @pytest.mark.asyncio
    async def test_export_receipt_not_found(self, handler):
        result = await handler._export_receipt("nonexistent", {"format": "json"}, scope=SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_export_json(self, handler):
        mock_dr = MagicMock()
        mock_dr.to_json.return_value = '{"test": "data"}'

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._export_receipt("receipt-001", {"format": "json"}, scope=SCOPE)
            assert result.status_code == 200
            assert result.content_type.startswith("application/json")

    @pytest.mark.asyncio
    async def test_export_html(self, handler):
        mock_dr = MagicMock()
        mock_dr.to_html.return_value = "<html><body>Receipt</body></html>"

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._export_receipt("receipt-001", {"format": "html"}, scope=SCOPE)
            assert result.status_code == 200
            assert result.content_type.startswith("text/html")

    @pytest.mark.asyncio
    async def test_export_markdown(self, handler):
        mock_dr = MagicMock()
        mock_dr.to_markdown.return_value = "# Receipt\nApproved"

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._export_receipt("receipt-001", {"format": "md"}, scope=SCOPE)
            assert result.status_code == 200
            assert result.content_type.startswith("text/markdown")

    @pytest.mark.asyncio
    async def test_export_csv(self, handler):
        mock_dr = MagicMock()
        mock_dr.to_csv.return_value = "id,verdict\nreceipt-001,APPROVED"

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._export_receipt("receipt-001", {"format": "csv"}, scope=SCOPE)
            assert result.status_code == 200
            assert result.content_type.startswith("text/csv")
            assert "Content-Disposition" in result.headers

    @pytest.mark.asyncio
    async def test_export_download_mode(self, handler):
        """Download flag adds Content-Disposition header for text formats."""
        mock_dr = MagicMock()
        mock_dr.to_markdown.return_value = "# Receipt\nApproved"

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._export_receipt(
                "receipt-001", {"format": "md", "download": "true"}, scope=SCOPE
            )
            assert result.status_code == 200
            assert "Content-Disposition" in result.headers
            assert "receipt-001.md" in result.headers["Content-Disposition"]

    @pytest.mark.asyncio
    async def test_export_pdf_success(self, handler):
        mock_dr = MagicMock()
        mock_dr.to_pdf.return_value = b"%PDF-1.4 fake pdf bytes"

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._export_receipt("receipt-001", {"format": "pdf"}, scope=SCOPE)
            assert result.status_code == 200
            assert result.content_type == "application/pdf"

    @pytest.mark.asyncio
    async def test_export_pdf_missing_weasyprint(self, handler):
        """When WeasyPrint is unavailable, handler gracefully degrades to HTML fallback."""
        mock_dr = MagicMock()
        mock_dr.to_pdf.side_effect = ImportError("No module named 'weasyprint'")
        mock_dr.to_html.return_value = "<div>Receipt Content</div>"

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._export_receipt("receipt-001", {"format": "pdf"}, scope=SCOPE)
            # Handler gracefully degrades to HTML with print instructions
            assert result.status_code == 200
            assert result.content_type == "text/html"
            assert result.headers.get("X-PDF-Fallback") == "true"
            body = result.body.decode("utf-8")
            assert "PDF export is unavailable" in body
            assert "Print" in body  # Instructions to use browser print

    @pytest.mark.asyncio
    async def test_export_sarif(self, handler):
        mock_dr = MagicMock()
        mock_export_fn = MagicMock(return_value='{"runs": []}')
        mock_format_cls = MagicMock()
        mock_format_cls.SARIF = "sarif"

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            with patch.dict(
                "sys.modules",
                {
                    "aragora.gauntlet.api.export": MagicMock(
                        export_receipt=mock_export_fn,
                        ReceiptExportFormat=mock_format_cls,
                    ),
                },
            ):
                result = await handler._export_receipt(
                    "receipt-001", {"format": "sarif"}, scope=SCOPE
                )
                assert result.status_code == 200
                assert result.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_export_unsupported_format(self, handler):
        mock_dr = MagicMock()

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._export_receipt("receipt-001", {"format": "xml"}, scope=SCOPE)
            assert result.status_code == 400
            data = _parse_body(result)
            assert "unsupported" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_export_failure(self, handler):
        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict",
            side_effect=OSError("Serialization error"),
        ):
            result = await handler._export_receipt("receipt-001", {"format": "json"}, scope=SCOPE)
            assert result.status_code == 500


# ===========================================================================
# Test Batch Sign
# ===========================================================================


class TestBatchSign:
    """Tests for batch receipt signing."""

    @pytest.mark.asyncio
    async def test_batch_sign_empty_list(self, handler):
        result = await handler._sign_batch({"receipt_ids": []}, scope=SCOPE)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_sign_exceeds_limit(self, handler):
        ids = [f"r-{i}" for i in range(101)]
        result = await handler._sign_batch({"receipt_ids": ids}, scope=SCOPE)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_sign_missing_signing_module(self, handler):
        with patch.dict("sys.modules", {"aragora.storage.receipt_signing": None}):
            result = await handler._sign_batch(
                {
                    "receipt_ids": ["receipt-001"],
                    "algorithm": "hmac-sha256",
                },
                scope=SCOPE,
            )
            assert result.status_code == 501

    @pytest.mark.asyncio
    async def test_batch_sign_success(self, handler):
        mock_signer = MagicMock()
        mock_signer.sign.return_value = MagicMock(
            signature="c2lnbmF0dXJl",
            signature_metadata=MagicMock(algorithm="HMAC-SHA256", key_id="key-1"),
        )

        mock_backend = MagicMock()
        mock_hmac_cls = MagicMock()
        mock_hmac_cls.from_env.return_value = mock_backend
        mock_signer_cls = MagicMock(return_value=mock_signer)

        signing_mod = MagicMock()
        signing_mod.HMACSigner = mock_hmac_cls
        signing_mod.RSASigner = MagicMock()
        signing_mod.Ed25519Signer = MagicMock()
        signing_mod.ReceiptSigner = mock_signer_cls
        signing_mod.SigningBackend = MagicMock()

        with patch.dict("sys.modules", {"aragora.storage.receipt_signing": signing_mod}):
            result = await handler._sign_batch(
                {
                    "receipt_ids": ["receipt-001"],
                    "algorithm": "hmac-sha256",
                },
                scope=SCOPE,
            )
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["summary"]["signed"] == 1
            assert handler._store.get("receipt-001").signature == "c2lnbmF0dXJl"


# ===========================================================================
# Test Batch Export
# ===========================================================================


class TestBatchExport:
    """Tests for batch receipt export to ZIP."""

    @pytest.mark.asyncio
    async def test_batch_export_empty_list(self, handler):
        result = await handler._batch_export({"receipt_ids": []}, scope=SCOPE)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_export_exceeds_limit(self, handler):
        ids = [f"r-{i}" for i in range(101)]
        result = await handler._batch_export({"receipt_ids": ids}, scope=SCOPE)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_export_unsupported_format(self, handler):
        result = await handler._batch_export(
            {
                "receipt_ids": ["receipt-001"],
                "format": "xml",
            },
            scope=SCOPE,
        )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_export_json_success(self, handler):
        mock_dr = MagicMock()
        mock_dr.to_json.return_value = '{"test": "data"}'

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._batch_export(
                {
                    "receipt_ids": ["receipt-001", "receipt-002"],
                    "format": "json",
                },
                scope=SCOPE,
            )
            assert result.status_code == 200
            assert result.content_type == "application/zip"

            # Verify ZIP contents
            zf = zipfile.ZipFile(io.BytesIO(result.body))
            names = zf.namelist()
            assert "manifest.json" in names
            assert "receipt-receipt-001.json" in names
            assert "receipt-receipt-002.json" in names

            # Verify manifest
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["exported"] == 2
            assert manifest["format"] == "json"

    @pytest.mark.asyncio
    async def test_batch_export_with_not_found_receipts(self, handler):
        mock_dr = MagicMock()
        mock_dr.to_json.return_value = '{"test": "data"}'

        with patch(
            "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
        ):
            result = await handler._batch_export(
                {
                    "receipt_ids": ["receipt-001", "nonexistent"],
                    "format": "json",
                },
                scope=SCOPE,
            )
            assert result.status_code == 200

            zf = zipfile.ZipFile(io.BytesIO(result.body))
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["exported"] == 1
            assert "nonexistent" in manifest["failed"]


# ===========================================================================
# Test Share Receipt
# ===========================================================================


class TestShareReceipt:
    """Tests for creating shareable receipt links."""

    @pytest.mark.asyncio
    async def test_share_receipt_success(self, handler):
        with patch(
            "aragora.integrations.receipt_webhooks.ReceiptWebhookNotifier",
            side_effect=ImportError("not available"),
        ):
            result = await handler._share_receipt("receipt-001", {}, scope=SCOPE)
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["success"] is True
            assert data["receipt_id"] == "receipt-001"
            assert "share_url" in data
            assert "token" in data
            assert "expires_at" in data

    @pytest.mark.asyncio
    async def test_share_receipt_not_found(self, handler):
        result = await handler._share_receipt("nonexistent", {}, scope=SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_share_receipt_with_options(self, handler):
        with patch(
            "aragora.integrations.receipt_webhooks.ReceiptWebhookNotifier",
            side_effect=ImportError("not available"),
        ):
            result = await handler._share_receipt(
                "receipt-001",
                {
                    "expires_in_hours": "48",
                    "max_accesses": 5,
                },
                scope=SCOPE,
            )
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["max_accesses"] == 5


# ===========================================================================
# Test Get Shared Receipt
# ===========================================================================


class TestGetSharedReceipt:
    """Tests for accessing receipts via share tokens."""

    @pytest.mark.asyncio
    async def test_get_shared_receipt_success(self, handler, mock_share_store):
        # Create a valid share token
        future_ts = datetime.now(timezone.utc).timestamp() + 3600
        mock_share_store.save(
            token="test-token",
            receipt_id="receipt-001",
            expires_at=future_ts,
        )

        result = await handler._get_shared_receipt("test-token")
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["shared"] is True
        assert data["receipt"]["id"] == "receipt-001"

    @pytest.mark.asyncio
    async def test_get_shared_receipt_not_found(self, handler):
        result = await handler._get_shared_receipt("bad-token")
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_shared_receipt_expired(self, handler, mock_share_store):
        past_ts = datetime.now(timezone.utc).timestamp() - 3600
        mock_share_store.save(
            token="expired-token",
            receipt_id="receipt-001",
            expires_at=past_ts,
        )

        result = await handler._get_shared_receipt("expired-token")
        assert result.status_code == 410

    @pytest.mark.asyncio
    async def test_get_shared_receipt_access_limit_reached(self, handler, mock_share_store):
        future_ts = datetime.now(timezone.utc).timestamp() + 3600
        mock_share_store.save(
            token="limited-token",
            receipt_id="receipt-001",
            expires_at=future_ts,
            max_accesses=2,
        )
        # Exhaust the access limit
        mock_share_store._tokens["limited-token"]["access_count"] = 2

        result = await handler._get_shared_receipt("limited-token")
        assert result.status_code == 410


# ===========================================================================
# Test DSAR and Retention
# ===========================================================================


class TestDSARAndRetention:
    """Tests for GDPR DSAR and retention status endpoints."""

    @pytest.mark.asyncio
    async def test_dsar_success(self, handler):
        result = await handler._get_dsar("user-abc", {}, scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["dsar_request"]["user_id"] == "user-abc"
        assert data["dsar_request"]["gdpr_article"] == "Article 15 - Right of access"
        assert "receipts" in data

    @pytest.mark.asyncio
    async def test_dsar_short_user_id(self, handler):
        result = await handler._get_dsar("ab", {}, scope=SCOPE)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_retention_status(self, handler):
        result = await handler._get_retention_status(scope=SCOPE)
        assert result.status_code == 200
        data = _parse_body(result)
        assert data["retention_policy"] == "7_years"


# ===========================================================================
# Test Send to Channel
# ===========================================================================


class TestSendToChannel:
    """Tests for sending receipts to channels."""

    @pytest.mark.asyncio
    async def test_send_missing_channel_type(self, handler):
        result = await handler._send_to_channel("receipt-001", {"channel_id": "C123"}, scope=SCOPE)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_send_missing_channel_id(self, handler):
        result = await handler._send_to_channel(
            "receipt-001", {"channel_type": "slack"}, scope=SCOPE
        )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_send_receipt_not_found(self, handler):
        result = await handler._send_to_channel(
            "nonexistent",
            {
                "channel_type": "slack",
                "channel_id": "C123",
            },
            scope=SCOPE,
        )
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_send_unsupported_channel(self, handler):
        mock_dr = MagicMock()
        mock_format_fn = MagicMock(return_value={"blocks": []})

        with patch("aragora.channels.formatter.format_receipt_for_channel", mock_format_fn):
            with patch(
                "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
            ):
                result = await handler._send_to_channel(
                    "receipt-001",
                    {
                        "channel_type": "fax",
                        "channel_id": "123",
                    },
                    scope=SCOPE,
                )
                assert result.status_code == 400


# ===========================================================================
# Test Get Formatted
# ===========================================================================


class TestGetFormatted:
    """Tests for getting formatted receipt for a channel."""

    @pytest.mark.asyncio
    async def test_get_formatted_not_found(self, handler):
        result = await handler._get_formatted("nonexistent", "slack", {}, scope=SCOPE)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_formatted_success(self, handler):
        mock_dr = MagicMock()
        mock_format_fn = MagicMock(return_value={"blocks": [{"type": "section"}]})

        with patch("aragora.channels.formatter.format_receipt_for_channel", mock_format_fn):
            with patch(
                "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
            ):
                result = await handler._get_formatted("receipt-001", "slack", {}, scope=SCOPE)
                assert result.status_code == 200
                data = _parse_body(result)
                assert data["receipt_id"] == "receipt-001"
                assert data["channel_type"] == "slack"
                assert "formatted" in data

    @pytest.mark.asyncio
    async def test_get_formatted_value_error(self, handler):
        mock_dr = MagicMock()
        mock_format_fn = MagicMock(side_effect=ValueError("Unsupported channel: fax"))

        with patch("aragora.channels.formatter.format_receipt_for_channel", mock_format_fn):
            with patch(
                "aragora.export.decision_receipt.DecisionReceipt.from_dict", return_value=mock_dr
            ):
                result = await handler._get_formatted("receipt-001", "fax", {}, scope=SCOPE)
                assert result.status_code == 400


# ===========================================================================
# Test Timestamp Parsing
# ===========================================================================


class TestTimestampParsing:
    """Tests for the _parse_timestamp utility."""

    def test_parse_none(self, handler):
        assert handler._parse_timestamp(None) is None

    def test_parse_unix_timestamp(self, handler):
        result = handler._parse_timestamp("1704067200.0")
        assert result == 1704067200.0

    def test_parse_iso_date(self, handler):
        result = handler._parse_timestamp("2025-01-01T00:00:00Z")
        assert result is not None
        assert isinstance(result, float)

    def test_parse_invalid_value(self, handler):
        assert handler._parse_timestamp("not-a-date") is None


# ===========================================================================
# Test Handle() Top-Level Routing
# ===========================================================================


class TestHandleRouting:
    """Tests for the top-level handle() method routing."""

    @pytest.mark.asyncio
    async def test_handle_not_found(self, handler):
        result = await handler.handle("PATCH", "/api/v2/receipts", {}, {}, {})
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_handle_trailing_slash_list_path(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/", {}, {}, {})
        assert result.status_code == 200
        assert "receipts" in _parse_body(result)

    @pytest.mark.asyncio
    async def test_handle_internal_error(self, handler):
        """Internal errors should be caught and returned as 500."""
        handler._store = None  # Force lazy init
        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            side_effect=RuntimeError("DB connection failed"),
        ):
            result = await handler.handle("GET", "/api/v2/receipts/stats", {}, {}, {})
            assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_handle_routes_to_stats(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/stats", {}, {}, {})
        assert result.status_code == 200
        data = _parse_body(result)
        assert "stats" in data

    @pytest.mark.asyncio
    async def test_handle_routes_to_search(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/search", {}, {"q": "deploy"}, {})
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_routes_to_list(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts", {}, {}, {})
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_routes_to_get_receipt(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/receipt-001", {}, {}, {})
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_routes_to_verify(self, handler):
        result = await handler.handle("POST", "/api/v2/receipts/receipt-001/verify", {}, {}, {})
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_routes_to_retention_status(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/retention-status", {}, {}, {})
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_routes_to_dsar(self, handler):
        result = await handler.handle("GET", "/api/v2/receipts/dsar/user-test123", {}, {}, {})
        assert result.status_code == 200


# ===========================================================================
# Test Factory Function
# ===========================================================================


class TestFactory:
    """Tests for the handler factory function."""

    def test_create_receipts_handler(self):
        ctx: dict[str, Any] = {}
        h = create_receipts_handler(ctx)
        assert isinstance(h, ReceiptsHandler)
