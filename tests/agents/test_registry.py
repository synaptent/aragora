"""
Tests for aragora.agents.registry module.

This module tests the AgentRegistry factory pattern for agent creation,
including registration, caching, local LLM detection integration, and
edge cases. These tests complement the tests in test_agent_registry.py.

Tests cover:
- RegistrySpec dataclass (frozen, fields, defaults)
- AgentRegistry registration (@register decorator)
- Agent creation (basic, with parameters, error handling)
- Cache behavior (hits, misses, eviction, stats)
- Local LLM detection methods (detect_local_agents, get_local_status)
- Helper functions (_run_async_in_thread)
- Module exports and __all__
- Edge cases and error conditions
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clear_registry_state():
    """Clear registry and cache before and after each test."""
    from aragora.agents.registry import AgentRegistry, _agent_cache

    # Store original registry state
    original_registry = AgentRegistry._registry.copy()
    original_cache = _agent_cache.copy()

    # Clear for test
    AgentRegistry.clear()

    yield

    # Restore original state
    AgentRegistry._registry.clear()
    AgentRegistry._registry.update(original_registry)
    _agent_cache.clear()
    _agent_cache.update(original_cache)


@pytest.fixture
def mock_agent_class():
    """Create a mock agent class for testing."""

    class MockAgent:
        def __init__(
            self,
            name: str,
            role: str = "proposer",
            model: str | None = None,
            api_key: str | None = None,
            **kwargs: Any,
        ):
            self.name = name
            self.role = role
            self.model = model
            self.api_key = api_key
            self.extra_kwargs = kwargs

        async def generate(self, prompt: str, context=None) -> str:
            return "Mock response"

    return MockAgent


@pytest.fixture
def registered_mock_agent(mock_agent_class):
    """Register a mock agent and return the class."""
    from aragora.agents.registry import AgentRegistry

    AgentRegistry.register(
        "mock-agent",
        default_model="mock-model-v1",
        default_name="mock-agent",
        agent_type="API",
        requires=None,
        env_vars="MOCK_API_KEY",
        description="A mock agent for testing",
        accepts_api_key=True,
    )(mock_agent_class)

    return mock_agent_class


# =============================================================================
# RegistrySpec Tests
# =============================================================================


class TestRegistrySpecDataclass:
    """Test RegistrySpec dataclass properties."""

    def test_registry_spec_all_fields(self, mock_agent_class):
        """Test RegistrySpec creation with all fields."""
        from aragora.agents.registry import RegistrySpec

        spec = RegistrySpec(
            name="full-spec-agent",
            agent_class=mock_agent_class,
            default_model="spec-model-v1",
            default_name="full-spec-agent",
            agent_type="CLI",
            requires="spec-cli tool",
            env_vars="SPEC_API_KEY",
            description="A fully specified agent",
            accepts_api_key=True,
        )

        assert spec.name == "full-spec-agent"
        assert spec.agent_class is mock_agent_class
        assert spec.default_model == "spec-model-v1"
        assert spec.default_name == "full-spec-agent"
        assert spec.agent_type == "CLI"
        assert spec.requires == "spec-cli tool"
        assert spec.env_vars == "SPEC_API_KEY"
        assert spec.description == "A fully specified agent"
        assert spec.accepts_api_key is True

    def test_registry_spec_frozen_prevents_name_change(self, mock_agent_class):
        """Test RegistrySpec is frozen and name cannot be changed."""
        from aragora.agents.registry import RegistrySpec

        spec = RegistrySpec(
            name="immutable-agent",
            agent_class=mock_agent_class,
            default_model="model",
            default_name="immutable-agent",
            agent_type="API",
            requires=None,
            env_vars=None,
        )

        with pytest.raises(FrozenInstanceError):
            spec.name = "new-name"  # type: ignore[misc]

    def test_registry_spec_frozen_prevents_model_change(self, mock_agent_class):
        """Test RegistrySpec is frozen and default_model cannot be changed."""
        from aragora.agents.registry import RegistrySpec

        spec = RegistrySpec(
            name="immutable-model-agent",
            agent_class=mock_agent_class,
            default_model="original-model",
            default_name="immutable-model-agent",
            agent_type="API",
            requires=None,
            env_vars=None,
        )

        with pytest.raises(FrozenInstanceError):
            spec.default_model = "new-model"  # type: ignore[misc]

    def test_registry_spec_default_description_is_none(self, mock_agent_class):
        """Test RegistrySpec description defaults to None."""
        from aragora.agents.registry import RegistrySpec

        spec = RegistrySpec(
            name="no-desc-agent",
            agent_class=mock_agent_class,
            default_model=None,
            default_name="no-desc-agent",
            agent_type="API",
            requires=None,
            env_vars=None,
        )

        assert spec.description is None

    def test_registry_spec_default_accepts_api_key_is_false(self, mock_agent_class):
        """Test RegistrySpec accepts_api_key defaults to False."""
        from aragora.agents.registry import RegistrySpec

        spec = RegistrySpec(
            name="no-api-key-agent",
            agent_class=mock_agent_class,
            default_model=None,
            default_name="no-api-key-agent",
            agent_type="API",
            requires=None,
            env_vars=None,
        )

        assert spec.accepts_api_key is False


# =============================================================================
# Registration Decorator Tests
# =============================================================================


class TestRegistrationDecorator:
    """Test @AgentRegistry.register decorator."""

    def test_register_minimal_spec(self, mock_agent_class):
        """Test registration with minimal specification."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register("minimal-agent")
        class MinimalAgent(mock_agent_class):
            pass

        assert AgentRegistry.is_registered("minimal-agent")
        spec = AgentRegistry.get_spec("minimal-agent")
        assert spec is not None
        assert spec.name == "minimal-agent"
        assert spec.default_name == "minimal-agent"  # Defaults to type_name
        assert spec.agent_type == "API"  # Default
        assert spec.default_model is None

    def test_register_openrouter_agent_type(self, mock_agent_class):
        """Test registration with API (OpenRouter) agent type."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register(
            "openrouter-agent",
            agent_type="API (OpenRouter)",
            default_model="deepseek/deepseek-v4-pro",
        )
        class OpenRouterAgent(mock_agent_class):
            pass

        spec = AgentRegistry.get_spec("openrouter-agent")
        assert spec is not None
        assert spec.agent_type == "API (OpenRouter)"
        assert spec.default_model == "deepseek/deepseek-v4-pro"

    def test_register_preserves_class_methods(self, mock_agent_class):
        """Test registration preserves class methods."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register("method-agent")
        class MethodAgent(mock_agent_class):
            def custom_method(self):
                return "custom"

        agent = AgentRegistry.create("method-agent")
        assert hasattr(agent, "custom_method")
        assert agent.custom_method() == "custom"

    def test_register_preserves_class_attributes(self, mock_agent_class):
        """Test registration preserves class attributes."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register("attr-agent")
        class AttrAgent(mock_agent_class):
            CLASS_CONST = "constant_value"

        assert AttrAgent.CLASS_CONST == "constant_value"

    def test_register_with_env_vars(self, mock_agent_class):
        """Test registration with environment variable specification."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register(
            "env-agent",
            env_vars="ENV_AGENT_KEY,ENV_AGENT_SECRET",
        )
        class EnvAgent(mock_agent_class):
            pass

        spec = AgentRegistry.get_spec("env-agent")
        assert spec is not None
        assert spec.env_vars == "ENV_AGENT_KEY,ENV_AGENT_SECRET"


# =============================================================================
# Agent Creation Tests
# =============================================================================


class TestAgentCreation:
    """Test AgentRegistry.create method."""

    def test_create_with_all_params(self, registered_mock_agent):
        """Test create with all parameters specified."""
        from aragora.agents.registry import AgentRegistry

        agent = AgentRegistry.create(
            "mock-agent",
            name="custom-agent-name",
            role="critic",
            model="custom-model",
            api_key="sk-custom-key",
        )

        assert agent.name == "custom-agent-name"
        assert agent.role == "critic"
        assert agent.model == "custom-model"
        assert agent.api_key == "sk-custom-key"

    def test_create_with_synthesizer_role(self, registered_mock_agent):
        """Test create with synthesizer role."""
        from aragora.agents.registry import AgentRegistry

        agent = AgentRegistry.create("mock-agent", role="synthesizer")

        assert agent.role == "synthesizer"

    def test_create_with_judge_role(self, registered_mock_agent):
        """Test create with judge role."""
        from aragora.agents.registry import AgentRegistry

        agent = AgentRegistry.create("mock-agent", role="judge")

        assert agent.role == "judge"

    def test_create_passes_extra_kwargs(self, registered_mock_agent):
        """Test create passes extra kwargs to agent constructor."""
        from aragora.agents.registry import AgentRegistry

        agent = AgentRegistry.create(
            "mock-agent",
            temperature=0.7,
            max_tokens=1000,
            system_prompt="Be helpful",
        )

        assert agent.extra_kwargs["temperature"] == 0.7
        assert agent.extra_kwargs["max_tokens"] == 1000
        assert agent.extra_kwargs["system_prompt"] == "Be helpful"

    def test_create_error_message_shows_all_valid_types(self, mock_agent_class):
        """Test error message lists all registered types."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register("type-a")
        class TypeAAgent(mock_agent_class):
            pass

        @AgentRegistry.register("type-b")
        class TypeBAgent(mock_agent_class):
            pass

        with pytest.raises(ValueError) as exc_info:
            AgentRegistry.create("nonexistent")

        error_msg = str(exc_info.value)
        assert "type-a" in error_msg
        assert "type-b" in error_msg


# =============================================================================
# Cache Behavior Tests
# =============================================================================


class TestCacheBehavior:
    """Test agent caching behavior."""

    def test_cache_hit_with_same_api_key(self, registered_mock_agent):
        """Test cache hit returns same instance with same API key."""
        from aragora.agents.registry import AgentRegistry

        agent1 = AgentRegistry.get_cached("mock-agent", name="api-agent", api_key="sk-same-key")
        agent2 = AgentRegistry.get_cached("mock-agent", name="api-agent", api_key="sk-same-key")

        assert agent1 is agent2

    def test_cache_miss_with_different_api_key(self, registered_mock_agent):
        """Test cache miss with different API keys."""
        from aragora.agents.registry import AgentRegistry

        agent1 = AgentRegistry.get_cached("mock-agent", name="api-agent", api_key="sk-key-1")
        agent2 = AgentRegistry.get_cached("mock-agent", name="api-agent", api_key="sk-key-2")

        assert agent1 is not agent2

    def test_cache_disabled_with_kwargs(self, registered_mock_agent):
        """Test cache is disabled when kwargs are provided."""
        from aragora.agents.registry import AgentRegistry, _agent_cache

        AgentRegistry.clear_cache()
        initial_size = len(_agent_cache)

        AgentRegistry.create(
            "mock-agent",
            name="kwarg-test",
            use_cache=True,
            custom_kwarg="value",
        )

        # Cache should not grow when kwargs are provided
        assert len(_agent_cache) == initial_size

    def test_cache_eviction_removes_oldest(self, mock_agent_class):
        """Test cache eviction removes oldest entry."""
        from aragora.agents.registry import AgentRegistry, _CACHE_MAX_SIZE, _agent_cache

        @AgentRegistry.register("eviction-agent", default_model="model")
        class EvictionAgent(mock_agent_class):
            pass

        # Fill cache to max
        for i in range(_CACHE_MAX_SIZE):
            AgentRegistry.create("eviction-agent", name=f"evict-{i}", use_cache=True)

        # Get reference to oldest key
        oldest_key = next(iter(_agent_cache.keys()))

        # Add one more
        AgentRegistry.create("eviction-agent", name="evict-overflow", use_cache=True)

        # Oldest should be evicted
        assert oldest_key not in _agent_cache
        assert len(_agent_cache) == _CACHE_MAX_SIZE

    def test_cache_stats_reports_correct_size(self, registered_mock_agent):
        """Test cache_stats reports correct size."""
        from aragora.agents.registry import AgentRegistry

        AgentRegistry.clear_cache()
        AgentRegistry.get_cached("mock-agent", name="stat-agent-1")
        AgentRegistry.get_cached("mock-agent", name="stat-agent-2")
        AgentRegistry.get_cached("mock-agent", name="stat-agent-3")

        stats = AgentRegistry.cache_stats()

        assert stats["size"] == 3

    def test_cache_stats_masks_long_api_key(self, registered_mock_agent):
        """Test cache_stats masks API keys longer than 8 chars."""
        from aragora.agents.registry import AgentRegistry

        AgentRegistry.clear_cache()
        AgentRegistry.get_cached(
            "mock-agent",
            name="masked-key-agent",
            api_key="sk-12345678901234567890",
        )

        stats = AgentRegistry.cache_stats()

        for key in stats["keys"]:
            api_key_field = key[4]
            if api_key_field:
                assert "..." in api_key_field
                assert len(api_key_field) < 20


# =============================================================================
# Local LLM Detection Tests
# =============================================================================


class TestDetectLocalAgents:
    """Test AgentRegistry.detect_local_agents method."""

    def test_detect_local_agents_returns_list(self):
        """Test detect_local_agents returns a list."""
        from aragora.agents.registry import AgentRegistry

        # Mock the detector
        mock_status = MagicMock()
        mock_server = MagicMock()
        mock_server.name = "ollama"
        mock_server.base_url = "http://localhost:11434"
        mock_server.models = ["llama3.2"]
        mock_server.available = True
        mock_server.default_model = "llama3.2"
        mock_server.version = "0.1.0"
        mock_status.servers = [mock_server]

        with patch("aragora.agents.registry._LocalLLMDetector") as MockDetector:
            mock_instance = MockDetector.return_value
            mock_instance.detect_all = AsyncMock(return_value=mock_status)

            result = AgentRegistry.detect_local_agents()

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["name"] == "ollama"
            assert result[0]["available"] is True

    def test_detect_local_agents_returns_empty_when_detector_unavailable(self):
        """Test detect_local_agents returns empty list when detector not available."""
        from aragora.agents.registry import AgentRegistry

        with patch("aragora.agents.registry._LocalLLMDetector", None):
            result = AgentRegistry.detect_local_agents()

            assert result == []

    def test_detect_local_agents_handles_multiple_servers(self):
        """Test detect_local_agents handles multiple servers."""
        from aragora.agents.registry import AgentRegistry

        mock_status = MagicMock()
        mock_ollama = MagicMock()
        mock_ollama.name = "ollama"
        mock_ollama.base_url = "http://localhost:11434"
        mock_ollama.models = ["llama3.2", "codellama"]
        mock_ollama.available = True
        mock_ollama.default_model = "llama3.2"
        mock_ollama.version = "0.1.0"

        mock_lm_studio = MagicMock()
        mock_lm_studio.name = "lm-studio"
        mock_lm_studio.base_url = "http://localhost:1234/v1"
        mock_lm_studio.models = ["mistral-7b"]
        mock_lm_studio.available = True
        mock_lm_studio.default_model = "mistral-7b"
        mock_lm_studio.version = None

        mock_status.servers = [mock_ollama, mock_lm_studio]

        with patch("aragora.agents.registry._LocalLLMDetector") as MockDetector:
            mock_instance = MockDetector.return_value
            mock_instance.detect_all = AsyncMock(return_value=mock_status)

            result = AgentRegistry.detect_local_agents()

            assert len(result) == 2
            assert result[0]["name"] == "ollama"
            assert result[1]["name"] == "lm-studio"


class TestGetLocalStatus:
    """Test AgentRegistry.get_local_status method."""

    def test_get_local_status_structure(self):
        """Test get_local_status returns expected structure."""
        from aragora.agents.registry import AgentRegistry

        mock_status = MagicMock()
        mock_status.any_available = True
        mock_status.total_models = 5
        mock_status.recommended_server = "ollama"
        mock_status.recommended_model = "llama3.2"
        mock_status.get_available_agents.return_value = ["ollama", "lm-studio"]

        mock_server = MagicMock()
        mock_server.name = "ollama"
        mock_server.base_url = "http://localhost:11434"
        mock_server.available = True
        mock_server.models = ["llama3.2"]
        mock_server.default_model = "llama3.2"
        mock_status.servers = [mock_server]

        with patch("aragora.agents.registry._LocalLLMDetector") as MockDetector:
            mock_instance = MockDetector.return_value
            mock_instance.detect_all = AsyncMock(return_value=mock_status)

            result = AgentRegistry.get_local_status()

            assert "any_available" in result
            assert "total_models" in result
            assert "recommended_server" in result
            assert "recommended_model" in result
            assert "available_agents" in result
            assert "servers" in result

    def test_get_local_status_when_no_detector(self):
        """Test get_local_status returns defaults when detector unavailable."""
        from aragora.agents.registry import AgentRegistry

        with patch("aragora.agents.registry._LocalLLMDetector", None):
            result = AgentRegistry.get_local_status()

            assert result["any_available"] is False
            assert result["total_models"] == 0
            assert result["recommended_server"] is None
            assert result["recommended_model"] is None
            assert result["available_agents"] == []
            assert result["servers"] == []

    def test_get_local_status_with_available_agents(self):
        """Test get_local_status includes available agents list."""
        from aragora.agents.registry import AgentRegistry

        mock_status = MagicMock()
        mock_status.any_available = True
        mock_status.total_models = 3
        mock_status.recommended_server = "ollama"
        mock_status.recommended_model = "llama3.2"
        mock_status.get_available_agents.return_value = ["ollama"]
        mock_status.servers = []

        with patch("aragora.agents.registry._LocalLLMDetector") as MockDetector:
            mock_instance = MockDetector.return_value
            mock_instance.detect_all = AsyncMock(return_value=mock_status)

            result = AgentRegistry.get_local_status()

            assert result["available_agents"] == ["ollama"]


# =============================================================================
# _run_async_in_thread Tests
# =============================================================================


class TestRunAsyncInThread:
    """Test _run_async_in_thread helper function."""

    def test_run_async_in_thread_executes_coroutine(self):
        """Test _run_async_in_thread executes async coroutine."""
        from aragora.agents.registry import _run_async_in_thread

        async def async_function():
            await asyncio.sleep(0)
            return "result"

        result = _run_async_in_thread(async_function())

        assert result == "result"

    def test_run_async_in_thread_handles_exception(self):
        """Test _run_async_in_thread propagates exceptions."""
        from aragora.agents.registry import _run_async_in_thread

        async def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            _run_async_in_thread(failing_function())

    def test_run_async_in_thread_with_async_value(self):
        """Test _run_async_in_thread with coroutine returning complex value."""
        from aragora.agents.registry import _run_async_in_thread

        async def complex_return():
            return {"key": "value", "list": [1, 2, 3]}

        result = _run_async_in_thread(complex_return())

        assert result == {"key": "value", "list": [1, 2, 3]}


# =============================================================================
# Registry Query Tests
# =============================================================================


class TestRegistryQueries:
    """Test registry query methods."""

    def test_list_all_includes_all_metadata(self, mock_agent_class):
        """Test list_all includes all metadata fields."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register(
            "metadata-agent",
            default_model="metadata-model",
            agent_type="CLI",
            requires="metadata-cli",
            env_vars="METADATA_KEY",
            description="Agent with full metadata",
        )
        class MetadataAgent(mock_agent_class):
            pass

        all_agents = AgentRegistry.list_all()

        assert "metadata-agent" in all_agents
        agent_info = all_agents["metadata-agent"]
        assert agent_info["type"] == "CLI"
        assert agent_info["requires"] == "metadata-cli"
        assert agent_info["env_vars"] == "METADATA_KEY"
        assert agent_info["description"] == "Agent with full metadata"
        assert agent_info["default_model"] == "metadata-model"

    def test_get_registered_types_returns_list(self, mock_agent_class):
        """Test get_registered_types returns a list."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register("list-type-1")
        class ListType1Agent(mock_agent_class):
            pass

        @AgentRegistry.register("list-type-2")
        class ListType2Agent(mock_agent_class):
            pass

        types = AgentRegistry.get_registered_types()

        assert isinstance(types, list)
        assert "list-type-1" in types
        assert "list-type-2" in types

    def test_get_spec_for_nonexistent_returns_none(self):
        """Test get_spec returns None for unregistered type."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("nonexistent-type")

        assert spec is None


# =============================================================================
# Allowed Type Validation Tests
# =============================================================================


class TestValidateAllowed:
    """Test validate_allowed method."""

    def test_validate_allowed_returns_boolean(self):
        """Test validate_allowed returns a boolean."""
        from aragora.agents.registry import AgentRegistry

        result = AgentRegistry.validate_allowed("demo")

        assert isinstance(result, bool)

    def test_validate_allowed_demo_is_allowed(self):
        """Test demo agent type is allowed."""
        from aragora.agents.registry import AgentRegistry

        assert AgentRegistry.validate_allowed("demo") is True

    def test_validate_allowed_anthropic_api_is_allowed(self):
        """Test anthropic-api agent type is allowed."""
        from aragora.agents.registry import AgentRegistry

        assert AgentRegistry.validate_allowed("anthropic-api") is True

    def test_validate_allowed_arbitrary_string_is_not_allowed(self):
        """Test arbitrary string is not allowed."""
        from aragora.agents.registry import AgentRegistry

        assert AgentRegistry.validate_allowed("arbitrary-evil-agent") is False

    def test_validate_allowed_empty_string_is_not_allowed(self):
        """Test empty string is not allowed."""
        from aragora.agents.registry import AgentRegistry

        assert AgentRegistry.validate_allowed("") is False


# =============================================================================
# register_all_agents Tests
# =============================================================================


class TestRegisterAllAgents:
    """Test register_all_agents function."""

    def test_register_all_agents_callable(self):
        """Test register_all_agents is callable."""
        from aragora.agents.registry import register_all_agents

        assert callable(register_all_agents)

    def test_register_all_agents_handles_import_errors(self):
        """Test register_all_agents handles import errors gracefully."""
        from aragora.agents.registry import AgentRegistry, register_all_agents

        # Save original registry
        original = AgentRegistry._registry.copy()
        AgentRegistry._registry.clear()

        try:
            # Should not raise even with missing modules
            register_all_agents()
        finally:
            # Restore
            AgentRegistry._registry.clear()
            AgentRegistry._registry.update(original)

    def test_register_all_agents_self_heals_cleared_registry(self):
        """A cleared registry is repopulated even when agent modules are cached.

        Regression test for #8277: under xdist a test that clears (or rebinds)
        AgentFactory._registry used to permanently break agent lookup for the
        rest of the worker, because aragora.agents.cli_agents stays cached in
        sys.modules so its @AgentRegistry.register decorators never re-run.
        """
        from aragora.agents.registry import AgentRegistry, register_all_agents

        register_all_agents()
        assert AgentRegistry.is_registered("claude")

        AgentRegistry.clear()
        assert not AgentRegistry.is_registered("claude")

        register_all_agents()
        assert AgentRegistry.is_registered("claude")
        assert AgentRegistry.is_registered("openai")

    def test_register_all_agents_self_heals_rebound_registry(self):
        """Healing also works when _registry was replaced with a new dict."""
        from aragora.agents.registry import AgentRegistry, register_all_agents

        register_all_agents()
        AgentRegistry._registry = {}

        register_all_agents()
        assert AgentRegistry.is_registered("claude")

    def test_register_all_agents_does_not_clobber_existing_entries(self):
        """Healing only fills gaps; deliberate overrides are preserved."""
        from aragora.agents.registry import AgentRegistry, RegistrySpec, register_all_agents

        register_all_agents()
        sentinel = RegistrySpec(
            name="claude",
            agent_class=object,
            default_model=None,
            default_name="claude",
            agent_type="CLI",
            requires=None,
            env_vars=None,
        )
        AgentRegistry._registry["claude"] = sentinel

        register_all_agents()
        assert AgentRegistry.get_spec("claude") is sentinel


# =============================================================================
# Module Exports Tests
# =============================================================================


class TestModuleExports:
    """Test module exports."""

    def test_registry_spec_in_all(self):
        """Test RegistrySpec is in __all__."""
        from aragora.agents import registry

        assert "RegistrySpec" in registry.__all__

    def test_agent_registry_in_all(self):
        """Test AgentRegistry is in __all__."""
        from aragora.agents import registry

        assert "AgentRegistry" in registry.__all__

    def test_register_all_agents_in_all(self):
        """Test register_all_agents is in __all__."""
        from aragora.agents import registry

        assert "register_all_agents" in registry.__all__

    def test_all_exports_importable(self):
        """Test all __all__ exports are importable."""
        from aragora.agents import registry

        for name in registry.__all__:
            assert hasattr(registry, name), f"Missing export: {name}"


# =============================================================================
# Agent Without Model Tests
# =============================================================================


class TestAgentWithoutModel:
    """Test agent creation when no model is specified."""

    def test_create_agent_no_default_model_no_provided_model(self, mock_agent_class):
        """Test creation when no default model and no model provided."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register("no-model-agent")
        class NoModelAgent(mock_agent_class):
            pass

        agent = AgentRegistry.create("no-model-agent")

        # Model should be None since not passed to constructor
        assert agent.model is None

    def test_create_agent_provides_model_when_specified(self, mock_agent_class):
        """Test model is provided when explicitly passed."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register("explicit-model-agent")
        class ExplicitModelAgent(mock_agent_class):
            pass

        agent = AgentRegistry.create("explicit-model-agent", model="explicit-model")

        assert agent.model == "explicit-model"


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_multiple_registrations_same_name_overwrites(self, mock_agent_class):
        """Test registering same name twice overwrites."""
        from aragora.agents.registry import AgentRegistry

        @AgentRegistry.register("overwrite-test", default_model="model-1")
        class FirstAgent(mock_agent_class):
            pass

        @AgentRegistry.register("overwrite-test", default_model="model-2")
        class SecondAgent(mock_agent_class):
            pass

        spec = AgentRegistry.get_spec("overwrite-test")
        assert spec is not None
        assert spec.default_model == "model-2"
        assert spec.agent_class is SecondAgent

    def test_cache_with_all_none_params(self, registered_mock_agent):
        """Test cache with all None parameters."""
        from aragora.agents.registry import AgentRegistry

        agent1 = AgentRegistry.get_cached(
            "mock-agent",
            name=None,
            role="proposer",
            model=None,
            api_key=None,
        )
        agent2 = AgentRegistry.get_cached(
            "mock-agent",
            name=None,
            role="proposer",
            model=None,
            api_key=None,
        )

        assert agent1 is agent2

    def test_create_falsy_name_uses_default(self, registered_mock_agent):
        """Test empty string name uses default."""
        from aragora.agents.registry import AgentRegistry

        agent = AgentRegistry.create("mock-agent", name="")

        # Empty string is falsy, should use default
        assert agent.name == "mock-agent"

    def test_cache_max_size_constant_exists(self):
        """Test _CACHE_MAX_SIZE constant exists."""
        from aragora.agents.registry import _CACHE_MAX_SIZE

        assert isinstance(_CACHE_MAX_SIZE, int)
        assert _CACHE_MAX_SIZE > 0

    def test_agent_cache_is_module_level_dict(self):
        """Test _agent_cache is a module-level dict."""
        from aragora.agents.registry import _agent_cache

        assert isinstance(_agent_cache, dict)


# =============================================================================
# Async Context Tests
# =============================================================================


class TestAsyncContextDetection:
    """Test async context detection for local LLM detection."""

    @pytest.mark.asyncio
    async def test_detect_local_agents_in_async_context(self):
        """Test detect_local_agents works when called from async context."""
        from aragora.agents.registry import AgentRegistry

        mock_status = MagicMock()
        mock_status.servers = []

        with patch("aragora.agents.registry._LocalLLMDetector") as MockDetector:
            mock_instance = MockDetector.return_value
            mock_instance.detect_all = AsyncMock(return_value=mock_status)

            # Call from async context
            result = AgentRegistry.detect_local_agents()

            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_local_status_in_async_context(self):
        """Test get_local_status works when called from async context."""
        from aragora.agents.registry import AgentRegistry

        mock_status = MagicMock()
        mock_status.any_available = False
        mock_status.total_models = 0
        mock_status.recommended_server = None
        mock_status.recommended_model = None
        mock_status.get_available_agents.return_value = []
        mock_status.servers = []

        with patch("aragora.agents.registry._LocalLLMDetector") as MockDetector:
            mock_instance = MockDetector.return_value
            mock_instance.detect_all = AsyncMock(return_value=mock_status)

            # Call from async context
            result = AgentRegistry.get_local_status()

            assert isinstance(result, dict)
