"""
Repository indexing endpoint handlers.

Exposes the repository crawler and orchestrator for codebase indexing.

Endpoints:
- POST /api/repository/index - Start full repository index
- POST /api/repository/incremental - Incremental update
- GET /api/repository/:id/status - Get indexing status
- GET /api/repository/:id/entities - List entities with filters
- GET /api/repository/:id/graph - Get relationship graph
- DELETE /api/repository/:id - Remove indexed repository
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any

from aragora.server.validation import validate_path_segment, SAFE_ID_PATTERN

from ..base import (
    BaseHandler,
    HandlerResult,
    PaginatedHandlerMixin,
    error_response,
    get_int_param,
    get_string_param,
    json_response,
    safe_error_message,
    handle_errors,
)
from ..utils.rate_limit import rate_limit
from aragora.rbac.decorators import require_permission

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _validate_repo_path(repo_path: str) -> tuple[str | None, str | None]:
    """Validate repo_path to prevent path traversal attacks.

    Resolves the path (including symlinks and '..'). If ARAGORA_SCAN_ROOT is
    configured, the resolved path must remain within that boundary.

    Returns:
        (resolved_path, None) on success, or (None, error_message) on failure.
    """
    if not repo_path or not repo_path.strip():
        return None, "repo_path is required"

    if "\x00" in repo_path:
        return None, "repo_path contains invalid null byte"

    allowed_root_env = os.environ.get("ARAGORA_SCAN_ROOT", "").strip()
    resolved = os.path.realpath(repo_path)

    if allowed_root_env:
        allowed_root = os.path.realpath(allowed_root_env)
        # Ensure the resolved path is within the allowed root directory.
        # The trailing os.sep prevents "/allowed_root_extra" matching "/allowed_root".
        # Special-case the filesystem root since root + os.sep would be "//".
        if allowed_root == os.sep:
            pass  # All absolute paths are under the root
        elif not (resolved == allowed_root or resolved.startswith(allowed_root + os.sep)):
            return None, "repo_path must be within the allowed workspace directory"

    return resolved, None


# Module-level cache for orchestrator instance
_orchestrator_instance: Any | None = None
_orchestrator_lock = asyncio.Lock()


async def _get_orchestrator() -> Any | None:
    """Get or create the repository orchestrator instance."""
    global _orchestrator_instance

    if _orchestrator_instance is not None:
        return _orchestrator_instance

    async with _orchestrator_lock:
        if _orchestrator_instance is not None:
            return _orchestrator_instance

        try:
            from aragora.knowledge.repository_orchestrator import (
                RepositoryOrchestrator,
                OrchestratorConfig,
            )
            from aragora.knowledge.mound import KnowledgeMound

            # Initialize with default mound
            # KnowledgeMound is composed from mixins; all abstract methods are
            # implemented by the mixin chain but mypy cannot verify this at instantiation.
            from typing import cast

            _mound_instance = KnowledgeMound()  # type: ignore[abstract]  # Runtime: mixin chain provides implementations
            mound = cast(Any, _mound_instance)  # Type: treat as Any to allow any method calls
            await mound.initialize()

            _orchestrator_instance = RepositoryOrchestrator(
                mound=mound,
                config=OrchestratorConfig(),
            )
            return _orchestrator_instance
        except ImportError as e:
            logger.warning("Failed to import repository modules: %s", e)
            return None
        except (RuntimeError, OSError, ValueError, TypeError) as e:
            logger.warning("Failed to create orchestrator: %s", e)
            return None


async def _get_relationship_builder(repository_name: str) -> Any | None:
    """Get a relationship builder instance for a repository."""
    try:
        from aragora.knowledge.relationship_builder import RelationshipBuilder

        return RelationshipBuilder(repository_name)
    except ImportError as e:
        logger.warning("Failed to import RelationshipBuilder: %s", e)
        return None


class RepositoryHandler(BaseHandler, PaginatedHandlerMixin):
    """Handler for repository indexing endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/repository",
        "/api/v1/repository/index",
        "/api/v1/repository/incremental",
        "/api/v1/repository/batch",
        "/api/v1/repository/*/status",
        "/api/v1/repository/*/entities",
        "/api/v1/repository/*/graph",
        "/api/v1/repository/*",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the request."""
        if path.startswith("/api/v1/repository/"):
            return True
        return False

    @require_permission("repository:read")
    @rate_limit(requests_per_minute=30)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Handle GET requests for repository endpoints."""
        # Handle repository-specific GET routes
        parts = path.split("/")
        if len(parts) >= 4:
            repo_id = parts[3]  # /api/v1/repository/{repo_id}/...

            # Validate repo_id for repository-specific routes
            # Skip validation for action routes like 'index', 'incremental', 'batch'
            if repo_id not in ("index", "incremental", "batch"):
                is_valid, err = validate_path_segment(repo_id, "repo_id", SAFE_ID_PATTERN)
                if not is_valid:
                    return error_response(err or "Invalid repository ID", 400)

                # GET /api/v1/repository/:id/status
                if len(parts) == 5 and parts[4] == "status":
                    return await self._get_status(repo_id)

                # GET /api/v1/repository/:id/entities
                if len(parts) == 5 and parts[4] == "entities":
                    return await self._get_entities(repo_id, query_params)

                # GET /api/v1/repository/:id/graph
                if len(parts) == 5 and parts[4] == "graph":
                    return await self._get_graph(repo_id, query_params)

                # GET /api/v1/repository/:id - Get repository info
                if len(parts) == 4:
                    return await self._get_repository(repo_id)

        return error_response("Repository endpoint not found", 404)

    @handle_errors("repository creation")
    @require_permission("repository:write")
    @rate_limit(requests_per_minute=30)
    async def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Handle POST requests for repository endpoints."""
        body: dict[str, Any] = {}

        # Read JSON body for POST requests
        if handler:
            try:
                content_length = int(handler.headers.get("Content-Length", 0))
                if content_length > 0:
                    raw_body = handler.rfile.read(content_length)
                    body = json.loads(raw_body.decode("utf-8"))
            except (json.JSONDecodeError, ValueError, KeyError, UnicodeDecodeError) as e:
                logger.debug("Failed to parse request body: %s", e)

        # POST /api/v1/repository/index - Start full index
        if path == "/api/v1/repository/index":
            return await self._start_index(body)

        # POST /api/v1/repository/incremental - Incremental update
        if path == "/api/v1/repository/incremental":
            return await self._incremental_update(body)

        # POST /api/v1/repository/batch - Batch index multiple repos
        if path == "/api/v1/repository/batch":
            return await self._batch_index(body)

        return error_response("Repository POST endpoint not found", 404)

    @handle_errors("repository deletion")
    @require_permission("repository:delete")
    @rate_limit(requests_per_minute=30)
    async def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Handle DELETE requests for repository endpoints."""
        body: dict[str, Any] = {}

        # Read JSON body for DELETE requests (for workspace_id)
        if handler:
            try:
                content_length = int(handler.headers.get("Content-Length", 0))
                if content_length > 0:
                    raw_body = handler.rfile.read(content_length)
                    body = json.loads(raw_body.decode("utf-8"))
            except (json.JSONDecodeError, ValueError, KeyError, UnicodeDecodeError) as e:
                logger.debug("Failed to parse request body: %s", e)

        # Handle repository-specific DELETE routes
        parts = path.split("/")
        if len(parts) == 5:
            repo_id = parts[4]  # /api/v1/repository/{repo_id}

            # Validate repo_id
            is_valid, err = validate_path_segment(repo_id, "repo_id", SAFE_ID_PATTERN)
            if not is_valid:
                return error_response(err or "Invalid repository ID", 400)

            # DELETE /api/v1/repository/:id - Remove repository
            return await self._remove_repository(repo_id, body)

        return error_response("Repository DELETE endpoint not found", 404)

    @require_permission("repository.create")
    async def _start_index(self, body: dict[str, Any]) -> HandlerResult:
        """Start a full repository index."""
        orchestrator = await _get_orchestrator()
        if not orchestrator:
            return error_response("Repository orchestrator not available", 503)

        # Validate required fields
        repo_path = body.get("repo_path")
        workspace_id = body.get("workspace_id", "default")

        if not repo_path:
            return error_response("repo_path is required", 400)

        # Validate repo_path to prevent path traversal
        validated_path, path_error = _validate_repo_path(repo_path)
        if path_error:
            return error_response(path_error, 400)
        repo_path = validated_path

        # Optional crawl config
        crawl_config = None
        if "crawl_config" in body:
            try:
                from aragora.connectors.repository_crawler import CrawlConfig

                config_data = body["crawl_config"]
                crawl_config = CrawlConfig(
                    include_patterns=config_data.get("include_patterns", ["*", "**/*"]),
                    exclude_patterns=config_data.get("exclude_patterns", []),
                    max_file_size_bytes=config_data.get("max_file_size_bytes", 1_000_000),
                    max_files=config_data.get("max_files", 10_000),
                    extract_symbols=config_data.get("extract_symbols", True),
                    extract_dependencies=config_data.get("extract_dependencies", True),
                )
            except (ImportError, TypeError, ValueError, KeyError) as e:
                logger.warning("Invalid crawl_config: %s", e)

        try:
            result = await orchestrator.index_repository(
                repo_path=repo_path,
                workspace_id=workspace_id,
                crawl_config=crawl_config,
                incremental=False,  # Full index
            )

            return json_response(
                {
                    "success": len(result.errors) == 0,
                    "result": result.to_dict(),
                }
            )

        except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.error("Repository indexing failed: %s", e)
            return error_response(safe_error_message(e, "indexing"), 500)

    @require_permission("repository.update")
    async def _incremental_update(self, body: dict[str, Any]) -> HandlerResult:
        """Perform incremental repository update."""
        orchestrator = await _get_orchestrator()
        if not orchestrator:
            return error_response("Repository orchestrator not available", 503)

        repo_path = body.get("repo_path")
        workspace_id = body.get("workspace_id", "default")

        if not repo_path:
            return error_response("repo_path is required", 400)

        # Validate repo_path to prevent path traversal
        validated_path, path_error = _validate_repo_path(repo_path)
        if path_error:
            return error_response(path_error, 400)
        repo_path = validated_path

        try:
            result = await orchestrator.incremental_update(
                repo_path=repo_path,
                workspace_id=workspace_id,
            )

            return json_response(
                {
                    "success": len(result.errors) == 0,
                    "result": result.to_dict(),
                }
            )

        except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.error("Incremental update failed: %s", e)
            return error_response(safe_error_message(e, "incremental update"), 500)

    @require_permission("repository.create")
    async def _batch_index(self, body: dict[str, Any]) -> HandlerResult:
        """Index multiple repositories in batch."""
        orchestrator = await _get_orchestrator()
        if not orchestrator:
            return error_response("Repository orchestrator not available", 503)

        repos = body.get("repositories", [])
        if not repos:
            return error_response("repositories array is required", 400)

        try:
            from aragora.knowledge.repository_orchestrator import RepoConfig

            repo_configs = []
            for repo in repos:
                repo_path = repo.get("path")
                if repo_path:
                    validated_path, path_error = _validate_repo_path(repo_path)
                    if path_error:
                        return error_response(f"Invalid path in batch: {path_error}", 400)
                    repo_path = validated_path

                config = RepoConfig(
                    path=repo_path,
                    workspace_id=repo.get("workspace_id", "default"),
                    name=repo.get("name"),
                    priority=repo.get("priority", 0),
                    metadata=repo.get("metadata", {}),
                )
                repo_configs.append(config)

            result = await orchestrator.index_multiple(repo_configs)

            return json_response(
                {
                    "success": result.failed == 0,
                    "result": result.to_dict(),
                }
            )

        except (ImportError, OSError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.error("Batch indexing failed: %s", e)
            return error_response(safe_error_message(e, "batch indexing"), 500)

    @require_permission("repository.read")
    async def _get_status(self, repo_id: str) -> HandlerResult:
        """Get indexing status for a repository."""
        orchestrator = await _get_orchestrator()
        if not orchestrator:
            return error_response("Repository orchestrator not available", 503)

        progress = orchestrator.get_progress(repo_id)
        if not progress:
            # Check all progress
            all_progress = orchestrator.get_all_progress()
            # Try to find by name match
            for path, prog in all_progress.items():
                if repo_id in path:
                    progress = prog
                    break

        if not progress:
            return json_response(
                {
                    "repository_id": repo_id,
                    "status": "unknown",
                    "message": "No active indexing operation found",
                }
            )

        return json_response(
            {
                "repository_id": repo_id,
                "status": progress.status,
                "files_discovered": progress.files_discovered,
                "files_processed": progress.files_processed,
                "nodes_created": progress.nodes_created,
                "current_file": progress.current_file,
                "started_at": progress.started_at.isoformat() if progress.started_at else None,
                "error": progress.error,
            }
        )

    @require_permission("repository.read")
    async def _get_entities(self, repo_id: str, query_params: dict[str, Any]) -> HandlerResult:
        """Get entities from an indexed repository."""
        orchestrator = await _get_orchestrator()
        if not orchestrator:
            return error_response("Repository orchestrator not available", 503)

        # Parse query params
        kind = get_string_param(query_params, "kind")  # file, class, function, etc.
        file_path = get_string_param(query_params, "file_path")
        limit = get_int_param(query_params, "limit", 50)
        offset = get_int_param(query_params, "offset", 0)

        try:
            # Query the mound for entities from this repository
            query = f"repository:{repo_id}"
            if kind:
                query += f" kind:{kind}"
            if file_path:
                query += f" file_path:{file_path}"

            results = await orchestrator.mound.query(
                query=query,
                limit=limit,
            )

            entities = []
            for item in results.items:
                entities.append(
                    {
                        "id": item.id,
                        "content": item.content[:500] if item.content else None,
                        "metadata": item.metadata,
                    }
                )

            return json_response(
                {
                    "repository_id": repo_id,
                    "entities": entities,
                    "total": results.total_count,
                    "limit": limit,
                    "offset": offset,
                }
            )

        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("Failed to get entities: %s", e)
            return error_response(safe_error_message(e, "get entities"), 500)

    @require_permission("repository.read")
    async def _get_graph(self, repo_id: str, query_params: dict[str, Any]) -> HandlerResult:
        """Get relationship graph for a repository."""
        builder = await _get_relationship_builder(repo_id)
        if not builder:
            return error_response("Relationship builder not available", 503)

        # Parse query params
        entity_id = get_string_param(query_params, "entity_id")
        depth = get_int_param(query_params, "depth", 2)
        direction = get_string_param(query_params, "direction", "both")

        try:
            if entity_id:
                # Get dependencies/dependents for specific entity
                if direction == "dependencies":
                    entities = await builder.find_dependencies(entity_id, depth)
                elif direction == "dependents":
                    entities = await builder.find_dependents(entity_id, depth)
                else:
                    deps = await builder.find_dependencies(entity_id, depth)
                    dependents = await builder.find_dependents(entity_id, depth)
                    entities = deps + dependents

                return json_response(
                    {
                        "repository_id": repo_id,
                        "entity_id": entity_id,
                        "direction": direction,
                        "depth": depth,
                        "entities": [
                            {
                                "id": e.id,
                                "name": e.name,
                                "kind": e.kind,
                                "file_path": e.file_path,
                                "line_start": e.line_start,
                            }
                            for e in entities
                        ],
                    }
                )
            else:
                # Return graph statistics
                stats = builder.get_statistics()
                return json_response(
                    {
                        "repository_id": repo_id,
                        "statistics": stats,
                    }
                )

        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("Failed to get graph: %s", e)
            return error_response(safe_error_message(e, "get graph"), 500)

    @require_permission("repository.read")
    async def _get_repository(self, repo_id: str) -> HandlerResult:
        """Get repository information."""
        orchestrator = await _get_orchestrator()
        if not orchestrator:
            return error_response("Repository orchestrator not available", 503)

        try:
            stats = await orchestrator.get_repository_stats(
                repository_name=repo_id,
                workspace_id="default",
            )

            return json_response(stats)

        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("Failed to get repository: %s", e)
            return error_response(safe_error_message(e, "get repository"), 500)

    @require_permission("repository.delete")
    async def _remove_repository(self, repo_id: str, body: dict[str, Any]) -> HandlerResult:
        """Remove an indexed repository."""
        orchestrator = await _get_orchestrator()
        if not orchestrator:
            return error_response("Repository orchestrator not available", 503)

        workspace_id = body.get("workspace_id", "default")

        try:
            removed = await orchestrator.remove_repository(
                repository_name=repo_id,
                workspace_id=workspace_id,
            )

            return json_response(
                {
                    "success": True,
                    "repository_id": repo_id,
                    "nodes_removed": removed,
                }
            )

        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error("Failed to remove repository: %s", e)
            return error_response(safe_error_message(e, "remove repository"), 500)
