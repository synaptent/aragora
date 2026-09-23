"""
Decision Receipt HTTP Handlers for Aragora.

Provides REST API endpoints for decision receipt management:
- List and retrieve receipts with filtering
- Verify receipt integrity and signatures
- Export receipts in multiple formats
- Batch verification and signing operations
- Shareable links for receipts

Endpoints:
    GET  /api/v2/receipts                              - List receipts with filters
    GET  /api/v2/receipts/search                       - Full-text search receipts
    GET  /api/v2/receipts/:receipt_id                  - Get specific receipt
    GET  /api/v2/receipts/:receipt_id/export           - Export (format=json|html|md|pdf)
    GET  /api/v2/receipts/:receipt_id/verify           - Verify integrity + signature
    POST /api/v2/receipts/:receipt_id/verify           - Verify integrity checksum
    POST /api/v2/receipts/:receipt_id/verify-signature - Verify cryptographic signature
    POST /api/v2/receipts/verify-batch                 - Batch signature verification
    POST /api/v2/receipts/sign-batch                   - Batch signing
    POST /api/v2/receipts/batch-export                 - Batch export to ZIP
    GET  /api/v2/receipts/stats                        - Receipt statistics
    POST /api/v2/receipts/:receipt_id/share            - Create shareable link
    GET  /api/v2/receipts/share/:token                 - Access receipt via share token
    GET  /api/v2/receipts/signing-key                  - ODR signing public key (JSON envelope)
    GET  /.well-known/aragora-odr-signing-key          - ODR signing public key (raw PEM)
    GET  /api/v1/receipts/deliveries                   - Legacy/frontend delivery history bridge

These endpoints support the "defensible decisions" pillar with:
- Cryptographic signature verification
- 7-year retention for compliance
- Full audit trail integration
- Time-limited shareable links
"""

from __future__ import annotations

import asyncio
import inspect
import io
import logging
import secrets
import zipfile
from datetime import datetime, timezone
from inspect import signature
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
)
from aragora.server.handlers.utils.lazy_stores import LazyStoreFactory
from aragora.server.handlers.utils.receipt_delivery_history import (
    get_receipt_delivery_history_store,
)
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.rbac.decorators import require_permission
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)


async def _call_nonblocking(target: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Run sync store methods in a worker thread when called from async handlers."""

    method = getattr(target, method_name)
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)

    result = await asyncio.to_thread(method, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def _consume_share_access(share_store: Any, token: str) -> tuple[str, dict[str, Any] | None]:
    """Consume one receipt-share access, preferring atomic store support."""
    consume_result = None
    consume_access = getattr(share_store, "consume_access", None)
    if callable(consume_access):
        consume_result = await _call_nonblocking(share_store, "consume_access", token)
        if isinstance(consume_result, dict) and "status" in consume_result:
            return consume_result["status"], consume_result.get("share_info")

    share_info = await _call_nonblocking(share_store, "get_by_token", token)
    if not share_info:
        return "not_found", None

    expires_at = share_info.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc).timestamp():
        return "expired", share_info

    max_accesses = share_info.get("max_accesses")
    access_count = share_info.get("access_count", 0)
    if max_accesses and access_count >= max_accesses:
        return "limit_reached", share_info

    await _call_nonblocking(share_store, "increment_access", token)
    updated_share_info = dict(share_info)
    updated_share_info["access_count"] = access_count + 1
    return "ok", updated_share_info


def _render_shared_receipt_html(receipt: Any, token: str) -> str:
    """Render a shared receipt as a self-contained HTML page with OG meta tags."""
    import html as html_mod

    esc = html_mod.escape
    payload = _extract_decision_receipt_payload(receipt)

    def payload_value(key: str, default: Any = None) -> Any:
        value = payload.get(key, getattr(receipt, key, default))
        return default if value is None else value

    def finding_field(finding: Any, key: str, default: str = "") -> str:
        if isinstance(finding, dict):
            value = finding.get(key, default)
        else:
            value = getattr(finding, key, default)
        return "" if value is None else str(value)

    def format_percentage(value: Any) -> str:
        try:
            return f"{float(value):.0%}"
        except (TypeError, ValueError):
            return "0%"

    def float_value(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def format_duration(value: Any) -> str | None:
        try:
            duration = float(value)
        except (TypeError, ValueError):
            return None
        if duration <= 0:
            return None
        return f"{duration:.1f}s"

    def format_cost(value: Any) -> str | None:
        try:
            cost = float(value)
        except (TypeError, ValueError):
            return None
        if cost <= 0:
            return None
        return f"${cost:.4f}"

    def format_tokens(value: Any) -> str | None:
        try:
            tokens = int(value)
        except (TypeError, ValueError):
            return None
        if tokens <= 0:
            return None
        return f"{tokens:,}"

    receipt_id = str(payload_value("receipt_id", "unknown"))
    verdict = str(payload_value("verdict", "UNKNOWN"))
    confidence = float_value(payload_value("confidence", 0.0), 0.0)
    risk_level = str(payload_value("risk_level", "unknown"))
    input_summary = str(payload_value("input_summary", "Decision receipt"))
    timestamp = str(payload_value("timestamp", ""))
    checksum = str(payload_value("checksum", ""))
    raw_agents = payload_value("agents_involved", [])
    agents = raw_agents if isinstance(raw_agents, list) else []
    raw_findings = payload_value("findings", [])
    findings = raw_findings if isinstance(raw_findings, list) else []
    robustness_score = payload_value("robustness_score", 0.0)
    coverage_score = payload_value("coverage_score", 0.0)
    verification_coverage = payload_value("verification_coverage", 0.0)
    duration_display = format_duration(payload_value("duration_seconds"))
    cost_display = format_cost(payload_value("cost_usd"))
    tokens_used = payload_value("tokens_used")
    if tokens_used in (None, 0) and isinstance(payload.get("cost_summary"), dict):
        cost_summary = payload["cost_summary"]
        tokens_used = int(cost_summary.get("total_tokens_in", 0) or 0) + int(
            cost_summary.get("total_tokens_out", 0) or 0
        )
    tokens_display = format_tokens(tokens_used)

    verdict_colors = {
        "APPROVED": "#28a745",
        "APPROVED_WITH_CONDITIONS": "#ffc107",
        "NEEDS_REVIEW": "#fd7e14",
        "REJECTED": "#dc3545",
    }
    verdict_color = verdict_colors.get(verdict.upper() if verdict else "", "#6c757d")

    findings_html = ""
    for f in findings:
        sev = finding_field(f, "severity", "UNKNOWN")
        title = finding_field(f, "title")
        desc = finding_field(f, "description")
        mit = finding_field(f, "mitigation")
        sev_color = {
            "CRITICAL": "#dc3545",
            "HIGH": "#fd7e14",
            "MEDIUM": "#ffc107",
            "LOW": "#28a745",
        }.get(sev, "#6c757d")
        findings_html += f"""
        <div style="border-left: 4px solid {sev_color}; padding: 12px 16px; margin: 12px 0; background: #f8f9fa; border-radius: 0 6px 6px 0;">
            <strong style="color: {sev_color};">[{esc(sev)}]</strong> {esc(title)}
            <p style="margin: 6px 0 0; color: #555;">{esc(desc)}</p>
            {f'<p style="margin: 6px 0 0; font-style: italic; color: #666;">Mitigation: {esc(mit)}</p>' if mit else ""}
        </div>"""

    og_description = f"Verdict: {verdict} | Confidence: {confidence:.0%} | Risk: {risk_level}"
    if findings:
        og_description += f" | {len(findings)} finding(s)"

    detail_rows = [
        f'<div class="meta-row"><span class="meta-key">Input</span><span class="meta-val">{esc(str(input_summary)[:100])}</span></div>',
        f'<div class="meta-row"><span class="meta-key">Timestamp</span><span class="meta-val">{esc(str(timestamp))}</span></div>',
        f'<div class="meta-row"><span class="meta-key">Agents</span><span class="meta-val">{esc(", ".join(str(agent) for agent in agents[:5]))}{" ..." if len(agents) > 5 else ""}</span></div>',
        f'<div class="meta-row"><span class="meta-key">Receipt ID</span><span class="meta-val">{esc(receipt_id[:24])}</span></div>',
    ]
    if duration_display:
        detail_rows.append(
            f'<div class="meta-row"><span class="meta-key">Duration</span><span class="meta-val">{esc(duration_display)}</span></div>'
        )
    if cost_display:
        detail_rows.append(
            f'<div class="meta-row"><span class="meta-key">Cost</span><span class="meta-val">{esc(cost_display)}</span></div>'
        )
    if tokens_display:
        detail_rows.append(
            f'<div class="meta-row"><span class="meta-key">Tokens Used</span><span class="meta-val">{esc(tokens_display)}</span></div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Decision Receipt - {esc(receipt_id[:16])}</title>
    <meta property="og:title" content="Aragora Decision Receipt">
    <meta property="og:description" content="{esc(og_description)}">
    <meta property="og:type" content="article">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="Aragora Decision Receipt">
    <meta name="twitter:description" content="{esc(og_description)}">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; color: #333; min-height: 100vh; }}
        .container {{ max-width: 800px; margin: 0 auto; padding: 24px 16px; }}
        .header {{ text-align: center; padding: 24px 0 16px; }}
        .header h1 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 2px; color: #666; margin-bottom: 4px; }}
        .header .brand {{ font-size: 24px; font-weight: 700; color: #1a1a2e; }}
        .card {{ background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); padding: 32px; margin-bottom: 16px; }}
        .verdict-card {{ text-align: center; }}
        .verdict-label {{ font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #888; }}
        .verdict-value {{ font-size: 36px; font-weight: 800; color: {verdict_color}; margin: 8px 0; }}
        .verdict-meta {{ font-size: 15px; color: #666; }}
        .scores {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 20px 0 0; }}
        .score {{ text-align: center; padding: 16px 8px; background: #f8f9fa; border-radius: 8px; }}
        .score-val {{ font-size: 28px; font-weight: 700; color: #333; }}
        .score-lbl {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}
        .section-title {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; color: #1a1a2e; }}
        .meta-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f0f0f0; font-size: 14px; }}
        .meta-row:last-child {{ border-bottom: none; }}
        .meta-key {{ color: #888; }}
        .meta-val {{ color: #333; font-weight: 500; font-family: monospace; }}
        .footer {{ text-align: center; padding: 16px; color: #aaa; font-size: 12px; }}
        .footer code {{ background: #f0f2f5; padding: 2px 6px; border-radius: 4px; font-size: 11px; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Decision Receipt</h1>
            <div class="brand">Aragora</div>
        </div>

        <div class="card verdict-card">
            <div class="verdict-label">Verdict</div>
            <div class="verdict-value">{esc(verdict)}</div>
            <div class="verdict-meta">
                Confidence: {confidence:.0%} &middot; Risk: {esc(risk_level)}
            </div>
            <div class="scores">
                <div class="score">
                    <div class="score-val">{format_percentage(robustness_score)}</div>
                    <div class="score-lbl">Robustness</div>
                </div>
                <div class="score">
                    <div class="score-val">{format_percentage(coverage_score)}</div>
                    <div class="score-lbl">Coverage</div>
                </div>
                <div class="score">
                    <div class="score-val">{format_percentage(verification_coverage)}</div>
                    <div class="score-lbl">Verification</div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="section-title">Decision Details</div>
            {"".join(detail_rows)}
        </div>

        {"<div class='card'><div class='section-title'>Findings (" + str(len(findings)) + ")</div>" + findings_html + "</div>" if findings else ""}

        <div class="footer">
            <p>Integrity: <code>{esc(checksum[:32])}...</code></p>
            <p style="margin-top: 8px;">Generated by <strong>Aragora</strong> &middot; Decision Integrity Platform</p>
        </div>
    </div>
</body>
</html>"""


def _extract_decision_receipt_payload(receipt: Any) -> dict[str, Any]:
    """Extract only the constructor-supported DecisionReceipt payload."""
    if isinstance(receipt, dict):
        nested = receipt.get("data")
        if isinstance(nested, dict):
            payload = dict(nested)
        else:
            payload = dict(receipt)
        plain = receipt
    else:
        nested = getattr(receipt, "data", None)
        if isinstance(nested, dict):
            payload = dict(nested)
        elif hasattr(receipt, "to_dict"):
            plain_value = receipt.to_dict()
            payload = dict(plain_value) if isinstance(plain_value, dict) else {}
        else:
            payload = {}
        plain = receipt.to_dict() if hasattr(receipt, "to_dict") else {}

    if isinstance(plain, dict):
        for key in ("receipt_id", "gauntlet_id", "timestamp", "checksum"):
            payload.setdefault(key, plain.get(key))

    if not payload:
        return {}

    try:
        from aragora.export.decision_receipt import DecisionReceipt

        allowed_fields = signature(DecisionReceipt).parameters
        return {key: value for key, value in payload.items() if key in allowed_fields}
    except (ImportError, ValueError, TypeError):
        return payload


class ReceiptsHandler(BaseHandler):
    """
    HTTP handler for decision receipt operations.

    Provides REST API access to decision receipts with signature
    verification and export capabilities.
    """

    ROUTES = [
        "/api/v2/receipts",
        "/api/v2/receipts/*",
        "/api/v2/receipts/search",
        "/api/v2/receipts/stats",
        "/api/v2/receipts/signing-key",
        "/.well-known/aragora-odr-signing-key",
        "/api/v1/receipts/deliveries",
        "/api/v1/receipts/*/deliver",
    ]

    #: How long a successfully resolved signing public key is cached before
    #: re-reading it from Secrets Manager (allows key rotation without restart).
    SIGNING_KEY_CACHE_TTL_SECONDS = 300.0

    #: How long a FAILED key resolution (no key configured / Secrets Manager
    #: error) is cached. These endpoints are public and unauthenticated, so
    #: without negative caching every request would hit AWS Secrets Manager —
    #: an amplification vector for throttling and billing. Short TTL so a
    #: freshly provisioned key is picked up quickly.
    SIGNING_KEY_NEGATIVE_CACHE_TTL_SECONDS = 30.0

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._store_factory = LazyStoreFactory(
            store_name="receipt_store",
            import_path="aragora.storage.receipt_store",
            factory_name="get_receipt_store",
            logger_context="Receipts",
        )
        self._share_store_factory = LazyStoreFactory(
            store_name="receipt_share_store",
            import_path="aragora.storage.receipt_share_store",
            factory_name="get_receipt_share_store",
            logger_context="Receipts",
        )
        self._store = None  # Set by tests or lazy init
        self._share_store = None  # Set by tests or lazy init
        # Cached (monotonic_timestamp, (public_key_pem, key_id) | None) for the
        # ODR signing-key endpoints; only PUBLIC key material is ever cached.
        # A cached None is a negative entry (resolution failed recently).
        self._signing_key_cache: tuple[float, tuple[str, str] | None] | None = None

    def _get_store(self):
        """Get receipt store (lazy initialization)."""
        if self._store is None:
            self._store = self._store_factory.get()
        return self._store

    def _get_share_store(self):
        """Get receipt share store (lazy initialization)."""
        if self._share_store is None:
            self._share_store = self._share_store_factory.get()
        return self._share_store

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path == "/.well-known/aragora-odr-signing-key":
            return method == "GET"
        if path.startswith("/api/v2/receipts"):
            return method in ("GET", "POST")
        if path == "/api/v1/receipts/deliveries":
            return method == "GET"
        # v1 delivery bridge for frontend DeliveryModal
        if path.startswith("/api/v1/receipts/") and path.endswith("/deliver"):
            return method == "POST"
        return False

    @staticmethod
    def _normalize_receipt_path(path: str) -> str:
        """Collapse optional trailing slashes on receipt routes.

        The handler registry explicitly routes ``/api/v2/receipts/`` to this
        handler, so the list endpoint should treat that path the same as the
        canonical ``/api/v2/receipts`` route instead of falling through to an
        empty receipt_id lookup.
        """
        if path == "/api/v1/receipts/deliveries/":
            return "/api/v1/receipts/deliveries"
        if path == "/api/v2/receipts/":
            return "/api/v2/receipts"
        return path

    @rate_limit(requests_per_minute=60)
    async def handle(self, *args: Any, **kwargs: Any) -> HandlerResult | None:  # type: ignore[override]
        """Route request to appropriate handler method.

        Supports both (path, query_params, handler) and (method, path, ...) call signatures.
        """
        method = kwargs.pop("method", None)
        path = kwargs.pop("path", None)
        body = kwargs.pop("body", None)
        query_params = kwargs.pop("query_params", None)
        headers = kwargs.pop("headers", None)
        handler = kwargs.pop("handler", None)

        if args:
            first = args[0]
            http_methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
            if isinstance(first, str) and first.upper() in http_methods:
                method = first.upper()
                path = args[1] if len(args) > 1 else path
                if body is None and len(args) > 2 and isinstance(args[2], dict):
                    body = args[2]
                if query_params is None and len(args) > 3 and isinstance(args[3], dict):
                    query_params = args[3]
                if headers is None and len(args) > 4 and isinstance(args[4], dict):
                    headers = args[4]
                if handler is None and len(args) > 5:
                    handler = args[5]
            else:
                path = first
                if query_params is None and len(args) > 1 and isinstance(args[1], dict):
                    query_params = args[1]
                if handler is None and len(args) > 2:
                    handler = args[2]

        if method is None:
            method = getattr(handler, "command", "GET") if handler else "GET"
        if path is None or not isinstance(path, str):
            return error_response("Invalid receipt path", 400)
        path = self._normalize_receipt_path(path)
        if query_params is None:
            query_params = {}
        if body is None:
            if handler and method in {"POST", "PUT", "PATCH"}:
                body = self.read_json_body(handler) or {}
            else:
                body = {}
        if headers is None:
            headers = dict(handler.headers) if handler and hasattr(handler, "headers") else {}

        try:
            # ODR signing public key trust anchor (public endpoints, issue #8804).
            # Checked before the generic /api/v2/receipts/{id} parsing so
            # "signing-key" is never treated as a receipt id.
            if path == "/.well-known/aragora-odr-signing-key" and method == "GET":
                return await self._get_signing_key_pem()
            if path == "/api/v2/receipts/signing-key" and method == "GET":
                return await self._get_signing_key()

            # Stats endpoint
            if path == "/api/v2/receipts/stats" and method == "GET":
                return await self._get_stats()

            # Retention status endpoint (GDPR compliance)
            if path == "/api/v2/receipts/retention-status" and method == "GET":
                return await self._get_retention_status()

            # DSAR endpoint (GDPR Data Subject Access Request)
            if path.startswith("/api/v2/receipts/dsar/") and method == "GET":
                parts = path.split("/")
                if len(parts) >= 6:
                    user_id = parts[5]
                    return await self._get_dsar(user_id, query_params)
                return error_response("User ID required for DSAR request", 400)

            # Search endpoint
            if path == "/api/v2/receipts/search" and method == "GET":
                return await self._search_receipts(query_params)

            # Batch verification
            if path == "/api/v2/receipts/verify-batch" and method == "POST":
                return await self._verify_batch(body)

            # Batch signing
            if path == "/api/v2/receipts/sign-batch" and method == "POST":
                return await self._sign_batch(body)

            # Batch export
            if path == "/api/v2/receipts/batch-export" and method == "POST":
                return await self._batch_export(body)

            # Access shared receipt (public endpoint)
            if path.startswith("/api/v2/receipts/share/") and method == "GET":
                token = path.split("/api/v2/receipts/share/")[1].rstrip("/")
                return await self._get_shared_receipt(token, query_params, headers)

            # v1 delivery history bridge: GET /api/v1/receipts/deliveries
            if path == "/api/v1/receipts/deliveries" and method == "GET":
                return await self._list_delivery_history(query_params)

            # v1 delivery bridge: POST /api/v1/receipts/{id}/deliver
            # Maps frontend DeliveryModal calls to v2 send-to-channel logic
            if (
                path.startswith("/api/v1/receipts/")
                and path.endswith("/deliver")
                and method == "POST"
            ):
                parts_v1 = path.split("/")
                if len(parts_v1) >= 5:
                    receipt_id_v1 = parts_v1[4]
                    # Map frontend 'channel' field to v2 'channel_type'
                    delivery_body = {
                        "channel_type": body.get("channel_type") or body.get("channel"),
                        "channel_id": body.get("channel_id") or body.get("destination"),
                        "workspace_id": body.get("workspace_id"),
                        "options": body.get("options", {}),
                    }
                    if body.get("message"):
                        delivery_body["options"]["custom_message"] = body["message"]
                    return await self._send_to_channel(receipt_id_v1, delivery_body)

            # List receipts
            if path == "/api/v2/receipts" and method == "GET":
                return await self._list_receipts(query_params)

            # Receipt-specific routes
            if path.startswith("/api/v2/receipts/"):
                parts = path.split("/")
                if len(parts) < 5:
                    return error_response("Invalid receipt path", 400)

                receipt_id = parts[4]

                # Export endpoint
                if len(parts) > 5 and parts[5] == "export":
                    return await self._export_receipt(receipt_id, query_params)

                # Combined verification (signature + integrity)
                if len(parts) > 5 and parts[5] == "verify" and method == "GET":
                    return await self._verify_receipt(receipt_id)

                # Integrity verification
                if len(parts) > 5 and parts[5] == "verify" and method == "POST":
                    return await self._verify_integrity(receipt_id)

                # Signature verification
                if len(parts) > 5 and parts[5] == "verify-signature" and method == "POST":
                    return await self._verify_signature(receipt_id)

                # Share receipt
                if len(parts) > 5 and parts[5] == "share" and method == "POST":
                    return await self._share_receipt(receipt_id, body)

                # Send to channel
                if len(parts) > 5 and parts[5] == "send-to-channel" and method == "POST":
                    return await self._send_to_channel(receipt_id, body)

                # Get formatted for channel
                if len(parts) > 5 and parts[5] == "formatted" and method == "GET":
                    channel_type = parts[6] if len(parts) > 6 else "slack"
                    return await self._get_formatted(receipt_id, channel_type, query_params)

                # Get single receipt
                if method == "GET":
                    return await self._get_receipt(receipt_id)

            return error_response("Not found", 404)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError, AttributeError) as e:
            logger.exception("Error handling receipt request: %s", e)
            return error_response(safe_error_message(e, "receipt request"), 500)

    @api_endpoint(
        method="GET",
        path="/api/v2/receipts",
        summary="List receipts",
        description="List receipts with filtering and pagination. Supports filtering by debate_id, verdict, risk level, date range, and signed status.",
        tags=["Receipts"],
        parameters=[
            {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
            {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
            {"name": "debate_id", "in": "query", "schema": {"type": "string"}},
            {"name": "verdict", "in": "query", "schema": {"type": "string"}},
            {"name": "risk_level", "in": "query", "schema": {"type": "string"}},
            {"name": "date_from", "in": "query", "schema": {"type": "string"}},
            {"name": "date_to", "in": "query", "schema": {"type": "string"}},
            {"name": "signed_only", "in": "query", "schema": {"type": "boolean"}},
        ],
        responses={
            "200": {"description": "List of receipts returned"},
            "401": {"description": "Unauthorized"},
        },
    )
    @require_permission("receipts:read")
    async def _list_receipts(self, query_params: dict[str, str]) -> HandlerResult:
        """
        List receipts with filtering and pagination.

        Query params:
            limit: Max results (default 20, max 100)
            offset: Pagination offset
            debate_id: Filter by debate ID
            verdict: Filter by verdict (APPROVED, REJECTED, etc.)
            risk_level: Filter by risk (LOW, MEDIUM, HIGH, CRITICAL)
            date_from: ISO date/timestamp for start
            date_to: ISO date/timestamp for end
            signed_only: Only return signed receipts (true/false)
            sort_by: Sort field (created_at, confidence, risk_score)
            order: Sort order (asc, desc)
        """
        store = self._get_store()

        # Parse pagination
        limit = safe_query_int(query_params, "limit", default=20, max_val=100)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=1000000)

        # Parse filters
        debate_id = (query_params.get("debate_id") or "").strip() or None
        verdict = query_params.get("verdict")
        risk_level = query_params.get("risk_level")
        signed_only = query_params.get("signed_only", "").lower() == "true"

        # Parse date range
        date_from = self._parse_timestamp(query_params.get("date_from"))
        date_to = self._parse_timestamp(query_params.get("date_to"))

        # Parse sorting
        sort_by = query_params.get("sort_by", "created_at")
        order = query_params.get("order", "desc")

        # Query store
        receipts = await _call_nonblocking(
            store,
            "list",
            limit=limit,
            offset=offset,
            debate_id=debate_id,
            verdict=verdict,
            risk_level=risk_level,
            date_from=date_from,
            date_to=date_to,
            signed_only=signed_only,
            sort_by=sort_by,
            order=order,
        )

        total = await _call_nonblocking(
            store,
            "count",
            debate_id=debate_id,
            verdict=verdict,
            risk_level=risk_level,
            date_from=date_from,
            date_to=date_to,
            signed_only=signed_only,
        )

        return json_response(
            {
                "receipts": [r.to_dict() for r in receipts],
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total": total,
                    "has_more": offset + len(receipts) < total,
                },
                "filters": {
                    "debate_id": debate_id,
                    "verdict": verdict,
                    "risk_level": risk_level,
                    "date_from": date_from,
                    "date_to": date_to,
                    "signed_only": signed_only,
                },
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v2/receipts/search",
        summary="Search receipts",
        description="Full-text search across receipt content with optional filtering by verdict and risk level.",
        tags=["Receipts", "Search"],
        parameters=[
            {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
            {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
            {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
            {"name": "verdict", "in": "query", "schema": {"type": "string"}},
            {"name": "risk_level", "in": "query", "schema": {"type": "string"}},
        ],
        responses={
            "200": {"description": "Search results returned"},
            "400": {"description": "Invalid search query"},
            "401": {"description": "Unauthorized"},
        },
    )
    @require_permission("receipts:read")
    async def _search_receipts(self, query_params: dict[str, str]) -> HandlerResult:
        """
        Full-text search across receipt content.

        Query params:
            q: Search query (required, minimum 3 characters)
            limit: Max results (default 50, max 100)
            offset: Pagination offset
            verdict: Optional filter by verdict (APPROVED, REJECTED, etc.)
            risk_level: Optional filter by risk (LOW, MEDIUM, HIGH, CRITICAL)
        """
        query = query_params.get("q", "").strip()

        if not query:
            return error_response("Query parameter 'q' is required", 400)

        if len(query) < 3:
            return error_response("Search query must be at least 3 characters", 400)

        store = self._get_store()

        # Parse pagination
        limit = safe_query_int(query_params, "limit", default=50, max_val=100)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=1000000)

        # Optional filters
        verdict = query_params.get("verdict")
        risk_level = query_params.get("risk_level")

        # Perform search
        receipts = await _call_nonblocking(
            store,
            "search",
            query=query,
            limit=limit,
            offset=offset,
            verdict=verdict,
            risk_level=risk_level,
        )

        total = await _call_nonblocking(
            store,
            "search_count",
            query=query,
            verdict=verdict,
            risk_level=risk_level,
        )

        return json_response(
            {
                "receipts": [r.to_dict() for r in receipts],
                "query": query,
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total": total,
                    "has_more": offset + len(receipts) < total,
                },
                "filters": {
                    "verdict": verdict,
                    "risk_level": risk_level,
                },
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v2/receipts/{receipt_id}",
        summary="Get receipt",
        description="Get a specific receipt by ID or gauntlet ID.",
        tags=["Receipts"],
        operation_id="get_receipt_by_id",
        parameters=[
            {"name": "receipt_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Receipt returned"},
            "404": {"description": "Receipt not found"},
        },
    )
    @require_permission("receipts:read")
    async def _get_receipt(self, receipt_id: str) -> HandlerResult:
        """Get a specific receipt by ID."""
        store = self._get_store()
        receipt = await _call_nonblocking(store, "get", receipt_id)

        if not receipt:
            # Try by gauntlet_id
            receipt = await _call_nonblocking(store, "get_by_gauntlet", receipt_id)

        if not receipt:
            return error_response("Receipt not found", 404)

        return json_response(receipt.to_full_dict())

    @api_endpoint(
        method="GET",
        path="/api/v2/receipts/{receipt_id}/export",
        summary="Export receipt",
        description="Export receipt in specified format (json, html, md, pdf, sarif, csv).",
        tags=["Receipts", "Export"],
        parameters=[
            {"name": "receipt_id", "in": "path", "required": True, "schema": {"type": "string"}},
            {
                "name": "format",
                "in": "query",
                "schema": {
                    "type": "string",
                    "default": "json",
                    "enum": ["json", "html", "md", "pdf", "sarif", "csv"],
                },
            },
            {"name": "signed", "in": "query", "schema": {"type": "boolean", "default": True}},
        ],
        responses={
            "200": {
                "description": "Export returned in requested format. PDF format falls back to printable HTML if weasyprint unavailable (check X-PDF-Fallback header)"
            },
            "400": {"description": "Unsupported format"},
            "404": {"description": "Receipt not found"},
            "500": {"description": "Export failed"},
        },
    )
    @require_permission("receipts:read")
    async def _export_receipt(self, receipt_id: str, query_params: dict[str, str]) -> HandlerResult:
        """
        Export receipt in specified format.

        Query params:
            format: Export format (json, html, md, pdf, sarif, csv)
            signed: Include signature if available (true/false)
        """
        store = self._get_store()
        receipt = await _call_nonblocking(store, "get", receipt_id)

        if not receipt:
            return error_response("Receipt not found", 404)

        export_format = query_params.get("format", "json").lower()
        download = query_params.get("download", "false").lower() == "true"
        _include_signature = query_params.get("signed", "true").lower() == "true"  # noqa: F841 - Future: signed exports

        try:
            from aragora.export.decision_receipt import DecisionReceipt

            # Reconstruct DecisionReceipt from stored data
            decision_receipt = DecisionReceipt.from_dict(_extract_decision_receipt_payload(receipt))

            if export_format == "json":
                content = decision_receipt.to_json(indent=2)
                body = content.encode("utf-8") if isinstance(content, str) else content
                headers = {}
                if download:
                    headers["Content-Disposition"] = (
                        f"attachment; filename=receipt-{receipt_id}.json"
                    )
                return HandlerResult(
                    status_code=200,
                    content_type="application/json; charset=utf-8",
                    body=body,
                    headers=headers if headers else None,
                )

            elif export_format == "html":
                content = decision_receipt.to_html()
                body = content.encode("utf-8") if isinstance(content, str) else content
                headers = {}
                if download:
                    headers["Content-Disposition"] = (
                        f"attachment; filename=receipt-{receipt_id}.html"
                    )
                return HandlerResult(
                    status_code=200,
                    content_type="text/html; charset=utf-8",
                    body=body,
                    headers=headers if headers else None,
                )

            elif export_format == "md" or export_format == "markdown":
                content = decision_receipt.to_markdown()
                body = content.encode("utf-8") if isinstance(content, str) else content
                headers = {}
                if download:
                    headers["Content-Disposition"] = f"attachment; filename=receipt-{receipt_id}.md"
                return HandlerResult(
                    status_code=200,
                    content_type="text/markdown; charset=utf-8",
                    body=body,
                    headers=headers if headers else None,
                )

            elif export_format == "pdf":
                try:
                    pdf_bytes = decision_receipt.to_pdf()
                    return HandlerResult(
                        status_code=200,
                        content_type="application/pdf",
                        body=pdf_bytes,
                        headers={
                            "Content-Disposition": f"attachment; filename=receipt-{receipt_id}.pdf",
                        },
                    )
                except ImportError:
                    # Fallback to print-friendly HTML when weasyprint not available
                    logger.info("PDF export unavailable, falling back to printable HTML")
                    html_content = decision_receipt.to_html()
                    # Add print-friendly wrapper
                    printable_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Receipt {receipt_id}</title>
    <style>
        @media print {{
            body {{ font-size: 12pt; }}
            .no-print {{ display: none; }}
        }}
        body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        .print-notice {{ background: #fff3cd; border: 1px solid #ffc107; padding: 10px; margin-bottom: 20px; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="print-notice no-print">
        <strong>Note:</strong> PDF export is unavailable. Use your browser's Print function (Ctrl+P / Cmd+P) to save as PDF.
    </div>
    {html_content}
</body>
</html>"""
                    body = printable_html.encode("utf-8")
                    return HandlerResult(
                        status_code=200,
                        content_type="text/html",
                        body=body,
                        headers={
                            "X-PDF-Fallback": "true",
                        },
                    )

            elif export_format == "sarif":
                from aragora.gauntlet.api.export import export_receipt, ReceiptExportFormat

                sarif_content = export_receipt(decision_receipt, format=ReceiptExportFormat.SARIF)  # type: ignore[arg-type]
                body = (
                    sarif_content.encode("utf-8")
                    if isinstance(sarif_content, str)
                    else sarif_content
                )
                return HandlerResult(
                    status_code=200,
                    content_type="application/json",
                    body=body,
                )

            elif export_format == "csv":
                content = decision_receipt.to_csv()
                body = content.encode("utf-8") if isinstance(content, str) else content
                return HandlerResult(
                    status_code=200,
                    content_type="text/csv; charset=utf-8",
                    body=body,
                    headers={
                        "Content-Disposition": f"attachment; filename=receipt-{receipt_id}.csv",
                    },
                )

            else:
                return error_response(
                    f"Unsupported format: {export_format}. "
                    "Supported: json, html, md, pdf, sarif, csv",
                    400,
                )

        except (ImportError, KeyError, ValueError, TypeError, OSError) as e:
            logger.exception("Export failed: %s", e)
            return error_response(safe_error_message(e, "receipt export"), 500)

    @api_endpoint(
        method="GET",
        path="/api/v2/receipts/{receipt_id}/verify",
        summary="Verify receipt integrity and signature",
        description="Verify both receipt integrity checksum and cryptographic signature.",
        tags=["Receipts", "Verification"],
        operation_id="verify_receipt_by_id",
        parameters=[
            {"name": "receipt_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Verification results returned"},
            "404": {"description": "Receipt not found"},
        },
    )
    @require_permission("receipts:verify")
    async def _verify_receipt(self, receipt_id: str) -> HandlerResult:
        """Verify receipt integrity checksum and signature."""
        store = self._get_store()
        signature_result = await _call_nonblocking(store, "verify_signature", receipt_id)
        integrity_result = await _call_nonblocking(store, "verify_integrity", receipt_id)

        signature_error = getattr(signature_result, "error", None)
        integrity_error = (
            integrity_result.get("error") if isinstance(integrity_result, dict) else None
        )

        if signature_error and "not found" in signature_error.lower():
            return error_response("Receipt not found", 404)
        if integrity_error and "not found" in integrity_error.lower():
            return error_response("Receipt not found", 404)

        return json_response(
            {
                "receipt_id": receipt_id,
                "signature": signature_result.to_dict()
                if hasattr(signature_result, "to_dict")
                else signature_result,
                "integrity": integrity_result,
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v2/receipts/{receipt_id}/verify",
        summary="Verify receipt integrity",
        description="Verify receipt integrity checksum to ensure data hasn't been tampered with.",
        tags=["Receipts", "Verification"],
        parameters=[
            {"name": "receipt_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Verification result returned"},
            "404": {"description": "Receipt not found"},
        },
    )
    @require_permission("receipts:verify")
    async def _verify_integrity(self, receipt_id: str) -> HandlerResult:
        """Verify receipt integrity checksum."""
        store = self._get_store()
        result = await _call_nonblocking(store, "verify_integrity", receipt_id)

        if "error" in result and result.get("integrity_valid") is False:
            if "not found" in result.get("error", "").lower():
                return error_response("Receipt not found", 404)

        return json_response(result)

    @api_endpoint(
        method="POST",
        path="/api/v2/receipts/{receipt_id}/verify-signature",
        summary="Verify receipt signature",
        description="Verify receipt cryptographic signature for authenticity.",
        tags=["Receipts", "Verification"],
        parameters=[
            {"name": "receipt_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Signature verification result returned"},
            "404": {"description": "Receipt not found"},
        },
    )
    @require_permission("receipts:verify")
    async def _verify_signature(self, receipt_id: str) -> HandlerResult:
        """Verify receipt cryptographic signature."""
        store = self._get_store()
        result = await _call_nonblocking(store, "verify_signature", receipt_id)

        if result.error and "not found" in result.error.lower():
            return error_response("Receipt not found", 404)

        return json_response(result.to_dict())

    @require_permission("receipts:verify")
    async def _verify_batch(self, body: dict[str, Any]) -> HandlerResult:
        """
        Batch verify multiple receipt signatures.

        Body:
            receipt_ids: List of receipt IDs to verify
        """
        receipt_ids = body.get("receipt_ids", [])

        if not receipt_ids:
            return error_response("receipt_ids required", 400)

        if len(receipt_ids) > 100:
            return error_response("Maximum 100 receipts per batch", 400)

        store = self._get_store()
        results, summary = await _call_nonblocking(store, "verify_batch", receipt_ids)

        return json_response(
            {
                "results": [r.to_dict() for r in results],
                "summary": summary,
            }
        )

    @api_endpoint(
        method="GET",
        path="/api/v2/receipts/stats",
        summary="Get receipt statistics",
        description="Get aggregated statistics about receipts including counts by verdict and risk level.",
        tags=["Receipts", "Statistics"],
        operation_id="get_receipt_stats",
        responses={
            "200": {"description": "Statistics returned"},
            "401": {"description": "Unauthorized"},
        },
    )
    @require_permission("receipts:read")
    async def _get_stats(self) -> HandlerResult:
        """Get receipt statistics."""
        store = self._get_store()
        stats = await _call_nonblocking(store, "get_stats")

        return json_response(
            {
                "stats": stats,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @staticmethod
    def _resolve_signing_public_key() -> tuple[str, str]:
        """Load the configured ODR signing key and return (public_key_pem, key_id).

        The private key never leaves this function: only the PEM of its public
        half and the derived key id are returned. Raises
        :class:`aragora.gauntlet.odr_signing.OdrSigningError` when no signing
        key is configured or it cannot be loaded — the endpoints fail closed
        (404) instead of ever generating a key on demand.
        """
        from aragora.gauntlet.odr_signing import (
            compute_key_id,
            load_signing_key_from_secrets,
            public_key_pem,
        )

        private_key = load_signing_key_from_secrets()
        return public_key_pem(private_key), compute_key_id(private_key.public_key())

    async def _get_signing_public_key(self) -> tuple[str, str] | None:
        """Return cached (public_key_pem, key_id), or None when unconfigured."""
        import time

        from aragora.gauntlet.odr_signing import OdrSigningError

        now = time.monotonic()
        cached = self._signing_key_cache
        if cached is not None:
            ttl = (
                self.SIGNING_KEY_CACHE_TTL_SECONDS
                if cached[1] is not None
                else self.SIGNING_KEY_NEGATIVE_CACHE_TTL_SECONDS
            )
            if now - cached[0] < ttl:
                return cached[1]

        try:
            resolved: tuple[str, str] | None = await asyncio.to_thread(
                self._resolve_signing_public_key
            )
        except OdrSigningError as e:
            # Fail closed: no key configured/loadable means 404, never a
            # generated key. Static message to callers; detail in logs only.
            # Negative-cached: these endpoints are public, and an uncached
            # failure would forward every request to Secrets Manager.
            logger.info("ODR signing key unavailable: %s", e)
            resolved = None

        self._signing_key_cache = (now, resolved)
        return resolved

    @api_endpoint(
        method="GET",
        path="/api/v2/receipts/signing-key",
        summary="Get ODR signing public key",
        description=(
            "Return the Ed25519 public key (PEM) used to sign Open Decision "
            "Receipts on this deployment, with the derived key id. This is a "
            "public trust anchor for offline verification via aragora-verify; "
            "no authentication is required. Returns 404 when no signing key "
            "is configured. Also served as raw PEM at "
            "/.well-known/aragora-odr-signing-key."
        ),
        tags=["Receipts"],
        operation_id="get_receipt_signing_key",
        responses={
            "200": {"description": "Signing public key returned"},
            "404": {"description": "No ODR signing key is configured"},
        },
    )
    async def _get_signing_key(self) -> HandlerResult:
        """Serve the ODR signing public key as a stable JSON envelope."""
        resolved = await self._get_signing_public_key()
        if resolved is None:
            return error_response("No ODR signing key is configured for this deployment", 404)

        pem, key_id = resolved
        return json_response(
            {
                "algorithm": "Ed25519",
                "key_id": key_id,
                "public_key_pem": pem,
            },
            headers={"Cache-Control": "public, max-age=300"},
        )

    async def _get_signing_key_pem(self) -> HandlerResult:
        """Serve the ODR signing public key as raw PEM (/.well-known route)."""
        resolved = await self._get_signing_public_key()
        if resolved is None:
            return error_response("No ODR signing key is configured for this deployment", 404)

        pem, key_id = resolved
        return HandlerResult(
            status_code=200,
            content_type="application/x-pem-file; charset=utf-8",
            body=pem.encode("utf-8"),
            headers={
                "Cache-Control": "public, max-age=300",
                "X-Aragora-Key-Id": key_id,
            },
        )

    @require_permission("receipts:read")
    async def _list_delivery_history(self, query_params: dict[str, str]) -> HandlerResult:
        """Return receipt delivery history in the legacy/frontend response shape."""
        limit = safe_query_int(query_params, "limit", default=50, max_val=100)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=1000000)
        receipt_id = (
            query_params.get("receipt_id") or query_params.get("receiptId") or ""
        ).strip() or None
        channel_type = (
            query_params.get("channel_type") or query_params.get("channel") or ""
        ).strip() or None
        status = (query_params.get("status") or "").strip() or None

        history = list(get_receipt_delivery_history_store())
        filtered = [
            item
            for item in history
            if (not receipt_id or item.get("receiptId") == receipt_id)
            and (not channel_type or item.get("channel") == channel_type)
            and (not status or item.get("status") == status)
        ]
        filtered.sort(
            key=lambda item: str(item.get("deliveredAt") or item.get("delivered_at") or ""),
            reverse=True,
        )
        paginated = filtered[offset : offset + limit]

        return json_response(
            {
                "deliveries": paginated,
                "total": len(filtered),
                "limit": limit,
                "offset": offset,
            }
        )

    def _record_delivery_history(
        self,
        *,
        receipt_id: str,
        channel_type: str,
        channel_id: str,
        workspace_id: str | None,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Record a lightweight delivery event for frontend history views."""
        delivery_result = result or {}
        delivered_at = datetime.now(timezone.utc).isoformat()
        destination_name = (
            delivery_result.get("channel_name")
            or delivery_result.get("channel")
            or delivery_result.get("email_sent_to")
            or channel_id
        )
        message_id = delivery_result.get("message_id") or delivery_result.get("message_ts")
        get_receipt_delivery_history_store().append(
            {
                "id": f"delivery-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{secrets.token_hex(4)}",
                "receiptId": receipt_id,
                "receipt_id": receipt_id,
                "channel": channel_type,
                "channel_type": channel_type,
                "destination": channel_id,
                "channel_id": channel_id,
                "destinationName": destination_name,
                "destination_name": destination_name,
                "deliveredAt": delivered_at,
                "delivered_at": delivered_at,
                "status": status,
                "workspaceId": workspace_id,
                "workspace_id": workspace_id,
                "messageId": message_id,
                "message_id": message_id,
                "errorMessage": error,
                "error_message": error,
            }
        )
        history = get_receipt_delivery_history_store()
        if len(history) > 1000:
            del history[:-1000]

    @require_permission("receipts:share")
    async def _send_to_channel(self, receipt_id: str, body: dict[str, Any]) -> HandlerResult:
        """
        Send a decision receipt to a specified channel.

        Body:
            channel_type: Channel type (slack, teams, email, discord)
            channel_id: Target channel/conversation ID
            workspace_id: Workspace/tenant ID (for Slack/Teams)
            options: Optional formatting options (compact, etc.)
        """
        channel_type = body.get("channel_type")
        channel_id = body.get("channel_id")
        workspace_id = body.get("workspace_id")
        options = body.get("options", {})

        if not channel_type:
            return error_response("channel_type is required", 400)
        if not channel_id:
            return error_response("channel_id is required", 400)

        # Get the receipt
        store = self._get_store()
        receipt = await _call_nonblocking(store, "get", receipt_id)
        if not receipt:
            return error_response("Receipt not found", 404)

        try:
            from aragora.channels.formatter import format_receipt_for_channel
            from aragora.export.decision_receipt import DecisionReceipt

            # Reconstruct DecisionReceipt from stored data
            decision_receipt = DecisionReceipt.from_dict(_extract_decision_receipt_payload(receipt))

            # Format the receipt for the channel
            formatted = format_receipt_for_channel(decision_receipt, channel_type, options)

            # Send to the channel based on type
            if channel_type == "slack":
                result = await self._send_to_slack(formatted, channel_id, workspace_id)
            elif channel_type == "teams":
                result = await self._send_to_teams(formatted, channel_id, workspace_id)
            elif channel_type == "email":
                result = await self._send_to_email(formatted, channel_id, options)
            elif channel_type == "discord":
                result = await self._send_to_discord(formatted, channel_id, options)
            else:
                return error_response(
                    f"Unsupported channel type: {channel_type}. "
                    "Supported: slack, teams, email, discord",
                    400,
                )

            self._record_delivery_history(
                receipt_id=receipt_id,
                channel_type=channel_type,
                channel_id=channel_id,
                workspace_id=workspace_id,
                status="success",
                result=result,
            )
            return json_response(
                {
                    "sent": True,
                    "receipt_id": receipt_id,
                    "channel_type": channel_type,
                    "channel_id": channel_id,
                    **result,
                }
            )

        except ImportError as e:
            self._record_delivery_history(
                receipt_id=receipt_id,
                channel_type=channel_type,
                channel_id=channel_id,
                workspace_id=workspace_id,
                status="failed",
                error=safe_error_message(e, f"channel {channel_type}"),
            )
            logger.exception("Missing dependency for channel %s: %s", channel_type, e)
            return error_response(safe_error_message(e, f"channel {channel_type}"), 501)
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            self._record_delivery_history(
                receipt_id=receipt_id,
                channel_type=channel_type,
                channel_id=channel_id,
                workspace_id=workspace_id,
                status="failed",
                error=safe_error_message(e, "receipt send"),
            )
            logger.exception("Failed to send receipt to channel: %s", e)
            return error_response(safe_error_message(e, "receipt send"), 500)

    async def _send_to_slack(
        self,
        formatted: dict[str, Any],
        channel_id: str,
        workspace_id: str | None,
    ) -> dict[str, Any]:
        """Send formatted receipt to Slack channel."""
        from aragora.storage.slack_workspace_store import get_slack_workspace_store

        if not workspace_id:
            raise ValueError("workspace_id is required for Slack")

        store = get_slack_workspace_store()
        workspace = await _call_nonblocking(store, "get", workspace_id)
        if not workspace:
            raise ValueError(f"Slack workspace not found: {workspace_id}")

        # Use Slack connector to send
        from aragora.connectors.chat.slack import SlackConnector

        connector = SlackConnector(
            token=workspace.access_token,
            signing_secret=workspace.signing_secret,
        )

        blocks = formatted.get("blocks", [])
        result = await connector.send_message(
            channel_id=channel_id,
            text="Decision Receipt",
            blocks=blocks,
        )

        return {"message_ts": result.timestamp, "channel": result.channel_id}

    async def _send_to_teams(
        self,
        formatted: dict[str, Any],
        channel_id: str,
        workspace_id: str | None,
    ) -> dict[str, Any]:
        """Send formatted receipt to Teams channel."""
        from aragora.storage.teams_workspace_store import get_teams_workspace_store

        if not workspace_id:
            raise ValueError("workspace_id (tenant_id) is required for Teams")

        store = get_teams_workspace_store()
        workspace = await _call_nonblocking(store, "get", workspace_id)
        if not workspace:
            raise ValueError(f"Teams workspace not found: {workspace_id}")

        # Use Teams connector to send
        from aragora.connectors.chat.teams import TeamsConnector

        connector = TeamsConnector(
            app_id=workspace.bot_id,
            app_password="",  # Bot Framework uses different auth flow
            service_url=workspace.service_url or "https://smba.trafficmanager.net/amer/",
        )

        # Send Adaptive Card via send_message with blocks
        card_body = formatted.get("body", [])
        result = await connector.send_message(
            channel_id=channel_id,
            text="Decision Receipt",
            blocks=card_body,
            conversation_id=channel_id,
        )

        return {"message_id": result.message_id}

    async def _send_to_email(
        self,
        formatted: dict[str, Any],
        email_address: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Send formatted receipt via email."""
        import os
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        smtp_host = os.environ.get("SMTP_HOST", "localhost")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        from_email = os.environ.get("SMTP_FROM", "aragora@localhost")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = formatted.get("subject", "Decision Receipt")
        msg["From"] = from_email
        msg["To"] = email_address

        # Add plain text and HTML parts
        if "plain_text" in formatted:
            msg.attach(MIMEText(formatted["plain_text"], "plain"))
        if "html" in formatted:
            msg.attach(MIMEText(formatted["html"], "html"))

        # Send email
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_user and smtp_password:
                server.starttls()
                server.login(smtp_user, smtp_password)
            server.send_message(msg)

        return {"email_sent_to": email_address}

    async def _send_to_discord(
        self,
        formatted: dict[str, Any],
        channel_id: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Send formatted receipt to Discord channel."""
        import os

        import httpx

        bot_token = os.environ.get("DISCORD_BOT_TOKEN")
        if not bot_token:
            raise ValueError("DISCORD_BOT_TOKEN environment variable required")

        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=formatted, headers=headers)
            resp.raise_for_status()
            result = resp.json()

        return {"message_id": result.get("id")}

    async def _get_formatted(
        self,
        receipt_id: str,
        channel_type: str,
        query_params: dict[str, str],
    ) -> HandlerResult:
        """
        Get receipt formatted for a specific channel type.

        Returns the formatted payload without sending it.
        """
        store = self._get_store()
        receipt = await _call_nonblocking(store, "get", receipt_id)

        if not receipt:
            return error_response("Receipt not found", 404)

        options = {
            "compact": query_params.get("compact", "").lower() == "true",
        }

        try:
            from aragora.channels.formatter import format_receipt_for_channel
            from aragora.export.decision_receipt import DecisionReceipt

            decision_receipt = DecisionReceipt.from_dict(_extract_decision_receipt_payload(receipt))
            formatted = format_receipt_for_channel(decision_receipt, channel_type, options)

            return json_response(
                {
                    "receipt_id": receipt_id,
                    "channel_type": channel_type,
                    "formatted": formatted,
                }
            )

        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except (ImportError, KeyError, TypeError, OSError) as e:
            logger.exception("Failed to format receipt: %s", e)
            return error_response(safe_error_message(e, "receipt formatting"), 500)

    @require_permission("receipts:read")
    async def _get_retention_status(self) -> HandlerResult:
        """Get retention status for GDPR compliance. Endpoint: GET /api/v2/receipts/retention-status"""
        store = self._get_store()
        status = await _call_nonblocking(store, "get_retention_status")
        return json_response(status)

    @require_permission("receipts:read")
    async def _get_dsar(self, user_id: str, query_params: dict[str, str]) -> HandlerResult:
        """Handle GDPR DSAR. Endpoint: GET /api/v2/receipts/dsar/{user_id}"""
        if not user_id or len(user_id) < 3:
            return error_response("Valid user_id required (minimum 3 characters)", 400)

        store = self._get_store()
        limit = safe_query_int(query_params, "limit", default=100, max_val=1000)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=1000000)

        receipts, total = await _call_nonblocking(
            store,
            "get_by_user",
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        receipt_data = [r.to_full_dict() for r in receipts]

        return json_response(
            {
                "dsar_request": {
                    "user_id": user_id,
                    "request_type": "data_subject_access_request",
                    "gdpr_article": "Article 15 - Right of access",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                "receipts": receipt_data,
                "pagination": {"limit": limit, "offset": offset, "total": total},
                "summary": {"total_receipts": total, "returned_receipts": len(receipts)},
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v2/receipts/{receipt_id}/share",
        summary="Create shareable link",
        description="Create a time-limited shareable link for a receipt with optional access limits.",
        tags=["Receipts", "Sharing"],
        parameters=[
            {"name": "receipt_id", "in": "path", "required": True, "schema": {"type": "string"}}
        ],
        responses={
            "200": {"description": "Share link created"},
            "404": {"description": "Receipt not found"},
        },
    )
    @require_permission("receipts:share")
    async def _share_receipt(self, receipt_id: str, body: dict[str, Any]) -> HandlerResult:
        """
        Create a shareable link for a receipt.

        Body:
            expires_in_hours: Hours until link expires (default 24, max 720 = 30 days)
            max_accesses: Maximum number of accesses (optional, None = unlimited)

        Returns:
            Share URL and token details
        """
        store = self._get_store()
        receipt = await _call_nonblocking(store, "get", receipt_id)

        if not receipt:
            return error_response("Receipt not found", 404)

        # Parse options
        expires_in_hours = safe_query_int(body, "expires_in_hours", default=24, max_val=720)
        max_accesses = body.get("max_accesses")

        # Generate share token
        token = secrets.token_urlsafe(24)
        expires_at = datetime.now(timezone.utc).timestamp() + (expires_in_hours * 3600)

        # Store share link
        share_store = self._get_share_store()
        await _call_nonblocking(
            share_store,
            "save",
            token=token,
            receipt_id=receipt_id,
            expires_at=expires_at,
            max_accesses=max_accesses,
        )

        # Emit webhook notification
        share_url = f"/api/v2/receipts/share/{token}"
        try:
            from aragora.integrations.receipt_webhooks import ReceiptWebhookNotifier

            notifier = ReceiptWebhookNotifier()
            debate_id = getattr(receipt, "debate_id", "") or ""
            notifier.notify_receipt_shared(
                receipt_id=receipt_id,
                debate_id=debate_id,
                share_url=share_url,
                expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
            )
        except ImportError:
            logger.debug("Receipt webhooks not available")

        return json_response(
            {
                "success": True,
                "receipt_id": receipt_id,
                "share_url": share_url,
                "token": token,
                "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
                "max_accesses": max_accesses,
            }
        )

    async def _get_shared_receipt(
        self,
        token: str,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HandlerResult:
        """
        Access a receipt via share token.

        This is a public endpoint - no authentication required.
        Returns HTML by default for browsers, JSON for API clients.
        """
        query_params = query_params or {}
        headers = headers or {}
        share_store = self._get_share_store()
        share_status, share_info = await _consume_share_access(share_store, token)
        if share_status == "not_found":
            return error_response("Share link not found", 404)
        if share_status == "expired":
            return error_response("Share link has expired", 410)
        if share_status == "limit_reached":
            return error_response("Share link access limit reached", 410)
        if share_info is None:
            # Defensive: every non-"ok" status is handled above, and "ok"
            # always carries share_info.
            return error_response("Share link not found", 404)

        # Get receipt
        store = self._get_store()
        receipt = await _call_nonblocking(store, "get", share_info["receipt_id"])

        if not receipt:
            return error_response("Receipt not found", 404)

        # Determine format: HTML for browsers, JSON for API clients
        fmt = query_params.get("format", "").lower()
        accept = headers.get("Accept", headers.get("accept", ""))
        wants_html = fmt == "html" or (not fmt and "text/html" in accept)

        if wants_html:
            html_content = _render_shared_receipt_html(receipt, token)
            return HandlerResult(
                status_code=200,
                body=html_content.encode("utf-8"),
                content_type="text/html; charset=utf-8",
            )

        return json_response(
            {
                "receipt": receipt.to_full_dict(),
                "shared": True,
                "access_count": share_info.get("access_count", 0),
            }
        )

    @require_permission("receipts:sign")
    async def _sign_batch(self, body: dict[str, Any]) -> HandlerResult:
        """
        Batch sign multiple receipts.

        Body:
            receipt_ids: List of receipt IDs to sign (max 100)
            algorithm: Signing algorithm (hmac-sha256, rsa-sha256, ed25519)
            signatory: Optional signatory information for compliance audits
                - name: Signatory name (required if signatory provided)
                - email: Signatory email (required if signatory provided)
                - title: Job title (optional)
                - organization: Organization name (optional)
                - role: Role in decision process, e.g., "Architect" (optional)
                - department: Department name (optional)
        """
        receipt_ids = body.get("receipt_ids", [])
        algorithm = body.get("algorithm", "hmac-sha256")
        signatory_data = body.get("signatory")

        if not receipt_ids:
            return error_response("receipt_ids required", 400)

        if len(receipt_ids) > 100:
            return error_response("Maximum 100 receipts per batch", 400)

        store = self._get_store()
        results = []
        signed_count = 0
        failed_count = 0
        skipped_count = 0

        try:
            from aragora.gauntlet.signing import (
                Ed25519Signer,
                HMACSigner,
                ReceiptSigner,
                RSASigner,
                SignatoryInfo,
                SigningBackend,
            )

            # Parse signatory info if provided
            signatory: SignatoryInfo | None = None
            if signatory_data:
                if not signatory_data.get("name") or not signatory_data.get("email"):
                    return error_response(
                        "signatory.name and signatory.email are required when signatory is provided",
                        400,
                    )
                signatory = SignatoryInfo(
                    name=signatory_data["name"],
                    email=signatory_data["email"],
                    title=signatory_data.get("title"),
                    organization=signatory_data.get("organization"),
                    role=signatory_data.get("role"),
                    department=signatory_data.get("department"),
                )

            # Create backend based on algorithm
            backend: SigningBackend
            if algorithm == "rsa-sha256":
                backend = RSASigner.generate_keypair()
            elif algorithm == "ed25519":
                backend = Ed25519Signer.generate_keypair()
            else:
                # Default to HMAC-SHA256
                backend = HMACSigner.from_env()

            signer = ReceiptSigner(backend=backend)

            for receipt_id in receipt_ids:
                receipt = await _call_nonblocking(store, "get", receipt_id)

                if not receipt:
                    results.append({"receipt_id": receipt_id, "status": "not_found"})
                    failed_count += 1
                    continue

                # Check if already signed
                if await _call_nonblocking(store, "get_signature", receipt_id):
                    results.append({"receipt_id": receipt_id, "status": "already_signed"})
                    skipped_count += 1
                    continue

                try:
                    # Sign the receipt with optional signatory info
                    signature = signer.sign(receipt.data, signatory=signatory)
                    await _call_nonblocking(
                        store, "store_signature", receipt_id, signature, algorithm
                    )
                    results.append({"receipt_id": receipt_id, "status": "signed"})
                    signed_count += 1
                except (ValueError, TypeError, OSError) as e:
                    logger.warning("Failed to sign receipt %s: %s", receipt_id, e)
                    results.append(
                        {"receipt_id": receipt_id, "status": "error", "error": "Signing failed"}
                    )
                    failed_count += 1

        except ImportError:
            return error_response(
                "Signing module not available. Install cryptographic dependencies with: "
                "pip install aragora[crypto]",
                501,
            )

        return json_response(
            {
                "results": results,
                "summary": {
                    "total": len(receipt_ids),
                    "signed": signed_count,
                    "skipped": skipped_count,
                    "failed": failed_count,
                },
            }
        )

    @require_permission("receipts:export")
    async def _batch_export(self, body: dict[str, Any]) -> HandlerResult:
        """
        Batch export multiple receipts to a ZIP file.

        Body:
            receipt_ids: List of receipt IDs to export (max 100)
            format: Export format (json, html, markdown, csv)
        """
        receipt_ids = body.get("receipt_ids", [])
        export_format = body.get("format", "json").lower()

        if not receipt_ids:
            return error_response("receipt_ids required", 400)

        if len(receipt_ids) > 100:
            return error_response("Maximum 100 receipts per batch", 400)

        if export_format not in ("json", "html", "markdown", "md", "csv"):
            return error_response(
                f"Unsupported format: {export_format}. Supported: json, html, markdown, csv",
                400,
            )

        store = self._get_store()

        # Create ZIP in memory
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            exported_count = 0
            failed_ids = []

            for receipt_id in receipt_ids:
                receipt = await _call_nonblocking(store, "get", receipt_id)

                if not receipt:
                    failed_ids.append(receipt_id)
                    continue

                try:
                    from aragora.export.decision_receipt import DecisionReceipt

                    decision_receipt = DecisionReceipt.from_dict(
                        _extract_decision_receipt_payload(receipt)
                    )

                    # Determine file extension
                    if export_format == "json":
                        content = decision_receipt.to_json(indent=2)
                        ext = "json"
                    elif export_format in ("html",):
                        content = decision_receipt.to_html()
                        ext = "html"
                    elif export_format in ("markdown", "md"):
                        content = decision_receipt.to_markdown()
                        ext = "md"
                    elif export_format == "csv":
                        content = decision_receipt.to_csv()
                        ext = "csv"
                    else:
                        content = decision_receipt.to_json(indent=2)
                        ext = "json"

                    filename = f"receipt-{receipt_id}.{ext}"
                    zip_file.writestr(filename, content)
                    exported_count += 1

                except (ImportError, KeyError, ValueError, TypeError, OSError) as e:
                    logger.warning("Failed to export receipt %s: %s", receipt_id, e)
                    failed_ids.append(receipt_id)

            # Add manifest
            manifest = {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "format": export_format,
                "total_requested": len(receipt_ids),
                "exported": exported_count,
                "failed": failed_ids,
            }
            import json

            zip_file.writestr("manifest.json", json.dumps(manifest, indent=2))

        zip_buffer.seek(0)
        zip_bytes = zip_buffer.read()

        return HandlerResult(
            status_code=200,
            content_type="application/zip",
            body=zip_bytes,
            headers={
                "Content-Disposition": "attachment; filename=receipts-export.zip",
            },
        )

    def _parse_timestamp(self, value: str | None) -> float | None:
        """Parse timestamp from string (ISO date or unix timestamp)."""
        if not value:
            return None

        try:
            # Try as unix timestamp
            return float(value)
        except (ValueError, TypeError):
            pass

        try:
            # Try as ISO date
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, AttributeError):
            pass

        return None


# Handler factory function for registration
def create_receipts_handler(server_context: dict[str, Any]) -> ReceiptsHandler:
    """Factory function for handler registration."""
    return ReceiptsHandler(server_context)
