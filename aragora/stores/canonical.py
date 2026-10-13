"""
Canonical store access helpers.

This module centralizes access to the canonical persistence layers for:
- Convoys/Beads/Workspaces (Nomic stores)
- Gateway/Inbox (Gateway store + Unified Inbox store)

Use these helpers instead of constructing ad-hoc store instances.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from aragora.stores.gateway_store_hook import get_gateway_store_factory

if TYPE_CHECKING:
    from aragora.gateway.persistence import GatewayStore
    from aragora.memory.store import CritiqueStore
    from aragora.nomic.beads import BeadStore
    from aragora.nomic.convoys import ConvoyManager
    from aragora.storage.unified_inbox_store import UnifiedInboxStoreBackend


@runtime_checkable
class WorkspaceStores(Protocol):
    async def bead_store(self) -> BeadStore: ...
    async def convoy_manager(self) -> ConvoyManager: ...


@runtime_checkable
class GatewayStores(Protocol):
    def gateway_store(self) -> GatewayStore: ...
    def inbox_store(self) -> UnifiedInboxStoreBackend: ...


@dataclass
class CanonicalWorkspaceStores(WorkspaceStores):
    """Canonical stores for convoys/beads/workspaces."""

    bead_dir: str | None = None
    convoy_dir: str | None = None
    git_enabled: bool = True
    auto_commit: bool = False
    _bead_store: BeadStore | None = None
    _convoy_manager: ConvoyManager | None = None

    async def bead_store(self) -> BeadStore:
        if self._bead_store is None:
            from aragora.nomic.beads import create_bead_store

            self._bead_store = await create_bead_store(
                bead_dir=self.bead_dir,
                git_enabled=self.git_enabled,
                auto_commit=self.auto_commit,
            )
        return self._bead_store

    async def convoy_manager(self) -> ConvoyManager:
        if self._convoy_manager is None:
            bead_store = await self.bead_store()
            if self.convoy_dir:
                from aragora.nomic.convoys import ConvoyManager

                self._convoy_manager = ConvoyManager(
                    bead_store=bead_store,
                    convoy_dir=Path(self.convoy_dir),
                )
                await self._convoy_manager.initialize()
            else:
                from aragora.nomic.convoys import get_convoy_manager

                self._convoy_manager = await get_convoy_manager(bead_store)
        return self._convoy_manager


@dataclass
class CanonicalGatewayStores(GatewayStores):
    """Canonical stores for gateway/inbox persistence."""

    allow_disabled: bool = False
    _gateway_store: GatewayStore | None = None
    _inbox_store: UnifiedInboxStoreBackend | None = None

    def gateway_store(self) -> GatewayStore:
        if self._gateway_store is None:
            self._gateway_store = get_gateway_store_factory()(
                backend_env="ARAGORA_GATEWAY_STORE",
                fallback_backend_env="ARAGORA_GATEWAY_SESSION_STORE",
                path_env="ARAGORA_GATEWAY_STORE_PATH",
                fallback_path_env="ARAGORA_GATEWAY_SESSION_PATH",
                redis_env="ARAGORA_GATEWAY_STORE_REDIS_URL",
                fallback_redis_env="ARAGORA_GATEWAY_SESSION_REDIS_URL",
                default_backend="auto",
                allow_disabled=self.allow_disabled,
                emit_warning=False,
            )
        return self._gateway_store

    def inbox_store(self) -> UnifiedInboxStoreBackend:
        if self._inbox_store is None:
            from aragora.storage.unified_inbox_store import get_unified_inbox_store

            self._inbox_store = get_unified_inbox_store()
        return self._inbox_store


def get_canonical_workspace_stores(
    *,
    bead_dir: str | None = None,
    convoy_dir: str | None = None,
    git_enabled: bool = True,
    auto_commit: bool = False,
    bead_store: BeadStore | None = None,
) -> CanonicalWorkspaceStores:
    """Return a canonical workspace stores accessor."""
    stores = CanonicalWorkspaceStores(
        bead_dir=bead_dir,
        convoy_dir=convoy_dir,
        git_enabled=git_enabled,
        auto_commit=auto_commit,
    )
    if bead_store is not None:
        stores._bead_store = bead_store
    return stores


def get_canonical_gateway_stores(*, allow_disabled: bool = False) -> CanonicalGatewayStores:
    """Return a canonical gateway stores accessor."""
    return CanonicalGatewayStores(allow_disabled=allow_disabled)


def get_critique_store(nomic_dir: Path | str | None = None) -> CritiqueStore | None:
    """
    Get a CritiqueStore instance using the canonical path resolution.

    This helper centralizes CritiqueStore instantiation with proper path handling:
    - Uses DatabaseType.AGORA_MEMORY for path resolution
    - Handles missing nomic_dir gracefully
    - Returns None if the database doesn't exist or CritiqueStore is unavailable

    Args:
        nomic_dir: Base directory for databases. If None, uses get_nomic_dir().

    Returns:
        CritiqueStore instance or None if unavailable.
    """
    try:
        from aragora.memory.store import CritiqueStore
    except ImportError:
        return None

    try:
        from aragora.persistence.db_config import DatabaseType, get_db_path, get_nomic_dir
    except ImportError:
        # Fallback if db_config not available
        if nomic_dir is None:
            return None
        db_path = Path(nomic_dir) / "agora_memory.db"
        if not db_path.exists():
            return None
        return CritiqueStore(str(db_path))

    if nomic_dir is None:
        nomic_dir = get_nomic_dir()
    elif isinstance(nomic_dir, str):
        nomic_dir = Path(nomic_dir)

    db_path = get_db_path(DatabaseType.AGORA_MEMORY, nomic_dir)
    if not db_path.exists():
        return None

    return CritiqueStore(str(db_path))


def is_critique_store_available() -> bool:
    """Check if CritiqueStore is available for import."""
    try:
        from aragora.memory.store import CritiqueStore  # noqa: F401

        return True
    except ImportError:
        return False


__all__ = [
    "CanonicalGatewayStores",
    "CanonicalWorkspaceStores",
    "GatewayStores",
    "WorkspaceStores",
    "get_canonical_gateway_stores",
    "get_canonical_workspace_stores",
    "get_critique_store",
    "is_critique_store_available",
]
