"""
Integration tests for the DebatesHandler.

Tests cover the actual handler method implementations with mock storage:
- _list_debates: Pagination, org filtering
- _get_debate_by_slug: Debate retrieval, 404 handling, in-progress debates
- _get_debate_messages: Paginated message history
- _get_convergence: Convergence status retrieval
- _get_citations: Evidence citations retrieval
- _get_impasse: Impasse detection
- _get_verification_report: Verification feedback
- _get_summary: Human-readable summary
- _get_evidence: Comprehensive evidence trail
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock


class TestListDebates:
    """Integration tests for _list_debates method."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        # Create proper mock objects with __dict__ attribute
        mock_debate_1 = MagicMock()
        mock_debate_1.__dict__ = {
            "id": "debate_1",
            "slug": "test-debate-1",
            "task": "Test task 1",
            "created_at": "2026-01-25T00:00:00Z",
            "status": "completed",
            "consensus_reached": True,
        }

        mock_debate_2 = MagicMock()
        mock_debate_2.__dict__ = {
            "id": "debate_2",
            "slug": "test-debate-2",
            "task": "Test task 2",
            "created_at": "2026-01-24T00:00:00Z",
            "status": "running",
            "consensus_reached": False,
        }

        mock_storage = MagicMock()
        mock_storage.list_recent = MagicMock(return_value=[mock_debate_1, mock_debate_2])
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_list_debates_returns_debates(self, handler_with_storage):
        """List debates returns debate list."""
        result = handler_with_storage._list_debates(limit=20)

        assert result is not None
        assert result.status_code == 200

    def test_list_debates_with_limit(self, handler_with_storage):
        """List debates respects limit parameter."""
        handler_with_storage._list_debates(limit=5)

        storage = handler_with_storage.get_storage()
        storage.list_recent.assert_called_once()
        call_kwargs = storage.list_recent.call_args[1]
        assert call_kwargs["limit"] == 5

    def test_list_debates_with_org_id(self, handler_with_storage):
        """List debates passes org_id for scoping."""
        handler_with_storage._list_debates(limit=20, org_id="org_123")

        storage = handler_with_storage.get_storage()
        call_kwargs = storage.list_recent.call_args[1]
        assert call_kwargs.get("org_id") == "org_123"

    def test_list_debates_returns_count(self, handler_with_storage):
        """List debates response includes count."""
        import json
        from aragora.server.handlers.base import clear_cache

        clear_cache()

        result = handler_with_storage._list_debates(limit=20)
        # Handle bytes, str, or dict
        if isinstance(result.body, bytes):
            body = json.loads(result.body.decode("utf-8"))
        elif isinstance(result.body, str):
            body = json.loads(result.body)
        else:
            body = result.body

        assert "count" in body
        assert body["count"] == 2


class TestGetDebateBySlug:
    """Integration tests for _get_debate_by_slug method."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        mock_storage = MagicMock()
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_get_debate_found(self, handler_with_storage):
        """Get debate returns debate when found."""
        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_123",
                "slug": "test-debate",
                "task": "Test task",
                "status": "completed",
                "messages": [],
                "consensus_reached": True,
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_debate_by_slug(mock_handler, "test-debate")

        assert result is not None
        assert result.status_code == 200

    def test_get_debate_not_found(self, handler_with_storage):
        """Get debate returns 404 when not found."""
        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(return_value=None)

        # Patch _active_debates to return empty
        with patch("aragora.server.handlers.debates.handler._active_debates", {}):
            mock_handler = MagicMock()
            result = handler_with_storage._get_debate_by_slug(mock_handler, "nonexistent")

            assert result is not None
            assert result.status_code == 404

    def test_get_debate_in_progress(self, handler_with_storage):
        """Get debate returns in-progress debate from active debates."""
        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(return_value=None)

        active_debates = {
            "in-progress-debate": {
                "task": "In progress task",
                "status": "running",
                "agents": "claude,gemini",
                "rounds": 3,
                "mode": "epistemic_hygiene",
                "settlement": {
                    "status": "pending_human_adjudication",
                    "resolver_type": "human",
                    "sla_state": "pending",
                },
            }
        }

        with patch(
            "aragora.server.handlers.debates.handler._active_debates",
            active_debates,
        ):
            mock_handler = MagicMock()
            result = handler_with_storage._get_debate_by_slug(mock_handler, "in-progress-debate")

            assert result is not None
            assert result.status_code == 200
            body = json.loads(result.body.decode("utf-8"))
            assert body["mode"] == "epistemic_hygiene"
            assert body["settlement"]["status"] == "pending_human_adjudication"
            assert body["settlement"]["sla_state"] == "pending"

    def test_get_debate_malformed_in_progress_payload_returns_not_found(self, handler_with_storage):
        """Malformed in-memory active debates should fail safe without raising."""
        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(return_value=None)

        active_debates = {"in-progress-debate": "unexpected-non-dict-state"}
        with patch(
            "aragora.server.handlers.debates.handler._active_debates",
            active_debates,
        ):
            mock_handler = MagicMock()
            result = handler_with_storage._get_debate_by_slug(mock_handler, "in-progress-debate")

            assert result is not None
            assert result.status_code == 404


class TestGetDebateMessages:
    """Integration tests for _get_debate_messages method."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.base import clear_cache

        # Clear any cached results
        clear_cache()

        mock_storage = MagicMock()
        mock_storage.get_debate = MagicMock(
            return_value={
                "id": "debate_123",
                "messages": [
                    {
                        "role": "proposer",
                        "content": "Message 1",
                        "agent": "claude",
                        "round": 1,
                    },
                    {
                        "role": "critic",
                        "content": "Message 2",
                        "agent": "gemini",
                        "round": 1,
                    },
                    {
                        "role": "proposer",
                        "content": "Message 3",
                        "agent": "claude",
                        "round": 2,
                    },
                    {
                        "role": "critic",
                        "content": "Message 4",
                        "agent": "gemini",
                        "round": 2,
                    },
                    {
                        "role": "proposer",
                        "content": "Message 5",
                        "agent": "claude",
                        "round": 3,
                    },
                ],
            }
        )
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_get_messages_returns_all(self, handler_with_storage):
        """Get messages returns all messages by default."""
        import json

        result = handler_with_storage._get_debate_messages("debate_123")

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["total"] == 5
        assert len(body["messages"]) == 5

    def test_get_messages_pagination(self, handler_with_storage):
        """Get messages respects limit and offset."""
        import json

        result = handler_with_storage._get_debate_messages("debate_123", limit=2, offset=1)

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert len(body["messages"]) == 2
        assert body["offset"] == 1
        assert body["has_more"] is True

    def test_get_messages_not_found(self, handler_with_storage):
        """Get messages returns 404 for nonexistent debate."""
        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(return_value=None)

        result = handler_with_storage._get_debate_messages("nonexistent")

        assert result.status_code == 404

    def test_get_messages_format(self, handler_with_storage):
        """Get messages formats response correctly."""
        import json

        result = handler_with_storage._get_debate_messages("debate_123", limit=1)
        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body

        message = body["messages"][0]
        assert "index" in message
        assert "role" in message
        assert "content" in message
        assert "agent" in message
        assert "round" in message


class TestGetConvergence:
    """Integration tests for _get_convergence method."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.base import clear_cache

        clear_cache()
        mock_storage = MagicMock()
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_get_convergence_success(self, handler_with_storage):
        """Get convergence returns convergence data."""
        import json
        from aragora.server.handlers.base import clear_cache

        clear_cache()  # Clear before test to avoid stale cache

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_123",
                "convergence_status": "converged",
                "convergence_similarity": 0.85,
                "consensus_reached": True,
                "rounds_used": 3,
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_convergence(mock_handler, "debate_123")

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["convergence_status"] == "converged"
        assert body["convergence_similarity"] == 0.85
        assert body["consensus_reached"] is True

    def test_get_convergence_not_found(self, handler_with_storage):
        """Get convergence returns 404 for nonexistent debate."""
        from aragora.server.handlers.base import clear_cache

        clear_cache()

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(return_value=None)

        mock_handler = MagicMock()
        result = handler_with_storage._get_convergence(mock_handler, "nonexistent")

        assert result.status_code == 404

    def test_get_convergence_defaults(self, handler_with_storage):
        """Get convergence uses defaults for missing fields."""
        import json
        from aragora.server.handlers.base import clear_cache

        clear_cache()

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_456",  # Different ID to avoid cache
                # No convergence fields set
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_convergence(mock_handler, "debate_456")

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["convergence_status"] == "unknown"
        assert body["convergence_similarity"] == 0.0
        assert body["consensus_reached"] is False


class TestGetCitations:
    """Integration tests for _get_citations method."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.base import clear_cache

        clear_cache()
        mock_storage = MagicMock()
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_get_citations_with_grounded_verdict(self, handler_with_storage):
        """Get citations returns grounded verdict data."""
        import json

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_cit_1",
                "grounded_verdict": json.dumps(
                    {
                        "grounding_score": 0.9,
                        "confidence": 0.85,
                        "claims": [{"claim": "Test claim", "evidence": ["source1"]}],
                        "all_citations": [{"source": "source1", "text": "Evidence"}],
                        "verdict": "The claim is well-supported.",
                    }
                ),
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_citations(mock_handler, "debate_cit_1")

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["has_citations"] is True
        assert body["grounding_score"] == 0.9

    def test_get_citations_no_grounded_verdict(self, handler_with_storage):
        """Get citations handles missing grounded verdict."""
        import json

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_cit_2",
                # No grounded_verdict
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_citations(mock_handler, "debate_cit_2")

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["has_citations"] is False
        assert "No evidence citations available" in body["message"]

    def test_get_citations_not_found(self, handler_with_storage):
        """Get citations returns 404 for nonexistent debate."""
        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(return_value=None)

        mock_handler = MagicMock()
        result = handler_with_storage._get_citations(mock_handler, "nonexistent")

        assert result.status_code == 404


class TestGetImpasse:
    """Integration tests for _get_impasse method."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.base import clear_cache

        clear_cache()
        mock_storage = MagicMock()
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_get_impasse_detected(self, handler_with_storage):
        """Get impasse detects impasse conditions."""
        import json
        from aragora.server.handlers.base import clear_cache

        clear_cache()

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_imp_1",
                "consensus_reached": False,
                "critiques": [
                    {"severity": 0.8, "content": "Major issue"},
                    {"severity": 0.9, "content": "Critical problem"},
                ],
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_impasse(mock_handler, "debate_imp_1")

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["is_impasse"] is True
        assert body["indicators"]["no_convergence"] is True
        assert body["indicators"]["high_severity_critiques"] is True

    def test_get_impasse_not_detected(self, handler_with_storage):
        """Get impasse returns false when no impasse."""
        import json
        from aragora.server.handlers.base import clear_cache

        clear_cache()

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_imp_2",
                "consensus_reached": True,
                "critiques": [
                    {"severity": 0.3, "content": "Minor note"},
                ],
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_impasse(mock_handler, "debate_imp_2")

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["is_impasse"] is False

    def test_get_impasse_not_found(self, handler_with_storage):
        """Get impasse returns 404 for nonexistent debate."""
        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(return_value=None)

        mock_handler = MagicMock()
        result = handler_with_storage._get_impasse(mock_handler, "nonexistent")

        assert result.status_code == 404


class TestGetVerificationReport:
    """Integration tests for _get_verification_report method."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.base import clear_cache

        clear_cache()
        mock_storage = MagicMock()
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_get_verification_report_success(self, handler_with_storage):
        """Get verification report returns verification data."""
        import json
        from aragora.server.handlers.base import clear_cache

        clear_cache()

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_ver_1",
                "verification_results": {"claude": 3, "gemini": 2},
                "verification_bonuses": {"claude": 0.15, "gemini": 0.1},
                "winner": "claude",
                "consensus_reached": True,
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_verification_report(mock_handler, "debate_ver_1")

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["verification_enabled"] is True
        assert body["summary"]["total_verified_claims"] == 5
        assert body["summary"]["agents_with_verified_claims"] == 2

    def test_get_verification_report_no_verification(self, handler_with_storage):
        """Get verification report handles no verification data."""
        import json
        from aragora.server.handlers.base import clear_cache

        clear_cache()

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_ver_2",
                # No verification data
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_verification_report(mock_handler, "debate_ver_2")

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["verification_enabled"] is False


class TestGetEvidence:
    """Integration tests for _get_evidence method."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage and continuum memory."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.base import clear_cache

        clear_cache()
        mock_storage = MagicMock()
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_get_evidence_with_grounded_verdict(self, handler_with_storage):
        """Get evidence returns combined evidence data."""
        import json

        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(
            return_value={
                "id": "debate_evi_1",
                "task": "Test task for evidence",
                "grounded_verdict": json.dumps(
                    {
                        "grounding_score": 0.85,
                        "confidence": 0.8,
                        "claims": [{"claim": "Test claim"}],
                        "all_citations": [{"source": "source1"}],
                        "verdict": "Verdict text",
                    }
                ),
            }
        )

        mock_handler = MagicMock()
        result = handler_with_storage._get_evidence(mock_handler, "debate_evi_1")

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body) if isinstance(result.body, (str, bytes)) else result.body
        assert body["has_evidence"] is True
        assert body["grounded_verdict"]["grounding_score"] == 0.85

    def test_get_evidence_not_found(self, handler_with_storage):
        """Get evidence returns 404 for nonexistent debate."""
        storage = handler_with_storage.get_storage()
        storage.get_debate = MagicMock(return_value=None)

        mock_handler = MagicMock()
        result = handler_with_storage._get_evidence(mock_handler, "nonexistent")

        assert result.status_code == 404


class TestHandleMethod:
    """Integration tests for the main handle method routing."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler
        from aragora.server.handlers.base import clear_cache

        clear_cache()

        mock_storage = MagicMock()
        mock_storage.list_recent = MagicMock(return_value=[])
        mock_storage.get_debate = MagicMock(return_value=None)
        mock_storage.is_public = MagicMock(return_value=True)
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_handle_routes_to_list_debates(self, handler_with_storage):
        """Handle routes /api/debates to list debates."""
        from aragora.server.handlers.base import clear_cache

        clear_cache()

        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = False

            mock_handler = MagicMock()
            result = handler_with_storage.handle("/api/v1/debates", {"limit": "10"}, mock_handler)

            assert result is not None
            assert result.status_code == 200

    def test_handle_routes_to_search(self, handler_with_storage):
        """Handle routes /api/search to search debates."""
        with patch.object(handler_with_storage, "_search_debates") as mock_search:
            mock_search.return_value = MagicMock(status_code=200)

            mock_handler = MagicMock()
            result = handler_with_storage.handle(
                "/api/v1/search", {"q": "test query"}, mock_handler
            )

            mock_search.assert_called_once()

    def test_handle_routes_to_queue_status(self, handler_with_storage):
        """Handle routes queue status endpoint."""
        with patch.object(handler_with_storage, "_get_queue_status") as mock_queue:
            mock_queue.return_value = MagicMock(status_code=200)

            mock_handler = MagicMock()
            result = handler_with_storage.handle("/api/v1/debates/queue/status", {}, mock_handler)

            mock_queue.assert_called_once()


class TestHandlePost:
    """Integration tests for POST request handling."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        mock_storage = MagicMock()
        # Debate writes are org-scoped: the debate belongs to the caller's org.
        mock_storage.get_access_info.side_effect = lambda ref: (ref, "test-org-001", False)
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_handle_post_routes_to_create_debate(self, handler_with_storage):
        """Handle POST /api/debates routes to create debate."""
        with patch.object(handler_with_storage, "_create_debate") as mock_create:
            mock_create.return_value = MagicMock(status_code=202)

            mock_handler = MagicMock()
            result = handler_with_storage.handle_post("/api/v1/debates", {}, mock_handler)

            mock_create.assert_called_once()

    def test_handle_post_routes_to_batch_submit(self, handler_with_storage):
        """Handle POST /api/debates/batch routes to batch submit."""
        with patch.object(handler_with_storage, "_submit_batch") as mock_batch:
            mock_batch.return_value = MagicMock(status_code=202)

            mock_handler = MagicMock()
            result = handler_with_storage.handle_post("/api/v1/debates/batch", {}, mock_handler)

            mock_batch.assert_called_once()

    def test_handle_post_routes_to_fork(self, handler_with_storage):
        """Handle POST /api/debates/{id}/fork routes to fork debate."""
        with patch.object(handler_with_storage, "_fork_debate") as mock_fork:
            mock_fork.return_value = MagicMock(status_code=201)
            with patch.object(handler_with_storage, "_extract_debate_id") as mock_extract:
                mock_extract.return_value = ("debate_123", None)

                mock_handler = MagicMock()
                result = handler_with_storage.handle_post(
                    "/api/v1/debates/debate_123/fork", {}, mock_handler
                )

                mock_fork.assert_called_once()

    def test_handle_post_routes_to_cancel(self, handler_with_storage):
        """Handle POST /api/debates/{id}/cancel routes to cancel debate."""
        with patch.object(handler_with_storage, "_cancel_debate") as mock_cancel:
            mock_cancel.return_value = MagicMock(status_code=200)
            with patch.object(handler_with_storage, "_extract_debate_id") as mock_extract:
                mock_extract.return_value = ("debate_123", None)

                mock_handler = MagicMock()
                result = handler_with_storage.handle_post(
                    "/api/v1/debates/debate_123/cancel", {}, mock_handler
                )

                mock_cancel.assert_called_once()


class TestHandlePatch:
    """Integration tests for PATCH request handling."""

    @pytest.fixture
    def handler_with_storage(self):
        """Create handler with mock storage."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        mock_storage = MagicMock()
        mock_storage.get_debate = MagicMock(
            return_value={
                "id": "debate_123",
                "task": "Test task",
                "status": "active",
            }
        )
        mock_storage.save_debate = MagicMock()
        # Debate writes are org-scoped: the debate belongs to the caller's org.
        mock_storage.get_access_info.side_effect = lambda ref: (ref, "test-org-001", False)
        return DebatesHandler(server_context={"storage": mock_storage})

    def test_handle_patch_updates_debate(self, handler_with_storage):
        """Handle PATCH /api/debates/{id} updates debate."""
        import json

        mock_handler = MagicMock()
        mock_handler.rfile = MagicMock()
        mock_handler.headers = {"Content-Length": "50"}

        # Mock read_json_body
        with patch.object(handler_with_storage, "read_json_body") as mock_read:
            mock_read.return_value = {"title": "Updated Title", "status": "paused"}
            with patch.object(handler_with_storage, "get_current_user") as mock_user:
                mock_user.return_value = None

                result = handler_with_storage.handle_patch(
                    "/api/v1/debates/debate_123", {}, mock_handler
                )

                assert result is not None
                assert result.status_code == 200

    def test_handle_patch_validates_status(self, handler_with_storage):
        """Handle PATCH validates status values."""
        mock_handler = MagicMock()

        with patch.object(handler_with_storage, "read_json_body") as mock_read:
            mock_read.return_value = {"status": "invalid_status"}
            with patch.object(handler_with_storage, "get_current_user") as mock_user:
                mock_user.return_value = None

                result = handler_with_storage.handle_patch(
                    "/api/v1/debates/debate_123", {}, mock_handler
                )

                assert result is not None
                assert result.status_code == 400


class TestExtractDebateId:
    """Tests for _extract_debate_id method."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        return DebatesHandler(server_context={})

    def test_extract_valid_id(self, handler):
        """Extracts valid debate ID from path."""
        debate_id, err = handler._extract_debate_id("/api/v1/debates/debate_123/impasse")

        assert debate_id == "debate_123"
        assert err is None

    def test_extract_invalid_path(self, handler):
        """Returns error for invalid path."""
        debate_id, err = handler._extract_debate_id("/api/invalid")

        assert debate_id is None
        assert err is not None

    def test_extract_normalizes_version(self, handler):
        """Normalizes versioned paths correctly."""
        debate_id, err = handler._extract_debate_id("/api/v2/debates/debate_456/convergence")

        assert debate_id == "debate_456"
        assert err is None
