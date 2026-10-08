"""
Comprehensive tests for FastAPI debate route endpoints.

Covers:
- GET  /api/v2/debates                         - List debates with pagination
- GET  /api/v2/debates/{debate_id}             - Get debate by ID
- GET  /api/v2/debates/{debate_id}/messages    - Get debate messages
- GET  /api/v2/debates/{debate_id}/convergence - Get convergence status
- PATCH /api/v2/debates/{debate_id}            - Update debate metadata
- DELETE /api/v2/debates/{debate_id}           - Delete a debate
- Input validation (Pydantic 422 errors)
- Auth enforcement on write operations

Callers are signed in as an owner of ``org-1``, which owns every mocked debate;
cross-org isolation is covered in ``test_debates_decisions_isolation.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.server.fastapi import create_app


@pytest.fixture
def app():
    """Create a test FastAPI app."""
    return create_app()


@pytest.fixture
def mock_storage():
    """Create a mock debate storage whose debates all belong to org-1."""
    storage = MagicMock()
    storage.list_recent = MagicMock(return_value=[])
    storage.count_debates = MagicMock(return_value=0)
    storage.get_access_info = MagicMock(side_effect=lambda ref: (ref, "org-1", False))
    storage.get_debate = MagicMock(return_value=None)
    storage.save_debate = MagicMock()
    storage.delete_debate = MagicMock(return_value=True)
    return storage


@pytest.fixture
def org1_headers(fastapi_bearer):
    return fastapi_bearer("user-1", "org-1")


@pytest.fixture
def app_with_context(app, mock_storage):
    app.state.context = {
        "storage": mock_storage,
        "elo_system": MagicMock(),
        "user_store": None,
        "rbac_checker": MagicMock(),
        "decision_service": MagicMock(),
    }
    return app


@pytest.fixture
def anon_client(app_with_context):
    """A client with mocked context and no credentials."""
    return TestClient(app_with_context, raise_server_exceptions=False)


@pytest.fixture
def client(app_with_context, org1_headers):
    """A client signed in as an owner of org-1."""
    return TestClient(app_with_context, headers=org1_headers, raise_server_exceptions=False)


@pytest.fixture
def sample_debate_dict():
    """Sample debate data in dict form."""
    return {
        "id": "debate-abc123",
        "task": "Design a rate limiter for high-traffic API",
        "status": "completed",
        "protocol": {"rounds": 3, "consensus": "majority"},
        "agents": ["claude", "codex", "gemini"],
        "rounds": [
            {
                "round_num": 1,
                "messages": [
                    {"role": "proposal", "content": "Token bucket approach", "agent": "claude"},
                    {"role": "proposal", "content": "Sliding window approach", "agent": "codex"},
                ],
            },
            {
                "round_num": 2,
                "messages": [
                    {
                        "role": "critique",
                        "content": "Token bucket scales better",
                        "agent": "gemini",
                    },
                ],
            },
        ],
        "final_answer": "Token bucket with sliding window fallback",
        "consensus": {"confidence": 0.85, "method": "majority"},
        "created_at": "2026-02-10T10:00:00",
        "updated_at": "2026-02-10T10:15:00",
        "metadata": {"domain": "engineering"},
        "tags": ["api", "performance"],
    }


@pytest.fixture
def sample_debates_list():
    """Sample list of debate summaries."""
    return [
        {
            "id": "debate-001",
            "task": "Design authentication system",
            "status": "completed",
            "agents": ["claude", "codex"],
            "rounds": [{"round_num": 1, "messages": []}],
            "consensus": {"confidence": 0.9},
            "created_at": "2026-02-10T09:00:00",
        },
        {
            "id": "debate-002",
            "task": "Choose database for analytics",
            "status": "active",
            "agents": ["claude", "gemini", "grok"],
            "rounds": [],
            "consensus": None,
            "created_at": "2026-02-10T10:00:00",
        },
        {
            "id": "debate-003",
            "task": "Review security architecture",
            "status": "paused",
            "agents": ["claude"],
            "rounds": [{"round_num": 1, "messages": []}, {"round_num": 2, "messages": []}],
            "consensus": None,
            "created_at": "2026-02-10T11:00:00",
        },
    ]


def _make_auth_context(*permissions: str):
    from aragora.rbac.models import AuthorizationContext

    return AuthorizationContext(
        user_id="user-1",
        org_id="org-1",
        workspace_id="ws-1",
        roles={"admin"},
        permissions=set(permissions),
    )


# =============================================================================
# GET /api/v2/debates
# =============================================================================


class TestListDebates:
    """Tests for GET /api/v2/debates."""

    def test_returns_200_empty_list(self, client):
        """List debates returns 200 with empty list."""
        response = client.get("/api/v2/debates")
        assert response.status_code == 200
        data = response.json()
        assert data["debates"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0

    def test_requires_auth(self, anon_client, mock_storage):
        """Anonymous callers get 401 and storage is never listed."""
        response = anon_client.get("/api/v2/debates")
        assert response.status_code == 401
        assert response.json()["code"] == "auth_required"
        mock_storage.list_recent.assert_not_called()

    def test_returns_debates_with_data(self, client, mock_storage, sample_debates_list):
        """List debates returns summaries from storage."""
        mock_storage.list_recent.return_value = sample_debates_list
        mock_storage.count_debates.return_value = 3

        response = client.get("/api/v2/debates")
        assert response.status_code == 200
        data = response.json()
        assert len(data["debates"]) == 3
        assert data["total"] == 3

        # Check first debate summary
        first = data["debates"][0]
        assert first["id"] == "debate-001"
        assert first["task"] == "Design authentication system"
        assert first["status"] == "completed"
        assert first["agent_count"] == 2
        assert first["round_count"] == 1
        assert first["has_consensus"] is True

    def test_pagination_params(self, client, mock_storage):
        """List debates passes pagination params and the caller's org to storage."""
        mock_storage.list_recent.return_value = []
        mock_storage.count_debates.return_value = 0

        response = client.get("/api/v2/debates?limit=10&offset=20")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 20
        mock_storage.list_recent.assert_called_once_with(limit=10, org_id="org-1", offset=20)
        mock_storage.count_debates.assert_called_once_with(org_id="org-1")

    def test_status_filter(self, client, mock_storage, sample_debates_list):
        """List debates supports status filter."""
        mock_storage.list_recent.return_value = sample_debates_list
        mock_storage.count_debates.return_value = 3

        response = client.get("/api/v2/debates?status=active")
        assert response.status_code == 200
        data = response.json()
        assert [d["id"] for d in data["debates"]] == ["debate-002"]

    def test_limit_validation_min(self, client):
        """Limit must be >= 1."""
        response = client.get("/api/v2/debates?limit=0")
        assert response.status_code == 422

    def test_limit_validation_max(self, client):
        """Limit must be <= 100."""
        response = client.get("/api/v2/debates?limit=101")
        assert response.status_code == 422

    def test_offset_validation_min(self, client):
        """Offset must be >= 0."""
        response = client.get("/api/v2/debates?offset=-1")
        assert response.status_code == 422

    def test_no_consensus_shows_false(self, client, mock_storage):
        """Debate without consensus shows has_consensus=False."""
        mock_storage.list_recent.return_value = [
            {
                "id": "d-1",
                "task": "No consensus yet",
                "status": "active",
                "agents": [],
                "rounds": [],
                "consensus": None,
            }
        ]
        mock_storage.count_debates.return_value = 1

        response = client.get("/api/v2/debates")
        data = response.json()
        assert data["debates"][0]["has_consensus"] is False

    def test_returns_503_when_storage_unavailable(self, app, org1_headers):
        """List debates returns 503 when storage not available."""
        app.state.context = {"storage": None}
        c = TestClient(app, headers=org1_headers, raise_server_exceptions=False)
        response = c.get("/api/v2/debates")
        assert response.status_code == 503


# =============================================================================
# GET /api/v2/debates/{debate_id}
# =============================================================================


class TestGetDebate:
    """Tests for GET /api/v2/debates/{debate_id}."""

    def test_returns_404_for_nonexistent(self, client, mock_storage):
        """Get nonexistent debate returns 404."""
        mock_storage.get_debate.return_value = None
        response = client.get("/api/v2/debates/nonexistent-id")
        assert response.status_code == 404

    def test_returns_debate_details(self, client, mock_storage, sample_debate_dict):
        """Get existing debate returns full details."""
        mock_storage.get_debate.return_value = sample_debate_dict

        response = client.get("/api/v2/debates/debate-abc123")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "debate-abc123"
        assert data["task"] == "Design a rate limiter for high-traffic API"
        assert data["status"] == "completed"
        assert data["agents"] == ["claude", "codex", "gemini"]
        assert len(data["rounds"]) == 2
        assert data["final_answer"] == "Token bucket with sliding window fallback"
        assert data["consensus"]["confidence"] == 0.85
        assert data["metadata"]["domain"] == "engineering"

    def test_returns_debate_with_environment_task(self, client, mock_storage):
        """Get debate handles environment.task field."""
        mock_storage.get_debate.return_value = {
            "id": "debate-env",
            "environment": {"task": "Review API design"},
            "status": "active",
            "agents": [],
            "rounds": [],
        }

        response = client.get("/api/v2/debates/debate-env")
        assert response.status_code == 200
        data = response.json()
        assert data["task"] == "Review API design"

    def test_passes_debate_id_to_storage(self, client, mock_storage, sample_debate_dict):
        """Get debate passes the correct ID to storage."""
        mock_storage.get_debate.return_value = sample_debate_dict
        client.get("/api/v2/debates/debate-abc123")
        mock_storage.get_debate.assert_called_with("debate-abc123")

    def test_serializes_object_backed_consensus_for_popup_polling(self, client, mock_storage):
        """Object-backed debates expose final answers and confidence for popup polling."""
        mock_storage.get_debate.return_value = SimpleNamespace(
            debate_id="debate-popup-123",
            task="Review highlighted webpage text",
            status="completed",
            protocol=SimpleNamespace(rounds=3, consensus="majority"),
            agents=["claude", "codex"],
            rounds=[
                SimpleNamespace(
                    round_num=1,
                    messages=[
                        SimpleNamespace(
                            role="proposal",
                            content="This claim depends on an unverified premise.",
                            agent="claude",
                        )
                    ],
                )
            ],
            final_answer="The selected text overstates certainty and omits evidence.",
            consensus=SimpleNamespace(
                confidence=0.91,
                final_answer="The selected text overstates certainty and omits evidence.",
                reached=True,
            ),
            metadata={"source": "browser_extension_context_menu"},
        )

        response = client.get("/api/v2/debates/debate-popup-123")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "debate-popup-123"
        assert data["protocol"]["consensus"] == "majority"
        assert data["rounds"][0]["messages"][0]["content"] == (
            "This claim depends on an unverified premise."
        )
        assert data["final_answer"] == (
            "The selected text overstates certainty and omits evidence."
        )
        assert data["consensus"]["confidence"] == 0.91
        assert data["consensus"]["final_answer"] == (
            "The selected text overstates certainty and omits evidence."
        )


# =============================================================================
# GET /api/v2/debates/{debate_id}/messages
# =============================================================================


class TestGetDebateMessages:
    """Tests for GET /api/v2/debates/{debate_id}/messages."""

    def test_returns_404_for_nonexistent(self, client, mock_storage):
        """Messages endpoint returns 404 for nonexistent debate."""
        mock_storage.get_debate.return_value = None
        response = client.get("/api/v2/debates/nonexistent/messages")
        assert response.status_code == 404

    def test_returns_messages_from_rounds(self, client, mock_storage, sample_debate_dict):
        """Messages endpoint extracts messages from rounds."""
        mock_storage.get_debate.return_value = sample_debate_dict

        response = client.get("/api/v2/debates/debate-abc123/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["debate_id"] == "debate-abc123"
        assert data["total"] == 3  # 2 from round 1, 1 from round 2
        assert len(data["messages"]) == 3
        assert data["messages"][0]["content"] == "Token bucket approach"
        assert data["messages"][0]["agent"] == "claude"

    def test_pagination(self, client, mock_storage, sample_debate_dict):
        """Messages endpoint supports pagination."""
        mock_storage.get_debate.return_value = sample_debate_dict

        response = client.get("/api/v2/debates/debate-abc123/messages?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 2
        assert data["total"] == 3
        assert data["has_more"] is True

    def test_pagination_offset(self, client, mock_storage, sample_debate_dict):
        """Messages endpoint respects offset."""
        mock_storage.get_debate.return_value = sample_debate_dict

        response = client.get("/api/v2/debates/debate-abc123/messages?limit=10&offset=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 1  # Only 1 message after offset 2
        assert data["has_more"] is False

    def test_empty_messages(self, client, mock_storage):
        """Messages endpoint handles debates with no messages."""
        mock_storage.get_debate.return_value = {
            "id": "debate-empty",
            "task": "Empty debate",
            "status": "active",
            "rounds": [],
        }

        response = client.get("/api/v2/debates/debate-empty/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["total"] == 0
        assert data["has_more"] is False

    def test_limit_validation(self, client):
        """Message limit must be between 1 and 500."""
        response = client.get("/api/v2/debates/x/messages?limit=0")
        assert response.status_code == 422

        response = client.get("/api/v2/debates/x/messages?limit=501")
        assert response.status_code == 422


# =============================================================================
# GET /api/v2/debates/{debate_id}/convergence
# =============================================================================


class TestGetDebateConvergence:
    """Tests for GET /api/v2/debates/{debate_id}/convergence."""

    def test_returns_404_for_nonexistent(self, client, mock_storage):
        """Convergence endpoint returns 404 for nonexistent debate."""
        mock_storage.get_debate.return_value = None
        response = client.get("/api/v2/debates/nonexistent/convergence")
        assert response.status_code == 404

    def test_converged_debate(self, client, mock_storage, sample_debate_dict):
        """Convergence endpoint returns converged=True with consensus."""
        mock_storage.get_debate.return_value = sample_debate_dict

        response = client.get("/api/v2/debates/debate-abc123/convergence")
        assert response.status_code == 200
        data = response.json()
        assert data["debate_id"] == "debate-abc123"
        assert data["converged"] is True
        assert data["confidence"] == 0.85
        assert data["rounds_to_convergence"] == 2

    def test_not_converged_debate(self, client, mock_storage):
        """Convergence endpoint returns converged=False without consensus."""
        mock_storage.get_debate.return_value = {
            "id": "debate-active",
            "task": "Ongoing debate",
            "status": "active",
            "consensus": None,
            "rounds": [{"round_num": 1}],
        }

        response = client.get("/api/v2/debates/debate-active/convergence")
        assert response.status_code == 200
        data = response.json()
        assert data["converged"] is False
        assert data["confidence"] == 0.0
        assert data["rounds_to_convergence"] is None

    def test_includes_similarity_scores(self, client, mock_storage):
        """Convergence endpoint includes similarity scores from metrics."""
        mock_storage.get_debate.return_value = {
            "id": "debate-sim",
            "task": "With scores",
            "status": "completed",
            "consensus": {"confidence": 0.9},
            "rounds": [{"round_num": 1}],
            "metrics": {"similarity_scores": [0.5, 0.7, 0.85, 0.92]},
        }

        response = client.get("/api/v2/debates/debate-sim/convergence")
        assert response.status_code == 200
        data = response.json()
        assert data["similarity_scores"] == [0.5, 0.7, 0.85, 0.92]

    def test_object_backed_debate_uses_consensus_fallbacks(self, client, mock_storage):
        """Convergence endpoint uses object-backed confidence fields when consensus is not a dict."""
        mock_storage.get_debate.return_value = SimpleNamespace(
            debate_id="debate-popup-123",
            task="Review highlighted webpage text",
            rounds=[
                SimpleNamespace(
                    round_num=1,
                    messages=[SimpleNamespace(role="proposal", content="Objection", agent="codex")],
                )
            ],
            confidence=0.73,
            consensus_reached=True,
            final_answer="Key assumptions remain unsupported.",
        )

        response = client.get("/api/v2/debates/debate-popup-123/convergence")
        assert response.status_code == 200

        data = response.json()
        assert data["converged"] is True
        assert data["confidence"] == 0.73
        assert data["rounds_to_convergence"] == 1


# =============================================================================
# POST /api/v2/debates
# =============================================================================


def _as_org_member(client):
    from aragora.server.fastapi.dependencies.auth import require_authenticated
    from aragora.tenancy.record_scope import OrgScope, require_org_scope_fastapi

    client.app.dependency_overrides[require_authenticated] = lambda: _make_auth_context(
        "debates:create"
    )
    client.app.dependency_overrides[require_org_scope_fastapi] = lambda: OrgScope(
        org_id="org-1", user_id="user-1", role="admin"
    )


class TestCreateDebate:
    """Tests for POST /api/v2/debates."""

    def test_requires_auth(self, anon_client):
        """Create debate requires authentication."""
        response = anon_client.post("/api/v2/debates", json={"question": "Review this selection"})
        assert response.status_code == 401

    def test_requires_org_before_the_controller(self, client, monkeypatch):
        """An authenticated caller without an org gets 403 org_required; nothing starts."""
        from aragora.rbac.models import AuthorizationContext
        from aragora.server.fastapi.dependencies.auth import require_authenticated

        no_org = AuthorizationContext(
            user_id="user-1", org_id=None, roles={"admin"}, permissions={"debates:create"}
        )

        async def _no_org_auth_context(request):
            return no_org

        monkeypatch.setattr(
            "aragora.server.fastapi.dependencies.auth.get_auth_context", _no_org_auth_context
        )
        client.app.dependency_overrides[require_authenticated] = lambda: no_org
        controller_getter = MagicMock()
        with patch(
            "aragora.server.fastapi.routes.debates._get_debate_controller", controller_getter
        ):
            response = client.post(
                "/api/v2/debates",
                json={"question": "Review this selection", "metadata": {"org_id": "org-1"}},
            )
        client.app.dependency_overrides.clear()

        assert response.status_code == 403
        assert response.json()["code"] == "org_required"
        controller_getter.assert_not_called()

    def test_creates_debate_for_browser_extension_contract(self, client):
        """Create debate passes extension payload through to the controller."""
        from aragora.server.debate_controller import DebateResponse

        _as_org_member(client)

        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = DebateResponse(
            success=True,
            debate_id="adhoc_ext1234",
            status="created",
        )

        with patch(
            "aragora.server.fastapi.routes.debates._get_debate_controller",
            return_value=mock_controller,
        ):
            response = client.post(
                "/api/v2/debates",
                json={
                    "question": 'Analyze the selected text from "Example Docs".',
                    "rounds": 3,
                    "consensus": "majority",
                    "auto_select": True,
                    "context": "Source title: Example Docs\nSource URL: https://example.com",
                    "metadata": {
                        "source": "browser_extension_context_menu",
                        "source_title": "Example Docs",
                        "source_url": "https://example.com",
                    },
                },
            )

        client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["debate_id"] == "adhoc_ext1234"
        assert data["status"] == "created"

        debate_request = mock_controller.start_debate.call_args.args[0]
        assert debate_request.question == 'Analyze the selected text from "Example Docs".'
        assert debate_request.rounds == 3
        assert debate_request.consensus == "majority"
        assert debate_request.auto_select is True
        assert (
            debate_request.context == "Source title: Example Docs\nSource URL: https://example.com"
        )
        assert debate_request.metadata["source"] == "browser_extension_context_menu"
        assert debate_request.metadata["source_url"] == "https://example.com"

    def test_create_debate_stamps_caller_org_not_client_metadata(self, client):
        """The debate owner comes from the auth context, never from the body."""
        from aragora.server.debate_controller import DebateResponse

        _as_org_member(client)
        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = DebateResponse(
            success=True, debate_id="adhoc_owned", status="created"
        )

        with patch(
            "aragora.server.fastapi.routes.debates._get_debate_controller",
            return_value=mock_controller,
        ):
            response = client.post(
                "/api/v2/debates",
                json={
                    "question": "Should we shard the database?",
                    "metadata": {"organization_id": "org-evil", "org_id": "org-evil"},
                },
            )

        client.app.dependency_overrides.clear()

        assert response.status_code == 200
        debate_request = mock_controller.start_debate.call_args.args[0]
        assert debate_request.org_id == "org-1"

    def test_maps_controller_failures_to_http_errors(self, client):
        """Create debate returns controller error details/status for popup display."""
        from aragora.server.debate_controller import DebateResponse

        _as_org_member(client)

        mock_controller = MagicMock()
        mock_controller.start_debate.return_value = DebateResponse(
            success=False,
            error="No AI model API keys are configured on this server.",
            status_code=400,
            use_playground=True,
        )

        with patch(
            "aragora.server.fastapi.routes.debates._get_debate_controller",
            return_value=mock_controller,
        ):
            response = client.post("/api/v2/debates", json={"question": "Review this selection"})

        client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json()["detail"] == "No AI model API keys are configured on this server."

    def test_falls_back_to_fastapi_controller_builder_when_legacy_getter_missing(self, client):
        """FastAPI route can resolve a controller even without a legacy getter."""
        from aragora.server.fastapi.routes import debates as debates_routes

        request = MagicMock()
        request.app = client.app
        mock_controller = MagicMock()

        with patch(
            "aragora.server.fastapi.routes.debates._build_fastapi_debate_controller",
            return_value=mock_controller,
        ) as builder:
            with patch(
                "aragora.server.debate_controller.get_debate_controller",
                new=None,
                create=True,
            ):
                controller = debates_routes._get_debate_controller(
                    request, client.app.state.context["storage"]
                )

        assert controller is mock_controller
        builder.assert_called_once_with(request, client.app.state.context["storage"])


# =============================================================================
# PATCH /api/v2/debates/{debate_id}
# =============================================================================


class TestUpdateDebate:
    """Tests for PATCH /api/v2/debates/{debate_id}."""

    def test_requires_auth(self, anon_client, mock_storage):
        """PATCH debates requires authentication."""
        response = anon_client.patch(
            "/api/v2/debates/debate-abc123",
            json={"title": "New title"},
        )
        assert response.status_code == 401
        mock_storage.save_debate.assert_not_called()

    def test_returns_404_for_nonexistent(self, client, mock_storage):
        """PATCH returns 404 for nonexistent debate."""
        mock_storage.get_debate.return_value = None

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        response = client.patch(
            "/api/v2/debates/nonexistent",
            json={"title": "New title"},
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_updates_title(self, client, mock_storage, sample_debate_dict):
        """PATCH updates debate title."""
        mock_storage.get_debate.return_value = sample_debate_dict.copy()

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        response = client.patch(
            "/api/v2/debates/debate-abc123",
            json={"title": "Updated title"},
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["debate_id"] == "debate-abc123"
        assert "title" in data["updated_fields"]

    def test_updates_status(self, client, mock_storage, sample_debate_dict):
        """PATCH updates debate status."""
        mock_storage.get_debate.return_value = sample_debate_dict.copy()

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        response = client.patch(
            "/api/v2/debates/debate-abc123",
            json={"status": "archived"},
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert "status" in data["updated_fields"]

    def test_rejects_invalid_status(self, client, mock_storage, sample_debate_dict):
        """PATCH rejects invalid status values."""
        mock_storage.get_debate.return_value = sample_debate_dict.copy()

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        response = client.patch(
            "/api/v2/debates/debate-abc123",
            json={"status": "invalid_status"},
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 400

    def test_rejects_empty_update(self, client, mock_storage, sample_debate_dict):
        """PATCH rejects update with no fields."""
        mock_storage.get_debate.return_value = sample_debate_dict.copy()

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        response = client.patch(
            "/api/v2/debates/debate-abc123",
            json={},
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 400

    def test_updates_tags(self, client, mock_storage, sample_debate_dict):
        """PATCH updates debate tags."""
        mock_storage.get_debate.return_value = sample_debate_dict.copy()

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        response = client.patch(
            "/api/v2/debates/debate-abc123",
            json={"tags": ["security", "architecture"]},
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert "tags" in data["updated_fields"]

    def test_updates_metadata(self, client, mock_storage, sample_debate_dict):
        """PATCH updates debate metadata."""
        mock_storage.get_debate.return_value = sample_debate_dict.copy()

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        response = client.patch(
            "/api/v2/debates/debate-abc123",
            json={"metadata": {"priority": "high", "reviewer": "alice"}},
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert "metadata" in data["updated_fields"]

    def test_calls_save_debate(self, client, mock_storage, sample_debate_dict):
        """PATCH calls storage.save_debate after update."""
        mock_storage.get_debate.return_value = sample_debate_dict.copy()

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        client.patch(
            "/api/v2/debates/debate-abc123",
            json={"title": "New title"},
        )
        client.app.dependency_overrides.clear()

        mock_storage.save_debate.assert_called_once()


# =============================================================================
# DELETE /api/v2/debates/{debate_id}
# =============================================================================


class TestDeleteDebate:
    """Tests for DELETE /api/v2/debates/{debate_id}."""

    def test_requires_auth(self, anon_client, mock_storage):
        """DELETE debates requires authentication."""
        response = anon_client.delete("/api/v2/debates/debate-abc123")
        assert response.status_code == 401
        mock_storage.delete_debate.assert_not_called()

    def test_deletes_debate(self, client, mock_storage, sample_debate_dict):
        """DELETE removes debate from storage."""
        mock_storage.get_debate.return_value = sample_debate_dict
        mock_storage.delete_debate.return_value = True

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:delete"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        response = client.delete("/api/v2/debates/debate-abc123")
        client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["id"] == "debate-abc123"

    def test_returns_404_for_nonexistent(self, client, mock_storage):
        """DELETE returns 404 for nonexistent debate."""
        mock_storage.get_debate.return_value = None

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:delete"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        response = client.delete("/api/v2/debates/nonexistent")
        client.app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_calls_delete_with_cascade(self, client, mock_storage, sample_debate_dict):
        """DELETE calls storage.delete_debate with cascade=True."""
        mock_storage.get_debate.return_value = sample_debate_dict
        mock_storage.delete_debate.return_value = True

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"debates:delete"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

        client.delete("/api/v2/debates/debate-abc123")
        client.app.dependency_overrides.clear()

        mock_storage.delete_debate.assert_called_once_with("debate-abc123", cascade_critiques=True)


# =============================================================================
# Storage Fallback
# =============================================================================


class TestStorageFallback:
    """Tests for storage dependency fallback behavior."""

    def test_returns_503_without_context(self, app, org1_headers):
        """Routes return 503 when server context is not initialized."""
        # Don't set app.state.context
        c = TestClient(app, headers=org1_headers, raise_server_exceptions=False)
        response = c.get("/api/v2/debates")
        assert response.status_code == 503

    def test_returns_503_without_storage(self, app, org1_headers):
        """Routes return 503 when storage is not available."""
        app.state.context = {"storage": None}
        c = TestClient(app, headers=org1_headers, raise_server_exceptions=False)
        response = c.get("/api/v2/debates")
        assert response.status_code == 503

    def test_fallback_to_debates_dict(self, app, org1_headers):
        """Without list_recent the list reads storage.debates, keeping the caller org's."""
        storage = MagicMock(spec=[])  # No list_recent or count_debates
        storage.debates = {
            "d-1": {
                "id": "d-1",
                "task": "Test",
                "status": "active",
                "agents": [],
                "rounds": [],
                "consensus": None,
                "org_id": "org-1",
            },
            "d-other": {"id": "d-other", "task": "Other org", "org_id": "org-2"},
            "d-unowned": {"id": "d-unowned", "task": "No owner"},
        }
        app.state.context = {
            "storage": storage,
            "elo_system": None,
            "rbac_checker": None,
            "decision_service": None,
        }
        c = TestClient(app, headers=org1_headers, raise_server_exceptions=False)
        response = c.get("/api/v2/debates")
        assert response.status_code == 200
        data = response.json()
        assert [d["id"] for d in data["debates"]] == ["d-1"]
        assert data["total"] == 1
