"""
Comprehensive tests for RLM Tier 2 integration features.

Tests cover:
- MemoryEntry dataclass (defaults, custom values, red_line flag)
- MemoryREPLContext dataclass (construction, indexing, stats)
- load_memory_context() with various continuum backends
- Memory helper functions (get_tier, filter_by_importance, etc.)
- get_memory_helpers() return values
- AragoraRLM.log_to_audit() with and without AuditLog
- AragoraRLM.inject_memory_helpers() / inject_knowledge_helpers()
- Module exports verification
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aragora.rlm.memory_helpers import (
    MemoryEntry,
    MemoryREPLContext,
    filter_by_importance,
    filter_red_line,
    get_memory_helpers,
    get_tier,
    load_memory_context,
    search_memory,
    sort_by_surprise,
)


# ---------------------------------------------------------------------------
# 1. MemoryEntry dataclass
# ---------------------------------------------------------------------------


class TestMemoryEntry:
    """Tests for the MemoryEntry dataclass."""

    def test_default_field_values(self):
        """MemoryEntry should have sensible defaults for metadata and red_line."""
        entry = MemoryEntry(
            id="e1",
            tier="fast",
            content="hello",
            importance=0.5,
            surprise_score=0.1,
            success_rate=0.9,
        )
        assert entry.metadata == {}
        assert entry.red_line is False

    def test_custom_values(self):
        """All fields can be explicitly set."""
        entry = MemoryEntry(
            id="e2",
            tier="glacial",
            content="critical constraint",
            importance=1.0,
            surprise_score=0.95,
            success_rate=0.3,
            metadata={"source": "debate-42"},
            red_line=True,
        )
        assert entry.id == "e2"
        assert entry.tier == "glacial"
        assert entry.content == "critical constraint"
        assert entry.importance == 1.0
        assert entry.surprise_score == 0.95
        assert entry.success_rate == 0.3
        assert entry.metadata == {"source": "debate-42"}
        assert entry.red_line is True

    def test_red_line_flag(self):
        """red_line defaults to False and can be toggled."""
        normal = MemoryEntry(
            id="n",
            tier="fast",
            content="x",
            importance=0.5,
            surprise_score=0.0,
            success_rate=0.5,
        )
        critical = MemoryEntry(
            id="c",
            tier="fast",
            content="y",
            importance=0.5,
            surprise_score=0.0,
            success_rate=0.5,
            red_line=True,
        )
        assert normal.red_line is False
        assert critical.red_line is True


# ---------------------------------------------------------------------------
# 2. MemoryREPLContext dataclass
# ---------------------------------------------------------------------------


class TestMemoryREPLContext:
    """Tests for the MemoryREPLContext dataclass."""

    @staticmethod
    def _make_entries() -> list[MemoryEntry]:
        return [
            MemoryEntry(
                id="a",
                tier="fast",
                content="alpha",
                importance=0.8,
                surprise_score=0.2,
                success_rate=0.9,
            ),
            MemoryEntry(
                id="b",
                tier="slow",
                content="beta",
                importance=0.4,
                surprise_score=0.7,
                success_rate=0.5,
            ),
        ]

    def test_construction(self):
        """MemoryREPLContext can be built with all required fields."""
        entries = self._make_entries()
        ctx = MemoryREPLContext(
            entries=entries,
            by_tier={"fast": [entries[0]], "slow": [entries[1]]},
            by_id={"a": entries[0], "b": entries[1]},
            total_entries=2,
            tier_counts={"fast": 1, "slow": 1},
            avg_importance=0.6,
        )
        assert ctx.total_entries == 2

    def test_by_tier_indexing(self):
        """by_tier allows lookup by tier name."""
        entries = self._make_entries()
        ctx = MemoryREPLContext(
            entries=entries,
            by_tier={"fast": [entries[0]], "slow": [entries[1]]},
            by_id={"a": entries[0], "b": entries[1]},
            total_entries=2,
            tier_counts={"fast": 1, "slow": 1},
            avg_importance=0.6,
        )
        assert len(ctx.by_tier["fast"]) == 1
        assert ctx.by_tier["fast"][0].id == "a"

    def test_by_id_lookup(self):
        """by_id allows direct entry lookup."""
        entries = self._make_entries()
        ctx = MemoryREPLContext(
            entries=entries,
            by_tier={},
            by_id={"a": entries[0], "b": entries[1]},
            total_entries=2,
            tier_counts={},
            avg_importance=0.6,
        )
        assert ctx.by_id["b"].content == "beta"

    def test_tier_counts_and_avg_importance(self):
        """tier_counts and avg_importance are computed correctly."""
        entries = self._make_entries()
        ctx = MemoryREPLContext(
            entries=entries,
            by_tier={"fast": [entries[0]], "slow": [entries[1]]},
            by_id={"a": entries[0], "b": entries[1]},
            total_entries=2,
            tier_counts={"fast": 1, "slow": 1},
            avg_importance=0.6,
        )
        assert ctx.tier_counts == {"fast": 1, "slow": 1}
        assert ctx.avg_importance == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# 3. load_memory_context()
# ---------------------------------------------------------------------------


class TestLoadMemoryContext:
    """Tests for the load_memory_context function."""

    def test_with_get_entries(self):
        """Uses get_entries() when available."""
        continuum = MagicMock()
        continuum.search = MagicMock(side_effect=AttributeError)
        # Only get_entries is available
        del continuum.search
        del continuum.get_tier
        del continuum.retrieve
        continuum.get_entries.return_value = [
            {
                "id": "m1",
                "content": "entry one",
                "importance": 0.9,
                "surprise_score": 0.1,
                "success_rate": 0.8,
            },
        ]
        ctx = load_memory_context(continuum)
        assert ctx.total_entries >= 1
        assert "m1" in ctx.by_id

    def test_with_search_when_query_provided(self):
        """Uses search() when a query is provided and search() exists."""
        continuum = MagicMock()
        continuum.search.return_value = [
            {
                "id": "s1",
                "content": "searched result",
                "importance": 0.7,
                "surprise_score": 0.3,
                "success_rate": 0.6,
            },
        ]
        ctx = load_memory_context(continuum, query="searched")
        # search should have been called at least once (per tier)
        assert continuum.search.called
        assert ctx.total_entries >= 1

    def test_with_get_tier(self):
        """Uses get_tier() when get_entries and search are absent."""
        continuum = MagicMock(spec=[])
        # Manually add only get_tier
        continuum.get_tier = MagicMock(
            return_value=[
                {
                    "id": "t1",
                    "content": "tier item",
                    "importance": 0.5,
                    "surprise_score": 0.0,
                    "success_rate": 0.5,
                },
            ]
        )
        ctx = load_memory_context(continuum)
        assert ctx.total_entries >= 1

    def test_graceful_degradation_on_method_failure(self):
        """Returns empty context when continuum methods raise errors."""
        continuum = MagicMock()
        continuum.get_entries.side_effect = TypeError("broken")
        del continuum.search
        del continuum.get_tier
        del continuum.retrieve
        ctx = load_memory_context(continuum)
        assert ctx.total_entries == 0
        assert ctx.avg_importance == 0.0

    def test_empty_continuum_no_methods(self):
        """Returns empty context when continuum has no recognised methods."""
        continuum = MagicMock(spec=[])
        ctx = load_memory_context(continuum)
        assert ctx.total_entries == 0
        assert ctx.entries == []
        # All four tiers should still exist in by_tier
        assert set(ctx.by_tier.keys()) == {"fast", "medium", "slow", "glacial"}


# ---------------------------------------------------------------------------
# 4. Memory helper functions
# ---------------------------------------------------------------------------


def _sample_context() -> MemoryREPLContext:
    """Build a small MemoryREPLContext for helper function tests."""
    entries = [
        MemoryEntry(
            id="h1",
            tier="fast",
            content="rate limit config",
            importance=0.9,
            surprise_score=0.1,
            success_rate=0.8,
            red_line=True,
        ),
        MemoryEntry(
            id="h2",
            tier="fast",
            content="cache invalidation",
            importance=0.4,
            surprise_score=0.8,
            success_rate=0.5,
        ),
        MemoryEntry(
            id="h3",
            tier="slow",
            content="retry policy",
            importance=0.7,
            surprise_score=0.5,
            success_rate=0.6,
        ),
        MemoryEntry(
            id="h4",
            tier="glacial",
            content="Rate LIMIT override",
            importance=0.6,
            surprise_score=0.3,
            success_rate=0.7,
        ),
    ]
    by_tier: dict[str, list[MemoryEntry]] = {
        "fast": [entries[0], entries[1]],
        "medium": [],
        "slow": [entries[2]],
        "glacial": [entries[3]],
    }
    by_id = {e.id: e for e in entries}
    return MemoryREPLContext(
        entries=entries,
        by_tier=by_tier,
        by_id=by_id,
        total_entries=len(entries),
        tier_counts={t: len(v) for t, v in by_tier.items()},
        avg_importance=sum(e.importance for e in entries) / len(entries),
    )


class TestGetTier:
    def test_existing_tier(self):
        ctx = _sample_context()
        fast = get_tier(ctx, "fast")
        assert len(fast) == 2
        assert all(e.tier == "fast" for e in fast)

    def test_missing_tier(self):
        ctx = _sample_context()
        assert get_tier(ctx, "nonexistent") == []


class TestFilterByImportance:
    def test_threshold_filtering(self):
        ctx = _sample_context()
        high = filter_by_importance(ctx.entries, threshold=0.7)
        assert all(e.importance >= 0.7 for e in high)
        assert len(high) == 2  # h1 (0.9) and h3 (0.7)

    def test_threshold_zero_returns_all(self):
        ctx = _sample_context()
        assert len(filter_by_importance(ctx.entries, threshold=0.0)) == 4


class TestFilterRedLine:
    def test_red_line_only(self):
        ctx = _sample_context()
        red = filter_red_line(ctx.entries)
        assert len(red) == 1
        assert red[0].id == "h1"

    def test_no_red_line(self):
        entries = [
            MemoryEntry(
                id="x",
                tier="fast",
                content="safe",
                importance=0.5,
                surprise_score=0.0,
                success_rate=0.5,
            ),
        ]
        assert filter_red_line(entries) == []


class TestSearchMemory:
    def test_regex_case_insensitive(self):
        ctx = _sample_context()
        results = search_memory(ctx, r"rate limit")
        # h1 = "rate limit config", h4 = "Rate LIMIT override"
        assert len(results) == 2

    def test_regex_case_sensitive(self):
        ctx = _sample_context()
        results = search_memory(ctx, r"Rate LIMIT", case_insensitive=False)
        assert len(results) == 1
        assert results[0].id == "h4"

    def test_no_match(self):
        ctx = _sample_context()
        assert search_memory(ctx, r"zzzznotfound") == []


class TestSortBySurprise:
    def test_descending(self):
        ctx = _sample_context()
        sorted_entries = sort_by_surprise(ctx.entries, descending=True)
        scores = [e.surprise_score for e in sorted_entries]
        assert scores == sorted(scores, reverse=True)

    def test_ascending(self):
        ctx = _sample_context()
        sorted_entries = sort_by_surprise(ctx.entries, descending=False)
        scores = [e.surprise_score for e in sorted_entries]
        assert scores == sorted(scores)


# ---------------------------------------------------------------------------
# 5. get_memory_helpers()
# ---------------------------------------------------------------------------


class TestGetMemoryHelpers:
    def test_returns_expected_names(self):
        helpers = get_memory_helpers()
        expected = {
            "MemoryEntry",
            "MemoryREPLContext",
            "load_memory_context",
            "get_tier",
            "filter_by_importance",
            "filter_red_line",
            "search_memory",
            "sort_by_surprise",
        }
        assert expected.issubset(set(helpers.keys()))

    def test_without_rlm_primitives(self):
        helpers = get_memory_helpers(include_rlm_primitives=False)
        assert "llm_query" not in helpers
        assert "FINAL" not in helpers

    def test_with_rlm_primitives(self):
        helpers = get_memory_helpers(include_rlm_primitives=True)
        assert "llm_query" in helpers
        assert "FINAL" in helpers
        # llm_query should be callable
        assert callable(helpers["llm_query"])
        assert callable(helpers["FINAL"])


# ---------------------------------------------------------------------------
# 6. AragoraRLM.log_to_audit()
# ---------------------------------------------------------------------------


class TestLogToAudit:
    @staticmethod
    def _make_rlm() -> "AragoraRLM":
        from aragora.rlm.bridge import AragoraRLM

        return AragoraRLM()

    @staticmethod
    def _make_result() -> "RLMResult":
        from aragora.rlm.types import RLMResult

        return RLMResult(
            answer="test answer",
            confidence=0.85,
            tokens_processed=100,
            used_true_rlm=False,
        )

    def test_log_to_audit_success(self):
        """Successfully logs when audit subsystem is available."""
        rlm = self._make_rlm()
        result = self._make_result()

        mock_audit_instance = MagicMock()
        mock_audit_event = MagicMock()
        mock_audit_category = MagicMock()
        mock_audit_category.SYSTEM = "system"

        # Patch the import inside log_to_audit to match the new API:
        # from aragora.observability.audit_log import AuditCategory, AuditEvent, get_audit_log
        mock_module = MagicMock(
            AuditCategory=mock_audit_category,
            AuditEvent=mock_audit_event,
            get_audit_log=MagicMock(return_value=mock_audit_instance),
        )
        with patch.dict("sys.modules", {"aragora.observability.audit_log": mock_module}):
            rlm.log_to_audit(result, query="test query", debate_id="d-1")
            mock_audit_instance.log.assert_called_once()
            call_args = mock_audit_instance.log.call_args
            # AuditEvent is the first positional arg
            assert mock_audit_event.called

    def test_log_to_audit_graceful_when_unavailable(self):
        """Does not raise when AuditLog is not available.

        The real AuditLog class does not have get_instance(), so the
        try/except in log_to_audit swallows the AttributeError. This
        test verifies that calling log_to_audit never raises even when
        the audit subsystem is not wired up.
        """
        rlm = self._make_rlm()
        result = self._make_result()
        # Should not raise -- the except block inside log_to_audit handles it
        rlm.log_to_audit(result, query="q")


# ---------------------------------------------------------------------------
# 7. AragoraRLM.inject_memory_helpers()
# ---------------------------------------------------------------------------


class TestInjectMemoryHelpers:
    @staticmethod
    def _make_rlm() -> "AragoraRLM":
        from aragora.rlm.bridge import AragoraRLM

        return AragoraRLM()

    def test_returns_context_and_helpers(self):
        """inject_memory_helpers returns dict with context and helpers."""
        rlm = self._make_rlm()
        continuum = MagicMock()
        continuum.get_entries.return_value = [
            {
                "id": "im1",
                "content": "injected",
                "importance": 0.5,
                "surprise_score": 0.0,
                "success_rate": 0.5,
            },
        ]
        # Remove search/get_tier/retrieve so get_entries is used
        del continuum.search
        del continuum.get_tier
        del continuum.retrieve

        result = rlm.inject_memory_helpers(continuum)
        assert "context" in result
        assert "helpers" in result
        assert result["context"] is not None
        assert isinstance(result["helpers"], dict)

    def test_graceful_with_none_continuum(self):
        """Does not crash when continuum is None-like or broken."""
        rlm = self._make_rlm()
        # A continuum with no useful methods
        continuum = MagicMock(spec=[])
        result = rlm.inject_memory_helpers(continuum)
        # Should still return a valid dict (empty or not)
        assert "context" in result
        assert "helpers" in result

    def test_passes_query_parameter(self):
        """query parameter is forwarded to load_memory_context."""
        rlm = self._make_rlm()
        continuum = MagicMock()
        continuum.search.return_value = []
        rlm.inject_memory_helpers(continuum, query="find me")
        continuum.search.assert_called()


# ---------------------------------------------------------------------------
# 8. AragoraRLM.inject_knowledge_helpers()
# ---------------------------------------------------------------------------


class TestInjectKnowledgeHelpers:
    @staticmethod
    def _make_rlm() -> "AragoraRLM":
        from aragora.rlm.bridge import AragoraRLM

        return AragoraRLM()

    def test_returns_context_and_helpers(self):
        """inject_knowledge_helpers returns dict with context and helpers."""
        rlm = self._make_rlm()
        mound = MagicMock()
        mound.get_facts.return_value = [
            {"id": "f1", "content": "fact one", "confidence": 0.9, "created_at": "2025-01-01"},
        ]
        mound.get_claims.return_value = []
        mound.get_evidence.return_value = []

        result = rlm.inject_knowledge_helpers(mound, workspace_id="ws-1")
        assert "context" in result
        assert "helpers" in result
        assert result["context"] is not None
        assert isinstance(result["helpers"], dict)

    def test_graceful_with_none_mound(self):
        """Does not crash when mound has no expected methods."""
        rlm = self._make_rlm()
        mound = MagicMock(spec=[])
        result = rlm.inject_knowledge_helpers(mound, workspace_id="ws-bad")
        assert "context" in result
        assert "helpers" in result

    def test_no_query_parameter(self):
        """load_knowledge_context does NOT accept a query parameter.

        Unlike inject_memory_helpers, inject_knowledge_helpers does not
        forward a query -- the underlying load_knowledge_context signature
        is (mound, workspace_id, limit).
        """
        from aragora.rlm.knowledge_helpers import load_knowledge_context
        import inspect

        sig = inspect.signature(load_knowledge_context)
        param_names = list(sig.parameters.keys())
        assert "query" not in param_names


# ---------------------------------------------------------------------------
# 9. Module exports
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Verify that key symbols are importable from aragora.rlm."""

    def test_memory_entry_exported(self):
        from aragora.rlm import MemoryEntry as ME

        assert ME is MemoryEntry

    def test_memory_repl_context_exported(self):
        from aragora.rlm import MemoryREPLContext as MRC

        assert MRC is MemoryREPLContext

    def test_load_memory_context_exported(self):
        from aragora.rlm import load_memory_context as lmc

        assert lmc is load_memory_context

    def test_get_memory_helpers_exported(self):
        from aragora.rlm import get_memory_helpers as gmh

        assert gmh is get_memory_helpers
