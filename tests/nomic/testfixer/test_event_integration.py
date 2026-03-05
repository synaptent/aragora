"""
Tests for TestFixer → Nomic Loop event integration.

Verifies:
1. Orchestrator emits events at key points
2. TestFixerHandlersMixin accumulates and processes events
3. Failures flow to MetaPlanner for prioritization
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from aragora.events.types import StreamEvent, StreamEventType


class TestOrchestratorEventEmission:
    """Tests for event emission from TestFixerOrchestrator."""

    @pytest.fixture
    def mock_event_emitter(self):
        """Create a mock event emitter that collects events."""
        events = []

        async def collect_event(event: StreamEvent):
            events.append(event)

        collect_event.events = events
        return collect_event

    @pytest.fixture
    def orchestrator_with_emitter(self, mock_event_emitter, tmp_path):
        """Create orchestrator with event emitter."""
        from aragora.nomic.testfixer.orchestrator import (
            TestFixerOrchestrator,
            FixLoopConfig,
        )

        return TestFixerOrchestrator(
            repo_path=tmp_path,
            test_command="pytest tests/ -q",
            config=FixLoopConfig(max_iterations=2),
            event_emitter=mock_event_emitter,
        )

    @pytest.mark.asyncio
    async def test_emit_event_with_async_emitter(
        self, orchestrator_with_emitter, mock_event_emitter
    ):
        """Test that _emit_event works with async emitter."""
        await orchestrator_with_emitter._emit_event(
            StreamEventType.TESTFIXER_FAILURE_DETECTED,
            {"test_name": "test_example", "error_type": "AssertionError"},
        )

        assert len(mock_event_emitter.events) == 1
        event = mock_event_emitter.events[0]
        assert event.type == StreamEventType.TESTFIXER_FAILURE_DETECTED
        assert event.data["test_name"] == "test_example"
        assert event.data["run_id"] == orchestrator_with_emitter.run_id

    @pytest.mark.asyncio
    async def test_emit_event_with_sync_emitter(self, tmp_path):
        """Test that _emit_event works with sync emitter."""
        from aragora.nomic.testfixer.orchestrator import (
            TestFixerOrchestrator,
            FixLoopConfig,
        )

        events = []

        def sync_emitter(event: StreamEvent):
            events.append(event)

        orchestrator = TestFixerOrchestrator(
            repo_path=tmp_path,
            test_command="pytest",
            config=FixLoopConfig(max_iterations=1),
            event_emitter=sync_emitter,
        )

        await orchestrator._emit_event(
            StreamEventType.TESTFIXER_LOOP_COMPLETE,
            {"status": "success"},
        )

        assert len(events) == 1
        assert events[0].type == StreamEventType.TESTFIXER_LOOP_COMPLETE

    @pytest.mark.asyncio
    async def test_emit_event_no_emitter(self, tmp_path):
        """Test that _emit_event handles no emitter gracefully."""
        from aragora.nomic.testfixer.orchestrator import (
            TestFixerOrchestrator,
            FixLoopConfig,
        )

        orchestrator = TestFixerOrchestrator(
            repo_path=tmp_path,
            test_command="pytest",
            config=FixLoopConfig(max_iterations=1),
            # No event_emitter
        )

        # Should not raise
        await orchestrator._emit_event(
            StreamEventType.TESTFIXER_FAILURE_DETECTED,
            {"test_name": "test_example"},
        )

    @pytest.mark.asyncio
    async def test_emit_event_handles_emitter_error(self, tmp_path):
        """Test that _emit_event handles emitter errors gracefully."""
        from aragora.nomic.testfixer.orchestrator import (
            TestFixerOrchestrator,
            FixLoopConfig,
        )

        def failing_emitter(event: StreamEvent):
            raise RuntimeError("Emitter failed")

        orchestrator = TestFixerOrchestrator(
            repo_path=tmp_path,
            test_command="pytest",
            config=FixLoopConfig(max_iterations=1),
            event_emitter=failing_emitter,
        )

        # Should not raise, just log
        await orchestrator._emit_event(
            StreamEventType.TESTFIXER_FAILURE_DETECTED,
            {"test_name": "test_example"},
        )


class TestTestFixerHandlersMixin:
    """Tests for TestFixerHandlersMixin event handlers."""

    @pytest.fixture
    def mock_handler_class(self):
        """Create a mock class that includes the mixin."""
        from aragora.events.subscribers.testfixer_handlers import TestFixerHandlersMixin

        class MockHandler(TestFixerHandlersMixin):
            def __init__(self):
                self.stats = {}
                self.retry_handler = MagicMock()
                self.circuit_breaker = MagicMock()

            def _is_km_handler_enabled(self, handler_name: str) -> bool:
                return True

        return MockHandler()

    def test_handle_failure_detected_accumulates(self, mock_handler_class):
        """Test that failure detected events are accumulated."""
        event = StreamEvent(
            type=StreamEventType.TESTFIXER_FAILURE_DETECTED,
            data={
                "run_id": "run-001",
                "test_name": "test_example",
                "test_file": "tests/test_example.py",
                "error_type": "AssertionError",
                "error_message": "Expected True but got False",
                "timestamp": datetime.now().isoformat(),
            },
        )

        mock_handler_class._handle_testfixer_failure_detected(event)

        accumulator = mock_handler_class._get_testfixer_accumulator()
        assert len(accumulator.failures) == 1
        assert accumulator.failures[0]["test_name"] == "test_example"
        assert mock_handler_class.stats["testfixer_to_planner"]["events"] == 1

    def test_handle_failure_detected_auto_flush(self, mock_handler_class):
        """Test that failures auto-flush when batch limit reached."""
        accumulator = mock_handler_class._get_testfixer_accumulator()
        accumulator.max_failures = 3

        # Add failures up to the limit
        for i in range(3):
            event = StreamEvent(
                type=StreamEventType.TESTFIXER_FAILURE_DETECTED,
                data={
                    "run_id": "run-001",
                    "test_name": f"test_{i}",
                    "test_file": f"tests/test_{i}.py",
                    "error_type": "AssertionError",
                },
            )
            mock_handler_class._handle_testfixer_failure_detected(event)

        # After reaching limit, should have flushed
        assert len(accumulator.failures) == 0

    def test_handle_loop_complete_stores_patterns(self, mock_handler_class):
        """Test that loop complete stores patterns."""
        event = StreamEvent(
            type=StreamEventType.TESTFIXER_LOOP_COMPLETE,
            data={
                "run_id": "run-001",
                "status": "max_iterations",
                "failed_patterns": [
                    {"category": "assertion", "fix_target": "source", "diff": "..."},
                ],
                "successful_patterns": [
                    {"category": "import", "fix_target": "source", "diff": "..."},
                ],
            },
        )

        mock_handler_class._handle_testfixer_loop_complete(event)

        assert mock_handler_class.stats["testfixer_loop_complete"]["events"] == 1
        assert mock_handler_class.stats["testfixer_patterns_learned"]["total"] == 2
        assert mock_handler_class.stats["testfixer_patterns_learned"]["successful"] == 1
        assert mock_handler_class.stats["testfixer_patterns_learned"]["failed"] == 1

    def test_flush_failures_to_planner(self, mock_handler_class):
        """Test that failures are formatted and flushed to planner."""
        from aragora.nomic.improvement_queue import get_improvement_queue

        queue = get_improvement_queue()
        queue.dequeue_batch(1000)  # clear prior test residue

        accumulator = mock_handler_class._get_testfixer_accumulator()
        accumulator.failures = [
            {
                "run_id": "run-001",
                "test_name": "test_example",
                "test_file": "tests/test_example.py",
                "error_type": "AssertionError",
                "error_message": "Expected True",
            },
            {
                "run_id": "run-001",
                "test_name": "test_other",
                "test_file": "tests/test_other.py",
                "error_type": "TypeError",
                "error_message": "Cannot call None",
            },
        ]

        mock_handler_class._flush_failures_to_planner()

        # Failures should be cleared after flush
        assert len(accumulator.failures) == 0
        queued = queue.dequeue_batch(10)
        assert len(queued) == 2
        assert all(item.source_system == "testfixer" for item in queued)
        assert all(item.category == "reliability" for item in queued)

    def test_register_handlers(self, mock_handler_class):
        """Test that handlers can be registered with a dispatcher."""
        mock_dispatcher = MagicMock()
        mock_dispatcher.subscribe = MagicMock()

        mock_handler_class.register_testfixer_handlers(mock_dispatcher)

        # Should register 2 handlers
        assert mock_dispatcher.subscribe.call_count == 2
        call_args = [call[0][0] for call in mock_dispatcher.subscribe.call_args_list]
        assert StreamEventType.TESTFIXER_FAILURE_DETECTED in call_args
        assert StreamEventType.TESTFIXER_LOOP_COMPLETE in call_args


class TestEventTypes:
    """Tests for TestFixer event types."""

    def test_all_testfixer_event_types_exist(self):
        """Test that all expected testfixer event types are defined."""
        expected_types = [
            "TESTFIXER_FAILURE_DETECTED",
            "TESTFIXER_ANALYSIS_COMPLETE",
            "TESTFIXER_FIX_PROPOSED",
            "TESTFIXER_FIX_APPLIED",
            "TESTFIXER_FIX_REVERTED",
            "TESTFIXER_ITERATION_COMPLETE",
            "TESTFIXER_LOOP_COMPLETE",
            "TESTFIXER_PATTERN_LEARNED",
        ]

        for type_name in expected_types:
            assert hasattr(StreamEventType, type_name), f"Missing event type: {type_name}"

    def test_event_type_values_are_snake_case(self):
        """Test that event type values follow naming convention."""
        testfixer_types = [t for t in StreamEventType if t.name.startswith("TESTFIXER_")]

        for event_type in testfixer_types:
            assert event_type.value.startswith("testfixer_")
            assert event_type.value == event_type.value.lower()


class TestEndToEndFlow:
    """Tests for end-to-end event flow."""

    @pytest.mark.asyncio
    async def test_orchestrator_to_handler_flow(self, tmp_path):
        """Test events flow from orchestrator to handler."""
        from aragora.nomic.testfixer.orchestrator import (
            TestFixerOrchestrator,
            FixLoopConfig,
        )
        from aragora.events.subscribers.testfixer_handlers import TestFixerHandlersMixin

        # Create handler
        class TestHandler(TestFixerHandlersMixin):
            def __init__(self):
                self.stats = {}
                self.retry_handler = MagicMock()
                self.circuit_breaker = MagicMock()

            def _is_km_handler_enabled(self, handler_name: str) -> bool:
                return True

        handler = TestHandler()

        # Create emitter that routes to handler
        def route_to_handler(event: StreamEvent):
            if event.type == StreamEventType.TESTFIXER_FAILURE_DETECTED:
                handler._handle_testfixer_failure_detected(event)
            elif event.type == StreamEventType.TESTFIXER_LOOP_COMPLETE:
                handler._handle_testfixer_loop_complete(event)

        orchestrator = TestFixerOrchestrator(
            repo_path=tmp_path,
            test_command="pytest",
            config=FixLoopConfig(max_iterations=1),
            event_emitter=route_to_handler,
        )

        # Emit events
        await orchestrator._emit_event(
            StreamEventType.TESTFIXER_FAILURE_DETECTED,
            {
                "test_name": "test_foo",
                "test_file": "tests/test_foo.py",
                "error_type": "AssertionError",
            },
        )
        await orchestrator._emit_event(
            StreamEventType.TESTFIXER_LOOP_COMPLETE,
            {
                "status": "max_iterations",
                "failed_patterns": [],
                "successful_patterns": [],
            },
        )

        # Verify handler received events
        assert handler.stats["testfixer_to_planner"]["events"] == 1
        assert handler.stats["testfixer_loop_complete"]["events"] == 1

    @pytest.mark.asyncio
    async def test_meta_planner_context_with_failures(self):
        """Test that PlanningContext accepts test failures."""
        from aragora.nomic.meta_planner import PlanningContext

        context = PlanningContext(
            test_failures=[
                "tests/test_auth.py::test_login (AssertionError): Expected success",
                "tests/test_api.py::test_get_user (TypeError): None is not callable",
            ],
        )

        assert len(context.test_failures) == 2
        assert "test_login" in context.test_failures[0]
        assert "test_get_user" in context.test_failures[1]
