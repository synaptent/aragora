"""
Audit Trail HTTP Handlers for Aragora.

Provides REST API endpoints for audit trail access and verification:
- List and retrieve audit trails
- Export audit trails in multiple formats
- Verify audit trail integrity
- List and retrieve decision receipts

Endpoints:
    GET  /api/v1/audit-trails                    - List recent audit trails
    GET  /api/v1/audit-trails/:trail_id          - Get specific audit trail
    GET  /api/v1/audit-trails/:trail_id/export   - Export (format=json|csv|md)
    POST /api/v1/audit-trails/:trail_id/verify   - Verify integrity checksum

    GET  /api/v1/receipts                        - List recent decision receipts
    GET  /api/v1/receipts/:receipt_id            - Get specific receipt
    POST /api/v1/receipts/:receipt_id/verify     - Verify receipt integrity

These endpoints surface the "defensible decisions" pillar of Aragora's
control plane positioning, providing full audit trails with cryptographic
integrity verification for compliance documentation.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)


class AuditTrailHandler(BaseHandler):
    """
    HTTP handler for audit trail operations.

    Provides REST API access to audit trails and decision receipts
    for compliance documentation and integrity verification.
    """

    ROUTES = [
        "/api/v1/audit-trails",
        "/api/v1/receipts",
    ]

    # Legacy in-memory storage (kept for backward compatibility during migration)
    _trails: dict[str, dict[str, Any]] = {}
    _receipts: dict[str, dict[str, Any]] = {}

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)

        # Use database-backed store for persistence
        from aragora.storage.audit_trail_store import get_audit_trail_store

        self._store = get_audit_trail_store()

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path.startswith("/api/v1/audit-trails"):
            return method in ("GET", "POST")
        if path.startswith("/api/v1/receipts"):
            return method in ("GET", "POST")
        return False

    async def _call_store_nonblocking(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Run sync-backed store methods without blocking the event loop."""
        method = getattr(self._store, method_name)
        if inspect.iscoroutinefunction(method):
            return await method(*args, **kwargs)

        result = await asyncio.to_thread(method, *args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _extract_and_validate_id(path: str, index: int = 4) -> str | None:
        """Extract a path segment and validate it is a non-empty string."""
        parts = path.split("/")
        if len(parts) <= index:
            return None
        segment = parts[index]
        if not isinstance(segment, str) or not segment.strip():
            return None
        return segment

    @rate_limit(requests_per_minute=60)
    async def handle(  # type: ignore[override]
        self,
        method_or_path: str,
        path_or_query: str | dict[str, Any] | Any | None = None,
        handler: Any | None = None,
        query_params: dict[str, Any] | None = None,
    ) -> HandlerResult:
        """Route request to appropriate handler method."""
        if not isinstance(method_or_path, str):
            return error_response("Invalid request: method_or_path must be a string", 400)

        # Support both handle(path, query_params, handler) and handle(method, path, ...)
        if method_or_path.startswith("/"):
            path = method_or_path
            if isinstance(path_or_query, dict):
                query_params = path_or_query
            elif path_or_query is not None and handler is None:
                handler = path_or_query
        else:
            path = str(path_or_query or "")
        method = (
            method_or_path
            if not method_or_path.startswith("/")
            else getattr(handler, "command", "GET")
            if handler
            else "GET"
        )
        if query_params is not None and not isinstance(query_params, dict):
            return error_response("Invalid request: query_params must be a dict", 400)
        query_params = query_params or {}

        try:
            # Audit Trail Routes
            if path == "/api/v1/audit-trails" and method == "GET":
                return await self._list_audit_trails(query_params)

            if path.startswith("/api/v1/audit-trails/") and "/export" in path:
                trail_id = self._extract_and_validate_id(path)
                if not trail_id:
                    return error_response("Invalid or missing trail_id", 400)
                return await self._export_audit_trail(trail_id, query_params)

            if path.startswith("/api/v1/audit-trails/") and "/verify" in path:
                trail_id = self._extract_and_validate_id(path)
                if not trail_id:
                    return error_response("Invalid or missing trail_id", 400)
                return await self._verify_audit_trail(trail_id)

            if path.startswith("/api/v1/audit-trails/"):
                trail_id = self._extract_and_validate_id(path)
                if not trail_id:
                    return error_response("Invalid or missing trail_id", 400)
                return await self._get_audit_trail(trail_id)

            # Receipt Routes
            if path == "/api/v1/receipts" and method == "GET":
                return await self._list_receipts(query_params)

            if path.startswith("/api/v1/receipts/") and "/verify" in path:
                receipt_id = self._extract_and_validate_id(path)
                if not receipt_id:
                    return error_response("Invalid or missing receipt_id", 400)
                return await self._verify_receipt(receipt_id)

            if path.startswith("/api/v1/receipts/"):
                receipt_id = self._extract_and_validate_id(path)
                if not receipt_id:
                    return error_response("Invalid or missing receipt_id", 400)
                return await self._get_receipt(receipt_id)

            return error_response("Not found", 404)

        except (
            KeyError,
            ValueError,
            TypeError,
            AttributeError,
            OSError,
        ) as e:  # broad catch: last-resort handler
            logger.exception("Error handling audit trail request: %s", e)
            return error_response("Internal server error", 500)

    @require_permission("audit:read")
    async def _list_audit_trails(self, query_params: dict[str, str]) -> HandlerResult:
        """List recent audit trails with pagination."""
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=1000)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=1000000)
        verdict = query_params.get("verdict")

        # Get trails from database-backed store
        summaries = await self._call_store_nonblocking(
            "list_trails",
            limit=limit,
            offset=offset,
            verdict=verdict,
        )
        total = await self._call_store_nonblocking("count_trails", verdict=verdict)

        # Fall back to in-memory for backward compatibility
        if not summaries and self._trails:
            trails = list(self._trails.values())
            trails.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            paginated = trails[offset : offset + limit]
            summaries = [
                {
                    "trail_id": t.get("trail_id"),
                    "gauntlet_id": t.get("gauntlet_id"),
                    "created_at": t.get("created_at"),
                    "verdict": t.get("verdict"),
                    "confidence": t.get("confidence"),
                    "total_findings": t.get("total_findings"),
                    "duration_seconds": t.get("duration_seconds"),
                    "checksum": t.get("checksum"),
                }
                for t in paginated
            ]
            total = len(trails)

        return json_response(
            {
                "trails": summaries,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    @require_permission("audit:read")
    async def _get_audit_trail(self, trail_id: str) -> HandlerResult:
        """Get a specific audit trail by ID."""
        # Try database-backed store first
        trail = await self._call_store_nonblocking("get_trail", trail_id)

        # Fall back to in-memory cache
        if not trail:
            trail = self._trails.get(trail_id)

        if not trail:
            # Try to load from gauntlet results if available
            trail = await self._load_trail_from_gauntlet(trail_id)

        if not trail:
            return error_response(f"Audit trail not found: {trail_id}", 404)

        return json_response(trail)

    @require_permission("audit:export")
    async def _export_audit_trail(
        self, trail_id: str, query_params: dict[str, str]
    ) -> HandlerResult:
        """Export audit trail in specified format."""
        format_type = query_params.get("format", "json")

        # Try database-backed store first
        trail = await self._call_store_nonblocking("get_trail", trail_id)
        if not trail:
            trail = self._trails.get(trail_id)
        if not trail:
            trail = await self._load_trail_from_gauntlet(trail_id)

        if not trail:
            return error_response(f"Audit trail not found: {trail_id}", 404)

        try:
            from aragora.export.audit_trail import AuditTrail

            # Reconstruct AuditTrail object
            audit_trail = AuditTrail.from_json(__import__("json").dumps(trail))

            if format_type == "json":
                return HandlerResult(
                    status_code=200,
                    content_type="application/json",
                    body=audit_trail.to_json().encode(),
                    headers={
                        "Content-Disposition": f'attachment; filename="{trail_id}.json"',
                    },
                )
            elif format_type == "csv":
                return HandlerResult(
                    status_code=200,
                    content_type="text/csv",
                    body=audit_trail.to_csv().encode(),
                    headers={
                        "Content-Disposition": f'attachment; filename="{trail_id}.csv"',
                    },
                )
            elif format_type in ("md", "markdown"):
                return HandlerResult(
                    status_code=200,
                    content_type="text/markdown",
                    body=audit_trail.to_markdown().encode(),
                    headers={
                        "Content-Disposition": f'attachment; filename="{trail_id}.md"',
                    },
                )
            else:
                return error_response(f"Unknown format: {format_type}. Use json, csv, or md.", 400)

        except ImportError:
            # Fallback if export module not available
            import json

            return HandlerResult(
                status_code=200,
                content_type="application/json",
                body=json.dumps(trail, indent=2).encode(),
                headers={
                    "Content-Disposition": f'attachment; filename="{trail_id}.json"',
                },
            )

    @require_permission("audit:verify")
    async def _verify_audit_trail(self, trail_id: str) -> HandlerResult:
        """Verify audit trail integrity checksum."""
        trail = self._trails.get(trail_id)
        if not trail:
            trail = await self._load_trail_from_gauntlet(trail_id)

        if not trail:
            return error_response(f"Audit trail not found: {trail_id}", 404)

        try:
            from aragora.export.audit_trail import AuditTrail

            audit_trail = AuditTrail.from_json(__import__("json").dumps(trail))

            is_valid = audit_trail.verify_integrity()
            stored_checksum = trail.get("checksum", "")
            computed_checksum = audit_trail.checksum

            return json_response(
                {
                    "trail_id": trail_id,
                    "valid": is_valid,
                    "stored_checksum": stored_checksum,
                    "computed_checksum": computed_checksum,
                    "match": stored_checksum == computed_checksum,
                }
            )

        except (ImportError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("Error verifying audit trail %s: %s", trail_id, e)
            return json_response(
                {
                    "trail_id": trail_id,
                    "valid": False,
                    "error": "Audit trail verification failed",
                }
            )

    @require_permission("audit:receipts.read")
    async def _list_receipts(self, query_params: dict[str, str]) -> HandlerResult:
        """List recent decision receipts with pagination."""
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=1000)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=1000000)
        verdict = query_params.get("verdict")
        risk_level = query_params.get("risk_level")

        # Get from database-backed store
        summaries = await self._call_store_nonblocking(
            "list_receipts",
            limit=limit,
            offset=offset,
            verdict=verdict,
            risk_level=risk_level,
        )
        total = await self._call_store_nonblocking(
            "count_receipts", verdict=verdict, risk_level=risk_level
        )

        # Fall back to in-memory for backward compatibility
        if not summaries and self._receipts:
            receipts = list(self._receipts.values())
            receipts.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            paginated = receipts[offset : offset + limit]
            summaries = [
                {
                    "receipt_id": r.get("receipt_id"),
                    "gauntlet_id": r.get("gauntlet_id"),
                    "timestamp": r.get("timestamp"),
                    "verdict": r.get("verdict"),
                    "confidence": r.get("confidence"),
                    "risk_level": r.get("risk_level"),
                    "findings_count": len(r.get("findings", [])),
                    "checksum": r.get("checksum"),
                }
                for r in paginated
            ]
            total = len(receipts)

        return json_response(
            {
                "receipts": summaries,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    @require_permission("audit:receipts.read")
    async def _get_receipt(self, receipt_id: str) -> HandlerResult:
        """Get a specific decision receipt by ID."""
        # Try database-backed store first
        receipt = await self._call_store_nonblocking("get_receipt", receipt_id)

        # Fall back to in-memory cache
        if not receipt:
            receipt = self._receipts.get(receipt_id)

        if not receipt:
            receipt = await self._load_receipt_from_gauntlet(receipt_id)

        if not receipt:
            return error_response(f"Receipt not found: {receipt_id}", 404)

        return json_response(receipt)

    @require_permission("audit:receipts.verify")
    async def _verify_receipt(self, receipt_id: str) -> HandlerResult:
        """Verify decision receipt integrity."""
        # Try database-backed store first
        receipt = await self._call_store_nonblocking("get_receipt", receipt_id)
        if not receipt:
            receipt = self._receipts.get(receipt_id)
        if not receipt:
            receipt = await self._load_receipt_from_gauntlet(receipt_id)

        if not receipt:
            return error_response(f"Receipt not found: {receipt_id}", 404)

        try:
            # Compute checksum and verify
            import hashlib
            import json

            content = json.dumps(
                {
                    "receipt_id": receipt.get("receipt_id"),
                    "gauntlet_id": receipt.get("gauntlet_id"),
                    "verdict": receipt.get("verdict"),
                    "confidence": receipt.get("confidence"),
                },
                sort_keys=True,
            )
            computed = hashlib.sha256(content.encode()).hexdigest()[:16]
            stored = receipt.get("checksum", "")

            return json_response(
                {
                    "receipt_id": receipt_id,
                    "valid": computed == stored,
                    "stored_checksum": stored,
                    "computed_checksum": computed,
                    "match": computed == stored,
                }
            )

        except (ImportError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("Error verifying receipt %s: %s", receipt_id, e)
            return json_response(
                {
                    "receipt_id": receipt_id,
                    "valid": False,
                    "error": "Receipt verification failed",
                }
            )

    async def _load_trail_from_gauntlet(self, trail_id: str) -> dict[str, Any] | None:
        """
        Try to load audit trail from gauntlet results.

        In production, this would query the database for historical results.
        """
        # Extract gauntlet_id from trail_id (format: trail-{gauntlet_id})
        if trail_id.startswith("trail-"):
            gauntlet_id = trail_id[6:]
        else:
            gauntlet_id = trail_id

        # Try database store first (by gauntlet_id)
        trail_dict = await self._call_store_nonblocking("get_trail_by_gauntlet", gauntlet_id)
        if trail_dict:
            return trail_dict

        # Try to get from gauntlet handler's result cache
        gauntlet_handler = self.ctx.get("gauntlet_handler")
        if gauntlet_handler and hasattr(gauntlet_handler, "_results"):
            result = gauntlet_handler._results.get(gauntlet_id)
            if result:
                try:
                    from aragora.export.audit_trail import generate_audit_trail

                    trail = generate_audit_trail(result)
                    trail_dict = trail.to_dict()
                    # Persist to database store
                    await self._call_store_nonblocking("save_trail", trail_dict)
                    # Also cache in-memory for backward compatibility
                    self._trails[trail_id] = trail_dict
                    return trail_dict
                except (ImportError, ValueError, TypeError, KeyError, AttributeError) as e:
                    logger.debug("Could not generate audit trail: %s", e)

        return None

    async def _load_receipt_from_gauntlet(self, receipt_id: str) -> dict[str, Any] | None:
        """
        Try to load decision receipt from gauntlet results.

        In production, this would query the database for historical results.
        """
        # Extract gauntlet_id from receipt_id (format: receipt-{gauntlet_id})
        if receipt_id.startswith("receipt-"):
            gauntlet_id = receipt_id[8:]
        else:
            gauntlet_id = receipt_id

        # Try database store first (by gauntlet_id)
        receipt_dict = await self._call_store_nonblocking("get_receipt_by_gauntlet", gauntlet_id)
        if receipt_dict:
            return receipt_dict

        gauntlet_handler = self.ctx.get("gauntlet_handler")
        if gauntlet_handler and hasattr(gauntlet_handler, "_results"):
            result = gauntlet_handler._results.get(gauntlet_id)
            if result:
                try:
                    from aragora.export.decision_receipt import (
                        generate_decision_receipt,
                    )

                    receipt = generate_decision_receipt(result)
                    receipt_dict = receipt.to_dict()
                    # Persist to database store
                    await self._call_store_nonblocking("save_receipt", receipt_dict)
                    # Also cache in-memory for backward compatibility
                    self._receipts[receipt_id] = receipt_dict
                    return receipt_dict
                except (ImportError, ValueError, TypeError, KeyError, AttributeError) as e:
                    logger.debug("Could not generate receipt: %s", e)

        return None

    @classmethod
    def store_trail(cls, trail_id: str, trail_data: dict[str, Any]) -> None:
        """Store an audit trail (called from gauntlet handler)."""
        cls._trails[trail_id] = trail_data

    @classmethod
    def store_receipt(cls, receipt_id: str, receipt_data: dict[str, Any]) -> None:
        """Store a decision receipt (called from gauntlet handler)."""
        cls._receipts[receipt_id] = receipt_data
