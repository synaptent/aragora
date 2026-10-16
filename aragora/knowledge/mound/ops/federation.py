"""
Knowledge Federation Mixin for Knowledge Mound.

Provides operations for multi-region knowledge synchronization:
- register_federated_region: Register a remote region for sync
- sync_to_region: Push knowledge to a federated region
- pull_from_region: Pull knowledge from a federated region
- get_federation_status: Get sync status for all regions
- configure_federation_policy: Set up sync policies

This integrates with the CrossWorkspaceCoordinator for federation
operations and leverages existing FederationPolicy infrastructure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from aragora.knowledge.mound.types import (
        KnowledgeItem,
        MoundConfig,
    )

logger = logging.getLogger(__name__)


class FederationMode(str, Enum):
    """Mode of federation between regions."""

    PUSH = "push"  # Push changes to remote
    PULL = "pull"  # Pull changes from remote
    BIDIRECTIONAL = "bidirectional"  # Both push and pull
    NONE = "none"  # Federation disabled


class SyncScope(str, Enum):
    """Scope of data to sync."""

    FULL = "full"  # Full content and metadata
    METADATA = "metadata"  # Only metadata (no content)
    SUMMARY = "summary"  # Summarized content


@dataclass
class FederatedRegion:
    """A federated region configuration."""

    region_id: str
    endpoint_url: str
    api_key: str
    mode: FederationMode = FederationMode.BIDIRECTIONAL
    sync_scope: SyncScope = SyncScope.SUMMARY
    enabled: bool = True
    last_sync_at: datetime | None = None
    last_sync_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncResult:
    """Result of a federation sync operation."""

    region_id: str
    direction: str  # "push" or "pull"
    nodes_synced: int = 0
    nodes_skipped: int = 0
    nodes_failed: int = 0
    duration_ms: float = 0
    success: bool = True
    error: str | None = None


COORDINATOR_MODE_ATTR_BY_REGION_MODE: dict[FederationMode, str] = {
    FederationMode.NONE: "ISOLATED",
    FederationMode.PULL: "READONLY",
    FederationMode.BIDIRECTIONAL: "BIDIRECTIONAL",
    FederationMode.PUSH: "ORCHESTRATED",
}


def _normalize_region_federation_mode(
    raw_mode: object,
    *,
    region_id: str,
) -> FederationMode:
    if isinstance(raw_mode, FederationMode):
        return raw_mode

    candidate = getattr(raw_mode, "value", raw_mode)
    if isinstance(candidate, str):
        try:
            return FederationMode(candidate.strip().lower())
        except ValueError:
            logger.warning(
                "Unknown federation mode %r for region %s; defaulting to none",
                candidate,
                region_id,
            )
            return FederationMode.NONE

    logger.warning(
        "Unsupported federation mode %r for region %s; defaulting to none",
        raw_mode,
        region_id,
    )
    return FederationMode.NONE


class FederationProtocol(Protocol):
    """Protocol defining expected interface for Federation mixin."""

    config: MoundConfig
    workspace_id: str
    _meta_store: Any | None
    _cache: Any | None
    _initialized: bool

    def _ensure_initialized(self) -> None: ...

    async def store(self, request: Any) -> Any: ...

    async def query(
        self,
        query: str,
        sources: Any = ("all",),
        filters: Any = None,
        limit: int = 20,
        workspace_id: str | None = None,
    ) -> Any: ...


class KnowledgeFederationMixin:
    """Mixin providing federation operations for KnowledgeMound.

    Note: This mixin follows the FederationProtocol interface but does NOT
    inherit from it directly, as Protocol inheritance breaks the MRO chain
    in multiple inheritance scenarios (Protocol.__init__ doesn't call super()).

    Type Safety: Use `self._proto` property for type-checked access to protocol
    methods/attributes. This enables IDE support and reduces type:ignore comments.
    """

    # Note: Federation registry is now persisted via FederationRegistryStore
    # The class-level dict is kept for backward compatibility as a cache
    _federated_regions: dict[str, FederatedRegion] = {}

    @property
    def _proto(self) -> FederationProtocol:
        """Cast self to FederationProtocol for type-safe method access.

        This property provides type-checked access to methods defined in the
        Protocol without requiring type:ignore comments on every usage.
        """
        return cast(FederationProtocol, self)

    async def register_federated_region(
        self,
        region_id: str,
        endpoint_url: str,
        api_key: str,
        mode: FederationMode = FederationMode.BIDIRECTIONAL,
        sync_scope: SyncScope = SyncScope.SUMMARY,
    ) -> FederatedRegion:
        """
        Register a federated region for knowledge sync.

        Args:
            region_id: Unique identifier for the region
            endpoint_url: API endpoint URL for the remote region
            api_key: Authentication key for the remote region
            mode: Federation mode (push, pull, bidirectional)
            sync_scope: Scope of data to sync

        Returns:
            The registered FederatedRegion
        """
        self._proto._ensure_initialized()

        region = FederatedRegion(
            region_id=region_id,
            endpoint_url=endpoint_url,
            api_key=api_key,
            mode=mode,
            sync_scope=sync_scope,
        )

        # Persist to storage
        try:
            from aragora.storage.federation_registry_store import (
                FederatedRegionConfig,
                get_federation_registry_store,
            )

            store = get_federation_registry_store()
            config = FederatedRegionConfig(
                region_id=region_id,
                endpoint_url=endpoint_url,
                api_key=api_key,
                mode=mode.value,
                sync_scope=sync_scope.value,
                workspace_id=self._proto.workspace_id,
            )
            await store.save(config)
        except ImportError:
            logger.debug("Federation registry store not available")
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to persist federation registry: %s", e)

        # Also register with CrossWorkspaceCoordinator if available
        await self._register_with_coordinator(region)

        # Cache in class-level dict for backward compatibility
        KnowledgeFederationMixin._federated_regions[region_id] = region

        logger.info("Registered federated region %s at %s", region_id, endpoint_url)
        return region

    async def unregister_federated_region(
        self,
        region_id: str,
    ) -> bool:
        """
        Unregister a federated region.

        Args:
            region_id: ID of the region to unregister

        Returns:
            True if region was unregistered, False if not found
        """
        # Remove from class-level cache first
        was_in_cache = region_id in KnowledgeFederationMixin._federated_regions
        if was_in_cache:
            del KnowledgeFederationMixin._federated_regions[region_id]

        # Also try to remove from persistent store
        try:
            from aragora.storage.federation_registry_store import get_federation_registry_store

            store = get_federation_registry_store()
            result = await store.delete(region_id, self._proto.workspace_id)
            if result or was_in_cache:
                logger.info("Unregistered federated region %s", region_id)
                return True
            return False
        except ImportError:
            logger.debug("Federation registry store not available")
            # Return True if we removed from cache
            if was_in_cache:
                logger.info("Unregistered federated region %s", region_id)
                return True
            return False
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to unregister federated region: %s", e)
            # Return True if we removed from cache
            return was_in_cache

    async def sync_to_region(
        self,
        region_id: str,
        workspace_id: str | None = None,
        since: datetime | None = None,
        visibility_levels: list[str] | None = None,
    ) -> SyncResult:
        """
        Sync knowledge to a federated region.

        Pushes knowledge items that match the visibility criteria to the
        remote region.

        Args:
            region_id: ID of the target region
            workspace_id: Workspace to sync (defaults to current)
            since: Only sync items updated after this time
            visibility_levels: Only sync items with these visibility levels
                              (default: ["public", "organization"])

        Returns:
            SyncResult with sync statistics
        """
        import time

        self._proto._ensure_initialized()

        start_time = time.time()
        ws_id = workspace_id or self._proto.workspace_id

        # Get region from persistent store
        region = await self._get_region_from_store(region_id)
        if not region:
            return SyncResult(
                region_id=region_id,
                direction="push",
                success=False,
                error=f"Region {region_id} not registered",
            )

        if region.mode == FederationMode.PULL:
            return SyncResult(
                region_id=region_id,
                direction="push",
                success=False,
                error=f"Region {region_id} is configured for pull-only",
            )

        try:
            # Get items to sync
            from aragora.knowledge.mound.types import VisibilityLevel

            allowed_visibility = visibility_levels or [
                VisibilityLevel.PUBLIC.value,
                VisibilityLevel.ORGANIZATION.value,
            ]

            # Query items without filters (filter visibility post-query)
            result = await self._proto.query(
                query="",  # Get all matching items
                workspace_id=ws_id,
                limit=1000,
            )

            items = result.items

            # Filter by visibility
            filtered_items = []
            for item in items:
                item_vis = (item.metadata or {}).get("visibility", "workspace")
                if item_vis in allowed_visibility:
                    # Filter by since if specified
                    if since:
                        updated_at = (item.metadata or {}).get("updated_at")
                        if updated_at:
                            try:
                                item_time = datetime.fromisoformat(
                                    updated_at.replace("Z", "+00:00")
                                )
                                if item_time < since:
                                    continue
                            except (ValueError, TypeError) as e:
                                logger.warning("Failed to parse datetime value: %s", e)
                    filtered_items.append(item)

            # Apply scope filtering
            items_to_sync = []
            for item in filtered_items:
                sync_data = self._apply_sync_scope(item, region.sync_scope)
                if sync_data:
                    items_to_sync.append(sync_data)

            # Send to remote region via coordinator
            nodes_synced = await self._push_to_region(region, items_to_sync)

            duration_ms = (time.time() - start_time) * 1000

            # Update sync status in persistent store
            await self._update_region_sync_status(region_id, "push", nodes_synced)

            logger.info(f"Synced {nodes_synced} items to region {region_id} in {duration_ms:.0f}ms")

            return SyncResult(
                region_id=region_id,
                direction="push",
                nodes_synced=nodes_synced,
                nodes_skipped=len(items) - nodes_synced,
                duration_ms=duration_ms,
                success=True,
            )

        except (OSError, ConnectionError, RuntimeError, TimeoutError, ValueError) as e:
            # Update sync status with error
            logger.warning("Failed to sync to region %s: %s", region_id, e)
            await self._update_region_sync_status(region_id, "push", 0, "Push sync failed")
            return SyncResult(
                region_id=region_id,
                direction="push",
                success=False,
                error="Push sync failed",
            )

    async def pull_from_region(
        self,
        region_id: str,
        workspace_id: str | None = None,
        since: datetime | None = None,
    ) -> SyncResult:
        """
        Pull knowledge from a federated region.

        Fetches knowledge items from the remote region and ingests them
        into the local knowledge mound.

        Args:
            region_id: ID of the source region
            workspace_id: Workspace to sync into (defaults to current)
            since: Only pull items updated after this time

        Returns:
            SyncResult with sync statistics
        """
        import time

        self._proto._ensure_initialized()

        start_time = time.time()
        ws_id = workspace_id or self._proto.workspace_id

        # Get region from persistent store
        region = await self._get_region_from_store(region_id)
        if not region:
            return SyncResult(
                region_id=region_id,
                direction="pull",
                success=False,
                error=f"Region {region_id} not registered",
            )

        if region.mode == FederationMode.PUSH:
            return SyncResult(
                region_id=region_id,
                direction="pull",
                success=False,
                error=f"Region {region_id} is configured for push-only",
            )

        try:
            # Fetch from remote region via coordinator
            remote_items = await self._fetch_from_region(region, since)

            # Ingest items
            nodes_synced = 0
            nodes_failed = 0

            for item_data in remote_items:
                try:
                    from aragora.knowledge.mound.types import IngestionRequest, KnowledgeSource

                    request = IngestionRequest(
                        content=item_data.get("content", ""),
                        workspace_id=ws_id,
                        source_type=KnowledgeSource.FACT,
                        confidence=item_data.get("confidence", 0.5),
                        metadata={
                            "source_region": region_id,
                            "federation_sync": True,
                            "original_id": item_data.get("id"),
                            **item_data.get("metadata", {}),
                        },
                    )
                    await self._proto.store(request)
                    nodes_synced += 1
                except (RuntimeError, ValueError, KeyError, AttributeError) as e:  # noqa: BLE001 - adapter isolation
                    logger.warning("Failed to ingest item from %s: %s", region_id, e)
                    nodes_failed += 1

            duration_ms = (time.time() - start_time) * 1000

            # Update sync status in persistent store
            await self._update_region_sync_status(region_id, "pull", nodes_synced)

            logger.info(
                f"Pulled {nodes_synced} items from region {region_id} in {duration_ms:.0f}ms"
            )

            return SyncResult(
                region_id=region_id,
                direction="pull",
                nodes_synced=nodes_synced,
                nodes_failed=nodes_failed,
                duration_ms=duration_ms,
                success=True,
            )

        except (OSError, ConnectionError, RuntimeError, TimeoutError, ValueError) as e:
            # Update sync status with error
            logger.warning("Failed to pull from region %s: %s", region_id, e)
            await self._update_region_sync_status(region_id, "pull", 0, "Pull sync failed")
            return SyncResult(
                region_id=region_id,
                direction="pull",
                success=False,
                error="Pull sync failed",
            )

    async def sync_all_regions(
        self,
        workspace_id: str | None = None,
        since: datetime | None = None,
    ) -> list[SyncResult]:
        """
        Sync with all registered federated regions.

        Args:
            workspace_id: Workspace to sync (defaults to current)
            since: Only sync items updated after this time

        Returns:
            List of SyncResult for each region
        """
        results = []

        # Get all enabled regions from persistent store
        regions = await self._list_enabled_regions()

        for region in regions:
            if region.mode in (FederationMode.PUSH, FederationMode.BIDIRECTIONAL):
                result = await self.sync_to_region(region.region_id, workspace_id, since)
                results.append(result)

            if region.mode in (FederationMode.PULL, FederationMode.BIDIRECTIONAL):
                result = await self.pull_from_region(region.region_id, workspace_id, since)
                results.append(result)

        return results

    async def get_federation_status(
        self,
    ) -> dict[str, dict[str, Any]]:
        """
        Get sync status for all registered regions.

        Returns:
            Dict mapping region_id to status info
        """
        status = {}

        # Get all regions from persistent store
        regions = await self._list_all_regions()

        for region in regions:
            status[region.region_id] = {
                "endpoint_url": region.endpoint_url,
                "mode": region.mode.value if hasattr(region.mode, "value") else region.mode,
                "sync_scope": (
                    region.sync_scope.value
                    if hasattr(region.sync_scope, "value")
                    else region.sync_scope
                ),
                "enabled": region.enabled,
                "last_sync_at": region.last_sync_at,
                "last_sync_error": region.last_sync_error,
            }

        return status

    async def _get_region_from_store(
        self,
        region_id: str,
    ) -> FederatedRegion | None:
        """Get a federated region from persistent storage or cache."""
        try:
            from aragora.storage.federation_registry_store import get_federation_registry_store

            store = get_federation_registry_store()
            config = await store.get(region_id, self._proto.workspace_id)
            if config:
                return FederatedRegion(
                    region_id=config.region_id,
                    endpoint_url=config.endpoint_url,
                    api_key=config.api_key,
                    mode=FederationMode(config.mode),
                    sync_scope=SyncScope(config.sync_scope),
                    enabled=config.enabled,
                    last_sync_at=(
                        datetime.fromisoformat(config.last_sync_at) if config.last_sync_at else None
                    ),
                    last_sync_error=config.last_sync_error,
                )
            # Fall through to cache check
        except ImportError:
            logger.debug("Federation registry store not available")
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to get region from store: %s", e)

        # Fall back to class-level cache
        return KnowledgeFederationMixin._federated_regions.get(region_id)

    async def _list_enabled_regions(
        self,
    ) -> list[FederatedRegion]:
        """List all enabled federated regions from persistent storage or cache."""
        try:
            from aragora.storage.federation_registry_store import get_federation_registry_store

            store = get_federation_registry_store()
            configs = await store.list_enabled(self._proto.workspace_id)
            return [
                FederatedRegion(
                    region_id=config.region_id,
                    endpoint_url=config.endpoint_url,
                    api_key=config.api_key,
                    mode=FederationMode(config.mode),
                    sync_scope=SyncScope(config.sync_scope),
                    enabled=config.enabled,
                    last_sync_at=(
                        datetime.fromisoformat(config.last_sync_at) if config.last_sync_at else None
                    ),
                    last_sync_error=config.last_sync_error,
                )
                for config in configs
            ]
        except ImportError:
            logger.debug("Federation registry store not available")
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to list enabled regions: %s", e)

        # Fall back to class-level cache - return only enabled regions
        return [
            region
            for region in KnowledgeFederationMixin._federated_regions.values()
            if region.enabled
        ]

    async def _list_all_regions(
        self,
    ) -> list[FederatedRegion]:
        """List all federated regions from persistent storage or cache."""
        try:
            from aragora.storage.federation_registry_store import get_federation_registry_store

            store = get_federation_registry_store()
            configs = await store.list_all(self._proto.workspace_id)
            return [
                FederatedRegion(
                    region_id=config.region_id,
                    endpoint_url=config.endpoint_url,
                    api_key=config.api_key,
                    mode=FederationMode(config.mode),
                    sync_scope=SyncScope(config.sync_scope),
                    enabled=config.enabled,
                    last_sync_at=(
                        datetime.fromisoformat(config.last_sync_at) if config.last_sync_at else None
                    ),
                    last_sync_error=config.last_sync_error,
                )
                for config in configs
            ]
        except ImportError:
            logger.debug("Federation registry store not available")
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to list all regions: %s", e)

        # Fall back to class-level cache
        return list(KnowledgeFederationMixin._federated_regions.values())

    async def _update_region_sync_status(
        self,
        region_id: str,
        direction: str,
        nodes_synced: int = 0,
        error: str | None = None,
    ) -> None:
        """Update sync status for a region in persistent storage and cache."""
        # Update class-level cache first
        if region_id in KnowledgeFederationMixin._federated_regions:
            region = KnowledgeFederationMixin._federated_regions[region_id]
            region.last_sync_at = datetime.now()
            region.last_sync_error = error

        # Also try to update persistent storage
        try:
            from aragora.storage.federation_registry_store import get_federation_registry_store

            store = get_federation_registry_store()
            await store.update_sync_status(
                region_id=region_id,
                direction=direction,
                nodes_synced=nodes_synced,
                error=error,
                workspace_id=self._proto.workspace_id,
            )
        except ImportError:
            logger.debug("Federation registry store not available")
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to update region sync status: %s", e)

    def _apply_sync_scope(
        self,
        item: KnowledgeItem,
        scope: SyncScope,
    ) -> dict[str, Any] | None:
        """Apply sync scope filtering to an item."""
        if scope == SyncScope.FULL:
            return {
                "id": item.id,
                "content": item.content,
                "confidence": getattr(item, "importance", 0.5),
                "metadata": item.metadata or {},
            }
        elif scope == SyncScope.SUMMARY:
            # Truncate content
            content = item.content[:500] if item.content else ""
            return {
                "id": item.id,
                "content": content,
                "confidence": getattr(item, "importance", 0.5),
                "metadata": {
                    k: v
                    for k, v in (item.metadata or {}).items()
                    if k in ("topics", "node_type", "visibility")
                },
            }
        elif scope == SyncScope.METADATA:
            return {
                "id": item.id,
                "content_hash": (item.metadata or {}).get("content_hash", item.content[:50]),
                "metadata": item.metadata or {},
            }
        return None

    async def _register_with_coordinator(
        self,
        region: FederatedRegion,
    ) -> None:
        """Register region with CrossWorkspaceCoordinator."""
        try:
            from aragora.tenancy.cross_workspace import (
                CrossWorkspaceCoordinator,
                FederatedWorkspace,
                FederationMode as CoordinatorFederationMode,
            )

            normalized_mode = _normalize_region_federation_mode(
                region.mode,
                region_id=region.region_id,
            )
            coordinator_mode = getattr(
                CoordinatorFederationMode,
                COORDINATOR_MODE_ATTR_BY_REGION_MODE[normalized_mode],
            )

            workspace = FederatedWorkspace(
                id=f"region:{region.region_id}",
                name=f"Region: {region.region_id}",
                federation_mode=coordinator_mode,
                endpoint_url=region.endpoint_url,
                public_key=region.api_key,
            )

            coordinator = CrossWorkspaceCoordinator()
            if hasattr(coordinator, "register_workspace"):
                coordinator.register_workspace(workspace)
        except ImportError:
            logger.debug("CrossWorkspaceCoordinator not available")
        except (OSError, RuntimeError, ValueError, AttributeError) as e:
            logger.warning("Failed to register with coordinator: %s", e)

    async def _push_to_region(
        self,
        region: FederatedRegion,
        items: list[dict[str, Any]],
    ) -> int:
        """Push items to remote region via coordinator."""
        try:
            from aragora.tenancy.cross_workspace import (
                CrossWorkspaceCoordinator,
                CrossWorkspaceOperation,
            )

            coordinator = CrossWorkspaceCoordinator()
            # Optional cross-workspace integration
            if hasattr(coordinator, "execute_operation"):
                result = await coordinator.execute_operation(
                    operation=CrossWorkspaceOperation.SYNC_CULTURE,
                    from_workspace_id=self._proto.workspace_id,
                    to_workspace_id=f"region:{region.region_id}",
                    payload={"items": items},
                )
                return result.get("synced_count", len(items))
            return len(items)
        except ImportError:
            # Fallback: just return count
            logger.debug("CrossWorkspaceCoordinator not available, simulating sync")
            return len(items)
        except (OSError, ConnectionError, RuntimeError, TimeoutError, ValueError) as e:
            logger.warning("Push to region failed: %s", e)
            raise

    async def _fetch_from_region(
        self,
        region: FederatedRegion,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch items from remote region via coordinator."""
        try:
            from aragora.tenancy.cross_workspace import (
                CrossWorkspaceCoordinator,
                CrossWorkspaceOperation,
            )

            coordinator = CrossWorkspaceCoordinator()
            # Optional cross-workspace integration
            if hasattr(coordinator, "execute_operation"):
                result = await coordinator.execute_operation(
                    operation=CrossWorkspaceOperation.QUERY_MOUND,
                    from_workspace_id=self._proto.workspace_id,
                    to_workspace_id=f"region:{region.region_id}",
                    payload={"since": since.isoformat() if since else None},
                )
                return result.get("items", [])
            return []
        except ImportError:
            # Fallback: return empty list
            logger.debug("CrossWorkspaceCoordinator not available")
            return []
        except (OSError, ConnectionError, RuntimeError, TimeoutError, ValueError) as e:
            logger.warning("Fetch from region failed: %s", e)
            raise
