"""
TestFixer event handler mixin for CrossSubscriberManager.

Handles event flow from TestFixer to Nomic Loop:
- TESTFIXER_FAILURE_DETECTED → MetaPlanner: Queue failures for prioritization
- TESTFIXER_LOOP_COMPLETE → MetaPlanner: Batch submit patterns for debate
- TESTFIXER_PATTERN_LEARNED → KnowledgeMound: Store learned patterns
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.events.types import StreamEvent, StreamEventType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class TestFailureAccumulator:
    """Accumulates test failures for batch submission to MetaPlanner."""

    failures: list[dict[str, Any]] = field(default_factory=list)
    patterns: list[dict[str, Any]] = field(default_factory=list)
    last_flush: datetime = field(default_factory=datetime.now)
    max_failures: int = 50  # Batch limit before auto-flush


class TestFixerHandlersMixin:
    """Mixin providing TestFixer event handlers.

    This mixin requires the implementing class to provide:
    - stats: dict - Handler statistics tracking
    - retry_handler: Any - Retry logic handler
    - circuit_breaker: Any - Circuit breaker for failure protection
    - _is_km_handler_enabled(handler_name: str) -> bool - Feature flag check
    """

    # Type annotations for required attributes from the implementing class
    stats: dict
    retry_handler: Any
    circuit_breaker: Any

    # Required method from parent class - checks feature flags
    _is_km_handler_enabled: Callable[[str], bool]

    # Internal accumulator for failures
    _testfixer_accumulator: TestFailureAccumulator | None = None

    def _get_testfixer_accumulator(self) -> TestFailureAccumulator:
        """Get or create the failure accumulator."""
        if self._testfixer_accumulator is None:
            self._testfixer_accumulator = TestFailureAccumulator()
        return self._testfixer_accumulator

    def _handle_testfixer_failure_detected(self, event: StreamEvent) -> None:
        """Handle TESTFIXER_FAILURE_DETECTED events.

        Accumulates failures for batch submission to MetaPlanner.
        """
        _check_and_record_slo: Callable[[str, float, str], Any] | None = None
        try:
            from aragora.observability.metrics.slo import check_and_record_slo as _slo_fn

            _check_and_record_slo = _slo_fn
        except ImportError:
            pass

        start = time.time()

        try:
            data = event.data
            run_id = data.get("run_id")
            test_name = data.get("test_name")
            test_file = data.get("test_file")
            error_type = data.get("error_type")
            error_message = data.get("error_message")

            if not test_name:
                logger.warning("TestFixer → MetaPlanner: Missing test_name")
                return

            accumulator = self._get_testfixer_accumulator()
            accumulator.failures.append(
                {
                    "run_id": run_id,
                    "test_name": test_name,
                    "test_file": test_file,
                    "error_type": error_type,
                    "error_message": error_message,
                    "timestamp": data.get("timestamp"),
                }
            )

            # Stats tracking
            if "testfixer_to_planner" not in self.stats:
                self.stats["testfixer_to_planner"] = {"events": 0, "errors": 0, "latency_ms": []}
            self.stats["testfixer_to_planner"]["events"] += 1

            # Auto-flush if at batch limit
            if len(accumulator.failures) >= accumulator.max_failures:
                self._flush_failures_to_planner()

            logger.debug(
                f"TestFixer failure accumulated: {test_name} (total: {len(accumulator.failures)})"
            )

            if _check_and_record_slo:
                _check_and_record_slo(
                    "testfixer_failure_detected",
                    (time.time() - start) * 1000,
                    "success",
                )

        except (KeyError, TypeError, AttributeError, ValueError) as e:
            logger.warning("TestFixer → MetaPlanner accumulation failed: %s", e)
            if "testfixer_to_planner" in self.stats:
                self.stats["testfixer_to_planner"]["errors"] += 1

    def _handle_testfixer_loop_complete(self, event: StreamEvent) -> None:
        """Handle TESTFIXER_LOOP_COMPLETE events.

        Submits accumulated patterns to MetaPlanner for debate prioritization.
        """
        _check_and_record_slo: Callable[[str, float, str], Any] | None = None
        try:
            from aragora.observability.metrics.slo import check_and_record_slo as _slo_fn

            _check_and_record_slo = _slo_fn
        except ImportError:
            pass

        start = time.time()

        try:
            data = event.data
            run_id = data.get("run_id")
            status = data.get("status")
            failed_patterns = data.get("failed_patterns", [])
            successful_patterns = data.get("successful_patterns", [])

            # Store patterns for learning
            accumulator = self._get_testfixer_accumulator()
            for pattern in failed_patterns:
                accumulator.patterns.append(
                    {
                        "run_id": run_id,
                        "success": False,
                        **pattern,
                    }
                )
            for pattern in successful_patterns:
                accumulator.patterns.append(
                    {
                        "run_id": run_id,
                        "success": True,
                        **pattern,
                    }
                )

            # Stats tracking
            if "testfixer_loop_complete" not in self.stats:
                self.stats["testfixer_loop_complete"] = {"events": 0, "errors": 0, "latency_ms": []}
            self.stats["testfixer_loop_complete"]["events"] += 1

            # Flush accumulated failures to MetaPlanner
            if status != "success":
                self._flush_failures_to_planner()

            # Submit patterns for learning
            if accumulator.patterns:
                self._submit_patterns_to_km(accumulator.patterns)
                accumulator.patterns = []

            logger.info(
                f"TestFixer loop complete: status={status}, "
                f"failed_patterns={len(failed_patterns)}, "
                f"successful_patterns={len(successful_patterns)}"
            )

            if _check_and_record_slo:
                _check_and_record_slo(
                    "testfixer_loop_complete",
                    (time.time() - start) * 1000,
                    "success",
                )

        except (KeyError, TypeError, AttributeError, ValueError) as e:
            logger.warning("TestFixer loop complete handling failed: %s", e)
            if "testfixer_loop_complete" in self.stats:
                self.stats["testfixer_loop_complete"]["errors"] += 1

    def _flush_failures_to_planner(self) -> None:
        """Flush accumulated failures to the improvement queue.

        Creates ImprovementSuggestion entries from test failures and
        enqueues them for the MetaPlanner to consume in the next
        planning cycle.
        """
        accumulator = self._get_testfixer_accumulator()
        if not accumulator.failures:
            return

        try:
            from aragora.nomic.improvement_queue import (
                ImprovementSuggestion,
                get_improvement_queue,
            )

            queue = get_improvement_queue()
            enqueued = 0

            for f in accumulator.failures:
                desc = f"{f['test_file']}::{f['test_name']}"
                if f.get("error_type"):
                    desc += f" ({f['error_type']})"
                if f.get("error_message"):
                    msg = f["error_message"][:200]
                    desc += f": {msg}"

                suggestion = ImprovementSuggestion(
                    debate_id="",
                    task=f"Fix test failure: {f['test_file']}::{f['test_name']}",
                    suggestion=desc,
                    category="reliability",
                    confidence=0.8,
                    source_system="testfixer",
                    source_id=f.get("run_id", ""),
                    files=[f["test_file"]] + f.get("source_files", []),
                )
                queue.enqueue(suggestion)
                enqueued += 1

            logger.info("Enqueued %d test failure suggestions to improvement queue", enqueued)

        except ImportError:
            logger.debug("Improvement queue not available for test failure submission")
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.warning("Failed to enqueue test failures: %s", e)
        finally:
            # Clear accumulator after flush attempt
            accumulator.failures = []
            accumulator.last_flush = datetime.now()

    def _submit_patterns_to_km(self, patterns: list[dict[str, Any]]) -> None:
        """Submit learned patterns to Knowledge Mound.

        Stores successful and failed fix patterns for future reference.
        """
        if not patterns:
            return

        try:
            from aragora.knowledge.mound.core import KnowledgeMound  # noqa: F401

            # Format patterns for KM ingestion
            for pattern in patterns:
                # Emit as TESTFIXER_PATTERN_LEARNED event for async processing
                logger.debug(
                    f"Pattern learned: {pattern.get('category')} -> "
                    f"{'success' if pattern.get('success') else 'failure'}"
                )

            # Stats tracking
            if "testfixer_patterns_learned" not in self.stats:
                self.stats["testfixer_patterns_learned"] = {
                    "total": 0,
                    "successful": 0,
                    "failed": 0,
                }

            for pattern in patterns:
                self.stats["testfixer_patterns_learned"]["total"] += 1
                if pattern.get("success"):
                    self.stats["testfixer_patterns_learned"]["successful"] += 1
                else:
                    self.stats["testfixer_patterns_learned"]["failed"] += 1

        except ImportError:
            logger.debug("KnowledgeMound not available for pattern storage")
        except (RuntimeError, TypeError, AttributeError, ValueError, OSError) as e:
            logger.warning("Failed to submit patterns to KM: %s", e)

    def register_testfixer_handlers(self, dispatcher: Any) -> None:
        """Register TestFixer event handlers with the dispatcher.

        Args:
            dispatcher: Event dispatcher to register with
        """
        handlers = {
            StreamEventType.TESTFIXER_FAILURE_DETECTED: self._handle_testfixer_failure_detected,
            StreamEventType.TESTFIXER_LOOP_COMPLETE: self._handle_testfixer_loop_complete,
        }

        for event_type, handler in handlers.items():
            try:
                dispatcher.subscribe(event_type, handler)
                logger.debug("Registered TestFixer handler for %s", event_type.value)
            except (RuntimeError, TypeError, AttributeError, ValueError) as e:
                logger.warning("Failed to register handler for %s: %s", event_type, e)
