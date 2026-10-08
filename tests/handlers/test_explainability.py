"""
Tests for Explainability Handler.

Tests for debate decision explainability endpoints:
- GET /api/v1/debates/{id}/explanation - Full decision explanation
- GET /api/v1/debates/{id}/evidence - Evidence chain
- GET /api/v1/debates/{id}/votes/pivots - Vote influence analysis
- GET /api/v1/debates/{id}/counterfactuals - Counterfactual analysis
- GET /api/v1/debates/{id}/summary - Human-readable summary
- POST /api/v1/explainability/batch - Batch processing
- POST /api/v1/explainability/compare - Compare decisions
"""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

# Explainability reads are org-scoped; requests act for the org that owns every debate.
pytestmark = pytest.mark.usefixtures("explainability_org_member")

TEST_ORG = "test-org-001"
# Batch jobs answer status and results only for the org that created them.
OWNED_BY_TEST_ORG = {"_owner_org_id": TEST_ORG}


class TestExplainabilityHandlerRouting:
    """Tests for route matching."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    def test_can_handle_explanation_route(self, handler):
        """Test matching explanation route."""
        assert handler.can_handle("/api/v1/debates/debate_123/explanation", "GET")

    def test_can_handle_evidence_route(self, handler):
        """Test matching evidence route."""
        assert handler.can_handle("/api/v1/debates/debate_123/evidence", "GET")

    def test_can_handle_vote_pivots_route(self, handler):
        """Test matching vote pivots route."""
        assert handler.can_handle("/api/v1/debates/debate_123/votes/pivots", "GET")

    def test_can_handle_counterfactuals_route(self, handler):
        """Test matching counterfactuals route."""
        assert handler.can_handle("/api/v1/debates/debate_123/counterfactuals", "GET")

    def test_does_not_handle_summary_route(self, handler):
        """Summary is owned by DebatesHandler, not ExplainabilityHandler.

        ExplainabilityHandler previously also claimed
        /api/v1/debates/{id}/summary but was first-wins shadowed by
        DebatesHandler since registration. The duplicate claim was removed
        (run-20260611 PROD route-collision lane), so this handler must no
        longer match the summary route.
        """
        assert not handler.can_handle("/api/v1/debates/debate_123/summary", "GET")

    def test_can_handle_explain_shortcut(self, handler):
        """Test matching explain shortcut route."""
        assert handler.can_handle("/api/v1/explain/debate_123", "GET")

    def test_can_handle_batch_create(self, handler):
        """Test matching batch create route."""
        assert handler.can_handle("/api/v1/explainability/batch", "POST")

    def test_can_handle_batch_status(self, handler):
        """Test matching batch status route."""
        assert handler.can_handle("/api/v1/explainability/batch/batch_123/status", "GET")

    def test_can_handle_batch_results(self, handler):
        """Test matching batch results route."""
        assert handler.can_handle("/api/v1/explainability/batch/batch_123/results", "GET")

    def test_can_handle_compare(self, handler):
        """Test matching compare route."""
        assert handler.can_handle("/api/v1/explainability/compare", "POST")

    def test_rejects_post_on_get_endpoints(self, handler):
        """Test rejecting POST on GET-only endpoints."""
        assert not handler.can_handle("/api/v1/debates/debate_123/explanation", "POST")

    def test_rejects_get_on_batch_create(self, handler):
        """Test rejecting GET on batch create endpoint."""
        assert not handler.can_handle("/api/v1/explainability/batch", "GET")

    def test_rejects_unknown_route(self, handler):
        """Test rejecting unknown routes."""
        assert not handler.can_handle("/api/v1/debates/debate_123/unknown", "GET")


class TestExplainabilityHandlerExplanation:
    """Tests for full explanation endpoint."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    @pytest.fixture
    def mock_decision(self):
        """Create mock decision object."""
        decision = MagicMock()
        decision.debate_id = "debate_123"
        decision.outcome = "consensus"
        decision.confidence = 0.85
        decision.factors = [
            {"name": "evidence", "weight": 0.4, "value": 0.9},
            {"name": "agent_agreement", "weight": 0.3, "value": 0.8},
        ]
        decision.to_dict = MagicMock(
            return_value={
                "debate_id": "debate_123",
                "outcome": "consensus",
                "confidence": 0.85,
                "factors": decision.factors,
            }
        )
        return decision

    @pytest.mark.asyncio
    async def test_handle_explanation_success(self, handler, mock_decision):
        """Test successful explanation request."""
        mock_handler = MagicMock()

        with patch.object(
            handler, "_get_or_build_decision", new=AsyncMock(return_value=mock_decision)
        ):
            result = await handler.handle(
                "/api/v1/debates/debate_123/explanation", {}, mock_handler
            )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_explanation_not_found(self, handler):
        """Test explanation for non-existent debate."""
        mock_handler = MagicMock()

        with patch.object(handler, "_get_or_build_decision", new=AsyncMock(return_value=None)):
            result = await handler.handle(
                "/api/v1/debates/nonexistent/explanation", {}, mock_handler
            )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_handle_explanation_with_format_param(self, handler, mock_decision):
        """Test explanation with format parameter."""
        mock_handler = MagicMock()

        with patch.object(
            handler, "_get_or_build_decision", new=AsyncMock(return_value=mock_decision)
        ):
            with patch("aragora.explainability.ExplanationBuilder") as MockBuilder:
                MockBuilder.return_value.generate_summary.return_value = "Summary text"
                result = await handler.handle(
                    "/api/v1/debates/debate_123/explanation",
                    {"format": "summary"},
                    mock_handler,
                )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_explain_shortcut(self, handler, mock_decision):
        """Test explain shortcut route."""
        mock_handler = MagicMock()

        with patch.object(
            handler, "_get_or_build_decision", new=AsyncMock(return_value=mock_decision)
        ):
            result = await handler.handle("/api/v1/explain/debate_123", {}, mock_handler)

        assert result.status_code == 200


class TestExplainabilityHandlerEvidence:
    """Tests for evidence endpoint."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    @pytest.fixture
    def mock_decision(self):
        """Create mock decision with evidence."""
        decision = MagicMock()
        decision.debate_id = "debate_123"
        decision.evidence_quality_score = 0.85

        # Create proper evidence items with required attributes
        ev1 = MagicMock()
        ev1.relevance_score = 0.9
        ev1.to_dict.return_value = {"id": "ev_1", "source": "document", "relevance_score": 0.9}

        ev2 = MagicMock()
        ev2.relevance_score = 0.7
        ev2.to_dict.return_value = {"id": "ev_2", "source": "url", "relevance_score": 0.7}

        decision.evidence_chain = [ev1, ev2]
        return decision

    @pytest.mark.asyncio
    async def test_handle_evidence_success(self, handler, mock_decision):
        """Test successful evidence request."""
        mock_handler = MagicMock()

        with patch.object(
            handler, "_get_or_build_decision", new=AsyncMock(return_value=mock_decision)
        ):
            result = await handler.handle("/api/v1/debates/debate_123/evidence", {}, mock_handler)

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_evidence_not_found(self, handler):
        """Test evidence for non-existent debate."""
        mock_handler = MagicMock()

        with patch.object(handler, "_get_or_build_decision", new=AsyncMock(return_value=None)):
            result = await handler.handle("/api/v1/debates/nonexistent/evidence", {}, mock_handler)

        assert result.status_code == 404


class TestExplainabilityHandlerVotePivots:
    """Tests for vote pivots endpoint."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    @pytest.fixture
    def mock_decision(self):
        """Create mock decision with vote pivots."""
        decision = MagicMock()
        decision.debate_id = "debate_123"
        decision.agent_agreement_score = 0.85

        # Create proper vote pivot items with required attributes
        vp1 = MagicMock()
        vp1.influence_score = 0.3
        vp1.to_dict.return_value = {"agent": "claude", "vote": "approve", "influence_score": 0.3}

        vp2 = MagicMock()
        vp2.influence_score = 0.25
        vp2.to_dict.return_value = {"agent": "gpt4", "vote": "approve", "influence_score": 0.25}

        decision.vote_pivots = [vp1, vp2]
        return decision

    @pytest.mark.asyncio
    async def test_handle_vote_pivots_success(self, handler, mock_decision):
        """Test successful vote pivots request."""
        mock_handler = MagicMock()

        with patch.object(
            handler, "_get_or_build_decision", new=AsyncMock(return_value=mock_decision)
        ):
            result = await handler.handle(
                "/api/v1/debates/debate_123/votes/pivots", {}, mock_handler
            )

        assert result.status_code == 200


class TestExplainabilityHandlerCounterfactuals:
    """Tests for counterfactuals endpoint."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    @pytest.fixture
    def mock_decision(self):
        """Create mock decision with counterfactuals."""
        decision = MagicMock()
        decision.debate_id = "debate_123"

        # Create proper counterfactual items with required attributes
        cf1 = MagicMock()
        cf1.sensitivity = 0.7
        cf1.to_dict.return_value = {
            "scenario": "If claude voted reject",
            "outcome_change": "consensus -> split",
            "sensitivity": 0.7,
        }

        decision.counterfactuals = [cf1]
        return decision

    @pytest.mark.asyncio
    async def test_handle_counterfactuals_success(self, handler, mock_decision):
        """Test successful counterfactuals request."""
        mock_handler = MagicMock()

        with patch.object(
            handler, "_get_or_build_decision", new=AsyncMock(return_value=mock_decision)
        ):
            result = await handler.handle(
                "/api/v1/debates/debate_123/counterfactuals", {}, mock_handler
            )

        assert result.status_code == 200


class TestExplainabilityHandlerSummary:
    """Summary ownership moved to DebatesHandler (run-20260611 PROD lane).

    ``/api/v1/debates/{id}/summary`` is served by DebatesHandler
    (``_get_summary`` via ``aragora.debate.summarizer.summarize_debate``).
    ExplainabilityHandler used to carry a duplicate, first-wins-shadowed claim
    on the same path; the claim, its dispatch branch, and the now-dead
    ``_handle_summary`` method were removed. These tests pin that removal.
    """

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    @pytest.mark.asyncio
    async def test_handle_summary_not_dispatched(self, handler):
        """ExplainabilityHandler must not dispatch the summary endpoint."""
        mock_handler = MagicMock()

        result = await handler.handle("/api/v1/debates/debate_123/summary", {}, mock_handler)

        # No summary branch remains: dispatch falls through to the invalid-endpoint
        # response rather than generating a summary.
        assert result is not None
        assert result.status_code == 400

    def test_handle_summary_method_removed(self, handler):
        """The dead ``_handle_summary`` method must no longer exist."""
        assert not hasattr(handler, "_handle_summary")


class TestExplainabilityHandlerBatch:
    """Tests for batch processing endpoints."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    def _create_mock_handler(self, body_data):
        """Create mock handler with proper headers and rfile."""
        import io

        body_bytes = json.dumps(body_data).encode("utf-8")
        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": str(len(body_bytes))}
        mock_handler.rfile = io.BytesIO(body_bytes)
        return mock_handler

    @pytest.mark.asyncio
    async def test_handle_batch_create_success(self, handler):
        """Test successful batch job creation."""
        mock_handler = self._create_mock_handler(
            {"debate_ids": ["debate_1", "debate_2", "debate_3"]}
        )

        with patch("aragora.server.handlers.explainability._save_batch_job"):
            with patch.object(handler, "_start_batch_processing"):
                result = await handler.handle("/api/v1/explainability/batch", {}, mock_handler)

        # Should create batch job
        assert result.status_code == 202

    @pytest.mark.asyncio
    async def test_handle_batch_create_missing_debate_ids(self, handler):
        """Test batch creation without debate_ids."""
        mock_handler = self._create_mock_handler({})

        result = await handler.handle("/api/v1/explainability/batch", {}, mock_handler)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_handle_batch_create_empty_debate_ids(self, handler):
        """Test batch creation with empty debate_ids."""
        mock_handler = self._create_mock_handler({"debate_ids": []})

        result = await handler.handle("/api/v1/explainability/batch", {}, mock_handler)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_handle_batch_create_exceeds_max_size(self, handler):
        """Test batch creation exceeding max size."""
        mock_handler = self._create_mock_handler(
            {"debate_ids": [f"debate_{i}" for i in range(150)]}
        )

        result = await handler.handle("/api/v1/explainability/batch", {}, mock_handler)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_handle_batch_create_empty_body(self, handler):
        """Test batch creation with empty body."""
        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": "0"}

        result = await handler.handle("/api/v1/explainability/batch", {}, mock_handler)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_handle_batch_status_success(self, handler):
        """Test getting batch job status."""
        from aragora.server.handlers.explainability import BatchJob, BatchStatus

        mock_job = BatchJob(
            batch_id="batch_123",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["debate_1", "debate_2"],
            status=BatchStatus.PROCESSING,
            processed_count=1,
        )

        with patch("aragora.server.handlers.explainability._get_batch_job", return_value=mock_job):
            result = await handler.handle(
                "/api/v1/explainability/batch/batch_123/status", {}, MagicMock()
            )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["batch_id"] == "batch_123"
        assert data["status"] == "processing"

    @pytest.mark.asyncio
    async def test_handle_batch_status_not_found(self, handler):
        """Test batch status for non-existent job."""
        with patch("aragora.server.handlers.explainability._get_batch_job", return_value=None):
            result = await handler.handle(
                "/api/v1/explainability/batch/nonexistent/status", {}, MagicMock()
            )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_handle_batch_results_success(self, handler):
        """Test getting batch job results."""
        from aragora.server.handlers.explainability import (
            BatchJob,
            BatchStatus,
            BatchDebateResult,
        )

        mock_job = BatchJob(
            batch_id="batch_123",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["debate_1", "debate_2"],
            status=BatchStatus.COMPLETED,
            processed_count=2,
            results=[
                BatchDebateResult(
                    debate_id="debate_1",
                    status="success",
                    explanation={"outcome": "consensus"},
                ),
                BatchDebateResult(
                    debate_id="debate_2",
                    status="success",
                    explanation={"outcome": "split"},
                ),
            ],
        )

        with patch("aragora.server.handlers.explainability._get_batch_job", return_value=mock_job):
            result = await handler.handle(
                "/api/v1/explainability/batch/batch_123/results", {}, MagicMock()
            )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert len(data["results"]) == 2

    @pytest.mark.asyncio
    async def test_handle_batch_results_not_found(self, handler):
        """Test batch results for non-existent job."""
        with patch("aragora.server.handlers.explainability._get_batch_job", return_value=None):
            result = await handler.handle(
                "/api/v1/explainability/batch/nonexistent/results", {}, MagicMock()
            )

        assert result.status_code == 404


class TestExplainabilityHandlerCompare:
    """Tests for compare endpoint."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    def _create_mock_handler(self, body_data):
        """Create mock handler with proper headers and rfile."""
        import io

        body_bytes = json.dumps(body_data).encode("utf-8")
        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": str(len(body_bytes))}
        mock_handler.rfile = io.BytesIO(body_bytes)
        return mock_handler

    @pytest.mark.asyncio
    async def test_handle_compare_success(self, handler):
        """Test successful comparison."""
        mock_handler = self._create_mock_handler({"debate_ids": ["debate_1", "debate_2"]})

        mock_decision_1 = MagicMock()
        mock_decision_1.debate_id = "debate_1"
        mock_decision_1.confidence = 0.9
        mock_decision_1.consensus_reached = True
        mock_decision_1.evidence_quality_score = 0.85

        mock_decision_2 = MagicMock()
        mock_decision_2.debate_id = "debate_2"
        mock_decision_2.confidence = 0.6
        mock_decision_2.consensus_reached = False
        mock_decision_2.evidence_quality_score = 0.7

        with patch.object(
            handler,
            "_get_or_build_decision",
            new=AsyncMock(side_effect=[mock_decision_1, mock_decision_2]),
        ):
            result = await handler.handle("/api/v1/explainability/compare", {}, mock_handler)

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_compare_missing_debate_ids(self, handler):
        """Test comparison without debate_ids."""
        mock_handler = self._create_mock_handler({})

        result = await handler.handle("/api/v1/explainability/compare", {}, mock_handler)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_handle_compare_single_debate(self, handler):
        """Test comparison with only one debate."""
        mock_handler = self._create_mock_handler({"debate_ids": ["debate_1"]})

        result = await handler.handle("/api/v1/explainability/compare", {}, mock_handler)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_handle_compare_empty_body(self, handler):
        """Test comparison with empty body."""
        mock_handler = MagicMock()
        mock_handler.headers = {"Content-Length": "0"}

        result = await handler.handle("/api/v1/explainability/compare", {}, mock_handler)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_handle_compare_too_many_debates(self, handler):
        """Test comparison with too many debates."""
        mock_handler = self._create_mock_handler({"debate_ids": [f"debate_{i}" for i in range(15)]})

        result = await handler.handle("/api/v1/explainability/compare", {}, mock_handler)

        assert result.status_code == 400


class TestExplainabilityHandlerCaching:
    """Tests for decision caching."""

    def test_cache_hit(self):
        """Test cache hit returns cached decision."""
        from aragora.server.handlers.explainability import (
            _cache_decision,
            _get_cached_decision,
        )

        mock_decision = MagicMock()
        _cache_decision("debate_123", mock_decision)

        result = _get_cached_decision("debate_123")

        assert result is mock_decision

    def test_cache_miss(self):
        """Test cache miss returns None."""
        from aragora.server.handlers.explainability import _get_cached_decision

        result = _get_cached_decision("nonexistent_debate")

        assert result is None

    def test_cache_expiry(self):
        """Test cache expires after TTL."""
        from aragora.server.handlers.explainability import (
            _cache_decision,
            _decision_cache,
            _get_cached_decision,
            CACHE_TTL_SECONDS,
        )
        import time

        mock_decision = MagicMock()
        _cache_decision("debate_old", mock_decision)

        # Simulate expired cache by backdating the stored timestamp
        # _LRUTTLCache stores (value, cached_at) tuples
        value, _ = _decision_cache._cache["debate_old"]
        _decision_cache._cache["debate_old"] = (value, time.time() - CACHE_TTL_SECONDS - 1)

        result = _get_cached_decision("debate_old")

        assert result is None


class TestExplainabilityHandlerHeaders:
    """Tests for response headers."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    def test_adds_version_header(self, handler):
        """Test API version header is added."""
        from aragora.server.handlers.base import HandlerResult

        result = HandlerResult(status_code=200, content_type="application/json", body=b"{}")

        result = handler._add_headers(result, is_legacy=False)

        assert result.headers["X-API-Version"] == "v1"

    def test_adds_deprecation_headers_for_legacy(self, handler):
        """Test deprecation headers for legacy routes."""
        from aragora.server.handlers.base import HandlerResult

        result = HandlerResult(status_code=200, content_type="application/json", body=b"{}")

        result = handler._add_headers(result, is_legacy=True)

        assert result.headers["Deprecation"] == "true"
        assert "Sunset" in result.headers


class TestBatchJobModel:
    """Tests for BatchJob data model."""

    def test_batch_job_to_dict(self):
        """Test BatchJob serialization."""
        from aragora.server.handlers.explainability import BatchJob, BatchStatus

        job = BatchJob(
            batch_id="batch_123",
            debate_ids=["debate_1", "debate_2", "debate_3"],
            status=BatchStatus.PROCESSING,
            processed_count=1,
        )

        data = job.to_dict()

        assert data["batch_id"] == "batch_123"
        assert data["total_debates"] == 3
        assert data["processed_count"] == 1
        assert data["status"] == "processing"
        assert data["progress_pct"] == pytest.approx(33.3, 0.1)

    def test_batch_debate_result_to_dict(self):
        """Test BatchDebateResult serialization."""
        from aragora.server.handlers.explainability import BatchDebateResult

        result = BatchDebateResult(
            debate_id="debate_123",
            status="success",
            explanation={"outcome": "consensus"},
            processing_time_ms=150.5,
        )

        data = result.to_dict()

        assert data["debate_id"] == "debate_123"
        assert data["status"] == "success"
        assert data["explanation"]["outcome"] == "consensus"
        assert data["processing_time_ms"] == 150.5

    def test_batch_debate_result_error(self):
        """Test BatchDebateResult with error."""
        from aragora.server.handlers.explainability import BatchDebateResult

        result = BatchDebateResult(
            debate_id="debate_123",
            status="error",
            error="Debate not found",
        )

        data = result.to_dict()

        assert data["status"] == "error"
        assert data["error"] == "Debate not found"
        assert "explanation" not in data
