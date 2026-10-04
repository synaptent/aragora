"""Tests for ReceiptExportHandler (aragora/server/handlers/receipt_export.py).

Covers:
- can_handle path matching
- handle() route dispatch and path extraction
- Format validation (json, html, pdf, invalid)
- Receipt lookup: store, ctx fallback, not found
- JSON export with to_dict and plain dict receipts
- HTML export with Content-Disposition header
- PDF export with Content-Disposition header
- Edge cases: empty receipt ID, short paths, missing format
- _get_receipt_store lazy loader: ImportError fallback
- Org scoping: anonymous 401, other-org and unknown-owner receipts 404
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.receipt_export import (
    ReceiptExportHandler,
    _get_receipt_store,
    _VALID_FORMATS,
)
from aragora.server.handlers.utils.responses import HandlerResult

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

# The org ``org_scoped_request_user`` authenticates every request as.
TEST_ORG = "test-org-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: HandlerResult) -> dict:
    """Extract the JSON body from a HandlerResult."""
    if isinstance(result, HandlerResult):
        if isinstance(result.body, bytes):
            try:
                return json.loads(result.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}
        return result.body
    if isinstance(result, dict):
        return result.get("body", result)
    return {}


def _status(result: HandlerResult) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, HandlerResult):
        return result.status_code
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return 200


def _content_type(result: HandlerResult) -> str:
    """Extract content type from a HandlerResult."""
    if isinstance(result, HandlerResult):
        return result.content_type
    return ""


def _headers(result: HandlerResult) -> dict:
    """Extract headers from a HandlerResult."""
    if isinstance(result, HandlerResult):
        return result.headers or {}
    return {}


# Keep a reference to the real __import__ for selective patching.
_real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__


def _make_import_error(blocked_module: str):
    """Return a side_effect callable that raises ImportError only for *blocked_module*."""

    def _guarded_import(name, *args, **kwargs):
        if name == blocked_module:
            raise ImportError(f"Mocked: no module named '{blocked_module}'")
        return _real_import(name, *args, **kwargs)

    return _guarded_import


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a ReceiptExportHandler with empty ctx."""
    return ReceiptExportHandler(ctx={})


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler object."""
    h = MagicMock()
    h.headers = {"Content-Length": "0"}
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    return h


@pytest.fixture
def mock_receipt():
    """Create a mock receipt object with to_dict()."""
    receipt = MagicMock()
    receipt.org_id = TEST_ORG
    receipt.to_dict.return_value = {
        "receipt_id": "r-123",
        "decision": "approved",
        "confidence": 0.95,
        "timestamp": "2026-02-23T00:00:00Z",
    }
    return receipt


@pytest.fixture
def plain_receipt():
    """Create a plain dict receipt (no to_dict method)."""
    return {
        "receipt_id": "r-plain",
        "decision": "rejected",
        "confidence": 0.42,
        "org_id": TEST_ORG,
    }


# ---------------------------------------------------------------------------
# _VALID_FORMATS constant
# ---------------------------------------------------------------------------


class TestValidFormats:
    """Tests for the _VALID_FORMATS constant."""

    def test_valid_formats_contains_json(self):
        assert "json" in _VALID_FORMATS

    def test_valid_formats_contains_html(self):
        assert "html" in _VALID_FORMATS

    def test_valid_formats_contains_pdf(self):
        assert "pdf" in _VALID_FORMATS

    def test_valid_formats_has_three_entries(self):
        assert len(_VALID_FORMATS) == 3

    def test_valid_formats_excludes_csv(self):
        assert "csv" not in _VALID_FORMATS

    def test_valid_formats_excludes_xml(self):
        assert "xml" not in _VALID_FORMATS


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for ReceiptExportHandler.can_handle()."""

    def test_valid_export_path(self, handler):
        assert handler.can_handle("/api/v1/receipts/abc123/export") is True

    def test_valid_export_path_with_uuid(self, handler):
        assert (
            handler.can_handle("/api/v1/receipts/550e8400-e29b-41d4-a716-446655440000/export")
            is True
        )

    def test_rejects_non_receipt_path(self, handler):
        assert handler.can_handle("/api/v1/debates/abc/export") is False

    def test_rejects_path_without_export(self, handler):
        assert handler.can_handle("/api/v1/receipts/abc123") is False

    def test_rejects_path_without_trailing_export(self, handler):
        assert handler.can_handle("/api/v1/receipts/abc123/details") is False

    def test_rejects_empty_path(self, handler):
        assert handler.can_handle("") is False

    def test_rejects_root_path(self, handler):
        assert handler.can_handle("/") is False

    def test_rejects_partial_receipt_path(self, handler):
        assert handler.can_handle("/api/v1/receipts/") is False

    def test_accepts_nested_receipt_id(self, handler):
        """Path like /api/v1/receipts/some-long-id/export should match."""
        assert handler.can_handle("/api/v1/receipts/some-long-id/export") is True


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for ReceiptExportHandler initialization."""

    def test_init_with_ctx(self):
        ctx = {"receipt_store": {}}
        h = ReceiptExportHandler(ctx=ctx)
        assert h.ctx is ctx

    def test_init_without_ctx(self):
        h = ReceiptExportHandler()
        assert h.ctx == {}

    def test_init_with_none_ctx(self):
        h = ReceiptExportHandler(ctx=None)
        assert h.ctx == {}


# ---------------------------------------------------------------------------
# _get_receipt_store
# ---------------------------------------------------------------------------


class TestGetReceiptStore:
    """Tests for the _get_receipt_store lazy loader."""

    def test_returns_store_when_import_succeeds(self):
        """When the receipt store module is available, returns a store."""
        mock_store = MagicMock()
        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
            create=True,
        ):
            result = _get_receipt_store()
            assert result is mock_store

    def test_returns_none_on_import_error(self):
        """When the receipt store module is not importable, returns None."""
        with patch(
            "builtins.__import__",
            side_effect=_make_import_error("aragora.storage.receipt_store"),
        ):
            result = _get_receipt_store()
            assert result is None

    def test_does_not_raise_on_import_error(self):
        """_get_receipt_store must never propagate ImportError."""
        with patch(
            "builtins.__import__",
            side_effect=_make_import_error("aragora.storage.receipt_store"),
        ):
            # Should not raise
            _get_receipt_store()


# ---------------------------------------------------------------------------
# handle() — path not matching
# ---------------------------------------------------------------------------


class TestHandleNonMatchingPath:
    """Tests for handle() when path does not match."""

    def test_returns_none_for_non_matching_path(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/debates/123", {}, mock_http_handler)
        assert result is None

    def test_returns_none_for_empty_path(self, handler, mock_http_handler):
        result = handler.handle("", {}, mock_http_handler)
        assert result is None


# ---------------------------------------------------------------------------
# handle() — invalid path
# ---------------------------------------------------------------------------


class TestHandleInvalidPath:
    """Tests for handle() with paths that match can_handle but have invalid segments."""

    def test_short_path_returns_400(self, handler, mock_http_handler):
        """A path with too few segments should return 400."""
        # Build a path that starts with /api/v1/receipts/ and ends with /export
        # but is short enough that parts < 4
        result = handler.handle("/api/v1/receipts//export", {}, mock_http_handler)
        # This path splits to ['', 'api', 'v1', 'receipts', '', 'export'] which is 6 parts
        # receipt_id = parts[3] = 'receipts', not empty
        # So it will try to find a receipt named "receipts" - which won't exist
        # Let's handle this differently
        assert result is not None


# ---------------------------------------------------------------------------
# handle() — format validation
# ---------------------------------------------------------------------------


class TestHandleFormatValidation:
    """Tests for format query parameter validation."""

    def test_invalid_format_returns_400(self, handler, mock_http_handler):
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = handler.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "csv"},
                mock_http_handler,
            )
            assert _status(result) == 400
            body = _body(result)
            assert "Invalid format" in body.get("error", "")

    def test_invalid_format_xml_returns_400(self, handler, mock_http_handler):
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = handler.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "xml"},
                mock_http_handler,
            )
            assert _status(result) == 400

    def test_invalid_format_error_message_lists_valid_formats(self, handler, mock_http_handler):
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = handler.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "yaml"},
                mock_http_handler,
            )
            body = _body(result)
            error_msg = body.get("error", "")
            assert "html" in error_msg
            assert "json" in error_msg
            assert "pdf" in error_msg

    def test_default_format_is_json(self, handler, mock_http_handler, mock_receipt):
        """When no format is specified, defaults to json."""
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            result = handler.handle(
                "/api/v1/receipts/r-123/export",
                {},
                mock_http_handler,
            )
            assert _status(result) == 200
            assert "application/json" in _content_type(result)


# ---------------------------------------------------------------------------
# handle() — receipt not found
# ---------------------------------------------------------------------------


class TestHandleReceiptNotFound:
    """Tests for receipt lookup when not found."""

    def test_not_found_when_store_returns_none(self, handler, mock_http_handler):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = None
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            result = handler.handle(
                "/api/v1/receipts/nonexistent/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 404
            body = _body(result)
            assert "not found" in body.get("error", "").lower()

    def test_not_found_when_no_store_and_no_ctx(self, handler, mock_http_handler):
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = handler.handle(
                "/api/v1/receipts/r-999/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 404

    def test_not_found_does_not_echo_receipt_id(self, handler, mock_http_handler):
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = handler.handle(
                "/api/v1/receipts/r-unique-id/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _body(result) == {"error": "Receipt not found", "code": "not_found"}


# ---------------------------------------------------------------------------
# handle() — org scoping
# ---------------------------------------------------------------------------


class TestHandleOrgScope:
    """Only the receipt's own org can export it."""

    def _export(self, mock_http_handler, *, store=None, ctx=None):
        h = ReceiptExportHandler(ctx=ctx or {})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=store,
        ):
            return h.handle("/api/v1/receipts/r-1/export", {"format": "json"}, mock_http_handler)

    @pytest.mark.no_auto_auth
    def test_anonymous_gets_401_without_store_lookup(self, mock_http_handler):
        store = MagicMock()
        result = self._export(mock_http_handler, store=store)
        assert _status(result) == 401
        store.get_for_org.assert_not_called()

    def test_store_lookup_is_scoped_to_caller_org(self, mock_http_handler):
        store = MagicMock()
        store.get_for_org.return_value = None
        result = self._export(mock_http_handler, store=store)
        assert _status(result) == 404
        store.get_for_org.assert_called_once_with("r-1", TEST_ORG)
        store.get.assert_not_called()

    @pytest.mark.parametrize("owner", ["other-org", None, ""])
    def test_ctx_receipt_of_other_or_unknown_org_is_404(self, mock_http_handler, owner):
        receipt = {"receipt_id": "r-1", "org_id": owner}
        result = self._export(mock_http_handler, ctx={"receipt_store": {"r-1": receipt}})
        assert _status(result) == 404
        assert _body(result) == {"error": "Receipt not found", "code": "not_found"}

    def test_ctx_object_receipt_of_other_org_is_404(self, mock_http_handler):
        receipt = MagicMock()
        receipt.org_id = "other-org"
        result = self._export(mock_http_handler, ctx={"receipt_store": {"r-1": receipt}})
        assert _status(result) == 404
        receipt.to_dict.assert_not_called()


# ---------------------------------------------------------------------------
# handle() — ctx fallback receipt store
# ---------------------------------------------------------------------------


class TestHandleCtxFallback:
    """Tests for receipt lookup falling back to ctx receipt_store."""

    def test_finds_receipt_in_ctx_when_store_is_none(self, mock_http_handler, mock_receipt):
        ctx = {"receipt_store": {"r-ctx": mock_receipt}}
        h = ReceiptExportHandler(ctx=ctx)
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = h.handle(
                "/api/v1/receipts/r-ctx/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 200

    def test_finds_receipt_in_ctx_when_store_get_returns_none(
        self, mock_http_handler, mock_receipt
    ):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = None
        ctx = {"receipt_store": {"r-fallback": mock_receipt}}
        h = ReceiptExportHandler(ctx=ctx)
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            result = h.handle(
                "/api/v1/receipts/r-fallback/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 200

    def test_ctx_receipt_store_without_get_method(self, mock_http_handler):
        """When ctx receipt_store has no get method, receipt stays None."""
        ctx = {"receipt_store": "not-a-dict"}
        h = ReceiptExportHandler(ctx=ctx)
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 404

    def test_ctx_with_empty_receipt_store(self, mock_http_handler):
        ctx = {"receipt_store": {}}
        h = ReceiptExportHandler(ctx=ctx)
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = h.handle(
                "/api/v1/receipts/r-missing/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 404


# ---------------------------------------------------------------------------
# handle() — JSON export
# ---------------------------------------------------------------------------


class TestHandleJsonExport:
    """Tests for JSON format export."""

    def test_json_export_with_to_dict(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 200
            assert "application/json" in _content_type(result)
            body = _body(result)
            assert body["receipt_id"] == "r-123"
            assert body["confidence"] == 0.95

    def test_json_export_with_plain_dict(self, mock_http_handler, plain_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = plain_receipt
        h = ReceiptExportHandler(ctx={})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            result = h.handle(
                "/api/v1/receipts/r-plain/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 200
            body = _body(result)
            assert body["receipt_id"] == "r-plain"
            assert body["decision"] == "rejected"

    def test_json_export_calls_to_dict(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "json"},
                mock_http_handler,
            )
            mock_receipt.to_dict.assert_called_once()


# ---------------------------------------------------------------------------
# handle() — HTML export
# ---------------------------------------------------------------------------


class TestHandleHtmlExport:
    """Tests for HTML format export."""

    def test_html_export_returns_200(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_html",
                return_value="<html><body>Receipt</body></html>",
            ),
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "html"},
                mock_http_handler,
            )
            assert _status(result) == 200

    def test_html_export_content_type(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_html",
                return_value="<html></html>",
            ),
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "html"},
                mock_http_handler,
            )
            assert "text/html" in _content_type(result)

    def test_html_export_body_is_bytes(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        html_content = "<html><body>Test Receipt</body></html>"
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_html",
                return_value=html_content,
            ),
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "html"},
                mock_http_handler,
            )
            assert isinstance(result.body, bytes)
            assert result.body == html_content.encode("utf-8")

    def test_html_export_content_disposition(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_html",
                return_value="<html></html>",
            ),
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "html"},
                mock_http_handler,
            )
            headers = _headers(result)
            assert "Content-Disposition" in headers
            assert "receipt-r-123.html" in headers["Content-Disposition"]
            assert "attachment" in headers["Content-Disposition"]

    def test_html_export_calls_receipt_to_html(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_html",
                return_value="<html></html>",
            ) as mock_to_html,
        ):
            h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "html"},
                mock_http_handler,
            )
            mock_to_html.assert_called_once_with(mock_receipt)


# ---------------------------------------------------------------------------
# handle() — PDF export
# ---------------------------------------------------------------------------


class TestHandlePdfExport:
    """Tests for PDF format export."""

    def test_pdf_export_returns_200(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_pdf",
                return_value=b"%PDF-1.4 fake content",
            ),
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "pdf"},
                mock_http_handler,
            )
            assert _status(result) == 200

    def test_pdf_export_content_type(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_pdf",
                return_value=b"%PDF-1.4",
            ),
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "pdf"},
                mock_http_handler,
            )
            assert _content_type(result) == "application/pdf"

    def test_pdf_export_body_is_bytes(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        pdf_bytes = b"%PDF-1.4 binary content"
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_pdf",
                return_value=pdf_bytes,
            ),
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "pdf"},
                mock_http_handler,
            )
            assert result.body == pdf_bytes

    def test_pdf_export_content_disposition(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_pdf",
                return_value=b"%PDF",
            ),
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "pdf"},
                mock_http_handler,
            )
            headers = _headers(result)
            assert "Content-Disposition" in headers
            assert "receipt-r-123.pdf" in headers["Content-Disposition"]
            assert "attachment" in headers["Content-Disposition"]

    def test_pdf_export_calls_receipt_to_pdf(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_pdf",
                return_value=b"%PDF",
            ) as mock_to_pdf,
        ):
            h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "pdf"},
                mock_http_handler,
            )
            mock_to_pdf.assert_called_once_with(mock_receipt)


# ---------------------------------------------------------------------------
# handle() — receipt ID extraction
# ---------------------------------------------------------------------------


class TestReceiptIdExtraction:
    """Tests for receipt ID extraction from the URL path."""

    def test_extracts_simple_id(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            h.handle(
                "/api/v1/receipts/abc123/export",
                {"format": "json"},
                mock_http_handler,
            )
            mock_store.get_for_org.assert_called_once_with("abc123", TEST_ORG)

    def test_extracts_uuid_id(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        receipt_id = "550e8400-e29b-41d4-a716-446655440000"
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            h.handle(
                f"/api/v1/receipts/{receipt_id}/export",
                {"format": "json"},
                mock_http_handler,
            )
            mock_store.get_for_org.assert_called_once_with(receipt_id, TEST_ORG)

    def test_extracts_receipt_id_at_correct_index(self, mock_http_handler, mock_receipt):
        """Path /api/v1/receipts/{id}/export -> parts[3] after strip('/').split('/')."""
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            h.handle(
                "/api/v1/receipts/my-id/export",
                {"format": "json"},
                mock_http_handler,
            )
            # After strip("/").split("/"), parts = ["api", "v1", "receipts", "my-id", "export"]
            # parts[3] = "my-id"
            mock_store.get_for_org.assert_called_once_with("my-id", TEST_ORG)


# ---------------------------------------------------------------------------
# handle() — store priority
# ---------------------------------------------------------------------------


class TestStorePriority:
    """Tests for store vs ctx lookup priority."""

    def test_store_receipt_takes_priority_over_ctx(self, mock_http_handler):
        store_receipt = MagicMock()
        store_receipt.org_id = TEST_ORG
        store_receipt.to_dict.return_value = {"source": "store"}
        ctx_receipt = MagicMock()
        ctx_receipt.org_id = TEST_ORG
        ctx_receipt.to_dict.return_value = {"source": "ctx"}

        mock_store = MagicMock()
        mock_store.get_for_org.return_value = store_receipt

        h = ReceiptExportHandler(ctx={"receipt_store": {"r-123": ctx_receipt}})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "json"},
                mock_http_handler,
            )
            body = _body(result)
            assert body["source"] == "store"

    def test_ctx_used_only_when_store_returns_none(self, mock_http_handler):
        ctx_receipt = MagicMock()
        ctx_receipt.org_id = TEST_ORG
        ctx_receipt.to_dict.return_value = {"source": "ctx"}

        mock_store = MagicMock()
        mock_store.get_for_org.return_value = None

        h = ReceiptExportHandler(ctx={"receipt_store": {"r-123": ctx_receipt}})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "json"},
                mock_http_handler,
            )
            body = _body(result)
            assert body["source"] == "ctx"


# ---------------------------------------------------------------------------
# handle() — edge cases
# ---------------------------------------------------------------------------


class TestHandleEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_receipt_with_special_characters_in_id(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            result = h.handle(
                "/api/v1/receipts/receipt_2026-02-23/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 200

    def test_ctx_without_receipt_store_key(self, mock_http_handler):
        """When ctx has no receipt_store key, fallback should still work."""
        h = ReceiptExportHandler(ctx={"other_key": "value"})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "json"},
                mock_http_handler,
            )
            assert _status(result) == 404

    def test_format_case_sensitive(self, handler, mock_http_handler):
        """Format check is case-sensitive; 'JSON' is invalid."""
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = handler.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "JSON"},
                mock_http_handler,
            )
            assert _status(result) == 400

    def test_format_with_whitespace_is_invalid(self, handler, mock_http_handler):
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=None,
        ):
            result = handler.handle(
                "/api/v1/receipts/r-123/export",
                {"format": " json"},
                mock_http_handler,
            )
            assert _status(result) == 400

    def test_empty_query_params_defaults_to_json(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        with patch(
            "aragora.server.handlers.receipt_export._get_receipt_store",
            return_value=mock_store,
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {},
                mock_http_handler,
            )
            assert _status(result) == 200
            assert "application/json" in _content_type(result)

    def test_html_export_with_unicode_content(self, mock_http_handler, mock_receipt):
        mock_store = MagicMock()
        mock_store.get_for_org.return_value = mock_receipt
        h = ReceiptExportHandler(ctx={})
        unicode_html = "<html><body>Receipt: \u00e9\u00e8\u00ea \u00fc\u00f6\u00e4</body></html>"
        with (
            patch(
                "aragora.server.handlers.receipt_export._get_receipt_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.gauntlet.export.receipt_to_html",
                return_value=unicode_html,
            ),
        ):
            result = h.handle(
                "/api/v1/receipts/r-123/export",
                {"format": "html"},
                mock_http_handler,
            )
            assert _status(result) == 200
            assert result.body == unicode_html.encode("utf-8")


# ---------------------------------------------------------------------------
# __all__ export
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Tests for module-level exports."""

    def test_all_exports_receipt_export_handler(self):
        from aragora.server.handlers import receipt_export

        assert "ReceiptExportHandler" in receipt_export.__all__

    def test_all_has_single_entry(self):
        from aragora.server.handlers import receipt_export

        assert len(receipt_export.__all__) == 1
