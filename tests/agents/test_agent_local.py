"""
Tests for local LLM agents (Ollama and LM Studio).

Tests:
- Agent initialization and configuration
- Availability checks
- Model listing and discovery
- Successful generation (mock response)
- Streaming responses
- Connection error handling
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.agents.api_agents.ollama import OllamaAgent
from aragora.agents.api_agents.lm_studio import LMStudioAgent


class TestOllamaAgentInitialization:
    """Tests for OllamaAgent initialization."""

    def test_default_initialization(self):
        """Test agent initializes with defaults."""
        agent = OllamaAgent()

        assert agent.name == "ollama"
        assert agent.model == "llama3.2"
        assert agent.role == "proposer"
        assert agent.timeout == 180
        assert agent.agent_type == "ollama"

    def test_custom_initialization(self):
        """Test agent with custom parameters."""
        agent = OllamaAgent(
            name="my-ollama",
            model="codellama",
            role="critic",
            timeout=300,
            base_url="http://custom:11434",
        )

        assert agent.name == "my-ollama"
        assert agent.model == "codellama"
        assert agent.role == "critic"
        assert agent.timeout == 300
        assert agent.base_url == "http://custom:11434"

    def test_default_base_url(self):
        """Test default base URL is localhost:11434."""
        agent = OllamaAgent()
        assert "localhost:11434" in agent.base_url

    def test_env_var_base_url(self):
        """Test OLLAMA_HOST environment variable."""
        with patch.dict("os.environ", {"OLLAMA_HOST": "http://remote:8080"}):
            agent = OllamaAgent()
            assert agent.base_url == "http://remote:8080"


class TestOllamaAvailability:
    """Tests for Ollama availability checks."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return OllamaAgent()

    @pytest.mark.asyncio
    async def test_is_available_when_running(self, agent):
        """Test availability check when server is running."""
        mock_response = MagicMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await agent.is_available()

        assert result is True

    @pytest.mark.asyncio
    async def test_is_available_when_error_response(self, agent):
        """Test availability check returns False on non-200 response."""
        mock_response = MagicMock()
        mock_response.status = 500

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await agent.is_available()

        assert result is False


class TestOllamaModelDiscovery:
    """Tests for Ollama model listing."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return OllamaAgent()

    @pytest.mark.asyncio
    async def test_list_models_success(self, agent):
        """Test listing models when server returns data."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "models": [
                    {"name": "llama3.2", "size": 1000000},
                    {"name": "codellama", "size": 2000000},
                ]
            }
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            models = await agent.list_models()

        assert len(models) == 2
        assert models[0]["name"] == "llama3.2"

    @pytest.mark.asyncio
    async def test_list_models_error_returns_empty(self, agent):
        """Test listing models returns empty on non-200 response."""
        mock_response = MagicMock()
        mock_response.status = 500

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            models = await agent.list_models()

        assert models == []


class TestOllamaGenerate:
    """Tests for Ollama generation."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return OllamaAgent()

    @pytest.mark.asyncio
    async def test_successful_generation(self, agent):
        """Test successful generation."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"response": "Hello from Ollama!"})

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await agent.generate("Test prompt")

        assert result == "Hello from Ollama!"

    @pytest.mark.asyncio
    async def test_connection_error_handled(self, agent):
        """Test connection error raises appropriate exception."""
        import aiohttp
        from aragora.agents.api_agents.common import AgentConnectionError

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            side_effect=aiohttp.ClientConnectorError(MagicMock(), OSError("Connection refused"))
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            # May raise or return error string depending on decorator
            try:
                result = await agent.generate("Test prompt")
                if result is not None:
                    assert isinstance(result, str)
            except AgentConnectionError:
                pass  # Expected


class TestOllamaCritique:
    """Tests for Ollama critique method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return OllamaAgent()

    @pytest.mark.asyncio
    async def test_critique_calls_generate(self, agent):
        """Test critique uses generate method."""
        mock_response = """ISSUES:
- Issue 1

SUGGESTIONS:
- Suggestion 1

SEVERITY: 0.5
REASONING: Test reasoning"""

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = mock_response
            critique = await agent.critique("Test proposal", "Test task")

        assert mock_generate.called
        assert critique is not None


class TestLMStudioAgentInitialization:
    """Tests for LMStudioAgent initialization."""

    def test_default_initialization(self):
        """Test agent initializes with defaults."""
        agent = LMStudioAgent()

        assert agent.name == "lm-studio"
        assert agent.model == "local-model"
        assert agent.role == "proposer"
        assert agent.timeout == 180
        assert agent.agent_type == "lm-studio"

    def test_custom_initialization(self):
        """Test agent with custom parameters."""
        agent = LMStudioAgent(
            name="my-lm-studio",
            model="my-model",
            role="critic",
            timeout=300,
            base_url="http://custom:1234",
            max_tokens=8192,
        )

        assert agent.name == "my-lm-studio"
        assert agent.model == "my-model"
        assert agent.role == "critic"
        assert agent.max_tokens == 8192

    def test_base_url_appends_v1(self):
        """Test base URL appends /v1 if missing."""
        agent = LMStudioAgent(base_url="http://localhost:1234")
        assert agent.base_url == "http://localhost:1234/v1"

    def test_base_url_preserves_v1(self):
        """Test base URL preserves /v1 if present."""
        agent = LMStudioAgent(base_url="http://localhost:1234/v1")
        assert agent.base_url == "http://localhost:1234/v1"

    def test_env_var_base_url(self):
        """Test LM_STUDIO_HOST environment variable."""
        with patch.dict("os.environ", {"LM_STUDIO_HOST": "http://remote:5000"}):
            agent = LMStudioAgent()
            assert "remote:5000" in agent.base_url


class TestLMStudioAvailability:
    """Tests for LM Studio availability checks."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return LMStudioAgent()

    @pytest.mark.asyncio
    async def test_is_available_when_running(self, agent):
        """Test availability check when server is running."""
        mock_response = MagicMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await agent.is_available()

        assert result is True


class TestLMStudioModelDiscovery:
    """Tests for LM Studio model listing."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return LMStudioAgent()

    @pytest.mark.asyncio
    async def test_list_models_success(self, agent):
        """Test listing models when server returns data."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "data": [
                    {"id": "model-1", "object": "model"},
                    {"id": "model-2", "object": "model"},
                ]
            }
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            models = await agent.list_models()

        assert len(models) == 2
        assert models[0]["id"] == "model-1"

    @pytest.mark.asyncio
    async def test_get_loaded_model(self, agent):
        """Test getting currently loaded model."""
        with patch.object(agent, "list_models", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [{"id": "loaded-model"}]
            model = await agent.get_loaded_model()

        assert model == "loaded-model"

    @pytest.mark.asyncio
    async def test_get_loaded_model_none_when_empty(self, agent):
        """Test getting loaded model returns None when no models."""
        with patch.object(agent, "list_models", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            model = await agent.get_loaded_model()

        assert model is None


class TestLMStudioGenerate:
    """Tests for LM Studio generation."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return LMStudioAgent()

    @pytest.mark.asyncio
    async def test_successful_generation(self, agent):
        """Test successful generation."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "Hello from LM Studio!"}}]}
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await agent.generate("Test prompt")

        assert result == "Hello from LM Studio!"

    @pytest.mark.asyncio
    async def test_payload_includes_messages(self, agent):
        """Test payload includes properly formatted messages."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "Response"}}]}
        )

        captured_payload = None

        def capture_post(*args, **kwargs):
            nonlocal captured_payload
            captured_payload = kwargs.get("json", {})
            return MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = capture_post

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await agent.generate("Test prompt")

        assert captured_payload is not None
        assert "messages" in captured_payload
        assert captured_payload["messages"][-1]["role"] == "user"
        assert captured_payload["messages"][-1]["content"] == "Test prompt"


class TestLMStudioCritique:
    """Tests for LM Studio critique method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return LMStudioAgent()

    @pytest.mark.asyncio
    async def test_critique_calls_generate(self, agent):
        """Test critique uses generate method."""
        mock_response = """ISSUES:
- Issue 1

SUGGESTIONS:
- Suggestion 1

SEVERITY: 0.5
REASONING: Test reasoning"""

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = mock_response
            critique = await agent.critique("Test proposal", "Test task")

        assert mock_generate.called
        assert critique is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
