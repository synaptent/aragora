"""
Receipt Export Handler.

Provides an endpoint to export decision receipts in multiple formats:
- GET /api/v1/receipts/:id/export?format=html|pdf|json

Only a member of the receipt's org can export it; another org's receipt, an
unknown-owner receipt and a missing one all get the same 404.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.server.handlers.utils.responses import HandlerResult as HR
from aragora.tenancy.record_scope import record_not_found, record_visible, require_org_scope

logger = logging.getLogger(__name__)

_VALID_FORMATS = {"json", "html", "pdf"}


def _get_receipt_store():
    """Lazy-load receipt store."""
    try:
        from aragora.storage.receipt_store import get_receipt_store

        return get_receipt_store()
    except ImportError:
        return None


class ReceiptExportHandler(BaseHandler):
    """Handler for receipt export endpoints."""

    def __init__(self, ctx: dict[str, Any] | None = None, **kwargs: Any):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/v1/receipts/") and path.endswith("/export")

    @require_permission("debates:export")
    @handle_errors("export receipt")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        if not self.can_handle(path):
            return None

        # Extract receipt ID from path: /api/v1/receipts/{id}/export
        parts = path.strip("/").split("/")
        if len(parts) < 4:
            return error_response("Invalid path", 400)
        receipt_id = parts[3]

        if not receipt_id:
            return error_response("Missing receipt ID", 400)

        scope, scope_err = require_org_scope(handler)
        if scope is None:
            return scope_err

        export_format = query_params.get("format", "json")
        if export_format not in _VALID_FORMATS:
            return error_response(
                f"Invalid format '{export_format}'. Must be one of: {', '.join(sorted(_VALID_FORMATS))}",
                400,
            )

        # Try to get receipt from store
        store = _get_receipt_store()
        receipt = None
        if store is not None:
            receipt = store.get_for_org(receipt_id, scope.org_id)

        if receipt is None:
            # Also check ctx for any receipt storage
            receipt_data = self.ctx.get("receipt_store", {})
            if hasattr(receipt_data, "get"):
                receipt = receipt_data.get(receipt_id)

        owner = (
            receipt.get("org_id") if isinstance(receipt, dict) else getattr(receipt, "org_id", None)
        )
        if receipt is None or not record_visible(owner, scope):
            return record_not_found("Receipt")

        if export_format == "json":
            data = receipt.to_dict() if hasattr(receipt, "to_dict") else receipt
            return json_response(data)

        if export_format == "html":
            from aragora.gauntlet.export import receipt_to_html

            html_content = receipt_to_html(receipt)
            return HR(
                status_code=200,
                content_type="text/html; charset=utf-8",
                body=html_content.encode("utf-8"),
                headers={
                    "Content-Disposition": f'attachment; filename="receipt-{receipt_id}.html"',
                },
            )

        if export_format == "pdf":
            from aragora.gauntlet.export import receipt_to_pdf

            pdf_content = receipt_to_pdf(receipt)
            return HR(
                status_code=200,
                content_type="application/pdf",
                body=pdf_content,
                headers={
                    "Content-Disposition": f'attachment; filename="receipt-{receipt_id}.pdf"',
                },
            )

        return error_response("Unsupported format", 400)


__all__ = ["ReceiptExportHandler"]
