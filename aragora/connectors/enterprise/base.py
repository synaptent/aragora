"""
Enterprise Connector Base Class.

Extends BaseConnector with incremental sync capabilities for
enterprise data source integration with the Knowledge Mound.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import AsyncIterator, Callable

from aragora.connectors.base import BaseConnector, Evidence
from aragora.reasoning.provenance import SourceType

if TYPE_CHECKING:
    from aragora.connectors.base import ConnectorCapabilities
    from aragora.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


class CredentialProviderProtocol(Protocol):
    """Protocol for credential providers."""

    async def get_credential(self, key: str) -> str | None:
        """Get a credential by key."""
        ...

    async def set_credential(self, key: str, value: str) -> None:
        """Set a credential."""
        ...


class SyncStatus(Enum):
    """Status of a sync operation."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SyncState:
    """
    Persistent state for incremental sync operations.

    Tracks cursor/token position to enable resumable syncs.
    """

    connector_id: str
    tenant_id: str = "default"

    # Cursor tracking
    cursor: str | None = None  # Opaque cursor for pagination
    last_sync_at: datetime | None = None
    last_item_id: str | None = None  # Last processed item ID
    last_item_timestamp: datetime | None = None

    # Sync metadata
    items_synced: int = 0
    items_total: int = 0
    errors: list[str] = field(default_factory=list)

    # Status
    status: SyncStatus = SyncStatus.IDLE
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "connector_id": self.connector_id,
            "tenant_id": self.tenant_id,
            "cursor": self.cursor,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "last_item_id": self.last_item_id,
            "last_item_timestamp": (
                self.last_item_timestamp.isoformat() if self.last_item_timestamp else None
            ),
            "items_synced": self.items_synced,
            "items_total": self.items_total,
            "errors": self.errors[-10:],  # Keep last 10 errors
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncState:
        """Deserialize from dictionary."""
        return cls(
            connector_id=data["connector_id"],
            tenant_id=data.get("tenant_id", "default"),
            cursor=data.get("cursor"),
            last_sync_at=(
                datetime.fromisoformat(data["last_sync_at"]) if data.get("last_sync_at") else None
            ),
            last_item_id=data.get("last_item_id"),
            last_item_timestamp=(
                datetime.fromisoformat(data["last_item_timestamp"])
                if data.get("last_item_timestamp")
                else None
            ),
            items_synced=data.get("items_synced", 0),
            items_total=data.get("items_total", 0),
            errors=data.get("errors", []),
            status=SyncStatus(data.get("status", "idle")),
            started_at=(
                datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
        )

    def save(self, path: Path) -> None:
        """Save state to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> SyncState | None:
        """Load state from file."""
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return cls.from_dict(json.load(f))
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to load sync state from %s: %s", path, e)
            return None


@dataclass
class SyncResult:
    """Result of a sync operation."""

    connector_id: str
    success: bool
    items_synced: int
    items_updated: int
    items_skipped: int
    items_failed: int
    duration_ms: float
    errors: list[str] = field(default_factory=list)
    new_cursor: str | None = None

    @property
    def items_total(self) -> int:
        """Total items processed (synced + updated + skipped + failed)."""
        return self.items_synced + self.items_updated + self.items_skipped + self.items_failed

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "connector_id": self.connector_id,
            "success": self.success,
            "items_synced": self.items_synced,
            "items_updated": self.items_updated,
            "items_skipped": self.items_skipped,
            "items_failed": self.items_failed,
            "duration_ms": self.duration_ms,
            "errors": self.errors,
            "new_cursor": self.new_cursor,
        }


# Import credential providers from dedicated module
_CREDENTIALS_MODULE_AVAILABLE = False

try:
    from aragora.connectors.credentials import (
        get_credential_provider,
    )

    _CREDENTIALS_MODULE_AVAILABLE = True
except ImportError:
    _CREDENTIALS_MODULE_AVAILABLE = False


# Define fallback outside try/except to avoid conditional function variant error
def _fallback_get_credential_provider(
    provider_type: str | None = None,
    **kwargs: Any,
) -> CredentialProviderProtocol:
    return EnvCredentialProvider()


if not _CREDENTIALS_MODULE_AVAILABLE:
    get_credential_provider = _fallback_get_credential_provider


class EnvCredentialProvider:
    """Credential provider using environment variables (backwards compatibility)."""

    def __init__(self, prefix: str = "ARAGORA_"):
        self.prefix = prefix

    async def get_credential(self, key: str) -> str | None:
        """Get credential from environment variable."""
        env_key = f"{self.prefix}{key.upper()}"
        return os.environ.get(env_key)

    async def set_credential(self, key: str, value: str) -> None:
        """Set credential as environment variable (in-memory only)."""
        env_key = f"{self.prefix}{key.upper()}"
        os.environ[env_key] = value


# Type alias for backwards compatibility
CredentialProvider = CredentialProviderProtocol


@dataclass
class SyncItem:
    """An item to be synced to the Knowledge Mound."""

    id: str
    content: str
    source_type: str
    source_id: str
    title: str = ""
    url: str = ""
    author: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    domain: str = "general"
    confidence: float = 0.7
    metadata: dict[str, Any] = field(default_factory=dict)
    # Content hash for change detection (e.g., S3 ETag, GDrive md5Checksum)
    content_hash: str | None = None

    def to_evidence(self, connector_source_type: SourceType) -> Evidence:
        """Convert to Evidence for compatibility with base connector."""
        return Evidence(
            id=self.id,
            source_type=connector_source_type,
            source_id=self.source_id,
            content=self.content,
            title=self.title,
            url=self.url,
            author=self.author,
            created_at=self.created_at.isoformat() if self.created_at else None,
            confidence=self.confidence,
            metadata=self.metadata,
        )

    def has_changed(self, previous_hash: str | None) -> bool:
        """
        Check if the item has changed based on content hash.

        Enables efficient change detection by comparing hashes instead of
        re-processing entire documents. Uses content_hash field (e.g., S3 ETag,
        GDrive md5Checksum) when available.

        Args:
            previous_hash: The hash from the previous sync (None if new item)

        Returns:
            True if the item has changed or is new, False if unchanged
        """
        # New item or no previous hash
        if previous_hash is None:
            return True

        # No current hash available - assume changed
        if self.content_hash is None:
            return True

        # Compare hashes
        return self.content_hash != previous_hash

    def compute_content_hash(self) -> str:
        """
        Compute a content hash if one wasn't provided.

        Uses SHA-256 of content for consistent hashing.
        """
        if self.content_hash:
            return self.content_hash
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class EnterpriseConnector(BaseConnector):
    """
    Extended connector for enterprise data sources.

    Provides:
    - Incremental sync with cursor/token tracking
    - Credential management
    - Knowledge Mound ingestion
    - Multi-tenant isolation
    - Webhook support for real-time sync
    - Circuit breaker protection for API calls
    - OAuth token refresh handling

    Subclasses must implement:
    - source_type: The SourceType for this connector
    - name: Human-readable name
    - sync_items(): Async generator yielding SyncItems
    - search(): Search for evidence (inherited from BaseConnector)
    - fetch(): Fetch specific evidence (inherited from BaseConnector)
    """

    # Circuit breaker configuration
    DEFAULT_CIRCUIT_BREAKER_FAILURES = 5
    DEFAULT_CIRCUIT_BREAKER_COOLDOWN = 60.0  # seconds

    def __init__(
        self,
        connector_id: str,
        tenant_id: str = "default",
        credentials: CredentialProviderProtocol | None = None,
        state_dir: Path | None = None,
        enable_circuit_breaker: bool = True,
        circuit_breaker_failures: int = DEFAULT_CIRCUIT_BREAKER_FAILURES,
        circuit_breaker_cooldown: float = DEFAULT_CIRCUIT_BREAKER_COOLDOWN,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.connector_id = connector_id
        self.tenant_id = tenant_id
        # Use factory function for flexible credential provider auto-detection
        self.credentials: CredentialProviderProtocol = credentials or get_credential_provider()
        if state_dir is None:
            from aragora.persistence.db_config import get_nomic_dir

            state_dir = get_nomic_dir() / "sync_state"
        self.state_dir = state_dir

        # Circuit breaker
        self._enable_circuit_breaker = enable_circuit_breaker
        self._circuit_breaker: CircuitBreaker | None = None
        if enable_circuit_breaker:
            from aragora.resilience import get_circuit_breaker

            self._circuit_breaker = get_circuit_breaker(
                name=f"connector_{connector_id}_{tenant_id}",
                failure_threshold=circuit_breaker_failures,
                cooldown_seconds=circuit_breaker_cooldown,
            )

        # Sync state
        self._state: SyncState | None = None
        self._is_syncing = False
        self._cancel_requested = False

        # Callbacks
        self._on_item_synced: Callable[[SyncItem], None] | None = None
        self._on_progress: Callable[[int, int], None] | None = None

    @property
    def state_path(self) -> Path:
        """Path to sync state file."""
        return self.state_dir / f"{self.connector_id}_{self.tenant_id}.json"

    def load_state(self) -> SyncState:
        """Load or create sync state."""
        if self._state is None:
            self._state = SyncState.load(self.state_path)
            if self._state is None:
                self._state = SyncState(
                    connector_id=self.connector_id,
                    tenant_id=self.tenant_id,
                )
        return self._state

    def save_state(self) -> None:
        """Persist sync state."""
        if self._state:
            self._state.save(self.state_path)

    def check_circuit_breaker(self) -> bool:
        """
        Check if API requests are allowed by the circuit breaker.

        Returns:
            True if requests are allowed, False if circuit is open
        """
        if self._circuit_breaker is None:
            return True
        return self._circuit_breaker.can_proceed()

    def record_success(self) -> None:
        """Record a successful API call for circuit breaker."""
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()

    def record_failure(self) -> None:
        """Record a failed API call for circuit breaker."""
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_failure()

    def get_circuit_breaker_status(self) -> dict[str, Any]:
        """Get current circuit breaker status."""
        if self._circuit_breaker is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "status": self._circuit_breaker.get_status(),
            "failures": self._circuit_breaker.failures,
            "failure_threshold": self._circuit_breaker.failure_threshold,
            "cooldown_seconds": self._circuit_breaker.cooldown_seconds,
        }

    async def execute_with_circuit_breaker(
        self,
        request_func: Callable[[], Any],
        operation: str = "request",
    ) -> Any:
        """
        Execute a request with circuit breaker protection.

        Combines circuit breaker checks with the retry logic from BaseConnector.

        Args:
            request_func: Async callable to execute
            operation: Description for logging

        Returns:
            Result from request_func

        Raises:
            ConnectorAPIError: If circuit is open or request fails
        """
        from aragora.connectors.exceptions import ConnectorAPIError

        # Check circuit breaker first
        if not self.check_circuit_breaker():
            cb_status = self.get_circuit_breaker_status()
            raise ConnectorAPIError(
                f"Circuit breaker open for {self.connector_id}. "
                f"Cooldown: {cb_status.get('cooldown_seconds', 60)}s",
                connector_name=self.name,
            )

        try:
            # Use base class retry logic
            result = await self._request_with_retry(request_func, operation)
            self.record_success()
            return result
        except (OSError, ValueError, TypeError, RuntimeError):
            self.record_failure()
            raise

    @abstractmethod
    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield items to sync incrementally.

        Subclasses implement this to fetch items from their source.
        Should use state.cursor for pagination and update state.last_item_id.

        Args:
            state: Current sync state with cursor
            batch_size: Number of items per batch

        Yields:
            SyncItem objects to ingest into Knowledge Mound
        """
        # Abstract async generator - subclasses must implement
        # This pattern is required to make mypy recognize this as an async generator
        if False:  # pragma: no cover
            yield SyncItem(
                id="",
                content="",
                source_type="",
                source_id="",
            )

    async def sync(
        self,
        full_sync: bool = False,
        batch_size: int = 100,
        max_items: int | None = None,
    ) -> SyncResult:
        """
        Run incremental sync from this connector to Knowledge Mound.

        Args:
            full_sync: If True, ignore cursor and sync everything
            batch_size: Items per batch
            max_items: Maximum items to sync (for testing)

        Returns:
            SyncResult with statistics
        """
        if self._is_syncing:
            return SyncResult(
                connector_id=self.connector_id,
                success=False,
                items_synced=0,
                items_updated=0,
                items_skipped=0,
                items_failed=0,
                duration_ms=0,
                errors=["Sync already in progress"],
            )

        self._is_syncing = True
        self._cancel_requested = False
        start_time = time.time()

        state = self.load_state()
        if full_sync:
            state.cursor = None
            state.last_item_id = None

        state.status = SyncStatus.RUNNING
        state.started_at = datetime.now(timezone.utc)
        state.errors = []

        items_synced = 0
        items_updated = 0
        items_skipped = 0
        items_failed = 0
        errors = []

        try:
            # Normalize AsyncMock side_effect lists to iterators (test safety).
            try:
                from unittest.mock import AsyncMock

                ingest = self._ingest_item
                if isinstance(ingest, AsyncMock):
                    side_effect = getattr(ingest, "side_effect", None)
                    if isinstance(side_effect, list):
                        ingest.side_effect = iter(side_effect)
            except (ImportError, TypeError, AttributeError) as e:
                logger.debug("Mock side_effect normalization skipped: %s", e)

            async for item in self.sync_items(state, batch_size):
                if self._cancel_requested:
                    logger.info("[%s] Sync cancelled", self.name)
                    state.status = SyncStatus.CANCELLED
                    break

                if max_items and items_synced >= max_items:
                    logger.info("[%s] Reached max items limit: %s", self.name, max_items)
                    break

                try:
                    result = await self._ingest_item(item)
                    if result == "created":
                        items_synced += 1
                    elif result == "updated":
                        items_updated += 1
                    elif result == "skipped":
                        items_skipped += 1

                    state.last_item_id = item.id
                    if item.updated_at:
                        state.last_item_timestamp = item.updated_at
                    state.items_synced = items_synced + items_updated

                    if self._on_item_synced:
                        self._on_item_synced(item)

                    if self._on_progress:
                        self._on_progress(items_synced + items_updated, state.items_total)

                except (OSError, ValueError, TypeError, RuntimeError, KeyError) as e:
                    items_failed += 1
                    error_msg = f"Failed to ingest {item.id}: {e}"
                    state.errors.append(error_msg)
                    logger.warning("[%s] %s", self.name, error_msg)

                # Periodic state save
                if (items_synced + items_updated) % 100 == 0:
                    self.save_state()

            if state.status != SyncStatus.CANCELLED:
                state.status = SyncStatus.COMPLETED

        except (OSError, ValueError, TypeError, RuntimeError) as e:
            state.status = SyncStatus.FAILED
            errors.append(f"Sync failed: {e}")
            logger.error("[%s] Sync failed: %s", self.name, e)

        finally:
            state.completed_at = datetime.now(timezone.utc)
            state.last_sync_at = datetime.now(timezone.utc)
            self.save_state()
            self._is_syncing = False

        duration_ms = (time.time() - start_time) * 1000

        return SyncResult(
            connector_id=self.connector_id,
            success=state.status == SyncStatus.COMPLETED,
            items_synced=items_synced,
            items_updated=items_updated,
            items_skipped=items_skipped,
            items_failed=items_failed,
            duration_ms=duration_ms,
            # state.errors is reset at the start of the run, so it holds only this
            # run's ingest failures and those recorded by sync_items.
            errors=[*state.errors, *errors],
            new_cursor=state.cursor,
        )

    async def _ingest_item(self, item: SyncItem) -> str:
        """
        Ingest a sync item into the Knowledge Mound.

        Returns: "created", "updated", or "skipped"
        """
        try:
            from aragora.knowledge.mound import (
                get_knowledge_mound,
                IngestionRequest,
                KnowledgeSource,
            )

            # Map source type string to enum
            source_type_map: dict[str, KnowledgeSource] = {
                "code": KnowledgeSource.FACT,
                "document": KnowledgeSource.FACT,
                "issue": KnowledgeSource.FACT,
                "pr": KnowledgeSource.FACT,
                "discussion": KnowledgeSource.CONSENSUS,
                "comment": KnowledgeSource.FACT,
            }
            source_type = source_type_map.get(item.source_type, KnowledgeSource.FACT)

            request = IngestionRequest(
                content=item.content,
                workspace_id=self.tenant_id,
                source_type=source_type,
                document_id=item.source_id,
                confidence=item.confidence,
                topics=[item.domain],
                metadata={
                    "connector_id": self.connector_id,
                    "source_url": item.url,
                    "author": item.author,
                    "title": item.title,
                    **item.metadata,
                },
            )

            # Use the singleton getter which handles initialization properly
            mound = get_knowledge_mound(workspace_id=self.tenant_id)
            result = await mound.store(request)

            if result.deduplicated:
                return "skipped"
            return "created"

        except ImportError:
            logger.debug("[%s] Knowledge Mound not available, skipping ingestion", self.name)
            return "skipped"

    def cancel_sync(self) -> None:
        """Request cancellation of running sync."""
        self._cancel_requested = True

    def on_item_synced(self, callback: Callable[[SyncItem], None]) -> None:
        """Register callback for when an item is synced."""
        self._on_item_synced = callback

    def on_progress(self, callback: Callable[[int, int], None]) -> None:
        """Register callback for progress updates."""
        self._on_progress = callback

    async def get_sync_status(self) -> dict[str, Any]:
        """Get current sync status."""
        state = self.load_state()
        return {
            "connector_id": self.connector_id,
            "connector_name": self.name,
            "tenant_id": self.tenant_id,
            "status": state.status.value,
            "is_syncing": self._is_syncing,
            "last_sync_at": state.last_sync_at.isoformat() if state.last_sync_at else None,
            "items_synced": state.items_synced,
            "cursor": state.cursor,
            "errors": state.errors[-5:],
        }

    # Webhook support for real-time sync

    async def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """
        Handle incoming webhook for real-time sync.

        Subclasses override to handle source-specific webhooks.

        Args:
            payload: Webhook payload

        Returns:
            True if handled successfully
        """
        logger.debug("[%s] Webhook received but not implemented", self.name)
        return False

    def get_webhook_secret(self) -> str | None:
        """Get webhook secret for signature verification."""
        return None

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify webhook signature."""
        secret = self.get_webhook_secret()
        if not secret:
            return True  # No secret configured, skip verification

        import hmac

        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    def capabilities(self) -> ConnectorCapabilities:
        """
        Report the capabilities of this enterprise connector.

        Enterprise connectors extend base connectors with sync capabilities.

        Returns:
            ConnectorCapabilities for this connector
        """
        from aragora.connectors.base import ConnectorCapabilities

        return ConnectorCapabilities(
            can_send=False,
            can_receive=False,
            can_search=True,
            can_sync=True,  # Enterprise connectors support incremental sync
            can_stream=False,
            can_batch=True,  # Batch processing via sync
            is_stateful=False,
            requires_auth=True,
            supports_oauth=False,  # Subclasses may override
            supports_webhooks=True,  # Enterprise connectors support webhooks
            supports_files=False,
            supports_rich_text=False,
            supports_reactions=False,
            supports_threads=False,
            supports_voice=False,
            supports_delivery_receipts=False,
            supports_retry=True,
            has_circuit_breaker=self._enable_circuit_breaker,
        )
