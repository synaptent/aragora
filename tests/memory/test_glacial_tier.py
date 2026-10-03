"""
Tests for ContinuumGlacialMixin - glacial tier operations.

Tests the 5 methods in aragora/memory/continuum_glacial.py:
- get_glacial_insights() / get_glacial_insights_async()
- get_cross_session_patterns() / get_cross_session_patterns_async()
- get_glacial_tier_stats()

These methods enable cross-session learning by retrieving long-term patterns
from the glacial tier (30-day half-life foundational knowledge).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from aragora.memory.continuum import ContinuumMemory
from aragora.memory.tier_manager import MemoryTier


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    os.unlink(db_path)


@pytest.fixture
def cms(temp_db):
    """Create a ContinuumMemory instance with temp database."""
    return ContinuumMemory(db_path=temp_db)


@pytest.fixture
def populated_glacial_cms(cms):
    """Create CMS with sample glacial tier entries for testing."""
    # Add glacial tier entries with varying importance and topics
    cms.add(
        "glacial-1",
        "Error handling best practices for Python exceptions",
        tier=MemoryTier.GLACIAL,
        importance=0.9,
        metadata={"tags": ["error", "python"]},
    )
    cms.add(
        "glacial-2",
        "Performance optimization patterns for databases",
        tier=MemoryTier.GLACIAL,
        importance=0.7,
        metadata={"tags": ["performance", "database"]},
    )
    cms.add(
        "glacial-3",
        "Error recovery strategies in distributed systems",
        tier=MemoryTier.GLACIAL,
        importance=0.5,
        metadata={"tags": ["error", "distributed"]},
    )
    cms.add(
        "glacial-4",
        "API design principles for RESTful services",
        tier=MemoryTier.GLACIAL,
        importance=0.2,
        metadata={"tags": ["api", "rest"]},
    )

    # Add slow tier entries for cross-session tests
    cms.add(
        "slow-1",
        "Recent code refactoring patterns",
        tier=MemoryTier.SLOW,
        importance=0.8,
        metadata={"tags": ["code", "refactoring"]},
    )
    cms.add(
        "slow-2",
        "Error logging improvements",
        tier=MemoryTier.SLOW,
        importance=0.6,
        metadata={"tags": ["error", "logging"]},
    )

    # Add fast/medium entries (should not appear in glacial queries)
    cms.add("fast-1", "Immediate error context", tier=MemoryTier.FAST, importance=0.9)
    cms.add("medium-1", "Round-level tactical insight", tier=MemoryTier.MEDIUM, importance=0.8)

    return cms


@pytest.fixture
def cms_with_red_line(cms):
    """Create CMS with a red-line protected glacial entry."""
    cms.add(
        "glacial-protected",
        "Critical safety constraint",
        tier=MemoryTier.GLACIAL,
        importance=0.95,
    )
    # Set red_line flag directly in database
    with sqlite3.connect(cms.db_path) as conn:
        conn.execute(
            "UPDATE continuum_memory SET red_line = 1, red_line_reason = ? WHERE id = ?",
            ("Safety critical", "glacial-protected"),
        )
    return cms


# =============================================================================
# TestGetGlacialInsights - Basic Functionality
# =============================================================================


class TestGetGlacialInsights:
    """Tests for get_glacial_insights() method."""

    def test_returns_only_glacial_tier_entries(self, populated_glacial_cms):
        """Verify get_glacial_insights returns only entries from glacial tier."""
        insights = populated_glacial_cms.get_glacial_insights()

        assert len(insights) > 0
        for entry in insights:
            assert entry.tier == MemoryTier.GLACIAL

    def test_filters_by_topic(self, populated_glacial_cms):
        """Verify topic parameter filters entries by keyword match."""
        insights = populated_glacial_cms.get_glacial_insights(topic="error")

        assert len(insights) >= 1
        for entry in insights:
            assert "error" in entry.content.lower()

    def test_respects_limit_parameter(self, populated_glacial_cms):
        """Verify limit parameter restricts result count."""
        insights = populated_glacial_cms.get_glacial_insights(limit=2)

        assert len(insights) <= 2

    def test_default_min_importance_is_0_3(self, populated_glacial_cms):
        """Verify default min_importance of 0.3 filters low importance entries."""
        insights = populated_glacial_cms.get_glacial_insights()

        # glacial-4 has importance=0.2, should be excluded
        ids = [e.id for e in insights]
        assert "glacial-4" not in ids

    def test_custom_min_importance_threshold(self, populated_glacial_cms):
        """Verify custom min_importance filters appropriately."""
        insights = populated_glacial_cms.get_glacial_insights(min_importance=0.8)

        assert len(insights) == 1
        assert insights[0].id == "glacial-1"
        assert insights[0].importance >= 0.8

    def test_min_importance_zero_includes_all(self, populated_glacial_cms):
        """Verify min_importance=0 includes all glacial entries."""
        insights = populated_glacial_cms.get_glacial_insights(min_importance=0.0)

        assert len(insights) == 4  # All 4 glacial entries

    def test_empty_tier_returns_empty_list(self, cms):
        """Verify returns empty list when glacial tier has no entries."""
        insights = cms.get_glacial_insights()

        assert insights == []

    def test_no_topic_match_returns_empty(self, populated_glacial_cms):
        """Verify returns empty list when topic matches no entries."""
        insights = populated_glacial_cms.get_glacial_insights(topic="nonexistent_xyz")

        assert insights == []


# =============================================================================
# TestGetGlacialInsightsAsync - Async Wrapper
# =============================================================================


class TestGetGlacialInsightsAsync:
    """Tests for get_glacial_insights_async() async wrapper."""

    @pytest.mark.asyncio
    async def test_async_returns_same_as_sync(self, populated_glacial_cms):
        """Verify async method returns same results as sync version."""
        sync_insights = populated_glacial_cms.get_glacial_insights(topic="error")
        async_insights = await populated_glacial_cms.get_glacial_insights_async(topic="error")

        assert len(async_insights) == len(sync_insights)
        sync_ids = {e.id for e in sync_insights}
        async_ids = {e.id for e in async_insights}
        assert sync_ids == async_ids

    @pytest.mark.asyncio
    async def test_async_with_all_parameters(self, populated_glacial_cms):
        """Verify async passes all parameters correctly."""
        insights = await populated_glacial_cms.get_glacial_insights_async(
            topic="performance", limit=5, min_importance=0.5
        )

        assert len(insights) >= 1
        assert all(e.importance >= 0.5 for e in insights)


# =============================================================================
# TestGetCrossSessionPatterns - Combined Slow + Glacial
# =============================================================================


class TestGetCrossSessionPatterns:
    """Tests for get_cross_session_patterns() method."""

    def test_returns_glacial_and_slow_tiers(self, populated_glacial_cms):
        """Verify returns entries from both glacial and slow tiers by default."""
        patterns = populated_glacial_cms.get_cross_session_patterns()

        tiers = {e.tier for e in patterns}
        assert MemoryTier.GLACIAL in tiers
        assert MemoryTier.SLOW in tiers

    def test_excludes_fast_and_medium_tiers(self, populated_glacial_cms):
        """Verify fast and medium tier entries are excluded."""
        patterns = populated_glacial_cms.get_cross_session_patterns()

        ids = [e.id for e in patterns]
        assert "fast-1" not in ids
        assert "medium-1" not in ids

    def test_include_slow_false_returns_only_glacial(self, populated_glacial_cms):
        """Verify include_slow=False excludes slow tier entries."""
        patterns = populated_glacial_cms.get_cross_session_patterns(include_slow=False)

        for entry in patterns:
            assert entry.tier == MemoryTier.GLACIAL

    def test_domain_filter_applies_keyword_matching(self, populated_glacial_cms):
        """Verify domain parameter filters by keyword."""
        patterns = populated_glacial_cms.get_cross_session_patterns(domain="error")

        for entry in patterns:
            assert "error" in entry.content.lower()

    def test_results_sorted_by_importance_descending(self, populated_glacial_cms):
        """Verify results are sorted by importance (highest first)."""
        patterns = populated_glacial_cms.get_cross_session_patterns()

        importances = [e.importance for e in patterns]
        assert importances == sorted(importances, reverse=True)

    def test_respects_limit_parameter(self, populated_glacial_cms):
        """Verify limit parameter restricts result count."""
        patterns = populated_glacial_cms.get_cross_session_patterns(limit=3)

        assert len(patterns) <= 3

    def test_default_min_importance_is_0_2(self, populated_glacial_cms):
        """Verify default min_importance of 0.2 is applied."""
        # glacial-4 has importance=0.2, should be included with default 0.2 threshold
        patterns = populated_glacial_cms.get_cross_session_patterns()

        ids = [e.id for e in patterns]
        assert "glacial-4" in ids


# =============================================================================
# TestGetCrossSessionPatternsAsync - Async Wrapper
# =============================================================================


class TestGetCrossSessionPatternsAsync:
    """Tests for get_cross_session_patterns_async() async wrapper."""

    @pytest.mark.asyncio
    async def test_async_returns_same_as_sync(self, populated_glacial_cms):
        """Verify async method returns same results as sync version."""
        sync_patterns = populated_glacial_cms.get_cross_session_patterns(domain="error")
        async_patterns = await populated_glacial_cms.get_cross_session_patterns_async(
            domain="error"
        )

        sync_ids = {e.id for e in sync_patterns}
        async_ids = {e.id for e in async_patterns}
        assert sync_ids == async_ids

    @pytest.mark.asyncio
    async def test_async_with_include_slow_false(self, populated_glacial_cms):
        """Verify async passes include_slow parameter correctly."""
        patterns = await populated_glacial_cms.get_cross_session_patterns_async(include_slow=False)

        for entry in patterns:
            assert entry.tier == MemoryTier.GLACIAL


# =============================================================================
# TestGetGlacialTierStats - SQL Aggregations
# =============================================================================


class TestGetGlacialTierStats:
    """Tests for get_glacial_tier_stats() SQL aggregation method."""

    def test_returns_tier_name(self, cms):
        """Verify stats include tier identifier."""
        stats = cms.get_glacial_tier_stats()

        assert stats["tier"] == "glacial"

    def test_empty_tier_returns_zero_counts(self, cms):
        """Verify empty glacial tier returns zero for all counts."""
        stats = cms.get_glacial_tier_stats()

        assert stats["count"] == 0
        assert stats["avg_importance"] == 0
        assert stats["avg_surprise"] == 0
        assert stats["red_line_count"] == 0

    def test_count_reflects_glacial_entries_only(self, populated_glacial_cms):
        """Verify count only includes glacial tier entries."""
        stats = populated_glacial_cms.get_glacial_tier_stats()

        assert stats["count"] == 4  # Only glacial entries, not slow/fast/medium

    def test_avg_importance_calculated_correctly(self, populated_glacial_cms):
        """Verify avg_importance is correctly aggregated."""
        stats = populated_glacial_cms.get_glacial_tier_stats()

        # glacial entries: 0.9, 0.7, 0.5, 0.2 -> avg = 0.575
        assert abs(stats["avg_importance"] - 0.575) < 0.01

    def test_red_line_count_tracks_protected_entries(self, cms_with_red_line):
        """Verify red_line_count counts protected entries."""
        stats = cms_with_red_line.get_glacial_tier_stats()

        assert stats["red_line_count"] == 1

    def test_utilization_calculated_against_max_entries(self, populated_glacial_cms):
        """Verify utilization is count / max_entries_per_tier['glacial']."""
        stats = populated_glacial_cms.get_glacial_tier_stats()

        max_glacial = populated_glacial_cms.hyperparams["max_entries_per_tier"]["glacial"]
        expected_utilization = 4 / max_glacial
        assert abs(stats["utilization"] - expected_utilization) < 0.001

    def test_top_tags_extracted_from_metadata(self, populated_glacial_cms):
        """Verify top_tags extracts and counts tags from metadata."""
        stats = populated_glacial_cms.get_glacial_tier_stats()

        # "error" tag appears in glacial-1 and glacial-3
        tag_names = [t["tag"] for t in stats["top_tags"]]
        assert "error" in tag_names

    def test_oldest_and_newest_timestamps_populated(self, populated_glacial_cms):
        """Verify oldest_entry and newest_update timestamps are returned."""
        stats = populated_glacial_cms.get_glacial_tier_stats()

        assert stats["oldest_entry"] is not None
        assert stats["newest_update"] is not None


# =============================================================================
# TestGlacialTierIntegration - End-to-End Scenarios
# =============================================================================


class TestGlacialTierIntegration:
    """Integration tests for glacial tier operations with actual ContinuumMemory."""

    def test_glacial_insights_workflow(self, cms):
        """Test complete workflow: add glacial entries, retrieve insights, check stats."""
        # Add entries
        cms.add(
            "insight-1",
            "Machine learning model performance patterns",
            tier=MemoryTier.GLACIAL,
            importance=0.85,
        )
        cms.add(
            "insight-2",
            "Database query optimization techniques",
            tier=MemoryTier.GLACIAL,
            importance=0.75,
        )

        # Retrieve insights
        insights = cms.get_glacial_insights(topic="performance")
        assert len(insights) == 1
        assert "performance" in insights[0].content.lower()

        # Check stats
        stats = cms.get_glacial_tier_stats()
        assert stats["count"] == 2
        assert stats["avg_importance"] == 0.8

    def test_cross_session_pattern_discovery(self, cms):
        """Test discovering patterns across slow and glacial tiers."""
        # Slow tier: recent patterns
        cms.add(
            "recent-1",
            "New error handling approach",
            tier=MemoryTier.SLOW,
            importance=0.7,
        )

        # Glacial tier: foundational knowledge
        cms.add(
            "foundational-1",
            "Core error handling principles",
            tier=MemoryTier.GLACIAL,
            importance=0.9,
        )

        # Get cross-session patterns for "error"
        patterns = cms.get_cross_session_patterns(domain="error")

        # Should find both
        ids = [p.id for p in patterns]
        assert "recent-1" in ids
        assert "foundational-1" in ids

        # Should be sorted by importance
        assert patterns[0].id == "foundational-1"  # Higher importance

    def test_glacial_methods_exclude_non_glacial_data(self, cms):
        """Verify glacial methods properly isolate glacial tier."""
        # Add entries in all tiers
        cms.add("fast", "Fast tier content", tier=MemoryTier.FAST, importance=0.9)
        cms.add("medium", "Medium tier content", tier=MemoryTier.MEDIUM, importance=0.9)
        cms.add("slow", "Slow tier content", tier=MemoryTier.SLOW, importance=0.9)
        cms.add("glacial", "Glacial tier content", tier=MemoryTier.GLACIAL, importance=0.9)

        # get_glacial_insights should only return glacial
        insights = cms.get_glacial_insights(min_importance=0.0)
        assert len(insights) == 1
        assert insights[0].tier == MemoryTier.GLACIAL

        # get_glacial_tier_stats should only count glacial
        stats = cms.get_glacial_tier_stats()
        assert stats["count"] == 1


# =============================================================================
# TestGlacialBackend - New Backend Implementation Tests
# =============================================================================


class TestGlacialBackend:
    """Tests for the glacial tier backend implementation."""

    def test_glacial_connection_context_manager(self, cms):
        """Test _glacial_connection() provides working SQLite connection."""
        # The mixin's _glacial_connection should work standalone
        with cms._glacial_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1

    def test_glacial_retrieve_returns_only_glacial_tier(self, populated_glacial_cms):
        """Test _glacial_retrieve() returns only glacial tier entries."""
        entries = populated_glacial_cms._glacial_retrieve(limit=10)

        assert len(entries) > 0
        for entry in entries:
            assert entry.tier == MemoryTier.GLACIAL

    def test_glacial_retrieve_filters_by_query(self, populated_glacial_cms):
        """Test _glacial_retrieve() filters by keyword query."""
        entries = populated_glacial_cms._glacial_retrieve(query="error", limit=10)

        assert len(entries) >= 1
        for entry in entries:
            assert "error" in entry.content.lower()

    def test_glacial_retrieve_respects_min_importance(self, populated_glacial_cms):
        """Test _glacial_retrieve() filters by minimum importance."""
        entries = populated_glacial_cms._glacial_retrieve(min_importance=0.8, limit=10)

        for entry in entries:
            assert entry.importance >= 0.8

    def test_glacial_retrieve_respects_limit(self, populated_glacial_cms):
        """Test _glacial_retrieve() respects limit parameter."""
        entries = populated_glacial_cms._glacial_retrieve(limit=2)

        assert len(entries) <= 2

    def test_glacial_retrieve_applies_decay_scoring(self, cms):
        """Test _glacial_retrieve() applies 30-day half-life decay to scoring."""
        # Add a glacial entry
        cms.add(
            "decay_test",
            "Test entry for decay",
            tier=MemoryTier.GLACIAL,
            importance=0.9,
        )

        # Retrieve with decay scoring
        entries = cms._glacial_retrieve(limit=10)

        # Entry should be returned (decay is applied in scoring, not filtering)
        assert len(entries) == 1
        assert entries[0].id == "decay_test"


class TestGlacialConfidenceDecay:
    """Tests for calculate_glacial_decay() method."""

    def test_decay_factor_is_one_for_just_updated(self, cms):
        """Test decay factor is 1.0 for entries updated now."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        decay = cms.calculate_glacial_decay(now)

        assert abs(decay - 1.0) < 0.01

    def test_decay_factor_is_half_at_30_days(self, cms):
        """Test decay factor is 0.5 at exactly 30 days old."""
        from datetime import datetime, timedelta, timezone

        thirty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        decay = cms.calculate_glacial_decay(thirty_days_ago)

        assert abs(decay - 0.5) < 0.01

    def test_decay_factor_is_quarter_at_60_days(self, cms):
        """Test decay factor is 0.25 at 60 days old (two half-lives)."""
        from datetime import datetime, timedelta, timezone

        sixty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)
        decay = cms.calculate_glacial_decay(sixty_days_ago)

        assert abs(decay - 0.25) < 0.01

    def test_decay_handles_string_timestamp(self, cms):
        """Test decay calculation handles ISO string timestamps."""
        from datetime import datetime, timedelta, timezone

        thirty_days_ago = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        ).isoformat()
        decay = cms.calculate_glacial_decay(thirty_days_ago)

        assert abs(decay - 0.5) < 0.01

    def test_decay_clamps_to_one_for_future_timestamps(self, cms):
        """Test decay factor is clamped to 1.0 for future timestamps."""
        from datetime import datetime, timedelta, timezone

        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
        decay = cms.calculate_glacial_decay(future)

        assert decay == 1.0


class TestGlacialBackendStandalone:
    """Tests for standalone glacial backend usage (without full ContinuumMemory)."""

    def test_standalone_glacial_db_path_environment(self, tmp_path):
        """Test standalone glacial connection uses environment variable."""
        import os
        from aragora.memory.continuum_glacial import ContinuumGlacialMixin

        # Create a standalone mixin instance
        class StandaloneGlacialStore(ContinuumGlacialMixin):
            hyperparams: dict = {"max_entries_per_tier": {"glacial": 50000}}

        store = StandaloneGlacialStore()
        db_path = str(tmp_path / "glacial_standalone.db")
        store._glacial_db_path = db_path

        # Test connection works
        with store._glacial_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sqlite_version()")
            version = cursor.fetchone()
            assert version is not None

        # Verify database was created
        assert os.path.exists(db_path)

    def test_glacial_retrieve_empty_database(self, tmp_path):
        """Test _glacial_retrieve() on empty database returns empty list."""
        from aragora.memory.continuum_glacial import ContinuumGlacialMixin

        class StandaloneGlacialStore(ContinuumGlacialMixin):
            hyperparams: dict = {"max_entries_per_tier": {"glacial": 50000}}

        store = StandaloneGlacialStore()
        store._glacial_db_path = str(tmp_path / "empty_glacial.db")

        # Create schema manually for standalone test
        with store._glacial_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS continuum_memory (
                    id TEXT PRIMARY KEY,
                    tier TEXT NOT NULL DEFAULT 'slow',
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    surprise_score REAL DEFAULT 0.0,
                    consolidation_score REAL DEFAULT 0.0,
                    update_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT DEFAULT '{}',
                    red_line INTEGER DEFAULT 0,
                    red_line_reason TEXT DEFAULT ''
                )
            """)
            conn.commit()

        entries = store._glacial_retrieve(limit=10)
        assert entries == []
