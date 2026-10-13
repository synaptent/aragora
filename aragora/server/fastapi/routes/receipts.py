"""
Receipt Endpoints (FastAPI v2).

Provides async receipt management endpoints:
- List receipts with pagination
- Get receipt by ID
- Create receipt share links
- Access shared receipts
- Verify receipt integrity
- Export receipt in various formats (json, markdown, sarif)
- Batch verify multiple receipts
- Batch export multiple receipts
- Search receipts by query/date/debate_id
- Receipt statistics
"""

from __future__ import annotations

import asyncio
import inspect
import io
import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from enum import Enum
from inspect import signature
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..dependencies.auth import require_permission
from ..middleware.error_handling import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["Receipts"])


# =============================================================================
# Pydantic Models
# =============================================================================


class ExportFormat(str, Enum):
    """Supported export formats."""

    json = "json"
    html = "html"
    markdown = "markdown"
    md = "md"
    pdf = "pdf"
    sarif = "sarif"


class ReceiptSummary(BaseModel):
    """Summary of a receipt for list views."""

    receipt_id: str
    gauntlet_id: str
    timestamp: str | None = None
    input_summary: str = ""
    verdict: str = ""
    confidence: float = 0.0
    risk_level: str = "MEDIUM"
    risk_score: float = 0.0
    robustness_score: float = 0.0
    findings_count: int = 0
    checksum: str = ""

    model_config = {"extra": "allow"}


class ReceiptListResponse(BaseModel):
    """Response for receipt listing."""

    receipts: list[ReceiptSummary]
    total: int
    limit: int
    offset: int


class ReceiptDetail(BaseModel):
    """Full receipt details."""

    receipt_id: str
    gauntlet_id: str
    timestamp: str | None = None
    input_summary: str = ""
    input_type: str = "spec"
    schema_version: str = "1.0"
    verdict: str = ""
    confidence: float = 0.0
    risk_level: str = "MEDIUM"
    risk_score: float = 0.0
    robustness_score: float = 0.0
    coverage_score: float = 0.0
    verification_coverage: float = 0.0
    findings: list[dict[str, Any]] = Field(default_factory=list)
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    mitigations: list[str] = Field(default_factory=list)
    dissenting_views: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_tensions: list[str] = Field(default_factory=list)
    verified_claims: list[dict[str, Any]] = Field(default_factory=list)
    unverified_claims: list[str] = Field(default_factory=list)
    agents_involved: list[str] = Field(default_factory=list)
    rounds_completed: int = 0
    duration_seconds: float = 0.0
    audit_trail_id: str | None = None
    checksum: str = ""

    model_config = {"extra": "allow"}


class VerifyResponse(BaseModel):
    """Response for receipt verification."""

    receipt_id: str
    verified: bool
    integrity_valid: bool
    checksum_match: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ExportResponse(BaseModel):
    """Response for receipt export."""

    receipt_id: str
    format: str
    content: str


class BatchVerifyRequest(BaseModel):
    """Request body for POST /receipts/batch-verify."""

    receipt_ids: list[str] = Field(
        ..., min_length=1, max_length=100, description="Receipt IDs to verify (max 100)"
    )


class BatchVerifyResult(BaseModel):
    """Result for a single receipt in batch verification."""

    receipt_id: str
    verified: bool
    integrity_valid: bool
    error: str | None = None


class BatchVerifyResponse(BaseModel):
    """Response for batch verification."""

    results: list[BatchVerifyResult]
    total: int
    verified_count: int
    failed_count: int


class BatchExportRequest(BaseModel):
    """Request body for POST /receipts/batch-export."""

    receipt_ids: list[str] = Field(
        ..., min_length=1, max_length=100, description="Receipt IDs to export (max 100)"
    )
    format: str = Field(
        "json",
        description="Export format (json, html, markdown, md, csv, sarif, pdf). PDF batch exports require the ZIP/raw response.",
    )
    raw: bool = Field(
        True,
        description="Keep the legacy ZIP archive response. Set false to return a JSON item bundle.",
    )


class BatchExportItem(BaseModel):
    """A single exported receipt in the batch."""

    receipt_id: str
    format: str
    content: str


class BatchExportResponse(BaseModel):
    """Response for batch export."""

    items: list[BatchExportItem]
    total_requested: int
    exported_count: int
    failed_ids: list[str] = Field(default_factory=list)


class ReceiptSearchResponse(BaseModel):
    """Response for receipt search."""

    receipts: list[ReceiptSummary]
    query: str
    total: int
    limit: int
    offset: int


class ReceiptStatsResponse(BaseModel):
    """Response for receipt statistics."""

    total: int = 0
    verified: int = 0
    delivered: int = 0
    pending: int = 0
    failed: int = 0
    delivery_rate: float | None = None
    by_verdict: dict[str, int] = Field(default_factory=dict)
    by_risk_level: dict[str, int] = Field(default_factory=dict)
    by_framework: dict[str, int] = Field(default_factory=dict)
    generated_at: str = ""


class CreateShareRequest(BaseModel):
    """Request body for POST /receipts/{receipt_id}/share."""

    expires_in_hours: int = Field(
        24,
        ge=1,
        le=720,
        description="Hours until the share link expires (max 30 days)",
    )
    max_accesses: int | None = Field(
        None,
        ge=1,
        description="Optional maximum number of times the link can be accessed",
    )


class ShareReceiptResponse(BaseModel):
    """Response for receipt share-link creation."""

    success: bool
    receipt_id: str
    share_url: str
    token: str
    expires_at: str
    max_accesses: int | None = None


class SharedReceiptResponse(BaseModel):
    """JSON response for a publicly shared receipt."""

    receipt: dict[str, Any]
    shared: bool
    access_count: int


class SignatureVerifyResponse(BaseModel):
    """Response for receipt signature verification."""

    receipt_id: str
    signature_valid: bool
    algorithm: str | None = None
    key_id: str | None = None
    signed_at: float | None = None
    verification_timestamp: str
    error: str | None = None


class FormattedReceiptResponse(BaseModel):
    """Response for receipt channel formatting."""

    receipt_id: str
    channel_type: str
    formatted: dict[str, Any]


class SendToChannelRequest(BaseModel):
    """Request body for POST /receipts/{receipt_id}/send-to-channel."""

    channel_type: str = Field(..., min_length=1)
    channel_id: str = Field(..., min_length=1)
    workspace_id: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class SendToChannelResponse(BaseModel):
    """Response for receipt delivery requests."""

    sent: bool
    receipt_id: str
    channel_type: str
    channel_id: str

    model_config = {"extra": "allow"}


# =============================================================================
# Dependencies
# =============================================================================


async def get_receipt_store(request: Request):
    """Dependency to get the receipt store.

    Tries the storage.receipt_store from app context first,
    then falls back to the global receipt store.
    """
    ctx = getattr(request.app.state, "context", None)
    if ctx:
        store = ctx.get("receipt_store")
        if store:
            return store

    # Fall back to global receipt store
    try:
        from aragora.storage.receipt_store import get_receipt_store as _get_store

        return _get_store()
    except (ImportError, RuntimeError, OSError, ValueError) as e:
        logger.warning("Receipt store not available: %s", e)
        raise HTTPException(status_code=503, detail="Receipt store not available")


async def get_receipt_share_store(request: Request):
    """Dependency to get the receipt share store."""
    ctx = getattr(request.app.state, "context", None)
    if ctx:
        store = ctx.get("receipt_share_store")
        if store:
            return store

    try:
        from aragora.storage.receipt_share_store import (
            get_receipt_share_store as _get_share_store,
        )

        return _get_share_store()
    except (ImportError, RuntimeError, OSError, ValueError) as e:
        logger.warning("Receipt share store not available: %s", e)
        raise HTTPException(status_code=503, detail="Receipt share store not available")


async def _call_store_method(store: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Run receipt store methods without blocking the FastAPI event loop."""

    method = getattr(store, method_name)
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)

    result = await asyncio.to_thread(method, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _store_accepts_keyword_argument(store: Any, method_name: str, keyword: str) -> bool:
    """Return whether a store method accepts a named keyword or arbitrary kwargs."""

    method = getattr(store, method_name, None)
    if method is None:
        return False

    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return True

    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == keyword
        for parameter in parameters
    )


async def _consume_share_access(share_store: Any, token: str) -> tuple[str, dict[str, Any] | None]:
    """Consume one receipt-share access, preferring atomic store support."""
    consume_result = None
    consume_access = getattr(share_store, "consume_access", None)
    if callable(consume_access):
        consume_result = await _call_store_method(share_store, "consume_access", token)
        if isinstance(consume_result, dict) and "status" in consume_result:
            return consume_result["status"], consume_result.get("share_info")

    share_info = await _call_store_method(share_store, "get_by_token", token)
    if not share_info:
        return "not_found", None

    expires_at = share_info.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc).timestamp():
        return "expired", share_info

    max_accesses = share_info.get("max_accesses")
    access_count = share_info.get("access_count", 0)
    if max_accesses and access_count >= max_accesses:
        return "limit_reached", share_info

    await _call_store_method(share_store, "increment_access", token)
    updated_share_info = dict(share_info)
    updated_share_info["access_count"] = access_count + 1
    return "ok", updated_share_info


def _build_decision_receipt(receipt: Any) -> Any:
    """Reconstruct a DecisionReceipt from stored receipt payloads."""
    from aragora.export.decision_receipt import DecisionReceipt

    payload = _extract_decision_receipt_payload(receipt)
    if not payload:
        raise ValueError("Cannot reconstruct receipt payload")
    return DecisionReceipt.from_dict(payload)


def _render_receipt_export_content(receipt: Any, export_format: str) -> tuple[str, str, str]:
    """Render exported receipt content and a file extension for batch bundles."""
    normalized = export_format.lower()

    if normalized == "json":
        return receipt.to_json(), "json", "json"
    if normalized == "html":
        return receipt.to_html(), "html", "html"
    if normalized in ("markdown", "md"):
        return receipt.to_markdown(), "markdown", "md"
    if normalized == "csv":
        return receipt.to_csv(), "csv", "csv"
    if normalized == "sarif":
        return receipt.to_sarif_json(), "sarif", "sarif.json"

    raise ValueError(f"Unsupported export format: {export_format}")


def _build_batch_export_zip(
    *,
    archive_items: list[tuple[str, str, str | bytes]],
    export_format: str,
    total_requested: int,
    failed_ids: list[str],
) -> bytes:
    """Build a ZIP bundle matching the legacy receipt batch-export surface."""
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for receipt_id, extension, content in archive_items:
            zip_file.writestr(f"receipt-{receipt_id}.{extension}", content)

        manifest = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "format": export_format,
            "total_requested": total_requested,
            "exported": len(archive_items),
            "failed": failed_ids,
        }
        zip_file.writestr("manifest.json", json.dumps(manifest, indent=2))

    zip_buffer.seek(0)
    return zip_buffer.read()


# =============================================================================
# Helpers
# =============================================================================


def _coerce_int(value: Any) -> int | None:
    """Return an int for numeric-like values, preserving zero."""

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    """Return a float for numeric-like values, preserving zero."""

    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _derive_delivery_aggregates_from_history() -> tuple[int, int, int, float | None]:
    """Summarize the shared delivery-history bridge for truthful receipt metrics."""

    from aragora.server.handlers.utils.receipt_delivery_history import (
        get_receipt_delivery_history_store,
    )

    delivered = 0
    pending = 0
    failed = 0

    for item in get_receipt_delivery_history_store():
        if item.get("is_test"):
            continue
        if not (item.get("receipt_id") or item.get("receiptId")):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status in {"delivered", "success"}:
            delivered += 1
        elif status in {"failed", "error"}:
            failed += 1
        else:
            pending += 1

    delivery_rate = delivered / (delivered + failed) if delivered + failed > 0 else None
    return delivered, pending, failed, delivery_rate


def _resolve_delivery_aggregates(stats: dict[str, Any]) -> tuple[int, int, int, float | None]:
    """Prefer store-provided delivery aggregates, then backfill from history."""

    delivered = _coerce_int(stats.get("delivered"))
    if delivered is None:
        delivered = _coerce_int(stats.get("delivered_count"))

    pending = _coerce_int(stats.get("pending"))
    if pending is None:
        pending = _coerce_int(stats.get("pending_count"))

    failed = _coerce_int(stats.get("failed"))
    if failed is None:
        failed = _coerce_int(stats.get("failed_count"))

    delivery_rate = _coerce_float(stats.get("delivery_rate"))
    if delivery_rate is None:
        delivery_rate = _coerce_float(stats.get("delivery_success_rate"))

    if None not in (delivered, pending, failed, delivery_rate):
        return delivered or 0, pending or 0, failed or 0, delivery_rate

    history_delivered, history_pending, history_failed, history_delivery_rate = (
        _derive_delivery_aggregates_from_history()
    )

    resolved_delivered = delivered if delivered is not None else history_delivered
    resolved_pending = pending if pending is not None else history_pending
    resolved_failed = failed if failed is not None else history_failed

    if delivery_rate is None:
        total_attempted = resolved_delivered + resolved_failed
        delivery_rate = (
            resolved_delivered / total_attempted if total_attempted > 0 else history_delivery_rate
        )

    return (
        resolved_delivered,
        resolved_pending,
        resolved_failed,
        delivery_rate,
    )


def _to_receipt_summary(r: Any) -> ReceiptSummary:
    """Convert a receipt dict or object to a ReceiptSummary."""
    data = _extract_receipt_payload(r)
    if data:
        return ReceiptSummary(
            receipt_id=data.get("receipt_id", ""),
            gauntlet_id=data.get("gauntlet_id", ""),
            timestamp=data.get("timestamp"),
            input_summary=data.get("input_summary", ""),
            verdict=data.get("verdict", ""),
            confidence=data.get("confidence", 0.0),
            risk_level=data.get("risk_level", "MEDIUM"),
            risk_score=data.get("risk_score", 0.0),
            robustness_score=data.get("robustness_score", 0.0),
            findings_count=len(data.get("findings", [])),
            checksum=data.get("checksum", ""),
        )
    return ReceiptSummary(
        receipt_id=getattr(r, "receipt_id", ""),
        gauntlet_id=getattr(r, "gauntlet_id", ""),
        timestamp=str(getattr(r, "timestamp", "")) if hasattr(r, "timestamp") else None,
        input_summary=getattr(r, "input_summary", ""),
        verdict=getattr(r, "verdict", ""),
        confidence=getattr(r, "confidence", 0.0),
        risk_level=getattr(r, "risk_level", "MEDIUM"),
        risk_score=getattr(r, "risk_score", 0.0),
        robustness_score=getattr(r, "robustness_score", 0.0),
        findings_count=len(getattr(r, "findings", [])),
        checksum=getattr(r, "checksum", ""),
    )


def _extract_receipt_payload(receipt: Any) -> dict[str, Any]:
    """Normalize receipt payloads from dict, StoredReceipt, or legacy objects."""
    if isinstance(receipt, dict):
        payload: dict[str, Any] = dict(receipt)
        nested = receipt.get("data")
        if isinstance(nested, dict):
            payload.update(nested)
        return payload

    if hasattr(receipt, "to_full_dict"):
        full_payload = receipt.to_full_dict()
        if isinstance(full_payload, dict):
            return full_payload

    payload = {}
    nested = getattr(receipt, "data", None)
    if isinstance(nested, dict):
        payload.update(nested)

    for field in (
        "receipt_id",
        "gauntlet_id",
        "debate_id",
        "created_at",
        "expires_at",
        "verdict",
        "confidence",
        "risk_level",
        "risk_score",
        "audit_trail_id",
        "checksum",
    ):
        if field not in payload and hasattr(receipt, field):
            payload[field] = getattr(receipt, field)

    if payload:
        return payload

    if hasattr(receipt, "to_dict"):
        plain = receipt.to_dict()
        if isinstance(plain, dict):
            return plain

    return {}


def _extract_decision_receipt_payload(receipt: Any) -> dict[str, Any]:
    """Extract only the original decision-receipt payload used for reconstruction."""
    if isinstance(receipt, dict):
        nested = receipt.get("data")
        if isinstance(nested, dict):
            payload = dict(nested)
        else:
            payload = dict(receipt)
    else:
        nested = getattr(receipt, "data", None)
        if isinstance(nested, dict):
            payload = dict(nested)
        elif hasattr(receipt, "to_dict"):
            plain = receipt.to_dict()
            if isinstance(plain, dict):
                payload = plain
            else:
                payload = _extract_receipt_payload(receipt)
        else:
            payload = _extract_receipt_payload(receipt)

    if not payload:
        return {}

    if hasattr(receipt, "to_dict"):
        plain = receipt.to_dict()
        if isinstance(plain, dict):
            for key in ("receipt_id", "gauntlet_id", "timestamp", "checksum"):
                payload.setdefault(key, plain.get(key))

    try:
        from aragora.export.decision_receipt import DecisionReceipt

        allowed_fields = signature(DecisionReceipt).parameters
        return {key: value for key, value in payload.items() if key in allowed_fields}
    except (ImportError, ValueError, TypeError):
        return payload


def _reconstruct_decision_receipt(receipt: Any) -> Any | None:
    """Rebuild a DecisionReceipt when callers only have stored payload data."""
    if hasattr(receipt, "to_html"):
        return receipt

    payload = _extract_decision_receipt_payload(receipt)
    if not payload:
        return None

    try:
        from aragora.export.decision_receipt import DecisionReceipt

        return DecisionReceipt.from_dict(payload)
    except (ImportError, ValueError, TypeError, KeyError):
        return None


def _render_shared_receipt_html(receipt: Any, token: str) -> str:
    """Render a lightweight standalone HTML view for shared receipts."""
    title = getattr(receipt, "receipt_id", None) or token
    base_url = os.environ.get("ARAGORA_BASE_URL", "https://aragora.ai").rstrip("/")
    share_url = f"{base_url}/api/v2/receipts/share/{token}"
    if hasattr(receipt, "to_html"):
        body = receipt.to_html()
    else:
        body = "<html><body><p>Receipt preview unavailable.</p></body></html>"

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta property="og:title" content="Aragora Decision Receipt {title}" />
    <meta property="og:type" content="article" />
    <meta property="og:url" content="{share_url}" />
    <link rel="canonical" href="{share_url}" />
    <title>Aragora Decision Receipt {title}</title>
  </head>
  <body>
{body}
  </body>
</html>"""


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/receipts", response_model=ReceiptListResponse)
async def list_receipts(
    request: Request,
    limit: int = Query(50, ge=1, le=100, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    verdict: str | None = Query(None, description="Filter by verdict"),
    debate_id: str | None = Query(None, description="Filter by debate ID"),
    store=Depends(get_receipt_store),
) -> ReceiptListResponse:
    """List all receipts with pagination."""
    try:
        filter_kwargs: dict[str, Any] = {}
        if verdict:
            filter_kwargs["verdict"] = verdict
        if debate_id:
            filter_kwargs["debate_id"] = debate_id

        if hasattr(store, "list_recent"):
            list_recent_kwargs: dict[str, Any] = {
                "limit": limit,
                "offset": offset,
                "verdict": verdict,
            }
            if debate_id and _store_accepts_keyword_argument(store, "list_recent", "debate_id"):
                list_recent_kwargs["debate_id"] = debate_id

            results = await _call_store_method(
                store,
                "list_recent",
                **list_recent_kwargs,
            )
            if debate_id and "debate_id" not in list_recent_kwargs:
                results = [
                    receipt
                    for receipt in results
                    if _extract_receipt_payload(receipt).get("debate_id") == debate_id
                ]
        elif hasattr(store, "list"):
            results = await _call_store_method(
                store, "list", limit=limit, offset=offset, **filter_kwargs
            )
        elif hasattr(store, "list_all"):
            all_receipts = await _call_store_method(store, "list_all")
            if verdict:
                all_receipts = [
                    r
                    for r in all_receipts
                    if (r.get("verdict") if isinstance(r, dict) else getattr(r, "verdict", ""))
                    == verdict
                ]
            if debate_id:
                all_receipts = [
                    receipt
                    for receipt in all_receipts
                    if _extract_receipt_payload(receipt).get("debate_id") == debate_id
                ]
            results = all_receipts[offset : offset + limit]
        else:
            results = []

        if hasattr(store, "count"):
            count_kwargs: dict[str, Any] = {"verdict": verdict}
            if debate_id and _store_accepts_keyword_argument(store, "count", "debate_id"):
                count_kwargs["debate_id"] = debate_id
            total = await _call_store_method(store, "count", **count_kwargs)
            if debate_id and "debate_id" not in count_kwargs and hasattr(store, "list_all"):
                all_receipts = await _call_store_method(store, "list_all")
                total = sum(
                    1
                    for receipt in all_receipts
                    if _extract_receipt_payload(receipt).get("debate_id") == debate_id
                    and (not verdict or _extract_receipt_payload(receipt).get("verdict") == verdict)
                )
        else:
            total = len(results)

        receipts = [_to_receipt_summary(r) for r in results]

        return ReceiptListResponse(receipts=receipts, total=total, limit=limit, offset=offset)

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error listing receipts: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list receipts")


# --- Fixed-path routes MUST come before {receipt_id} parameterized routes ---


@router.get("/receipts/search", response_model=ReceiptSearchResponse)
async def search_receipts(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(50, ge=1, le=100, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    verdict: str | None = Query(None, description="Filter by verdict"),
    risk_level: str | None = Query(None, description="Filter by risk level"),
    debate_id: str | None = Query(None, description="Filter by debate ID"),
    date_from: str | None = Query(None, description="Start date (ISO format)"),
    date_to: str | None = Query(None, description="End date (ISO format)"),
    store=Depends(get_receipt_store),
) -> ReceiptSearchResponse:
    """Search receipts by query, date range, debate ID, and other filters."""
    try:
        results: list[Any] = []
        total = 0

        search_kwargs: dict[str, Any] = {"limit": limit, "offset": offset}
        if verdict:
            search_kwargs["verdict"] = verdict
        if risk_level:
            search_kwargs["risk_level"] = risk_level
        if debate_id:
            search_kwargs["debate_id"] = debate_id
        if date_from:
            search_kwargs["date_from"] = date_from
        if date_to:
            search_kwargs["date_to"] = date_to

        if hasattr(store, "search"):
            raw_results = await _call_store_method(store, "search", query=q, **search_kwargs)
            results = list(raw_results)
            if hasattr(store, "search_count"):
                total = await _call_store_method(
                    store,
                    "search_count",
                    query=q,
                    verdict=verdict,
                    risk_level=risk_level,
                )
            else:
                total = len(results)
        elif hasattr(store, "list_all"):
            all_receipts = await _call_store_method(store, "list_all")
            query_lower = q.lower()
            for r in all_receipts:
                data = r if isinstance(r, dict) else (r.to_dict() if hasattr(r, "to_dict") else {})
                if query_lower in str(data).lower():
                    results.append(data)
            total = len(results)
            results = results[offset : offset + limit]

        receipts = [_to_receipt_summary(r) for r in results]

        return ReceiptSearchResponse(
            receipts=receipts, query=q, total=total, limit=limit, offset=offset
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error searching receipts: %s", e)
        raise HTTPException(status_code=500, detail="Failed to search receipts")


@router.get("/receipts/stats", response_model=ReceiptStatsResponse)
async def get_receipt_stats(
    request: Request,
    store=Depends(get_receipt_store),
) -> ReceiptStatsResponse:
    """Get receipt statistics including counts by verdict and risk level."""
    try:
        stats: dict[str, Any] = {}

        if hasattr(store, "get_stats"):
            raw_stats = await _call_store_method(store, "get_stats")
            if isinstance(raw_stats, dict):
                stats = raw_stats

        delivered, pending, failed, delivery_rate = _resolve_delivery_aggregates(stats)

        return ReceiptStatsResponse(
            total=stats.get("total", stats.get("total_count", 0)),
            verified=stats.get("verified", stats.get("verified_count", 0)),
            delivered=delivered,
            pending=pending,
            failed=failed,
            delivery_rate=delivery_rate,
            by_verdict=stats.get("by_verdict", {}),
            by_risk_level=stats.get("by_risk_level", {}),
            by_framework=stats.get("by_framework", {}),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting receipt stats: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get receipt stats")


@router.get("/receipts/share/{token}", response_model=SharedReceiptResponse)
async def get_shared_receipt(
    token: str,
    request: Request,
    format: str | None = Query(None, description="Response format override (html or json)"),
    store=Depends(get_receipt_store),
    share_store=Depends(get_receipt_share_store),
) -> SharedReceiptResponse | Response:
    """Access a receipt via public share token."""
    try:
        share_status, share_info = await _consume_share_access(share_store, token)
        if share_status == "not_found":
            raise HTTPException(status_code=404, detail="Share link not found")
        if share_status == "expired":
            raise HTTPException(status_code=410, detail="Share link has expired")
        if share_status == "limit_reached":
            raise HTTPException(status_code=410, detail="Share link access limit reached")
        if share_info is None:
            raise HTTPException(status_code=404, detail="Share link not found")

        receipt_id = share_info.get("receipt_id", "")
        receipt_data = None
        if hasattr(store, "get"):
            receipt_data = await _call_store_method(store, "get", receipt_id)
        elif hasattr(store, "get_by_id"):
            receipt_data = await _call_store_method(store, "get_by_id", receipt_id)

        if not receipt_data:
            raise NotFoundError(f"Receipt {receipt_id} not found")

        wants_html = (format or "").lower() == "html" or (
            not format and "text/html" in request.headers.get("accept", "").lower()
        )
        if wants_html:
            receipt = _reconstruct_decision_receipt(receipt_data)
            if receipt is not None:
                return Response(
                    content=_render_shared_receipt_html(receipt, token),
                    media_type="text/html; charset=utf-8",
                )

        return SharedReceiptResponse(
            receipt=_extract_receipt_payload(receipt_data),
            shared=True,
            access_count=share_info.get("access_count", 0),
        )

    except HTTPException:
        raise
    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting shared receipt %s: %s", token, e)
        raise HTTPException(status_code=500, detail="Failed to load shared receipt")


@router.post("/receipts/batch-verify", response_model=BatchVerifyResponse)
async def batch_verify_receipts(
    body: BatchVerifyRequest,
    store=Depends(get_receipt_store),
) -> BatchVerifyResponse:
    """Verify multiple receipts at once (up to 100)."""
    try:
        results: list[BatchVerifyResult] = []
        verified_count = 0

        for rid in body.receipt_ids:
            try:
                receipt_data = None
                if hasattr(store, "get"):
                    receipt_data = await _call_store_method(store, "get", rid)
                elif hasattr(store, "get_by_id"):
                    receipt_data = await _call_store_method(store, "get_by_id", rid)

                if not receipt_data:
                    results.append(
                        BatchVerifyResult(
                            receipt_id=rid,
                            verified=False,
                            integrity_valid=False,
                            error="Receipt not found",
                        )
                    )
                    continue

                try:
                    from aragora.export.decision_receipt import DecisionReceipt

                    if isinstance(receipt_data, dict):
                        data = receipt_data.get("data", receipt_data)
                        receipt = DecisionReceipt.from_dict(data)
                    elif hasattr(receipt_data, "to_dict"):
                        receipt = DecisionReceipt.from_dict(receipt_data.to_dict())
                    else:
                        results.append(
                            BatchVerifyResult(
                                receipt_id=rid,
                                verified=False,
                                integrity_valid=False,
                                error="Cannot reconstruct receipt",
                            )
                        )
                        continue

                    integrity_valid = receipt.verify_integrity()
                    results.append(
                        BatchVerifyResult(
                            receipt_id=rid,
                            verified=integrity_valid,
                            integrity_valid=integrity_valid,
                        )
                    )
                    if integrity_valid:
                        verified_count += 1

                except (ImportError, ValueError, TypeError, KeyError) as e:
                    logger.warning("Batch verify failed for %s: %s", rid, e)
                    results.append(
                        BatchVerifyResult(
                            receipt_id=rid,
                            verified=False,
                            integrity_valid=False,
                            error="Verification failed",
                        )
                    )

            except (RuntimeError, OSError, AttributeError) as e:
                logger.warning("Batch verify error for %s: %s", rid, e)
                results.append(
                    BatchVerifyResult(
                        receipt_id=rid,
                        verified=False,
                        integrity_valid=False,
                        error="Verification error",
                    )
                )

        return BatchVerifyResponse(
            results=results,
            total=len(results),
            verified_count=verified_count,
            failed_count=len(results) - verified_count,
        )

    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error in batch verify: %s", e)
        raise HTTPException(status_code=500, detail="Failed to batch verify receipts")


@router.post("/receipts/batch-export", response_model=BatchExportResponse)
async def batch_export_receipts(
    body: BatchExportRequest,
    store=Depends(get_receipt_store),
) -> BatchExportResponse | Response:
    """Export multiple receipts at once (up to 100), defaulting to the legacy ZIP surface."""
    try:
        items: list[BatchExportItem] = []
        archive_items: list[tuple[str, str, str | bytes]] = []
        failed_ids: list[str] = []

        export_format = body.format.lower()
        if export_format not in ("json", "html", "markdown", "md", "csv", "sarif", "pdf"):
            raise HTTPException(
                status_code=422,
                detail="Unsupported format. Supported: json, html, markdown, md, csv, sarif, pdf",
            )
        if export_format == "pdf" and not body.raw:
            raise HTTPException(
                status_code=422,
                detail="PDF batch export requires raw=true and returns a ZIP bundle of PDF files",
            )

        for rid in body.receipt_ids:
            try:
                receipt_data = None
                if hasattr(store, "get"):
                    receipt_data = await _call_store_method(store, "get", rid)
                elif hasattr(store, "get_by_id"):
                    receipt_data = await _call_store_method(store, "get_by_id", rid)

                if not receipt_data:
                    failed_ids.append(rid)
                    continue

                receipt = _build_decision_receipt(receipt_data)
                if export_format == "pdf":
                    archive_items.append((rid, "pdf", receipt.to_pdf()))
                    continue

                content, response_format, extension = _render_receipt_export_content(
                    receipt, export_format
                )

                items.append(
                    BatchExportItem(receipt_id=rid, format=response_format, content=content)
                )
                archive_items.append((rid, extension, content))

            except (ImportError, ValueError, TypeError, KeyError, OSError) as e:
                logger.warning("Batch export failed for %s: %s", rid, e)
                failed_ids.append(rid)

        if body.raw:
            zip_bytes = _build_batch_export_zip(
                archive_items=archive_items,
                export_format=export_format,
                total_requested=len(body.receipt_ids),
                failed_ids=failed_ids,
            )
            return Response(
                content=zip_bytes,
                media_type="application/zip",
                headers={"Content-Disposition": "attachment; filename=receipts-export.zip"},
            )

        return BatchExportResponse(
            items=items,
            total_requested=len(body.receipt_ids),
            exported_count=len(items),
            failed_ids=failed_ids,
        )

    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error in batch export: %s", e)
        raise HTTPException(status_code=500, detail="Failed to batch export receipts")


# --- Parameterized routes below ---


@router.get("/receipts/{receipt_id}", response_model=ReceiptDetail)
async def get_receipt(
    receipt_id: str,
    store=Depends(get_receipt_store),
) -> ReceiptDetail:
    """Get receipt by ID with full details including findings and verification data."""
    try:
        receipt_data = None

        if hasattr(store, "get"):
            receipt_data = await _call_store_method(store, "get", receipt_id)
        elif hasattr(store, "get_by_id"):
            receipt_data = await _call_store_method(store, "get_by_id", receipt_id)

        if not receipt_data:
            raise NotFoundError(f"Receipt {receipt_id} not found")

        data = _extract_receipt_payload(receipt_data)
        return ReceiptDetail(
            receipt_id=data.get("receipt_id", receipt_id),
            gauntlet_id=data.get("gauntlet_id", ""),
            timestamp=data.get("timestamp"),
            input_summary=data.get("input_summary", ""),
            input_type=data.get("input_type", "spec"),
            schema_version=data.get("schema_version", "1.0"),
            verdict=data.get("verdict", ""),
            confidence=data.get("confidence", 0.0),
            risk_level=data.get("risk_level", "MEDIUM"),
            risk_score=data.get("risk_score", 0.0),
            robustness_score=data.get("robustness_score", 0.0),
            coverage_score=data.get("coverage_score", 0.0),
            verification_coverage=data.get("verification_coverage", 0.0),
            findings=data.get("findings", []),
            critical_count=data.get("critical_count", 0),
            high_count=data.get("high_count", 0),
            medium_count=data.get("medium_count", 0),
            low_count=data.get("low_count", 0),
            mitigations=data.get("mitigations", []),
            dissenting_views=data.get("dissenting_views", []),
            unresolved_tensions=data.get("unresolved_tensions", []),
            verified_claims=data.get("verified_claims", []),
            unverified_claims=data.get("unverified_claims", []),
            agents_involved=data.get("agents_involved", []),
            rounds_completed=data.get("rounds_completed", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
            audit_trail_id=data.get("audit_trail_id"),
            checksum=data.get("checksum", ""),
        )

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error getting receipt %s: %s", receipt_id, e)
        raise HTTPException(status_code=500, detail="Failed to get receipt")


@router.post(
    "/receipts/{receipt_id}/share",
    response_model=ShareReceiptResponse,
    openapi_extra={"security": [{"bearerAuth": []}]},
)
async def share_receipt(
    receipt_id: str,
    body: CreateShareRequest,
    _auth: Any = Depends(require_permission("receipts:share")),
    store=Depends(get_receipt_store),
    share_store=Depends(get_receipt_share_store),
) -> ShareReceiptResponse:
    """Create a time-limited public share link for a receipt."""
    try:
        import secrets

        receipt_data = None
        if hasattr(store, "get"):
            receipt_data = await _call_store_method(store, "get", receipt_id)
        elif hasattr(store, "get_by_id"):
            receipt_data = await _call_store_method(store, "get_by_id", receipt_id)

        if not receipt_data:
            raise NotFoundError(f"Receipt {receipt_id} not found")

        token = secrets.token_urlsafe(24)
        expires_at_ts = datetime.now(timezone.utc).timestamp() + (body.expires_in_hours * 3600)
        await _call_store_method(
            share_store,
            "save",
            token=token,
            receipt_id=receipt_id,
            expires_at=expires_at_ts,
            max_accesses=body.max_accesses,
        )

        return ShareReceiptResponse(
            success=True,
            receipt_id=receipt_id,
            share_url=f"/api/v2/receipts/share/{token}",
            token=token,
            expires_at=datetime.fromtimestamp(expires_at_ts, tz=timezone.utc).isoformat(),
            max_accesses=body.max_accesses,
        )

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error sharing receipt %s: %s", receipt_id, e)
        raise HTTPException(status_code=500, detail="Failed to share receipt")


@router.get(
    "/receipts/{receipt_id}/formatted/{channel_type}",
    response_model=FormattedReceiptResponse,
)
async def get_formatted_receipt(
    receipt_id: str,
    channel_type: str,
    compact: bool = Query(False, description="Return a compact formatter payload"),
    store=Depends(get_receipt_store),
) -> FormattedReceiptResponse:
    """Return the receipt payload formatted for a specific channel."""
    try:
        receipt_data = None
        if hasattr(store, "get"):
            receipt_data = await _call_store_method(store, "get", receipt_id)
        elif hasattr(store, "get_by_id"):
            receipt_data = await _call_store_method(store, "get_by_id", receipt_id)

        if not receipt_data:
            raise NotFoundError(f"Receipt {receipt_id} not found")

        from aragora.channels.formatter import format_receipt_for_channel

        formatted = format_receipt_for_channel(
            _build_decision_receipt(receipt_data),
            channel_type,
            {"compact": compact},
        )
        return FormattedReceiptResponse(
            receipt_id=receipt_id,
            channel_type=channel_type,
            formatted=formatted,
        )
    except NotFoundError:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (ImportError, RuntimeError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error formatting receipt %s for %s: %s", receipt_id, channel_type, e)
        raise HTTPException(status_code=500, detail="Failed to format receipt")


@router.post(
    "/receipts/{receipt_id}/send-to-channel",
    response_model=SendToChannelResponse,
    openapi_extra={"security": [{"bearerAuth": []}]},
)
async def send_receipt_to_channel(
    receipt_id: str,
    body: SendToChannelRequest,
    request: Request,
    _auth: Any = Depends(require_permission("receipts:share")),
    store=Depends(get_receipt_store),
) -> SendToChannelResponse:
    """Send a receipt to a configured channel using the legacy delivery adapters."""
    try:
        receipt_data = None
        if hasattr(store, "get"):
            receipt_data = await _call_store_method(store, "get", receipt_id)
        elif hasattr(store, "get_by_id"):
            receipt_data = await _call_store_method(store, "get_by_id", receipt_id)

        if not receipt_data:
            raise NotFoundError(f"Receipt {receipt_id} not found")

        from aragora.channels.formatter import format_receipt_for_channel
        from aragora.server.handlers.decisions.receipts import ReceiptsHandler

        supported_channels = {"slack", "teams", "email", "discord"}
        if body.channel_type not in supported_channels:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported channel type: {body.channel_type}. "
                    "Supported: slack, teams, email, discord"
                ),
            )

        formatted = format_receipt_for_channel(
            _build_decision_receipt(receipt_data),
            body.channel_type,
            body.options,
        )

        handler = ReceiptsHandler(getattr(request.app.state, "context", {}) or {})
        if body.channel_type == "slack":
            result = await handler._send_to_slack(formatted, body.channel_id, body.workspace_id)
        elif body.channel_type == "teams":
            result = await handler._send_to_teams(formatted, body.channel_id, body.workspace_id)
        elif body.channel_type == "email":
            result = await handler._send_to_email(formatted, body.channel_id, body.options)
        else:
            result = await handler._send_to_discord(formatted, body.channel_id, body.options)

        handler._record_delivery_history(
            receipt_id=receipt_id,
            channel_type=body.channel_type,
            channel_id=body.channel_id,
            workspace_id=body.workspace_id,
            status="success",
            result=result,
        )
        return SendToChannelResponse(
            sent=True,
            receipt_id=receipt_id,
            channel_type=body.channel_type,
            channel_id=body.channel_id,
            **result,
        )
    except HTTPException:
        raise
    except NotFoundError:
        raise
    except ImportError as e:
        logger.exception("Missing dependency for receipt delivery to %s: %s", body.channel_type, e)
        raise HTTPException(status_code=501, detail=f"Delivery backend unavailable: {e}") from e
    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        logger.exception("Failed to send receipt %s to %s: %s", receipt_id, body.channel_type, e)
        raise HTTPException(status_code=500, detail=f"Failed to send receipt: {e}") from e


@router.post("/receipts/{receipt_id}/verify-signature", response_model=SignatureVerifyResponse)
async def verify_receipt_signature(
    receipt_id: str,
    store=Depends(get_receipt_store),
) -> SignatureVerifyResponse:
    """Verify a stored receipt's cryptographic signature."""
    try:
        if not hasattr(store, "verify_signature"):
            raise HTTPException(
                status_code=501, detail="Receipt signature verification unavailable"
            )

        result = await _call_store_method(store, "verify_signature", receipt_id)
        if hasattr(result, "to_dict"):
            payload = result.to_dict()
            error = getattr(result, "error", None)
        elif isinstance(result, dict):
            payload = result
            error = result.get("error")
        else:
            raise TypeError("Unexpected signature verification result")

        if isinstance(error, str) and "not found" in error.lower():
            raise NotFoundError(f"Receipt {receipt_id} not found")

        return SignatureVerifyResponse(**payload)
    except HTTPException:
        raise
    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error verifying receipt signature %s: %s", receipt_id, e)
        raise HTTPException(status_code=500, detail="Failed to verify receipt signature")


@router.post("/receipts/{receipt_id}/verify", response_model=VerifyResponse)
async def verify_receipt_post(
    receipt_id: str,
    store=Depends(get_receipt_store),
) -> VerifyResponse:
    """Verify receipt integrity (POST variant)."""
    return await verify_receipt(receipt_id=receipt_id, store=store)


@router.get("/receipts/{receipt_id}/verify", response_model=VerifyResponse)
async def verify_receipt(
    receipt_id: str,
    store=Depends(get_receipt_store),
) -> VerifyResponse:
    """Verify receipt integrity by checking the checksum."""
    try:
        receipt_data = None

        if hasattr(store, "get"):
            receipt_data = await _call_store_method(store, "get", receipt_id)
        elif hasattr(store, "get_by_id"):
            receipt_data = await _call_store_method(store, "get_by_id", receipt_id)

        if not receipt_data:
            raise NotFoundError(f"Receipt {receipt_id} not found")

        try:
            from aragora.export.decision_receipt import DecisionReceipt

            data = _extract_decision_receipt_payload(receipt_data)
            if data:
                receipt = DecisionReceipt.from_dict(data)
            else:
                return VerifyResponse(
                    receipt_id=receipt_id,
                    verified=False,
                    integrity_valid=False,
                    checksum_match=False,
                    details={"error": "Cannot reconstruct receipt for verification"},
                )

            integrity_valid = receipt.verify_integrity()
            stored_checksum = (
                receipt_data.get("checksum", "")
                if isinstance(receipt_data, dict)
                else getattr(receipt_data, "checksum", "")
            )
            checksum_match = receipt.checksum == stored_checksum if stored_checksum else True

            return VerifyResponse(
                receipt_id=receipt_id,
                verified=integrity_valid and checksum_match,
                integrity_valid=integrity_valid,
                checksum_match=checksum_match,
                details={
                    "computed_checksum": receipt.checksum,
                    "stored_checksum": stored_checksum,
                    "verdict": receipt.verdict,
                    "confidence": receipt.confidence,
                },
            )

        except (ImportError, ValueError, TypeError, KeyError) as e:
            logger.warning("Receipt verification failed for %s: %s", receipt_id, e)
            return VerifyResponse(
                receipt_id=receipt_id,
                verified=False,
                integrity_valid=False,
                checksum_match=False,
                details={"error": "Verification failed"},
            )

    except NotFoundError:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error verifying receipt %s: %s", receipt_id, e)
        raise HTTPException(status_code=500, detail="Failed to verify receipt")


@router.get("/receipts/{receipt_id}/export", response_model=ExportResponse)
async def export_receipt(
    receipt_id: str,
    format: ExportFormat = Query(ExportFormat.json, description="Export format"),
    raw: bool = Query(
        False,
        description="Return the exported bytes directly instead of a JSON wrapper.",
    ),
    store=Depends(get_receipt_store),
) -> ExportResponse | Response:
    """Export receipt in the specified format."""
    try:
        receipt_data = None

        if hasattr(store, "get"):
            receipt_data = await _call_store_method(store, "get", receipt_id)
        elif hasattr(store, "get_by_id"):
            receipt_data = await _call_store_method(store, "get_by_id", receipt_id)

        if not receipt_data:
            raise NotFoundError(f"Receipt {receipt_id} not found")

        try:
            from aragora.export.decision_receipt import DecisionReceipt

            data = _extract_decision_receipt_payload(receipt_data)
            if data:
                receipt = DecisionReceipt.from_dict(data)
            else:
                raise ValueError("Cannot reconstruct receipt for export")

            if format == ExportFormat.pdf:
                try:
                    return Response(
                        content=receipt.to_pdf(),
                        media_type="application/pdf",
                    )
                except ImportError:
                    logger.info("PDF export unavailable, falling back to printable HTML")
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
    {receipt.to_html()}
</body>
</html>"""
                    return Response(
                        content=printable_html.encode("utf-8"),
                        media_type="text/html",
                        headers={"X-PDF-Fallback": "true"},
                    )

            if format in (ExportFormat.markdown, ExportFormat.md):
                content = receipt.to_markdown()
                response_format = "markdown"
                media_type = "text/markdown"
            elif format == ExportFormat.html:
                content = receipt.to_html()
                response_format = "html"
                media_type = "text/html"
            elif format == ExportFormat.sarif:
                content = receipt.to_sarif_json()
                response_format = "sarif"
                media_type = "application/sarif+json"
            else:
                content = receipt.to_json()
                response_format = "json"
                media_type = "application/json"

            if raw:
                body = content if isinstance(content, bytes) else content.encode("utf-8")
                return Response(content=body, media_type=media_type)

            return ExportResponse(
                receipt_id=receipt_id,
                format=response_format,
                content=content,
            )

        except ImportError as e:
            raise HTTPException(
                status_code=501,
                detail=f"Export module not available: {e}",
            )

    except NotFoundError:
        raise
    except HTTPException:
        raise
    except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:
        logger.exception("Error exporting receipt %s: %s", receipt_id, e)
        raise HTTPException(status_code=500, detail="Failed to export receipt")
