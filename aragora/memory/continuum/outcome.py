"""
Outcome and surprise scoring mixin for ContinuumMemory.

Provides update_outcome, learning rate calculation, and related
surprise-based learning operations.
"""
# mypy: disable-error-code="misc"
# Mixin classes use self: "ContinuumMemory" type hints which mypy doesn't understand

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aragora.memory.tier_manager import MemoryTier, TierConfig
from aragora.resilience.retry import PROVIDER_RETRY_POLICIES, with_retry
from aragora.utils.datetime_helpers import utc_now_iso_naive

from .types import TIER_CONFIGS

if TYPE_CHECKING:
    from .core import ContinuumMemory

logger = logging.getLogger(__name__)

# Retry configuration for memory operations
_MEMORY_RETRY_CONFIG = PROVIDER_RETRY_POLICIES["memory"]


class OutcomeMixin:
    """Mixin providing outcome and surprise scoring operations for ContinuumMemory.

    Supports post-outcome hooks for pattern extraction and other downstream
    processing. Hooks are fire-and-forget (failures are logged but don't
    block the update).
    """

    # Post-outcome hooks registered via register_post_outcome_hook()
    _post_outcome_hooks: list | None = None

    def register_post_outcome_hook(
        self: ContinuumMemory,
        hook: Any,
    ) -> None:
        """Register a callback to fire after update_outcome completes.

        The hook receives a dict with:
            - id: Memory ID that was updated
            - success: Whether the outcome was successful
            - surprise_score: Updated surprise score
            - tier: Memory tier
            - total_observations: Total success + failure count

        Hooks are fire-and-forget: exceptions are logged but don't propagate.

        Args:
            hook: Callable[[dict], None] to invoke after outcome updates.
        """
        if self._post_outcome_hooks is None:
            self._post_outcome_hooks = []
        self._post_outcome_hooks.append(hook)

    def _fire_post_outcome_hooks(
        self: ContinuumMemory,
        outcome_data: dict[str, Any],
    ) -> None:
        """Fire all registered post-outcome hooks (non-blocking)."""
        if not self._post_outcome_hooks:
            return

        for hook in self._post_outcome_hooks:
            try:
                result = hook(outcome_data)
                # Handle async hooks via fire-and-forget task
                if asyncio.iscoroutine(result):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        # No event loop running - can't dispatch async
                        pass
            except (
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                RuntimeError,
                OSError,
            ) as hook_err:
                logger.warning("Post-outcome hook failed: %s", hook_err)

    def update_outcome(
        self: ContinuumMemory,
        id: str,
        success: bool,
        agent_prediction_error: float | None = None,
    ) -> float:
        """
        Update memory after observing outcome.

        This implements surprise-based learning: the surprise score is
        updated based on how unexpected the outcome was.

        Uses BEGIN IMMEDIATE to prevent race conditions by acquiring
        a write lock before reading the current state.

        Args:
            id: Memory ID
            success: Whether the pattern led to success
            agent_prediction_error: Optional agent's prediction error

        Returns:
            Updated surprise score
        """
        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()

            # Use BEGIN IMMEDIATE to acquire write lock before reading.
            # This prevents race conditions in read-modify-write operations.
            # Note: get_wal_connection sets busy_timeout (default 30s) to prevent
            # indefinite blocking - will raise sqlite3.OperationalError if timeout
            # exceeded waiting for the lock.
            cursor.execute("BEGIN IMMEDIATE")

            try:
                # Get current state (now protected by write lock)
                cursor.execute(
                    """
                    SELECT success_count, failure_count, surprise_score, tier
                    FROM continuum_memory WHERE id = ?
                    """,
                    (id,),
                )
                row: tuple[Any, ...] | None = cursor.fetchone()
                if not row:
                    cursor.execute("ROLLBACK")
                    return 0.0

                success_count: int
                failure_count: int
                old_surprise_raw: Any
                tier: str
                success_count, failure_count, old_surprise_raw, tier = row
                old_surprise: float = float(old_surprise_raw) if old_surprise_raw else 0.0
                total: int = success_count + failure_count

                # Calculate expected success rate (base rate)
                expected_rate: float = success_count / total if total > 0 else 0.5

                # Actual outcome
                actual: float = 1.0 if success else 0.0

                # Success rate surprise component
                success_surprise: float = abs(actual - expected_rate)

                # Combine surprise signals
                new_surprise: float = self.hyperparams[
                    "surprise_weight_success"
                ] * success_surprise + self.hyperparams["surprise_weight_agent"] * (
                    agent_prediction_error or 0.0
                )

                # Exponential moving average for surprise
                alpha: float = 0.3
                updated_surprise: float = old_surprise * (1 - alpha) + new_surprise * alpha

                # Update consolidation score
                update_count: int = total + 1
                consolidation: float = min(
                    1.0,
                    math.log(1 + update_count)
                    / math.log(self.hyperparams["consolidation_threshold"]),
                )

                # Update database
                if success:
                    cursor.execute(
                        """
                        UPDATE continuum_memory
                        SET success_count = success_count + 1,
                            update_count = update_count + 1,
                            surprise_score = ?,
                            consolidation_score = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (updated_surprise, consolidation, utc_now_iso_naive(), id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE continuum_memory
                        SET failure_count = failure_count + 1,
                            update_count = update_count + 1,
                            surprise_score = ?,
                            consolidation_score = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (updated_surprise, consolidation, utc_now_iso_naive(), id),
                    )

                cursor.execute("COMMIT")

                # Fire post-outcome hooks (non-blocking, outside transaction)
                self._fire_post_outcome_hooks(
                    {
                        "id": id,
                        "success": success,
                        "surprise_score": updated_surprise,
                        "tier": tier,
                        "total_observations": update_count,
                    }
                )
            except sqlite3.Error as e:
                logger.error("Database error updating surprise score: %s", e, exc_info=True)
                cursor.execute("ROLLBACK")
                raise
            except (ValueError, TypeError, ArithmeticError, RuntimeError) as e:
                # Rollback on non-database exceptions, then re-raise unchanged
                logger.warning(
                    "Non-database exception during surprise update, rolling back: %s: %s",
                    type(e).__name__,
                    e,
                )
                cursor.execute("ROLLBACK")
                raise

        return updated_surprise

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def update_outcome_async(
        self: ContinuumMemory,
        id: str,
        success: bool,
        agent_prediction_error: float | None = None,
    ) -> float:
        """Async wrapper for update_outcome() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.update_outcome(id, success, agent_prediction_error),
        )

    def get_learning_rate(self: ContinuumMemory, tier: MemoryTier, update_count: int) -> float:
        """
        Get tier-specific learning rate with decay.

        HOPE-inspired: fast tiers have high initial LR with rapid decay,
        slow tiers have low initial LR with gradual decay.
        """
        config: TierConfig = TIER_CONFIGS[tier]
        return config.base_learning_rate * (config.decay_rate**update_count)

    def create_pattern_feedback_hook(
        self: ContinuumMemory,
    ) -> Any:
        """Create a hook that feeds outcome data back to pattern confidence.

        When a memory in SLOW or GLACIAL tier accumulates enough observations,
        the outcome data is captured as pattern feedback. This enables
        PatternBridge and CultureAccumulator to adjust pattern confidence
        based on real-world outcome tracking.

        Returns:
            Callable hook suitable for register_post_outcome_hook().
        """
        feedback_log: list[dict[str, Any]] = []

        def _pattern_feedback_hook(outcome_data: dict[str, Any]) -> None:
            tier = outcome_data.get("tier", "")
            total_obs = outcome_data.get("total_observations", 0)

            # Only generate feedback for well-established memories
            if tier not in ("slow", "glacial") or total_obs < 10:
                return

            memory_id = outcome_data["id"]
            success = outcome_data["success"]
            surprise = outcome_data.get("surprise_score", 0.0)

            # Look up pattern_id from memory metadata
            pattern_id = None
            try:
                with self.connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT metadata FROM continuum_memory WHERE id = ?",
                        (memory_id,),
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        import json

                        meta = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                        pattern_id = meta.get("pattern_id")
            except (OSError, KeyError, ValueError):
                logger.debug(
                    "Non-critical metadata lookup failure for memory %s", memory_id, exc_info=True
                )

            feedback_entry = {
                "memory_id": memory_id,
                "pattern_id": pattern_id,
                "success": success,
                "surprise_score": surprise,
                "tier": tier,
                "total_observations": total_obs,
                "timestamp": datetime.now().isoformat(),
            }

            feedback_log.append(feedback_entry)

            logger.debug(
                "Pattern feedback: memory=%s pattern=%s success=%s surprise=%.3f obs=%d",
                memory_id,
                pattern_id,
                success,
                surprise,
                total_obs,
            )

        # Attach the log to the hook for external access
        _pattern_feedback_hook.feedback_log = feedback_log  # type: ignore[attr-defined]
        return _pattern_feedback_hook

    def get_pattern_feedback(self: ContinuumMemory) -> list[dict[str, Any]]:
        """Get accumulated pattern feedback from all registered feedback hooks.

        Returns:
            List of pattern feedback entries from outcome observations.
        """
        feedback: list[dict[str, Any]] = []
        if not self._post_outcome_hooks:
            return feedback

        for hook in self._post_outcome_hooks:
            log = getattr(hook, "feedback_log", None)
            if log:
                feedback.extend(log)

        return feedback


__all__ = ["OutcomeMixin"]
