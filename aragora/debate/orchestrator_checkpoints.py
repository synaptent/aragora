"""Checkpoint save/restore/list/cleanup helpers for Arena.

Extracted from orchestrator.py to reduce its size. These standalone
async functions receive the required state (checkpoint_manager, env,
agents, protocol, etc.) as explicit parameters rather than reading
``self`` attributes, following the same pattern as orchestrator_hooks.py.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from aragora.core import Critique, DebateResult, Message, Vote
from aragora.debate.context import DebateContext
from aragora.logging_config import get_logger as get_structured_logger

if TYPE_CHECKING:
    from aragora.core import Agent, Environment
    from aragora.protocols.debate import DebateProtocol

logger = get_structured_logger(__name__)


async def save_checkpoint(
    checkpoint_manager: Any,
    debate_id: str,
    env: Environment,
    protocol: DebateProtocol,
    agents: list[Agent],
    phase: str = "manual",
    messages: list[Message] | None = None,
    critiques: list[Critique] | None = None,
    votes: list[Vote] | None = None,
    current_round: int = 0,
    current_consensus: str | None = None,
) -> str | None:
    """Save a checkpoint for the current debate state.

    This allows manual checkpoint creation at any point during or after
    debate.  Checkpoints enable debate resumption and crash recovery.

    Args:
        checkpoint_manager: The :class:`CheckpointManager` instance
            (``None`` is acceptable -- the call becomes a no-op).
        debate_id: Unique identifier for the debate.
        env: The debate :class:`Environment`.
        protocol: The :class:`DebateProtocol` in use.
        agents: List of participating agents.
        phase: Current phase name (e.g. "proposal", "critique",
            "consensus", "manual").
        messages: Message history to checkpoint.
        critiques: Critique history to checkpoint.
        votes: Vote history to checkpoint.
        current_round: Current round number.
        current_consensus: Current consensus text if available.

    Returns:
        Checkpoint ID if successful, ``None`` otherwise.
    """
    if not checkpoint_manager:
        logger.debug("[checkpoint] No checkpoint manager configured")
        return None

    try:
        checkpoint = await checkpoint_manager.create_checkpoint(
            debate_id=debate_id,
            task=env.task if env else "",
            current_round=current_round,
            total_rounds=protocol.rounds if protocol else 0,
            phase=phase,
            messages=messages or [],
            critiques=critiques or [],
            votes=votes or [],
            agents=agents or [],
            current_consensus=current_consensus,
        )
        logger.info(
            "[checkpoint] Saved checkpoint %s for debate %s", checkpoint.checkpoint_id, debate_id
        )
        return checkpoint.checkpoint_id

    except (OSError, ValueError, TypeError, RuntimeError) as e:
        logger.warning("[checkpoint] Failed to save checkpoint: %s", e)
        return None


async def restore_from_checkpoint(
    checkpoint_manager: Any,
    checkpoint_id: str,
    env: Environment,
    agents: list[Agent],
    domain: str = "",
    hook_manager: Any = None,
    org_id: str = "",
    resumed_by: str = "system",
) -> DebateContext | None:
    """Restore debate state from a checkpoint.

    Loads a checkpoint and reconstructs the debate context, enabling
    resumption of interrupted debates.

    Args:
        checkpoint_manager: The :class:`CheckpointManager` instance
            (``None`` is acceptable -- the call becomes a no-op).
        checkpoint_id: ID of the checkpoint to restore from.
        env: The debate :class:`Environment`.
        agents: List of participating agents.
        domain: Debate domain string (e.g. from
            ``_extract_debate_domain``).
        hook_manager: Optional hook manager for extended lifecycle hooks.
        org_id: Organisation identifier for multi-tenancy.
        resumed_by: Identifier for who/what is resuming (for audit).

    Returns:
        :class:`DebateContext` if restoration successful, ``None``
        otherwise.
    """
    if not checkpoint_manager:
        logger.debug("[checkpoint] No checkpoint manager configured")
        return None

    try:
        resumed = await checkpoint_manager.resume_from_checkpoint(
            checkpoint_id=checkpoint_id,
            resumed_by=resumed_by,
        )

        if not resumed:
            logger.warning("[checkpoint] Checkpoint %s not found or corrupted", checkpoint_id)
            return None

        # Reconstruct DebateContext from checkpoint
        ctx = DebateContext(
            env=env,
            agents=agents,
            start_time=time.time(),
            debate_id=resumed.original_debate_id,
            correlation_id=f"resumed-{checkpoint_id[:8]}",
            domain=domain,
            hook_manager=hook_manager,
            org_id=org_id,
        )

        # Restore result state
        ctx.result = DebateResult(
            task=resumed.checkpoint.task,
            messages=resumed.messages,
            critiques=[],  # Critiques stored as dicts in checkpoint
            votes=resumed.votes,
            rounds_used=resumed.checkpoint.current_round,
            consensus_reached=False,
            confidence=resumed.checkpoint.consensus_confidence,
            final_answer=resumed.checkpoint.current_consensus or "",
        )

        # Reconstruct critiques from checkpoint data
        for c_dict in resumed.checkpoint.critiques:
            ctx.result.critiques.append(
                Critique(
                    agent=c_dict.get("agent", ""),
                    target_agent=c_dict.get("target_agent", ""),
                    target_content=c_dict.get("target_content", ""),
                    issues=c_dict.get("issues", []),
                    suggestions=c_dict.get("suggestions", []),
                    severity=c_dict.get("severity", 0.0),
                    reasoning=c_dict.get("reasoning", ""),
                )
            )

        # Store checkpoint reference for tracking
        ctx._restored_from_checkpoint = checkpoint_id
        ctx._checkpoint_resume_round = resumed.checkpoint.current_round

        logger.info(
            "[checkpoint] Restored from checkpoint %s at round %s",
            checkpoint_id,
            resumed.checkpoint.current_round,
        )
        return ctx

    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        logger.warning("[checkpoint] Failed to restore checkpoint: %s", e)
        return None


async def list_checkpoints(
    checkpoint_manager: Any,
    debate_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """List available checkpoints.

    Args:
        checkpoint_manager: The :class:`CheckpointManager` instance
            (``None`` is acceptable -- the call becomes a no-op).
        debate_id: Filter by debate ID (``None`` for all checkpoints).
        limit: Maximum number of checkpoints to return.

    Returns:
        List of checkpoint metadata dicts with keys:

        - ``checkpoint_id``: Unique checkpoint identifier
        - ``debate_id``: Associated debate ID
        - ``task``: Debate task (truncated)
        - ``current_round``: Round number at checkpoint
        - ``created_at``: Checkpoint creation timestamp
        - ``status``: Checkpoint status (complete, resuming, etc.)
    """
    if not checkpoint_manager:
        logger.debug("[checkpoint] No checkpoint manager configured")
        return []

    try:
        return await checkpoint_manager.store.list_checkpoints(
            debate_id=debate_id,
            limit=limit,
        )
    except (OSError, ValueError, TypeError, AttributeError) as e:
        logger.warning("[checkpoint] Failed to list checkpoints: %s", e)
        return []


async def cleanup_checkpoints(
    checkpoint_manager: Any,
    debate_id: str,
    keep_latest: int = 1,
) -> int:
    """Clean up old checkpoints for a completed debate.

    Removes checkpoints beyond the *keep_latest* count, freeing storage.
    Should be called after successful debate completion.

    Args:
        checkpoint_manager: The :class:`CheckpointManager` instance
            (``None`` is acceptable -- the call becomes a no-op).
        debate_id: Debate ID to clean up checkpoints for.
        keep_latest: Number of most recent checkpoints to keep.

    Returns:
        Number of checkpoints deleted.
    """
    if not checkpoint_manager:
        return 0

    try:
        checkpoints = await checkpoint_manager.store.list_checkpoints(
            debate_id=debate_id,
            limit=1000,  # Get all
        )

        # Sort by creation time (newest first)
        checkpoints.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # Delete extras beyond keep_latest
        deleted = 0
        for cp in checkpoints[keep_latest:]:
            if await checkpoint_manager.store.delete(cp["checkpoint_id"]):
                deleted += 1
                logger.debug("[checkpoint] Deleted checkpoint %s", cp["checkpoint_id"])

        if deleted > 0:
            logger.info("[checkpoint] Cleaned up %s checkpoints for debate %s", deleted, debate_id)
        return deleted

    except (OSError, ValueError, TypeError, AttributeError) as e:
        logger.warning("[checkpoint] Cleanup failed: %s", e)
        return 0
