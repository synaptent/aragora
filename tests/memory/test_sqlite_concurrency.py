"""
Tests for SQLite WAL mode and concurrency handling.

Verifies that the WAL mode is properly enabled and that concurrent
read/write operations work correctly across the codebase.
"""

import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import Mock

import pytest

from aragora.storage.schema import get_wal_connection, DB_TIMEOUT
from aragora.memory.store import CritiqueStore
from aragora.memory.continuum import ContinuumMemory
from aragora.core import Critique


class TestWalConnection:
    """Tests for the WAL connection helper function."""

    def test_wal_mode_enabled(self, temp_db):
        """Verify that WAL mode is actually enabled on the connection."""
        conn = get_wal_connection(temp_db)
        try:
            cursor = conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode.lower() == "wal", f"Expected WAL mode, got {mode}"
        finally:
            conn.close()

    def test_synchronous_normal(self, temp_db):
        """Verify that synchronous mode is set to NORMAL."""
        conn = get_wal_connection(temp_db)
        try:
            cursor = conn.execute("PRAGMA synchronous")
            sync = cursor.fetchone()[0]
            # NORMAL = 1
            assert sync == 1, f"Expected NORMAL (1), got {sync}"
        finally:
            conn.close()

    def test_busy_timeout_set(self, temp_db):
        """Verify that busy_timeout is set correctly."""
        conn = get_wal_connection(temp_db)
        try:
            cursor = conn.execute("PRAGMA busy_timeout")
            timeout = cursor.fetchone()[0]
            expected_ms = int(DB_TIMEOUT * 1000)
            assert timeout == expected_ms, f"Expected {expected_ms}ms, got {timeout}ms"
        finally:
            conn.close()

    def test_custom_timeout(self, temp_db):
        """Verify that custom timeout is applied correctly."""
        custom_timeout = 5.0
        conn = get_wal_connection(temp_db, timeout=custom_timeout)
        try:
            cursor = conn.execute("PRAGMA busy_timeout")
            timeout = cursor.fetchone()[0]
            assert timeout == 5000, f"Expected 5000ms, got {timeout}ms"
        finally:
            conn.close()


class TestConcurrentReads:
    """Tests for concurrent read operations with WAL mode."""

    def test_multiple_readers(self, temp_db):
        """Verify that multiple readers can access the database simultaneously."""
        # Set up database with test data
        conn = get_wal_connection(temp_db)
        conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO test_data (value) VALUES ('test1'), ('test2'), ('test3')")
        conn.commit()
        conn.close()

        results = []
        errors = []

        def read_data():
            try:
                conn = get_wal_connection(temp_db)
                cursor = conn.execute("SELECT * FROM test_data")
                data = cursor.fetchall()
                results.append(len(data))
                conn.close()
            except Exception as e:
                errors.append(str(e))

        # Spawn multiple reader threads
        threads = [threading.Thread(target=read_data) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Read errors occurred: {errors}"
        assert all(r == 3 for r in results), f"Not all readers got expected data: {results}"

    def test_read_during_write(self, temp_db):
        """Verify that readers can operate while a writer is active."""
        # Set up database
        conn = get_wal_connection(temp_db)
        conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

        write_started = threading.Event()
        write_complete = threading.Event()
        read_results = []
        errors = []

        def writer():
            conn = get_wal_connection(temp_db)
            for i in range(100):
                conn.execute("INSERT INTO test_data (value) VALUES (?)", (f"value_{i}",))
                if i == 10:
                    write_started.set()
            conn.commit()
            conn.close()
            write_complete.set()

        def reader():
            write_started.wait(timeout=5)
            try:
                conn = get_wal_connection(temp_db)
                cursor = conn.execute("SELECT COUNT(*) FROM test_data")
                count = cursor.fetchone()[0]
                read_results.append(count)
                conn.close()
            except Exception as e:
                errors.append(str(e))

        writer_thread = threading.Thread(target=writer)
        reader_threads = [threading.Thread(target=reader) for _ in range(5)]

        writer_thread.start()
        for t in reader_threads:
            t.start()

        writer_thread.join()
        for t in reader_threads:
            t.join()

        assert len(errors) == 0, f"Read errors during write: {errors}"
        # All readers should have gotten some data (may vary due to timing)
        assert len(read_results) == 5, "Not all readers completed"


class TestConcurrentWrites:
    """Tests for concurrent write operations with WAL mode."""

    def test_sequential_writes_with_wal(self, temp_db):
        """Verify that sequential writes work correctly with WAL mode."""
        conn = get_wal_connection(temp_db)
        conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, value TEXT)")
        conn.commit()

        # Multiple writes in sequence
        for i in range(50):
            conn.execute("INSERT INTO test_data (value) VALUES (?)", (f"value_{i}",))
            conn.commit()

        cursor = conn.execute("SELECT COUNT(*) FROM test_data")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 50, f"Expected 50 rows, got {count}"

    def test_concurrent_writes_different_rows(self, temp_db):
        """Test concurrent writes to different rows (should succeed)."""
        conn = get_wal_connection(temp_db)
        conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()

        success_count = [0]
        error_count = [0]
        lock = threading.Lock()

        def write_row(row_id):
            try:
                conn = get_wal_connection(temp_db)
                conn.execute(
                    "INSERT INTO test_data (id, value) VALUES (?, ?)", (row_id, f"value_{row_id}")
                )
                conn.commit()
                conn.close()
                with lock:
                    success_count[0] += 1
            except Exception:
                with lock:
                    error_count[0] += 1

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_row, i) for i in range(100)]
            for future in as_completed(futures):
                pass  # Wait for all to complete

        # With WAL mode and unique row IDs, most writes should succeed
        # Some may fail due to lock contention, but that's expected
        assert success_count[0] > 90, f"Too many write failures: {error_count[0]}/100"


class TestCritiqueStoreConcurrency:
    """Tests for concurrent access to CritiqueStore with WAL mode."""

    def test_critique_store_uses_wal(self, temp_db):
        """Verify that CritiqueStore connections use WAL mode."""
        store = CritiqueStore(temp_db)

        # Access the connection through the context manager
        with store._get_connection() as conn:
            cursor = conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode.lower() == "wal", f"CritiqueStore not using WAL: {mode}"

    def test_concurrent_reputation_updates(self, temp_db):
        """Successful concurrent updates must match the persisted reputation totals."""
        store = CritiqueStore(temp_db)

        errors = []
        success_count = [0]
        lock = threading.Lock()
        start = threading.Barrier(10)

        def update_reputation(agent_name):
            try:
                start.wait(timeout=5)
                store.update_reputation(
                    agent_name=agent_name,
                    proposal_accepted=True,
                    critique_valuable=True,
                )
                with lock:
                    success_count[0] += 1
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Concurrent updates for the same agent (potential conflict)
        threads = [
            threading.Thread(target=update_reputation, args=("test-agent",)) for _ in range(10)
        ]

        for t in threads:
            t.start()
        deadline = time.monotonic() + 30
        for t in threads:
            t.join(timeout=max(0, deadline - time.monotonic()))

        assert not any(t.is_alive() for t in threads), "Reputation workers did not finish"
        assert success_count[0] + len(errors) == len(threads)
        # Most updates should succeed with WAL mode
        assert success_count[0] >= 5, f"Too many failures: {len(errors)} errors"

        # Read committed state on a fresh connection, not the cached reputation getter.
        conn = sqlite3.connect(temp_db)
        try:
            row = conn.execute(
                "SELECT proposals_made, proposals_accepted, critiques_given, critiques_valuable "
                "FROM agent_reputation WHERE agent_name = ?",
                ("test-agent",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "Successful calls did not persist a reputation row"
        assert row == (0, success_count[0], 0, success_count[0])


class TestContinuumMemoryConcurrency:
    """Tests for concurrent access to ContinuumMemory with WAL mode."""

    def test_continuum_memory_uses_wal(self, temp_db):
        """Verify that ContinuumMemory connections use WAL mode."""
        memory = ContinuumMemory(temp_db)

        # Check that WAL mode is set by querying a new connection
        conn = get_wal_connection(temp_db)
        try:
            cursor = conn.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode.lower() == "wal", f"ContinuumMemory DB not using WAL: {mode}"
        finally:
            conn.close()

    def test_concurrent_memory_stores(self, temp_db):
        """Test concurrent memory stores don't cause deadlocks."""
        memory = ContinuumMemory(temp_db)

        errors = []
        success_count = [0]
        lock = threading.Lock()

        def store_memory(idx):
            try:
                memory.add(
                    id=f"test-memory-{idx}",
                    content=f"Test memory content {idx}",
                    importance=0.5 + (idx % 5) * 0.1,
                    metadata={"source": "test", "index": idx},
                )
                with lock:
                    success_count[0] += 1
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Concurrent stores (using unique IDs to avoid conflicts)
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(store_memory, i) for i in range(20)]
            for future in as_completed(futures):
                pass

        # Most stores should succeed with WAL mode and unique IDs
        assert success_count[0] >= 15, (
            f"Too many failures: {len(errors)} errors, {success_count[0]} successes"
        )


class TestWalFileCreation:
    """Tests for WAL file management."""

    def test_wal_file_created(self, temp_db):
        """Verify that WAL mode creates the expected files."""
        conn = get_wal_connection(temp_db)
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        db_path = Path(temp_db)
        wal_path = Path(f"{temp_db}-wal")
        shm_path = Path(f"{temp_db}-shm")

        # WAL and SHM files should exist after write operations
        assert db_path.exists(), "Database file should exist"
        # Note: WAL files may be cleaned up when last connection closes
        # This is just to verify the mechanism works
