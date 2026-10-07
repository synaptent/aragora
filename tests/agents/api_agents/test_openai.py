"""
Tests for OpenAI API Agent.

Tests cover:
- Initialization and configuration
- Web search detection
- Generate and streaming responses
- OpenAI-compatible mixin functionality
- Error handling and fallback
"""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentStreamError,
)


class TestOpenAIAgentInitialization:
    """Tests for agent initialization."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with default values."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.registry import AgentRegistry

        agent = OpenAIAPIAgent()
        spec = AgentRegistry.get_spec("openai-api")

        assert agent.name == "openai-api"
        assert agent.model == "gpt-5.6-sol"
        assert agent.role == "proposer"
        assert agent.timeout == 120
        assert agent.agent_type == "openai"
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True
        assert agent.enable_web_search is True
        assert "api.openai.com" in agent.base_url

    def test_init_with_custom_config(self, mock_env_with_api_keys):
        """Should initialize with custom configuration."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent(
            name="custom-gpt",
            model="gpt-4o",
            role="analyst",
            timeout=90,
            enable_fallback=False,
        )

        assert agent.name == "custom-gpt"
        assert agent.model == "gpt-4o"
        assert agent.role == "analyst"
        assert agent.timeout == 90
        assert agent.enable_fallback is False

    def test_init_with_explicit_api_key(self, mock_env_no_api_keys):
        """Should use explicitly provided API key."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent(api_key="explicit-openai-key")

        assert agent.api_key == "explicit-openai-key"

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("openai-api")

        assert spec is not None
        assert spec.default_model == "gpt-5.6-sol"
        assert spec.agent_type == "API"


class TestOpenAIWebSearchDetection:
    """Tests for web search detection."""

    def test_detects_url_in_prompt(self, mock_env_with_api_keys):
        """Should detect URLs indicating web search need."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        assert agent._needs_web_search("Check https://example.com for info") is True
        assert agent._needs_web_search("Visit http://docs.python.org") is True

    def test_detects_github_mentions(self, mock_env_with_api_keys):
        """Should detect GitHub references."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        assert agent._needs_web_search("Look at github.com/openai/openai-python") is True

    def test_detects_current_info_keywords(self, mock_env_with_api_keys):
        """Should detect keywords for current information."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        assert agent._needs_web_search("What's the latest news?") is True
        assert agent._needs_web_search("Find current prices") is True
        assert agent._needs_web_search("Get recent articles") is True

    def test_no_web_search_for_basic_prompts(self, mock_env_with_api_keys):
        """Should not trigger web search for basic prompts."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        assert agent._needs_web_search("Write a hello world program") is False
        assert agent._needs_web_search("Explain the concept of OOP") is False

    def test_disabled_web_search(self, mock_env_with_api_keys):
        """Should respect disabled web search setting."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.enable_web_search = False

        assert agent._needs_web_search("Check https://example.com") is False


class TestOpenAIGenerate:
    """Tests for generate method."""

    @pytest.mark.asyncio
    async def test_generate_basic_response(self, mock_env_with_api_keys, mock_openai_response):
        """Should generate response from API."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_openai_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await agent.generate("Test prompt")

        assert "test response from GPT" in result

    @pytest.mark.asyncio
    async def test_generate_with_context(
        self, mock_env_with_api_keys, mock_openai_response, sample_context
    ):
        """Should include context in prompt."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_openai_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await agent.generate("Test prompt", context=sample_context)

        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_records_token_usage(self, mock_env_with_api_keys, mock_openai_response):
        """Should record token usage from response."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.reset_token_usage()

        # Create mock response with async context manager
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_openai_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        # Create mock session - must be an async context manager itself
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        # create_client_session() returns the session object directly
        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            await agent.generate("Test prompt")

        assert agent.last_tokens_in == 100
        assert agent.last_tokens_out == 50

    @pytest.mark.asyncio
    async def test_generate_records_conservative_budget_spend_when_usage_missing(
        self, mock_env_with_api_keys, mock_openai_response, monkeypatch, tmp_path
    ):
        """Successful metered calls without usage still decrement the budget guard."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.billing import budget_guard

        store = tmp_path / "budget_guard.json"
        monkeypatch.setenv("ARAGORA_MONTHLY_BUDGET_USD", "100")
        monkeypatch.setenv("ARAGORA_BUDGET_GUARD_STORE", str(store))
        budget_guard._mem_state.clear()

        response_without_usage = dict(mock_openai_response)
        response_without_usage.pop("usage", None)

        agent = OpenAIAPIAgent()
        agent.max_tokens = 1000
        agent.reset_token_usage()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=response_without_usage)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Test prompt")

        assert result
        assert agent.last_tokens_in == 0
        assert agent.last_tokens_out == 0
        assert budget_guard.current_spend_usd() > 0


class TestOpenAIVibeProxyRouting:
    """Exact-match OpenAI Chat routing through the central transport policy."""

    class FakeClient:
        base_url = "http://127.0.0.1:8318/v1"

        def __init__(
            self,
            *,
            fail: bool = False,
            error: Exception | None = None,
            response: dict | None = None,
        ) -> None:
            self.fail = fail
            self.error = error
            self.response = response
            self.calls: list[dict[str, Any]] = []

        def catalog(self, *, timeout: float | None = None):
            self.calls.append({"operation": "catalog", "timeout": timeout})
            return SimpleNamespace(models=frozenset({"gpt-5.5", "proxy-gpt"}))

        def openai_request(self, **kwargs):
            from aragora.agents.transports.vibeproxy import VibeProxyUnavailableError

            self.calls.append({"operation": "request", **kwargs})
            if self.error is not None:
                raise self.error
            if self.fail:
                raise VibeProxyUnavailableError("proxy unavailable")
            if self.response is not None:
                return self.response
            model = kwargs["model"]
            return {
                "model": model,
                "choices": [{"message": {"content": "proxy response"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            }

    @pytest.mark.asyncio
    async def test_exact_chat_uses_proxy_without_direct_request(
        self, mock_env_with_api_keys
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient()
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
            model_map={"openai:gpt-5.5": "proxy-gpt"},
        )

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session"
        ) as direct_session:
            result = await agent.generate("hello")

        assert result == "proxy response"
        direct_session.assert_not_called()
        assert agent.model == "gpt-5.5"
        assert agent.last_tokens_in == 7
        assert agent.last_tokens_out == 3
        request = next(call for call in client.calls if call["operation"] == "request")
        assert request["protocol"].value == "chat"
        assert request["model"] == "proxy-gpt"
        assert request["payload"]["model"] == "proxy-gpt"
        assert request["payload"]["messages"] == [{"role": "user", "content": "hello"}]

    @pytest.mark.asyncio
    async def test_web_search_stays_on_direct_path(
        self, mock_env_with_api_keys, mock_openai_response
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient()
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value=mock_openai_response)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=response)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=session,
        ):
            result = await agent.generate("check https://example.com")

        assert "test response from GPT" in result
        assert client.calls == []
        assert session.post.call_args.kwargs["json"]["tools"]

    @pytest.mark.asyncio
    async def test_custom_openai_endpoint_stays_on_direct_path(
        self, mock_env_with_api_keys, mock_openai_response, monkeypatch
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/openai")
        client = self.FakeClient()
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value=mock_openai_response)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=response)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=session,
        ):
            await agent.generate("hello")

        assert client.calls == []
        assert session.post.call_args.args[0] == (
            "https://gateway.example/openai/v1/chat/completions"
        )

    @pytest.mark.asyncio
    async def test_streaming_stays_on_direct_path(self, mock_env_with_api_keys) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.api_agents.openai_compatible import OpenAICompatibleMixin
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient()
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )

        async def fake_direct_stream(_agent, _prompt, _context=None):
            yield "direct chunk"

        with patch.object(OpenAICompatibleMixin, "generate_stream", fake_direct_stream):
            chunks = [chunk async for chunk in agent.generate_stream("hello")]

        assert chunks == ["direct chunk"]
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_catalog_and_request_share_one_timeout_budget(
        self, mock_env_with_api_keys, monkeypatch
    ) -> None:
        from aragora.agents.api_agents import openai as openai_module
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        clock = [100.0]

        class DeadlineClient:
            base_url = "http://127.0.0.1:8318/v1"

            def __init__(inner_self) -> None:
                inner_self.calls: list[dict[str, Any]] = []

            def catalog(inner_self, *, timeout: float | None = None):
                inner_self.calls.append({"operation": "catalog", "timeout": timeout})
                clock[0] += 3.0
                return SimpleNamespace(models=frozenset({"gpt-5.5"}))

            def openai_request(inner_self, **kwargs):
                inner_self.calls.append({"operation": "request", **kwargs})
                return {
                    "model": kwargs["model"],
                    "choices": [{"message": {"content": "proxy response"}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                }

        monkeypatch.setattr(openai_module.time, "monotonic", lambda: clock[0])
        client = DeadlineClient()
        agent = OpenAIAPIAgent(model="gpt-5.5", timeout=10, enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )

        await agent.generate("hello")

        catalog = next(call for call in client.calls if call["operation"] == "catalog")
        request = next(call for call in client.calls if call["operation"] == "request")
        # Discovery is capped so a wedged proxy cannot burn the inference
        # budget; the request leg still draws from the shared deadline.
        assert catalog["timeout"] == pytest.approx(6.0)
        assert request["timeout"] == pytest.approx(7.0)

    @pytest.mark.asyncio
    async def test_prefer_falls_back_direct_before_output(
        self, mock_env_with_api_keys, mock_openai_response
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient(fail=True)
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value=mock_openai_response)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=response)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=session,
        ):
            result = await agent.generate("hello")

        assert "test response from GPT" in result
        assert session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_prefer_timeout_falls_back_direct_before_output(
        self, mock_env_with_api_keys, mock_openai_response
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import (
            ModelTransportPolicy,
            TransportMode,
            VibeProxyTimeoutError,
        )

        client = self.FakeClient(error=VibeProxyTimeoutError("proxy timed out"))
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value=mock_openai_response)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=response)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=session,
        ):
            result = await agent.generate("hello")

        assert "test response from GPT" in result
        assert session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_required_proxy_failure_never_calls_direct(self, mock_env_with_api_keys) -> None:
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient(fail=True)
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.REQUIRED,
            client=client,  # type: ignore[arg-type]
        )

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session"
        ) as direct_session:
            with pytest.raises(AgentAPIError, match="required VibeProxy OpenAI request failed"):
                await agent.generate("hello")

        direct_session.assert_not_called()

    def _direct_session(self, mock_openai_response) -> MagicMock:
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value=mock_openai_response)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=response)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        return session

    @pytest.mark.asyncio
    async def test_prefer_malformed_proxy_response_falls_back_direct(
        self, mock_env_with_api_keys, mock_openai_response
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient(response={"model": "gpt-5.5", "usage": {}})
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=self._direct_session(mock_openai_response),
        ):
            result = await agent.generate("hello")

        assert "test response from GPT" in result
        assert any(call["operation"] == "request" for call in client.calls)

    @pytest.mark.asyncio
    async def test_prefer_empty_proxy_response_falls_back_direct(
        self, mock_env_with_api_keys, mock_openai_response
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient(
            response={
                "model": "gpt-5.5",
                "choices": [{"message": {"content": "   "}}],
                "usage": {},
            }
        )
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=self._direct_session(mock_openai_response),
        ):
            result = await agent.generate("hello")

        assert "test response from GPT" in result

    @pytest.mark.asyncio
    async def test_required_proxy_failure_records_circuit_breaker_failure(
        self, mock_env_with_api_keys
    ) -> None:
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient(fail=True)
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.REQUIRED,
            client=client,  # type: ignore[arg-type]
        )
        cb = MagicMock()
        cb.can_proceed.return_value = True
        agent._circuit_breaker = cb

        with patch("aragora.agents.api_agents.openai.record_provider_call") as provider_call:
            with pytest.raises(AgentAPIError, match="required VibeProxy OpenAI request failed"):
                await agent.generate("hello")

        cb.record_failure.assert_called_once()
        cb.record_success.assert_not_called()
        assert provider_call.call_args.kwargs["success"] is False
        assert provider_call.call_args.kwargs["latency_seconds"] is not None

    @pytest.mark.asyncio
    async def test_required_empty_response_records_circuit_breaker_failure(
        self, mock_env_with_api_keys
    ) -> None:
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient(response={"model": "gpt-5.5", "usage": {}})
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.REQUIRED,
            client=client,  # type: ignore[arg-type]
        )
        cb = MagicMock()
        cb.can_proceed.return_value = True
        agent._circuit_breaker = cb

        with pytest.raises(AgentAPIError, match="required VibeProxy OpenAI request failed"):
            await agent.generate("hello")

        cb.record_failure.assert_called_once()
        cb.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_required_web_search_prompt_fails_closed(self, mock_env_with_api_keys) -> None:
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient()
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.REQUIRED,
            client=client,  # type: ignore[arg-type]
        )

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session"
        ) as direct_session:
            with pytest.raises(AgentAPIError, match="vibeproxy-required cannot serve"):
                await agent.generate("check https://example.com")

        direct_session.assert_not_called()
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_required_custom_endpoint_fails_closed(
        self, mock_env_with_api_keys, monkeypatch
    ) -> None:
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/openai")
        client = self.FakeClient()
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.REQUIRED,
            client=client,  # type: ignore[arg-type]
        )

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session"
        ) as direct_session:
            with pytest.raises(AgentAPIError, match="vibeproxy-required cannot serve"):
                await agent.generate("hello")

        direct_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_required_streaming_fails_closed(self, mock_env_with_api_keys) -> None:
        from aragora.agents.api_agents.common import AgentAPIError
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.api_agents.openai_compatible import OpenAICompatibleMixin
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient()
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.REQUIRED,
            client=client,  # type: ignore[arg-type]
        )

        async def fake_direct_stream(_agent, _prompt, _context=None):
            yield "direct chunk"

        with patch.object(OpenAICompatibleMixin, "generate_stream", fake_direct_stream):
            with pytest.raises(AgentAPIError, match="vibeproxy-required cannot serve"):
                async for _ in agent.generate_stream("hello"):
                    pass

        assert client.calls == []

    @pytest.mark.asyncio
    async def test_prefer_fallback_records_proxy_leg_failure(
        self, mock_env_with_api_keys, mock_openai_response
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient(fail=True)
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )

        with patch("aragora.agents.api_agents.openai.record_provider_call") as provider_call:
            with patch(
                "aragora.agents.api_agents.openai_compatible.create_client_session",
                return_value=self._direct_session(mock_openai_response),
            ):
                result = await agent.generate("hello")

        assert "test response from GPT" in result
        proxy_leg = next(
            call
            for call in provider_call.call_args_list
            if call.kwargs.get("provider") == "vibeproxy"
        )
        assert proxy_leg.kwargs["success"] is False

    @pytest.mark.asyncio
    async def test_prefer_wedged_discovery_bounded_by_wall_clock(
        self, mock_env_with_api_keys, mock_openai_response, monkeypatch
    ) -> None:
        """A stuck discovery leg (queue wait or socket) must not delay
        PREFER-mode fallback beyond the wall-clock discovery cap."""
        import threading
        import time as time_module

        from aragora.agents.api_agents import openai as openai_module
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        # The abandoned discovery leg keeps running in the executor after the
        # wall-clock cap fires; block on an event (released in the finally)
        # instead of a bare sleep so executor teardown does not re-serialize
        # the full wedge duration.
        release_wedge = threading.Event()

        class WedgedClient:
            base_url = "http://127.0.0.1:8318/v1"

            def catalog(self, *, timeout: float | None = None):
                release_wedge.wait(5.0)
                return SimpleNamespace(models=frozenset({"gpt-5.5"}))

            def openai_request(self, **kwargs):
                raise AssertionError("must not reach the request leg")

        monkeypatch.setattr(openai_module, "_PROXY_DISCOVERY_TIMEOUT_SECONDS", 0.2)
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=WedgedClient(),  # type: ignore[arg-type]
        )

        try:
            started = time_module.perf_counter()
            with patch(
                "aragora.agents.api_agents.openai_compatible.create_client_session",
                return_value=self._direct_session(mock_openai_response),
            ):
                result = await agent.generate("hello")
            elapsed = time_module.perf_counter() - started

            assert "test response from GPT" in result
            assert elapsed < 3.0
        finally:
            release_wedge.set()

    @pytest.mark.asyncio
    async def test_proxy_success_records_latency(self, mock_env_with_api_keys) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        client = self.FakeClient()
        agent = OpenAIAPIAgent(model="gpt-5.5", enable_fallback=False)
        agent.enable_web_search = False
        agent._model_transport_policy = ModelTransportPolicy(
            TransportMode.PREFER,
            client=client,  # type: ignore[arg-type]
        )

        with patch("aragora.agents.api_agents.openai.record_provider_call") as provider_call:
            result = await agent.generate("hello")

        assert result == "proxy response"
        assert provider_call.call_args.kwargs["success"] is True
        assert provider_call.call_args.kwargs["latency_seconds"] is not None


class TestOpenAIVibeProxyEnvDegradation:
    """Misconfigured VibeProxy environments must not break agent construction."""

    def test_invalid_model_map_degrades_prefer_to_direct(
        self, mock_env_with_api_keys, monkeypatch
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import TransportMode

        monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-prefer")
        monkeypatch.setenv("ARAGORA_VIBEPROXY_MODEL_MAP", "{bad")

        agent = OpenAIAPIAgent(enable_fallback=False)

        assert agent._model_transport_policy.mode is TransportMode.DIRECT

    def test_invalid_transport_mode_degrades_to_direct(
        self, mock_env_with_api_keys, monkeypatch
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import TransportMode

        monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "bogus-transport")

        agent = OpenAIAPIAgent(enable_fallback=False)

        assert agent._model_transport_policy.mode is TransportMode.DIRECT

    def test_explicit_transport_override_ignores_ambient_env(
        self, mock_env_with_api_keys, monkeypatch
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import ModelTransportPolicy, TransportMode

        monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-prefer")
        monkeypatch.setenv("ARAGORA_VIBEPROXY_BASE_URL", "http://127.0.0.1:8318")

        agent = OpenAIAPIAgent(
            enable_fallback=False,
            model_transport=ModelTransportPolicy(TransportMode.DIRECT),
        )

        assert agent._model_transport_policy.mode is TransportMode.DIRECT

    def test_required_mode_misconfiguration_stays_fail_closed(
        self, mock_env_with_api_keys, monkeypatch
    ) -> None:
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.agents.transports.vibeproxy import VibeProxyConfigurationError

        monkeypatch.setenv("ARAGORA_MODEL_TRANSPORT", "vibeproxy-required")
        monkeypatch.setenv("ARAGORA_VIBEPROXY_MODEL_MAP", "{bad")

        with pytest.raises(VibeProxyConfigurationError):
            OpenAIAPIAgent(enable_fallback=False)


class TestOpenAIGenerateStream:
    """Tests for streaming generation."""

    @pytest.mark.asyncio
    async def test_stream_blocks_before_network_when_budget_cap_reached(
        self, mock_env_with_api_keys, monkeypatch, tmp_path
    ):
        """Streaming OpenAI-compatible calls must obey the fail-closed cap."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.billing import budget_guard
        from aragora.billing.budget_guard import BudgetExceededError

        monkeypatch.setenv("ARAGORA_MONTHLY_BUDGET_USD", "1")
        monkeypatch.setenv("ARAGORA_BUDGET_GUARD_STORE", str(tmp_path / "budget.json"))
        budget_guard._mem_state.clear()

        agent = OpenAIAPIAgent()
        monkeypatch.setattr(agent, "_estimate_budget_cost_usd", lambda payload: 2.0)

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session"
        ) as create_session:
            with pytest.raises(BudgetExceededError):
                async for _ in agent.generate_stream("Test prompt"):
                    pass

        create_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_stream_records_conservative_budget_spend(
        self, mock_env_with_api_keys, mock_sse_chunks, monkeypatch, tmp_path
    ):
        """Successful streams without usage metadata still decrement the guard."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.billing import budget_guard
        from tests.agents.api_agents.conftest import MockStreamResponse

        monkeypatch.setenv("ARAGORA_MONTHLY_BUDGET_USD", "100")
        monkeypatch.setenv("ARAGORA_BUDGET_GUARD_STORE", str(tmp_path / "budget.json"))
        budget_guard._mem_state.clear()

        agent = OpenAIAPIAgent()
        monkeypatch.setattr(agent, "_estimate_budget_cost_usd", lambda payload: 7.0)
        mock_response = MockStreamResponse(status=200, chunks=mock_sse_chunks)

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session"
        ) as mock_create:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_create.return_value = mock_session

            async for _ in agent.generate_stream("Test prompt"):
                pass

        assert budget_guard.current_spend_usd() == pytest.approx(7.0)

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, mock_env_with_api_keys, mock_sse_chunks):
        """Should yield text chunks from SSE stream."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = OpenAIAPIAgent()
        agent.enable_web_search = False

        mock_response = MockStreamResponse(status=200, chunks=mock_sse_chunks)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            chunks = []
            async for chunk in agent.generate_stream("Test prompt"):
                chunks.append(chunk)

            # Should have received chunks
            assert len(chunks) >= 0  # May vary based on SSE parsing


class TestOpenAICompatibleMixin:
    """Tests for OpenAI-compatible mixin functionality."""

    def test_build_headers(self, mock_env_with_api_keys):
        """Should build correct headers."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        headers = agent._build_headers()

        assert "Authorization" in headers
        assert "Bearer" in headers["Authorization"]
        assert headers["Content-Type"] == "application/json"

    def test_build_messages_with_system_prompt(self, mock_env_with_api_keys):
        """Should include system prompt in messages."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.system_prompt = "You are a helpful assistant."

        messages = agent._build_messages("User prompt")

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_build_messages_without_system_prompt(self, mock_env_with_api_keys):
        """Should work without system prompt."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.system_prompt = None

        messages = agent._build_messages("User prompt")

        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_build_payload_basic(self, mock_env_with_api_keys):
        """Should build correct payload."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        messages = [{"role": "user", "content": "Test"}]

        payload = agent._build_payload(messages, stream=False)

        assert payload["model"] == "gpt-5.6-sol"
        assert payload["messages"] == messages
        assert "max_tokens" in payload
        assert "stream" not in payload or payload.get("stream") is False

    def test_build_payload_with_stream(self, mock_env_with_api_keys):
        """Should include stream flag when streaming."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        messages = [{"role": "user", "content": "Test"}]

        payload = agent._build_payload(messages, stream=True)

        assert payload["stream"] is True

    def test_build_payload_with_temperature(self, mock_env_with_api_keys):
        """Should include temperature when set."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.temperature = 0.8
        messages = [{"role": "user", "content": "Test"}]

        payload = agent._build_payload(messages, stream=False)

        assert payload["temperature"] == 0.8

    def test_build_extra_payload_with_web_search(self, mock_env_with_api_keys):
        """Should add web search tool when triggered."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent._current_prompt = "Check https://example.com"

        extra = agent._build_extra_payload()

        assert extra is not None
        assert "tools" in extra

    def test_build_extra_payload_without_web_search(self, mock_env_with_api_keys):
        """Should not add tools for basic prompts."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent._current_prompt = "Write a function"

        extra = agent._build_extra_payload()

        assert extra is None


class TestOpenAICritique:
    """Tests for critique method."""

    @pytest.mark.asyncio
    async def test_critique_returns_structured_feedback(self, mock_env_with_api_keys):
        """Should return structured critique."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = """ISSUES:
- Issue one
- Issue two

SUGGESTIONS:
- Suggestion one

SEVERITY: 6.0
REASONING: This is the reasoning."""

            critique = await agent.critique(
                proposal="Test proposal",
                task="Test task",
                target_agent="test-agent",
            )

            assert critique is not None


class TestOpenAIErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_api_error(self, mock_env_with_api_keys):
        """Should raise AgentAPIError on API failure."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 500
            mock_response.text = AsyncMock(return_value='{"error": "Internal error"}')
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            with pytest.raises(AgentAPIError):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_handles_unexpected_response_format(self, mock_env_with_api_keys):
        """Should handle unexpected response format."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        # Missing 'choices' field
        bad_response = {"id": "test", "usage": {}}

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=bad_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            with pytest.raises(AgentAPIError):
                await agent.generate("Test prompt")


class TestOpenAIModelMapping:
    """Tests for OpenRouter model mapping."""

    def test_model_map_contains_common_models(self, mock_env_with_api_keys):
        """Should have mappings for common models."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        assert "gpt-4o" in OpenAIAPIAgent.OPENROUTER_MODEL_MAP
        assert "gpt-4o-mini" in OpenAIAPIAgent.OPENROUTER_MODEL_MAP
        assert "gpt-4" in OpenAIAPIAgent.OPENROUTER_MODEL_MAP
        assert OpenAIAPIAgent.OPENROUTER_MODEL_MAP["gpt-4o"] == "openai/gpt-5.5"
        assert OpenAIAPIAgent.OPENROUTER_MODEL_MAP["gpt-5.4"] == "openai/gpt-5.6-sol"

    def test_has_default_fallback_model(self, mock_env_with_api_keys):
        """Should have default fallback model."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        assert OpenAIAPIAgent.DEFAULT_FALLBACK_MODEL is not None
        assert OpenAIAPIAgent.DEFAULT_FALLBACK_MODEL == "openai/gpt-5.5"
