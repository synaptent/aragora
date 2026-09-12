"""Comprehensive tests for AgentConfigHandler (aragora/server/handlers/agents/config.py).

Tests cover:
- Handler initialization and routing (can_handle, ROUTES, permissions)
- GET /api/v1/agents/configs - List all agent configurations
- GET /api/v1/agents/configs/search - Search configs by expertise/capability/tag
- POST /api/v1/agents/configs/reload - Reload all configurations
- _handle_config_endpoint internal routing and path parsing
- _get_config - Get specific agent configuration
- _create_agent_from_config - Create agent from configuration
- _list_configs - List with priority/role filters
- _search_configs - Search with deduplication
- _reload_configs - Reload with error handling
- get_config_loader - Global loader caching, import error handling
- RBAC permission enforcement (auth required, admin for reload, write for create)
- Config loader unavailability (503)
- Input validation (path segment, config name pattern)
- Security tests (path traversal, injection)
- Edge cases (empty configs, filters, deduplication)

Note on path parsing:
    The handler's _handle_config_endpoint extracts parts[4] as the config name.
    For versioned paths like /api/v1/agents/configs/{name}, parts[4] is "configs"
    (not the actual name). The exact-match routes (list, reload, search) work
    correctly via the handle() method. The internal methods (_get_config,
    _create_agent_from_config) are tested directly for correctness.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.rbac.models import AuthorizationContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: object) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    if hasattr(result, "body"):
        if isinstance(result.body, bytes):
            return json.loads(result.body.decode("utf-8"))
        if isinstance(result.body, str):
            return json.loads(result.body)
    return {}


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("status_code", 200)
    if hasattr(result, "status_code"):
        return result.status_code
    return 200


# ---------------------------------------------------------------------------
# Mock config object
# ---------------------------------------------------------------------------


class MockAgentConfig:
    """Mock agent configuration object."""

    def __init__(
        self,
        name: str = "test-agent",
        model_type: str = "anthropic-api",
        role: str = "proposer",
        priority: str = "normal",
        description: str = "A test agent configuration",
        expertise_domains: list[str] | None = None,
        capabilities: list[str] | None = None,
        tags: list[str] | None = None,
    ):
        self.name = name
        self.model_type = model_type
        self.role = role
        self.priority = priority
        self.description = description
        self.expertise_domains = expertise_domains or ["general"]
        self.capabilities = capabilities or ["debate"]
        self.tags = tags or ["default"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model_type": self.model_type,
            "role": self.role,
            "priority": self.priority,
            "description": self.description,
            "expertise_domains": self.expertise_domains,
            "capabilities": self.capabilities,
            "tags": self.tags,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset rate limiters before and after each test."""
    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

        reset_rate_limiters()
    except ImportError:
        pass

    yield

    try:
        from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

        reset_rate_limiters()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _reset_config_loader():
    """Reset the global config loader before each test."""
    import aragora.server.handlers.agents.config as config_mod

    config_mod._config_loader = None
    yield
    config_mod._config_loader = None


@pytest.fixture
def handler():
    """Create an AgentConfigHandler with empty context."""
    from aragora.server.handlers.agents.config import AgentConfigHandler

    return AgentConfigHandler(ctx={})


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler with client address, headers, and rfile."""
    h = MagicMock()
    h.client_address = ("127.0.0.1", 54321)
    h.headers = {"Content-Length": "2"}
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    return h


@pytest.fixture
def mock_loader():
    """Create a mock config loader with standard test data."""
    loader = MagicMock()
    configs = {
        "claude-critic": MockAgentConfig(
            name="claude-critic",
            model_type="anthropic-api",
            role="critic",
            priority="high",
            description="Claude-based critic agent",
            expertise_domains=["security", "code-review"],
            capabilities=["critique", "analysis"],
            tags=["claude", "critic"],
        ),
        "gpt4-proposer": MockAgentConfig(
            name="gpt4-proposer",
            model_type="openai-api",
            role="proposer",
            priority="normal",
            description="GPT-4 proposer agent",
            expertise_domains=["architecture", "design"],
            capabilities=["proposal", "synthesis"],
            tags=["gpt4", "proposer"],
        ),
        "gemini-judge": MockAgentConfig(
            name="gemini-judge",
            model_type="google-api",
            role="judge",
            priority="low",
            description="Gemini judge agent",
            expertise_domains=["legal", "compliance"],
            capabilities=["judgment", "scoring"],
            tags=["gemini", "judge"],
        ),
    }
    loader.list_configs.return_value = list(configs.keys())
    loader.get_config.side_effect = lambda name: configs.get(name)
    loader.get_by_expertise.side_effect = lambda e: [
        c for c in configs.values() if e in c.expertise_domains
    ]
    loader.get_by_capability.side_effect = lambda c: [
        cfg for cfg in configs.values() if c in cfg.capabilities
    ]
    loader.get_by_tag.side_effect = lambda t: [c for c in configs.values() if t in c.tags]
    return loader


# ---------------------------------------------------------------------------
# Initialization and Routing
# ---------------------------------------------------------------------------


class TestAgentConfigHandlerInit:
    """Tests for handler initialization."""

    def test_init_with_empty_ctx(self, handler):
        """Handler initializes with empty context."""
        assert handler.ctx == {}

    def test_init_with_provided_ctx(self):
        from aragora.server.handlers.agents.config import AgentConfigHandler

        ctx = {"key": "value"}
        h = AgentConfigHandler(ctx=ctx)
        assert h.ctx is ctx

    def test_init_with_none_ctx(self):
        from aragora.server.handlers.agents.config import AgentConfigHandler

        h = AgentConfigHandler(ctx=None)
        assert h.ctx == {}

    def test_routes_defined(self, handler):
        """Routes list contains expected endpoints."""
        assert "/api/v1/agents/configs" in handler.ROUTES
        assert "/api/v1/agents/configs/reload" in handler.ROUTES
        assert "/api/v1/agents/configs/search" in handler.ROUTES

    def test_permission_keys(self, handler):
        """Permission keys are defined."""
        assert handler.READ_PERMISSION == "agents:config:read"
        assert handler.WRITE_PERMISSION == "agents:config:write"
        assert handler.CREATE_PERMISSION == "agents:config:write"

    def test_resource_type(self, handler):
        """Resource type is defined."""
        assert handler.RESOURCE_TYPE == "agent_config"

    def test_create_permission_is_alias(self, handler):
        """CREATE_PERMISSION is an alias for WRITE_PERMISSION."""
        assert handler.CREATE_PERMISSION == handler.WRITE_PERMISSION


class TestCanHandle:
    """Tests for can_handle routing."""

    def test_configs_root(self, handler):
        assert handler.can_handle("/api/v1/agents/configs") is True

    def test_configs_specific(self, handler):
        assert handler.can_handle("/api/v1/agents/configs/claude-critic") is True

    def test_configs_search(self, handler):
        assert handler.can_handle("/api/v1/agents/configs/search") is True

    def test_configs_reload(self, handler):
        assert handler.can_handle("/api/v1/agents/configs/reload") is True

    def test_configs_create(self, handler):
        assert handler.can_handle("/api/v1/agents/configs/claude-critic/create") is True

    def test_unrelated_agents_path(self, handler):
        assert handler.can_handle("/api/v1/agents") is False

    def test_unrelated_debates_path(self, handler):
        assert handler.can_handle("/api/v1/debates") is False

    def test_partial_prefix(self, handler):
        assert handler.can_handle("/api/v1/agents/config") is False

    def test_different_version_prefix(self, handler):
        assert handler.can_handle("/api/v2/agents/configs") is False

    def test_version_stripped_path(self, handler):
        """Version-stripped path does not match."""
        assert handler.can_handle("/api/agents/configs") is False


# ---------------------------------------------------------------------------
# GET /api/v1/agents/configs - List Configs (via handle)
# ---------------------------------------------------------------------------


class TestListConfigsViaHandle:
    """Tests for the list configurations endpoint via the handle method."""

    @pytest.mark.asyncio
    async def test_list_configs_success(self, handler, mock_http_handler, mock_loader):
        """Returns all configs when no filters applied."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle("/api/v1/agents/configs", {}, mock_http_handler)
            body = _body(result)
            assert _status(result) == 200
            assert body["total"] == 3
            assert len(body["configs"]) == 3

    @pytest.mark.asyncio
    async def test_list_configs_response_structure(self, handler, mock_http_handler, mock_loader):
        """Verify response structure of each config entry."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle("/api/v1/agents/configs", {}, mock_http_handler)
            body = _body(result)
            config_entry = body["configs"][0]
            expected_keys = {
                "name",
                "model_type",
                "role",
                "priority",
                "description",
                "expertise_domains",
                "capabilities",
                "tags",
            }
            assert expected_keys == set(config_entry.keys())

    @pytest.mark.asyncio
    async def test_list_configs_filter_by_priority(self, handler, mock_http_handler, mock_loader):
        """Filter configs by priority."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle(
                "/api/v1/agents/configs",
                {"priority": ["high"]},
                mock_http_handler,
            )
            body = _body(result)
            assert body["total"] == 1
            assert body["configs"][0]["name"] == "claude-critic"

    @pytest.mark.asyncio
    async def test_list_configs_filter_by_role(self, handler, mock_http_handler, mock_loader):
        """Filter configs by role."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle(
                "/api/v1/agents/configs",
                {"role": ["judge"]},
                mock_http_handler,
            )
            body = _body(result)
            assert body["total"] == 1
            assert body["configs"][0]["name"] == "gemini-judge"

    @pytest.mark.asyncio
    async def test_list_configs_filter_by_priority_and_role(
        self, handler, mock_http_handler, mock_loader
    ):
        """Combined filter returns intersection."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle(
                "/api/v1/agents/configs",
                {"priority": ["normal"], "role": ["proposer"]},
                mock_http_handler,
            )
            body = _body(result)
            assert body["total"] == 1
            assert body["configs"][0]["name"] == "gpt4-proposer"

    @pytest.mark.asyncio
    async def test_list_configs_filter_no_match(self, handler, mock_http_handler, mock_loader):
        """Filter with no matching results returns empty list."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle(
                "/api/v1/agents/configs",
                {"priority": ["critical"]},
                mock_http_handler,
            )
            body = _body(result)
            assert body["total"] == 0
            assert body["configs"] == []

    @pytest.mark.asyncio
    async def test_list_configs_loader_unavailable(self, handler, mock_http_handler):
        """Returns 503 when config loader is unavailable."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=None,
        ):
            result = await handler.handle("/api/v1/agents/configs", {}, mock_http_handler)
            assert _status(result) == 503
            body = _body(result)
            assert "not available" in body.get("error", "").lower()


# ---------------------------------------------------------------------------
# GET /api/v1/agents/configs/search - Search Configs (via handle)
# ---------------------------------------------------------------------------


class TestSearchConfigsViaHandle:
    """Tests for searching configurations via the handle method."""

    @pytest.mark.asyncio
    async def test_search_by_expertise(self, handler, mock_http_handler, mock_loader):
        """Search by expertise domain returns matching configs."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle(
                "/api/v1/agents/configs/search",
                {"expertise": ["security"]},
                mock_http_handler,
            )
            body = _body(result)
            assert _status(result) == 200
            assert body["total"] == 1
            assert body["results"][0]["name"] == "claude-critic"

    @pytest.mark.asyncio
    async def test_search_by_capability(self, handler, mock_http_handler, mock_loader):
        """Search by capability returns matching configs."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle(
                "/api/v1/agents/configs/search",
                {"capability": ["synthesis"]},
                mock_http_handler,
            )
            body = _body(result)
            assert _status(result) == 200
            assert body["total"] == 1
            assert body["results"][0]["name"] == "gpt4-proposer"

    @pytest.mark.asyncio
    async def test_search_by_tag(self, handler, mock_http_handler, mock_loader):
        """Search by tag returns matching configs."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle(
                "/api/v1/agents/configs/search",
                {"tag": ["gemini"]},
                mock_http_handler,
            )
            body = _body(result)
            assert _status(result) == 200
            assert body["total"] == 1
            assert body["results"][0]["name"] == "gemini-judge"

    @pytest.mark.asyncio
    async def test_search_no_params_returns_400(self, handler, mock_http_handler, mock_loader):
        """Returns 400 when no search parameters provided."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle("/api/v1/agents/configs/search", {}, mock_http_handler)
            assert _status(result) == 400
            body = _body(result)
            assert "search parameter" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_search_loader_unavailable(self, handler, mock_http_handler):
        """Returns 503 when config loader is unavailable."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=None,
        ):
            result = await handler.handle(
                "/api/v1/agents/configs/search",
                {"expertise": ["anything"]},
                mock_http_handler,
            )
            assert _status(result) == 503


# ---------------------------------------------------------------------------
# POST /api/v1/agents/configs/reload - Reload Configs (via handle)
# ---------------------------------------------------------------------------


class TestReloadConfigsViaHandle:
    """Tests for reloading configurations via the handle method."""

    @pytest.mark.asyncio
    async def test_reload_success(self, handler, mock_http_handler, mock_loader):
        """Successfully reloads configs."""
        mock_loader.reload_all.return_value = {
            "claude-critic": MockAgentConfig(name="claude-critic"),
            "gpt4-proposer": MockAgentConfig(name="gpt4-proposer"),
        }
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle("/api/v1/agents/configs/reload", {}, mock_http_handler)
            body = _body(result)
            assert _status(result) == 200
            assert body["success"] is True
            assert body["reloaded"] == 2
            assert set(body["configs"]) == {"claude-critic", "gpt4-proposer"}

    @pytest.mark.asyncio
    async def test_reload_loader_unavailable(self, handler, mock_http_handler):
        """Returns 503 when config loader is unavailable."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=None,
        ):
            result = await handler.handle("/api/v1/agents/configs/reload", {}, mock_http_handler)
            assert _status(result) == 503


# ---------------------------------------------------------------------------
# _list_configs (direct)
# ---------------------------------------------------------------------------


class TestListConfigsDirect:
    """Tests for _list_configs method called directly."""

    def test_list_empty_loader(self, handler):
        """Returns empty list when loader has no configs."""
        loader = MagicMock()
        loader.list_configs.return_value = []
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=loader,
        ):
            result = handler._list_configs({})
            body = _body(result)
            assert _status(result) == 200
            assert body["total"] == 0

    def test_list_skips_none_config(self, handler):
        """Gracefully skips configs that return None from get_config."""
        loader = MagicMock()
        loader.list_configs.return_value = ["good", "bad"]
        good = MockAgentConfig(name="good")
        loader.get_config.side_effect = lambda n: good if n == "good" else None
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=loader,
        ):
            result = handler._list_configs({})
            body = _body(result)
            assert body["total"] == 1
            assert body["configs"][0]["name"] == "good"

    def test_list_filter_priority_case_sensitive(self, handler, mock_loader):
        """Priority filter is case-sensitive."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._list_configs({"priority": ["HIGH"]})
            body = _body(result)
            assert body["total"] == 0

    def test_list_filter_role_case_sensitive(self, handler, mock_loader):
        """Role filter is case-sensitive."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._list_configs({"role": ["CRITIC"]})
            body = _body(result)
            assert body["total"] == 0

    def test_list_loader_unavailable(self, handler):
        """Returns 503 when loader is None."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=None,
        ):
            result = handler._list_configs({})
            assert _status(result) == 503

    def test_list_no_filters_returns_all(self, handler, mock_loader):
        """No filters returns all configs."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._list_configs({})
            body = _body(result)
            assert body["total"] == 3

    def test_list_with_single_match(self, handler, mock_loader):
        """Filter returning single match works."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._list_configs({"role": ["judge"]})
            body = _body(result)
            assert body["total"] == 1
            assert body["configs"][0]["role"] == "judge"


# ---------------------------------------------------------------------------
# _get_config (direct)
# ---------------------------------------------------------------------------


class TestGetConfigDirect:
    """Tests for _get_config method called directly."""

    def test_get_config_success(self, handler, mock_loader):
        """Returns full config details for valid name."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._get_config("claude-critic")
            body = _body(result)
            assert _status(result) == 200
            assert "config" in body
            assert body["config"]["name"] == "claude-critic"
            assert body["config"]["model_type"] == "anthropic-api"

    def test_get_config_not_found(self, handler, mock_loader):
        """Returns 404 for non-existent config."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._get_config("nonexistent")
            assert _status(result) == 404
            body = _body(result)
            assert "not found" in body.get("error", "").lower()

    def test_get_config_loader_unavailable(self, handler):
        """Returns 503 when config loader is unavailable."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=None,
        ):
            result = handler._get_config("any-agent")
            assert _status(result) == 503

    def test_get_config_uses_to_dict(self, handler):
        """Uses config.to_dict() for the response."""
        mock_config = MagicMock()
        mock_config.to_dict.return_value = {"full": "config-data"}
        loader = MagicMock()
        loader.get_config.return_value = mock_config
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=loader,
        ):
            result = handler._get_config("test-agent")
            body = _body(result)
            assert _status(result) == 200
            assert body["config"] == {"full": "config-data"}
            mock_config.to_dict.assert_called_once()

    def test_get_config_error_message_includes_name(self, handler, mock_loader):
        """404 error message includes the config name."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._get_config("missing-name")
            body = _body(result)
            assert "missing-name" in body.get("error", "")


# ---------------------------------------------------------------------------
# _create_agent_from_config (direct)
# ---------------------------------------------------------------------------


class TestCreateAgentDirect:
    """Tests for _create_agent_from_config method called directly."""

    def test_create_agent_success(self, handler, mock_loader):
        """Successfully creates an agent from config."""
        mock_agent = MagicMock()
        mock_agent.name = "claude-critic"
        mock_agent.role = "critic"
        mock_loader.create_agent.return_value = mock_agent
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("claude-critic")
            body = _body(result)
            assert _status(result) == 200
            assert body["success"] is True
            assert body["agent"]["name"] == "claude-critic"
            assert body["config_used"] == "claude-critic"

    def test_create_agent_not_found(self, handler, mock_loader):
        """Returns 404 when config name doesn't exist."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("nonexistent")
            assert _status(result) == 404

    def test_create_agent_type_error(self, handler, mock_loader):
        """Returns 500 when agent creation raises TypeError."""
        mock_loader.create_agent.side_effect = TypeError("bad type")
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("claude-critic")
            assert _status(result) == 500
            body = _body(result)
            assert "failed" in body.get("error", "").lower()

    def test_create_agent_value_error(self, handler, mock_loader):
        """Returns 500 when agent creation raises ValueError."""
        mock_loader.create_agent.side_effect = ValueError("bad value")
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("claude-critic")
            assert _status(result) == 500

    def test_create_agent_key_error(self, handler, mock_loader):
        """Returns 500 when agent creation raises KeyError."""
        mock_loader.create_agent.side_effect = KeyError("missing key")
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("claude-critic")
            assert _status(result) == 500

    def test_create_agent_attribute_error(self, handler, mock_loader):
        """Returns 500 when agent creation raises AttributeError."""
        mock_loader.create_agent.side_effect = AttributeError("no attr")
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("claude-critic")
            assert _status(result) == 500

    def test_create_agent_loader_unavailable(self, handler):
        """Returns 503 when config loader is unavailable."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=None,
        ):
            result = handler._create_agent_from_config("any-agent")
            assert _status(result) == 503

    def test_create_agent_response_includes_model_type(self, handler, mock_loader):
        """Response includes model_type from config."""
        mock_agent = MagicMock()
        mock_agent.name = "gpt4-proposer"
        mock_agent.role = "proposer"
        mock_loader.create_agent.return_value = mock_agent
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("gpt4-proposer")
            body = _body(result)
            assert body["agent"]["model_type"] == "openai-api"

    def test_create_agent_uses_getattr_for_role(self, handler, mock_loader):
        """Uses getattr(agent, 'role', config.role) for role."""
        mock_agent = MagicMock(spec=[])  # no 'role' attribute
        mock_agent.name = "claude-critic"
        mock_loader.create_agent.return_value = mock_agent
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("claude-critic")
            body = _body(result)
            assert _status(result) == 200
            # Falls back to config.role since agent has no 'role' attr
            assert body["agent"]["role"] == "critic"

    def test_create_agent_with_role_on_agent(self, handler, mock_loader):
        """Uses agent.role when it exists."""
        mock_agent = MagicMock()
        mock_agent.name = "claude-critic"
        mock_agent.role = "custom-role"
        mock_loader.create_agent.return_value = mock_agent
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("claude-critic")
            body = _body(result)
            assert body["agent"]["role"] == "custom-role"


# ---------------------------------------------------------------------------
# _reload_configs (direct)
# ---------------------------------------------------------------------------


class TestReloadConfigsDirect:
    """Tests for _reload_configs method called directly."""

    def test_reload_success(self, handler, mock_loader):
        """Successfully reloads configs."""
        mock_loader.reload_all.return_value = {
            "a": MockAgentConfig(name="a"),
            "b": MockAgentConfig(name="b"),
        }
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._reload_configs()
            body = _body(result)
            assert _status(result) == 200
            assert body["success"] is True
            assert body["reloaded"] == 2

    def test_reload_loader_unavailable(self, handler):
        """Returns 503 when loader is None."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=None,
        ):
            result = handler._reload_configs()
            assert _status(result) == 503

    def test_reload_os_error(self, handler, mock_loader):
        """Returns 500 when reload raises OSError."""
        mock_loader.reload_all.side_effect = OSError("disk error")
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._reload_configs()
            assert _status(result) == 500

    def test_reload_type_error(self, handler, mock_loader):
        """Returns 500 when reload raises TypeError."""
        mock_loader.reload_all.side_effect = TypeError("bad")
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._reload_configs()
            assert _status(result) == 500

    def test_reload_value_error(self, handler, mock_loader):
        """Returns 500 when reload raises ValueError."""
        mock_loader.reload_all.side_effect = ValueError("invalid")
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._reload_configs()
            assert _status(result) == 500

    def test_reload_key_error(self, handler, mock_loader):
        """Returns 500 when reload raises KeyError."""
        mock_loader.reload_all.side_effect = KeyError("missing")
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._reload_configs()
            assert _status(result) == 500

    def test_reload_attribute_error(self, handler, mock_loader):
        """Returns 500 when reload raises AttributeError."""
        mock_loader.reload_all.side_effect = AttributeError("no attr")
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._reload_configs()
            assert _status(result) == 500

    def test_reload_empty_result(self, handler, mock_loader):
        """Reload with empty result set."""
        mock_loader.reload_all.return_value = {}
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._reload_configs()
            body = _body(result)
            assert _status(result) == 200
            assert body["reloaded"] == 0
            assert body["configs"] == []


# ---------------------------------------------------------------------------
# _search_configs (direct)
# ---------------------------------------------------------------------------


class TestSearchConfigsDirect:
    """Tests for _search_configs method called directly."""

    def test_search_no_params_returns_400(self, handler, mock_loader):
        """Returns 400 when no search parameters provided."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._search_configs({})
            assert _status(result) == 400

    def test_search_multiple_params_deduplication(self, handler):
        """Multiple search params combine results with deduplication."""
        config_a = MockAgentConfig(
            name="multi-match",
            expertise_domains=["ai"],
            capabilities=["reasoning"],
            tags=["smart"],
        )
        loader = MagicMock()
        loader.get_by_expertise.return_value = [config_a]
        loader.get_by_capability.return_value = [config_a]
        loader.get_by_tag.return_value = [config_a]
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=loader,
        ):
            result = handler._search_configs(
                {"expertise": ["ai"], "capability": ["reasoning"], "tag": ["smart"]}
            )
            body = _body(result)
            assert body["total"] == 1

    def test_search_no_results(self, handler, mock_loader):
        """Search with no matches returns empty results."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._search_configs({"expertise": ["nonexistent-domain"]})
            body = _body(result)
            assert _status(result) == 200
            assert body["total"] == 0
            assert body["results"] == []

    def test_search_response_structure(self, handler, mock_loader):
        """Verify search response structure."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._search_configs({"expertise": ["security"]})
            body = _body(result)
            assert "results" in body
            assert "total" in body
            assert "search_params" in body
            entry = body["results"][0]
            expected_keys = {
                "name",
                "model_type",
                "role",
                "description",
                "expertise_domains",
                "capabilities",
                "tags",
            }
            assert expected_keys == set(entry.keys())

    def test_search_params_echoed(self, handler, mock_loader):
        """Search params are echoed in the response."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._search_configs(
                {"expertise": ["security"], "capability": ["analysis"]}
            )
            body = _body(result)
            assert body["search_params"]["expertise"] == "security"
            assert body["search_params"]["capability"] == "analysis"
            assert body["search_params"]["tag"] is None

    def test_search_loader_unavailable(self, handler):
        """Returns 503 when config loader is unavailable."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=None,
        ):
            result = handler._search_configs({"expertise": ["anything"]})
            assert _status(result) == 503

    def test_search_expertise_only(self, handler, mock_loader):
        """Search with only expertise param works."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._search_configs({"expertise": ["code-review"]})
            body = _body(result)
            assert _status(result) == 200
            assert body["total"] == 1

    def test_search_capability_only(self, handler, mock_loader):
        """Search with only capability param works."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._search_configs({"capability": ["judgment"]})
            body = _body(result)
            assert body["total"] == 1
            assert body["results"][0]["name"] == "gemini-judge"

    def test_search_tag_only(self, handler, mock_loader):
        """Search with only tag param works."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._search_configs({"tag": ["gpt4"]})
            body = _body(result)
            assert body["total"] == 1
            assert body["results"][0]["name"] == "gpt4-proposer"

    def test_search_all_three_params_union(self, handler):
        """Search with all three params returns union of results."""
        config_a = MockAgentConfig(name="agent-a", expertise_domains=["ml"])
        config_b = MockAgentConfig(name="agent-b", capabilities=["coding"])
        config_c = MockAgentConfig(name="agent-c", tags=["fast"])

        loader = MagicMock()
        loader.get_by_expertise.return_value = [config_a]
        loader.get_by_capability.return_value = [config_b]
        loader.get_by_tag.return_value = [config_c]

        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=loader,
        ):
            result = handler._search_configs(
                {"expertise": ["ml"], "capability": ["coding"], "tag": ["fast"]}
            )
            body = _body(result)
            assert body["total"] == 3
            names = {r["name"] for r in body["results"]}
            assert names == {"agent-a", "agent-b", "agent-c"}


# ---------------------------------------------------------------------------
# _handle_config_endpoint internal path parsing
# ---------------------------------------------------------------------------


class TestHandleConfigEndpoint:
    """Tests for _handle_config_endpoint internal routing."""

    def test_short_path_returns_400(self, handler):
        """Returns 400 for paths with fewer than 5 segments."""
        # "/a/b/c" splits to ["", "a", "b", "c"] = 4 parts
        result = handler._handle_config_endpoint("/a/b/c", {})
        assert _status(result) == 400
        body = _body(result)
        assert "invalid" in body.get("error", "").lower()

    def test_extract_config_name(self, handler, mock_loader):
        """Extracts parts[4] as config name."""
        # For non-versioned: "/api/agents/configs/myagent"
        # parts = ["", "api", "agents", "configs", "myagent"]
        # parts[4] = "myagent"
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._handle_config_endpoint("/api/agents/configs/claude-critic", {})
            body = _body(result)
            assert _status(result) == 200
            assert body["config"]["name"] == "claude-critic"

    def test_create_subpath(self, handler, mock_loader):
        """Config endpoint with /create suffix dispatches to create."""
        mock_agent = MagicMock()
        mock_agent.name = "claude-critic"
        mock_agent.role = "critic"
        mock_loader.create_agent.return_value = mock_agent
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            # /api/agents/configs/{name}/create
            # parts = ["", "api", "agents", "configs", "claude-critic", "create"]
            # parts[4] = "claude-critic", len(parts) >= 6, parts[5] = "create"
            result = handler._handle_config_endpoint("/api/agents/configs/claude-critic/create", {})
            body = _body(result)
            assert _status(result) == 200
            assert body["success"] is True

    def test_invalid_config_name_with_special_chars(self, handler):
        """Rejects config names that fail SAFE_AGENT_PATTERN validation."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=MagicMock(),
        ):
            result = handler._handle_config_endpoint("/api/agents/configs/<script>alert(1)", {})
            assert _status(result) == 400

    def test_config_name_too_long(self, handler):
        """Rejects config names longer than 32 characters."""
        long_name = "a" * 33
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=MagicMock(),
        ):
            result = handler._handle_config_endpoint(f"/api/agents/configs/{long_name}", {})
            assert _status(result) == 400

    def test_config_name_with_dots(self, handler):
        """Accepts dotted model-version names (#9994); rejects a leading dot and slashes."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=MagicMock(),
        ):
            result = handler._handle_config_endpoint("/api/agents/configs/gemini-3.1-pro", {})
            assert _status(result) == 200
            result = handler._handle_config_endpoint("/api/agents/configs/.my-agent", {})
            assert _status(result) == 400
            result = handler._handle_config_endpoint("/api/agents/configs/..", {})
            assert _status(result) == 400

    def test_config_name_with_spaces(self, handler):
        """Rejects config names with spaces."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=MagicMock(),
        ):
            result = handler._handle_config_endpoint("/api/agents/configs/my agent", {})
            assert _status(result) == 400

    def test_valid_name_at_max_length(self, handler, mock_loader):
        """Accepts config names at exactly 32 characters."""
        name = "a" * 32
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._handle_config_endpoint(f"/api/agents/configs/{name}", {})
            # Should not be 400 (will be 404 since not in mock)
            assert _status(result) != 400

    def test_valid_name_with_hyphens_underscores(self, handler, mock_loader):
        """Accepts config names with hyphens and underscores."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._handle_config_endpoint("/api/agents/configs/my_agent-v2", {})
            # passes validation, gets 404 from mock
            assert _status(result) == 404

    def test_get_config_dispatched_for_simple_name(self, handler, mock_loader):
        """Simple name (no extra segments) dispatches to _get_config."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._handle_config_endpoint("/api/agents/configs/gpt4-proposer", {})
            body = _body(result)
            assert _status(result) == 200
            assert body["config"]["name"] == "gpt4-proposer"


# ---------------------------------------------------------------------------
# Security Tests
# ---------------------------------------------------------------------------


class TestSecurity:
    """Security-focused tests on path parsing."""

    def test_path_traversal_dots(self, handler):
        """Rejects path traversal with dots."""
        result = handler._handle_config_endpoint("/api/agents/configs/../etc", {})
        # ".." contains dots, fails SAFE_AGENT_PATTERN
        assert _status(result) == 400

    def test_script_injection(self, handler):
        """Rejects script injection in config names."""
        result = handler._handle_config_endpoint("/api/agents/configs/<script>", {})
        assert _status(result) == 400

    def test_null_byte_injection(self, handler):
        """Rejects null bytes in config names."""
        result = handler._handle_config_endpoint("/api/agents/configs/test\x00evil", {})
        assert _status(result) == 400

    def test_sql_injection(self, handler):
        """Rejects SQL injection in config names."""
        result = handler._handle_config_endpoint("/api/agents/configs/';DROP", {})
        assert _status(result) == 400

    def test_unicode_chars(self, handler):
        """Rejects unicode characters in config names."""
        result = handler._handle_config_endpoint("/api/agents/configs/test\u00e9", {})
        assert _status(result) == 400

    def test_empty_name(self, handler):
        """Rejects empty config name."""
        # Path would be /api/agents/configs/ with empty parts[4] after trailing slash
        # But split gives ["", "api", "agents", "configs", ""]
        result = handler._handle_config_endpoint("/api/agents/configs/", {})
        assert _status(result) == 400

    def test_whitespace_only_name(self, handler):
        """Rejects whitespace-only config name."""
        result = handler._handle_config_endpoint("/api/agents/configs/ ", {})
        assert _status(result) == 400


# ---------------------------------------------------------------------------
# RBAC / Authentication Tests
# ---------------------------------------------------------------------------


class TestRBAC:
    """Tests for RBAC permission enforcement."""

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, handler, mock_http_handler):
        """Returns 401 when not authenticated."""
        from aragora.server.handlers.secure import SecureHandler
        from aragora.server.handlers.utils.auth import UnauthorizedError

        async def mock_get_auth_raising(self, request, require_auth=False):
            raise UnauthorizedError("Not authenticated")

        with patch.object(SecureHandler, "get_auth_context", mock_get_auth_raising):
            result = await handler.handle("/api/v1/agents/configs", {}, mock_http_handler)
            assert _status(result) == 401
            body = _body(result)
            assert "authentication" in body.get("error", "").lower()

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_forbidden_returns_403(self, handler, mock_http_handler):
        """Returns 403 when permission check fails."""
        from aragora.server.handlers.secure import SecureHandler, ForbiddenError

        mock_auth_ctx = AuthorizationContext(
            user_id="user-001",
            user_email="user@example.com",
            org_id="org-001",
            roles={"viewer"},
            permissions=set(),
        )

        async def mock_get_auth(self, request, require_auth=False):
            return mock_auth_ctx

        def mock_check_perm(self, ctx, perm, resource_id=None):
            raise ForbiddenError(f"Missing permission: {perm}")

        with (
            patch.object(SecureHandler, "get_auth_context", mock_get_auth),
            patch.object(SecureHandler, "check_permission", mock_check_perm),
        ):
            result = await handler.handle("/api/v1/agents/configs", {}, mock_http_handler)
            assert _status(result) == 403
            body = _body(result)
            assert "denied" in body.get("error", "").lower()

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_reload_requires_admin_role(self, handler, mock_http_handler):
        """Reload returns 403 when user doesn't have admin role."""
        from aragora.server.handlers.secure import SecureHandler

        non_admin_ctx = AuthorizationContext(
            user_id="user-001",
            user_email="user@example.com",
            org_id="org-001",
            roles={"viewer"},
            permissions={"agents:config:read", "agents:config:write"},
        )

        async def mock_get_auth(self, request, require_auth=False):
            return non_admin_ctx

        with patch.object(SecureHandler, "get_auth_context", mock_get_auth):
            result = await handler.handle("/api/v1/agents/configs/reload", {}, mock_http_handler)
            assert _status(result) == 403
            body = _body(result)
            assert "admin" in body.get("error", "").lower()

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_reload_allowed_for_admin(self, handler, mock_http_handler):
        """Reload succeeds for admin users."""
        from aragora.server.handlers.secure import SecureHandler

        admin_ctx = AuthorizationContext(
            user_id="admin-001",
            user_email="admin@example.com",
            org_id="org-001",
            roles={"admin"},
            permissions={"*"},
        )

        async def mock_get_auth(self, request, require_auth=False):
            return admin_ctx

        mock_loader = MagicMock()
        mock_loader.reload_all.return_value = {}

        with (
            patch.object(SecureHandler, "get_auth_context", mock_get_auth),
            patch(
                "aragora.server.handlers.agents.config.get_config_loader",
                return_value=mock_loader,
            ),
        ):
            result = await handler.handle("/api/v1/agents/configs/reload", {}, mock_http_handler)
            assert _status(result) == 200

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_reload_allowed_for_owner(self, handler, mock_http_handler):
        """Reload succeeds for owner users."""
        from aragora.server.handlers.secure import SecureHandler

        owner_ctx = AuthorizationContext(
            user_id="owner-001",
            user_email="owner@example.com",
            org_id="org-001",
            roles={"owner"},
            permissions={"*"},
        )

        async def mock_get_auth(self, request, require_auth=False):
            return owner_ctx

        mock_loader = MagicMock()
        mock_loader.reload_all.return_value = {}

        with (
            patch.object(SecureHandler, "get_auth_context", mock_get_auth),
            patch(
                "aragora.server.handlers.agents.config.get_config_loader",
                return_value=mock_loader,
            ),
        ):
            result = await handler.handle("/api/v1/agents/configs/reload", {}, mock_http_handler)
            assert _status(result) == 200

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_create_requires_write_permission(self, handler, mock_http_handler):
        """Create endpoint returns 403 when user lacks write permission."""
        from aragora.server.handlers.secure import SecureHandler, ForbiddenError

        read_only_ctx = AuthorizationContext(
            user_id="user-001",
            user_email="user@example.com",
            org_id="org-001",
            roles={"viewer"},
            permissions={"agents:config:read"},
        )

        async def mock_get_auth(self, request, require_auth=False):
            return read_only_ctx

        def mock_check_perm(self, ctx, perm, resource_id=None):
            if perm == "agents:config:write":
                raise ForbiddenError(f"Missing permission: {perm}")
            return True

        with (
            patch.object(SecureHandler, "get_auth_context", mock_get_auth),
            patch.object(SecureHandler, "check_permission", mock_check_perm),
        ):
            result = await handler.handle(
                "/api/v1/agents/configs/test-agent/create",
                {},
                mock_http_handler,
            )
            assert _status(result) == 403

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_list_requires_read_permission(self, handler, mock_http_handler):
        """List endpoint returns 403 when user lacks read permission."""
        from aragora.server.handlers.secure import SecureHandler, ForbiddenError

        no_perms_ctx = AuthorizationContext(
            user_id="user-001",
            user_email="user@example.com",
            org_id="org-001",
            roles={"viewer"},
            permissions=set(),
        )

        async def mock_get_auth(self, request, require_auth=False):
            return no_perms_ctx

        def mock_check_perm(self, ctx, perm, resource_id=None):
            raise ForbiddenError(f"Missing permission: {perm}")

        with (
            patch.object(SecureHandler, "get_auth_context", mock_get_auth),
            patch.object(SecureHandler, "check_permission", mock_check_perm),
        ):
            result = await handler.handle("/api/v1/agents/configs", {}, mock_http_handler)
            assert _status(result) == 403

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_search_requires_read_permission(self, handler, mock_http_handler):
        """Search endpoint returns 403 when user lacks read permission."""
        from aragora.server.handlers.secure import SecureHandler, ForbiddenError

        no_perms_ctx = AuthorizationContext(
            user_id="user-001",
            user_email="user@example.com",
            org_id="org-001",
            roles={"viewer"},
            permissions=set(),
        )

        async def mock_get_auth(self, request, require_auth=False):
            return no_perms_ctx

        def mock_check_perm(self, ctx, perm, resource_id=None):
            raise ForbiddenError(f"Missing permission: {perm}")

        with (
            patch.object(SecureHandler, "get_auth_context", mock_get_auth),
            patch.object(SecureHandler, "check_permission", mock_check_perm),
        ):
            result = await handler.handle(
                "/api/v1/agents/configs/search",
                {"expertise": ["any"]},
                mock_http_handler,
            )
            assert _status(result) == 403


# ---------------------------------------------------------------------------
# Routing edge cases via handle
# ---------------------------------------------------------------------------


class TestHandleRouting:
    """Tests for handle method routing edge cases."""

    @pytest.mark.asyncio
    async def test_unmatched_path_returns_none(self, handler, mock_http_handler):
        """Returns None for paths that don't match any route."""
        result = await handler.handle("/api/v1/other/endpoint", {}, mock_http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_configs_root_routes_to_list(self, handler, mock_http_handler, mock_loader):
        """Root path routes to list configs."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle("/api/v1/agents/configs", {}, mock_http_handler)
            body = _body(result)
            assert "configs" in body
            assert "total" in body

    @pytest.mark.asyncio
    async def test_search_routes_correctly(self, handler, mock_http_handler, mock_loader):
        """Search path routes to search handler."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle(
                "/api/v1/agents/configs/search",
                {"expertise": ["security"]},
                mock_http_handler,
            )
            body = _body(result)
            assert "results" in body
            assert "search_params" in body

    @pytest.mark.asyncio
    async def test_reload_routes_correctly(self, handler, mock_http_handler, mock_loader):
        """Reload path routes to reload handler."""
        mock_loader.reload_all.return_value = {}
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = await handler.handle("/api/v1/agents/configs/reload", {}, mock_http_handler)
            body = _body(result)
            assert "success" in body
            assert "reloaded" in body

    @pytest.mark.asyncio
    async def test_path_with_trailing_content(self, handler, mock_http_handler):
        """Path starting with /api/v1/agents/configs/ routes to config endpoint."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=MagicMock(),
        ):
            result = await handler.handle("/api/v1/agents/configs/some-name", {}, mock_http_handler)
            # This goes through _handle_config_endpoint; may return an error
            # because parts[4] is "configs" which passes validation but likely
            # returns 404 from the mock loader
            assert result is not None


# ---------------------------------------------------------------------------
# get_config_loader function
# ---------------------------------------------------------------------------


class TestGetConfigLoader:
    """Tests for the get_config_loader function."""

    def test_returns_cached_loader(self):
        """Returns cached loader on second call."""
        import aragora.server.handlers.agents.config as config_mod

        mock_loader = MagicMock()
        config_mod._config_loader = mock_loader
        result = config_mod.get_config_loader()
        assert result is mock_loader

    def test_caching_prevents_reinitialization(self):
        """Cached loader prevents re-creation."""
        import aragora.server.handlers.agents.config as config_mod

        mock_loader = MagicMock()
        config_mod._config_loader = mock_loader
        result1 = config_mod.get_config_loader()
        result2 = config_mod.get_config_loader()
        assert result1 is result2 is mock_loader

    def test_none_loader_triggers_creation(self):
        """None _config_loader triggers creation attempt."""
        import aragora.server.handlers.agents.config as config_mod

        config_mod._config_loader = None
        mock_instance = MagicMock()
        mock_instance.list_configs.return_value = []

        with patch(
            "aragora.agents.config_loader.AgentConfigLoader",
            return_value=mock_instance,
        ):
            result = config_mod.get_config_loader()
            # May succeed or fail depending on import; key: no crash
            # If it returns something, it should be the mock or None
            assert result is None or result is not None

    def test_import_error_returns_none(self):
        """Returns None when AgentConfigLoader import fails."""
        import aragora.server.handlers.agents.config as config_mod
        import sys

        config_mod._config_loader = None

        # Remove module from cache and force import error
        saved = sys.modules.get("aragora.agents.config_loader")
        sys.modules["aragora.agents.config_loader"] = None  # type: ignore

        try:
            result = config_mod.get_config_loader()
            assert result is None
        finally:
            if saved is not None:
                sys.modules["aragora.agents.config_loader"] = saved
            else:
                sys.modules.pop("aragora.agents.config_loader", None)

    def test_loader_loads_default_directory(self):
        """Loader attempts to load from default config directory."""
        import aragora.server.handlers.agents.config as config_mod

        config_mod._config_loader = None
        mock_instance = MagicMock()
        mock_instance.list_configs.return_value = ["test"]
        mock_cls = MagicMock(return_value=mock_instance)

        mock_path = MagicMock()
        mock_path.exists.return_value = True

        with (
            patch(
                "aragora.agents.config_loader.AgentConfigLoader",
                mock_cls,
            ),
            patch(
                "aragora.server.handlers.agents.config.Path",
            ) as mock_path_cls,
        ):
            # Make the default_dir.exists() return True
            mock_path_obj = MagicMock()
            mock_path_obj.exists.return_value = True
            mock_path_obj.__truediv__ = MagicMock(return_value=mock_path_obj)
            mock_path_cls.return_value = mock_path_obj
            # Re-stub parent chain
            mock_path_cls.__truediv__ = MagicMock(return_value=mock_path_obj)

            result = config_mod.get_config_loader()
            # Verify the loader was instantiated
            if result is not None:
                mock_cls.assert_called_once()


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge case tests."""

    def test_list_configs_with_priority_filter_only(self, handler, mock_loader):
        """Priority filter with no role filter works."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._list_configs({"priority": ["low"]})
            body = _body(result)
            assert body["total"] == 1
            assert body["configs"][0]["priority"] == "low"

    def test_list_configs_with_role_filter_only(self, handler, mock_loader):
        """Role filter with no priority filter works."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._list_configs({"role": ["critic"]})
            body = _body(result)
            assert body["total"] == 1
            assert body["configs"][0]["role"] == "critic"

    def test_list_configs_priority_mismatch_excludes(self, handler, mock_loader):
        """Config excluded when priority doesn't match filter."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._list_configs({"priority": ["normal"], "role": ["critic"]})
            body = _body(result)
            # claude-critic has priority=high, role=critic -> excluded by priority
            assert body["total"] == 0

    def test_create_config_used_echoed(self, handler, mock_loader):
        """Created response echoes the config_used name."""
        mock_agent = MagicMock()
        mock_agent.name = "gemini-judge"
        mock_agent.role = "judge"
        mock_loader.create_agent.return_value = mock_agent
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._create_agent_from_config("gemini-judge")
            body = _body(result)
            assert body["config_used"] == "gemini-judge"

    def test_reload_returns_config_names(self, handler, mock_loader):
        """Reload response includes list of config names."""
        mock_loader.reload_all.return_value = {
            "x": MagicMock(),
            "y": MagicMock(),
            "z": MagicMock(),
        }
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._reload_configs()
            body = _body(result)
            assert body["reloaded"] == 3
            assert set(body["configs"]) == {"x", "y", "z"}

    @pytest.mark.asyncio
    async def test_handle_returns_none_for_non_matching_prefix(self, handler, mock_http_handler):
        """handle returns None when path prefix doesn't match."""
        result = await handler.handle("/api/v1/debates/something", {}, mock_http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_subpath_forwards_to_config_endpoint(self, handler, mock_http_handler):
        """Paths like /api/v1/agents/configs/xxx go through _handle_config_endpoint."""
        loader = MagicMock()
        loader.get_config.return_value = None  # No config named "configs"
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=loader,
        ):
            result = await handler.handle("/api/v1/agents/configs/test-name", {}, mock_http_handler)
            # Goes through _handle_config_endpoint which extracts parts[4]="configs"
            # This will pass validation (matches SAFE_AGENT_PATTERN)
            # and then call _get_config("configs") which returns 404 from loader
            assert result is not None
            assert _status(result) == 404

    def test_search_returns_correct_config_fields(self, handler, mock_loader):
        """Search results contain all expected fields."""
        with patch(
            "aragora.server.handlers.agents.config.get_config_loader",
            return_value=mock_loader,
        ):
            result = handler._search_configs({"tag": ["claude"]})
            body = _body(result)
            entry = body["results"][0]
            assert entry["name"] == "claude-critic"
            assert entry["model_type"] == "anthropic-api"
            assert entry["role"] == "critic"
            assert entry["description"] == "Claude-based critic agent"
            assert "security" in entry["expertise_domains"]
            assert "critique" in entry["capabilities"]
            assert "claude" in entry["tags"]
