"""
Knowledge Mound Checkpoint HTTP Handler.

Provides REST endpoints for managing KM checkpoints:
- GET /api/km/checkpoints - List all checkpoints
- POST /api/km/checkpoints - Create a checkpoint
- GET /api/km/checkpoints/{name} - Get checkpoint details
- DELETE /api/km/checkpoints/{name} - Delete a checkpoint
- POST /api/km/checkpoints/{name}/restore - Restore from checkpoint
- GET /api/km/checkpoints/{name}/compare - Compare with current state
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Protocol

from aragora.events.handler_events import emit_handler_event, CREATED

if TYPE_CHECKING:
    from aragora.knowledge.mound.checkpoint import KMCheckpointMetadata, KMCheckpointStore

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    success_response,
    handle_errors,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils.rate_limit import (
    RateLimiter,
    rate_limit,
)
from aragora.observability.metrics import (
    record_checkpoint_operation,
    track_checkpoint_operation,
)
from aragora.observability.metrics.slo import check_and_record_slo


# Protocol for the checkpoint store's extended interface
# This documents the methods used by the handler, even if the underlying
# implementation may have different signatures
class CheckpointStoreProtocol(Protocol):
    """Protocol defining the expected checkpoint store interface."""

    async def list_checkpoints(self) -> list[Any]: ...
    async def create_checkpoint(
        self,
        name: str,
        description: str = "",
        tags: list[str] | None = None,
        return_metadata: bool = False,
    ) -> str | Any: ...
    def get_checkpoint(self, name: str) -> Any | None: ...
    def delete_checkpoint(self, name: str) -> bool: ...
    def restore_checkpoint(
        self,
        name: str,
        strategy: str = "merge",
        skip_duplicates: bool = True,
    ) -> Any | None: ...
    def compare_with_current(self, name: str) -> dict[str, Any] | None: ...
    def compare_checkpoints(
        self, checkpoint_a: str, checkpoint_b: str
    ) -> dict[str, Any] | None: ...


# Protocol for restore result objects
class RestoreResultProtocol(Protocol):
    """Protocol for checkpoint restore result."""

    checkpoint_name: str
    nodes_restored: int
    nodes_skipped: int
    errors: list[str]


# =============================================================================
# RBAC Permissions
# =============================================================================

KNOWLEDGE_READ_PERMISSION = "knowledge:read"
KNOWLEDGE_WRITE_PERMISSION = "knowledge:write"

# RBAC imports with fallback for backwards compatibility
try:
    from aragora.rbac import check_permission, AuthorizationContext
    from aragora.observability.metrics import record_rbac_check

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

logger = logging.getLogger(__name__)

# Rate limiter for checkpoint endpoints (20 requests per minute)
_checkpoint_limiter = RateLimiter(requests_per_minute=20)

# More restrictive rate limiter for write operations (5 per minute)
_checkpoint_write_limiter = RateLimiter(requests_per_minute=5)


class KMCheckpointHandler(BaseHandler):
    """Handler for Knowledge Mound checkpoint management endpoints."""

    routes = [
        "/api/v1/km/checkpoints",
        "/api/v1/km/checkpoints/compare",
    ]

    # Dynamic routes handled via pattern matching in handle_*
    dynamic_routes = [
        "/api/v1/km/checkpoints/{name}",
        "/api/v1/km/checkpoints/{name}/restore",
        "/api/v1/km/checkpoints/{name}/compare",
        "/api/v1/km/checkpoints/{name}/download",
    ]

    def __init__(self, server_context: dict[str, Any] | None = None):
        # Default to empty dict if None, then cast for BaseHandler
        ctx = server_context if server_context is not None else dict()
        super().__init__(ctx)
        self._checkpoint_store: KMCheckpointStore | None = None

    def _get_checkpoint_store(self) -> KMCheckpointStore:
        """Get or create the checkpoint store instance."""
        if self._checkpoint_store is None:
            try:
                from aragora.knowledge.mound.checkpoint import get_km_checkpoint_store

                store = get_km_checkpoint_store()
                if store is None:
                    raise RuntimeError("KM checkpoint store not initialized")
                self._checkpoint_store = store
            except ImportError:
                raise RuntimeError("KM checkpoint module not available")
        return self._checkpoint_store

    def _check_auth(self, handler: Any) -> tuple[dict[str, Any] | None, HandlerResult | None]:
        """Check authentication for checkpoint operations.

        Returns:
            Tuple of (user_context, error_response) - one will be None
        """
        user, err = self.require_auth_or_error(handler)
        if err:
            return None, err
        # Convert UserAuthContext to dict for RBAC checks
        if user is not None:
            user_dict: dict[str, Any] = {
                "user_id": getattr(user, "user_id", None),
                "sub": getattr(user, "user_id", None),
                "roles": getattr(user, "roles", set()),
                "org_id": getattr(user, "org_id", None),
            }
            return user_dict, None
        return None, None

    def _check_rbac_permission(
        self, auth_ctx: Any, permission_key: str, resource_id: str | None = None
    ) -> HandlerResult | None:
        """Check granular RBAC permission for KM checkpoint operations.

        Args:
            auth_ctx: Authentication context with user info
            permission_key: Permission to check (e.g., "km.checkpoints.read")
            resource_id: Optional specific resource ID

        Returns:
            Error response if permission denied, None if allowed
        """
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
            return None

        try:
            user_id = auth_ctx.get("user_id") or auth_ctx.get("sub")
            if not user_id:
                return error_response("User ID not found in auth context", status=401)

            roles = auth_ctx.get("roles", set())
            if isinstance(roles, list):
                roles = set(roles)

            rbac_context = AuthorizationContext(
                user_id=user_id,
                roles=roles,
                org_id=auth_ctx.get("org_id"),
            )

            decision = check_permission(rbac_context, permission_key, resource_id)

            if not decision.allowed:
                record_rbac_check(permission_key, granted=False)
                logger.warning(
                    "RBAC denied: user=%s permission=%s reason=%s",
                    user_id,
                    permission_key,
                    decision.reason,
                )
                return error_response(
                    f"Permission denied: {permission_key}",
                    status=403,
                )

            record_rbac_check(permission_key, granted=True)
            return None

        except (ValueError, TypeError, AttributeError, KeyError) as e:
            logger.error("RBAC check failed: %s", e)
            # Fail open for backwards compatibility but log the error
            return None

    @rate_limit(requests_per_minute=20)
    async def _list_checkpoints(self, handler: Any) -> HandlerResult:
        """List all KM checkpoints.

        GET /api/km/checkpoints

        Query params:
            limit: Maximum number to return (default: 20, max: 100)
        """
        user, err = self._check_auth(handler)
        if err:
            return err

        # Check RBAC permission
        perm_err = self._check_rbac_permission(user, KNOWLEDGE_READ_PERMISSION)
        if perm_err:
            return perm_err

        try:
            store = self._get_checkpoint_store()

            # Get limit parameter
            limit = int(self.get_query_param(handler, "limit", "20"))
            limit = min(max(1, limit), 100)

            all_checkpoints = await store.list_checkpoints()
            checkpoints: list[KMCheckpointMetadata] = all_checkpoints[:limit]

            return success_response(
                {
                    "checkpoints": [
                        {
                            "name": cp.name,
                            "description": cp.description,
                            "created_at": cp.created_at,
                            "node_count": cp.node_count,
                            "size_bytes": cp.size_bytes,
                            "compressed": cp.compressed,
                            "tags": cp.tags,
                        }
                        for cp in checkpoints
                    ],
                    "total": len(checkpoints),
                }
            )
        except RuntimeError as e:
            logger.error("Checkpoint store not available: %s", e)
            return error_response("Checkpoint service unavailable", status=503)
        except OSError as e:
            logger.error("IO error listing checkpoints: %s", e)
            return error_response("Failed to list checkpoints", status=500)

    @rate_limit(requests_per_minute=5, limiter_name="km_checkpoint_write")
    async def _create_checkpoint(self, handler: Any) -> HandlerResult:
        """Create a new KM checkpoint.

        POST /api/km/checkpoints

        Body:
            name: Checkpoint name (required)
            description: Optional description
            tags: Optional list of tags
        """
        user, err = self._check_auth(handler)
        if err:
            return err

        # Check RBAC permission for write operations
        perm_err = self._check_rbac_permission(user, KNOWLEDGE_WRITE_PERMISSION)
        if perm_err:
            return perm_err

        start_time = time.perf_counter()
        success = False

        try:
            body = self.read_json_body(handler)
            if body is None:
                body = {}
            name = body.get("name")
            if not name:
                return error_response("Checkpoint name is required", status=400)

            description = body.get("description", "")
            tags = body.get("tags", [])

            store = self._get_checkpoint_store()

            with track_checkpoint_operation("create") as ctx:
                result = await store.create_checkpoint(
                    name=name,
                    description=description,
                    tags=tags,
                    return_metadata=True,
                )
                # create_checkpoint returns either a string (checkpoint ID) or KMCheckpointMetadata
                if isinstance(result, str):
                    # If only ID returned, construct minimal response
                    return json_response(
                        {"name": name, "id": result, "description": description, "tags": tags},
                        status=201,
                    )
                # At this point, result is KMCheckpointMetadata (not a string)
                # Import the type for runtime and cast

                metadata = result  # Already CheckpointMeta type
                ctx["size_bytes"] = metadata.size_bytes

            success = True  # noqa: F841
            emit_handler_event("knowledge", CREATED, {"checkpoint": metadata.name})
            return json_response(
                {
                    "name": metadata.name,
                    "description": metadata.description,
                    "created_at": metadata.created_at,
                    "node_count": metadata.node_count,
                    "size_bytes": metadata.size_bytes,
                    "compressed": metadata.compressed,
                    "tags": metadata.tags,
                },
                status=201,
            )
        except ValueError as e:
            logger.warning("Invalid checkpoint request: %s", e)
            return error_response("Invalid request", status=400)
        except FileExistsError:
            return error_response("Checkpoint with this name already exists", status=409)
        except RuntimeError as e:
            logger.error("Checkpoint creation failed: %s", e)
            return error_response("Failed to create checkpoint", status=500)
        finally:
            latency = time.perf_counter() - start_time
            latency_ms = latency * 1000
            record_checkpoint_operation("create", success, latency)
            # Check SLO compliance
            check_and_record_slo("km_checkpoint", latency_ms)

    @rate_limit(requests_per_minute=30)
    async def _get_checkpoint(self, handler: Any, name: str) -> HandlerResult:
        """Get checkpoint details by name.

        GET /api/km/checkpoints/{name}
        """
        user, err = self._check_auth(handler)
        if err:
            return err

        # Check RBAC permission
        perm_err = self._check_rbac_permission(user, KNOWLEDGE_READ_PERMISSION, name)
        if perm_err:
            return perm_err

        try:
            store = self._get_checkpoint_store()
            # Use get_checkpoint_metadata which is the actual async method
            metadata = await store.get_checkpoint_metadata(name)

            if metadata is None:
                return error_response(f"Checkpoint '{name}' not found", status=404)

            # Handle created_at which may be string or datetime
            created_at_str = metadata.created_at
            if hasattr(metadata.created_at, "isoformat"):
                created_at_str = metadata.created_at.isoformat()

            return success_response(
                {
                    "name": metadata.name,
                    "description": metadata.description,
                    "created_at": created_at_str,
                    "node_count": metadata.node_count,
                    "size_bytes": metadata.size_bytes,
                    "compressed": metadata.compressed,
                    "tags": metadata.tags,
                    "checksum": metadata.checksum,
                }
            )
        except RuntimeError as e:
            logger.error("Failed to get checkpoint: %s", e)
            return error_response("Checkpoint service unavailable", status=503)

    @rate_limit(requests_per_minute=5, limiter_name="km_checkpoint_write")
    @require_permission("knowledge:delete")
    async def _delete_checkpoint(self, handler: Any, name: str) -> HandlerResult:
        """Delete a checkpoint.

        DELETE /api/km/checkpoints/{name}
        """
        user, err = self._check_auth(handler)
        if err:
            return err

        # Check RBAC permission for delete operations
        perm_err = self._check_rbac_permission(user, KNOWLEDGE_WRITE_PERMISSION, name)
        if perm_err:
            return perm_err

        start_time = time.perf_counter()
        success = False

        try:
            store = self._get_checkpoint_store()

            # delete_checkpoint is async in the actual implementation
            deleted = await store.delete_checkpoint(name)
            if not deleted:
                return error_response(f"Checkpoint '{name}' not found", status=404)

            success = True
            return success_response({"deleted": name})
        except RuntimeError as e:
            logger.error("Failed to delete checkpoint: %s", e)
            return error_response("Failed to delete checkpoint", status=500)
        finally:
            latency = time.perf_counter() - start_time
            record_checkpoint_operation("delete", success, latency)

    @rate_limit(requests_per_minute=3, limiter_name="km_checkpoint_restore")
    async def _restore_checkpoint(self, handler: Any, name: str) -> HandlerResult:
        """Restore KM state from a checkpoint.

        POST /api/km/checkpoints/{name}/restore

        Body:
            strategy: "merge" (default) or "replace"
            skip_duplicates: boolean (default: True)
        """
        user, err = self._check_auth(handler)
        if err:
            return err

        # Check RBAC permission for restore operations (requires elevated access)
        perm_err = self._check_rbac_permission(user, KNOWLEDGE_WRITE_PERMISSION, name)
        if perm_err:
            return perm_err

        start_time = time.perf_counter()
        success = False

        try:
            body = self.read_json_body(handler) or {}
            strategy = body.get("strategy", "merge")

            if strategy not in ("merge", "replace"):
                return error_response("Invalid strategy. Use 'merge' or 'replace'", status=400)

            store = self._get_checkpoint_store()
            # The actual restore_checkpoint has different signature - use clear_existing based on strategy
            clear_existing = strategy == "replace"
            result = await store.restore_checkpoint(
                checkpoint_id=name,
                clear_existing=clear_existing,
            )

            # RestoreResult has checkpoint_id, not checkpoint_name
            # Map the fields appropriately
            if not result.success and not result.nodes_restored:
                return error_response(f"Checkpoint '{name}' not found", status=404)

            success = True

            from aragora.observability.metrics import record_checkpoint_restore_result

            # The result is a RestoreResult dataclass with known fields
            nodes_restored = result.nodes_restored
            # RestoreResult doesn't have nodes_skipped, calculate from relationships
            nodes_skipped = 0  # Not tracked in actual implementation
            errors_list = result.errors

            record_checkpoint_restore_result(
                nodes_restored=nodes_restored,
                nodes_skipped=nodes_skipped,
                errors=len(errors_list),
            )

            return success_response(
                {
                    "checkpoint_name": result.checkpoint_id,
                    "strategy": strategy,
                    "nodes_restored": nodes_restored,
                    "relationships_restored": result.relationships_restored,
                    "nodes_skipped": nodes_skipped,
                    "errors": errors_list[:10],
                    "error_count": len(errors_list),
                }
            )
        except ValueError as e:
            logger.warning("Invalid restore request: %s", e)
            return error_response("Invalid request", status=400)
        except RuntimeError as e:
            logger.error("Restore failed: %s", e)
            return error_response("Failed to restore checkpoint", status=500)
        finally:
            latency = time.perf_counter() - start_time
            latency_ms = latency * 1000
            record_checkpoint_operation("restore", success, latency)
            # Check SLO compliance
            check_and_record_slo("km_checkpoint", latency_ms)

    @rate_limit(requests_per_minute=30)
    async def _compare_checkpoint(self, handler: Any, name: str) -> HandlerResult:
        """Compare checkpoint with current KM state.

        GET /api/km/checkpoints/{name}/compare

        Note: This compares the checkpoint with a "current" checkpoint.
        The actual implementation uses compare_checkpoints between two checkpoints.
        """
        user, err = self._check_auth(handler)
        if err:
            return err

        # Check RBAC permission for read operations
        perm_err = self._check_rbac_permission(user, KNOWLEDGE_READ_PERMISSION, name)
        if perm_err:
            return perm_err

        start_time = time.perf_counter()
        success = False

        try:
            store = self._get_checkpoint_store()
            # Get the list of checkpoints to find the most recent one for comparison
            checkpoints = await store.list_checkpoints()
            if not checkpoints:
                return error_response("No checkpoints available for comparison", status=404)

            # Find the requested checkpoint
            target_checkpoint = None
            for cp in checkpoints:
                if cp.id == name or cp.name == name:
                    target_checkpoint = cp
                    break

            if target_checkpoint is None:
                return error_response(f"Checkpoint '{name}' not found", status=404)

            # Find a different checkpoint to compare with (the most recent one if not the target)
            compare_with = None
            for cp in checkpoints:
                if cp.id != target_checkpoint.id:
                    compare_with = cp
                    break

            if compare_with is None:
                # Only one checkpoint exists, return its metadata as comparison
                return success_response(
                    {
                        "checkpoint": name,
                        "node_count": target_checkpoint.node_count,
                        "size_bytes": target_checkpoint.size_bytes,
                        "message": "Only one checkpoint exists, no comparison available",
                    }
                )

            comparison = await store.compare_checkpoints(target_checkpoint.id, compare_with.id)

            if comparison is None:
                return error_response(f"Checkpoint '{name}' not found", status=404)

            success = True
            return success_response(comparison)
        except RuntimeError as e:
            logger.error("Comparison failed: %s", e)
            return error_response("Failed to compare checkpoint", status=500)
        finally:
            latency = time.perf_counter() - start_time
            record_checkpoint_operation("compare", success, latency)

    @rate_limit(requests_per_minute=10, limiter_name="km_checkpoint_compare")
    async def _compare_checkpoints(self, handler: Any) -> HandlerResult:
        """Compare two checkpoints.

        POST /api/km/checkpoints/compare

        Body:
            checkpoint_a: First checkpoint name
            checkpoint_b: Second checkpoint name
        """
        user, err = self._check_auth(handler)
        if err:
            return err

        # Check RBAC permission for read operations
        perm_err = self._check_rbac_permission(user, KNOWLEDGE_READ_PERMISSION)
        if perm_err:
            return perm_err

        try:
            body = self.read_json_body(handler)
            if body is None:
                return error_response("Invalid JSON body", status=400)

            checkpoint_a = body.get("checkpoint_a")
            checkpoint_b = body.get("checkpoint_b")

            if not checkpoint_a or not checkpoint_b:
                return error_response("Both checkpoint_a and checkpoint_b are required", status=400)

            store = self._get_checkpoint_store()
            comparison = await store.compare_checkpoints(checkpoint_a, checkpoint_b)

            if comparison is None or comparison.get("error"):
                return error_response("One or both checkpoints not found", status=404)

            return success_response(comparison)
        except RuntimeError as e:
            logger.error("Checkpoint comparison failed: %s", e)
            return error_response("Failed to compare checkpoints", status=500)

    @require_permission("knowledge:read")
    async def handle_get(
        self,
        path: str = "",
        query_params: dict[str, Any] | None = None,
        handler: Any = None,
    ) -> HandlerResult:
        """Handle GET requests.

        Note: This overrides BaseHandler.handle() with async signature and different
        parameters to match the handler registry's calling convention.
        """
        if handler is None:
            return error_response("Missing handler", status=500)

        request_path = handler.path.split("?")[0]

        if request_path == "/api/v1/km/checkpoints":
            return await self._list_checkpoints(handler)

        # Handle /api/km/checkpoints/{name} or /api/km/checkpoints/{name}/compare
        if request_path.startswith("/api/v1/km/checkpoints/"):
            parts = request_path.replace("/api/v1/km/checkpoints/", "").split("/")
            name = parts[0]

            if len(parts) == 1:
                return await self._get_checkpoint(handler, name)
            elif len(parts) == 2 and parts[1] == "compare":
                return await self._compare_checkpoint(handler, name)

        return error_response("Not found", status=404)

    @handle_errors("k m checkpoint creation")
    @require_permission("knowledge:write")
    async def handle_post(
        self,
        path: str = "",
        query_params: dict[str, Any] | None = None,
        handler: Any = None,
    ) -> HandlerResult:
        """Handle POST requests.

        Note: This overrides BaseHandler.handle_post() with async signature to
        match the handler registry's calling convention.
        """
        if handler is None:
            return error_response("Missing handler", status=500)

        request_path = handler.path.split("?")[0]

        if request_path == "/api/v1/km/checkpoints":
            return await self._create_checkpoint(handler)

        if request_path == "/api/v1/km/checkpoints/compare":
            return await self._compare_checkpoints(handler)

        # Handle /api/km/checkpoints/{name}/restore
        if request_path.startswith("/api/v1/km/checkpoints/") and request_path.endswith("/restore"):
            name = request_path.replace("/api/v1/km/checkpoints/", "").replace("/restore", "")
            return await self._restore_checkpoint(handler, name)

        return error_response("Not found", status=404)

    @handle_errors("k m checkpoint deletion")
    @require_permission("knowledge:delete")
    async def handle_delete(
        self,
        path: str = "",
        query_params: dict[str, Any] | None = None,
        handler: Any = None,
    ) -> HandlerResult:
        """Handle DELETE requests.

        Note: This overrides BaseHandler.handle_delete() with async signature to
        match the handler registry's calling convention.
        """
        if handler is None:
            return error_response("Missing handler", status=500)

        request_path = handler.path.split("?")[0]

        # Handle /api/km/checkpoints/{name}
        if request_path.startswith("/api/v1/km/checkpoints/"):
            name = request_path.replace("/api/v1/km/checkpoints/", "")
            if "/" not in name:  # Ensure it's just the name
                return await self._delete_checkpoint(handler, name)

        return error_response("Not found", status=404)
