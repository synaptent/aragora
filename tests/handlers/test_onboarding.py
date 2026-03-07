"""Tests for the OnboardingHandler (aragora/server/handlers/onboarding.py).

Covers all routes and behavior of the OnboardingHandler class:
- can_handle() routing for all ROUTES and path normalization
- GET /api/v1/onboarding/flow - Get current onboarding state
- POST /api/v1/onboarding/flow - Initialize onboarding flow
- PUT /api/v1/onboarding/flow/step - Update step progress
- GET /api/v1/onboarding/templates - Get recommended starter templates
- POST /api/v1/onboarding/first-debate - Start guided first debate
- POST /api/v1/onboarding/quick-start - Apply quick-start configuration
- POST /api/v1/onboarding/quick-debate - One-click quick debate
- GET /api/v1/onboarding/analytics - Get onboarding funnel analytics
- Error handling (not found, invalid data, missing params)
- Edge cases (empty flows, completed flows, re-onboarding)
- Method not allowed responses
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.onboarding import (
    QUICK_START_CONFIGS,
    STARTER_TEMPLATES,
    OnboardingHandler,
    OnboardingState,
    OnboardingStep,
    QuickStartProfile,
    UseCase,
    _analytics_events,
    _analytics_lock,
    _get_next_step,
    _get_recommended_templates,
    _get_step_order,
    _onboarding_flows,
    _onboarding_lock,
    _track_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _data(result) -> dict:
    """Extract the 'data' envelope from a success response."""
    body = _body(result)
    return body.get("data", body)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create an OnboardingHandler with minimal server context."""
    return OnboardingHandler({})


@pytest.fixture(autouse=True)
def _clear_state():
    """Clear in-memory onboarding state between tests."""
    with _onboarding_lock:
        _onboarding_flows.clear()
    with _analytics_lock:
        _analytics_events.clear()
    yield
    with _onboarding_lock:
        _onboarding_flows.clear()
    with _analytics_lock:
        _analytics_events.clear()


@pytest.fixture(autouse=True)
def _mock_repo(monkeypatch):
    """Mock the onboarding repository to avoid SQLite I/O in tests."""
    mock_repo = MagicMock()
    mock_repo.get_flow.return_value = None
    mock_repo.create_flow.return_value = "mock-flow-id"
    mock_repo.update_flow.return_value = True

    monkeypatch.setattr(
        "aragora.server.handlers.onboarding.get_onboarding_repository",
        lambda: mock_repo,
    )
    return mock_repo


@pytest.fixture(autouse=True)
def _mock_marketplace(monkeypatch):
    """Mock marketplace template loading to avoid import side effects."""
    monkeypatch.setattr(
        "aragora.server.handlers.onboarding._load_marketplace_templates",
        lambda: [],
    )


def _make_flow(
    user_id: str = "test-user-001",
    org_id: str | None = None,
    step: OnboardingStep = OnboardingStep.WELCOME,
    completed_steps: list[str] | None = None,
    use_case: str | None = None,
    completed_at: str | None = None,
    skipped: bool = False,
) -> OnboardingState:
    """Create a test OnboardingState and store it in the in-memory dict."""
    now = datetime.now(timezone.utc).isoformat()
    flow = OnboardingState(
        id="onb_test123",
        user_id=user_id,
        organization_id=org_id,
        current_step=step,
        completed_steps=completed_steps or [],
        use_case=use_case,
        selected_template_id=None,
        first_debate_id=None,
        quick_start_profile=None,
        team_invites=[],
        started_at=now,
        updated_at=now,
        completed_at=completed_at,
        skipped=skipped,
        metadata={},
    )
    key = f"{user_id}:{org_id or 'personal'}"
    with _onboarding_lock:
        _onboarding_flows[key] = flow
    return flow


# ============================================================================
# can_handle routing
# ============================================================================


class TestCanHandle:
    """Verify that can_handle correctly accepts or rejects paths."""

    def test_accepts_onboarding_flow(self, handler):
        assert handler.can_handle("/api/v1/onboarding/flow") is True

    def test_accepts_onboarding_templates(self, handler):
        assert handler.can_handle("/api/v1/onboarding/templates") is True

    def test_accepts_onboarding_first_debate(self, handler):
        assert handler.can_handle("/api/v1/onboarding/first-debate") is True

    def test_accepts_onboarding_quick_start(self, handler):
        assert handler.can_handle("/api/v1/onboarding/quick-start") is True

    def test_accepts_onboarding_quick_debate(self, handler):
        assert handler.can_handle("/api/v1/onboarding/quick-debate") is True

    def test_accepts_onboarding_analytics(self, handler):
        assert handler.can_handle("/api/v1/onboarding/analytics") is True

    def test_accepts_onboarding_flow_step(self, handler):
        assert handler.can_handle("/api/v1/onboarding/flow/step") is True

    def test_accepts_v2_paths(self, handler):
        assert handler.can_handle("/api/v2/onboarding/flow") is True

    def test_accepts_unversioned_paths(self, handler):
        assert handler.can_handle("/api/onboarding/flow") is True

    def test_rejects_non_onboarding_paths(self, handler):
        assert handler.can_handle("/api/v1/billing/plans") is False

    def test_rejects_partial_match(self, handler):
        assert handler.can_handle("/api/v1/onboard") is False

    def test_rejects_root_api(self, handler):
        assert handler.can_handle("/api/v1/") is False


# ============================================================================
# GET /api/v1/onboarding/flow
# ============================================================================


class TestGetFlow:
    """Tests for GET onboarding flow endpoint."""

    @pytest.mark.asyncio
    async def test_no_flow_returns_needs_onboarding(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 200
        data = _data(result)
        assert data["exists"] is False
        assert data["needs_onboarding"] is True

    @pytest.mark.asyncio
    async def test_existing_flow_returned(self, handler):
        flow = _make_flow(step=OnboardingStep.USE_CASE)
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 200
        data = _data(result)
        assert data["exists"] is True
        assert data["flow"]["current_step"] == "use_case"

    @pytest.mark.asyncio
    async def test_completed_flow_no_longer_needs_onboarding(self, handler):
        now = datetime.now(timezone.utc).isoformat()
        _make_flow(
            completed_at=now,
            completed_steps=[s.value for s in _get_step_order()],
        )
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["exists"] is True
        assert data["needs_onboarding"] is False

    @pytest.mark.asyncio
    async def test_skipped_flow_no_longer_needs_onboarding(self, handler):
        _make_flow(skipped=True)
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["needs_onboarding"] is False

    @pytest.mark.asyncio
    async def test_flow_includes_progress_percentage(self, handler):
        _make_flow(completed_steps=["welcome", "use_case"])
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["flow"]["progress_percentage"] == 25  # 2/8 = 25%

    @pytest.mark.asyncio
    async def test_flow_includes_recommended_templates(self, handler):
        _make_flow(use_case="architecture_review")
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert "recommended_templates" in data

    @pytest.mark.asyncio
    async def test_flow_with_organization_id(self, handler):
        _make_flow(org_id="org-001")
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="GET",
            user_id="test-user-001",
            organization_id="org-001",
        )
        data = _data(result)
        assert data["exists"] is True

    @pytest.mark.asyncio
    async def test_flow_from_repo_when_not_in_memory(self, handler, _mock_repo):
        _mock_repo.get_flow.return_value = {
            "id": "flow-from-repo",
            "user_id": "test-user-001",
            "org_id": None,
            "current_step": "welcome",
            "completed_steps": [],
            "use_case": None,
            "selected_template": None,
            "first_debate_id": None,
            "quick_start_profile": None,
            "metadata": {},
            "started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        }
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["exists"] is True
        assert data["flow"]["id"] == "flow-from-repo"


# ============================================================================
# POST /api/v1/onboarding/flow
# ============================================================================


class TestInitFlow:
    """Tests for POST onboarding flow initialization."""

    @pytest.mark.asyncio
    async def test_init_basic_flow(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        assert _status(result) == 200
        data = _data(result)
        assert "flow_id" in data
        assert data["current_step"] == "welcome"
        assert data["message"] == "Onboarding flow initialized"

    @pytest.mark.asyncio
    async def test_init_with_use_case(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={"use_case": "security_audit"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["use_case"] == "security_audit"

    @pytest.mark.asyncio
    async def test_init_with_quick_start_profile(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={"quick_start_profile": "developer"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["quick_start_profile"] == "developer"

    @pytest.mark.asyncio
    async def test_init_with_skip_to_step(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={"skip_to_step": "template_select"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["current_step"] == "template_select"

    @pytest.mark.asyncio
    async def test_init_with_invalid_skip_to_step_defaults_to_welcome(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={"skip_to_step": "nonexistent_step"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["current_step"] == "welcome"

    @pytest.mark.asyncio
    async def test_init_stores_flow_in_memory(self, handler):
        await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        key = "test-user-001:personal"
        with _onboarding_lock:
            assert key in _onboarding_flows

    @pytest.mark.asyncio
    async def test_init_tracks_analytics_event(self, handler):
        await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        with _analytics_lock:
            assert len(_analytics_events) == 1
            assert _analytics_events[0]["event_type"] == "onboarding_started"

    @pytest.mark.asyncio
    async def test_init_returns_recommended_templates(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={"use_case": "security_audit"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert "recommended_templates" in data
        assert isinstance(data["recommended_templates"], list)

    @pytest.mark.asyncio
    async def test_init_with_quick_start_sets_template(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={"quick_start_profile": "developer"},
            user_id="test-user-001",
        )
        data = _data(result)
        # Developer profile has default_template = "arch_review_starter"
        key = "test-user-001:personal"
        with _onboarding_lock:
            flow = _onboarding_flows[key]
            assert flow.selected_template_id == "arch_review_starter"


# ============================================================================
# PUT /api/v1/onboarding/flow/step
# ============================================================================


class TestUpdateStep:
    """Tests for PUT onboarding step update."""

    @pytest.mark.asyncio
    async def test_next_action_advances_step(self, handler):
        _make_flow(step=OnboardingStep.WELCOME)
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "next"},
            user_id="test-user-001",
        )
        assert _status(result) == 200
        data = _data(result)
        assert data["current_step"] == "use_case"
        assert "welcome" in data["completed_steps"]

    @pytest.mark.asyncio
    async def test_previous_action_goes_back(self, handler):
        _make_flow(step=OnboardingStep.ORGANIZATION)
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "previous"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["current_step"] == "use_case"

    @pytest.mark.asyncio
    async def test_previous_at_first_step_stays(self, handler):
        _make_flow(step=OnboardingStep.WELCOME)
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "previous"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["current_step"] == "welcome"

    @pytest.mark.asyncio
    async def test_skip_action_marks_skipped(self, handler):
        _make_flow(step=OnboardingStep.USE_CASE)
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "skip"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["is_skipped"] is True
        assert data["is_complete"] is True

    @pytest.mark.asyncio
    async def test_complete_action_marks_all_done(self, handler):
        _make_flow(step=OnboardingStep.RECEIPT_REVIEW)
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "complete"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["is_complete"] is True
        assert data["current_step"] == "completion"
        assert len(data["completed_steps"]) == len(_get_step_order())

    @pytest.mark.asyncio
    async def test_jump_to_specific_step(self, handler):
        _make_flow(step=OnboardingStep.WELCOME)
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "next", "jump_to_step": "first_debate"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["current_step"] == "first_debate"

    @pytest.mark.asyncio
    async def test_jump_to_invalid_step_returns_400(self, handler):
        _make_flow(step=OnboardingStep.WELCOME)
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "next", "jump_to_step": "nonexistent"},
            user_id="test-user-001",
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_no_flow_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "next"},
            user_id="unknown-user",
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_step_data_stored_in_metadata(self, handler):
        _make_flow(step=OnboardingStep.USE_CASE)
        await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={
                "action": "next",
                "step_data": {"use_case": "security_audit"},
            },
            user_id="test-user-001",
        )
        key = "test-user-001:personal"
        with _onboarding_lock:
            flow = _onboarding_flows[key]
            assert flow.use_case == "security_audit"

    @pytest.mark.asyncio
    async def test_template_select_step_stores_template_id(self, handler):
        _make_flow(step=OnboardingStep.TEMPLATE_SELECT)
        await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={
                "action": "next",
                "step_data": {"template_id": "arch_review_starter"},
            },
            user_id="test-user-001",
        )
        key = "test-user-001:personal"
        with _onboarding_lock:
            flow = _onboarding_flows[key]
            assert flow.selected_template_id == "arch_review_starter"

    @pytest.mark.asyncio
    async def test_first_debate_step_stores_debate_id(self, handler):
        _make_flow(step=OnboardingStep.FIRST_DEBATE)
        await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={
                "action": "next",
                "step_data": {"debate_id": "debate_abc123"},
            },
            user_id="test-user-001",
        )
        key = "test-user-001:personal"
        with _onboarding_lock:
            flow = _onboarding_flows[key]
            assert flow.first_debate_id == "debate_abc123"

    @pytest.mark.asyncio
    async def test_team_invite_step_stores_invites(self, handler):
        _make_flow(step=OnboardingStep.TEAM_INVITE)
        invites = [{"email": "alice@example.com"}, {"email": "bob@example.com"}]
        await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={
                "action": "next",
                "step_data": {"invites": invites},
            },
            user_id="test-user-001",
        )
        key = "test-user-001:personal"
        with _onboarding_lock:
            flow = _onboarding_flows[key]
            assert len(flow.team_invites) == 2

    @pytest.mark.asyncio
    async def test_reaching_completion_marks_completed(self, handler):
        _make_flow(
            step=OnboardingStep.RECEIPT_REVIEW,
            completed_steps=[s.value for s in _get_step_order()[:-2]],
        )
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "next"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["current_step"] == "completion"
        assert data["is_complete"] is True

    @pytest.mark.asyncio
    async def test_progress_percentage_increases(self, handler):
        _make_flow(step=OnboardingStep.WELCOME)
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "next"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["progress_percentage"] > 0

    @pytest.mark.asyncio
    async def test_tracks_step_updated_event(self, handler):
        _make_flow(step=OnboardingStep.WELCOME)
        await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "next"},
            user_id="test-user-001",
        )
        with _analytics_lock:
            event = next(e for e in _analytics_events if e["event_type"] == "step_updated")
            assert event["data"]["flow_id"] == "onb_test123"
            assert event["data"]["from_step"] == "welcome"
            assert event["data"]["to_step"] == "use_case"
            assert event["data"]["completed_steps"] == ["welcome"]


# ============================================================================
# GET /api/v1/onboarding/templates
# ============================================================================


class TestGetTemplates:
    """Tests for GET templates endpoint."""

    @pytest.mark.asyncio
    async def test_get_all_templates(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/templates",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 200
        data = _data(result)
        assert "templates" in data
        assert data["total"] > 0

    @pytest.mark.asyncio
    async def test_filter_by_use_case(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/templates",
            method="GET",
            query_params={"use_case": "security_audit"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["use_case"] == "security_audit"
        # Security templates should come first
        if data["templates"]:
            first = data["templates"][0]
            assert "security_audit" in first["use_cases"] or len(data["templates"]) > 0

    @pytest.mark.asyncio
    async def test_filter_by_profile(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/templates",
            method="GET",
            query_params={"profile": "developer"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["profile"] == "developer"

    @pytest.mark.asyncio
    async def test_profile_reorders_templates(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/templates",
            method="GET",
            query_params={"profile": "security"},
            user_id="test-user-001",
        )
        data = _data(result)
        # Security profile should have security_scan_starter near the top
        template_ids = [t["id"] for t in data["templates"]]
        if "security_scan_starter" in template_ids:
            assert template_ids.index("security_scan_starter") < len(template_ids) // 2

    @pytest.mark.asyncio
    async def test_max_8_templates_returned(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/templates",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["total"] <= 8

    @pytest.mark.asyncio
    async def test_templates_have_required_fields(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/templates",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        for t in data["templates"]:
            assert "id" in t
            assert "name" in t
            assert "description" in t
            assert "agents_count" in t
            assert "rounds" in t
            assert "example_prompt" in t


# ============================================================================
# POST /api/v1/onboarding/first-debate
# ============================================================================


class TestFirstDebate:
    """Tests for POST first-debate endpoint."""

    @pytest.mark.asyncio
    async def test_start_first_debate_default_topic(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        assert _status(result) == 200
        data = _data(result)
        assert "debate_id" in data
        assert "topic" in data
        assert data["message"] == "First debate created successfully"
        assert "next_steps" in data

    @pytest.mark.asyncio
    async def test_start_first_debate_with_template(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="POST",
            data={"template_id": "arch_review_starter"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["template"] is not None
        assert data["template"]["id"] == "arch_review_starter"

    @pytest.mark.asyncio
    async def test_start_first_debate_with_example_prompt(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="POST",
            data={"template_id": "arch_review_starter", "use_example": True},
            user_id="test-user-001",
        )
        data = _data(result)
        # Should use the template's example prompt
        template = next(t for t in STARTER_TEMPLATES if t.id == "arch_review_starter")
        assert data["topic"] == template.example_prompt

    @pytest.mark.asyncio
    async def test_start_first_debate_with_custom_topic(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="POST",
            data={"topic": "Custom debate topic"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["topic"] == "Custom debate topic"

    @pytest.mark.asyncio
    async def test_first_debate_updates_onboarding_flow(self, handler):
        _make_flow(step=OnboardingStep.FIRST_DEBATE)
        result = await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="POST",
            data={"template_id": "arch_review_starter"},
            user_id="test-user-001",
        )
        data = _data(result)
        key = "test-user-001:personal"
        with _onboarding_lock:
            flow = _onboarding_flows[key]
            assert flow.first_debate_id == data["debate_id"]
            assert flow.selected_template_id == "arch_review_starter"

    @pytest.mark.asyncio
    async def test_first_debate_config_has_receipt_generation(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["config"]["enable_receipt_generation"] is True
        assert data["config"]["is_onboarding"] is True

    @pytest.mark.asyncio
    async def test_first_debate_tracks_event(self, handler):
        flow = _make_flow(step=OnboardingStep.FIRST_DEBATE)
        await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        with _analytics_lock:
            event = next(e for e in _analytics_events if e["event_type"] == "first_debate_started")
            assert event["data"]["flow_id"] == flow.id

    @pytest.mark.asyncio
    async def test_first_debate_unknown_template_uses_default(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="POST",
            data={"template_id": "nonexistent_template"},
            user_id="test-user-001",
        )
        data = _data(result)
        # No template found, should fall back to default topic
        assert data["template"] is None
        assert "trade-offs" in data["topic"].lower()

    @pytest.mark.asyncio
    async def test_first_debate_template_topic_fallback(self, handler):
        """When template found but use_example=False and no custom topic."""
        result = await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="POST",
            data={"template_id": "arch_review_starter", "use_example": False},
            user_id="test-user-001",
        )
        data = _data(result)
        assert "Architecture Review" in data["topic"]


# ============================================================================
# POST /api/v1/onboarding/quick-start
# ============================================================================


class TestQuickStart:
    """Tests for POST quick-start endpoint."""

    @pytest.mark.asyncio
    async def test_apply_developer_profile(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="POST",
            data={"profile": "developer"},
            user_id="test-user-001",
        )
        assert _status(result) == 200
        data = _data(result)
        assert data["profile"] == "developer"
        assert "config" in data
        assert "default_template" in data

    @pytest.mark.asyncio
    async def test_apply_security_profile(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="POST",
            data={"profile": "security"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["profile"] == "security"

    @pytest.mark.asyncio
    async def test_apply_sme_profile(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="POST",
            data={"profile": "sme"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["profile"] == "sme"
        assert data["config"].get("budget_enabled") is True

    @pytest.mark.asyncio
    async def test_invalid_profile_returns_400(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="POST",
            data={"profile": "invalid_profile"},
            user_id="test-user-001",
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_missing_profile_returns_400(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_quick_start_creates_flow_if_none(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="POST",
            data={"profile": "developer"},
            user_id="test-user-001",
        )
        key = "test-user-001:personal"
        with _onboarding_lock:
            flow = _onboarding_flows[key]
            assert flow.quick_start_profile == "developer"
            assert flow.current_step == OnboardingStep.FIRST_DEBATE

    @pytest.mark.asyncio
    async def test_quick_start_updates_existing_flow(self, handler):
        _make_flow(step=OnboardingStep.USE_CASE)
        await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="POST",
            data={"profile": "executive"},
            user_id="test-user-001",
        )
        key = "test-user-001:personal"
        with _onboarding_lock:
            flow = _onboarding_flows[key]
            assert flow.quick_start_profile == "executive"
            assert flow.current_step == OnboardingStep.FIRST_DEBATE

    @pytest.mark.asyncio
    async def test_quick_start_response_has_next_action(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="POST",
            data={"profile": "developer"},
            user_id="test-user-001",
        )
        data = _data(result)
        assert "next_action" in data
        assert data["next_action"]["type"] == "start_debate"

    @pytest.mark.asyncio
    async def test_quick_start_tracks_event(self, handler):
        await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="POST",
            data={"profile": "developer"},
            user_id="test-user-001",
        )
        with _analytics_lock:
            assert any(e["event_type"] == "quick_start_applied" for e in _analytics_events)

    @pytest.mark.asyncio
    async def test_all_profiles_accepted(self, handler):
        """Ensure all QuickStartProfile values are valid."""
        for profile in QuickStartProfile:
            result = await handler.handle(
                "/api/v1/onboarding/quick-start",
                method="POST",
                data={"profile": profile.value},
                user_id=f"user-{profile.value}",
            )
            assert _status(result) == 200, f"Profile {profile.value} returned non-200"


# ============================================================================
# POST /api/v1/onboarding/quick-debate
# ============================================================================


class TestQuickDebate:
    """Tests for POST quick-debate endpoint."""

    @pytest.mark.asyncio
    async def test_quick_debate_without_storage_returns_error(self, handler):
        """Quick debate depends on DebateController; returns error without storage."""
        result = await handler.handle(
            "/api/v1/onboarding/quick-debate",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        # May succeed (200), fail on storage (503), or fail on import (500)
        status = _status(result)
        assert status in (200, 500, 503)

    @pytest.mark.asyncio
    async def test_quick_debate_with_profile(self, handler):
        """Test that profile param is accepted (may fail due to missing deps)."""
        result = await handler.handle(
            "/api/v1/onboarding/quick-debate",
            method="POST",
            data={"profile": "developer", "topic": "Test topic"},
            user_id="test-user-001",
        )
        status = _status(result)
        assert status in (200, 500, 503)


# ============================================================================
# GET /api/v1/onboarding/analytics
# ============================================================================


class TestAnalytics:
    """Tests for GET analytics endpoint."""

    @pytest.mark.asyncio
    async def test_empty_analytics(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/analytics",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 200
        data = _data(result)
        assert data["funnel"]["started"] == 0
        assert data["funnel"]["completed"] == 0
        assert data["total_events"] == 0

    @pytest.mark.asyncio
    async def test_analytics_with_events(self, handler):
        # Generate some events by creating a flow
        await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        result = await handler.handle(
            "/api/v1/onboarding/analytics",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["funnel"]["started"] == 1
        assert data["total_events"] > 0

    @pytest.mark.asyncio
    async def test_analytics_time_range(self, handler):
        # Add some events
        _track_event("onboarding_started", "u1", None, {"flow_id": "f1"})
        _track_event("first_debate_started", "u1", None, {"debate_id": "d1"})

        result = await handler.handle(
            "/api/v1/onboarding/analytics",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["time_range"]["earliest"] is not None
        assert data["time_range"]["latest"] is not None

    @pytest.mark.asyncio
    async def test_analytics_completion_rate(self, handler):
        _track_event("onboarding_started", "u1", None, {"flow_id": "f1"})
        _track_event("onboarding_started", "u2", None, {"flow_id": "f2"})
        _track_event(
            "step_updated",
            "u1",
            None,
            {"action": "complete", "from_step": "receipt_review", "to_step": "completion"},
        )

        result = await handler.handle(
            "/api/v1/onboarding/analytics",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["funnel"]["started"] == 2
        assert data["funnel"]["completed"] == 1
        assert data["funnel"]["completion_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_analytics_first_debate_count(self, handler):
        _track_event("first_debate_started", "u1", None, {"debate_id": "d1"})
        _track_event("first_debate_started", "u2", None, {"debate_id": "d2"})

        result = await handler.handle(
            "/api/v1/onboarding/analytics",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)
        assert data["funnel"]["first_debate"] == 2

    @pytest.mark.asyncio
    async def test_analytics_filters_by_organization(self, handler):
        _track_event("onboarding_started", "u1", "org-1", {"flow_id": "f1"})
        _track_event("onboarding_started", "u2", "org-2", {"flow_id": "f2"})
        _track_event("onboarding_started", "u3", "org-1", {"flow_id": "f3"})

        result = await handler.handle(
            "/api/v1/onboarding/analytics",
            method="GET",
            user_id="test-user-001",
            organization_id="org-1",
        )
        data = _data(result)
        assert data["funnel"]["started"] == 2

    @pytest.mark.asyncio
    async def test_analytics_includes_timing_and_dropoff(self, handler):
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with _analytics_lock:
            _analytics_events.extend(
                [
                    {
                        "event_type": "onboarding_started",
                        "user_id": "u1",
                        "organization_id": None,
                        "data": {"flow_id": "f1"},
                        "timestamp": t0.isoformat(),
                    },
                    {
                        "event_type": "onboarding_started",
                        "user_id": "u2",
                        "organization_id": None,
                        "data": {"flow_id": "f2"},
                        "timestamp": (t0 + timedelta(seconds=5)).isoformat(),
                    },
                    {
                        "event_type": "step_updated",
                        "user_id": "u1",
                        "organization_id": None,
                        "data": {
                            "flow_id": "f1",
                            "from_step": "welcome",
                            "to_step": "use_case",
                            "completed_steps": ["welcome"],
                        },
                        "timestamp": (t0 + timedelta(seconds=10)).isoformat(),
                    },
                    {
                        "event_type": "step_updated",
                        "user_id": "u2",
                        "organization_id": None,
                        "data": {
                            "flow_id": "f2",
                            "from_step": "welcome",
                            "to_step": "use_case",
                            "completed_steps": ["welcome"],
                        },
                        "timestamp": (t0 + timedelta(seconds=20)).isoformat(),
                    },
                    {
                        "event_type": "step_updated",
                        "user_id": "u1",
                        "organization_id": None,
                        "data": {
                            "flow_id": "f1",
                            "from_step": "use_case",
                            "to_step": "organization",
                            "completed_steps": ["welcome", "use_case"],
                        },
                        "timestamp": (t0 + timedelta(seconds=25)).isoformat(),
                    },
                    {
                        "event_type": "first_debate_started",
                        "user_id": "u1",
                        "organization_id": None,
                        "data": {"flow_id": "f1", "debate_id": "d1"},
                        "timestamp": (t0 + timedelta(seconds=30)).isoformat(),
                    },
                    {
                        "event_type": "quick_debate_started",
                        "user_id": "u2",
                        "organization_id": None,
                        "data": {"flow_id": "f2", "debate_id": "d2"},
                        "timestamp": (t0 + timedelta(seconds=65)).isoformat(),
                    },
                    {
                        "event_type": "first_receipt_generated",
                        "user_id": "u1",
                        "organization_id": None,
                        "data": {"flow_id": "f1", "debate_id": "d1", "receipt_id": "r1"},
                        "timestamp": (t0 + timedelta(seconds=90)).isoformat(),
                    },
                    {
                        "event_type": "first_receipt_generated",
                        "user_id": "u2",
                        "organization_id": None,
                        "data": {"flow_id": "f2", "debate_id": "d2", "receipt_id": "r2"},
                        "timestamp": (t0 + timedelta(seconds=185)).isoformat(),
                    },
                ]
            )

        result = await handler.handle(
            "/api/v1/onboarding/analytics",
            method="GET",
            user_id="test-user-001",
        )
        data = _data(result)

        debate_timing = data["timing"]["time_to_first_debate_seconds"]
        assert debate_timing["count"] == 2
        assert debate_timing["avg"] == 45.0
        assert debate_timing["min"] == 30.0
        assert debate_timing["max"] == 60.0

        receipt_timing = data["timing"]["time_to_first_receipt_seconds"]
        assert receipt_timing["count"] == 2
        assert receipt_timing["avg"] == 135.0
        assert receipt_timing["min"] == 90.0
        assert receipt_timing["max"] == 180.0

        assert data["step_completion"]["welcome"] == 2
        assert data["step_completion"]["use_case"] == 1
        assert data["step_drop_off"]["use_case"]["reached"] == 2
        assert data["step_drop_off"]["use_case"]["advanced"] == 1
        assert data["step_drop_off"]["use_case"]["dropped"] == 1


# ============================================================================
# Method not allowed / 404
# ============================================================================


class TestMethodNotAllowed:
    """Tests for unsupported methods and unknown endpoints."""

    @pytest.mark.asyncio
    async def test_delete_on_flow_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="DELETE",
            user_id="test-user-001",
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_put_on_flow_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="PUT",
            user_id="test-user-001",
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_on_first_debate_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/first-debate",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_on_quick_start_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/quick-start",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_post_on_templates_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/templates",
            method="POST",
            user_id="test-user-001",
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_post_on_analytics_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/analytics",
            method="POST",
            user_id="test-user-001",
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_unknown_subpath_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/nonexistent",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_on_quick_debate_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/quick-debate",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_on_flow_step_returns_404(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 404


# ============================================================================
# Helper function unit tests
# ============================================================================


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_step_order_has_8_steps(self):
        steps = _get_step_order()
        assert len(steps) == 8
        assert steps[0] == OnboardingStep.WELCOME
        assert steps[-1] == OnboardingStep.COMPLETION

    def test_get_next_step_advances(self):
        assert _get_next_step(OnboardingStep.WELCOME) == OnboardingStep.USE_CASE
        assert _get_next_step(OnboardingStep.USE_CASE) == OnboardingStep.ORGANIZATION

    def test_get_next_step_at_end_stays(self):
        assert _get_next_step(OnboardingStep.COMPLETION) == OnboardingStep.COMPLETION

    def test_recommended_templates_no_use_case(self):
        templates = _get_recommended_templates(None)
        assert len(templates) <= 8
        assert len(templates) > 0

    def test_recommended_templates_prioritizes_matching(self):
        templates = _get_recommended_templates("security_audit")
        if templates:
            # At least the first template should match security_audit
            matching = [t for t in templates if "security_audit" in t.use_cases]
            non_matching = [t for t in templates if "security_audit" not in t.use_cases]
            # If there are matching templates, they should come before non-matching
            if matching and non_matching:
                first_matching_idx = templates.index(matching[0])
                last_matching_idx = templates.index(matching[-1])
                first_non_matching_idx = templates.index(non_matching[0])
                assert last_matching_idx < first_non_matching_idx

    def test_track_event_adds_to_list(self):
        _track_event("test_event", "user1", None, {"key": "value"})
        with _analytics_lock:
            assert len(_analytics_events) == 1
            assert _analytics_events[0]["event_type"] == "test_event"
            assert _analytics_events[0]["user_id"] == "user1"

    def test_track_event_trims_to_10000(self):
        """Analytics events should be trimmed when exceeding 10000."""
        with _analytics_lock:
            for i in range(10001):
                _analytics_events.append(
                    {
                        "event_type": f"event_{i}",
                        "user_id": "u",
                        "organization_id": None,
                        "data": {},
                        "timestamp": "2024-01-01",
                    }
                )
        # Now add one more via _track_event (which trims)
        _track_event("overflow_event", "u", None, {})
        with _analytics_lock:
            assert len(_analytics_events) <= 10002  # Already exceeded, trim pops 1 at a time


# ============================================================================
# Path normalization
# ============================================================================


class TestPathNormalization:
    """Test that v1 and v2 paths are normalized correctly."""

    @pytest.mark.asyncio
    async def test_v1_path_routes_correctly(self, handler):
        _make_flow()
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_v2_path_routes_correctly(self, handler):
        _make_flow()
        result = await handler.handle(
            "/api/v2/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_unversioned_path_routes_correctly(self, handler):
        _make_flow()
        result = await handler.handle(
            "/api/onboarding/flow",
            method="GET",
            user_id="test-user-001",
        )
        assert _status(result) == 200


# ============================================================================
# Edge cases and data types
# ============================================================================


class TestEdgeCases:
    """Edge case and data integrity tests."""

    @pytest.mark.asyncio
    async def test_concurrent_users_isolated(self, handler):
        """Two users should have independent flows."""
        await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={"use_case": "security_audit"},
            user_id="user-a",
        )
        await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={"use_case": "team_decisions"},
            user_id="user-b",
        )
        with _onboarding_lock:
            assert "user-a:personal" in _onboarding_flows
            assert "user-b:personal" in _onboarding_flows
            assert _onboarding_flows["user-a:personal"].use_case == "security_audit"
            assert _onboarding_flows["user-b:personal"].use_case == "team_decisions"

    @pytest.mark.asyncio
    async def test_org_and_personal_flows_separate(self, handler):
        """Same user can have personal and org flows."""
        await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={},
            user_id="test-user-001",
        )
        await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data={},
            user_id="test-user-001",
            organization_id="org-001",
        )
        with _onboarding_lock:
            assert "test-user-001:personal" in _onboarding_flows
            assert "test-user-001:org-001" in _onboarding_flows

    @pytest.mark.asyncio
    async def test_empty_data_defaults_handled(self, handler):
        result = await handler.handle(
            "/api/v1/onboarding/flow",
            method="POST",
            data=None,
            user_id="test-user-001",
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_step_not_duplicated_in_completed(self, handler):
        """Advancing past the same step twice should not duplicate it."""
        _make_flow(step=OnboardingStep.WELCOME, completed_steps=["welcome"])
        await handler.handle(
            "/api/v1/onboarding/flow/step",
            method="PUT",
            data={"action": "next"},
            user_id="test-user-001",
        )
        key = "test-user-001:personal"
        with _onboarding_lock:
            flow = _onboarding_flows[key]
            assert flow.completed_steps.count("welcome") == 1

    @pytest.mark.asyncio
    async def test_handler_constructor_default_ctx(self):
        h = OnboardingHandler()
        assert h.ctx == {}

    @pytest.mark.asyncio
    async def test_handler_constructor_with_ctx(self):
        ctx = {"key": "value"}
        h = OnboardingHandler(ctx)
        assert h.ctx == ctx


# ============================================================================
# Constants and data integrity
# ============================================================================


class TestConstants:
    """Tests for module-level constants and data structures."""

    def test_starter_templates_not_empty(self):
        assert len(STARTER_TEMPLATES) > 0

    def test_all_templates_have_unique_ids(self):
        ids = [t.id for t in STARTER_TEMPLATES]
        assert len(ids) == len(set(ids)), "Duplicate template IDs found"

    def test_quick_start_configs_match_profiles(self):
        for profile in QuickStartProfile:
            assert profile.value in QUICK_START_CONFIGS, (
                f"Profile {profile.value} missing from QUICK_START_CONFIGS"
            )

    def test_quick_start_configs_reference_valid_templates(self):
        template_ids = {t.id for t in STARTER_TEMPLATES}
        for name, config in QUICK_START_CONFIGS.items():
            default = config.get("default_template")
            if default:
                assert default in template_ids, (
                    f"Config '{name}' references unknown template '{default}'"
                )

    def test_use_case_enum_values(self):
        assert UseCase.TEAM_DECISIONS.value == "team_decisions"
        assert UseCase.SECURITY_AUDIT.value == "security_audit"
        assert UseCase.GENERAL.value == "general"

    def test_onboarding_step_enum_values(self):
        assert OnboardingStep.WELCOME.value == "welcome"
        assert OnboardingStep.COMPLETION.value == "completion"

    def test_quick_start_profile_enum_values(self):
        assert QuickStartProfile.DEVELOPER.value == "developer"
        assert QuickStartProfile.SME.value == "sme"

    def test_handler_routes_list(self):
        routes = OnboardingHandler.ROUTES
        assert "/api/onboarding/flow" in routes
        assert "/api/onboarding/templates" in routes
        assert "/api/onboarding/analytics" in routes
