"""Tests for marketplace-to-debate launch functionality.

Covers:
- MarketplaceService.launch_debate_from_listing (valid listing, invalid listing)
- TeamSelector.resolve_agents_from_template
- MarketplacePilotHandler POST .../launch-debate endpoint
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from aragora.marketplace.catalog import MarketplaceCatalog
from aragora.marketplace.service import MarketplaceService
from aragora.server.handlers.marketplace_pilot import MarketplacePilotHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog():
    """Create a seeded MarketplaceCatalog."""
    return MarketplaceCatalog(seed=True)


@pytest.fixture
def service(catalog):
    """Create a MarketplaceService with seed data."""
    return MarketplaceService(catalog=catalog)


@pytest.fixture
def handler(service):
    """Create a MarketplacePilotHandler with injected service."""
    ctx: dict = {"storage": MagicMock()}
    h = MarketplacePilotHandler(ctx)
    h._service = service
    return h


def _make_body_handler(body: dict) -> MagicMock:
    """Create an authed mock handler with a JSON body."""
    raw = json.dumps(body).encode()
    h = MagicMock()
    h.client_address = ("127.0.0.1", 54321)
    h.headers = {
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
        "Authorization": "Bearer test-token",
    }
    h.rfile = BytesIO(raw)
    return h


def _parse_data(result):
    """Unwrap the ``{"data": ...}`` envelope from a HandlerResult."""
    assert result is not None
    body = result[0]
    if isinstance(body, dict):
        return body.get("data", body)
    return body


# ===========================================================================
# MarketplaceService.launch_debate_from_listing
# ===========================================================================


class TestLaunchDebateFromListing:
    """Tests for MarketplaceService.launch_debate_from_listing."""

    def test_valid_listing_returns_config(self, service):
        """Launching with a known catalog item produces a debate config."""
        result = service.launch_debate_from_listing(
            item_id="tpl-code-review",
            question="Is this code secure?",
            user_id="user-42",
        )

        assert "debate_id" in result
        assert result["debate_id"].startswith("mkt-")
        assert result["template_used"] == "tpl-code-review"
        assert "config" in result

        config = result["config"]
        assert config["question"] == "Is this code secure?"
        assert config["user_id"] == "user-42"
        assert config["source_listing"] == "tpl-code-review"
        assert isinstance(config["rounds"], int)
        assert config["rounds"] >= 1

    def test_rounds_override(self, service):
        """Explicit rounds_override takes precedence over template default."""
        result = service.launch_debate_from_listing(
            item_id="tpl-code-review",
            question="Review this PR",
            rounds_override=7,
        )
        assert result["config"]["rounds"] == 7

    def test_invalid_listing_raises_key_error(self, service):
        """A non-existent item_id raises KeyError."""
        with pytest.raises(KeyError, match="not-a-real-item"):
            service.launch_debate_from_listing(
                item_id="not-a-real-item",
                question="Does not matter",
            )

    def test_default_user_id(self, service):
        """Without explicit user_id, defaults to 'anonymous'."""
        result = service.launch_debate_from_listing(
            item_id="tpl-brainstorm",
            question="Brainstorm ideas",
        )
        assert result["config"]["user_id"] == "anonymous"

    def test_consensus_mode_present(self, service):
        """Config always includes a consensus_mode."""
        result = service.launch_debate_from_listing(
            item_id="tpl-risk-assessment",
            question="Evaluate risk",
        )
        assert "consensus_mode" in result["config"]

    def test_debate_ids_are_unique(self, service):
        """Each call generates a unique debate_id."""
        r1 = service.launch_debate_from_listing("tpl-brainstorm", "Q1")
        r2 = service.launch_debate_from_listing("tpl-brainstorm", "Q2")
        assert r1["debate_id"] != r2["debate_id"]


# ===========================================================================
# TeamSelector.resolve_agents_from_template
# ===========================================================================


class TestResolveAgentsFromTemplate:
    """Tests for TeamSelector.resolve_agents_from_template."""

    def _make_selector(self, registry=None):
        """Create a minimal TeamSelector with an optional mock registry."""
        from aragora.debate.team_selector import TeamSelector

        return TeamSelector(marketplace_registry=registry)

    def test_returns_role_agent_dicts(self):
        """Returns a list of {role, agent} dicts when template has roles."""
        # Mock registry that returns a DebateTemplate-like object
        from aragora.marketplace.models import (
            BUILTIN_DEBATE_TEMPLATES,
            DebateTemplate,
        )

        tpl = BUILTIN_DEBATE_TEMPLATES[0]  # oxford-style

        registry = MagicMock()
        registry.get.return_value = tpl

        selector = self._make_selector(registry=registry)
        result = selector.resolve_agents_from_template("oxford-style")

        assert len(result) > 0
        for entry in result:
            assert "role" in entry
            assert "agent" in entry
            assert isinstance(entry["role"], str)
            assert isinstance(entry["agent"], str)

    def test_unknown_template_returns_empty(self):
        """Unknown template name yields empty list."""
        registry = MagicMock()
        registry.get.return_value = None

        selector = self._make_selector(registry=registry)
        result = selector.resolve_agents_from_template("nonexistent-template")
        assert result == []

    def test_respects_available_agents(self):
        """When available_agents is provided, agents are constrained."""
        from aragora.marketplace.models import BUILTIN_DEBATE_TEMPLATES

        tpl = BUILTIN_DEBATE_TEMPLATES[2]  # code-review-session

        registry = MagicMock()
        registry.get.return_value = tpl

        selector = self._make_selector(registry=registry)
        result = selector.resolve_agents_from_template(
            "code-review-session",
            available_agents=["gemini", "gpt"],
        )

        assert len(result) > 0
        for entry in result:
            assert entry["agent"] in ("gemini", "gpt")

    def test_empty_template_name(self):
        """Empty string template name returns empty list."""
        selector = self._make_selector()
        result = selector.resolve_agents_from_template("")
        assert result == []


# ===========================================================================
# Handler: POST /api/v1/marketplace/listings/{id}/launch-debate
# ===========================================================================


class TestLaunchDebateHandler:
    """Tests for the launch-debate endpoint via MarketplacePilotHandler."""

    def test_launch_debate_success(self, handler):
        """Successful launch returns debate config in data envelope."""
        mock_http = _make_body_handler({"question": "Is this architecture sound?", "rounds": 3})
        # Bypass auth
        handler.require_auth_or_error = MagicMock(return_value=(MagicMock(user_id="u1"), None))

        result = handler.handle_post(
            "/api/v1/marketplace/listings/tpl-code-review/launch-debate",
            {},
            mock_http,
        )

        data = _parse_data(result)
        assert data is not None
        assert "debate_id" in data
        assert data["template_used"] == "tpl-code-review"
        assert data["config"]["question"] == "Is this architecture sound?"

    def test_launch_debate_missing_question(self, handler):
        """Missing question returns 400."""
        mock_http = _make_body_handler({"rounds": 3})
        handler.require_auth_or_error = MagicMock(return_value=(MagicMock(user_id="u1"), None))

        result = handler.handle_post(
            "/api/v1/marketplace/listings/tpl-code-review/launch-debate",
            {},
            mock_http,
        )

        assert result is not None
        # Status code is second element
        assert result[1] == 400

    def test_launch_debate_invalid_item(self, handler):
        """Non-existent listing returns 404."""
        mock_http = _make_body_handler({"question": "Test?"})
        handler.require_auth_or_error = MagicMock(return_value=(MagicMock(user_id="u1"), None))

        result = handler.handle_post(
            "/api/v1/marketplace/listings/nonexistent-item-id/launch-debate",
            {},
            mock_http,
        )

        assert result is not None
        assert result[1] == 404

    def test_launch_debate_invalid_rounds(self, handler):
        """Rounds out of range returns 400."""
        mock_http = _make_body_handler({"question": "Test?", "rounds": 999})
        handler.require_auth_or_error = MagicMock(return_value=(MagicMock(user_id="u1"), None))

        result = handler.handle_post(
            "/api/v1/marketplace/listings/tpl-code-review/launch-debate",
            {},
            mock_http,
        )

        assert result is not None
        assert result[1] == 400
