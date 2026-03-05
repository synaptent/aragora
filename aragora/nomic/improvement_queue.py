"""Thread-safe improvement queue for debate-sourced suggestions.

Bridges the gap between debate outcomes and the self-improvement pipeline:
debates identify improvement opportunities, this queue buffers them for
the MetaPlanner to consume during the next planning cycle.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ImprovementSuggestion:
    """A debate-sourced improvement suggestion."""

    debate_id: str
    task: str
    suggestion: str
    category: str  # test_coverage, performance, reliability, code_quality, documentation
    confidence: float
    created_at: float = field(default_factory=time.time)
    # Provenance fields for bidirectional handoff tracking
    source_system: str = ""  # e.g. "pipeline", "testfixer", "debate", "nomic_loop"
    source_id: str = ""  # ID from the originating system (pipeline_id, run_id, etc.)
    files: list[str] = field(default_factory=list)  # affected file paths
    gate_verdict: str = ""  # quality gate result: "pass", "fail", "skip"
    fidelity_score: float = -1.0  # objective fidelity score (-1 = not measured)


class ImprovementQueue:
    """Thread-safe bounded queue for improvement suggestions.

    Provides a buffer between debate outcomes (producers) and the
    MetaPlanner (consumer). When the queue is full, the oldest
    suggestion is evicted to make room.

    Usage:
        queue = ImprovementQueue(max_size=100)
        queue.enqueue(ImprovementSuggestion(...))
        batch = queue.dequeue_batch(10)
    """

    def __init__(self, max_size: int = 100):
        self._queue: deque[ImprovementSuggestion] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self.max_size = max_size

    def enqueue(self, suggestion: ImprovementSuggestion) -> None:
        """Add a suggestion to the queue. Evicts oldest if full."""
        with self._lock:
            self._queue.append(suggestion)

    def dequeue_batch(self, n: int = 10) -> list[ImprovementSuggestion]:
        """Remove and return up to n suggestions."""
        with self._lock:
            batch = []
            for _ in range(min(n, len(self._queue))):
                batch.append(self._queue.popleft())
            return batch

    def peek(self, n: int = 10) -> list[ImprovementSuggestion]:
        """Return up to n suggestions without removing them."""
        with self._lock:
            return list(self._queue)[:n]

    def __len__(self) -> int:
        with self._lock:
            return len(self._queue)


# Module-level singleton for cross-module access
_global_queue: ImprovementQueue | None = None
_global_lock = threading.Lock()


def get_improvement_queue() -> ImprovementQueue:
    """Get or create the global improvement queue singleton."""
    global _global_queue
    if _global_queue is None:
        with _global_lock:
            if _global_queue is None:
                _global_queue = ImprovementQueue()
    return _global_queue
