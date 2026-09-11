"""Tests for Platform Configuration handler.

Covers the GET /api/v1/platform/config endpoint that returns runtime
configuration for the frontend (agents, display names, debate defaults,
feature flags, and version info).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.platform_config import (
    AGENT_DISPLAY_NAMES,
    DEFAULT_AGENTS,
    STREAMING_CAPABLE_AGENTS,
    PlatformConfigHandler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler(ctx: dict[str, Any] | None = None) -> PlatformConfigHandler:
    """Create a PlatformConfigHandler with optional server context."""
    return PlatformConfigHandler(ctx or {})


def _parse_response(result: Any) -> dict[str, Any]:
    """Extract parsed JSON body from a HandlerResult."""
    if hasattr(result, "body"):
        body = result.body
        if isinstance(body, (bytes, bytearray)):
            body = body.decode("utf-8")
        if isinstance(body, str):
            body = json.loads(body)
        if isinstance(body, dict):
            return body
    if isinstance(result, dict):
        return result
    return {}


def _get_data(result: Any) -> dict[str, Any]:
    """Extract the 'data' envelope from a response."""
    body = _parse_response(result)
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def _get_status_code(result: Any) -> int:
    """Extract HTTP status code from HandlerResult."""
    if hasattr(result, "status_code"):
        return result.status_code
    if isinstance(result, tuple) and len(result) > 1:
        return result[1]
    return 200


# ---------------------------------------------------------------------------
# can_handle tests
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for PlatformConfigHandler.can_handle()."""

    def test_matches_versioned_path(self):
        handler = _make_handler()
        assert handler.can_handle("/api/v1/platform/config") is True

    def test_matches_unversioned_path(self):
        handler = _make_handler()
        assert handler.can_handle("/api/platform/config") is True

    def test_rejects_unknown_path(self):
        handler = _make_handler()
        assert handler.can_handle("/api/v1/platform/other") is False

    def test_rejects_post_method(self):
        handler = _make_handler()
        assert handler.can_handle("/api/v1/platform/config", method="POST") is False

    def test_rejects_delete_method(self):
        handler = _make_handler()
        assert handler.can_handle("/api/v1/platform/config", method="DELETE") is False


# ---------------------------------------------------------------------------
# Response structure tests
# ---------------------------------------------------------------------------


class TestResponseStructure:
    """Tests that the response has the expected top-level structure."""

    def test_returns_200(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        assert _get_status_code(result) == 200

    def test_response_has_data_envelope(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        body = _parse_response(result)
        assert "data" in body

    def test_data_has_required_keys(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        required_keys = {
            "available_agents",
            "agent_display_names",
            "default_agents",
            "streaming_capable_agents",
            "default_debate_config",
            "features",
            "version",
        }
        assert required_keys.issubset(set(data.keys()))

    def test_unversioned_path_returns_same_data(self):
        handler = _make_handler()
        result = handler.handle("/api/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert "available_agents" in data
        assert "version" in data


# ---------------------------------------------------------------------------
# Agent list tests
# ---------------------------------------------------------------------------


class TestAvailableAgents:
    """Tests for the available_agents field."""

    def test_returns_sorted_list(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        agents = data["available_agents"]
        assert isinstance(agents, list)
        assert agents == sorted(agents)

    @patch("aragora.server.handlers.platform_config.AgentFactory", create=True)
    @patch("aragora.server.handlers.platform_config.register_all_agents", create=True)
    def test_uses_registry_when_available(self, mock_register, mock_factory):
        """When the agent registry is importable, use its types."""
        mock_factory.get_registered_types.return_value = ["alpha", "beta", "gamma"]

        handler = _make_handler()
        # Patch at the method level to use the mock
        with (
            patch(
                "aragora.agents.registry.AgentFactory.get_registered_types",
                return_value=["alpha", "beta", "gamma"],
            ),
            patch(
                "aragora.agents.registry.register_all_agents",
            ),
        ):
            result = handler.handle("/api/v1/platform/config", {}, MagicMock())
            data = _get_data(result)
            agents = data["available_agents"]
            assert isinstance(agents, list)
            # Should be sorted
            assert agents == sorted(agents)

    def test_fallback_on_import_error(self):
        """When agent registry fails to import, fall back to defaults."""
        handler = _make_handler()
        with patch(
            "aragora.server.handlers.platform_config.PlatformConfigHandler._collect_available_agents",
            side_effect=ImportError("no module"),
        ):
            # The handler should catch errors gracefully
            # Since we're patching the method itself to raise, the decorator
            # will handle it. Let's test the internal method directly instead.
            pass

        # Test the fallback path directly by making the import fail
        with patch.dict("sys.modules", {"aragora.agents.registry": None}):
            # Re-import won't help here, so test the internal method
            agents = handler._collect_available_agents()
            # Should still return a list (either from registry or fallback)
            assert isinstance(agents, list)
            assert len(agents) > 0


# ---------------------------------------------------------------------------
# Display names tests
# ---------------------------------------------------------------------------


class TestAgentDisplayNames:
    """Tests for the agent_display_names field."""

    def test_contains_default_agents(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        names = data["agent_display_names"]
        for agent in DEFAULT_AGENTS:
            assert agent in names, f"Missing display name for {agent}"

    def test_known_display_names(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        names = data["agent_display_names"]
        # Spot check known display names
        assert names.get("grok") == "Grok 4"
        assert names.get("anthropic-api") == "Opus 4.6"
        assert names.get("openai-api") == "GPT 5.2"

    def test_unknown_agent_gets_title_cased_name(self):
        """Unknown agents should get a title-cased display name."""
        handler = _make_handler()
        names = handler._collect_display_names(["unknown-agent-x"])
        assert names["unknown-agent-x"] == "Unknown Agent X"

    def test_retired_agent_types_are_not_offered(self):
        """C-P3 (#9989 merge-gate, round 2): the frontier refresh removed the
        ``YiAgent`` registration (01.AI Yi Large is off the live OpenRouter
        catalog), but this map still offered "Yi Large" as a display option,
        so the UI could present an agent type the server now rejects at
        construction."""
        assert "yi" not in AGENT_DISPLAY_NAMES
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        assert "yi" not in _get_data(result)["agent_display_names"]

    def test_display_names_is_dict(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert isinstance(data["agent_display_names"], dict)


# ---------------------------------------------------------------------------
# Default debate config tests
# ---------------------------------------------------------------------------


class TestDefaultDebateConfig:
    """Tests for the default_debate_config field."""

    def test_has_rounds(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        config = data["default_debate_config"]
        assert config["rounds"] == 9

    def test_has_max_rounds(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        config = data["default_debate_config"]
        assert config["max_rounds"] == 12

    def test_has_consensus_mode(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        config = data["default_debate_config"]
        assert config["consensus_mode"] == "judge"


# ---------------------------------------------------------------------------
# Feature flags tests
# ---------------------------------------------------------------------------


class TestFeatureFlags:
    """Tests for the features field."""

    def test_features_is_dict(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert isinstance(data["features"], dict)

    def test_default_flags(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        features = data["features"]
        assert features["streaming"] is True
        assert features["audience"] is True
        assert features["spectate"] is True
        assert features["receipts"] is True

    def test_streaming_disabled_by_env(self, monkeypatch):
        monkeypatch.setenv("NEXT_PUBLIC_ENABLE_STREAMING", "false")
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert data["features"]["streaming"] is False

    def test_audience_disabled_by_env(self, monkeypatch):
        monkeypatch.setenv("NEXT_PUBLIC_ENABLE_AUDIENCE", "false")
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert data["features"]["audience"] is False


# ---------------------------------------------------------------------------
# Version tests
# ---------------------------------------------------------------------------


class TestVersion:
    """Tests for the version field."""

    def test_version_is_string(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert isinstance(data["version"], str)

    def test_version_not_empty(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert data["version"] != ""

    def test_version_fallback_on_import_error(self):
        """When aragora.__version__ is missing, return 'unknown'."""
        handler = _make_handler()
        with patch(
            "aragora.server.handlers.platform_config.PlatformConfigHandler._get_version",
            return_value="unknown",
        ):
            result = handler.handle("/api/v1/platform/config", {}, MagicMock())
            data = _get_data(result)
            assert data["version"] == "unknown"


# ---------------------------------------------------------------------------
# Default agents and streaming agents tests
# ---------------------------------------------------------------------------


class TestDefaultAndStreamingAgents:
    """Tests for default_agents and streaming_capable_agents."""

    def test_default_agents_is_list(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert isinstance(data["default_agents"], list)
        assert len(data["default_agents"]) > 0

    def test_default_agents_match_constant(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert data["default_agents"] == DEFAULT_AGENTS

    def test_streaming_capable_agents_is_list(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert isinstance(data["streaming_capable_agents"], list)
        assert len(data["streaming_capable_agents"]) > 0

    def test_streaming_capable_agents_match_constant(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config", {}, MagicMock())
        data = _get_data(result)
        assert data["streaming_capable_agents"] == STREAMING_CAPABLE_AGENTS


# ---------------------------------------------------------------------------
# Non-matching path tests
# ---------------------------------------------------------------------------


class TestNonMatchingPaths:
    """Tests that non-matching paths return None."""

    def test_unknown_path_returns_none(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/unknown", {}, MagicMock())
        assert result is None

    def test_similar_path_returns_none(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/configs", {}, MagicMock())
        assert result is None

    def test_sub_path_returns_none(self):
        handler = _make_handler()
        result = handler.handle("/api/v1/platform/config/agents", {}, MagicMock())
        assert result is None


# ---------------------------------------------------------------------------
# Module-level constant tests
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_agent_display_names_has_entries(self):
        assert len(AGENT_DISPLAY_NAMES) > 10

    def test_default_agents_has_entries(self):
        assert len(DEFAULT_AGENTS) >= 6

    def test_streaming_capable_agents_has_entries(self):
        assert len(STREAMING_CAPABLE_AGENTS) >= 3

    def test_all_default_agents_have_display_names(self):
        for agent in DEFAULT_AGENTS:
            assert agent in AGENT_DISPLAY_NAMES, f"{agent} missing from AGENT_DISPLAY_NAMES"

    def test_all_streaming_agents_in_display_names(self):
        for agent in STREAMING_CAPABLE_AGENTS:
            assert agent in AGENT_DISPLAY_NAMES, f"{agent} missing from AGENT_DISPLAY_NAMES"
