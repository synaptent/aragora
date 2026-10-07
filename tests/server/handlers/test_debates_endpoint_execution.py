"""
Tests for DebatesHandler endpoint execution.

Tests actual handler method execution (not just routing):
- List debates
- Get debate by slug/ID
- Get impasse status
- Get convergence status
- Get citations
- Get verification report
- Get summary
- Get messages (paginated)
- Export debates
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Response Helpers
# ===========================================================================


def get_response_data(body: dict) -> dict:
    """Extract data from response body."""
    if "data" in body:
        return body["data"]
    return body


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def mock_storage():
    """Create mock storage with common debate data."""
    storage = MagicMock()

    # Sample debate data
    sample_debate = {
        "id": "debate_123",
        "debate_id": "debate_123",
        "task": "Should we use microservices?",
        "status": "completed",
        "consensus_reached": True,
        "convergence_status": "converged",
        "convergence_similarity": 0.85,
        "rounds_used": 3,
        "agents": ["claude", "gpt4"],
        "winner": "claude",
        "confidence": 0.9,
        "critiques": [
            {"agent": "gpt4", "severity": 0.5, "text": "Consider scalability"},
            {"agent": "claude", "severity": 0.3, "text": "Valid point"},
        ],
        "messages": [
            {"agent": "claude", "round": 1, "content": "I propose..."},
            {"agent": "gpt4", "round": 1, "content": "I counter..."},
            {"agent": "claude", "round": 2, "content": "Revised proposal..."},
        ],
        "verification_results": {"claude": 3, "gpt4": 2},
        "verification_bonuses": {"claude": 0.15, "gpt4": 0.1},
        "grounded_verdict": json.dumps(
            {
                "verdict": "Use microservices for scalable systems",
                "grounding_score": 0.8,
                "confidence": 0.85,
                "claims": [
                    {"text": "Microservices improve scalability", "evidence": ["Source 1"]},
                ],
                "all_citations": [{"source": "Source 1", "text": "Citation text"}],
            }
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    storage.get_debate = MagicMock(return_value=sample_debate)
    storage.list_recent = MagicMock(return_value=[sample_debate])
    storage.is_public = MagicMock(return_value=True)
    # Every debate id resolves to a private debate of the test user's org.
    storage.get_access_info = MagicMock(side_effect=lambda ref: (ref, "test-org-001", False))

    return storage


@pytest.fixture
def debates_handler(mock_storage):
    """Create DebatesHandler with mock storage."""
    from aragora.server.handlers.debates.handler import DebatesHandler

    handler = DebatesHandler(server_context={"storage": mock_storage})
    return handler


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler."""
    http = MagicMock()
    http.headers = {}
    http.command = "GET"
    return http


# ===========================================================================
# Test List Debates
# ===========================================================================


class TestListDebates:
    """Tests for _list_debates endpoint."""

    def test_list_debates_success(self, debates_handler, mock_storage):
        """Test listing debates returns list."""
        result = debates_handler._list_debates(limit=20)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "debates" in body
        assert "count" in body
        assert len(body["debates"]) == 1
        mock_storage.list_recent.assert_called_once()

    def test_list_debates_with_org_id(self, debates_handler, mock_storage):
        """Test listing debates filtered by org_id."""
        result = debates_handler._list_debates(limit=20, org_id="org_123")

        assert result.status_code == 200
        mock_storage.list_recent.assert_called_with(limit=20, org_id="org_123", offset=0)

    def test_list_debates_empty(self, debates_handler, mock_storage):
        """Test listing debates when none exist."""
        mock_storage.list_recent.return_value = []

        result = debates_handler._list_debates(limit=20)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["debates"] == []
        assert body["count"] == 0

    def test_list_debates_respects_limit(self, debates_handler, mock_storage):
        """Test that limit parameter is passed to storage."""
        debates_handler._list_debates(limit=5)

        mock_storage.list_recent.assert_called_with(limit=5, org_id=None, offset=0)


# ===========================================================================
# Test Get Debate by Slug
# ===========================================================================


class TestGetDebateBySlug:
    """Tests for _get_debate_by_slug endpoint."""

    def test_get_debate_success(self, debates_handler, mock_http_handler, mock_storage):
        """Test getting debate by slug returns debate data."""
        result = debates_handler._get_debate_by_slug(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["id"] == "debate_123"
        assert body["task"] == "Should we use microservices?"

    def test_get_debate_not_found(self, debates_handler, mock_http_handler, mock_storage):
        """Test getting non-existent debate returns 404."""
        mock_storage.get_debate.return_value = None

        result = debates_handler._get_debate_by_slug(mock_http_handler, "nonexistent")

        assert result.status_code == 404
        body = json.loads(result.body)
        assert "not found" in body.get("error", "").lower()

    def test_get_active_debate(self, debates_handler, mock_http_handler, mock_storage):
        """Test getting in-progress debate from active debates."""
        mock_storage.get_debate.return_value = None

        # Mock active debates via StateManager
        # The _active_debates proxy delegates to get_state_manager().get_debate()
        mock_state = MagicMock()
        mock_state.to_dict.return_value = {
            "task": "Active debate question",
            "status": "running",
            "agents": "claude,gpt4",
            "rounds": 3,
            "mode": "epistemic_hygiene",
            "settlement": {
                "status": "pending_human_adjudication",
                "resolver_type": "human",
            },
        }
        mock_state_manager = MagicMock()
        mock_state_manager.get_debate.return_value = mock_state

        with patch(
            "aragora.server.debate_utils.get_state_manager",
            return_value=mock_state_manager,
        ):
            result = debates_handler._get_debate_by_slug(mock_http_handler, "active_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["id"] == "active_123"
        assert body["in_progress"] is True
        assert body["mode"] == "epistemic_hygiene"
        assert body["settlement"]["status"] == "pending_human_adjudication"


# ===========================================================================
# Test Get Impasse
# ===========================================================================


class TestGetImpasse:
    """Tests for _get_impasse endpoint."""

    def test_get_impasse_no_impasse(self, debates_handler, mock_http_handler, mock_storage):
        """Test impasse detection when no impasse."""
        result = debates_handler._get_impasse(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["debate_id"] == "debate_123"
        assert "is_impasse" in body
        assert "indicators" in body

    def test_get_impasse_detected(self, debates_handler, mock_http_handler, mock_storage):
        """Test impasse detection when impasse detected."""
        # Create debate with high severity critiques and no convergence
        mock_storage.get_debate.return_value = {
            "id": "debate_123",
            "consensus_reached": False,
            "critiques": [
                {"severity": 0.9},
                {"severity": 0.85},
            ],
        }

        result = debates_handler._get_impasse(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        # With no_convergence=True and high_severity=True, is_impasse should be True
        assert body["is_impasse"] is True
        assert body["indicators"]["no_convergence"] is True
        assert body["indicators"]["high_severity_critiques"] is True

    def test_get_impasse_not_found(self, debates_handler, mock_http_handler, mock_storage):
        """Test impasse check for non-existent debate."""
        mock_storage.get_debate.return_value = None

        result = debates_handler._get_impasse(mock_http_handler, "nonexistent")

        assert result.status_code == 404


# ===========================================================================
# Test Get Convergence
# ===========================================================================


class TestGetConvergence:
    """Tests for _get_convergence endpoint."""

    def test_get_convergence_success(self, debates_handler, mock_http_handler, mock_storage):
        """Test getting convergence status."""
        result = debates_handler._get_convergence(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["debate_id"] == "debate_123"
        assert body["convergence_status"] == "converged"
        assert body["convergence_similarity"] == 0.85
        assert body["consensus_reached"] is True

    def test_get_convergence_not_converged(self, debates_handler, mock_http_handler, mock_storage):
        """Test convergence status when not converged."""
        mock_storage.get_debate.return_value = {
            "id": "debate_123",
            "convergence_status": "diverged",
            "convergence_similarity": 0.3,
            "consensus_reached": False,
            "rounds_used": 5,
        }

        result = debates_handler._get_convergence(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["convergence_status"] == "diverged"
        assert body["consensus_reached"] is False

    def test_get_convergence_not_found(self, debates_handler, mock_http_handler, mock_storage):
        """Test convergence check for non-existent debate."""
        mock_storage.get_debate.return_value = None

        result = debates_handler._get_convergence(mock_http_handler, "nonexistent")

        assert result.status_code == 404


# ===========================================================================
# Test Get Citations
# ===========================================================================


class TestGetCitations:
    """Tests for _get_citations endpoint."""

    def test_get_citations_success(self, debates_handler, mock_http_handler, mock_storage):
        """Test getting citations with grounded verdict."""
        result = debates_handler._get_citations(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["debate_id"] == "debate_123"
        assert body["has_citations"] is True
        assert body["grounding_score"] == 0.8
        assert len(body["claims"]) > 0

    def test_get_citations_no_evidence(self, debates_handler, mock_http_handler, mock_storage):
        """Test getting citations when no evidence available."""
        mock_storage.get_debate.return_value = {
            "id": "debate_123",
            "grounded_verdict": None,
        }

        result = debates_handler._get_citations(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["has_citations"] is False
        assert body["grounded_verdict"] is None

    def test_get_citations_not_found(self, debates_handler, mock_http_handler, mock_storage):
        """Test citations for non-existent debate."""
        mock_storage.get_debate.return_value = None

        result = debates_handler._get_citations(mock_http_handler, "nonexistent")

        assert result.status_code == 404


# ===========================================================================
# Test Get Verification Report
# ===========================================================================


class TestGetVerificationReport:
    """Tests for _get_verification_report endpoint."""

    def test_get_verification_report_success(
        self, debates_handler, mock_http_handler, mock_storage
    ):
        """Test getting verification report."""
        result = debates_handler._get_verification_report(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["debate_id"] == "debate_123"
        assert body["verification_enabled"] is True
        assert "verification_results" in body
        assert "verification_bonuses" in body
        assert "summary" in body
        assert body["summary"]["total_verified_claims"] == 5  # 3 + 2

    def test_get_verification_report_not_enabled(
        self, debates_handler, mock_http_handler, mock_storage
    ):
        """Test verification report when verification not enabled."""
        mock_storage.get_debate.return_value = {
            "id": "debate_123",
            "verification_results": {},
            "verification_bonuses": {},
        }

        result = debates_handler._get_verification_report(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["verification_enabled"] is False

    def test_get_verification_report_not_found(
        self, debates_handler, mock_http_handler, mock_storage
    ):
        """Test verification report for non-existent debate."""
        mock_storage.get_debate.return_value = None

        result = debates_handler._get_verification_report(mock_http_handler, "nonexistent")

        assert result.status_code == 404


# ===========================================================================
# Test Get Summary
# ===========================================================================


class TestGetSummary:
    """Tests for _get_summary endpoint."""

    def test_get_summary_success(self, debates_handler, mock_http_handler, mock_storage):
        """Test getting debate summary."""
        # Mock the summarizer - patch where it's imported from
        mock_summary = MagicMock()
        mock_summary.to_dict.return_value = {
            "verdict": "Use microservices for scalable systems",
            "key_points": ["Point 1", "Point 2"],
            "confidence": 0.9,
        }

        with patch(
            "aragora.debate.summarizer.summarize_debate",
            return_value=mock_summary,
        ):
            result = debates_handler._get_summary(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["debate_id"] == "debate_123"
        assert "summary" in body
        assert body["summary"]["verdict"] == "Use microservices for scalable systems"

    def test_get_summary_not_found(self, debates_handler, mock_http_handler, mock_storage):
        """Test summary for non-existent debate."""
        mock_storage.get_debate.return_value = None

        result = debates_handler._get_summary(mock_http_handler, "nonexistent")

        assert result.status_code == 404


# ===========================================================================
# Test Get Messages (Paginated)
# ===========================================================================


class TestGetMessages:
    """Tests for _get_debate_messages endpoint."""

    def test_get_messages_success(self, debates_handler, mock_storage):
        """Test getting paginated messages."""
        # The handler needs storage to be available
        with patch.object(debates_handler, "get_storage", return_value=mock_storage):
            result = debates_handler._get_debate_messages("debate_123", limit=50, offset=0)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["debate_id"] == "debate_123"
        assert "messages" in body
        assert len(body["messages"]) == 3  # From mock data

    def test_get_messages_with_pagination(self, debates_handler, mock_storage):
        """Test messages with offset pagination."""
        with patch.object(debates_handler, "get_storage", return_value=mock_storage):
            result = debates_handler._get_debate_messages("debate_123", limit=2, offset=1)

        assert result.status_code == 200
        body = json.loads(result.body)
        # Pagination should apply
        assert len(body["messages"]) <= 2

    def test_get_messages_not_found(self, debates_handler, mock_storage):
        """Test messages for non-existent debate."""
        mock_storage.get_debate.return_value = None

        with patch.object(debates_handler, "get_storage", return_value=mock_storage):
            result = debates_handler._get_debate_messages("nonexistent", limit=50, offset=0)

        assert result.status_code == 404


# ===========================================================================
# Test Handle Method Routing
# ===========================================================================


class TestHandleRouting:
    """Tests for handle() method routing to correct handlers."""

    def test_handle_list_debates(self, debates_handler, mock_http_handler, mock_storage):
        """Test handle routes to list debates."""
        # Mock auth to allow access
        with patch.object(debates_handler, "_check_auth", return_value=None):
            result = debates_handler.handle("/api/v1/debates", {}, mock_http_handler)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "debates" in body

    def test_handle_search(self, debates_handler, mock_http_handler, mock_storage):
        """Test handle routes to search."""
        with patch.object(
            debates_handler, "_search_debates", return_value=MagicMock(status_code=200)
        ) as mock_search:
            debates_handler.handle("/api/v1/search", {"q": "microservices"}, mock_http_handler)

            mock_search.assert_called_once()

    def test_handle_get_debate_by_slug(self, debates_handler, mock_http_handler, mock_storage):
        """Test handle routes to get debate by slug."""
        result = debates_handler.handle("/api/v1/debates/debate_123", {}, mock_http_handler)

        assert result.status_code == 200

    def test_handle_impasse(self, debates_handler, mock_http_handler, mock_storage):
        """Test handle routes to impasse endpoint."""
        result = debates_handler.handle("/api/v1/debates/debate_123/impasse", {}, mock_http_handler)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "is_impasse" in body

    def test_handle_convergence(self, debates_handler, mock_http_handler, mock_storage):
        """Test handle routes to convergence endpoint."""
        result = debates_handler.handle(
            "/api/v1/debates/debate_123/convergence", {}, mock_http_handler
        )

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "convergence_status" in body


# ===========================================================================
# Test Export Validation
# ===========================================================================


class TestExportValidation:
    """Tests for export format and table validation."""

    def test_export_invalid_format(self, debates_handler, mock_http_handler):
        """Test export with invalid format returns 400."""
        with patch.object(debates_handler, "_check_auth", return_value=None):
            result = debates_handler.handle(
                "/api/v1/debates/debate_123/export/invalid", {}, mock_http_handler
            )

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "format" in body.get("error", "").lower()

    def test_export_invalid_table(self, debates_handler, mock_http_handler):
        """Test export with invalid table returns 400."""
        with patch.object(debates_handler, "_check_auth", return_value=None):
            result = debates_handler.handle(
                "/api/v1/debates/debate_123/export/json",
                {"table": "invalid_table"},
                mock_http_handler,
            )

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "table" in body.get("error", "").lower()


# ===========================================================================
# Test Authentication
# ===========================================================================


class TestAuthentication:
    """Tests for authentication on protected endpoints."""

    def test_list_debates_is_public(self, debates_handler, mock_http_handler):
        """Test list debates endpoint is public (no auth required)."""
        # Even if _check_auth would fail, list endpoint skips auth
        with patch.object(
            debates_handler,
            "_check_auth",
            return_value=MagicMock(status_code=401, body=b'{"error": "Unauthorized"}'),
        ):
            result = debates_handler.handle("/api/v1/debates", {}, mock_http_handler)

        # List endpoint is intentionally public — should NOT return 401
        assert result is None or result.status_code != 401

    def test_export_requires_auth(self, debates_handler, mock_http_handler):
        """Test export endpoint requires authentication."""
        with patch.object(
            debates_handler,
            "_check_auth",
            return_value=MagicMock(status_code=401, body=b'{"error": "Unauthorized"}'),
        ):
            result = debates_handler.handle(
                "/api/v1/debates/debate_123/export/json", {}, mock_http_handler
            )

        assert result.status_code == 401

    def test_public_debate_artifacts_no_auth(
        self, debates_handler, mock_http_handler, mock_storage
    ):
        """A debate stored as public is readable outside its org."""
        mock_storage.get_access_info.side_effect = lambda ref: (ref, "org-other", True)

        result = debates_handler.handle(
            "/api/v1/debates/debate_123/messages", {}, mock_http_handler
        )

        # Should succeed without auth for public debate
        assert result.status_code == 200


# ===========================================================================
# Test Error Handling
# ===========================================================================


class TestErrorHandling:
    """Tests for error handling in debate endpoints."""

    def test_storage_error_handled(self, debates_handler, mock_http_handler, mock_storage):
        """Test storage errors are handled gracefully."""
        from aragora.exceptions import StorageError

        mock_storage.get_debate.side_effect = StorageError("Database error")

        result = debates_handler._get_citations(mock_http_handler, "debate_123")

        assert result.status_code == 500
        body = json.loads(result.body)
        assert "error" in body

    def test_invalid_debate_id_format(self, debates_handler, mock_http_handler):
        """Test invalid debate ID format returns 400."""
        # The handler validates debate IDs
        result = debates_handler.handle(
            "/api/v1/debates/../../../etc/passwd/impasse", {}, mock_http_handler
        )

        # Should either return 400 for invalid ID or 404 for not found
        assert result.status_code in (400, 404)


# ===========================================================================
# Test Response Formatting
# ===========================================================================


class TestResponseFormatting:
    """Tests for response formatting consistency."""

    def test_debate_response_normalized(self, debates_handler, mock_http_handler, mock_storage):
        """Test debate responses are normalized for SDK compatibility."""
        result = debates_handler._get_debate_by_slug(mock_http_handler, "debate_123")

        assert result.status_code == 200
        body = json.loads(result.body)

        # Should have normalized fields
        assert "id" in body or "debate_id" in body
        assert "task" in body or "question" in body

    def test_list_response_has_count(self, debates_handler, mock_storage):
        """Test list response includes count."""
        result = debates_handler._list_debates(limit=20)

        body = json.loads(result.body)
        assert "count" in body
        assert body["count"] == len(body["debates"])
