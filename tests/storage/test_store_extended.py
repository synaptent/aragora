"""
Extended tests for SQLite-based critique pattern store.

Tests cover gaps not in test_memory_store.py:
- Pattern storage with null/edge case fields
- Agent reputation concurrent updates and edge cases
- Debate storage with grounded_verdict
- Pattern pruning with 100% success rate
- Database connection handling under load
- Statistics with corrupted or zero data
"""

import json
import os
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from aragora.core import Critique, DebateResult
from aragora.memory.store import AgentReputation, CritiqueStore, Pattern


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def store(temp_db):
    """Create a CritiqueStore with temporary database."""
    # Clear the global cache to prevent cross-test contamination
    from aragora.server.handlers.base import clear_cache

    clear_cache()
    return CritiqueStore(db_path=temp_db)


@pytest.fixture
def sample_critique():
    """Create a sample critique for testing."""
    return Critique(
        agent="claude",
        target_agent="gpt4",
        target_content="Code to review",
        issues=["Performance issue: slow query"],
        suggestions=["Add an index"],
        severity=0.7,
        reasoning="Query takes too long",
    )


@pytest.fixture
def grounded_verdict():
    """Create a mock grounded verdict."""
    mock = MagicMock()
    mock.to_dict.return_value = {
        "verdict": "supported",
        "evidence": ["source1", "source2"],
        "citations": [{"url": "http://example.com"}],
        "grounding_score": 0.85,
    }
    return mock


# =============================================================================
# Pattern Storage Extended Tests
# =============================================================================


class TestPatternStorageExtended:
    """Extended tests for pattern storage operations."""

    def test_store_pattern_empty_suggestions(self, store):
        """Test storing pattern with empty suggestions list."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["Issue with no suggestion"],
            suggestions=[],  # Empty
            severity=0.5,
            reasoning="",
        )

        store.store_pattern(critique, "fix")

        patterns = store.retrieve_patterns(min_success=1)
        assert len(patterns) >= 1
        assert patterns[0].suggestion_text == ""

    def test_store_pattern_multiple_issues(self, store):
        """Test storing critique with multiple issues creates multiple patterns."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["Issue one", "Issue two", "Issue three"],
            suggestions=["Fix one"],
            severity=0.6,
            reasoning="",
        )

        store.store_pattern(critique, "fix")

        patterns = store.retrieve_patterns(min_success=1)
        assert len(patterns) == 3  # One per issue

    def test_store_pattern_very_long_example_task(self, store):
        """Test that long example_task is truncated."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["test issue"],
            suggestions=["fix"],
            severity=0.5,
            reasoning="",
        )

        long_fix = "x" * 1000
        store.store_pattern(critique, long_fix)

        patterns = store.retrieve_patterns(min_success=1)
        assert len(patterns[0].example_task) <= 500

    def test_store_pattern_special_characters(self, store):
        """Test storing pattern with special characters."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["Issue with 'quotes' and \"double quotes\""],
            suggestions=["Fix with; semicolon"],
            severity=0.5,
            reasoning="",
        )

        store.store_pattern(critique, "fix")

        patterns = store.retrieve_patterns(min_success=1)
        assert "quotes" in patterns[0].issue_text

    def test_store_pattern_unicode(self, store):
        """Test storing pattern with unicode characters."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["Issue with emoji 🔥 and unicode ñ"],
            suggestions=["Fix with symbols ★"],
            severity=0.5,
            reasoning="",
        )

        store.store_pattern(critique, "fix")

        patterns = store.retrieve_patterns(min_success=1)
        assert "🔥" in patterns[0].issue_text or "emoji" in patterns[0].issue_text

    def test_fail_pattern_nonexistent(self, store):
        """Test failing a pattern that doesn't exist (no error)."""
        # Should not raise
        store.fail_pattern("nonexistent issue text")

        # Verify no patterns were created
        patterns = store.retrieve_patterns(min_success=0)
        assert all("nonexistent" not in p.issue_text for p in patterns)

    def test_concurrent_pattern_upsert(self, store):
        """Test concurrent upserts to same pattern."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["concurrent test issue"],
            suggestions=["fix"],
            severity=0.5,
            reasoning="",
        )

        def store_pattern():
            for _ in range(10):
                store.store_pattern(critique, "fix")

        threads = [threading.Thread(target=store_pattern) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        patterns = store.retrieve_patterns(min_success=1)
        matching = [p for p in patterns if "concurrent test issue" in p.issue_text]
        assert len(matching) == 1
        assert matching[0].success_count == 50  # 5 threads * 10 iterations


# =============================================================================
# Agent Reputation Extended Tests
# =============================================================================


class TestAgentReputationExtended:
    """Extended tests for agent reputation tracking."""

    def test_vote_weight_boundary_high(self):
        """Test vote weight at upper boundary (1.6)."""
        rep = AgentReputation(
            agent_name="perfect",
            proposals_made=100,
            proposals_accepted=100,
            critiques_given=100,
            critiques_valuable=100,
            calibration_score=1.0,  # Max calibration
        )
        # Score = 1.0, base_weight = 1.5, calibration_bonus = 0.1
        assert rep.vote_weight == 1.6

    def test_vote_weight_boundary_low(self):
        """Test vote weight at lower boundary (0.4)."""
        rep = AgentReputation(
            agent_name="terrible",
            proposals_made=100,
            proposals_accepted=0,
            critiques_given=100,
            critiques_valuable=0,
            calibration_score=0.0,  # Min calibration
        )
        # Score = 0.0, base_weight = 0.5, calibration_penalty = -0.1
        assert rep.vote_weight == 0.4

    def test_vote_weight_negative_calibration(self):
        """Test vote weight doesn't go below 0.4 with negative values."""
        rep = AgentReputation(
            agent_name="bad",
            proposals_made=100,
            proposals_accepted=0,
            critiques_given=100,
            critiques_valuable=0,
            calibration_score=-1.0,  # Invalid but test boundary
        )
        # Should be clamped to 0.4 minimum
        assert rep.vote_weight >= 0.4

    def test_concurrent_reputation_updates(self, store):
        """Test concurrent reputation updates don't corrupt data."""

        def update_proposals():
            for _ in range(20):
                store.update_reputation("concurrent_agent", proposal_made=True)

        def update_critiques():
            for _ in range(20):
                store.update_reputation("concurrent_agent", critique_given=True)

        threads = [
            threading.Thread(target=update_proposals),
            threading.Thread(target=update_critiques),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        rep = store.get_reputation("concurrent_agent")
        assert rep is not None
        assert rep.proposals_made == 20
        assert rep.critiques_given == 20

    def test_update_reputation_no_changes(self, store):
        """Test update_reputation with no flags does nothing."""
        store.update_reputation("test_agent", proposal_made=True)
        initial_rep = store.get_reputation("test_agent")

        # Call with no flags
        store.update_reputation("test_agent")

        final_rep = store.get_reputation("test_agent")
        assert final_rep.proposals_made == initial_rep.proposals_made

    def test_get_all_reputations_ordering(self, store):
        """Test reputations are ordered by proposals_accepted DESC."""
        store.update_reputation("low_agent", proposal_made=True)
        store.update_reputation("medium_agent", proposal_made=True, proposal_accepted=True)
        store.update_reputation("high_agent", proposal_made=True, proposal_accepted=True)
        store.update_reputation("high_agent", proposal_made=True, proposal_accepted=True)

        reps = store.get_all_reputations()
        accepted_counts = [r.proposals_accepted for r in reps]

        # Should be descending
        assert accepted_counts == sorted(accepted_counts, reverse=True)


# =============================================================================
# Calibration Extended Tests
# =============================================================================


class TestCalibrationExtended:
    """Extended tests for calibration scoring."""

    def test_calibration_convergence_multiple_predictions(self, store):
        """Test calibration converges with multiple predictions."""
        # Create debate with critique
        critique = Critique(
            agent="calibration_agent",
            target_agent="t",
            target_content="code",
            issues=["test"],
            suggestions=["fix"],
            severity=0.5,
            reasoning="",
        )
        result = DebateResult(
            id="cal_debate",
            task="test",
            final_answer="answer",
            consensus_reached=True,
            confidence=0.8,
            rounds_used=1,
            duration_seconds=1.0,
            critiques=[critique],
        )
        store.store_debate(result)

        # Get critique ID
        with store._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM critiques WHERE debate_id = ?", ("cal_debate",))
            critique_id = cursor.fetchone()[0]

        # Make multiple perfect predictions
        for _ in range(5):
            store.update_prediction_outcome(critique_id, 0.5, "calibration_agent")

        rep = store.get_reputation("calibration_agent")
        assert rep.total_predictions == 5
        assert rep.calibration_score == pytest.approx(1.0, rel=0.01)

    def test_update_prediction_outcome_invalid_critique_id(self, store):
        """Test update with invalid critique ID returns 0.0."""
        error = store.update_prediction_outcome(9999, 0.8, "agent")
        assert error == 0.0

    def test_calibration_without_agent_name(self, store):
        """Test update_prediction_outcome uses critique's agent if none provided."""
        critique = Critique(
            agent="original_agent",
            target_agent="t",
            target_content="code",
            issues=["test"],
            suggestions=["fix"],
            severity=0.5,
            reasoning="",
        )
        result = DebateResult(
            id="cal_debate2",
            task="test",
            final_answer="answer",
            consensus_reached=True,
            confidence=0.8,
            rounds_used=1,
            duration_seconds=1.0,
            critiques=[critique],
        )
        store.store_debate(result)

        with store._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM critiques WHERE debate_id = ?", ("cal_debate2",))
            critique_id = cursor.fetchone()[0]

        # Update without agent_name - should use "original_agent"
        store.update_prediction_outcome(critique_id, 0.5)

        rep = store.get_reputation("original_agent")
        assert rep is not None
        assert rep.total_predictions == 1


# =============================================================================
# Debate Storage Extended Tests
# =============================================================================


class TestDebateStorageExtended:
    """Extended tests for debate storage."""

    def test_store_debate_with_grounded_verdict(self, store, grounded_verdict):
        """Test storing debate with grounded_verdict."""
        result = DebateResult(
            id="grounded_debate",
            task="Verify claim",
            final_answer="Claim is true",
            consensus_reached=True,
            confidence=0.9,
            rounds_used=2,
            duration_seconds=30.0,
            critiques=[],
            grounded_verdict=grounded_verdict,
        )

        store.store_debate(result)

        with store._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT grounded_verdict FROM debates WHERE id = ?", ("grounded_debate",)
            )
            row = cursor.fetchone()
            assert row is not None
            verdict_data = json.loads(row[0])
            assert verdict_data["verdict"] == "supported"
            assert verdict_data["grounding_score"] == 0.85

    def test_store_debate_grounded_verdict_no_to_dict(self, store):
        """Test storing debate when grounded_verdict has no to_dict method."""

        class BadVerdict:
            pass

        result = DebateResult(
            id="bad_verdict_debate",
            task="Test",
            final_answer="Answer",
            consensus_reached=True,
            confidence=0.8,
            rounds_used=1,
            duration_seconds=10.0,
            critiques=[],
            grounded_verdict=BadVerdict(),
        )

        # Should not raise
        store.store_debate(result)

        with store._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT grounded_verdict FROM debates WHERE id = ?", ("bad_verdict_debate",)
            )
            row = cursor.fetchone()
            assert row[0] is None

    def test_store_debate_many_critiques(self, store):
        """Test storing debate with many critiques."""
        critiques = [
            Critique(
                agent=f"agent{i}",
                target_agent="target",
                target_content="code",
                issues=[f"Issue {i}"],
                suggestions=[f"Fix {i}"],
                severity=0.5 + i * 0.01,
                reasoning=f"Reasoning {i}",
            )
            for i in range(100)
        ]

        result = DebateResult(
            id="many_critiques_debate",
            task="Big debate",
            final_answer="Consensus",
            consensus_reached=True,
            confidence=0.85,
            rounds_used=10,
            duration_seconds=600.0,
            critiques=critiques,
        )

        store.store_debate(result)

        stats = store.get_stats()
        assert stats["total_critiques"] >= 100

    def test_store_debate_replace_existing(self, store):
        """Test storing debate with same ID replaces existing."""
        result1 = DebateResult(
            id="replace_debate",
            task="Original",
            final_answer="Original answer",
            consensus_reached=False,
            confidence=0.5,
            rounds_used=1,
            duration_seconds=10.0,
            critiques=[],
        )
        store.store_debate(result1)

        result2 = DebateResult(
            id="replace_debate",  # Same ID
            task="Updated",
            final_answer="Updated answer",
            consensus_reached=True,
            confidence=0.9,
            rounds_used=5,
            duration_seconds=100.0,
            critiques=[],
        )
        store.store_debate(result2)

        stats = store.get_stats()
        # Should still be 1 debate (replaced)
        assert stats["total_debates"] == 1

    @pytest.mark.asyncio
    async def test_get_relevant_context_returns_similar_conclusions(self, store):
        """Returns conclusions from similar past debates for future prompts."""
        store.store_debate(
            DebateResult(
                id="redis-rate-limit",
                task="Should we adopt Redis-backed rate limiting for the API?",
                final_answer="Adopt a Redis-backed token bucket so limits are shared across nodes.",
                consensus_reached=True,
                confidence=0.91,
                rounds_used=3,
                duration_seconds=45.0,
                critiques=[],
            )
        )
        store.store_debate(
            DebateResult(
                id="branding",
                task="How should we choose a new brand color palette?",
                final_answer="Use a warmer accent palette with higher contrast.",
                consensus_reached=True,
                confidence=0.78,
                rounds_used=2,
                duration_seconds=20.0,
                critiques=[],
            )
        )
        store.store_debate(
            DebateResult(
                id="redis-no-consensus",
                task="Should we use Redis for API throttling?",
                final_answer="Try a local in-memory counter.",
                consensus_reached=False,
                confidence=0.4,
                rounds_used=4,
                duration_seconds=35.0,
                critiques=[],
            )
        )

        context = await store.get_relevant_context("Should the API use Redis rate limiting?")

        assert "Redis-backed token bucket" in context
        assert "brand color palette" not in context
        assert "local in-memory counter" not in context


# =============================================================================
# Pattern Pruning Extended Tests
# =============================================================================


def _backdate_patterns(store, days: int = 10) -> None:
    """Age all stored patterns using SQLite's own UTC clock.

    Patterns are stamped with local-time ``datetime.now()`` while
    ``prune_stale_patterns`` compares against UTC ``julianday('now')``, so a
    freshly written pattern can appear up to a millisecond (or, east of UTC,
    hours) in the future and dodge ``max_age_days=0`` pruning.
    """
    with store.connection() as conn:
        conn.execute(
            "UPDATE patterns SET updated_at = datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.commit()


class TestPatternPruningExtended:
    """Extended tests for pattern pruning."""

    def test_prune_patterns_100_percent_success_rate(self, store):
        """Test patterns with 100% success rate are not pruned."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["perfect pattern"],
            suggestions=["fix"],
            severity=0.5,
            reasoning="",
        )

        # Store many times (100% success rate)
        for _ in range(10):
            store.store_pattern(critique, "fix")

        _backdate_patterns(store)

        # Prune with high min_success_rate
        pruned = store.prune_stale_patterns(max_age_days=0, min_success_rate=0.5)

        # Should not prune (success_rate = 100% > 0.5)
        patterns = store.retrieve_patterns(min_success=1)
        assert any("perfect pattern" in p.issue_text for p in patterns)

    def test_prune_patterns_archive_created(self, store):
        """Test pruned patterns are archived."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["archive test pattern"],
            suggestions=["fix"],
            severity=0.5,
            reasoning="",
        )
        store.store_pattern(critique, "fix")

        # Add a failure to lower success rate
        store.fail_pattern("archive test pattern")
        store.fail_pattern("archive test pattern")
        store.fail_pattern("archive test pattern")

        _backdate_patterns(store)

        # Prune (success_rate = 1/4 = 0.25 < 0.5)
        pruned = store.prune_stale_patterns(max_age_days=0, min_success_rate=0.5, archive=True)
        assert pruned == 1

        archive_stats = store.get_archive_stats()
        assert archive_stats["total_archived"] >= 1

    def test_prune_patterns_no_archive(self, store):
        """Test pruning without archiving deletes permanently."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["no archive pattern"],
            suggestions=["fix"],
            severity=0.5,
            reasoning="",
        )
        store.store_pattern(critique, "fix")
        store.fail_pattern("no archive pattern")
        store.fail_pattern("no archive pattern")
        store.fail_pattern("no archive pattern")

        _backdate_patterns(store)

        initial_archive = store.get_archive_stats()["total_archived"]

        pruned = store.prune_stale_patterns(max_age_days=0, min_success_rate=0.5, archive=False)
        assert pruned == 1

        final_archive = store.get_archive_stats()["total_archived"]
        assert final_archive == initial_archive  # No new archives


# =============================================================================
# Database Connection Extended Tests
# =============================================================================


class TestDatabaseConnectionExtended:
    """Extended tests for database connection handling."""

    def test_many_rapid_connections(self, store):
        """Test many rapid connection acquisitions."""
        for _ in range(100):
            stats = store.get_stats()
            assert "total_debates" in stats

    def test_exception_in_connection_context(self, store):
        """Test connection is closed even on exception."""
        try:
            with store._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Should still be able to use store
        stats = store.get_stats()
        assert "total_debates" in stats

    def test_concurrent_reads_and_writes(self, store, sample_critique):
        """Test concurrent reads and writes don't deadlock."""

        def writer():
            for _ in range(20):
                store.store_pattern(sample_critique, "fix")
                time.sleep(0.001)

        def reader():
            for _ in range(20):
                store.retrieve_patterns(min_success=0)
                time.sleep(0.001)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # All threads should complete
        for t in threads:
            assert not t.is_alive()

    def test_store_with_high_concurrency(self, store):
        """Test store handles high concurrency."""

        def task(task_id):
            critique = Critique(
                agent=f"agent_{task_id}",
                target_agent="target",
                target_content="code",
                issues=[f"Issue from task {task_id}"],
                suggestions=["fix"],
                severity=0.5,
                reasoning="",
            )
            store.store_pattern(critique, "fix")
            store.update_reputation(f"agent_{task_id}", proposal_made=True)
            store.retrieve_patterns(min_success=0, limit=5)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(task, i) for i in range(50)]
            for f in futures:
                f.result(timeout=30)

        # Verify data integrity
        stats = store.get_stats()
        assert stats["total_patterns"] >= 50


# =============================================================================
# Statistics Extended Tests
# =============================================================================


class TestStatisticsExtended:
    """Extended tests for statistics retrieval."""

    def test_get_stats_empty_database(self, store):
        """Test stats on empty database."""
        stats = store.get_stats()

        assert stats["total_debates"] == 0
        assert stats["consensus_debates"] == 0
        assert stats["total_critiques"] == 0
        assert stats["total_patterns"] == 0
        assert stats["patterns_by_type"] == {}
        assert stats["avg_consensus_confidence"] == 0.0

    def test_get_stats_avg_confidence_calculation(self, store):
        """Test average confidence calculation."""
        for i in range(5):
            result = DebateResult(
                id=f"conf_debate_{i}",
                task="Test",
                final_answer="Answer",
                consensus_reached=True,
                confidence=0.6 + i * 0.05,  # 0.6, 0.65, 0.7, 0.75, 0.8
                rounds_used=1,
                duration_seconds=10.0,
                critiques=[],
            )
            store.store_debate(result)

        stats = store.get_stats()
        # Average of [0.6, 0.65, 0.7, 0.75, 0.8] = 0.7
        assert stats["avg_consensus_confidence"] == pytest.approx(0.7, rel=0.01)

    def test_get_stats_patterns_by_type(self, store):
        """Test patterns grouped by type."""
        # Use keywords that match the categorization
        type_issues = [
            ("performance", "slow performance issue"),
            ("security", "security vulnerability issue"),
            ("clarity", "unclear documentation issue"),
        ]
        for t, issue_text in type_issues:
            critique = Critique(
                agent="a",
                target_agent="b",
                target_content="code",
                issues=[issue_text],  # Will be categorized by keyword
                suggestions=["fix"],
                severity=0.5,
                reasoning="",
            )
            store.store_pattern(critique, "fix")
            store.store_pattern(critique, "fix")

        stats = store.get_stats()
        types = ["performance", "security", "clarity"]
        for t in types:
            assert t in stats["patterns_by_type"]
            assert stats["patterns_by_type"][t] >= 1

    def test_export_only_consensus_debates(self, store):
        """Test export only includes consensus debates."""
        critique = Critique(
            agent="a",
            target_agent="b",
            target_content="code",
            issues=["export test"],
            suggestions=["fix"],
            severity=0.5,
            reasoning="",
        )

        # Consensus debate
        store.store_debate(
            DebateResult(
                id="export_consensus",
                task="Consensus task",
                final_answer="Answer",
                consensus_reached=True,
                confidence=0.9,
                rounds_used=1,
                duration_seconds=10.0,
                critiques=[critique],
            )
        )

        # Non-consensus debate
        store.store_debate(
            DebateResult(
                id="export_no_consensus",
                task="No consensus task",
                final_answer=None,
                consensus_reached=False,
                confidence=0.3,
                rounds_used=5,
                duration_seconds=100.0,
                critiques=[critique],
            )
        )

        export = store.export_for_training()
        assert len(export) >= 1
        assert all(e["task"] != "No consensus task" for e in export)

    def test_get_archive_stats_empty(self, store):
        """Test archive stats with empty archive."""
        stats = store.get_archive_stats()
        assert stats["total_archived"] == 0
        assert stats["archived_by_type"] == {}


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_pattern_success_rate_division_by_zero(self):
        """Test success_rate with zero total."""
        pattern = Pattern(
            id="p1",
            issue_type="test",
            issue_text="test",
            suggestion_text="fix",
            success_count=0,
            failure_count=0,
            avg_severity=0.5,
            example_task="",
            created_at="",
            updated_at="",
        )
        assert pattern.success_rate == 0.5  # Default

    def test_agent_score_only_critiques(self):
        """Test score when agent only gives critiques."""
        rep = AgentReputation(
            agent_name="critic",
            proposals_made=0,
            critiques_given=10,
            critiques_valuable=8,
        )
        # proposals_made=0 returns 0.5 score
        assert rep.score == 0.5

    def test_agent_score_only_proposals(self):
        """Test score when agent only makes proposals."""
        rep = AgentReputation(
            agent_name="proposer",
            proposals_made=10,
            proposals_accepted=7,
            critiques_given=0,
        )
        # Score = 0.6 * 0.7 + 0.4 * 0.5 = 0.42 + 0.2 = 0.62
        assert rep.score == pytest.approx(0.62, rel=0.01)

    def test_retrieve_patterns_with_limit_zero(self, store, sample_critique):
        """Test retrieve with limit=0 returns empty."""
        store.store_pattern(sample_critique, "fix")

        patterns = store.retrieve_patterns(min_success=1, limit=0)
        assert patterns == []

    def test_store_critique_with_none_issues(self, store):
        """Test critique JSON serialization handles edge cases."""
        # This shouldn't happen in practice, but test robustness
        result = DebateResult(
            id="edge_debate",
            task="Test",
            final_answer="Answer",
            consensus_reached=True,
            confidence=0.8,
            rounds_used=1,
            duration_seconds=10.0,
            critiques=[
                Critique(
                    agent="a",
                    target_agent="b",
                    target_content="code",
                    issues=["Valid issue"],
                    suggestions=[],  # Empty but valid
                    severity=0.5,
                    reasoning="",
                )
            ],
        )

        # Should not raise
        store.store_debate(result)

        stats = store.get_stats()
        assert stats["total_critiques"] >= 1

    def test_categorize_issue_multiple_matches(self, store):
        """Test categorization with multiple category matches."""
        # Should pick first match (performance comes before testing)
        issue = "slow test performance"
        # "slow" matches performance, "test" matches testing
        # Performance is checked first
        assert store._categorize_issue(issue) == "performance"

    def test_database_path_with_special_characters(self):
        """Test database path with special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Path with space
            db_path = os.path.join(tmpdir, "test db.db")
            store = CritiqueStore(db_path=db_path)

            # Should work
            stats = store.get_stats()
            assert "total_debates" in stats

    def test_surprise_calculation_empty_category(self, store):
        """Test surprise calculation with no prior patterns in category."""
        with store._get_connection() as conn:
            cursor = conn.cursor()
            surprise = store._calculate_surprise(cursor, "nonexistent_category", True)

            # With no data, base_rate defaults to 0.5
            # Success = 1.0, surprise = |1.0 - 0.5| * 2 = 1.0
            assert surprise == pytest.approx(1.0, rel=0.1)
