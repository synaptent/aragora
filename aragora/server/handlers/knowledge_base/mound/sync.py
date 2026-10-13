"""
Sync Operations Mixin for Knowledge Mound Handler.

Provides sync with legacy memory systems:
- Sync from ContinuumMemory
- Sync from ConsensusMemory
- Sync from FactStore
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from aragora.server.http_utils import run_async as _run_async
from aragora.rbac.decorators import require_permission

from ...base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine


logger = logging.getLogger(__name__)


class _MoundSyncOps(Protocol):
    """Subset of KnowledgeMound methods used by SyncOperationsMixin.

    Provides explicit method signatures so mypy can resolve calls
    without traversing the full 17-mixin KnowledgeMound MRO.
    """

    def sync_continuum_incremental(
        self,
        workspace_id: str | None = ...,
        since: str | None = ...,
        limit: int = ...,
    ) -> Coroutine[Any, Any, Any]: ...
    def sync_consensus_incremental(
        self,
        workspace_id: str | None = ...,
        since: str | None = ...,
        limit: int = ...,
    ) -> Coroutine[Any, Any, Any]: ...
    def sync_facts_incremental(
        self,
        workspace_id: str | None = ...,
        since: str | None = ...,
        limit: int = ...,
    ) -> Coroutine[Any, Any, Any]: ...
    def connect_memory_stores(
        self,
        continuum: Any = ...,
        consensus: Any = ...,
        facts: Any = ...,
        evidence: Any = ...,
    ) -> Coroutine[Any, Any, Any]: ...


class SyncHandlerProtocol(Protocol):
    """Protocol for handlers that use SyncOperationsMixin."""

    def _get_mound(self) -> _MoundSyncOps | None: ...


class SyncOperationsMixin:
    """Mixin providing sync operations for KnowledgeMoundHandler."""

    @handle_errors("sync continuum")
    @require_permission("knowledge:read")
    def _handle_sync_continuum(self: SyncHandlerProtocol, handler: Any) -> HandlerResult:
        """Handle POST /api/knowledge/mound/sync/continuum - Sync from ContinuumMemory."""

        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 0:
                body = handler.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            else:
                data = {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        workspace_id = data.get("workspace_id", "default")
        since = data.get("since")
        limit = data.get("limit", 100)

        mound = self._get_mound()
        if not mound:
            return error_response("Knowledge Mound not available", 503)

        try:
            # Use the handler-compatible incremental sync method
            result = _run_async(
                mound.sync_continuum_incremental(
                    workspace_id=workspace_id, since=since, limit=limit
                )
            )
        except AttributeError:
            # Fallback: Connect continuum and try direct sync
            try:
                from aragora.memory import get_continuum_memory

                continuum = get_continuum_memory()
                _run_async(mound.connect_memory_stores(continuum=continuum))
                result = _run_async(
                    mound.sync_continuum_incremental(
                        workspace_id=workspace_id, since=since, limit=limit
                    )
                )
            except (ImportError, AttributeError, RuntimeError) as inner_e:
                logger.debug("ContinuumMemory fallback failed: %s", inner_e)
                return json_response(
                    {
                        "synced": 0,
                        "message": "ContinuumMemory not available or not connected",
                        "workspace_id": workspace_id,
                    }
                )
        except (AttributeError, RuntimeError, OSError) as e:
            logger.error("Failed to sync from continuum: %s", e)
            return error_response("Failed to sync from continuum", 500)

        return json_response(
            {
                "synced": result.nodes_synced if hasattr(result, "nodes_synced") else 0,
                "workspace_id": workspace_id,
                "message": "Sync from ContinuumMemory completed",
            }
        )

    @handle_errors("sync consensus")
    @require_permission("knowledge:read")
    def _handle_sync_consensus(self: SyncHandlerProtocol, handler: Any) -> HandlerResult:
        """Handle POST /api/knowledge/mound/sync/consensus - Sync from ConsensusMemory."""

        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 0:
                body = handler.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            else:
                data = {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        workspace_id = data.get("workspace_id", "default")
        since = data.get("since")
        limit = data.get("limit", 100)

        mound = self._get_mound()
        if not mound:
            return error_response("Knowledge Mound not available", 503)

        try:
            # Use the handler-compatible incremental sync method
            result = _run_async(
                mound.sync_consensus_incremental(
                    workspace_id=workspace_id, since=since, limit=limit
                )
            )
        except AttributeError:
            # Fallback: Connect consensus and try direct sync
            try:
                from aragora.memory import ConsensusMemory

                consensus = ConsensusMemory()
                _run_async(mound.connect_memory_stores(consensus=consensus))
                result = _run_async(
                    mound.sync_consensus_incremental(
                        workspace_id=workspace_id, since=since, limit=limit
                    )
                )
            except (ImportError, AttributeError, RuntimeError) as inner_e:
                logger.debug("ConsensusMemory fallback failed: %s", inner_e)
                return json_response(
                    {
                        "synced": 0,
                        "message": "ConsensusMemory not available or not connected",
                        "workspace_id": workspace_id,
                    }
                )
        except (AttributeError, RuntimeError, OSError) as e:
            logger.error("Failed to sync from consensus: %s", e)
            return error_response("Failed to sync from consensus", 500)

        return json_response(
            {
                "synced": result.nodes_synced if hasattr(result, "nodes_synced") else 0,
                "workspace_id": workspace_id,
                "message": "Sync from ConsensusMemory completed",
            }
        )

    @handle_errors("sync facts")
    @require_permission("knowledge:read")
    def _handle_sync_facts(self: SyncHandlerProtocol, handler: Any) -> HandlerResult:
        """Handle POST /api/knowledge/mound/sync/facts - closed.

        Facts belong to organizations and the Knowledge Mound is not
        organization-scoped, so a sync could only copy every organization's
        facts into a shared mound.
        """
        return error_response(
            "Fact sync needs an organization-scoped Knowledge Mound",
            403,
            code="knowledge_fact_access_closed",
        )
