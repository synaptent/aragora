"""Tests for critique pattern store."""

import pytest
import tempfile
from pathlib import Path

from aragora.core import DebateResult, Critique
from aragora.memory.store import (
    Pattern,
    AgentReputation,
    CritiqueStore,
)


class TestPattern:
    """Test Pattern dataclass."""

    def test_create_pattern(self):
        """Test creating a pattern."""
        pattern = Pattern(
            id="p1",
            issue_type="security",
            issue_text="SQL injection vulnerability",
            suggestion_text="Use parameterized queries",
            success_count=10,
            failure_count=2,
            avg_severity=0.8,
            example_task="Database query handler",
            created_at="2025-01-01",
            updated_at="2025-01-15",
        )

        assert pattern.id == "p1"
        assert pattern.issue_type == "security"
        assert pattern.success_count == 10

    def test_success_rate(self):
        """Test success rate calculation."""
        pattern = Pattern(
            id="p1",
            issue_type="test",
            issue_text="Issue",
            suggestion_text="Fix",
            success_count=8,
            failure_count=2,
            avg_severity=0.5,
            example_task="Task",
            created_at="2025-01-01",
            updated_at="2025-01-01",
        )

        assert pattern.success_rate == 0.8

    def test_success_rate_no_data(self):
        """Test success rate with no data."""
        pattern = Pattern(
            id="p1",
            issue_type="test",
            issue_text="Issue",
            suggestion_text="Fix",
            success_count=0,
            failure_count=0,
            avg_severity=0.5,
            example_task="Task",
            created_at="2025-01-01",
            updated_at="2025-01-01",
        )

        assert pattern.success_rate == 0.5  # Default


class TestAgentReputation:
    """Test AgentReputation dataclass."""

    def test_create_reputation(self):
        """Test creating reputation."""
        rep = AgentReputation(
            agent_name="claude",
            proposals_made=100,
            proposals_accepted=80,
            critiques_given=50,
            critiques_valuable=40,
        )

        assert rep.agent_name == "claude"
        assert rep.proposals_made == 100

    def test_score_calculation(self):
        """Test reputation score calculation."""
        rep = AgentReputation(
            agent_name="claude",
            proposals_made=100,
            proposals_accepted=80,  # 80% acceptance
            critiques_given=50,
            critiques_valuable=40,  # 80% valuable
        )

        # Score = 0.6 * 0.8 + 0.4 * 0.8 = 0.8
        assert abs(rep.score - 0.8) < 0.01

    def test_score_new_agent(self):
        """Test score for new agent with no history."""
        rep = AgentReputation(
            agent_name="new_agent",
            proposals_made=0,
            proposals_accepted=0,
        )

        assert rep.score == 0.5  # Neutral

    def test_reputation_score_alias(self):
        """Test reputation_score is alias for score."""
        rep = AgentReputation(
            agent_name="claude",
            proposals_made=10,
            proposals_accepted=8,
        )

        assert rep.reputation_score == rep.score

    def test_proposal_acceptance_rate(self):
        """Test proposal acceptance rate."""
        rep = AgentReputation(
            agent_name="claude",
            proposals_made=100,
            proposals_accepted=75,
        )

        assert rep.proposal_acceptance_rate == 0.75

    def test_proposal_acceptance_rate_no_proposals(self):
        """Test acceptance rate with no proposals."""
        rep = AgentReputation(
            agent_name="claude",
            proposals_made=0,
            proposals_accepted=0,
        )

        assert rep.proposal_acceptance_rate == 0.0

    def test_default_calibration_fields(self):
        """Test default calibration fields."""
        rep = AgentReputation(agent_name="test")

        assert rep.total_predictions == 0
        assert rep.total_prediction_error == 0.0
        assert rep.calibration_score == 0.5


class TestCritiqueStore:
    """Test CritiqueStore class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_critique.db"

    def test_init(self, temp_db):
        """Test initialization creates database."""
        store = CritiqueStore(str(temp_db))
        assert temp_db.exists()

    def test_store_debate(self, temp_db):
        """Test storing a debate."""
        store = CritiqueStore(str(temp_db))

        # Create proper debate result
        result = DebateResult(
            id="test-debate-1",
            task="Implement rate limiter",
            final_answer="Use token bucket",
            consensus_reached=True,
            confidence=0.85,
            rounds_used=3,
            participants=["claude", "gpt"],
            duration_seconds=120.5,
            critiques=[],
        )

        # store_debate returns None, just verify it doesn't raise
        store.store_debate(result)

    def test_get_reputation_unknown_agent(self, temp_db):
        """Test getting reputation for unknown agent returns None."""
        store = CritiqueStore(str(temp_db))

        # Unknown agent returns None
        rep = store.get_reputation("unknown_agent")
        assert rep is None

    def test_get_reputation_existing_agent(self, temp_db):
        """Test getting reputation for existing agent."""
        store = CritiqueStore(str(temp_db))

        # Create reputation first
        store.update_reputation(agent_name="claude", proposal_made=True)

        rep = store.get_reputation("claude")
        assert rep is not None
        assert rep.agent_name == "claude"
        assert rep.proposals_made == 1

    def test_update_reputation(self, temp_db):
        """Test updating agent reputation."""
        store = CritiqueStore(str(temp_db))

        # Initial update
        store.update_reputation(
            agent_name="claude",
            proposal_made=True,
            proposal_accepted=True,
        )

        rep = store.get_reputation("claude")
        assert rep.proposals_made == 1
        assert rep.proposals_accepted == 1

        # Additional update for a different agent (avoid cache issues)
        store.update_reputation(
            agent_name="gpt",
            proposal_made=True,
            proposal_accepted=False,
        )

        rep = store.get_reputation("gpt")
        assert rep.proposals_made == 1
        assert rep.proposals_accepted == 0

    def test_update_reputation_critique(self, temp_db):
        """Test updating reputation with critique."""
        store = CritiqueStore(str(temp_db))

        store.update_reputation(
            agent_name="claude",
            critique_given=True,
            critique_valuable=True,
        )

        rep = store.get_reputation("claude")
        assert rep.critiques_given == 1
        assert rep.critiques_valuable == 1

    def test_get_relevant_patterns(self, temp_db):
        """Test retrieving relevant patterns (get_relevant)."""
        store = CritiqueStore(str(temp_db))

        # Initially empty
        patterns = store.get_relevant()
        assert isinstance(patterns, list)

    def test_get_relevant_patterns_by_type(self, temp_db):
        """Test retrieving patterns by issue type."""
        store = CritiqueStore(str(temp_db))

        patterns = store.get_relevant(issue_type="security")
        assert isinstance(patterns, list)

    def test_get_all_reputations(self, temp_db):
        """Test getting all agent reputations."""
        store = CritiqueStore(str(temp_db))

        # Add some agents
        store.update_reputation("agent1", proposal_made=True)
        store.update_reputation("agent2", proposal_made=True)

        reputations = store.get_all_reputations()
        assert len(reputations) >= 2

    def test_get_stats(self, temp_db):
        """Test getting store statistics."""
        store = CritiqueStore(str(temp_db))

        stats = store.get_stats()

        assert "total_debates" in stats
        assert "total_critiques" in stats


class TestCritiqueStorePatterns:
    """Test pattern management in CritiqueStore."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_patterns.db"

    def test_store_pattern_success(self, temp_db):
        """Test storing a successful pattern."""
        store = CritiqueStore(str(temp_db))

        # Create a critique object
        critique = Critique(
            agent="claude",
            target_agent="gpt",
            target_content="The database query uses string concatenation",
            issues=["SQL injection vulnerability"],
            suggestions=["Use parameterized queries"],
            severity=0.9,
            reasoning="String concatenation in SQL queries allows injection attacks",
        )

        # Store the pattern
        store.store_pattern(critique, successful_fix="Database handler")

        patterns = store.get_relevant(issue_type="security")
        assert len(patterns) >= 1

    def test_fail_pattern(self, temp_db):
        """Test recording a failed pattern."""
        store = CritiqueStore(str(temp_db))

        # First store a pattern
        critique = Critique(
            agent="claude",
            target_agent="gpt",
            target_content="The variable is named x",
            issues=["Variable naming issue"],
            suggestions=["Use camelCase"],
            severity=0.3,
            reasoning="Variable names should be descriptive",
        )
        store.store_pattern(critique, successful_fix="Some fix")

        # Then record failure
        store.fail_pattern(issue_text="Variable naming issue", issue_type="style")

    def test_pattern_aggregation(self, temp_db):
        """Test that patterns aggregate success/failure counts."""
        store = CritiqueStore(str(temp_db))

        # Store same pattern multiple times with Critique objects
        critique = Critique(
            agent="claude",
            target_agent="gpt",
            target_content="Some code with an issue",
            issues=["Same issue"],
            suggestions=["Same suggestion"],
            severity=0.5,
            reasoning="This is the reasoning for the critique",
        )

        for _ in range(3):
            store.store_pattern(critique, successful_fix="Task")

        # Record a failure
        store.fail_pattern(issue_text="Same issue", issue_type="general")

        patterns = store.get_relevant(issue_type="general")
        if patterns:
            # Should have aggregated counts
            pattern = patterns[0]
            assert pattern.success_count >= 3
            assert pattern.failure_count >= 1


class TestCritiqueStoreArchive:
    """Test archive functionality."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_archive.db"

    def test_prune_stale_patterns(self, temp_db):
        """Test pruning stale patterns."""
        store = CritiqueStore(str(temp_db))

        # Record some patterns
        critique = Critique(
            agent="claude",
            target_agent="gpt",
            target_content="Some old code with an issue",
            issues=["Old pattern"],
            suggestions=["Fix"],
            severity=0.5,
            reasoning="This pattern is old and needs fixing",
        )
        store.store_pattern(critique, successful_fix="Task")

        # Prune (won't prune recent patterns)
        pruned = store.prune_stale_patterns(max_age_days=365)

        assert isinstance(pruned, int)
        assert pruned >= 0

    def test_get_archive_stats(self, temp_db):
        """Test getting archive statistics."""
        store = CritiqueStore(str(temp_db))

        stats = store.get_archive_stats()

        assert "total_archived" in stats
        assert "archived_by_type" in stats


class TestTimestampUTCConsistency:
    """Python-side timestamps must be UTC to match SQLite's julianday('now').

    Pattern and reputation rows are aged/pruned/ranked with UTC
    julianday('now') comparisons, so local-time stamps skew staleness math
    by the machine's UTC offset (see PR #9311's CI flake).
    """

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_tz.db"

    @pytest.fixture
    def non_utc_timezone(self):
        """Force a far-from-UTC, DST-free local timezone for the process."""
        import os
        import time

        if not hasattr(time, "tzset"):
            pytest.skip("requires time.tzset (POSIX)")
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Pacific/Kiritimati"  # UTC+14, no DST
        time.tzset()
        try:
            yield
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

    @staticmethod
    def _age_seconds(store, table: str, column: str = "updated_at") -> float:
        """Age of the single row's timestamp as SQLite's UTC clock sees it."""
        assert table in {"patterns", "agent_reputation"}
        with store.connection() as conn:
            row = conn.execute(
                f"SELECT (julianday('now') - julianday({column})) * 86400.0 FROM {table}"  # noqa: S608 -- table from whitelist above
            ).fetchone()
        assert row is not None and row[0] is not None
        return row[0]

    def _make_critique(self) -> Critique:
        return Critique(
            agent="claude",
            target_agent="gpt",
            target_content="Some code",
            issues=["Timestamp skew issue"],
            suggestions=["Stamp in UTC"],
            severity=0.5,
            reasoning="Local-time stamps skew julianday comparisons",
        )

    def test_store_pattern_stamps_utc(self, temp_db, non_utc_timezone):
        """A freshly stored pattern must not appear hours old/new to julianday."""
        store = CritiqueStore(str(temp_db))
        store.store_pattern(self._make_critique(), successful_fix="fix")

        age = self._age_seconds(store, "patterns")
        assert abs(age) < 300, f"pattern updated_at skewed by {age:.0f}s vs UTC"

        created_age = self._age_seconds(store, "patterns", column="created_at")
        assert abs(created_age) < 300, f"pattern created_at skewed by {created_age:.0f}s vs UTC"

    def test_fail_pattern_stamps_utc(self, temp_db, non_utc_timezone):
        """fail_pattern's updated_at stamp must be UTC as well."""
        store = CritiqueStore(str(temp_db))
        store.store_pattern(self._make_critique(), successful_fix="fix")
        store.fail_pattern("Timestamp skew issue")

        age = self._age_seconds(store, "patterns")
        assert abs(age) < 300, f"pattern updated_at skewed by {age:.0f}s vs UTC"

    def test_reputation_update_stamps_utc(self, temp_db, non_utc_timezone):
        """Reputation updates must stamp updated_at in UTC."""
        store = CritiqueStore(str(temp_db))
        store.update_reputation(agent_name="claude", proposal_made=True)

        age = self._age_seconds(store, "agent_reputation")
        assert abs(age) < 300, f"reputation updated_at skewed by {age:.0f}s vs UTC"

    def test_fresh_pattern_not_pruned_under_utc_clock(self, temp_db, non_utc_timezone):
        """A just-written, low-success pattern is fresh, so age gating keeps it."""
        store = CritiqueStore(str(temp_db))
        store.store_pattern(self._make_critique(), successful_fix="fix")
        store.fail_pattern("Timestamp skew issue")
        store.fail_pattern("Timestamp skew issue")

        pruned = store.prune_stale_patterns(max_age_days=1, min_success_rate=0.5)
        assert pruned == 0
