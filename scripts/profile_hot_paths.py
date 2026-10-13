#!/usr/bin/env python3
"""
Profile critical hot paths in Aragora.

This script measures the performance of key operations identified
as performance-critical in the codebase:

1. Memory retrieval (ContinuumMemory)
2. Semantic similarity computation
3. Database operations
4. Pattern retrieval

Usage:
    python scripts/profile_hot_paths.py
"""

import cProfile
import pstats
import io
import time
import tempfile
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
import statistics

# Ensure imports work
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class ProfileResult:
    """Result of profiling a function."""

    name: str
    iterations: int
    total_time: float
    avg_time: float
    min_time: float
    max_time: float
    std_dev: float

    def __str__(self) -> str:
        return (
            f"{self.name}:\n"
            f"  Iterations: {self.iterations}\n"
            f"  Total: {self.total_time * 1000:.2f}ms\n"
            f"  Avg: {self.avg_time * 1000:.3f}ms\n"
            f"  Min: {self.min_time * 1000:.3f}ms\n"
            f"  Max: {self.max_time * 1000:.3f}ms\n"
            f"  StdDev: {self.std_dev * 1000:.3f}ms"
        )


@contextmanager
def timer():
    """Simple context manager for timing operations."""
    start = time.perf_counter()

    def elapsed():
        return time.perf_counter() - start

    yield elapsed


def profile_function(func, iterations: int = 100, name: str | None = None) -> ProfileResult:
    """Profile a function over multiple iterations."""
    times = []

    for _ in range(iterations):
        start = time.perf_counter()
        func()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    return ProfileResult(
        name=name or func.__name__,
        iterations=iterations,
        total_time=sum(times),
        avg_time=statistics.mean(times),
        min_time=min(times),
        max_time=max(times),
        std_dev=statistics.stdev(times) if len(times) > 1 else 0.0,
    )


# ============================================================================
# Profile Targets
# ============================================================================


def profile_cosine_similarity():
    """Profile cosine similarity computation."""
    from aragora.memory.embeddings import cosine_similarity
    import random

    # Generate test vectors
    dim = 1536  # OpenAI embedding dimension
    vec1 = [random.random() for _ in range(dim)]
    vec2 = [random.random() for _ in range(dim)]

    def compute_similarity():
        return cosine_similarity(vec1, vec2)

    result = profile_function(compute_similarity, iterations=1000, name="cosine_similarity (1536d)")
    print(result)
    return result


def profile_text_similarity():
    """Profile text similarity (word-based fallback)."""
    from aragora.debate.meta import MetaCritiqueAnalyzer

    analyzer = MetaCritiqueAnalyzer()

    text1 = "The system should use microservices for better scalability and maintainability."
    text2 = "Microservices architecture provides scalability but adds complexity."

    def compute_similarity():
        return analyzer._text_similarity(text1, text2)

    result = profile_function(
        compute_similarity, iterations=1000, name="text_similarity (word-based)"
    )
    print(result)
    return result


def profile_database_operations():
    """Profile SQLite database operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create test database
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS test_data (
                id INTEGER PRIMARY KEY,
                key TEXT,
                value TEXT,
                score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.execute("CREATE INDEX idx_key ON test_data(key)")

        # Insert test data
        for i in range(1000):
            conn.execute(
                "INSERT INTO test_data (key, value, score) VALUES (?, ?, ?)",
                (f"key_{i % 100}", f"value_{i}", i / 1000.0),
            )
        conn.commit()

        # Profile read operations
        def read_by_key():
            cursor = conn.execute("SELECT * FROM test_data WHERE key = ?", ("key_50",))
            return list(cursor.fetchall())

        result_read = profile_function(
            read_by_key, iterations=500, name="SQLite SELECT by key (indexed)"
        )
        print(result_read)

        # Profile aggregation
        def aggregate_scores():
            cursor = conn.execute("SELECT key, AVG(score) FROM test_data GROUP BY key")
            return list(cursor.fetchall())

        result_agg = profile_function(
            aggregate_scores, iterations=100, name="SQLite GROUP BY aggregation"
        )
        print(result_agg)

        conn.close()
        return result_read, result_agg


def profile_memory_store_operations():
    """Profile CritiqueStore pattern operations."""
    from aragora.memory.store import CritiqueStore
    from aragora.core import Critique, DebateResult, Message, Vote

    with tempfile.TemporaryDirectory() as tmpdir:
        store = CritiqueStore(db_path=f"{tmpdir}/critique.db")

        # Create mock debate results
        for i in range(10):
            messages = [
                Message(round=j, role="proposer", agent=f"agent-{j % 3}", content=f"Content {j}")
                for j in range(5)
            ]
            critiques = [
                Critique(
                    agent=f"agent-{j % 3}",
                    target_agent=f"agent-{(j + 1) % 3}",
                    target_content=f"Target {j}",
                    issues=[f"Issue {k}" for k in range(2)],
                    suggestions=[f"Suggestion {k}" for k in range(2)],
                    severity=0.5,
                    reasoning=f"Reasoning for critique {j}",
                )
                for j in range(3)
            ]
            result = DebateResult(
                id=f"debate-{i}",
                task=f"Task {i}",
                final_answer=f"Answer {i}",
                confidence=0.8,
                consensus_reached=True,
                messages=messages,
                critiques=critiques,
                votes=[],
            )
            store.store_debate(result)

        # Profile reputation retrieval
        def get_stats():
            stats = store.get_stats()
            return stats

        result = profile_function(get_stats, iterations=100, name="CritiqueStore.get_stats")
        print(result)

        # Profile pattern retrieval
        def retrieve_patterns():
            patterns = store.retrieve_patterns(limit=10)
            return patterns

        result2 = profile_function(
            retrieve_patterns, iterations=100, name="CritiqueStore.retrieve_patterns"
        )
        print(result2)
        return result2


def profile_meta_critique_analysis():
    """Profile meta-critique analysis operations."""
    from aragora.debate.meta import MetaCritiqueAnalyzer
    from aragora.core import Message, Critique, DebateResult

    analyzer = MetaCritiqueAnalyzer()

    # Create mock debate result
    messages = [
        Message(
            round=i,
            role="proposer" if i % 2 == 0 else "critic",
            agent=f"agent-{i % 3}",
            content=f"Message content for round {i}" * 10,
        )
        for i in range(20)
    ]

    critiques = [
        Critique(
            agent=f"agent-{i % 3}",
            target_agent=f"agent-{(i + 1) % 3}",
            target_content=f"Target content {i}",
            issues=[f"Issue {j}" for j in range(2)],
            suggestions=[f"Suggestion {j}" for j in range(2)],
            severity=0.5 + (i % 5) / 10,
            reasoning=f"Reasoning for critique {i}",
        )
        for i in range(10)
    ]

    result = DebateResult(
        id="test-debate",
        task="Test debate task",
        final_answer="Final answer here",
        confidence=0.8,
        consensus_reached=True,
        messages=messages,
        critiques=critiques,
        votes=[],
    )

    def analyze_debate():
        return analyzer.analyze(result)

    profile_result = profile_function(
        analyze_debate, iterations=100, name="MetaCritiqueAnalyzer.analyze"
    )
    print(profile_result)
    return profile_result


def run_all_profiles():
    """Run all profiling benchmarks."""
    print("=" * 60)
    print("ARAGORA HOT PATH PROFILING")
    print("=" * 60)
    print()

    results = {}

    print("1. Cosine Similarity (Vector Operations)")
    print("-" * 40)
    results["cosine"] = profile_cosine_similarity()
    print()

    print("2. Text Similarity (Word-Based)")
    print("-" * 40)
    results["text"] = profile_text_similarity()
    print()

    print("3. Database Operations")
    print("-" * 40)
    results["db"] = profile_database_operations()
    print()

    print("4. Memory Store Operations")
    print("-" * 40)
    results["memory"] = profile_memory_store_operations()
    print()

    print("5. Meta-Critique Analysis")
    print("-" * 40)
    results["meta"] = profile_meta_critique_analysis()
    print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print()
    print("Operation                              Avg Time (ms)")
    print("-" * 55)

    flat_results = []
    for key, value in results.items():
        if isinstance(value, tuple):
            flat_results.extend(value)
        else:
            flat_results.append(value)

    for r in flat_results:
        if r:
            print(f"{r.name[:38]:<40} {r.avg_time * 1000:>10.3f}")

    print()
    print("Recommendations:")
    print("-" * 55)

    # Identify slowest operations
    sorted_results = sorted([r for r in flat_results if r], key=lambda x: x.avg_time, reverse=True)
    if sorted_results:
        slowest = sorted_results[0]
        print(f"  - Optimize '{slowest.name}' (avg {slowest.avg_time * 1000:.2f}ms)")

        if len(sorted_results) > 1:
            second_slowest = sorted_results[1]
            print(
                f"  - Consider caching '{second_slowest.name}' (avg {second_slowest.avg_time * 1000:.2f}ms)"
            )


if __name__ == "__main__":
    run_all_profiles()
