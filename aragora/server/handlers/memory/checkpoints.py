"""
Checkpoint management endpoint handlers.

Endpoints:
- GET /api/checkpoints - List all checkpoints
- GET /api/checkpoints/{id} - Get checkpoint details
- POST /api/checkpoints/{id}/resume - Resume debate from checkpoint
- DELETE /api/checkpoints/{id} - Delete checkpoint
- GET /api/debates/{id}/checkpoints - List checkpoints for a debate
- POST /api/debates/{id}/checkpoint - Create checkpoint for running debate
- POST /api/debates/{id}/pause - Pause debate and create checkpoint
"""

from __future__ import annotations

__all__ = [
    "CheckpointHandler",
]

import logging
from typing import Any

from aragora.debate.checkpoint import (
    CheckpointManager,
    DatabaseCheckpointStore,
)

from aragora.rbac.decorators import require_permission
from ..base import (
    BaseHandler,
    HandlerResult,
    ServerContext,
    error_response,
    get_int_param,
    handle_errors,
    json_response,
    safe_json_parse,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for checkpoint endpoints (30 requests per minute)
_checkpoint_limiter = RateLimiter(requests_per_minute=30)


class CheckpointHandler(BaseHandler):
    """Handler for checkpoint management endpoints."""

    ROUTES = [
        "/api/v1/checkpoints",
        "/api/v1/checkpoints/resumable",
        "/api/v1/checkpoints/*",
        "/api/v1/checkpoints/*/resume",
        "/api/v1/checkpoints/*/intervention",
    ]

    def __init__(self, context: ServerContext | None = None):
        super().__init__(context or {})
        self._checkpoint_manager: CheckpointManager | None = None

    def _get_checkpoint_manager(self) -> CheckpointManager:
        """Get or create checkpoint manager instance."""
        if self._checkpoint_manager is None:
            # Use database store for persistence
            store = DatabaseCheckpointStore()
            self._checkpoint_manager = CheckpointManager(store=store)
        return self._checkpoint_manager

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return (
            path == "/api/v1/checkpoints"
            or path == "/api/v1/checkpoints/resumable"
            or path.startswith("/api/v1/checkpoints/")
            or (path.startswith("/api/v1/debates/") and "/checkpoint" in path)
        )

    @require_permission("checkpoints:read")
    @handle_errors("checkpoint handling")
    async def handle(
        self,
        path: str,
        query_params: dict[str, str],
        handler: Any,
        body: bytes | None = None,
    ) -> HandlerResult:
        """Route checkpoint requests to appropriate method."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _checkpoint_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for checkpoint endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        method = handler.command

        # GET /api/checkpoints
        if path == "/api/v1/checkpoints" and method == "GET":
            return await self.list_checkpoints(query_params)

        # GET /api/checkpoints/resumable
        if path == "/api/v1/checkpoints/resumable" and method == "GET":
            return await self.list_resumable_debates()

        # /api/v1/checkpoints/{id}...
        if path.startswith("/api/v1/checkpoints/") and not path.startswith(
            "/api/v1/checkpoints/resumable"
        ):
            parts = path.split("/")
            # Parts: ["", "api", "v1", "checkpoints", ":id", ...]
            if len(parts) >= 5:
                checkpoint_id = parts[4]

                # GET /api/v1/checkpoints/{id} (5 parts)
                if method == "GET" and len(parts) == 5:
                    return await self.get_checkpoint(checkpoint_id)

                # POST /api/v1/checkpoints/{id}/resume (6 parts)
                if method == "POST" and len(parts) >= 6 and parts[5] == "resume":
                    return await self.resume_checkpoint(checkpoint_id, body)

                # DELETE /api/v1/checkpoints/{id} (5 parts)
                if method == "DELETE" and len(parts) == 5:
                    return await self.delete_checkpoint(checkpoint_id)

                # POST /api/v1/checkpoints/{id}/intervention (6 parts)
                if method == "POST" and len(parts) >= 6 and parts[5] == "intervention":
                    return await self.add_intervention(checkpoint_id, body)

        # /api/v1/debates/{id}/checkpoint...
        if path.startswith("/api/v1/debates/") and "/checkpoint" in path:
            parts = path.split("/")
            # Parts: ["", "api", "v1", "debates", ":id", ...]
            if len(parts) >= 5:
                debate_id = parts[4]

                # GET /api/v1/debates/{id}/checkpoints (6 parts)
                if method == "GET" and len(parts) >= 6 and parts[5] == "checkpoints":
                    return await self.list_debate_checkpoints(debate_id, query_params)

                # POST /api/v1/debates/{id}/checkpoint (6 parts)
                if method == "POST" and len(parts) == 6 and parts[5] == "checkpoint":
                    return await self.create_checkpoint(debate_id, body)

                # POST /api/v1/debates/{id}/checkpoint/pause (7 parts)
                if (
                    method == "POST"
                    and len(parts) >= 7
                    and parts[5] == "checkpoint"
                    and parts[6] == "pause"
                ):
                    return await self.pause_debate(debate_id, body)

        return error_response("Not found", 404)

    async def list_checkpoints(self, query_params: dict[str, str]) -> HandlerResult:
        """
        GET /api/checkpoints

        List all checkpoints with optional filtering.

        Query params:
        - debate_id: Filter by debate ID
        - status: Filter by status (complete, resuming, corrupted, expired)
        - limit: Maximum results (default 50)
        - offset: Pagination offset
        """
        manager = self._get_checkpoint_manager()

        debate_id = query_params.get("debate_id")
        status_filter = query_params.get("status")
        limit = get_int_param(query_params, "limit", 50)
        offset = get_int_param(query_params, "offset", 0)

        # List checkpoints from store
        all_checkpoints = await manager.store.list_checkpoints(debate_id=debate_id)

        # Filter by status if requested
        if status_filter:
            all_checkpoints = [cp for cp in all_checkpoints if cp.get("status") == status_filter]

        # Apply pagination
        total = len(all_checkpoints)
        checkpoints = all_checkpoints[offset : offset + limit]

        return json_response(
            {
                "checkpoints": checkpoints,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    async def list_resumable_debates(self) -> HandlerResult:
        """
        GET /api/checkpoints/resumable

        List all debates that have resumable checkpoints.
        """
        manager = self._get_checkpoint_manager()
        debates = await manager.list_debates_with_checkpoints()

        return json_response(
            {
                "debates": debates,
                "total": len(debates),
            }
        )

    async def get_checkpoint(self, checkpoint_id: str) -> HandlerResult:
        """
        GET /api/checkpoints/{id}

        Get detailed information about a specific checkpoint.
        """
        manager = self._get_checkpoint_manager()
        checkpoint = await manager.store.load(checkpoint_id)

        if not checkpoint:
            return error_response(f"Checkpoint not found: {checkpoint_id}", 404)

        # Include integrity status
        checkpoint_dict = checkpoint.to_dict()
        checkpoint_dict["integrity_valid"] = checkpoint.verify_integrity()

        return json_response({"checkpoint": checkpoint_dict})

    async def resume_checkpoint(self, checkpoint_id: str, body: bytes | None) -> HandlerResult:
        """
        POST /api/checkpoints/{id}/resume

        Resume a debate from a checkpoint.

        Request body (optional):
        {
            "resumed_by": "user_id",
            "modifications": {
                "task": "Modified task description",
                "additional_rounds": 2
            }
        }
        """
        manager = self._get_checkpoint_manager()

        # Parse request body
        data = safe_json_parse(body) or {}
        resumed_by = data.get("resumed_by", "api")

        # Resume from checkpoint
        resumed = await manager.resume_from_checkpoint(
            checkpoint_id=checkpoint_id,
            resumed_by=resumed_by,
        )

        if not resumed:
            return error_response(
                f"Checkpoint not found or corrupted: {checkpoint_id}",
                404,
            )

        return json_response(
            {
                "message": "Debate resumed from checkpoint",
                "resumed_debate": {
                    "original_debate_id": resumed.original_debate_id,
                    "checkpoint_id": checkpoint_id,
                    "resumed_at": resumed.resumed_at,
                    "resumed_by": resumed.resumed_by,
                    "current_round": resumed.checkpoint.current_round,
                    "total_rounds": resumed.checkpoint.total_rounds,
                    "task": resumed.checkpoint.task,
                    "message_count": len(resumed.messages),
                    "vote_count": len(resumed.votes),
                },
            },
            status=200,
        )

    async def delete_checkpoint(self, checkpoint_id: str) -> HandlerResult:
        """
        DELETE /api/checkpoints/{id}

        Delete a checkpoint.
        """
        manager = self._get_checkpoint_manager()

        # Check if checkpoint exists
        checkpoint = await manager.store.load(checkpoint_id)
        if not checkpoint:
            return error_response(f"Checkpoint not found: {checkpoint_id}", 404)

        # Delete
        success = await manager.store.delete(checkpoint_id)

        if success:
            return json_response(
                {"message": f"Checkpoint deleted: {checkpoint_id}"},
                status=200,
            )
        else:
            return error_response("Failed to delete checkpoint", 500)

    async def add_intervention(self, checkpoint_id: str, body: bytes | None) -> HandlerResult:
        """
        POST /api/checkpoints/{id}/intervention

        Add a human intervention note to a checkpoint.

        Request body:
        {
            "note": "Human review: The debate is stuck on...",
            "by": "reviewer_name"
        }
        """
        data = safe_json_parse(body) or {}
        note = data.get("note")
        by = data.get("by", "human")

        if not note:
            return error_response("Missing required field: note", 400)

        manager = self._get_checkpoint_manager()
        success = await manager.add_intervention(
            checkpoint_id=checkpoint_id,
            note=note,
            by=by,
        )

        if success:
            return json_response(
                {
                    "message": "Intervention note added",
                    "checkpoint_id": checkpoint_id,
                }
            )
        else:
            return error_response(f"Checkpoint not found: {checkpoint_id}", 404)

    async def list_debate_checkpoints(
        self, debate_id: str, query_params: dict[str, str]
    ) -> HandlerResult:
        """
        GET /api/debates/{id}/checkpoints

        List all checkpoints for a specific debate.
        """
        manager = self._get_checkpoint_manager()

        checkpoints = await manager.store.list_checkpoints(debate_id=debate_id)

        # Sort by creation time (most recent first)
        checkpoints.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return json_response(
            {
                "debate_id": debate_id,
                "checkpoints": checkpoints,
                "total": len(checkpoints),
            }
        )

    async def create_checkpoint(self, debate_id: str, body: bytes | None) -> HandlerResult:
        """
        POST /api/debates/{id}/checkpoint

        Manually trigger checkpoint creation for a running debate.

        Request body (optional):
        {
            "phase": "manual",
            "note": "Checkpoint note"
        }
        """
        from aragora.server.state import get_state_manager

        # Get the running debate state
        state_manager = get_state_manager()
        debate_state = state_manager.get_debate(debate_id)

        if debate_state is None:
            return error_response(f"Debate not found: {debate_id}", 404)

        if debate_state.status not in ("running", "initializing", "paused"):
            return error_response(
                f"Cannot checkpoint debate in '{debate_state.status}' state. "
                "Only running, initializing, or paused debates can be checkpointed.",
                400,
            )

        # Parse optional body
        data = safe_json_parse(body) or {}
        phase = data.get("phase", "manual")
        note = data.get("note", "")

        # Create checkpoint using available state
        manager = self._get_checkpoint_manager()

        try:
            # Convert messages from DebateState to checkpoint format
            messages = []
            for msg in debate_state.messages:
                if isinstance(msg, dict):
                    messages.append(msg)
                elif hasattr(msg, "to_dict"):
                    messages.append(msg.to_dict())
                else:
                    messages.append({"content": str(msg)})

            checkpoint = await manager.create_checkpoint(
                debate_id=debate_id,
                task=debate_state.task,
                current_round=debate_state.current_round,
                total_rounds=debate_state.total_rounds,
                phase=phase,
                messages=messages,  # type: ignore[arg-type]
                critiques=[],  # Not available from StateManager
                votes=[],  # Not available from StateManager
                agents=[],  # Agent objects not available, only names
                current_consensus=None,
            )

            # Store note in metadata if provided
            if note:
                checkpoint.metadata = checkpoint.metadata or {}  # type: ignore[attr-defined]
                checkpoint.metadata["note"] = note  # type: ignore[attr-defined]
                await manager.store.save(checkpoint)

            logger.info(
                "Created manual checkpoint %s for debate %s", checkpoint.checkpoint_id, debate_id
            )

            return json_response(
                {
                    "success": True,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "debate_id": debate_id,
                    "phase": phase,
                    "current_round": debate_state.current_round,
                    "message": "Checkpoint created successfully",
                }
            )

        except (OSError, ValueError, TypeError, RuntimeError) as e:
            logger.error("Failed to create checkpoint for %s: %s", debate_id, e)
            return error_response("Checkpoint creation failed", 500)

    async def pause_debate(self, debate_id: str, body: bytes | None) -> HandlerResult:
        """
        POST /api/debates/{id}/checkpoint/pause

        Pause a running debate and create a checkpoint.

        Request body (optional):
        {
            "note": "Pause reason",
            "create_checkpoint": true
        }
        """
        import datetime

        from aragora.server.state import get_state_manager

        # Get the running debate state
        state_manager = get_state_manager()
        debate_state = state_manager.get_debate(debate_id)

        if debate_state is None:
            return error_response(f"Debate not found: {debate_id}", 404)

        if debate_state.status not in ("running", "initializing"):
            return error_response(
                f"Cannot pause debate in '{debate_state.status}' state. "
                "Only running or initializing debates can be paused.",
                400,
            )

        # Parse optional body
        data = safe_json_parse(body) or {}
        note = data.get("note", "")
        create_checkpoint = data.get("create_checkpoint", True)

        # Set pause flag using intervention system
        try:
            from aragora.server.handlers.debates.intervention import (
                get_debate_state,
                log_intervention,
            )

            intervention_state = get_debate_state(debate_id)
            intervention_state["is_paused"] = True
            intervention_state["paused_at"] = datetime.datetime.now().isoformat()

            log_intervention(
                debate_id,
                "pause_with_checkpoint",
                {"note": note, "create_checkpoint": create_checkpoint},
                user_id=None,
            )
        except ImportError:
            logger.warning("Intervention module not available, pause flag not set")

        # Update debate status
        state_manager.update_debate_status(debate_id, status="paused")

        # Create checkpoint if requested
        checkpoint_id = None
        if create_checkpoint:
            manager = self._get_checkpoint_manager()
            try:
                messages = []
                for msg in debate_state.messages:
                    if isinstance(msg, dict):
                        messages.append(msg)
                    elif hasattr(msg, "to_dict"):
                        messages.append(msg.to_dict())
                    else:
                        messages.append({"content": str(msg)})

                checkpoint = await manager.create_checkpoint(
                    debate_id=debate_id,
                    task=debate_state.task,
                    current_round=debate_state.current_round,
                    total_rounds=debate_state.total_rounds,
                    phase="paused",
                    messages=messages,  # type: ignore[arg-type]
                    critiques=[],
                    votes=[],
                    agents=[],
                    current_consensus=None,
                )
                checkpoint_id = checkpoint.checkpoint_id

                # Store note in metadata
                if note:
                    checkpoint.metadata = checkpoint.metadata or {}  # type: ignore[attr-defined]
                    checkpoint.metadata["pause_note"] = note  # type: ignore[attr-defined]
                    await manager.store.save(checkpoint)

                logger.info("Paused debate %s with checkpoint %s", debate_id, checkpoint_id)

            except (OSError, ValueError, TypeError, RuntimeError) as e:
                logger.warning("Failed to create checkpoint during pause: %s", e)

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "status": "paused",
                "checkpoint_id": checkpoint_id,
                "message": "Debate paused successfully",
                "hint": "Use POST /api/checkpoints/{id}/resume to resume the debate "
                "or POST /api/debates/{id}/intervention/resume to continue without checkpoint.",
            }
        )
