"""Receipt Explorer API Handler for Pipeline Execution Receipts.

Provides REST endpoints for exploring, verifying, and searching pipeline
execution receipts with full provenance data.

Endpoints:
    GET  /api/v1/receipts              - List receipts with filtering
    GET  /api/v1/receipts/:id          - Get full receipt + provenance
    GET  /api/v1/receipts/:id/verify   - Re-verify SHA-256 hashes
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, cast

from aragora.server.versioning.compat import strip_version_prefix

try:
    from aragora.rbac.decorators import require_permission
except ImportError:  # pragma: no cover

    def require_permission(*_a, **_kw):  # type: ignore[misc]
        def _noop(fn):  # type: ignore[no-untyped-def]
            return fn

        return _noop


from ..base import (
    SAFE_ID_PATTERN,
    BaseHandler,
    HandlerResult,
    error_response,
    get_int_param,
    get_string_param,
    json_response,
    validate_path_segment,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# In-memory receipt store (production would use persistent storage)
_receipt_store: dict[str, dict[str, Any]] = {}


def register_receipt(receipt: dict[str, Any]) -> None:
    """Register a receipt in the explorer store."""
    receipt_id = receipt.get("receipt_id", "")
    if receipt_id:
        _receipt_store[receipt_id] = receipt


def _receipt_matches_filters(
    receipt: dict[str, Any],
    *,
    pipeline_id: str | None,
    status: str | None,
) -> bool:
    """Apply list filters to both in-memory and KM-backed receipt records."""
    if pipeline_id and receipt.get("pipeline_id") != pipeline_id:
        return False
    if status and receipt.get("execution", {}).get("status") != status:
        return False
    return True


class ReceiptExplorerHandler(BaseHandler):
    """HTTP handler for pipeline receipt exploration and verification."""

    def __init__(self, server_context: dict[str, Any] | None = None) -> None:
        super().__init__(server_context or {})
        self._limiter: RateLimiter | None
        try:
            self._limiter = RateLimiter(requests_per_minute=60)
        except (TypeError, RuntimeError):
            self._limiter = None

    def _check_rate_limit(self, handler: Any) -> HandlerResult | None:
        if self._limiter is None:
            return None
        client_ip = get_client_ip(handler)
        if not self._limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)
        return None

    @require_permission("pipeline:read")
    def handle_get(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route GET requests for receipt exploration."""
        rate_err = self._check_rate_limit(handler)
        if rate_err:
            return rate_err

        cleaned = strip_version_prefix(path)
        parts = cleaned.split("/")
        # parts[0]="" parts[1]="api" parts[2]="receipts" parts[3]=:id ...

        # GET /api/receipts
        if len(parts) == 3 and parts[2] == "receipts":
            return self._list_receipts(query_params)

        # GET /api/receipts/:id
        if len(parts) == 4 and parts[2] == "receipts":
            receipt_id = parts[3]
            ok, err = validate_path_segment(receipt_id, "receipt_id", SAFE_ID_PATTERN)
            if not ok:
                return error_response(cast(str, err), 400)
            return self._get_receipt(receipt_id)

        # GET /api/receipts/:id/verify
        if len(parts) == 5 and parts[2] == "receipts" and parts[4] == "verify":
            receipt_id = parts[3]
            ok, err = validate_path_segment(receipt_id, "receipt_id", SAFE_ID_PATTERN)
            if not ok:
                return error_response(cast(str, err), 400)
            return self._verify_receipt(receipt_id)

        return None

    def _list_receipts(self, params: dict[str, Any]) -> HandlerResult:
        """List receipts with optional filtering."""
        pipeline_id = get_string_param(params, "pipeline_id")
        status = get_string_param(params, "status")
        limit = get_int_param(params, "limit", 50)

        receipts_by_id: dict[str, dict[str, Any]] = {
            cast(str, receipt.get("receipt_id")): receipt
            for receipt in _receipt_store.values()
            if receipt.get("receipt_id")
        }

        # Merge KM-stored historical receipts into listing using the same singleton
        # adapter that post-debate persistence writes into.
        try:
            from aragora.knowledge.mound.adapters.receipt_adapter import get_receipt_adapter

            adapter = get_receipt_adapter()
            km_receipts = adapter.list_receipts(limit=limit)
            if km_receipts:
                for km_receipt in km_receipts:
                    rid = km_receipt.get("receipt_id")
                    if rid and rid not in receipts_by_id:
                        receipts_by_id[rid] = km_receipt
        except (ImportError, RuntimeError, AttributeError, TypeError) as e:
            logger.debug("KM receipt lookup skipped: %s", type(e).__name__)

        receipts = [
            receipt
            for receipt in receipts_by_id.values()
            if _receipt_matches_filters(receipt, pipeline_id=pipeline_id, status=status)
        ]
        receipts = receipts[:limit]
        return json_response(
            {
                "receipts": [
                    {
                        "receipt_id": r.get("receipt_id"),
                        "pipeline_id": r.get("pipeline_id"),
                        "generated_at": r.get("generated_at"),
                        "status": r.get("execution", {}).get("status", "unknown"),
                        "content_hash": r.get("content_hash"),
                    }
                    for r in receipts
                ],
                "count": len(receipts),
            }
        )

    def _get_receipt(self, receipt_id: str) -> HandlerResult:
        """Get full receipt with provenance."""
        receipt = _receipt_store.get(receipt_id)
        if receipt is None:
            return error_response("Receipt not found", 404)
        return json_response(receipt)

    def _verify_receipt(self, receipt_id: str) -> HandlerResult:
        """Re-compute SHA-256 hash and compare to stored hash."""
        receipt = _receipt_store.get(receipt_id)
        if receipt is None:
            return error_response("Receipt not found", 404)

        stored_hash = receipt.get("content_hash", "")
        pipeline_id = receipt.get("pipeline_id", "")
        execution = receipt.get("execution", {})
        stages = receipt.get("provenance", {})

        # Recompute hash using the same method as receipt_generator
        content_str = f"{pipeline_id}:{execution}:{stages}"
        recomputed_hash = hashlib.sha256(content_str.encode()).hexdigest()

        valid = recomputed_hash == stored_hash

        return json_response(
            {
                "receipt_id": receipt_id,
                "valid": valid,
                "stored_hash": stored_hash,
                "recomputed_hash": recomputed_hash,
                "pipeline_id": pipeline_id,
            }
        )


__all__ = ["ReceiptExplorerHandler", "register_receipt"]
