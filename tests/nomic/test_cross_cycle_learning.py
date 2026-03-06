"""Tests for cross-cycle learning enhancements.

Covers:
- KMFeedbackBridge.persist_structured_outcome
- KMFeedbackBridge.retrieve_success_patterns (with filtering)
- KMFeedbackBridge.get_track_agent_effectiveness
- KMFeedbackBridge.get_error_pattern_frequency
- classify_error utility
- SelfCorrectionEngine with km_bridge integration
- KM unavailability fallback (in-memory only)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aragora.nomic.km_feedback_bridge import (
    KMFeedbackBridge,
    classify_error,
)
from aragora.nomic.self_correction import (
    SelfCorrectionConfig,
    SelfCorrectionEngine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge() -> KMFeedbackBridge:
    """Bridge with no KM backend (in-memory only)."""
    return KMFeedbackBridge()


def _persist_outcome(bridge: KMFeedbackBridge, **kwargs) -> dict:
    """Helper to persist a structured outcome with defaults."""
    defaults = {
        "cycle_id": "c1",
        "goal": "improve coverage",
        "goal_type": "feature",
        "track": "qa",
        "agent": "claude",
        "success": True,
        "files_changed": 3,
        "quality_delta": 0.12,
        "cost_usd": 0.05,
        "error_pattern": "",
        "duration_seconds": 45.0,
    }
    defaults.update(kwargs)
    return bridge.persist_structured_outcome(**defaults)


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------


class TestClassifyError:
    def test_test_failure(self):
        assert classify_error("AssertionError: expected 5, actual 3") == "test_failure"

    def test_syntax_error(self):
        assert classify_error("SyntaxError: invalid syntax") == "syntax_error"

    def test_import_error(self):
        assert classify_error("ModuleNotFoundError: No module named 'foo'") == "import_error"

    def test_timeout(self):
        assert classify_error("asyncio.TimeoutError: timed out") == "timeout"

    def test_budget_exceeded(self):
        assert classify_error("Budget limit exceeded for this cycle") == "budget_exceeded"

    def test_merge_conflict(self):
        assert classify_error("Cannot merge: conflict marker <<<<<<") == "merge_conflict"

    def test_gauntlet_fail(self):
        assert classify_error("Gauntlet receipt verification failed") == "gauntlet_fail"

    def test_unknown(self):
        assert classify_error("Something completely unrecognizable happened") == "unknown"

    def test_empty_string(self):
        assert classify_error("") == "unknown"

    def test_case_insensitive(self):
        assert classify_error("SYNTAXERROR: unexpected") == "syntax_error"

    def test_rate_limit_429(self):
        assert classify_error("HTTP 429 Too Many Requests") == "budget_exceeded"


# ---------------------------------------------------------------------------
# persist_structured_outcome
# ---------------------------------------------------------------------------


class TestPersistStructuredOutcome:
    def test_returns_outcome_dict(self, bridge: KMFeedbackBridge):
        outcome = _persist_outcome(bridge)
        assert outcome["cycle_id"] == "c1"
        assert outcome["goal"] == "improve coverage"
        assert outcome["success"] is True
        assert outcome["files_changed"] == 3
        assert outcome["quality_delta"] == 0.12
        assert "timestamp" in outcome

    def test_stores_in_memory(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge)
        assert len(bridge._in_memory_store) == 1
        item = bridge._in_memory_store[0]
        assert item.source == "nomic_structured_outcome"
        assert "structured_outcome:true" in item.tags

    def test_tags_include_metadata(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, track="core", agent="gemini", goal_type="bugfix")
        item = bridge._in_memory_store[0]
        assert "track:core" in item.tags
        assert "agent:gemini" in item.tags
        assert "goal_type:bugfix" in item.tags

    def test_error_classification_in_outcome(self, bridge: KMFeedbackBridge):
        outcome = _persist_outcome(
            bridge,
            success=False,
            error_pattern="SyntaxError: invalid syntax at line 42",
        )
        assert outcome["error_class"] == "syntax_error"
        item = bridge._in_memory_store[0]
        assert "error_class:syntax_error" in item.tags

    def test_no_error_when_empty_pattern(self, bridge: KMFeedbackBridge):
        outcome = _persist_outcome(bridge, error_pattern="")
        assert outcome["error_class"] == ""

    def test_multiple_outcomes_stored(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, cycle_id="c1")
        _persist_outcome(bridge, cycle_id="c2")
        _persist_outcome(bridge, cycle_id="c3")
        assert len(bridge._in_memory_store) == 3


# ---------------------------------------------------------------------------
# retrieve_success_patterns
# ---------------------------------------------------------------------------


class TestRetrieveSuccessPatterns:
    def test_returns_successful_outcomes(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, cycle_id="c1", success=True)
        _persist_outcome(bridge, cycle_id="c2", success=False)
        _persist_outcome(bridge, cycle_id="c3", success=True)
        results = bridge.retrieve_success_patterns()
        assert len(results) == 2
        assert all(r["success"] is True for r in results)

    def test_filter_by_goal_type(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, cycle_id="c1", goal_type="feature", success=True)
        _persist_outcome(bridge, cycle_id="c2", goal_type="bugfix", success=True)
        _persist_outcome(bridge, cycle_id="c3", goal_type="feature", success=True)
        results = bridge.retrieve_success_patterns(goal_type="bugfix")
        assert len(results) == 1
        assert results[0]["goal_type"] == "bugfix"

    def test_filter_by_track(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, cycle_id="c1", track="qa", success=True)
        _persist_outcome(bridge, cycle_id="c2", track="core", success=True)
        results = bridge.retrieve_success_patterns(track="core")
        assert len(results) == 1
        assert results[0]["track"] == "core"

    def test_combined_filter(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, cycle_id="c1", track="qa", goal_type="feature", success=True)
        _persist_outcome(bridge, cycle_id="c2", track="qa", goal_type="bugfix", success=True)
        _persist_outcome(bridge, cycle_id="c3", track="core", goal_type="feature", success=True)
        results = bridge.retrieve_success_patterns(goal_type="feature", track="qa")
        assert len(results) == 1
        assert results[0]["cycle_id"] == "c1"

    def test_respects_limit(self, bridge: KMFeedbackBridge):
        for i in range(20):
            _persist_outcome(bridge, cycle_id=f"c{i}", success=True)
        results = bridge.retrieve_success_patterns(limit=5)
        assert len(results) == 5

    def test_most_recent_first(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, cycle_id="old", success=True)
        _persist_outcome(bridge, cycle_id="new", success=True)
        results = bridge.retrieve_success_patterns()
        assert results[0]["cycle_id"] == "new"

    def test_empty_store(self, bridge: KMFeedbackBridge):
        results = bridge.retrieve_success_patterns()
        assert results == []


# ---------------------------------------------------------------------------
# get_track_agent_effectiveness
# ---------------------------------------------------------------------------


class TestTrackAgentEffectiveness:
    def test_basic_effectiveness(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, track="qa", agent="claude", success=True)
        _persist_outcome(bridge, track="qa", agent="claude", success=True)
        _persist_outcome(bridge, track="qa", agent="claude", success=False)
        _persist_outcome(bridge, track="qa", agent="gemini", success=True)
        _persist_outcome(bridge, track="qa", agent="gemini", success=False)
        effectiveness = bridge.get_track_agent_effectiveness("qa")
        assert abs(effectiveness["claude"] - 2 / 3) < 0.01
        assert abs(effectiveness["gemini"] - 0.5) < 0.01

    def test_filters_by_track(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, track="qa", agent="claude", success=True)
        _persist_outcome(bridge, track="core", agent="claude", success=False)
        effectiveness = bridge.get_track_agent_effectiveness("qa")
        assert effectiveness["claude"] == 1.0

    def test_ignores_empty_agent(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, track="qa", agent="", success=True)
        effectiveness = bridge.get_track_agent_effectiveness("qa")
        assert effectiveness == {}

    def test_empty_store(self, bridge: KMFeedbackBridge):
        effectiveness = bridge.get_track_agent_effectiveness("qa")
        assert effectiveness == {}

    def test_nonexistent_track(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, track="qa", agent="claude", success=True)
        effectiveness = bridge.get_track_agent_effectiveness("nonexistent")
        assert effectiveness == {}


# ---------------------------------------------------------------------------
# get_error_pattern_frequency
# ---------------------------------------------------------------------------


class TestErrorPatternFrequency:
    def test_counts_errors(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, success=False, error_pattern="SyntaxError: bad")
        _persist_outcome(bridge, success=False, error_pattern="SyntaxError: worse")
        _persist_outcome(bridge, success=False, error_pattern="Timeout exceeded")
        freq = bridge.get_error_pattern_frequency()
        # syntax_error appears twice, timeout once
        freq_dict = dict(freq)
        assert freq_dict["syntax_error"] == 2
        assert freq_dict["timeout"] == 1

    def test_sorted_descending(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, success=False, error_pattern="Timeout exceeded")
        for _ in range(3):
            _persist_outcome(bridge, success=False, error_pattern="SyntaxError: bad")
        freq = bridge.get_error_pattern_frequency()
        assert freq[0][0] == "syntax_error"
        assert freq[0][1] == 3

    def test_respects_limit(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, success=False, error_pattern="SyntaxError: bad")
        _persist_outcome(bridge, success=False, error_pattern="Timeout exceeded")
        _persist_outcome(bridge, success=False, error_pattern="ImportError: no mod")
        freq = bridge.get_error_pattern_frequency(limit=2)
        assert len(freq) <= 2

    def test_excludes_successes_without_errors(self, bridge: KMFeedbackBridge):
        _persist_outcome(bridge, success=True, error_pattern="")
        freq = bridge.get_error_pattern_frequency()
        assert freq == []

    def test_empty_store(self, bridge: KMFeedbackBridge):
        freq = bridge.get_error_pattern_frequency()
        assert freq == []


# ---------------------------------------------------------------------------
# SelfCorrectionEngine with km_bridge
# ---------------------------------------------------------------------------


class TestSelfCorrectionWithKMBridge:
    def test_merges_historical_patterns(self):
        """Historical patterns from KM should be included in analysis."""
        bridge = KMFeedbackBridge()
        # Persist some historical successes
        _persist_outcome(bridge, cycle_id="h1", track="qa", agent="claude", success=True)
        _persist_outcome(bridge, cycle_id="h2", track="qa", agent="claude", success=True)
        _persist_outcome(bridge, cycle_id="h3", track="qa", agent="claude", success=True)

        engine = SelfCorrectionEngine(
            config=SelfCorrectionConfig(min_cycles_for_pattern=2),
            km_bridge=bridge,
        )

        # Provide only one in-memory outcome
        in_memory = [{"track": "qa", "success": True, "agent": "claude"}]
        report = engine.analyze_patterns(in_memory)

        # Should see more than 1 total cycle (merged historical)
        assert report.total_cycles > 1

    def test_works_without_km_bridge(self):
        """Engine should work normally when km_bridge is None."""
        engine = SelfCorrectionEngine(
            config=SelfCorrectionConfig(min_cycles_for_pattern=2),
            km_bridge=None,
        )
        outcomes = [
            {"track": "qa", "success": True},
            {"track": "qa", "success": False},
            {"track": "core", "success": True},
        ]
        report = engine.analyze_patterns(outcomes)
        assert report.total_cycles == 3

    def test_km_bridge_failure_graceful(self):
        """If km_bridge.retrieve_success_patterns raises, analysis proceeds."""
        mock_bridge = MagicMock()
        mock_bridge.retrieve_success_patterns.side_effect = RuntimeError("KM down")

        engine = SelfCorrectionEngine(
            config=SelfCorrectionConfig(min_cycles_for_pattern=2),
            km_bridge=mock_bridge,
        )
        outcomes = [
            {"track": "qa", "success": True},
            {"track": "qa", "success": False},
        ]
        report = engine.analyze_patterns(outcomes)
        # Should fall back to just the in-memory outcomes
        assert report.total_cycles == 2


# ---------------------------------------------------------------------------
# KM unavailability fallback
# ---------------------------------------------------------------------------


class TestKMUnavailabilityFallback:
    def test_structured_outcome_without_km(self):
        """All structured methods work with in-memory only (no KM)."""
        bridge = KMFeedbackBridge(km=None)
        outcome = _persist_outcome(bridge, cycle_id="c1", success=True)
        assert outcome["success"] is True

        patterns = bridge.retrieve_success_patterns()
        assert len(patterns) == 1

        effectiveness = bridge.get_track_agent_effectiveness("qa")
        assert "claude" in effectiveness

        # No errors stored, should return empty
        errors = bridge.get_error_pattern_frequency()
        assert errors == []

    def test_persist_and_query_roundtrip(self):
        """Full roundtrip: persist outcomes, query patterns, check agent effectiveness."""
        bridge = KMFeedbackBridge(km=None)

        _persist_outcome(bridge, cycle_id="c1", track="qa", agent="claude", success=True)
        _persist_outcome(
            bridge,
            cycle_id="c2",
            track="qa",
            agent="claude",
            success=False,
            error_pattern="assert failed test",
        )
        _persist_outcome(bridge, cycle_id="c3", track="qa", agent="gemini", success=True)
        _persist_outcome(bridge, cycle_id="c4", track="core", agent="claude", success=True)

        # Check success patterns for qa track
        qa_patterns = bridge.retrieve_success_patterns(track="qa")
        assert len(qa_patterns) == 2

        # Check agent effectiveness on qa
        effectiveness = bridge.get_track_agent_effectiveness("qa")
        assert effectiveness["claude"] == 0.5
        assert effectiveness["gemini"] == 1.0

        # Check error frequency
        errors = bridge.get_error_pattern_frequency()
        assert len(errors) == 1
        assert errors[0][0] == "test_failure"
