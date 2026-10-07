"""
Tests for Explainability API handler.

Tests cover:
- Route matching (can_handle) for single debate and batch endpoints
- Natural language explanation generation (full, summary, markdown, html, json)
- Factor decomposition endpoints
- Evidence chain retrieval with filtering
- Vote pivot analysis with influence filtering
- Counterfactual analysis with sensitivity filtering
- Summary endpoint with multiple output formats
- Explanation caching (_LRUTTLCache)
- Batch job creation, status, and results
- Compare endpoint for multi-debate comparison
- Error handling paths (not found, invalid input, internal errors)
- Legacy route detection and deprecation headers
- Handler factory (get_explainability_handler)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.explainability.decision import (
    Counterfactual,
    Decision,
    EvidenceLink,
    VotePivot,
)
from aragora.server.handlers.explainability import (
    BatchDebateResult,
    BatchJob,
    BatchStatus,
    ExplainabilityHandler,
    _LRUTTLCache,
    _cache_decision,
    _decision_cache,
    _get_cached_decision,
    get_explainability_handler,
)

# Explainability reads are org-scoped; requests act for the org that owns every debate.
pytestmark = pytest.mark.usefixtures("explainability_org_member")

TEST_ORG = "test-org-001"
# Batch jobs answer status and results only for the org that created them.
OWNED_BY_TEST_ORG = {"_owner_org_id": TEST_ORG}


# ============================================================================
# Helpers
# ============================================================================


def parse_response(result) -> dict[str, Any] | None:
    """Parse HandlerResult body as JSON."""
    if result is None:
        return None
    return json.loads(result.body.decode("utf-8"))


def _make_evidence(id: str, relevance: float = 0.8) -> EvidenceLink:
    return EvidenceLink(
        id=id,
        content=f"Evidence content {id}",
        source="claude",
        relevance_score=relevance,
    )


def _make_vote_pivot(agent: str, influence: float = 0.7) -> VotePivot:
    return VotePivot(
        agent=agent,
        choice="approve",
        confidence=0.9,
        weight=1.0,
        reasoning_summary="Strong argument",
        influence_score=influence,
    )


def _make_counterfactual(condition: str, sensitivity: float = 0.6) -> Counterfactual:
    return Counterfactual(
        condition=condition,
        outcome_change="Decision reversed",
        likelihood=0.5,
        sensitivity=sensitivity,
    )


def _make_decision(debate_id: str = "debate-123", **overrides) -> Decision:
    """Create a Decision with sensible defaults for testing."""
    kwargs: dict[str, Any] = {
        "decision_id": f"dec-{debate_id}",
        "debate_id": debate_id,
        "conclusion": "The proposal should be accepted.",
        "consensus_reached": True,
        "confidence": 0.85,
        "consensus_type": "majority",
        "task": "Evaluate proposal",
        "domain": "engineering",
        "rounds_used": 3,
        "agents_participated": ["claude", "gpt4", "gemini"],
        "evidence_chain": [
            _make_evidence("ev-1", 0.9),
            _make_evidence("ev-2", 0.7),
            _make_evidence("ev-3", 0.3),
        ],
        "vote_pivots": [
            _make_vote_pivot("claude", 0.9),
            _make_vote_pivot("gpt4", 0.5),
            _make_vote_pivot("gemini", 0.2),
        ],
        "counterfactuals": [
            _make_counterfactual("Remove claude", 0.8),
            _make_counterfactual("Change topic", 0.3),
        ],
        "evidence_quality_score": 0.82,
        "agent_agreement_score": 0.91,
    }
    kwargs.update(overrides)
    return Decision(**kwargs)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear the global decision cache before and after each test."""
    _decision_cache.clear()
    yield
    _decision_cache.clear()


@pytest.fixture(autouse=True)
def _reset_handler_singleton():
    """Reset the global handler singleton between tests."""
    import aragora.server.handlers.explainability as mod

    mod._explainability_handler = None
    yield
    mod._explainability_handler = None


@pytest.fixture
def handler() -> ExplainabilityHandler:
    """Create an ExplainabilityHandler with empty server context."""
    ctx: dict[str, Any] = {"elo_system": None}
    return ExplainabilityHandler(ctx)


@pytest.fixture
def decision() -> Decision:
    """A default Decision fixture for reuse."""
    return _make_decision()


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler for POST request reading."""
    h = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    h.headers = {"Content-Length": "0"}
    h.command = "GET"
    return h


def _post_handler_with_body(data: dict[str, Any]) -> MagicMock:
    """Create a mock HTTP handler with a JSON body."""
    h = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    body = json.dumps(data).encode("utf-8")
    h.headers = {"Content-Length": str(len(body))}
    h.rfile = BytesIO(body)
    h.command = "POST"
    return h


# ============================================================================
# Test: _LRUTTLCache
# ============================================================================


class TestLRUTTLCache:
    """Tests for the internal LRU + TTL cache."""

    def test_set_and_get(self):
        cache = _LRUTTLCache(max_size=10, ttl_seconds=60)
        cache.set("k1", "value1")
        assert cache.get("k1") == "value1"

    def test_get_missing_key_returns_none(self):
        cache = _LRUTTLCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = _LRUTTLCache(max_size=10, ttl_seconds=1)
        cache.set("k1", "value1")
        # Manually expire entry by backdating its timestamp
        cache._cache["k1"] = ("value1", time.time() - 2)
        assert cache.get("k1") is None

    def test_max_size_eviction(self):
        cache = _LRUTTLCache(max_size=3, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # Should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("d") == 4

    def test_lru_order_updated_on_get(self):
        cache = _LRUTTLCache(max_size=3, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # Access "a" to make it most recently used
        cache.get("a")
        cache.set("d", 4)  # Should evict "b" (now oldest)
        assert cache.get("a") == 1
        assert cache.get("b") is None

    def test_overwrite_existing_key(self):
        cache = _LRUTTLCache(max_size=10, ttl_seconds=60)
        cache.set("k", "old")
        cache.set("k", "new")
        assert cache.get("k") == "new"

    def test_clear(self):
        cache = _LRUTTLCache(max_size=10, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


class TestCacheHelpers:
    """Tests for module-level cache get/set helpers."""

    def test_cache_and_retrieve_decision(self, decision):
        _cache_decision("d1", decision)
        result = _get_cached_decision("d1")
        assert result is decision

    def test_get_uncached_returns_none(self):
        assert _get_cached_decision("nonexistent") is None


# ============================================================================
# Test: can_handle
# ============================================================================


class TestCanHandle:
    """Tests for ExplainabilityHandler.can_handle route matching."""

    def test_explanation_get(self, handler):
        assert handler.can_handle("/api/v1/debates/abc/explanation", "GET") is True

    def test_evidence_get(self, handler):
        assert handler.can_handle("/api/v1/debates/abc/evidence", "GET") is True

    def test_vote_pivots_get(self, handler):
        assert handler.can_handle("/api/v1/debates/abc/votes/pivots", "GET") is True

    def test_counterfactuals_get(self, handler):
        assert handler.can_handle("/api/v1/debates/abc/counterfactuals", "GET") is True

    def test_summary_get_owned_by_debates_handler(self, handler):
        assert handler.can_handle("/api/v1/debates/abc/summary", "GET") is False

    def test_explain_shortcut_get(self, handler):
        assert handler.can_handle("/api/v1/explain/abc", "GET") is True

    def test_batch_create_post(self, handler):
        assert handler.can_handle("/api/v1/explainability/batch", "POST") is True

    def test_batch_create_get_rejected(self, handler):
        assert handler.can_handle("/api/v1/explainability/batch", "GET") is False

    def test_batch_status_get(self, handler):
        assert handler.can_handle("/api/v1/explainability/batch/batch-123/status", "GET") is True

    def test_batch_results_get(self, handler):
        assert handler.can_handle("/api/v1/explainability/batch/batch-123/results", "GET") is True

    def test_compare_post(self, handler):
        assert handler.can_handle("/api/v1/explainability/compare", "POST") is True

    def test_compare_get_rejected(self, handler):
        assert handler.can_handle("/api/v1/explainability/compare", "GET") is False

    def test_unrelated_path_rejected(self, handler):
        assert handler.can_handle("/api/v1/debates/abc/messages", "GET") is False

    def test_post_on_single_debate_rejected(self, handler):
        assert handler.can_handle("/api/v1/debates/abc/explanation", "POST") is False


# ============================================================================
# Test: Full Explanation endpoint
# ============================================================================


class TestFullExplanation:
    """Tests for _handle_full_explanation."""

    @pytest.mark.asyncio
    async def test_full_explanation_json(self, handler, decision):
        """GET /api/v1/debates/{id}/explanation returns JSON by default."""
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_full_explanation("debate-123", {}, False)

        assert result.status_code == 200
        assert result.content_type == "application/json"
        data = parse_response(result)
        assert data["debate_id"] == "debate-123"
        assert data["confidence"] == 0.85
        assert data["consensus_reached"] is True

    @pytest.mark.asyncio
    async def test_full_explanation_summary_format(self, handler, decision):
        """GET with ?format=summary returns markdown."""
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            with patch("aragora.explainability.ExplanationBuilder") as MockBuilder:
                MockBuilder.return_value.generate_summary.return_value = "## Summary\nTest"
                result = await handler._handle_full_explanation(
                    "debate-123", {"format": "summary"}, False
                )

        assert result.status_code == 200
        assert result.content_type == "text/markdown"
        assert b"Summary" in result.body

    @pytest.mark.asyncio
    async def test_full_explanation_not_found(self, handler):
        """Returns 404 when debate not found."""
        with patch.object(handler, "_get_or_build_decision", return_value=None):
            result = await handler._handle_full_explanation("nonexistent", {}, False)

        assert result.status_code == 404
        data = parse_response(result)
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_full_explanation_error_handling(self, handler):
        """Returns 500 on unexpected errors."""
        with patch.object(handler, "_get_or_build_decision", side_effect=ValueError("DB down")):
            result = await handler._handle_full_explanation("debate-123", {}, False)

        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_full_explanation_legacy_headers(self, handler, decision):
        """Legacy routes include Deprecation and Sunset headers."""
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_full_explanation("debate-123", {}, True)

        assert result.headers.get("Deprecation") == "true"
        assert result.headers.get("Sunset") == "2026-06-01"
        assert result.headers.get("X-API-Version") == "v1"

    @pytest.mark.asyncio
    async def test_full_explanation_non_legacy_no_deprecation(self, handler, decision):
        """Non-legacy routes do not include Deprecation header."""
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_full_explanation("debate-123", {}, False)

        assert result.headers.get("Deprecation") is None
        assert result.headers.get("X-API-Version") == "v1"


# ============================================================================
# Test: Evidence endpoint
# ============================================================================


class TestEvidence:
    """Tests for _handle_evidence."""

    @pytest.mark.asyncio
    async def test_evidence_default(self, handler, decision):
        """Returns all evidence sorted by relevance."""
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_evidence("debate-123", {}, False)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["debate_id"] == "debate-123"
        assert data["evidence_count"] == 3
        # Verify sorted by relevance descending
        scores = [e["relevance_score"] for e in data["evidence"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_evidence_min_relevance_filter(self, handler, decision):
        """Filters evidence by min_relevance parameter."""
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_evidence("debate-123", {"min_relevance": "0.5"}, False)

        data = parse_response(result)
        assert data["evidence_count"] == 2
        for e in data["evidence"]:
            assert e["relevance_score"] >= 0.5

    @pytest.mark.asyncio
    async def test_evidence_limit(self, handler, decision):
        """Respects limit parameter."""
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_evidence("debate-123", {"limit": "1"}, False)

        data = parse_response(result)
        assert data["evidence_count"] == 1

    @pytest.mark.asyncio
    async def test_evidence_not_found(self, handler):
        with patch.object(handler, "_get_or_build_decision", return_value=None):
            result = await handler._handle_evidence("nope", {}, False)

        assert result.status_code == 404


# ============================================================================
# Test: Vote Pivots endpoint
# ============================================================================


class TestVotePivots:
    """Tests for _handle_vote_pivots."""

    @pytest.mark.asyncio
    async def test_vote_pivots_default(self, handler, decision):
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_vote_pivots("debate-123", {}, False)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["debate_id"] == "debate-123"
        assert data["total_votes"] == 3
        assert data["pivotal_votes"] == 3
        assert data["agent_agreement_score"] == 0.91

    @pytest.mark.asyncio
    async def test_vote_pivots_min_influence_filter(self, handler, decision):
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_vote_pivots(
                "debate-123", {"min_influence": "0.6"}, False
            )

        data = parse_response(result)
        assert data["pivotal_votes"] == 1  # Only claude with influence=0.9
        assert data["total_votes"] == 3  # Total unchanged

    @pytest.mark.asyncio
    async def test_vote_pivots_not_found(self, handler):
        with patch.object(handler, "_get_or_build_decision", return_value=None):
            result = await handler._handle_vote_pivots("nope", {}, False)

        assert result.status_code == 404


# ============================================================================
# Test: Counterfactuals endpoint
# ============================================================================


class TestCounterfactuals:
    """Tests for _handle_counterfactuals."""

    @pytest.mark.asyncio
    async def test_counterfactuals_default(self, handler, decision):
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_counterfactuals("debate-123", {}, False)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["debate_id"] == "debate-123"
        assert data["counterfactual_count"] == 2

    @pytest.mark.asyncio
    async def test_counterfactuals_min_sensitivity_filter(self, handler, decision):
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler._handle_counterfactuals(
                "debate-123", {"min_sensitivity": "0.5"}, False
            )

        data = parse_response(result)
        assert data["counterfactual_count"] == 1  # Only sensitivity=0.8

    @pytest.mark.asyncio
    async def test_counterfactuals_not_found(self, handler):
        with patch.object(handler, "_get_or_build_decision", return_value=None):
            result = await handler._handle_counterfactuals("nope", {}, False)

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_counterfactuals_internal_error(self, handler):
        with patch.object(handler, "_get_or_build_decision", side_effect=ValueError("bad")):
            result = await handler._handle_counterfactuals("debate-123", {}, False)

        assert result.status_code == 500


# ============================================================================
# Test: Summary endpoint
# ============================================================================


class TestSummary:
    """Tests that summary remains owned by DebatesHandler."""

    def test_summary_helper_not_defined(self, handler):
        assert not hasattr(handler, "_handle_summary")

    @pytest.mark.asyncio
    async def test_summary_route_rejected(self, handler):
        result = await handler.handle.__wrapped__.__wrapped__(
            handler,
            "/api/v1/debates/d1/summary",
            {},
            MagicMock(),
        )

        assert result.status_code == 400


# ============================================================================
# Test: _get_or_build_decision
# ============================================================================


class TestGetOrBuildDecision:
    """Tests for decision retrieval and building."""

    @pytest.mark.asyncio
    async def test_returns_cached_decision(self, handler, decision):
        """Returns decision from cache when available."""
        _cache_decision("debate-123", decision)
        result = await handler._get_or_build_decision("debate-123")
        assert result is decision

    @pytest.mark.asyncio
    async def test_builds_and_caches_decision(self, handler, decision):
        """Builds decision from storage and caches it."""
        mock_db = MagicMock()
        mock_db.get.return_value = {
            "question": "Test?",
            "status": "concluded",
        }

        with patch(
            "aragora.server.storage.get_debates_db",
            return_value=mock_db,
        ):
            with patch("aragora.explainability.ExplanationBuilder") as MockBuilder:
                mock_builder = MockBuilder.return_value
                mock_builder.build = AsyncMock(return_value=decision)

                result = await handler._get_or_build_decision("debate-123")

        assert result is decision
        # Verify it was cached
        assert _get_cached_decision("debate-123") is decision

    @pytest.mark.asyncio
    async def test_returns_none_when_db_unavailable(self, handler):
        with patch(
            "aragora.server.storage.get_debates_db",
            return_value=None,
        ):
            result = await handler._get_or_build_decision("debate-123")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_debate_missing(self, handler):
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch(
            "aragora.server.storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await handler._get_or_build_decision("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_builder_error(self, handler):
        """Handles errors in the builder gracefully."""
        mock_db = MagicMock()
        mock_db.get.return_value = {"question": "Test?"}

        with patch(
            "aragora.server.storage.get_debates_db",
            return_value=mock_db,
        ):
            with patch(
                "aragora.explainability.ExplanationBuilder",
                side_effect=ImportError("builder broken"),
            ):
                result = await handler._get_or_build_decision("debate-123")

        assert result is None


# ============================================================================
# Test: _build_explanation_dict
# ============================================================================


class TestBuildExplanationDict:
    """Tests for batch explanation formatting."""

    def test_full_format_with_all(self, handler, decision):
        result = handler._build_explanation_dict(
            decision,
            include_evidence=True,
            include_counterfactuals=True,
            include_vote_pivots=True,
            format_type="full",
        )
        assert "evidence_chain" in result
        assert "counterfactuals" in result
        assert "vote_pivots" in result

    def test_full_format_exclude_evidence(self, handler, decision):
        result = handler._build_explanation_dict(
            decision,
            include_evidence=False,
            include_counterfactuals=False,
            include_vote_pivots=False,
            format_type="full",
        )
        assert "evidence_chain" not in result
        assert "counterfactuals" not in result
        assert "vote_pivots" not in result

    def test_minimal_format(self, handler, decision):
        result = handler._build_explanation_dict(decision, format_type="minimal")
        assert result["confidence"] == 0.85
        assert result["consensus_reached"] is True
        assert "debate_id" in result
        # No heavy fields in minimal
        assert "evidence_chain" not in result

    def test_summary_format(self, handler, decision):
        with patch("aragora.explainability.ExplanationBuilder") as MockBuilder:
            MockBuilder.return_value.generate_summary.return_value = "Test summary"
            result = handler._build_explanation_dict(decision, format_type="summary")

        assert result["summary"] == "Test summary"
        assert result["confidence"] == 0.85


# ============================================================================
# Test: Batch Processing
# ============================================================================


class TestBatchCreate:
    """Tests for _handle_batch_create."""

    def test_batch_create_success(self, handler):
        """Creates a batch job and returns 202."""
        body = {"debate_ids": ["d1", "d2", "d3"]}
        mock_handler = _post_handler_with_body(body)

        with patch.object(handler, "_start_batch_processing"):
            with patch("aragora.server.handlers.explainability._save_batch_job"):
                result = handler._handle_batch_create(mock_handler)

        assert result.status_code == 202
        data = parse_response(result)
        assert data["status"] == "pending"
        assert data["total_debates"] == 3
        assert "batch_id" in data
        assert "status_url" in data
        assert "results_url" in data

    def test_batch_create_empty_body(self, handler, mock_http_handler):
        """Returns 400 when no body is provided."""
        mock_http_handler.headers = {"Content-Length": "0"}
        result = handler._handle_batch_create(mock_http_handler)
        assert result.status_code == 400

    def test_batch_create_no_debate_ids(self, handler):
        """Returns 400 when debate_ids is missing."""
        mock_handler = _post_handler_with_body({"options": {}})
        result = handler._handle_batch_create(mock_handler)
        assert result.status_code == 400

    def test_batch_create_invalid_json(self, handler):
        """Returns 400 on invalid JSON body."""
        h = MagicMock()
        h.client_address = ("127.0.0.1", 12345)
        h.headers = {"Content-Length": "10"}
        h.rfile = BytesIO(b"not json!!")
        h.command = "POST"
        result = handler._handle_batch_create(h)
        assert result.status_code == 400

    def test_batch_create_exceeds_max_size(self, handler):
        """Returns 400 when batch size exceeds MAX_BATCH_SIZE."""
        body = {"debate_ids": [f"d{i}" for i in range(101)]}
        mock_handler = _post_handler_with_body(body)
        result = handler._handle_batch_create(mock_handler)
        assert result.status_code == 400
        data = parse_response(result)
        assert "100" in data["error"]

    def test_batch_create_debate_ids_not_array(self, handler):
        """Returns 400 when debate_ids is not an array."""
        mock_handler = _post_handler_with_body({"debate_ids": "not-an-array"})
        result = handler._handle_batch_create(mock_handler)
        assert result.status_code == 400


# ============================================================================
# Test: Batch Status and Results
# ============================================================================


class TestBatchStatusAndResults:
    """Tests for _handle_batch_status and _handle_batch_results."""

    def test_batch_status_not_found(self, handler):
        with patch(
            "aragora.server.handlers.explainability._get_batch_job",
            return_value=None,
        ):
            result = handler._handle_batch_status("missing-batch", TEST_ORG)

        assert result.status_code == 404

    def test_batch_status_found(self, handler):
        job = BatchJob(
            batch_id="batch-001",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1", "d2"],
            status=BatchStatus.PROCESSING,
        )
        job.processed_count = 1
        with patch(
            "aragora.server.handlers.explainability._get_batch_job",
            return_value=job,
        ):
            result = handler._handle_batch_status("batch-001", TEST_ORG)

        assert result.status_code == 200
        data = parse_response(result)
        assert data["batch_id"] == "batch-001"
        assert data["status"] == "processing"
        assert data["total_debates"] == 2
        assert data["processed_count"] == 1

    def test_batch_results_not_found(self, handler):
        with patch(
            "aragora.server.handlers.explainability._get_batch_job",
            return_value=None,
        ):
            result = handler._handle_batch_results("missing", {}, TEST_ORG)

        assert result.status_code == 404

    def test_batch_results_pending(self, handler):
        job = BatchJob(
            batch_id="batch-001",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1"],
            status=BatchStatus.PENDING,
        )
        with patch(
            "aragora.server.handlers.explainability._get_batch_job",
            return_value=job,
        ):
            result = handler._handle_batch_results("batch-001", {}, TEST_ORG)

        assert result.status_code == 202

    def test_batch_results_processing_no_partial(self, handler):
        job = BatchJob(
            batch_id="batch-001",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1"],
            status=BatchStatus.PROCESSING,
        )
        with patch(
            "aragora.server.handlers.explainability._get_batch_job",
            return_value=job,
        ):
            result = handler._handle_batch_results("batch-001", {}, TEST_ORG)

        assert result.status_code == 202
        data = parse_response(result)
        assert "include_partial=true" in data.get("message", "")

    def test_batch_results_completed_with_pagination(self, handler):
        job = BatchJob(
            batch_id="batch-001",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1", "d2", "d3"],
            status=BatchStatus.COMPLETED,
        )
        job.results = [BatchDebateResult(debate_id=f"d{i}", status="success") for i in range(3)]
        job.processed_count = 3
        with patch(
            "aragora.server.handlers.explainability._get_batch_job",
            return_value=job,
        ):
            result = handler._handle_batch_results(
                "batch-001", {"offset": "0", "limit": "2"}, TEST_ORG
            )

        data = parse_response(result)
        assert len(data["results"]) == 2
        assert data["pagination"]["total"] == 3
        assert data["pagination"]["has_more"] is True


# ============================================================================
# Test: _process_batch (async batch processing logic)
# ============================================================================


class TestProcessBatch:
    """Tests for the async batch processing pipeline."""

    @pytest.mark.asyncio
    async def test_process_batch_all_success(self, handler, decision):
        job = BatchJob(
            batch_id="batch-test",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1", "d2"],
        )
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            with patch(
                "aragora.server.handlers.explainability._save_batch_job_async",
                new_callable=AsyncMock,
            ):
                await handler._process_batch(job)

        assert job.status == BatchStatus.COMPLETED
        assert job.processed_count == 2
        assert all(r.status == "success" for r in job.results)

    @pytest.mark.asyncio
    async def test_process_batch_all_not_found(self, handler):
        job = BatchJob(
            batch_id="batch-test",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1", "d2"],
        )
        with patch.object(handler, "_get_or_build_decision", return_value=None):
            with patch(
                "aragora.server.handlers.explainability._save_batch_job_async",
                new_callable=AsyncMock,
            ):
                await handler._process_batch(job)

        assert job.status == BatchStatus.FAILED
        assert all(r.status == "not_found" for r in job.results)

    @pytest.mark.asyncio
    async def test_process_batch_partial_failure(self, handler, decision):
        job = BatchJob(
            batch_id="batch-test",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1", "d2"],
        )

        call_count = 0

        async def mixed_results(debate_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return decision
            return None

        with patch.object(handler, "_get_or_build_decision", side_effect=mixed_results):
            with patch(
                "aragora.server.handlers.explainability._save_batch_job_async",
                new_callable=AsyncMock,
            ):
                await handler._process_batch(job)

        assert job.status == BatchStatus.PARTIAL
        statuses = {r.status for r in job.results}
        assert "success" in statuses
        assert "not_found" in statuses


# ============================================================================
# Test: Compare endpoint
# ============================================================================


class TestCompare:
    """Tests for _handle_compare."""

    @pytest.mark.asyncio
    async def test_compare_two_debates(self, handler):
        d1 = _make_decision("debate-1", confidence=0.9, consensus_reached=True)
        d2 = _make_decision("debate-2", confidence=0.6, consensus_reached=False)

        body = {"debate_ids": ["debate-1", "debate-2"]}
        mock_handler = _post_handler_with_body(body)

        async def mock_get(debate_id):
            return {"debate-1": d1, "debate-2": d2}.get(debate_id)

        with patch.object(handler, "_get_or_build_decision", side_effect=mock_get):
            result = await handler._handle_compare(mock_handler)

        assert result.status_code == 200
        data = parse_response(result)
        assert len(data["debates_compared"]) == 2
        assert data["comparison"]["confidence"]["debate-1"] == 0.9
        assert data["comparison"]["confidence"]["debate-2"] == 0.6
        assert data["comparison"]["confidence_stats"]["spread"] == pytest.approx(0.3)
        assert data["comparison"]["consensus_agreement"] is False

    @pytest.mark.asyncio
    async def test_compare_empty_body(self, handler):
        h = MagicMock()
        h.headers = {"Content-Length": "0"}
        result = await handler._handle_compare(h)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_compare_too_few_debates(self, handler):
        body = {"debate_ids": ["only-one"]}
        mock_handler = _post_handler_with_body(body)
        result = await handler._handle_compare(mock_handler)
        assert result.status_code == 400
        data = parse_response(result)
        assert "2" in data["error"]

    @pytest.mark.asyncio
    async def test_compare_too_many_debates(self, handler):
        body = {"debate_ids": [f"d{i}" for i in range(11)]}
        mock_handler = _post_handler_with_body(body)
        result = await handler._handle_compare(mock_handler)
        assert result.status_code == 400
        assert b"10" in result.body

    @pytest.mark.asyncio
    async def test_compare_not_enough_valid(self, handler):
        """Returns 404 when fewer than 2 debates resolve."""
        body = {"debate_ids": ["d1", "d2"]}
        mock_handler = _post_handler_with_body(body)

        async def mock_get(debate_id):
            if debate_id == "d1":
                return _make_decision("d1")
            return None

        with patch.object(handler, "_get_or_build_decision", side_effect=mock_get):
            result = await handler._handle_compare(mock_handler)

        assert result.status_code == 404


# ============================================================================
# Test: handle() routing
# ============================================================================


class TestHandleRouting:
    """Tests that the top-level handle() method dispatches correctly."""

    @pytest.mark.asyncio
    async def test_routes_to_explanation(self, handler, decision):
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler.handle.__wrapped__.__wrapped__(
                handler,
                "/api/v1/debates/d1/explanation",
                {},
                MagicMock(),
            )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_routes_to_explain_shortcut(self, handler, decision):
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler.handle.__wrapped__.__wrapped__(
                handler,
                "/api/v1/explain/d1",
                {},
                MagicMock(),
            )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_routes_to_evidence(self, handler, decision):
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler.handle.__wrapped__.__wrapped__(
                handler,
                "/api/v1/debates/d1/evidence",
                {},
                MagicMock(),
            )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_routes_to_counterfactuals(self, handler, decision):
        with patch.object(handler, "_get_or_build_decision", return_value=decision):
            result = await handler.handle.__wrapped__.__wrapped__(
                handler,
                "/api/v1/debates/d1/counterfactuals",
                {},
                MagicMock(),
            )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_summary_route_owned_by_debates_handler(self, handler):
        result = await handler.handle.__wrapped__.__wrapped__(
            handler,
            "/api/v1/debates/d1/summary",
            {},
            MagicMock(),
        )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_routes_invalid_returns_400(self, handler):
        result = await handler.handle.__wrapped__.__wrapped__(
            handler,
            "/api/v1/debates/d1/unknown_endpoint",
            {},
            MagicMock(),
        )
        assert result.status_code == 400


# ============================================================================
# Test: BatchDebateResult and BatchJob dataclasses
# ============================================================================


class TestDataclasses:
    """Tests for BatchDebateResult and BatchJob data structures."""

    def test_batch_debate_result_to_dict_success(self):
        r = BatchDebateResult(
            debate_id="d1",
            status="success",
            explanation={"confidence": 0.9},
            processing_time_ms=42.5,
        )
        d = r.to_dict()
        assert d["debate_id"] == "d1"
        assert d["status"] == "success"
        assert d["explanation"]["confidence"] == 0.9
        assert "error" not in d

    def test_batch_debate_result_to_dict_error(self):
        r = BatchDebateResult(
            debate_id="d2",
            status="error",
            error="Something went wrong",
            processing_time_ms=10.0,
        )
        d = r.to_dict()
        assert d["error"] == "Something went wrong"
        assert "explanation" not in d

    def test_batch_job_to_dict(self):
        job = BatchJob(
            batch_id="batch-001",
            debate_ids=["d1", "d2", "d3"],
            status=BatchStatus.COMPLETED,
        )
        job.processed_count = 3
        job.results = [
            BatchDebateResult(debate_id="d1", status="success"),
            BatchDebateResult(debate_id="d2", status="success"),
            BatchDebateResult(debate_id="d3", status="error", error="not found"),
        ]
        d = job.to_dict()
        assert d["batch_id"] == "batch-001"
        assert d["status"] == "completed"
        assert d["total_debates"] == 3
        assert d["success_count"] == 2
        assert d["error_count"] == 1
        assert d["progress_pct"] == 100.0

    def test_batch_job_progress_pct_empty(self):
        job = BatchJob(batch_id="b", debate_ids=[])
        assert job.to_dict()["progress_pct"] == 0


# ============================================================================
# Test: Handler factory
# ============================================================================


class TestHandlerFactory:
    """Tests for get_explainability_handler singleton factory."""

    def test_creates_handler_with_context(self):
        ctx: dict[str, Any] = {"elo_system": MagicMock()}
        h = get_explainability_handler(ctx)
        assert isinstance(h, ExplainabilityHandler)

    def test_returns_same_instance(self):
        h1 = get_explainability_handler({})
        h2 = get_explainability_handler({})
        assert h1 is h2

    def test_creates_with_none_context(self):
        h = get_explainability_handler(None)
        assert isinstance(h, ExplainabilityHandler)


# ============================================================================
# Test: Legacy route detection
# ============================================================================


class TestLegacyRouteDetection:
    """Tests for _is_legacy_route."""

    def test_api_v1_is_not_legacy(self, handler):
        assert handler._is_legacy_route("/api/v1/debates/d1/explanation") is False

    def test_non_v1_is_legacy(self, handler):
        assert handler._is_legacy_route("/api/debates/d1/explanation") is True
