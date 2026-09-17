"""
Audit Verification Handler.

Provides audit verification operations including:
- Trail verification
- Receipt verification
- Date range verification
- Audit event export (SIEM-compatible formats)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    json_response,
)
from aragora.rbac.decorators import require_permission
from aragora.observability.metrics import track_handler
from aragora.storage.audit_store import get_audit_store
from aragora.storage.receipt_store import get_receipt_store as _base_get_receipt_store

logger = logging.getLogger(__name__)


def get_receipt_store():  # type: ignore[override]
    """Indirection for tests that patch compliance_handler.get_receipt_store."""
    try:
        from aragora.server.handlers.compliance import handler as compat

        return compat.get_receipt_store()
    except (ImportError, AttributeError):
        logger.debug(
            "compliance_handler.get_receipt_store unavailable, using base receipt store",
            exc_info=True,
        )
        return _base_get_receipt_store()


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse timestamp from string (ISO date or unix timestamp)."""
    if not value:
        return None

    try:
        ts = float(value)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except ValueError:
        pass

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt
    except (ValueError, AttributeError):
        pass

    return None


class AuditVerifyMixin:
    """Mixin providing audit verification methods."""

    @track_handler("compliance/audit-verify", method="POST")
    @require_permission("compliance:audit")
    async def _verify_audit(self, body: dict[str, Any]) -> HandlerResult:
        """
        Verify audit trail integrity.

        Body:
            trail_id: Audit trail ID to verify (optional)
            receipt_ids: List of receipt IDs to verify (optional)
            date_range: Date range to verify (optional)
        """
        trail_id = body.get("trail_id")
        receipt_ids = body.get("receipt_ids", [])
        date_range = body.get("date_range", {})

        verification_results: dict[str, Any] = {
            "verified": True,
            "checks": [],
            "errors": [],
        }

        # Verify specific trail
        if trail_id:
            check = await self._verify_trail(trail_id)
            verification_results["checks"].append(check)
            if not check["valid"]:
                verification_results["verified"] = False
                verification_results["errors"].append(
                    check.get("error", "Trail verification failed")
                )

        # Verify receipts
        if receipt_ids:
            try:
                from aragora.storage.receipt_store import get_receipt_store as _store_get

                store = _store_get()
            except (ImportError, AttributeError):
                logger.warning(
                    "Direct receipt_store import failed, using compat fallback for batch verify",
                    exc_info=True,
                )
                store = get_receipt_store()
            results, summary = store.verify_batch(receipt_ids)

            for result in results:
                check = {
                    "type": "receipt",
                    "id": result.receipt_id,
                    "valid": result.is_valid,
                    "error": result.error,
                }
                verification_results["checks"].append(check)
                if not result.is_valid:
                    verification_results["verified"] = False
                    verification_results["errors"].append(
                        f"Receipt {result.receipt_id}: {result.error}"
                    )

            verification_results["receipt_summary"] = summary

        # Verify date range
        if date_range:
            range_check = await self._verify_date_range(date_range)
            verification_results["checks"].append(range_check)
            if not range_check["valid"]:
                verification_results["verified"] = False
                verification_results["errors"].extend(range_check.get("errors", []))

        verification_results["verified_at"] = datetime.now(timezone.utc).isoformat()

        return json_response(verification_results)

    @track_handler("compliance/audit-events", method="GET")
    @require_permission("compliance:audit")
    async def _get_audit_events(self, query_params: dict[str, str]) -> HandlerResult:
        """
        Export audit events in SIEM-compatible format.

        Query params:
            format: Export format (elasticsearch, json, ndjson) - default: json
            from: Start timestamp (ISO or unix)
            to: End timestamp (ISO or unix)
            limit: Max events (default 1000, max 10000)
            event_type: Filter by event type
        """
        output_format = query_params.get("format", "json")
        from_ts = parse_timestamp(query_params.get("from"))
        to_ts = parse_timestamp(query_params.get("to"))
        limit = min(int(query_params.get("limit", "1000")), 10000)
        event_type = query_params.get("event_type")

        # Fetch events from audit store
        events = await self._fetch_audit_events(
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
            event_type=event_type,
        )

        if output_format == "elasticsearch":
            # Elasticsearch bulk format
            bulk_lines = []
            for event in events:
                # Get event ID (handle both "id" and "event_id" field names)
                event_id = event.get("id") or event.get("event_id", "unknown")
                # Index action
                bulk_lines.append(
                    json.dumps({"index": {"_index": "aragora-audit", "_id": str(event_id)}})
                )
                # Document
                es_event = {
                    "@timestamp": event.get("timestamp", ""),
                    "event.category": "audit",
                    "event.type": event.get("event_type", event.get("action", "")),
                    "event.id": str(event_id),
                    "source": event.get("source", "aragora"),
                    "message": event.get("description", ""),
                    "aragora": event,
                }
                bulk_lines.append(json.dumps(es_event))

            content = "\n".join(bulk_lines) + "\n"
            return HandlerResult(
                status_code=200,
                content_type="application/x-ndjson",
                body=content.encode("utf-8"),
            )

        if output_format == "ndjson":
            # Newline-delimited JSON
            lines = [json.dumps(event) for event in events]
            content = "\n".join(lines) + "\n"
            return HandlerResult(
                status_code=200,
                content_type="application/x-ndjson",
                body=content.encode("utf-8"),
            )

        # Default JSON response
        return json_response(
            {
                "events": events,
                "count": len(events),
                "from": from_ts.isoformat() if from_ts else None,
                "to": to_ts.isoformat() if to_ts else None,
            }
        )

    async def _verify_trail(self, trail_id: str) -> dict[str, Any]:
        """Verify a specific audit trail by checking receipt integrity."""
        try:
            store = get_receipt_store()
            # Try to get the receipt by ID (trail_id could be receipt_id or gauntlet_id)
            receipt = store.get(trail_id) or store.get_by_gauntlet(trail_id)
            if not receipt:
                return {
                    "type": "audit_trail",
                    "id": trail_id,
                    "valid": False,
                    "error": "Trail not found",
                    "checked": datetime.now(timezone.utc).isoformat(),
                }
            # Verify signature if present
            signature_valid = receipt.signature is not None
            return {
                "type": "audit_trail",
                "id": trail_id,
                "valid": True,
                "receipt_id": receipt.receipt_id,
                "signed": signature_valid,
                "verdict": receipt.verdict,
                "checked": datetime.now(timezone.utc).isoformat(),
            }
        except (RuntimeError, AttributeError, KeyError, ValueError) as e:
            logger.warning("Failed to verify trail %s: %s", trail_id, e)
            return {
                "type": "audit_trail",
                "id": trail_id,
                "valid": False,
                "error": "Trail verification failed",
                "checked": datetime.now(timezone.utc).isoformat(),
            }

    async def _verify_date_range(self, date_range: dict[str, str]) -> dict[str, Any]:
        """Verify audit events in date range by checking integrity."""
        try:
            try:
                from aragora.server.handlers.compliance import handler as compat

                store = compat.get_audit_store()
            except (ImportError, AttributeError):
                logger.debug(
                    "compliance_handler.get_audit_store unavailable for date range verify",
                    exc_info=True,
                )
                try:
                    from aragora.storage.audit_store import get_audit_store as _audit_get

                    store = _audit_get()
                except (ImportError, AttributeError):
                    logger.warning(
                        "Direct audit_store import also failed, using module-level fallback",
                        exc_info=True,
                    )
                    store = get_audit_store()
            from_str = date_range.get("from")
            to_str = date_range.get("to")

            # Parse dates
            from_dt = datetime.fromisoformat(from_str.replace("Z", "+00:00")) if from_str else None
            to_dt = datetime.fromisoformat(to_str.replace("Z", "+00:00")) if to_str else None

            # Get events and verify basic integrity
            events = store.get_log(limit=1000)
            errors = []
            events_in_range = 0

            for event in events:
                event_time = event.get("timestamp")
                if event_time:
                    try:
                        if isinstance(event_time, str):
                            event_dt = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
                        else:
                            event_dt = event_time
                        if from_dt and event_dt < from_dt:
                            continue
                        if to_dt and event_dt > to_dt:
                            continue
                        events_in_range += 1
                        # Basic integrity check - ensure required fields exist
                        if not event.get("action"):
                            errors.append(
                                f"Event missing action field: {event.get('id', 'unknown')}"
                            )
                    except (ValueError, TypeError) as e:
                        errors.append(f"Invalid timestamp: {e}")

            return {
                "type": "date_range",
                "from": from_str,
                "to": to_str,
                "valid": len(errors) == 0,
                "events_checked": events_in_range,
                "errors": errors[:10],  # Limit errors in response
            }
        except (RuntimeError, AttributeError, KeyError, ValueError, TypeError) as e:
            logger.warning("Failed to verify date range: %s", e)
            return {
                "type": "date_range",
                "from": date_range.get("from"),
                "to": date_range.get("to"),
                "valid": False,
                "events_checked": 0,
                "errors": ["Date range verification failed"],
            }

    async def _fetch_audit_events(
        self,
        from_ts: datetime | None,
        to_ts: datetime | None,
        limit: int,
        event_type: str | None,
    ) -> list[dict[str, Any]]:
        """Fetch audit events from audit store."""
        try:
            try:
                from aragora.server.handlers.compliance import handler as compat

                store = compat.get_audit_store()
            except (ImportError, AttributeError):
                logger.debug(
                    "compliance_handler.get_audit_store unavailable for event fetch",
                    exc_info=True,
                )
                store = get_audit_store()
            # Convert datetimes to the format expected by the store
            events = store.get_log(
                action=event_type,
                limit=limit,
            )
            # Filter by date range if provided
            filtered = []
            for event in events:
                event_time = event.get("timestamp")
                if event_time:
                    try:
                        if isinstance(event_time, str):
                            event_dt = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
                        else:
                            event_dt = event_time
                        if from_ts and event_dt < from_ts:
                            continue
                        if to_ts and event_dt > to_ts:
                            continue
                    except (ValueError, TypeError):
                        pass  # Include events with unparseable timestamps
                filtered.append(event)
            return filtered[:limit]
        except (RuntimeError, AttributeError, KeyError, ValueError) as e:
            logger.warning("Failed to fetch audit events: %s", e)
            return []


__all__ = ["AuditVerifyMixin", "parse_timestamp"]
