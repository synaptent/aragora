"""Tests for the ImprovementQueue.

Validates that:
1. enqueue/dequeue round-trip works
2. max_size eviction works (queue is bounded)
3. thread safety (concurrent producers/consumers)
4. peek doesn't remove items
5. empty dequeue returns empty list
6. dequeue_batch returns correct count
7. get_improvement_queue returns singleton
8. ImprovementSuggestion has correct fields
"""

from __future__ import annotations

import threading
import time

import pytest

from aragora.nomic.improvement_queue import (
    ImprovementQueue,
    ImprovementSuggestion,
    get_improvement_queue,
)


def _make_suggestion(
    debate_id: str = "d1",
    task: str = "test task",
    suggestion: str = "test suggestion",
    category: str = "code_quality",
    confidence: float = 0.9,
) -> ImprovementSuggestion:
    return ImprovementSuggestion(
        debate_id=debate_id,
        task=task,
        suggestion=suggestion,
        category=category,
        confidence=confidence,
    )


class TestImprovementSuggestion:
    """Tests for ImprovementSuggestion dataclass."""

    def test_suggestion_fields(self):
        s = _make_suggestion()
        assert s.debate_id == "d1"
        assert s.task == "test task"
        assert s.suggestion == "test suggestion"
        assert s.category == "code_quality"
        assert s.confidence == 0.9

    def test_suggestion_created_at_auto(self):
        before = time.time()
        s = _make_suggestion()
        after = time.time()
        assert before <= s.created_at <= after

    def test_suggestion_created_at_override(self):
        s = ImprovementSuggestion(
            debate_id="d1",
            task="t",
            suggestion="s",
            category="c",
            confidence=0.5,
            created_at=1000.0,
        )
        assert s.created_at == 1000.0

    def test_provenance_fields_default(self):
        s = _make_suggestion()
        assert s.source_system == ""
        assert s.source_id == ""
        assert s.files == []
        assert s.gate_verdict == ""
        assert s.fidelity_score == -1.0

    def test_provenance_fields_set(self):
        s = ImprovementSuggestion(
            debate_id="d1",
            task="fix test",
            suggestion="test failure in auth",
            category="reliability",
            confidence=0.8,
            source_system="testfixer",
            source_id="run-abc123",
            files=["tests/test_auth.py", "aragora/auth/oidc.py"],
            gate_verdict="fail",
            fidelity_score=0.85,
        )
        assert s.source_system == "testfixer"
        assert s.source_id == "run-abc123"
        assert len(s.files) == 2
        assert s.gate_verdict == "fail"
        assert s.fidelity_score == 0.85

    def test_provenance_files_mutable_default(self):
        """Verify files list is not shared between instances."""
        s1 = _make_suggestion()
        s2 = _make_suggestion()
        s1.files.append("a.py")
        assert s2.files == []


class TestImprovementQueue:
    """Tests for ImprovementQueue."""

    def test_enqueue_dequeue_round_trip(self):
        queue = ImprovementQueue(max_size=10)
        s = _make_suggestion(debate_id="d1")
        queue.enqueue(s)
        batch = queue.dequeue_batch(1)
        assert len(batch) == 1
        assert batch[0].debate_id == "d1"

    def test_empty_dequeue_returns_empty_list(self):
        queue = ImprovementQueue()
        batch = queue.dequeue_batch(10)
        assert batch == []

    def test_dequeue_batch_correct_count(self):
        queue = ImprovementQueue()
        for i in range(5):
            queue.enqueue(_make_suggestion(debate_id=f"d{i}"))
        batch = queue.dequeue_batch(3)
        assert len(batch) == 3
        assert len(queue) == 2

    def test_dequeue_batch_less_than_requested(self):
        queue = ImprovementQueue()
        queue.enqueue(_make_suggestion(debate_id="d0"))
        queue.enqueue(_make_suggestion(debate_id="d1"))
        batch = queue.dequeue_batch(10)
        assert len(batch) == 2

    def test_max_size_eviction(self):
        queue = ImprovementQueue(max_size=3)
        for i in range(5):
            queue.enqueue(_make_suggestion(debate_id=f"d{i}"))
        assert len(queue) == 3
        batch = queue.dequeue_batch(10)
        # Oldest (d0, d1) should have been evicted
        assert [s.debate_id for s in batch] == ["d2", "d3", "d4"]

    def test_peek_does_not_remove(self):
        queue = ImprovementQueue()
        queue.enqueue(_make_suggestion(debate_id="d0"))
        queue.enqueue(_make_suggestion(debate_id="d1"))

        peeked = queue.peek(10)
        assert len(peeked) == 2
        assert len(queue) == 2  # Still there

        peeked_again = queue.peek(1)
        assert len(peeked_again) == 1
        assert peeked_again[0].debate_id == "d0"

    def test_peek_empty_queue(self):
        queue = ImprovementQueue()
        assert queue.peek(5) == []

    def test_len(self):
        queue = ImprovementQueue()
        assert len(queue) == 0
        queue.enqueue(_make_suggestion())
        assert len(queue) == 1
        queue.enqueue(_make_suggestion())
        assert len(queue) == 2
        queue.dequeue_batch(1)
        assert len(queue) == 1

    def test_fifo_order(self):
        queue = ImprovementQueue()
        for i in range(3):
            queue.enqueue(_make_suggestion(debate_id=f"d{i}"))
        batch = queue.dequeue_batch(3)
        assert [s.debate_id for s in batch] == ["d0", "d1", "d2"]


class TestThreadSafety:
    """Tests for concurrent access to ImprovementQueue."""

    def test_concurrent_enqueue(self):
        queue = ImprovementQueue(max_size=1000)
        errors = []

        def producer(start: int, count: int):
            try:
                for i in range(count):
                    queue.enqueue(_make_suggestion(debate_id=f"d{start + i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=producer, args=(i * 100, 100)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(queue) == 500

    def test_concurrent_enqueue_dequeue(self):
        queue = ImprovementQueue(max_size=1000)
        produced = []
        consumed = []
        errors = []

        def producer():
            try:
                for i in range(100):
                    s = _make_suggestion(debate_id=f"d{i}")
                    queue.enqueue(s)
                    produced.append(s)
                    time.sleep(0.0001)
            except Exception as e:
                errors.append(e)

        def consumer():
            try:
                for _ in range(50):
                    batch = queue.dequeue_batch(5)
                    consumed.extend(batch)
                    time.sleep(0.0002)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
        # All produced items should be either consumed or still in queue
        assert len(consumed) + len(queue) == len(produced)


class TestGetImprovementQueue:
    """Tests for the global singleton."""

    def test_returns_improvement_queue(self):
        queue = get_improvement_queue()
        assert isinstance(queue, ImprovementQueue)

    def test_returns_same_instance(self):
        q1 = get_improvement_queue()
        q2 = get_improvement_queue()
        assert q1 is q2
