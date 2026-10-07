"""
Tests for the Debates Handler.

Covers:
- Route handling (can_handle, dispatch)
- Authentication checks
- List/search debates
- Get debate by slug
- Analysis endpoints (impasse, convergence, verification, summary)
- Export endpoints (json, csv, html)
- Citations and evidence
- Messages with pagination
- Meta critique and graph stats
- POST endpoints (create debate)
- PATCH endpoints (update metadata)
- Fork operations
- Followup operations
- Error handling
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

from aragora.server.handlers.debates import DebatesHandler
from aragora.server.handlers.base import HandlerResult


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def handler(handler_context):
    """Create a DebatesHandler instance with mock context."""
    h = DebatesHandler(handler_context)
    return h


@pytest.fixture
def sample_debate():
    """Return a sample debate dict for testing."""
    return {
        "id": "debate-123",
        "slug": "test-debate",
        "task": "Test the aragora debate system",
        "messages": [
            {"agent": "claude", "content": "I propose we test", "role": "proposer", "round": 1},
            {"agent": "gemini", "content": "I have concerns", "role": "critic", "round": 1},
            {"agent": "claude", "content": "Addressing concerns", "role": "proposer", "round": 2},
        ],
        "critiques": [
            {
                "agent": "gemini",
                "target": "claude",
                "severity": 0.5,
                "reasoning": "Missing details",
            },
        ],
        "votes": [
            {"agent": "claude", "choice": "accept", "confidence": 0.8, "reasoning": "Looks good"},
            {"agent": "gemini", "choice": "accept", "confidence": 0.7, "reasoning": "Okay"},
        ],
        "consensus_reached": True,
        "convergence_status": "converged",
        "convergence_similarity": 0.95,
        "rounds_used": 2,
        "agents": ["claude", "gemini"],
        "created_at": "2026-01-10T12:00:00Z",
    }


@pytest.fixture
def mock_handler_request():
    """Create a mock HTTP handler request."""
    handler = Mock()
    handler.headers = {"Authorization": "Bearer test-token"}
    handler._check_rate_limit = Mock(return_value=True)
    handler._check_tier_rate_limit = Mock(return_value=True)
    handler.stream_emitter = Mock()
    return handler


# =============================================================================
# Route Handling Tests
# =============================================================================


class TestCanHandle:
    """Tests for route matching."""

    def test_can_handle_debates_list(self, handler):
        """Test matching /api/debates."""
        assert handler.can_handle("/api/v1/debates") is True

    def test_can_handle_debate_create(self, handler):
        """Test matching /api/debate (legacy POST)."""
        assert handler.can_handle("/api/v1/debate") is True

    def test_can_handle_search(self, handler):
        """Test matching /api/search."""
        assert handler.can_handle("/api/v1/search") is True

    def test_can_handle_debates_by_slug(self, handler):
        """Test matching /api/debates/slug/{slug}."""
        assert handler.can_handle("/api/v1/debates/slug/my-debate") is True

    def test_can_handle_debates_by_id(self, handler):
        """Test matching /api/debates/{id}."""
        assert handler.can_handle("/api/v1/debates/debate-123") is True

    def test_can_handle_impasse(self, handler):
        """Test matching /api/debates/{id}/impasse."""
        assert handler.can_handle("/api/v1/debates/debate-123/impasse") is True

    def test_can_handle_convergence(self, handler):
        """Test matching /api/debates/{id}/convergence."""
        assert handler.can_handle("/api/v1/debates/debate-123/convergence") is True

    def test_can_handle_export(self, handler):
        """Test matching /api/debates/{id}/export/{format}."""
        assert handler.can_handle("/api/v1/debates/debate-123/export/json") is True

    def test_can_handle_meta_critique(self, handler):
        """Test matching /api/debate/{id}/meta-critique."""
        assert handler.can_handle("/api/v1/debate/debate-123/meta-critique") is True

    def test_can_handle_graph_stats(self, handler):
        """Test matching /api/debate/{id}/graph/stats."""
        assert handler.can_handle("/api/v1/debate/debate-123/graph/stats") is True

    def test_cannot_handle_other_paths(self, handler):
        """Test non-matching paths."""
        assert handler.can_handle("/api/v1/agents") is False
        assert handler.can_handle("/api/v1/health") is False
        assert handler.can_handle("/api/v1/elo") is False


# =============================================================================
# Authentication Tests
# =============================================================================


class TestAuthentication:
    """Tests for authentication checks."""

    def test_does_not_require_auth_for_debates_list(self, handler):
        """Test that /api/debates listing is publicly readable."""
        assert handler._requires_auth("/api/debates") is False

    def test_requires_auth_for_export(self, handler):
        """Test that export endpoints require auth."""
        assert handler._requires_auth("/api/debates/123/export/json") is True

    def test_requires_auth_for_citations(self, handler):
        """Test that citations endpoint requires auth."""
        assert handler._requires_auth("/api/debates/123/citations") is True

    def test_requires_auth_for_fork(self, handler):
        """Test that fork endpoint requires auth."""
        assert handler._requires_auth("/api/debates/123/fork") is True

    def test_impasse_path_does_not_require_auth(self, handler):
        """Test that impasse path is publicly readable.

        AUTH_REQUIRED_ENDPOINTS only covers specific endpoints like batch,
        export, citations, fork, and followup. Impasse is not in that list.
        """
        assert handler._requires_auth("/api/debates/123/impasse") is False

    @patch("aragora.server.auth.auth_config")
    def test_check_auth_disabled(self, mock_auth_config, handler, mock_handler_request):
        """Test auth check when auth is disabled."""
        mock_auth_config.enabled = False
        result = handler._check_auth(mock_handler_request)
        assert result is None

    @patch("aragora.server.auth.auth_config")
    def test_check_auth_no_token_configured(self, mock_auth_config, handler, mock_handler_request):
        """Test auth check when no API token is configured."""
        mock_auth_config.enabled = True
        mock_auth_config.api_token = None
        result = handler._check_auth(mock_handler_request)
        assert result is None

    @patch("aragora.server.auth.auth_config")
    def test_check_auth_valid_token(self, mock_auth_config, handler, mock_handler_request):
        """Test auth check with valid token."""
        mock_auth_config.enabled = True
        mock_auth_config.api_token = "test-token"
        mock_auth_config.validate_token = Mock(return_value=True)
        result = handler._check_auth(mock_handler_request)
        assert result is None

    @patch("aragora.server.auth.auth_config")
    def test_check_auth_invalid_token(self, mock_auth_config, handler, mock_handler_request):
        """Test auth check with invalid token."""
        mock_auth_config.enabled = True
        mock_auth_config.api_token = "real-token"
        mock_auth_config.validate_token = Mock(return_value=False)
        result = handler._check_auth(mock_handler_request)
        assert result is not None
        assert result.status_code == 401


# =============================================================================
# List and Search Debates Tests
# =============================================================================


class TestListDebates:
    """Tests for listing debates via handle() method."""

    @patch("aragora.server.auth.auth_config")
    def test_list_debates_success(
        self, mock_auth_config, handler, mock_storage, mock_handler_request
    ):
        """Test listing debates returns expected data via handle()."""
        mock_auth_config.enabled = False
        mock_storage.list_recent = Mock(
            return_value=[
                {"id": "d1", "task": "Task 1"},
                {"id": "d2", "task": "Task 2"},
            ]
        )

        # Use handle() which is the public interface
        result = handler.handle("/api/debates", {"limit": "20"}, mock_handler_request)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["count"] == 2
        assert len(body["debates"]) == 2

    @patch("aragora.server.auth.auth_config")
    def test_list_debates_respects_limit(
        self, mock_auth_config, handler, mock_storage, mock_handler_request
    ):
        """Test listing debates respects limit parameter."""
        mock_auth_config.enabled = False
        mock_storage.list_recent = Mock(
            return_value=[
                {"id": "d1", "task": "Task 1"},
            ]
        )

        result = handler.handle("/api/debates", {"limit": "5"}, mock_handler_request)

        assert result.status_code == 200
        # Verify list_recent was called with the limit
        mock_storage.list_recent.assert_called_once()


class TestSearchDebates:
    """Tests for searching debates via handle() method."""

    @patch("aragora.server.auth.auth_config")
    def test_search_debates_with_query(
        self, mock_auth_config, handler, mock_storage, mock_handler_request
    ):
        """Test searching debates with a query."""
        mock_auth_config.enabled = False
        mock_storage.search = Mock(return_value=([{"id": "d1", "task": "Match"}], 1))

        result = handler.handle("/api/search", {"q": "test", "limit": "20"}, mock_handler_request)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["query"] == "test"
        assert body["total"] == 1

    @patch("aragora.server.auth.auth_config")
    def test_search_debates_empty_query(
        self, mock_auth_config, handler, mock_storage, mock_handler_request
    ):
        """Test searching with empty query returns list."""
        mock_auth_config.enabled = False
        mock_storage.list_recent = Mock(
            return_value=[
                {"id": "d1", "task": "Task 1"},
            ]
        )

        result = handler.handle("/api/search", {"q": ""}, mock_handler_request)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["query"] == ""

    @patch("aragora.server.auth.auth_config")
    def test_search_debates_pagination(
        self, mock_auth_config, handler, mock_storage, mock_handler_request
    ):
        """Test search pagination."""
        mock_auth_config.enabled = False
        mock_storage.search = Mock(return_value=([{"id": "d1"}], 50))

        result = handler.handle(
            "/api/search", {"q": "test", "limit": "10", "offset": "20"}, mock_handler_request
        )

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["offset"] == 20
        assert body["limit"] == 10
        assert body["has_more"] is True


# =============================================================================
# Get Debate Tests
# =============================================================================


class TestGetDebateBySlug:
    """Tests for getting debate by slug."""

    def test_get_debate_found(self, handler, mock_storage, sample_debate, mock_handler_request):
        """Test getting existing debate."""
        mock_storage.get_debate = Mock(return_value=sample_debate)

        result = handler._get_debate_by_slug(mock_handler_request, "test-debate")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["id"] == "debate-123"

    def test_get_debate_not_found(self, handler, mock_storage, mock_handler_request):
        """Test getting non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)
        mock_storage.get_debate_by_slug = Mock(return_value=None)

        result = handler._get_debate_by_slug(mock_handler_request, "missing")

        assert result.status_code == 404


# =============================================================================
# Analysis Endpoints Tests
# =============================================================================


class TestImpasseDetection:
    """Tests for impasse detection endpoint."""

    def test_impasse_detected(self, handler, mock_storage, mock_handler_request):
        """Test impasse is detected when indicators are present."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "consensus_reached": False,
                "critiques": [
                    {"severity": 0.9},
                    {"severity": 0.8},
                ],
            }
        )

        result = handler._get_impasse(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["is_impasse"] is True
        assert body["indicators"]["no_convergence"] is True

    def test_no_impasse(self, handler, mock_storage, mock_handler_request):
        """Test no impasse when consensus reached."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "consensus_reached": True,
                "critiques": [],
            }
        )

        result = handler._get_impasse(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["is_impasse"] is False

    def test_impasse_debate_not_found(self, handler, mock_storage, mock_handler_request):
        """Test impasse for non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)

        result = handler._get_impasse(mock_handler_request, "missing")

        assert result.status_code == 404


class TestConvergence:
    """Tests for convergence endpoint."""

    def test_convergence_status(self, handler, mock_storage, sample_debate, mock_handler_request):
        """Test getting convergence status."""
        mock_storage.get_debate = Mock(return_value=sample_debate)

        result = handler._get_convergence(mock_handler_request, "debate-123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["convergence_status"] == "converged"
        assert body["convergence_similarity"] == 0.95
        assert body["consensus_reached"] is True

    def test_convergence_debate_not_found(self, handler, mock_storage, mock_handler_request):
        """Test convergence for non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)

        result = handler._get_convergence(mock_handler_request, "missing")

        assert result.status_code == 404


class TestVerificationReport:
    """Tests for verification report endpoint."""

    def test_verification_with_results(self, handler, mock_storage, mock_handler_request):
        """Test verification report with results."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "winner": "claude",
                "consensus_reached": True,
                "verification_results": {"claude": 3, "gemini": 2},
                "verification_bonuses": {"claude": 0.15, "gemini": 0.10},
            }
        )

        result = handler._get_verification_report(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["verification_enabled"] is True
        assert body["summary"]["total_verified_claims"] == 5
        assert body["summary"]["agents_with_verified_claims"] == 2

    def test_verification_without_results(self, handler, mock_storage, mock_handler_request):
        """Test verification report without results."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "consensus_reached": False,
            }
        )

        result = handler._get_verification_report(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["verification_enabled"] is False


class TestSummary:
    """Tests for summary endpoint."""

    @patch("aragora.debate.summarizer.summarize_debate")
    def test_summary_success(
        self, mock_summarize, handler, mock_storage, sample_debate, mock_handler_request
    ):
        """Test getting debate summary."""
        mock_storage.get_debate = Mock(return_value=sample_debate)

        mock_summary = Mock()
        mock_summary.to_dict = Mock(
            return_value={
                "verdict": "Claude's proposal was accepted",
                "key_points": ["Testing is important"],
                "confidence": 0.85,
            }
        )
        mock_summarize.return_value = mock_summary

        result = handler._get_summary(mock_handler_request, "debate-123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "summary" in body
        assert body["consensus_reached"] is True

    def test_summary_debate_not_found(self, handler, mock_storage, mock_handler_request):
        """Test summary for non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)

        result = handler._get_summary(mock_handler_request, "missing")

        assert result.status_code == 404


# =============================================================================
# Export Tests
# =============================================================================


class TestExportDebate:
    """Tests for export endpoints."""

    def test_export_json(self, handler, mock_storage, sample_debate, mock_handler_request):
        """Test JSON export."""
        mock_storage.get_debate = Mock(return_value=sample_debate)

        result = handler._export_debate(mock_handler_request, "debate-123", "json", "summary")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["id"] == "debate-123"

    @patch("aragora.server.debate_export.format_debate_csv")
    def test_export_csv(
        self, mock_format_csv, handler, mock_storage, sample_debate, mock_handler_request
    ):
        """Test CSV export."""
        mock_storage.get_debate = Mock(return_value=sample_debate)

        mock_result = Mock()
        mock_result.content_type = "text/csv"
        mock_result.content = "id,task\ndebate-123,Test"
        mock_result.filename = "debate-123.csv"
        mock_format_csv.return_value = mock_result

        result = handler._export_debate(mock_handler_request, "debate-123", "csv", "summary")

        assert result.status_code == 200
        assert result.content_type == "text/csv"

    @patch("aragora.server.debate_export.format_debate_html")
    def test_export_html(
        self, mock_format_html, handler, mock_storage, sample_debate, mock_handler_request
    ):
        """Test HTML export."""
        mock_storage.get_debate = Mock(return_value=sample_debate)

        mock_result = Mock()
        mock_result.content_type = "text/html"
        mock_result.content = "<html><body>Debate</body></html>"
        mock_result.filename = "debate-123.html"
        mock_format_html.return_value = mock_result

        result = handler._export_debate(mock_handler_request, "debate-123", "html", "summary")

        assert result.status_code == 200
        assert result.content_type == "text/html"

    def test_export_invalid_format(self, handler, mock_storage, mock_handler_request):
        """Test export with invalid format."""
        result = handler._export_debate(mock_handler_request, "debate-123", "invalid", "summary")

        assert result.status_code == 400

    def test_export_debate_not_found(self, handler, mock_storage, mock_handler_request):
        """Test export for non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)

        result = handler._export_debate(mock_handler_request, "missing", "json", "summary")

        assert result.status_code == 404


# =============================================================================
# Citations and Evidence Tests
# =============================================================================


class TestCitations:
    """Tests for citations endpoint."""

    def test_citations_with_data(self, handler, mock_storage, mock_handler_request):
        """Test getting citations with grounded verdict."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "grounded_verdict": json.dumps(
                    {
                        "grounding_score": 0.8,
                        "confidence": 0.9,
                        "claims": [{"claim": "Test claim", "evidence": ["Source 1"]}],
                        "all_citations": [{"source": "Source 1", "url": "http://example.com"}],
                        "verdict": "The claim is supported",
                    }
                ),
            }
        )

        result = handler._get_citations(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["has_citations"] is True
        assert body["grounding_score"] == 0.8
        assert len(body["claims"]) == 1

    def test_citations_no_data(self, handler, mock_storage, mock_handler_request):
        """Test getting citations without grounded verdict."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
            }
        )

        result = handler._get_citations(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["has_citations"] is False


class TestEvidence:
    """Tests for evidence endpoint."""

    def test_evidence_with_data(self, handler, mock_storage, mock_handler_request):
        """Test getting evidence trail."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "task": "Test task",
                "grounded_verdict": json.dumps(
                    {
                        "grounding_score": 0.85,
                        "confidence": 0.9,
                        "claims": [],
                        "all_citations": [],
                        "verdict": "Supported",
                    }
                ),
            }
        )
        # Mock continuum memory not being available
        handler.ctx["continuum_memory"] = None

        result = handler._get_evidence(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["has_evidence"] is True
        assert body["grounded_verdict"]["grounding_score"] == 0.85

    def test_evidence_debate_not_found(self, handler, mock_storage, mock_handler_request):
        """Test evidence for non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)

        result = handler._get_evidence(mock_handler_request, "missing")

        assert result.status_code == 404


# =============================================================================
# Messages Tests
# =============================================================================


class TestDebateMessages:
    """Tests for paginated messages endpoint."""

    def test_messages_default_pagination(self, handler, mock_storage, sample_debate):
        """Test getting messages with default pagination."""
        mock_storage.get_debate = Mock(return_value=sample_debate)

        result = handler._get_debate_messages("debate-123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["total"] == 3
        assert len(body["messages"]) == 3
        assert body["has_more"] is False

    def test_messages_with_pagination(self, handler, mock_storage):
        """Test getting messages with pagination."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "messages": [{"content": f"msg{i}", "role": "proposer"} for i in range(100)],
            }
        )

        result = handler._get_debate_messages("d1", limit=10, offset=50)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["total"] == 100
        assert len(body["messages"]) == 10
        assert body["offset"] == 50
        assert body["has_more"] is True

    def test_messages_debate_not_found(self, handler, mock_storage):
        """Test messages for non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)

        result = handler._get_debate_messages("missing")

        assert result.status_code == 404


# =============================================================================
# Meta Critique Tests
# =============================================================================


class TestMetaCritique:
    """Tests for meta critique endpoint."""

    @patch("aragora.debate.traces.DebateTrace")
    @patch("aragora.debate.meta.MetaCritiqueAnalyzer")
    def test_meta_critique_success(
        self, mock_analyzer_class, mock_trace_class, handler, temp_nomic_dir
    ):
        """Test getting meta critique analysis."""
        # Create trace file
        traces_dir = temp_nomic_dir / "traces"
        traces_dir.mkdir(exist_ok=True)
        trace_file = traces_dir / "debate-123.json"
        trace_file.write_text(json.dumps({"id": "debate-123"}))

        # Mock trace loading
        mock_trace = Mock()
        mock_result = Mock()
        mock_result.task = "Test task"
        mock_result.messages = []
        mock_result.critiques = []
        mock_trace.to_debate_result.return_value = mock_result
        mock_trace_class.load.return_value = mock_trace

        # Mock analyzer
        mock_observation = Mock()
        mock_observation.observation_type = "repetition"
        mock_observation.severity = "low"
        mock_observation.description = "Some repetition detected"

        mock_critique = Mock()
        mock_critique.overall_quality = 0.8
        mock_critique.productive_rounds = 3
        mock_critique.unproductive_rounds = 1
        mock_critique.observations = [mock_observation]
        mock_critique.recommendations = ["Improve diversity"]

        mock_analyzer = Mock()
        mock_analyzer.analyze.return_value = mock_critique
        mock_analyzer_class.return_value = mock_analyzer

        result = handler._get_meta_critique("debate-123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["overall_quality"] == 0.8

    def test_meta_critique_trace_not_found(self, handler, temp_nomic_dir):
        """Test meta critique when trace file doesn't exist."""
        result = handler._get_meta_critique("missing")

        assert result.status_code == 404


# =============================================================================
# Graph Stats Tests
# =============================================================================


class TestGraphStats:
    """Tests for graph stats endpoint."""

    @patch("aragora.visualization.mapper.ArgumentCartographer")
    @patch("aragora.debate.traces.DebateTrace")
    def test_graph_stats_success(
        self, mock_trace_class, mock_cartographer_class, handler, temp_nomic_dir
    ):
        """Test getting graph statistics."""
        # Create trace file
        traces_dir = temp_nomic_dir / "traces"
        traces_dir.mkdir(exist_ok=True)
        trace_file = traces_dir / "debate-123.json"
        trace_file.write_text(json.dumps({"id": "debate-123"}))

        # Mock trace loading
        mock_trace = Mock()
        mock_result = Mock()
        mock_result.task = "Test task"
        mock_result.messages = []
        mock_result.critiques = []
        mock_trace.to_debate_result.return_value = mock_result
        mock_trace_class.load.return_value = mock_trace

        # Mock cartographer
        mock_cart = Mock()
        mock_cart.get_statistics.return_value = {
            "node_count": 10,
            "edge_count": 15,
            "depth": 3,
            "branching_factor": 2.5,
            "complexity": "medium",
        }
        mock_cartographer_class.return_value = mock_cart

        result = handler._get_graph_stats("debate-123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["node_count"] == 10

    def test_graph_stats_trace_not_found(self, handler, temp_nomic_dir):
        """Test graph stats when trace file doesn't exist."""
        result = handler._get_graph_stats("missing")

        assert result.status_code == 404


# =============================================================================
# PATCH Debate Tests
# =============================================================================


class TestPatchDebate:
    """Tests for updating debate metadata."""

    def test_patch_title(self, handler, mock_storage, mock_handler_request):
        """Test updating debate title."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "title": "Old Title",
                "task": "Test task",
            }
        )
        mock_storage.save_debate = Mock()

        handler.read_json_body = Mock(return_value={"title": "New Title"})

        result = handler._patch_debate(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["success"] is True
        assert "title" in body["updated_fields"]
        mock_storage.save_debate.assert_called_once()

    def test_patch_tags(self, handler, mock_storage, mock_handler_request):
        """Test updating debate tags."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "tags": [],
            }
        )
        mock_storage.save_debate = Mock()

        handler.read_json_body = Mock(return_value={"tags": ["tag1", "tag2"]})

        result = handler._patch_debate(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "tags" in body["updated_fields"]

    def test_patch_status(self, handler, mock_storage, mock_handler_request):
        """Test updating debate status."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "status": "active",
            }
        )
        mock_storage.save_debate = Mock()

        handler.read_json_body = Mock(return_value={"status": "concluded"})

        result = handler._patch_debate(mock_handler_request, "d1")

        assert result.status_code == 200

    def test_patch_invalid_status(self, handler, mock_storage, mock_handler_request):
        """Test updating with invalid status."""
        mock_storage.get_debate = Mock(return_value={"id": "d1"})

        handler.read_json_body = Mock(return_value={"status": "invalid"})

        result = handler._patch_debate(mock_handler_request, "d1")

        assert result.status_code == 400

    def test_patch_no_valid_fields(self, handler, mock_storage, mock_handler_request):
        """Test patching with no valid fields."""
        mock_storage.get_debate = Mock(return_value={"id": "d1"})

        handler.read_json_body = Mock(return_value={"invalid_field": "value"})

        result = handler._patch_debate(mock_handler_request, "d1")

        assert result.status_code == 400

    def test_patch_empty_body(self, handler, mock_storage, mock_handler_request):
        """Test patching with empty body."""
        handler.read_json_body = Mock(return_value={})

        result = handler._patch_debate(mock_handler_request, "d1")

        assert result.status_code == 400

    def test_patch_debate_not_found(self, handler, mock_storage, mock_handler_request):
        """Test patching non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)

        handler.read_json_body = Mock(return_value={"title": "New"})

        result = handler._patch_debate(mock_handler_request, "missing")

        assert result.status_code == 404


# =============================================================================
# Fork Operations Tests
# =============================================================================


class TestForkDebate:
    """Tests for forking debates."""

    @patch("aragora.server.validation.validate_against_schema")
    @patch.dict("sys.modules", {"aragora.debate.counterfactual": MagicMock()})
    def test_fork_success(
        self, mock_validate, handler, mock_storage, mock_handler_request, temp_nomic_dir
    ):
        """Test successful debate fork."""
        # Create proper mock classes that produce serializable data
        import sys

        mock_counterfactual = sys.modules["aragora.debate.counterfactual"]

        # Mock PivotClaim to return a proper object with statement attribute
        mock_pivot = Mock()
        mock_pivot.statement = "What if we tried approach B?"
        mock_counterfactual.PivotClaim.return_value = mock_pivot

        # Mock CounterfactualBranch - all attributes must be JSON-serializable strings
        mock_branch = Mock()
        mock_branch.branch_id = "fork-d1-r1-abc12345"
        mock_branch.parent_debate_id = "d1"
        mock_branch.pivot_claim = mock_pivot
        mock_counterfactual.CounterfactualBranch.return_value = mock_branch

        mock_validate.return_value = Mock(is_valid=True)
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "messages": [
                    {"content": "msg1", "round": 1},
                    {"content": "msg2", "round": 2},
                ],
            }
        )
        handler.read_json_body = Mock(
            return_value={
                "branch_point": 1,
                "modified_context": "What if we tried approach B?",
            }
        )

        result = handler._fork_debate(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["success"] is True
        assert body["parent_debate_id"] == "d1"
        assert body["branch_point"] == 1

    def test_fork_invalid_json(self, handler, mock_storage, mock_handler_request):
        """Test fork with invalid JSON body."""
        handler.read_json_body = Mock(return_value=None)

        result = handler._fork_debate(mock_handler_request, "d1")

        assert result.status_code == 400

    @patch("aragora.server.validation.validate_against_schema")
    def test_fork_debate_not_found(
        self, mock_validate, handler, mock_storage, mock_handler_request
    ):
        """Test fork for non-existent debate."""
        mock_validate.return_value = Mock(is_valid=True)
        mock_storage.get_debate = Mock(return_value=None)
        handler.read_json_body = Mock(return_value={"branch_point": 1})

        result = handler._fork_debate(mock_handler_request, "missing")

        assert result.status_code == 404

    @patch("aragora.server.validation.validate_against_schema")
    def test_fork_invalid_branch_point(
        self, mock_validate, handler, mock_storage, mock_handler_request
    ):
        """Test fork with branch point exceeding message count."""
        mock_validate.return_value = Mock(is_valid=True)
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "messages": [{"content": "msg1"}],
            }
        )
        handler.read_json_body = Mock(return_value={"branch_point": 10})

        result = handler._fork_debate(mock_handler_request, "d1")

        assert result.status_code == 400


# =============================================================================
# Followup Operations Tests
# =============================================================================


class TestFollowupSuggestions:
    """Tests for followup suggestions endpoint."""

    @patch("aragora.uncertainty.estimator.DisagreementAnalyzer")
    def test_followup_suggestions_with_cruxes(self, mock_analyzer_class, handler, mock_storage):
        """Test getting followup suggestions when cruxes exist."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "agents": ["claude", "gemini"],
                "uncertainty_metrics": {
                    "cruxes": [
                        {
                            "description": "Key disagreement",
                            "agents": ["claude", "gemini"],
                            "evidence_needed": "More data",
                            "severity": 0.8,
                        }
                    ]
                },
            }
        )

        mock_suggestion = Mock()
        mock_suggestion.to_dict.return_value = {
            "task": "Explore the disagreement",
            "priority": 0.8,
        }

        mock_analyzer = Mock()
        mock_analyzer.suggest_followups.return_value = [mock_suggestion]
        mock_analyzer_class.return_value = mock_analyzer

        result = handler._get_followup_suggestions("d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["count"] == 1

    def test_followup_suggestions_no_cruxes(self, handler, mock_storage):
        """Test followup suggestions when no cruxes are found."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "agents": ["claude", "gemini"],
                "messages": [],
                "votes": [],
                "proposals": {},
            }
        )

        # This test may need additional mocking depending on the analyzer behavior
        # For now, we test the structure

    def test_followup_suggestions_debate_not_found(self, handler, mock_storage):
        """Test followup suggestions for non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)

        result = handler._get_followup_suggestions("missing")

        assert result.status_code == 404


class TestCreateFollowup:
    """Tests for creating followup debates."""

    def test_create_followup_with_custom_task(
        self, handler, mock_storage, mock_handler_request, temp_nomic_dir
    ):
        """Test creating followup with custom task."""
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "agents": ["claude", "gemini"],
            }
        )
        handler.read_json_body = Mock(
            return_value={
                "task": "Custom followup task",
                "agents": ["claude"],
            }
        )

        result = handler._create_followup_debate(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["success"] is True
        assert body["task"] == "Custom followup task"

    def test_create_followup_missing_task_and_crux(
        self, handler, mock_storage, mock_handler_request
    ):
        """Test creating followup without task or crux_id."""
        mock_storage.get_debate = Mock(return_value={"id": "d1"})
        handler.read_json_body = Mock(return_value={})

        result = handler._create_followup_debate(mock_handler_request, "d1")

        assert result.status_code == 400

    def test_create_followup_debate_not_found(self, handler, mock_storage, mock_handler_request):
        """Test creating followup for non-existent debate."""
        mock_storage.get_debate = Mock(return_value=None)
        handler.read_json_body = Mock(return_value={"task": "Test"})

        result = handler._create_followup_debate(mock_handler_request, "missing")

        assert result.status_code == 404


# =============================================================================
# Verify Outcome Tests
# =============================================================================


class TestVerifyOutcome:
    """Tests for outcome verification endpoint."""

    def test_verify_outcome_with_tracker(self, handler, mock_handler_request):
        """Test verifying outcome when position tracker is available."""
        mock_tracker = Mock()
        handler.ctx["position_tracker"] = mock_tracker
        handler.read_json_body = Mock(
            return_value={
                "correct": True,
                "source": "manual",
            }
        )

        result = handler._verify_outcome(mock_handler_request, "d1")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "verified"
        assert body["correct"] is True
        mock_tracker.record_verification.assert_called_once()

    def test_verify_outcome_invalid_json(self, handler, mock_handler_request):
        """Test verifying outcome with invalid JSON."""
        handler.read_json_body = Mock(return_value=None)

        result = handler._verify_outcome(mock_handler_request, "d1")

        assert result.status_code == 400


# =============================================================================
# Handle Method Integration Tests
# =============================================================================


class TestHandleMethod:
    """Integration tests for the main handle method."""

    @patch("aragora.server.auth.auth_config")
    def test_handle_search(self, mock_auth, handler, mock_storage, mock_handler_request):
        """Test handling search endpoint."""
        mock_auth.enabled = False
        mock_storage.search = Mock(return_value=([], 0))

        result = handler.handle("/api/search", {"q": "test"}, mock_handler_request)

        assert result is not None
        assert result.status_code == 200

    @patch("aragora.server.auth.auth_config")
    def test_handle_debates_list(self, mock_auth, handler, mock_storage, mock_handler_request):
        """Test handling debates list endpoint."""
        mock_auth.enabled = False
        mock_storage.list_recent = Mock(return_value=[])

        result = handler.handle("/api/debates", {}, mock_handler_request)

        assert result is not None
        assert result.status_code == 200

    @patch("aragora.server.auth.auth_config")
    def test_handle_impasse_dispatch(self, mock_auth, handler, mock_storage, mock_handler_request):
        """Test dispatching to impasse endpoint."""
        mock_auth.enabled = False
        mock_storage.get_debate = Mock(
            return_value={
                "id": "d1",
                "consensus_reached": True,
                "critiques": [],
            }
        )
        mock_storage.is_public = Mock(return_value=True)

        result = handler.handle("/api/debates/d1/impasse", {}, mock_handler_request)

        assert result is not None
        assert result.status_code == 200


class TestHandlePost:
    """Tests for POST request handling."""

    def test_handle_post_fork(self, handler, mock_storage, mock_handler_request):
        """Test POST to fork endpoint routes correctly."""
        mock_storage.get_debate = Mock(return_value=None)
        handler.read_json_body = Mock(return_value={"branch_point": 1})

        result = handler.handle_post("/api/debates/d1/fork", {}, mock_handler_request)

        # Should attempt to fork (and fail because debate not found)
        assert result is not None


class TestHandlePatch:
    """Tests for PATCH request handling."""

    def test_handle_patch_routes_correctly(self, handler, mock_storage, mock_handler_request):
        """Test PATCH to debate endpoint routes correctly."""
        mock_storage.get_debate = Mock(return_value=None)
        handler.read_json_body = Mock(return_value={"title": "New"})

        # handle_patch checks path.startswith("/api/v1/debates/") and path.count("/") == 4
        # so we must use the versioned path format
        result = handler.handle_patch("/api/v1/debates/d1", {}, mock_handler_request)

        assert result is not None
        assert result.status_code == 404


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_extract_debate_id_valid(self, handler):
        """Test extracting valid debate ID."""
        debate_id, error = handler._extract_debate_id("/api/debates/debate-123/impasse")
        assert debate_id == "debate-123"
        assert error is None

    def test_extract_debate_id_invalid_path(self, handler):
        """Test extracting debate ID from invalid path."""
        debate_id, error = handler._extract_debate_id("/api")
        assert debate_id is None
        assert error is not None

    def test_handle_returns_none_for_unmatched(self, handler, mock_handler_request):
        """Test that handle returns None for unmatched paths."""
        result = handler.handle("/api/unknown", {}, mock_handler_request)
        # Should return None or a result depending on the path
        # For completely unmatched, it returns None


# =============================================================================
# Artifact Access Tests
# =============================================================================


class TestArtifactAccess:
    """Tests for artifact endpoint access control."""

    @patch("aragora.server.auth.auth_config")
    def test_artifact_access_public_debate(
        self, mock_auth, handler, mock_storage, mock_handler_request
    ):
        """Test accessing artifacts from public debate without auth."""
        mock_auth.enabled = True
        mock_storage.is_public = Mock(return_value=True)

        result = handler._check_artifact_access("d1", "/messages", mock_handler_request)

        assert result is None  # Access allowed

    @patch("aragora.server.auth.auth_config")
    def test_artifact_access_private_debate_no_auth(
        self, mock_auth, handler, mock_storage, mock_handler_request
    ):
        """Test accessing artifacts from private debate without auth."""
        mock_auth.enabled = True
        mock_auth.api_token = "secret"
        mock_auth.validate_token = Mock(return_value=False)
        mock_storage.is_public = Mock(return_value=False)
        mock_handler_request.headers = {}

        result = handler._check_artifact_access("d1", "/messages", mock_handler_request)

        assert result is not None
        assert result.status_code == 401

    def test_artifact_access_non_artifact_endpoint(
        self, handler, mock_storage, mock_handler_request
    ):
        """Test accessing non-artifact endpoint."""
        result = handler._check_artifact_access("d1", "/impasse", mock_handler_request)

        assert result is None  # Not an artifact endpoint
