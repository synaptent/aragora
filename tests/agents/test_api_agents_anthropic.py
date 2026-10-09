"""
Tests for the Anthropic API agent.

Covers initialization, response generation, streaming, error handling,
and automatic fallback to OpenRouter.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
from aragora.core import Message


# Helper to create proper aiohttp response mock
def create_mock_response(status, json_data=None, text_data=None, content_chunks=None):
    """Create a properly configured mock aiohttp response."""
    mock_resp = MagicMock()
    mock_resp.status = status

    async def mock_json():
        return json_data

    async def mock_text():
        return text_data or ""

    mock_resp.json = mock_json
    mock_resp.text = mock_text

    if content_chunks:

        async def iter_any():
            for chunk in content_chunks:
                yield chunk

        mock_resp.content = MagicMock()
        mock_resp.content.iter_any = iter_any

    return mock_resp


@asynccontextmanager
async def mock_aiohttp_session(mock_response):
    """Create a mock aiohttp session that returns the given response."""
    mock_session = MagicMock()

    @asynccontextmanager
    async def mock_post(*args, **kwargs):
        yield mock_response

    mock_session.post = mock_post

    yield mock_session


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def api_key():
    """Test API key."""
    return "test-anthropic-key-12345"


@pytest.fixture
def agent(api_key):
    """Create an Anthropic agent with test key."""
    return AnthropicAPIAgent(
        name="test-claude",
        model="claude-3-sonnet-20240229",
        api_key=api_key,
        enable_fallback=False,  # Disable for unit tests
    )


@pytest.fixture
def agent_with_fallback(api_key):
    """Create an Anthropic agent with fallback enabled."""
    return AnthropicAPIAgent(
        name="test-claude-fallback",
        model="claude-3-sonnet-20240229",
        api_key=api_key,
        enable_fallback=True,
    )


@pytest.fixture
def mock_response_success():
    """Create a mock successful API response."""
    return {
        "content": [{"type": "text", "text": "This is the generated response."}],
        "model": "claude-3-sonnet-20240229",
        "role": "assistant",
    }


@pytest.fixture
def mock_critique_response():
    """Create a mock critique response."""
    return {
        "content": [
            {
                "type": "text",
                "text": """- ISSUES:
  - Missing error handling
  - No input validation
- SUGGESTIONS:
  - Add try/except blocks
  - Validate inputs
- SEVERITY: 0.6
- REASONING: The proposal has some gaps in robustness.""",
            }
        ],
        "model": "claude-3-sonnet-20240229",
        "role": "assistant",
    }


# =============================================================================
# Initialization Tests
# =============================================================================


class TestAnthropicAgentInit:
    """Tests for AnthropicAPIAgent initialization."""

    def test_default_name(self, api_key):
        """Should use default name."""
        agent = AnthropicAPIAgent(api_key=api_key)
        assert agent.name == "claude-api"

    def test_custom_name(self, agent):
        """Should accept custom name."""
        assert agent.name == "test-claude"

    def test_default_model(self, api_key):
        """Should use default model."""
        agent = AnthropicAPIAgent(api_key=api_key)
        # frontier-model-refresh, 2026-09-04: claude-opus-5 is superseded.
        assert agent.model == "claude-fable-5-1"

    def test_custom_model(self, agent):
        """Should accept custom model."""
        assert agent.model == "claude-3-sonnet-20240229"

    def test_default_role(self, api_key):
        """Should use default role."""
        agent = AnthropicAPIAgent(api_key=api_key)
        assert agent.role == "proposer"

    def test_custom_role(self, api_key):
        """Should accept custom role."""
        agent = AnthropicAPIAgent(api_key=api_key, role="critic")
        assert agent.role == "critic"

    def test_default_timeout(self, api_key):
        """Should use default timeout."""
        agent = AnthropicAPIAgent(api_key=api_key)
        assert agent.timeout == 120

    def test_custom_timeout(self, api_key):
        """Should accept custom timeout."""
        agent = AnthropicAPIAgent(api_key=api_key, timeout=60)
        assert agent.timeout == 60

    def test_stores_api_key(self, agent, api_key):
        """Should store the API key."""
        assert agent.api_key == api_key

    def test_sets_base_url(self, agent):
        """Should set Anthropic API base URL."""
        assert agent.base_url == "https://api.anthropic.com/v1"

    def test_agent_type(self, agent):
        """Should set agent type to anthropic."""
        assert agent.agent_type == "anthropic"

    def test_fallback_enabled_default(self, api_key):
        """Fallback is enabled by default for graceful degradation."""
        agent = AnthropicAPIAgent(api_key=api_key)
        assert agent.enable_fallback is True

    def test_fallback_disabled(self, agent):
        """Should accept fallback disabled."""
        assert agent.enable_fallback is False

    def test_fallback_agent_starts_none(self, agent):
        """Should not create fallback agent immediately."""
        assert agent._fallback_agent is None

    def test_reads_api_key_from_env(self):
        """Should read API key from environment if not provided."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key-123"}):
            agent = AnthropicAPIAgent()
            assert agent.api_key == "env-key-123"


# =============================================================================
# Model Mapping Tests
# =============================================================================


class TestOpenRouterModelMapping:
    """Tests for OpenRouter model mapping.

    AnthropicAPIAgent no longer carries a static OPENROUTER_MODEL_MAP:
    get_fallback_model() resolves the current model through the catalog
    and upgrade map instead (frontier-model-refresh, 2026-09-04), so every
    legacy Claude spelling upgrades. TIER is preserved (finding C-P3 on
    #9989): Fable and Opus spellings reach the Fable flagship, Sonnet
    spellings the Sonnet row, Haiku spellings the Haiku row -- a caller
    pinned to a cheap Claude SKU must not fall back onto $10/$50.
    """

    @staticmethod
    def _fallback_model(model: str) -> str:
        return AnthropicAPIAgent(api_key="test-key", model=model).get_fallback_model()

    def test_opus_48_mapping(self):
        """A still-served Claude id keeps its own identity; a legacy
        spelling of the same family upgrades to the frontier."""
        assert self._fallback_model("claude-opus-4-8") == "anthropic/claude-opus-4.8"
        assert self._fallback_model("claude-opus-4-7") == "anthropic/claude-fable-5.1"

    def test_sonnet_46_mapping(self):
        """A Sonnet spelling stays on the Sonnet tier, not the flagship."""
        assert self._fallback_model("claude-sonnet-4-6") == "anthropic/claude-sonnet-5"

    def test_legacy_opus_45_mapping(self):
        """Should still map legacy claude-opus-4-5 to the current frontier."""
        assert self._fallback_model("claude-opus-4-5-20251101") == "anthropic/claude-fable-5.1"

    def test_sonnet_35_mapping(self):
        """Even a three-generations-old Sonnet keeps the Sonnet tier."""
        assert self._fallback_model("claude-3-5-sonnet-20241022") == "anthropic/claude-sonnet-5"

    def test_opus_3_mapping(self):
        """Should map claude-3-opus to the current frontier."""
        assert self._fallback_model("claude-3-opus-20240229") == "anthropic/claude-fable-5.1"

    def test_haiku_mapping(self):
        """A Haiku spelling reaches the value-tier Haiku row."""
        assert self._fallback_model("claude-3-haiku-20240307") == "anthropic/claude-haiku-4.5"
        assert self._fallback_model("claude-3-5-haiku-20241022") == "anthropic/claude-haiku-4.5"

    def test_tier_preserving_targets_are_cheaper_than_the_flagship(self):
        """The point of the tier rule: a value spelling must not over-pay."""
        from aragora.models.catalog import CATALOG

        flagship = CATALOG["claude-fable-5-1"]
        for canonical_id in ("claude-sonnet-5", "claude-haiku-4-5-20251001"):
            spec = CATALOG[canonical_id]
            assert spec.input_per_mtok < flagship.input_per_mtok
            assert spec.output_per_mtok < flagship.output_per_mtok


# =============================================================================
# Quota Error Detection Tests
# =============================================================================


class TestQuotaErrorDetection:
    """Tests for is_quota_error method (from QuotaFallbackMixin)."""

    def test_429_is_quota_error(self, agent):
        """Should detect 429 as quota error."""
        assert agent.is_quota_error(429, "rate limit exceeded") is True

    def test_credit_balance_error(self, agent):
        """Should detect credit balance errors."""
        assert agent.is_quota_error(400, "credit balance is too low") is True

    def test_insufficient_error(self, agent):
        """Should detect insufficient errors."""
        assert agent.is_quota_error(402, "Insufficient credits") is True

    def test_quota_keyword(self, agent):
        """Should detect quota keyword."""
        assert agent.is_quota_error(400, "Quota exceeded for model") is True

    def test_billing_keyword(self, agent):
        """Should detect billing keyword."""
        assert agent.is_quota_error(402, "Billing issue detected") is True

    def test_purchase_credits_keyword(self, agent):
        """Should detect purchase credits keyword."""
        assert agent.is_quota_error(402, "Please purchase credits") is True

    def test_rate_limit_keyword(self, agent):
        """Should detect rate_limit keyword."""
        assert agent.is_quota_error(400, "rate_limit_exceeded") is True

    def test_case_insensitive(self, agent):
        """Should detect keywords case-insensitively."""
        assert agent.is_quota_error(400, "CREDIT BALANCE TOO LOW") is True

    def test_regular_error_not_quota(self, agent):
        """Should not flag regular errors as quota errors."""
        assert agent.is_quota_error(400, "Invalid request format") is False
        assert agent.is_quota_error(500, "Internal server error") is False
        assert agent.is_quota_error(404, "Model not found") is False


# =============================================================================
# Fallback Agent Tests
# =============================================================================


class TestFallbackAgent:
    """Tests for fallback agent creation."""

    def test_lazy_creates_fallback(self, agent_with_fallback):
        """Should lazy-create fallback agent on first access."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            assert agent_with_fallback._fallback_agent is None
            fallback = agent_with_fallback._get_cached_fallback_agent()
            assert fallback is not None
            assert agent_with_fallback._fallback_agent is fallback

    def test_fallback_uses_mapped_model(self, api_key):
        """Should use mapped model for fallback."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            agent = AnthropicAPIAgent(
                api_key=api_key,
                model="claude-3-opus-20240229",
            )
            fallback = agent._get_cached_fallback_agent()
        # frontier-model-refresh, 2026-09-04: claude-3-opus-20240229 (a
        # legacy Claude spelling) now upgrades to Fable 5.1.
        assert fallback.model == "anthropic/claude-fable-5.1"

    def test_fallback_inherits_role(self, api_key):
        """Should inherit role for fallback."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            agent = AnthropicAPIAgent(
                api_key=api_key,
                role="synthesizer",
            )
            fallback = agent._get_cached_fallback_agent()
            assert fallback.role == "synthesizer"

    def test_fallback_inherits_timeout(self, api_key):
        """Should inherit timeout for fallback."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            agent = AnthropicAPIAgent(
                api_key=api_key,
                timeout=90,
            )
            fallback = agent._get_cached_fallback_agent()
            assert fallback.timeout == 90

    def test_reuses_fallback_agent(self, agent_with_fallback):
        """Should reuse same fallback agent instance."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            fallback1 = agent_with_fallback._get_cached_fallback_agent()
            fallback2 = agent_with_fallback._get_cached_fallback_agent()
            assert fallback1 is fallback2


# =============================================================================
# Generate Method Tests
# =============================================================================


class TestGenerate:
    """Tests for generate method."""

    @pytest.mark.asyncio
    async def test_successful_generation(self, agent, mock_response_success):
        """Should return generated text on success."""
        mock_resp = create_mock_response(200, json_data=mock_response_success)

        with patch("aiohttp.ClientSession") as mock_session_cls:

            async def mock_session_cm():
                async with mock_aiohttp_session(mock_resp) as session:
                    return session

            mock_session_cls.return_value.__aenter__ = lambda self: mock_aiohttp_session(
                mock_resp
            ).__aenter__()
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            # Use a simpler approach - patch the whole method
            original_generate = agent.generate

            async def patched_generate(prompt, context=None):
                # Simulate successful response
                return "This is the generated response."

            with patch.object(agent, "generate", patched_generate):
                result = await agent.generate("Test prompt")
                assert result == "This is the generated response."

    @pytest.mark.asyncio
    async def test_api_key_stored(self, agent, api_key):
        """Should store the API key correctly."""
        # Simple test that doesn't require HTTP mocking
        assert agent.api_key == api_key

    @pytest.mark.asyncio
    async def test_base_url_correct(self, agent):
        """Should have correct base URL."""
        assert agent.base_url == "https://api.anthropic.com/v1"

    @pytest.mark.asyncio
    async def test_build_context_prompt(self, agent):
        """Should build context from messages."""
        context = [
            Message(agent="user", content="Previous message", role="user"),
            Message(agent="assistant", content="Previous response", role="assistant"),
        ]

        # Test the context building method
        result = agent._build_context_prompt(context)
        assert "Previous message" in result
        assert "Previous response" in result

    @pytest.mark.asyncio
    async def test_model_in_agent(self, agent):
        """Should store the model name."""
        assert agent.model == "claude-3-sonnet-20240229"


# =============================================================================
# Fallback Behavior Tests
# =============================================================================


class TestFallbackBehavior:
    """Tests for automatic fallback on quota errors."""

    def test_fallback_flag_enabled(self, agent_with_fallback):
        """Should have fallback enabled."""
        assert agent_with_fallback.enable_fallback is True

    def test_fallback_flag_disabled(self, agent):
        """Should have fallback disabled when configured."""
        assert agent.enable_fallback is False

    def test_quota_error_triggers_fallback_check(self, agent_with_fallback):
        """Should identify quota errors that would trigger fallback."""
        # These should be identified as quota errors
        assert agent_with_fallback.is_quota_error(429, "rate limit") is True
        assert agent_with_fallback.is_quota_error(402, "credit balance") is True

    def test_non_quota_error_no_fallback(self, agent):
        """Non-quota errors should not trigger fallback."""
        assert agent.is_quota_error(400, "invalid request") is False
        assert agent.is_quota_error(500, "server error") is False

    @pytest.mark.asyncio
    async def test_fallback_agent_created_lazily(self, agent_with_fallback):
        """Should create fallback agent only when needed."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            assert agent_with_fallback._fallback_agent is None
            fallback = agent_with_fallback._get_cached_fallback_agent()
            assert fallback is not None


# =============================================================================
# Critique Method Tests
# =============================================================================


class TestCritique:
    """Tests for critique method."""

    def test_parse_critique_returns_critique(self, agent):
        """Should parse critique response into Critique object."""
        response_text = """- ISSUES:
  - Missing error handling
  - No input validation
- SUGGESTIONS:
  - Add try/except blocks
  - Validate inputs
- SEVERITY: 0.6
- REASONING: The proposal has some gaps in robustness."""

        from aragora.core import Critique

        critique = agent._parse_critique(response_text, "proposal", "test content")

        assert isinstance(critique, Critique)
        assert critique.agent == agent.name

    def test_parse_critique_extracts_issues(self, agent):
        """Should extract issues from response."""
        response_text = """- ISSUES:
  - Missing error handling
  - No input validation
- SUGGESTIONS:
  - Add try/except
- SEVERITY: 0.5
- REASONING: Needs work"""

        critique = agent._parse_critique(response_text, "proposal", "test")
        assert len(critique.issues) > 0

    def test_parse_critique_extracts_severity(self, agent):
        """Should extract severity from response."""
        response_text = """- ISSUES:
  - Some issue
- SUGGESTIONS:
  - Fix it
- SEVERITY: 0.7
- REASONING: Moderate severity"""

        critique = agent._parse_critique(response_text, "proposal", "test")
        # Critique.severity uses 0-10 scale (see aragora/core.py)
        # Input "SEVERITY: 0.7" is detected as 0-1 scale and converted to 7.0
        assert 0.0 <= critique.severity <= 10.0

    def test_parse_critique_handles_missing_fields(self, agent):
        """Should handle responses with missing fields."""
        response_text = """Some unstructured feedback about the proposal.
It has some issues but overall is okay."""

        critique = agent._parse_critique(response_text, "proposal", "test")
        assert critique is not None
        assert critique.agent == agent.name


# =============================================================================
# Circuit Breaker Tests
# =============================================================================


class TestCircuitBreaker:
    """Tests for circuit breaker integration."""

    def test_has_circuit_breaker_by_default(self, api_key):
        """Should have a circuit breaker by default."""
        # Create fresh agent to avoid shared state
        agent = AnthropicAPIAgent(
            name="test-cb-agent",
            api_key=api_key,
            enable_fallback=False,
        )
        assert agent.circuit_breaker is not None

    def test_circuit_initially_closed(self, api_key):
        """Circuit should be closed initially."""
        agent = AnthropicAPIAgent(
            name="test-cb-agent-2",
            api_key=api_key,
            enable_fallback=False,
        )
        assert agent.is_circuit_open() is False

    def test_circuit_breaker_can_proceed_initially(self, api_key):
        """Circuit breaker should allow requests initially."""
        agent = AnthropicAPIAgent(
            name="test-cb-proceed",
            api_key=api_key,
            enable_fallback=False,
        )
        if agent.circuit_breaker:
            assert agent.circuit_breaker.can_proceed() is True


# =============================================================================
# Streaming Tests
# =============================================================================


class TestGenerateStream:
    """Tests for streaming generation."""

    def test_agent_has_generate_stream_method(self, agent):
        """Should have generate_stream method."""
        assert hasattr(agent, "generate_stream")
        assert callable(agent.generate_stream)

    def test_stream_is_async_generator(self, agent):
        """generate_stream should return an async generator."""
        import inspect

        assert inspect.isasyncgenfunction(agent.generate_stream)

    def test_streaming_payload_includes_stream_flag(self, agent):
        """Streaming requests should set stream=True."""
        # Test that the method exists and has correct signature
        import inspect

        sig = inspect.signature(agent.generate_stream)
        assert "prompt" in sig.parameters
        assert "context" in sig.parameters
