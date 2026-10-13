"""
Debate queue management for batch processing.

Provides a queue-based approach for processing multiple debates with:
- Priority ordering (higher priority debates run first)
- Concurrency limits (configurable max parallel debates)
- Progress tracking and status monitoring
- Webhook callbacks on completion

Usage:
    from aragora.server.debate_queue import DebateQueue, BatchRequest, BatchItem

    queue = DebateQueue(max_concurrent=3)

    batch = BatchRequest(
        items=[
            BatchItem(question="Question 1", agents="anthropic-api,openai-api"),
            BatchItem(question="Question 2", priority=10),  # Higher priority
        ],
        webhook_url="https://example.com/callback",
    )

    batch_id = await queue.submit_batch(batch)
    status = queue.get_batch_status(batch_id)
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.agents.spec import AgentSpec
from aragora.config import DEFAULT_AGENTS, DEFAULT_CONSENSUS, DEFAULT_ROUNDS, MAX_ROUNDS
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MAX_WEBHOOK_URL_LENGTH = 2048
MAX_WEBHOOK_HEADER_COUNT = 20
MAX_WEBHOOK_HEADER_SIZE = 1024
BLOCKED_WEBHOOK_SUFFIXES = (".internal", ".local", ".localhost", ".lan")
BLOCKED_METADATA_HOSTNAMES = frozenset(
    [
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    ]
)


def _serialize_agent_spec(spec: AgentSpec) -> str:
    """Serialize AgentSpec using empty fields for unspecified values."""
    return f"{spec.provider}|{spec.model or ''}|{spec.persona or ''}|{spec.role or ''}"


def validate_webhook_url(url: str) -> tuple[bool, str]:
    """Validate webhook URL to prevent SSRF and malformed requests."""
    if not url or not isinstance(url, str):
        return False, "webhook_url must be a non-empty string"
    if len(url) > MAX_WEBHOOK_URL_LENGTH:
        return False, "webhook_url is too long"

    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "Invalid webhook_url format"

    if parsed.scheme not in ("http", "https"):
        return False, "webhook_url must use http or https"
    if not parsed.hostname:
        return False, "webhook_url must include a hostname"

    hostname = parsed.hostname.lower()
    if hostname in BLOCKED_METADATA_HOSTNAMES:
        return False, "webhook_url points to a blocked metadata endpoint"
    if hostname.endswith(BLOCKED_WEBHOOK_SUFFIXES):
        return False, "webhook_url uses an internal hostname"

    allow_localhost = os.environ.get("ARAGORA_WEBHOOK_ALLOW_LOCALHOST", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if allow_localhost and hostname in ("localhost", "127.0.0.1", "::1"):
        return True, ""

    try:
        ip_obj = ipaddress.ip_address(hostname)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            return False, "webhook_url resolves to a private or local address"
        return True, ""
    except ValueError:
        pass

    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, "webhook_url hostname could not be resolved"

    for family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            return False, "webhook_url resolves to a private or local address"

    return True, ""


def sanitize_webhook_headers(
    headers: dict[str, Any] | None,
) -> tuple[dict[str, str], str | None]:
    """Validate and sanitize webhook headers."""
    if headers is None:
        return {}, None
    if not isinstance(headers, dict):
        return {}, "webhook_headers must be an object"

    sanitized: dict[str, str] = {}
    for key, value in headers.items():
        if len(sanitized) >= MAX_WEBHOOK_HEADER_COUNT:
            return {}, "webhook_headers exceeds maximum header count"
        if not isinstance(key, str) or not isinstance(value, str):
            return {}, "webhook_headers keys and values must be strings"
        if "\n" in key or "\r" in key or "\n" in value or "\r" in value:
            return {}, "webhook_headers contains invalid characters"
        if len(key) > 200 or len(value) > MAX_WEBHOOK_HEADER_SIZE:
            return {}, "webhook_headers contains oversized values"
        sanitized[key] = value

    return sanitized, None


class BatchStatus(str, Enum):
    """Status of a batch request."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"  # Some items failed
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemStatus(str, Enum):
    """Status of an individual batch item."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BatchItem:
    """A single debate request within a batch."""

    question: str
    agents: str = "anthropic-api,openai-api,gemini"
    rounds: int = DEFAULT_ROUNDS
    consensus: str = "majority"
    priority: int = 0  # Higher = runs first
    metadata: dict[str, Any] = field(default_factory=dict)

    # Populated during execution
    item_id: str = field(default_factory=lambda: f"item_{uuid.uuid4().hex[:8]}")
    status: ItemStatus = ItemStatus.QUEUED
    debate_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "item_id": self.item_id,
            "question": self.question,
            "agents": self.agents,
            "rounds": self.rounds,
            "consensus": self.consensus,
            "priority": self.priority,
            "metadata": self.metadata,
            "status": self.status.value,
            "debate_id": self.debate_id,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": (
                self.completed_at - self.started_at
                if self.completed_at and self.started_at
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BatchItem:
        """Create from dictionary (e.g., parsed JSON)."""
        question = str(data.get("question", "")).strip()
        if not question:
            raise ValueError("question is required")
        if len(question) > 10000:
            raise ValueError("question exceeds 10,000 characters")

        raw_agents = data.get("agents", DEFAULT_AGENTS)
        if raw_agents is None:
            agents = DEFAULT_AGENTS
        elif isinstance(raw_agents, str):
            agents = raw_agents.strip()
        elif isinstance(raw_agents, dict):
            agents = _serialize_agent_spec(AgentSpec.coerce_list(raw_agents, warn=False)[0])
        elif isinstance(raw_agents, list):
            normalized_agents: list[str] = []
            for item in raw_agents:
                if isinstance(item, str):
                    agent_name = item.strip()
                    if agent_name:
                        normalized_agents.append(agent_name)
                    continue
                if isinstance(item, dict):
                    normalized_agents.append(
                        _serialize_agent_spec(AgentSpec.coerce_list(item, warn=False)[0])
                    )
                    continue
                raise ValueError("agents must be a string, object, or list of strings/objects")
            agents = ",".join(normalized_agents)
        else:
            raise ValueError("agents must be a string, object, or list of strings/objects")

        try:
            rounds = min(max(int(data.get("rounds", DEFAULT_ROUNDS)), 1), MAX_ROUNDS)
        except (TypeError, ValueError):
            rounds = DEFAULT_ROUNDS

        consensus = str(data.get("consensus", DEFAULT_CONSENSUS)).strip()
        if consensus not in {"majority", "unanimous", "judge", "hybrid", "none"}:
            raise ValueError("consensus must be one of: majority, unanimous, judge, hybrid, none")

        try:
            priority = int(data.get("priority", 0))
        except (TypeError, ValueError):
            priority = 0

        metadata = data.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")

        return cls(
            question=question,
            agents=agents or "anthropic-api,openai-api,gemini",
            rounds=rounds,
            consensus=consensus,
            priority=priority,
            metadata=metadata,
        )


@dataclass
class BatchRequest:
    """A batch of debate requests to process."""

    items: list[BatchItem]
    webhook_url: str | None = None  # Called when batch completes
    webhook_headers: dict[str, str] = field(default_factory=dict)
    max_parallel: int | None = None  # Override queue's default

    # Populated during execution
    batch_id: str = field(default_factory=lambda: f"batch_{uuid.uuid4().hex[:12]}")
    status: BatchStatus = BatchStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        completed = sum(1 for i in self.items if i.status == ItemStatus.COMPLETED)
        failed = sum(1 for i in self.items if i.status == ItemStatus.FAILED)
        running = sum(1 for i in self.items if i.status == ItemStatus.RUNNING)
        queued = sum(1 for i in self.items if i.status == ItemStatus.QUEUED)

        return {
            "batch_id": self.batch_id,
            "status": self.status.value,
            "total_items": len(self.items),
            "completed": completed,
            "failed": failed,
            "running": running,
            "queued": queued,
            "progress_percent": (
                round(100 * (completed + failed) / len(self.items), 1) if self.items else 0
            ),
            "webhook_url": self.webhook_url,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": (
                self.completed_at - self.started_at
                if self.completed_at and self.started_at
                else None
            ),
            "items": [item.to_dict() for item in self.items],
        }

    def summary(self) -> dict[str, Any]:
        """Get summary without individual items (for list endpoints)."""
        result = self.to_dict()
        del result["items"]
        return result


class DebateQueue:
    """
    Queue manager for batch debate processing.

    Handles:
    - Priority-based ordering of debates
    - Concurrency limits
    - Progress tracking
    - Webhook notifications

    Thread Safety:
        Uses asyncio primitives for coordination. The actual debate
        execution uses DebateController's thread pool.
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        debate_executor: Callable | None = None,
    ):
        """
        Initialize the debate queue.

        Args:
            max_concurrent: Maximum debates to run in parallel
            debate_executor: Callable that runs a single debate.
                            Signature: async (item: BatchItem) -> dict[str, Any]
        """
        self.max_concurrent = max_concurrent
        self.debate_executor = debate_executor

        # Active batches by batch_id
        self._batches: dict[str, BatchRequest] = {}

        # Processing state
        self._processing_lock = asyncio.Lock()
        self._active_count = 0

        # Background processing task
        self._processor_task: asyncio.Task | None = None
        self._shutdown = False

    def _has_pending_batches_locked(self) -> bool:
        """Return whether any batch still needs processor attention.

        Callers must hold ``self._processing_lock``.
        """
        if self._active_count > 0:
            return True
        return any(
            batch.status in (BatchStatus.PENDING, BatchStatus.PROCESSING)
            for batch in self._batches.values()
        )

    async def submit_batch(self, batch: BatchRequest) -> str:
        """
        Submit a batch of debates for processing.

        Args:
            batch: BatchRequest with items to process

        Returns:
            batch_id for tracking
        """
        if not batch.items:
            raise ValueError("Batch must contain at least one item")

        if len(batch.items) > 1000:
            raise ValueError("Batch cannot exceed 1000 items")

        # Sort items by priority (highest first)
        batch.items.sort(key=lambda x: x.priority, reverse=True)

        async with self._processing_lock:
            # Register batch
            self._batches[batch.batch_id] = batch

            # Start processing if not already running
            if self._processor_task is None or self._processor_task.done():
                self._processor_task = asyncio.create_task(self._process_batches())

        logger.info("Batch %s submitted with %s items", batch.batch_id, len(batch.items))

        return batch.batch_id

    def get_batch_status(self, batch_id: str) -> dict[str, Any] | None:
        """Get status of a batch."""
        batch = self._batches.get(batch_id)
        if batch:
            return batch.to_dict()
        return None

    def get_batch_summary(self, batch_id: str) -> dict[str, Any] | None:
        """Get summary of a batch (without individual items)."""
        batch = self._batches.get(batch_id)
        if batch:
            return batch.summary()
        return None

    def list_batches(
        self,
        status: BatchStatus | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List batches, optionally filtered by status."""
        batches = list(self._batches.values())

        if status:
            batches = [b for b in batches if b.status == status]

        # Sort by creation time, newest first
        batches.sort(key=lambda x: x.created_at, reverse=True)

        return [b.summary() for b in batches[:limit]]

    async def cancel_batch(self, batch_id: str) -> bool:
        """
        Cancel a pending or processing batch.

        Debates already running will complete, but queued items
        will be cancelled.
        """
        batch = self._batches.get(batch_id)
        if not batch:
            return False

        if batch.status in (BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.CANCELLED):
            return False  # Already terminal

        batch.status = BatchStatus.CANCELLED

        # Cancel queued items
        for item in batch.items:
            if item.status == ItemStatus.QUEUED:
                item.status = ItemStatus.CANCELLED

        logger.info("Batch %s cancelled", batch_id)
        return True

    async def _process_batches(self) -> None:
        """Background task that processes batches."""
        try:
            while not self._shutdown:
                # Find work to do
                work = await self._get_next_work()

                if not work:
                    async with self._processing_lock:
                        if not self._has_pending_batches_locked():
                            self._processor_task = None
                            return

                    # No work available yet, wait a bit
                    await asyncio.sleep(0.1)
                    continue

                batch, item = work

                # Process item
                await self._process_item(batch, item)
        finally:
            current_task = asyncio.current_task()
            if self._processor_task is current_task:
                self._processor_task = None

    async def _get_next_work(self) -> tuple[BatchRequest, BatchItem] | None:
        """Get the next item to process."""
        async with self._processing_lock:
            if self._active_count >= self.max_concurrent:
                return None

            # Find a batch with pending items
            for batch in self._batches.values():
                if batch.status in (
                    BatchStatus.COMPLETED,
                    BatchStatus.FAILED,
                    BatchStatus.CANCELLED,
                ):
                    continue

                # Start batch if not started
                if batch.status == BatchStatus.PENDING:
                    batch.status = BatchStatus.PROCESSING
                    batch.started_at = time.time()

                if batch.max_parallel:
                    running_for_batch = sum(
                        1 for item in batch.items if item.status == ItemStatus.RUNNING
                    )
                    if running_for_batch >= batch.max_parallel:
                        continue

                # Find next queued item
                for item in batch.items:
                    if item.status == ItemStatus.QUEUED:
                        item.status = ItemStatus.RUNNING
                        item.started_at = time.time()
                        self._active_count += 1
                        return batch, item

            return None

    async def _process_item(self, batch: BatchRequest, item: BatchItem) -> None:
        """Process a single batch item."""
        try:
            if self.debate_executor:
                result = await self.debate_executor(item)
                item.result = result
                item.debate_id = result.get("debate_id")
                item.status = ItemStatus.COMPLETED
            else:
                # No executor configured, simulate for testing
                item.status = ItemStatus.FAILED
                item.error = "No debate executor configured"

        except (RuntimeError, ValueError, TimeoutError, asyncio.CancelledError) as e:
            logger.error("Failed to process item %s: %s", item.item_id, e)
            item.status = ItemStatus.FAILED
            item.error = str(e).strip() or "Debate execution failed"
        finally:
            item.completed_at = time.time()

            async with self._processing_lock:
                self._active_count -= 1

            # Check if batch is complete
            await self._check_batch_completion(batch)

    async def _check_batch_completion(self, batch: BatchRequest) -> None:
        """Check if batch is complete and trigger webhook if so."""
        pending = sum(
            1 for item in batch.items if item.status in (ItemStatus.QUEUED, ItemStatus.RUNNING)
        )

        if pending > 0:
            return  # Still processing

        # Batch complete
        batch.completed_at = time.time()

        failed = sum(1 for item in batch.items if item.status == ItemStatus.FAILED)
        cancelled = sum(1 for item in batch.items if item.status == ItemStatus.CANCELLED)

        if cancelled == len(batch.items):
            batch.status = BatchStatus.CANCELLED
        elif failed == len(batch.items):
            batch.status = BatchStatus.FAILED
        elif failed > 0 or cancelled > 0:
            batch.status = BatchStatus.PARTIAL
        else:
            batch.status = BatchStatus.COMPLETED

        logger.info(
            "Batch %s completed: %s/%s succeeded",
            batch.batch_id,
            len(batch.items) - failed - cancelled,
            len(batch.items),
        )

        # Trigger webhook if configured
        if batch.webhook_url:
            await self._send_webhook(batch)

    async def _send_webhook(self, batch: BatchRequest) -> None:
        """Send webhook notification for completed batch."""
        try:
            from aragora.observability.http_client_pool import get_http_pool

            is_valid, error_msg = validate_webhook_url(batch.webhook_url or "")
            if not is_valid:
                logger.warning(
                    "Webhook skipped for batch %s: %s",
                    batch.batch_id,
                    error_msg,
                )
                return

            extra_headers, header_error = sanitize_webhook_headers(batch.webhook_headers)
            if header_error:
                logger.warning(
                    "Webhook headers invalid for batch %s: %s",
                    batch.batch_id,
                    header_error,
                )
                return

            payload = batch.to_dict()
            headers = {"Content-Type": "application/json"}
            headers.update(extra_headers)

            pool = get_http_pool()
            async with pool.get_session("webhook") as client:
                response = await client.post(
                    batch.webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
                if response.status_code >= 400:
                    logger.warning(
                        "Webhook failed for batch %s: status=%s",
                        batch.batch_id,
                        response.status_code,
                    )
                else:
                    logger.info("Webhook sent for batch %s", batch.batch_id)
        except ImportError:
            logger.debug("httpx not available for webhook")
        except (ConnectionError, OSError, TimeoutError, asyncio.TimeoutError) as e:
            logger.error("Webhook error for batch %s: %s", batch.batch_id, e)

    def cleanup_old_batches(self, max_age_hours: int = 24) -> int:
        """Remove batches older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        to_remove = [
            batch_id
            for batch_id, batch in self._batches.items()
            if batch.created_at < cutoff
            and batch.status
            in (
                BatchStatus.COMPLETED,
                BatchStatus.FAILED,
                BatchStatus.CANCELLED,
            )
        ]

        for batch_id in to_remove:
            del self._batches[batch_id]

        return len(to_remove)

    async def shutdown(self) -> None:
        """Shutdown the queue processor."""
        self._shutdown = True
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
            finally:
                self._processor_task = None


# Global queue instance
_queue: DebateQueue | None = None
_queue_lock = asyncio.Lock()


async def get_debate_queue() -> DebateQueue:
    """Get the global debate queue instance."""
    global _queue

    async with _queue_lock:
        if _queue is None:
            from aragora.config import MAX_CONCURRENT_DEBATES

            _queue = DebateQueue(max_concurrent=MAX_CONCURRENT_DEBATES)
        return _queue


def get_debate_queue_sync() -> DebateQueue | None:
    """Get the global debate queue instance (sync version)."""
    return _queue


__all__ = [
    "DebateQueue",
    "BatchRequest",
    "BatchItem",
    "BatchStatus",
    "ItemStatus",
    "get_debate_queue",
    "get_debate_queue_sync",
    "validate_webhook_url",
    "sanitize_webhook_headers",
]
