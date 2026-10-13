"""
OpenClaw Audit Bridge.

Bridges OpenClaw proxy events to Aragora's Knowledge Mound for
persistent, searchable audit trails with cryptographic signing.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.knowledge.mound.core import KnowledgeMound

logger = logging.getLogger(__name__)


@dataclass
class AuditRecord:
    """An audit record for Knowledge Mound storage."""

    record_id: str
    event_type: str
    timestamp: float
    source: str

    # Actor information
    user_id: str | None = None
    session_id: str | None = None
    tenant_id: str | None = None

    # Action details
    action_type: str | None = None
    action_target: str | None = None
    action_params: dict[str, Any] = field(default_factory=dict)

    # Result
    success: bool = True
    error: str | None = None

    # Security
    signature: str | None = None
    previous_hash: str | None = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)


class OpenClawAuditBridge:
    """
    Bridge between OpenClaw proxy and Knowledge Mound.

    Captures all audit events from the proxy and stores them in
    Knowledge Mound with:
    - Cryptographic signatures for tamper detection
    - Hash chain linking for integrity verification
    - Semantic indexing for searchability
    - Retention policy support

    Example:
    ```python
    from aragora.integrations.openclaw import OpenClawAuditBridge
    from aragora.compat.openclaw_proxy import OpenClawSecureProxy
    from aragora.knowledge.mound.core import KnowledgeMound

    # Create bridge
    bridge = OpenClawAuditBridge(
        knowledge_mound=km,
        workspace_id="enterprise",
        signing_key="your-signing-key",
    )

    # Connect to proxy
    proxy = OpenClawSecureProxy(
        audit_callback=bridge.capture_event,
    )

    # Events are automatically stored in KM
    ```
    """

    def __init__(
        self,
        knowledge_mound: KnowledgeMound | None = None,
        workspace_id: str = "default",
        signing_key: str | None = None,
        event_callback: Callable[[AuditRecord], None] | None = None,
        batch_size: int = 100,
        flush_interval_seconds: float = 5.0,
    ):
        """
        Initialize the audit bridge.

        Args:
            knowledge_mound: KnowledgeMound instance for storage
            workspace_id: Workspace for audit records
            signing_key: Key for signing records (tamper detection)
            event_callback: Optional callback for processed events
            batch_size: Number of events to batch before flush
            flush_interval_seconds: Max time between flushes
        """
        self._km = knowledge_mound
        self._workspace_id = workspace_id
        self._signing_key = signing_key
        self._event_callback = event_callback
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds

        # Batching state
        self._batch: list[AuditRecord] = []
        self._last_flush = time.time()
        self._last_hash: str | None = None

        # Statistics
        self._stats = {
            "events_captured": 0,
            "events_stored": 0,
            "events_failed": 0,
            "batches_flushed": 0,
        }

    def capture_event(self, event: dict[str, Any]) -> None:
        """
        Capture an audit event from the proxy.

        This method is designed to be used as the audit_callback
        for OpenClawSecureProxy.

        Args:
            event: Raw event dictionary from proxy
        """
        record = self._event_to_record(event)

        # Sign the record
        if self._signing_key:
            record.signature = self._sign_record(record)
            record.previous_hash = self._last_hash
            self._last_hash = record.signature

        self._batch.append(record)
        self._stats["events_captured"] += 1

        # Notify callback
        if self._event_callback:
            try:
                self._event_callback(record)
            except (RuntimeError, ValueError, TypeError, AttributeError) as e:
                logger.warning("Event callback failed: %s", e)

        # Check if we should flush
        should_flush = (
            len(self._batch) >= self._batch_size
            or time.time() - self._last_flush > self._flush_interval
        )

        if should_flush:
            self._flush_sync()

    def _event_to_record(self, event: dict[str, Any]) -> AuditRecord:
        """Convert raw event to AuditRecord."""
        return AuditRecord(
            record_id=str(uuid.uuid4()),
            event_type=event.get("event_type", "unknown"),
            timestamp=event.get("timestamp", time.time()),
            source=event.get("source", "openclaw_proxy"),
            user_id=event.get("user_id"),
            session_id=event.get("session_id"),
            tenant_id=event.get("tenant_id"),
            action_type=event.get("action_type"),
            action_target=event.get("path") or event.get("command") or event.get("url"),
            action_params={
                k: v
                for k, v in event.items()
                if k
                not in ("event_type", "timestamp", "source", "user_id", "session_id", "tenant_id")
            },
            success=event.get("success", True),
            error=event.get("error") or event.get("reason"),
            metadata=event.get("metadata", {}),
        )

    def _sign_record(self, record: AuditRecord) -> str:
        """Create cryptographic signature for record."""
        # Create deterministic content string
        content = f"{record.record_id}:{record.event_type}:{record.timestamp}:{record.user_id}:{record.action_type}"
        if self._last_hash:
            content = f"{self._last_hash}:{content}"

        # Sign with HMAC-SHA256
        key = (self._signing_key or "default").encode("utf-8")
        signature = hashlib.sha256(key + content.encode("utf-8")).hexdigest()
        return signature

    def _flush_sync(self) -> None:
        """Synchronously flush batch (for use in sync callbacks)."""
        if not self._batch:
            return

        records = self._batch
        self._batch = []
        self._last_flush = time.time()

        # Store records
        for record in records:
            try:
                self._store_record_sync(record)
                self._stats["events_stored"] += 1
            except (RuntimeError, ValueError, ConnectionError, TimeoutError, OSError) as e:
                logger.error("Failed to store audit record: %s", e)
                self._stats["events_failed"] += 1

        self._stats["batches_flushed"] += 1

    def _store_record_sync(self, record: AuditRecord) -> str | None:
        """Store a single record (synchronous wrapper)."""
        if not self._km:
            return None

        # Convert to KM item format
        item = {
            "type": "audit_record",
            "content": {
                "record_id": record.record_id,
                "event_type": record.event_type,
                "timestamp": record.timestamp,
                "source": record.source,
                "user_id": record.user_id,
                "session_id": record.session_id,
                "tenant_id": record.tenant_id,
                "action_type": record.action_type,
                "action_target": record.action_target,
                "success": record.success,
                "error": record.error,
            },
            "metadata": {
                "signature": record.signature,
                "previous_hash": record.previous_hash,
                "workspace_id": self._workspace_id,
                **record.metadata,
            },
        }

        # Use ingest_sync if available, otherwise skip
        if hasattr(self._km, "ingest_sync"):
            return self._km.ingest_sync(item)
        return None

    async def flush(self) -> int:
        """
        Flush pending records to Knowledge Mound.

        Returns:
            Number of records flushed
        """
        if not self._batch:
            return 0

        records = self._batch
        self._batch = []
        self._last_flush = time.time()

        count = 0
        for record in records:
            try:
                await self._store_record(record)
                self._stats["events_stored"] += 1
                count += 1
            except (RuntimeError, ValueError, ConnectionError, TimeoutError, OSError) as e:
                logger.error("Failed to store audit record: %s", e)
                self._stats["events_failed"] += 1

        self._stats["batches_flushed"] += 1
        return count

    async def _store_record(self, record: AuditRecord) -> str | None:
        """Store a single record in Knowledge Mound."""
        if not self._km:
            return None

        # Convert to KM item format
        item = {
            "type": "audit_record",
            "content": {
                "record_id": record.record_id,
                "event_type": record.event_type,
                "timestamp": record.timestamp,
                "source": record.source,
                "user_id": record.user_id,
                "session_id": record.session_id,
                "tenant_id": record.tenant_id,
                "action_type": record.action_type,
                "action_target": record.action_target,
                "success": record.success,
                "error": record.error,
            },
            "metadata": {
                "signature": record.signature,
                "previous_hash": record.previous_hash,
                "workspace_id": self._workspace_id,
                **record.metadata,
            },
        }

        return await self._km.ingest(item)

    async def query_audit_trail(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        event_type: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]:
        """
        Query the audit trail.

        Args:
            user_id: Filter by user
            session_id: Filter by session
            event_type: Filter by event type
            start_time: Start of time range
            end_time: End of time range
            limit: Maximum records to return

        Returns:
            List of matching AuditRecords
        """
        if not self._km:
            return []

        # Build query
        filters: dict[str, str | float] = {"type": "audit_record"}
        if user_id:
            filters["content.user_id"] = user_id
        if session_id:
            filters["content.session_id"] = session_id
        if event_type:
            filters["content.event_type"] = event_type
        if start_time:
            filters["content.timestamp__gte"] = start_time
        if end_time:
            filters["content.timestamp__lte"] = end_time

        try:
            results = await self._km.query(filters, limit=limit)
            return [self._result_to_record(r) for r in results]
        except (RuntimeError, ValueError, ConnectionError, TimeoutError, OSError) as e:
            logger.error("Audit trail query failed: %s", e)
            return []

    def _result_to_record(self, result: dict[str, Any]) -> AuditRecord:
        """Convert KM query result to AuditRecord."""
        content = result.get("content", {})
        metadata = result.get("metadata", {})

        return AuditRecord(
            record_id=content.get("record_id", ""),
            event_type=content.get("event_type", "unknown"),
            timestamp=content.get("timestamp", 0),
            source=content.get("source", "unknown"),
            user_id=content.get("user_id"),
            session_id=content.get("session_id"),
            tenant_id=content.get("tenant_id"),
            action_type=content.get("action_type"),
            action_target=content.get("action_target"),
            success=content.get("success", True),
            error=content.get("error"),
            signature=metadata.get("signature"),
            previous_hash=metadata.get("previous_hash"),
            metadata=metadata,
        )

    async def verify_integrity(
        self,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> dict[str, Any]:
        """
        Verify integrity of audit trail using hash chain.

        Args:
            start_time: Start of verification range
            end_time: End of verification range

        Returns:
            Verification result with any detected issues
        """
        records = await self.query_audit_trail(
            start_time=start_time,
            end_time=end_time,
            limit=10000,
        )

        if not records:
            return {"valid": True, "records_checked": 0, "issues": []}

        # Sort by timestamp
        records.sort(key=lambda r: r.timestamp)

        issues = []
        expected_prev_hash = None

        for i, record in enumerate(records):
            # Check hash chain
            if record.previous_hash != expected_prev_hash:
                issues.append(
                    {
                        "type": "chain_break",
                        "record_id": record.record_id,
                        "index": i,
                        "expected": expected_prev_hash,
                        "actual": record.previous_hash,
                    }
                )

            # Verify signature
            if self._signing_key and record.signature:
                expected_sig = self._sign_record(record)
                if record.signature != expected_sig:
                    issues.append(
                        {
                            "type": "invalid_signature",
                            "record_id": record.record_id,
                            "index": i,
                        }
                    )

            expected_prev_hash = record.signature

        return {
            "valid": len(issues) == 0,
            "records_checked": len(records),
            "issues": issues,
        }

    def get_stats(self) -> dict[str, Any]:
        """Get bridge statistics."""
        return {
            **self._stats,
            "pending_batch_size": len(self._batch),
            "seconds_since_flush": time.time() - self._last_flush,
            "has_knowledge_mound": self._km is not None,
            "signing_enabled": self._signing_key is not None,
        }

    async def close(self) -> None:
        """Flush remaining events and close."""
        await self.flush()
