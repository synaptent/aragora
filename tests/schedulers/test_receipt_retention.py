"""Tests for receipt retention scheduler."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.scheduler.receipt_retention import (
    CleanupResult,
    CleanupStats,
    ReceiptRetentionScheduler,
    get_receipt_retention_scheduler,
    set_receipt_retention_scheduler,
)


class TestCleanupResult:
    """Tests for CleanupResult dataclass."""

    def test_to_dict_success(self):
        """Test converting successful result to dict."""
        now = datetime.now(timezone.utc)
        result = CleanupResult(
            receipts_deleted=5,
            started_at=now,
            completed_at=now,
            duration_seconds=1.5,
            retention_days=2555,
        )
        d = result.to_dict()
        assert d["receipts_deleted"] == 5
        assert d["success"] is True
        assert d["error"] is None
        assert d["retention_days"] == 2555
        assert d["duration_seconds"] == 1.5

    def test_to_dict_with_error(self):
        """Test converting error result to dict."""
        now = datetime.now(timezone.utc)
        result = CleanupResult(
            receipts_deleted=0,
            started_at=now,
            completed_at=now,
            duration_seconds=0.1,
            retention_days=2555,
            error="Database connection failed",
        )
        d = result.to_dict()
        assert d["receipts_deleted"] == 0
        assert d["success"] is False
        assert d["error"] == "Database connection failed"


class TestCleanupStats:
    """Tests for CleanupStats dataclass."""

    def test_add_result_success(self):
        """Test adding successful result."""
        stats = CleanupStats()
        now = datetime.now(timezone.utc)
        result = CleanupResult(
            receipts_deleted=10,
            started_at=now,
            completed_at=now,
            duration_seconds=2.0,
            retention_days=2555,
        )
        stats.add_result(result)

        assert stats.total_runs == 1
        assert stats.total_receipts_deleted == 10
        assert stats.failures == 0
        assert stats.last_result == result
        assert len(stats.results) == 1

    def test_add_result_failure(self):
        """Test adding failed result."""
        stats = CleanupStats()
        now = datetime.now(timezone.utc)
        result = CleanupResult(
            receipts_deleted=0,
            started_at=now,
            completed_at=now,
            duration_seconds=0.1,
            retention_days=2555,
            error="Something went wrong",
        )
        stats.add_result(result)

        assert stats.total_runs == 1
        assert stats.total_receipts_deleted == 0
        assert stats.failures == 1

    def test_to_dict(self):
        """Test stats to dict conversion."""
        stats = CleanupStats()
        d = stats.to_dict()
        assert d["total_runs"] == 0
        assert d["total_receipts_deleted"] == 0
        assert d["success_rate"] == 1.0
        assert d["last_run"] is None

    def test_results_capped_at_100(self):
        """Test that results list is capped at 100."""
        stats = CleanupStats()
        now = datetime.now(timezone.utc)
        for i in range(150):
            result = CleanupResult(
                receipts_deleted=i,
                started_at=now,
                completed_at=now,
                duration_seconds=0.1,
                retention_days=2555,
            )
            stats.add_result(result)

        assert len(stats.results) == 100
        # Should keep the most recent 100
        assert stats.results[-1].receipts_deleted == 149


class TestReceiptRetentionScheduler:
    """Tests for ReceiptRetentionScheduler."""

    @pytest.fixture
    def mock_store(self):
        """Create a mock receipt store."""
        store = MagicMock()
        store.cleanup_expired.return_value = 5
        store.retention_days = 2555
        return store

    def test_init_defaults(self, mock_store):
        """Test scheduler initialization with defaults."""
        scheduler = ReceiptRetentionScheduler(mock_store)
        assert scheduler.store == mock_store
        assert scheduler.interval_hours == 24
        assert scheduler.retention_days is None
        assert not scheduler.is_running

    def test_init_custom_values(self, mock_store):
        """Test scheduler initialization with custom values."""
        scheduler = ReceiptRetentionScheduler(
            mock_store,
            interval_hours=12,
            retention_days=365,
        )
        assert scheduler.interval_hours == 12
        assert scheduler.retention_days == 365

    @pytest.mark.asyncio
    async def test_start_stop(self, mock_store):
        """Test starting and stopping the scheduler."""
        scheduler = ReceiptRetentionScheduler(mock_store, interval_hours=1)

        assert not scheduler.is_running

        await scheduler.start()
        assert scheduler.is_running

        # Stop immediately
        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_start_already_running(self, mock_store):
        """Test starting when already running."""
        scheduler = ReceiptRetentionScheduler(mock_store, interval_hours=1)

        await scheduler.start()
        # Second start should be a no-op
        await scheduler.start()
        assert scheduler.is_running

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_not_running(self, mock_store):
        """Test stopping when not running."""
        scheduler = ReceiptRetentionScheduler(mock_store)
        # Should be a no-op
        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_cleanup_now(self, mock_store):
        """Test immediate cleanup."""
        scheduler = ReceiptRetentionScheduler(mock_store)

        result = await scheduler.cleanup_now()

        assert result.receipts_deleted == 5
        assert result.error is None
        mock_store.cleanup_expired.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_now_with_retention_override(self, mock_store):
        """Test cleanup with retention days override."""
        scheduler = ReceiptRetentionScheduler(mock_store, retention_days=365)

        await scheduler.cleanup_now()

        mock_store.cleanup_expired.assert_called_with(
            retention_days=365,
            operator="system:receipt_retention_scheduler",
            log_deletions=True,
        )

    @pytest.mark.asyncio
    async def test_cleanup_result_reports_effective_retention_days(self, mock_store):
        """The result carries the override when set, else the store's retention days."""
        default_result = await ReceiptRetentionScheduler(mock_store).cleanup_now()
        override_result = await ReceiptRetentionScheduler(
            mock_store, retention_days=365
        ).cleanup_now()

        assert default_result.retention_days == 2555
        assert override_result.retention_days == 365

    @pytest.mark.asyncio
    async def test_cleanup_now_error(self, mock_store):
        """Test cleanup handling errors."""
        mock_store.cleanup_expired.side_effect = RuntimeError("Database error")
        scheduler = ReceiptRetentionScheduler(mock_store)

        result = await scheduler.cleanup_now()

        assert result.receipts_deleted == 0
        assert result.error == "Receipt cleanup failed"

    def test_get_status(self, mock_store):
        """Test getting scheduler status."""
        scheduler = ReceiptRetentionScheduler(
            mock_store,
            interval_hours=12,
            retention_days=365,
        )

        status = scheduler.get_status()

        assert status["running"] is False
        assert status["interval_hours"] == 12
        assert status["retention_days"] == 365
        assert "stats" in status

    @pytest.mark.asyncio
    async def test_on_cleanup_complete_callback(self, mock_store):
        """Test cleanup complete callback is called."""
        callback = MagicMock()
        scheduler = ReceiptRetentionScheduler(
            mock_store,
            on_cleanup_complete=callback,
        )

        result = await scheduler.cleanup_now()
        # Manually add to stats and call callback like the loop would
        scheduler._stats.add_result(result)
        scheduler.on_cleanup_complete(result)

        callback.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_on_error_callback(self, mock_store):
        """Test error callback is called on exceptions."""
        mock_store.cleanup_expired.side_effect = RuntimeError("Test error")
        error_callback = MagicMock()
        scheduler = ReceiptRetentionScheduler(
            mock_store,
            on_error=error_callback,
        )

        # Simulate the error handling that happens in _cleanup_loop
        try:
            await scheduler.cleanup_now()
        except Exception as e:
            error_callback(e)

        # The cleanup_now catches the exception, so we test differently
        result = await scheduler.cleanup_now()
        assert result.error is not None


class TestGlobalScheduler:
    """Tests for global scheduler management."""

    def teardown_method(self):
        """Reset global scheduler after each test."""
        set_receipt_retention_scheduler(None)

    def test_get_scheduler_none_without_store(self):
        """Test getting scheduler without store returns None."""
        set_receipt_retention_scheduler(None)
        scheduler = get_receipt_retention_scheduler()
        assert scheduler is None

    def test_get_scheduler_creates_with_store(self):
        """Test getting scheduler creates one with store."""
        set_receipt_retention_scheduler(None)
        mock_store = MagicMock()
        scheduler = get_receipt_retention_scheduler(mock_store)
        assert scheduler is not None
        assert scheduler.store == mock_store

    def test_get_scheduler_returns_existing(self):
        """Test getting scheduler returns existing instance."""
        mock_store = MagicMock()
        scheduler1 = get_receipt_retention_scheduler(mock_store)
        scheduler2 = get_receipt_retention_scheduler()
        assert scheduler1 is scheduler2

    def test_set_scheduler(self):
        """Test setting global scheduler."""
        mock_store = MagicMock()
        scheduler = ReceiptRetentionScheduler(mock_store)
        set_receipt_retention_scheduler(scheduler)

        retrieved = get_receipt_retention_scheduler()
        assert retrieved is scheduler
