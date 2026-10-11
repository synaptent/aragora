"""Training data emission for fine-tuning integration.

This module extracts training data generation from FeedbackPhase:
- SFT (Supervised Fine-Tuning) records
- DPO (Direct Preference Optimization) preference pairs
- Calibration data from prediction accuracy

Used for Tinker integration and model fine-tuning pipelines.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)


class TrainingEmitter:
    """Handles training data generation and export.

    Extracted from FeedbackPhase to improve modularity and enable
    reuse in other contexts (e.g., batch exports, gauntlet runs).
    """

    def __init__(
        self,
        *,
        training_exporter: Callable[..., Any] | None = None,
        event_emitter: Any = None,
        insight_store: Any = None,
        loop_id: str | None = None,
        # Thresholds
        sft_confidence_threshold: float = 0.8,
        min_response_length: int = 50,
        max_response_length: int = 4000,
    ) -> None:
        """Initialize the training emitter.

        Args:
            training_exporter: Callback to export training records
            event_emitter: Event emitter for WebSocket notifications
            insight_store: Insight store for recording usage
            loop_id: Current loop ID for event emission
            sft_confidence_threshold: Minimum confidence for SFT export
            min_response_length: Minimum response length for DPO pairs
            max_response_length: Maximum response length to export
        """
        self.training_exporter = training_exporter
        self.event_emitter = event_emitter
        self.insight_store = insight_store
        self.loop_id = loop_id

        self.sft_confidence_threshold = sft_confidence_threshold
        self.min_response_length = min_response_length
        self.max_response_length = max_response_length

    async def record_insight_usage(self, ctx: DebateContext) -> None:
        """Record insight usage to complete the insight application cycle.

        When insights were injected into this debate (tracked via ctx.applied_insight_ids),
        this method records whether the debate was successful.

        Args:
            ctx: Debate context with result and applied insight IDs
        """
        if not self.insight_store:
            return

        applied_ids = getattr(ctx, "applied_insight_ids", [])
        if not applied_ids:
            return

        result = ctx.result
        if not result:
            return

        was_successful = result.consensus_reached and result.confidence >= 0.7

        if not result.consensus_reached:
            logger.debug(
                "[insight] Skipping usage record - no consensus reached for %d insights",
                len(applied_ids),
            )
            return

        try:
            for insight_id in applied_ids:
                await self.insight_store.record_insight_usage(
                    insight_id=insight_id,
                    debate_id=ctx.debate_id,
                    was_successful=was_successful,
                )

            logger.info(
                "[insight] Recorded usage for %d insights (success=%s) in debate %s",
                len(applied_ids),
                was_successful,
                ctx.debate_id[:8],
            )
        except (
            TypeError,
            ValueError,
            AttributeError,
            KeyError,
            OSError,
            ConnectionError,
            RuntimeError,
        ) as e:
            logger.debug("[insight] Usage recording failed: %s", e)

    async def emit_training_data(self, ctx: DebateContext) -> None:
        """Emit training data for fine-tuning integration.

        Exports debate outcomes for model fine-tuning:
        1. SFT data from high-confidence winning debates
        2. DPO preference pairs from win/loss outcomes
        3. Calibration data from prediction accuracy

        Args:
            ctx: Debate context with result and votes
        """
        if not self.training_exporter:
            return

        result = ctx.result
        if not result or not result.final_answer:
            return

        try:
            training_records = []

            # 1. Export SFT data from high-confidence debates
            if result.confidence >= self.sft_confidence_threshold and result.consensus_reached:
                sft_record = self.build_sft_record(ctx)
                if sft_record:
                    training_records.append(sft_record)

            # 2. Export DPO preference pairs from votes
            dpo_records = self.build_dpo_records(ctx)
            training_records.extend(dpo_records)

            # 3. Export calibration data
            calibration_records = self.build_calibration_records(ctx)
            training_records.extend(calibration_records)

            if not training_records:
                return

            # Emit training data
            if asyncio.iscoroutinefunction(self.training_exporter):
                await self.training_exporter(training_records, ctx.debate_id)
            elif callable(self.training_exporter):
                self.training_exporter(training_records, ctx.debate_id)

            logger.info(
                "[training] Emitted %d training records for debate %s "
                "(sft=%d, dpo=%d, calibration=%d)",
                len(training_records),
                ctx.debate_id[:8],
                1 if result.confidence >= self.sft_confidence_threshold else 0,
                len(dpo_records),
                len(calibration_records),
            )

            # Emit event notification
            self._emit_training_event(ctx, len(training_records))

        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.debug("[training] Data emission failed: %s", e)

    def build_sft_record(self, ctx: DebateContext) -> dict[str, Any] | None:
        """Build SFT (Supervised Fine-Tuning) record from winning debate.

        Args:
            ctx: Debate context

        Returns:
            SFT training record or None if not suitable
        """
        result = ctx.result
        if result is None or not result.final_answer:
            return None

        instruction = f"Debate task: {ctx.env.task}"
        if hasattr(ctx.env, "context") and ctx.env.context:
            instruction += f"\n\nContext: {ctx.env.context[:500]}"

        response = result.final_answer

        return {
            "type": "sft",
            "instruction": instruction,
            "response": response[: self.max_response_length],
            "metadata": {
                "debate_id": ctx.debate_id,
                "domain": ctx.domain,
                "confidence": result.confidence,
                "rounds_used": result.rounds_used,
                "winner": result.winner,
                "participating_agents": [a.name for a in ctx.agents],
            },
        }

    def build_dpo_records(self, ctx: DebateContext) -> list[dict[str, Any]]:
        """Build DPO (Direct Preference Optimization) records from vote outcomes.

        Creates preference pairs where winner = chosen, loser = rejected.

        Args:
            ctx: Debate context

        Returns:
            List of DPO training records
        """
        result = ctx.result
        records: list[dict[str, Any]] = []

        if result is None or not result.winner or not result.messages:
            return records

        # Extract agent responses from messages
        agent_responses: dict[str, str] = {}
        for msg in result.messages:
            agent_name = getattr(msg, "agent", None)
            if not agent_name:
                continue
            content = getattr(msg, "content", str(msg))
            # Keep the most substantive response per agent
            if agent_name not in agent_responses or len(content) > len(agent_responses[agent_name]):
                agent_responses[agent_name] = content[:2000]

        if not agent_responses:
            return records

        winner_response = agent_responses.get(result.winner)
        if not winner_response:
            return records

        prompt = f"Debate task: {ctx.env.task}"

        for agent_name, response in agent_responses.items():
            if agent_name == result.winner:
                continue
            if not response or len(response) < self.min_response_length:
                continue

            records.append(
                {
                    "type": "dpo",
                    "prompt": prompt,
                    "chosen": winner_response,
                    "rejected": response,
                    "metadata": {
                        "debate_id": ctx.debate_id,
                        "domain": ctx.domain,
                        "winner": result.winner,
                        "loser": agent_name,
                        "confidence": result.confidence,
                    },
                }
            )

        return records

    def build_calibration_records(self, ctx: DebateContext) -> list[dict[str, Any]]:
        """Build calibration training records from prediction accuracy.

        Args:
            ctx: Debate context

        Returns:
            List of calibration training records
        """
        result = ctx.result
        records: list[dict[str, Any]] = []

        if result is None or not result.votes or not result.winner:
            return records

        for vote in result.votes:
            confidence = getattr(vote, "confidence", None)
            if confidence is None:
                continue

            canonical = ctx.choice_mapping.get(vote.choice, vote.choice)
            correct = canonical == result.winner

            records.append(
                {
                    "type": "calibration",
                    "agent": vote.agent,
                    "confidence": confidence,
                    "correct": correct,
                    "metadata": {
                        "debate_id": ctx.debate_id,
                        "domain": ctx.domain,
                        "choice": vote.choice,
                        "actual_winner": result.winner,
                    },
                }
            )

        return records

    def _emit_training_event(self, ctx: DebateContext, record_count: int) -> None:
        """Emit TRAINING_DATA_EXPORTED event to WebSocket."""
        if not self.event_emitter:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            if not hasattr(StreamEventType, "TRAINING_DATA_EXPORTED"):
                return

            self.event_emitter.emit(
                StreamEvent(
                    type=StreamEventType.TRAINING_DATA_EXPORTED,
                    loop_id=self.loop_id or "",
                    data={
                        "debate_id": ctx.debate_id,
                        "records_exported": record_count,
                        "domain": ctx.domain,
                        "confidence": ctx.result.confidence if ctx.result else 0.0,
                    },
                )
            )
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            logger.debug("Training event emission error: %s", e)


__all__ = ["TrainingEmitter"]
