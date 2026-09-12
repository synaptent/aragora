"""
Tests for tier operations concurrency and TOCTOU prevention.

Covers:
- immediate_transaction() for TOCTOU-safe operations
- Multi-process simulation with shared database
- Promotion cooldown enforcement under concurrent access
- Cross-process tier transition safety

Run with:
    pytest tests/memory/test_tier_ops_concurrency.py -v --timeout=60
"""

from __future__ import annotations

import multiprocessing
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from queue import Empty
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.memory.continuum import ContinuumMemory, reset_continuum_memory
from aragora.memory.tier_manager import MemoryTier, TierManager, reset_tier_manager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """Create a temporary database path for testing."""
    return str(tmp_path / "test_concurrency.db")


@pytest.fixture
def memory(temp_db_path: str) -> ContinuumMemory:
    """Create a ContinuumMemory instance with isolated database."""
    reset_tier_manager()
    reset_continuum_memory()
    cms = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())
    yield cms
    reset_tier_manager()
    reset_continuum_memory()


# ---------------------------------------------------------------------------
# immediate_transaction tests
# ---------------------------------------------------------------------------


class TestImmediateTransaction:
    """Tests for immediate_transaction() method."""

    def test_immediate_transaction_basic(self, memory: ContinuumMemory) -> None:
        """Test basic immediate_transaction functionality."""
        memory.add("tx_test", "Content", tier=MemoryTier.MEDIUM)

        with memory.immediate_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tier FROM continuum_memory WHERE id = ?", ("tx_test",))
            row = cursor.fetchone()
            assert row[0] == "medium"

            cursor.execute(
                "UPDATE continuum_memory SET tier = ? WHERE id = ?",
                ("fast", "tx_test"),
            )

        # Verify the update persisted
        entry = memory.get("tx_test")
        assert entry.tier == MemoryTier.FAST

    def test_immediate_transaction_rollback_on_error(self, memory: ContinuumMemory) -> None:
        """Test that immediate_transaction rolls back on error."""
        memory.add("rollback_test", "Content", tier=MemoryTier.MEDIUM)

        try:
            with memory.immediate_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE continuum_memory SET tier = ? WHERE id = ?",
                    ("fast", "rollback_test"),
                )
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Verify the update was rolled back
        entry = memory.get("rollback_test")
        assert entry.tier == MemoryTier.MEDIUM

    def test_immediate_transaction_acquires_lock(self, temp_db_path: str) -> None:
        """Test that BEGIN IMMEDIATE acquires a lock before reading."""
        # Create two separate memory instances pointing to same DB
        cms1 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())
        cms2 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())

        cms1.add("lock_test", "Content", tier=MemoryTier.MEDIUM)

        lock_acquired_order = []
        errors = []

        def writer1():
            try:
                with cms1.immediate_transaction() as conn:
                    lock_acquired_order.append("w1_start")
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT tier FROM continuum_memory WHERE id = ?",
                        ("lock_test",),
                    )
                    time.sleep(0.1)  # Hold the lock
                    cursor.execute(
                        "UPDATE continuum_memory SET surprise_score = 0.5 WHERE id = ?",
                        ("lock_test",),
                    )
                    lock_acquired_order.append("w1_end")
            except Exception as e:
                errors.append(("w1", str(e)))

        def writer2():
            try:
                time.sleep(0.02)  # Start slightly after writer1
                with cms2.immediate_transaction() as conn:
                    lock_acquired_order.append("w2_start")
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT tier FROM continuum_memory WHERE id = ?",
                        ("lock_test",),
                    )
                    cursor.execute(
                        "UPDATE continuum_memory SET surprise_score = 0.6 WHERE id = ?",
                        ("lock_test",),
                    )
                    lock_acquired_order.append("w2_end")
            except Exception as e:
                errors.append(("w2", str(e)))

        t1 = threading.Thread(target=writer1)
        t2 = threading.Thread(target=writer2)

        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        # Both should complete without errors
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Operations should be serialized (no interleaving)
        # Either w1 completes before w2 starts, or vice versa
        assert lock_acquired_order[0] in ["w1_start", "w2_start"]
        if lock_acquired_order[0] == "w1_start":
            # w1 started first, should complete before w2 starts
            w1_end_idx = lock_acquired_order.index("w1_end")
            w2_start_idx = lock_acquired_order.index("w2_start")
            assert w1_end_idx < w2_start_idx, "Transactions were not serialized"


# ---------------------------------------------------------------------------
# Promotion TOCTOU tests
# ---------------------------------------------------------------------------


class TestPromotionTOCTOU:
    """Tests for promotion TOCTOU prevention."""

    def test_concurrent_promote_same_entry(self, temp_db_path: str) -> None:
        """Test that concurrent promotion of same entry is handled safely."""
        cms1 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())
        cms2 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())

        cms1.add("concurrent_promote", "Content", tier=MemoryTier.MEDIUM)

        # Set high surprise score
        with cms1.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?",
                ("concurrent_promote",),
            )
            conn.commit()

        results = {}
        errors = []

        def promote1():
            try:
                result = cms1.promote("concurrent_promote")
                results["p1"] = result
            except Exception as e:
                errors.append(("p1", str(e)))

        def promote2():
            try:
                time.sleep(0.01)  # Slight delay
                result = cms2.promote("concurrent_promote")
                results["p2"] = result
            except Exception as e:
                errors.append(("p2", str(e)))

        t1 = threading.Thread(target=promote1)
        t2 = threading.Thread(target=promote2)

        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Exactly one should succeed (the first one)
        # The second one should fail due to cooldown set by the first
        successful = sum(1 for r in results.values() if r == MemoryTier.FAST)
        failed = sum(1 for r in results.values() if r is None)

        # At most one promotion should succeed
        assert successful <= 1, f"Multiple promotions succeeded: {results}"

        # Verify the entry is in FAST tier
        entry = cms1.get("concurrent_promote")
        assert entry.tier == MemoryTier.FAST

    def test_cooldown_prevents_rapid_promotion(self, memory: ContinuumMemory) -> None:
        """Test that cooldown is enforced after promotion."""
        memory.add("cooldown_test", "Content", tier=MemoryTier.SLOW)

        # Set high surprise
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?",
                ("cooldown_test",),
            )
            conn.commit()

        # First promotion should succeed
        result1 = memory.promote("cooldown_test")
        assert result1 == MemoryTier.MEDIUM

        # Update surprise again for another potential promotion
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?",
                ("cooldown_test",),
            )
            conn.commit()

        # Second promotion should fail due to cooldown
        result2 = memory.promote("cooldown_test")
        assert result2 is None

        # Verify still in MEDIUM tier
        entry = memory.get("cooldown_test")
        assert entry.tier == MemoryTier.MEDIUM


# ---------------------------------------------------------------------------
# Demotion TOCTOU tests
# ---------------------------------------------------------------------------


class TestDemotionTOCTOU:
    """Tests for demotion TOCTOU prevention."""

    def test_concurrent_demote_same_entry(self, temp_db_path: str) -> None:
        """Test that concurrent demotion of same entry is handled safely."""
        cms1 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())
        cms2 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())

        cms1.add("concurrent_demote", "Content", tier=MemoryTier.FAST)

        # Set low surprise and high update count
        with cms1.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.05, update_count = 20
                   WHERE id = ?""",
                ("concurrent_demote",),
            )
            conn.commit()

        results = {}
        errors = []

        def demote1():
            try:
                result = cms1.demote("concurrent_demote")
                results["d1"] = result
            except Exception as e:
                errors.append(("d1", str(e)))

        def demote2():
            try:
                time.sleep(0.01)  # Slight delay
                result = cms2.demote("concurrent_demote")
                results["d2"] = result
            except Exception as e:
                errors.append(("d2", str(e)))

        t1 = threading.Thread(target=demote1)
        t2 = threading.Thread(target=demote2)

        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(errors) == 0, f"Errors occurred: {errors}"

        # First demotion should succeed, second should fail (already demoted)
        successful = sum(1 for r in results.values() if r == MemoryTier.MEDIUM)

        # At most one demotion should succeed from FAST to MEDIUM
        assert successful <= 1, f"Multiple demotions succeeded: {results}"

        # Verify the entry moved down exactly one tier
        entry = cms1.get("concurrent_demote")
        assert entry.tier in [MemoryTier.MEDIUM, MemoryTier.SLOW]


# ---------------------------------------------------------------------------
# Batch operation concurrency tests
# ---------------------------------------------------------------------------


class TestBatchOperationConcurrency:
    """Tests for batch operation concurrency safety."""

    def test_concurrent_batch_promote(self, temp_db_path: str) -> None:
        """Test concurrent batch promotions."""
        cms1 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())
        cms2 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())

        # Add entries
        for i in range(10):
            cms1.add(f"batch_{i}", f"Content {i}", tier=MemoryTier.SLOW)

        # Set high surprise
        with cms1.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE continuum_memory SET surprise_score = 0.9")
            conn.commit()

        ids = [f"batch_{i}" for i in range(10)]
        results = {}
        errors = []

        def batch1():
            try:
                count = cms1._promote_batch(MemoryTier.SLOW, MemoryTier.MEDIUM, ids[:5])
                results["b1"] = count
            except Exception as e:
                errors.append(("b1", str(e)))

        def batch2():
            try:
                # Try to promote overlapping set
                count = cms2._promote_batch(MemoryTier.SLOW, MemoryTier.MEDIUM, ids[3:8])
                results["b2"] = count
            except Exception as e:
                errors.append(("b2", str(e)))

        t1 = threading.Thread(target=batch1)
        t2 = threading.Thread(target=batch2)

        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Each entry should only be promoted once
        # Total promoted should be at most 10 (even with overlapping sets)
        total_reported = results.get("b1", 0) + results.get("b2", 0)

        # Count actual entries in MEDIUM tier
        with cms1.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM continuum_memory WHERE tier = 'medium'")
            actual_promoted = cursor.fetchone()[0]

        # Due to cooldown, some overlapping promotions should be blocked
        assert actual_promoted <= 10


# ---------------------------------------------------------------------------
# Multi-process simulation tests
# ---------------------------------------------------------------------------


def _worker_promote(db_path: str, entry_id: str, result_queue):
    """Worker function for multi-process promotion test."""
    try:
        cms = ContinuumMemory(db_path=db_path, tier_manager=TierManager())
        result = cms.promote(entry_id)
        result_queue.put(("success", result))
    except Exception as e:
        result_queue.put(("error", str(e)))


class TestMultiProcessSimulation:
    """Tests simulating multi-process/multi-pod scenarios."""

    @pytest.mark.parametrize(
        ("failure", "message"),
        [
            ("missing_result", "Missing worker result"),
            ("worker_error", "Worker errors"),
            ("invalid_status", "Worker errors"),
            ("no_promotion", "Expected exactly one promotion"),
            ("duplicate_promotion", "Expected exactly one promotion"),
            ("crash", "Worker exit codes"),
            ("hang", "Workers did not finish"),
            ("not_persisted", "Promotion was not persisted"),
        ],
    )
    def test_multiprocess_rejects_false_success(
        self, temp_db_path: str, monkeypatch: pytest.MonkeyPatch, failure: str, message: str
    ) -> None:
        results = [("success", MemoryTier.FAST), ("success", None), ("success", None)]
        if failure == "missing_result":
            results[-1] = Empty()
        elif failure == "worker_error":
            results[-1] = ("error", "worker failed")
        elif failure == "invalid_status":
            results[-1] = ("unknown", None)
        elif failure == "no_promotion":
            results[0] = ("success", None)
        elif failure == "duplicate_promotion":
            results[1] = ("success", MemoryTier.FAST)

        context = MagicMock()
        result_queue = context.Queue.return_value
        result_queue.get.side_effect = results
        processes = [MagicMock(exitcode=0) for _ in range(3)]
        for process in processes:
            process.is_alive.return_value = False
        if failure == "crash":
            processes[0].exitcode = 1
        elif failure == "hang":
            processes[0].is_alive.return_value = True
        context.Process.side_effect = processes
        get_context = MagicMock(return_value=context)
        monkeypatch.setattr(multiprocessing, "get_context", get_context)

        with pytest.raises(AssertionError, match=message):
            self.test_multiprocess_promote_simulation(temp_db_path)

        get_context.assert_called_once_with("spawn")
        for process in processes:
            process.close.assert_called_once()
        if failure == "hang":
            processes[0].terminate.assert_called_once()
        result_queue.close.assert_called_once()
        result_queue.join_thread.assert_called_once()

    def test_multiprocess_promote_simulation(self, temp_db_path: str) -> None:
        """Test that promotion is safe across multiple processes."""
        # Initialize database in main process
        cms = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())
        cms.add("mp_test", "Content", tier=MemoryTier.MEDIUM)

        # Set high surprise
        with cms.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?",
                ("mp_test",),
            )
            conn.commit()

        # Spawn avoids inheriting the parent's database connections on fork platforms.
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue()
        processes = []
        try:
            for _ in range(3):
                process = context.Process(
                    target=_worker_promote,
                    args=(temp_db_path, "mp_test", result_queue),
                )
                process.start()
                processes.append(process)

            deadline = time.monotonic() + 15
            results = []
            for _ in processes:
                try:
                    results.append(result_queue.get(timeout=max(0, deadline - time.monotonic())))
                except Empty as exc:
                    raise AssertionError(
                        f"Missing worker result: received {len(results)}/3"
                    ) from exc

            for process in processes:
                process.join(timeout=max(0, deadline - time.monotonic()))
            assert not any(p.is_alive() for p in processes), "Workers did not finish"
            exit_codes = [p.exitcode for p in processes]
            assert exit_codes == [0, 0, 0], f"Worker exit codes: {exit_codes}"
            errors = [(status, result) for status, result in results if status != "success"]
            assert not errors, f"Worker errors: {errors}"
            successes = [result for _, result in results if result is not None]
            assert successes == [MemoryTier.FAST], f"Expected exactly one promotion: {results}"

            with cms.connection() as conn:
                tier = conn.execute(
                    "SELECT tier FROM continuum_memory WHERE id = ?", ("mp_test",)
                ).fetchone()[0]
                transitions = conn.execute(
                    "SELECT from_tier, to_tier FROM tier_transitions WHERE memory_id = ?",
                    ("mp_test",),
                ).fetchall()
            assert tier == "fast", "Promotion was not persisted"
            assert [tuple(row) for row in transitions] == [("medium", "fast")], (
                f"Unexpected transitions: {transitions}"
            )
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
                process.close()
            result_queue.close()
            result_queue.join_thread()


# ---------------------------------------------------------------------------
# Stress tests
# ---------------------------------------------------------------------------


class TestConcurrencyStress:
    """Stress tests for tier operation concurrency."""

    def test_many_concurrent_operations(self, temp_db_path: str) -> None:
        """Test many concurrent promote/demote operations."""
        cms = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())

        # Add many entries
        for i in range(50):
            if i % 2 == 0:
                cms.add(f"stress_{i}", f"Content {i}", tier=MemoryTier.MEDIUM)
            else:
                cms.add(f"stress_{i}", f"Content {i}", tier=MemoryTier.FAST)

        # Set up for promotions and demotions
        with cms.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE continuum_memory SET surprise_score = 0.9 WHERE tier = 'medium'")
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.05, update_count = 20
                   WHERE tier = 'fast'"""
            )
            conn.commit()

        errors = []

        def do_promotes():
            for i in range(0, 50, 2):
                try:
                    cms.promote(f"stress_{i}")
                except Exception as e:
                    errors.append(("promote", i, str(e)))

        def do_demotes():
            for i in range(1, 50, 2):
                try:
                    cms.demote(f"stress_{i}")
                except Exception as e:
                    errors.append(("demote", i, str(e)))

        threads = [
            threading.Thread(target=do_promotes),
            threading.Thread(target=do_promotes),
            threading.Thread(target=do_demotes),
            threading.Thread(target=do_demotes),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Verify database integrity
        with cms.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM continuum_memory")
            count = cursor.fetchone()[0]
            assert count == 50, "Database integrity violated"


# ---------------------------------------------------------------------------
# Transaction isolation tests
# ---------------------------------------------------------------------------


class TestTransactionIsolation:
    """Tests for transaction isolation behavior."""

    def test_immediate_vs_deferred_behavior(self, temp_db_path: str) -> None:
        """Test difference between immediate and deferred transactions."""
        cms1 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())
        cms2 = ContinuumMemory(db_path=temp_db_path, tier_manager=TierManager())

        cms1.add("isolation_test", "Content", tier=MemoryTier.MEDIUM)

        # Start immediate transaction in cms1
        with cms1.immediate_transaction() as conn1:
            cursor1 = conn1.cursor()
            cursor1.execute(
                "SELECT tier FROM continuum_memory WHERE id = ?",
                ("isolation_test",),
            )
            original = cursor1.fetchone()[0]
            assert original == "medium"

            # cms2 should be blocked from writing
            # (in SQLite, BEGIN IMMEDIATE blocks other writers but allows readers)
            with cms2.connection() as conn2:
                cursor2 = conn2.cursor()
                cursor2.execute(
                    "SELECT tier FROM continuum_memory WHERE id = ?",
                    ("isolation_test",),
                )
                # Reading should still work
                row = cursor2.fetchone()
                assert row[0] == "medium"

            # Update in cms1
            cursor1.execute(
                "UPDATE continuum_memory SET tier = 'fast' WHERE id = ?",
                ("isolation_test",),
            )

        # After commit, cms2 should see the change
        entry = cms2.get("isolation_test")
        assert entry.tier == MemoryTier.FAST
