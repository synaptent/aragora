"""
Redis-backed checkpoint store implementation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any

from aragora.workflow.checkpoints._compat import (
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_OPERATION_TIMEOUT,
)
from aragora.workflow.checkpoints.exceptions import ConnectionTimeoutError
from aragora.workflow.types import WorkflowCheckpoint

logger = logging.getLogger(__name__)


class RedisCheckpointStore:
    """
    Redis-backed checkpoint store for distributed, fast checkpoint storage.

    Features:
    - Fast distributed storage across multiple server instances
    - TTL-based automatic cleanup of old checkpoints
    - JSON serialization with compression for large checkpoints
    - Atomic operations for checkpoint updates
    - Connection and operation timeouts for reliability

    Usage:
        store = RedisCheckpointStore(ttl_hours=24)
        checkpoint_id = await store.save(checkpoint)
        checkpoint = await store.load_latest("workflow_123")

    Environment:
        Requires REDIS_URL environment variable or Redis configuration
        in aragora.utils.redis_config.
    """

    # Key prefixes for Redis
    PREFIX = "aragora:workflow:checkpoint"
    WORKFLOW_INDEX_PREFIX = "aragora:workflow:index"

    def __init__(
        self,
        ttl_hours: float = 24.0,
        compress_threshold: int = 4096,
        socket_timeout: float = DEFAULT_OPERATION_TIMEOUT,
        socket_connect_timeout: float = DEFAULT_CONNECTION_TIMEOUT,
    ):
        """
        Initialize Redis checkpoint store.

        Args:
            ttl_hours: Time-to-live for checkpoints in hours (default 24h)
            compress_threshold: Compress checkpoints larger than this (bytes)
            socket_timeout: Timeout for Redis operations in seconds (default 30s)
            socket_connect_timeout: Timeout for Redis connection in seconds (default 10s)
        """
        # Import from stub for test patching compatibility
        import aragora.workflow.checkpoint_store as _compat_stub

        if not _compat_stub.REDIS_AVAILABLE:
            raise RuntimeError(
                "Redis checkpoint store requires Redis configuration. "
                "Ensure aragora.utils.redis_config is available and REDIS_URL is set."
            )

        self._ttl_seconds = int(ttl_hours * 3600)
        self._compress_threshold = compress_threshold
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout
        self._redis = None

    def _get_redis(self) -> Any:
        """Get Redis client (lazy initialization)."""
        if self._redis is None:
            # Import from stub for test patching compatibility
            import aragora.workflow.checkpoint_store as _compat_stub

            if _compat_stub._get_redis_client is None:
                raise RuntimeError("Redis client not available")
            self._redis = _compat_stub._get_redis_client()
            if self._redis is None:
                raise RuntimeError("Redis client not available")
            # Configure socket timeouts if supported
            try:
                # Redis-py supports socket_timeout configuration
                if hasattr(self._redis, "connection_pool"):
                    pool = self._redis.connection_pool
                    pool.connection_kwargs["socket_timeout"] = self._socket_timeout
                    pool.connection_kwargs["socket_connect_timeout"] = self._socket_connect_timeout
                    logger.debug(
                        "Redis checkpoint store configured with timeouts: socket_timeout=%ss, connect_timeout=%ss",
                        self._socket_timeout,
                        self._socket_connect_timeout,
                    )
            except (AttributeError, KeyError, TypeError, RuntimeError) as e:
                logger.debug("Could not configure Redis socket timeouts: %s", e)
        return self._redis

    def _checkpoint_key(self, checkpoint_id: str) -> str:
        """Build Redis key for a checkpoint."""
        return f"{self.PREFIX}:{checkpoint_id}"

    def _workflow_index_key(self, workflow_id: str) -> str:
        """Build Redis key for workflow checkpoint index."""
        return f"{self.WORKFLOW_INDEX_PREFIX}:{workflow_id}"

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        """
        Save a checkpoint to Redis.

        Args:
            checkpoint: WorkflowCheckpoint to save

        Returns:
            Checkpoint ID

        Raises:
            ConnectionTimeoutError: If Redis operation times out
        """
        import time
        import zlib

        try:
            redis = self._get_redis()
            checkpoint_id = f"{checkpoint.workflow_id}_{int(time.time() * 1000)}"

            # Serialize checkpoint
            checkpoint_dict = self._checkpoint_to_dict(checkpoint)
            checkpoint_dict["checkpoint_id"] = checkpoint_id
            data = json.dumps(checkpoint_dict, default=str)

            # Compress if large
            data_bytes: bytes
            if len(data) > self._compress_threshold:
                data_bytes = zlib.compress(data.encode("utf-8"))
                is_compressed = True
            else:
                data_bytes = data.encode("utf-8")
                is_compressed = False

            # Store checkpoint
            key = self._checkpoint_key(checkpoint_id)
            redis.setex(key, self._ttl_seconds, data_bytes)

            # Store compression flag
            redis.setex(f"{key}:meta", self._ttl_seconds, json.dumps({"compressed": is_compressed}))

            # Add to workflow index (sorted set by timestamp)
            index_key = self._workflow_index_key(checkpoint.workflow_id)
            redis.zadd(index_key, {checkpoint_id: time.time()})
            redis.expire(index_key, self._ttl_seconds)

            logger.info(
                "Saved checkpoint to Redis: workflow=%s, id=%s, size=%s, compressed=%s",
                checkpoint.workflow_id,
                checkpoint_id,
                len(data_bytes),
                is_compressed,
            )
            return checkpoint_id

        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            # Check for Redis timeout errors
            error_name = type(e).__name__
            if "Timeout" in error_name or "ConnectionError" in error_name:
                raise ConnectionTimeoutError(f"Redis checkpoint save timed out: {e}") from e
            raise

    async def load(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """
        Load a checkpoint by ID.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            WorkflowCheckpoint or None if not found

        Raises:
            ConnectionTimeoutError: If Redis operation times out
        """
        import zlib

        try:
            redis = self._get_redis()
            key = self._checkpoint_key(checkpoint_id)

            # Get data
            data = redis.get(key)
            if data is None:
                return None

            # Check if compressed
            meta = redis.get(f"{key}:meta")
            is_compressed = False
            if meta:
                meta_dict = json.loads(meta)
                is_compressed = meta_dict.get("compressed", False)

            # Decompress if needed
            if is_compressed:
                data = zlib.decompress(data).decode("utf-8")
            elif isinstance(data, bytes):
                data = data.decode("utf-8")

            checkpoint_dict = json.loads(data)
            return self._dict_to_checkpoint(checkpoint_dict)

        except (
            ConnectionError,
            TimeoutError,
            OSError,
            RuntimeError,
            ValueError,
            json.JSONDecodeError,
        ) as e:
            # Check for Redis timeout errors
            error_name = type(e).__name__
            if "Timeout" in error_name or "ConnectionError" in error_name:
                raise ConnectionTimeoutError(f"Redis checkpoint load timed out: {e}") from e
            logger.error("Failed to load checkpoint %s from Redis: %s", checkpoint_id, e)
            return None

    async def load_latest(self, workflow_id: str) -> WorkflowCheckpoint | None:
        """
        Load the most recent checkpoint for a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            Most recent WorkflowCheckpoint or None

        Raises:
            ConnectionTimeoutError: If Redis operation times out
        """
        try:
            redis = self._get_redis()
            index_key = self._workflow_index_key(workflow_id)

            # Get latest checkpoint ID from sorted set (highest score = most recent)
            results = redis.zrevrange(index_key, 0, 0)
            if not results:
                return None

            checkpoint_id = results[0]
            if isinstance(checkpoint_id, bytes):
                checkpoint_id = checkpoint_id.decode("utf-8")

            return await self.load(checkpoint_id)

        except ConnectionTimeoutError:
            # Re-raise timeout errors
            raise
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            # Check for Redis timeout errors
            error_name = type(e).__name__
            if "Timeout" in error_name or "ConnectionError" in error_name:
                raise ConnectionTimeoutError(f"Redis checkpoint load_latest timed out: {e}") from e
            logger.error("Failed to load latest checkpoint for %s: %s", workflow_id, e)
            return None

    async def list_checkpoints(self, workflow_id: str) -> list[str]:
        """
        List all checkpoint IDs for a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            List of checkpoint IDs (newest first)
        """
        try:
            redis = self._get_redis()
            index_key = self._workflow_index_key(workflow_id)

            results = redis.zrevrange(index_key, 0, -1)
            return [r.decode("utf-8") if isinstance(r, bytes) else r for r in results]

        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.error("Failed to list checkpoints for %s: %s", workflow_id, e)
            return []

    async def delete(self, checkpoint_id: str) -> bool:
        """
        Delete a checkpoint.

        Args:
            checkpoint_id: Checkpoint ID to delete

        Returns:
            True if deleted
        """
        try:
            redis = self._get_redis()
            key = self._checkpoint_key(checkpoint_id)

            # Delete checkpoint and metadata
            deleted = redis.delete(key, f"{key}:meta")

            # Remove from workflow index
            # Extract workflow_id from checkpoint_id (format: workflow_id_timestamp)
            parts = checkpoint_id.rsplit("_", 1)
            if len(parts) == 2:
                workflow_id = parts[0]
                index_key = self._workflow_index_key(workflow_id)
                redis.zrem(index_key, checkpoint_id)

            return deleted > 0

        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.error("Failed to delete checkpoint %s: %s", checkpoint_id, e)
            return False

    def _checkpoint_to_dict(self, checkpoint: WorkflowCheckpoint) -> dict[str, Any]:
        """Convert checkpoint to dictionary."""
        if hasattr(checkpoint, "to_dict"):
            return checkpoint.to_dict()
        elif hasattr(checkpoint, "__dataclass_fields__"):
            return asdict(checkpoint)
        else:
            return {
                "id": getattr(checkpoint, "id", ""),
                "workflow_id": checkpoint.workflow_id,
                "definition_id": checkpoint.definition_id,
                "current_step": checkpoint.current_step,
                "completed_steps": list(checkpoint.completed_steps),
                "step_outputs": dict(checkpoint.step_outputs),
                "context_state": dict(getattr(checkpoint, "context_state", {})),
                "created_at": (
                    checkpoint.created_at.isoformat()
                    if hasattr(checkpoint.created_at, "isoformat")
                    else str(checkpoint.created_at)
                ),
                "checksum": getattr(checkpoint, "checksum", ""),
            }

    def _dict_to_checkpoint(self, data: dict[str, Any]) -> WorkflowCheckpoint:
        """Convert dictionary to WorkflowCheckpoint."""
        created_at = data.get("created_at", "")
        if isinstance(created_at, str) and created_at:
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                created_at = datetime.now()
        elif not isinstance(created_at, datetime):
            created_at = datetime.now()

        return WorkflowCheckpoint(
            id=data.get("id", ""),
            workflow_id=data.get("workflow_id", ""),
            definition_id=data.get("definition_id", ""),
            current_step=data.get("current_step", ""),
            completed_steps=list(data.get("completed_steps", [])),
            step_outputs=data.get("step_outputs", {}),
            context_state=data.get("context_state", {}),
            created_at=created_at,
            checksum=data.get("checksum", ""),
        )
