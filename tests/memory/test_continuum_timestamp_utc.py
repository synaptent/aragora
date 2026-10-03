"""Timestamp UTC-consistency regression tests for continuum memory tiers.

Python-side timestamps must be UTC to match SQLite's ``julianday('now')``.

Continuum rows are decay-ranked, TTL-pruned, and cooldown-gated with UTC
``julianday('now')`` / ``datetime('now')`` comparisons, so naive local-time
stamps skew retention and retrieval math by the machine's UTC offset (the
same bug family fixed for CritiqueStore patterns in
tests/memory/test_store.py::TestTimestampUTCConsistency, see PR #9311).

Tests pin far-from-UTC, DST-free timezones via time.tzset() so the skew is
deterministic on any runner:
- Pacific/Kiritimati (UTC+14): local stamps would look ~14h in the future
- Etc/GMT+12 (UTC-12, POSIX inverted sign): local stamps would look ~12h old,
  which under the old code made fresh fast-tier rows (2h TTL) expire on sight
"""

import os
import time

import pytest

from aragora.memory.continuum import (
    ContinuumMemory,
    reset_continuum_memory,
)
from aragora.memory.continuum.coordinator import ContinuumMemory as CoordinatorContinuumMemory
from aragora.memory.continuum_stats import cleanup_expired_memories
from aragora.memory.tier_manager import (
    MemoryTier,
    TierManager,
    reset_tier_manager,
)
from aragora.utils.datetime_helpers import utc_now_iso_naive

# Freshly written stamps must agree with SQLite's UTC clock within this many
# seconds. Any local-time stamp would be off by whole hours (>= 3600s).
MAX_SKEW_SECONDS = 300


def _pin_timezone(tz: str):
    """Force a specific process-local timezone; restores the old one after."""
    if not hasattr(time, "tzset"):
        pytest.skip("requires time.tzset (POSIX)")
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        yield
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


@pytest.fixture
def positive_offset_timezone():
    """UTC+14, no DST: local stamps would lead julianday('now') by 14h."""
    yield from _pin_timezone("Pacific/Kiritimati")


@pytest.fixture
def negative_offset_timezone():
    """UTC-12, no DST: local stamps would trail julianday('now') by 12h."""
    yield from _pin_timezone("Etc/GMT+12")


@pytest.fixture
def memory(tmp_path):
    """Package (core) ContinuumMemory with an isolated database."""
    reset_tier_manager()
    reset_continuum_memory()
    cms = ContinuumMemory(
        db_path=str(tmp_path / "test_tz_core.db"),
        tier_manager=TierManager(),
    )
    yield cms
    reset_tier_manager()
    reset_continuum_memory()


@pytest.fixture
def coordinator_memory(tmp_path):
    """Coordinator ContinuumMemory (tier-mixin store_* API) with isolated db."""
    reset_tier_manager()
    reset_continuum_memory()
    cms = CoordinatorContinuumMemory(
        db_path=str(tmp_path / "test_tz_coordinator.db"),
        tier_manager=TierManager(),
    )
    yield cms
    reset_tier_manager()
    reset_continuum_memory()


def _age_seconds(cms, memory_id: str, column: str = "updated_at") -> float:
    """Age of a row's timestamp as SQLite's UTC clock sees it."""
    assert column in {"created_at", "updated_at", "last_promotion_at"}
    with cms.connection() as conn:
        row = conn.execute(
            f"SELECT (julianday('now') - julianday({column})) * 86400.0 "
            "FROM continuum_memory WHERE id = ?",  # noqa: S608 -- column from whitelist above
            (memory_id,),
        ).fetchone()
    assert row is not None and row[0] is not None
    return row[0]


class TestContinuumTimestampUTCConsistency:
    """Fresh continuum rows must not appear hours old/new to julianday."""

    def test_add_stamps_utc_all_tiers(self, memory, positive_offset_timezone):
        for tier in MemoryTier:
            memory_id = f"add-{tier.value}"
            memory.add(memory_id, f"{tier.value} entry", tier=tier, importance=0.5)
            for column in ("created_at", "updated_at"):
                age = _age_seconds(memory, memory_id, column)
                assert abs(age) < MAX_SKEW_SECONDS, (
                    f"{tier.value} {column} skewed by {age:.0f}s vs UTC"
                )

    def test_tier_store_methods_stamp_utc(self, coordinator_memory, positive_offset_timezone):
        stores = {
            "fast": coordinator_memory.store_fast,
            "medium": coordinator_memory.store_medium,
            "slow": coordinator_memory.store_slow,
            "glacial": coordinator_memory.store_glacial,
        }
        for tier_name, store in stores.items():
            memory_id = f"store-{tier_name}"
            store(memory_id, f"{tier_name} entry", importance=0.5)
            age = _age_seconds(coordinator_memory, memory_id)
            assert abs(age) < MAX_SKEW_SECONDS, (
                f"store_{tier_name} updated_at skewed by {age:.0f}s vs UTC"
            )

    def test_update_entry_stamps_utc(self, memory, positive_offset_timezone):
        memory.add("upd-1", "entry", tier=MemoryTier.MEDIUM, importance=0.5)
        entry = memory.get("upd-1")
        assert entry is not None
        entry.success_count += 1
        assert memory.update_entry(entry)

        age = _age_seconds(memory, "upd-1")
        assert abs(age) < MAX_SKEW_SECONDS, f"updated_at skewed by {age:.0f}s vs UTC"

    def test_fresh_fast_entry_survives_cleanup(self, memory, negative_offset_timezone):
        """A just-written fast-tier row (2h TTL) must never expire on sight.

        Under local-time stamping at UTC-12, the fresh row looked 12 hours
        old to the UTC cutoff and was archived immediately.
        """
        memory.add("fresh-fast", "fast entry", tier=MemoryTier.FAST, importance=0.5)

        result = cleanup_expired_memories(memory, tier=MemoryTier.FAST)

        assert result["archived"] == 0
        assert result["deleted"] == 0
        assert memory.get("fresh-fast") is not None

    def test_promotion_cooldown_respects_utc_stamp(self, positive_offset_timezone):
        """A promotion stamped 'just now' in UTC must be inside the cooldown.

        Under the old local-time comparison at UTC+14, a fresh UTC stamp
        looked 14 hours old, so a 2h cooldown appeared long expired.
        """
        manager = TierManager(promotion_cooldown_hours=2.0)
        allowed = manager.should_promote(
            MemoryTier.MEDIUM,
            surprise_score=0.9,  # above the medium promotion threshold
            last_promotion_at=utc_now_iso_naive(),
        )
        assert allowed is False

    def test_calculate_glacial_decay_fresh_entry(self, memory, negative_offset_timezone):
        """A fresh naive-UTC stamp must show (almost) no glacial decay.

        Under local-time 'now' at UTC-12, a fresh UTC stamp looked 12 hours
        old and already decayed to ~0.989.
        """
        decay = memory.calculate_glacial_decay(utc_now_iso_naive())
        assert decay >= 0.999

    def test_legacy_current_timestamp_rows_compatible(self, memory, positive_offset_timezone):
        """Rows stamped by SQLite's CURRENT_TIMESTAMP default stay compatible.

        CURRENT_TIMESTAMP writes naive UTC 'YYYY-MM-DD HH:MM:SS' strings; both
        julianday aging and datetime.fromisoformat consumers must handle them.
        """
        with memory.connection() as conn:
            conn.execute(
                """
                INSERT INTO continuum_memory (id, tier, content, importance)
                VALUES ('legacy-1', 'glacial', 'legacy row', 0.5)
                """
            )
            conn.commit()

        age = _age_seconds(memory, "legacy-1")
        assert abs(age) < MAX_SKEW_SECONDS, f"CURRENT_TIMESTAMP row skewed by {age:.0f}s"

        entry = memory.get("legacy-1")
        assert entry is not None
        assert memory.calculate_glacial_decay(entry.updated_at) >= 0.999
