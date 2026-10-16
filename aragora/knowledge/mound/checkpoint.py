"""
Knowledge Mound Checkpoint Store.

Provides state persistence and recovery for the Knowledge Mound:
- Snapshot current KM state (nodes, relationships, metadata)
- Restore KM from checkpoint
- Incremental checkpoints
- Checkpoint management (list, delete, compare)

Usage:
    from aragora.knowledge.mound.checkpoint import KMCheckpointStore

    # Initialize
    store = KMCheckpointStore(mound, checkpoint_dir="/path/to/checkpoints")

    # Create checkpoint
    checkpoint_id = await store.create_checkpoint(
        description="Before migration",
        include_vectors=True,
    )

    # Restore from checkpoint
    await store.restore_checkpoint(checkpoint_id)

    # List checkpoints
    checkpoints = await store.list_checkpoints()
"""

from __future__ import annotations

import contextlib
import errno
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from aragora.knowledge.mound import KnowledgeMound

logger = logging.getLogger(__name__)

# No ".", "/", "\\", "%" or NUL, so traversal and percent-encoded separators
# are rejected without decoding.
_CHECKPOINT_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")

CAPACITY_LOCK_FILE = ".capacity.lock"
_NO_SPACE_ERRNOS = frozenset({errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)})
_unlocked_warning_logged = False


@contextlib.contextmanager
def _directory_lock(directory: Path) -> Iterator[None]:
    """Hold an exclusive flock on ``directory/.capacity.lock`` for every process using it.

    Same lock-file flock pattern as ``aragora.swarm.campaign.locked_manifest_path``.
    flock is not reliable on NFS shared across hosts. Without fcntl only the caller's
    in-process lock applies.
    """
    global _unlocked_warning_logged
    with open(directory / CAPACITY_LOCK_FILE, "a+", encoding="utf-8") as handle:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX
            if not _unlocked_warning_logged:
                _unlocked_warning_logged = True
                logger.warning("fcntl unavailable: the KM checkpoint ceiling holds per process")
            yield
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class InvalidCheckpointNameError(ValueError):
    """A checkpoint name is not a single safe segment inside the checkpoint directory."""


class CheckpointCapacityError(RuntimeError):
    """A create would leave more checkpoints stored than the store's global ceiling."""


class CheckpointWriteError(OSError):
    """A checkpoint could not be written for a reason other than lack of space."""


def validate_checkpoint_name(name: object) -> str:
    """Return ``name`` unchanged if it is a safe checkpoint name, else raise."""
    if not isinstance(name, str) or not _CHECKPOINT_NAME_RE.fullmatch(name):
        raise InvalidCheckpointNameError(
            "Invalid checkpoint name: use 1-128 characters from A-Z, a-z, 0-9, '_' and '-'"
        )
    return name


class _StalenessDetectorProtocol(Protocol):
    """Protocol for staleness detector export/import methods."""

    def export_state(self) -> dict[str, Any]: ...
    def import_state(self, state: dict[str, Any]) -> None: ...


@dataclass
class KMCheckpointMetadata:
    """Metadata for a Knowledge Mound checkpoint."""

    id: str
    created_at: str
    description: str
    workspace_id: str
    name: str = ""  # Human-readable checkpoint name (defaults to id if not set)
    mound_version: str = "1.0"

    # Statistics
    node_count: int = 0
    relationship_count: int = 0
    workspace_count: int = 0

    # Size info
    compressed: bool = True
    size_bytes: int = 0
    checksum: str = ""

    # Optional inclusions
    includes_vectors: bool = False
    includes_culture: bool = True
    includes_staleness: bool = True

    # Incremental checkpoint info
    incremental: bool = False
    parent_checkpoint_id: str | None = None

    # Tags for categorization/filtering
    tags: list[str] = field(default_factory=list)

    # Authenticated organization of the creator; None when none was recorded.
    org_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KMCheckpointContent:
    """Content of a Knowledge Mound checkpoint."""

    # Nodes as list of dicts
    nodes: list[dict[str, Any]] = field(default_factory=list)

    # Relationships as list of dicts
    relationships: list[dict[str, Any]] = field(default_factory=list)

    # Culture patterns
    culture_patterns: dict[str, Any] = field(default_factory=dict)

    # Staleness tracking state
    staleness_state: dict[str, Any] = field(default_factory=dict)

    # Vector embeddings (optional, large)
    vector_embeddings: dict[str, list[float]] = field(default_factory=dict)

    # Workspace metadata
    workspace_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "relationships": self.relationships,
            "culture_patterns": self.culture_patterns,
            "staleness_state": self.staleness_state,
            "vector_embeddings": self.vector_embeddings,
            "workspace_metadata": self.workspace_metadata,
        }


@dataclass
class RestoreResult:
    """Result of restoring from checkpoint."""

    success: bool
    checkpoint_id: str
    nodes_restored: int = 0
    relationships_restored: int = 0
    culture_restored: bool = False
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)


class KMCheckpointStore:
    """
    Checkpoint store for Knowledge Mound state persistence.

    Provides full and incremental checkpointing of KM state,
    enabling disaster recovery and migration.
    """

    VERSION = "1.0"

    def __init__(
        self,
        mound: KnowledgeMound,
        checkpoint_dir: str | None = None,
        compress: bool = True,
        max_checkpoints: int = 10,
        max_total_checkpoints: int = 100,
    ):
        """
        Initialize checkpoint store.

        Args:
            mound: KnowledgeMound instance to checkpoint
            checkpoint_dir: Directory for checkpoint storage
            compress: Whether to gzip compress checkpoints
            max_checkpoints: Maximum checkpoints kept per recorded org_id (oldest are pruned)
            max_total_checkpoints: Maximum checkpoint directories stored across all
                organizations, including legacy ones without an org_id and ones with
                unreadable metadata. Every process sharing ``checkpoint_dir`` enforces it
                under one directory lock. A create that would exceed it after its own
                organization's pruning is refused and writes nothing; other organizations'
                checkpoints are never pruned to make room.
        """
        self.mound = mound
        self.compress = compress
        self.max_checkpoints = max_checkpoints
        self.max_total_checkpoints = max_total_checkpoints
        self._write_lock = threading.Lock()

        # Set checkpoint directory
        if checkpoint_dir:
            self.checkpoint_dir = Path(checkpoint_dir)
        else:
            # Default to ARAGORA_DATA_DIR/km_checkpoints
            from aragora.persistence.db_config import get_nomic_dir

            self.checkpoint_dir = get_nomic_dir() / "km_checkpoints"

        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    async def create_checkpoint(
        self,
        name: str | None = None,
        description: str = "",
        tags: list[str] | None = None,
        include_vectors: bool = False,
        include_culture: bool = True,
        include_staleness: bool = True,
        incremental: bool = False,
        parent_checkpoint_id: str | None = None,
        return_metadata: bool = False,
        org_id: str | None = None,
    ) -> str | KMCheckpointMetadata:
        """
        Create a checkpoint of current KM state.

        Args:
            name: Human-readable checkpoint name (defaults to ID if not provided)
            description: Human-readable description
            tags: List of tags for categorization/filtering
            include_vectors: Include vector embeddings (large)
            include_culture: Include culture patterns
            include_staleness: Include staleness tracking state
            incremental: Create incremental checkpoint (only changes)
            parent_checkpoint_id: Parent checkpoint for incremental
            return_metadata: If True, return KMCheckpointMetadata; otherwise return ID string
            org_id: Authenticated organization of the creator, recorded in the metadata.
                Pruning only removes older checkpoints with the same recorded org_id.

        Returns:
            Checkpoint ID (str) or KMCheckpointMetadata if return_metadata=True

        Raises:
            CheckpointCapacityError: The create would exceed ``max_total_checkpoints``,
                even after deleting this organization's oldest checkpoints, or the disk
                is full; nothing is written.
            CheckpointWriteError: The checkpoint could not be written; nothing is left.
            FileExistsError: The generated id is already stored; that entry is untouched.
        """
        if name is not None:
            validate_checkpoint_name(name)
        start_time = time.time()

        # Generate checkpoint ID (not for security, just uniqueness)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_id = f"km_ckpt_{timestamp}_{hashlib.md5(str(time.time()).encode(), usedforsecurity=False).hexdigest()[:8]}"

        logger.info("Creating KM checkpoint: %s", checkpoint_id)

        # Collect content
        content = KMCheckpointContent()

        # Export nodes
        nodes = await self._export_nodes(incremental, parent_checkpoint_id)
        content.nodes = nodes

        # Export relationships
        relationships = await self._export_relationships(incremental, parent_checkpoint_id)
        content.relationships = relationships

        # Export culture patterns
        if include_culture:
            content.culture_patterns = await self._export_culture()

        # Export staleness state
        if include_staleness:
            content.staleness_state = await self._export_staleness()

        # Export vector embeddings (optional - can be large)
        if include_vectors:
            content.vector_embeddings = await self._export_vectors()

        # Export workspace metadata
        content.workspace_metadata = {
            "workspace_id": self.mound.workspace_id,
            "config": {
                "backend": (
                    self.mound.config.backend.value
                    if hasattr(self.mound.config.backend, "value")
                    else str(self.mound.config.backend)
                ),
                "enable_staleness_detection": self.mound.config.enable_staleness_detection,
                "enable_culture_accumulator": self.mound.config.enable_culture_accumulator,
            },
        }

        # Serialize and optionally compress
        content_json = json.dumps(content.to_dict(), default=str)

        if self.compress:
            content_bytes = gzip.compress(content_json.encode("utf-8"))
            extension = ".json.gz"
        else:
            content_bytes = content_json.encode("utf-8")
            extension = ".json"

        # Calculate checksum
        checksum = hashlib.sha256(content_bytes).hexdigest()

        # Create metadata
        metadata = KMCheckpointMetadata(
            id=checkpoint_id,
            name=name or checkpoint_id,  # Use ID as name if not provided
            created_at=datetime.now().isoformat(),
            description=description,
            workspace_id=self.mound.workspace_id,
            mound_version=self.VERSION,
            node_count=len(content.nodes),
            relationship_count=len(content.relationships),
            workspace_count=1,
            compressed=self.compress,
            size_bytes=len(content_bytes),
            checksum=checksum,
            includes_vectors=include_vectors,
            includes_culture=include_culture,
            includes_staleness=include_staleness,
            incremental=incremental,
            parent_checkpoint_id=parent_checkpoint_id,
            tags=tags or [],
            org_id=org_id,
        )

        metadata_json = json.dumps(metadata.to_dict(), indent=2)

        # Both locks span the capacity check and the write, so no two creates in this
        # or any other process sharing the directory pass against the same count.
        # Nothing inside them awaits.
        with self._write_lock, _directory_lock(self.checkpoint_dir):
            self._check_capacity(org_id)
            try:
                self._write_entry(
                    checkpoint_id, f"content{extension}", content_bytes, metadata_json
                )
            except FileExistsError:
                raise
            except OSError as e:
                logger.error("Failed to write KM checkpoint %s: %s", checkpoint_id, e)
                if e.errno in _NO_SPACE_ERRNOS:
                    raise CheckpointCapacityError("Checkpoint storage is full") from e
                raise CheckpointWriteError("Checkpoint could not be written") from e

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "Created KM checkpoint %s: %s nodes, %s relationships, %s bytes, %sms",
            checkpoint_id,
            len(content.nodes),
            len(content.relationships),
            len(content_bytes),
            duration_ms,
        )

        return metadata if return_metadata else checkpoint_id

    async def restore_checkpoint(
        self,
        checkpoint_id: str,
        clear_existing: bool = True,
        restore_vectors: bool = True,
    ) -> RestoreResult:
        """
        Restore KM state from checkpoint.

        Args:
            checkpoint_id: Checkpoint ID to restore
            clear_existing: Clear existing KM data before restore
            restore_vectors: Restore vector embeddings if present

        Returns:
            RestoreResult with statistics
        """
        start_time = time.time()
        errors: list[str] = []

        logger.info("Restoring KM from checkpoint: %s", checkpoint_id)

        # Load checkpoint
        checkpoint_path = self._checkpoint_path(checkpoint_id)
        if not checkpoint_path.exists():
            return RestoreResult(
                success=False,
                checkpoint_id=checkpoint_id,
                errors=[f"Checkpoint not found: {checkpoint_id}"],
            )

        # Load metadata
        metadata_file = self._contained_metadata_file(checkpoint_path)
        if metadata_file is None:
            return RestoreResult(
                success=False,
                checkpoint_id=checkpoint_id,
                errors=["Checkpoint metadata not found"],
            )

        metadata_dict = json.loads(metadata_file.read_text())
        metadata = KMCheckpointMetadata(**metadata_dict)

        # Load content
        content_name = "content.json.gz" if metadata.compressed else "content.json"
        content_file = self._contained_file(checkpoint_path, content_name)
        if content_file is None:
            return RestoreResult(
                success=False,
                checkpoint_id=checkpoint_id,
                errors=["Checkpoint content not found"],
            )

        # Verify checksum first (before decompression)
        content_bytes = content_file.read_bytes()
        actual_checksum = hashlib.sha256(content_bytes).hexdigest()
        if actual_checksum != metadata.checksum:
            errors.append(f"Checksum mismatch: expected {metadata.checksum}, got {actual_checksum}")

        # Decompress and parse content
        try:
            if metadata.compressed:
                content_json = gzip.decompress(content_bytes).decode("utf-8")
            else:
                content_json = content_bytes.decode("utf-8")
            content_dict = json.loads(content_json)
        except (gzip.BadGzipFile, OSError) as e:
            return RestoreResult(
                success=False,
                checkpoint_id=checkpoint_id,
                errors=errors + [f"Failed to decompress checkpoint: {e}"],
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return RestoreResult(
                success=False,
                checkpoint_id=checkpoint_id,
                errors=errors + [f"Failed to parse checkpoint content: {e}"],
            )

        # Clear existing data if requested
        if clear_existing:
            await self._clear_mound_data()

        # Restore nodes
        nodes_restored = 0
        for node_dict in content_dict.get("nodes", []):
            try:
                await self._restore_node(node_dict)
                nodes_restored += 1
            except (KeyError, TypeError, ValueError) as e:
                errors.append(f"Failed to restore node {node_dict.get('id')} (data error): {e}")
            except (OSError, ConnectionError, RuntimeError) as e:
                errors.append(f"Failed to restore node {node_dict.get('id')} (storage error): {e}")

        # Restore relationships
        relationships_restored = 0
        for rel_dict in content_dict.get("relationships", []):
            try:
                await self._restore_relationship(rel_dict)
                relationships_restored += 1
            except (KeyError, TypeError, ValueError) as e:
                errors.append(f"Failed to restore relationship (data error): {e}")
            except (OSError, ConnectionError, RuntimeError) as e:
                errors.append(f"Failed to restore relationship (storage error): {e}")

        # Restore culture patterns
        culture_restored = False
        if metadata.includes_culture and content_dict.get("culture_patterns"):
            try:
                await self._restore_culture(content_dict["culture_patterns"])
                culture_restored = True
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                errors.append(f"Failed to restore culture patterns: {e}")
                logger.warning("Culture pattern restore failed: %s", e)

        # Restore staleness state
        if metadata.includes_staleness and content_dict.get("staleness_state"):
            try:
                await self._restore_staleness(content_dict["staleness_state"])
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                errors.append(f"Failed to restore staleness state: {e}")
                logger.warning("Staleness state restore failed: %s", e)

        # Restore vectors if requested and present
        if restore_vectors and metadata.includes_vectors and content_dict.get("vector_embeddings"):
            try:
                await self._restore_vectors(content_dict["vector_embeddings"])
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                errors.append(f"Failed to restore vectors: {e}")
                logger.warning("Vector restore failed: %s", e)

        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "Restored KM checkpoint %s: %s nodes, %s relationships, %s errors, %sms",
            checkpoint_id,
            nodes_restored,
            relationships_restored,
            len(errors),
            duration_ms,
        )

        return RestoreResult(
            success=len(errors) == 0 or nodes_restored > 0,
            checkpoint_id=checkpoint_id,
            nodes_restored=nodes_restored,
            relationships_restored=relationships_restored,
            culture_restored=culture_restored,
            duration_ms=duration_ms,
            errors=errors,
        )

    async def list_checkpoints(self) -> list[KMCheckpointMetadata]:
        """List all available checkpoints."""
        return self._stored_checkpoints()

    def _check_capacity(self, org_id: str | None) -> None:
        """Make room for one more checkpoint of ``org_id`` or raise ``CheckpointCapacityError``.

        Callers hold both locks. Only ``org_id``'s oldest checkpoints beyond
        ``max_checkpoints - 1`` are deleted, and none when deleting them all would still
        leave no room. The count is then re-read from disk, so a failed deletion still
        counts and the create is refused.
        """
        keep = max(self.max_checkpoints - 1, 0)
        excess = len([cp for cp in self._stored_checkpoints() if cp.org_id == org_id][keep:])
        if self._entry_count() - excess < self.max_total_checkpoints:
            self._delete_oldest(org_id, keep)
            if self._entry_count() < self.max_total_checkpoints:
                return
        logger.warning(
            "Refusing KM checkpoint create: ceiling %s reached", self.max_total_checkpoints
        )
        raise CheckpointCapacityError("Checkpoint storage is full")

    def _delete_oldest(self, org_id: str | None, keep: int) -> int:
        """Delete ``org_id``'s checkpoints beyond the newest ``keep``; return how many went."""
        deleted = 0
        for cp in [cp for cp in self._stored_checkpoints() if cp.org_id == org_id][keep:]:
            try:
                deleted += self._remove_entry(self._checkpoint_path(cp.id))
            except InvalidCheckpointNameError:
                logger.warning("Skipping checkpoint with unsafe id in metadata: %r", cp.id)
        return deleted

    def _entry_count(self) -> int:
        """Count checkpoint directories, including ones whose metadata is missing or unreadable."""
        return sum(
            1
            for item in self.checkpoint_dir.iterdir()
            if item.name.startswith("km_ckpt_") and not item.is_symlink() and item.is_dir()
        )

    def _write_entry(
        self, checkpoint_id: str, content_name: str, content: bytes, metadata_json: str
    ) -> None:
        """Write the content, then publish ``metadata.json`` atomically.

        A new directory is required, so an id collision raises FileExistsError and leaves
        the existing entry alone. On any other failure the new directory is removed.
        """
        path = self.checkpoint_dir / checkpoint_id
        path.mkdir()
        committed = False
        try:
            (path / content_name).write_bytes(content)
            staged = path / "metadata.json.tmp"
            staged.write_text(metadata_json)
            os.replace(staged, path / "metadata.json")
            committed = True
        finally:
            if not committed:
                shutil.rmtree(path, ignore_errors=True)

    def _stored_checkpoints(self) -> list[KMCheckpointMetadata]:
        checkpoints = []

        for item in self.checkpoint_dir.iterdir():
            if item.is_symlink() or item.resolve().parent != self.checkpoint_dir.resolve():
                continue
            if item.is_dir() and item.name.startswith("km_ckpt_"):
                metadata_file = self._contained_metadata_file(item)
                if metadata_file is not None:
                    try:
                        metadata_dict = json.loads(metadata_file.read_text())
                        checkpoints.append(KMCheckpointMetadata(**metadata_dict))
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning("Failed to read checkpoint metadata %s: %s", item.name, e)

        # Sort by creation time (newest first)
        checkpoints.sort(key=lambda x: x.created_at, reverse=True)

        return checkpoints

    def _checkpoint_path(self, checkpoint_id: str) -> Path:
        """Map a checkpoint name to its directory, refusing anything outside ``checkpoint_dir``."""
        path = self.checkpoint_dir / validate_checkpoint_name(checkpoint_id)
        # resolve() follows symlinks, so a link that points elsewhere is refused too.
        if path.resolve().parent != self.checkpoint_dir.resolve():
            raise InvalidCheckpointNameError(
                "Invalid checkpoint name: resolves outside the checkpoint directory"
            )
        return path

    @staticmethod
    def _contained_metadata_file(entry: Path) -> Path | None:
        """Return ``entry/metadata.json`` if it is a file that resolves directly inside ``entry``."""
        return KMCheckpointStore._contained_file(entry, "metadata.json")

    @staticmethod
    def _contained_file(entry: Path, name: str) -> Path | None:
        """Return ``entry/name`` if it is a regular file that resolves directly inside ``entry``."""
        path = entry / name
        try:
            inside = path.resolve().parent == entry.resolve()
        except (OSError, RuntimeError):  # RuntimeError: symlink loop (Python < 3.13)
            return None
        return path if inside and path.is_file() else None

    async def get_checkpoint_metadata(self, checkpoint_id: str) -> KMCheckpointMetadata | None:
        """Get metadata for a specific checkpoint."""
        checkpoint_path = self._checkpoint_path(checkpoint_id)
        metadata_file = self._contained_metadata_file(checkpoint_path)

        if metadata_file is None:
            return None

        try:
            metadata_dict = json.loads(metadata_file.read_text())
            return KMCheckpointMetadata(**metadata_dict)
        except (json.JSONDecodeError, TypeError):
            return None

    async def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        return self._remove_entry(self._checkpoint_path(checkpoint_id))

    @staticmethod
    def _remove_entry(checkpoint_path: Path) -> bool:
        if not checkpoint_path.exists():
            return False

        try:
            # Content first: if the rest fails, metadata.json keeps the entry listed and
            # owned, so a later delete or rotation retries it.
            for name in ("content.json.gz", "content.json"):
                (checkpoint_path / name).unlink(missing_ok=True)
            shutil.rmtree(checkpoint_path)
            logger.info("Deleted KM checkpoint: %s", checkpoint_path.name)
            return True
        except OSError as e:
            logger.error("Failed to delete checkpoint %s: %s", checkpoint_path.name, e)
            return False

    async def compare_checkpoints(
        self,
        checkpoint_id_1: str,
        checkpoint_id_2: str,
    ) -> dict[str, Any]:
        """
        Compare two checkpoints.

        Returns statistics about differences between checkpoints.
        """
        meta1 = await self.get_checkpoint_metadata(checkpoint_id_1)
        meta2 = await self.get_checkpoint_metadata(checkpoint_id_2)

        if not meta1 or not meta2:
            return {"error": "One or both checkpoints not found"}

        return {
            "checkpoint_1": checkpoint_id_1,
            "checkpoint_2": checkpoint_id_2,
            "node_count_diff": meta2.node_count - meta1.node_count,
            "relationship_count_diff": meta2.relationship_count - meta1.relationship_count,
            "size_diff_bytes": meta2.size_bytes - meta1.size_bytes,
            "time_diff_seconds": (
                datetime.fromisoformat(meta2.created_at) - datetime.fromisoformat(meta1.created_at)
            ).total_seconds(),
        }

    # =========================================================================
    # Private Export Methods
    # =========================================================================

    async def _export_nodes(
        self,
        incremental: bool,
        parent_checkpoint_id: str | None,
        batch_size: int = 1000,
    ) -> list[dict[str, Any]]:
        """Export nodes from KM using batched iteration.

        Args:
            incremental: Whether this is an incremental export
            parent_checkpoint_id: Parent checkpoint for incremental exports
            batch_size: Number of nodes to fetch per batch (default 1000)

        Returns:
            List of node dictionaries
        """
        nodes = []

        # Get all nodes from the meta store using batched iteration
        if hasattr(self.mound, "_meta_store") and self.mound._meta_store:
            if hasattr(self.mound._meta_store, "query_nodes"):
                offset = 0
                while True:
                    raw_nodes = self.mound._meta_store.query_nodes(
                        workspace_id=self.mound.workspace_id,
                        limit=batch_size,
                        offset=offset,
                    )
                    if not raw_nodes:
                        break  # No more nodes to fetch
                    for node in raw_nodes:
                        node_dict = {
                            "id": node.id,
                            "node_type": node.node_type,
                            "content": node.content,
                            "confidence": node.confidence,
                            "workspace_id": node.workspace_id,
                            "metadata": node.metadata or {},
                            "topics": node.topics or [],
                        }
                        if hasattr(node, "created_at") and node.created_at:
                            node_dict["created_at"] = (
                                node.created_at.isoformat()
                                if hasattr(node.created_at, "isoformat")
                                else str(node.created_at)
                            )
                        if hasattr(node, "provenance") and node.provenance:
                            node_dict["provenance"] = {
                                "source_type": (
                                    node.provenance.source_type.value
                                    if hasattr(node.provenance.source_type, "value")
                                    else str(node.provenance.source_type)
                                ),
                                "source_id": node.provenance.source_id,
                            }
                        nodes.append(node_dict)

                    # Move to next batch
                    offset += len(raw_nodes)
                    if len(raw_nodes) < batch_size:
                        break  # Last batch was partial, no more data

        return nodes

    async def _export_relationships(
        self,
        incremental: bool,
        parent_checkpoint_id: str | None,
    ) -> list[dict[str, Any]]:
        """Export relationships from KM."""
        relationships = []

        # Get relationships from meta store
        if hasattr(self.mound, "_meta_store") and self.mound._meta_store:
            if hasattr(self.mound._meta_store, "get_all_relationships"):
                raw_rels = self.mound._meta_store.get_all_relationships()
                for rel in raw_rels:
                    relationships.append(
                        {
                            "from_node_id": rel.from_node_id,
                            "to_node_id": rel.to_node_id,
                            "relationship_type": rel.relationship_type,
                            "metadata": getattr(rel, "metadata", {}),
                        }
                    )

        return relationships

    async def _export_culture(self) -> dict[str, Any]:
        """Export culture accumulator state."""
        if hasattr(self.mound, "_culture_accumulator") and self.mound._culture_accumulator:
            try:
                return self.mound._culture_accumulator.export_state()
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug("Culture export skipped due to error: %s", e)
        return {}

    async def _export_staleness(self) -> dict[str, Any]:
        """Export staleness detector state."""
        if hasattr(self.mound, "_staleness_detector") and self.mound._staleness_detector:
            try:
                # export_state() provided by StalenessDetector at runtime
                detector = cast(_StalenessDetectorProtocol, self.mound._staleness_detector)
                return detector.export_state()
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug("Staleness export skipped due to error: %s", e)
        return {}

    async def _export_vectors(self) -> dict[str, list[float]]:
        """Export vector embeddings."""
        vectors = {}

        if hasattr(self.mound, "_semantic_store") and self.mound._semantic_store:
            try:
                vectors = self.mound._semantic_store.export_embeddings()
            except (AttributeError, TypeError, ValueError, OSError) as e:
                logger.debug("Vector export skipped due to error: %s", e)

        return vectors

    # =========================================================================
    # Private Restore Methods
    # =========================================================================

    async def _clear_mound_data(self) -> None:
        """Clear existing KM data before restore."""
        # This is dangerous - should be done carefully
        logger.warning("Clearing existing KM data for restore")

        if hasattr(self.mound, "_meta_store") and self.mound._meta_store:
            if hasattr(self.mound._meta_store, "clear_workspace"):
                self.mound._meta_store.clear_workspace(self.mound.workspace_id)

    async def _restore_node(self, node_dict: dict[str, Any]) -> None:
        """Restore a single node."""
        await self.mound._save_node(node_dict)

    async def _restore_relationship(self, rel_dict: dict[str, Any]) -> None:
        """Restore a single relationship."""
        await self.mound._save_relationship(
            from_id=rel_dict["from_node_id"],
            to_id=rel_dict["to_node_id"],
            rel_type=rel_dict["relationship_type"],
        )

    async def _restore_culture(self, culture_state: dict[str, Any]) -> None:
        """Restore culture accumulator state."""
        if hasattr(self.mound, "_culture_accumulator") and self.mound._culture_accumulator:
            try:
                self.mound._culture_accumulator.import_state(culture_state)
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("Failed to restore culture state: %s", e)

    async def _restore_staleness(self, staleness_state: dict[str, Any]) -> None:
        """Restore staleness detector state."""
        if hasattr(self.mound, "_staleness_detector") and self.mound._staleness_detector:
            try:
                # import_state() provided by StalenessDetector at runtime
                detector = cast(_StalenessDetectorProtocol, self.mound._staleness_detector)
                detector.import_state(staleness_state)
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("Failed to restore staleness state: %s", e)

    async def _restore_vectors(self, vectors: dict[str, list[float]]) -> None:
        """Restore vector embeddings."""
        if hasattr(self.mound, "_semantic_store") and self.mound._semantic_store:
            try:
                self.mound._semantic_store.import_embeddings(vectors)
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("Failed to restore vectors: %s", e)

    async def _prune_old_checkpoints(self, org_id: str | None = None) -> int:
        """Prune the oldest checkpoints recorded for ``org_id`` beyond max_checkpoints.

        Checkpoints recorded for any other organization (or for none, when
        ``org_id`` is set) are never pruned. Creates already rotate under the
        same locks, so this is only needed to shrink a store after lowering
        ``max_checkpoints``.
        """
        with self._write_lock, _directory_lock(self.checkpoint_dir):
            deleted = self._delete_oldest(org_id, self.max_checkpoints)

        if deleted > 0:
            logger.info("Pruned %s old KM checkpoints", deleted)

        return deleted


# ============================================================================
# Singleton and Factory
# ============================================================================

_checkpoint_store: KMCheckpointStore | None = None


def get_km_checkpoint_store(
    mound: KnowledgeMound | None = None,
    checkpoint_dir: str | None = None,
) -> KMCheckpointStore | None:
    """
    Get or create the KM checkpoint store singleton.

    Args:
        mound: KnowledgeMound instance (required for first call)
        checkpoint_dir: Optional checkpoint directory override

    Returns:
        KMCheckpointStore instance or None if mound not provided
    """
    global _checkpoint_store

    if _checkpoint_store is None and mound is not None:
        _checkpoint_store = KMCheckpointStore(mound, checkpoint_dir)

    return _checkpoint_store


def reset_km_checkpoint_store() -> None:
    """Reset the checkpoint store singleton (for testing)."""
    global _checkpoint_store
    _checkpoint_store = None


__all__ = [
    "CheckpointCapacityError",
    "InvalidCheckpointNameError",
    "KMCheckpointStore",
    "KMCheckpointMetadata",
    "KMCheckpointContent",
    "RestoreResult",
    "get_km_checkpoint_store",
    "reset_km_checkpoint_store",
    "validate_checkpoint_name",
]
