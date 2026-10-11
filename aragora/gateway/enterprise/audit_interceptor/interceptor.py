"""
Audit Interceptor for Enterprise Gateway.

Provides comprehensive request/response audit logging with cryptographic
integrity verification, PII redaction, and compliance support.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any
from collections.abc import Callable
from uuid import uuid4

from .enums import AuditEventType
from .models import AuditConfig, AuditRecord
from .storage import AuditStorage, InMemoryAuditStorage, PostgresAuditStorage

logger = logging.getLogger(__name__)


class AuditInterceptor:
    """
    Enterprise audit interceptor for request/response logging.

    Provides comprehensive audit logging with:
    - SHA-256 hashing and hash chains for tamper detection
    - HMAC-SHA256 signatures for integrity verification
    - GDPR-compliant PII redaction
    - SOC 2 Type II audit evidence generation
    - Real-time event emission and webhook integration
    - Prometheus metrics for monitoring

    Usage:
        interceptor = AuditInterceptor(config=AuditConfig(
            retention_days=365,
            emit_events=True,
            webhook_url="https://siem.example.com/webhook",
        ))

        # Intercept a request/response pair
        record = await interceptor.intercept(
            request={"method": "POST", "path": "/api/users", ...},
            response={"status": 200, "body": {...}},
            correlation_id="req-123",
            user_id="user-456",
        )

        # Verify chain integrity
        is_valid, errors = await interceptor.verify_chain()

        # Export for compliance audit
        report = await interceptor.export_soc2_evidence(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 3, 31),
        )
    """

    def __init__(
        self,
        config: AuditConfig | None = None,
        storage: AuditStorage | None = None,
    ) -> None:
        """
        Initialize the audit interceptor.

        Args:
            config: Audit configuration. If None, uses defaults.
            storage: Storage backend. If None, creates based on config.
        """
        self._config = config or AuditConfig()
        if storage is None:
            if self._config.storage_backend == "postgres":
                storage = PostgresAuditStorage()
            else:
                storage = InMemoryAuditStorage()
        self._storage: AuditStorage = storage
        self._event_handlers: list[Callable[[AuditEventType, dict[str, Any]], None]] = []
        self._metrics_enabled = self._config.enable_metrics

        # Metrics counters
        self._requests_total = 0
        self._requests_by_status: dict[int, int] = {}
        self._pii_redactions_total = 0
        self._chain_verifications_total = 0
        self._chain_errors_total = 0

        logger.info(
            "AuditInterceptor initialized with %s storage, retention=%d days",
            self._config.storage_backend,
            self._config.retention_days,
        )

    def add_event_handler(self, handler: Callable[[AuditEventType, dict[str, Any]], None]) -> None:
        """
        Add an event handler for audit events.

        Args:
            handler: Callback function receiving (event_type, event_data)
        """
        self._event_handlers.append(handler)

    def remove_event_handler(
        self, handler: Callable[[AuditEventType, dict[str, Any]], None]
    ) -> None:
        """Remove an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    async def intercept(
        self,
        request: dict[str, Any],
        response: dict[str, Any],
        correlation_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        ip_address: str = "",
        user_agent: str = "",
        start_time: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditRecord:
        """
        Intercept and log a request/response pair.

        Args:
            request: Request data with method, path, headers, body
            response: Response data with status, headers, body
            correlation_id: Request correlation/trace ID
            user_id: Authenticated user ID
            org_id: Organization ID
            ip_address: Client IP address
            user_agent: Client user agent
            start_time: Request start time (time.time()) for duration calc
            metadata: Additional metadata to include

        Returns:
            The created audit record
        """
        # Calculate duration
        duration_ms = 0.0
        if start_time:
            duration_ms = (time.time() - start_time) * 1000

        # Extract request data
        request_method = request.get("method", "")
        request_path = request.get("path", "")
        request_headers = dict(request.get("headers", {}))
        request_body = request.get("body")

        # Extract response data
        response_status = response.get("status", 0)
        response_headers = dict(response.get("headers", {}))
        response_body = response.get("body")

        # Redact sensitive headers
        request_headers = self._redact_headers(request_headers)
        response_headers = self._redact_headers(response_headers)

        # Hash original bodies before redaction
        request_body_hash = self._hash_body(request_body)
        response_body_hash = self._hash_body(response_body)

        # Redact PII from bodies
        redacted_fields: list[str] = []
        request_body, req_redacted = self._redact_body(request_body, "request")
        response_body, resp_redacted = self._redact_body(response_body, "response")
        redacted_fields.extend(req_redacted)
        redacted_fields.extend(resp_redacted)

        # Optionally hash response body for privacy
        if self._config.hash_responses and response_body:
            response_body = {"_hashed": True, "hash": response_body_hash}

        # Truncate large bodies
        request_body = self._truncate_body(request_body)
        response_body = self._truncate_body(response_body)

        # Get previous hash for chain
        previous_hash = await self._storage.get_last_hash()

        # Create record
        record = AuditRecord(
            correlation_id=correlation_id or str(uuid4()),
            request_method=request_method,
            request_path=request_path,
            request_headers=request_headers,
            request_body=request_body,
            request_body_hash=request_body_hash,
            response_status=response_status,
            response_headers=response_headers,
            response_body=response_body,
            response_body_hash=response_body_hash,
            duration_ms=duration_ms,
            user_id=user_id,
            org_id=org_id,
            ip_address=ip_address,
            user_agent=user_agent,
            previous_hash=previous_hash,
            metadata=metadata or {},
            pii_fields_redacted=redacted_fields,
        )

        # Compute hash and signature
        record.record_hash = record.compute_hash()
        record.signature = record.compute_signature()

        # Store record
        await self._storage.store(record)

        # Update metrics
        self._requests_total += 1
        self._requests_by_status[response_status] = (
            self._requests_by_status.get(response_status, 0) + 1
        )
        if redacted_fields:
            self._pii_redactions_total += len(redacted_fields)

        # Emit events
        if self._config.emit_events:
            await self._emit_event(
                AuditEventType.RESPONSE_SENT,
                {
                    "record_id": record.id,
                    "correlation_id": record.correlation_id,
                    "method": request_method,
                    "path": request_path,
                    "status": response_status,
                    "duration_ms": duration_ms,
                    "user_id": user_id,
                    "pii_fields_redacted": len(redacted_fields),
                },
            )

        # Send to webhook if configured
        if self._config.webhook_url:
            asyncio.create_task(self._send_webhook(record))

        logger.debug(
            "Audit record created: id=%s method=%s path=%s status=%d duration=%.2fms",
            record.id,
            request_method,
            request_path,
            response_status,
            duration_ms,
        )

        return record

    async def verify_chain(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Verify the integrity of the audit chain.

        Checks that:
        1. Each record's hash matches its computed hash
        2. Each record's previous_hash matches the prior record's hash
        3. Each record's signature is valid

        Args:
            since: Start of verification range
            until: End of verification range

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors: list[str] = []
        records = await self._storage.get_chain(since, until)

        prev_hash = ""
        for i, record in enumerate(records):
            # Verify previous hash chain
            if record.previous_hash != prev_hash:
                errors.append(
                    f"Chain broken at record {record.id}: "
                    f"expected previous_hash={prev_hash}, got {record.previous_hash}"
                )

            # Verify record hash
            computed_hash = record.compute_hash()
            if record.record_hash != computed_hash:
                errors.append(
                    f"Hash mismatch at record {record.id}: "
                    f"stored={record.record_hash}, computed={computed_hash}"
                )

            # Verify signature
            if record.signature and not record.verify_signature():
                errors.append(f"Invalid signature at record {record.id}")

            prev_hash = record.record_hash

        # Update metrics
        self._chain_verifications_total += 1
        if errors:
            self._chain_errors_total += 1

        # Emit event
        if self._config.emit_events:
            event_type = (
                AuditEventType.CHAIN_VERIFIED if not errors else AuditEventType.CHAIN_BROKEN
            )
            await self._emit_event(
                event_type,
                {
                    "records_verified": len(records),
                    "errors": len(errors),
                    "since": since.isoformat() if since else None,
                    "until": until.isoformat() if until else None,
                },
            )

        is_valid = len(errors) == 0
        if is_valid:
            logger.info("Audit chain verified: %d records, no errors", len(records))
        else:
            logger.warning("Audit chain verification failed: %d errors", len(errors))

        return is_valid, errors

    async def apply_retention(self) -> int:
        """
        Apply retention policy and delete old records.

        Returns:
            Number of records deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._config.retention_days)
        deleted = await self._storage.delete_before(cutoff)

        if deleted > 0:
            logger.info(
                "Retention policy applied: deleted %d records older than %s",
                deleted,
                cutoff.date(),
            )

            if self._config.emit_events:
                await self._emit_event(
                    AuditEventType.RETENTION_APPLIED,
                    {
                        "records_deleted": deleted,
                        "cutoff_date": cutoff.isoformat(),
                        "retention_days": self._config.retention_days,
                    },
                )

        return deleted

    async def export_soc2_evidence(
        self,
        start_date: datetime,
        end_date: datetime,
        org_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Export audit records as SOC 2 Type II evidence.

        Generates a comprehensive report suitable for SOC 2 auditors,
        including integrity verification and control evidence.

        Args:
            start_date: Audit period start
            end_date: Audit period end
            org_id: Filter by organization

        Returns:
            SOC 2 evidence report dictionary
        """
        # Get records
        records = await self._storage.query(
            start_date=start_date,
            end_date=end_date,
            org_id=org_id,
            limit=100000,
        )

        # Verify chain integrity
        is_valid, integrity_errors = await self.verify_chain(start_date, end_date)

        # Compute statistics
        total_records = len(records)
        by_method: dict[str, int] = {}
        by_status: dict[int, int] = {}
        by_path_prefix: dict[str, int] = {}
        unique_users: set[str] = set()
        unique_ips: set[str] = set()
        total_duration_ms = 0.0
        failed_requests = 0
        pii_redactions = 0

        for record in records:
            by_method[record.request_method] = by_method.get(record.request_method, 0) + 1
            by_status[record.response_status] = by_status.get(record.response_status, 0) + 1

            # Extract path prefix (first two segments)
            path_parts = record.request_path.split("/")[:3]
            path_prefix = "/".join(path_parts)
            by_path_prefix[path_prefix] = by_path_prefix.get(path_prefix, 0) + 1

            if record.user_id:
                unique_users.add(record.user_id)
            if record.ip_address:
                unique_ips.add(record.ip_address)

            total_duration_ms += record.duration_ms

            if record.response_status >= 400:
                failed_requests += 1

            pii_redactions += len(record.pii_fields_redacted)

        avg_duration_ms = total_duration_ms / total_records if total_records > 0 else 0

        # Build SOC 2 report
        report = {
            "report_type": "SOC 2 Type II Gateway Audit Evidence",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "audit_period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "days": (end_date - start_date).days,
            },
            "organization": org_id or "all",
            "integrity": {
                "chain_verified": is_valid,
                "errors": integrity_errors[:10] if integrity_errors else [],
                "total_errors": len(integrity_errors),
            },
            "summary": {
                "total_requests": total_records,
                "unique_users": len(unique_users),
                "unique_ips": len(unique_ips),
                "failed_requests": failed_requests,
                "pii_redactions": pii_redactions,
                "avg_duration_ms": round(avg_duration_ms, 2),
            },
            "breakdown": {
                "by_method": by_method,
                "by_status": dict(sorted(by_status.items())),
                "by_path_prefix": dict(
                    sorted(by_path_prefix.items(), key=lambda x: x[1], reverse=True)[:20]
                ),
            },
            "control_evidence": {
                "CC6.1_access_control": {
                    "requests_with_user_id": sum(1 for r in records if r.user_id),
                    "requests_without_user_id": sum(1 for r in records if not r.user_id),
                },
                "CC6.6_audit_logging": {
                    "total_logged": total_records,
                    "chain_integrity": is_valid,
                    "signatures_verified": sum(1 for r in records if r.signature),
                },
                "CC6.7_data_protection": {
                    "pii_fields_redacted": pii_redactions,
                    "sensitive_headers_protected": True,
                },
                "CC7.2_monitoring": {
                    "failed_requests": failed_requests,
                    "error_rate_percent": round(failed_requests / total_records * 100, 2)
                    if total_records > 0
                    else 0,
                },
            },
            "sample_records": [r.to_dict() for r in records[:10]],
        }

        # Emit event
        if self._config.emit_events:
            await self._emit_event(
                AuditEventType.EXPORT_GENERATED,
                {
                    "report_type": "soc2",
                    "records_exported": total_records,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
            )

        logger.info(
            "SOC 2 evidence export generated: %d records, integrity=%s",
            total_records,
            is_valid,
        )

        return report

    async def get_record(self, record_id: str) -> AuditRecord | None:
        """
        Get a specific audit record by ID.

        Args:
            record_id: The record ID

        Returns:
            The audit record or None if not found
        """
        return await self._storage.get(record_id)

    async def query_records(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        correlation_id: str | None = None,
        request_path: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[AuditRecord]:
        """
        Query audit records.

        Args:
            start_date: Filter records after this time
            end_date: Filter records before this time
            user_id: Filter by user ID
            org_id: Filter by organization ID
            correlation_id: Filter by correlation ID
            request_path: Filter by request path (prefix match)
            limit: Maximum records to return
            offset: Pagination offset

        Returns:
            List of matching audit records
        """
        return await self._storage.query(
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            org_id=org_id,
            correlation_id=correlation_id,
            request_path=request_path,
            limit=limit,
            offset=offset,
        )

    def get_metrics(self) -> dict[str, Any]:
        """
        Get Prometheus-compatible metrics.

        Returns:
            Dictionary of metric values
        """
        return {
            f"{self._config.metrics_prefix}_requests_total": self._requests_total,
            f"{self._config.metrics_prefix}_requests_by_status": self._requests_by_status,
            f"{self._config.metrics_prefix}_pii_redactions_total": self._pii_redactions_total,
            f"{self._config.metrics_prefix}_chain_verifications_total": self._chain_verifications_total,
            f"{self._config.metrics_prefix}_chain_errors_total": self._chain_errors_total,
        }

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Redact sensitive headers."""
        redacted = {}
        sensitive = {h.lower() for h in self._config.sensitive_headers}

        for key, value in headers.items():
            if key.lower() in sensitive:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = value

        return redacted

    def _hash_body(self, body: Any) -> str:
        """Compute SHA-256 hash of a body."""
        if body is None:
            return ""
        try:
            if isinstance(body, (dict, list)):
                data = json.dumps(body, sort_keys=True, separators=(",", ":"))
            else:
                data = str(body)
            return hashlib.sha256(data.encode()).hexdigest()
        except (TypeError, ValueError):
            return ""

    def _redact_body(self, body: Any, prefix: str = "") -> tuple[Any, list[str]]:
        """
        Recursively redact PII from a body.

        Returns:
            Tuple of (redacted_body, list of redacted field names)
        """
        redacted_fields: list[str] = []

        if body is None:
            return None, redacted_fields

        if isinstance(body, dict):
            redacted = {}
            for key, value in body.items():
                field_path = f"{prefix}.{key}" if prefix else key

                # Check if this field should be redacted
                for rule in self._config.pii_rules:
                    if rule.matches(key):
                        redacted[key] = rule.redact(value)
                        redacted_fields.append(field_path)
                        break
                else:
                    # Recursively process nested structures
                    if isinstance(value, (dict, list)):
                        redacted[key], nested_fields = self._redact_body(value, field_path)
                        redacted_fields.extend(nested_fields)
                    else:
                        redacted[key] = value

            return redacted, redacted_fields

        elif isinstance(body, list):
            redacted_list: list[Any] = []
            for i, item in enumerate(body):
                field_path = f"{prefix}[{i}]"
                if isinstance(item, (dict, list)):
                    redacted_item, nested_fields = self._redact_body(item, field_path)
                    redacted_list.append(redacted_item)
                    redacted_fields.extend(nested_fields)
                else:
                    redacted_list.append(item)
            return redacted_list, redacted_fields

        return body, redacted_fields

    def _truncate_body(self, body: Any) -> Any:
        """Truncate body if it exceeds max size."""
        if body is None or self._config.max_body_size == 0:
            return body

        try:
            serialized = json.dumps(body)
            if len(serialized) > self._config.max_body_size:
                return {
                    "_truncated": True,
                    "_original_size": len(serialized),
                    "_preview": serialized[: self._config.max_body_size // 10],
                }
        except (TypeError, ValueError) as e:
            logger.debug("Failed to parse JSON data: %s", e)

        return body

    async def _emit_event(self, event_type: AuditEventType, data: dict[str, Any]) -> None:
        """Emit an audit event to all handlers."""
        for handler in self._event_handlers:
            try:
                handler(event_type, data)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided event handler callback
                logger.error("Error in audit event handler: %s", e)

    async def _send_webhook(self, record: AuditRecord) -> None:
        """Send audit record to webhook."""
        if not self._config.webhook_url:
            return

        try:
            import aiohttp

            payload = {
                "event_type": "audit_record",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "record": record.to_dict(),
            }

            headers = {
                "Content-Type": "application/json",
                **self._config.webhook_headers,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._config.webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self._config.webhook_timeout),
                ) as response:
                    if response.status >= 400:
                        logger.warning(
                            "Webhook failed: status=%d url=%s",
                            response.status,
                            self._config.webhook_url,
                        )
        except ImportError:
            logger.warning("aiohttp not installed, webhook disabled")
        except (OSError, ConnectionError, TimeoutError) as e:
            logger.error("Webhook error: %s", e)


__all__ = [
    "AuditInterceptor",
]
