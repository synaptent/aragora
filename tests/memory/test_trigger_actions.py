"""Tests for memory trigger action implementations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.memory.triggers import (
    MemoryTriggerEngine,
    _create_debate_topic,
    _extract_pattern,
    _log_high_surprise,
    _mark_for_revalidation,
    _merge_summaries,
)


class TestHighSurpriseAction:
    """Tests for _log_high_surprise trigger action."""

    @pytest.mark.asyncio
    async def test_reports_to_anomaly_detector(self):
        mock_detector = MagicMock()
        with patch(
            "aragora.security.anomaly_detection.get_anomaly_detector",
            return_value=mock_detector,
        ):
            await _log_high_surprise(
                {
                    "item_id": "km_1",
                    "surprise": 0.85,
                    "content_preview": "test content",
                }
            )
        mock_detector._emit_anomaly_event.assert_called_once()
        anomaly_result = mock_detector._emit_anomaly_event.call_args[0][0]
        assert anomaly_result.details["source"] == "memory"
        assert anomaly_result.severity.value == "medium"

    @pytest.mark.asyncio
    async def test_high_severity_above_09(self):
        mock_detector = MagicMock()
        with patch(
            "aragora.security.anomaly_detection.get_anomaly_detector",
            return_value=mock_detector,
        ):
            await _log_high_surprise({"item_id": "km_1", "surprise": 0.95})
        anomaly_result = mock_detector._emit_anomaly_event.call_args[0][0]
        assert anomaly_result.severity.value == "high"

    @pytest.mark.asyncio
    async def test_dispatches_event(self):
        with (
            patch(
                "aragora.security.anomaly_detection.get_anomaly_detector",
                side_effect=ImportError,
            ),
            patch(
                "aragora.events.dispatcher.dispatch_event",
            ) as mock_dispatch,
        ):
            await _log_high_surprise(
                {
                    "item_id": "km_1",
                    "surprise": 0.8,
                    "source": "mound",
                }
            )
        mock_dispatch.assert_called_once_with(
            "memory.high_surprise",
            {"item_id": "km_1", "surprise": 0.8, "source": "mound"},
        )

    @pytest.mark.asyncio
    async def test_graceful_on_import_error(self):
        with patch.dict(
            "sys.modules",
            {
                "aragora.security.anomaly_detection": None,
                "aragora.events.dispatcher": None,
            },
        ):
            # Should not raise
            await _log_high_surprise({"item_id": "km_1", "surprise": 0.9})


class TestRevalidationAction:
    """Tests for _mark_for_revalidation trigger action."""

    @pytest.mark.asyncio
    async def test_applies_confidence_decay(self):
        mock_manager = MagicMock()
        mock_manager.apply_decay = AsyncMock()
        mock_mound = MagicMock()
        with (
            patch(
                "aragora.knowledge.mound.ops.confidence_decay.get_decay_manager",
                return_value=mock_manager,
            ),
            patch(
                "aragora.knowledge.mound.get_knowledge_mound",
                return_value=mock_mound,
            ),
        ):
            await _mark_for_revalidation(
                {
                    "item_id": "km_2",
                    "days_since_access": 14,
                    "confidence": 0.3,
                }
            )
        mock_manager.apply_decay.assert_called_once_with(
            mock_mound,
            "default",
            force=True,
        )

    @pytest.mark.asyncio
    async def test_dispatches_event(self):
        with (
            patch(
                "aragora.knowledge.mound.ops.confidence_decay.get_decay_manager",
                side_effect=ImportError,
            ),
            patch(
                "aragora.events.dispatcher.dispatch_event",
            ) as mock_dispatch,
        ):
            await _mark_for_revalidation(
                {
                    "item_id": "km_2",
                    "days_since_access": 14,
                    "confidence": 0.3,
                }
            )
        mock_dispatch.assert_called_once_with(
            "memory.stale_revalidation",
            {"item_id": "km_2", "days_since_access": 14, "confidence": 0.3},
        )

    @pytest.mark.asyncio
    async def test_graceful_on_import_error(self):
        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge.mound.ops.confidence_decay": None,
                "aragora.events.dispatcher": None,
            },
        ):
            await _mark_for_revalidation({"item_id": "km_2"})


class TestContradictionAction:
    """Tests for _create_debate_topic trigger action."""

    @pytest.mark.asyncio
    async def test_enqueues_improvement_suggestion(self):
        mock_queue = MagicMock()
        with patch(
            "aragora.learning.improvement_queue.get_improvement_queue",
            return_value=mock_queue,
        ):
            await _create_debate_topic(
                {
                    "description": "Claim A contradicts Claim B",
                }
            )
        mock_queue.enqueue.assert_called_once()
        suggestion = mock_queue.enqueue.call_args[0][0]
        assert "contradiction" in suggestion.category.lower()
        assert "Claim A" in suggestion.task

    @pytest.mark.asyncio
    async def test_dispatches_event(self):
        with (
            patch(
                "aragora.learning.improvement_queue.get_improvement_queue",
                side_effect=ImportError,
            ),
            patch(
                "aragora.events.dispatcher.dispatch_event",
            ) as mock_dispatch,
        ):
            await _create_debate_topic({"description": "test conflict"})
        mock_dispatch.assert_called_once_with(
            "memory.contradiction_detected",
            {"description": "test conflict"},
        )

    @pytest.mark.asyncio
    async def test_graceful_on_import_error(self):
        with patch.dict(
            "sys.modules",
            {
                "aragora.learning.improvement_queue": None,
                "aragora.events.dispatcher": None,
            },
        ):
            await _create_debate_topic({"description": "test"})


class TestConsolidationAction:
    """Tests for _merge_summaries trigger action."""

    @pytest.mark.asyncio
    async def test_dispatches_event(self):
        with patch(
            "aragora.events.dispatcher.dispatch_event",
        ) as mock_dispatch:
            await _merge_summaries({"item_count": 5, "avg_surprise": 0.1})
        mock_dispatch.assert_called_once_with(
            "memory.consolidation_merge",
            {"item_count": 5, "avg_surprise": 0.1},
        )

    @pytest.mark.asyncio
    async def test_graceful_on_import_error(self):
        with patch.dict("sys.modules", {"aragora.events.dispatcher": None}):
            await _merge_summaries({"item_count": 3})


class TestPatternAction:
    """Tests for _extract_pattern trigger action."""

    @pytest.mark.asyncio
    async def test_dispatches_event(self):
        with patch(
            "aragora.events.dispatcher.dispatch_event",
        ) as mock_dispatch:
            await _extract_pattern(
                {
                    "pattern": "repeated fix in auth module",
                    "surprise_ema_trend": "decreasing",
                }
            )
        mock_dispatch.assert_called_once_with(
            "memory.pattern_emerged",
            {"pattern": "repeated fix in auth module", "trend": "decreasing"},
        )

    @pytest.mark.asyncio
    async def test_graceful_on_import_error(self):
        with patch.dict("sys.modules", {"aragora.events.dispatcher": None}):
            await _extract_pattern({"pattern": "test"})


class TestTriggerEngineIntegration:
    """Integration tests for the full trigger engine with real actions."""

    @pytest.mark.asyncio
    async def test_high_surprise_fires_full_action(self):
        engine = MemoryTriggerEngine()
        mock_detector = MagicMock()

        with (
            patch(
                "aragora.security.anomaly_detection.get_anomaly_detector",
                return_value=mock_detector,
            ),
            patch("aragora.events.dispatcher.dispatch_event"),
        ):
            triggered = await engine.fire(
                "high_surprise",
                {
                    "item_id": "km_99",
                    "surprise": 0.85,
                },
            )

        assert "high_surprise_investigate" in triggered
        mock_detector._emit_anomaly_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_contradiction_fires_full_action(self):
        engine = MemoryTriggerEngine()
        mock_queue = MagicMock()

        with (
            patch(
                "aragora.learning.improvement_queue.get_improvement_queue",
                return_value=mock_queue,
            ),
            patch("aragora.events.dispatcher.dispatch_event"),
        ):
            triggered = await engine.fire(
                "contradiction",
                {
                    "description": "A contradicts B",
                },
            )

        assert "contradiction_detected" in triggered
        mock_queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_knowledge_fires_decay(self):
        engine = MemoryTriggerEngine()
        mock_manager = MagicMock()
        mock_manager.apply_decay = AsyncMock()

        with (
            patch(
                "aragora.knowledge.mound.ops.confidence_decay.get_decay_manager",
                return_value=mock_manager,
            ),
            patch("aragora.events.dispatcher.dispatch_event"),
        ):
            triggered = await engine.fire(
                "stale_knowledge",
                {
                    "item_id": "km_old",
                    "days_since_access": 14,
                    "confidence": 0.3,
                },
            )

        assert "stale_knowledge_revalidate" in triggered
        mock_manager.apply_decay.assert_called_once()
