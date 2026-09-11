"""
Tests for API agent implementations.

Tests agent_type attribute and basic agent structure without making API calls.
"""

import pytest
from unittest.mock import patch, MagicMock

from aragora.core import Agent


class TestAgentTypeAttribute:
    """Tests to ensure all agents have agent_type attribute."""

    def test_base_agent_has_agent_type(self):
        """Test base Agent class has agent_type attribute initialized."""

        # Create a concrete implementation for testing
        class ConcreteAgent(Agent):
            async def generate(self, prompt, context=None):
                return "test"

            async def critique(self, proposal, task, context=None):
                pass

        agent = ConcreteAgent("test", "model", "role")
        assert hasattr(agent, "agent_type")
        assert agent.agent_type == "unknown"

    def test_api_agent_base_has_agent_type(self):
        """Test APIAgent base class sets agent_type."""
        from aragora.agents.api_agents import APIAgent

        # Create a concrete implementation
        class ConcreteAPIAgent(APIAgent):
            async def generate(self, prompt, context=None):
                return "test"

            async def critique(self, proposal, task, context=None):
                pass

        agent = ConcreteAPIAgent("test", "model")
        assert hasattr(agent, "agent_type")
        assert agent.agent_type == "api"

    def test_gemini_agent_has_correct_type(self):
        """Test GeminiAgent has correct agent_type."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent()

        assert agent.agent_type == "gemini"

    def test_anthropic_agent_has_correct_type(self):
        """Test AnthropicAPIAgent has correct agent_type."""
        from aragora.agents.api_agents import AnthropicAPIAgent

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            agent = AnthropicAPIAgent()

        assert agent.agent_type == "anthropic"

    def test_openai_agent_has_correct_type(self):
        """Test OpenAIAPIAgent has correct agent_type."""
        from aragora.agents.api_agents import OpenAIAPIAgent

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            agent = OpenAIAPIAgent()

        assert agent.agent_type == "openai"

    def test_grok_agent_has_correct_type(self):
        """Test GrokAgent has correct agent_type."""
        from aragora.agents.api_agents import GrokAgent

        with patch.dict("os.environ", {"XAI_API_KEY": "test"}):
            agent = GrokAgent()

        assert agent.agent_type == "grok"

    def test_ollama_agent_has_correct_type(self):
        """Test OllamaAgent has correct agent_type."""
        from aragora.agents.api_agents import OllamaAgent

        agent = OllamaAgent()
        assert agent.agent_type == "ollama"

    def test_openrouter_agent_has_correct_type(self):
        """Test OpenRouterAgent has correct agent_type."""
        from aragora.agents.api_agents import OpenRouterAgent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = OpenRouterAgent()

        assert agent.agent_type == "openrouter"

    def test_deepseek_agent_has_correct_type(self):
        """Test DeepSeekAgent has correct agent_type."""
        from aragora.agents.api_agents import DeepSeekAgent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = DeepSeekAgent()

        assert agent.agent_type == "deepseek"

    def test_deepseek_reasoner_agent_has_correct_type(self):
        """Test DeepSeekReasonerAgent has correct agent_type."""
        from aragora.agents.api_agents import DeepSeekReasonerAgent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = DeepSeekReasonerAgent()

        assert agent.agent_type == "deepseek-r1"

    def test_llama_agent_has_correct_type(self):
        """Test LlamaAgent has correct agent_type."""
        from aragora.agents.api_agents import LlamaAgent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = LlamaAgent()

        assert agent.agent_type == "llama"

    def test_mistral_agent_has_correct_type(self):
        """Test MistralAgent has correct agent_type."""
        from aragora.agents.api_agents import MistralAgent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = MistralAgent()

        assert agent.agent_type == "mistral"


class TestAgentInheritance:
    """Tests for agent class inheritance."""

    def test_gemini_inherits_from_api_agent(self):
        """Test GeminiAgent inherits from APIAgent."""
        from aragora.agents.api_agents import GeminiAgent, APIAgent

        assert issubclass(GeminiAgent, APIAgent)

    def test_anthropic_inherits_from_api_agent(self):
        """Test AnthropicAPIAgent inherits from APIAgent."""
        from aragora.agents.api_agents import AnthropicAPIAgent, APIAgent

        assert issubclass(AnthropicAPIAgent, APIAgent)

    def test_openrouter_inherits_from_api_agent(self):
        """Test OpenRouterAgent inherits from APIAgent."""
        from aragora.agents.api_agents import OpenRouterAgent, APIAgent

        assert issubclass(OpenRouterAgent, APIAgent)

    def test_deepseek_inherits_from_openrouter(self):
        """Test DeepSeekAgent inherits from OpenRouterAgent."""
        from aragora.agents.api_agents import DeepSeekAgent, OpenRouterAgent

        assert issubclass(DeepSeekAgent, OpenRouterAgent)


class TestAgentAttributes:
    """Tests for agent attributes."""

    def test_agent_has_name(self):
        """Test agent has name attribute."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent(name="test-agent")

        assert agent.name == "test-agent"

    def test_agent_has_model(self):
        """Test agent has model attribute."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent(model="gemini-2.0-flash")

        # "gemini-2.0-flash" has no catalog row of its own; resolve_model_id
        # upgrades it to the current Google value-tier frontier
        # (frontier-model-refresh, 2026-09-04).
        assert agent.model == "gemini-3.8-flash"

    def test_agent_has_role(self):
        """Test agent has role attribute."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent(role="critic")

        assert agent.role == "critic"

    def test_agent_has_timeout(self):
        """Test agent has timeout attribute."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent(timeout=60)

        assert agent.timeout == 60

    def test_agent_has_system_prompt(self):
        """Test agent can have system_prompt."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent()
            agent.set_system_prompt("You are a helpful assistant.")

        assert agent.system_prompt == "You are a helpful assistant."


class TestAgentRepr:
    """Tests for agent string representation."""

    def test_agent_repr(self):
        """Test agent __repr__ method."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent(name="test", role="proposer")

        repr_str = repr(agent)
        assert "GeminiAgent" in repr_str
        assert "test" in repr_str
        assert "proposer" in repr_str


class TestCreateAgentFactory:
    """Tests for create_agent factory function."""

    def test_create_gemini_agent(self):
        """Test factory creates GeminiAgent."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = create_agent("gemini", name="test-gemini")

        assert agent.name == "test-gemini"
        assert agent.agent_type == "gemini"

    def test_create_ollama_agent(self):
        """Test factory creates OllamaAgent."""
        from aragora.agents.base import create_agent

        agent = create_agent("ollama", name="test-ollama")

        assert agent.name == "test-ollama"
        assert agent.agent_type == "ollama"

    def test_create_anthropic_agent(self):
        """Test factory creates AnthropicAPIAgent."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            agent = create_agent("anthropic-api", name="test-anthropic")

        assert agent.name == "test-anthropic"
        assert agent.agent_type == "anthropic"

    def test_create_openai_agent(self):
        """Test factory creates OpenAIAPIAgent."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            agent = create_agent("openai-api", name="test-openai")

        assert agent.name == "test-openai"
        assert agent.agent_type == "openai"

    def test_create_grok_agent(self):
        """Test factory creates GrokAgent."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"XAI_API_KEY": "test"}):
            agent = create_agent("grok", name="test-grok")

        assert agent.name == "test-grok"
        assert agent.agent_type == "grok"

    def test_create_openrouter_agent(self):
        """Test factory creates OpenRouterAgent."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = create_agent("openrouter", name="test-openrouter")

        assert agent.name == "test-openrouter"
        assert agent.agent_type == "openrouter"

    def test_create_deepseek_agent(self):
        """Test factory creates DeepSeekAgent."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = create_agent("deepseek", name="test-deepseek")

        assert agent.name == "test-deepseek"
        assert agent.agent_type == "deepseek"

    def test_create_deepseek_r1_agent(self):
        """Test factory creates DeepSeekReasonerAgent."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = create_agent("deepseek-r1", name="test-reasoner")

        assert agent.name == "test-reasoner"
        assert agent.agent_type == "deepseek-r1"

    def test_create_llama_agent(self):
        """Test factory creates LlamaAgent."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = create_agent("llama", name="test-llama")

        assert agent.name == "test-llama"
        assert agent.agent_type == "llama"

    def test_create_mistral_agent(self):
        """Test factory creates MistralAgent."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            agent = create_agent("mistral", name="test-mistral")

        assert agent.name == "test-mistral"
        assert agent.agent_type == "mistral"

    def test_create_agent_with_role(self):
        """Test factory respects role parameter."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = create_agent("gemini", name="critic", role="critic")

        assert agent.role == "critic"

    def test_create_agent_with_model(self):
        """Test factory preserves requested Gemini model intent while normalizing API ID."""
        from aragora.agents.base import create_agent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = create_agent("gemini", model="gemini-2.5-pro")

        assert agent.model == "gemini-3.1-pro-preview"
        assert agent._original_model == "gemini-2.5-pro"


class TestAgentStance:
    """Tests for agent stance functionality."""

    def test_default_stance_is_neutral(self):
        """Test agent default stance is neutral."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent()

        assert agent.stance == "neutral"

    def test_stance_can_be_set(self):
        """Test agent stance can be changed."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent()
            agent.stance = "affirmative"

        assert agent.stance == "affirmative"


class TestAgentStreamingCapability:
    """Tests for streaming capability detection."""

    def test_gemini_supports_streaming(self):
        """Test GeminiAgent has streaming capability."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}):
            agent = GeminiAgent()

        # GeminiAgent should support streaming
        assert hasattr(agent, "generate")

    def test_anthropic_supports_streaming(self):
        """Test AnthropicAPIAgent has streaming capability."""
        from aragora.agents.api_agents import AnthropicAPIAgent

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            agent = AnthropicAPIAgent()

        assert hasattr(agent, "generate")


class TestOpenRouterRateLimiter:
    """Tests for OpenRouter rate limiting."""

    def test_tier_configuration(self):
        """Test tier configurations exist and have expected values."""
        from aragora.agents.api_agents import OPENROUTER_TIERS

        assert "free" in OPENROUTER_TIERS
        assert "standard" in OPENROUTER_TIERS
        assert "premium" in OPENROUTER_TIERS

        assert OPENROUTER_TIERS["free"].requests_per_minute == 20
        assert OPENROUTER_TIERS["standard"].requests_per_minute == 200

    def test_limiter_initialization(self):
        """Test rate limiter initializes with correct tier."""
        from aragora.agents.api_agents import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="free")
        assert limiter.tier.name == "free"
        assert limiter.tier.requests_per_minute == 20

    def test_limiter_defaults_to_standard(self):
        """Test rate limiter defaults to standard tier."""
        from aragora.agents.api_agents import OpenRouterRateLimiter

        with patch.dict("os.environ", {}, clear=False):
            # Remove OPENROUTER_TIER if present
            import os

            os.environ.pop("OPENROUTER_TIER", None)
            limiter = OpenRouterRateLimiter()

        assert limiter.tier.name == "standard"

    def test_limiter_respects_env_tier(self):
        """Test rate limiter respects OPENROUTER_TIER env var."""
        from aragora.agents.api_agents import OpenRouterRateLimiter

        with patch.dict("os.environ", {"OPENROUTER_TIER": "premium"}):
            limiter = OpenRouterRateLimiter()

        assert limiter.tier.name == "premium"

    def test_limiter_stats(self):
        """Test rate limiter stats property."""
        from aragora.agents.api_agents import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="basic")
        stats = limiter.stats

        assert "tier" in stats
        assert stats["tier"] == "basic"
        assert "rpm_limit" in stats
        assert stats["rpm_limit"] == 60
        assert "tokens_available" in stats
        assert "burst_size" in stats

    def test_limiter_update_from_headers(self):
        """Test rate limiter updates from API response headers."""
        from aragora.agents.api_agents import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="standard")

        headers = {
            "X-RateLimit-Limit": "200",
            "X-RateLimit-Remaining": "150",
            "X-RateLimit-Reset": "1704067200",
        }

        limiter.update_from_headers(headers)
        stats = limiter.stats

        assert stats["api_limit"] == 200
        assert stats["api_remaining"] == 150

    def test_limiter_handles_invalid_headers(self, caplog):
        """Test rate limiter logs warnings for invalid header values."""
        import logging
        from aragora.agents.api_agents import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="standard")

        # Invalid non-numeric values
        headers = {
            "X-RateLimit-Limit": "invalid",
            "X-RateLimit-Remaining": "not_a_number",
            "X-RateLimit-Reset": "bad_timestamp",
        }

        with caplog.at_level(logging.DEBUG, logger="aragora.shared.rate_limiting.token_bucket"):
            limiter.update_from_headers(headers)

        # Should log debug messages about parse failures
        assert "Failed to parse numeric value" in caplog.text

        # Stats should not be updated with invalid values
        stats = limiter.stats
        assert stats["api_limit"] is None  # Default value
        assert stats["api_remaining"] is None

    def test_limiter_partial_valid_headers(self, caplog):
        """Test rate limiter handles mix of valid and invalid headers."""
        import logging
        from aragora.agents.api_agents import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="standard")

        # Mix of valid and invalid
        headers = {
            "X-RateLimit-Limit": "100",  # Valid
            "X-RateLimit-Remaining": "invalid",  # Invalid
        }

        with caplog.at_level(logging.DEBUG, logger="aragora.shared.rate_limiting.token_bucket"):
            limiter.update_from_headers(headers)

        # Valid should be updated
        stats = limiter.stats
        assert stats["api_limit"] == 100

        # Invalid should log debug message about parse failure
        assert "Failed to parse numeric value" in caplog.text

    def test_global_limiter_singleton(self):
        """Test global rate limiter is a singleton."""
        from aragora.agents.api_agents import get_openrouter_limiter, set_openrouter_tier

        # Reset global limiter
        set_openrouter_tier("standard")

        limiter1 = get_openrouter_limiter()
        limiter2 = get_openrouter_limiter()

        assert limiter1 is limiter2

    def test_set_tier_changes_limiter(self):
        """Test set_openrouter_tier creates new limiter with correct tier."""
        from aragora.agents.api_agents import get_openrouter_limiter, set_openrouter_tier

        set_openrouter_tier("free")
        limiter = get_openrouter_limiter()

        assert limiter.tier.name == "free"

    @pytest.mark.asyncio
    async def test_limiter_acquire_succeeds(self):
        """Test rate limiter acquire succeeds with available tokens."""
        from aragora.agents.api_agents import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="standard")

        # Should succeed immediately with burst tokens available
        acquired = await limiter.acquire(timeout=1.0)
        assert acquired is True

    def test_limiter_release_on_error(self):
        """Test release_on_error returns partial token."""
        from aragora.agents.api_agents import OpenRouterRateLimiter

        limiter = OpenRouterRateLimiter(tier="standard")
        initial_tokens = limiter.stats["tokens_available"]

        limiter.release_on_error()
        final_tokens = limiter.stats["tokens_available"]

        # Should not exceed burst size
        assert final_tokens <= limiter.tier.burst_size


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
