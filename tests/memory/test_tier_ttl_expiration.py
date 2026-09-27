"""Tests for ContinuumMemory tier TTL expiration with mocked time."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from aragora.memory.continuum import (
    DEFAULT_RETENTION_MULTIPLIER,
    ContinuumMemory,
    reset_continuum_memory,
)
from aragora.memory.continuum_stats import cleanup_expired_memories
from aragora.memory.tier_manager import (
    DEFAULT_TIER_CONFIGS,
    MemoryTier,
    TierManager,
    reset_tier_manager,
)


def _utc_naive_now() -> datetime:
    """Naive-UTC now, matching how rows are stamped and cutoffs computed."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def memory(tmp_path):
    """Create a ContinuumMemory instance with isolated database."""
    reset_tier_manager()
    reset_continuum_memory()
    cms = ContinuumMemory(
        db_path=str(tmp_path / "test_ttl.db"),
        tier_manager=TierManager(),
    )
    yield cms
    reset_tier_manager()
    reset_continuum_memory()


def _add_entries(memory):
    """Add one entry per tier."""
    memory.add("f1", "fast entry", tier=MemoryTier.FAST, importance=0.5)
    memory.add("m1", "medium entry", tier=MemoryTier.MEDIUM, importance=0.5)
    memory.add("s1", "slow entry", tier=MemoryTier.SLOW, importance=0.5)
    memory.add("g1", "glacial entry", tier=MemoryTier.GLACIAL, importance=0.5)


class TestFastTierExpiration:
    """Fast tier: half_life=1h, retention=2h."""

    def test_not_expired_before_ttl(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(hours=1, minutes=59)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory, tier=MemoryTier.FAST)
        assert result["archived"] == 0

    def test_expired_after_ttl(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(hours=3)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory, tier=MemoryTier.FAST)
        assert result["archived"] == 1


class TestMediumTierExpiration:
    """Medium tier: half_life=24h, retention=48h."""

    def test_not_expired_before_ttl(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(hours=47)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory, tier=MemoryTier.MEDIUM)
        assert result["archived"] == 0

    def test_expired_after_ttl(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(hours=49)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory, tier=MemoryTier.MEDIUM)
        assert result["archived"] == 1


class TestSlowTierExpiration:
    """Slow tier: half_life=168h (7d), retention=336h (14d)."""

    def test_not_expired_before_ttl(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(days=13)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory, tier=MemoryTier.SLOW)
        assert result["archived"] == 0

    def test_expired_after_ttl(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(days=15)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory, tier=MemoryTier.SLOW)
        assert result["archived"] == 1


class TestGlacialTierExpiration:
    """Glacial tier: half_life=720h (30d), retention=1440h (60d)."""

    def test_not_expired_before_ttl(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(days=59)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory, tier=MemoryTier.GLACIAL)
        assert result["archived"] == 0

    def test_expired_after_ttl(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(days=61)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory, tier=MemoryTier.GLACIAL)
        assert result["archived"] == 1


class TestCrosssTierExpiration:
    """Verify faster tiers expire before slower tiers."""

    def test_only_fast_expires_at_3h(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(hours=3)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory)
        assert result["by_tier"].get("fast", {}).get("archived", 0) == 1
        assert result["by_tier"].get("medium", {}).get("archived", 0) == 0
        assert result["by_tier"].get("slow", {}).get("archived", 0) == 0
        assert result["by_tier"].get("glacial", {}).get("archived", 0) == 0

    def test_fast_and_medium_expire_at_49h(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(hours=49)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory)
        assert result["by_tier"].get("fast", {}).get("archived", 0) == 1
        assert result["by_tier"].get("medium", {}).get("archived", 0) == 1
        assert result["by_tier"].get("slow", {}).get("archived", 0) == 0

    def test_all_tiers_expire_at_61d(self, memory):
        _add_entries(memory)
        future = _utc_naive_now() + timedelta(days=61)
        with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
            mock_dt.now.return_value = future
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = cleanup_expired_memories(memory)
        assert result["archived"] == 4


@pytest.mark.parametrize(
    ("tier", "future"),
    [
        (MemoryTier.FAST, timedelta(hours=3)),
        (MemoryTier.MEDIUM, timedelta(hours=49)),
        (MemoryTier.SLOW, timedelta(days=15)),
    ],
)
def test_delete_mode_reports_expected_cutoff_hours(memory, tier, future):
    _add_entries(memory)
    with patch("aragora.memory.continuum_stats.datetime") as mock_dt:
        mock_dt.now.return_value = _utc_naive_now() + future
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = cleanup_expired_memories(memory, tier=tier, archive=False)

    expected_cutoff_hours = (
        DEFAULT_TIER_CONFIGS[tier].half_life_hours * DEFAULT_RETENTION_MULTIPLIER
    )
    assert result["deleted"] == 1
    assert result["by_tier"][tier.value]["cutoff_hours"] == expected_cutoff_hours
