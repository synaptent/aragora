"""
MCP Checkpoint Tools.

Debate checkpoint management: create, list, resume, delete.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def create_checkpoint_tool(
    debate_id: str,
    label: str = "",
    storage_backend: str = "file",
) -> dict[str, Any]:
    """
    Create a checkpoint for a debate to enable resume later.

    Args:
        debate_id: ID of the debate to checkpoint
        label: Optional label for the checkpoint
        storage_backend: Storage backend (file, s3, git, database)

    Returns:
        Dict with checkpoint ID and status
    """
    if not debate_id:
        return {"error": "debate_id is required"}

    try:
        from aragora.core import Critique, Message, Vote
        from aragora.debate.checkpoint import (
            CheckpointManager,
            CheckpointStore,
            DatabaseCheckpointStore,
            FileCheckpointStore,
        )
        from aragora.storage.debate_storage import get_debates_db

        db = get_debates_db()
        if not db:
            return {"error": "Storage not available"}

        # Fetch debate data
        debate = db.get(debate_id)
        if not debate:
            return {"error": f"Debate {debate_id} not found"}

        # Choose storage backend
        checkpoint_store: CheckpointStore
        if storage_backend == "database":
            checkpoint_store = DatabaseCheckpointStore()
        else:
            checkpoint_store = FileCheckpointStore()

        manager = CheckpointManager(store=checkpoint_store)

        # Convert stored messages to Message objects
        messages = []
        for m in debate.get("messages", []):
            messages.append(
                Message(
                    role=m.get("role", "assistant"),
                    agent=m.get("agent", "unknown"),
                    content=m.get("content", ""),
                    round=m.get("round", 0),
                )
            )

        # Convert stored votes to Vote objects
        votes = []
        for v in debate.get("votes", []):
            votes.append(
                Vote(
                    agent=v.get("agent", "unknown"),
                    choice=v.get("choice", ""),
                    confidence=v.get("confidence", 0.5),
                    reasoning=v.get("reasoning", ""),
                )
            )

        # Convert stored critiques to Critique objects
        critiques = []
        for c in debate.get("critiques", []):
            critiques.append(
                Critique(
                    agent=c.get("agent", "unknown"),
                    target_agent=c.get("target_agent", ""),
                    target_content=c.get("target_content", ""),
                    issues=c.get("issues", []),
                    suggestions=c.get("suggestions", []),
                    severity=c.get("severity", "low"),
                    reasoning=c.get("reasoning", ""),
                )
            )

        # Create simple agent states from debate metadata
        # Use a simple class to hold agent info for checkpoint creation
        class _SimpleAgentHolder:
            def __init__(self, name: str, model: str = "unknown", role: str = "participant"):
                self.name = name
                self.model = model
                self.role = role

        agents_info = debate.get("agents", [])
        agents = []
        for a in agents_info:
            if isinstance(a, str):
                # Just agent name string
                agents.append(_SimpleAgentHolder(a))
            elif isinstance(a, dict):
                agents.append(
                    _SimpleAgentHolder(
                        name=a.get("name", "unknown"),
                        model=a.get("model", "unknown"),
                        role=a.get("role", "participant"),
                    )
                )

        # Create checkpoint
        from aragora.config.settings import DebateSettings

        checkpoint = await manager.create_checkpoint(
            debate_id=debate_id,
            task=debate.get("task", "Unknown task"),
            current_round=debate.get("rounds_used", len(messages) // 3),
            total_rounds=debate.get("total_rounds", DebateSettings().default_rounds),
            phase=debate.get("phase", "completed"),
            messages=messages,
            critiques=critiques,
            votes=votes,
            agents=agents,
            current_consensus=debate.get("final_answer"),
        )

        return {
            "success": True,
            "checkpoint_id": checkpoint.checkpoint_id,
            "debate_id": debate_id,
            "label": label or "(none)",
            "storage_backend": storage_backend,
            "current_round": checkpoint.current_round,
            "message_count": len(checkpoint.messages),
            "created_at": checkpoint.created_at,
        }

    except ImportError as e:
        return {"error": f"Checkpoint module not available: {e}"}
    except (RuntimeError, ValueError, OSError) as e:
        return {"error": f"Failed to create checkpoint: {e}"}


async def list_checkpoints_tool(
    debate_id: str = "",
    include_expired: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """
    List checkpoints for a debate or all debates.

    Args:
        debate_id: Optional debate ID to filter by
        include_expired: Include expired checkpoints
        limit: Max checkpoints to return

    Returns:
        Dict with list of checkpoints
    """
    limit = min(max(limit, 1), 100)

    try:
        from aragora.debate.checkpoint import CheckpointManager

        manager = CheckpointManager()
        # Use store.list_checkpoints which is the actual API
        checkpoints = await manager.store.list_checkpoints(
            debate_id=debate_id or None,
            limit=limit,
        )

        return {
            "checkpoints": [
                {
                    "checkpoint_id": c.get("checkpoint_id", ""),
                    "debate_id": c.get("debate_id", ""),
                    "task": c.get("task", ""),
                    "current_round": c.get("current_round", 0),
                    "message_count": c.get("message_count", 0),
                }
                for c in checkpoints
            ],
            "count": len(checkpoints),
            "debate_id": debate_id or "(all)",
        }

    except ImportError:
        return {"error": "Checkpoint module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        return {"error": f"Failed to list checkpoints: {e}"}


async def resume_checkpoint_tool(
    checkpoint_id: str,
) -> dict[str, Any]:
    """
    Resume a debate from a checkpoint.

    Args:
        checkpoint_id: ID of the checkpoint to resume

    Returns:
        Dict with resumed debate info
    """
    if not checkpoint_id:
        return {"error": "checkpoint_id is required"}

    try:
        from aragora.debate.checkpoint import CheckpointManager

        manager = CheckpointManager()
        # Load checkpoint via store
        checkpoint = await manager.store.load(checkpoint_id)

        if not checkpoint:
            return {"error": f"Checkpoint {checkpoint_id} not found"}

        return {
            "success": True,
            "checkpoint_id": checkpoint_id,
            "debate_id": checkpoint.debate_id,
            "messages_count": len(checkpoint.messages),
            "round": checkpoint.current_round,
            "phase": checkpoint.phase,
            "task": checkpoint.task,
        }

    except ImportError:
        return {"error": "Checkpoint module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        return {"error": f"Failed to resume checkpoint: {e}"}


async def delete_checkpoint_tool(
    checkpoint_id: str,
) -> dict[str, Any]:
    """
    Delete a checkpoint.

    Args:
        checkpoint_id: ID of the checkpoint to delete

    Returns:
        Dict with deletion status
    """
    if not checkpoint_id:
        return {"error": "checkpoint_id is required"}

    try:
        from aragora.debate.checkpoint import CheckpointManager

        manager = CheckpointManager()
        # Delete via store
        success = await manager.store.delete(checkpoint_id)

        return {
            "success": success,
            "checkpoint_id": checkpoint_id,
            "message": "Checkpoint deleted" if success else "Checkpoint not found",
        }

    except ImportError:
        return {"error": "Checkpoint module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        return {"error": f"Failed to delete checkpoint: {e}"}


__all__ = [
    "create_checkpoint_tool",
    "list_checkpoints_tool",
    "resume_checkpoint_tool",
    "delete_checkpoint_tool",
]
